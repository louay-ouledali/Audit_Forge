import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Search,
  Eye,
  Trash2,
} from 'lucide-react';
import type { Finding, ScanDetail } from '@/types';
import * as api from '@/services/api';

function statusBadge(status: string) {
  const styles: Record<string, string> = {
    PASS: 'bg-green-500/10 text-green-400',
    FAIL: 'bg-red-500/10 text-red-400',
    ERROR: 'bg-yellow-500/10 text-yellow-400',
    MANUAL_REVIEW: 'bg-blue-500/10 text-blue-400',
    NOT_APPLICABLE: 'bg-dark-overlay text-dark-muted',
    SKIPPED: 'bg-dark-overlay text-dark-muted',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status] || 'bg-dark-overlay text-dark-muted'}`}>
      {status}
    </span>
  );
}

function severityBadge(severity: string | null) {
  if (!severity) return null;
  const styles: Record<string, string> = {
    critical: 'bg-red-500/10 text-red-400',
    high: 'bg-orange-500/10 text-orange-400',
    medium: 'bg-yellow-500/10 text-yellow-400',
    low: 'bg-green-500/10 text-green-400',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[severity] || 'bg-dark-overlay text-dark-muted'}`}>
      {severity}
    </span>
  );
}

/** Build a human-friendly scan label from enriched data. */
function scanLabel(s: ScanDetail): string {
  const parts: string[] = [];
  // Benchmark short name (strip "CIS " prefix for brevity)
  if (s.benchmark_name) {
    const short = s.benchmark_name.replace(/^CIS\s+/, '');
    parts.push(s.benchmark_version ? `${short} ${s.benchmark_version}` : short);
  }
  // Target identifier
  const target = s.target_hostname || s.target_ip;
  if (target) parts.push(target);
  // Date
  if (s.started_at) {
    parts.push(new Date(s.started_at).toLocaleDateString());
  } else if (s.created_at) {
    parts.push(new Date(s.created_at).toLocaleDateString());
  }
  // Fallback to generic if nothing enriched
  if (parts.length === 0) parts.push(`Scan #${s.id} - ${s.scan_mode}`);
  return `${parts.join(' | ')} (${s.status})`;
}

