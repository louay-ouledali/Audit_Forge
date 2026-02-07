import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  ArrowLeft,
  Loader2,
  Sparkles,
  Save,
  CheckCircle2,
  AlertTriangle,
  FileText,
} from 'lucide-react';
import type { Finding } from '@/types';
import * as api from '@/services/api';

function statusBadge(status: string) {
  const styles: Record<string, string> = {
    PASS: 'bg-green-100 text-green-800',
    FAIL: 'bg-red-100 text-red-800',
    ERROR: 'bg-yellow-100 text-yellow-800',
    MANUAL_REVIEW: 'bg-blue-100 text-blue-800',
    NOT_APPLICABLE: 'bg-gray-100 text-gray-600',
    SKIPPED: 'bg-gray-100 text-gray-600',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status] || 'bg-gray-100 text-gray-600'}`}>
      {status}
    </span>
  );
}

function severityBadge(severity: string | null) {
  if (!severity) return null;
  const styles: Record<string, string> = {
    critical: 'bg-red-100 text-red-800',
    high: 'bg-orange-100 text-orange-800',
    medium: 'bg-yellow-100 text-yellow-800',
    low: 'bg-green-100 text-green-800',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[severity] || 'bg-gray-100 text-gray-600'}`}>
      {severity}
    </span>
  );
}

export default function FindingDetail() {
  const { id } = useParams<{ id: string }>();
  const [finding, setFinding] = useState<Finding | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // AI advice
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState('');

  // Annotations
  const [notes, setNotes] = useState('');
  const [override, setOverride] = useState('');
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
      })
      .catch(() => setError('Failed to load finding'))
      .finally(() => setLoading(false));
  }, [id]);

  async function handleGetAIAdvice() {
    if (!finding) return;
    setAiLoading(true);
    setAiError('');
    try {
      const result = await api.generateAIAdvice(finding.id);
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
        <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
      </div>
    );
  }

  if (error || !finding) {
    return (
      <div className="space-y-4">
        <Link to="/findings" className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800">
          <ArrowLeft className="h-4 w-4" /> Back to findings
        </Link>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error || 'Finding not found'}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Link to="/findings" className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800">
          <ArrowLeft className="h-4 w-4" /> Back to findings
        </Link>
        <div className="mt-3 flex items-center gap-3">
          <h1 className="text-2xl font-bold text-gray-900">
            {finding.section_number || 'Finding'} — {finding.rule_title || `Finding #${finding.id}`}
          </h1>
          {statusBadge(finding.status)}
          {severityBadge(finding.severity)}
        </div>
        <p className="mt-1 text-sm text-gray-500">Scan #{finding.scan_id} • Rule #{finding.rule_id}</p>
      </div>

      {/* Expected vs Actual */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-700">
            <CheckCircle2 className="h-4 w-4 text-green-500" />
            Expected Output (Regex)
          </h3>
          <pre className="max-h-64 overflow-auto rounded-lg bg-gray-50 p-4 text-sm text-gray-800 font-mono">
            {finding.expected_output || 'No expected output pattern defined'}
          </pre>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-700">
            <FileText className="h-4 w-4 text-blue-500" />
            Actual Output
          </h3>
          <pre className="max-h-64 overflow-auto rounded-lg bg-gray-50 p-4 text-sm text-gray-800 font-mono">
            {finding.actual_output || 'No output captured'}
          </pre>
        </div>
      </div>

      {/* AI Advice */}
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-700">
            <Sparkles className="h-4 w-4 text-purple-500" />
            AI Remediation Advice
          </h3>
          {!finding.ai_advice && (
            <button
              onClick={handleGetAIAdvice}
              disabled={aiLoading}
              className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            >
              {aiLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {aiLoading ? 'Generating...' : 'Get AI Advice'}
            </button>
          )}
        </div>
        {aiError && (
          <div className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{aiError}</div>
        )}
        {finding.ai_advice ? (
          <div className="prose prose-sm max-w-none">
            <pre className="whitespace-pre-wrap rounded-lg bg-gray-50 p-4 text-sm text-gray-800">
              {finding.ai_advice}
            </pre>
            {finding.ai_advice_generated_at && (
              <p className="mt-2 text-xs text-gray-400">
                Generated at {new Date(finding.ai_advice_generated_at).toLocaleString()}
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-gray-500">
            Click &quot;Get AI Advice&quot; to generate remediation recommendations using AI.
          </p>
        )}
      </div>

      {/* Auditor Annotations */}
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold text-gray-700">
          <AlertTriangle className="h-4 w-4 text-yellow-500" />
          Auditor Annotations
        </h3>
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Override Status</label>
            <select
              className="w-full max-w-xs rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
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
            <label className="mb-1 block text-sm font-medium text-gray-700">Notes</label>
            <textarea
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              rows={4}
              placeholder="Add auditor notes..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleSaveAnnotations}
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {saving ? 'Saving...' : 'Save Annotations'}
            </button>
            {saveSuccess && (
              <span className="flex items-center gap-1 text-sm text-green-600">
                <CheckCircle2 className="h-4 w-4" /> Saved
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
