import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, X } from 'lucide-react';

export interface ConfirmDialogProps {
  open: boolean;
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** 'danger' uses red confirm button, 'default' uses yellow */
  variant?: 'danger' | 'default';
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title = 'Confirm Action',
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'danger',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  // Auto-focus confirm button on open
  useEffect(() => {
    if (open) {
      // Small delay so portal is rendered
      const t = setTimeout(() => confirmRef.current?.focus(), 50);
      return () => clearTimeout(t);
    }
  }, [open]);

  // Escape key to cancel
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onCancel(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onCancel]);

  if (!open) return null;

  const isDanger = variant === 'danger';

  return createPortal(
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-[70] bg-black/60 backdrop-blur-sm" onClick={onCancel} />

      {/* Dialog */}
      <div className="fixed inset-0 z-[70] flex items-center justify-center p-4" style={{ pointerEvents: 'none' }}>
        <div
          className="pointer-events-auto w-full max-w-md rounded-xl border border-dark-border bg-dark-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200"
          onClick={e => e.stopPropagation()}
        >
          <div className="flex items-start gap-4">
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${isDanger ? 'bg-red-500/10' : 'bg-ey-yellow/10'}`}>
              <AlertTriangle className={`h-5 w-5 ${isDanger ? 'text-red-400' : 'text-ey-yellow'}`} />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-lg font-semibold text-white">{title}</h3>
              <p className="mt-2 text-sm text-dark-secondary leading-relaxed">{message}</p>
            </div>
            <button onClick={onCancel} className="rounded-md p-1 text-dark-muted hover:text-white transition-colors">
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="mt-6 flex justify-end gap-3">
            <button
              onClick={onCancel}
              className="rounded-lg border border-dark-border px-4 py-2 text-sm font-medium text-dark-secondary hover:bg-dark-elevated hover:text-white transition-colors"
            >
              {cancelLabel}
            </button>
            <button
              ref={confirmRef}
              onClick={onConfirm}
              className={`rounded-lg px-4 py-2 text-sm font-semibold transition-colors ${
                isDanger
                  ? 'bg-red-600 text-white hover:bg-red-700 shadow-lg shadow-red-600/20'
                  : 'bg-ey-yellow text-black hover:bg-ey-yellow-hover shadow-lg shadow-ey-yellow/10'
              }`}
            >
              {confirmLabel}
            </button>
          </div>
        </div>
      </div>
    </>,
    document.body,
  );
}
