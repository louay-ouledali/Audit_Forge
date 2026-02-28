import { useState } from 'react';
import { Plus, Server, X } from 'lucide-react';
import type { Target } from '@/types';
import * as api from '@/services/api';
import { inputClass } from '../mission/badgeHelpers';

interface Props {
  missionId: number;
  missionTargets: Target[];
  clientTargets: Target[];
  onRefresh: () => Promise<void>;
}

export default function TargetsTab({ missionId, missionTargets, clientTargets, onRefresh }: Props) {
  const [assignTargetId, setAssignTargetId] = useState<number | ''>('');
  const [error, setError] = useState('');

  const unassignedTargets = clientTargets.filter(
    ct => !missionTargets.some(mt => mt.id === ct.id),
  );

  const handleAssignTarget = async () => {
    if (!assignTargetId) return;
    try {
      await api.assignTargetToMission(missionId, assignTargetId as number);
      setAssignTargetId('');
      await onRefresh();
    } catch {
      setError('Failed to assign target');
    }
  };

  const handleUnassignTarget = async (targetId: number) => {
    try {
      await api.unassignTargetFromMission(missionId, targetId);
      await onRefresh();
    } catch {
      setError('Failed to unassign target');
    }
  };

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
          <button onClick={() => setError('')} className="ml-2 text-red-300 hover:text-white">×</button>
        </div>
      )}

      {/* Assign existing target */}
      {unassignedTargets.length > 0 && (
        <div className="flex items-center gap-3 rounded-xl border border-dark-border bg-dark-card p-4">
          <span className="text-sm text-dark-secondary">Assign existing target:</span>
          <select
            value={assignTargetId}
            onChange={e => setAssignTargetId(e.target.value ? Number(e.target.value) : '')}
            className={`${inputClass} max-w-xs`}
          >
            <option value="">Select a target…</option>
            {unassignedTargets.map(t => (
              <option key={t.id} value={t.id}>{t.hostname || t.ip_address || `Target #${t.id}`} ({t.target_type})</option>
            ))}
          </select>
          <button
            onClick={handleAssignTarget}
            disabled={!assignTargetId}
            className="rounded-lg bg-ey-yellow px-3 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Assigned targets list */}
      {missionTargets.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-12 text-center">
          <Server className="mx-auto h-10 w-10 text-dark-muted" />
          <p className="mt-3 text-dark-secondary">No targets assigned to this mission.</p>
          <p className="mt-1 text-xs text-dark-muted">
            {unassignedTargets.length > 0
              ? 'Use the dropdown above to assign existing client targets.'
              : 'Add targets to the client first, then assign them here.'}
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-dark-border bg-dark-card">
          <table className="min-w-full divide-y divide-dark-border">
            <thead className="bg-dark-elevated">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-dark-muted">Target</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-dark-muted">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-dark-muted">Connection</th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-dark-muted">IP</th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase text-dark-muted">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-dark-border">
              {missionTargets.map(t => (
                <tr key={t.id} className="hover:bg-dark-elevated/30">
                  <td className="px-4 py-3 text-sm font-medium text-white">{t.hostname || `Target #${t.id}`}</td>
                  <td className="px-4 py-3 text-sm text-dark-secondary">{t.target_type}</td>
                  <td className="px-4 py-3 text-sm text-dark-secondary">{t.connection_method || '—'}</td>
                  <td className="px-4 py-3 text-sm text-dark-muted">{t.ip_address || '—'}{t.port ? `:${t.port}` : ''}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleUnassignTarget(t.id)}
                      className="rounded p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400"
                      title="Unassign from mission"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
