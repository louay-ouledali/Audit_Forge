import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, Eye, Loader2 } from 'lucide-react';
import type { ScanDetail, Finding } from '@/types';
import * as api from '@/services/api';
import { inputClass, findingStatusBadge, severityBadge } from './badgeHelpers';

interface Props {
  scans: ScanDetail[];
}

export default function MissionFindings({ scans }: Props) {
  const [selectedScanId, setSelectedScanId] = useState<number | ''>('');
  const [statusFilter, setStatusFilter] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');
  const [findings, setFindings] = useState<Finding[]>([]);
  const [findingsLoading, setFindingsLoading] = useState(false);

  useEffect(() => {
    if (!selectedScanId) { setFindings([]); return; }
    let cancelled = false;
    (async () => {
      setFindingsLoading(true);
      try {
        const params: Record<string, string> = {};
        if (statusFilter) params.status = statusFilter;
        if (severityFilter) params.severity = severityFilter;
        const res = await api.getScanFindings(selectedScanId as number, params);
        if (!cancelled) setFindings(res.data);
      } catch {
        if (!cancelled) setFindings([]);
      } finally {
        if (!cancelled) setFindingsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedScanId, statusFilter, severityFilter]);

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <select value={selectedScanId} onChange={e => setSelectedScanId(e.target.value ? Number(e.target.value) : '')} className={`${inputClass} max-w-xs`}>
          <option value="">Select scan…</option>
          {scans.filter(s => s.status === 'completed' || s.status === 'imported').map(s => (
            <option key={s.id} value={s.id}>
              #{s.id} — {s.target_hostname || s.target_ip || `Target #${s.target_id}`} ({s.compliance_percentage?.toFixed(0)}%)
            </option>
          ))}
        </select>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className={`${inputClass} max-w-[140px]`}>
          <option value="">All Statuses</option>
          <option value="PASS">PASS</option>
          <option value="FAIL">FAIL</option>
          <option value="ERROR">ERROR</option>
          <option value="MANUAL_REVIEW">MANUAL REVIEW</option>
          <option value="NOT_APPLICABLE">NOT APPLICABLE</option>
          <option value="SKIPPED">SKIPPED</option>
        </select>
        <select value={severityFilter} onChange={e => setSeverityFilter(e.target.value)} className={`${inputClass} max-w-[140px]`}>
          <option value="">All Severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>

      {/* Scan context summary */}
      {selectedScanId && (() => {
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

      {/* Findings Table */}
      {!selectedScanId ? (
        <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-12 text-center">
          <AlertTriangle className="mx-auto h-10 w-10 text-dark-muted" />
          <p className="mt-3 text-dark-secondary">Select a scan to view its findings.</p>
        </div>
      ) : findingsLoading ? (
        <div className="flex items-center justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-ey-yellow" /></div>
      ) : findings.length === 0 ? (
        <div className="rounded-xl border border-dark-border bg-dark-card p-8 text-center text-sm text-dark-muted">No findings match your filters.</div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-dark-border bg-dark-card">
          <table className="min-w-full divide-y divide-dark-border">
            <thead className="bg-dark-elevated">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-dark-muted">Section</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-dark-muted">Rule</th>
                <th className="px-4 py-3 text-center text-xs font-medium uppercase text-dark-muted">Status</th>
                <th className="px-4 py-3 text-center text-xs font-medium uppercase text-dark-muted">Severity</th>
                <th className="px-4 py-3 text-center text-xs font-medium uppercase text-dark-muted">Override</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase text-dark-muted">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-dark-border">
              {findings.map(f => (
                <tr key={f.id} className="hover:bg-dark-elevated/30">
                  <td className="px-4 py-3 text-sm font-mono text-dark-secondary">{f.section_number || '—'}</td>
                  <td className="px-4 py-3 text-sm text-white truncate max-w-xs">{f.rule_title || '—'}</td>
                  <td className="px-4 py-3 text-center">{findingStatusBadge(f.override_status || f.status)}</td>
                  <td className="px-4 py-3 text-center">{severityBadge(f.override_severity || f.severity)}</td>
                  <td className="px-4 py-3 text-center text-xs text-dark-secondary">{f.auditor_override || '—'}</td>
                  <td className="px-4 py-3 text-right">
                    <Link to={`/findings/${f.id}`} className="inline-flex items-center gap-1 rounded p-1.5 text-dark-muted hover:text-ey-yellow" title="View details">
                      <Eye className="h-4 w-4" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-dark-border px-4 py-2 text-xs text-dark-muted">{findings.length} findings</div>
        </div>
      )}
    </div>
  );
}
