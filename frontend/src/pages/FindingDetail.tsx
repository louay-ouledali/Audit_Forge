import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Loader2,
  Sparkles,
  Save,
  CheckCircle2,
  AlertTriangle,
  FileText,
  RefreshCw,
  Pencil,
} from 'lucide-react';
import Markdown from 'react-markdown';
import type { Finding } from '@/types';
import * as api from '@/services/api';

function statusBadge(status: string) {
  const styles: Record<string, string> = {
    PASS: 'bg-green-500/10 text-green-400',
    FAIL: 'bg-red-500/10 text-red-400',
    ERROR: 'bg-yellow-500/10 text-yellow-400',
    MANUAL_REVIEW: 'bg-blue-500/10 text-blue-400',
    NOT_APPLICABLE: 'bg-dark-overlay text-dark-muted',
    SKIPPED: 'bg-dark-overlay text-dark-muted',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status] || 'bg-dark-overlay text-dark-muted'}`}>
      {status}
    </span>
  );
}

function severityBadge(severity: string | null) {
  if (!severity) return null;
  const styles: Record<string, string> = {
    critical: 'bg-red-500/10 text-red-400',
    high: 'bg-orange-500/10 text-orange-400',
    medium: 'bg-yellow-500/10 text-yellow-400',
    low: 'bg-green-500/10 text-green-400',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[severity] || 'bg-dark-overlay text-dark-muted'}`}>
      {severity}
    </span>
  );
}

