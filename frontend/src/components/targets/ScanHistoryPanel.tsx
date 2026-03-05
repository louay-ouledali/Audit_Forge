import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  ChevronDown,
  ChevronRight,
  History,
  Wifi,
  Upload,
  Monitor,
  Terminal,
  Network,
  Database,
  HelpCircle,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Loader2,
  ExternalLink,
  Trash2,
  Package,
  Search,
  X,
} from 'lucide-react';
import type { ScanDetail, Target } from '@/types';
import * as api from '@/services/api';
import ConfirmDialog from '@/components/common/ConfirmDialog';

/* ── Platform icon lookup ─────────────────────────────────────── */
const PLATFORM_ICON: Record<string, { icon: typeof Monitor; color: string }> = {
  windows:    { icon: Monitor,  color: 'text-sky-400' },
  linux:      { icon: Terminal,  color: 'text-emerald-400' },
  cisco_ios:  { icon: Network,  color: 'text-purple-400' },
  juniper:    { icon: Network,  color: 'text-purple-400' },
  fortinet:   { icon: Network,  color: 'text-purple-400' },
  palo_alto:  { icon: Network,  color: 'text-purple-400' },
  arista:     { icon: Network,  color: 'text-purple-400' },
  hp_procurve:{ icon: Network,  color: 'text-purple-400' },
  postgresql: { icon: Database,  color: 'text-orange-400' },
  mssql:      { icon: Database,  color: 'text-orange-400' },
  oracle:     { icon: Database,  color: 'text-orange-400' },
};
const DEFAULT_ICON = { icon: HelpCircle, color: 'text-dark-muted' };

function getTargetIcon(targets: Target[], targetId: number) {
  const t = targets.find(x => x.id === targetId);
  if (!t) return DEFAULT_ICON;
  return PLATFORM_ICON[(t.target_type || '').toLowerCase()] || DEFAULT_ICON;
}

/* ── Helpers ──────────────────────────────────────────────────── */
function formatDuration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt || !completedAt) return '—';
  const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime();
  if (ms < 1000) return `${ms}ms`;
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  return `${mins}m ${remSecs}s`;
}

function statusBadge(status: string) {
  switch (status) {
    case 'completed':
      return { icon: CheckCircle2, text: 'Completed', cls: 'text-emerald-400 bg-emerald-500/10' };
    case 'running':
    case 'in_progress':
      return { icon: Loader2, text: 'Running', cls: 'text-ey-yellow bg-ey-yellow/10 animate-pulse' };
    case 'failed':
    case 'error':
      return { icon: XCircle, text: 'Failed', cls: 'text-red-400 bg-red-500/10' };
    case 'cancelled':
      return { icon: AlertTriangle, text: 'Cancelled', cls: 'text-amber-400 bg-amber-500/10' };
    default:
      return { icon: Clock, text: status, cls: 'text-dark-muted bg-dark-elevated' };
  }
}

function complianceColor(pct: number | null): string {
  if (pct == null) return 'text-dark-muted';
  if (pct >= 80) return 'text-emerald-400';
  if (pct >= 50) return 'text-amber-400';
  return 'text-red-400';
}

const PAGE_SIZE = 10;

/* ── Props ────────────────────────────────────────────────────── */
interface Props {
  missionId: number;
  targets: Target[];
  onViewFindings: (scanId: number) => void;
  onImportResults: (target: Target) => void;
  refreshKey?: number; // increment to trigger reload
}

