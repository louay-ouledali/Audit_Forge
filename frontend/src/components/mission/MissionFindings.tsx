import { useState, useEffect, useMemo, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Eye, Loader2, Lock, Search, Download, ChevronUp, ChevronDown, ChevronLeft, ChevronRight, CheckSquare, Square, X, ShieldCheck, ShieldOff, RefreshCw } from 'lucide-react';
import type { ScanDetail, Finding } from '@/types';
import * as api from '@/services/api';
import { inputClass, findingStatusBadge, severityBadge } from './badgeHelpers';

const PAGE_SIZE = 50;

/* ── Filter state interface (persisted in MissionWorkspace) ── */
export interface FindingsFilterState {
  selectedScanId: number | 'all' | '';
  statusFilter: string;
  severityFilter: string;
  searchTerm: string;
  sortCol: string;
  sortDir: 'asc' | 'desc';
  page: number;
}

export const DEFAULT_FILTER_STATE: FindingsFilterState = {
  selectedScanId: '',
  statusFilter: '',
  severityFilter: '',
  searchTerm: '',
  sortCol: 'section_number',
  sortDir: 'asc',
  page: 1,
};

/* ── Augmented finding for "All Scans" mode ─────────────── */
type AugmentedFinding = Finding & { _scan_label?: string };

interface Props {
  scans: ScanDetail[];
  isLocked?: boolean;
  /** External filter state (persisted in MissionWorkspace) */
  filterState: FindingsFilterState;
  onFilterChange: (state: FindingsFilterState) => void;
  /** Total finding count callback — feeds the tab badge */
  onTotalCount?: (count: number) => void;
}

