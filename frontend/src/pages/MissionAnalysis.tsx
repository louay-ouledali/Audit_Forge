import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Bot, Trash2, RefreshCw, AlertTriangle, ChevronDown, ChevronUp, Shield, Target, BarChart3 } from 'lucide-react';
import type { Mission, MissionAnalysisResult, ComparableMission } from '@/types';
import * as api from '@/services/api';

type AnalysisTab = 'cross_target' | 'category_analysis' | 'cross_mission';

export default function MissionAnalysis() {
  const { missionId } = useParams<{ missionId: string }>();
  const navigate = useNavigate();
  const id = Number(missionId);

  const [mission, setMission] = useState<Mission | null>(null);
  const [analyses, setAnalyses] = useState<MissionAnalysisResult[]>([]);
  const [comparableMissions, setComparableMissions] = useState<ComparableMission[]>([]);
  const [selectedCompareId, setSelectedCompareId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<AnalysisTab>('cross_target');
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const fetchData = async () => {
    try {
      const [missionData, analysesData] = await Promise.all([
        api.getClient(0).catch(() => null), // will fetch mission below
        api.getMissionAnalyses(id),
      ]);
      void missionData;
      setAnalyses(analysesData.data);
    } catch {
      setError('Failed to load analyses');
    } finally {
      setLoading(false);
    }
  };

  const fetchMission = async () => {
    try {
      const resp = await fetch(`/api/missions/${id}`);
      const json = await resp.json();
      if (json.data) {
        setMission(json.data);
        // Load comparable missions for the same client
        if (json.data.client_id) {
          const comparable = await api.getComparableMissions(json.data.client_id);
          setComparableMissions(comparable.filter((m: ComparableMission) => m.id !== id));
        }
      }
    } catch {
      // Mission data is optional for display
    }
  };

  useEffect(() => {
    fetchMission();
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const handleRunAnalysis = async () => {
    setError('');
    setAnalyzing(true);
    try {
      const payload: { analysis_type: AnalysisTab; compare_mission_id?: number | null } = {
        analysis_type: activeTab,
      };
      if (activeTab === 'cross_mission') {
        if (!selectedCompareId) {
          setError('Please select a previous mission to compare with');
          setAnalyzing(false);
          return;
        }
        payload.compare_mission_id = selectedCompareId;
      }
      await api.runMissionAnalysis(id, payload);
      await fetchData();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Analysis failed';
      setError(message);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleDelete = async (analysisId: number) => {
    if (!window.confirm('Delete this analysis?')) return;
    try {
      await api.deleteMissionAnalysis(id, analysisId);
      await fetchData();
    } catch {
      setError('Failed to delete analysis');
    }
  };

  const filteredAnalyses = analyses.filter((a) => a.analysis_type === activeTab);

  const tabs: { key: AnalysisTab; label: string; icon: React.ReactNode }[] = [
    { key: 'cross_target', label: 'Cross-Target Analysis', icon: <Target className="h-4 w-4" /> },
    { key: 'category_analysis', label: 'Category Analysis', icon: <BarChart3 className="h-4 w-4" /> },
    { key: 'cross_mission', label: 'Compare with Previous Mission', icon: <Shield className="h-4 w-4" /> },
  ];

  if (loading) {
    return <div className="flex items-center justify-center py-12 text-gray-500">Loading…</div>;
  }

  return (
    <div className="space-y-6">
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
      >
        <ArrowLeft className="h-4 w-4" />
        Back
      </button>

      <div className="flex items-center gap-3">
        <Bot className="h-6 w-6 text-purple-600" />
        <div>
          <h2 className="text-xl font-semibold text-gray-900">🤖 AI Analysis</h2>
          {mission && (
            <p className="text-sm text-gray-500">Mission: {mission.name}</p>
          )}
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Tab Bar */}
      <div className="flex gap-1 rounded-lg border border-gray-200 bg-gray-50 p-1">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.key
                ? 'bg-white text-purple-700 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Cross-mission comparison selector */}
      {activeTab === 'cross_mission' && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Select a previous mission to compare with:
          </label>
          {comparableMissions.length === 0 ? (
            <p className="text-sm text-gray-500">No comparable missions found for this client.</p>
          ) : (
            <select
              value={selectedCompareId ?? ''}
              onChange={(e) => setSelectedCompareId(e.target.value ? Number(e.target.value) : null)}
              className="block w-full max-w-md rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:ring-1 focus:ring-purple-500 focus:outline-none"
            >
              <option value="">— Select mission —</option>
              {comparableMissions.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} {m.compliance != null ? `(${m.compliance}% compliance)` : ''} {m.start_date ? `— ${m.start_date}` : ''}
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      {/* Run Analysis Button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleRunAnalysis}
          disabled={analyzing}
          className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {analyzing ? (
            <>
              <RefreshCw className="h-4 w-4 animate-spin" />
              Analyzing…
            </>
          ) : (
            <>
              <Bot className="h-4 w-4" />
              Run {tabs.find((t) => t.key === activeTab)?.label}
            </>
          )}
        </button>
        {analyzing && (
          <span className="text-sm text-gray-500">This may take a few minutes…</span>
        )}
      </div>

      {/* Results */}
      {filteredAnalyses.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-12 text-center text-gray-500">
          No {tabs.find((t) => t.key === activeTab)?.label.toLowerCase()} results yet. Click the button above to run an analysis.
        </div>
      ) : (
        <div className="space-y-4">
          {filteredAnalyses.map((analysis) => (
            <AnalysisCard
              key={analysis.id}
              analysis={analysis}
              expanded={expandedId === analysis.id}
              onToggle={() => setExpandedId(expandedId === analysis.id ? null : analysis.id)}
              onDelete={() => handleDelete(analysis.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function AnalysisCard({
  analysis,
  expanded,
  onToggle,
  onDelete,
}: {
  analysis: MissionAnalysisResult;
  expanded: boolean;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const result = analysis.result as Record<string, unknown>;

  return (
    <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 cursor-pointer hover:bg-gray-50" onClick={onToggle}>
        <div className="flex items-center gap-3">
          <Bot className="h-5 w-5 text-purple-500" />
          <div>
            <span className="text-sm font-medium text-gray-900">
              {analysis.analysis_type === 'cross_target' && 'Cross-Target Pattern Detection'}
              {analysis.analysis_type === 'category_analysis' && 'Category-Level Analysis'}
              {analysis.analysis_type === 'cross_mission' && 'Cross-Mission Comparison'}
            </span>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              {analysis.generated_at && (
                <span>{new Date(analysis.generated_at).toLocaleString()}</span>
              )}
              {analysis.llm_model_used && (
                <span className="rounded bg-gray-100 px-1.5 py-0.5">{analysis.llm_model_used}</span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="rounded-md p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600"
            title="Delete"
          >
            <Trash2 className="h-4 w-4" />
          </button>
          {expanded ? <ChevronUp className="h-4 w-4 text-gray-400" /> : <ChevronDown className="h-4 w-4 text-gray-400" />}
        </div>
      </div>

      {expanded && (
        <div className="border-t border-gray-200 px-6 py-4 space-y-6">
          {analysis.analysis_type === 'cross_target' && <CrossTargetResult result={result} />}
          {analysis.analysis_type === 'category_analysis' && <CategoryResult result={result} />}
          {analysis.analysis_type === 'cross_mission' && <CrossMissionResult result={result} />}
        </div>
      )}
    </div>
  );
}

/* ── Cross-Target Result Display ── */

function CrossTargetResult({ result }: { result: Record<string, unknown> }) {
  const systemic = (result.systemic_issues as Array<Record<string, unknown>>) || [];
  const outliers = (result.outliers as Array<Record<string, unknown>>) || [];
  const riskChains = (result.risk_chains as Array<Record<string, unknown>>) || [];
  const plan = (result.remediation_plan as Array<Record<string, unknown>>) || [];

  return (
    <>
      {systemic.length > 0 && (
        <Section title="🔴 Systemic Issues">
          {systemic.map((issue, i) => (
            <div key={i} className="rounded-lg border border-red-100 bg-red-50 p-4 space-y-1">
              <div className="flex items-center gap-2">
                <SeverityBadge severity={String(issue.severity || 'medium')} />
                <span className="font-medium text-gray-900">{String(issue.title || '')}</span>
              </div>
              {!!issue.likely_cause && <p className="text-sm text-gray-700">Root cause: {String(issue.likely_cause)}</p>}
              {!!issue.affected_targets && (
                <p className="text-xs text-gray-500">Targets: {(issue.affected_targets as string[]).join(', ')}</p>
              )}
              {!!issue.recommendation && <p className="text-sm text-blue-700 mt-1">💡 {String(issue.recommendation)}</p>}
            </div>
          ))}
        </Section>
      )}

      {outliers.length > 0 && (
        <Section title="⚠️ Outliers">
          {outliers.map((o, i) => (
            <div key={i} className="rounded-lg border border-yellow-100 bg-yellow-50 p-4 space-y-1">
              <span className="font-medium text-gray-900">{String(o.target || '')}</span>
              <p className="text-sm text-gray-700">
                Compliance: {String(o.compliance ?? '')}% (avg: {String(o.average_compliance ?? '')}%)
              </p>
              {!!o.recommendation && <p className="text-sm text-blue-700">💡 {String(o.recommendation)}</p>}
            </div>
          ))}
        </Section>
      )}

      {riskChains.length > 0 && (
        <Section title="🔗 Critical Risk Chains">
          {riskChains.map((rc, i) => (
            <div key={i} className="rounded-lg border border-orange-100 bg-orange-50 p-4 space-y-1">
              <div className="flex items-center gap-2">
                <SeverityBadge severity={String(rc.combined_risk || 'high')} />
                <span className="font-medium text-gray-900">{String(rc.title || '')}</span>
              </div>
              <p className="text-sm text-gray-700">{String(rc.description || '')}</p>
              {!!rc.recommendation && <p className="text-sm text-blue-700">💡 {String(rc.recommendation)}</p>}
            </div>
          ))}
        </Section>
      )}

      {plan.length > 0 && (
        <Section title="📋 Prioritized Remediation Plan">
          <ol className="space-y-2">
            {plan.map((item, i) => (
              <li key={i} className="flex gap-3 rounded-lg border border-gray-100 bg-gray-50 p-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-purple-600 text-xs font-bold text-white">
                  {String(item.priority ?? i + 1)}
                </span>
                <div className="space-y-1">
                  <p className="text-sm font-medium text-gray-900">{String(item.action || '')}</p>
                  <div className="flex gap-3 text-xs text-gray-500">
                    <span>Effort: <EffortBadge effort={String(item.effort || 'medium')} /></span>
                    <span>Impact: <ImpactBadge impact={String(item.impact || 'medium')} /></span>
                  </div>
                  {!!item.rationale && <p className="text-xs text-gray-500">{String(item.rationale)}</p>}
                </div>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {systemic.length === 0 && outliers.length === 0 && riskChains.length === 0 && plan.length === 0 && (
        <p className="text-sm text-gray-500">No significant findings in this analysis.</p>
      )}
    </>
  );
}

/* ── Category Result Display ── */

function CategoryResult({ result }: { result: Record<string, unknown> }) {
  const strengths = (result.strengths as Array<Record<string, unknown>>) || [];
  const weaknesses = (result.weaknesses as Array<Record<string, unknown>>) || [];
  const quickWins = (result.quick_wins as Array<Record<string, unknown>>) || [];
  const recommendations = (result.strategic_recommendations as Array<Record<string, unknown>>) || [];

  return (
    <>
      {strengths.length > 0 && (
        <Section title="💪 Strengths">
          {strengths.map((s, i) => (
            <div key={i} className="rounded-lg border border-green-100 bg-green-50 p-3">
              <span className="font-medium text-green-800">{String(s.category || '')}</span>
              {s.compliance != null && <span className="ml-2 text-sm text-green-600">{String(s.compliance)}%</span>}
              <p className="text-sm text-gray-700 mt-1">{String(s.description || '')}</p>
            </div>
          ))}
        </Section>
      )}

      {weaknesses.length > 0 && (
        <Section title="⚠️ Weaknesses">
          {weaknesses.map((w, i) => (
            <div key={i} className="rounded-lg border border-red-100 bg-red-50 p-3">
              <span className="font-medium text-red-800">{String(w.category || '')}</span>
              {w.compliance != null && <span className="ml-2 text-sm text-red-600">{String(w.compliance)}%</span>}
              <p className="text-sm text-gray-700 mt-1">{String(w.description || '')}</p>
            </div>
          ))}
        </Section>
      )}

      {quickWins.length > 0 && (
        <Section title="🎯 Quick Wins">
          {quickWins.map((q, i) => (
            <div key={i} className="rounded-lg border border-blue-100 bg-blue-50 p-3">
              <span className="font-medium text-blue-800">{String(q.category || '')}</span>
              <p className="text-sm text-gray-700 mt-1">{String(q.description || '')}</p>
              {q.fix_count != null && (
                <p className="text-xs text-blue-600 mt-1">
                  {String(q.fix_count)} fixes needed ({String(q.current_compliance ?? '')}% → {String(q.potential_compliance ?? '')}%)
                </p>
              )}
            </div>
          ))}
        </Section>
      )}

      {recommendations.length > 0 && (
        <Section title="🧭 Strategic Recommendations">
          <ol className="space-y-2">
            {recommendations.map((r, i) => (
              <li key={i} className="flex gap-3 rounded-lg border border-gray-100 bg-gray-50 p-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-purple-600 text-xs font-bold text-white">
                  {String(r.priority ?? i + 1)}
                </span>
                <div>
                  <p className="text-sm font-medium text-gray-900">{String(r.recommendation || '')}</p>
                  {!!r.rationale && <p className="text-xs text-gray-500 mt-1">{String(r.rationale)}</p>}
                </div>
              </li>
            ))}
          </ol>
        </Section>
      )}
    </>
  );
}

/* ── Cross-Mission Result Display ── */

function CrossMissionResult({ result }: { result: Record<string, unknown> }) {
  const improvement = result.improvement_summary as Record<string, unknown> | undefined;
  const regressions = (result.regression_alerts as Array<Record<string, unknown>>) || [];
  const persistent = (result.persistent_issues as Array<Record<string, unknown>>) || [];
  const newRisks = (result.new_risks as Array<Record<string, unknown>>) || [];
  const trend = result.trend_assessment as Record<string, unknown> | undefined;
  const recommendations = (result.recommendations as Array<Record<string, unknown>>) || [];

  return (
    <>
      {trend && (
        <div className={`rounded-lg p-4 ${
          trend.direction === 'improving' ? 'border border-green-200 bg-green-50' :
          trend.direction === 'declining' ? 'border border-red-200 bg-red-50' :
          'border border-yellow-200 bg-yellow-50'
        }`}>
          <span className="text-sm font-medium">
            Trend: {trend.direction === 'improving' ? '📈 Improving' :
                    trend.direction === 'declining' ? '📉 Declining' : '➡️ Stable'}
          </span>
          {!!trend.summary && <p className="text-sm text-gray-700 mt-1">{String(trend.summary)}</p>}
        </div>
      )}

      {improvement && (
        <Section title="✅ Improvement Summary">
          <p className="text-sm text-gray-700">{String(improvement.description || '')}</p>
          {improvement.improved_count != null && (
            <p className="text-sm text-green-600 mt-1">{String(improvement.improved_count)} rules improved</p>
          )}
        </Section>
      )}

      {regressions.length > 0 && (
        <Section title="🔴 Regression Alerts">
          {regressions.map((r, i) => (
            <div key={i} className="rounded-lg border border-red-100 bg-red-50 p-3">
              <div className="flex items-center gap-2">
                <SeverityBadge severity={String(r.severity || 'medium')} />
                <span className="text-sm font-medium">{String(r.rule || '')}</span>
              </div>
              <p className="text-sm text-gray-700 mt-1">{String(r.description || '')}</p>
            </div>
          ))}
        </Section>
      )}

      {persistent.length > 0 && (
        <Section title="⚠️ Persistent Issues">
          {persistent.map((p, i) => (
            <div key={i} className="rounded-lg border border-yellow-100 bg-yellow-50 p-3">
              <div className="flex items-center gap-2">
                <SeverityBadge severity={String(p.severity || 'medium')} />
                <span className="text-sm font-medium">{String(p.rule || '')}</span>
              </div>
              <p className="text-sm text-gray-700 mt-1">{String(p.description || '')}</p>
            </div>
          ))}
        </Section>
      )}

      {newRisks.length > 0 && (
        <Section title="🆕 New Risks">
          {newRisks.map((r, i) => (
            <div key={i} className="rounded-lg border border-orange-100 bg-orange-50 p-3">
              <div className="flex items-center gap-2">
                <SeverityBadge severity={String(r.severity || 'medium')} />
                <span className="text-sm font-medium">{String(r.rule || '')}</span>
              </div>
              <p className="text-sm text-gray-700 mt-1">{String(r.description || '')}</p>
            </div>
          ))}
        </Section>
      )}

      {recommendations.length > 0 && (
        <Section title="📋 Recommendations">
          <ol className="space-y-2">
            {recommendations.map((r, i) => (
              <li key={i} className="flex gap-3 rounded-lg border border-gray-100 bg-gray-50 p-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-purple-600 text-xs font-bold text-white">
                  {String(r.priority ?? i + 1)}
                </span>
                <div>
                  <p className="text-sm font-medium text-gray-900">{String(r.action || '')}</p>
                  {!!r.rationale && <p className="text-xs text-gray-500 mt-1">{String(r.rationale)}</p>}
                </div>
              </li>
            ))}
          </ol>
        </Section>
      )}
    </>
  );
}

/* ── Shared Components ── */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-sm font-semibold text-gray-900 mb-3">{title}</h4>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const colors: Record<string, string> = {
    critical: 'bg-red-600 text-white',
    high: 'bg-orange-500 text-white',
    medium: 'bg-yellow-400 text-gray-900',
    low: 'bg-blue-400 text-white',
  };
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${colors[severity] || colors.medium}`}>
      {severity}
    </span>
  );
}

function EffortBadge({ effort }: { effort: string }) {
  const colors: Record<string, string> = { low: 'text-green-600', medium: 'text-yellow-600', high: 'text-red-600' };
  return <span className={`font-medium ${colors[effort] || ''}`}>{effort}</span>;
}

function ImpactBadge({ impact }: { impact: string }) {
  const colors: Record<string, string> = { high: 'text-green-600', medium: 'text-yellow-600', low: 'text-gray-600' };
  return <span className={`font-medium ${colors[impact] || ''}`}>{impact}</span>;
}
