import { useEffect, useRef, useState } from 'react';
import {
  X,
  Save,
  Wifi,
  Loader2,
  CheckCircle2,
  XCircle,
  Monitor,
  Terminal,
  Network,
  Database,
  HelpCircle,
} from 'lucide-react';
import type { Target, ConnectionTestResult } from '@/types';
import * as api from '@/services/api';
import { useTargetForm } from './config/useTargetForm';
import WindowsForm from './config/WindowsForm';
import LinuxForm from './config/LinuxForm';
import NetworkForm from './config/NetworkForm';
import DatabaseForm from './config/DatabaseForm';

/* ── Platform icon mapping (static for Tailwind) ─────────── */
const PLATFORM_ICON: Record<string, { icon: typeof Monitor; color: string; bg: string }> = {
  windows:  { icon: Monitor,  color: 'text-sky-400',     bg: 'bg-sky-500/10 border-sky-500/20' },
  linux:    { icon: Terminal,  color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' },
  network:  { icon: Network,   color: 'text-purple-400',  bg: 'bg-purple-500/10 border-purple-500/20' },
  database: { icon: Database,   color: 'text-orange-400',  bg: 'bg-orange-500/10 border-orange-500/20' },
};

interface Props {
  target: Target | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

export default function TargetConfigDrawer({ target, open, onClose, onSaved }: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const {
    form, setField, setConnectionMethod,
    benchmarks, loadingBenchmarks: _lb,
    saving, error, success,
    handleSave, setError,
  } = useTargetForm(target, onSaved);

  // Connection test state
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);

  // Reset test result when target changes
  useEffect(() => {
    setTestResult(null);
  }, [target?.id]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // Lock body scroll
  useEffect(() => {
    if (open) document.body.style.overflow = 'hidden';
    else document.body.style.overflow = '';
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  if (!target) return null;

  const platformKey = (target.target_type || '').toLowerCase();
  const pIcon = PLATFORM_ICON[platformKey] ?? { icon: HelpCircle, color: 'text-dark-muted', bg: 'bg-dark-elevated border-dark-border' };
  const Icon = pIcon.icon;

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

  const formProps = { form, setField, setConnectionMethod, benchmarks };

  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 z-40 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ${open ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
        onClick={onClose}
      />

      {/* Drawer panel */}
      <div
        ref={panelRef}
        className={`fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-dark-border bg-dark-surface shadow-2xl shadow-black/50 transition-transform duration-300 ${open ? 'translate-x-0' : 'translate-x-full'}`}
      >
        {/* ── Header ──────────────────────────────────────── */}
        <div className="flex items-center gap-3 border-b border-dark-border px-5 py-4">
          <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${pIcon.bg}`}>
            <Icon className={`h-5 w-5 ${pIcon.color}`} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-sm font-bold text-white">
              Configure: {target.hostname || target.ip_address || `Target #${target.id}`}
            </h2>
            <p className="text-[11px] text-dark-muted capitalize">{target.target_type} target</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-dark-muted hover:bg-dark-elevated hover:text-white transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* ── Scrollable form area ────────────────────────── */}
        <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5 scrollbar-thin">
          {/* Platform-specific form */}
          {platformKey === 'windows' && <WindowsForm {...formProps} />}
          {platformKey === 'linux' && <LinuxForm {...formProps} />}
          {platformKey === 'network' && <NetworkForm {...formProps} />}
          {platformKey === 'database' && <DatabaseForm {...formProps} />}
          {!['windows', 'linux', 'network', 'database'].includes(platformKey) && (
            <LinuxForm {...formProps} />
          )}
        </div>

        {/* ── Footer actions ──────────────────────────────── */}
        <div className="border-t border-dark-border px-5 py-4 space-y-3">
          {/* Error / Success banners */}
          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400 flex items-center gap-2">
              <XCircle className="h-3.5 w-3.5 shrink-0" /> {error}
              <button onClick={() => setError('')} className="ml-auto text-red-300 hover:text-white">×</button>
            </div>
          )}
          {success && (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-400 flex items-center gap-2">
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" /> {success}
            </div>
          )}

          {/* Connection test result */}
          {testResult && (
            <div className={`rounded-lg border px-3 py-2 text-xs flex items-center gap-2 ${
              testResult.status === 'ok'
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                : 'border-red-500/30 bg-red-500/10 text-red-400'
            }`}>
              {testResult.status === 'ok' ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
              <span>{testResult.message}</span>
              {testResult.response_time_ms != null && (
                <span className="ml-auto text-dark-muted">{testResult.response_time_ms}ms</span>
              )}
            </div>
          )}

          {/* Buttons */}
          <div className="flex items-center gap-3">
            <button
              onClick={handleTestConnection}
              disabled={testing || !form.ip_address}
              className="inline-flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-4 py-2.5 text-xs font-medium text-dark-secondary transition-colors hover:bg-dark-overlay hover:text-white disabled:opacity-40"
            >
              {testing ? (
                <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Testing…</>
              ) : (
                <><Wifi className="h-3.5 w-3.5" /> Test Connection</>
              )}
            </button>

            <button
              onClick={handleSave}
              disabled={saving}
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-ey-yellow px-4 py-2.5 text-xs font-bold text-black transition-colors hover:bg-ey-yellow-hover disabled:opacity-50"
            >
              {saving ? (
                <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Saving…</>
              ) : (
                <><Save className="h-3.5 w-3.5" /> Save Configuration</>
              )}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
