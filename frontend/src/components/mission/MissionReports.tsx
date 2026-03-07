import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { BarChart3, Bot, FileText, Trash2, Calendar, Loader2, Lock } from 'lucide-react';
import type { SavedReport } from '@/types';
import * as api from '@/services/api';
import ConfirmDialog from '@/components/common/ConfirmDialog';
import { useToast } from '@/components/common/Toast';

interface Props {
  missionId: number;
  missionName?: string;
  isLocked?: boolean;
}

export default function MissionReports({ missionId, missionName, isLocked = false }: Props) {
  const navigate = useNavigate();
  const toast = useToast();
  const [reports, setReports] = useState<SavedReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);

  const fetchReports = useCallback(async () => {
    try {
      const data = await api.getSavedReports(missionId);
      setReports(data);
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, [missionId]);

  useEffect(() => { fetchReports(); }, [fetchReports]);

  const handleDelete = async () => {
    if (deleteTarget === null) return;
    try {
      await api.deleteSavedReport(deleteTarget);
      toast.success('Report deleted');
      setReports(prev => prev.filter(r => r.id !== deleteTarget));
    } catch { toast.error('Failed to delete report'); }
    finally { setDeleteTarget(null); }
  };

  return (
    <div className="space-y-6">
      {/* Locked banner */}
      {isLocked && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-xs text-amber-400">
          <Lock className="h-3.5 w-3.5 shrink-0" /> Mission is locked — report creation and deletion are disabled.
        </div>
      )}

      {/* Generate section */}
      <div className="rounded-xl border border-dark-border bg-dark-card p-6">
        <h3 className="mb-4 text-lg font-semibold text-white">Generate Reports</h3>
        <p className="mb-4 text-sm text-dark-secondary">
          Use the Reports page for full report generation with the Report Builder.
        </p>
        <div className="flex gap-3">
          <button
            onClick={() => navigate('/reports', { state: { missionId, missionName } })}
            className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2.5 text-sm font-semibold text-black hover:bg-ey-yellow-hover"
          >
            <BarChart3 className="h-4 w-4" /> Open Report Builder
          </button>
          <button
            onClick={() => navigate(`/missions/${missionId}/analysis`)}
            className="inline-flex items-center gap-2 rounded-lg border border-dark-border bg-dark-elevated px-4 py-2.5 text-sm font-medium text-dark-secondary hover:text-white"
          >
            <Bot className="h-4 w-4" /> AI Analysis
          </button>
        </div>
      </div>

      {/* Saved reports list */}
      <div className="rounded-xl border border-dark-border bg-dark-card p-6">
        <h3 className="mb-4 text-lg font-semibold text-white flex items-center justify-between">
          <span>Saved Reports</span>
          <span className="text-xs text-dark-muted bg-dark-elevated px-2.5 py-1 rounded-full">{reports.length}</span>
        </h3>

        {loading ? (
          <div className="flex items-center justify-center py-8 gap-2 text-dark-secondary text-sm">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading reports…
          </div>
        ) : reports.length === 0 ? (
          <div className="text-center py-10 border-2 border-dashed border-dark-border rounded-lg">
            <FileText className="h-8 w-8 text-dark-muted mx-auto mb-3" />
            <p className="text-sm text-dark-muted">No saved reports for this mission yet.</p>
            <p className="text-xs text-dark-muted mt-1">Generate a report using the Report Builder above.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {reports.map(r => (
              <div key={r.id} className="flex items-center justify-between rounded-lg border border-dark-border/50 bg-dark-elevated/50 px-4 py-3 group hover:border-dark-hover transition-colors">
                <div className="flex items-center gap-3 min-w-0 flex-1">
                  <div className="shrink-0 rounded-lg bg-purple-500/10 p-2">
                    <FileText className="h-4 w-4 text-purple-400" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-white truncate">{r.title}</p>
                    <div className="flex items-center gap-3 mt-0.5 text-xs text-dark-muted">
                      <span className="uppercase font-medium bg-dark-overlay px-1.5 py-0.5 rounded">{r.format}</span>
                      {r.created_at && (
                        <span className="flex items-center gap-1">
                          <Calendar className="h-3 w-3" />
                          {new Date(r.created_at).toLocaleDateString(undefined, { dateStyle: 'medium' })}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {!isLocked && (
                    <button
                      onClick={() => setDeleteTarget(r.id)}
                      className="rounded-md p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400 transition-colors"
                      title="Delete report"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete Report"
        message="Delete this saved report? This cannot be undone."
        confirmLabel="Delete"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
