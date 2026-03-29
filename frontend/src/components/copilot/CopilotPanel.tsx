import { useState, useRef, useEffect, useCallback } from 'react';
import { Sparkles, Send, Loader2, ClipboardList, Search, HelpCircle, ShieldAlert, BarChart3, X, Activity, CheckCircle2, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useToast } from '@/components/common/Toast';
import CopilotMessage, { type CopilotMessageData } from './CopilotMessage';
import PendingRulesReview from './PendingRulesReview';
import PipelineStatusBar from './PipelineStatusBar';
import {
  copilotChat,
  copilotGenerateBenchmark,
  copilotApprove,
  copilotApproveWithEdits,
  copilotGetPending,
  type CopilotPendingRule,
} from '@/services/api';
import type { EnrichStatus, VerifyStatus, ValidateStatus } from '@/types';

interface CopilotPanelProps {
  benchmarkId: number;
  benchmarkName: string;
  platform: string;
  platformFamily: string;
  onRulesChanged: () => void;
  phase1Status?: string;
  enrichStatus?: EnrichStatus | null;
  verifyStatus?: VerifyStatus | null;
  validateStatus?: ValidateStatus | null;
}

import BrandLockup from '@/components/common/BrandLockup';

// ── Module-level cache so chat survives tab switches ──
const _chatCache = new Map<number, { messages: CopilotMessageData[]; conversationId?: string }>();

