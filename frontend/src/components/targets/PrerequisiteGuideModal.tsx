import { useState, useEffect } from 'react';
import {
  X,
  Monitor,
  Terminal,
  Network,
  Database,
  HelpCircle,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  Info,
  AlertTriangle,
  Loader2,
  Package,
  BookOpen,
} from 'lucide-react';
import type { Target, PrerequisiteGuide as PrereqGuideType } from '@/types';
import * as api from '@/services/api';

/* ── Platform config ──────────────────────────────────────────── */
const PLATFORM_META: Record<string, {
  icon: typeof Monitor;
  color: string;
  label: string;
}> = {
  windows:  { icon: Monitor,  color: 'text-sky-400',     label: 'Windows'  },
  linux:    { icon: Terminal,  color: 'text-emerald-400', label: 'Linux'    },
  network:  { icon: Network,  color: 'text-purple-400',  label: 'Network'  },
  database: { icon: Database,  color: 'text-orange-400',  label: 'Database' },
};

const DEFAULT_META = { icon: HelpCircle, color: 'text-dark-muted', label: 'Unknown' };

function getMeta(platform: string) {
  return PLATFORM_META[platform.toLowerCase()] || DEFAULT_META;
}

/* ── Props ────────────────────────────────────────────────────── */
interface Props {
  target: Target | null;
  open: boolean;
  onClose: () => void;
}

