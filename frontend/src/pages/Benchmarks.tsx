import { useEffect, useState, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Upload, Trash2, FileText, CheckCircle2, Clock, Loader2 } from 'lucide-react';
import type { Benchmark } from '@/types';
import * as api from '@/services/api';

function statusBadge(status: string) {
  const styles: Record<string, string> = {
    completed: 'bg-green-100 text-green-800',
    processing: 'bg-blue-100 text-blue-800',
    failed: 'bg-red-100 text-red-800',
    paused: 'bg-yellow-100 text-yellow-800',
    pending: 'bg-gray-100 text-gray-600',
    completed_with_issues: 'bg-orange-100 text-orange-800',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status] || styles.pending}`}>
      {status.replace(/_/g, ' ')}
    </span>
  );
}

export default function Benchmarks() {
  const navigate = useNavigate();
  const location = useLocation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  const fetchBenchmarks = async () => {
    try {
      const data = await api.getBenchmarks();
      setBenchmarks(data);
    } catch {
      setError('Failed to load benchmarks');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (location.pathname !== '/benchmarks') return;
    fetchBenchmarks();
    const interval = setInterval(fetchBenchmarks, 5000);
    return () => clearInterval(interval);
  }, [location.pathname]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Only PDF files are accepted');
      return;
    }

    setUploading(true);
    setError('');
    setSuccessMsg('');
    try {
      const result = await api.importBenchmark(file);
      setSuccessMsg(`PDF uploaded! Benchmark #${result.benchmark_id} is now being processed.`);
      await fetchBenchmarks();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to upload PDF';
      setError(detail);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Delete this benchmark and all its rules?')) return;
    try {
      await api.deleteBenchmark(id);
      await fetchBenchmarks();
    } catch {
      setError('Failed to delete benchmark');
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-12 text-gray-500">Loading…</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900">CIS Benchmarks</h2>
        <label className={`inline-flex cursor-pointer items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white ${uploading ? 'bg-gray-400' : 'bg-blue-600 hover:bg-blue-700'}`}>
          {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          {uploading ? 'Uploading…' : 'Import CIS PDF'}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            onChange={handleUpload}
            disabled={uploading}
            className="hidden"
          />
        </label>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
      )}
      {successMsg && (
        <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">{successMsg}</div>
      )}

      {benchmarks.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-12 text-center">
          <FileText className="mx-auto h-12 w-12 text-gray-300" />
          <h3 className="mt-4 text-lg font-medium text-gray-900">No benchmarks imported</h3>
          <p className="mt-2 text-sm text-gray-500">
            Upload a CIS Benchmark PDF to get started. The system will parse it and extract all rules.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Benchmark</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Platform</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Rules</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Phase 1</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Phase 2</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Verify</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Ready</th>
                <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {benchmarks.map((b, idx) => (
                <tr key={b.id} className={idx % 2 === 1 ? 'bg-gray-50' : 'bg-white'}>
                  <td className="whitespace-nowrap px-6 py-4">
                    <button
                      onClick={() => navigate(`/benchmarks/${b.id}`)}
                      className="font-medium text-blue-600 hover:text-blue-800 hover:underline"
                    >
                      {b.name}
                    </button>
                    <div className="text-xs text-gray-400">{b.version}</div>
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                    {b.platform_family}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                    {b.total_rules}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4">{statusBadge(b.phase1_status)}</td>
                  <td className="whitespace-nowrap px-6 py-4">{statusBadge(b.phase2_status)}</td>
                  <td className="whitespace-nowrap px-6 py-4">{statusBadge(b.verification_status)}</td>
                  <td className="whitespace-nowrap px-6 py-4">
                    {b.is_ready ? (
                      <CheckCircle2 className="h-5 w-5 text-green-500" />
                    ) : (
                      <Clock className="h-5 w-5 text-gray-300" />
                    )}
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-right">
                    <button
                      onClick={() => handleDelete(b.id)}
                      className="inline-flex items-center rounded-md p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600"
                      title="Delete"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