export default function MissionFindings({ scans, isLocked = false, filterState, onFilterChange, onTotalCount }: Props) {
  const { selectedScanId, statusFilter, severityFilter, searchTerm, sortCol, sortDir, page } = filterState;
  const [allFindings, setAllFindings] = useState<AugmentedFinding[]>([]);
  const [findingsLoading, setFindingsLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);

  const set = useCallback(
    (patch: Partial<FindingsFilterState>) => onFilterChange({ ...filterState, ...patch }),
    [filterState, onFilterChange],
  );

  const completedScans = useMemo(
    () => scans.filter(s => s.status === 'completed' || s.status === 'imported'),
    [scans],
  );

  /* ── Fetch findings ────────────────────────────────────── */
  useEffect(() => {
    if (!selectedScanId) { setAllFindings([]); return; }
    let cancelled = false;
    (async () => {
      setFindingsLoading(true);
      setSelectedIds(new Set());
      try {
        if (selectedScanId === 'all') {
          const results = await Promise.all(
            completedScans.map(s =>
              api.getScanFindings(s.id).then(r =>
                r.data.map((f: Finding) => ({
                  ...f,
                  _scan_label: `#${s.id} ${s.target_hostname || s.target_ip || ''}`.trim(),
                })),
              ),
            ),
          );
          if (!cancelled) setAllFindings(results.flat());
        } else {
          const res = await api.getScanFindings(selectedScanId as number);
          if (!cancelled) setAllFindings(res.data);
        }
      } catch {
        if (!cancelled) setAllFindings([]);
      } finally {
        if (!cancelled) setFindingsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedScanId, completedScans]);

  /* ── Report total count to parent (for tab badge) ──────── */
  useEffect(() => { onTotalCount?.(allFindings.length); }, [allFindings.length, onTotalCount]);

  /* ── Faceted counts (computed on unfiltered set) ───────── */
  const facets = useMemo(() => {
    const status: Record<string, number> = {};
    const severity: Record<string, number> = {};
    for (const f of allFindings) {
      const s = f.auditor_override === 'false_positive' ? 'FALSE_POSITIVE' : (f.auditor_status_override || f.status);
      status[s] = (status[s] || 0) + 1;
      const sev = f.auditor_severity_override || f.severity || 'unknown';
      severity[sev] = (severity[sev] || 0) + 1;
    }
    return { status, severity };
  }, [allFindings]);

  /* ── Filter + search + sort ────────────────────────────── */
  const processedFindings = useMemo(() => {
    let result = [...allFindings];

    // Status filter
    if (statusFilter) {
      result = result.filter(f => {
        const s = f.auditor_override === 'false_positive' ? 'FALSE_POSITIVE' : (f.auditor_status_override || f.status);
        return s === statusFilter;
      });
    }
    // Severity filter
    if (severityFilter) {
      result = result.filter(f => (f.auditor_severity_override || f.severity) === severityFilter);
    }
    // Text search
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      result = result.filter(f =>
        (f.rule_title || '').toLowerCase().includes(q) ||
        (f.section_number || '').toLowerCase().includes(q) ||
        (f.actual_output || '').toLowerCase().includes(q) ||
        (f.auditor_notes || '').toLowerCase().includes(q),
      );
    }
    // Sort
    result.sort((a, b) => {
      let av: string | number = '';
      let bv: string | number = '';
      switch (sortCol) {
        case 'section_number': av = a.section_number || ''; bv = b.section_number || ''; break;
        case 'rule_title': av = a.rule_title || ''; bv = b.rule_title || ''; break;
        case 'status': av = a.auditor_status_override || a.status; bv = b.auditor_status_override || b.status; break;
        case 'severity': {
          const ord: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
          av = ord[a.auditor_severity_override || a.severity || ''] ?? 4;
          bv = ord[b.auditor_severity_override || b.severity || ''] ?? 4;
          break;
        }
        case 'scan': av = a.scan_id; bv = b.scan_id; break;
      }
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return result;
  }, [allFindings, statusFilter, severityFilter, searchTerm, sortCol, sortDir]);

  /* ── Pagination ────────────────────────────────────────── */
  const totalPages = Math.max(1, Math.ceil(processedFindings.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pagedFindings = processedFindings.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  /* ── Sortable header component ─────────────────────────── */
  function SortHeader({ col, label, center }: { col: string; label: string; center?: boolean }) {
    const active = sortCol === col;
    return (
      <th
        className={`px-4 py-3 text-xs font-medium uppercase text-dark-muted cursor-pointer select-none hover:text-white transition-colors ${center ? 'text-center' : 'text-left'}`}
        onClick={() => set({ sortCol: col, sortDir: active && sortDir === 'asc' ? 'desc' : 'asc', page: 1 })}
      >
        <span className="inline-flex items-center gap-1">
          {label}
          {active && (sortDir === 'asc' ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />)}
        </span>
      </th>
    );
  }

  /* ── Bulk selection helpers ────────────────────────────── */
  const allPageIds = useMemo(() => pagedFindings.map(f => f.id), [pagedFindings]);
  const allPageSelected = allPageIds.length > 0 && allPageIds.every(id => selectedIds.has(id));
  const somePageSelected = allPageIds.some(id => selectedIds.has(id));

  const toggleSelectAll = useCallback(() => {
    if (allPageSelected) {
      setSelectedIds(prev => {
        const next = new Set(prev);
        allPageIds.forEach(id => next.delete(id));
        return next;
      });
    } else {
      setSelectedIds(prev => {
        const next = new Set(prev);
        allPageIds.forEach(id => next.add(id));
        return next;
      });
    }
  }, [allPageSelected, allPageIds]);

  const toggleRow = useCallback((id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const handleBulkAction = useCallback(async (action: {
    auditor_override?: string;
    auditor_status_override?: string;
    auditor_severity_override?: string;
  }) => {
    if (selectedIds.size === 0) return;
    setBulkLoading(true);
    try {
      await api.bulkUpdateFindings({ finding_ids: Array.from(selectedIds), ...action });
      // Refresh findings from server
      if (selectedScanId && selectedScanId !== 'all') {
        const res = await api.getScanFindings(selectedScanId as number);
        setAllFindings(res.data);
      } else if (selectedScanId === 'all') {
        const results = await Promise.all(
          completedScans.map(s =>
            api.getScanFindings(s.id).then(r =>
              r.data.map((f: Finding) => ({
                ...f,
                _scan_label: `#${s.id} ${s.target_hostname || s.target_ip || ''}`.trim(),
              })),
            ),
          ),
        );
        setAllFindings(results.flat());
      }
      setSelectedIds(new Set());
    } catch {
      // silently ignore — individual row badges will reflect DB state on next load
    } finally {
      setBulkLoading(false);
    }
  }, [selectedIds, selectedScanId, completedScans]);

  /* ── CSV export ────────────────────────────────────────── */
  function exportCSV() {
    const header = ['Section', 'Rule', 'Status', 'Severity', 'Override', 'Scan ID', 'Notes'];
    const rows = processedFindings.map(f => [
      f.section_number || '',
      `"${(f.rule_title || '').replace(/"/g, '""')}"`,
      f.auditor_status_override || f.status,
      f.auditor_severity_override || f.severity || '',
      f.auditor_override || '',
      String(f.scan_id),
      `"${(f.auditor_notes || '').replace(/"/g, '""')}"`,
    ]);
    const csv = [header.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `findings_export_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-4">
      {/* Locked banner */}
      {isLocked && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-400">
          <Lock className="h-3.5 w-3.5 shrink-0" /> Mission is locked — finding overrides are disabled.
        </div>
      )}

      {/* ── Faceted Filter Bar ───────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Scan selector with "All Scans" option */}
        <select
          value={selectedScanId}
          onChange={e => {
            const v = e.target.value;
            set({ selectedScanId: v === 'all' ? 'all' : v ? Number(v) : '', page: 1 });
          }}
          className={`${inputClass} max-w-xs`}
        >
          <option value="">Select scan…</option>
          {completedScans.length > 1 && (
            <option value="all">All Scans ({completedScans.length})</option>
          )}
          {completedScans.map(s => (
            <option key={s.id} value={s.id}>
              #{s.id} — {s.target_hostname || s.target_ip || `Target #${s.target_id}`} ({s.compliance_percentage?.toFixed(0)}%)
            </option>
          ))}
        </select>

        {/* Status filter with facet counts */}
        <select value={statusFilter} onChange={e => set({ statusFilter: e.target.value, page: 1 })} className={`${inputClass} max-w-[180px]`}>
          <option value="">All Statuses ({allFindings.length})</option>
          {['FAIL', 'PASS', 'ERROR', 'MANUAL_REVIEW', 'NOT_APPLICABLE', 'SKIPPED'].map(s =>
            facets.status[s] ? <option key={s} value={s}>{s} ({facets.status[s]})</option> : null,
          )}
        </select>

        {/* Severity filter with facet counts */}
        <select value={severityFilter} onChange={e => set({ severityFilter: e.target.value, page: 1 })} className={`${inputClass} max-w-[160px]`}>
          <option value="">All Severities</option>
          {['critical', 'high', 'medium', 'low'].map(s =>
            facets.severity[s] ? <option key={s} value={s}>{s} ({facets.severity[s]})</option> : null,
          )}
        </select>

        {/* Text search */}
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-dark-muted" />
          <input
            type="text"
            value={searchTerm}
            onChange={e => set({ searchTerm: e.target.value, page: 1 })}
            placeholder="Search rule, section, output, notes…"
            className={`${inputClass} pl-9`}
          />
        </div>

        {/* CSV export button */}
        {processedFindings.length > 0 && (
          <button
            onClick={exportCSV}
            className="inline-flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-xs font-medium text-dark-secondary hover:text-white transition-colors"
            title="Export filtered findings as CSV"
          >
            <Download className="h-3.5 w-3.5" /> CSV
          </button>
        )}
      </div>

      {/* Scan context summary (single-scan mode only) */}
      {typeof selectedScanId === 'number' && (() => {
        const sel = scans.find(s => s.id === selectedScanId);
        if (!sel) return null;
        return (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-dark-border bg-dark-elevated px-5 py-3 text-xs text-dark-secondary">
            {sel.benchmark_name && (
              <span><span className="font-medium text-gray-300">Benchmark:</span> {sel.benchmark_name}{sel.benchmark_version ? ` ${sel.benchmark_version}` : ''}</span>
            )}
            {(sel.target_hostname || sel.target_ip) && (
              <span><span className="font-medium text-gray-300">Target:</span> {sel.target_hostname || sel.target_ip}</span>
            )}
            {sel.compliance_percentage != null && (
              <span><span className="font-medium text-gray-300">Compliance:</span> <span className={sel.compliance_percentage >= 70 ? 'text-emerald-400' : sel.compliance_percentage >= 40 ? 'text-amber-400' : 'text-red-400'}>{sel.compliance_percentage.toFixed(1)}%</span></span>
            )}
            <span><span className="font-medium text-gray-300">Mode:</span> {sel.scan_mode}</span>
            {sel.started_at && (
              <span><span className="font-medium text-gray-300">Date:</span> {new Date(sel.started_at).toLocaleString()}</span>
            )}
          </div>
        );
      })()}

      {/* ── Bulk Action Bar (visible when rows selected) ────── */}
      {selectedIds.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-ey-yellow/30 bg-ey-yellow/5 px-4 py-2.5">
          <span className="text-xs font-medium text-ey-yellow">{selectedIds.size} selected</span>
          <div className="h-3.5 w-px bg-dark-border" />
          <button
            onClick={() => handleBulkAction({ auditor_override: 'false_positive' })}
            disabled={bulkLoading || isLocked}
            className="inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium text-dark-secondary hover:text-white bg-dark-elevated border border-dark-border disabled:opacity-40 transition-colors"
            title="Mark selected findings as false positives"
          >
            {bulkLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <ShieldOff className="h-3 w-3" />}
            False Positive
          </button>
          <button
            onClick={() => handleBulkAction({ auditor_override: 'accepted_risk' })}
            disabled={bulkLoading || isLocked}
            className="inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium text-dark-secondary hover:text-white bg-dark-elevated border border-dark-border disabled:opacity-40 transition-colors"
            title="Mark selected findings as accepted risk"
          >
            <ShieldCheck className="h-3 w-3" />
            Accept Risk
          </button>
          <button
            onClick={() => handleBulkAction({ auditor_status_override: 'PASS' })}
            disabled={bulkLoading || isLocked}
            className="inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium text-emerald-400 hover:text-emerald-300 bg-dark-elevated border border-dark-border disabled:opacity-40 transition-colors"
            title="Override status to PASS for selected findings"
          >
            Override → PASS
          </button>
          <button
            onClick={() => handleBulkAction({ auditor_status_override: 'FAIL' })}
            disabled={bulkLoading || isLocked}
            className="inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium text-red-400 hover:text-red-300 bg-dark-elevated border border-dark-border disabled:opacity-40 transition-colors"
            title="Override status to FAIL for selected findings"
          >
            Override → FAIL
          </button>
          <button
            onClick={() => handleBulkAction({ auditor_override: '', auditor_status_override: '', auditor_severity_override: '' })}
            disabled={bulkLoading || isLocked}
            className="inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium text-dark-secondary hover:text-white bg-dark-elevated border border-dark-border disabled:opacity-40 transition-colors"
            title="Clear all overrides for selected findings"
          >
            <RefreshCw className="h-3 w-3" />
            Clear Overrides
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="ml-auto inline-flex items-center gap-1 rounded p-1 text-dark-muted hover:text-white"
            title="Deselect all"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* ── Table ───────────────────────────────────────────── */}
      {!selectedScanId ? (
        <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-12 text-center">
          <AlertTriangle className="mx-auto h-10 w-10 text-dark-muted" />
          <p className="mt-3 text-dark-secondary">Select a scan to view its findings.</p>
        </div>
      ) : findingsLoading ? (
        <div className="flex items-center justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-ey-yellow" /></div>
      ) : pagedFindings.length === 0 ? (
        <div className="rounded-xl border border-dark-border bg-dark-card p-8 text-center text-sm text-dark-muted">No findings match your filters.</div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-dark-border bg-dark-card">
          <table className="min-w-full divide-y divide-dark-border">
            <thead className="bg-dark-elevated">
              <tr>
                <th className="w-10 px-3 py-3">
                  <button
                    onClick={toggleSelectAll}
                    className="text-dark-muted hover:text-ey-yellow transition-colors"
                    title={allPageSelected ? 'Deselect page' : 'Select page'}
                  >
                    {allPageSelected
                      ? <CheckSquare className="h-4 w-4 text-ey-yellow" />
                      : somePageSelected
                        ? <CheckSquare className="h-4 w-4 text-ey-yellow/50" />
                        : <Square className="h-4 w-4" />}
                  </button>
                </th>
                <SortHeader col="section_number" label="Section" />
                <SortHeader col="rule_title" label="Rule" />
                <SortHeader col="status" label="Status" center />
                <SortHeader col="severity" label="Severity" center />
                <th className="px-4 py-3 text-center text-xs font-medium uppercase text-dark-muted">Override</th>
                {selectedScanId === 'all' && <SortHeader col="scan" label="Scan" />}
                <th className="px-4 py-3 text-right text-xs font-medium uppercase text-dark-muted">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-dark-border">
              {pagedFindings.map(f => (
                <tr key={f.id} className={`hover:bg-dark-elevated/30 ${selectedIds.has(f.id) ? 'bg-ey-yellow/5' : ''}`}>
                  <td className="w-10 px-3 py-3">
                    <button
                      onClick={() => toggleRow(f.id)}
                      className="text-dark-muted hover:text-ey-yellow transition-colors"
                    >
                      {selectedIds.has(f.id)
                        ? <CheckSquare className="h-4 w-4 text-ey-yellow" />
                        : <Square className="h-4 w-4" />}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-sm font-mono text-dark-secondary">{f.section_number || '—'}</td>
                  <td className="px-4 py-3 text-sm text-white max-w-xs">
                    <span className="block truncate" title={f.rule_title || ''}>{f.rule_title || '—'}</span>
                  </td>
                  <td className="px-4 py-3 text-center">{findingStatusBadge(f.auditor_status_override || f.status)}</td>
                  <td className="px-4 py-3 text-center">
                    <span className="inline-flex items-center gap-1.5">
                      {severityBadge(f.auditor_severity_override || f.severity)}
                      {f.evaluation_source === 'config_file' && (
                        <span className="inline-flex items-center rounded-full bg-blue-500/15 px-1.5 py-0.5 text-[10px] font-medium text-blue-400" title="Evaluated from config file">Config</span>
                      )}
                      {f.evaluation_source === 'live' && (
                        <span className="inline-flex items-center rounded-full bg-green-500/15 px-1.5 py-0.5 text-[10px] font-medium text-green-400" title="Evaluated via live connection">Live</span>
                      )}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center text-xs text-dark-secondary">{f.auditor_override || '—'}</td>
                  {selectedScanId === 'all' && (
                    <td className="px-4 py-3 text-xs text-dark-secondary whitespace-nowrap">{(f as AugmentedFinding)._scan_label || `#${f.scan_id}`}</td>
                  )}
                  <td className="px-4 py-3 text-right">
                    <Link
                      to={`/findings/${f.id}`}
                      state={{ fromFindings: true, scanId: f.scan_id }}
                      className="inline-flex items-center gap-1 rounded p-1.5 text-dark-muted hover:text-ey-yellow"
                      title="View details"
                    >
                      <Eye className="h-4 w-4" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Pagination footer */}
          <div className="flex items-center justify-between border-t border-dark-border px-4 py-2.5">
            <span className="text-xs text-dark-muted">
              {processedFindings.length} finding{processedFindings.length !== 1 ? 's' : ''} · page {safePage} of {totalPages}
            </span>
            {totalPages > 1 && (
              <div className="flex items-center gap-1">
                <button onClick={() => set({ page: safePage - 1 })} disabled={safePage <= 1} className="rounded p-1 text-dark-muted hover:text-white disabled:opacity-30"><ChevronLeft className="h-4 w-4" /></button>
                {Array.from({ length: Math.min(7, totalPages) }, (_, i) => {
                  let p: number;
                  if (totalPages <= 7) p = i + 1;
                  else if (safePage <= 4) p = i + 1;
                  else if (safePage >= totalPages - 3) p = totalPages - 6 + i;
                  else p = safePage - 3 + i;
                  return (
                    <button key={p} onClick={() => set({ page: p })} className={`rounded px-2 py-0.5 text-xs font-medium ${safePage === p ? 'bg-ey-yellow/20 text-ey-yellow' : 'text-dark-muted hover:text-white'}`}>{p}</button>
                  );
                })}
                <button onClick={() => set({ page: safePage + 1 })} disabled={safePage >= totalPages} className="rounded p-1 text-dark-muted hover:text-white disabled:opacity-30"><ChevronRight className="h-4 w-4" /></button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
