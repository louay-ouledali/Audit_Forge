import { useEffect, useState, useRef, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
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
  Trash2,
} from 'lucide-react';
import type { Benchmark, Target, Mission, Client, ScanStatus, ImportResultsResponse, ScriptPreviewResponse, DiscoveredHost } from '@/types';
import * as api from '@/services/api';

function statusBadge(status: string) {
  const styles: Record<string, string> = {
    running: 'bg-sky-500/10 text-sky-400',
    completed: 'bg-emerald-500/10 text-emerald-400',
    failed: 'bg-red-500/10 text-red-400',
    cancelled: 'bg-amber-500/10 text-amber-400',
    pending: 'bg-dark-overlay text-dark-secondary',
    cancelling: 'bg-amber-500/10 text-amber-400',
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

  // Inline target creation state
  const [showTargetForm, setShowTargetForm] = useState(false);
  const [targetHostname, setTargetHostname] = useState('');
  const [targetIp, setTargetIp] = useState('');
  const [targetType, setTargetType] = useState('windows');
  const [targetConnectionMethod, setTargetConnectionMethod] = useState('ssh');
  const [targetSshUsername, setTargetSshUsername] = useState('');
  const [targetSshPassword, setTargetSshPassword] = useState('');
  const [targetPort, setTargetPort] = useState('');
  const [targetNotes, setTargetNotes] = useState('');
  const [creatingTarget, setCreatingTarget] = useState(false);

  // Credential edit state for existing targets
  const [showCredentialEdit, setShowCredentialEdit] = useState(false);
  const [editCredUsername, setEditCredUsername] = useState('');
  const [editCredPassword, setEditCredPassword] = useState('');
  const [savingCredentials, setSavingCredentials] = useState(false);

  // Network discovery state
  const [discoverySubnet, setDiscoverySubnet] = useState('');
  const [discovering, setDiscovering] = useState(false);
  const [discoveredHosts, setDiscoveredHosts] = useState<DiscoveredHost[]>([]);
  const [discoveryError, setDiscoveryError] = useState('');
  const [discoveryDone, setDiscoveryDone] = useState(false);
  const location = useLocation();

  // Load initial data (refetch when page becomes visible via KeepAlive)
  useEffect(() => {
    if (location.pathname !== '/scans') return;
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
  }, [location.pathname]);

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

  /** Build a smart filename matching the backend convention:
   *  auditforge_audit_{BenchmarkName}_{Version}_{YYYYMMDD}.zip */
  function buildExportFilename(): string {
    const bm = benchmarks.find((b) => b.id === selectedBenchmarkId);
    if (!bm) return `audit_scripts_benchmark_${selectedBenchmarkId}.zip`;
    const safeName = bm.name.replace(/[\s/\\]+/g, '_');
    const safeVersion = (bm.version || 'unknown').replace(/[\s/\\]+/g, '_');
    const dateStamp = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    return `auditforge_audit_${safeName}_${safeVersion}_${dateStamp}.zip`;
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
      a.download = buildExportFilename();
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

  // Inline target creation
  async function handleCreateTarget(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedClientId || !selectedMissionId || (!targetHostname.trim() && !targetIp.trim())) return;
    setCreatingTarget(true);
    setError('');
    try {
      const created = await api.createTarget({
        client_id: selectedClientId as number,
        hostname: targetHostname.trim() || undefined,
        ip_address: targetIp.trim() || undefined,
        target_type: targetType,
        connection_method: targetConnectionMethod || undefined,
        ssh_username: targetSshUsername.trim() || undefined,
        ssh_password: targetSshPassword || undefined,
        port: targetPort ? Number(targetPort) : undefined,
        notes: targetNotes.trim() || undefined,
      } as any);
      // Assign the new target to the selected mission
      await api.assignTargetToMission(selectedMissionId as number, created.id);
      // Refresh targets and select the new one
      const updatedTargets = await api.getTargets(selectedMissionId as number);
      setTargets(updatedTargets);
      setSelectedTargetId(created.id);
      // Mark discovered host as added (if applicable)
      if (targetIp) {
        setDiscoveredHosts(prev => prev.map(h => h.ip === targetIp.trim() ? { ...h, _added: true } as any : h));
      }
      setShowTargetForm(false);
      setTargetHostname('');
      setTargetIp('');
      setTargetType('windows');
      setTargetConnectionMethod('ssh');
      setTargetSshUsername('');
      setTargetSshPassword('');
      setTargetPort('');
      setTargetNotes('');
    } catch {
      setError('Failed to create target');
    } finally {
      setCreatingTarget(false);
    }
  }

  // Save credentials on an existing target
  async function handleSaveCredentials() {
    if (!selectedTargetId || !editCredPassword) return;
    setSavingCredentials(true);
    setError('');
    try {
      await api.updateTarget(selectedTargetId as number, {
        ssh_username: editCredUsername.trim() || undefined,
        ssh_password: editCredPassword,
      } as any);
      // Refresh targets
      if (selectedMissionId) {
        const updatedTargets = await api.getTargets(selectedMissionId as number);
        setTargets(updatedTargets);
      }
      setShowCredentialEdit(false);
      setEditCredUsername('');
      setEditCredPassword('');
    } catch {
      setError('Failed to update target credentials');
    } finally {
      setSavingCredentials(false);
    }
  }

  // Network Discovery
  async function handleDiscovery() {
    if (!discoverySubnet.trim()) return;
    setDiscovering(true);
    setDiscoveryError('');
    setDiscoveredHosts([]);
    setDiscoveryDone(false);
    try {
      const result = await api.discoverNetwork(discoverySubnet.trim());
      setDiscoveredHosts(result.hosts);
      setDiscoveryDone(true);
    } catch (err: any) {
      setDiscoveryError(err?.response?.data?.detail || 'Discovery failed');
    } finally {
      setDiscovering(false);
    }
  }

  function handleAddDiscoveredTarget(host: DiscoveredHost) {
    if (!selectedMissionId) {
      setError('Please select a Client and Mission first to add discovered targets');
      return;
    }
    // Pre-fill the target form with discovered host data so user can add credentials
    setTargetHostname(host.hostname || '');
    setTargetIp(host.ip);
    setTargetType(host.os_guess === 'unknown' ? 'windows' : host.os_guess);
    const connMethod = host.connection_methods[0] || '';
    setTargetConnectionMethod(connMethod || (host.os_guess === 'windows' ? 'winrm' : 'ssh'));
    setTargetPort(
      host.open_ports.find(p => p.service === 'WinRM-HTTPS')?.port?.toString() ||
      (connMethod === 'winrm' ? '5986' :
      connMethod === 'ssh' ? '22' :
      host.open_ports.find(p => p.service === 'WinRM-HTTP')?.port?.toString() ||
      host.open_ports.find(p => p.service === 'SSH')?.port?.toString() || '')
    );
    setTargetSshUsername('');
    setTargetSshPassword('');
    setTargetNotes(`Discovered via network scan. Open ports: ${host.open_ports.map(p => `${p.port}/${p.service}`).join(', ')}`);
    setShowTargetForm(true);
    // Scroll to the target form
    setTimeout(() => document.getElementById('target-form')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 100);
  }

  const isFinished = scanStatus && ['completed', 'failed', 'cancelled'].includes(scanStatus.status);
  const canLaunch = selectedTargetId && selectedBenchmarkId && !activeScanId;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-ey-yellow" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Scans</h1>
          <p className="mt-1 text-sm text-dark-secondary">
            Launch network scans or export scripts for USB/offline execution
          </p>
        </div>
      </div>

      {/* Mode Tabs */}
      <div className="flex gap-1 rounded-xl border border-dark-border bg-dark-elevated p-1">
        <button
          onClick={() => setScanMode('network')}
          className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
            scanMode === 'network'
              ? 'bg-dark-card text-white shadow-sm'
              : 'text-dark-secondary hover:text-white'
          }`}
        >
          <Wifi className="h-4 w-4" />
          Network Scan
        </button>
        <button
          onClick={() => setScanMode('script_export')}
          className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
            scanMode === 'script_export'
              ? 'bg-dark-card text-white shadow-sm'
              : 'text-dark-secondary hover:text-white'
          }`}
        >
          <Usb className="h-4 w-4" />
          Script Export (USB)
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* ════════════════════════════════════════════════════════════════════
          NETWORK SCAN MODE
          ════════════════════════════════════════════════════════════════════ */}
      {scanMode === 'network' && (
        <>
          {/* Network Discovery */}
          <div className="rounded-xl border border-dark-border bg-dark-card p-6">
            <h2 className="mb-1 text-lg font-semibold text-white flex items-center gap-2">
              <Wifi className="h-5 w-5 text-ey-yellow" />
              Network Discovery
            </h2>
            <p className="mb-4 text-sm text-dark-secondary">
              Scan your network to find live devices. Use <code className="rounded bg-dark-elevated text-ey-yellow/80 px-1 text-xs">host.docker.internal</code> to scan your own machine,
              or enter a subnet like <code className="rounded bg-dark-elevated text-ey-yellow/80 px-1 text-xs">192.168.1.0/24</code>.
            </p>

            <div className="flex gap-3 items-end flex-wrap">
              <div className="flex-1 min-w-[250px] max-w-md">
                <label className="mb-1 block text-sm font-medium text-gray-300">Subnet / IP / Hostname</label>
                <input
                  type="text"
                  value={discoverySubnet}
                  onChange={(e) => setDiscoverySubnet(e.target.value)}
                  placeholder="host.docker.internal or 192.168.1.0/24"
                  className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-2 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                  disabled={discovering}
                />
              </div>
              <button
                onClick={handleDiscovery}
                disabled={discovering || !discoverySubnet.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {discovering ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wifi className="h-4 w-4" />}
                {discovering ? 'Scanning...' : 'Discover'}
              </button>
            </div>

            {discoveryError && (
              <div className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
                {discoveryError}
              </div>
            )}

            {discovering && (
              <div className="mt-4 flex items-center gap-3 text-sm text-ey-yellow">
                <Loader2 className="h-5 w-5 animate-spin" />
                Scanning network... This may take 30-60 seconds for a /24 subnet.
              </div>
            )}

            {discoveryDone && (
              <div className="mt-4">
                {discoveredHosts.length === 0 ? (
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-300">
                    <AlertTriangle className="inline h-4 w-4 mr-1" />
                    No devices found on {discoverySubnet}. Make sure the subnet is reachable from the Docker container.
                    <p className="mt-1 text-xs">Tip: Use your machine's gateway IP (e.g. <code className="bg-dark-elevated text-ey-yellow/80 rounded px-1">192.168.1.0/24</code>) or try a single IP first.</p>
                  </div>
                ) : (
                  <>
                    <div className="mb-3 flex items-center justify-between">
                      <h3 className="text-sm font-semibold text-white">
                        Found {discoveredHosts.length} device{discoveredHosts.length !== 1 ? 's' : ''}
                      </h3>
                      {!selectedMissionId && (
                        <span className="text-xs text-amber-400">Select a Client &amp; Mission below to add targets</span>
                      )}
                    </div>
                    <div className="overflow-hidden rounded-lg border border-dark-border">
                      <table className="min-w-full divide-y divide-dark-border text-sm">
                        <thead className="bg-dark-elevated">
                          <tr>
                            <th className="px-4 py-2 text-left font-medium text-dark-secondary">IP Address</th>
                            <th className="px-4 py-2 text-left font-medium text-dark-secondary">Hostname</th>
                            <th className="px-4 py-2 text-left font-medium text-dark-secondary">OS Type</th>
                            <th className="px-4 py-2 text-left font-medium text-dark-secondary">Open Ports</th>
                            <th className="px-4 py-2 text-left font-medium text-dark-secondary">Connection</th>
                            <th className="px-4 py-2 text-right font-medium text-dark-secondary">Action</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-dark-border">
                          {discoveredHosts.map((host) => (
                            <tr key={host.ip} className="hover:bg-dark-elevated">
                              <td className="px-4 py-2 font-mono text-white">{host.ip}</td>
                              <td className="px-4 py-2 text-gray-300">{host.hostname || <span className="text-dark-muted">-</span>}</td>
                              <td className="px-4 py-2">
                                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                                  host.os_guess === 'windows' ? 'bg-sky-500/10 text-sky-400' :
                                  host.os_guess === 'linux' ? 'bg-emerald-500/10 text-emerald-400' :
                                  host.os_guess === 'network' ? 'bg-purple-500/10 text-purple-400' :
                                  host.os_guess === 'database' ? 'bg-orange-500/10 text-orange-400' :
                                  'bg-dark-overlay text-gray-300'
                                }`}>
                                  <Server className="h-3 w-3" />
                                  {host.os_guess}
                                </span>
                              </td>
                              <td className="px-4 py-2 text-dark-secondary text-xs">
                                {host.open_ports.map(p => `${p.port}/${p.service}`).join(', ')}
                              </td>
                              <td className="px-4 py-2 text-dark-secondary text-xs">
                                {host.connection_methods.join(', ') || '-'}
                              </td>
                              <td className="px-4 py-2 text-right">
                                {(host as any)._added ? (
                                  <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
                                    <CheckCircle2 className="h-3 w-3" /> Added
                                  </span>
                                ) : (
                                  <button
                                    onClick={() => handleAddDiscoveredTarget(host)}
                                    disabled={!selectedMissionId || creatingTarget}
                                    className="inline-flex items-center gap-1 rounded-lg bg-green-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                                  >
                                    <Plus className="h-3 w-3" /> Add &amp; Configure
                                  </button>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          {/* Scan Launcher */}
          <div className="rounded-xl border border-dark-border bg-dark-card p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">Launch Network Scan</h2>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {/* Client */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Client</label>
                <select
                  className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-2 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
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
                <label className="mb-1 block text-sm font-medium text-gray-300">Mission</label>
                <select
                  className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-2 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
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
                    className="mt-1 inline-flex items-center gap-1 text-xs text-ey-yellow hover:text-ey-yellow-hover"
                  >
                    <Plus className="h-3 w-3" /> Create a mission
                  </button>
                )}
              </div>

              {/* Target */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Target</label>
                <div className="flex gap-2">
                  <select
                    className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-2 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
                    value={selectedTargetId}
                    onChange={(e) => { setSelectedTargetId(e.target.value ? Number(e.target.value) : ''); setShowCredentialEdit(false); }}
                    disabled={!selectedMissionId || (!!activeScanId && !isFinished)}
                  >
                    <option value="">Select target...</option>
                    {targets.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.hostname || t.ip_address} ({t.target_type})
                      </option>
                    ))}
                  </select>
                  {selectedTargetId && !(!!activeScanId && !isFinished) && (
                    <button
                      onClick={async () => {
                        const t = targets.find(x => x.id === selectedTargetId);
                        if (!confirm(`Delete target "${t?.hostname || t?.ip_address}"? This will also delete all its scans and findings.`)) return;
                        try {
                          await api.deleteTarget(selectedTargetId as number);
                          setTargets(prev => prev.filter(x => x.id !== selectedTargetId));
                          setSelectedTargetId('');
                          setShowCredentialEdit(false);
                        } catch { setError('Failed to delete target'); }
                      }}
                      className="flex-shrink-0 rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-red-400 hover:bg-red-500/20 hover:text-red-300"
                      title="Delete this target"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
                {selectedMissionId && !showTargetForm && (
                  <button
                    type="button"
                    onClick={() => setShowTargetForm(true)}
                    className="mt-1 inline-flex items-center gap-1 text-xs text-ey-yellow hover:text-ey-yellow-hover"
                  >
                    <Plus className="h-3 w-3" /> Create a target
                  </button>
                )}
              </div>

              {/* Benchmark */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Benchmark</label>
                <select
                  className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-2 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
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
              <form onSubmit={handleCreateMission} className="mt-4 rounded-lg border border-ey-yellow/30 bg-ey-yellow/5 p-4 space-y-3">
                <h4 className="text-sm font-semibold text-white">Quick Create Mission</h4>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Mission Name *</label>
                    <input
                      value={missionName}
                      onChange={(e) => setMissionName(e.target.value)}
                      required
                      placeholder="e.g. Q1 2026 Audit"
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Description</label>
                    <input
                      value={missionDescription}
                      onChange={(e) => setMissionDescription(e.target.value)}
                      placeholder="Optional description"
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={creatingMission || !missionName.trim()}
                    className="inline-flex items-center gap-1 rounded-lg bg-ey-yellow px-3 py-1.5 text-xs font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50"
                  >
                    {creatingMission ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                    Create
                  </button>
                  <button
                    type="button"
                    onClick={() => { setShowMissionForm(false); setMissionName(''); setMissionDescription(''); }}
                    className="rounded-lg bg-dark-overlay px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-border"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}

            {/* Inline Target Creation Form */}
            {showTargetForm && (
              <form id="target-form" onSubmit={handleCreateTarget} className="mt-4 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4 space-y-3">
                <h4 className="text-sm font-semibold text-white">Quick Create Target</h4>
                {targetConnectionMethod === 'winrm' && targetPort === '5985' && (
                  <div className="rounded-lg bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-xs text-amber-300">
                    <strong>Tip:</strong> Port 5985 uses unencrypted HTTP which is blocked on public network profiles. Switch to port <button type="button" className="font-bold underline" onClick={() => setTargetPort('5986')}>5986 (HTTPS)</button> for encrypted connections.
                  </div>
                )}
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Hostname</label>
                    <input
                      value={targetHostname}
                      onChange={(e) => setTargetHostname(e.target.value)}
                      placeholder="e.g. ubuntu-vm"
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">IP Address *</label>
                    <input
                      value={targetIp}
                      onChange={(e) => setTargetIp(e.target.value)}
                      placeholder="e.g. 192.168.1.100"
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Type *</label>
                    <select
                      value={targetType}
                      onChange={(e) => setTargetType(e.target.value)}
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
                    >
                      <option value="windows">Windows</option>
                      <option value="linux">Linux</option>
                      <option value="network">Network</option>
                      <option value="database">Database</option>
                    </select>
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Connection</label>
                    <select
                      value={targetConnectionMethod}
                      onChange={(e) => setTargetConnectionMethod(e.target.value)}
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
                    >
                      <option value="ssh">SSH</option>
                      <option value="winrm">WinRM</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Username</label>
                    <input
                      value={targetSshUsername}
                      onChange={(e) => setTargetSshUsername(e.target.value)}
                      placeholder={targetConnectionMethod === 'winrm' ? 'Administrator' : 'root'}
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Password</label>
                    <input
                      type="password"
                      value={targetSshPassword}
                      onChange={(e) => setTargetSshPassword(e.target.value)}
                      placeholder="Required for scan"
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Port</label>
                    <input
                      value={targetPort}
                      onChange={(e) => setTargetPort(e.target.value)}
                      placeholder={targetConnectionMethod === 'winrm' ? '5985' : '22'}
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                </div>
                <div className="flex gap-2 items-center">
                  <button
                    type="submit"
                    disabled={creatingTarget || !targetIp.trim()}
                    className="inline-flex items-center gap-1 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                  >
                    {creatingTarget ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                    Create
                  </button>
                  <button
                    type="button"
                    onClick={() => { setShowTargetForm(false); setTargetHostname(''); setTargetIp(''); setTargetType('windows'); setTargetConnectionMethod('ssh'); setTargetSshUsername(''); setTargetSshPassword(''); setTargetPort(''); setTargetNotes(''); }}
                    className="rounded-lg bg-dark-overlay px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-border"
                  >
                    Cancel
                  </button>
                  {!targetSshPassword && <span className="text-xs text-amber-400">Credentials are needed for remote scanning</span>}
                </div>
              </form>
            )}

            <div className="mt-6 flex items-center gap-3 flex-wrap">
              {/* Credential warning */}
              {selectedTargetId && !showCredentialEdit && (() => {
                const t = targets.find(x => x.id === selectedTargetId);
                if (t && !t.ssh_username) {
                  return (
                    <div className="w-full mb-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-300 flex items-center gap-2">
                      <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                      <span>
                        <strong>No credentials configured</strong> for this target.
                        The scan requires a username and password to connect.
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          const tgt = targets.find(x => x.id === selectedTargetId);
                          setEditCredUsername(tgt?.ssh_username || (tgt?.target_type === 'windows' ? 'Administrator' : 'root'));
                          setEditCredPassword('');
                          setShowCredentialEdit(true);
                        }}
                        className="ml-auto text-xs font-medium bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 rounded-lg px-3 py-1.5 flex-shrink-0"
                      >
                        Set Credentials
                      </button>
                    </div>
                  );
                }
                return null;
              })()}

              {/* Inline credential editor */}
              {showCredentialEdit && (
                <div className="w-full mb-2 rounded-lg border border-ey-yellow/30 bg-ey-yellow/5 p-4 space-y-3">
                  <h4 className="text-sm font-semibold text-white">Set Target Credentials</h4>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <div>
                      <label className="mb-1 block text-xs font-medium text-gray-300">Username</label>
                      <input
                        value={editCredUsername}
                        onChange={(e) => setEditCredUsername(e.target.value)}
                        placeholder="Administrator"
                        className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-medium text-gray-300">Password *</label>
                      <input
                        type="password"
                        value={editCredPassword}
                        onChange={(e) => setEditCredPassword(e.target.value)}
                        placeholder="Required for scan"
                        className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                      />
                    </div>
                    <div className="flex items-end gap-2">
                      <button
                        type="button"
                        onClick={handleSaveCredentials}
                        disabled={!editCredPassword || savingCredentials}
                        className="inline-flex items-center gap-1 rounded-lg bg-ey-yellow px-3 py-1.5 text-xs font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50"
                      >
                        {savingCredentials ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                        Save
                      </button>
                      <button
                        type="button"
                        onClick={() => { setShowCredentialEdit(false); setEditCredUsername(''); setEditCredPassword(''); }}
                        className="rounded-lg bg-dark-overlay px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-border"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {!activeScanId || isFinished ? (
                <button
                  onClick={handleLaunch}
                  disabled={!canLaunch || launching}
                  className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover disabled:cursor-not-allowed disabled:opacity-50"
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
                  className="inline-flex items-center gap-2 rounded-lg border border-dark-border bg-dark-elevated px-4 py-2 text-sm font-medium text-gray-300 hover:bg-dark-overlay hover:text-white"
                >
                  New Scan
                </button>
              )}
            </div>
          </div>

          {/* Scan Progress */}
          {scanStatus && (
            <div className="rounded-xl border border-dark-border bg-dark-card p-6">
              <div className="mb-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-white">
                    Scan #{scanStatus.scan_id} {' - '} {statusBadge(scanStatus.status)}
                  </h2>
                  {scanStatus.current_rule && (
                    <span className="text-sm text-dark-secondary">
                      Current rule: <span className="font-mono">{scanStatus.current_rule}</span>
                    </span>
                  )}
                </div>
                {/* Smart context line */}
                {(() => {
                  const bm = benchmarks.find((b) => b.id === selectedBenchmarkId);
                  const tgt = targets.find((t) => t.id === selectedTargetId);
                  const parts: string[] = [];
                  if (bm) parts.push(`${bm.name} ${bm.version || ''}`);
                  if (tgt) parts.push(tgt.hostname || tgt.ip_address || `Target #${tgt.id}`);
                  return parts.length > 0 ? (
                    <p className="mt-1 text-xs text-dark-secondary">{parts.join(' - ')}</p>
                  ) : null;
                })()}
              </div>

              {/* Error message for failed scans */}
              {scanStatus.status === 'failed' && scanStatus.error_message && (
                <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
                  <p className="font-medium">Scan failed</p>
                  <p className="mt-1">{scanStatus.error_message}</p>
                </div>
              )}

              {/* Progress bar */}
              {scanStatus.total > 0 && (
                <div className="mb-6">
                  <div className="mb-1 flex justify-between text-sm text-dark-secondary">
                    <span>
                      {scanStatus.progress} / {scanStatus.total} rules
                    </span>
                    <span>{Math.round((scanStatus.progress / scanStatus.total) * 100)}%</span>
                  </div>
                  <div className="h-3 w-full overflow-hidden rounded-full bg-dark-overlay">
                    <div
                      className={`h-full rounded-full transition-all duration-300 ${
                        scanStatus.status === 'failed'
                          ? 'bg-red-500'
                          : scanStatus.status === 'completed'
                            ? 'bg-green-500'
                            : 'bg-ey-yellow'
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
                <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 text-center">
                  <CheckCircle2 className="mx-auto mb-1 h-6 w-6 text-emerald-400" />
                  <div className="text-2xl font-bold text-emerald-400">{scanStatus.passed}</div>
                  <div className="text-xs text-emerald-400/70">Passed</div>
                </div>
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-center">
                  <XCircle className="mx-auto mb-1 h-6 w-6 text-red-400" />
                  <div className="text-2xl font-bold text-red-400">{scanStatus.failed}</div>
                  <div className="text-xs text-red-400/70">Failed</div>
                </div>
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-center">
                  <AlertTriangle className="mx-auto mb-1 h-6 w-6 text-amber-400" />
                  <div className="text-2xl font-bold text-amber-400">{scanStatus.errors}</div>
                  <div className="text-xs text-amber-400/70">Errors</div>
                </div>
                <div className="rounded-lg border border-sky-500/30 bg-sky-500/10 p-4 text-center">
                  <Server className="mx-auto mb-1 h-6 w-6 text-sky-400" />
                  <div className="text-2xl font-bold text-sky-400">
                    {scanStatus.compliance_percentage}%
                  </div>
                  <div className="text-xs text-sky-400/70">Compliance</div>
                </div>
              </div>
            </div>
          )}

          {/* Empty state */}
          {!scanStatus && (
            <div className="rounded-xl border border-dashed border-dark-border bg-dark-card p-12 text-center">
              <Wifi className="mx-auto h-12 w-12 text-dark-muted" />
              <h3 className="mt-4 text-lg font-medium text-white">No active scan</h3>
              <p className="mt-2 text-sm text-dark-secondary">
                Select a target and benchmark above, then click &quot;Start Scan&quot; to begin a network audit.
              </p>
            </div>
          )}

          {/* Result Import Section */}
          <div className="rounded-xl border border-dark-border bg-dark-card p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">Import Results</h2>
            <p className="mb-4 text-sm text-dark-secondary">
              Import scan results from offline/USB execution (audit_results.json or marker-based output)
            </p>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">
                  Results File (JSON, TXT, or ZIP)
                </label>
                <input
                  type="file"
                  accept=".json,.txt,.zip"
                  onChange={(e) => setImportFile(e.target.files?.[0] || null)}
                  className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-2 text-sm file:mr-4 file:rounded-lg file:border-0 file:bg-ey-yellow/10 file:px-4 file:py-2 file:text-sm file:font-medium file:text-ey-yellow hover:file:bg-ey-yellow/20"
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
                <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-400">
                  <p className="font-medium">Import successful!</p>
                  <p>Findings created: {importResult.findings_created} | Passed: {importResult.passed} | Failed: {importResult.failed} | Errors: {importResult.errors}</p>
                  <p>Compliance: {importResult.compliance_percentage}%</p>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* ════════════════════════════════════════════════════════════════════
          SCRIPT EXPORT (USB) MODE
          ════════════════════════════════════════════════════════════════════ */}
      {scanMode === 'script_export' && (
        <>
          <div className="rounded-xl border border-dark-border bg-dark-card p-6">
            <div className="mb-4 flex items-center gap-3">
              <Usb className="h-6 w-6 text-purple-400" />
              <div>
                <h2 className="text-lg font-semibold text-white">Export Audit Scripts</h2>
                <p className="text-sm text-dark-secondary">
                  Generate a ZIP package of audit scripts for offline/USB execution on air-gapped systems
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {/* Benchmark */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Benchmark *</label>
                <select
                  className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-2 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
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
                className="inline-flex items-center gap-2 rounded-lg border border-dark-border bg-dark-elevated px-4 py-2 text-sm font-medium text-gray-300 hover:bg-dark-overlay hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
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

            {/* Smart filename preview */}
            {selectedBenchmarkId && (
              <p className="mt-3 text-xs text-dark-muted">
                <span className="font-medium text-dark-secondary">Export filename:</span>{' '}
                <span className="font-mono text-ey-yellow/70">{buildExportFilename()}</span>
              </p>
            )}
          </div>

          {/* Script Preview */}
          {scriptPreview && (
            <div className="rounded-xl border border-dark-border bg-dark-card p-6">
              <h3 className="mb-4 text-lg font-semibold text-white">
                Script Preview {' - '} {scriptPreview.total_rules} rules
              </h3>
              {scriptPreview.rules.length === 0 ? (
                <p className="text-sm text-dark-secondary">No rules found for the selected criteria.</p>
              ) : (
                <div className="max-h-96 overflow-y-auto">
                  <table className="min-w-full divide-y divide-dark-border">
                    <thead className="bg-dark-elevated">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-medium uppercase text-dark-secondary">Section</th>
                        <th className="px-4 py-2 text-left text-xs font-medium uppercase text-dark-secondary">Title</th>
                        <th className="px-4 py-2 text-left text-xs font-medium uppercase text-dark-secondary">Severity</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-dark-border">
                      {scriptPreview.rules.map((rule) => (
                        <tr key={rule.id}>
                          <td className="whitespace-nowrap px-4 py-2 text-sm font-mono text-white">{rule.section_number}</td>
                          <td className="px-4 py-2 text-sm text-gray-300">{rule.title ?? '-'}</td>
                          <td className="whitespace-nowrap px-4 py-2">
                            <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                              rule.severity === 'high' ? 'bg-red-500/10 text-red-400' :
                              rule.severity === 'medium' ? 'bg-amber-500/10 text-amber-400' :
                              'bg-emerald-500/10 text-emerald-400'
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
            <div className="rounded-xl border border-dashed border-dark-border bg-dark-card p-12 text-center">
              <Usb className="mx-auto h-12 w-12 text-dark-muted" />
              <h3 className="mt-4 text-lg font-medium text-white">Script Export Workflow</h3>
              <div className="mx-auto mt-4 max-w-lg text-left text-sm text-dark-secondary space-y-2">
                <p><strong>1.</strong> Select a benchmark and click &quot;Download Script Package&quot;</p>
                <p><strong>2.</strong> Copy the ZIP to a USB drive and transfer to the target system</p>
                <p><strong>3.</strong> Extract and run the audit script on the target</p>
                <p><strong>4.</strong> Copy the results file back and import below</p>
              </div>
            </div>
          )}

          {/* Import Results Section (Script Export Tab) */}
          <div className="rounded-xl border border-dark-border bg-dark-card p-6">
            <div className="mb-4 flex items-center gap-3">
              <Upload className="h-6 w-6 text-green-400" />
              <div>
                <h2 className="text-lg font-semibold text-white">Import Results</h2>
                <p className="text-sm text-dark-secondary">
                  Import scan results from offline/USB execution (audit_results.json)
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {/* Client selector */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Client</label>
                <select
                  className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-2 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
                  value={selectedClientId}
                  onChange={(e) => setSelectedClientId(e.target.value ? Number(e.target.value) : '')}
                >
                  <option value="">Select client...</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>

              {/* Mission selector */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Mission</label>
                <select
                  className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-2 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
                  value={selectedMissionId}
                  onChange={(e) => setSelectedMissionId(e.target.value ? Number(e.target.value) : '')}
                  disabled={!selectedClientId}
                >
                  <option value="">Select mission...</option>
                  {missions.map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
                {selectedClientId && missions.length === 0 && !showMissionForm && (
                  <button
                    type="button"
                    onClick={() => setShowMissionForm(true)}
                    className="mt-1 inline-flex items-center gap-1 text-xs text-ey-yellow hover:text-ey-yellow-hover"
                  >
                    <Plus className="h-3 w-3" /> Create a mission
                  </button>
                )}
              </div>

              {/* Target selector */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Target</label>
                <select
                  className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-2 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
                  value={selectedTargetId}
                  onChange={(e) => setSelectedTargetId(e.target.value ? Number(e.target.value) : '')}
                  disabled={!selectedMissionId}
                >
                  <option value="">Select target...</option>
                  {targets.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.hostname || t.ip_address} ({t.target_type})
                    </option>
                  ))}
                </select>
                {selectedMissionId && targets.length === 0 && !showTargetForm && (
                  <button
                    type="button"
                    onClick={() => setShowTargetForm(true)}
                    className="mt-1 inline-flex items-center gap-1 text-xs text-green-400 hover:text-green-300"
                  >
                    <Plus className="h-3 w-3" /> Create a target
                  </button>
                )}
              </div>
            </div>

            {/* Inline Target Creation Form (Script Export Tab) */}
            {showTargetForm && scanMode === 'script_export' && (
              <form onSubmit={handleCreateTarget} className="mt-4 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4 space-y-3">
                <h4 className="text-sm font-semibold text-white">Quick Create Target</h4>
                {targetConnectionMethod === 'winrm' && targetPort === '5985' && (
                  <div className="rounded-lg bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-xs text-amber-300">
                    <strong>Tip:</strong> Port 5985 uses unencrypted HTTP which is blocked on public network profiles. Switch to port <button type="button" className="font-bold underline" onClick={() => setTargetPort('5986')}>5986 (HTTPS)</button> for encrypted connections.
                  </div>
                )}
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Hostname</label>
                    <input
                      value={targetHostname}
                      onChange={(e) => setTargetHostname(e.target.value)}
                      placeholder="e.g. ubuntu-vm"
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">IP Address *</label>
                    <input
                      value={targetIp}
                      onChange={(e) => setTargetIp(e.target.value)}
                      placeholder="e.g. 192.168.1.100"
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Type *</label>
                    <select
                      value={targetType}
                      onChange={(e) => setTargetType(e.target.value)}
                      required
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    >
                      <option value="windows">Windows</option>
                      <option value="linux">Linux</option>
                      <option value="network">Network</option>
                      <option value="database">Database</option>
                    </select>
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Connection</label>
                    <select
                      value={targetConnectionMethod}
                      onChange={(e) => { setTargetConnectionMethod(e.target.value); setTargetPort(e.target.value === 'winrm' ? '5986' : '22'); }}
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
                    >
                      <option value="ssh">SSH</option>
                      <option value="winrm">WinRM</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Username</label>
                    <input
                      value={targetSshUsername}
                      onChange={(e) => setTargetSshUsername(e.target.value)}
                      placeholder={targetConnectionMethod === 'winrm' ? 'Administrator' : 'root'}
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Password</label>
                    <input
                      type="password"
                      value={targetSshPassword}
                      onChange={(e) => setTargetSshPassword(e.target.value)}
                      placeholder="Required for scan"
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Port</label>
                    <input
                      value={targetPort}
                      onChange={(e) => setTargetPort(e.target.value)}
                      placeholder={targetConnectionMethod === 'winrm' ? '5986' : '22'}
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                </div>
                <div className="flex gap-2 items-center">
                  <button
                    type="submit"
                    disabled={creatingTarget || !targetIp.trim()}
                    className="inline-flex items-center gap-1 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                  >
                    {creatingTarget ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                    Create
                  </button>
                  <button
                    type="button"
                    onClick={() => { setShowTargetForm(false); setTargetHostname(''); setTargetIp(''); setTargetType('windows'); setTargetConnectionMethod('ssh'); setTargetSshUsername(''); setTargetSshPassword(''); setTargetPort(''); setTargetNotes(''); }}
                    className="rounded-lg bg-dark-overlay px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-border"
                  >
                    Cancel
                  </button>
                  {!targetSshPassword && <span className="text-xs text-amber-400">Credentials are needed for remote scanning</span>}
                </div>
              </form>
            )}

            {/* Inline Mission Creation Form (Script Export Tab) */}
            {showMissionForm && scanMode === 'script_export' && (
              <form onSubmit={handleCreateMission} className="mt-4 rounded-lg border border-ey-yellow/30 bg-ey-yellow/5 p-4 space-y-3">
                <h4 className="text-sm font-semibold text-white">Quick Create Mission</h4>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Mission Name *</label>
                    <input
                      value={missionName}
                      onChange={(e) => setMissionName(e.target.value)}
                      required
                      placeholder="e.g. Q1 2026 Audit"
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Description</label>
                    <input
                      value={missionDescription}
                      onChange={(e) => setMissionDescription(e.target.value)}
                      placeholder="Optional description"
                      className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white placeholder-dark-muted px-3 py-1.5 text-sm focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                    />
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={creatingMission || !missionName.trim()}
                    className="inline-flex items-center gap-1 rounded-lg bg-ey-yellow px-3 py-1.5 text-xs font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50"
                  >
                    {creatingMission ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                    Create
                  </button>
                  <button
                    type="button"
                    onClick={() => { setShowMissionForm(false); setMissionName(''); setMissionDescription(''); }}
                    className="rounded-lg bg-dark-overlay px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-border"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}

            <div className="mt-4 space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">
                  Results File (JSON, TXT, or ZIP)
                </label>
                <input
                  type="file"
                  accept=".json,.txt,.zip"
                  onChange={(e) => setImportFile(e.target.files?.[0] || null)}
                  className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-2 text-sm file:mr-4 file:rounded-lg file:border-0 file:bg-ey-yellow/10 file:px-4 file:py-2 file:text-sm file:font-medium file:text-ey-yellow hover:file:bg-ey-yellow/20"
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
              {!selectedTargetId && importFile && (
                <p className="text-xs text-amber-400">
                  Please select a Client, Mission, and Target above to enable import.
                </p>
              )}
              {importResult && (
                <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-400">
                  <p className="font-medium">Import successful!</p>
                  <p>Findings created: {importResult.findings_created} | Passed: {importResult.passed} | Failed: {importResult.failed} | Errors: {importResult.errors}</p>
                  <p>Compliance: {importResult.compliance_percentage}%</p>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
