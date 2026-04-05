/**
 * Shared date/time formatting utilities for AuditForge.
 *
 * The backend stores UTC timestamps but historically serialised them
 * *without* a trailing "Z".  `ensureUtc()` is a defence-in-depth guard
 * that appends "Z" when no timezone indicator is present so that
 * `new Date()` always interprets the string as UTC.
 */

/** Append "Z" if the ISO string has no timezone indicator (+/- offset or Z). */
export function ensureUtc(iso: string): string {
  if (!iso) return iso;
  // Already has timezone info
  if (iso.endsWith('Z') || iso.endsWith('z') || /[+-]\d{2}:\d{2}$/.test(iso)) {
    return iso;
  }
  return iso + 'Z';
}

/**
 * Human-friendly relative time: "just now", "3m ago", "2h ago", "5d ago".
 * Handles both past and future timestamps.
 */
export function formatTimeAgo(iso: string): string {
  const diff = Date.now() - new Date(ensureUtc(iso)).getTime();
  const absDiff = Math.abs(diff);
  const isPast = diff >= 0;

  const mins = Math.floor(absDiff / 60_000);
  if (mins < 1) return isPast ? 'just now' : 'in a moment';

  const hrs = Math.floor(mins / 60);
  if (mins < 60) return isPast ? `${mins}m ago` : `in ${mins}m`;

  const days = Math.floor(hrs / 24);
  if (hrs < 24) return isPast ? `${hrs}h ago` : `in ${hrs}h`;

  if (days < 30) return isPast ? `${days}d ago` : `in ${days}d`;

  const months = Math.floor(days / 30);
  return isPast ? `${months}mo ago` : `in ${months}mo`;
}

/**
 * Locale-aware date+time display.
 * Example: "Apr 2, 19:14" or "Apr 2, 7:14 PM" depending on locale.
 */
export function formatDateTime(iso: string): string {
  const d = new Date(ensureUtc(iso));
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Rich relative time for schedule "next run" display.
 * Handles past, future, "yesterday", "tomorrow at HH:MM", etc.
 */
export function formatDistanceToNow(iso: string): string {
  const target = new Date(ensureUtc(iso)).getTime();
  const now = Date.now();
  const diffMs = target - now;
  const absDiff = Math.abs(diffMs);
  const isPast = diffMs < 0;

  const mins = Math.floor(absDiff / 60_000);
  const hrs = Math.floor(mins / 60);
  const days = Math.floor(hrs / 24);

  if (mins < 1) return isPast ? 'just now' : 'in less than a minute';

  let label: string;
  if (mins < 60) {
    label = `${mins} minute${mins !== 1 ? 's' : ''}`;
  } else if (hrs < 24) {
    const remainMins = mins % 60;
    if (hrs < 6 && remainMins > 0) {
      label = `${hrs}h ${remainMins}m`;
    } else {
      label = `${hrs} hour${hrs !== 1 ? 's' : ''}`;
    }
  } else if (days === 1) {
    const d = new Date(ensureUtc(iso));
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return isPast ? `yesterday at ${hh}:${mm}` : `tomorrow at ${hh}:${mm}`;
  } else if (days < 30) {
    label = `${days} day${days !== 1 ? 's' : ''}`;
  } else {
    const months = Math.floor(days / 30);
    label = `${months} month${months !== 1 ? 's' : ''}`;
  }

  return isPast ? `${label} ago` : `in ${label}`;
}
