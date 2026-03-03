import { useState } from 'react';
import {
  X,
  Upload,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';
import type { Target } from '@/types';
import * as api from '@/services/api';
import type { SmartImportPreviewResponse } from '@/services/api';
import { inputClass } from '../mission/badgeHelpers';
import DiscoveryBar from './DiscoveryBar';
import TargetActionBar from './TargetActionBar';
import TargetCardGrid from './TargetCardGrid';
import TargetConfigDrawer from './TargetConfigDrawer';
import { useScanManager } from './scan/useScanManager';
import ScanAllDialog from './scan/ScanAllDialog';
import ActiveScansPanel from './scan/ActiveScansPanel';
import UsbBulkExportDialog from './scan/UsbBulkExportDialog';
import PrerequisiteGuideModal from './PrerequisiteGuideModal';
import ScanHistoryPanel from './ScanHistoryPanel';
import ImportPreviewModal from '../import/ImportPreviewModal';
import type { ImportOptions } from '../import/ImportPreviewModal';

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

  // Scan history refresh key (incremented after scans complete)
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);

  // Wrap onRefresh to also bump scan history
  const handleRefreshAll = async () => {
    await onRefresh();
    setHistoryRefreshKey(k => k + 1);
  };

  // Scan manager (Phase 7)
  const scan = useScanManager(missionId, missionTargets, handleRefreshAll);

  // Config drawer state
  const [drawerTarget, setDrawerTarget] = useState<Target | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // USB bulk export dialog
  const [showUsbBulk, setShowUsbBulk] = useState(false);

  // Prerequisites guide modal
  const [prereqTarget, setPrereqTarget] = useState<Target | null>(null);
  const [showPrereqs, setShowPrereqs] = useState(false);

  // Smart Import Preview Modal state
  const [showPreviewModal, setShowPreviewModal] = useState(false);
  const [previewData, setPreviewData] = useState<SmartImportPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewFilename, setPreviewFilename] = useState('');
  const [pendingImportFile, setPendingImportFile] = useState<File | null>(null);

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
    scan.launchSingleScan(target);
  };

  const handleUsbExport = async (target: Target) => {
    if (!target.default_benchmark_id) {
      setError('Set a benchmark before exporting.');
      return;
    }
    try {
      const blob = await api.generateScript({
        benchmark_id: target.default_benchmark_id,
        target_id: target.id,
      });
      const host = target.hostname || target.ip_address || `target_${target.id}`;
      const bench = (target.default_benchmark_name || 'audit').replace(/\s+/g, '_');
      const date = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      const filename = `auditforge_audit_${bench}_${host}_${date}.zip`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'USB export failed';
      setError(msg);
    }
  };

  const handleViewFindings = (target: Target) => {
    // Will switch to Findings tab filtered to this target
    console.log('View findings for target:', target.id);
  };

  const handleViewScanFindings = (scanId: number) => {
    // Will switch to Findings tab with this specific scan selected
    console.log('View findings for scan:', scanId);
  };

  const handleImportResults = (target: Target) => {
    if (!target.default_benchmark_id) {
      setError('Set a benchmark before importing results.');
      return;
    }
    // Open file picker
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,.zip';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        await api.importWithNewScan(target.id, target.default_benchmark_id!, file, missionId);
        await onRefresh();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Import failed';
        setError(msg);
      }
    };
    input.click();
  };

  const handleSetupHelp = (target: Target) => {
    setPrereqTarget(target);
    setShowPrereqs(true);
  };

  const handleScanAll = () => {
    scan.setShowScanAllDialog(true);
  };

  const handleUsbAll = () => {
    setShowUsbBulk(true);
  };

  const handleSmartImport = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,.zip,.csv,.html,.htm,.nessus,.xml';
    input.multiple = true;
    input.onchange = async () => {
      const files = input.files;
      if (!files || files.length === 0) return;
      setError('');

      // Check if any file is a Nessus-type file (CSV/HTML) — show preview for first one
      const firstFile = files[0];
      const ext = firstFile.name.split('.').pop()?.toLowerCase();
      const isNessusType = ext === 'csv' || ext === 'html' || ext === 'htm';

      if (isNessusType && files.length === 1) {
        // Show preview modal for Nessus-type files
        setPendingImportFile(firstFile);
        setPreviewFilename(firstFile.name);
        setPreviewLoading(true);
        setShowPreviewModal(true);
        try {
          const preview = await api.smartImportPreview(firstFile, clientId);
          setPreviewData(preview);
        } catch (err: unknown) {
          const msg = err && typeof err === 'object' && 'response' in err
            ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Preview failed'
            : err instanceof Error ? err.message : 'Preview failed';
          setPreviewData({ format: 'error', filename: firstFile.name, message: msg });
        } finally {
          setPreviewLoading(false);
        }
        return;
      }

      // Legacy flow for JSON/ZIP files (or multi-file)
      let totalFindings = 0;
      let totalCompliance = 0;
      let fileCount = 0;
      const errors: string[] = [];

      for (const file of Array.from(files)) {
        try {
          const res = await api.smartImport(file, missionId, clientId);
          totalFindings += res.findings_created;
          totalCompliance += res.compliance_percentage;
          fileCount++;
        } catch (err: unknown) {
          const msg = err && typeof err === 'object' && 'response' in err
            ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Import failed'
            : err instanceof Error ? err.message : 'Import failed';
          errors.push(`${file.name}: ${msg}`);
        }
      }

      if (fileCount > 0) {
        const avgCompliance = (totalCompliance / fileCount).toFixed(1);
        scan.setError(''); // clear any scan errors
        setError('');
        await handleRefreshAll();
        alert(`Smart Import complete!\n\n${fileCount} file(s) imported\n${totalFindings} findings created\nAvg compliance: ${avgCompliance}%${errors.length ? '\n\nErrors:\n' + errors.join('\n') : ''}`);
      } else {
        setError(errors.join('; '));
      }
    };
    input.click();
  };

  const handlePreviewImport = async (options: ImportOptions) => {
    if (!pendingImportFile) return;
    try {
      const res = await api.smartImport(pendingImportFile, missionId, clientId, {
        runFpDetection: options.runFpDetection,
        allowBenchmarkCreation: options.allowBenchmarkCreation,
        targetId: options.targetId,
      });
      setShowPreviewModal(false);
      setPendingImportFile(null);
      setPreviewData(null);
      await handleRefreshAll();

      const parts: string[] = [`Smart Import complete!`];
      parts.push(`${res.findings_created} findings imported`);
      if (res.benchmark_reconstructed) parts.push(`Benchmark reconstructed: ${res.benchmark_name}`);
      if (res.fp_suspects && res.fp_suspects > 0) parts.push(`${res.fp_suspects} potential false positives flagged`);
      if (res.warnings && res.warnings.length > 0) parts.push(`\nWarnings:\n${res.warnings.join('\n')}`);
      alert(parts.join('\n'));
    } catch (err) {
      throw err; // Let the modal handle the error display
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
      {(error || scan.error) && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error || scan.error}
          <button onClick={() => { setError(''); scan.setError(''); }} className="ml-2 text-red-300 hover:text-white transition-colors">×</button>
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
        onSmartImport={handleSmartImport}
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

      {/* ── 3. Active Scans Panel ───────────────────────────── */}
      <ActiveScansPanel
        scans={scan.activeScans}
        onCancelScan={scan.cancelSingleScan}
        onCancelAll={scan.cancelAllScans}
        onDismiss={scan.dismissCompleted}
      />

      {/* ── 4. Target Cards Grid ───────────────────────────── */}
      <TargetCardGrid
        targets={missionTargets}
        onConfigure={handleConfigure}
        onDelete={handleUnassignTarget}
        onScan={handleScan}
        onUsbExport={handleUsbExport}
        onImportResults={handleImportResults}
        onSetupHelp={handleSetupHelp}
        onViewFindings={handleViewFindings}
        scanningTargetIds={scan.scanningTargetIds}
        scanProgressMap={scan.scanProgressMap}
      />

      {/* ── 5. Scan History Panel (collapsible) ────────────── */}
      <ScanHistoryPanel
        missionId={missionId}
        targets={missionTargets}
        onViewFindings={handleViewScanFindings}
        onImportResults={handleImportResults}
        refreshKey={historyRefreshKey}
      />

      {/* ── 6. Scan All Dialog ────────────────────────────── */}
      <ScanAllDialog
        targets={missionTargets}
        open={scan.showScanAllDialog}
        onClose={() => scan.setShowScanAllDialog(false)}
        onLaunch={scan.launchBatchScan}
      />

      {/* ── 6. USB Bulk Export Dialog ─────────────────────── */}
      <UsbBulkExportDialog
        targets={missionTargets}
        open={showUsbBulk}
        onClose={() => setShowUsbBulk(false)}
        missionId={missionId}
      />

      {/* ── 7. Config Drawer ──────────────────────────────── */}
      <TargetConfigDrawer
        target={drawerTarget}
        open={drawerOpen}
        onClose={handleDrawerClose}
        onSaved={async () => { await onRefresh(); }}
      />

      {/* ── 8. Prerequisite Guide Modal ───────────────────── */}
      <PrerequisiteGuideModal
        target={prereqTarget}
        open={showPrereqs}
        onClose={() => { setShowPrereqs(false); setTimeout(() => setPrereqTarget(null), 300); }}
      />

      {/* ── 9. Smart Import Preview Modal ─────────────────── */}
      <ImportPreviewModal
        open={showPreviewModal}
        onClose={() => { setShowPreviewModal(false); setPendingImportFile(null); setPreviewData(null); }}
        preview={previewData}
        loading={previewLoading}
        filename={previewFilename}
        onImport={handlePreviewImport}
      />
    </div>
  );
}
