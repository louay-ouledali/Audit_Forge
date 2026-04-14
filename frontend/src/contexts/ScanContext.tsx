/**
 * ScanContext — persists scan state across tab switches in MissionWorkspace.
 *
 * Lives at the MissionWorkspace level so that TargetsTab can unmount/remount
 * without losing active scan progress, polling intervals, or batch state.
 *
 * On mount, recovers any active scans from the backend so refreshing the
 * page or navigating away and back still shows in-flight scans.
 */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
  type ReactNode,
} from 'react';
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

interface ScanContextValue {
  /* state */
  scanningTargetIds: Set<number>;
  scanProgressMap: Map<number, number>;
  activeScans: ActiveScan[];
  activeBatchId: number | null;
  batchStatus: ScanBatchStatus | null;
  showScanAllDialog: boolean;
  error: string;

  /* actions */
  launchSingleScan: (target: Target) => Promise<void>;
  launchBatchScan: (targetIds: number[], concurrency?: number) => Promise<void>;
  cancelSingleScan: (scanId: number) => Promise<void>;
  cancelAllScans: () => Promise<void>;
  dismissCompleted: () => void;
  setShowScanAllDialog: (v: boolean) => void;
  setError: (v: string) => void;
}

const POLL_INTERVAL = 2000;
const ScanCtx = createContext<ScanContextValue | null>(null);

export function useScanContext(): ScanContextValue {
  const ctx = useContext(ScanCtx);
  if (!ctx) throw new Error('useScanContext must be used inside <ScanProvider>');
  return ctx;
}

/* ── Provider ─────────────────────────────────────────────── */

interface ProviderProps {
  missionId: number;
  targets: Target[];
  onRefresh: () => Promise<void>;
  children: ReactNode;
}

