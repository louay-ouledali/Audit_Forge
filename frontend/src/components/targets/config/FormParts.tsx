import { ReactNode } from 'react';
import { Info } from 'lucide-react';

/* ── Shared classes (compact) ──────────────────────────────── */
export const fieldInput =
  'w-full rounded-md border border-dark-border bg-dark-elevated px-2.5 py-1.5 text-[13px] text-white placeholder-dark-muted focus:border-ey-yellow/40 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20 transition-colors';

export const fieldSelect =
  'w-full rounded-md border border-dark-border bg-dark-elevated px-2.5 py-1.5 text-[13px] text-white focus:border-ey-yellow/40 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20 transition-colors appearance-none';

export const fieldLabel =
  'block text-[11px] font-semibold text-dark-secondary mb-1';

/* ── Form Section (lightweight divider instead of heavy card) ── */
export function FormSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2.5">
      <h4 className="text-[10px] font-bold uppercase tracking-widest text-dark-muted border-b border-dark-border/40 pb-1.5">{title}</h4>
      <div className="space-y-2.5 pl-0.5">{children}</div>
    </div>
  );
}

/* ── Hint / Info Box ───────────────────────────────────────── */
export function HintBox({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-1.5 rounded-md bg-dark-overlay/40 px-2.5 py-1.5 text-[10px] leading-relaxed text-dark-muted">
      <Info className="mt-0.5 h-2.5 w-2.5 shrink-0 text-ey-yellow/50" />
      <div>{children}</div>
    </div>
  );
}

/* ── Prerequisite Code Block ───────────────────────────────── */
export function CodeBlock({ children }: { children: string }) {
  const handleCopy = () => navigator.clipboard?.writeText(children);
  return (
    <div className="group/code relative rounded-md border border-dark-border/40 bg-dark-card px-2.5 py-2 font-mono text-[10px] leading-relaxed text-dark-secondary">
      <pre className="whitespace-pre-wrap">{children}</pre>
      <button
        onClick={handleCopy}
        className="absolute right-1 top-1 rounded px-1.5 py-0.5 text-[9px] text-dark-muted opacity-0 transition-opacity hover:bg-ey-yellow/10 hover:text-ey-yellow group-hover/code:opacity-100"
      >
        Copy
      </button>
    </div>
  );
}

/* ── Warning Box (for USB not supported etc.) ──────────────── */
export function WarningBox({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-1.5 rounded-md border border-amber-500/15 bg-amber-500/5 px-2.5 py-1.5 text-[10px] leading-relaxed text-amber-300/80">
      <span className="mt-0.5 shrink-0 text-[9px]">⚠</span>
      <div>{children}</div>
    </div>
  );
}
