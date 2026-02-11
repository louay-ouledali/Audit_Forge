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
  Upload,
  Download,
  Usb,
  Plus,
} from 'lucide-react';
import type { Benchmark, Target, Mission, Client, ScanStatus, ImportResultsResponse, ScriptPreviewResponse } from '@/types';
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

type ScanMode = 'network' | 'script_export';

export default function Scans() {
  // Mode tab state
  const [scanMode, setScanMode] = useState<ScanMode>('network');

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

  // Import state
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<ImportResultsResponse | null>(null);

  // Script export state
  const [exporting, setExporting] = useState(false);
  const [scriptPreview, setScriptPreview] = useState<ScriptPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Inline mission creation state
  const [showMissionForm, setShowMissionForm] = useState(false);
  const [missionName, setMissionName] = useState('');
  const [missionDescription, setMissionDescription] = useState('');
  const [creatingMission, setCreatingMission] = useState(false);

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

  async function handleImport() {
    if (!selectedTargetId || !selectedBenchmarkId || !importFile) return;
    setImporting(true);
    setError('');
    try {
      const result = await api.importWithNewScan(
        selectedTargetId as number,
        selectedBenchmarkId as number,
        importFile,
      );
      setImportResult(result);
    } catch (err: unknown) {
      const message = err instanceof Error && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : undefined;
      setError(message || 'Failed to import results');
    } finally {
      setImporting(false);
    }
  }

  // Script export handlers
  async function handlePreviewScript() {
    if (!selectedBenchmarkId) return;
    setPreviewLoading(true);
    setError('');
    try {
      const preview = await api.previewScript({ benchmark_id: selectedBenchmarkId as number });
      setScriptPreview(preview);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to preview script');
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleExportScript() {
    if (!selectedBenchmarkId) return;
    setExporting(true);
    setError('');
    try {
      const blob = await api.generateScript({ benchmark_id: selectedBenchmarkId as number });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `audit_scripts_benchmark_${selectedBenchmarkId}.zip`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to generate script package');
    } finally {
      setExporting(false);
    }
  }

  // Inline mission creation
  async function handleCreateMission(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedClientId || !missionName.trim()) return;
    setCreatingMission(true);
    setError('');
    try {
      const created = await api.createMission({
        client_id: selectedClientId as number,
        name: missionName.trim(),
        description: missionDescription.trim() || undefined,
      });
      // Refresh missions and select the new one
      const updatedMissions = await api.getMissions(selectedClientId as number);
      setMissions(updatedMissions);
      setSelectedMissionId(created.id);
      setShowMissionForm(false);
      setMissionName('');
      setMissionDescription('');
    } catch {
      setError('Failed to create mission');
    } finally {
      setCreatingMission(false);
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
          <h1 className="text-2xl font-bold text-gray-900">Scans</h1>
          <p className="mt-1 text-sm text-gray-500">
            Launch network scans or export scripts for USB/offline execution
          </p>
        </div>
      </div>

      {/* Mode Tabs */}
      <div className="flex gap-1 rounded-lg border border-gray-200 bg-gray-100 p-1">
        <button
          onClick={() => setScanMode('network')}
          className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
            scanMode === 'network'
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-600 hover:text-gray-900'
          }`}
        >
          <Wifi className="h-4 w-4" />
          Network Scan
        </button>
        <button
          onClick={() => setScanMode('script_export')}
          className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
            scanMode === 'script_export'
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-600 hover:text-gray-900'
          }`}
        >
          <Usb className="h-4 w-4" />
          Script Export (USB)
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════
          NETWORK SCAN MODE
          ═══════════════════════════════════════════════════════════ */}
      {scanMode === 'network' && (
        <>
          {/* Scan Launcher */}
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <h2 className="mb-4 text-lg font-semibold text-gray-900">Launch Network Scan</h2>

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
                {/* Inline create mission */}
                {selectedClientId && missions.length === 0 && !showMissionForm && (
                  <button
                    type="button"
                    onClick={() => setShowMissionForm(true)}
                    className="mt-1 inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800"
                  >
                    <Plus className="h-3 w-3" /> Create a mission
                  </button>
                )}
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

            {/* Inline Mission Creation Form */}
            {showMissionForm && (
              <form onSubmit={handleCreateMission} className="mt-4 rounded-lg border border-blue-200 bg-blue-50 p-4 space-y-3">
                <h4 className="text-sm font-semibold text-gray-900">Quick Create Mission</h4>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-700">Mission Name *</label>
                    <input
                      value={missionName}
                      onChange={(e) => setMissionName(e.target.value)}
                      required
                      placeholder="e.g. Q1 2026 Audit"
                      className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-700">Description</label>
                    <input
                      value={missionDescription}
                      onChange={(e) => setMissionDescription(e.target.value)}
                      placeholder="Optional description"
                      className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                    />
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={creatingMission || !missionName.trim()}
                    className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {creatingMission ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                    Create
                  </button>
                  <button
                    type="button"
                    onClick={() => { setShowMissionForm(false); setMissionName(''); setMissionDescription(''); }}
                    className="rounded-lg bg-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-300"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}

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
                Select a target and benchmark above, then click &quot;Start Scan&quot; to begin a network audit.
              </p>
            </div>
          )}

          {/* Result Import Section */}
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <h2 className="mb-4 text-lg font-semibold text-gray-900">Import Results</h2>
            <p className="mb-4 text-sm text-gray-500">
              Import scan results from offline/USB execution (audit_results.json or marker-based output)
            </p>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  Results File (JSON, TXT, or ZIP)
                </label>
                <input
                  type="file"
                  accept=".json,.txt,.zip"
                  onChange={(e) => setImportFile(e.target.files?.[0] || null)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm file:mr-4 file:rounded-lg file:border-0 file:bg-blue-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-blue-700 hover:file:bg-blue-100"
                />
              </div>
              <button
                onClick={handleImport}
                disabled={!selectedTargetId || !selectedBenchmarkId || !importFile || importing}
                className="inline-flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                {importing ? 'Importing...' : 'Import Results'}
              </button>
              {importResult && (
                <div className="rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-700">
                  <p className="font-medium">Import successful!</p>
                  <p>Findings created: {importResult.findings_created} | Passed: {importResult.passed} | Failed: {importResult.failed} | Errors: {importResult.errors}</p>
                  <p>Compliance: {importResult.compliance_percentage}%</p>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* ═══════════════════════════════════════════════════════════
          SCRIPT EXPORT (USB) MODE
          ═══════════════════════════════════════════════════════════ */}
      {scanMode === 'script_export' && (
        <>
          <div className="rounded-lg border border-gray-200 bg-white p-6">
            <div className="mb-4 flex items-center gap-3">
              <Usb className="h-6 w-6 text-purple-600" />
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Export Audit Scripts</h2>
                <p className="text-sm text-gray-500">
                  Generate a ZIP package of audit scripts for offline/USB execution on air-gapped systems
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {/* Benchmark */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Benchmark *</label>
                <select
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  value={selectedBenchmarkId}
                  onChange={(e) => {
                    setSelectedBenchmarkId(e.target.value ? Number(e.target.value) : '');
                    setScriptPreview(null);
                  }}
                >
                  <option value="">Select benchmark...</option>
                  {benchmarks.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name} v{b.version} ({b.platform})
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="mt-6 flex flex-wrap gap-3">
              <button
                onClick={handlePreviewScript}
                disabled={!selectedBenchmarkId || previewLoading}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {previewLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Server className="h-4 w-4" />}
                Preview Rules
              </button>
              <button
                onClick={handleExportScript}
                disabled={!selectedBenchmarkId || exporting}
                className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                {exporting ? 'Generating...' : 'Download Script Package'}
              </button>
            </div>
          </div>

          {/* Script Preview */}
          {scriptPreview && (
            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h3 className="mb-4 text-lg font-semibold text-gray-900">
                Script Preview — {scriptPreview.total_rules} rules
              </h3>
              {scriptPreview.rules.length === 0 ? (
                <p className="text-sm text-gray-500">No rules found for the selected criteria.</p>
              ) : (
                <div className="max-h-96 overflow-y-auto">
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Section</th>
                        <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Title</th>
                        <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">Severity</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200">
                      {scriptPreview.rules.map((rule) => (
                        <tr key={rule.id}>
                          <td className="whitespace-nowrap px-4 py-2 text-sm font-mono text-gray-900">{rule.section_number}</td>
                          <td className="px-4 py-2 text-sm text-gray-700">{rule.title ?? '—'}</td>
                          <td className="whitespace-nowrap px-4 py-2">
                            <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                              rule.severity === 'high' ? 'bg-red-100 text-red-800' :
                              rule.severity === 'medium' ? 'bg-yellow-100 text-yellow-800' :
                              'bg-green-100 text-green-800'
                            }`}>
                              {rule.severity ?? 'unknown'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Instructions */}
          {!scriptPreview && (
            <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-12 text-center">
              <Usb className="mx-auto h-12 w-12 text-gray-400" />
              <h3 className="mt-4 text-lg font-medium text-gray-900">Script Export Workflow</h3>
              <div className="mx-auto mt-4 max-w-lg text-left text-sm text-gray-500 space-y-2">
                <p><strong>1.</strong> Select a benchmark and click &quot;Download Script Package&quot;</p>
                <p><strong>2.</strong> Copy the ZIP to a USB drive and transfer to the target system</p>
                <p><strong>3.</strong> Extract and run the audit script on the target</p>
                <p><strong>4.</strong> Copy the results file back and import via the &quot;Network Scan&quot; tab → Import Results</p>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
