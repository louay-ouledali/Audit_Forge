import { ReactNode } from 'react';
import { Info } from 'lucide-react';

/* ── Shared classes ────────────────────────────────────────── */
export const fieldInput =
  'w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/40 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20 transition-colors';

export const fieldSelect =
  'w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white focus:border-ey-yellow/40 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20 transition-colors appearance-none';

export const fieldLabel =
  'block text-xs font-semibold text-dark-secondary mb-1.5';

/* ── Form Section ──────────────────────────────────────────── */
export function FormSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dark-border/50 bg-dark-elevated/30 p-4">
      <h4 className="mb-3 text-xs font-bold uppercase tracking-wider text-dark-muted">{title}</h4>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

/* ── Hint / Info Box ───────────────────────────────────────── */
export function HintBox({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-md bg-dark-overlay/50 border border-dark-border/30 px-3 py-2 text-[11px] leading-relaxed text-dark-secondary">
      <Info className="mt-0.5 h-3 w-3 shrink-0 text-ey-yellow/60" />
      <div>{children}</div>
    </div>
  );
}

/* ── Prerequisite Code Block ───────────────────────────────── */
export function CodeBlock({ children }: { children: string }) {
  const handleCopy = () => navigator.clipboard?.writeText(children);
  return (
    <div className="group/code relative rounded-md border border-dark-border/50 bg-dark-card p-2.5 font-mono text-[11px] leading-relaxed text-dark-secondary">
      <pre className="whitespace-pre-wrap">{children}</pre>
      <button
        onClick={handleCopy}
        className="absolute right-1.5 top-1.5 rounded px-1.5 py-0.5 text-[10px] text-dark-muted opacity-0 transition-opacity hover:bg-ey-yellow/10 hover:text-ey-yellow group-hover/code:opacity-100"
      >
        Copy
      </button>
    </div>
  );
}

/* ── Warning Box (for USB not supported etc.) ──────────────── */
export function WarningBox({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2.5 text-[11px] leading-relaxed text-amber-300/90">
      <span className="mt-0.5 shrink-0">⚠</span>
      <div>{children}</div>
    </div>
  );
}
