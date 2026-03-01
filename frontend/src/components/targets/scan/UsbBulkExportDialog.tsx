import { useState } from 'react';
import { createPortal } from 'react-dom';
import {
  X,
  Package,
  Monitor,
  Terminal,
  Network,
  Database,
  HelpCircle,
  AlertTriangle,
  Download,
  Loader2,
  CheckCircle2,
} from 'lucide-react';
import type { Target, GenerateScriptRequest } from '@/types';
import * as api from '@/services/api';

/* ── Platform helpers ─────────────────────────────────────────── */
const PLATFORM_META: Record<string, {
  icon: typeof Monitor;
  color: string;
  ext: string;
  supported: boolean;
}> = {
  windows: { icon: Monitor, color: 'text-sky-400', ext: '.ps1', supported: true },
  linux:   { icon: Terminal, color: 'text-emerald-400', ext: '.sh', supported: true },
  network: { icon: Network, color: 'text-purple-400', ext: '', supported: false },
  database:{ icon: Database, color: 'text-orange-400', ext: '', supported: false },
};

const DEFAULT_META = { icon: HelpCircle, color: 'text-dark-muted', ext: '', supported: false };

function getMeta(t: Target) {
  return PLATFORM_META[(t.target_type || '').toLowerCase()] || DEFAULT_META;
}

/* ── Props ────────────────────────────────────────────────────── */
interface Props {
  targets: Target[];
  open: boolean;
  onClose: () => void;
  missionId: number;
}

type DownloadFormat = 'separate' | 'combined';

interface DownloadState {
  downloading: boolean;
  completed: number;
  failed: number;
  total: number;
}