export default function ScanHistoryPanel({
  missionId,
  targets,
  onViewFindings,
  onImportResults,
  refreshKey = 0,
}: Props) {
  const [expanded, setExpanded] = useState(true);
  const [scans, setScans] = useState<ScanDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [deletingScanId, setDeletingScanId] = useState<number | null>(null);

  const loadScans = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await api.getScans({ mission_id: missionId });
      setScans(resp.data);
      setTotal(resp.total);
    } catch {
      // Silently fail — panel is supplementary
    } finally {
      setLoading(false);
    }
  }, [missionId]);

  // Load on mount (expanded by default) and when refreshKey changes
  useEffect(() => {
    if (expanded) loadScans();
  }, [expanded, refreshKey, loadScans]);

  // Client-side filtering
  const filteredScans = useMemo(() => {
    let result = scans;
    if (statusFilter) {
      result = result.filter(s => s.status === statusFilter);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(s =>
        (s.target_hostname || '').toLowerCase().includes(q) ||
        (s.target_ip || '').toLowerCase().includes(q) ||
        (s.benchmark_name || '').toLowerCase().includes(q) ||
        (s.scan_mode || '').toLowerCase().includes(q)
      );
    }
    return result;
  }, [scans, searchQuery, statusFilter]);

  const visibleScans = filteredScans.slice(0, visibleCount);
  const hasMore = visibleCount < filteredScans.length;

  const handleDelete = async () => {
    if (deletingScanId == null) return;
    try {
      await api.deleteScan(deletingScanId);
      await loadScans();
    } catch {
      // ignore
    } finally {
      setDeletingScanId(null);
    }
  };

  const uniqueStatuses = useMemo(() => {
    const set = new Set(scans.map(s => s.status));
    return Array.from(set).sort();
  }, [scans]);

  return (
    <div className="rounded-xl border border-dark-border bg-dark-card overflow-hidden">
      {/* Collapsible header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-5 py-4 text-left hover:bg-dark-elevated/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          <History className="h-5 w-5 text-dark-muted" />
          <span className="text-sm font-semibold text-white">Scan History</span>
          {total > 0 && (
            <span className="rounded-full bg-dark-elevated border border-dark-border px-2 py-0.5 text-[11px] font-bold text-dark-secondary">
              {total} scan{total !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {loading && <Loader2 className="h-4 w-4 animate-spin text-dark-muted" />}
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-dark-muted" />
          ) : (
            <ChevronRight className="h-4 w-4 text-dark-muted" />
          )}
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t border-dark-border">
          {/* Search + Status filter bar */}
          {scans.length > 0 && (
            <div className="flex flex-col sm:flex-row gap-2 px-4 py-3 border-b border-dark-border/50">
              <div className="relative flex-1">
                <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-dark-muted" />
                <input
                  type="text"
                  placeholder="Search scans..."
                  value={searchQuery}
                  onChange={(e) => { setSearchQuery(e.target.value); setVisibleCount(PAGE_SIZE); }}
                  className="w-full rounded-lg border border-dark-border bg-dark-elevated py-1.5 pl-8 pr-8 text-xs text-white placeholder-dark-muted focus:border-ey-yellow/30 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20"
                />
                {searchQuery && (
                  <button onClick={() => setSearchQuery('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-dark-muted hover:text-white">
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
              <select
                value={statusFilter}
                onChange={(e) => { setStatusFilter(e.target.value); setVisibleCount(PAGE_SIZE); }}
                className="rounded-lg border border-dark-border bg-dark-elevated px-2.5 py-1.5 text-xs text-white focus:border-ey-yellow/30 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20"
              >
                <option value="">All statuses</option>
                {uniqueStatuses.map(s => (
                  <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1).replace('_', ' ')}</option>
                ))}
              </select>
            </div>
          )}

          {filteredScans.length === 0 && !loading ? (
            <div className="px-5 py-8 text-center">
              <History className="mx-auto h-8 w-8 text-dark-muted" />
              <p className="mt-2 text-sm text-dark-secondary">
                {scans.length === 0 ? 'No scans yet for this mission.' : 'No scans match your filters.'}
              </p>
              {scans.length === 0 && (
                <p className="mt-1 text-xs text-dark-muted">Run a scan or import results to get started.</p>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-dark-border/50 text-dark-muted">
                    <th className="px-4 py-2.5 text-left font-semibold">Target</th>
                    <th className="px-4 py-2.5 text-left font-semibold">Benchmark</th>
                    <th className="px-4 py-2.5 text-center font-semibold">Mode</th>
                    <th className="px-4 py-2.5 text-center font-semibold">Status</th>
                    <th className="px-4 py-2.5 text-center font-semibold">Rules</th>
                    <th className="px-4 py-2.5 text-center font-semibold">Pass / Fail</th>
                    <th className="px-4 py-2.5 text-center font-semibold">Compliance</th>
                    <th className="px-4 py-2.5 text-center font-semibold">Duration</th>
                    <th className="px-4 py-2.5 text-left font-semibold">Date</th>
                    <th className="px-4 py-2.5 text-center font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleScans.map(s => {
                    const tIcon = getTargetIcon(targets, s.target_id);
                    const TargetIcon = tIcon.icon;
                    const badge = statusBadge(s.status);
                    const StatusIcon = badge.icon;
                    const isImport = s.scan_mode === 'import';

                    return (
                      <tr
                        key={s.id}
                        className="border-b border-dark-border/30 hover:bg-dark-elevated/20 transition-colors"
                      >
                        {/* Target */}
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-2">
                            <TargetIcon className={`h-3.5 w-3.5 ${tIcon.color} shrink-0`} />
                            <span className="text-white font-medium truncate max-w-[140px]">
                              {s.target_hostname || s.target_ip || `#${s.target_id}`}
                            </span>
                          </div>
                        </td>

                        {/* Benchmark */}
                        <td className="px-4 py-2.5">
                          <span className="text-dark-secondary truncate max-w-[180px] block">
                            {s.benchmark_name
                              ? `${s.benchmark_name}${s.benchmark_version ? ` v${s.benchmark_version}` : ''}`
                              : `Benchmark #${s.benchmark_id}`}
                          </span>
                        </td>

                        {/* Mode */}
                        <td className="px-4 py-2.5 text-center">
                          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                            isImport ? 'bg-purple-500/10 text-purple-400' : 'bg-sky-500/10 text-sky-400'
                          }`}>
                            {isImport ? <><Package className="h-3 w-3" /> USB</> : <><Wifi className="h-3 w-3" /> Net</>}
                          </span>
                        </td>

                        {/* Status */}
                        <td className="px-4 py-2.5 text-center">
                          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold ${badge.cls}`}>
                            <StatusIcon className={`h-3 w-3 ${s.status === 'running' || s.status === 'in_progress' ? 'animate-spin' : ''}`} />
                            {badge.text}
                          </span>
                        </td>

                        {/* Rules */}
                        <td className="px-4 py-2.5 text-center text-dark-secondary font-mono">
                          {s.total_rules_checked || '—'}
                        </td>

                        {/* Pass / Fail */}
                        <td className="px-4 py-2.5 text-center">
                          <span className="text-emerald-400 font-mono">{s.passed}</span>
                          <span className="text-dark-muted mx-1">/</span>
                          <span className="text-red-400 font-mono">{s.failed}</span>
                          {s.errors > 0 && (
                            <span className="text-amber-400 font-mono ml-1">({s.errors}e)</span>
                          )}
                        </td>

                        {/* Compliance */}
                        <td className="px-4 py-2.5 text-center">
                          <span className={`font-bold font-mono ${complianceColor(s.compliance_percentage)}`}>
                            {s.compliance_percentage != null ? `${s.compliance_percentage.toFixed(1)}%` : '—'}
                          </span>
                        </td>

                        {/* Duration */}
                        <td className="px-4 py-2.5 text-center text-dark-muted font-mono">
                          {formatDuration(s.started_at, s.completed_at)}
                        </td>

                        {/* Date */}
                        <td className="px-4 py-2.5 text-dark-muted whitespace-nowrap">
                          {s.started_at ? new Date(s.started_at).toLocaleDateString() : s.created_at ? new Date(s.created_at).toLocaleDateString() : '—'}
                          {s.started_at && (
                            <span className="ml-1 text-dark-muted/60">
                              {new Date(s.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </span>
                          )}
                        </td>

                        {/* Actions */}
                        <td className="px-4 py-2.5 text-center">
                          <div className="flex items-center justify-center gap-1">
                            {(s.status === 'completed') && (
                              <button
                                onClick={() => onViewFindings(s.id)}
                                className="rounded-md p-1.5 text-dark-muted hover:text-ey-yellow hover:bg-ey-yellow/10 transition-colors"
                                title="View findings"
                              >
                                <ExternalLink className="h-3.5 w-3.5" />
                              </button>
                            )}
                            <button
                              onClick={() => setDeletingScanId(s.id)}
                              className="rounded-md p-1.5 text-dark-muted hover:text-red-400 hover:bg-red-500/10 transition-colors"
                              title="Delete scan"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Load more + footer */}
          {filteredScans.length > 0 && (
            <div className="flex items-center justify-between px-5 py-3 border-t border-dark-border/50">
              <span className="text-[11px] text-dark-muted">
                Showing {visibleScans.length} of {filteredScans.length} scan{filteredScans.length !== 1 ? 's' : ''}
                {filteredScans.filter(s => s.status === 'completed').length > 0 && (
                  <> · {filteredScans.filter(s => s.status === 'completed').length} completed</>
                )}
              </span>
              <div className="flex items-center gap-3">
                {hasMore && (
                  <button
                    onClick={() => setVisibleCount(prev => prev + PAGE_SIZE)}
                    className="text-[11px] text-ey-yellow hover:text-ey-yellow-hover transition-colors font-medium"
                  >
                    Load more ({filteredScans.length - visibleCount} remaining)
                  </button>
                )}
                <button
                  onClick={() => {
                    const t = targets.find(x => !!x.default_benchmark_id);
                    if (t) onImportResults(t);
                  }}
                  className="inline-flex items-center gap-1.5 text-[11px] text-dark-secondary hover:text-ey-yellow transition-colors"
                >
                  <Upload className="h-3 w-3" /> Import Results
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        open={deletingScanId != null}
        title="Delete Scan"
        message="Delete this scan and all its findings? This action cannot be undone."
        confirmLabel="Delete"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeletingScanId(null)}
      />
    </div>
  );
}
