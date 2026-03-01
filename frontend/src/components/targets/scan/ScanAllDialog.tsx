import { useState } from 'react';
import {
  X,
  Crosshair,
  CheckCircle2,
  AlertTriangle,
  Monitor,
  Terminal,
  Network,
  Database,
  HelpCircle,
  Rocket,
} from 'lucide-react';
import type { Target } from '@/types';

/* ── Platform icon map (static for Tailwind) ──────────────── */
const PLT: Record<string, { icon: typeof Monitor; color: string }> = {
  windows:  { icon: Monitor,  color: 'text-sky-400' },
  linux:    { icon: Terminal,  color: 'text-emerald-400' },
  network:  { icon: Network,   color: 'text-purple-400' },
  database: { icon: Database,   color: 'text-orange-400' },
};

function targetReady(t: Target): { ready: boolean; reason: string } {
  if (!t.ssh_username && !t.has_enable_password)
    return { ready: false, reason: 'No credentials configured' };
  if (!t.default_benchmark_id)
    return { ready: false, reason: 'No benchmark assigned' };
  return { ready: true, reason: '' };
}

interface Props {
  targets: Target[];
  open: boolean;
  onClose: () => void;
  onLaunch: (targetIds: number[], concurrency: number) => void;
}

export default function ScanAllDialog({ targets, open, onClose, onLaunch }: Props) {
  const [concurrency, setConcurrency] = useState(3);

  if (!open) return null;

  const items = targets.map(t => {
    const { ready, reason } = targetReady(t);
    return { target: t, ready, reason };
  });
  const readyTargets = items.filter(i => i.ready);
  const skippedTargets = items.filter(i => !i.ready);

  const handleLaunch = () => {
    const ids = readyTargets.map(i => i.target.id);
    if (ids.length > 0) onLaunch(ids, concurrency);
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Dialog */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="w-full max-w-lg rounded-2xl border border-dark-border bg-dark-card shadow-2xl shadow-black/50"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-dark-border px-5 py-4">
            <div className="flex items-center gap-2">
              <Crosshair className="h-5 w-5 text-ey-yellow" />
              <h2 className="text-sm font-bold text-white">Scan All Targets</h2>
            </div>
            <button onClick={onClose} className="rounded-lg p-1.5 text-dark-muted hover:bg-dark-elevated hover:text-white transition-colors">
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Body */}
          <div className="max-h-[60vh] overflow-y-auto px-5 py-4 space-y-4 scrollbar-thin">
            <p className="text-xs text-dark-secondary">
              Ready to launch scans for <strong className="text-white">{targets.length}</strong> mission target{targets.length !== 1 ? 's' : ''}:
            </p>

            {/* Target list */}
            <div className="space-y-1.5">
              {/* Ready targets */}
              {readyTargets.map(({ target: t }) => {
                const pl = PLT[(t.target_type || '').toLowerCase()] ?? { icon: HelpCircle, color: 'text-dark-muted' };
                const Icon = pl.icon;
                return (
                  <div key={t.id} className="flex items-center gap-2.5 rounded-lg bg-dark-elevated/50 px-3 py-2 text-xs">
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
                    <Icon className={`h-3.5 w-3.5 shrink-0 ${pl.color}`} />
                    <span className="font-medium text-white truncate flex-1">
                      {t.hostname || t.ip_address || `#${t.id}`}
                    </span>
                    <span className="text-dark-muted">→</span>
                    <span className="truncate text-dark-secondary max-w-[180px]">
                      {t.default_benchmark_name || 'Benchmark'}
                    </span>
                  </div>
                );
              })}

              {/* Skipped targets */}
              {skippedTargets.map(({ target: t, reason }) => {
                const pl = PLT[(t.target_type || '').toLowerCase()] ?? { icon: HelpCircle, color: 'text-dark-muted' };
                const Icon = pl.icon;
                return (
                  <div key={t.id} className="flex items-center gap-2.5 rounded-lg bg-dark-elevated/50 px-3 py-2 text-xs opacity-60">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                    <Icon className={`h-3.5 w-3.5 shrink-0 ${pl.color}`} />
                    <span className="font-medium text-white truncate flex-1">
                      {t.hostname || t.ip_address || `#${t.id}`}
                    </span>
                    <span className="text-dark-muted">→</span>
                    <span className="text-amber-400 text-[11px]">⚠ {reason}</span>
                  </div>
                );
              })}
            </div>

            {/* Options */}
            <div className="rounded-lg border border-dark-border/50 bg-dark-elevated/30 p-3 space-y-3">
              {skippedTargets.length > 0 && (
                <div className="flex items-center gap-2 text-xs text-dark-secondary">
                  <span className="inline-block h-2 w-2 rounded-full bg-amber-400" />
                  {skippedTargets.length} target{skippedTargets.length !== 1 ? 's' : ''} will be skipped (not ready)
                </div>
              )}
              <div className="flex items-center justify-between text-xs">
                <label className="text-dark-secondary font-medium">Parallel scans:</label>
                <select
                  value={concurrency}
                  onChange={e => setConcurrency(Number(e.target.value))}
                  className="rounded-lg border border-dark-border bg-dark-card px-3 py-1.5 text-xs text-white focus:border-ey-yellow/40 focus:outline-none"
                >
                  {[1, 2, 3, 4, 5].map(n => (
                    <option key={n} value={n}>{n} simultaneous</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-3 border-t border-dark-border px-5 py-4">
            <button
              onClick={onClose}
              className="rounded-lg border border-dark-border bg-dark-elevated px-4 py-2 text-xs font-medium text-dark-secondary hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleLaunch}
              disabled={readyTargets.length === 0}
              className="inline-flex items-center gap-1.5 rounded-lg bg-ey-yellow px-5 py-2 text-xs font-bold text-black transition-colors hover:bg-ey-yellow-hover disabled:opacity-40 shadow-sm shadow-ey-yellow/10"
            >
              <Rocket className="h-3.5 w-3.5" />
              Launch {readyTargets.length} Scan{readyTargets.length !== 1 ? 's' : ''}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
