import { useState, useEffect, useMemo, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X, Wrench, ChevronDown, Download, Wifi, HardDrive, Radio, FileDown, CheckCircle2, XCircle, SkipForward, Loader2, AlertTriangle, Shield, Search, Filter, Brain } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { Target, ScanDetail, RemediationSession, RemediationItem, ScanIntelligence } from '@/types';
import * as api from '@/services/api';

// ── Badge helpers ────────────────────────────────────────────────────

const severityColor: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  low: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
};

const statusIcon: Record<string, React.ReactNode> = {
  success: <CheckCircle2 className="w-4 h-4 text-emerald-400" />,
  failed: <XCircle className="w-4 h-4 text-red-400" />,
  skipped: <SkipForward className="w-4 h-4 text-zinc-400" />,
  pending: <div className="w-4 h-4 rounded-full border-2 border-zinc-500" />,
  executing: <Loader2 className="w-4 h-4 text-yellow-400 animate-spin" />,
};

const sourceColors: Record<string, string> = {
  benchmark: 'bg-blue-500/20 text-blue-400',
  cis_text: 'bg-amber-500/20 text-amber-400',
  auditor_edit: 'bg-purple-500/20 text-purple-400',
};

// ── Main Panel ───────────────────────────────────────────────────────

interface ResolvePanelProps {
  target: Target;
  missionId: number;
  scans: ScanDetail[];
  onClose: () => void;
}

