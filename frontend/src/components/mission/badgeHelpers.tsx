/* ── Shared badge helpers for mission components ─────────────── */

export const STATUS_STYLES: Record<string, string> = {
  in_progress: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20',
  completed: 'bg-sky-500/10 text-sky-400 ring-sky-500/20',
  cancelled: 'bg-dark-overlay text-dark-secondary ring-dark-border',
};

export const STATUS_LABELS: Record<string, string> = {
  in_progress: 'In Progress',
  completed: 'Completed',
  cancelled: 'Cancelled',
};

export const inputClass =
  'block w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none';

export function scanStatusBadge(status: string) {
  const styles: Record<string, string> = {
    running: 'bg-sky-500/10 text-sky-400',
    completed: 'bg-emerald-500/10 text-emerald-400',
    imported: 'bg-emerald-500/10 text-emerald-400',
    failed: 'bg-red-500/10 text-red-400',
    cancelled: 'bg-amber-500/10 text-amber-400',
    pending: 'bg-dark-overlay text-dark-secondary',
    cancelling: 'bg-amber-500/10 text-amber-400',
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status] || styles.pending}`}
    >
      {status}
    </span>
  );
}

export function findingStatusBadge(status: string) {
  const styles: Record<string, string> = {
    PASS: 'bg-green-500/10 text-green-400',
    FAIL: 'bg-red-500/10 text-red-400',
    ERROR: 'bg-yellow-500/10 text-yellow-400',
    MANUAL_REVIEW: 'bg-blue-500/10 text-blue-400',
    NOT_APPLICABLE: 'bg-dark-overlay text-dark-muted',
    SKIPPED: 'bg-dark-overlay text-dark-muted',
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status] || 'bg-dark-overlay text-dark-muted'}`}
    >
      {status}
    </span>
  );
}

export function severityBadge(severity: string | null) {
  if (!severity) return null;
  const styles: Record<string, string> = {
    critical: 'bg-red-500/10 text-red-400',
    high: 'bg-orange-500/10 text-orange-400',
    medium: 'bg-yellow-500/10 text-yellow-400',
    low: 'bg-green-500/10 text-green-400',
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[severity] || 'bg-dark-overlay text-dark-muted'}`}
    >
      {severity}
    </span>
  );
}
