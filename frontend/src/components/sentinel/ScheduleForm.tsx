import { useState, useMemo, useCallback } from 'react';
import {
  Save,
  X,
  Clock,
  Bell,
  Monitor,
  Terminal,
  Network,
  Database,
  HelpCircle,
  ChevronDown,
  FileText,
  ShieldAlert,
  AlertTriangle,
  CheckSquare,
  Square,
  Loader2,
  Send,
  Mail,
  MessageSquare,
  BellRing,
} from 'lucide-react';
import type { Target, Schedule } from '@/types';
import { createSchedule, updateSchedule, testScheduleAlerts } from '@/services/api';
import { useToast } from '@/components/common/Toast';

/* ── Props ────────────────────────────────────────────────── */
interface ScheduleFormProps {
  missionId: number;
  targets: Target[];
  schedule?: Schedule | null;
  onSave: () => void;
  onCancel: () => void;
}

/* ── Platform icon map ────────────────────────────────────── */
const PLT: Record<string, { icon: typeof Monitor; color: string }> = {
  windows:  { icon: Monitor,  color: 'text-sky-400' },
  linux:    { icon: Terminal,  color: 'text-emerald-400' },
  network:  { icon: Network,  color: 'text-purple-400' },
  database: { icon: Database,  color: 'text-orange-400' },
};

/* ── Shared style tokens ──────────────────────────────────── */
const inputCls =
  'w-full bg-dark-bg border border-dark-border rounded-lg px-3 py-2 text-white text-sm focus:border-ey-yellow/50 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20 transition-colors placeholder-dark-muted';
const selectCls =
  'w-full bg-dark-bg border border-dark-border rounded-lg px-3 py-2 text-white text-sm focus:border-ey-yellow/50 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20 transition-colors appearance-none';
const labelCls = 'block text-xs font-semibold text-dark-secondary mb-1.5';
const sectionTitle = 'text-sm font-semibold text-white uppercase tracking-wider mb-3';

/* ── Day abbreviations ────────────────────────────────────── */
const WEEKDAYS = [
  { label: 'Mon', value: 0 },
  { label: 'Tue', value: 1 },
  { label: 'Wed', value: 2 },
  { label: 'Thu', value: 3 },
  { label: 'Fri', value: 4 },
  { label: 'Sat', value: 5 },
  { label: 'Sun', value: 6 },
] as const;

type Frequency = 'daily' | 'weekly' | 'monthly' | 'custom';
type AlertChannel = 'in_app' | 'email' | 'slack';
type ReportFormat = 'pdf' | 'html' | 'excel';

/* ── Toggle switch component ──────────────────────────────── */
function Toggle({
  checked,
  onChange,
  disabled = false,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={() => !disabled && onChange(!checked)}
      className={`
        relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors
        ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
        ${checked ? 'bg-ey-yellow' : 'bg-dark-border'}
      `}
    >
      <span
        className={`
          inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform
          ${checked ? 'translate-x-[18px]' : 'translate-x-[3px]'}
        `}
      />
    </button>
  );
}

