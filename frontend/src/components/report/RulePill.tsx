import { GripVertical, X } from 'lucide-react';
import type { BuilderFinding } from '@/types';

const SEV_COLORS: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  low: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  informational: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
};

interface RulePillProps {
  ruleId: number;
  groupIdx: number;
  rule: BuilderFinding | undefined;
  onDragStart: (ruleId: number, groupIdx: number) => void;
  onRemove: (ruleId: number, groupIdx: number) => void;
}

export default function RulePill({ ruleId, groupIdx, rule, onDragStart, onRemove }: RulePillProps) {
  if (!rule) return null;
  const sev = SEV_COLORS[rule.severity] || SEV_COLORS.medium;
  return (
    <div
      draggable
      onDragStart={() => onDragStart(ruleId, groupIdx)}
      className="flex items-center gap-2 rounded-lg border border-dark-border bg-dark-elevated px-2.5 py-1.5 cursor-grab active:cursor-grabbing transition-all hover:border-dark-secondary group"
    >
      <GripVertical className="h-3.5 w-3.5 text-dark-muted group-hover:text-dark-secondary flex-shrink-0" />
      <span className="text-xs font-mono text-dark-muted flex-shrink-0">{rule.section_number}</span>
      <span className="text-xs text-white truncate flex-1">{rule.rule_title || `Rule #${ruleId}`}</span>
      <span className={`inline-flex items-center rounded-full border px-1.5 py-0 text-[10px] font-medium ${sev} flex-shrink-0`}>{rule.severity}</span>
      {groupIdx >= 0 && (
        <button onClick={e => { e.stopPropagation(); onRemove(ruleId, groupIdx); }} className="text-dark-muted hover:text-red-400 transition-colors flex-shrink-0" title="Remove">
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}
