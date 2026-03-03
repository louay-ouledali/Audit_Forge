import { useState } from 'react';
import {
  X,
  FileSearch,
  Monitor,
  Server,
  Shield,
  AlertTriangle,
  CheckCircle2,
  Upload,
  Loader2,
  Database,
  Target,
} from 'lucide-react';
import type { SmartImportPreviewResponse, SmartImportResponse } from '@/services/api';

/* ═══════════════════════════════════════════════════════════════════════════
   Import Preview Modal — Phase 1 Smart Import
   Shows auto-detected platform, benchmark, and finding counts before import.
   ═══════════════════════════════════════════════════════════════════════════ */

interface Props {
  open: boolean;
  onClose: () => void;
  preview: SmartImportPreviewResponse | null;
  loading: boolean;
  filename: string;
  onImport: (options: ImportOptions) => Promise<void>;
  onResult?: (result: SmartImportResponse) => void;
}

export interface ImportOptions {
  runFpDetection: boolean;
  allowBenchmarkCreation: boolean;
  targetId?: number | null;
}

const PLATFORM_ICONS: Record<string, typeof Monitor> = {
  windows: Monitor,
  linux: Server,
  network: Server,
  macos: Monitor,
  database: Database,
};

function StatCard({ label, value, color }: { label: string; value: number | string; color: string }) {
  return (
    <div className="rounded-lg border border-dark-border bg-dark-elevated p-3 text-center">
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-[11px] text-dark-muted uppercase tracking-wider mt-1">{label}</div>
    </div>
  );
}

