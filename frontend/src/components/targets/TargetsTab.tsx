import { useState } from 'react';
import {
  Server,
  X,
  Upload,
  CheckCircle2,
  AlertCircle,
  Monitor,
  Terminal,
  Network,
  Database,
  HelpCircle,
  Plus,
  Wifi,
} from 'lucide-react';
import type { Target } from '@/types';
import * as api from '@/services/api';
import { inputClass } from '../mission/badgeHelpers';
import DiscoveryBar from './DiscoveryBar';

/* ── Platform icon + accent mapping ─────────────────────────── */
const PLATFORM_CONFIG: Record<string, { icon: typeof Monitor; accent: string }> = {
  windows:  { icon: Monitor,   accent: 'sky' },
  linux:    { icon: Terminal,   accent: 'emerald' },
  network:  { icon: Network,    accent: 'purple' },
  database: { icon: Database,   accent: 'orange' },
};

function getPlatform(t: Target) {
  const key = (t.target_type || '').toLowerCase();
  return PLATFORM_CONFIG[key] || { icon: HelpCircle, accent: 'gray' };
}

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
      const parts = line.split(',').map(p => p.trim());
      const ipOrHost = parts[0];
      const targetType = parts[1]?.toLowerCase() || 'linux';
      const connectionMethod = parts[2]?.toLowerCase() || 'ssh';
      const username = parts[3] || null;
      const password = parts[4] || null;

      try {
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

      {/* ── 1. Discovery Bar (collapsible) ───────────────────── */}
      <DiscoveryBar
        clientId={clientId}
        missionId={missionId}
        onTargetsAdded={onRefresh}
      />

      {/* ── 2. Action Bar ────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row gap-4 items-end sm:items-center justify-between">
        {/* Assign existing target */}
        {unassignedTargets.length > 0 ? (
          <div className="flex items-center gap-3 w-full sm:w-auto">
            <select
              value={assignTargetId}
              onChange={e => setAssignTargetId(e.target.value ? Number(e.target.value) : '')}
              className={`${inputClass} max-w-[200px]`}
            >
              <option value="">Assign existing target…</option>
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
          <Upload className="h-4 w-4" /> Bulk Import
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

      {/* ── 3. Target Cards Grid ─────────────────────────────── */}
      {missionTargets.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-12 text-center">
          <Server className="mx-auto h-10 w-10 text-dark-muted" />
          <p className="mt-3 text-dark-secondary font-medium">No targets assigned to this mission.</p>
          <p className="mt-1 text-xs text-dark-muted">
            Discover your network above, assign an existing client target, or bulk import new ones.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {missionTargets.map(t => {
            const platform = getPlatform(t);
            const Icon = platform.icon;
            const a = platform.accent;

            return (
              <div
                key={t.id}
                className={`group relative rounded-xl border bg-dark-card p-5 transition-all duration-200 hover:shadow-lg hover:shadow-black/20
                  ${t.connection_status === 'ok'
                    ? 'border-l-2 border-l-emerald-500 border-t-dark-border border-r-dark-border border-b-dark-border'
                    : t.connection_status === 'failed'
                      ? 'border-l-2 border-l-red-500 border-t-dark-border border-r-dark-border border-b-dark-border'
                      : 'border-dark-border'
                  }`}
              >
                {/* Top row: Icon + Name + Actions */}
                <div className="flex items-start gap-3">
                  <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-${a}-500/10 border border-${a}-500/20`}>
                    <Icon className={`h-5 w-5 text-${a}-400`} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-bold text-white">{t.hostname || `Target #${t.id}`}</p>
                    <p className="text-xs text-dark-muted font-mono">{t.ip_address || 'No IP'}</p>
                  </div>
                  <button
                    onClick={() => handleUnassignTarget(t.id)}
                    className="rounded-md bg-dark-elevated p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
                    title="Unassign from mission"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>

                {/* Status row */}
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <div className="flex items-center gap-1.5 text-xs">
                    <span className={`inline-block h-1.5 w-1.5 rounded-full ${
                      t.connection_status === 'ok' ? 'bg-emerald-400' : t.connection_status === 'failed' ? 'bg-red-400' : 'bg-dark-muted'
                    }`} />
                    <span className="text-dark-secondary capitalize">
                      {t.connection_status === 'ok' ? 'Reachable' : t.connection_status === 'failed' ? 'Unreachable' : 'Untested'}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs">
                    <span className={`inline-flex items-center rounded-full bg-${a}-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-${a}-400`}>
                      {t.target_type}
                    </span>
                  </div>
                </div>

                {/* Connection + port info */}
                <div className="mt-2 flex items-center gap-3 text-xs text-dark-muted">
                  {t.connection_method && (
                    <span className="flex items-center gap-1">
                      <Wifi className="h-3 w-3" /> {t.connection_method.toUpperCase()}
                    </span>
                  )}
                  {t.port && <span>Port {t.port}</span>}
                </div>

                {/* Benchmark */}
                {t.default_benchmark_name && (
                  <div className="mt-2 truncate text-xs text-dark-muted">
                    📋 {t.default_benchmark_name}
                  </div>
                )}

                {/* Scan stats (if any) */}
                {t.last_scan_date && (
                  <div className="mt-3 flex items-center justify-between border-t border-dark-border/50 pt-2.5 text-xs">
                    <span className="text-dark-muted">
                      Last: {new Date(t.last_scan_date).toLocaleDateString()}
                    </span>
                    {t.last_scan_compliance != null && (
                      <span className={`font-semibold ${t.last_scan_compliance >= 80 ? 'text-emerald-400' : t.last_scan_compliance >= 50 ? 'text-amber-400' : 'text-red-400'}`}>
                        {t.last_scan_compliance.toFixed(1)}%
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
