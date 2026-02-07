import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Search,
  Eye,
} from 'lucide-react';
import type { Finding, ScanDetail } from '@/types';
import * as api from '@/services/api';

function statusBadge(status: string) {
  const styles: Record<string, string> = {
    PASS: 'bg-green-100 text-green-800',
    FAIL: 'bg-red-100 text-red-800',
    ERROR: 'bg-yellow-100 text-yellow-800',
    MANUAL_REVIEW: 'bg-blue-100 text-blue-800',
    NOT_APPLICABLE: 'bg-gray-100 text-gray-600',
    SKIPPED: 'bg-gray-100 text-gray-600',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status] || 'bg-gray-100 text-gray-600'}`}>
      {status}
    </span>
  );
}

function severityBadge(severity: string | null) {
  if (!severity) return null;
  const styles: Record<string, string> = {
    critical: 'bg-red-100 text-red-800',
    high: 'bg-orange-100 text-orange-800',
    medium: 'bg-yellow-100 text-yellow-800',
    low: 'bg-green-100 text-green-800',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[severity] || 'bg-gray-100 text-gray-600'}`}>
      {severity}
    </span>
  );
}

export default function Findings() {
  const [scans, setScans] = useState<ScanDetail[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [selectedScanId, setSelectedScanId] = useState<number | ''>('');
  const [statusFilter, setStatusFilter] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');

  useEffect(() => {
    api.getScans().then((res) => setScans(res.data)).catch(() => setError('Failed to load scans'));
  }, []);

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
          <h1 className="text-2xl font-bold text-gray-900">Findings</h1>
          <p className="mt-1 text-sm text-gray-500">
            Browse compliance findings across all scans
          </p>
        </div>
        <AlertTriangle className="h-8 w-8 text-yellow-400" />
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
      )}

      {/* Filters */}
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Scan</label>
            <select
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              value={selectedScanId}
              onChange={(e) => setSelectedScanId(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">Select scan...</option>
              {scans.map((s) => (
                <option key={s.id} value={s.id}>
                  Scan #{s.id} — {s.scan_mode} ({s.status})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Status</label>
            <select
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
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
            <label className="mb-1 block text-sm font-medium text-gray-700">Severity</label>
            <select
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
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

      {/* Results table */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
        </div>
      ) : !selectedScanId ? (
        <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-12 text-center">
          <Search className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-4 text-lg font-medium text-gray-900">Select a scan</h3>
          <p className="mt-2 text-sm text-gray-500">Choose a scan above to view its findings.</p>
        </div>
      ) : findings.length === 0 ? (
        <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-12 text-center">
          <CheckCircle2 className="mx-auto h-12 w-12 text-green-400" />
          <h3 className="mt-4 text-lg font-medium text-gray-900">No findings</h3>
          <p className="mt-2 text-sm text-gray-500">No findings match the current filters.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Section
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Rule
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Severity
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Override
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {findings.map((f) => (
                <tr key={f.id} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-6 py-4 text-sm font-mono text-gray-900">
                    {f.section_number || '—'}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-900">
                    <div className="max-w-md truncate">{f.rule_title || '—'}</div>
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm">
                    {statusBadge(f.status)}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm">
                    {severityBadge(f.severity)}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                    {f.auditor_override || '—'}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-right text-sm">
                    <Link
                      to={`/findings/${f.id}`}
                      className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800"
                    >
                      <Eye className="h-4 w-4" />
                      View
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-gray-200 bg-gray-50 px-6 py-3 text-sm text-gray-500">
            {findings.length} finding{findings.length !== 1 ? 's' : ''}
          </div>
        </div>
      )}
    </div>
  );
}