/* ── Custom checkbox ──────────────────────────────────────── */
function Checkbox({
  checked,
  onChange,
  disabled = false,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  const Icon = checked ? CheckSquare : Square;
  return (
    <button
      type="button"
      onClick={() => !disabled && onChange(!checked)}
      className={`shrink-0 ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      <Icon
        className={`h-4 w-4 ${
          checked ? 'text-ey-yellow' : 'text-dark-muted'
        } transition-colors`}
      />
    </button>
  );
}

/* ════════════════════════════════════════════════════════════ */
/*  ScheduleForm                                               */
/* ════════════════════════════════════════════════════════════ */

export default function ScheduleForm({
  missionId,
  targets,
  schedule,
  onSave,
  onCancel,
}: ScheduleFormProps) {
  const toast = useToast();
  const isEdit = !!schedule;

  /* ── Parse existing schedule values ─────────────────────── */
  const existingTargetIds: number[] = useMemo(() => {
    if (!schedule?.target_ids) return [];
    return Array.isArray(schedule.target_ids) ? schedule.target_ids : [];
  }, [schedule]);

  const existingChannels: AlertChannel[] = useMemo(() => {
    if (!schedule?.alert_channels) return ['in_app'];
    return Array.isArray(schedule.alert_channels) ? schedule.alert_channels as AlertChannel[] : ['in_app'];
  }, [schedule]);

  /* ── Form state ─────────────────────────────────────────── */
  const [name, setName] = useState(schedule?.name ?? '');
  const [selectedTargetIds, setSelectedTargetIds] = useState<Set<number>>(
    new Set(existingTargetIds),
  );
  const [frequency, setFrequency] = useState<Frequency>(schedule?.frequency ?? 'daily');
  const [dayOfWeek, setDayOfWeek] = useState<number | null>(schedule?.day_of_week ?? 0);
  const [dayOfMonth, setDayOfMonth] = useState<number | null>(schedule?.day_of_month ?? 1);
  const [timeOfDay, setTimeOfDay] = useState(schedule?.time_of_day ?? '02:00');
  const [customIntervalHours, setCustomIntervalHours] = useState<number | null>(
    schedule?.custom_interval_hours ?? 24,
  );

  // Alert channels
  const [emailEnabled, setEmailEnabled] = useState(existingChannels.includes('email'));
  const [slackEnabled, setSlackEnabled] = useState(existingChannels.includes('slack'));
  const [alertEmails, setAlertEmails] = useState(schedule?.alert_emails ?? '');
  const [slackWebhookUrl, setSlackWebhookUrl] = useState(schedule?.slack_webhook_url ?? '');

  // Thresholds
  const [notifyOnRegression, setNotifyOnRegression] = useState(schedule?.notify_on_regression ?? true);
  const [regressionThreshold, setRegressionThreshold] = useState(schedule?.regression_threshold ?? 5);
  const [notifyOnCritical, setNotifyOnCritical] = useState(schedule?.notify_on_critical ?? true);

  // Auto-report
  const [autoGenerateReport, setAutoGenerateReport] = useState(schedule?.auto_generate_report ?? false);
  const [reportFormat, setReportFormat] = useState<ReportFormat>(
    (schedule?.report_format as ReportFormat) ?? 'pdf',
  );

  // UI state
  const [saving, setSaving] = useState(false);
  const [testingAlerts, setTestingAlerts] = useState(false);

  /* ── Target selection helpers ────────────────────────────── */
  const allSelected = targets.length > 0 && selectedTargetIds.size === targets.length;

  const toggleTarget = useCallback((id: number) => {
    setSelectedTargetIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    if (allSelected) {
      setSelectedTargetIds(new Set());
    } else {
      setSelectedTargetIds(new Set(targets.map(t => t.id)));
    }
  }, [allSelected, targets]);

  /* ── Build alert channels array ─────────────────────────── */
  const buildChannels = useCallback((): AlertChannel[] => {
    const ch: AlertChannel[] = ['in_app'];
    if (emailEnabled) ch.push('email');
    if (slackEnabled) ch.push('slack');
    return ch;
  }, [emailEnabled, slackEnabled]);

  /* ── Submit ─────────────────────────────────────────────── */
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validation
    if (!name.trim()) {
      toast.error('Schedule name is required.');
      return;
    }
    if (selectedTargetIds.size === 0) {
      toast.error('Select at least one target.');
      return;
    }
    if (emailEnabled && !alertEmails.trim()) {
      toast.error('Enter at least one email address.');
      return;
    }
    if (slackEnabled && !slackWebhookUrl.trim()) {
      toast.error('Enter a Slack webhook URL.');
      return;
    }

    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        name: name.trim(),
        mission_id: missionId,
        target_ids: Array.from(selectedTargetIds),
        frequency,
        day_of_week: frequency === 'weekly' ? dayOfWeek : null,
        day_of_month: frequency === 'monthly' ? dayOfMonth : null,
        time_of_day: timeOfDay,
        custom_interval_hours: frequency === 'custom' ? customIntervalHours : null,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        alert_channels: buildChannels(),
        alert_emails: emailEnabled ? alertEmails.trim() : null,
        slack_webhook_url: slackEnabled ? slackWebhookUrl.trim() : null,
        notify_on_regression: notifyOnRegression,
        regression_threshold: regressionThreshold,
        notify_on_critical: notifyOnCritical,
        auto_generate_report: autoGenerateReport,
        report_format: autoGenerateReport ? reportFormat : 'pdf',
      };

      if (isEdit && schedule) {
        await updateSchedule(schedule.id, payload);
        toast.success('Schedule updated successfully.');
      } else {
        await createSchedule(payload);
        toast.success('Schedule created successfully.');
      }
      onSave();
    } catch (err: any) {
      const msg = err?.response?.data?.detail ?? err?.message ?? 'Failed to save schedule.';
      toast.error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setSaving(false);
    }
  };

  /* ── Test alerts ────────────────────────────────────────── */
  const handleTestAlerts = async () => {
    if (!schedule?.id) return;
    setTestingAlerts(true);
    try {
      await testScheduleAlerts(schedule.id);
      toast.success('Test alerts sent successfully.');
    } catch (err: any) {
      const msg = err?.response?.data?.detail ?? err?.message ?? 'Failed to send test alerts.';
      toast.error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setTestingAlerts(false);
    }
  };

  /* ── Render ─────────────────────────────────────────────── */
  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* ── Header ────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-white">
          {isEdit ? 'Edit Schedule' : 'New Schedule'}
        </h2>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg p-1.5 text-dark-muted hover:text-white hover:bg-dark-elevated transition-colors"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* ── Name ──────────────────────────────────────────── */}
      <div>
        <label className={labelCls}>Schedule Name</label>
        <input
          type="text"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="e.g. Weekly Linux Compliance Check"
          className={inputCls}
          required
        />
      </div>

      {/* ── Target Selection ──────────────────────────────── */}
      <div>
        <h3 className={sectionTitle}>Targets</h3>
        <div className="rounded-lg border border-dark-border bg-dark-bg p-3 space-y-2">
          {/* Select All */}
          <button
            type="button"
            onClick={toggleAll}
            className="flex items-center gap-2 text-xs font-medium text-dark-secondary hover:text-white transition-colors w-full pb-2 border-b border-dark-border/50"
          >
            <Checkbox checked={allSelected} onChange={() => {}} />
            <span>Select All ({targets.length} targets)</span>
          </button>

          {/* Target list */}
          <div className="max-h-48 overflow-y-auto space-y-1 custom-scrollbar">
            {targets.length === 0 && (
              <p className="text-xs text-dark-muted py-2 text-center">
                No targets available for this mission.
              </p>
            )}
            {targets.map(t => {
              const pl =
                PLT[(t.target_type || '').toLowerCase()] ?? {
                  icon: HelpCircle,
                  color: 'text-dark-muted',
                };
              const PlatIcon = pl.icon;
              const checked = selectedTargetIds.has(t.id);
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => toggleTarget(t.id)}
                  className={`
                    flex items-center gap-2.5 w-full rounded-md px-2.5 py-1.5 text-xs transition-colors text-left
                    ${checked ? 'bg-ey-yellow/10 border border-ey-yellow/20' : 'bg-dark-elevated/40 border border-transparent hover:bg-dark-elevated'}
                  `}
                >
                  <Checkbox checked={checked} onChange={() => toggleTarget(t.id)} />
                  <PlatIcon className={`h-3.5 w-3.5 shrink-0 ${pl.color}`} />
                  <span className="font-medium text-white truncate flex-1">
                    {t.hostname || t.ip_address || `Target #${t.id}`}
                  </span>
                  {t.ip_address && t.hostname && (
                    <span className="text-dark-muted text-[11px] shrink-0">{t.ip_address}</span>
                  )}
                </button>
              );
            })}
          </div>

          {selectedTargetIds.size > 0 && (
            <p className="text-[11px] text-ey-yellow/70 pt-1">
              {selectedTargetIds.size} target{selectedTargetIds.size !== 1 ? 's' : ''} selected
            </p>
          )}
        </div>
      </div>

      {/* ── Frequency & Time ──────────────────────────────── */}
      <div>
        <h3 className={sectionTitle}>
          <Clock className="inline h-4 w-4 mr-1.5 -mt-0.5" />
          Schedule
        </h3>

        <div className="grid grid-cols-2 gap-4">
          {/* Frequency */}
          <div>
            <label className={labelCls}>Frequency</label>
            <div className="relative">
              <select
                value={frequency}
                onChange={e => setFrequency(e.target.value as Frequency)}
                className={selectCls}
              >
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
                <option value="custom">Custom</option>
              </select>
              <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-dark-muted" />
            </div>
          </div>

          {/* Time of day */}
          <div>
            <label className={labelCls}>Time of Day</label>
            <input
              type="time"
              value={timeOfDay}
              onChange={e => setTimeOfDay(e.target.value)}
              className={inputCls}
            />
          </div>
        </div>

        {/* Weekly: day-of-week pills */}
        {frequency === 'weekly' && (
          <div className="mt-3">
            <label className={labelCls}>Day of Week</label>
            <div className="flex gap-1.5">
              {WEEKDAYS.map(d => (
                <button
                  key={d.value}
                  type="button"
                  onClick={() => setDayOfWeek(d.value)}
                  className={`
                    px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
                    ${dayOfWeek === d.value
                      ? 'bg-ey-yellow text-dark-bg'
                      : 'bg-dark-elevated text-dark-secondary hover:text-white hover:bg-dark-elevated/80'}
                  `}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Monthly: day-of-month */}
        {frequency === 'monthly' && (
          <div className="mt-3">
            <label className={labelCls}>Day of Month</label>
            <input
              type="number"
              min={1}
              max={28}
              value={dayOfMonth ?? 1}
              onChange={e => setDayOfMonth(Math.min(28, Math.max(1, parseInt(e.target.value) || 1)))}
              className={`${inputCls} w-24`}
            />
            <p className="text-[11px] text-dark-muted mt-1">Range: 1-28 (to avoid month-end issues)</p>
          </div>
        )}

        {/* Custom: interval hours */}
        {frequency === 'custom' && (
          <div className="mt-3">
            <label className={labelCls}>Interval (hours)</label>
            <input
              type="number"
              min={1}
              max={720}
              value={customIntervalHours ?? 24}
              onChange={e => setCustomIntervalHours(Math.max(1, parseInt(e.target.value) || 1))}
              className={`${inputCls} w-32`}
            />
            <p className="text-[11px] text-dark-muted mt-1">
              Runs every {customIntervalHours ?? 24}h ({((customIntervalHours ?? 24) / 24).toFixed(1)} days)
            </p>
          </div>
        )}
      </div>

      {/* ── Alert Configuration ───────────────────────────── */}
      <div>
        <h3 className={sectionTitle}>
          <Bell className="inline h-4 w-4 mr-1.5 -mt-0.5" />
          Alert Channels
        </h3>

        <div className="space-y-3">
          {/* In-App (always on) */}
          <div className="flex items-center justify-between rounded-lg bg-dark-elevated/50 px-3 py-2.5">
            <div className="flex items-center gap-2.5">
              <BellRing className="h-4 w-4 text-ey-yellow" />
              <span className="text-sm text-white font-medium">In-App Notifications</span>
            </div>
            <Checkbox checked={true} onChange={() => {}} disabled />
          </div>

          {/* Email */}
          <div className="rounded-lg bg-dark-elevated/50 px-3 py-2.5 space-y-2.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <Mail className="h-4 w-4 text-sky-400" />
                <span className="text-sm text-white font-medium">Email</span>
              </div>
              <Toggle checked={emailEnabled} onChange={setEmailEnabled} />
            </div>
            {emailEnabled && (
              <div>
                <label className={labelCls}>Recipients (comma-separated)</label>
                <input
                  type="text"
                  value={alertEmails}
                  onChange={e => setAlertEmails(e.target.value)}
                  placeholder="auditor@company.com, team@company.com"
                  className={inputCls}
                />
              </div>
            )}
          </div>

          {/* Slack */}
          <div className="rounded-lg bg-dark-elevated/50 px-3 py-2.5 space-y-2.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <MessageSquare className="h-4 w-4 text-purple-400" />
                <span className="text-sm text-white font-medium">Slack</span>
              </div>
              <Toggle checked={slackEnabled} onChange={setSlackEnabled} />
            </div>
            {slackEnabled && (
              <div>
                <label className={labelCls}>Webhook URL</label>
                <input
                  type="url"
                  value={slackWebhookUrl}
                  onChange={e => setSlackWebhookUrl(e.target.value)}
                  placeholder="https://hooks.slack.com/services/..."
                  className={inputCls}
                />
              </div>
            )}
          </div>

          {/* Test Alerts button (edit mode only) */}
          {isEdit && schedule?.id && (
            <button
              type="button"
              onClick={handleTestAlerts}
              disabled={testingAlerts}
              className="flex items-center gap-2 rounded-lg bg-dark-elevated px-4 py-2 text-sm font-medium text-dark-secondary hover:text-white hover:bg-dark-elevated/80 transition-colors disabled:opacity-50"
            >
              {testingAlerts ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              {testingAlerts ? 'Sending...' : 'Test Alerts'}
            </button>
          )}
        </div>
      </div>

      {/* ── Thresholds ────────────────────────────────────── */}
      <div>
        <h3 className={sectionTitle}>
          <ShieldAlert className="inline h-4 w-4 mr-1.5 -mt-0.5" />
          Thresholds
        </h3>

        <div className="space-y-4">
          {/* Regression alert */}
          <div className="rounded-lg bg-dark-elevated/50 px-3 py-3 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <AlertTriangle className="h-4 w-4 text-amber-400" />
                <span className="text-sm text-white font-medium">Alert on compliance regression</span>
              </div>
              <Toggle checked={notifyOnRegression} onChange={setNotifyOnRegression} />
            </div>
            {notifyOnRegression && (
              <div className="pl-6.5">
                <label className={labelCls}>
                  Threshold: <span className="text-ey-yellow">{regressionThreshold}%</span>
                </label>
                <input
                  type="range"
                  min={1}
                  max={20}
                  value={regressionThreshold}
                  onChange={e => setRegressionThreshold(parseInt(e.target.value))}
                  className="w-full h-1.5 rounded-full appearance-none cursor-pointer
                    bg-dark-border
                    [&::-webkit-slider-thumb]:appearance-none
                    [&::-webkit-slider-thumb]:w-4
                    [&::-webkit-slider-thumb]:h-4
                    [&::-webkit-slider-thumb]:rounded-full
                    [&::-webkit-slider-thumb]:bg-ey-yellow
                    [&::-webkit-slider-thumb]:shadow-md
                    [&::-webkit-slider-thumb]:cursor-pointer
                    [&::-moz-range-thumb]:w-4
                    [&::-moz-range-thumb]:h-4
                    [&::-moz-range-thumb]:rounded-full
                    [&::-moz-range-thumb]:bg-ey-yellow
                    [&::-moz-range-thumb]:border-none
                    [&::-moz-range-thumb]:shadow-md
                    [&::-moz-range-thumb]:cursor-pointer"
                />
                <div className="flex justify-between text-[10px] text-dark-muted mt-0.5">
                  <span>1%</span>
                  <span>20%</span>
                </div>
              </div>
            )}
          </div>

          {/* Critical openings alert */}
          <div className="flex items-center justify-between rounded-lg bg-dark-elevated/50 px-3 py-3">
            <div className="flex items-center gap-2.5">
              <ShieldAlert className="h-4 w-4 text-red-400" />
              <div>
                <span className="text-sm text-white font-medium block">Alert on critical openings</span>
                <span className="text-[11px] text-dark-muted">
                  Triggers when a high/critical rule changes from PASS to FAIL
                </span>
              </div>
            </div>
            <Toggle checked={notifyOnCritical} onChange={setNotifyOnCritical} />
          </div>
        </div>
      </div>

      {/* ── Auto-Report ───────────────────────────────────── */}
      <div>
        <h3 className={sectionTitle}>
          <FileText className="inline h-4 w-4 mr-1.5 -mt-0.5" />
          Auto-Report
        </h3>

        <div className="rounded-lg bg-dark-elevated/50 px-3 py-3 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-white font-medium">Generate report after each run</span>
            <Toggle checked={autoGenerateReport} onChange={setAutoGenerateReport} />
          </div>

          {autoGenerateReport && (
            <div>
              <label className={labelCls}>Report Format</label>
              <div className="flex gap-2">
                {(['pdf', 'html', 'excel'] as ReportFormat[]).map(fmt => (
                  <button
                    key={fmt}
                    type="button"
                    onClick={() => setReportFormat(fmt)}
                    className={`
                      px-4 py-1.5 rounded-lg text-xs font-medium uppercase transition-colors
                      ${reportFormat === fmt
                        ? 'bg-ey-yellow text-dark-bg'
                        : 'bg-dark-bg text-dark-secondary border border-dark-border hover:text-white hover:border-dark-muted'}
                    `}
                  >
                    {fmt}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Actions ───────────────────────────────────────── */}
      <div className="flex items-center justify-end gap-3 pt-2 border-t border-dark-border/50">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg bg-dark-elevated px-5 py-2 text-sm font-medium text-dark-secondary hover:text-white transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="flex items-center gap-2 rounded-lg bg-ey-yellow px-5 py-2 text-sm font-bold text-dark-bg hover:bg-ey-yellow/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          {saving ? 'Saving...' : isEdit ? 'Update Schedule' : 'Create Schedule'}
        </button>
      </div>
    </form>
  );
}
