import { useEffect, useState, useRef, useCallback } from 'react';
import {
  Play,
  Square,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Wifi,
  Server,
} from 'lucide-react';
import type { Benchmark, Target, Mission, Client, ScanStatus } from '@/types';
import * as api from '@/services/api';

function statusBadge(status: string) {
  const styles: Record<string, string> = {
    running: 'bg-blue-100 text-blue-800',
    completed: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800',
    cancelled: 'bg-yellow-100 text-yellow-800',
    pending: 'bg-gray-100 text-gray-600',
    cancelling: 'bg-yellow-100 text-yellow-800',
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status] || styles.pending}`}
    >
      {status}
    </span>
  );
}

export default function Scans() {
  // Form state
  const [clients, setClients] = useState<Client[]>([]);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);

  const [selectedClientId, setSelectedClientId] = useState<number | ''>('');
  const [selectedMissionId, setSelectedMissionId] = useState<number | ''>('');
  const [selectedTargetId, setSelectedTargetId] = useState<number | ''>('');
  const [selectedBenchmarkId, setSelectedBenchmarkId] = useState<number | ''>('');

  const [loading, setLoading] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState('');

  // Active scan tracking
  const [activeScanId, setActiveScanId] = useState<number | null>(null);
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load initial data
  useEffect(() => {
    async function load() {
      try {
        const [c, b] = await Promise.all([api.getClients(), api.getBenchmarks()]);
        setClients(c);
        setBenchmarks(b.filter((bm) => bm.is_ready));
      } catch {
        setError('Failed to load data');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // Load missions when client changes
  useEffect(() => {
    if (!selectedClientId) {
      setMissions([]);
      setSelectedMissionId('');
      return;
    }
    api.getMissions(selectedClientId as number).then(setMissions).catch(() => setMissions([]));
    setSelectedMissionId('');
    setTargets([]);
    setSelectedTargetId('');
  }, [selectedClientId]);

  // Load targets when mission changes
  useEffect(() => {
    if (!selectedMissionId) {
      setTargets([]);
      setSelectedTargetId('');
      return;
    }
    api.getTargets(selectedMissionId as number).then(setTargets).catch(() => setTargets([]));
    setSelectedTargetId('');
  }, [selectedMissionId]);

  // Polling for scan progress
  const pollStatus = useCallback(async () => {
    if (!activeScanId) return;
    try {
      const status = await api.getScanStatus(activeScanId);
      setScanStatus(status);
      if (['completed', 'failed', 'cancelled'].includes(status.status)) {
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      }
    } catch {
      // ignore polling errors
    }
  }, [activeScanId]);

  useEffect(() => {
    if (activeScanId) {
      pollRef.current = setInterval(pollStatus, 2000);
      pollStatus(); // immediate first poll
      return () => {
        if (pollRef.current) clearInterval(pollRef.current);
      };
    }
  }, [activeScanId, pollStatus]);

  // Launch scan
  async function handleLaunch() {
    if (!selectedTargetId || !selectedBenchmarkId) return;
    setLaunching(true);
    setError('');
    try {
      const result = await api.startNetworkScan({
        target_id: selectedTargetId as number,
        benchmark_id: selectedBenchmarkId as number,
      });
      setActiveScanId(result.scan_id);
      setScanStatus({
        scan_id: result.scan_id,
        status: 'running',
        progress: 0,
        total: 0,
        current_rule: '',
        passed: 0,
        failed: 0,
        errors: 0,
        compliance_percentage: 0,
      });
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to start scan');
    } finally {
      setLaunching(false);
    }
  }

  // Cancel scan
  async function handleCancel() {
    if (!activeScanId) return;
    try {
      await api.cancelScan(activeScanId);
    } catch {
      // ignore
    }
  }

  const isFinished = scanStatus && ['completed', 'failed', 'cancelled'].includes(scanStatus.status);
  const canLaunch = selectedTargetId && selectedBenchmarkId && !activeScanId;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Network Scans</h1>
          <p className="mt-1 text-sm text-gray-500">
            Launch live network scans against target systems
          </p>
        </div>
        <Wifi className="h-8 w-8 text-blue-400" />
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Scan Launcher */}
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h2 className="mb-4 text-lg font-semibold text-gray-900">Launch Scan</h2>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {/* Client */}
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Client</label>
            <select
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              value={selectedClientId}
              onChange={(e) => setSelectedClientId(e.target.value ? Number(e.target.value) : '')}
              disabled={!!activeScanId && !isFinished}
            >
              <option value="">Select client...</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          {/* Mission */}
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Mission</label>
            <select
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              value={selectedMissionId}
              onChange={(e) => setSelectedMissionId(e.target.value ? Number(e.target.value) : '')}
              disabled={!selectedClientId || (!!activeScanId && !isFinished)}
            >
              <option value="">Select mission...</option>
              {missions.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>

          {/* Target */}
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Target</label>
            <select
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              value={selectedTargetId}
              onChange={(e) => setSelectedTargetId(e.target.value ? Number(e.target.value) : '')}
              disabled={!selectedMissionId || (!!activeScanId && !isFinished)}
            >
              <option value="">Select target...</option>
              {targets.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.hostname || t.ip_address} ({t.target_type})
                </option>
              ))}
            </select>
          </div>

          {/* Benchmark */}
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Benchmark</label>
            <select
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              value={selectedBenchmarkId}
              onChange={(e) =>
                setSelectedBenchmarkId(e.target.value ? Number(e.target.value) : '')
              }
              disabled={!!activeScanId && !isFinished}
            >
              <option value="">Select benchmark...</option>
              {benchmarks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} v{b.version}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-6 flex gap-3">
          {!activeScanId || isFinished ? (
            <button
              onClick={handleLaunch}
              disabled={!canLaunch || launching}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {launching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              {launching ? 'Starting...' : 'Start Scan'}
            </button>
          ) : (
            <button
              onClick={handleCancel}
              className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
            >
              <Square className="h-4 w-4" />
              Cancel Scan
            </button>
          )}

          {isFinished && (
            <button
              onClick={() => {
                setActiveScanId(null);
                setScanStatus(null);
              }}
              className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              New Scan
            </button>
          )}
        </div>
      </div>

      {/* Scan Progress */}
      {scanStatus && (
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">
              Scan #{scanStatus.scan_id} — {statusBadge(scanStatus.status)}
            </h2>
            {scanStatus.current_rule && (
              <span className="text-sm text-gray-500">
                Current rule: <span className="font-mono">{scanStatus.current_rule}</span>
              </span>
            )}
          </div>

          {/* Progress bar */}
          {scanStatus.total > 0 && (
            <div className="mb-6">
              <div className="mb-1 flex justify-between text-sm text-gray-600">
                <span>
                  {scanStatus.progress} / {scanStatus.total} rules
                </span>
                <span>{Math.round((scanStatus.progress / scanStatus.total) * 100)}%</span>
              </div>
              <div className="h-3 w-full overflow-hidden rounded-full bg-gray-200">
                <div
                  className={`h-full rounded-full transition-all duration-300 ${
                    scanStatus.status === 'failed'
                      ? 'bg-red-500'
                      : scanStatus.status === 'completed'
                        ? 'bg-green-500'
                        : 'bg-blue-500'
                  }`}
                  style={{
                    width: `${Math.round((scanStatus.progress / scanStatus.total) * 100)}%`,
                  }}
                />
              </div>
            </div>
          )}

          {/* Stats cards */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="rounded-lg border border-green-200 bg-green-50 p-4 text-center">
              <CheckCircle2 className="mx-auto mb-1 h-6 w-6 text-green-600" />
              <div className="text-2xl font-bold text-green-700">{scanStatus.passed}</div>
              <div className="text-xs text-green-600">Passed</div>
            </div>
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-center">
              <XCircle className="mx-auto mb-1 h-6 w-6 text-red-600" />
              <div className="text-2xl font-bold text-red-700">{scanStatus.failed}</div>
              <div className="text-xs text-red-600">Failed</div>
            </div>
            <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 text-center">
              <AlertTriangle className="mx-auto mb-1 h-6 w-6 text-yellow-600" />
              <div className="text-2xl font-bold text-yellow-700">{scanStatus.errors}</div>
              <div className="text-xs text-yellow-600">Errors</div>
            </div>
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-center">
              <Server className="mx-auto mb-1 h-6 w-6 text-blue-600" />
              <div className="text-2xl font-bold text-blue-700">
                {scanStatus.compliance_percentage}%
              </div>
              <div className="text-xs text-blue-600">Compliance</div>
            </div>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!scanStatus && (
        <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-12 text-center">
          <Wifi className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-4 text-lg font-medium text-gray-900">No active scan</h3>
          <p className="mt-2 text-sm text-gray-500">
            Select a target and benchmark above, then click "Start Scan" to begin a network audit.
          </p>
        </div>
      )}
    </div>
  );
}
