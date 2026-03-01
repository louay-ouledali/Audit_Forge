import { useState } from 'react';
import {
  X,
  Upload,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';
import type { Target } from '@/types';
import * as api from '@/services/api';
import { inputClass } from '../mission/badgeHelpers';
import DiscoveryBar from './DiscoveryBar';
import TargetActionBar from './TargetActionBar';
import TargetCardGrid from './TargetCardGrid';
import TargetConfigDrawer from './TargetConfigDrawer';

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
  const [importResult, setImportResult] = useState<{ success: number; failed: number } | null>(null);

  // Scanning state (will be enhanced in Phase 7)
  const [scanningTargetIds] = useState<Set<number>>(new Set());
  const [scanProgressMap] = useState<Map<number, number>>(new Map());

  // Config drawer state
  const [drawerTarget, setDrawerTarget] = useState<Target | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const unassignedTargets = clientTargets.filter(
    ct => !missionTargets.some(mt => mt.id === ct.id),
  );

  // Targets that could be scanned (have creds + benchmark)
  const hasScannable = missionTargets.some(
    t => !!(t.ssh_username || t.has_enable_password) && !!t.default_benchmark_id,
  );

  /* ── Handlers ──────────────────────────────────────────────── */
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
    if (!confirm('Unassign this target from the mission?')) return;
    try {
      await api.unassignTargetFromMission(missionId, targetId);
      await onRefresh();
    } catch {
      setError('Failed to unassign target');
    }
  };

  const handleConfigure = (target: Target) => {
    setDrawerTarget(target);
    setDrawerOpen(true);
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    // Delay clearing target so close animation plays
    setTimeout(() => setDrawerTarget(null), 300);
  };

  const handleScan = (target: Target) => {
    // Phase 7 will implement per-target scan launch
    console.log('Scan target:', target.id);
  };

  const handleUsbExport = (target: Target) => {
    // Phase 8 will implement per-target USB export
    console.log('USB export target:', target.id);
  };

  const handleViewFindings = (target: Target) => {
    // Will switch to Findings tab filtered to this target
    console.log('View findings for target:', target.id);
  };

  const handleScanAll = () => {
    // Phase 7 will open the ScanAllDialog
    console.log('Scan All targets');
  };

  const handleUsbAll = () => {
    // Phase 8 will open UsbBulkExportDialog
    console.log('USB Export All');
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
          port: connectionMethod === 'ssh' ? 22 : connectionMethod === 'winrm' ? 5985 : null,
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
      {/* Error banner */}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
          <button onClick={() => setError('')} className="ml-2 text-red-300 hover:text-white transition-colors">×</button>
        </div>
      )}

      {/* ── 1. Discovery Bar (collapsible) ───────────────────── */}
      <DiscoveryBar
        clientId={clientId}
        missionId={missionId}
        onTargetsAdded={onRefresh}
      />

      {/* ── 2. Action Bar ────────────────────────────────────── */}
      <TargetActionBar
        unassignedTargets={unassignedTargets}
        assignTargetId={assignTargetId}
        onAssignChange={setAssignTargetId}
        onAssign={handleAssignTarget}
        onBulkImportToggle={() => { setShowImport(!showImport); setImportResult(null); }}
        showImport={showImport}
        onScanAll={handleScanAll}
        onUsbAll={handleUsbAll}
        targetCount={missionTargets.length}
        hasScannable={hasScannable}
      />

      {/* Bulk Import Panel */}
      {showImport && (
        <div className="rounded-xl border border-ey-yellow/30 bg-dark-card p-5 shadow-lg shadow-ey-yellow/5">
          <div className="flex justify-between items-start mb-4">
            <div>
              <h3 className="text-base font-semibold text-white">Bulk Import Targets</h3>
              <p className="text-xs text-dark-secondary mt-1">Paste CSV data to quickly create and assign targets.</p>
            </div>
            <button onClick={() => setShowImport(false)} className="text-dark-muted hover:text-white transition-colors">
              <X className="h-5 w-5" />
            </button>
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
                  {importResult.success > 0 && (
                    <span className="flex items-center gap-1.5 text-emerald-400">
                      <CheckCircle2 className="h-4 w-4" /> {importResult.success} Imported
                    </span>
                  )}
                  {importResult.failed > 0 && (
                    <span className="flex items-center gap-1.5 text-red-400">
                      <AlertCircle className="h-4 w-4" /> {importResult.failed} Failed
                    </span>
                  )}
                </div>
              )}
            </div>
            <button
              onClick={handleBulkImport}
              disabled={importing || !importText.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-5 py-2 text-sm font-semibold text-black shadow-sm transition-colors hover:bg-ey-yellow-hover disabled:opacity-50"
            >
              {importing ? (
                <><div className="h-4 w-4 animate-spin rounded-full border-2 border-black border-t-transparent" /> Processing…</>
              ) : (
                <><Upload className="h-4 w-4" /> Import Targets</>
              )}
            </button>
          </div>
        </div>
      )}

      {/* ── 3. Target Cards Grid ─────────────────────────────── */}
      <TargetCardGrid
        targets={missionTargets}
        onConfigure={handleConfigure}
        onDelete={handleUnassignTarget}
        onScan={handleScan}
        onUsbExport={handleUsbExport}
        onViewFindings={handleViewFindings}
        scanningTargetIds={scanningTargetIds}
        scanProgressMap={scanProgressMap}
      />

      {/* ── 4. Config Drawer ─────────────────────────────────── */}
      <TargetConfigDrawer
        target={drawerTarget}
        open={drawerOpen}
        onClose={handleDrawerClose}
        onSaved={async () => { await onRefresh(); }}
      />
    </div>
  );
}
