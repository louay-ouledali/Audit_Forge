import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
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

/* ── Platform config ──────────────────────────────────────── */
const PLATFORM_CFG: Record<string, {
  icon: typeof Monitor;
  color: string;
  bg: string;
  label: string;
}> = {
  windows:  { icon: Monitor,  color: 'text-sky-400',     bg: 'bg-sky-500/10',     label: 'Windows' },
  linux:    { icon: Terminal,  color: 'text-emerald-400', bg: 'bg-emerald-500/10', label: 'Linux' },
  network:  { icon: Network,   color: 'text-purple-400',  bg: 'bg-purple-500/10',  label: 'Network' },
  database: { icon: Database,   color: 'text-orange-400',  bg: 'bg-orange-500/10',  label: 'Database' },
};

const DEFAULT_CFG = { icon: HelpCircle, color: 'text-dark-muted', bg: 'bg-dark-elevated', label: 'Target' };

interface Props {
  target: Target | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

export default function TargetConfigDrawer({ target, open, onClose, onSaved }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const {
    form, setField, setConnectionMethod,
    benchmarks, loadingBenchmarks: _lb,
    saving, error, success,
    handleSave, setError,
  } = useTargetForm(target, onSaved);

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);

  useEffect(() => { setTestResult(null); }, [target?.id]);

  // Escape to close
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // Scroll to top when target changes
  useEffect(() => {
    if (open && scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [target?.id, open]);

  if (!open || !target) return null;

  const platformKey = (target.target_type || '').toLowerCase();
  const p = PLATFORM_CFG[platformKey] ?? DEFAULT_CFG;
  const Icon = p.icon;

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

  const statusDot = testResult
    ? testResult.status === 'ok' ? 'bg-emerald-400' : 'bg-red-400'
    : target.connection_status === 'ok' ? 'bg-emerald-400'
    : target.connection_status === 'failed' ? 'bg-red-400'
    : 'bg-dark-muted';

  /* ── Portal to document.body ────────────────────────────
     The <main> in MainLayout uses backdrop-blur-sm which creates
     a new containing block for fixed children. Portaling to <body>
     escapes that entirely so position: fixed works relative to the
     true viewport regardless of scroll position.               */
  return createPortal(
    <>
      {/* Backdrop — true viewport-fixed */}
      <div
        className="fixed inset-0 z-[60] bg-black/60 backdrop-blur-[3px]"
        style={{ animation: 'fadeIn 150ms ease-out' }}
        onClick={onClose}
      />

      {/* Modal wrapper — uses absolute pixel positioning for reliability */}
      <div
        className="fixed z-[60] flex justify-center"
        style={{
          top: '100px',      /* clears the floating navbar pill */
          left: '0',
          right: '0',
          bottom: '16px',
          pointerEvents: 'none',
        }}
      >
        <div
          className="pointer-events-auto flex w-full flex-col rounded-2xl border border-dark-border/50 bg-dark-surface shadow-2xl shadow-black/60"
          style={{
            maxWidth: '32rem',
            maxHeight: '100%',
            margin: '0 1rem',
            animation: 'modalIn 200ms ease-out',
          }}
        >
          {/* ── Header ──────────────────────────────────── */}
          <div className="flex items-center gap-3 px-5 py-3.5 border-b border-dark-border/40 shrink-0">
            <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${p.bg}`}>
              <Icon className={`h-4.5 w-4.5 ${p.color}`} />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-sm font-semibold text-white">
                {target.hostname || target.ip_address || `Target #${target.id}`}
              </h2>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-[10px] font-medium text-dark-muted uppercase tracking-wider">{p.label}</span>
                <span className={`h-1.5 w-1.5 rounded-full ${statusDot}`} />
                {target.ip_address && (
                  <span className="text-[10px] text-dark-muted font-mono">{target.ip_address}{target.port ? `:${target.port}` : ''}</span>
                )}
              </div>
            </div>
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-dark-muted hover:bg-dark-elevated hover:text-white transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* ── Scrollable form ─────────────────────────── */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-3 overscroll-contain min-h-0">
            {platformKey === 'windows' && <WindowsForm {...formProps} />}
            {platformKey === 'linux' && <LinuxForm {...formProps} />}
            {platformKey === 'network' && <NetworkForm {...formProps} />}
            {platformKey === 'database' && <DatabaseForm {...formProps} />}
            {!['windows', 'linux', 'network', 'database'].includes(platformKey) && (
              <LinuxForm {...formProps} />
            )}
          </div>

          {/* ── Footer ──────────────────────────────────── */}
          <div className="border-t border-dark-border/40 px-5 py-3 space-y-2 shrink-0">
            {/* Status banners */}
            {error && (
              <div className="rounded-lg bg-red-500/10 px-3 py-1.5 text-[11px] text-red-400 flex items-center gap-1.5">
                <XCircle className="h-3 w-3 shrink-0" />
                <span className="flex-1 truncate">{error}</span>
                <button onClick={() => setError('')} className="text-red-300 hover:text-white text-xs ml-1">×</button>
              </div>
            )}
            {success && (
              <div className="rounded-lg bg-emerald-500/10 px-3 py-1.5 text-[11px] text-emerald-400 flex items-center gap-1.5">
                <CheckCircle2 className="h-3 w-3 shrink-0" /> {success}
              </div>
            )}
            {testResult && (
              <div className={`rounded-lg px-3 py-1.5 text-[11px] flex items-center gap-1.5 ${
                testResult.status === 'ok' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
              }`}>
                {testResult.status === 'ok' ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                <span className="flex-1 truncate">{testResult.message}</span>
                {testResult.response_time_ms != null && (
                  <span className="text-dark-muted text-[10px]">{testResult.response_time_ms}ms</span>
                )}
              </div>
            )}

            {/* Action buttons */}
            <div className="flex items-center gap-2.5">
              <button
                onClick={handleTestConnection}
                disabled={testing || !form.ip_address}
                className="inline-flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-3.5 py-2 text-xs font-medium text-dark-secondary transition-colors hover:bg-dark-overlay hover:text-white disabled:opacity-30"
              >
                {testing ? (
                  <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Testing…</>
                ) : (
                  <><Wifi className="h-3.5 w-3.5" /> Test</>
                )}
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-ey-yellow px-3.5 py-2 text-xs font-bold text-black transition-colors hover:bg-ey-yellow-hover disabled:opacity-50"
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
      </div>

      {/* Inline keyframes — avoids needing tailwind config changes */}
      <style>{`
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes modalIn { from { opacity: 0; transform: scale(0.96) translateY(8px); } to { opacity: 1; transform: scale(1) translateY(0); } }
      `}</style>
    </>,
    document.body,
  );
}