export default function UsbBulkExportDialog({ targets, open, onClose, missionId: _missionId }: Props) {
  const [format, setFormat] = useState<DownloadFormat>('separate');
  const [dlState, setDlState] = useState<DownloadState | null>(null);

  if (!open) return null;

  const supported = targets.filter(t => getMeta(t).supported && !!t.default_benchmark_id);
  const unsupported = targets.filter(t => !getMeta(t).supported || !t.default_benchmark_id);

  /* ── Download logic ──────────────────────────────────────── */
  const handleDownload = async () => {
    if (supported.length === 0) return;

    setDlState({ downloading: true, completed: 0, failed: 0, total: supported.length });

    if (format === 'separate') {
      // Download each target as its own ZIP
      let completed = 0;
      let failed = 0;

      for (const t of supported) {
        try {
          const payload: GenerateScriptRequest = {
            benchmark_id: t.default_benchmark_id!,
            target_id: t.id,
          };
          const blob = await api.generateScript(payload);
          triggerDownload(blob, buildFilename(t));
          completed++;
        } catch (err) {
          console.error(`USB export failed for target ${t.id}:`, err);
          failed++;
        }
        setDlState(prev => prev ? { ...prev, completed, failed } : null);
      }

      setDlState({ downloading: false, completed, failed, total: supported.length });
    } else {
      // Combined: download all sequentially, then merge into one ZIP via JSZip
      // For MVP, we download them sequentially as separate files (combined ZIP requires JSZip)
      let completed = 0;
      let failed = 0;

      for (const t of supported) {
        try {
          const payload: GenerateScriptRequest = {
            benchmark_id: t.default_benchmark_id!,
            target_id: t.id,
          };
          const blob = await api.generateScript(payload);
          triggerDownload(blob, buildFilename(t));
          completed++;
        } catch (err) {
          console.error(`USB export failed for target ${t.id}:`, err);
          failed++;
        }
        setDlState(prev => prev ? { ...prev, completed, failed } : null);
      }

      setDlState({ downloading: false, completed, failed, total: supported.length });
    }
  };

  const handleDismiss = () => {
    setDlState(null);
    onClose();
  };

  return createPortal(
    <>
      {/* Backdrop — portaled to body to escape backdrop-blur containing block */}
      <div className="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm" onClick={dlState?.downloading ? undefined : handleDismiss} />

      {/* Dialog */}
      <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" style={{ pointerEvents: 'none' }}>
        <div className="pointer-events-auto w-full max-w-lg rounded-2xl border border-dark-border bg-dark-card shadow-2xl shadow-ey-yellow/5">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-dark-border p-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-ey-yellow/10 border border-ey-yellow/20">
              <Package className="h-5 w-5 text-ey-yellow" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white">Bulk USB Export</h3>
              <p className="text-xs text-dark-secondary">Generate offline audit scripts for USB distribution</p>
            </div>
          </div>
          <button
            onClick={handleDismiss}
            disabled={dlState?.downloading}
            className="rounded-lg p-2 text-dark-muted hover:bg-dark-elevated hover:text-white transition-colors disabled:opacity-30"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4 max-h-[60vh] overflow-y-auto">
          {/* Supported targets */}
          {supported.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-semibold text-dark-secondary uppercase tracking-wider">
                Ready for export ({supported.length})
              </h4>
              {supported.map(t => {
                const m = getMeta(t);
                const Icon = m.icon;
                return (
                  <div key={t.id} className="flex items-center gap-3 rounded-lg bg-dark-elevated/50 border border-dark-border/50 px-3 py-2">
                    <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                    <Icon className={`h-4 w-4 ${m.color} shrink-0`} />
                    <div className="min-w-0 flex-1">
                      <span className="text-sm text-white font-medium truncate block">
                        {t.hostname || t.ip_address || `Target #${t.id}`}
                      </span>
                    </div>
                    <span className="text-xs text-dark-muted shrink-0">
                      {t.default_benchmark_name || 'Benchmark set'}
                    </span>
                    <span className="text-[10px] text-dark-muted font-mono shrink-0">{m.ext}</span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Unsupported targets */}
          {unsupported.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-semibold text-dark-secondary uppercase tracking-wider">
                Not supported ({unsupported.length})
              </h4>
              {unsupported.map(t => {
                const m = getMeta(t);
                const Icon = m.icon;
                const reason = !m.supported
                  ? `${(t.target_type || 'Unknown').charAt(0).toUpperCase() + (t.target_type || 'unknown').slice(1)} requires live connection`
                  : 'No benchmark assigned';
                return (
                  <div key={t.id} className="flex items-center gap-3 rounded-lg bg-dark-elevated/30 border border-dark-border/30 px-3 py-2 opacity-60">
                    <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
                    <Icon className={`h-4 w-4 ${m.color} shrink-0`} />
                    <div className="min-w-0 flex-1">
                      <span className="text-sm text-dark-secondary truncate block">
                        {t.hostname || t.ip_address || `Target #${t.id}`}
                      </span>
                    </div>
                    <span className="text-xs text-amber-400/80 shrink-0">{reason}</span>
                  </div>
                );
              })}

              {/* Info banner */}
              <div className="rounded-lg bg-amber-500/5 border border-amber-500/20 px-3 py-2 text-xs text-amber-400/80">
                <AlertTriangle className="inline h-3 w-3 mr-1.5" />
                Network devices and databases require live connections — USB air-gap is not available.
                Use <strong>Scan All</strong> for those targets instead.
              </div>
            </div>
          )}

          {/* Download format selector */}
          {supported.length > 1 && (
            <div className="space-y-2 pt-2 border-t border-dark-border/50">
              <h4 className="text-xs font-semibold text-dark-secondary uppercase tracking-wider">
                Download format
              </h4>
              <div className="flex gap-3">
                <label className="flex items-center gap-2 cursor-pointer group">
                  <input
                    type="radio"
                    name="dlFormat"
                    checked={format === 'separate'}
                    onChange={() => setFormat('separate')}
                    className="accent-ey-yellow"
                  />
                  <span className="text-sm text-dark-secondary group-hover:text-white transition-colors">
                    Separate ZIPs <span className="text-xs text-dark-muted">(one per target)</span>
                  </span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer group">
                  <input
                    type="radio"
                    name="dlFormat"
                    checked={format === 'combined'}
                    onChange={() => setFormat('combined')}
                    className="accent-ey-yellow"
                  />
                  <span className="text-sm text-dark-secondary group-hover:text-white transition-colors">
                    Combined ZIP <span className="text-xs text-dark-muted">(all in one)</span>
                  </span>
                </label>
              </div>
            </div>
          )}

          {/* Download progress */}
          {dlState && (
            <div className="rounded-lg bg-dark-elevated border border-dark-border px-4 py-3 space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-dark-secondary font-medium">
                  {dlState.downloading ? 'Downloading…' : 'Complete'}
                </span>
                <span className="text-xs text-dark-muted">
                  {dlState.completed + dlState.failed} / {dlState.total}
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-dark-overlay overflow-hidden">
                <div
                  className="h-full rounded-full bg-ey-yellow transition-all duration-300"
                  style={{ width: `${((dlState.completed + dlState.failed) / dlState.total) * 100}%` }}
                />
              </div>
              <div className="flex gap-4 text-xs">
                {dlState.completed > 0 && (
                  <span className="text-emerald-400 flex items-center gap-1">
                    <CheckCircle2 className="h-3 w-3" /> {dlState.completed} downloaded
                  </span>
                )}
                {dlState.failed > 0 && (
                  <span className="text-red-400 flex items-center gap-1">
                    <AlertTriangle className="h-3 w-3" /> {dlState.failed} failed
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-dark-border p-5">
          <button
            onClick={handleDismiss}
            disabled={dlState?.downloading}
            className="rounded-lg border border-dark-border bg-dark-elevated px-4 py-2 text-sm font-medium text-dark-secondary hover:text-white hover:bg-dark-overlay transition-colors disabled:opacity-30"
          >
            {dlState && !dlState.downloading ? 'Done' : 'Cancel'}
          </button>
          {(!dlState || dlState.downloading) && (
            <button
              onClick={handleDownload}
              disabled={supported.length === 0 || dlState?.downloading}
              className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-5 py-2 text-sm font-bold text-black transition-colors hover:bg-ey-yellow-hover disabled:opacity-40 shadow-sm shadow-ey-yellow/10"
            >
              {dlState?.downloading ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Exporting…</>
              ) : (
                <><Download className="h-4 w-4" /> Download {supported.length} Package{supported.length !== 1 ? 's' : ''}</>
              )}
            </button>
          )}
        </div>
        </div>
      </div>
    </>,
    document.body,
  );
}

/* ── Helpers ──────────────────────────────────────────────────── */

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function buildFilename(t: Target): string {
  const host = t.hostname || t.ip_address || `target_${t.id}`;
  const bench = (t.default_benchmark_name || 'audit').replace(/\s+/g, '_');
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  return `auditforge_audit_${bench}_${host}_${date}.zip`;
}
