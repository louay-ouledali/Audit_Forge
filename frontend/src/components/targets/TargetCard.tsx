import { useState } from 'react';
import {
  Monitor,
  Terminal,
  Network,
  Database,
  HelpCircle,
  Settings,
  Trash2,
  Play,
  Package,
  Wifi,
  WifiOff,
  Key,
  FileText,
  Clock,
  ExternalLink,
  Loader2,
  Info,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Upload,
  BookOpen,
} from 'lucide-react';
import type { Target, ConnectionTestResult } from '@/types';
import * as api from '@/services/api';

/* ── Platform config (static classes for Tailwind) ───────────── */
const PLATFORM: Record<string, {
  icon: typeof Monitor;
  iconBox: string;
  iconColor: string;
  badge: string;
  label: string;
  usbSupported: boolean;
  usbTooltip: string;
}> = {
  windows: {
    icon: Monitor,
    iconBox: 'bg-sky-500/10 border-sky-500/20 group-hover:border-sky-500/40',
    iconColor: 'text-sky-400',
    badge: 'bg-sky-500/10 text-sky-400',
    label: 'Windows',
    usbSupported: true,
    usbTooltip: 'Download PowerShell audit script ZIP',
  },
  linux: {
    icon: Terminal,
    iconBox: 'bg-emerald-500/10 border-emerald-500/20 group-hover:border-emerald-500/40',
    iconColor: 'text-emerald-400',
    badge: 'bg-emerald-500/10 text-emerald-400',
    label: 'Linux',
    usbSupported: true,
    usbTooltip: 'Download Bash audit script ZIP',
  },
  network: {
    icon: Network,
    iconBox: 'bg-purple-500/10 border-purple-500/20 group-hover:border-purple-500/40',
    iconColor: 'text-purple-400',
    badge: 'bg-purple-500/10 text-purple-400',
    label: 'Network',
    usbSupported: false,
    usbTooltip: 'Network devices require direct SSH access. USB air-gap is not supported.',
  },
  database: {
    icon: Database,
    iconBox: 'bg-orange-500/10 border-orange-500/20 group-hover:border-orange-500/40',
    iconColor: 'text-orange-400',
    badge: 'bg-orange-500/10 text-orange-400',
    label: 'Database',
    usbSupported: false,
    usbTooltip: 'Database audits require a live connection. USB air-gap is not supported.',
  },
};

const DEFAULT_PLATFORM = {
  icon: HelpCircle,
  iconBox: 'bg-dark-elevated border-dark-border',
  iconColor: 'text-dark-muted',
  badge: 'bg-dark-overlay text-dark-secondary',
  label: 'Unknown',
  usbSupported: false,
  usbTooltip: 'USB export not available for this target type.',
};

function getPlatform(t: Target) {
  return PLATFORM[(t.target_type || '').toLowerCase()] || DEFAULT_PLATFORM;
}

/* ── Card border class based on connection state ─────────────── */
function cardBorderClass(t: Target, isScanning: boolean): string {
  if (isScanning)
    return 'border-ey-yellow/40 animate-pulse shadow-[0_0_15px_rgba(255,230,0,0.08)]';
  if (!t.ssh_username && !t.default_benchmark_id)
    return 'border-dashed border-amber-500/40';
  if (t.connection_status === 'ok')
    return 'border-l-2 border-l-emerald-500 border-t-dark-border border-r-dark-border border-b-dark-border';
  if (t.connection_status === 'failed')
    return 'border-l-2 border-l-red-500 border-t-dark-border border-r-dark-border border-b-dark-border';
  return 'border-dark-border';
}

/* ── Props ───────────────────────────────────────────────────── */
interface Props {
  target: Target;
  onConfigure: (target: Target) => void;
  onDelete: (targetId: number) => void;
  onScan?: (target: Target) => void;
  onUsbExport?: (target: Target) => void;
  onImportResults?: (target: Target) => void;
  onSetupHelp?: (target: Target) => void;
  onViewFindings?: (target: Target) => void;
  isScanning?: boolean;
  scanProgress?: number;
}

