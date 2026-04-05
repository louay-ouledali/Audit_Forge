import { useState } from 'react';
import {
  Play,
  Pencil,
  Trash2,
  Bell,
  Mail,
  MessageSquare,
  ArrowUp,
  ArrowDown,
  Clock,
  Loader2,
} from 'lucide-react';
import type { Schedule } from '@/types';
import { formatDistanceToNow } from '@/utils/time';

/* ── Helpers ─────────────────────────────────────────────────── */

const FREQ_BADGE: Record<string, string> = {
  daily: 'bg-blue-500/15 text-blue-400 border-blue-500/20',
  weekly: 'bg-purple-500/15 text-purple-400 border-purple-500/20',
  monthly: 'bg-amber-500/15 text-amber-400 border-amber-500/20',
  custom: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/20',
};

/* ── Props ───────────────────────────────────────────────────── */

interface ScheduleCardProps {
  schedule: Schedule;
  isSelected: boolean;
  onSelect: () => void;
  onToggle: () => void;
  onRunNow: () => void;
  onEdit: () => void;
  onDelete: () => void;
  isLocked: boolean;
  isToggling?: boolean;
  isRunning?: boolean;
}

/* ── Component ───────────────────────────────────────────────── */

export default function ScheduleCard({
  schedule,
  isSelected,
  onSelect,
  onToggle,
  onRunNow,
  onEdit,
  onDelete,
  isLocked,
  isToggling,
  isRunning,
}: ScheduleCardProps) {
  const [hovered, setHovered] = useState(false);

  const channels: string[] = Array.isArray(schedule.alert_channels) ? schedule.alert_channels : [];

  /* Compliance color */
  const compliance = schedule.last_compliance;
  let complianceColor = 'text-dark-muted';
  let complianceBg = '';
  if (compliance != null) {
    if (compliance >= 80) {
      complianceColor = 'text-emerald-400';
      complianceBg = 'bg-emerald-500/10';
    } else if (compliance >= 60) {
      complianceColor = 'text-amber-400';
      complianceBg = 'bg-amber-500/10';
    } else {
      complianceColor = 'text-red-400';
      complianceBg = 'bg-red-500/10';
    }
  }

  /* Border classes */
  const borderClass = isSelected
    ? 'border-ey-yellow/50 ring-1 ring-ey-yellow/20'
    : 'border-dark-border';

  const freqBadge = FREQ_BADGE[schedule.frequency] || FREQ_BADGE.custom;

  return (
    <div
      onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={`group relative cursor-pointer rounded-xl border bg-dark-card p-4 transition-all duration-200 ${borderClass} ${hovered && !isSelected ? 'bg-dark-border/30' : ''}`}
    >
      {/* ── Header row: name + frequency + toggle ─────────────── */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h4 className="truncate text-sm font-bold text-white">
              {schedule.name}
            </h4>
            <span
              className={`shrink-0 inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest ${freqBadge}`}
            >
              {schedule.frequency}
            </span>
          </div>
        </div>

        {/* Toggle switch */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onToggle();
          }}
          disabled={isLocked || isToggling}
          className="shrink-0 disabled:opacity-30 disabled:cursor-not-allowed"
          title={isLocked ? 'Mission is locked' : schedule.enabled ? 'Disable schedule' : 'Enable schedule'}
        >
          {isToggling ? (
            <Loader2 className="h-5 w-5 text-dark-muted animate-spin" />
          ) : (
            <div
              className={`relative h-5 w-9 rounded-full transition-colors duration-200 ${
                schedule.enabled ? 'bg-ey-yellow' : 'bg-dark-overlay'
              }`}
            >
              <div
                className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                  schedule.enabled ? 'translate-x-[18px]' : 'translate-x-0.5'
                }`}
              />
            </div>
          )}
        </button>
      </div>

      {/* ── Next run ──────────────────────────────────────────── */}
      <div className="mt-3 flex items-center gap-1.5 text-xs text-dark-secondary">
        <Clock className="h-3 w-3 text-dark-muted" />
        <span>
          Next run:{' '}
          <span className={schedule.enabled ? 'text-white font-medium' : 'text-dark-muted'}>
            {schedule.enabled ? formatDistanceToNow(schedule.next_run_at) : 'paused'}
          </span>
        </span>
      </div>

      {/* ── Last compliance ───────────────────────────────────── */}
      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs text-dark-muted">Last compliance</span>
        {compliance != null ? (
          <div className="flex items-center gap-1.5">
            <span
              className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-bold ${complianceColor} ${complianceBg}`}
            >
              {compliance.toFixed(1)}%
            </span>
            {/* Delta arrow from last run data */}
            {schedule.last_run_status === 'completed' && (
              <ComplianceDelta delta={schedule.compliance_delta ?? null} />
            )}
          </div>
        ) : (
          <span className="text-xs text-dark-muted">--</span>
        )}
      </div>

      {/* ── Alert channel icons ───────────────────────────────── */}
      {channels.length > 0 && (
        <div className="mt-2.5 flex items-center gap-2">
          {channels.includes('in_app') && (
            <Bell className="h-3.5 w-3.5 text-dark-muted" title="In-app notifications" />
          )}
          {channels.includes('email') && (
            <Mail className="h-3.5 w-3.5 text-dark-muted" title="Email alerts" />
          )}
          {channels.includes('slack') && (
            <MessageSquare className="h-3.5 w-3.5 text-dark-muted" title="Slack alerts" />
          )}
        </div>
      )}

      {/* ── Quick action row ──────────────────────────────────── */}
      <div className="mt-3 flex items-center gap-1 border-t border-dark-border/50 pt-3">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRunNow();
          }}
          disabled={isLocked || !schedule.enabled || isRunning}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-dark-secondary transition-colors hover:bg-ey-yellow/10 hover:text-ey-yellow disabled:opacity-30 disabled:cursor-not-allowed"
          title={isLocked ? 'Mission is locked' : 'Run now'}
        >
          {isRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />} Run Now
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onEdit();
          }}
          disabled={isLocked}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-dark-secondary transition-colors hover:bg-dark-overlay hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
          title={isLocked ? 'Mission is locked' : 'Edit schedule'}
        >
          <Pencil className="h-3 w-3" /> Edit
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          disabled={isLocked}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-dark-secondary transition-colors hover:bg-red-500/10 hover:text-red-400 disabled:opacity-30 disabled:cursor-not-allowed"
          title={isLocked ? 'Mission is locked' : 'Delete schedule'}
        >
          <Trash2 className="h-3 w-3" /> Delete
        </button>
      </div>
    </div>
  );
}

/* ── Exported delta renderer for external use ──────────────────── */

export function ComplianceDelta({ delta }: { delta: number | null | undefined }) {
  if (delta == null || delta === 0) return null;
  const isPositive = delta > 0;
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-[11px] font-semibold ${
        isPositive ? 'text-emerald-400' : 'text-red-400'
      }`}
    >
      {isPositive ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
      {isPositive ? '+' : ''}
      {delta.toFixed(1)}%
    </span>
  );
}
