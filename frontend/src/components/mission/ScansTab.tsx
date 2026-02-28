import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Plus,
  Trash2,
  Server,
  Play,
  Square,
  AlertTriangle,
  Upload,
  Download,
  Loader2,
  Wifi,
  Usb,
  CheckCircle2,
  XCircle,
} from 'lucide-react';
import type {
  Target,
  Benchmark,
  ScanDetail,
  ScanStatus,
  ImportResultsResponse,
  ScriptPreviewResponse,
  DiscoveredHost,
} from '@/types';
import * as api from '@/services/api';
import { inputClass, scanStatusBadge } from '../mission/badgeHelpers';

type ScanMode = 'network' | 'script_export';

interface Props {
  missionId: number;
  missionTargets: Target[];
  scans: ScanDetail[];
  benchmarks: Benchmark[];
  client: { id: number; name: string } | null;
  mission: { client_id: number } | null;
  onRefresh: () => Promise<void>;
  onError: (msg: string) => void;
}

export default function ScansTab({
  missionId,
  missionTargets,
  scans,
  benchmarks,
  client,
  mission,
  onRefresh,
  onError,
}: Props) {
  /* ── Scan mode ─────────────────────────────────────────── */
  const [scanMode, setScanMode] = useState<ScanMode>('network');

  /* ── Scan control ──────────────────────────────────────── */
  const [selectedTargetId, setSelectedTargetId] = useState<number | ''>('');
  const [selectedBenchmarkId, setSelectedBenchmarkId] = useState<number | ''>('');
  const [launching, setLaunching] = useState(false);
  const [activeScanId, setActiveScanId] = useState<number | null>(null);
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ── Import state ──────────────────────────────────────── */
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<ImportResultsResponse | null>(null);

  /* ── Script export state ───────────────────────────────── */
  const [exporting, setExporting] = useState(false);
  const [scriptPreview, setScriptPreview] = useState<ScriptPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  /* ── Discovery state ───────────────────────────────────── */
  const [discoverySubnet, setDiscoverySubnet] = useState('');
  const [discovering, setDiscovering] = useState(false);
  const [discoveredHosts, setDiscoveredHosts] = useState<DiscoveredHost[]>([]);
  const [discoveryError, setDiscoveryError] = useState('');
  const [discoveryDone, setDiscoveryDone] = useState(false);

  /* ── Inline target creation ────────────────────────────── */
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

  /* ── Credential edit ───────────────────────────────────── */
  const [showCredentialEdit, setShowCredentialEdit] = useState(false);
  const [editCredUsername, setEditCredUsername] = useState('');
  const [editCredPassword, setEditCredPassword] = useState('');
  const [savingCredentials, setSavingCredentials] = useState(false);

  /* ── Derived ───────────────────────────────────────────── */
  const isFinished = scanStatus && ['completed', 'failed', 'cancelled'].includes(scanStatus.status);
  const canLaunch = selectedTargetId && selectedBenchmarkId && !activeScanId;

  /* ── Polling scan status ───────────────────────────────── */
  const pollScanStatusCb = useCallback(async () => {
    if (!activeScanId) return;
    try {
      const status = await api.getScanStatus(activeScanId);
      setScanStatus(status);
      if (['completed', 'failed', 'cancelled'].includes(status.status)) {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        onRefresh();
      }
    } catch { /* ignore */ }
  }, [activeScanId, onRefresh]);

  useEffect(() => {
    if (activeScanId) {
      pollRef.current = setInterval(pollScanStatusCb, 2000);
      pollScanStatusCb();
      return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }
  }, [activeScanId, pollScanStatusCb]);

  /* ── Handlers ──────────────────────────────────────────── */
  const handleLaunchScan = async () => {
    if (!selectedTargetId || !selectedBenchmarkId) return;
    setLaunching(true);
    try {
      const result = await api.startNetworkScan({
        target_id: selectedTargetId as number,
        benchmark_id: selectedBenchmarkId as number,
        mission_id: missionId,
      });
      setActiveScanId(result.scan_id);
      setScanStatus({
        scan_id: result.scan_id, status: 'running', progress: 0, total: 0,
        current_rule: '', passed: 0, failed: 0, errors: 0, compliance_percentage: 0,
      });
    } catch (err: any) {
      onError(err?.response?.data?.detail || 'Failed to start scan');
    } finally {
      setLaunching(false);
    }
  };

  const handleCancelScan = async () => {
    if (!activeScanId) return;
    try { await api.cancelScan(activeScanId); } catch { /* */ }
  };

  const handleImport = async () => {
    if (!importFile || !selectedTargetId || !selectedBenchmarkId) return;
    setImporting(true);
    try {
      const result = await api.importWithNewScan(selectedTargetId as number, selectedBenchmarkId as number, importFile, missionId);
      setImportResult(result);
      setImportFile(null);
      await onRefresh();
    } catch (err: any) {
      onError(err?.response?.data?.detail || 'Import failed');
    } finally {
      setImporting(false);
    }
  };

  const handleDeleteScan = async (scanId: number) => {
    if (!window.confirm('Delete this scan and all its findings?')) return;
    try { await api.deleteScan(scanId); await onRefresh(); }
    catch { onError('Failed to delete scan'); }
  };

  function buildExportFilename(): string {
    const bm = benchmarks.find(b => b.id === selectedBenchmarkId);
    if (!bm) return `audit_scripts_benchmark_${selectedBenchmarkId}.zip`;
    const safeName = bm.name.replace(/[\s/\\]+/g, '_');
    const safeVersion = (bm.version || 'unknown').replace(/[\s/\\]+/g, '_');
    const dateStamp = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    return `auditforge_audit_${safeName}_${safeVersion}_${dateStamp}.zip`;
  }

  const handlePreviewScript = async () => {
    if (!selectedBenchmarkId) return;
    setPreviewLoading(true);
    try {
      const preview = await api.previewScript({ benchmark_id: selectedBenchmarkId as number });
      setScriptPreview(preview);
    } catch (err: any) {
      onError(err?.response?.data?.detail || 'Failed to preview script');
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleExportScript = async () => {
    if (!selectedBenchmarkId) return;
    setExporting(true);
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
      onError(err?.response?.data?.detail || 'Failed to generate script package');
    } finally {
      setExporting(false);
    }
  };

  const handleDiscovery = async () => {
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
  };

  const handleAddDiscoveredTarget = (host: DiscoveredHost) => {
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
      host.open_ports.find(p => p.service === 'SSH')?.port?.toString() || ''),
    );
    setTargetSshUsername('');
    setTargetSshPassword('');
    setTargetNotes(`Discovered via network scan. Open ports: ${host.open_ports.map(p => `${p.port}/${p.service}`).join(', ')}`);
    setShowTargetForm(true);
    setTimeout(() => document.getElementById('target-form')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 100);
  };

  const handleCreateTarget = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetIp.trim() && !targetHostname.trim()) return;
    setCreatingTarget(true);
    try {
      const created = await api.createTarget({
        client_id: client?.id || mission?.client_id,
        hostname: targetHostname.trim() || undefined,
        ip_address: targetIp.trim() || undefined,
        target_type: targetType,
        connection_method: targetConnectionMethod || undefined,
        ssh_username: targetSshUsername.trim() || undefined,
        ssh_password: targetSshPassword || undefined,
        port: targetPort ? Number(targetPort) : undefined,
        notes: targetNotes.trim() || undefined,
      } as any);
      await api.assignTargetToMission(missionId, created.id);
      if (targetIp) {
        setDiscoveredHosts(prev => prev.map(h => h.ip === targetIp.trim() ? { ...h, _added: true } as any : h));
      }
      setShowTargetForm(false);
      setTargetHostname(''); setTargetIp(''); setTargetType('windows');
      setTargetConnectionMethod('ssh'); setTargetSshUsername(''); setTargetSshPassword('');
      setTargetPort(''); setTargetNotes('');
      await onRefresh();
    } catch {
      onError('Failed to create target');
    } finally {
      setCreatingTarget(false);
    }
  };

  const handleSaveCredentials = async () => {
    if (!selectedTargetId || !editCredPassword) return;
    setSavingCredentials(true);
    try {
      await api.updateTarget(selectedTargetId as number, {
        ssh_username: editCredUsername.trim() || undefined,
        ssh_password: editCredPassword,
      } as any);
      setShowCredentialEdit(false);
      setEditCredUsername(''); setEditCredPassword('');
      await onRefresh();
    } catch {
      onError('Failed to update target credentials');
    } finally {
      setSavingCredentials(false);
    }
  };

  /* ── Render ────────────────────────────────────────────── */
  return (
    <div className="space-y-6">

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

      {/* ════════════════════════════════ NETWORK SCAN MODE ════════════════════════════════ */}
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
                  onChange={e => setDiscoverySubnet(e.target.value)}
                  placeholder="host.docker.internal or 192.168.1.0/24"
                  className={inputClass}
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
              <div className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{discoveryError}</div>
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
                    <p className="mt-1 text-xs">Tip: Use your machine&apos;s gateway IP (e.g. <code className="bg-dark-elevated text-ey-yellow/80 rounded px-1">192.168.1.0/24</code>) or try a single IP first.</p>
                  </div>
                ) : (
                  <>
                    <div className="mb-3">
                      <h3 className="text-sm font-semibold text-white">
                        Found {discoveredHosts.length} device{discoveredHosts.length !== 1 ? 's' : ''}
                      </h3>
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
                          {discoveredHosts.map(host => (
                            <tr key={host.ip} className="hover:bg-dark-elevated">
                              <td className="px-4 py-2 font-mono text-white">{host.ip}</td>
                              <td className="px-4 py-2 text-gray-300">{host.hostname || <span className="text-dark-muted">—</span>}</td>
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
                                {host.connection_methods.join(', ') || '—'}
                              </td>
                              <td className="px-4 py-2 text-right">
                                {(host as any)._added ? (
                                  <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
                                    <CheckCircle2 className="h-3 w-3" /> Added
                                  </span>
                                ) : (
                                  <button
                                    onClick={() => handleAddDiscoveredTarget(host)}
                                    disabled={creatingTarget}
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

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {/* Target */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Target *</label>
                <div className="flex gap-2">
                  <select
                    className={inputClass}
                    value={selectedTargetId}
                    onChange={e => { setSelectedTargetId(e.target.value ? Number(e.target.value) : ''); setShowCredentialEdit(false); }}
                    disabled={!!activeScanId && !isFinished}
                  >
                    <option value="">Select target...</option>
                    {missionTargets.map(t => (
                      <option key={t.id} value={t.id}>
                        {t.hostname || t.ip_address} ({t.target_type})
                      </option>
                    ))}
                  </select>
                  {selectedTargetId && !(!!activeScanId && !isFinished) && (
                    <button
                      onClick={async () => {
                        const t = missionTargets.find(x => x.id === selectedTargetId);
                        if (!confirm(`Delete target "${t?.hostname || t?.ip_address}"? This will also delete all its scans and findings.`)) return;
                        try {
                          await api.deleteTarget(selectedTargetId as number);
                          setSelectedTargetId('');
                          setShowCredentialEdit(false);
                          await onRefresh();
                        } catch { onError('Failed to delete target'); }
                      }}
                      className="flex-shrink-0 rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-red-400 hover:bg-red-500/20 hover:text-red-300"
                      title="Delete this target"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
                {!showTargetForm && (
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
                <label className="mb-1 block text-sm font-medium text-gray-300">Benchmark *</label>
                <select
                  className={inputClass}
                  value={selectedBenchmarkId}
                  onChange={e => setSelectedBenchmarkId(e.target.value ? Number(e.target.value) : '')}
                  disabled={!!activeScanId && !isFinished}
                >
                  <option value="">Select benchmark...</option>
                  {benchmarks.map(b => (
                    <option key={b.id} value={b.id}>{b.name} v{b.version}</option>
                  ))}
                </select>
              </div>

              {/* Import Results */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Import Results</label>
                <div className="flex items-center gap-2">
                  <input
                    type="file"
                    accept=".json,.txt,.csv,.zip"
                    onChange={e => setImportFile(e.target.files?.[0] || null)}
                    className="block w-full text-xs text-dark-muted file:mr-2 file:rounded file:border-0 file:bg-dark-elevated file:px-2 file:py-1 file:text-xs file:text-dark-secondary"
                  />
                  <button
                    onClick={handleImport}
                    disabled={!importFile || !selectedTargetId || !selectedBenchmarkId || importing}
                    className="rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-dark-secondary hover:bg-dark-elevated hover:text-white disabled:opacity-50"
                  >
                    {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                  </button>
                </div>
              </div>
            </div>

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
                    <input value={targetHostname} onChange={e => setTargetHostname(e.target.value)} placeholder="e.g. ubuntu-vm" className={inputClass} />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">IP Address *</label>
                    <input value={targetIp} onChange={e => setTargetIp(e.target.value)} placeholder="e.g. 192.168.1.100" className={inputClass} />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Type *</label>
                    <select value={targetType} onChange={e => setTargetType(e.target.value)} className={inputClass}>
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
                    <select value={targetConnectionMethod} onChange={e => { setTargetConnectionMethod(e.target.value); setTargetPort(e.target.value === 'winrm' ? '5986' : '22'); }} className={inputClass}>
                      <option value="ssh">SSH</option>
                      <option value="winrm">WinRM</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Username</label>
                    <input value={targetSshUsername} onChange={e => setTargetSshUsername(e.target.value)} placeholder={targetConnectionMethod === 'winrm' ? 'Administrator' : 'root'} className={inputClass} />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Password</label>
                    <input type="password" value={targetSshPassword} onChange={e => setTargetSshPassword(e.target.value)} placeholder="Required for scan" className={inputClass} />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-300">Port</label>
                    <input value={targetPort} onChange={e => setTargetPort(e.target.value)} placeholder={targetConnectionMethod === 'winrm' ? '5986' : '22'} className={inputClass} />
                  </div>
                </div>
                <div className="flex gap-2 items-center">
                  <button type="submit" disabled={creatingTarget || !targetIp.trim()} className="inline-flex items-center gap-1 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50">
                    {creatingTarget ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                    Create &amp; Assign
                  </button>
                  <button type="button" onClick={() => { setShowTargetForm(false); setTargetHostname(''); setTargetIp(''); setTargetType('windows'); setTargetConnectionMethod('ssh'); setTargetSshUsername(''); setTargetSshPassword(''); setTargetPort(''); setTargetNotes(''); }} className="rounded-lg bg-dark-overlay px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-border">
                    Cancel
                  </button>
                  {!targetSshPassword && <span className="text-xs text-amber-400">Credentials are needed for remote scanning</span>}
                </div>
              </form>
            )}

            {/* Credential warning & editing */}
            <div className="mt-4 space-y-3">
              {selectedTargetId && !showCredentialEdit && (() => {
                const t = missionTargets.find(x => x.id === selectedTargetId);
                if (t && !t.ssh_username) {
                  return (
                    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-300 flex items-center gap-2">
                      <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                      <span>
                        <strong>No credentials configured</strong> for this target.
                        The scan requires a username and password to connect.
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          const tgt = missionTargets.find(x => x.id === selectedTargetId);
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

              {showCredentialEdit && (
                <div className="rounded-lg border border-ey-yellow/30 bg-ey-yellow/5 p-4 space-y-3">
                  <h4 className="text-sm font-semibold text-white">Set Target Credentials</h4>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <div>
                      <label className="mb-1 block text-xs font-medium text-gray-300">Username</label>
                      <input value={editCredUsername} onChange={e => setEditCredUsername(e.target.value)} placeholder="Administrator" className={inputClass} />
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-medium text-gray-300">Password *</label>
                      <input type="password" value={editCredPassword} onChange={e => setEditCredPassword(e.target.value)} placeholder="Required for scan" className={inputClass} />
                    </div>
                    <div className="flex items-end gap-2">
                      <button type="button" onClick={handleSaveCredentials} disabled={!editCredPassword || savingCredentials} className="inline-flex items-center gap-1 rounded-lg bg-ey-yellow px-3 py-1.5 text-xs font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50">
                        {savingCredentials ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                        Save
                      </button>
                      <button type="button" onClick={() => { setShowCredentialEdit(false); setEditCredUsername(''); setEditCredPassword(''); }} className="rounded-lg bg-dark-overlay px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-border">
                        Cancel
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Scan Launch Controls */}
            <div className="mt-4 flex items-center gap-3 flex-wrap">
              {!activeScanId || isFinished ? (
                <button
                  onClick={handleLaunchScan}
                  disabled={!canLaunch || launching}
                  className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {launching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  {launching ? 'Starting...' : 'Start Scan'}
                </button>
              ) : (
                <button
                  onClick={handleCancelScan}
                  className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
                >
                  <Square className="h-4 w-4" />
                  Cancel Scan
                </button>
              )}

              {isFinished && (
                <button
                  onClick={() => { setActiveScanId(null); setScanStatus(null); }}
                  className="inline-flex items-center gap-2 rounded-lg border border-dark-border bg-dark-elevated px-4 py-2 text-sm font-medium text-gray-300 hover:bg-dark-overlay hover:text-white"
                >
                  New Scan
                </button>
              )}
            </div>
          </div>

          {/* Scan Progress — Detailed Card */}
          {scanStatus && (
            <div className="rounded-xl border border-dark-border bg-dark-card p-6">
              <div className="mb-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-white">
                    Scan #{scanStatus.scan_id} — {scanStatusBadge(scanStatus.status)}
                  </h2>
                  {scanStatus.current_rule && (
                    <span className="text-sm text-dark-secondary">
                      Current rule: <span className="font-mono">{scanStatus.current_rule}</span>
                    </span>
                  )}
                </div>
                {(() => {
                  const bm = benchmarks.find(b => b.id === selectedBenchmarkId);
                  const tgt = missionTargets.find(t => t.id === selectedTargetId);
                  const parts: string[] = [];
                  if (bm) parts.push(`${bm.name} ${bm.version || ''}`);
                  if (tgt) parts.push(tgt.hostname || tgt.ip_address || `Target #${tgt.id}`);
                  return parts.length > 0 ? <p className="mt-1 text-xs text-dark-secondary">{parts.join(' — ')}</p> : null;
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
                    <span>{scanStatus.progress} / {scanStatus.total} rules</span>
                    <span>{Math.round((scanStatus.progress / scanStatus.total) * 100)}%</span>
                  </div>
                  <div className="h-3 w-full overflow-hidden rounded-full bg-dark-overlay">
                    <div
                      className={`h-full rounded-full transition-all duration-300 ${
                        scanStatus.status === 'failed' ? 'bg-red-500' :
                        scanStatus.status === 'completed' ? 'bg-green-500' : 'bg-ey-yellow'
                      }`}
                      style={{ width: `${Math.round((scanStatus.progress / scanStatus.total) * 100)}%` }}
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
                  <div className="text-2xl font-bold text-sky-400">{scanStatus.compliance_percentage}%</div>
                  <div className="text-xs text-sky-400/70">Compliance</div>
                </div>
              </div>
            </div>
          )}

          {/* Import Result Banner */}
          {importResult && (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-400">
              <p className="font-medium">Import successful!</p>
              <p>Findings created: {importResult.findings_created} | Passed: {importResult.passed} | Failed: {importResult.failed} | Errors: {importResult.errors}</p>
              <p>Compliance: {importResult.compliance_percentage}%</p>
              <button onClick={() => setImportResult(null)} className="mt-1 text-emerald-300 hover:text-white text-xs">Dismiss</button>
            </div>
          )}

          {/* Empty state */}
          {!scanStatus && !importResult && scans.length === 0 && (
            <div className="rounded-xl border border-dashed border-dark-border bg-dark-card p-12 text-center">
              <Wifi className="mx-auto h-12 w-12 text-dark-muted" />
              <h3 className="mt-4 text-lg font-medium text-white">No active scan</h3>
              <p className="mt-2 text-sm text-dark-secondary">
                Select a target and benchmark above, then click &quot;Start Scan&quot; to begin a network audit.
              </p>
            </div>
          )}
        </>
      )}

      {/* ════════════════════════════════ SCRIPT EXPORT (USB) MODE ════════════════════════════════ */}
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
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Benchmark *</label>
                <select
                  className={inputClass}
                  value={selectedBenchmarkId}
                  onChange={e => { setSelectedBenchmarkId(e.target.value ? Number(e.target.value) : ''); setScriptPreview(null); }}
                >
                  <option value="">Select benchmark...</option>
                  {benchmarks.map(b => (
                    <option key={b.id} value={b.id}>{b.name} v{b.version} ({b.platform})</option>
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
                Script Preview — {scriptPreview.total_rules} rules
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
                      {scriptPreview.rules.map(rule => (
                        <tr key={rule.id}>
                          <td className="whitespace-nowrap px-4 py-2 text-sm font-mono text-white">{rule.section_number}</td>
                          <td className="px-4 py-2 text-sm text-gray-300">{rule.title ?? '—'}</td>
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
                <p><strong>4.</strong> Copy the results file back and import using the Network Scan tab</p>
              </div>
            </div>
          )}

          {/* Import in USB mode */}
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
              {/* Target selector */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Target *</label>
                <select
                  className={inputClass}
                  value={selectedTargetId}
                  onChange={e => setSelectedTargetId(e.target.value ? Number(e.target.value) : '')}
                >
                  <option value="">Select target...</option>
                  {missionTargets.map(t => (
                    <option key={t.id} value={t.id}>
                      {t.hostname || t.ip_address} ({t.target_type})
                    </option>
                  ))}
                </select>
                {missionTargets.length === 0 && (
                  <p className="mt-1 text-xs text-amber-400">Assign targets to this mission first via the Targets tab.</p>
                )}
              </div>

              {/* Benchmark already selected above */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Benchmark *</label>
                <select
                  className={inputClass}
                  value={selectedBenchmarkId}
                  onChange={e => setSelectedBenchmarkId(e.target.value ? Number(e.target.value) : '')}
                >
                  <option value="">Select benchmark...</option>
                  {benchmarks.map(b => (
                    <option key={b.id} value={b.id}>{b.name} v{b.version}</option>
                  ))}
                </select>
              </div>

              {/* File */}
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Results File (JSON, TXT, or ZIP)</label>
                <input
                  type="file"
                  accept=".json,.txt,.zip"
                  onChange={e => setImportFile(e.target.files?.[0] || null)}
                  className="w-full rounded-lg border border-dark-border bg-dark-elevated text-white px-3 py-2 text-sm file:mr-4 file:rounded-lg file:border-0 file:bg-ey-yellow/10 file:px-4 file:py-2 file:text-sm file:font-medium file:text-ey-yellow hover:file:bg-ey-yellow/20"
                />
              </div>
            </div>

            <div className="mt-4">
              <button
                onClick={handleImport}
                disabled={!selectedTargetId || !selectedBenchmarkId || !importFile || importing}
                className="inline-flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                {importing ? 'Importing...' : 'Import Results'}
              </button>
              {!selectedTargetId && importFile && (
                <p className="mt-2 text-xs text-amber-400">
                  Please select a Target and Benchmark above to enable import.
                </p>
              )}
              {importResult && (
                <div className="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-400">
                  <p className="font-medium">Import successful!</p>
                  <p>Findings created: {importResult.findings_created} | Passed: {importResult.passed} | Failed: {importResult.failed} | Errors: {importResult.errors}</p>
                  <p>Compliance: {importResult.compliance_percentage}%</p>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* ════════════════════════════════ SCAN HISTORY (always visible) ════════════════════════════════ */}
      <div className="rounded-xl border border-dark-border bg-dark-card">
        <div className="border-b border-dark-border px-5 py-3">
          <h3 className="text-sm font-semibold text-white uppercase tracking-wider">Scan History</h3>
        </div>
        {scans.length === 0 ? (
          <div className="p-8 text-center text-sm text-dark-muted">No scans yet for this mission.</div>
        ) : (
          <table className="min-w-full divide-y divide-dark-border">
            <thead className="bg-dark-elevated">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-dark-muted">ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-dark-muted">Target</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-dark-muted">Benchmark</th>
                <th className="px-4 py-3 text-center text-xs font-medium uppercase text-dark-muted">Status</th>
                <th className="px-4 py-3 text-center text-xs font-medium uppercase text-dark-muted">Compliance</th>
                <th className="px-4 py-3 text-center text-xs font-medium uppercase text-dark-muted">Pass/Fail</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-dark-muted">Date</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase text-dark-muted">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-dark-border">
              {scans.map(s => (
                <tr key={s.id} className="hover:bg-dark-elevated/30">
                  <td className="px-4 py-3 text-sm text-dark-muted">#{s.id}</td>
                  <td className="px-4 py-3 text-sm text-white">{s.target_hostname || s.target_ip || `Target #${s.target_id}`}</td>
                  <td className="px-4 py-3 text-sm text-dark-secondary">{s.benchmark_name || `Benchmark #${s.benchmark_id}`}</td>
                  <td className="px-4 py-3 text-center">{scanStatusBadge(s.status)}</td>
                  <td className="px-4 py-3 text-center">
                    {s.compliance_percentage !== null ? (
                      <span className={`text-sm font-medium ${(s.compliance_percentage || 0) >= 80 ? 'text-emerald-400' : (s.compliance_percentage || 0) >= 50 ? 'text-amber-400' : 'text-red-400'}`}>
                        {s.compliance_percentage?.toFixed(1)}%
                      </span>
                    ) : '—'}
                  </td>
                  <td className="px-4 py-3 text-center text-xs text-dark-muted">
                    <span className="text-emerald-400">{s.passed}</span> / <span className="text-red-400">{s.failed}</span> / <span className="text-amber-400">{s.errors}</span>
                  </td>
                  <td className="px-4 py-3 text-sm text-dark-muted">{s.started_at ? new Date(s.started_at).toLocaleDateString() : s.created_at ? new Date(s.created_at).toLocaleDateString() : '—'}</td>
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => handleDeleteScan(s.id)} className="rounded p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400" title="Delete scan">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
