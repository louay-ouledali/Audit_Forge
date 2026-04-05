import { useState, useEffect, useCallback } from 'react';
import {
  CheckCircle2,
  XCircle,
  Loader2,
  ArrowUp,
  ArrowDown,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Clock,
  RefreshCw,
} from 'lucide-react';
import type { SentinelRun } from '@/types';
import { getScheduleRuns } from '@/services/api';
import { formatTimeAgo, formatDateTime } from '@/utils/time';
import ComplianceTrendChart from './ComplianceTrendChart';

/* ── Status badge config ─────────────────────────────────────── */

const STATUS_CONFIG: Record<
  string,
  { icon: React.ElementType; label: string; dot: string; badge: string }
> = {
  running: {
    icon: Loader2,
    label: 'Running',
    dot: 'bg-amber-400 animate-pulse',
    badge: 'bg-amber-500/15 text-amber-400 border-amber-500/20',
  },
  completed: {
    icon: CheckCircle2,
    label: 'Completed',
    dot: 'bg-emerald-400',
    badge: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
  },
  failed: {
    icon: XCircle,
    label: 'Failed',
    dot: 'bg-red-400',
    badge: 'bg-red-500/15 text-red-400 border-red-500/20',
  },
};

/* ── Props ───────────────────────────────────────────────────── */

interface RunTimelineProps {
  scheduleId: number;
  scheduleName: string;
}

/* ── Component ───────────────────────────────────────────────── */

