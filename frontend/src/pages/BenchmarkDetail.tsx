import { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, Pause, Shield, ShieldOff, Search, ChevronDown, ChevronUp, AlertCircle, CheckCircle2, Flag, RefreshCw, Lock, Unlock, History, ShieldCheck, CheckCheck, AlertTriangle, Download, Upload } from 'lucide-react';
import type { Benchmark, Rule, EnrichStatus, VerifyStatus, RuleCommand, CommandHistoryEntry, VerificationReport } from '@/types';
import * as api from '@/services/api';

function severityBadge(severity: string) {
  const styles: Record<string, string> = {
    critical: 'bg-red-100 text-red-800',
    high: 'bg-orange-100 text-orange-800',
    medium: 'bg-yellow-100 text-yellow-800',
    low: 'bg-green-100 text-green-800',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${styles[severity] || 'bg-gray-100 text-gray-600'}`}>
      {severity}
    </span>
  );
}

function statusBadge(status: string) {
  const styles: Record<string, string> = {
    completed: 'bg-green-100 text-green-800',
    processing: 'bg-blue-100 text-blue-800',
    failed: 'bg-red-100 text-red-800',
    paused: 'bg-yellow-100 text-yellow-800',
    pending: 'bg-gray-100 text-gray-600',
    completed_with_issues: 'bg-orange-100 text-orange-800',
    overridden: 'bg-yellow-100 text-yellow-800',
    verified: 'bg-green-100 text-green-800',
    flagged: 'bg-red-100 text-red-800',
    generated: 'bg-blue-100 text-blue-800',
    pending_review: 'bg-yellow-100 text-yellow-800',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status] || styles.pending}`}>
      {status.replace(/_/g, ' ')}
    </span>
  );
}

