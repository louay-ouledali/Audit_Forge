import { useEffect, useState } from 'react';
import { getFrameworkCoverage, getFrameworkRules } from '@/services/api';
import type { FrameworkCoverage, FrameworkCoverageItem, FrameworkRuleItem } from '@/types';
import { Shield, ChevronDown, ChevronRight, BarChart3, AlertTriangle, CheckCircle2 } from 'lucide-react';

interface Props {
  benchmarkId: number;
  benchmarkName: string;
}

const CATEGORY_COLORS: Record<string, string> = {
  Government: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  Healthcare: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  Financial: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  Privacy: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  Audit: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  International: 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
  'Best Practice': 'bg-teal-500/20 text-teal-400 border-teal-500/30',
  Threat: 'bg-red-500/20 text-red-400 border-red-500/30',
  Reference: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
  Vulnerability: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  Other: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
};

export default function FrameworkCoveragePanel({ benchmarkId }: Props) {
  const [coverage, setCoverage] = useState<FrameworkCoverage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedFw, setExpandedFw] = useState<string | null>(null);
  const [fwRules, setFwRules] = useState<Record<string, FrameworkRuleItem[]>>({});
  const [loadingRules, setLoadingRules] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getFrameworkCoverage(benchmarkId)
      .then(setCoverage)
      .catch((e) => setError(e?.response?.data?.detail || 'Failed to load framework coverage'))
      .finally(() => setLoading(false));
  }, [benchmarkId]);

  const toggleFramework = async (fw: FrameworkCoverageItem) => {
    if (expandedFw === fw.key) {
      setExpandedFw(null);
      return;
    }
    setExpandedFw(fw.key);
    if (!fwRules[fw.key]) {
      setLoadingRules(fw.key);
      try {
        const data = await getFrameworkRules(benchmarkId, fw.key);
        setFwRules((prev) => ({ ...prev, [fw.key]: data.rules }));
      } catch {
        // silent
      } finally {
        setLoadingRules(null);
      }
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-ey-yellow" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-6 text-center">
        <AlertTriangle className="inline h-5 w-5 text-red-400 mb-2" />
        <p className="text-red-400 text-sm">{error}</p>
      </div>
    );
  }

  if (!coverage || coverage.total_rules === 0) {
    return (
      <div className="rounded-xl border border-dark-border bg-dark-card p-8 text-center">
        <Shield className="inline h-8 w-8 text-dark-secondary mb-3" />
        <p className="text-dark-secondary text-sm">No rules found in this benchmark.</p>
      </div>
    );
  }

  const scorePct = coverage.overall_score;
  const scoreColor = scorePct >= 75 ? 'text-emerald-400' : scorePct >= 40 ? 'text-amber-400' : 'text-red-400';
  const scoreRing = scorePct >= 75 ? 'border-emerald-500' : scorePct >= 40 ? 'border-amber-500' : 'border-red-500';

  // Group frameworks by category
  const categories = coverage.frameworks.reduce<Record<string, FrameworkCoverageItem[]>>((acc, fw) => {
    const cat = fw.category || 'Other';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(fw);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      {/* Overall Score Card */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="rounded-xl border border-dark-border bg-dark-card p-5 flex flex-col items-center justify-center">
          <div className={`w-20 h-20 rounded-full border-4 ${scoreRing} flex items-center justify-center mb-2`}>
            <span className={`text-2xl font-bold ${scoreColor}`}>{scorePct}%</span>
          </div>
          <p className="text-xs text-dark-secondary mt-1">Framework Coverage</p>
        </div>

        <div className="rounded-xl border border-dark-border bg-dark-card p-5">
          <BarChart3 className="h-5 w-5 text-ey-yellow mb-2" />
          <p className="text-2xl font-bold text-white">{coverage.framework_count}</p>
          <p className="text-xs text-dark-secondary">Frameworks Mapped</p>
        </div>

        <div className="rounded-xl border border-dark-border bg-dark-card p-5">
          <Shield className="h-5 w-5 text-sky-400 mb-2" />
          <p className="text-2xl font-bold text-white">{coverage.rules_with_framework_mappings}</p>
          <p className="text-xs text-dark-secondary">Rules with Mappings</p>
          <p className="text-xs text-dark-tertiary">of {coverage.total_rules} total</p>
        </div>

        <div className="rounded-xl border border-dark-border bg-dark-card p-5">
          <CheckCircle2 className="h-5 w-5 text-emerald-400 mb-2" />
          <p className="text-2xl font-bold text-white">
            {coverage.frameworks.reduce((s, f) => s + f.controls_mapped, 0)}
          </p>
          <p className="text-xs text-dark-secondary">Total Controls Mapped</p>
        </div>
      </div>

      {/* Frameworks by Category */}
      {Object.entries(categories).map(([category, fws]) => (
        <div key={category} className="space-y-2">
          <h3 className="text-sm font-semibold text-dark-secondary uppercase tracking-wider flex items-center gap-2">
            <span className={`inline-block w-2 h-2 rounded-full ${CATEGORY_COLORS[category]?.split(' ')[0] || 'bg-gray-500/20'}`} />
            {category}
          </h3>

          <div className="space-y-2">
            {fws.map((fw) => (
              <div key={fw.key} className="rounded-xl border border-dark-border bg-dark-card overflow-hidden">
                {/* Framework Header */}
                <button
                  onClick={() => toggleFramework(fw)}
                  className="w-full flex items-center justify-between p-4 hover:bg-dark-elevated transition-colors"
                >
                  <div className="flex items-center gap-3">
                    {expandedFw === fw.key
                      ? <ChevronDown className="h-4 w-4 text-dark-secondary" />
                      : <ChevronRight className="h-4 w-4 text-dark-secondary" />
                    }
                    <div className="text-left">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white">{fw.name}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded border ${CATEGORY_COLORS[fw.category] || CATEGORY_COLORS.Other}`}>
                          {fw.category}
                        </span>
                      </div>
                      {fw.description && (
                        <p className="text-xs text-dark-secondary mt-0.5">{fw.description}</p>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-6">
                    <div className="text-right">
                      <p className="text-sm font-medium text-white">{fw.controls_mapped}</p>
                      <p className="text-[10px] text-dark-secondary">controls</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-medium text-white">{fw.rules_covered}</p>
                      <p className="text-[10px] text-dark-secondary">rules</p>
                    </div>
                    <div className="w-24">
                      <div className="flex justify-between text-[10px] mb-1">
                        <span className="text-dark-secondary">Coverage</span>
                        <span className={fw.coverage_percentage >= 50 ? 'text-emerald-400' : 'text-amber-400'}>
                          {fw.coverage_percentage}%
                        </span>
                      </div>
                      <div className="h-1.5 bg-dark-base rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${fw.coverage_percentage >= 50 ? 'bg-emerald-500' : 'bg-amber-500'}`}
                          style={{ width: `${Math.min(fw.coverage_percentage, 100)}%` }}
                        />
                      </div>
                    </div>
                  </div>
                </button>

                {/* Expanded: Sample Controls + Rules */}
                {expandedFw === fw.key && (
                  <div className="border-t border-dark-border p-4 space-y-4">
                    {/* Sample Controls */}
                    {fw.sample_controls.length > 0 && (
                      <div>
                        <p className="text-xs font-medium text-dark-secondary mb-2">Sample Controls:</p>
                        <div className="flex flex-wrap gap-1.5">
                          {fw.sample_controls.map((ctrl) => (
                            <span key={ctrl} className="text-[10px] px-2 py-0.5 rounded-full bg-dark-elevated border border-dark-border text-dark-secondary">
                              {ctrl}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Rules List */}
                    {loadingRules === fw.key ? (
                      <div className="text-center py-4">
                        <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-ey-yellow mx-auto" />
                      </div>
                    ) : fwRules[fw.key] ? (
                      <div>
                        <p className="text-xs font-medium text-dark-secondary mb-2">
                          Mapped Rules ({fwRules[fw.key].length}):
                        </p>
                        <div className="max-h-64 overflow-y-auto custom-scrollbar space-y-1">
                          {fwRules[fw.key].map((rule) => (
                            <div key={rule.rule_id} className="flex items-center justify-between py-1.5 px-3 rounded-lg hover:bg-dark-elevated">
                              <div className="flex items-center gap-2 min-w-0">
                                <span className="text-xs font-mono text-ey-yellow shrink-0">{rule.section_number}</span>
                                <span className="text-xs text-white truncate">{rule.title}</span>
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                                  rule.severity === 'critical' ? 'bg-red-500/20 text-red-400' :
                                  rule.severity === 'high' ? 'bg-orange-500/20 text-orange-400' :
                                  rule.severity === 'medium' ? 'bg-amber-500/20 text-amber-400' :
                                  'bg-gray-500/20 text-gray-400'
                                }`}>{rule.severity}</span>
                                <span className="text-[10px] text-dark-secondary">{rule.controls.join(', ')}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}

      {coverage.frameworks.length === 0 && (
        <div className="rounded-xl border border-dark-border bg-dark-card p-8 text-center">
          <Shield className="inline h-8 w-8 text-dark-secondary mb-3" />
          <p className="text-dark-secondary text-sm">No framework mappings found in this benchmark's rules.</p>
          <p className="text-dark-tertiary text-xs mt-1">
            Import scan results from Nessus, Qualys, or OpenVAS to auto-detect framework references.
          </p>
        </div>
      )}
    </div>
  );
}
