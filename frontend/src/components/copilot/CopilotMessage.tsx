import { useState } from 'react';
import { Sparkles, User, RefreshCw, ChevronDown, ChevronUp, Clock, Activity } from 'lucide-react';
import { cn } from '@/lib/utils';
import ReactMarkdown from 'react-markdown';
import RuleSuggestionCard from './RuleSuggestionCard';
import type { CopilotPendingRule, CopilotAction } from '@/types';

const PIPELINE_TOOLS = new Set([
  'start_enrichment', 'start_verification', 'start_validation',
  'pause_enrichment', 'regenerate_command',
]);

const PIPELINE_LABELS: Record<string, string> = {
  start_enrichment: 'Phase 2: Command Enrichment',
  start_verification: 'Command Verification',
  start_validation: 'Phase 3: Quality Validation',
  pause_enrichment: 'Enrichment Paused',
  regenerate_command: 'Command Regeneration',
};

export interface CopilotMessageData {
  id: string;
  role: 'user' | 'copilot' | 'system';
  content: string;
  rulesCreated?: CopilotPendingRule[];
  actions?: CopilotAction[];
  timestamp: Date;
  retryMessage?: string;
}

interface CopilotMessageProps {
  msg: CopilotMessageData;
  onRetry?: (message: string) => void;
  onSendMessage?: (message: string) => void;
}

export default function CopilotMessage({ msg, onRetry, onSendMessage }: CopilotMessageProps) {
  const isUser = msg.role === 'user';
  const isSystem = msg.role === 'system';
  const [expanded, setExpanded] = useState(false);
  const rulesCount = msg.rulesCreated?.length ?? 0;
  const showExpandToggle = rulesCount > 5;
  const visibleRules = expanded ? msg.rulesCreated : msg.rulesCreated?.slice(0, 5);
  const pipelineActions = msg.actions?.filter(a => PIPELINE_TOOLS.has(a.tool)) ?? [];

  return (
    <div className={cn('flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
      {!isSystem && (
        <div className={cn(
          'shrink-0 flex h-8 w-8 items-center justify-center rounded-lg shadow-sm border',
          isUser ? 'bg-ey-yellow/10 border-ey-yellow/20 text-ey-yellow shadow-[0_0_10px_rgba(255,230,0,0.1)]' : 'bg-sky-500/10 border-sky-500/20 text-sky-400 shadow-[0_0_10px_rgba(14,165,233,0.1)]'
        )}>
          {isUser ? <User className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
        </div>
      )}
      <div className={cn(
        'max-w-[85%] rounded-2xl px-4 py-3 text-sm shadow-sm border backdrop-blur-sm',
        isUser
          ? 'bg-gradient-to-br from-ey-yellow/10 to-ey-yellow/5 border-ey-yellow/20 text-white rounded-tr-sm'
          : isSystem
            ? 'bg-dark-elevated/50 border-dark-border/50 text-dark-secondary text-xs italic w-full text-center'
            : 'bg-gradient-to-br from-sky-500/5 to-transparent border-sky-500/10 text-sky-50 rounded-tl-sm',
      )}>
        {isSystem ? (
          <div>
            <p>{msg.content}</p>
            {msg.retryMessage && onRetry && (
              <button
                onClick={() => onRetry(msg.retryMessage!)}
                className="mt-1.5 inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30 hover:bg-amber-500/20 transition-colors"
              >
                <RefreshCw className="h-3 w-3" /> Retry
              </button>
            )}
          </div>
        ) : (
          <ReactMarkdown
            components={{
              p: ({ children }) => <p className="mb-1 last:mb-0">{children}</p>,
              strong: ({ children }) => <strong className="text-white font-semibold">{children}</strong>,
              ul: ({ children }) => <ul className="list-disc list-inside space-y-0.5 my-1">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal list-inside space-y-0.5 my-1">{children}</ol>,
              li: ({ children }) => <li className="text-dark-secondary">{children}</li>,
              code: ({ className, children, ...props }) => {
                const isBlock = className?.includes('language-');
                if (isBlock) {
                  return (
                    <pre className="bg-dark-bg rounded-md p-2 my-1 overflow-x-auto text-xs">
                      <code className="text-emerald-400">{children}</code>
                    </pre>
                  );
                }
                return <code className="bg-dark-bg px-1 py-0.5 rounded text-xs text-amber-400" {...props}>{children}</code>;
              },
              h1: ({ children }) => <h1 className="text-base font-bold text-white mt-2 mb-1">{children}</h1>,
              h2: ({ children }) => <h2 className="text-sm font-bold text-white mt-2 mb-1">{children}</h2>,
              h3: ({ children }) => <h3 className="text-sm font-semibold text-white mt-1.5 mb-0.5">{children}</h3>,
              table: ({ children }) => (
                <div className="overflow-x-auto my-1">
                  <table className="text-xs border-collapse w-full">{children}</table>
                </div>
              ),
              th: ({ children }) => <th className="border border-dark-border px-2 py-1 text-left text-white bg-dark-bg">{children}</th>,
              td: ({ children }) => <td className="border border-dark-border px-2 py-1">{children}</td>,
            }}
          >
            {msg.content}
          </ReactMarkdown>
        )}

        {/* Inline rule cards */}
        {visibleRules && visibleRules.length > 0 && (
          <div className="mt-2 space-y-1.5">
            {visibleRules.map((rule, i) => (
              <RuleSuggestionCard key={rule.id ?? i} rule={rule} compact />
            ))}
            {showExpandToggle && (
              <button
                onClick={() => setExpanded(!expanded)}
                className="flex items-center gap-1 text-xs text-dark-muted hover:text-white transition-colors mt-1"
              >
                {expanded ? (
                  <><ChevronUp className="h-3 w-3" /> Show less</>
                ) : (
                  <><ChevronDown className="h-3 w-3" /> +{rulesCount - 5} more rules</>
                )}
              </button>
            )}
          </div>
        )}

        {/* Inline pipeline action cards */}
        {pipelineActions.length > 0 && (
          <div className="mt-2 space-y-1.5">
            {pipelineActions.map((action, i) => (
              <div
                key={i}
                className="flex items-center justify-between rounded-md border border-amber-500/20 bg-amber-500/5 px-2.5 py-1.5"
              >
                <div className="flex items-center gap-2">
                  <Activity className="h-3.5 w-3.5 text-amber-400 animate-pulse" />
                  <span className="text-xs font-medium text-amber-400">
                    {PIPELINE_LABELS[action.tool] ?? action.tool}
                  </span>
                  <span className="text-[10px] text-dark-muted">started</span>
                </div>
                {onSendMessage && (
                  <button
                    onClick={() => onSendMessage('What is the current pipeline status?')}
                    className="text-[10px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 transition-colors"
                  >
                    Check progress
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Timestamp */}
        {!isSystem && msg.timestamp && (
          <div className="flex items-center gap-1 mt-1.5 text-[10px] text-dark-muted">
            <Clock className="h-2.5 w-2.5" />
            {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </div>
        )}
      </div>
    </div>
  );
}