function verificationResultBadge(result: string) {
  const styles: Record<string, string> = {
    pass: 'bg-green-100 text-green-800',
    fail: 'bg-red-100 text-red-800',
    warn: 'bg-yellow-100 text-yellow-800',
    skip: 'bg-gray-100 text-gray-500',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${styles[result] || 'bg-gray-100 text-gray-600'}`}>
      {result}
    </span>
  );
}

export default function BenchmarkDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const benchmarkId = Number(id);

  const [benchmark, setBenchmark] = useState<Benchmark | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [enrichStatus, setEnrichStatus] = useState<EnrichStatus | null>(null);
  const [verifyStatus, setVerifyStatus] = useState<VerifyStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');
  const [expandedRule, setExpandedRule] = useState<number | null>(null);
  const [ruleCommand, setRuleCommand] = useState<RuleCommand | null>(null);
  const [commandHistory, setCommandHistory] = useState<CommandHistoryEntry[]>([]);
  const [verificationReports, setVerificationReports] = useState<VerificationReport[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [showReports, setShowReports] = useState(false);
  const [flagReason, setFlagReason] = useState('');
  const [showFlagForm, setShowFlagForm] = useState(false);
  const [unlockReason, setUnlockReason] = useState('');
  const [showUnlockForm, setShowUnlockForm] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const rulesImportRef = useRef<HTMLInputElement>(null);
  const commandsImportRef = useRef<HTMLInputElement>(null);

  const fetchData = useCallback(async () => {
    try {
      const [bm, es, vs] = await Promise.all([
        api.getBenchmark(benchmarkId),
        api.getEnrichmentStatus(benchmarkId),
        api.getVerificationStatus(benchmarkId),
      ]);
      setBenchmark(bm);
      setEnrichStatus(es);
      setVerifyStatus(vs);
    } catch {
      setError('Failed to load benchmark');
    } finally {
      setLoading(false);
    }
  }, [benchmarkId]);

  const fetchRules = useCallback(async () => {
    try {
      const params: Record<string, string> = {};
      if (searchTerm) params.search = searchTerm;
      if (severityFilter) params.severity = severityFilter;
      const data = await api.getBenchmarkRules(benchmarkId, params);
      setRules(data);
    } catch {
      // Silently handle - rules may not be ready yet
    }
  }, [benchmarkId, searchTerm, severityFilter]);

  useEffect(() => {
    fetchData();
    fetchRules();
  }, [fetchData, fetchRules]);

  // Poll for updates when processing
  useEffect(() => {
    if (!benchmark) return;
    const isProcessing = ['processing'].includes(benchmark.phase1_status) ||
      ['processing'].includes(benchmark.phase2_status) ||
      ['processing'].includes(benchmark.verification_status);
    if (!isProcessing) return;
    const interval = setInterval(() => { fetchData(); fetchRules(); }, 3000);
    return () => clearInterval(interval);
  }, [benchmark, fetchData, fetchRules]);

  // Auto-dismiss success message
  useEffect(() => {
    if (!successMsg) return;
    const timer = setTimeout(() => setSuccessMsg(''), 5000);
    return () => clearTimeout(timer);
  }, [successMsg]);

  const handleEnrich = async () => {
    try {
      await api.startEnrichment(benchmarkId);
      await fetchData();
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to start enrichment');
    }
  };

  const handlePauseEnrich = async () => {
    try {
      await api.pauseEnrichment(benchmarkId);
      await fetchData();
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to pause enrichment');
    }
  };

  const handleVerify = async () => {
    try {
      await api.startVerification(benchmarkId);
      await fetchData();
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to start verification');
    }
  };

  const handleBulkAccept = async () => {
    try {
      setActionLoading(true);
      await api.bulkAcceptCommands(benchmarkId);
      await fetchData();
      await fetchRules();
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to bulk accept');
    } finally {
      setActionLoading(false);
    }
  };

  const handleBulkRegenerate = async () => {
    try {
      setActionLoading(true);
      await api.bulkRegenerateCommands(benchmarkId);
      await fetchData();
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to start bulk regeneration');
    } finally {
      setActionLoading(false);
    }
  };

  const handleOverride = async () => {
    try {
      setActionLoading(true);
      await api.overrideVerification(benchmarkId);
      await fetchData();
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to override');
    } finally {
      setActionLoading(false);
    }
  };

  // ── Export / Import handlers ──

  const downloadBlob = (blob: Blob, filename: string) => {
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  };

  const handleExportRules = async () => {
    try {
      const blob = await api.exportRules(benchmarkId);
      const name = benchmark?.name?.replace(/ /g, '_') || 'benchmark';
      downloadBlob(blob, `${name}_phase1_rules.json`);
    } catch {
      setError('Failed to export rules');
    }
  };

  const handleImportRules = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setActionLoading(true);
      const result = await api.importRules(benchmarkId, file);
      setError('');
      setSuccessMsg(result.message);
      await fetchData();
      await fetchRules();
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to import rules');
    } finally {
      setActionLoading(false);
      if (rulesImportRef.current) rulesImportRef.current.value = '';
    }
  };

  const handleExportCommands = async () => {
    try {
      const blob = await api.exportCommands(benchmarkId);
      const name = benchmark?.name?.replace(/ /g, '_') || 'benchmark';
      downloadBlob(blob, `${name}_phase2_commands.json`);
    } catch {
      setError('Failed to export commands');
    }
  };

  const handleImportCommands = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setActionLoading(true);
      const result = await api.importCommands(benchmarkId, file);
      setError('');
      setSuccessMsg(result.message);
      await fetchData();
      await fetchRules();
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to import commands');
    } finally {
      setActionLoading(false);
      if (commandsImportRef.current) commandsImportRef.current.value = '';
    }
  };

  const handleExpandRule = async (ruleId: number) => {
    if (expandedRule === ruleId) {
      setExpandedRule(null);
      setRuleCommand(null);
      setCommandHistory([]);
      setVerificationReports([]);
      setShowHistory(false);
      setShowReports(false);
      setShowFlagForm(false);
      setShowUnlockForm(false);
      return;
    }
    setExpandedRule(ruleId);
    setShowHistory(false);
    setShowReports(false);
    setShowFlagForm(false);
    setShowUnlockForm(false);
    try {
      const cmd = await api.getRuleCommand(ruleId);
      setRuleCommand(cmd);
    } catch {
      setRuleCommand(null);
    }
  };

  const handleFlagCommand = async (ruleId: number) => {
    if (!flagReason.trim()) return;
    try {
      setActionLoading(true);
      const cmd = await api.flagCommand(ruleId, flagReason);
      setRuleCommand(cmd);
      setShowFlagForm(false);
      setFlagReason('');
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to flag command');
    } finally {
      setActionLoading(false);
    }
  };

  const handleRegenerateCommand = async (ruleId: number) => {
    try {
      setActionLoading(true);
      const cmd = await api.regenerateCommand(ruleId);
      setRuleCommand(cmd);
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to regenerate command');
    } finally {
      setActionLoading(false);
    }
  };

  const handleProtectCommand = async (ruleId: number) => {
    try {
      setActionLoading(true);
      const cmd = await api.protectCommand(ruleId);
      setRuleCommand(cmd);
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to protect command');
    } finally {
      setActionLoading(false);
    }
  };

  const handleUnlockCommand = async (ruleId: number) => {
    if (!unlockReason.trim()) return;
    try {
      setActionLoading(true);
      const cmd = await api.unlockCommand(ruleId, unlockReason);
      setRuleCommand(cmd);
      setShowUnlockForm(false);
      setUnlockReason('');
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to unlock command');
    } finally {
      setActionLoading(false);
    }
  };

  const handleVerifySingle = async (ruleId: number) => {
    try {
      setActionLoading(true);
      const cmd = await api.verifySingleCommand(ruleId);
      setRuleCommand(cmd);
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to verify command');
    } finally {
      setActionLoading(false);
    }
  };

  const handleShowHistory = async (ruleId: number) => {
    if (showHistory) {
      setShowHistory(false);
      return;
    }
    try {
      const history = await api.getCommandHistory(ruleId);
      setCommandHistory(history);
      setShowHistory(true);
    } catch {
      setCommandHistory([]);
    }
  };

  const handleShowReports = async (ruleId: number) => {
    if (showReports) {
      setShowReports(false);
      return;
    }
    try {
      const reports = await api.getCommandVerificationReports(ruleId);
      setVerificationReports(reports);
      setShowReports(true);
    } catch {
      setVerificationReports([]);
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-12 text-gray-500">Loading…</div>;
  }

  if (!benchmark) {
    return <div className="text-center py-12 text-red-500">Benchmark not found</div>;
  }

  const enrichPercent = enrichStatus && enrichStatus.total > 0
    ? Math.round((enrichStatus.processed / enrichStatus.total) * 100)
    : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button onClick={() => navigate('/benchmarks')} className="rounded-lg p-2 hover:bg-gray-100">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div>
          <h2 className="text-xl font-semibold text-gray-900">{benchmark.name}</h2>
          <p className="text-sm text-gray-500">
            {benchmark.platform} · {benchmark.platform_family} · v{benchmark.version} · {benchmark.total_rules} rules
          </p>
        </div>
        {benchmark.is_ready && (
          <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-green-100 px-3 py-1 text-sm font-medium text-green-800">
            <CheckCircle2 className="h-4 w-4" /> Ready
          </span>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <button onClick={() => setError('')} className="float-right text-red-400 hover:text-red-600">×</button>
          {error}
        </div>
      )}

      {successMsg && (
        <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">
          <button onClick={() => setSuccessMsg('')} className="float-right text-green-400 hover:text-green-600">×</button>
          <CheckCircle2 className="mr-2 inline h-4 w-4" />
          {successMsg}
        </div>
      )}

      {benchmark.notes && benchmark.phase1_status === 'failed' && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <AlertCircle className="mr-2 inline h-4 w-4" />
          Phase 1 Error: {benchmark.notes}
        </div>
      )}

      {/* Phase Status Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {/* Phase 1 */}
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-700">Phase 1: Parse</h3>
            {statusBadge(benchmark.phase1_status)}
          </div>
          <p className="mt-2 text-2xl font-bold text-gray-900">{benchmark.total_rules} <span className="text-sm font-normal text-gray-500">rules extracted</span></p>
          <div className="mt-3 flex flex-wrap gap-2">
            {benchmark.phase1_status === 'completed' && benchmark.total_rules > 0 && (
              <button onClick={handleExportRules} className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">
                <Download className="h-3 w-3" /> Export Rules
              </button>
            )}
            <label className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">
              <Upload className="h-3 w-3" /> Import Rules
              <input ref={rulesImportRef} type="file" accept=".json" className="hidden" onChange={handleImportRules} disabled={actionLoading} />
            </label>
          </div>
        </div>

        {/* Phase 2 */}
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-700">Phase 2: Enrich</h3>
            {statusBadge(enrichStatus?.status || benchmark.phase2_status)}
          </div>
          {enrichStatus && enrichStatus.total > 0 && (
            <>
              <p className="mt-2 text-2xl font-bold text-gray-900">
                {enrichStatus.processed}/{enrichStatus.total}
                <span className="text-sm font-normal text-gray-500"> commands</span>
              </p>
              <div className="mt-2 h-2 w-full rounded-full bg-gray-200">
                <div className="h-2 rounded-full bg-blue-600 transition-all" style={{ width: `${enrichPercent}%` }} />
              </div>
            </>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {benchmark.phase1_status === 'completed' && !['processing'].includes(benchmark.phase2_status) && benchmark.phase2_status !== 'completed' && (
              <button onClick={handleEnrich} className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700">
                <Play className="h-3 w-3" /> {benchmark.phase2_status === 'paused' ? 'Resume' : 'Start'} Enrichment
              </button>
            )}
            {benchmark.phase2_status === 'processing' && (
              <button onClick={handlePauseEnrich} className="inline-flex items-center gap-1 rounded-md bg-yellow-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-yellow-700">
                <Pause className="h-3 w-3" /> Pause
              </button>
            )}
            {benchmark.phase1_status === 'completed' && benchmark.phase2_status === 'completed' && (
              <button onClick={handleExportCommands} className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">
                <Download className="h-3 w-3" /> Export Commands
              </button>
            )}
            {benchmark.phase1_status === 'completed' && !['processing'].includes(benchmark.phase2_status) && (
              <label className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">
                <Upload className="h-3 w-3" /> Import Commands
                <input ref={commandsImportRef} type="file" accept=".json" className="hidden" onChange={handleImportCommands} disabled={actionLoading} />
              </label>
            )}
          </div>
        </div>

        {/* Verification */}
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-700">Verification</h3>
            {statusBadge(verifyStatus?.status || benchmark.verification_status)}
          </div>
          {verifyStatus && verifyStatus.total > 0 && (
            <div className="mt-2 flex gap-4">
              <div>
                <span className="text-2xl font-bold text-green-600">{verifyStatus.passed}</span>
                <span className="text-sm text-gray-500"> passed</span>
              </div>
              <div>
                <span className="text-2xl font-bold text-red-600">{verifyStatus.failed}</span>
                <span className="text-sm text-gray-500"> failed</span>
              </div>
            </div>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {benchmark.phase2_status === 'completed' && !['processing'].includes(benchmark.verification_status) && (
              <button onClick={handleVerify} className="inline-flex items-center gap-1 rounded-md bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-700">
                <Shield className="h-3 w-3" /> {['completed', 'completed_with_issues', 'overridden'].includes(benchmark.verification_status) ? 'Re-run' : 'Run'} Verification
              </button>
            )}
            {verifyStatus && verifyStatus.failed > 0 && (
              <button onClick={handleBulkRegenerate} disabled={actionLoading} className="inline-flex items-center gap-1 rounded-md bg-orange-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-orange-700 disabled:opacity-50">
                <RefreshCw className="h-3 w-3" /> Regenerate Flagged
              </button>
            )}
            {['completed', 'completed_with_issues'].includes(benchmark.verification_status) && (
              <button onClick={handleBulkAccept} disabled={actionLoading} className="inline-flex items-center gap-1 rounded-md bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50">
                <CheckCheck className="h-3 w-3" /> Accept All
              </button>
            )}
            {benchmark.verification_status === 'completed_with_issues' && !benchmark.is_ready && (
              <button onClick={handleOverride} disabled={actionLoading} className="inline-flex items-center gap-1 rounded-md bg-yellow-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-yellow-700 disabled:opacity-50">
                <AlertTriangle className="h-3 w-3" /> Override
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Rules Section */}
      {benchmark.phase1_status === 'completed' && (
        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="border-b border-gray-200 p-4">
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="text-lg font-medium text-gray-900">Rules</h3>
              <div className="ml-auto flex items-center gap-2">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                  <input
                    type="text"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder="Search rules…"
                    className="rounded-lg border border-gray-300 py-1.5 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
                <select
                  value={severityFilter}
                  onChange={(e) => setSeverityFilter(e.target.value)}
                  className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="">All severities</option>
                  <option value="critical">Critical</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </div>
            </div>
          </div>

          <div className="divide-y divide-gray-100">
            {rules.length === 0 ? (
              <div className="p-8 text-center text-gray-500">
                No rules found matching your criteria.
              </div>
            ) : (
              rules.map((rule) => (
                <div key={rule.id}>
                  <button
                    onClick={() => handleExpandRule(rule.id)}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-gray-50"
                  >
                    <span className="min-w-[60px] text-sm font-mono text-gray-500">{rule.section_number}</span>
                    <span className="flex-1 text-sm font-medium text-gray-900">{rule.title}</span>
                    {severityBadge(rule.severity)}
                    {rule.assessment_type && (
                      <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-500">{rule.assessment_type}</span>
                    )}
                    {rule.tags.map((t) => (
                      <span key={t.id} className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700">{t.tag_id}</span>
                    ))}
                    {expandedRule === rule.id ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
                  </button>
                  {expandedRule === rule.id && (
                    <div className="border-t border-gray-100 bg-gray-50 px-4 py-3 space-y-3">
                      {rule.description && (
                        <div>
                          <span className="text-xs font-medium text-gray-500">Description:</span>
                          <p className="mt-1 text-sm text-gray-700">{rule.description}</p>
                        </div>
                      )}
                      {ruleCommand && (
                        <div className="space-y-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-medium text-gray-500">Command Status:</span>
                            {statusBadge(ruleCommand.status)}
                            {ruleCommand.is_protected && <span className="rounded bg-purple-100 px-2 py-0.5 text-xs text-purple-700">Protected</span>}
                            {ruleCommand.source && (
                              <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-500">{ruleCommand.source}</span>
                            )}
                            {ruleCommand.regeneration_count > 0 && (
                              <span className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
                                Regen #{ruleCommand.regeneration_count}
                              </span>
                            )}
                          </div>
                          {ruleCommand.audit_command && (
                            <div>
                              <span className="text-xs font-medium text-gray-500">Audit Command:</span>
                              <pre className="mt-1 rounded bg-gray-900 p-3 text-xs text-green-400 overflow-x-auto">{ruleCommand.audit_command}</pre>
                            </div>
                          )}
                          {ruleCommand.expected_output_description && (
                            <div>
                              <span className="text-xs font-medium text-gray-500">Expected Output:</span>
                              <p className="mt-1 text-sm text-gray-700">{ruleCommand.expected_output_description}</p>
                            </div>
                          )}
                          {ruleCommand.expected_output_regex && (
                            <div>
                              <span className="text-xs font-medium text-gray-500">Expected Regex:</span>
                              <code className="mt-1 block rounded bg-gray-100 p-2 text-xs text-gray-800">{ruleCommand.expected_output_regex}</code>
                            </div>
                          )}
                          {ruleCommand.flag_reason && (
                            <div className="rounded bg-red-50 p-2">
                              <span className="text-xs font-medium text-red-700">Flag Reason:</span>
                              <p className="mt-1 text-sm text-red-600">{ruleCommand.flag_reason}</p>
                            </div>
                          )}

                          {/* Command Action Buttons */}
                          <div className="flex flex-wrap gap-2 pt-2 border-t border-gray-200">
                            {!ruleCommand.is_protected && ruleCommand.status !== 'flagged' && (
                              <button
                                onClick={() => setShowFlagForm(!showFlagForm)}
                                className="inline-flex items-center gap-1 rounded-md bg-red-50 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100"
                              >
                                <Flag className="h-3 w-3" /> Flag
                              </button>
                            )}
                            {ruleCommand.status === 'flagged' && !ruleCommand.is_protected && (
                              <button
                                onClick={() => handleRegenerateCommand(rule.id)}
                                disabled={actionLoading}
                                className="inline-flex items-center gap-1 rounded-md bg-orange-50 px-3 py-1.5 text-xs font-medium text-orange-700 hover:bg-orange-100 disabled:opacity-50"
                              >
                                <RefreshCw className="h-3 w-3" /> Regenerate
                              </button>
                            )}
                            {!ruleCommand.is_protected && (
                              <button
                                onClick={() => handleVerifySingle(rule.id)}
                                disabled={actionLoading}
                                className="inline-flex items-center gap-1 rounded-md bg-purple-50 px-3 py-1.5 text-xs font-medium text-purple-700 hover:bg-purple-100 disabled:opacity-50"
                              >
                                <ShieldCheck className="h-3 w-3" /> Verify
                              </button>
                            )}
                            {!ruleCommand.is_protected && ['verified', 'generated'].includes(ruleCommand.status) && (
                              <button
                                onClick={() => handleProtectCommand(rule.id)}
                                disabled={actionLoading}
                                className="inline-flex items-center gap-1 rounded-md bg-green-50 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-100 disabled:opacity-50"
                              >
                                <Lock className="h-3 w-3" /> Protect
                              </button>
                            )}
                            {ruleCommand.is_protected && (
                              <button
                                onClick={() => setShowUnlockForm(!showUnlockForm)}
                                className="inline-flex items-center gap-1 rounded-md bg-yellow-50 px-3 py-1.5 text-xs font-medium text-yellow-700 hover:bg-yellow-100"
                              >
                                <Unlock className="h-3 w-3" /> Unlock
                              </button>
                            )}
                            <button
                              onClick={() => handleShowHistory(rule.id)}
                              className="inline-flex items-center gap-1 rounded-md bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100"
                            >
                              <History className="h-3 w-3" /> {showHistory ? 'Hide' : 'Show'} History
                            </button>
                            <button
                              onClick={() => handleShowReports(rule.id)}
                              className="inline-flex items-center gap-1 rounded-md bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-100"
                            >
                              <ShieldOff className="h-3 w-3" /> {showReports ? 'Hide' : 'Show'} Reports
                            </button>
                          </div>

                          {/* Flag Form */}
                          {showFlagForm && (
                            <div className="rounded-lg border border-red-200 bg-red-50 p-3 space-y-2">
                              <label className="block text-xs font-medium text-red-700">Flag Reason:</label>
                              <textarea
                                value={flagReason}
                                onChange={(e) => setFlagReason(e.target.value)}
                                placeholder="Describe why this command is broken…"
                                className="w-full rounded border border-red-300 p-2 text-sm focus:border-red-500 focus:outline-none"
                                rows={2}
                              />
                              <div className="flex gap-2">
                                <button
                                  onClick={() => handleFlagCommand(rule.id)}
                                  disabled={actionLoading || !flagReason.trim()}
                                  className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                                >
                                  Submit Flag
                                </button>
                                <button
                                  onClick={() => { setShowFlagForm(false); setFlagReason(''); }}
                                  className="rounded-md bg-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-300"
                                >
                                  Cancel
                                </button>
                              </div>
                            </div>
                          )}

                          {/* Unlock Form */}
                          {showUnlockForm && (
                            <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 space-y-2">
                              <label className="block text-xs font-medium text-yellow-700">Unlock Reason:</label>
                              <textarea
                                value={unlockReason}
                                onChange={(e) => setUnlockReason(e.target.value)}
                                placeholder="Explain why you are unlocking this protected command…"
                                className="w-full rounded border border-yellow-300 p-2 text-sm focus:border-yellow-500 focus:outline-none"
                                rows={2}
                              />
                              <div className="flex gap-2">
                                <button
                                  onClick={() => handleUnlockCommand(rule.id)}
                                  disabled={actionLoading || !unlockReason.trim()}
                                  className="rounded-md bg-yellow-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-yellow-700 disabled:opacity-50"
                                >
                                  Confirm Unlock
                                </button>
                                <button
                                  onClick={() => { setShowUnlockForm(false); setUnlockReason(''); }}
                                  className="rounded-md bg-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-300"
                                >
                                  Cancel
                                </button>
                              </div>
                            </div>
                          )}

                          {/* Command History */}
                          {showHistory && (
                            <div className="rounded-lg border border-gray-200 bg-white p-3 space-y-2">
                              <h4 className="text-xs font-medium text-gray-700">Command History ({commandHistory.length} entries)</h4>
                              {commandHistory.length === 0 ? (
                                <p className="text-xs text-gray-400">No previous command versions.</p>
                              ) : (
                                commandHistory.map((entry, idx) => (
                                  <div key={idx} className="rounded border border-gray-100 bg-gray-50 p-2 space-y-1">
                                    <div className="flex items-center gap-2 text-xs text-gray-500">
                                      <span>Attempt #{idx + 1}</span>
                                      {entry.source && <span className="rounded bg-gray-100 px-1.5 py-0.5">{entry.source}</span>}
                                      {entry.timestamp && <span>{new Date(entry.timestamp).toLocaleString()}</span>}
                                    </div>
                                    {entry.audit_command && (
                                      <pre className="rounded bg-gray-900 p-2 text-xs text-green-400 overflow-x-auto">{entry.audit_command}</pre>
                                    )}
                                    {entry.flag_reason && (
                                      <p className="text-xs text-red-600">Flag: {entry.flag_reason}</p>
                                    )}
                                  </div>
                                ))
                              )}
                            </div>
                          )}

                          {/* Verification Reports */}
                          {showReports && (
                            <div className="rounded-lg border border-gray-200 bg-white p-3 space-y-2">
                              <h4 className="text-xs font-medium text-gray-700">Verification Reports ({verificationReports.length})</h4>
                              {verificationReports.length === 0 ? (
                                <p className="text-xs text-gray-400">No verification reports yet. Run verification first.</p>
                              ) : (
                                verificationReports.map((report) => (
                                  <div key={report.id} className="flex items-center gap-2 rounded border border-gray-100 bg-gray-50 p-2">
                                    <span className="min-w-[90px] text-xs font-mono text-gray-500">{report.level}</span>
                                    {verificationResultBadge(report.result)}
                                    <span className="flex-1 text-xs text-gray-700">{report.message}</span>
                                    {report.auto_fixable && (
                                      <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-700">auto-fixable</span>
                                    )}
                                  </div>
                                ))
                              )}
                            </div>
                          )}
                        </div>
                      )}
                      {!ruleCommand && benchmark.phase2_status !== 'completed' && (
                        <p className="text-sm text-gray-400 italic">No audit command generated yet. Run Phase 2 enrichment to generate commands.</p>
                      )}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