export default function PrerequisiteGuideModal({ target, open, onClose }: Props) {
  const [guide, setGuide] = useState<PrereqGuideType | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (!open || !target) {
      setGuide(null);
      setError('');
      setExpandedSteps(new Set());
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError('');

    api.getTargetPrerequisites(target.id)
      .then(data => {
        if (!cancelled) {
          setGuide(data);
          // Expand all steps by default
          setExpandedSteps(new Set(data.steps.map((_, i) => i)));
        }
      })
      .catch(() => {
        if (!cancelled) setError('Failed to load prerequisites');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [open, target]);

  if (!open || !target) return null;

  const platform = (target.target_type || '').toLowerCase();
  // Map specific types to guide category
  const guideKey = ['cisco_ios', 'juniper', 'fortinet', 'palo_alto', 'arista', 'hp_procurve'].includes(platform)
    ? 'network'
    : ['postgresql', 'oracle', 'mssql'].includes(platform)
      ? 'database'
      : platform;
  const meta = getMeta(guideKey);
  const Icon = meta.icon;

  const toggleStep = (idx: number) => {
    setExpandedSteps(prev => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-2xl max-h-[85vh] flex flex-col rounded-2xl border border-dark-border bg-dark-card shadow-2xl shadow-ey-yellow/5">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-dark-border p-5 shrink-0">
          <div className="flex items-center gap-3">
            <div className={`flex h-10 w-10 items-center justify-center rounded-xl bg-dark-elevated border border-dark-border`}>
              <BookOpen className="h-5 w-5 text-ey-yellow" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                Setup Guide
                <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest ${meta.color} bg-dark-elevated border border-dark-border`}>
                  <Icon className="h-3 w-3" /> {meta.label}
                </span>
              </h3>
              <p className="text-xs text-dark-secondary mt-0.5">
                {target.hostname || target.ip_address || `Target #${target.id}`}
                {target.connection_method && <span className="text-dark-muted ml-1">({target.connection_method})</span>}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-dark-muted hover:bg-dark-elevated hover:text-white transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {loading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-ey-yellow" />
              <span className="ml-2 text-sm text-dark-secondary">Loading prerequisites…</span>
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
              {error}
            </div>
          )}

          {guide && !loading && (
            <>
              {/* Connection method badge */}
              <div className="rounded-lg bg-dark-elevated border border-dark-border/50 px-4 py-3 flex items-center gap-3">
                <Info className="h-4 w-4 text-ey-yellow shrink-0" />
                <p className="text-sm text-dark-secondary">
                  Connection method: <strong className="text-white">{guide.connection_method}</strong>
                  {' — '}Follow the steps below to prepare the target for auditing.
                </p>
              </div>

              {/* Steps */}
              {guide.steps.length === 0 ? (
                <div className="text-center py-8 text-dark-muted text-sm">
                  No specific prerequisites for this target type.
                </div>
              ) : (
                <div className="space-y-3">
                  {guide.steps.map((step, idx) => (
                    <StepCard
                      key={idx}
                      index={idx}
                      step={step}
                      expanded={expandedSteps.has(idx)}
                      onToggle={() => toggleStep(idx)}
                    />
                  ))}
                </div>
              )}

              {/* Alternative (USB / none) */}
              {guide.alternative && (
                <div className={`rounded-lg border px-4 py-3 ${
                  guide.alternative.method === 'usb'
                    ? 'border-ey-yellow/20 bg-ey-yellow/5'
                    : 'border-amber-500/20 bg-amber-500/5'
                }`}>
                  <div className="flex items-start gap-3">
                    {guide.alternative.method === 'usb' ? (
                      <Package className="h-4 w-4 text-ey-yellow mt-0.5 shrink-0" />
                    ) : (
                      <AlertTriangle className="h-4 w-4 text-amber-400 mt-0.5 shrink-0" />
                    )}
                    <div>
                      <h5 className="text-sm font-semibold text-white">
                        {guide.alternative.method === 'usb' ? 'Alternative: USB Air-Gap' : 'No Alternative Available'}
                      </h5>
                      <p className="text-xs text-dark-secondary mt-1">{guide.alternative.description}</p>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t border-dark-border p-5 shrink-0">
          <button
            onClick={onClose}
            className="rounded-lg bg-dark-elevated border border-dark-border px-4 py-2 text-sm font-medium text-dark-secondary hover:text-white hover:bg-dark-overlay transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── StepCard sub-component ───────────────────────────────────── */
interface StepCardProps {
  index: number;
  step: { title: string; description: string; command: string | null; notes: string | null };
  expanded: boolean;
  onToggle: () => void;
}

function StepCard({ index, step, expanded, onToggle }: StepCardProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="rounded-xl border border-dark-border bg-dark-elevated/50 overflow-hidden">
      {/* Step header (collapsible) */}
      <button
        onClick={onToggle}
        className="flex items-center gap-3 w-full px-4 py-3 text-left hover:bg-dark-overlay/30 transition-colors"
      >
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ey-yellow/10 border border-ey-yellow/20 text-[11px] font-bold text-ey-yellow">
          {index + 1}
        </span>
        <span className="flex-1 text-sm font-semibold text-white">{step.title}</span>
        {expanded ? (
          <ChevronDown className="h-4 w-4 text-dark-muted" />
        ) : (
          <ChevronRight className="h-4 w-4 text-dark-muted" />
        )}
      </button>

      {/* Step body */}
      {expanded && (
        <div className="border-t border-dark-border/50 px-4 py-3 space-y-3">
          <p className="text-xs text-dark-secondary leading-relaxed whitespace-pre-line">
            {step.description}
          </p>

          {step.command && (
            <div className="relative group/cmd">
              <pre className="rounded-lg bg-[#0a0a0a] border border-dark-border p-3 text-xs font-mono text-emerald-400 overflow-x-auto whitespace-pre-wrap leading-relaxed">
                {step.command}
              </pre>
              <button
                onClick={() => handleCopy(step.command!)}
                className="absolute top-2 right-2 rounded-md bg-dark-elevated border border-dark-border p-1.5 text-dark-muted hover:text-ey-yellow hover:border-ey-yellow/30 transition-all opacity-0 group-hover/cmd:opacity-100"
                title="Copy to clipboard"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
            </div>
          )}

          {step.notes && (
            <div className="flex items-start gap-2 rounded-lg bg-dark-overlay/30 border border-dark-border/30 px-3 py-2">
              <Info className="h-3.5 w-3.5 text-dark-muted mt-0.5 shrink-0" />
              <p className="text-[11px] text-dark-muted leading-relaxed">{step.notes}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
