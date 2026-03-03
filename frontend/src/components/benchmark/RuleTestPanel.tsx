import { useState, useEffect } from 'react';
import { Play, CheckCircle2, XCircle, AlertTriangle, Loader2, Terminal, Clock, Server } from 'lucide-react';
import type { Target, RuleTestResponse, RuleValidateRequest } from '@/types';
import * as api from '@/services/api';

interface RuleTestPanelProps {
  benchmarkId: number;
  ruleId: number;
  sectionNumber: string;
  hasCommand: boolean;
  onValidated?: () => void;
}

function matchBadge(result: string) {
  const styles: Record<string, { bg: string; icon: React.ReactNode }> = {
    pass: { bg: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30', icon: <CheckCircle2 className="h-3.5 w-3.5" /> },
    fail: { bg: 'bg-red-500/10 text-red-400 border-red-500/30', icon: <XCircle className="h-3.5 w-3.5" /> },
    error: { bg: 'bg-orange-500/10 text-orange-400 border-orange-500/30', icon: <AlertTriangle className="h-3.5 w-3.5" /> },
    unknown: { bg: 'bg-dark-overlay text-dark-secondary border-dark-border', icon: <AlertTriangle className="h-3.5 w-3.5" /> },
  };
  const style = styles[result] || styles.unknown;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold ${style.bg}`}>
      {style.icon}
      {result.toUpperCase()}
    </span>
  );
}

export default function RuleTestPanel({ benchmarkId, ruleId, sectionNumber, hasCommand, onValidated }: RuleTestPanelProps) {
  const [targets, setTargets] = useState<Target[]>([]);
  const [selectedTargetId, setSelectedTargetId] = useState<number | null>(null);
  const [timeout, setTimeout_] = useState(30);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<RuleTestResponse | null>(null);
  const [testError, setTestError] = useState('');
  const [validating, setValidating] = useState(false);
  const [validateMsg, setValidateMsg] = useState('');
  const [showCorrection, setShowCorrection] = useState(false);
  const [correctedCommand, setCorrectedCommand] = useState('');
  const [correctedRegex, setCorrectedRegex] = useState('');
  const [validationNotes, setValidationNotes] = useState('');

  useEffect(() => {
    api.getAllTargets().then(setTargets).catch(() => {});
  }, []);

  const handleTest = async () => {
    if (!selectedTargetId) return;
    setTesting(true);
    setTestError('');
    setTestResult(null);
    setValidateMsg('');
    try {
      const result = await api.testRuleCommand(benchmarkId, ruleId, {
        target_id: selectedTargetId,
        timeout: timeout,
      });
      setTestResult(result);
    } catch (err: unknown) {
      setTestError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to execute test');
    } finally {
      setTesting(false);
    }
  };

  const handleValidate = async (status: RuleValidateRequest['validation_status']) => {
    setValidating(true);
    setValidateMsg('');
    try {
      const payload: RuleValidateRequest = {
        validation_status: status,
        notes: validationNotes.trim() || undefined,
        corrected_command: status === 'corrected' ? correctedCommand.trim() || undefined : undefined,
        corrected_regex: status === 'corrected' ? correctedRegex.trim() || undefined : undefined,
      };
      const result = await api.validateRuleCommand(benchmarkId, ruleId, payload);
      setValidateMsg(result.message);
      setShowCorrection(false);
      onValidated?.();
    } catch (err: unknown) {
      setValidateMsg((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Validation failed');
    } finally {
      setValidating(false);
    }
  };

  if (!hasCommand) {
    return (
      <div className="rounded-lg border border-dark-border bg-dark-overlay p-3 text-xs text-dark-muted italic">
        No audit command — generate one first before testing.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-sky-500/30 bg-sky-500/5 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Terminal className="h-4 w-4 text-sky-400" />
        <h4 className="text-sm font-semibold text-white">Live Test — {sectionNumber}</h4>
      </div>

      {/* Target Selector + Timeout */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs text-dark-secondary mb-1">
            <Server className="inline h-3 w-3 mr-1" />
            Target
          </label>
          <select
            value={selectedTargetId ?? ''}
            onChange={(e) => setSelectedTargetId(Number(e.target.value) || null)}
            className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white focus:border-sky-500/50 focus:outline-none focus:ring-1 focus:ring-sky-500/30"
          >
            <option value="">Select a target{'\u2026'}</option>
            {targets.map((t) => (
              <option key={t.id} value={t.id}>
                {t.hostname || t.ip_address} — {t.target_type} ({t.connection_method || 'no method'})
                {t.connection_status === 'ok' ? ' \u2713' : t.connection_status === 'failed' ? ' \u2717' : ''}
              </option>
            ))}
          </select>
        </div>
        <div className="w-24">
          <label className="block text-xs text-dark-secondary mb-1">
            <Clock className="inline h-3 w-3 mr-1" />
            Timeout (s)
          </label>
          <input
            type="number"
            min={5}
            max={300}
            value={timeout}
            onChange={(e) => setTimeout_(Number(e.target.value))}
            className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white focus:border-sky-500/50 focus:outline-none focus:ring-1 focus:ring-sky-500/30"
          />
        </div>
        <button
          onClick={handleTest}
          disabled={!selectedTargetId || testing}
          className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {testing ? 'Running\u2026' : 'Run Test'}
        </button>
      </div>

      {/* Error */}
      {testError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {testError}
        </div>
      )}

      {/* Test Result */}
      {testResult && (
        <div className="space-y-3 border-t border-sky-500/20 pt-3">
          <div className="flex items-center justify-between">
            <span className="text-xs text-dark-secondary font-medium">Result</span>
            <div className="flex items-center gap-3">
              {matchBadge(testResult.match_result)}
              <span className="text-xs text-dark-muted">
                {testResult.execution_time_ms}ms | exit {testResult.exit_code}
              </span>
            </div>
          </div>

          {testResult.match_details && (
            <p className="text-xs text-dark-secondary italic">{testResult.match_details}</p>
          )}

          {/* stdout */}
          {testResult.stdout && (
            <div>
              <span className="text-xs font-medium text-dark-secondary">stdout:</span>
              <pre className="mt-1 max-h-40 overflow-auto rounded bg-gray-900 p-3 text-xs text-green-400 custom-scrollbar">{testResult.stdout}</pre>
            </div>
          )}

          {/* stderr */}
          {testResult.stderr && (
            <div>
              <span className="text-xs font-medium text-dark-secondary">stderr:</span>
              <pre className="mt-1 max-h-24 overflow-auto rounded bg-gray-900 p-3 text-xs text-red-400 custom-scrollbar">{testResult.stderr}</pre>
            </div>
          )}

          {/* Expected pattern */}
          {testResult.expected_output_regex && (
            <div>
              <span className="text-xs font-medium text-dark-secondary">Expected pattern:</span>
              <code className="ml-2 rounded bg-sky-500/10 border border-sky-500/30 px-2 py-0.5 text-xs text-sky-400">
                {testResult.expected_output_regex}
              </code>
            </div>
          )}

          {/* Validation Actions */}
          <div className="border-t border-sky-500/20 pt-3 space-y-2">
            <span className="text-xs font-medium text-dark-secondary">Validate this command:</span>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => handleValidate('validated')}
                disabled={validating}
                className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                <CheckCircle2 className="h-3 w-3" /> Approve
              </button>
              <button
                onClick={() => setShowCorrection(!showCorrection)}
                className="inline-flex items-center gap-1 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700"
              >
                <AlertTriangle className="h-3 w-3" /> Correct
              </button>
              <button
                onClick={() => handleValidate('flagged')}
                disabled={validating}
                className="inline-flex items-center gap-1 rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                <XCircle className="h-3 w-3" /> Flag
              </button>
            </div>

            {/* Correction Form */}
            {showCorrection && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 space-y-2">
                <div>
                  <label className="block text-xs text-dark-secondary mb-1">Corrected Command (optional)</label>
                  <textarea
                    value={correctedCommand}
                    onChange={(e) => setCorrectedCommand(e.target.value)}
                    placeholder="Paste the corrected audit command here..."
                    rows={3}
                    className="w-full rounded border border-dark-border bg-dark-elevated p-2 text-xs text-white placeholder-dark-muted font-mono focus:border-amber-500/50 focus:outline-none focus:ring-1 focus:ring-amber-500/30"
                  />
                </div>
                <div>
                  <label className="block text-xs text-dark-secondary mb-1">Corrected Regex (optional)</label>
                  <input
                    value={correctedRegex}
                    onChange={(e) => setCorrectedRegex(e.target.value)}
                    placeholder="e.g. ==0 or >=1 or regex pattern"
                    className="w-full rounded border border-dark-border bg-dark-elevated p-2 text-xs text-white placeholder-dark-muted font-mono focus:border-amber-500/50 focus:outline-none focus:ring-1 focus:ring-amber-500/30"
                  />
                </div>
                <button
                  onClick={() => handleValidate('corrected')}
                  disabled={validating}
                  className="inline-flex items-center gap-1 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                >
                  {validating ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
                  Submit Correction
                </button>
              </div>
            )}

            {/* Notes */}
            <div>
              <label className="block text-xs text-dark-secondary mb-1">Notes (optional)</label>
              <input
                value={validationNotes}
                onChange={(e) => setValidationNotes(e.target.value)}
                placeholder="Add notes about this test result..."
                className="w-full rounded border border-dark-border bg-dark-elevated p-2 text-xs text-white placeholder-dark-muted focus:border-sky-500/50 focus:outline-none focus:ring-1 focus:ring-sky-500/30"
              />
            </div>

            {validateMsg && (
              <p className={`text-xs font-medium ${validateMsg.includes('fail') || validateMsg.includes('error') ? 'text-red-400' : 'text-emerald-400'}`}>
                {validateMsg}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
