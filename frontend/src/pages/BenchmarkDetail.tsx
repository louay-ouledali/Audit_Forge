import { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Play, Pause, Shield, Search, ChevronDown, ChevronUp, AlertCircle, CheckCircle2 } from 'lucide-react';
import type { Benchmark, Rule, EnrichStatus, VerifyStatus, RuleCommand } from '@/types';
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
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status] || styles.pending}`}>
      {status.replace(/_/g, ' ')}
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
  const [searchTerm, setSearchTerm] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');
  const [expandedRule, setExpandedRule] = useState<number | null>(null);
  const [ruleCommand, setRuleCommand] = useState<RuleCommand | null>(null);

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

  const handleExpandRule = async (ruleId: number) => {
    if (expandedRule === ruleId) {
      setExpandedRule(null);
      setRuleCommand(null);
      return;
    }
    setExpandedRule(ruleId);
    try {
      const cmd = await api.getRuleCommand(ruleId);
      setRuleCommand(cmd);
    } catch {
      setRuleCommand(null);
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
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
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
          <div className="mt-3 flex gap-2">
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
          <div className="mt-3">
            {benchmark.phase2_status === 'completed' && !['processing', 'completed', 'completed_with_issues'].includes(benchmark.verification_status) && (
              <button onClick={handleVerify} className="inline-flex items-center gap-1 rounded-md bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-700">
                <Shield className="h-3 w-3" /> Run Verification
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
                          {ruleCommand.flag_reason && (
                            <div className="rounded bg-red-50 p-2">
                              <span className="text-xs font-medium text-red-700">Flag Reason:</span>
                              <p className="mt-1 text-sm text-red-600">{ruleCommand.flag_reason}</p>
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