export default function ImportPreviewModal({ open, onClose, preview, loading, filename, onImport }: Props) {
  const [importing, setImporting] = useState(false);
  const [runFpDetection, setRunFpDetection] = useState(true);
  const [allowBenchmarkCreation, setAllowBenchmarkCreation] = useState(true);
  const [importError, setImportError] = useState('');

  if (!open) return null;

  const handleImport = async () => {
    setImporting(true);
    setImportError('');
    try {
      await onImport({
        runFpDetection,
        allowBenchmarkCreation,
      });
    } catch (err: unknown) {
      const msg = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Import failed'
        : err instanceof Error ? err.message : 'Import failed';
      setImportError(msg);
    } finally {
      setImporting(false);
    }
  };

  const PlatformIcon = preview?.platform
    ? PLATFORM_ICONS[preview.platform.toLowerCase()] ?? Shield
    : Shield;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative w-full max-w-lg rounded-2xl border border-dark-border bg-dark-bg shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-dark-border px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-emerald-500/10 p-2">
              <FileSearch className="h-5 w-5 text-emerald-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Smart Import Preview</h2>
              <p className="text-xs text-dark-secondary truncate max-w-[280px]">{filename}</p>
            </div>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-dark-muted hover:bg-dark-elevated hover:text-white transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-5">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <Loader2 className="h-8 w-8 text-ey-yellow animate-spin" />
              <p className="text-sm text-dark-secondary">Analyzing file...</p>
            </div>
          ) : preview?.message ? (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-400">
              <AlertTriangle className="mr-2 inline h-4 w-4" />
              {preview.message}
            </div>
          ) : preview ? (
            <>
              {/* Platform Detection */}
              <div className="rounded-xl border border-dark-border bg-dark-card p-4">
                <h3 className="text-xs font-medium text-dark-secondary uppercase tracking-wider mb-3">Detected Platform</h3>
                <div className="flex items-center gap-3">
                  <div className="rounded-lg bg-sky-500/10 p-2.5">
                    <PlatformIcon className="h-6 w-6 text-sky-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-base font-semibold text-white">
                      {preview.platform_family || preview.platform || 'Unknown'}
                    </div>
                    <div className="text-xs text-dark-secondary space-x-2">
                      {preview.os_version && <span>{preview.os_version}</span>}
                      {preview.profile_level && (
                        <span className="inline-flex rounded bg-violet-500/10 px-1.5 py-0.5 text-[10px] text-violet-400">
                          {preview.profile_level}
                        </span>
                      )}
                    </div>
                  </div>
                  {preview.source_tool && (
                    <span className="shrink-0 rounded-full bg-dark-overlay px-2.5 py-1 text-[11px] text-dark-secondary">
                      {preview.source_tool}
                    </span>
                  )}
                </div>
                {(preview.hostname || preview.ip_address) && (
                  <div className="mt-3 flex items-center gap-2 text-xs text-dark-secondary">
                    <Target className="h-3 w-3" />
                    <span>{preview.hostname || preview.ip_address}</span>
                  </div>
                )}
              </div>

              {/* Benchmark Detection */}
              <div className="rounded-xl border border-dark-border bg-dark-card p-4">
                <h3 className="text-xs font-medium text-dark-secondary uppercase tracking-wider mb-3">Benchmark</h3>
                <div className="flex items-center gap-3">
                  <div className={`rounded-lg p-2.5 ${preview.benchmark_exists ? 'bg-emerald-500/10' : 'bg-amber-500/10'}`}>
                    <Database className={`h-5 w-5 ${preview.benchmark_exists ? 'text-emerald-400' : 'text-amber-400'}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    {preview.benchmark_exists ? (
                      <>
                        <div className="text-sm font-medium text-white truncate">
                          {preview.existing_benchmark_name || preview.benchmark_name}
                        </div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                          <span className="text-xs text-emerald-400">Matched existing benchmark</span>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="text-sm font-medium text-white truncate">
                          {preview.benchmark_name || 'Unknown benchmark'}
                          {preview.benchmark_version && (
                            <span className="ml-1.5 text-dark-secondary">v{preview.benchmark_version}</span>
                          )}
                        </div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <AlertTriangle className="h-3 w-3 text-amber-400" />
                          <span className="text-xs text-amber-400">Will be reconstructed from scan data</span>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>

              {/* Finding Stats */}
              <div className="grid grid-cols-4 gap-2">
                <StatCard label="Passed" value={preview.passed ?? 0} color="text-emerald-400" />
                <StatCard label="Failed" value={preview.failed ?? 0} color="text-red-400" />
                <StatCard label="N/A" value={preview.not_applicable ?? 0} color="text-dark-secondary" />
                <StatCard label="Rules" value={preview.total_rules ?? 0} color="text-sky-400" />
              </div>

              {/* Import Options */}
              <div className="space-y-3">
                <h3 className="text-xs font-medium text-dark-secondary uppercase tracking-wider">Options</h3>
                <label className="flex items-center gap-3 cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={runFpDetection}
                    onChange={(e) => setRunFpDetection(e.target.checked)}
                    className="h-4 w-4 rounded border-dark-border bg-dark-elevated text-ey-yellow focus:ring-ey-yellow/30"
                  />
                  <div>
                    <span className="text-sm text-white group-hover:text-ey-yellow transition-colors">Run false-positive detection</span>
                    <p className="text-xs text-dark-muted">Automatically flag suspicious FAIL results</p>
                  </div>
                </label>
                {!preview.benchmark_exists && (
                  <label className="flex items-center gap-3 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={allowBenchmarkCreation}
                      onChange={(e) => setAllowBenchmarkCreation(e.target.checked)}
                      className="h-4 w-4 rounded border-dark-border bg-dark-elevated text-ey-yellow focus:ring-ey-yellow/30"
                    />
                    <div>
                      <span className="text-sm text-white group-hover:text-ey-yellow transition-colors">Allow benchmark reconstruction</span>
                      <p className="text-xs text-dark-muted">Create a new benchmark from scan rules</p>
                    </div>
                  </label>
                )}
              </div>
            </>
          ) : null}

          {/* Import Error */}
          {importError && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
              <AlertTriangle className="mr-2 inline h-4 w-4" />
              {importError}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-dark-border px-6 py-4">
          <button
            onClick={onClose}
            className="rounded-lg border border-dark-border px-4 py-2 text-sm text-dark-secondary hover:bg-dark-elevated hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleImport}
            disabled={loading || importing || !preview || !!preview.message}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-5 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-emerald-700 disabled:opacity-50"
          >
            {importing ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Importing...
              </>
            ) : (
              <>
                <Upload className="h-4 w-4" />
                Import
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
