import { cn } from '@/lib/utils';
import { CheckCircle, Zap, Bot, Cpu } from 'lucide-react';

interface RuleSuggestionCardProps {
  rule: {
    id?: number;
    section_number: string;
    title: string;
    description?: string;
    severity: string;
    confidence?: number | null;
    source_benchmark?: string | null;
    command_source?: string | null;
  };
  compact?: boolean;
}

const severityColors: Record<string, string> = {
  critical: 'bg-red-500/15 text-red-400 border-red-500/30',
  high: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  low: 'bg-green-500/15 text-green-400 border-green-500/30',
};

const sourceIcons: Record<string, typeof CheckCircle> = {
  template: Zap,
  cache: Cpu,
  llm: Bot,
  copilot: Bot,
};

export default function RuleSuggestionCard({ rule, compact }: RuleSuggestionCardProps) {
  const confidence = rule.confidence != null ? Math.round(rule.confidence * 100) : null;
  const SourceIcon = sourceIcons[rule.command_source || ''] || null;

  return (
    <div className={cn(
      'rounded-xl border border-sky-500/10 bg-dark-card/80 p-3 text-sm shadow-[0_4px_12px_rgba(0,0,0,0.2)] backdrop-blur-md transition-all hover:border-sky-500/30',
      compact && 'p-2',
    )}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-mono text-dark-muted">[{rule.section_number}]</span>
            <span className={cn(
              'text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded border',
              severityColors[rule.severity] || severityColors.medium,
            )}>
              {rule.severity}
            </span>
          </div>
          <p className="font-medium text-white truncate">{rule.title}</p>
          {!compact && rule.description && (
            <p className="text-xs text-dark-secondary mt-1 line-clamp-2">{rule.description}</p>
          )}
        </div>
        {confidence !== null && (
          <div className={cn(
            'shrink-0 text-xs font-bold px-2 py-1 rounded-full',
            confidence >= 80 ? 'bg-emerald-400/10 text-emerald-400' :
            confidence >= 50 ? 'bg-yellow-400/10 text-yellow-400' :
            'bg-orange-400/10 text-orange-400',
          )}>
            {confidence}%
          </div>
        )}
      </div>
      {!compact && (
        <div className="flex items-center gap-3 mt-2 text-[10px] text-dark-muted">
          {rule.source_benchmark && (
            <span>From: {rule.source_benchmark}</span>
          )}
          {SourceIcon && (
            <span className="flex items-center gap-1">
              <SourceIcon className="h-3 w-3" />
              {rule.command_source === 'template' ? 'Template' : rule.command_source === 'llm' ? 'AI Generated' : rule.command_source}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
