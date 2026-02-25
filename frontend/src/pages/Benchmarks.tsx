import { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Upload, Trash2, RefreshCw, ChevronRight, Database } from 'lucide-react';
import type { Benchmark } from '@/types';
import * as api from '@/services/api';

const PHASE_LABELS: Record<string, string> = {
  not_started: 'Not Started', pending: 'Pending', processing: 'Processing',
  completed: 'Completed', failed: 'Failed', paused: 'Paused',
};
const PHASE_STYLES: Record<string, string> = {
  not_started: 'bg-dark-overlay text-dark-muted',
  pending: 'bg-amber-500/10 text-amber-400',
  processing: 'bg-sky-500/10 text-sky-400',
  completed: 'bg-emerald-500/10 text-emerald-400',
  failed: 'bg-red-500/10 text-red-400',
  paused: 'bg-amber-500/10 text-amber-400',
};

export default function Benchmarks() {
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');

  const fetchBenchmarks = () => api.getBenchmarks().then(setBenchmarks).catch(() => setError('Failed to load benchmarks')).finally(() => setLoading(false));

  useEffect(() => { fetchBenchmarks(); const interval = setInterval(fetchBenchmarks, 5000); return () => clearInterval(interval); }, []);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    setUploading(true); setError('');
    try { await api.importBenchmark(file); await fetchBenchmarks(); }
    catch { setError('Benchmark import failed. Ensure it is a valid CIS benchmark PDF.'); }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = ''; }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Delete this benchmark and all associated data?')) return;
    try { await api.deleteBenchmark(id); setBenchmarks((prev) => prev.filter((b) => b.id !== id)); }
    catch { setError('Failed to delete benchmark'); }
  };

  const badge = (status: string) => (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${PHASE_STYLES[status] ?? PHASE_STYLES.not_started}`}>
      {PHASE_LABELS[status] ?? status}
    </span>
  );

  if (loading) return <div className="flex items-center justify-center py-12 text-dark-secondary">Loading…</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Benchmarks</h1>
          <p className="mt-1 text-sm text-dark-secondary">Upload CIS benchmark PDFs and manage enrichment pipelines</p>
        </div>
        <div className="flex gap-2">
          <button onClick={fetchBenchmarks} className="rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-dark-secondary hover:bg-dark-elevated hover:text-white">
            <RefreshCw className="h-4 w-4" />
          </button>
          <button onClick={() => fileRef.current?.click()} disabled={uploading}
            className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50">
            <Upload className="h-4 w-4" /> {uploading ? 'Uploading…' : 'Import PDF'}
          </button>
          <input ref={fileRef} type="file" accept=".pdf" className="hidden" onChange={handleUpload} />
        </div>
      </div>

      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>}

      {benchmarks.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-12 text-center">
          <Database className="mx-auto h-10 w-10 text-dark-muted" />
          <p className="mt-3 text-dark-secondary">No benchmarks yet. Upload a CIS PDF to begin.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-dark-border bg-dark-card">
          <table className="min-w-full divide-y divide-dark-border">
            <thead className="bg-dark-elevated">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-dark-muted">Benchmark</th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-dark-muted">Platform</th>
                <th className="px-6 py-3 text-center text-xs font-medium uppercase tracking-wider text-dark-muted">Rules</th>
                <th className="px-6 py-3 text-center text-xs font-medium uppercase tracking-wider text-dark-muted">Phase 1</th>
                <th className="px-6 py-3 text-center text-xs font-medium uppercase tracking-wider text-dark-muted">Phase 2</th>
                <th className="px-6 py-3 text-center text-xs font-medium uppercase tracking-wider text-dark-muted">Verify</th>
                <th className="px-6 py-3 text-center text-xs font-medium uppercase tracking-wider text-dark-muted">Ready</th>
                <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-dark-muted">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-dark-border">
              {benchmarks.map((b) => (
                <tr key={b.id} onClick={() => navigate(`/benchmarks/${b.id}`)} className="cursor-pointer hover:bg-dark-elevated/50 transition-colors">
                  <td className="px-6 py-4">
                    <div className="text-sm font-medium text-white">{b.name}</div>
                    <div className="text-xs text-dark-muted">v{b.version}</div>
                  </td>
                  <td className="px-6 py-4 text-sm text-dark-secondary">{b.platform}</td>
                  <td className="px-6 py-4 text-center text-sm font-medium text-white">{b.total_rules}</td>
                  <td className="px-6 py-4 text-center">{badge(b.phase1_status)}</td>
                  <td className="px-6 py-4 text-center">{badge(b.phase2_status)}</td>
                  <td className="px-6 py-4 text-center">{badge(b.verification_status)}</td>
                  <td className="px-6 py-4 text-center">
                    {b.is_ready
                      ? <span className="inline-flex rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400">Ready</span>
                      : <span className="inline-flex rounded-full bg-dark-overlay px-2 py-0.5 text-[10px] font-medium text-dark-muted">—</span>}
                  </td>
                  <td className="px-6 py-4 text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-1">
                      <button onClick={() => handleDelete(b.id)} className="rounded p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400"><Trash2 className="h-4 w-4" /></button>
                      <button onClick={() => navigate(`/benchmarks/${b.id}`)} className="rounded p-1.5 text-dark-muted hover:bg-ey-yellow/10 hover:text-ey-yellow"><ChevronRight className="h-4 w-4" /></button>
                    </div>
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
