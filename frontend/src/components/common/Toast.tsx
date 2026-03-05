import { createContext, useContext, useState, useCallback, useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { CheckCircle2, AlertTriangle, Info, X, XCircle } from 'lucide-react';

/* ── Types ────────────────────────────────────────────────── */
type ToastVariant = 'success' | 'error' | 'info' | 'warning';

interface Toast {
  id: number;
  message: string;
  variant: ToastVariant;
  /** ms before auto-dismiss (0 = sticky) */
  duration: number;
}

interface ToastContextValue {
  toast: (message: string, variant?: ToastVariant, duration?: number) => void;
  success: (message: string, duration?: number) => void;
  error: (message: string, duration?: number) => void;
  info: (message: string, duration?: number) => void;
  warning: (message: string, duration?: number) => void;
}

const ToastCtx = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}

/* ── Variant config ────────────────────────────────────────── */
const VARIANT_CFG: Record<ToastVariant, { icon: typeof CheckCircle2; border: string; bg: string; text: string }> = {
  success: { icon: CheckCircle2, border: 'border-emerald-500/30', bg: 'bg-emerald-500/10', text: 'text-emerald-400' },
  error:   { icon: XCircle,      border: 'border-red-500/30',     bg: 'bg-red-500/10',     text: 'text-red-400' },
  warning: { icon: AlertTriangle, border: 'border-amber-500/30',  bg: 'bg-amber-500/10',   text: 'text-amber-400' },
  info:    { icon: Info,          border: 'border-sky-500/30',     bg: 'bg-sky-500/10',     text: 'text-sky-400' },
};

const DEFAULT_DURATION: Record<ToastVariant, number> = {
  success: 4000,
  error: 8000,
  warning: 6000,
  info: 5000,
};

/* ── Single Toast item ─────────────────────────────────────── */
function ToastItem({ toast: t, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  const cfg = VARIANT_CFG[t.variant];
  const Icon = cfg.icon;
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (t.duration > 0) {
      timerRef.current = setTimeout(() => onDismiss(t.id), t.duration);
      return () => clearTimeout(timerRef.current);
    }
  }, [t.id, t.duration, onDismiss]);

  return (
    <div className={`flex items-start gap-3 rounded-lg border ${cfg.border} ${cfg.bg} px-4 py-3 shadow-lg backdrop-blur-sm animate-in slide-in-from-right-5 fade-in duration-300 max-w-md w-full`}>
      <Icon className={`h-5 w-5 shrink-0 mt-0.5 ${cfg.text}`} />
      <p className={`flex-1 text-sm ${cfg.text} leading-relaxed`}>{t.message}</p>
      <button onClick={() => onDismiss(t.id)} className={`shrink-0 ${cfg.text} opacity-60 hover:opacity-100 transition-opacity`}>
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

/* ── Provider ──────────────────────────────────────────────── */
let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const addToast = useCallback((message: string, variant: ToastVariant = 'info', duration?: number) => {
    const id = nextId++;
    setToasts(prev => [...prev, { id, message, variant, duration: duration ?? DEFAULT_DURATION[variant] }]);
  }, []);

  const value: ToastContextValue = {
    toast: addToast,
    success: useCallback((m, d) => addToast(m, 'success', d), [addToast]),
    error: useCallback((m, d) => addToast(m, 'error', d), [addToast]),
    info: useCallback((m, d) => addToast(m, 'info', d), [addToast]),
    warning: useCallback((m, d) => addToast(m, 'warning', d), [addToast]),
  };

  return (
    <ToastCtx.Provider value={value}>
      {children}
      {toasts.length > 0 && createPortal(
        <div className="fixed top-4 right-4 z-[80] flex flex-col gap-2 items-end pointer-events-auto">
          {toasts.map(t => (
            <ToastItem key={t.id} toast={t} onDismiss={dismiss} />
          ))}
        </div>,
        document.body,
      )}
    </ToastCtx.Provider>
  );
}