export default function FindingDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [finding, setFinding] = useState<Finding | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // AI advice
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState('');

  // Annotations
  const [notes, setNotes] = useState('');
  const [override, setOverride] = useState('');
  const [auditorDesc, setAuditorDesc] = useState('');
  const [auditorRemediation, setAuditorRemediation] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    api
      .getFinding(Number(id))
      .then((f) => {
        setFinding(f);
        setNotes(f.auditor_notes || '');
        setOverride(f.auditor_override || '');
        setAuditorDesc(f.auditor_description || '');
        setAuditorRemediation(f.auditor_remediation || '');
      })
      .catch(() => setError('Failed to load finding'))
      .finally(() => setLoading(false));
  }, [id]);

  async function handleGetAIAdvice(force = false) {
    if (!finding) return;
    setAiLoading(true);
    setAiError('');
    try {
      const result = await api.generateAIAdvice(finding.id, force);
      setFinding({ ...finding, ai_advice: result.advice, ai_advice_generated_at: result.generated_at });
    } catch (err: unknown) {
      const message = err instanceof Error && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : undefined;
      setAiError(message || 'Failed to generate AI advice');
    } finally {
      setAiLoading(false);
    }
  }

  async function handleSaveAnnotations() {
    if (!finding) return;
    setSaving(true);
    setSaveSuccess(false);
    try {
      const updated = await api.updateFinding(finding.id, {
        auditor_notes: notes,
        auditor_override: override,
        auditor_description: auditorDesc,
        auditor_remediation: auditorRemediation,
      });
      setFinding(updated);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      const message = err instanceof Error && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : undefined;
      setError(message || 'Failed to save annotations');
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-ey-yellow" />
      </div>
    );
  }

  if (error || !finding) {
    return (
      <div className="space-y-4">
        <button onClick={() => navigate(-1)} className="inline-flex items-center gap-1 text-sm text-ey-yellow hover:text-ey-yellow-hover">
          <ArrowLeft className="h-4 w-4" /> Back
        </button>
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          {error || 'Finding not found'}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <button onClick={() => navigate(-1)} className="inline-flex items-center gap-1 text-sm text-ey-yellow hover:text-ey-yellow-hover">
          <ArrowLeft className="h-4 w-4" /> Back
        </button>
        <div className="mt-3 flex items-center gap-3">
          <h1 className="text-2xl font-bold text-white">
            {finding.section_number || 'Finding'} {' - '} {finding.rule_title || `Finding #${finding.id}`}
          </h1>
          {statusBadge(finding.status)}
          {severityBadge(finding.severity)}
        </div>
        <p className="mt-1 text-sm text-dark-secondary">Scan #{finding.scan_id} {'\u00b7'} Rule #{finding.rule_id}</p>
      </div>

      {/* Expected vs Actual — Two-column side-by-side layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-dark-border bg-dark-card p-6">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-300">
            <CheckCircle2 className="h-4 w-4 text-green-400" />
            Expected Output
          </h3>
          {finding.expected_output_display && (
            <div className="mb-2 rounded-lg bg-blue-500/10 border border-blue-500/30 p-3 text-sm font-medium text-blue-400">
              {finding.expected_output_display}
            </div>
          )}
          <pre className="max-h-64 overflow-auto rounded-lg bg-dark-elevated p-4 text-sm text-gray-300 font-mono">
            {finding.expected_output || 'No expected output defined'}
          </pre>
          {finding.evaluation_explanation && (
            <div className={`mt-2 rounded-lg p-3 text-sm font-medium ${
              finding.status === 'PASS'
                ? 'bg-green-500/10 border border-green-500/30 text-green-400'
                : 'bg-red-500/10 border border-red-500/30 text-red-400'
            }`}>
              {finding.evaluation_explanation}
            </div>
          )}
        </div>
        <div className="rounded-xl border border-dark-border bg-dark-card p-6">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-300">
            <FileText className="h-4 w-4 text-blue-400" />
            Actual Output
          </h3>
          <pre className="max-h-64 overflow-auto rounded-lg bg-dark-elevated p-4 text-sm text-gray-300 font-mono">
            {finding.actual_output || 'No output captured'}
          </pre>
        </div>
      </div>

      {/* AI Advice */}
      <div className="rounded-xl border border-dark-border bg-dark-card p-6">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-300">
            <Sparkles className="h-4 w-4 text-purple-400" />
            AI Remediation Advice
          </h3>
          <div className="flex items-center gap-2">
            {finding.ai_advice && (
              <button
                onClick={() => handleGetAIAdvice(true)}
                disabled={aiLoading}
                className="inline-flex items-center gap-1.5 rounded-lg border border-purple-500/30 px-3 py-1.5 text-sm font-medium text-purple-400 hover:bg-purple-500/10 disabled:opacity-50"
              >
                {aiLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                Regenerate
              </button>
            )}
            {!finding.ai_advice && (
              <button
                onClick={() => handleGetAIAdvice(false)}
                disabled={aiLoading}
                className="inline-flex items-center gap-2 rounded-lg bg-purple-500/20 border border-purple-500/30 px-3 py-1.5 text-sm font-medium text-purple-400 hover:bg-purple-500/30 disabled:opacity-50"
              >
                {aiLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {aiLoading ? 'Generating\u2026' : 'Get AI Advice'}
              </button>
            )}
          </div>
        </div>
        {aiError && (
          <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{aiError}</div>
        )}
        {finding.ai_advice ? (
          <div>
            <div className="prose prose-sm prose-invert max-w-none rounded-lg bg-dark-elevated p-4 [&_pre]:bg-gray-900 [&_pre]:p-3 [&_pre]:rounded-lg [&_code]:text-emerald-400 [&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm [&_p]:text-gray-300 [&_li]:text-gray-300 [&_strong]:text-white [&_ol]:list-decimal [&_ul]:list-disc">
              <Markdown>{finding.ai_advice}</Markdown>
            </div>
            {finding.ai_advice_generated_at && (
              <p className="mt-2 text-xs text-dark-muted">
                Generated at {new Date(finding.ai_advice_generated_at).toLocaleString()}
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-dark-secondary">
            Click &quot;Get AI Advice&quot; to generate remediation recommendations using AI.
          </p>
        )}
      </div>

      {/* Auditor Annotations */}
      <div className="rounded-xl border border-dark-border bg-dark-card p-6">
        <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-gray-300">
          <AlertTriangle className="h-4 w-4 text-yellow-400" />
          Auditor Annotations
        </h3>
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-300">Override Status</label>
            <select
              className="w-full max-w-xs rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
              value={override}
              onChange={(e) => setOverride(e.target.value)}
            >
              <option value="">No override</option>
              <option value="confirmed">Confirmed</option>
              <option value="false_positive">False Positive</option>
              <option value="accepted_risk">Accepted Risk</option>
            </select>
          </div>
          <div>
            <label className="mb-1 flex items-center gap-2 text-sm font-medium text-gray-300">
              <Pencil className="h-3.5 w-3.5 text-ey-yellow" />
              Custom Description
            </label>
            <p className="mb-1 text-xs text-dark-muted">Overrides the rule's default description in reports.</p>
            <textarea
              className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
              rows={3}
              placeholder="Write a custom description for this finding…"
              value={auditorDesc}
              onChange={(e) => setAuditorDesc(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 flex items-center gap-2 text-sm font-medium text-gray-300">
              <Pencil className="h-3.5 w-3.5 text-ey-yellow" />
              Custom Remediation
            </label>
            <p className="mb-1 text-xs text-dark-muted">Overrides the rule's default remediation text in reports.</p>
            <textarea
              className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
              rows={3}
              placeholder="Write custom remediation steps…"
              value={auditorRemediation}
              onChange={(e) => setAuditorRemediation(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-300">Notes</label>
            <textarea
              className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30"
              rows={4}
              placeholder="Add auditor notes\u2026"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleSaveAnnotations}
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {saving ? 'Saving\u2026' : 'Save Annotations'}
            </button>
            {saveSuccess && (
              <span className="flex items-center gap-1 text-sm text-green-400">
                <CheckCircle2 className="h-4 w-4" /> Saved
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