export default function CopilotPanel({
  benchmarkId,
  benchmarkName,
  platform,
  platformFamily,
  onRulesChanged,
  phase1Status,
  enrichStatus,
  verifyStatus,
  validateStatus,
}: CopilotPanelProps) {
  const cached = _chatCache.get(benchmarkId);
  const [messages, setMessages] = useState<CopilotMessageData[]>(cached?.messages ?? []);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | undefined>(cached?.conversationId);
  const [pendingRules, setPendingRules] = useState<CopilotPendingRule[]>([]);
  const [showPending, setShowPending] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const lastUserMsgRef = useRef<string>('');
  const toast = useToast();

  // Persist to cache on every change
  useEffect(() => {
    _chatCache.set(benchmarkId, { messages, conversationId });
  }, [messages, conversationId, benchmarkId]);

  const scrollToBottom = useCallback(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);

  useEffect(() => {
    inputRef.current?.focus();
    refreshPending();
  }, []);

  // Auto-open pending panel if there are pending rules from cache
  useEffect(() => {
    if (pendingRules.length > 0 && messages.length > 0) setShowPending(true);
  }, [pendingRules.length, messages.length]);

  const refreshPending = async () => {
    try {
      const data = await copilotGetPending(benchmarkId);
      setPendingRules(data.rules);
    } catch {
      // silent on initial load
    }
  };

  const addMessage = (msg: Omit<CopilotMessageData, 'id' | 'timestamp'>) => {
    setMessages(prev => [...prev, {
      ...msg,
      id: crypto.randomUUID(),
      timestamp: new Date(),
    }]);
  };

  const cancelRequest = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsLoading(false);
    addMessage({ role: 'system', content: 'Request cancelled.' });
  }, []);

  const handleRetry = useCallback((retryText: string) => {
    sendMessage(retryText);
  }, []);

  const sendMessage = async (text?: string) => {
    const msg = text || input.trim();
    if (!msg || isLoading) return;
    setInput('');
    lastUserMsgRef.current = msg;

    addMessage({ role: 'user', content: msg });
    setIsLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await copilotChat(benchmarkId, msg, conversationId, controller.signal);
      setConversationId(res.conversation_id);

      if (res.intent === 'create_benchmark' || res.intent === 'add_rules') {
        addMessage({ role: 'copilot', content: 'Starting the rule generation pipeline...' });
        const description = res.actions?.[0]?.description || msg;
        const pipeline = await copilotGenerateBenchmark(benchmarkId, description, platform, platformFamily, controller.signal);
        const progressText = pipeline.progress.join('\n');
        addMessage({
          role: 'copilot',
          content: progressText + `\n\n**${pipeline.stats.total_pending} rules** are ready for review.`,
          rulesCreated: pipeline.created?.rules,
        });
        await refreshPending();
        onRulesChanged();
      } else {
        const createdRules = res.actions?.find((a: any) => a.tool === 'create_rules_batch')?.result?.rules;
        const searchResults = res.actions?.find((a: any) => a.tool === 'search_rules')?.result;
        addMessage({
          role: 'copilot',
          content: res.response,
          rulesCreated: createdRules || (Array.isArray(searchResults) ? searchResults : undefined),
          actions: res.actions,
        });
        if (res.pending_rules) setPendingRules(res.pending_rules);
        if (createdRules) {
          await refreshPending();
          onRulesChanged();
        }
      }
    } catch (err: any) {
      if (err?.name === 'AbortError' || err?.code === 'ERR_CANCELED') return;
      const errMsg = err?.response?.data?.detail || err?.message || 'Something went wrong';
      addMessage({ role: 'system', content: `Error: ${errMsg}`, retryMessage: msg });
      toast.error(errMsg);
    } finally {
      abortRef.current = null;
      setIsLoading(false);
    }
  };

  // ── Approval handlers — toast only, no chat system messages ──
  const handleApprove = async (ruleIds: number[]) => {
    try {
      await copilotApprove(benchmarkId, ruleIds, 'approve');
      toast.success(`Approved ${ruleIds.length} rule(s)`);
      await refreshPending();
      onRulesChanged();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to approve rules');
    }
  };

  const handleReject = async (ruleIds: number[]) => {
    try {
      await copilotApprove(benchmarkId, ruleIds, 'reject');
      toast.success(`Rejected ${ruleIds.length} rule(s)`);
      await refreshPending();
      onRulesChanged();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to reject rules');
    }
  };

  const handleEditAndApprove = async (ruleId: number, edits: Record<string, string>) => {
    try {
      await copilotApproveWithEdits(benchmarkId, ruleId, edits);
      toast.success('Edited and approved rule');
      await refreshPending();
      onRulesChanged();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to approve rule with edits');
    }
  };

  const quickActions = [
    // Row 1 — Rules
    { label: `Create rules for ${platform}`, prompt: `Create hardening rules for ${platform}`, icon: Sparkles },
    { label: 'Analyze gaps', prompt: 'What security areas are we missing coverage for?', icon: ShieldAlert },
    { label: 'Search rules', prompt: 'Search for rules about ', icon: Search },
    { label: 'Explain a rule', prompt: 'Explain rule ', icon: HelpCircle },
    // Row 2 — Pipeline & Quality
    { label: 'Pipeline status', prompt: 'Show me the current pipeline status and what I should do next', icon: Activity },
    { label: 'Start enrichment', prompt: 'Start Phase 2 enrichment for rules without commands', icon: RefreshCw },
    { label: 'Review corrections', prompt: 'Show me the Phase 3 validation corrections', icon: CheckCircle2 },
    { label: 'Migration readiness', prompt: 'Is this benchmark ready for deployment?', icon: BarChart3 },
  ];

  return (
    <div className="flex gap-4 h-[calc(100vh-280px)] min-h-[500px]">
      {/* Chat Column */}
      <div className={cn(
        'flex flex-col rounded-2xl border border-sky-500/20 bg-dark-card/60 shadow-[0_0_40px_rgba(14,165,233,0.05)] backdrop-blur-md overflow-hidden transition-all',
        showPending && pendingRules.length > 0 ? 'w-3/5' : 'w-full',
      )}>
        {/* Chat Header */}
        <div className="relative flex items-center justify-between px-5 py-4 border-b border-sky-500/10 bg-dark-card shrink-0">
          <div className="absolute inset-0 bg-gradient-to-r from-sky-500/5 to-transparent pointer-events-none" />
          <div className="relative z-10 flex items-center gap-3">
            <BrandLockup service="copilot" size="md" />
            <div className="pl-3 border-l border-dark-border/50">
              <p className="text-[11px] font-medium text-dark-muted truncate max-w-[300px]">Context: {benchmarkName}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {messages.length > 0 && (
              <button
                onClick={() => { setMessages([]); setConversationId(undefined); _chatCache.delete(benchmarkId); }}
                className="text-[11px] px-2.5 py-1 rounded-lg text-dark-muted hover:text-white border border-dark-border hover:border-dark-secondary transition-colors"
              >
                Clear chat
              </button>
            )}
            {pendingRules.length > 0 && (
              <button
                onClick={() => { setShowPending(!showPending); refreshPending(); }}
                className={cn(
                  'flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                  showPending
                    ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40'
                    : 'bg-dark-elevated text-dark-secondary hover:text-white border border-dark-border',
                )}
              >
                <ClipboardList className="h-3.5 w-3.5" />
                Pending: {pendingRules.length}
              </button>
            )}
          </div>
        </div>

        {/* Pipeline Status Bar */}
        <PipelineStatusBar
          phase1Status={phase1Status ?? 'idle'}
          enrichStatus={enrichStatus ?? null}
          verifyStatus={verifyStatus ?? null}
          validateStatus={validateStatus ?? null}
          onQuickMessage={sendMessage}
        />

        {/* Chat Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-500/10 border border-amber-500/20">
                <Sparkles className="h-7 w-7 text-amber-400" />
              </div>
              <div className="text-center">
                <p className="text-sm font-medium text-white">Forge Copilot</p>
                <p className="text-xs text-dark-secondary mt-1">AI-assisted benchmark creation & management</p>
              </div>
              <div className="w-full max-w-2xl grid grid-cols-4 gap-2 mt-4">
                {quickActions.map((qa, i) => (
                  <button
                    key={i}
                    onClick={() => {
                      if (qa.prompt.endsWith(' ')) {
                        setInput(qa.prompt);
                        inputRef.current?.focus();
                      } else {
                        sendMessage(qa.prompt);
                      }
                    }}
                    className="flex items-center gap-2 text-left px-3 py-2.5 rounded-lg border border-dark-border bg-dark-elevated text-xs text-dark-secondary hover:text-white hover:border-amber-500/30 transition-colors"
                  >
                    <qa.icon className="h-3.5 w-3.5 shrink-0 text-amber-400/60" />
                    <span className="truncate">{qa.label}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map(msg => (
                <CopilotMessage key={msg.id} msg={msg} onRetry={handleRetry} onSendMessage={sendMessage} />
              ))}
              {isLoading && (
                <div className="flex gap-2 items-start">
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-purple-500/15 text-purple-400 shrink-0">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="rounded-lg bg-dark-elevated px-3 py-2 text-sm text-dark-muted">
                      Thinking...
                    </div>
                    <button
                      onClick={cancelRequest}
                      className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-dark-muted hover:text-red-400 border border-dark-border hover:border-red-500/30 transition-colors"
                    >
                      <X className="h-3 w-3" /> Cancel
                    </button>
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </>
          )}
        </div>

        {/* Input Area */}
        <div className="shrink-0 border-t border-dark-border p-3 bg-dark-card">
          <form
            onSubmit={e => { e.preventDefault(); sendMessage(); }}
            className="flex items-center gap-2"
          >
            <input
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="Ask Forge Copilot..."
              className="flex-1 bg-dark-elevated border border-dark-border rounded-lg px-3 py-2 text-sm text-white placeholder:text-dark-muted focus:outline-none focus:border-amber-500/40 transition-colors"
              disabled={isLoading}
            />
            <button
              type="submit"
              disabled={!input.trim() || isLoading}
              className={cn(
                'flex h-9 w-9 items-center justify-center rounded-lg transition-colors',
                input.trim() && !isLoading
                  ? 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30 border border-amber-500/40'
                  : 'bg-dark-elevated text-dark-muted border border-dark-border',
              )}
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </div>
      </div>

      {/* Pending Rules Column */}
      {showPending && pendingRules.length > 0 && (
        <div className="w-2/5 rounded-2xl border border-sky-500/20 bg-dark-card/60 shadow-[0_0_40px_rgba(14,165,233,0.05)] backdrop-blur-md overflow-hidden flex flex-col">
          <PendingRulesReview
            rules={pendingRules}
            onApprove={handleApprove}
            onReject={handleReject}
            onEditAndApprove={handleEditAndApprove}
          />
        </div>
      )}
    </div>
  );
}