export default function TargetCard({
  target,
  onConfigure,
  onDelete,
  onScan,
  onUsbExport,
  onImportResults,
  onSetupHelp,
  onViewFindings,
  isScanning = false,
  scanProgress,
}: Props) {
  const p = getPlatform(target);
  const Icon = p.icon;
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);

  const hasCreds = !!(target.ssh_username || target.has_enable_password);
  const hasBenchmark = !!target.default_benchmark_id;
  const isUnconfigured = !hasCreds && !hasBenchmark;

  /* ── Connection test ───────────────────────────────────────── */
  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.testTargetConnection(target.id);
      setTestResult(result);
    } catch {
      setTestResult({
        target_id: target.id,
        status: 'failed',
        message: 'Connection test failed',
        response_time_ms: null,
        connection_method: null,
        error_details: 'Could not reach backend',
      });
    } finally {
      setTesting(false);
    }
  };

  /* ── Derived connection status (live test overrides DB) ────── */
  const connStatus = testResult?.status || target.connection_status;
  const connLabel = connStatus === 'ok' ? 'Reachable' : connStatus === 'failed' ? 'Unreachable' : 'Untested';
  const connLatency = testResult?.response_time_ms;

  return (
    <div
      className={`glow-card group relative rounded-xl border bg-dark-card p-5 transition-all duration-300 ${cardBorderClass(target, isScanning)}`}
    >
      {/* Scanning progress overlay */}
      {isScanning && scanProgress != null && (
        <div className="absolute inset-x-0 bottom-0 h-1 rounded-b-xl bg-dark-elevated overflow-hidden">
          <div
            className="h-full bg-ey-yellow transition-all duration-300"
            style={{ width: `${scanProgress}%` }}
          />
        </div>
      )}

      {/* ── Header: Icon + Name + Action buttons ─────────────── */}
      <div className="flex items-start gap-3">
        <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border transition-colors ${p.iconBox}`}>
          <Icon className={`h-6 w-6 ${p.iconColor}`} />
        </div>
        <div className="min-w-0 flex-1">
          <h4 className="truncate text-sm font-bold text-white">
            {target.hostname || `Target #${target.id}`}
          </h4>
          <div className="mt-0.5 flex items-center gap-2">
            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest ${p.badge}`}>
              {p.label}
            </span>
            {target.connection_method && (
              <span className="text-[10px] text-dark-muted uppercase tracking-wider">
                {target.connection_method}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-dark-muted font-mono">
            {target.ip_address || 'No IP'}{target.port ? ` : ${target.port}` : ''}
          </p>
        </div>
        {/* Top-right action icons */}
        <div className="flex gap-1 opacity-100 md:opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={() => onConfigure(target)}
            className="rounded-md p-1.5 text-dark-muted hover:bg-ey-yellow/10 hover:text-ey-yellow transition-colors"
            title="Configure"
          >
            <Settings className="h-4 w-4" />
          </button>
          <button
            onClick={() => onDelete(target.id)}
            disabled={isScanning}
            className="rounded-md p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400 transition-colors disabled:opacity-30"
            title="Remove"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* ── Status checklist ──────────────────────────────────── */}
      <div className="mt-4 space-y-2 rounded-lg bg-dark-elevated/50 p-3 border border-dark-border/50">
        {/* Credentials */}
        <div className="flex items-center justify-between text-xs">
          <span className="flex items-center gap-1.5 text-dark-muted">
            <Key className="h-3 w-3" /> Credentials
          </span>
          {hasCreds ? (
            <span className="flex items-center gap-1 text-emerald-400 font-medium">
              <CheckCircle2 className="h-3 w-3" /> OK ({target.ssh_username})
            </span>
          ) : (
            <span className="flex items-center gap-1 text-amber-400 font-medium">
              <AlertTriangle className="h-3 w-3" /> Not set
            </span>
          )}
        </div>

        {/* Connection */}
        <div className="flex items-center justify-between text-xs">
          <span className="flex items-center gap-1.5 text-dark-muted">
            {connStatus === 'ok' ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
            Connection
          </span>
          <div className="flex items-center gap-2">
            {testing ? (
              <span className="flex items-center gap-1 text-dark-secondary">
                <Loader2 className="h-3 w-3 animate-spin" /> Testing…
              </span>
            ) : connStatus === 'ok' ? (
              <span className="flex items-center gap-1 text-emerald-400 font-medium">
                <CheckCircle2 className="h-3 w-3" /> {connLabel}{connLatency ? ` (${connLatency}ms)` : ''}
              </span>
            ) : connStatus === 'failed' ? (
              <span className="flex items-center gap-1 text-red-400 font-medium">
                <XCircle className="h-3 w-3" /> {connLabel}
              </span>
            ) : (
              <button
                onClick={handleTestConnection}
                className="flex items-center gap-1 text-dark-secondary hover:text-ey-yellow transition-colors"
              >
                <Wifi className="h-3 w-3" /> Test
              </button>
            )}
            {/* Re-test link for already-tested */}
            {!testing && connStatus && connStatus !== 'untested' && (
              <button
                onClick={handleTestConnection}
                className="text-dark-muted hover:text-ey-yellow transition-colors"
                title="Re-test connection"
              >
                <Wifi className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>

        {/* Setup Help link — always visible, highlighted when connection failed */}
        {onSetupHelp && (
          <div className="flex items-center justify-end">
            <button
              onClick={() => onSetupHelp(target)}
              className={`flex items-center gap-1 text-[11px] transition-colors ${
                connStatus === 'failed'
                  ? 'text-amber-400 hover:text-ey-yellow font-medium'
                  : 'text-dark-muted hover:text-dark-secondary'
              }`}
            >
              <BookOpen className="h-3 w-3" /> Setup Help
            </button>
          </div>
        )}

        {/* Benchmark */}
        <div className="flex items-center justify-between text-xs">
          <span className="flex items-center gap-1.5 text-dark-muted">
            <FileText className="h-3 w-3" /> Benchmark
          </span>
          {target.default_benchmark_name ? (
            <span className="max-w-[60%] truncate text-dark-secondary font-medium" title={target.default_benchmark_name}>
              {target.default_benchmark_name}
            </span>
          ) : (
            <span className="text-amber-400 font-medium flex items-center gap-1">
              <AlertTriangle className="h-3 w-3" /> Not set
            </span>
          )}
        </div>
      </div>

      {/* ── Action buttons (only in mission context) ─────────── */}
      {(onScan || onUsbExport || onImportResults) && (
      <div className="mt-4 flex gap-2">
        {/* Scan Now */}
        {onScan && (
        <button
          onClick={() => onScan(target)}
          disabled={!hasCreds || isScanning || !hasBenchmark}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-ey-yellow px-3 py-2 text-xs font-bold text-black transition-colors hover:bg-ey-yellow-hover disabled:opacity-30 disabled:cursor-not-allowed"
          title={!hasCreds ? 'Configure credentials first' : !hasBenchmark ? 'Set a benchmark first' : isScanning ? 'Scan in progress' : 'Start network scan'}
        >
          {isScanning ? (
            <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Scanning…</>
          ) : (
            <><Play className="h-3.5 w-3.5" /> Scan Now</>
          )}
        </button>
        )}

        {/* USB Export */}
        {onUsbExport && (
        <div className="relative group/usb">
          <button
            onClick={() => onUsbExport(target)}
            disabled={!hasBenchmark || !p.usbSupported}
            className={`flex items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${
              p.usbSupported && hasBenchmark
                ? 'border-dark-border bg-dark-elevated text-dark-secondary hover:bg-dark-overlay hover:text-white'
                : 'border-dark-border/50 bg-dark-elevated/50 text-dark-muted/50 cursor-not-allowed'
            }`}
            title={p.usbTooltip}
          >
            <Package className="h-3.5 w-3.5" /> USB
          </button>
          {/* USB disabled tooltip */}
          {!p.usbSupported && (
            <div className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 -translate-x-1/2 whitespace-nowrap opacity-0 group-hover/usb:opacity-100 transition-opacity">
              <div className="rounded-lg bg-dark-overlay border border-dark-border px-3 py-2 text-[11px] text-dark-secondary shadow-xl max-w-[220px] whitespace-normal text-center">
                <Info className="inline h-3 w-3 text-amber-400 mr-1" />
                {p.usbTooltip}
              </div>
            </div>
          )}
        </div>
        )}

        {/* Import Results */}
        {onImportResults && (
        <button
          onClick={() => onImportResults(target)}
          disabled={!hasBenchmark}
          className="flex items-center justify-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-xs font-medium text-dark-secondary transition-colors hover:bg-dark-overlay hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
          title={!hasBenchmark ? 'Set a benchmark first' : 'Import scan results (JSON/ZIP)'}
        >
          <Upload className="h-3.5 w-3.5" /> Import
        </button>
        )}
      </div>
      )}

      {/* ── Unconfigured CTA ──────────────────────────────────── */}
      {isUnconfigured && (
        <button
          onClick={() => onConfigure(target)}
          className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs font-medium text-amber-400 transition-colors hover:bg-amber-500/10 hover:border-amber-500/50"
        >
          <Settings className="h-3.5 w-3.5" /> Configure credentials & benchmark
        </button>
      )}

      {/* ── Last scan footer ──────────────────────────────────── */}
      {target.last_scan_date ? (
        <div className="mt-4 flex items-center justify-between border-t border-dark-border/50 pt-3">
          <div className="flex items-center gap-1.5 text-xs text-dark-muted">
            <Clock className="h-3 w-3" />
            {new Date(target.last_scan_date).toLocaleDateString()}
            {target.scan_count > 0 && (
              <span className="ml-1 text-dark-muted">({target.scan_count} scan{target.scan_count > 1 ? 's' : ''})</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {target.last_scan_compliance != null && (
              <span className={`text-xs font-bold ${
                target.last_scan_compliance >= 80 ? 'text-emerald-400' : target.last_scan_compliance >= 50 ? 'text-amber-400' : 'text-red-400'
              }`}>
                {target.last_scan_compliance.toFixed(1)}%
              </span>
            )}
            {onViewFindings && (
            <button
              onClick={() => onViewFindings(target)}
              className="flex items-center gap-1 text-[11px] text-dark-secondary hover:text-ey-yellow transition-colors"
            >
              View <ExternalLink className="h-3 w-3" />
            </button>
            )}
          </div>
        </div>
      ) : (
        <div className="mt-4 border-t border-dark-border/50 pt-3">
          <p className="text-xs text-dark-muted">Never scanned</p>
        </div>
      )}
    </div>
  );
}