export default function Findings() {
  const [scans, setScans] = useState<ScanDetail[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [selectedScanId, setSelectedScanId] = useState<number | ''>('');
  const [statusFilter, setStatusFilter] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');
  const [deleting, setDeleting] = useState(false);

  const location = useLocation();

  // Refetch scans whenever this page becomes visible (KeepAlive means mount-only effects go stale)
  useEffect(() => {
    if (location.pathname === '/findings') {
      api.getScans().then((res) => setScans(res.data)).catch(() => setError('Failed to load scans'));
    }
  }, [location.pathname]);

  useEffect(() => {
    if (!selectedScanId) {
      setFindings([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const params: Record<string, string> = {};
    if (statusFilter) params.status = statusFilter;
    if (severityFilter) params.severity = severityFilter;
    api
      .getScanFindings(selectedScanId as number, params)
      .then((res) => setFindings(res.data))
      .catch(() => setError('Failed to load findings'))
      .finally(() => setLoading(false));
  }, [selectedScanId, statusFilter, severityFilter]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Findings</h1>
          <p className="mt-1 text-sm text-dark-secondary">
            Browse compliance findings across all scans
          </p>
        </div>
        <AlertTriangle className="h-8 w-8 text-yellow-400" />
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">{error}</div>
      )}

      {/* Filters */}
      <div className="rounded-xl border border-dark-border bg-dark-card p-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-300">Scan</label>
            <div className="flex gap-2">
              <select
                className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
                value={selectedScanId}
                onChange={(e) => setSelectedScanId(e.target.value ? Number(e.target.value) : '')}
              >
                <option value="">Select scan{'\u2026'}</option>
                {scans.map((s) => (
                  <option key={s.id} value={s.id}>
                    {scanLabel(s)}
                  </option>
                ))}
              </select>
              {selectedScanId && (
                <button
                  onClick={async () => {
                    if (!confirm(`Delete Scan #${selectedScanId} and all its findings? This cannot be undone.`)) return;
                    setDeleting(true);
                    setError('');
                    try {
                      await api.deleteScan(selectedScanId as number);
                      setScans(prev => prev.filter(s => s.id !== selectedScanId));
                      setSelectedScanId('');
                      setFindings([]);
                    } catch (err: any) {
                      const msg = err?.response?.data?.detail || err?.message || 'Unknown error';
                      setError(`Failed to delete scan: ${msg}`);
                    }
                    finally { setDeleting(false); }
                  }}
                  disabled={deleting}
                  className="flex-shrink-0 rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-red-400 hover:bg-red-500/20 hover:text-red-300 disabled:opacity-50"
                  title="Delete this scan"
                >
                  {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                </button>
              )}
            </div>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-300">Status</label>
            <select
              className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="">All statuses</option>
              <option value="PASS">PASS</option>
              <option value="FAIL">FAIL</option>
              <option value="ERROR">ERROR</option>
              <option value="MANUAL_REVIEW">MANUAL_REVIEW</option>
              <option value="NOT_APPLICABLE">NOT_APPLICABLE</option>
              <option value="SKIPPED">SKIPPED</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-300">Severity</label>
            <select
              className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
            >
              <option value="">All severities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>
        </div>
      </div>

      {/* Scan context summary */}
      {selectedScanId && (() => {
        const sel = scans.find((s) => s.id === selectedScanId);
        if (!sel) return null;
        return (
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-dark-border bg-dark-elevated px-5 py-3 text-xs text-dark-secondary">
            {sel.client_name && (
              <span><span className="font-medium text-gray-300">Client:</span> {sel.client_name}</span>
            )}
            {sel.mission_name && (
              <span><span className="font-medium text-gray-300">Mission:</span> {sel.mission_name}</span>
            )}
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

      {/* Results table */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-ey-yellow" />
        </div>
      ) : !selectedScanId ? (
        <div className="rounded-xl border border-dashed border-dark-border bg-dark-elevated p-12 text-center">
          <Search className="mx-auto h-12 w-12 text-dark-muted" />
          <h3 className="mt-4 text-lg font-medium text-white">Select a scan</h3>
          <p className="mt-2 text-sm text-dark-secondary">Choose a scan above to view its findings.</p>
        </div>
      ) : findings.length === 0 ? (
        <div className="rounded-xl border border-dashed border-dark-border bg-dark-elevated p-12 text-center">
          <CheckCircle2 className="mx-auto h-12 w-12 text-green-400" />
          <h3 className="mt-4 text-lg font-medium text-white">No findings</h3>
          <p className="mt-2 text-sm text-dark-secondary">No findings match the current filters.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-dark-border bg-dark-card">
          <table className="min-w-full divide-y divide-dark-border">
            <thead className="bg-dark-elevated">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-dark-muted">
                  Section
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-dark-muted">
                  Rule
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-dark-muted">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-dark-muted">
                  Severity
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-dark-muted">
                  Override
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-dark-muted">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-dark-border">
              {findings.map((f) => (
                <tr key={f.id} className="hover:bg-dark-elevated">
                  <td className="whitespace-nowrap px-6 py-4 text-sm font-mono text-white">
                    {f.section_number || '-'}
                  </td>
                  <td className="px-6 py-4 text-sm text-white">
                    <div className="max-w-md truncate">{f.rule_title || '-'}</div>
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm">
                    {statusBadge(f.status)}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm">
                    {severityBadge(f.severity)}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-dark-secondary">
                    {f.auditor_override || '-'}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-right text-sm">
                    <Link
                      to={`/findings/${f.id}`}
                      className="inline-flex items-center gap-1 text-ey-yellow hover:text-ey-yellow-hover"
                    >
                      <Eye className="h-4 w-4" />
                      View
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-dark-border bg-dark-elevated px-6 py-3 text-sm text-dark-secondary">
            {findings.length} finding{findings.length !== 1 ? 's' : ''}
          </div>
        </div>
      )}
    </div>
  );
}