export default function ResolvePanel({ target, missionId, scans, onClose }: ResolvePanelProps) {
  const [session, setSession] = useState<RemediationSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedScanIds, setSelectedScanIds] = useState<number[]>([]);
  const [intel, setIntel] = useState<ScanIntelligence | null>(null);
  const [intelLoading, setIntelLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'workspace' | 'execute' | 'results'>('workspace');
  const [searchTerm, setSearchTerm] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');
  const [executing, setExecuting] = useState(false);
  const [privilegeWarning, setPrivilegeWarning] = useState<any>(null);
  const [pollKey, setPollKey] = useState(0);

  // Completed scans for this target
  const targetScans = useMemo(
    () => scans.filter(s => s.target_id === target.id && (s.status === 'completed' || s.status === 'imported')),
    [scans, target.id]
  );

  // Auto-select latest scan
  useEffect(() => {
    if (targetScans.length > 0 && selectedScanIds.length === 0) {
      setSelectedScanIds([targetScans[0].id]);
    }
  }, [targetScans]);

  // Fetch intelligence when multiple scans selected
  useEffect(() => {
    if (selectedScanIds.length >= 2) {
      setIntelLoading(true);
      api.getScanIntelligence(target.id, selectedScanIds)
        .then((d: ScanIntelligence) => setIntel(d))
        .catch(() => {})
        .finally(() => setIntelLoading(false));
    } else {
      setIntel(null);
    }
  }, [selectedScanIds, target.id]);

  // Check for existing session
  useEffect(() => {
    api.getTargetResolveSessions(target.id, missionId)
      .then((sessions: any[]) => {
        if (sessions.length > 0) {
          // Load the latest session
          api.getResolveSession(sessions[0].id).then(setSession);
        }
      })
      .catch(() => {});
  }, [target.id, missionId, pollKey]);

  // Poll for execution progress
  useEffect(() => {
    if (!session || session.status !== 'executing') return;
    const iv = setInterval(() => {
      api.getResolveSession(session.id).then(s => {
        setSession(s);
        if (s.status !== 'executing') {
          setExecuting(false);
          setActiveTab('results');
        }
      });
    }, 2000);
    return () => clearInterval(iv);
  }, [session?.id, session?.status]);

  const handleCreateSession = async () => {
    if (selectedScanIds.length === 0) return;
    setLoading(true);
    setError('');
    try {
      const s = await api.createResolveSession(missionId, target.id, selectedScanIds);
      setSession(s);
      setActiveTab('workspace');
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to create session');
    } finally {
      setLoading(false);
    }
  };

  const handleToggleItem = async (item: RemediationItem) => {
    if (!session) return;
    try {
      const updated = await api.updateResolveItem(item.id, { selected: !item.selected });
      setSession(prev => prev ? {
        ...prev,
        items: prev.items.map(i => i.id === item.id ? updated : i),
      } : null);
    } catch {}
  };

  const handleBulkSelect = async (selected: boolean) => {
    if (!session) return;
    const ids = session.items.map(i => i.id);
    await api.bulkSelectResolveItems(session.id, ids, selected);
    setSession(prev => prev ? {
      ...prev,
      items: prev.items.map(i => ({ ...i, selected })),
    } : null);
  };

  const handleExport = async () => {
    if (!session) return;
    try {
      const blob = await api.exportResolveScript(session.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `resolve_${session.id}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      setPollKey(k => k + 1);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Export failed');
    }
  };

  const handleExecuteNetwork = async (confirmPrivilege = false) => {
    if (!session) return;
    setExecuting(true);
    setPrivilegeWarning(null);
    try {
      const res = await api.executeResolveNetwork(session.id, confirmPrivilege);
      if (res.warning === 'privilege_required') {
        setPrivilegeWarning(res);
        setExecuting(false);
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Execution failed');
      setExecuting(false);
    }
  };

  const handleExportCsv = async () => {
    if (!session) return;
    const blob = await api.exportResolveResultsCsv(session.id);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `resolve_${session.id}_results.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleEditCommand = async (item: RemediationItem, newCmd: string) => {
    const updated = await api.updateResolveItem(item.id, { remediation_command: newCmd });
    setSession(prev => prev ? {
      ...prev,
      items: prev.items.map(i => i.id === item.id ? updated : i),
    } : null);
  };

  // Filter items
  const filteredItems = useMemo(() => {
    if (!session) return [];
    return session.items.filter(item => {
      if (searchTerm && !item.rule_title.toLowerCase().includes(searchTerm.toLowerCase())
          && !item.section_number.toLowerCase().includes(searchTerm.toLowerCase())) return false;
      if (severityFilter && item.severity !== severityFilter) return false;
      return true;
    });
  }, [session?.items, searchTerm, severityFilter]);

  const selectedCount = session?.items.filter(i => i.selected).length || 0;
  const totalCount = session?.items.length || 0;

  return createPortal(
    <div className="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="w-full max-w-6xl h-[90vh] bg-dark-card rounded-2xl border border-dark-border shadow-2xl flex flex-col overflow-hidden"
           onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-dark-border shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/20 flex items-center justify-center">
              <Wrench className="w-5 h-5 text-emerald-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Forge Resolve</h2>
              <p className="text-sm text-dark-muted">{target.hostname || target.ip_address} — {target.target_type}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg hover:bg-dark-elevated text-dark-muted hover:text-white transition">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">

          {/* Scan Selection */}
          {!session && (
            <div className="space-y-4">
              <h3 className="text-white font-semibold flex items-center gap-2">
                <Shield className="w-4 h-4 text-emerald-400" /> Select Scans
              </h3>
              <div className="grid gap-2">
                {targetScans.map(scan => (
                  <label key={scan.id}
                    className={cn(
                      "flex items-center gap-3 px-4 py-3 rounded-xl border cursor-pointer transition",
                      selectedScanIds.includes(scan.id)
                        ? "border-emerald-500/50 bg-emerald-500/10"
                        : "border-dark-border bg-dark-elevated hover:border-zinc-600",
                    )}>
                    <input type="checkbox"
                      checked={selectedScanIds.includes(scan.id)}
                      onChange={() => setSelectedScanIds(prev =>
                        prev.includes(scan.id)
                          ? prev.filter(id => id !== scan.id)
                          : [...prev, scan.id]
                      )}
                      className="accent-emerald-500"
                    />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm text-white font-medium">Scan #{scan.id}</span>
                      <span className="text-xs text-dark-muted ml-2">
                        {scan.passed}P / {scan.failed}F / {scan.errors}E
                        {scan.compliance_percentage != null && ` — ${scan.compliance_percentage.toFixed(1)}%`}
                      </span>
                    </div>
                    <span className="text-xs text-dark-muted">
                      {scan.completed_at ? new Date(scan.completed_at).toLocaleDateString() : '—'}
                    </span>
                  </label>
                ))}
              </div>

              {/* Intelligence Preview */}
              {intel && (
                <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4 space-y-3">
                  <h4 className="text-sm font-semibold text-emerald-400 flex items-center gap-2">
                    <Brain className="w-4 h-4" /> Scan Intelligence — {selectedScanIds.length} scans compared
                  </h4>
                  <div className="grid grid-cols-4 gap-3 text-center">
                    <div className="px-3 py-2 rounded-lg bg-emerald-500/10">
                      <div className="text-lg font-bold text-emerald-400">{intel.rules_improved}</div>
                      <div className="text-xs text-dark-muted">Improved</div>
                    </div>
                    <div className="px-3 py-2 rounded-lg bg-red-500/10">
                      <div className="text-lg font-bold text-red-400">{intel.rules_regressed}</div>
                      <div className="text-xs text-dark-muted">Regressed</div>
                    </div>
                    <div className="px-3 py-2 rounded-lg bg-zinc-500/10">
                      <div className="text-lg font-bold text-zinc-400">{intel.rules_unchanged}</div>
                      <div className="text-xs text-dark-muted">Unchanged</div>
                    </div>
                    <div className="px-3 py-2 rounded-lg bg-blue-500/10">
                      <div className="text-lg font-bold text-blue-400">{intel.rules_new + intel.rules_removed}</div>
                      <div className="text-xs text-dark-muted">New/Removed</div>
                    </div>
                  </div>
                  {intel.time_intervals.length > 0 && (
                    <p className="text-xs text-dark-muted">Interval: {intel.time_intervals.join(' → ')}</p>
                  )}
                  {intel.ai_insights && (
                    <div className="mt-2 space-y-2">
                      <div className="flex items-center gap-2">
                        <span className={cn(
                          "text-xs px-2 py-0.5 rounded-full font-medium",
                          intel.ai_insights.risk_trajectory === 'improving' ? 'bg-emerald-500/20 text-emerald-400' :
                          intel.ai_insights.risk_trajectory === 'declining' ? 'bg-red-500/20 text-red-400' :
                          'bg-yellow-500/20 text-yellow-400'
                        )}>
                          {intel.ai_insights.risk_trajectory}
                        </span>
                      </div>
                      <p className="text-sm text-dark-secondary">{intel.ai_insights.summary}</p>
                      {intel.ai_insights.patterns.length > 0 && (
                        <ul className="text-xs text-dark-muted space-y-1">
                          {intel.ai_insights.patterns.map((p, i) => (
                            <li key={i} className="flex items-start gap-1.5">
                              <span className="text-emerald-400 mt-0.5">•</span> {p}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              )}
              {intelLoading && (
                <div className="flex items-center gap-2 text-sm text-dark-muted">
                  <Loader2 className="w-4 h-4 animate-spin" /> Analyzing scan delta...
                </div>
              )}

              {error && <p className="text-sm text-red-400">{error}</p>}

              <button onClick={handleCreateSession} disabled={loading || selectedScanIds.length === 0}
                className="px-6 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-medium disabled:opacity-50 transition flex items-center gap-2">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wrench className="w-4 h-4" />}
                Start Resolve Session
              </button>
            </div>
          )}

          {/* Session Active */}
          {session && (
            <>
              {/* Tab bar */}
              <div className="flex gap-1 bg-dark-elevated rounded-xl p-1">
                {(['workspace', 'execute', 'results'] as const).map(tab => (
                  <button key={tab} onClick={() => setActiveTab(tab)}
                    className={cn(
                      "flex-1 px-4 py-2 rounded-lg text-sm font-medium transition",
                      activeTab === tab ? "bg-emerald-600 text-white" : "text-dark-muted hover:text-white"
                    )}>
                    {tab === 'workspace' ? `Workspace (${selectedCount}/${totalCount})` :
                     tab === 'execute' ? 'Execute' : 'Results'}
                  </button>
                ))}
              </div>

              {/* Workspace Tab */}
              {activeTab === 'workspace' && (
                <div className="space-y-4">
                  {/* Toolbar */}
                  <div className="flex items-center gap-3 flex-wrap">
                    <div className="relative flex-1 min-w-[200px]">
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-dark-muted" />
                      <input value={searchTerm} onChange={e => setSearchTerm(e.target.value)}
                        placeholder="Search rules..."
                        className="w-full pl-10 pr-3 py-2 rounded-lg bg-dark-elevated border border-dark-border text-sm text-white placeholder:text-dark-muted" />
                    </div>
                    <select value={severityFilter} onChange={e => setSeverityFilter(e.target.value)}
                      className="px-3 py-2 rounded-lg bg-dark-elevated border border-dark-border text-sm text-white">
                      <option value="">All Severities</option>
                      <option value="critical">Critical</option>
                      <option value="high">High</option>
                      <option value="medium">Medium</option>
                      <option value="low">Low</option>
                    </select>
                    <button onClick={() => handleBulkSelect(true)}
                      className="px-3 py-2 rounded-lg bg-emerald-600/20 text-emerald-400 text-sm hover:bg-emerald-600/30 transition">
                      Select All
                    </button>
                    <button onClick={() => handleBulkSelect(false)}
                      className="px-3 py-2 rounded-lg bg-zinc-600/20 text-zinc-400 text-sm hover:bg-zinc-600/30 transition">
                      Deselect All
                    </button>
                  </div>

                  {/* Items list */}
                  <div className="space-y-2">
                    {filteredItems.map(item => (
                      <RemediationItemCard key={item.id} item={item}
                        onToggle={() => handleToggleItem(item)}
                        onEditCommand={(cmd) => handleEditCommand(item, cmd)}
                        disabled={session.status === 'executing' || session.status === 'completed'}
                      />
                    ))}
                    {filteredItems.length === 0 && (
                      <p className="text-center text-dark-muted py-8">No items match your filters</p>
                    )}
                  </div>
                </div>
              )}

              {/* Execute Tab */}
              {activeTab === 'execute' && (
                <div className="space-y-6">
                  <div className="text-sm text-dark-secondary">
                    {selectedCount} of {totalCount} rules selected for remediation
                  </div>

                  {/* Privilege Warning */}
                  {privilegeWarning && (
                    <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 space-y-3">
                      <div className="flex items-center gap-2 text-amber-400 font-medium">
                        <AlertTriangle className="w-5 h-5" /> Privilege Warning
                      </div>
                      <p className="text-sm text-dark-secondary">{privilegeWarning.message}</p>
                      <div className="max-h-40 overflow-y-auto space-y-1">
                        {privilegeWarning.privileged_commands?.map((c: any) => (
                          <div key={c.id} className="text-xs text-dark-muted font-mono truncate">
                            {c.section}: {c.command}
                          </div>
                        ))}
                      </div>
                      <button onClick={() => handleExecuteNetwork(true)}
                        className="px-4 py-2 rounded-lg bg-amber-600 text-white text-sm font-medium hover:bg-amber-500 transition">
                        I understand, proceed
                      </button>
                    </div>
                  )}

                  {/* 3 Method cards */}
                  <div className="grid gap-4">
                    {/* Air-Gapped */}
                    <div className="rounded-xl border border-dark-border bg-dark-elevated p-5 space-y-3">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center">
                          <HardDrive className="w-5 h-5 text-blue-400" />
                        </div>
                        <div>
                          <h4 className="font-semibold text-white">Air-Gapped Export</h4>
                          <p className="text-xs text-dark-muted">Download remediation script ZIP for offline execution</p>
                        </div>
                      </div>
                      <button onClick={handleExport} disabled={selectedCount === 0}
                        className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 disabled:opacity-50 transition flex items-center gap-2">
                        <Download className="w-4 h-4" /> Generate Script ZIP
                      </button>
                    </div>

                    {/* Network Live */}
                    <div className="rounded-xl border border-dark-border bg-dark-elevated p-5 space-y-3">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg bg-emerald-500/20 flex items-center justify-center">
                          <Wifi className="w-5 h-5 text-emerald-400" />
                        </div>
                        <div>
                          <h4 className="font-semibold text-white">Network Live</h4>
                          <p className="text-xs text-dark-muted">Execute directly via SSH/WinRM/SQL. Requires network access.</p>
                        </div>
                      </div>
                      <button onClick={() => handleExecuteNetwork(false)}
                        disabled={selectedCount === 0 || executing}
                        className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-500 disabled:opacity-50 transition flex items-center gap-2">
                        {executing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wifi className="w-4 h-4" />}
                        Execute Live
                      </button>
                    </div>

                    {/* WebSocket Agent */}
                    <div className="rounded-xl border border-dark-border bg-dark-elevated p-5 space-y-3">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg bg-purple-500/20 flex items-center justify-center">
                          <Radio className="w-5 h-5 text-purple-400" />
                        </div>
                        <div>
                          <h4 className="font-semibold text-white">WebSocket Agent</h4>
                          <p className="text-xs text-dark-muted">Dispatch to a connected Forge Connect agent on the target</p>
                        </div>
                      </div>
                      <button disabled
                        className="px-4 py-2 rounded-lg bg-purple-600 text-white text-sm font-medium disabled:opacity-50 transition flex items-center gap-2">
                        <Radio className="w-4 h-4" /> Execute via Agent
                      </button>
                      <p className="text-xs text-dark-muted">Select a connected agent from the Forge Connect panel first</p>
                    </div>
                  </div>

                  {error && <p className="text-sm text-red-400">{error}</p>}
                </div>
              )}

              {/* Results Tab */}
              {activeTab === 'results' && (
                <div className="space-y-4">
                  {/* Summary */}
                  {session.status !== 'draft' && (
                    <div className="grid grid-cols-4 gap-3 text-center">
                      <div className="px-3 py-3 rounded-xl bg-dark-elevated border border-dark-border">
                        <div className="text-2xl font-bold text-white">{session.total_items}</div>
                        <div className="text-xs text-dark-muted">Total</div>
                      </div>
                      <div className="px-3 py-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
                        <div className="text-2xl font-bold text-emerald-400">{session.succeeded_items}</div>
                        <div className="text-xs text-dark-muted">Succeeded</div>
                      </div>
                      <div className="px-3 py-3 rounded-xl bg-red-500/10 border border-red-500/20">
                        <div className="text-2xl font-bold text-red-400">{session.failed_items}</div>
                        <div className="text-xs text-dark-muted">Failed</div>
                      </div>
                      <div className="px-3 py-3 rounded-xl bg-zinc-500/10 border border-zinc-500/20">
                        <div className="text-2xl font-bold text-zinc-400">{session.skipped_items}</div>
                        <div className="text-xs text-dark-muted">Skipped</div>
                      </div>
                    </div>
                  )}

                  {/* Export button */}
                  {session.status !== 'draft' && (
                    <button onClick={handleExportCsv}
                      className="px-4 py-2 rounded-lg bg-dark-elevated border border-dark-border text-sm text-dark-secondary hover:text-white transition flex items-center gap-2">
                      <FileDown className="w-4 h-4" /> Export Results CSV
                    </button>
                  )}

                  {/* Items with results */}
                  <div className="space-y-2">
                    {session.items.map(item => (
                      <div key={item.id} className="rounded-xl border border-dark-border bg-dark-elevated p-4">
                        <div className="flex items-center gap-3">
                          {statusIcon[item.status] || statusIcon.pending}
                          <span className="text-sm font-mono text-dark-muted w-16 shrink-0">{item.section_number}</span>
                          <span className="text-sm text-white flex-1 truncate">{item.rule_title}</span>
                          <span className={cn("text-xs px-2 py-0.5 rounded-full border", severityColor[item.severity || 'medium'])}>
                            {item.severity}
                          </span>
                          <span className="text-xs text-dark-muted capitalize">{item.status}</span>
                        </div>
                        {(item.execution_output || item.execution_error) && (
                          <div className="mt-2 space-y-1">
                            {item.execution_output && (
                              <pre className="text-xs text-emerald-400/80 bg-black/30 rounded-lg p-2 overflow-x-auto max-h-24">
                                {item.execution_output}
                              </pre>
                            )}
                            {item.execution_error && (
                              <pre className="text-xs text-red-400/80 bg-black/30 rounded-lg p-2 overflow-x-auto max-h-24">
                                {item.execution_error}
                              </pre>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  {session.status === 'draft' && (
                    <p className="text-center text-dark-muted py-8">No execution results yet. Use the Execute tab to run remediation.</p>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}


// ── Item Card ────────────────────────────────────────────────────────

function RemediationItemCard({
  item, onToggle, onEditCommand, disabled,
}: {
  item: RemediationItem;
  onToggle: () => void;
  onEditCommand: (cmd: string) => void;
  disabled: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(item.remediation_command || '');
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={cn(
      "rounded-xl border p-4 transition",
      item.selected ? "border-emerald-500/30 bg-emerald-500/5" : "border-dark-border bg-dark-elevated",
    )}>
      <div className="flex items-start gap-3">
        {/* Checkbox */}
        <input type="checkbox" checked={item.selected} onChange={onToggle} disabled={disabled}
          className="mt-1 accent-emerald-500 shrink-0" />

        {/* Content */}
        <div className="flex-1 min-w-0 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-mono text-dark-muted">{item.section_number}</span>
            <span className="text-sm text-white font-medium">{item.rule_title}</span>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <span className={cn("text-xs px-2 py-0.5 rounded-full border", severityColor[item.severity || 'medium'])}>
              {item.severity}
            </span>
            <span className={cn("text-xs px-2 py-0.5 rounded-full", sourceColors[item.command_source])}>
              {item.command_source === 'benchmark' ? 'Benchmark' :
               item.command_source === 'cis_text' ? 'CIS Text Only' : 'Edited'}
            </span>
            {item.requires_privilege && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" /> Privilege
              </span>
            )}
            {item.command_transport && (
              <span className="text-xs text-dark-muted">{item.command_transport}</span>
            )}
          </div>

          {/* Command */}
          {item.remediation_command && (
            <div className="relative">
              <button onClick={() => setExpanded(!expanded)}
                className="w-full text-left">
                <pre className={cn(
                  "text-xs font-mono p-2 rounded-lg bg-black/40 text-emerald-300 overflow-hidden transition-all",
                  expanded ? "max-h-none" : "max-h-8",
                )}>
                  {item.remediation_command}
                </pre>
              </button>
              {!disabled && !editing && (
                <button onClick={() => { setEditing(true); setEditValue(item.remediation_command || ''); }}
                  className="absolute top-1 right-1 text-xs text-dark-muted hover:text-white px-1.5 py-0.5 rounded bg-dark-elevated/80">
                  Edit
                </button>
              )}
            </div>
          )}
          {!item.remediation_command && item.command_source === 'cis_text' && (
            <div className="text-xs text-amber-400/80 italic">No executable command — CIS reference text only</div>
          )}

          {/* Edit mode */}
          {editing && (
            <div className="space-y-2">
              <textarea value={editValue} onChange={e => setEditValue(e.target.value)}
                className="w-full h-20 text-xs font-mono p-2 rounded-lg bg-black/40 text-emerald-300 border border-emerald-500/30 resize-none" />
              <div className="flex gap-2">
                <button onClick={() => { onEditCommand(editValue); setEditing(false); }}
                  className="px-3 py-1 text-xs rounded-lg bg-emerald-600 text-white hover:bg-emerald-500">Save</button>
                <button onClick={() => setEditing(false)}
                  className="px-3 py-1 text-xs rounded-lg bg-dark-elevated text-dark-muted hover:text-white">Cancel</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
