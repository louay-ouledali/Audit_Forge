import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Bot, Trash2, RefreshCw, ChevronDown, ChevronUp, Target, BarChart3 } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import type { Mission, MissionAnalysisResult, ComparableMission } from '@/types';
import * as api from '@/services/api';
import logoImg from '../assets/logo.png';
import BrandLockup from '@/components/common/BrandLockup';
import ConfirmDialog from '@/components/common/ConfirmDialog';

type AnalysisTab = 'cross_target' | 'category_analysis' | 'cross_mission';

export default function MissionAnalysis() {
  const { missionId } = useParams<{ missionId: string }>();
  const navigate = useNavigate();
  const id = Number(missionId);

  const [mission, setMission] = useState<Mission | null>(null);
  const [analyses, setAnalyses] = useState<MissionAnalysisResult[]>([]);
  const [comparableMissions, setComparableMissions] = useState<ComparableMission[]>([]);
  const [selectedCompareId, setSelectedCompareId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzingType, setAnalyzingType] = useState<AnalysisTab | null>(null);
  const [error, setError] = useState('');
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);

  const fetchData = async () => {
    try {
      const analysesData = await api.getMissionAnalyses(id);
      setAnalyses(analysesData.data);
    } catch {
      setError('Failed to load analyses');
    } finally {
      setLoading(false);
    }
  };

  const fetchMission = async () => {
    try {
      const missionData = await api.getMission(id);
      setMission(missionData);
      if (missionData.client_id) {
        const comparable = await api.getComparableMissions(missionData.client_id);
        setComparableMissions(comparable.filter((m: ComparableMission) => m.id !== id));
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

  const handleRunAnalysis = async (type: AnalysisTab) => {
    setError('');
    setAnalyzingType(type);
    try {
      const payload: { analysis_type: AnalysisTab; compare_mission_id?: number | null } = {
        analysis_type: type,
      };
      if (type === 'cross_mission') {
        if (!selectedCompareId) {
          setError('Please select a previous mission to compare with');
          setAnalyzingType(null);
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
      setAnalyzingType(null);
    }
  };

  const handleDelete = (analysisId: number) => {
    setPendingDeleteId(analysisId);
  };

  const confirmDelete = async () => {
    if (!pendingDeleteId) return;
    try {
      await api.deleteMissionAnalysis(id, pendingDeleteId);
      await fetchData();
    } catch {
      setError('Failed to delete analysis');
    } finally {
      setPendingDeleteId(null);
    }
  };

  const tabs: { key: AnalysisTab; label: string; icon: React.ReactNode }[] = [
    { key: 'cross_target', label: 'Cross-Target Analysis', icon: <Target className="h-4 w-4" /> },
    { key: 'category_analysis', label: 'Category & Deep Analysis', icon: <BarChart3 className="h-4 w-4" /> },
    { key: 'cross_mission', label: 'Compare with Previous Mission', icon: <img src={logoImg} alt="logo" className="h-4 w-4" /> },
  ];

  if (loading) {
    return <div className="flex items-center justify-center py-12 text-dark-secondary">{`Loading\u2026`}</div>;
  }

  return (
    <div className="space-y-6">
      <button
        onClick={() => navigate(-1)}
        className="inline-flex items-center gap-1 text-sm text-dark-secondary hover:text-gray-300"
      >
        <ArrowLeft className="h-4 w-4" />
        Back
      </button>
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {error}
          <button onClick={() => setError('')} className="ml-3 text-red-300 hover:text-white">✕</button>
        </div>
      )}

        <div className="flex items-center gap-4 border-b border-dark-border pb-6 mt-1 mb-4">
          <BrandLockup service="lens" size="xl" />
          <div>
            {mission && (
              <p className="text-sm text-dark-secondary ml-1 mt-1">AI-powered cross-target and cross-mission analysis
                <span className="inline-block ml-3 px-2 py-0.5 rounded border border-dark-border text-[10px] bg-dark-card font-medium text-white">{mission.name}</span>
              </p>
            )}
          </div>
        </div>

      {/* Analysis Sections instead of Tabs */}
      <div className="space-y-8 mt-6">
        {tabs.map((tab, idx) => {
          const typeAnalyses = analyses.filter((a) => a.analysis_type === tab.key);
          const isComparing = tab.key === 'cross_mission';

          return (
            <motion.section
              key={tab.key}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.1 }}
              className="rounded-xl border border-dark-border bg-dark-card overflow-hidden"
            >
              {/* Section Header */}
              <div className="border-b border-dark-border bg-dark-elevated/50 px-6 py-5">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="rounded-lg bg-ey-yellow/10 p-2 text-ey-yellow shrink-0">
                      {tab.icon}
                    </div>
                    <div>
                      <h3 className="text-lg font-semibold text-white">{tab.label}</h3>
                      <p className="text-sm text-dark-secondary">
                        {tab.key === 'cross_target' && 'Detect patterns and outliers across all evaluated targets.'}
                        {tab.key === 'category_analysis' && 'Deep dive into strengths, weaknesses, and quick wins.'}
                        {tab.key === 'cross_mission' && 'Compare this mission against previous baselines.'}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    {typeAnalyses.length > 0 && (
                      <span className="text-xs font-medium text-dark-muted px-2 py-1 rounded-md bg-dark-overlay">
                        {typeAnalyses.length} Result{typeAnalyses.length !== 1 ? 's' : ''}
                      </span>
                    )}
                    <button
                      onClick={() => handleRunAnalysis(tab.key)}
                      disabled={analyzingType !== null}
                      className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50 transition-colors shadow-sm"
                    >
                      {analyzingType === tab.key ? (
                        <>
                          <RefreshCw className="h-4 w-4 animate-spin" />
                          Running...
                        </>
                      ) : (
                        <>
                          <Bot className="h-4 w-4" />
                          Run Analysis
                        </>
                      )}
                    </button>
                  </div>
                </div>

                {isComparing && (
                  <div className="mt-4 flex items-center gap-3 rounded-lg bg-dark-overlay/50 p-3 border border-dark-border/50">
                    <label className="text-sm text-gray-300 font-medium">Compare with:</label>
                    <select
                      value={selectedCompareId ?? ''}
                      onChange={(e) => setSelectedCompareId(e.target.value ? Number(e.target.value) : null)}
                      className="flex-1 rounded-lg border border-dark-border bg-dark-elevated px-3 py-1.5 text-sm text-white focus:border-ey-yellow/50 focus:outline-none"
                    >
                      <option value="">-- Select a previous mission --</option>
                      {comparableMissions.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name} {m.compliance != null ? `(${m.compliance}%)` : ''}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>

              {/* Section Body */}
              <div className="p-6 bg-dark-card">
                {typeAnalyses.length === 0 ? (
                  <div className="py-8 my-2 flex flex-col items-center text-center border-2 border-dashed border-dark-border rounded-lg text-dark-secondary bg-dark-elevated/20">
                    <Bot className="h-10 w-10 text-dark-muted mb-3 opacity-50" />
                    <p>No results yet.</p>
                    <p className="text-sm mt-1">Click "Run Analysis" to generate insights.</p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <AnimatePresence>
                      {typeAnalyses.map((analysis) => (
                        <motion.div
                          key={analysis.id}
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: 'auto' }}
                          exit={{ opacity: 0, height: 0 }}
                        >
                          <AnalysisCard
                            analysis={analysis}
                            expanded={expandedId === analysis.id}
                            onToggle={() => setExpandedId(expandedId === analysis.id ? null : analysis.id)}
                            onDelete={() => handleDelete(analysis.id)}
                          />
                        </motion.div>
                      ))}
                    </AnimatePresence>
                  </div>
                )}
              </div>
            </motion.section>
          );
        })}
      </div>
      <ConfirmDialog
        open={pendingDeleteId !== null}
        title="Delete Analysis"
        message="Are you sure you want to delete this analysis? This action cannot be undone."
        confirmLabel="Delete"
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setPendingDeleteId(null)}
      />
    </div >
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
    <div className="rounded-xl border border-dark-border bg-dark-card overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 cursor-pointer hover:bg-dark-elevated" onClick={onToggle}>
        <div className="flex items-center gap-3">
          <Bot className="h-5 w-5 text-ey-yellow" />
          <div>
            <span className="text-sm font-medium text-white">
              {analysis.analysis_type === 'cross_target' && 'Cross-Target Pattern Detection'}
              {analysis.analysis_type === 'category_analysis' && 'Category-Level Analysis'}
              {analysis.analysis_type === 'cross_mission' && 'Cross-Mission Comparison'}
            </span>
            <div className="flex items-center gap-3 text-xs text-dark-secondary">
              {analysis.generated_at && (
                <span>{new Date(analysis.generated_at).toLocaleString()}</span>
              )}
              {analysis.llm_model_used && (
                <span className="rounded bg-dark-overlay px-1.5 py-0.5">{analysis.llm_model_used}</span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="rounded-md p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400"
            title="Delete"
            aria-label="Delete analysis"
          >
            <Trash2 className="h-4 w-4" />
          </button>
          {expanded ? <ChevronUp className="h-4 w-4 text-dark-muted" /> : <ChevronDown className="h-4 w-4 text-dark-muted" />}
        </div>
      </div>

      {expanded && (
        <div className="border-t border-dark-border px-6 py-4 space-y-6">
          {analysis.analysis_type === 'cross_target' && <CrossTargetResult result={result} />}
          {analysis.analysis_type === 'category_analysis' && <CategoryResult result={result} />}
          {analysis.analysis_type === 'cross_mission' && <CrossMissionResult result={result} />}
        </div>
      )}
    </div>
  );
}

/* -- Cross-Target Result Display -- */

function CrossTargetResult({ result }: { result: Record<string, unknown> }) {
  const systemic = (result.systemic_issues as Array<Record<string, unknown>>) || [];
  const outliers = (result.outliers as Array<Record<string, unknown>>) || [];
  const riskChains = (result.risk_chains as Array<Record<string, unknown>>) || [];
  const plan = (result.remediation_plan as Array<Record<string, unknown>>) || [];

  return (
    <>
      {systemic.length > 0 && (
        <Section title="Systemic Issues">
          {systemic.map((issue, i) => (
            <div key={i} className="rounded-lg border border-red-500/20 bg-red-500/10 p-4 space-y-1">
              <div className="flex items-center gap-2">
                <SeverityBadge severity={String(issue.severity || 'medium')} />
                <span className="font-medium text-white">{String(issue.title || '')}</span>
              </div>
              {!!issue.likely_cause && <p className="text-sm text-gray-300">Root cause: {String(issue.likely_cause)}</p>}
              {!!issue.affected_targets && (
                <p className="text-xs text-dark-secondary">Targets: {(issue.affected_targets as string[]).join(', ')}</p>
              )}
              {!!issue.recommendation && <p className="text-sm text-ey-yellow mt-1">{String(issue.recommendation)}</p>}
            </div>
          ))}
        </Section>
      )}

      {outliers.length > 0 && (
        <Section title="Outliers">
          {outliers.map((o, i) => (
            <div key={i} className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-4 space-y-1">
              <span className="font-medium text-white">{String(o.target || '')}</span>
              <p className="text-sm text-gray-300">
                Compliance: {String(o.compliance ?? '')}% (avg: {String(o.average_compliance ?? '')}%)
              </p>
              {!!o.recommendation && <p className="text-sm text-ey-yellow">{String(o.recommendation)}</p>}
            </div>
          ))}
        </Section>
      )}

      {riskChains.length > 0 && (
        <Section title="Critical Risk Chains">
          {riskChains.map((rc, i) => (
            <div key={i} className="rounded-lg border border-orange-500/20 bg-orange-500/10 p-4 space-y-1">
              <div className="flex items-center gap-2">
                <SeverityBadge severity={String(rc.combined_risk || 'high')} />
                <span className="font-medium text-white">{String(rc.title || '')}</span>
              </div>
              <p className="text-sm text-gray-300">{String(rc.description || '')}</p>
              {!!rc.recommendation && <p className="text-sm text-ey-yellow">{String(rc.recommendation)}</p>}
            </div>
          ))}
        </Section>
      )}

      {plan.length > 0 && (
        <Section title="Prioritized Remediation Plan">
          <ol className="space-y-2">
            {plan.map((item, i) => (
              <li key={i} className="flex gap-3 rounded-lg border border-dark-border bg-dark-elevated p-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ey-yellow text-xs font-bold text-black">
                  {String(item.priority ?? i + 1)}
                </span>
                <div className="space-y-1">
                  <p className="text-sm font-medium text-white">{String(item.action || '')}</p>
                  <div className="flex gap-3 text-xs text-dark-secondary">
                    <span>Effort: <EffortBadge effort={String(item.effort || 'medium')} /></span>
                    <span>Impact: <ImpactBadge impact={String(item.impact || 'medium')} /></span>
                  </div>
                  {!!item.rationale && <p className="text-xs text-dark-secondary">{String(item.rationale)}</p>}
                </div>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {systemic.length === 0 && outliers.length === 0 && riskChains.length === 0 && plan.length === 0 && (
        <p className="text-sm text-dark-secondary">No significant findings in this analysis.</p>
      )}
    </>
  );
}

/* -- Category Result Display -- */

function CategoryResult({ result }: { result: Record<string, unknown> }) {
  const strengths = (result.strengths as Array<Record<string, unknown>>) || [];
  const weaknesses = (result.weaknesses as Array<Record<string, unknown>>) || [];
  const quickWins = (result.quick_wins as Array<Record<string, unknown>>) || [];
  const recommendations = (result.strategic_recommendations as Array<Record<string, unknown>>) || [];

  return (
    <>
      {strengths.length > 0 && (
        <Section title="Strengths">
          {strengths.map((s, i) => (
            <div key={i} className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-3">
              <span className="font-medium text-emerald-400">{String(s.category || '')}</span>
              {s.compliance != null && <span className="ml-2 text-sm text-emerald-400">{String(s.compliance)}%</span>}
              <p className="text-sm text-gray-300 mt-1">{String(s.description || '')}</p>
            </div>
          ))}
        </Section>
      )}

      {weaknesses.length > 0 && (
        <Section title="Weaknesses">
          {weaknesses.map((w, i) => (
            <div key={i} className="rounded-lg border border-red-500/20 bg-red-500/10 p-3">
              <span className="font-medium text-red-400">{String(w.category || '')}</span>
              {w.compliance != null && <span className="ml-2 text-sm text-red-400">{String(w.compliance)}%</span>}
              <p className="text-sm text-gray-300 mt-1">{String(w.description || '')}</p>
            </div>
          ))}
        </Section>
      )}

      {quickWins.length > 0 && (
        <Section title="Quick Wins">
          {quickWins.map((q, i) => (
            <div key={i} className="rounded-lg border border-blue-500/20 bg-blue-500/10 p-3">
              <span className="font-medium text-blue-400">{String(q.category || '')}</span>
              <p className="text-sm text-gray-300 mt-1">{String(q.description || '')}</p>
              {q.fix_count != null && (
                <p className="text-xs text-blue-400 mt-1">
                  {String(q.fix_count)} fixes needed ({String(q.current_compliance ?? '')}% {'\u2192'} {String(q.potential_compliance ?? '')}%)
                </p>
              )}
            </div>
          ))}
        </Section>
      )}

      {recommendations.length > 0 && (
        <Section title="Strategic Recommendations">
          <ol className="space-y-2">
            {recommendations.map((r, i) => (
              <li key={i} className="flex gap-3 rounded-lg border border-dark-border bg-dark-elevated p-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ey-yellow text-xs font-bold text-black">
                  {String(r.priority ?? i + 1)}
                </span>
                <div>
                  <p className="text-sm font-medium text-white">{String(r.recommendation || '')}</p>
                  {!!r.rationale && <p className="text-xs text-dark-secondary mt-1">{String(r.rationale)}</p>}
                </div>
              </li>
            ))}
          </ol>
        </Section>
      )}
    </>
  );
}

/* -- Cross-Mission Result Display -- */

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
        <div className={`rounded-lg p-4 ${trend.direction === 'improving' ? 'border border-emerald-500/30 bg-emerald-500/10' :
          trend.direction === 'declining' ? 'border border-red-500/30 bg-red-500/10' :
            'border border-amber-500/30 bg-amber-500/10'
          }`}>
          <span className="text-sm font-medium text-white">
            {'Trend: '}{trend.direction === 'improving' ? 'Improving' :
              trend.direction === 'declining' ? 'Declining' : 'Stable'}
          </span>
          {!!trend.summary && <p className="text-sm text-gray-300 mt-1">{String(trend.summary)}</p>}
        </div>
      )}

      {improvement && (
        <Section title="Improvement Summary">
          <p className="text-sm text-gray-300">{String(improvement.description || '')}</p>
          {improvement.improved_count != null && (
            <p className="text-sm text-emerald-400 mt-1">{String(improvement.improved_count)} rules improved</p>
          )}
        </Section>
      )}

      {regressions.length > 0 && (
        <Section title="Regression Alerts">
          {regressions.map((r, i) => (
            <div key={i} className="rounded-lg border border-red-500/20 bg-red-500/10 p-3">
              <div className="flex items-center gap-2">
                <SeverityBadge severity={String(r.severity || 'medium')} />
                <span className="text-sm font-medium text-white">{String(r.rule || '')}</span>
              </div>
              <p className="text-sm text-gray-300 mt-1">{String(r.description || '')}</p>
            </div>
          ))}
        </Section>
      )}

      {persistent.length > 0 && (
        <Section title="Persistent Issues">
          {persistent.map((p, i) => (
            <div key={i} className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-3">
              <div className="flex items-center gap-2">
                <SeverityBadge severity={String(p.severity || 'medium')} />
                <span className="text-sm font-medium text-white">{String(p.rule || '')}</span>
              </div>
              <p className="text-sm text-gray-300 mt-1">{String(p.description || '')}</p>
            </div>
          ))}
        </Section>
      )}

      {newRisks.length > 0 && (
        <Section title="New Risks">
          {newRisks.map((r, i) => (
            <div key={i} className="rounded-lg border border-orange-500/20 bg-orange-500/10 p-3">
              <div className="flex items-center gap-2">
                <SeverityBadge severity={String(r.severity || 'medium')} />
                <span className="text-sm font-medium text-white">{String(r.rule || '')}</span>
              </div>
              <p className="text-sm text-gray-300 mt-1">{String(r.description || '')}</p>
            </div>
          ))}
        </Section>
      )}

      {recommendations.length > 0 && (
        <Section title="Recommendations">
          <ol className="space-y-2">
            {recommendations.map((r, i) => (
              <li key={i} className="flex gap-3 rounded-lg border border-dark-border bg-dark-elevated p-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ey-yellow text-xs font-bold text-black">
                  {String(r.priority ?? i + 1)}
                </span>
                <div>
                  <p className="text-sm font-medium text-white">{String(r.action || '')}</p>
                  {!!r.rationale && <p className="text-xs text-dark-secondary mt-1">{String(r.rationale)}</p>}
                </div>
              </li>
            ))}
          </ol>
        </Section>
      )}
    </>
  );
}

/* -- Shared Components -- */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-sm font-semibold text-white mb-3">{title}</h4>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const colors: Record<string, string> = {
    critical: 'bg-red-500/20 text-red-400',
    high: 'bg-orange-500/20 text-orange-400',
    medium: 'bg-amber-500/20 text-amber-400',
    low: 'bg-blue-500/20 text-blue-400',
  };
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${colors[severity] || colors.medium}`}>
      {severity}
    </span>
  );
}

function EffortBadge({ effort }: { effort: string }) {
  const colors: Record<string, string> = { low: 'text-emerald-400', medium: 'text-amber-400', high: 'text-red-400' };
  return <span className={`font-medium ${colors[effort] || ''}`}>{effort}</span>;
}

function ImpactBadge({ impact }: { impact: string }) {
  const colors: Record<string, string> = { high: 'text-emerald-400', medium: 'text-amber-400', low: 'text-dark-secondary' };
  return <span className={`font-medium ${colors[impact] || ''}`}>{impact}</span>;
}
