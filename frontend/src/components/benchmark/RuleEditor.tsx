import { useState } from 'react';
import { Plus, Sparkles, Loader2 } from 'lucide-react';
import type { AIRuleCreateRequest, AIRuleCreateResponse } from '@/types';
import { createRuleWithAI } from '@/services/api';

interface RuleEditorProps {
  benchmarkId: number;
  onRuleCreated: (result: AIRuleCreateResponse) => void;
  onCancel: () => void;
  existingSections?: string[];
}

export default function RuleEditor({ benchmarkId, onRuleCreated, onCancel, existingSections = [] }: RuleEditorProps) {
  const [sectionNumber, setSectionNumber] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [rationale, setRationale] = useState('');
  const [severity, setSeverity] = useState('medium');
  const [profileApplicability, setProfileApplicability] = useState('');
  const [generateCommands, setGenerateCommands] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sectionNumber.trim() || !title.trim()) {
      setError('Section number and title are required');
      return;
    }
    if (existingSections.includes(sectionNumber.trim())) {
      setError(`Section ${sectionNumber} already exists in this benchmark`);
      return;
    }

    setLoading(true);
    setError('');

    try {
      const payload: AIRuleCreateRequest = {
        section_number: sectionNumber.trim(),
        title: title.trim(),
        description: description.trim() || undefined,
        rationale: rationale.trim() || undefined,
        severity,
        profile_applicability: profileApplicability.trim() || undefined,
        generate_commands: generateCommands,
      };
      const result = await createRuleWithAI(benchmarkId, payload);
      onRuleCreated(result);
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to create rule');
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-ey-yellow/30 bg-dark-card p-5 space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <Plus className="h-5 w-5 text-ey-yellow" />
        <h3 className="text-base font-semibold text-white">Add New Rule</h3>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-2.5 text-sm text-red-400">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Section Number */}
        <div>
          <label className="block text-xs text-dark-secondary mb-1">Section Number *</label>
          <input
            type="text"
            value={sectionNumber}
            onChange={(e) => setSectionNumber(e.target.value)}
            placeholder="e.g. 1.1.1"
            className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/30 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20"
            required
          />
        </div>

        {/* Severity */}
        <div>
          <label className="block text-xs text-dark-secondary mb-1">Severity</label>
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
            className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white focus:border-ey-yellow/30 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20"
          >
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>

        {/* Profile */}
        <div>
          <label className="block text-xs text-dark-secondary mb-1">Profile Applicability</label>
          <input
            type="text"
            value={profileApplicability}
            onChange={(e) => setProfileApplicability(e.target.value)}
            placeholder="e.g. Level 1"
            className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/30 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20"
          />
        </div>
      </div>

      {/* Title */}
      <div>
        <label className="block text-xs text-dark-secondary mb-1">Title *</label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Ensure 'Enforce password history' is set to '24 or more password(s)'"
          className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/30 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20"
          required
        />
      </div>

      {/* Description */}
      <div>
        <label className="block text-xs text-dark-secondary mb-1">Description</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What does this rule check? The AI will use this to generate audit commands."
          rows={3}
          className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/30 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20 resize-none"
        />
      </div>

      {/* Rationale */}
      <div>
        <label className="block text-xs text-dark-secondary mb-1">Rationale</label>
        <textarea
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          placeholder="Why is this rule important? (optional)"
          rows={2}
          className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/30 focus:outline-none focus:ring-1 focus:ring-ey-yellow/20 resize-none"
        />
      </div>

      {/* Generate Commands Toggle */}
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={generateCommands}
          onChange={(e) => setGenerateCommands(e.target.checked)}
          className="rounded border-dark-border bg-dark-elevated text-ey-yellow focus:ring-ey-yellow/20"
        />
        <Sparkles className="h-4 w-4 text-ey-yellow" />
        <span className="text-sm text-dark-secondary">
          Auto-generate audit &amp; remediation commands with AI
        </span>
      </label>

      {/* Actions */}
      <div className="flex items-center gap-3 pt-2">
        <button
          type="submit"
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50 transition-colors"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              {generateCommands ? 'Creating rule + generating commands...' : 'Creating rule...'}
            </>
          ) : (
            <>
              <Plus className="h-4 w-4" /> Add Rule
            </>
          )}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={loading}
          className="rounded-lg border border-dark-border px-4 py-2 text-sm text-dark-secondary hover:bg-dark-overlay hover:text-white transition-colors"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
