import { useState, useCallback, useRef, useEffect } from 'react';
import type {
  Target,
  ScanStatus,
  ScanBatchResponse,
  ScanBatchStatus,
  ScanBatchItemResponse,
} from '@/types';
import * as api from '@/services/api';

/* ── Types ────────────────────────────────────────────────── */
export interface ActiveScan {
  scanId: number;
  targetId: number;
  targetName: string;
  targetType: string;
  benchmarkName: string;
  status: string;
  progress: number;
  total: number;
  passed: number;
  failed: number;
  errors: number;
  compliance: number;
  currentRule: string;
  startedAt: number; // epoch ms
  errorMessage?: string;
}

export interface ScanManagerState {
  /* Per-target scans */
  scanningTargetIds: Set<number>;
  scanProgressMap: Map<number, number>;      // targetId → progress %
  activeScans: ActiveScan[];

  /* Batch state */
  activeBatchId: number | null;
  batchStatus: ScanBatchStatus | null;

  /* Scan All dialog */
  showScanAllDialog: boolean;
}

const POLL_INTERVAL = 2000;

export function useScanManager(
  missionId: number,
  targets: Target[],
  onRefresh: () => Promise<void>,
) {
  const [scanningTargetIds, setScanningTargetIds] = useState<Set<number>>(new Set());
  const [scanProgressMap, setScanProgressMap] = useState<Map<number, number>>(new Map());
  const [activeScans, setActiveScans] = useState<ActiveScan[]>([]);
  const [activeBatchId, setActiveBatchId] = useState<number | null>(null);
  const [batchStatus, setBatchStatus] = useState<ScanBatchStatus | null>(null);
  const [showScanAllDialog, setShowScanAllDialog] = useState(false);
  const [error, setError] = useState('');

  // Map scanId → targetId for single-target scans
  const scanTargetMap = useRef<Map<number, number>>(new Map());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const batchPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ── Single target scan ─────────────────────────────────── */
  const launchSingleScan = useCallback(async (target: Target) => {
    if (!target.default_benchmark_id) {
      setError(`Target "${target.hostname || target.ip_address}" has no benchmark assigned.`);
      return;
    }
    if (!target.ssh_username && !target.has_enable_password) {
      setError(`Target "${target.hostname || target.ip_address}" has no credentials configured.`);
      return;
    }

    try {
      const resp = await api.startNetworkScan({
        target_id: target.id,
        benchmark_id: target.default_benchmark_id,
        mission_id: missionId,
      });

      const scanId = resp.scan_id;
      scanTargetMap.current.set(scanId, target.id);

      // Add to scanning set
      setScanningTargetIds(prev => new Set(prev).add(target.id));
      setScanProgressMap(prev => new Map(prev).set(target.id, 0));

      // Add to active scans list
      setActiveScans(prev => [
        ...prev,
        {
          scanId,
          targetId: target.id,
          targetName: target.hostname || target.ip_address || `#${target.id}`,
          targetType: target.target_type,
          benchmarkName: target.default_benchmark_name || 'Unknown',
          status: 'running',
          progress: 0,
          total: 0,
          passed: 0,
          failed: 0,
          errors: 0,
          compliance: 0,
          currentRule: '',
          startedAt: Date.now(),
        },
      ]);

      startPolling();
    } catch {
      setError(`Failed to start scan for "${target.hostname || target.ip_address}".`);
    }
  }, [missionId]);

  /* ── Batch scan ("Scan All") ────────────────────────────── */
  const launchBatchScan = useCallback(async (
    targetIds: number[],
    concurrency: number = 3,
  ) => {
    try {
      const resp: ScanBatchResponse = await api.startScanBatch({
        mission_id: missionId,
        target_ids: targetIds,
        skip_untestable: true,
        concurrency,
      });

      setActiveBatchId(resp.batch_id);

      // Mark scannable targets as scanning
      const scannableIds = new Set(
        resp.items
          .filter((it: ScanBatchItemResponse) => it.status !== 'skipped')
          .map((it: ScanBatchItemResponse) => it.target_id),
      );

      setScanningTargetIds(prev => {
        const next = new Set(prev);
        scannableIds.forEach(id => next.add(id));
        return next;
      });

      // Build active scans from batch items
      const newScans: ActiveScan[] = resp.items
        .filter((it: ScanBatchItemResponse) => it.status !== 'skipped')
        .map((it: ScanBatchItemResponse) => {
          const t = targets.find(t => t.id === it.target_id);
          return {
            scanId: it.scan_id ?? 0,
            targetId: it.target_id,
            targetName: it.target_hostname || it.target_ip || `#${it.target_id}`,
            targetType: t?.target_type || 'linux',
            benchmarkName: it.benchmark_name || 'Unknown',
            status: it.status,
            progress: 0,
            total: 0,
            passed: 0,
            failed: 0,
            errors: 0,
            compliance: 0,
            currentRule: '',
            startedAt: Date.now(),
          };
        });

      setActiveScans(prev => [...prev, ...newScans]);
      startBatchPolling(resp.batch_id);
      setShowScanAllDialog(false);
    } catch {
      setError('Failed to launch batch scan.');
    }
  }, [missionId, targets]);

  /* ── Polling: individual scans ──────────────────────────── */
  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      setActiveScans(prev => {
        const running = prev.filter(s => s.status === 'running' || s.status === 'pending');
        if (running.length === 0) {
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
          return prev;
        }
        // Don't await inside setState — trigger polls outside
        return prev;
      });

      // Do the actual polling
      const currentScans = [...activeScansRef.current];
      const running = currentScans.filter(s => s.status === 'running' || s.status === 'pending');

      const updates: ActiveScan[] = [...currentScans];
      let anyChanged = false;

      for (const scan of running) {
        if (scan.scanId === 0) continue; // batch items without scan_id yet
        try {
          const status: ScanStatus = await api.getScanStatus(scan.scanId);
          const idx = updates.findIndex(s => s.scanId === scan.scanId);
          if (idx >= 0) {
            const total = status.total || 1;
            updates[idx] = {
              ...updates[idx],
              status: status.status,
              progress: status.progress,
              total: status.total,
              passed: status.passed,
              failed: status.failed,
              errors: status.errors,
              compliance: status.compliance_percentage,
              currentRule: status.current_rule,
              errorMessage: status.error_message,
            };
            anyChanged = true;

            // Update progress map
            const pct = Math.round((status.progress / total) * 100);
            setScanProgressMap(prev => new Map(prev).set(scan.targetId, pct));

            // If completed/failed, remove from scanning set
            if (['completed', 'failed', 'cancelled'].includes(status.status)) {
              setScanningTargetIds(prev => {
                const next = new Set(prev);
                next.delete(scan.targetId);
                return next;
              });
            }
          }
        } catch {
          // Poll failure — skip this cycle
        }
      }

      if (anyChanged) {
        setActiveScans(updates);
      }

      // Check if all done
      const stillRunning = updates.filter(s => s.status === 'running' || s.status === 'pending');
      if (stillRunning.length === 0 && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
        // Refresh data
        onRefresh();
      }
    }, POLL_INTERVAL);
  }, [onRefresh]);

  /* ── Polling: batch status ──────────────────────────────── */
  const startBatchPolling = useCallback((batchId: number) => {
    if (batchPollRef.current) clearInterval(batchPollRef.current);

    batchPollRef.current = setInterval(async () => {
      try {
        const status = await api.getScanBatchStatus(batchId);
        setBatchStatus(status);

        // Update active scans from batch items
        setActiveScans(prev => {
          const updated = [...prev];
          for (const item of status.items) {
            const idx = updated.findIndex(s => s.targetId === item.target_id);
            if (idx >= 0) {
              updated[idx] = {
                ...updated[idx],
                scanId: item.scan_id ?? updated[idx].scanId,
                status: item.status,
                errorMessage: item.error_message ?? undefined,
              };
            }
          }
          return updated;
        });

        // Poll individual scan progress for running items
        for (const item of status.items) {
          if (item.scan_id && (item.status === 'running' || item.status === 'scanning')) {
            try {
              const scanStatus = await api.getScanStatus(item.scan_id);
              const total = scanStatus.total || 1;
              const pct = Math.round((scanStatus.progress / total) * 100);
              setScanProgressMap(prev => new Map(prev).set(item.target_id, pct));

              setActiveScans(prev => prev.map(s =>
                s.targetId === item.target_id ? {
                  ...s,
                  progress: scanStatus.progress,
                  total: scanStatus.total,
                  passed: scanStatus.passed,
                  failed: scanStatus.failed,
                  errors: scanStatus.errors,
                  compliance: scanStatus.compliance_percentage,
                  currentRule: scanStatus.current_rule,
                  status: scanStatus.status,
                } : s,
              ));
            } catch { /* skip */ }
          }
        }

        // Remove completed targets from scanning set
        for (const item of status.items) {
          if (['completed', 'failed', 'skipped'].includes(item.status)) {
            setScanningTargetIds(prev => {
              const next = new Set(prev);
              next.delete(item.target_id);
              return next;
            });
          }
        }

        // If batch done, stop polling
        if (['completed', 'failed', 'cancelled'].includes(status.status)) {
          if (batchPollRef.current) {
            clearInterval(batchPollRef.current);
            batchPollRef.current = null;
          }
          setActiveBatchId(null);
          onRefresh();
        }
      } catch {
        // Poll failure — skip
      }
    }, POLL_INTERVAL);
  }, [onRefresh]);

  // Keep ref in sync for closures
  const activeScansRef = useRef(activeScans);
  useEffect(() => { activeScansRef.current = activeScans; }, [activeScans]);

  /* ── Cancel ─────────────────────────────────────────────── */
  const cancelSingleScan = useCallback(async (scanId: number) => {
    try {
      await api.cancelScan(scanId);
      setActiveScans(prev => prev.map(s =>
        s.scanId === scanId ? { ...s, status: 'cancelled' } : s,
      ));
      const targetId = scanTargetMap.current.get(scanId);
      if (targetId) {
        setScanningTargetIds(prev => { const n = new Set(prev); n.delete(targetId); return n; });
      }
    } catch {
      setError('Failed to cancel scan.');
    }
  }, []);

  const cancelAllScans = useCallback(async () => {
    if (activeBatchId) {
      try {
        await api.cancelScanBatch(activeBatchId);
        if (batchPollRef.current) { clearInterval(batchPollRef.current); batchPollRef.current = null; }
        setActiveBatchId(null);
        setScanningTargetIds(new Set());
        setActiveScans(prev => prev.map(s =>
          ['running', 'pending'].includes(s.status) ? { ...s, status: 'cancelled' } : s,
        ));
        onRefresh();
      } catch {
        setError('Failed to cancel batch.');
      }
    } else {
      // Cancel individual scans
      for (const scan of activeScans.filter(s => s.status === 'running')) {
        try { await api.cancelScan(scan.scanId); } catch { /* skip */ }
      }
      setScanningTargetIds(new Set());
      setActiveScans(prev => prev.map(s =>
        s.status === 'running' ? { ...s, status: 'cancelled' } : s,
      ));
    }
  }, [activeBatchId, activeScans, onRefresh]);

  /* ── Dismiss completed scans from the panel ─────────────── */
  const dismissCompleted = useCallback(() => {
    setActiveScans(prev => prev.filter(s => s.status === 'running' || s.status === 'pending'));
  }, []);

  /* ── Cleanup on unmount ─────────────────────────────────── */
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (batchPollRef.current) clearInterval(batchPollRef.current);
    };
  }, []);

  return {
    // State
    scanningTargetIds,
    scanProgressMap,
    activeScans,
    activeBatchId,
    batchStatus,
    showScanAllDialog,
    error,

    // Actions
    launchSingleScan,
    launchBatchScan,
    cancelSingleScan,
    cancelAllScans,
    dismissCompleted,
    setShowScanAllDialog,
    setError,
  };
}
