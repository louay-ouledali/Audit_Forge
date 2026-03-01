import {
  X,
  Monitor,
  Terminal,
  Network,
  Database,
  HelpCircle,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  Ban,
} from 'lucide-react';
import type { ActiveScan } from './useScanManager';

/* ── Platform icon map (static for Tailwind) ──────────────── */
const PLT: Record<string, { icon: typeof Monitor; color: string; barColor: string }> = {
  windows:  { icon: Monitor,  color: 'text-sky-400',     barColor: 'bg-sky-400' },
  linux:    { icon: Terminal,  color: 'text-emerald-400', barColor: 'bg-emerald-400' },
  network:  { icon: Network,   color: 'text-purple-400',  barColor: 'bg-purple-400' },
  database: { icon: Database,   color: 'text-orange-400',  barColor: 'bg-orange-400' },
};

function formatElapsed(startMs: number): string {
  const secs = Math.floor((Date.now() - startMs) / 1000);
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function statusIcon(status: string) {
  switch (status) {
    case 'running':
    case 'scanning':
      return <Loader2 className="h-3.5 w-3.5 animate-spin text-ey-yellow" />;
    case 'completed':
      return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />;
    case 'failed':
      return <XCircle className="h-3.5 w-3.5 text-red-400" />;
    case 'cancelled':
      return <Ban className="h-3.5 w-3.5 text-dark-muted" />;
    case 'pending':
    default:
      return <Clock className="h-3.5 w-3.5 text-dark-muted" />;
  }
}

interface Props {
  scans: ActiveScan[];
  onCancelScan: (scanId: number) => void;
  onCancelAll: () => void;
  onDismiss: () => void;
}

export default function ActiveScansPanel({ scans, onCancelScan, onCancelAll, onDismiss }: Props) {
  if (scans.length === 0) return null;

  const running = scans.filter(s => s.status === 'running' || s.status === 'scanning');
  const pending = scans.filter(s => s.status === 'pending');
  const done = scans.filter(s => ['completed', 'failed', 'cancelled'].includes(s.status));
  const allDone = running.length === 0 && pending.length === 0;

  return (
    <div className="rounded-xl border border-ey-yellow/20 bg-dark-card shadow-lg shadow-ey-yellow/5 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-dark-border px-4 py-3">
        <div className="flex items-center gap-2">
          {!allDone ? (
            <Loader2 className="h-4 w-4 animate-spin text-ey-yellow" />
          ) : (
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          )}
          <h3 className="text-xs font-bold text-white">
            {allDone
              ? `All Scans Complete (${done.length})`
              : `Active Scans (${running.length} running${pending.length > 0 ? `, ${pending.length} queued` : ''})`
            }
          </h3>
        </div>
        <div className="flex items-center gap-2">
          {!allDone && (
            <button
              onClick={onCancelAll}
              className="rounded-md px-2.5 py-1 text-[11px] font-medium text-red-400 border border-red-500/20 bg-red-500/5 hover:bg-red-500/10 transition-colors"
            >
              Cancel All
            </button>
          )}
          {allDone && (
            <button
              onClick={onDismiss}
              className="rounded-md px-2.5 py-1 text-[11px] font-medium text-dark-secondary border border-dark-border hover:text-white transition-colors"
            >
              Dismiss
            </button>
          )}
        </div>
      </div>

      {/* Scan rows */}
      <div className="divide-y divide-dark-border/50">
        {scans.map(scan => {
          const pl = PLT[scan.targetType.toLowerCase()] ?? { icon: HelpCircle, color: 'text-dark-muted', barColor: 'bg-dark-muted' };
          const Icon = pl.icon;
          const total = scan.total || 1;
          const pct = scan.total > 0 ? Math.round((scan.progress / total) * 100) : 0;
          const isActive = scan.status === 'running' || scan.status === 'scanning';
          const isPending = scan.status === 'pending';

          return (
            <div key={scan.scanId || scan.targetId} className="flex items-center gap-3 px-4 py-2.5">
              {/* Status + platform icon */}
              <div className="flex items-center gap-2 shrink-0">
                {statusIcon(scan.status)}
                <Icon className={`h-3.5 w-3.5 ${pl.color}`} />
              </div>

              {/* Target name */}
              <span className="text-xs font-medium text-white truncate w-32 shrink-0">
                {scan.targetName}
              </span>

              {/* Progress bar */}
              <div className="flex-1 min-w-0">
                {isActive ? (
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1.5 rounded-full bg-dark-elevated overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${pl.barColor}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-[11px] text-dark-secondary whitespace-nowrap w-20 text-right">
                      {scan.progress}/{scan.total} ({pct}%)
                    </span>
                  </div>
                ) : isPending ? (
                  <span className="text-[11px] text-dark-muted italic">Queued (waiting)</span>
                ) : scan.status === 'completed' ? (
                  <div className="flex items-center gap-2 text-[11px]">
                    <span className={`font-bold ${scan.compliance >= 80 ? 'text-emerald-400' : scan.compliance >= 50 ? 'text-amber-400' : 'text-red-400'}`}>
                      {scan.compliance.toFixed(1)}%
                    </span>
                    <span className="text-dark-muted">
                      {scan.passed}P / {scan.failed}F / {scan.errors}E
                    </span>
                  </div>
                ) : scan.status === 'failed' ? (
                  <span className="text-[11px] text-red-400 truncate">{scan.errorMessage || 'Scan failed'}</span>
                ) : (
                  <span className="text-[11px] text-dark-muted capitalize">{scan.status}</span>
                )}
              </div>

              {/* Elapsed time */}
              {(isActive || isPending) && (
                <span className="text-[11px] text-dark-muted whitespace-nowrap shrink-0">
                  ⏱ {formatElapsed(scan.startedAt)}
                </span>
              )}

              {/* Cancel individual */}
              {isActive && scan.scanId > 0 && (
                <button
                  onClick={() => onCancelScan(scan.scanId)}
                  className="rounded p-1 text-dark-muted hover:bg-red-500/10 hover:text-red-400 transition-colors shrink-0"
                  title="Cancel this scan"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
