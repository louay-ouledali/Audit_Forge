import { useState, useMemo } from 'react';
import { Check, X, Edit3, Filter, Loader2, CheckCheck, XCircle, ClipboardList } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { CopilotPendingRule } from '@/services/api';
import RuleSuggestionCard from './RuleSuggestionCard';
import ConfirmDialog from '@/components/common/ConfirmDialog';

interface PendingRulesReviewProps {
  rules: CopilotPendingRule[];
  onApprove: (ruleIds: number[]) => Promise<void>;
  onReject: (ruleIds: number[]) => Promise<void>;
  onEditAndApprove: (ruleId: number, edits: Record<string, string>) => Promise<void>;
}

type ConfidenceFilter = 'all' | 'high' | 'medium' | 'low';

export default function PendingRulesReview({ rules, onApprove, onReject, onEditAndApprove }: PendingRulesReviewProps) {
  const [filter, setFilter] = useState<ConfidenceFilter>('all');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [showDenyConfirm, setShowDenyConfirm] = useState(false);

  const filtered = useMemo(() => rules.filter(r => {
    const conf = (r.confidence ?? 0) * 100;
    if (filter === 'high') return conf >= 80;
    if (filter === 'medium') return conf >= 50 && conf < 80;
    if (filter === 'low') return conf < 50;
    return true;
  }), [rules, filter]);

  const filteredIds = useMemo(() => filtered.map(r => r.id), [filtered]);

  const startEdit = (rule: CopilotPendingRule) => {
    setEditingId(rule.id);
    setEditValues({
      title: rule.title,
      severity: rule.severity,
      section_number: rule.section_number,
      description: rule.description || '',
    });
  };

  const submitEdit = async () => {
    if (!editingId) return;
    setLoadingAction(`edit-${editingId}`);
    try {
      await onEditAndApprove(editingId, editValues);
      setEditingId(null);
    } finally {
      setLoadingAction(null);
    }
  };

  const wrappedApprove = async (ids: number[]) => {
    const key = ids.length === 1 ? `approve-${ids[0]}` : 'bulk-approve';
    setLoadingAction(key);
    try { await onApprove(ids); } finally { setLoadingAction(null); }
  };

  const wrappedReject = async (ids: number[]) => {
    const key = ids.length === 1 ? `reject-${ids[0]}` : 'bulk-reject';
    setLoadingAction(key);
    try { await onReject(ids); } finally { setLoadingAction(null); }
  };

  if (!rules.length) {
    return (
      <div className="flex items-center justify-center h-full text-dark-muted text-sm">
        No pending rules to review
      </div>
    );
  }

  return (
<div className="flex flex-col h-full bg-dark-card/30">
        {/* Header */}
        <div className="px-5 py-4 border-b border-sky-500/10 shrink-0 space-y-3 bg-gradient-to-r from-sky-500/5 to-transparent relative">
          <div className="absolute top-0 right-0 w-32 h-32 bg-sky-500/5 rounded-full blur-2xl pointer-events-none" />
          <div className="flex items-center justify-between relative z-10">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <ClipboardList className="h-4 w-4 text-sky-400" />
              Pending Review
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-sky-500/20 text-sky-400 font-bold border border-sky-500/30">
              {rules.length}
            </span>
          </h3>
        </div>

        {/* Approve All / Deny All */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => wrappedApprove(filteredIds)}
            disabled={!!loadingAction || !filteredIds.length}
            className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/20 transition-colors disabled:opacity-50"
          >
            {loadingAction === 'bulk-approve' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCheck className="h-3.5 w-3.5" />}
            Approve All ({filtered.length})
          </button>
          <button
            onClick={() => setShowDenyConfirm(true)}
            disabled={!!loadingAction || !filteredIds.length}
            className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-medium bg-red-500/10 text-red-400 border border-red-500/30 hover:bg-red-500/20 transition-colors disabled:opacity-50"
          >
            {loadingAction === 'bulk-reject' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />}
            Deny All ({filtered.length})
          </button>
        </div>

        <ConfirmDialog
          open={showDenyConfirm}
          title="Deny All Rules"
          message={`This will permanently delete ${filtered.length} rule${filtered.length !== 1 ? 's' : ''}. This cannot be undone.`}
          confirmLabel={`Delete ${filtered.length} rule${filtered.length !== 1 ? 's' : ''}`}
          variant="danger"
          onConfirm={() => { setShowDenyConfirm(false); wrappedReject(filteredIds); }}
          onCancel={() => setShowDenyConfirm(false)}
        />

        {/* Confidence filter */}
        <div className="flex items-center gap-1.5">
          <Filter className="h-3 w-3 text-dark-muted" />
          {(['all', 'high', 'medium', 'low'] as ConfidenceFilter[]).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                'px-2 py-0.5 text-[10px] font-medium rounded-full border transition-colors',
                filter === f
                  ? 'border-ey-yellow/40 bg-ey-yellow/10 text-ey-yellow'
                  : 'border-dark-border text-dark-secondary hover:text-white',
              )}
            >
              {f === 'all' ? `All (${rules.length})` : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Rule list */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2 custom-scrollbar">
        {filtered.map(rule => (
          <div key={rule.id} className="rounded-lg border border-dark-border bg-dark-elevated p-3">
            {editingId === rule.id ? (
              <div className="space-y-2">
                <div className="flex gap-2">
                  <input
                    value={editValues.section_number || ''}
                    onChange={e => setEditValues({ ...editValues, section_number: e.target.value })}
                    className="w-20 bg-dark-bg border border-dark-border rounded px-2 py-1 text-xs text-white font-mono"
                    placeholder="1.1.1"
                  />
                  <select
                    value={editValues.severity || 'medium'}
                    onChange={e => setEditValues({ ...editValues, severity: e.target.value })}
                    className="bg-dark-bg border border-dark-border rounded px-2 py-1 text-xs text-white"
                  >
                    <option value="critical">Critical</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </div>
                <input
                  value={editValues.title || ''}
                  onChange={e => setEditValues({ ...editValues, title: e.target.value })}
                  className="w-full bg-dark-bg border border-dark-border rounded px-2 py-1.5 text-sm text-white"
                  placeholder="Rule title"
                />
                <textarea
                  value={editValues.description || ''}
                  onChange={e => setEditValues({ ...editValues, description: e.target.value })}
                  className="w-full bg-dark-bg border border-dark-border rounded px-2 py-1.5 text-xs text-white resize-none"
                  rows={3}
                  placeholder="Description (optional)"
                />
                {rule.confidence != null && (
                  <div className="text-[10px] text-dark-muted">
                    Confidence: {Math.round(rule.confidence * 100)}%
                    {rule.source_benchmark && ` · From: ${rule.source_benchmark}`}
                  </div>
                )}
                <div className="flex justify-end gap-2">
                  <button
                    onClick={() => setEditingId(null)}
                    className="text-xs px-3 py-1 rounded border border-dark-border text-dark-secondary hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={submitEdit}
                    disabled={!!loadingAction}
                    className="text-xs px-3 py-1 rounded bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/30 disabled:opacity-50 flex items-center gap-1"
                  >
                    {loadingAction === `edit-${rule.id}` && <Loader2 className="h-3 w-3 animate-spin" />}
                    Save & Approve
                  </button>
                </div>
              </div>
            ) : (
              <>
                <RuleSuggestionCard rule={rule} compact />
                <div className="flex items-center gap-1.5 mt-2 pt-2 border-t border-dark-border/50">
                  <button
                    onClick={() => wrappedApprove([rule.id])}
                    disabled={!!loadingAction}
                    className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/20 transition-colors disabled:opacity-50"
                  >
                    {loadingAction === `approve-${rule.id}` ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                    Approve
                  </button>
                  <button
                    onClick={() => startEdit(rule)}
                    disabled={!!loadingAction}
                    className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg bg-sky-500/10 text-sky-400 border border-sky-500/30 hover:bg-sky-500/20 transition-colors disabled:opacity-50"
                  >
                    <Edit3 className="h-3 w-3" /> Edit
                  </button>
                  <button
                    onClick={() => wrappedReject([rule.id])}
                    disabled={!!loadingAction}
                    className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg bg-red-500/10 text-red-400 border border-red-500/30 hover:bg-red-500/20 transition-colors disabled:opacity-50"
                  >
                    {loadingAction === `reject-${rule.id}` ? <Loader2 className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />}
                    Reject
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