export function ScanProvider({ missionId, targets, onRefresh, children }: ProviderProps) {
  const [scanningTargetIds, setScanningTargetIds] = useState<Set<number>>(new Set());
  const [scanProgressMap, setScanProgressMap] = useState<Map<number, number>>(new Map());
  const [activeScans, setActiveScans] = useState<ActiveScan[]>([]);
  const [activeBatchId, setActiveBatchId] = useState<number | null>(null);
  const [batchStatus, setBatchStatus] = useState<ScanBatchStatus | null>(null);
  const [showScanAllDialog, setShowScanAllDialog] = useState(false);
  const [error, setError] = useState('');

  const scanTargetMap = useRef<Map<number, number>>(new Map());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const batchPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeScansRef = useRef(activeScans);
  const recoveredRef = useRef(false);

  // Keep ref in sync
  useEffect(() => { activeScansRef.current = activeScans; }, [activeScans]);

  /* ── Recovery: re-discover active scans on mount ────────── */
  useEffect(() => {
    if (recoveredRef.current) return;
    recoveredRef.current = true;

    (async () => {
      try {
        const [running, pending] = await Promise.all([
          api.getScans({ mission_id: missionId, status: 'running' }),
          api.getScans({ mission_id: missionId, status: 'pending' }),
        ]);

        const activeFromBackend = [...running.data, ...pending.data];
        if (activeFromBackend.length === 0) return;

        const recovered: ActiveScan[] = [];
        const scanning = new Set<number>();

        for (const scan of activeFromBackend) {
          const tid = scan.target_id;
          scanning.add(tid);
          scanTargetMap.current.set(scan.id, tid);

          recovered.push({
            scanId: scan.id,
            targetId: tid,
            targetName: scan.target_hostname || scan.target_ip || `#${tid}`,
            targetType: scan.target_type || 'linux',
            benchmarkName: scan.benchmark_name || 'Unknown',
            status: scan.status,
            progress: 0,
            total: 0,
            passed: 0,
            failed: 0,
            errors: 0,
            compliance: 0,
            currentRule: '',
            startedAt: Date.now(),
          });
        }

        setActiveScans(prev => {
          // Don't duplicate if somehow already present
          const existingIds = new Set(prev.map(s => s.scanId));
          const fresh = recovered.filter(s => !existingIds.has(s.scanId));
          return fresh.length > 0 ? [...prev, ...fresh] : prev;
        });

        setScanningTargetIds(prev => {
          const next = new Set(prev);
          scanning.forEach(id => next.add(id));
          return next;
        });

        // Start polling for the recovered scans
        startPolling();
      } catch {
        // Recovery is best-effort
      }
    })();
    // Reset guard when mission changes so new missions get recovery
    return () => { recoveredRef.current = false; };
  }, [missionId]);

  /* ── Visibility-aware polling helper ────────────────────── */
  const isVisibleRef = useRef(true);

  useEffect(() => {
    const handler = () => { isVisibleRef.current = document.visibilityState === 'visible'; };
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
  }, []);

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

      setScanningTargetIds(prev => new Set(prev).add(target.id));
      setScanProgressMap(prev => new Map(prev).set(target.id, 0));

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
      // Skip polling when tab is hidden to save resources
      if (!isVisibleRef.current) return;

      const currentScans = [...activeScansRef.current];
      const running = currentScans.filter(s => s.status === 'running' || s.status === 'pending');

      if (running.length === 0) {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        return;
      }

      const updates: ActiveScan[] = [...currentScans];
      let anyChanged = false;

      for (const scan of running) {
        if (scan.scanId === 0) continue;
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

            const pct = Math.round((status.progress / total) * 100);
            setScanProgressMap(prev => new Map(prev).set(scan.targetId, pct));

            if (['completed', 'failed', 'cancelled'].includes(status.status)) {
              setScanningTargetIds(prev => {
                const next = new Set(prev);
                next.delete(scan.targetId);
                return next;
              });
            }
          }
        } catch { /* skip cycle */ }
      }

      if (anyChanged) setActiveScans(updates);

      const stillRunning = updates.filter(s => s.status === 'running' || s.status === 'pending');
      if (stillRunning.length === 0 && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
        onRefresh();
      }
    }, POLL_INTERVAL);
  }, [onRefresh]);

  /* ── Polling: batch status ──────────────────────────────── */
  const startBatchPolling = useCallback((batchId: number) => {
    if (batchPollRef.current) clearInterval(batchPollRef.current);

    batchPollRef.current = setInterval(async () => {
      if (!isVisibleRef.current) return;

      try {
        const status = await api.getScanBatchStatus(batchId);
        setBatchStatus(status);

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

        for (const item of status.items) {
          if (['completed', 'failed', 'skipped'].includes(item.status)) {
            setScanningTargetIds(prev => {
              const next = new Set(prev);
              next.delete(item.target_id);
              return next;
            });
          }
        }

        if (['completed', 'failed', 'cancelled'].includes(status.status)) {
          if (batchPollRef.current) {
            clearInterval(batchPollRef.current);
            batchPollRef.current = null;
          }
          setActiveBatchId(null);
          onRefresh();
        }
      } catch { /* skip */ }
    }, POLL_INTERVAL);
  }, [onRefresh]);

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
      for (const scan of activeScans.filter(s => s.status === 'running')) {
        try { await api.cancelScan(scan.scanId); } catch { /* skip */ }
      }
      setScanningTargetIds(new Set());
      setActiveScans(prev => prev.map(s =>
        s.status === 'running' ? { ...s, status: 'cancelled' } : s,
      ));
    }
  }, [activeBatchId, activeScans, onRefresh]);

  const dismissCompleted = useCallback(() => {
    setActiveScans(prev => prev.filter(s => s.status === 'running' || s.status === 'pending'));
  }, []);

  /* ── Cleanup on provider unmount ────────────────────────── */
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (batchPollRef.current) clearInterval(batchPollRef.current);
    };
  }, []);

  const value: ScanContextValue = {
    scanningTargetIds,
    scanProgressMap,
    activeScans,
    activeBatchId,
    batchStatus,
    showScanAllDialog,
    error,
    launchSingleScan,
    launchBatchScan,
    cancelSingleScan,
    cancelAllScans,
    dismissCompleted,
    setShowScanAllDialog,
    setError,
  };

  return <ScanCtx.Provider value={value}>{children}</ScanCtx.Provider>;
}
