import { useState } from 'react';
import { Server, X, Upload, CheckCircle2, AlertCircle } from 'lucide-react';
import type { Target } from '@/types';
import * as api from '@/services/api';
import { inputClass } from '../mission/badgeHelpers';

interface Props {
  missionId: number;
  clientId: number;
  missionTargets: Target[];
  clientTargets: Target[];
  onRefresh: () => Promise<void>;
}

export default function TargetsTab({ missionId, clientId, missionTargets, clientTargets, onRefresh }: Props) {
  const [assignTargetId, setAssignTargetId] = useState<number | ''>('');
  const [error, setError] = useState('');

  // Bulk Import State
  const [showImport, setShowImport] = useState(false);
  const [importText, setImportText] = useState('');
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{ success: number, failed: number } | null>(null);

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

  const handleBulkImport = async () => {
    if (!importText.trim()) return;
    setImporting(true);
    setError('');
    setImportResult(null);

    const lines = importText.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    let successCount = 0;
    let failCount = 0;

    for (const line of lines) {
      // Expected format: hostnameOrIp, type, connectionMethod(optional), username(optional), password(optional)
      const parts = line.split(',').map(p => p.trim());
      const ipOrHost = parts[0];
      const targetType = parts[1]?.toLowerCase() || 'linux';
      const connectionMethod = parts[2]?.toLowerCase() || 'ssh';
      const username = parts[3] || null;
      const password = parts[4] || null;

      try {
        // 1. Create target for client
        const newTarget = await api.createTarget({
          client_id: clientId,
          hostname: ipOrHost.includes('.') && !ipOrHost.match(/^\d{1,3}\./) ? ipOrHost : null,
          ip_address: ipOrHost.match(/^\d{1,3}\./) ? ipOrHost : null,
          target_type: targetType,
          connection_method: connectionMethod,
          ssh_username: username,
          ssh_password: password,
          port: connectionMethod === 'ssh' ? 22 : connectionMethod === 'winrm' ? 5985 : null
        });

        // 2. Assign to mission
        await api.assignTargetToMission(missionId, newTarget.id);
        successCount++;
      } catch (err) {
        console.error('Failed to import line:', line, err);
        failCount++;
      }
    }

    setImportResult({ success: successCount, failed: failCount });
    setImporting(false);
    if (successCount > 0) {
      setImportText('');
      await onRefresh();
      if (failCount === 0) {
        setTimeout(() => { setShowImport(false); setImportResult(null); }, 3000);
      }
    } else {
      setError('Failed to import any targets. Please check the format.');
    }
  };

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
          <button onClick={() => setError('')} className="ml-2 text-red-300 hover:text-white">×</button>
        </div>
      )}

      {/* Top Actions Row */}
      <div className="flex flex-col sm:flex-row gap-4 items-end sm:items-center justify-between">
        {/* Assign existing target */}
        {unassignedTargets.length > 0 ? (
          <div className="flex items-center gap-3 w-full sm:w-auto">
            <select
              value={assignTargetId}
              onChange={e => setAssignTargetId(e.target.value ? Number(e.target.value) : '')}
              className={`${inputClass} max-w-[200px]`}
            >
              <option value="">Select existing client target…</option>
              {unassignedTargets.map(t => (
                <option key={t.id} value={t.id}>{t.hostname || t.ip_address || `Target #${t.id}`} ({t.target_type})</option>
              ))}
            </select>
            <button
              onClick={handleAssignTarget}
              disabled={!assignTargetId}
              className="rounded-lg bg-ey-yellow px-4 py-2 text-sm font-semibold text-black hover:bg-ey-yellow-hover disabled:opacity-50 transition-colors whitespace-nowrap"
            >
              Assign
            </button>
          </div>
        ) : <div />}

        <button
          onClick={() => { setShowImport(!showImport); setImportResult(null); }}
          className={`inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${showImport ? 'border-ey-yellow text-ey-yellow bg-ey-yellow/10' : 'border-dark-border bg-dark-card text-dark-secondary hover:text-white hover:bg-dark-elevated'}`}
        >
          <Upload className="h-4 w-4" /> Bulk Import New Targets
        </button>
      </div>

      {/* Bulk Import Panel */}
      {showImport && (
        <div className="rounded-xl border border-ey-yellow/30 bg-dark-card p-5 animate-in slide-in-from-top-2 fade-in duration-200 shadow-lg shadow-ey-yellow/5">
          <div className="flex justify-between items-start mb-4">
            <div>
              <h3 className="text-base font-semibold text-white">Bulk Import Targets</h3>
              <p className="text-xs text-dark-secondary mt-1">Paste CSV data to quickly create and assign targets.</p>
            </div>
            <button onClick={() => setShowImport(false)} className="text-dark-muted hover:text-white"><X className="h-5 w-5" /></button>
          </div>

          <div className="bg-dark-elevated rounded-lg p-3 mb-4 text-xs font-mono text-dark-muted border border-dark-border/50">
            <p className="text-ey-yellow/80 mb-1 font-semibold">Expected Format (one per line):</p>
            <p>IP/Hostname, OS_Type, ConnectionMethod, Username, Password</p>
            <p className="mt-2 text-dark-secondary">Example:</p>
            <p>192.168.1.10, windows, winrm, Administrator, SecretPass123!</p>
            <p>10.0.0.5, linux, ssh, root, rootpass</p>
            <p>webserver.local, linux, ssh</p>
          </div>

          <textarea
            value={importText}
            onChange={e => setImportText(e.target.value)}
            placeholder="Paste your CSV target data here..."
            className={`${inputClass} font-mono text-sm leading-relaxed h-40 resize-y`}
            disabled={importing}
          />

          <div className="mt-4 flex items-center justify-between">
            <div>
              {importResult && (
                <div className="flex items-center gap-4 text-sm font-medium">
                  {importResult.success > 0 && <span className="flex items-center gap-1.5 text-emerald-400"><CheckCircle2 className="h-4 w-4" /> {importResult.success} Imported</span>}
                  {importResult.failed > 0 && <span className="flex items-center gap-1.5 text-red-400"><AlertCircle className="h-4 w-4" /> {importResult.failed} Failed</span>}
                </div>
              )}
            </div>
            <button
              onClick={handleBulkImport}
              disabled={importing || !importText.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-5 py-2 text-sm font-semibold text-black shadow-sm transition-colors hover:bg-ey-yellow-hover disabled:opacity-50"
            >
              {importing ? (
                <><div className="h-4 w-4 animate-spin rounded-full border-2 border-black border-t-transparent" /> Processing...</>
              ) : (
                <><Upload className="h-4 w-4" /> Import Targets</>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Assigned targets list */}
      {missionTargets.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-12 text-center">
          <Server className="mx-auto h-10 w-10 text-dark-muted" />
          <p className="mt-3 text-dark-secondary">No targets assigned to this mission.</p>
          <p className="mt-1 text-xs text-dark-muted">
            {unassignedTargets.length > 0
              ? 'Use the dropdown above to assign existing client targets, or bulk import new ones.'
              : 'Add targets to the client first, or use the bulk import feature.'}
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-dark-border bg-dark-card shadow-sm">
          <table className="min-w-full divide-y divide-dark-border">
            <thead className="bg-dark-elevated/80 backdrop-blur-sm">
              <tr>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-dark-secondary">Target</th>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-dark-secondary">Details</th>
                <th className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-dark-secondary">Connection</th>
                <th className="px-5 py-3.5 text-right text-xs font-semibold uppercase tracking-wider text-dark-secondary">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-dark-border border-t border-dark-border/50">
              {missionTargets.map(t => (
                <tr key={t.id} className="hover:bg-dark-elevated/30 transition-colors group">
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-500/10 border border-sky-500/20 group-hover:border-sky-500/40 transition-colors">
                        <Server className="h-4 w-4 text-sky-400" />
                      </div>
                      <div>
                        <div className="text-sm font-bold text-white mb-0.5">{t.hostname || `Target #${t.id}`}</div>
                        <div className="text-xs text-dark-muted font-mono">{t.ip_address || 'No IP'}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <span className="inline-flex rounded-full bg-dark-overlay px-2.5 py-0.5 text-xs font-medium uppercase tracking-wider text-dark-secondary border border-dark-border/50">
                      {t.target_type}
                    </span>
                  </td>
                  <td className="px-5 py-4">
                    <div className="text-sm font-medium text-dark-secondary uppercase tracking-wider">{t.connection_method || '—'}</div>
                    {t.port && <div className="text-xs text-dark-muted mt-0.5">Port {t.port}</div>}
                  </td>
                  <td className="px-5 py-4 text-right">
                    <button
                      onClick={() => handleUnassignTarget(t.id)}
                      className="rounded-md bg-dark-elevated p-2 text-dark-muted hover:bg-red-500/10 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
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
