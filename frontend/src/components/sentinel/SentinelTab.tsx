import { useState, useEffect, useCallback } from 'react';
import {
  Shield,
  Plus,
  Calendar,
  Clock,
  Trash2,
  Play,
  Power,
  Loader2,
} from 'lucide-react';
import type { Schedule, Target } from '@/types';
import {
  getSchedules,
  deleteSchedule,
  toggleSchedule,
  runScheduleNow,
} from '@/services/api';
import BrandLockup from '@/components/common/BrandLockup';
import { useToast } from '@/components/common/Toast';
import { extractApiError } from '@/utils/apiError';
import ScheduleCard from './ScheduleCard';
import ScheduleForm from './ScheduleForm';
import RunTimeline from './RunTimeline';

/* ── Props ─────────────────────────────────────────────────── */

interface SentinelTabProps {
  missionId: number;
  missionTargets: Target[];
  isLocked: boolean;
}

/* ── Component ─────────────────────────────────────────────── */

export default function SentinelTab({ missionId, missionTargets, isLocked }: SentinelTabProps) {
  const toast = useToast();

  /* ── State ───────────────────────────────────────────────── */
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [selectedSchedule, setSelectedSchedule] = useState<Schedule | null>(null);
  const [mode, setMode] = useState<'list' | 'create' | 'edit'>('list');
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [togglingId, setTogglingId] = useState<number | null>(null);
  const [runningId, setRunningId] = useState<number | null>(null);

  /* ── Data fetching ───────────────────────────────────────── */

  const fetchSchedules = useCallback(async () => {
    try {
      setLoading(true);
      const data = await getSchedules(missionId);
      setSchedules(Array.isArray(data) ? data : []);
    } catch (err) {
      toast.error(extractApiError(err, 'Failed to load schedules'));
    } finally {
      setLoading(false);
    }
  }, [missionId, toast]);

  useEffect(() => {
    fetchSchedules();
  }, [fetchSchedules]);

  /* ── Handlers ────────────────────────────────────────────── */

  const handleCreateOpen = () => {
    setSelectedSchedule(null);
    setMode('create');
  };

  const handleEditOpen = (schedule: Schedule) => {
    setSelectedSchedule(schedule);
    setMode('edit');
  };

  const handleSelectSchedule = (schedule: Schedule) => {
    setSelectedSchedule(schedule);
    setMode('list');
  };

  const handleFormCancel = () => {
    setMode('list');
  };

  const handleFormSaved = async () => {
    setMode('list');
    setSelectedSchedule(null);
    await fetchSchedules();
  };

  const handleDelete = async (scheduleId: number) => {
    try {
      setDeletingId(scheduleId);
      await deleteSchedule(scheduleId);
      toast.success('Schedule deleted');
      if (selectedSchedule?.id === scheduleId) {
        setSelectedSchedule(null);
        setMode('list');
      }
      await fetchSchedules();
    } catch (err) {
      toast.error(extractApiError(err, 'Failed to delete schedule'));
    } finally {
      setDeletingId(null);
    }
  };

  const handleToggle = async (scheduleId: number) => {
    try {
      setTogglingId(scheduleId);
      const result = await toggleSchedule(scheduleId);
      await fetchSchedules();
      // Update selected schedule from API response (avoids stale closure)
      if (selectedSchedule?.id === scheduleId && result?.data) {
        setSelectedSchedule(result.data);
      }
    } catch (err) {
      toast.error(extractApiError(err, 'Failed to toggle schedule'));
    } finally {
      setTogglingId(null);
    }
  };

  const handleRunNow = async (scheduleId: number) => {
    try {
      setRunningId(scheduleId);
      await runScheduleNow(scheduleId);
      toast.success('Scan triggered. Results will appear shortly.');
      await fetchSchedules();
    } catch (err) {
      toast.error(extractApiError(err, 'Failed to trigger scan'));
    } finally {
      setRunningId(null);
    }
  };

  /* ── Inline delete confirmation state ────────────────────── */
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  /* ── Render helpers ──────────────────────────────────────── */

  const renderRightPanel = () => {
    if (mode === 'create') {
      return (
        <ScheduleForm
          missionId={missionId}
          targets={missionTargets}
          onSave={handleFormSaved}
          onCancel={handleFormCancel}
        />
      );
    }

    if (mode === 'edit' && selectedSchedule) {
      return (
        <ScheduleForm
          missionId={missionId}
          targets={missionTargets}
          schedule={selectedSchedule}
          onSave={handleFormSaved}
          onCancel={handleFormCancel}
        />
      );
    }

    // Default: show RunTimeline if a schedule is selected, otherwise show placeholder
    if (selectedSchedule) {
      return (
        <RunTimeline
          scheduleId={selectedSchedule.id}
          scheduleName={selectedSchedule.name}
        />
      );
    }

    return (
      <div className="flex flex-col items-center justify-center h-full text-center py-16 px-8">
        <Shield className="h-12 w-12 text-dark-muted mb-4" />
        <p className="text-dark-secondary text-sm">
          Select a schedule to view its run history, or create a new one.
        </p>
      </div>
    );
  };

  /* ── Empty state ─────────────────────────────────────────── */

  if (!loading && schedules.length === 0 && mode === 'list') {
    return (
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <BrandLockup service="sentinel" size="md" />
            <span className="text-dark-secondary text-sm">
              Manage scheduled scans and compliance monitoring
            </span>
          </div>
        </div>

        {/* Empty state card */}
        <div className="border border-dark-border bg-dark-elevated rounded-xl p-12 flex flex-col items-center justify-center text-center">
          <div className="h-16 w-16 rounded-2xl bg-dark-surface border border-dark-border flex items-center justify-center mb-6">
            <Calendar className="h-8 w-8 text-dark-muted" />
          </div>
          <h3 className="text-white text-lg font-semibold mb-2">No Scheduled Scans</h3>
          <p className="text-dark-secondary text-sm max-w-md mb-6">
            No scheduled scans yet. Create your first schedule to enable continuous compliance monitoring.
          </p>
          <button
            onClick={handleCreateOpen}
            disabled={isLocked}
            className="flex items-center gap-2 px-4 py-2 bg-ey-yellow text-dark-bg font-semibold rounded-lg hover:bg-ey-yellow/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Plus className="h-4 w-4" />
            New Schedule
          </button>
        </div>
      </div>
    );
  }

  /* ── Main layout ─────────────────────────────────────────── */

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BrandLockup service="sentinel" size="md" />
          <span className="text-dark-secondary text-sm">
            Manage scheduled scans and compliance monitoring
          </span>
        </div>
      </div>

      {/* Two-column layout */}
      <div className="flex gap-6 min-h-[500px]">
        {/* Left panel: schedule list */}
        <div className="w-2/5 flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm flex items-center gap-2">
              <Clock className="h-4 w-4 text-dark-secondary" />
              Schedules
              <span className="text-dark-muted text-xs font-normal">({schedules.length})</span>
            </h3>
            <button
              onClick={handleCreateOpen}
              disabled={isLocked}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-ey-yellow text-dark-bg text-xs font-semibold rounded-lg hover:bg-ey-yellow/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Plus className="h-3.5 w-3.5" />
              New Schedule
            </button>
          </div>

          {/* Schedule list */}
          <div className="flex-1 overflow-y-auto space-y-3 pr-1">
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-6 w-6 text-dark-muted animate-spin" />
              </div>
            ) : (
              schedules.map(schedule => (
                <div key={schedule.id} className="relative">
                  <ScheduleCard
                    schedule={schedule}
                    isSelected={selectedSchedule?.id === schedule.id && mode === 'list'}
                    onSelect={() => handleSelectSchedule(schedule)}
                    onEdit={() => handleEditOpen(schedule)}
                    onToggle={() => handleToggle(schedule.id)}
                    onRunNow={() => handleRunNow(schedule.id)}
                    onDelete={() => setConfirmDeleteId(schedule.id)}
                    isLocked={isLocked}
                    isToggling={togglingId === schedule.id}
                    isRunning={runningId === schedule.id}
                  />

                  {/* Inline delete confirmation */}
                  {confirmDeleteId === schedule.id && (
                    <div className="absolute inset-0 z-10 bg-dark-elevated/95 backdrop-blur-sm border border-red-500/30 rounded-xl flex items-center justify-center gap-3 px-4">
                      <span className="text-sm text-red-400 font-medium">Delete this schedule?</span>
                      <button
                        onClick={() => {
                          setConfirmDeleteId(null);
                          handleDelete(schedule.id);
                        }}
                        disabled={deletingId === schedule.id}
                        className="flex items-center gap-1 px-3 py-1.5 bg-red-500/20 text-red-400 border border-red-500/30 text-xs font-semibold rounded-lg hover:bg-red-500/30 transition-colors disabled:opacity-50"
                      >
                        {deletingId === schedule.id ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Trash2 className="h-3 w-3" />
                        )}
                        Confirm
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        className="px-3 py-1.5 bg-dark-elevated hover:bg-dark-border text-dark-secondary text-xs font-semibold rounded-lg border border-dark-border transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Right panel: form or timeline */}
        <div className="w-3/5 border border-dark-border bg-dark-surface rounded-xl overflow-hidden">
          {renderRightPanel()}
        </div>
      </div>
    </div>
  );
}