export default function RunTimeline({ scheduleId, scheduleName }: RunTimelineProps) {
  const [runs, setRuns] = useState<SentinelRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRunId, setExpandedRunId] = useState<number | null>(null);

  const fetchRuns = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const result = await getScheduleRuns(scheduleId, 0, 50);
      const data: SentinelRun[] = Array.isArray(result) ? result : result.data ?? [];
      setRuns(data);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load runs';
      if (!silent) setError(message);
    } finally {
      if (!silent) setLoading(false);
    }
  }, [scheduleId]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  /* Auto-refresh if any run is still running (silent — no spinner flash) */
  useEffect(() => {
    const hasRunning = runs.some((r) => r.status === 'running');
    if (!hasRunning) return;
    const timer = setInterval(() => fetchRuns(true), 10_000);
    return () => clearInterval(timer);
  }, [runs, fetchRuns]);

  /* ── Loading state ──────────────────────────────────────────── */
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-dark-muted" />
        <span className="ml-2 text-sm text-dark-muted">Loading run history...</span>
      </div>
    );
  }

  /* ── Error state ────────────────────────────────────────────── */
  if (error) {
    return (
      <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-6 text-center">
        <XCircle className="mx-auto h-6 w-6 text-red-400" />
        <p className="mt-2 text-sm text-red-400">{error}</p>
        <button
          onClick={fetchRuns}
          className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-dark-secondary hover:text-white transition-colors"
        >
          <RefreshCw className="h-3 w-3" /> Retry
        </button>
      </div>
    );
  }

  /* ── Empty state ────────────────────────────────────────────── */
  if (runs.length === 0) {
    return (
      <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-8 text-center">
        <Clock className="mx-auto h-8 w-8 text-dark-muted" />
        <h4 className="mt-3 text-sm font-semibold text-white">No runs yet</h4>
        <p className="mt-1 text-xs text-dark-muted max-w-xs mx-auto leading-relaxed">
          Use &quot;Run Now&quot; or wait for the next scheduled execution.
        </p>
      </div>
    );
  }

  /* ── Timeline ───────────────────────────────────────────────── */
  return (
    <div className="rounded-xl border border-dark-border bg-dark-card p-5">
      <div className="flex items-center justify-between mb-5">
        <h3 className="text-sm font-semibold text-white uppercase tracking-wider">
          Run History
        </h3>
        <span className="text-[10px] text-dark-muted font-medium">
          {scheduleName}
        </span>
      </div>

      {/* Compliance trend chart */}
      {runs.length >= 2 && (
        <div className="mb-5">
          <ComplianceTrendChart runs={runs} />
        </div>
      )}

      <div className="relative ml-4">
        {/* Vertical connecting line */}
        <div className="absolute left-[7px] top-2 bottom-2 w-0.5 bg-dark-border/60" />

        <div className="space-y-0">
          {runs.map((run, idx) => {
            const cfg = STATUS_CONFIG[run.status] || STATUS_CONFIG.completed;
            const StatusIcon = cfg.icon;
            const isExpanded = expandedRunId === run.id;
            const isLast = idx === runs.length - 1;

            return (
              <div key={run.id} className={`relative ${!isLast ? 'pb-6' : ''}`}>
                {/* Dot */}
                <div className="absolute left-0 top-1 z-10">
                  <div
                    className={`h-[15px] w-[15px] rounded-full border-[3px] border-dark-card ${cfg.dot}`}
                  />
                </div>

                {/* Content */}
                <div className="ml-8">
                  {/* Top row: date + status */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-xs font-medium text-white">
                        {formatDateTime(run.started_at)}
                      </span>
                      <span className="text-[10px] text-dark-muted">
                        {formatTimeAgo(run.started_at)}
                      </span>
                    </div>
                    <span
                      className={`shrink-0 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest ${cfg.badge}`}
                    >
                      <StatusIcon
                        className={`h-3 w-3 ${run.status === 'running' ? 'animate-spin' : ''}`}
                      />
                      {cfg.label}
                    </span>
                  </div>

                  {/* Metrics row */}
                  {run.status !== 'failed' && (
                    <div className="mt-1.5 flex flex-wrap items-center gap-3">
                      {/* Compliance */}
                      {run.compliance_current != null && (
                        <span
                          className={`text-xs font-bold ${
                            run.compliance_current >= 80
                              ? 'text-emerald-400'
                              : run.compliance_current >= 60
                                ? 'text-amber-400'
                                : 'text-red-400'
                          }`}
                        >
                          {run.compliance_current.toFixed(1)}%
                        </span>
                      )}

                      {/* Delta */}
                      {run.compliance_delta != null && run.compliance_delta !== 0 && (
                        <span
                          className={`inline-flex items-center gap-0.5 text-[11px] font-semibold ${
                            run.compliance_delta > 0 ? 'text-emerald-400' : 'text-red-400'
                          }`}
                        >
                          {run.compliance_delta > 0 ? (
                            <ArrowUp className="h-3 w-3" />
                          ) : (
                            <ArrowDown className="h-3 w-3" />
                          )}
                          {run.compliance_delta > 0 ? '+' : ''}
                          {run.compliance_delta.toFixed(1)}%
                        </span>
                      )}

                      {/* Counters */}
                      <div className="flex items-center gap-1.5">
                        {run.rules_regressed > 0 && (
                          <span className="inline-flex items-center gap-0.5 rounded-md bg-red-500/10 px-1.5 py-0.5 text-[10px] font-bold text-red-400">
                            <ArrowDown className="h-2.5 w-2.5" />
                            {run.rules_regressed} regressed
                          </span>
                        )}
                        {run.rules_improved > 0 && (
                          <span className="inline-flex items-center gap-0.5 rounded-md bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-bold text-emerald-400">
                            <ArrowUp className="h-2.5 w-2.5" />
                            {run.rules_improved} improved
                          </span>
                        )}
                        {run.critical_openings > 0 && (
                          <span className="inline-flex items-center gap-0.5 rounded-md bg-red-500/15 px-1.5 py-0.5 text-[10px] font-bold text-red-400">
                            <AlertTriangle className="h-2.5 w-2.5" />
                            {run.critical_openings} critical
                          </span>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Failed error message */}
                  {run.status === 'failed' && (
                    <p className="mt-1 text-xs text-red-400/80">
                      Run failed. Check server logs for details.
                    </p>
                  )}

                  {/* Expandable details */}
                  {run.comparison_details && (
                    <button
                      onClick={() => setExpandedRunId(isExpanded ? null : run.id)}
                      className="mt-1.5 inline-flex items-center gap-1 text-[11px] font-medium text-dark-secondary hover:text-ey-yellow transition-colors"
                    >
                      {isExpanded ? (
                        <>
                          <ChevronUp className="h-3 w-3" /> Hide details
                        </>
                      ) : (
                        <>
                          <ChevronDown className="h-3 w-3" /> Show details
                        </>
                      )}
                    </button>
                  )}

                  {isExpanded && run.comparison_details && (
                    <ComparisonDetails data={run.comparison_details} />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ── Comparison details sub-component ────────────────────────── */

interface ComparisonEntry {
  section_number?: string;
  title?: string;
  old_status?: string;
  new_status?: string;
  severity?: string;
}

function ComparisonDetails({ data }: { data: Record<string, unknown> }) {
  let items: ComparisonEntry[] = [];
  try {
    // comparison_details has regressed + improved arrays with rule data
    const regressed = Array.isArray(data.regressed) ? data.regressed : [];
    const improved = Array.isArray(data.improved) ? data.improved : [];
    items = [
      ...regressed.map((r: any) => ({
        section_number: r.section,
        title: r.rule_title,
        old_status: r.old || 'PASS',
        new_status: r.new || 'FAIL',
        severity: r.severity,
      })),
      ...improved.map((r: any) => ({
        section_number: r.section,
        title: r.rule_title,
        old_status: r.old || 'FAIL',
        new_status: r.new || 'PASS',
        severity: r.severity,
      })),
    ];
  } catch {
    return (
      <p className="mt-2 text-xs text-dark-muted italic">Could not parse comparison data.</p>
    );
  }

  if (items.length === 0) {
    return (
      <p className="mt-2 text-xs text-dark-muted italic">No comparison details available.</p>
    );
  }

  return (
    <div className="mt-2 rounded-lg border border-dark-border/50 bg-dark-elevated/50 overflow-hidden">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-dark-border/50 text-dark-muted uppercase tracking-wider">
            <th className="text-left px-3 py-1.5 font-semibold">Rule</th>
            <th className="text-center px-2 py-1.5 font-semibold w-20">Before</th>
            <th className="text-center px-2 py-1.5 font-semibold w-20">After</th>
          </tr>
        </thead>
        <tbody>
          {items.slice(0, 20).map((item, i) => {
            const regressed =
              item.old_status === 'PASS' && item.new_status === 'FAIL';
            const improved =
              item.old_status === 'FAIL' && item.new_status === 'PASS';
            return (
              <tr
                key={i}
                className={`border-b border-dark-border/30 last:border-0 ${
                  regressed
                    ? 'bg-red-500/5'
                    : improved
                      ? 'bg-emerald-500/5'
                      : ''
                }`}
              >
                <td className="px-3 py-1.5 text-dark-secondary truncate max-w-[200px]">
                  <span className="text-dark-muted font-mono mr-1">
                    {item.section_number}
                  </span>
                  {item.title}
                </td>
                <td className="text-center px-2 py-1.5">
                  <StatusPill status={item.old_status} />
                </td>
                <td className="text-center px-2 py-1.5">
                  <StatusPill status={item.new_status} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {items.length > 20 && (
        <div className="px-3 py-1.5 text-[10px] text-dark-muted text-center border-t border-dark-border/30">
          + {items.length - 20} more changes
        </div>
      )}
    </div>
  );
}

function StatusPill({ status }: { status?: string }) {
  if (!status) return <span className="text-dark-muted">--</span>;
  const upper = status.toUpperCase();
  const cls =
    upper === 'PASS'
      ? 'bg-emerald-500/15 text-emerald-400'
      : upper === 'FAIL'
        ? 'bg-red-500/15 text-red-400'
        : 'bg-dark-overlay text-dark-muted';
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold ${cls}`}>
      {upper}
    </span>
  );
}
