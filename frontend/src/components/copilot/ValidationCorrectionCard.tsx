import { CheckCircle2, X } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Correction {
  field: string;
  old_value: string;
  new_value: string;
  reason?: string;
}

export interface ValidationCorrectionData {
  rule_command_id: number;
  section_number: string;
  title: string;
  validation_status: string;
  validation_confidence: string;
  corrections: Correction[];
  notes?: string;
}

interface ValidationCorrectionCardProps {
  correction: ValidationCorrectionData;
  onApply: (ruleCommandId: number) => void;
  onDismiss: (ruleCommandId: number) => void;
}

export default function ValidationCorrectionCard({
  correction,
  onApply,
  onDismiss,
}: ValidationCorrectionCardProps) {
  const isHigh = correction.validation_confidence === 'high';

  return (
    <div className={cn(
      'rounded-lg border p-2.5 text-xs',
      isHigh
        ? 'border-emerald-500/20 bg-emerald-500/5'
        : 'border-amber-500/20 bg-amber-500/5',
    )}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="font-medium text-white">{correction.section_number}</span>
          <span className="text-dark-secondary ml-1.5 truncate">{correction.title}</span>
        </div>
        <span className={cn(
          'shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium',
          isHigh ? 'bg-emerald-500/15 text-emerald-400' : 'bg-amber-500/15 text-amber-400',
        )}>
          {correction.validation_confidence}
        </span>
      </div>

      {correction.corrections.map((c, i) => (
        <div key={i} className="mt-1.5 rounded bg-dark-bg/60 p-1.5">
          <div className="text-[10px] text-dark-muted mb-0.5">{c.field}</div>
          <div className="flex flex-col gap-0.5">
            <span className="line-through text-red-400/70 break-all">{c.old_value.slice(0, 120)}</span>
            <span className="text-emerald-400 break-all">{c.new_value.slice(0, 120)}</span>
          </div>
          {c.reason && (
            <div className="text-[10px] text-dark-muted mt-0.5 italic">{c.reason}</div>
          )}
        </div>
      ))}

      {correction.notes && (
        <p className="text-[10px] text-dark-muted mt-1 italic">{correction.notes}</p>
      )}

      <div className="flex items-center gap-1.5 mt-2">
        <button
          onClick={() => onApply(correction.rule_command_id)}
          className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors"
        >
          <CheckCircle2 className="h-2.5 w-2.5" /> Apply
        </button>
        <button
          onClick={() => onDismiss(correction.rule_command_id)}
          className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-dark-elevated text-dark-muted hover:text-white transition-colors"
        >
          <X className="h-2.5 w-2.5" /> Dismiss
        </button>
      </div>
    </div>
  );
}
