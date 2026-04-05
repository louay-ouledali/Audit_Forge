import { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { ArrowLeft, Play, Pause, ShieldOff, Search, ChevronDown, ChevronUp, AlertCircle, CheckCircle2, Flag, RefreshCw, Lock, Unlock, History, ShieldCheck, CheckCheck, AlertTriangle, Download, Upload, Sparkles, Check, X, Plus, Trash2, Zap, Activity, BarChart3, Pencil, GitCompare, Database, MoreHorizontal } from 'lucide-react';
import { motion } from 'framer-motion';
import type { Benchmark, Rule, EnrichStatus, VerifyStatus, ValidateStatus, ValidationResultItem, RuleCommand, CommandHistoryEntry, VerificationReport, AIRuleCreateResponse, MigrationReadiness, BenchmarkVersionItem, VersionDiffResponse, CacheAccelerationStats } from '@/types';
import * as api from '@/services/api';
import logoImg from '../assets/logo.png';
import RuleEditor from '@/components/benchmark/RuleEditor';
import RuleTestPanel from '@/components/benchmark/RuleTestPanel';
import InlineEditField from '@/components/benchmark/InlineEditField';
import FrameworkCoveragePanel from '@/components/FrameworkCoveragePanel';
import { useNumericParam } from '@/hooks/useNumericParam';
import { extractApiError } from '@/utils/apiError';
import ConfirmDialog from '@/components/common/ConfirmDialog';
import { useToast } from '@/components/common/Toast';
import CopilotPanel from '@/components/copilot/CopilotPanel';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';

// ── Helper Badges ──

function severityBadge(severity: string) {
  const styles: Record<string, string> = {
    critical: 'bg-red-500/10 text-red-400',
    high: 'bg-orange-500/10 text-orange-400',
    medium: 'bg-amber-500/10 text-amber-400',
    low: 'bg-emerald-500/10 text-emerald-400',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${styles[severity] || 'bg-dark-overlay text-dark-secondary'}`}>
      {severity}
    </span>
  );
}

function statusBadge(status: string) {
  const styles: Record<string, string> = {
    completed: 'bg-emerald-500/10 text-emerald-400',
    processing: 'bg-sky-500/10 text-sky-400',
    failed: 'bg-red-500/10 text-red-400',
    paused: 'bg-amber-500/10 text-amber-400',
    pending: 'bg-dark-overlay text-dark-secondary',
    completed_with_issues: 'bg-orange-500/10 text-orange-400',
    overridden: 'bg-amber-500/10 text-amber-400',
    verified: 'bg-emerald-500/10 text-emerald-400',
    flagged: 'bg-red-500/10 text-red-400',
    generated: 'bg-sky-500/10 text-sky-400',
    pending_review: 'bg-amber-500/10 text-amber-400',
    not_started: 'bg-dark-overlay text-dark-secondary',
    validated: 'bg-emerald-500/10 text-emerald-400',
    corrected: 'bg-amber-500/10 text-amber-400',
    applied: 'bg-emerald-500/10 text-emerald-400',
    dismissed: 'bg-dark-overlay text-dark-secondary',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status] || styles.pending}`}>
      {status.replace(/_/g, ' ')}
    </span>
  );
}

function verificationResultBadge(result: string) {
  const styles: Record<string, string> = {
    pass: 'bg-emerald-500/10 text-emerald-400',
    fail: 'bg-red-500/10 text-red-400',
    warn: 'bg-amber-500/10 text-amber-400',
    skip: 'bg-dark-overlay text-dark-secondary',
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${styles[result] || 'bg-dark-overlay text-dark-secondary'}`}>
      {result}
    </span>
  );
}

function commandStatusBadge(cmd: RuleCommand | null | undefined) {
  if (!cmd) return <span className="rounded bg-dark-overlay px-2 py-0.5 text-[10px] font-medium text-dark-muted">No Command</span>;
  if (cmd.is_protected) return <span className="rounded bg-purple-500/10 px-2 py-0.5 text-[10px] font-medium text-purple-400">Protected</span>;
  if (cmd.status === 'flagged') return <span className="rounded bg-red-500/10 px-2 py-0.5 text-[10px] font-medium text-red-400">Flagged</span>;
  if (cmd.status === 'verified') return <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400">Verified</span>;
  if (cmd.status === 'generated') return <span className="rounded bg-sky-500/10 px-2 py-0.5 text-[10px] font-medium text-sky-400">Generated</span>;
  if (cmd.status === 'inherited') return <span className="rounded bg-violet-500/10 px-2 py-0.5 text-[10px] font-medium text-violet-400">Inherited</span>;
  return <span className="rounded bg-dark-overlay px-2 py-0.5 text-[10px] font-medium text-dark-secondary">{cmd.status}</span>;
}

// ── Tab type ──
type TabId = 'rules' | 'pipeline' | 'validation' | 'coverage' | 'copilot';

export default function BenchmarkDetail() {
  const benchmarkId = useNumericParam('id', '/benchmarks');
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();

  // ── Core state ──
  const [benchmark, setBenchmark] = useState<Benchmark | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [enrichStatus, setEnrichStatus] = useState<EnrichStatus | null>(null);
  const [verifyStatus, setVerifyStatus] = useState<VerifyStatus | null>(null);
  const [validateStatus, setValidateStatus] = useState<ValidateStatus | null>(null);
  const [validationResults, setValidationResults] = useState<ValidationResultItem[]>([]);
  const [validationFilter, setValidationFilter] = useState('');
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
  const [showAddRule, setShowAddRule] = useState(false);
  const [editingRule, setEditingRule] = useState<Rule | null>(null);
  const benchmarkImportRef = useRef<HTMLInputElement>(null);
  const rulesImportRef = useRef<HTMLInputElement>(null);
  const commandsImportRef = useRef<HTMLInputElement>(null);
  const [migrationReadiness, setMigrationReadiness] = useState<MigrationReadiness | null>(null);
  const [versions, setVersions] = useState<BenchmarkVersionItem[]>([]);
  const [showVersionDropdown, setShowVersionDropdown] = useState(false);
  const [versionDiff, setVersionDiff] = useState<VersionDiffResponse | null>(null);
  const [diffBadges, setDiffBadges] = useState<Record<string, 'added' | 'modified'>>({});
  const [showDiffBadges, setShowDiffBadges] = useState(false);
  const [cacheStats, setCacheStats] = useState<CacheAccelerationStats | null>(null);
  const versionDropdownRef = useRef<HTMLDivElement>(null);
  const [showTestPanel, setShowTestPanel] = useState<number | null>(null);
  const [mediumRuleCount, setMediumRuleCount] = useState(0);
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [confirmDeleteRule, setConfirmDeleteRule] = useState<{ id: number; section: string } | null>(null);
  const [readinessLoading, setReadinessLoading] = useState(false);

  // ── Tab state ──
  const [activeTab, setActiveTab] = useState<TabId>('rules');
  const [pendingCopilotCount, setPendingCopilotCount] = useState(0);

  // Auto-open Copilot when navigated from AI-Assisted create
  useEffect(() => {
    const state = location.state as { openCopilot?: boolean } | null;
    if (state?.openCopilot) setActiveTab('copilot');
  }, [location.state]);

  // ── Data fetching ──
  const fetchData = useCallback(async () => {
    try {
      const [bm, es, vs, vds] = await Promise.all([
        api.getBenchmark(benchmarkId),
        api.getEnrichmentStatus(benchmarkId),
        api.getVerificationStatus(benchmarkId),
        api.getValidationStatus(benchmarkId),
      ]);
      setBenchmark(bm);
      setEnrichStatus(es);
      setVerifyStatus(vs);
      setValidateStatus(vds);
      api.getSeverityEnrichStatus(benchmarkId).then(s => setMediumRuleCount(s.medium_count)).catch(() => { });
      api.getMigrationReadiness(benchmarkId).then(setMigrationReadiness).catch(() => { });
      api.getBenchmarkVersions(benchmarkId).then(v => setVersions(v.versions)).catch(() => { });
      api.getBenchmarkCacheStats(benchmarkId).then(setCacheStats).catch(() => { });
      api.copilotGetPending(benchmarkId).then(d => setPendingCopilotCount(d.count)).catch(() => { });
    } catch {
      setError('Failed to load benchmark');
    } finally {
      setLoading(false);
    }
  }, [benchmarkId]);

  const fetchRules = useCallback(async () => {
    try {
      const params: Record<string, string> = {};
      if (debouncedSearch) params.search = debouncedSearch;
      if (severityFilter) params.severity = severityFilter;
      const data = await api.getBenchmarkRules(benchmarkId, params);
      setRules(data);
    } catch {
      // Rules may not be ready yet
    }
  }, [benchmarkId, debouncedSearch, severityFilter]);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchTerm), 300);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => { fetchRules(); }, [fetchRules]);

  // Poll when processing
  useEffect(() => {
    if (!benchmark) return;
    const isProcessing = ['processing'].includes(benchmark.phase1_status) ||
      ['processing'].includes(benchmark.phase2_status) ||
      ['processing'].includes(benchmark.verification_status) ||
      (benchmark.phase3_status === 'processing');
    if (!isProcessing) return;
    const interval = setInterval(() => { fetchData(); fetchRules(); }, 3000);
    return () => clearInterval(interval);
  }, [benchmark, fetchData, fetchRules]);

  useEffect(() => {
    if (!successMsg) return;
    const timer = setTimeout(() => setSuccessMsg(''), 5000);
    return () => clearTimeout(timer);
  }, [successMsg]);

  useEffect(() => {
    if (!showVersionDropdown) return;
    const handleClick = (e: MouseEvent) => {
      if (versionDropdownRef.current && !versionDropdownRef.current.contains(e.target as Node)) {
        setShowVersionDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showVersionDropdown]);

  // ── Handlers ──

  const handleEnrich = async () => {
    try { await api.startEnrichment(benchmarkId); await fetchData(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to start enrichment')); }
  };
  const handlePauseEnrich = async () => {
    try { await api.pauseEnrichment(benchmarkId); await fetchData(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to pause enrichment')); }
  };

  const [sevLoading, setSevLoading] = useState(false);
  const handleClassifySeverities = async () => {
    setSevLoading(true);
    try {
      const res = await api.startSeverityEnrichment(benchmarkId);
      if (res.rules_to_classify === 0) setSuccessMsg('All rules already have classified severities');
      else setSuccessMsg(`AI severity classification started for ${res.rules_to_classify} rules`);
      await fetchData();
    } catch (err: unknown) {
      setError(extractApiError(err, 'Failed to start severity classification'));
    } finally { setSevLoading(false); }
  };

  const handleVerify = async () => {
    try { await api.startVerification(benchmarkId); await fetchData(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to start verification')); }
  };
  const handleBulkAccept = async () => {
    try { setActionLoading(true); await api.bulkAcceptCommands(benchmarkId); await fetchData(); await fetchRules(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to bulk accept')); }
    finally { setActionLoading(false); }
  };
  const handleBulkRegenerate = async () => {
    try { setActionLoading(true); await api.bulkRegenerateCommands(benchmarkId); await fetchData(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to start bulk regeneration')); }
    finally { setActionLoading(false); }
  };
  const handleOverride = async () => {
    try { setActionLoading(true); await api.overrideVerification(benchmarkId); await fetchData(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to override')); }
    finally { setActionLoading(false); }
  };

  const handleStartValidation = async () => {
    try { await api.startValidation(benchmarkId); await fetchData(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to start validation')); }
  };
  const handlePauseValidation = async () => {
    try { await api.pauseValidation(benchmarkId); await fetchData(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to pause validation')); }
  };

  const fetchValidationResults = useCallback(async () => {
    try {
      const params = validationFilter ? { status_filter: validationFilter } : undefined;
      const result = await api.getValidationResults(benchmarkId, params);
      setValidationResults(result.data);
    } catch { /* silent */ }
  }, [benchmarkId, validationFilter]);

  useEffect(() => { fetchValidationResults(); }, [validationFilter, fetchValidationResults]);

  const handleApplyCorrection = async (ruleCommandId: number) => {
    try { setActionLoading(true); await api.applyCorrection(benchmarkId, ruleCommandId); await fetchValidationResults(); setSuccessMsg('Correction applied'); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to apply correction')); }
    finally { setActionLoading(false); }
  };
  const handleDismissCorrection = async (ruleCommandId: number) => {
    try { setActionLoading(true); await api.dismissCorrection(benchmarkId, ruleCommandId); await fetchValidationResults(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to dismiss correction')); }
    finally { setActionLoading(false); }
  };
  const handleBulkApplyCorrections = async () => {
    try {
      setActionLoading(true);
      const result = await api.bulkApplyCorrections(benchmarkId);
      setSuccessMsg(result.message); await fetchValidationResults(); await fetchData();
    } catch (err: unknown) { setError(extractApiError(err, 'Failed to bulk apply')); }
    finally { setActionLoading(false); }
  };
  const handleBulkDismissCorrections = async () => {
    try {
      setActionLoading(true);
      const result = await api.bulkDismissCorrections(benchmarkId);
      setSuccessMsg(result.message); await fetchValidationResults(); await fetchData();
    } catch (err: unknown) { setError(extractApiError(err, 'Failed to bulk dismiss')); }
    finally { setActionLoading(false); }
  };

  // ── Export/Import ──
  const downloadBlob = (blob: Blob, filename: string) => {
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    window.URL.revokeObjectURL(url); document.body.removeChild(a);
  };
  const handleExportRules = async () => {
    try { const blob = await api.exportRules(benchmarkId); downloadBlob(blob, `${benchmark?.name?.replace(/ /g, '_') || 'benchmark'}_phase1_rules.json`); }
    catch { setError('Failed to export rules'); }
  };
  const handleImportRules = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    try { setActionLoading(true); const result = await api.importRules(benchmarkId, file); setError(''); setSuccessMsg(result.message); await fetchData(); await fetchRules(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to import rules')); }
    finally { setActionLoading(false); if (rulesImportRef.current) rulesImportRef.current.value = ''; }
  };
  const handleExportCommands = async () => {
    try { const blob = await api.exportCommands(benchmarkId); downloadBlob(blob, `${benchmark?.name?.replace(/ /g, '_') || 'benchmark'}_phase2_commands.json`); }
    catch { setError('Failed to export commands'); }
  };
  const handleImportCommands = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    try { setActionLoading(true); const result = await api.importCommands(benchmarkId, file); setError(''); setSuccessMsg(result.message); await fetchData(); await fetchRules(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to import commands')); }
    finally { setActionLoading(false); if (commandsImportRef.current) commandsImportRef.current.value = ''; }
  };

  // ── Rule CRUD ──
  const handleRuleCreated = async (result: AIRuleCreateResponse) => {
    setShowAddRule(false);
    setSuccessMsg(result.message + (result.commands_generated ? ' (commands generated)' : ''));
    await fetchData(); await fetchRules();
  };
  const handleDeleteRule = (ruleId: number, sectionNumber: string) => { setConfirmDeleteRule({ id: ruleId, section: sectionNumber }); };
  const confirmDeleteRuleAction = async () => {
    if (!confirmDeleteRule) return;
    const { id: ruleId, section: sectionNumber } = confirmDeleteRule;
    setConfirmDeleteRule(null);
    try { setActionLoading(true); await api.deleteRuleFromBenchmark(benchmarkId, ruleId); toast.success(`Rule ${sectionNumber} deleted`); await fetchData(); await fetchRules(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to delete rule')); }
    finally { setActionLoading(false); }
  };
  const handleBulkGenerateAll = async () => {
    try { setActionLoading(true); const result = await api.bulkGenerateCommands(benchmarkId); setSuccessMsg(result.message); await fetchData(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to start command generation')); }
    finally { setActionLoading(false); }
  };
  const handleExportBenchmarkFull = async () => {
    try { const blob = await api.exportBenchmarkFull(benchmarkId); downloadBlob(blob, `${benchmark?.name?.replace(/ /g, '_') || 'benchmark'}.auditforge.json`); }
    catch { setError('Failed to export benchmark'); }
  };
  const handleImportBenchmarkFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    try { setActionLoading(true); const result = await api.importBenchmarkFile(benchmarkId, file); setError(''); setSuccessMsg(result.message); await fetchData(); await fetchRules(); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to import benchmark file')); }
    finally { setActionLoading(false); if (benchmarkImportRef.current) benchmarkImportRef.current.value = ''; }
  };

  const expandedRuleRef = useRef<number | null>(null);
  const handleExpandRule = async (ruleId: number) => {
    if (expandedRule === ruleId) {
      setExpandedRule(null); expandedRuleRef.current = null; setRuleCommand(null);
      setCommandHistory([]); setVerificationReports([]); setShowHistory(false); setShowReports(false); setShowFlagForm(false); setShowUnlockForm(false);
      return;
    }
    setExpandedRule(ruleId); expandedRuleRef.current = ruleId; setRuleCommand(null);
    setCommandHistory([]); setVerificationReports([]); setShowHistory(false); setShowReports(false); setShowFlagForm(false); setShowUnlockForm(false);
    try {
      const cmd = await api.getRuleCommand(ruleId);
      if (expandedRuleRef.current === ruleId) setRuleCommand(cmd);
    } catch { if (expandedRuleRef.current === ruleId) setRuleCommand(null); }
  };

  const handleSaveRuleField = async (ruleId: number, field: string, value: string) => {
    if (!benchmark) return;
    try {
      const updated = await api.updateRuleFull(benchmark.id, ruleId, { [field]: value || null });
      setRules(prev => prev.map(r => r.id === ruleId ? { ...r, ...updated } : r));
    } catch (err: unknown) { setError(extractApiError(err, 'Failed to save rule')); throw err; }
  };

  const handleFlagCommand = async (ruleId: number) => {
    if (!flagReason.trim()) return;
    try { setActionLoading(true); const cmd = await api.flagCommand(ruleId, flagReason); setRuleCommand(cmd); setShowFlagForm(false); setFlagReason(''); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to flag command')); }
    finally { setActionLoading(false); }
  };
  const handleRegenerateCommand = async (ruleId: number) => {
    try { setActionLoading(true); const cmd = await api.regenerateCommand(ruleId); setRuleCommand(cmd); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to regenerate command')); }
    finally { setActionLoading(false); }
  };
  const handleProtectCommand = async (ruleId: number) => {
    try { setActionLoading(true); const cmd = await api.protectCommand(ruleId); setRuleCommand(cmd); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to protect command')); }
    finally { setActionLoading(false); }
  };
  const handleUnlockCommand = async (ruleId: number) => {
    if (!unlockReason.trim()) return;
    try { setActionLoading(true); const cmd = await api.unlockCommand(ruleId, unlockReason); setRuleCommand(cmd); setShowUnlockForm(false); setUnlockReason(''); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to unlock command')); }
    finally { setActionLoading(false); }
  };
  const handleVerifySingle = async (ruleId: number) => {
    try { setActionLoading(true); const cmd = await api.verifySingleCommand(ruleId); setRuleCommand(cmd); }
    catch (err: unknown) { setError(extractApiError(err, 'Failed to verify command')); }
    finally { setActionLoading(false); }
  };
  const handleShowHistory = async (ruleId: number) => {
    if (showHistory) { setShowHistory(false); return; }
    try { const history = await api.getCommandHistory(ruleId); setCommandHistory(history); setShowHistory(true); }
    catch { setCommandHistory([]); }
  };
  const handleShowReports = async (ruleId: number) => {
    if (showReports) { setShowReports(false); return; }
    try { const reports = await api.getCommandVerificationReports(ruleId); setVerificationReports(reports); setShowReports(true); }
    catch { setVerificationReports([]); }
  };

  // ── Loading / Not found ──
  if (loading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="flex items-center gap-4">
          <div className="h-9 w-9 rounded-lg bg-dark-overlay" />
          <div className="space-y-2">
            <div className="h-5 w-64 rounded bg-dark-overlay" />
            <div className="h-3 w-40 rounded bg-dark-overlay" />
          </div>
        </div>
        <div className="h-12 rounded-xl bg-dark-overlay" />
        <div className="h-96 rounded-xl border border-dark-border bg-dark-card" />
      </div>
    );
  }

  if (!benchmark) {
    return <div className="text-center py-12 text-red-400">Benchmark not found</div>;
  }

  const enrichPercent = enrichStatus && enrichStatus.total > 0
    ? Math.round((enrichStatus.processed / enrichStatus.total) * 100) : 0;

  // ── Tab definitions ──
  const tabs: { id: TabId; label: string; badge?: string; show: boolean }[] = [
    { id: 'rules', label: 'Rules', badge: `${benchmark.total_rules}`, show: benchmark.phase1_status === 'completed' || benchmark.source === 'custom' },
    { id: 'pipeline', label: 'Pipeline', show: true },
    { id: 'validation', label: 'Validation', badge: validationResults.length > 0 ? `${validationResults.length}` : undefined, show: benchmark.phase2_status === 'completed' },
    { id: 'coverage', label: 'Coverage', show: true },
    { id: 'copilot', label: 'Copilot', badge: pendingCopilotCount > 0 ? `${pendingCopilotCount}` : undefined, show: true },
  ];

  const visibleTabs = tabs.filter(t => t.show);

  // ══════════════════════════════════════════
  // RENDER
  // ══════════════════════════════════════════

  return (
    <div className="space-y-4">
      {/* ── Header ── */}
      <div className="flex items-center gap-4">
        <button onClick={() => navigate('/benchmarks')} className="rounded-lg p-2 hover:bg-dark-overlay">
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-semibold text-white truncate">{benchmark.name}</h2>
            {/* Version Dropdown */}
            {versions.length > 1 && (
              <div className="relative" ref={versionDropdownRef}>
                <button
                  onClick={() => setShowVersionDropdown(!showVersionDropdown)}
                  className="inline-flex items-center gap-1 rounded-lg border border-dark-border bg-dark-elevated px-2.5 py-1 text-xs font-medium text-dark-secondary hover:border-ey-yellow/50 hover:text-white transition-colors"
                >
                  <GitCompare className="h-3.5 w-3.5" />
                  v{benchmark.version}
                  <ChevronDown className={`h-3 w-3 transition-transform ${showVersionDropdown ? 'rotate-180' : ''}`} />
                </button>
                {showVersionDropdown && (
                  <div className="absolute left-0 top-full z-50 mt-1 w-72 rounded-xl border border-dark-border bg-dark-card shadow-xl">
                    <div className="border-b border-dark-border px-3 py-2">
                      <span className="text-xs font-medium text-dark-secondary">Versions ({versions.length})</span>
                    </div>
                    <div className="max-h-60 overflow-y-auto py-1">
                      {versions.map((v) => (
                        <button
                          key={v.id}
                          onClick={async () => {
                            setShowVersionDropdown(false);
                            if (v.id !== benchmarkId) {
                              try {
                                const diff = await api.getBenchmarkDiff(benchmarkId, v.id);
                                setVersionDiff(diff);
                                const badges: Record<string, 'added' | 'modified'> = {};
                                diff.added.forEach(r => { badges[r.section_number] = 'added'; });
                                diff.modified.forEach(r => { badges[r.section_number] = 'modified'; });
                                setDiffBadges(badges);
                                setShowDiffBadges(true);
                                setTimeout(() => setShowDiffBadges(false), 10000);
                              } catch { /* ignore */ }
                              navigate(`/benchmarks/${v.id}`);
                            }
                          }}
                          className={`flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-dark-elevated ${v.id === benchmarkId ? 'bg-ey-yellow/5 border-l-2 border-ey-yellow' : ''}`}
                        >
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className="text-sm font-medium text-white truncate">v{v.version}</span>
                              {v.is_baseline && <span className="rounded bg-ey-yellow/10 px-1.5 py-0.5 text-[10px] font-medium text-ey-yellow">baseline</span>}
                              {v.id === benchmarkId && <span className="rounded bg-sky-500/10 px-1.5 py-0.5 text-[10px] font-medium text-sky-400">current</span>}
                            </div>
                            <div className="text-xs text-dark-muted mt-0.5">
                              {v.total_rules} rules {'\u00b7'} {v.phase2_status}
                              {v.import_date && ` \u00b7 ${new Date(v.import_date).toLocaleDateString()}`}
                            </div>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
          <p className="text-sm text-dark-secondary">
            {benchmark.platform} {'\u00b7'} {benchmark.platform_family} {'\u00b7'} v{benchmark.version} {'\u00b7'} {benchmark.total_rules} rules
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {benchmark.is_ready && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-3 py-1 text-sm font-medium text-emerald-400">
              <CheckCircle2 className="h-4 w-4" /> Ready
            </span>
          )}
          {benchmark.source === 'nessus_reconstructed' && <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-3 py-1 text-sm font-medium text-emerald-400">Nessus Import</span>}
          {benchmark.source === 'custom' && <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/10 px-3 py-1 text-sm font-medium text-sky-400">Custom</span>}
          {benchmark.is_editable && <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-3 py-1 text-sm font-medium text-amber-400">Editable</span>}
        </div>
      </div>

      {/* Migration Readiness Bar (for reconstructed benchmarks) */}
      {benchmark.source === 'nessus_reconstructed' && benchmark.migration_readiness != null && (
        <div className="rounded-xl border border-dark-border bg-dark-card p-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-dark-secondary">Migration Readiness</h3>
            <span className={`text-sm font-bold ${benchmark.migration_readiness >= 80 ? 'text-emerald-400' : benchmark.migration_readiness >= 50 ? 'text-amber-400' : 'text-red-400'}`}>
              {benchmark.migration_readiness.toFixed(0)}%
            </span>
          </div>
          <div className="h-2.5 w-full rounded-full bg-dark-overlay overflow-hidden">
            <div className={`h-full rounded-full transition-all duration-500 ${benchmark.migration_readiness >= 80 ? 'bg-emerald-500' : benchmark.migration_readiness >= 50 ? 'bg-amber-500' : 'bg-red-500'}`}
              style={{ width: `${Math.min(100, benchmark.migration_readiness)}%` }} />
          </div>
          <p className="text-xs text-dark-muted mt-2">
            {benchmark.migration_readiness >= 80 ? 'Most rules have audit commands — ready for scanning.'
              : benchmark.migration_readiness >= 50 ? 'Some rules need enrichment before this benchmark can be used for scanning.'
                : 'Run Phase 2 enrichment to generate audit commands for imported rules.'}
          </p>
        </div>
      )}

      {/* Error / Success banners */}
      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          <button onClick={() => setError('')} className="float-right text-red-400 hover:text-red-300">{'\u00d7'}</button>
          {error}
        </div>
      )}
      {successMsg && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-400">
          <button onClick={() => setSuccessMsg('')} className="float-right text-emerald-400 hover:text-emerald-300">{'\u00d7'}</button>
          <CheckCircle2 className="mr-2 inline h-4 w-4" />{successMsg}
        </div>
      )}
      {benchmark.notes && benchmark.phase1_status === 'failed' && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          <AlertCircle className="mr-2 inline h-4 w-4" />Phase 1 Error: {benchmark.notes}
        </div>
      )}

      {/* Version Diff Banner */}
      {showDiffBadges && versionDiff && (
        <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="rounded-xl border border-sky-500/30 bg-sky-500/5 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <GitCompare className="h-5 w-5 text-sky-400" />
              <span className="text-sm font-medium text-white">Version diff: {versionDiff.base_name} → {versionDiff.compare_name}</span>
            </div>
            <button onClick={() => setShowDiffBadges(false)} className="text-dark-muted hover:text-white"><X className="h-4 w-4" /></button>
          </div>
          <div className="mt-2 flex flex-wrap gap-4 text-xs">
            <span className="text-emerald-400">{versionDiff.added.length} added</span>
            <span className="text-red-400">{versionDiff.removed.length} removed</span>
            <span className="text-amber-400">{versionDiff.modified.length} modified</span>
            <span className="text-dark-secondary">{versionDiff.unchanged_count} unchanged</span>
          </div>
          {versionDiff.removed.length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs font-medium text-red-400 hover:text-red-300">Show {versionDiff.removed.length} removed rules</summary>
              <div className="mt-2 space-y-1 max-h-40 overflow-y-auto">
                {versionDiff.removed.map((r) => (
                  <div key={r.section_number} className="flex items-center gap-2 rounded bg-red-500/5 px-2 py-1 text-xs">
                    <span className="font-mono text-dark-muted">{r.section_number}</span>
                    <span className="text-red-300">{r.title}</span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </motion.div>
      )}

      {/* ══════════════════════════════════════════
          TAB BAR
         ══════════════════════════════════════════ */}
      <div className="flex items-center gap-1 border-b border-dark-border">
        {visibleTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => {
              setActiveTab(tab.id);
              if (tab.id === 'validation' && validationResults.length === 0) fetchValidationResults();
            }}
            className={`relative px-4 py-3 text-sm font-medium transition-colors ${activeTab === tab.id ? 'text-ey-yellow' : 'text-dark-secondary hover:text-white'}`}
          >
            <span className="flex items-center gap-2">
              {tab.label}
              {tab.badge && (
                <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${activeTab === tab.id ? 'bg-ey-yellow/10 text-ey-yellow' : 'bg-dark-overlay text-dark-muted'}`}>
                  {tab.badge}
                </span>
              )}
            </span>
            {activeTab === tab.id && (
              <motion.div layoutId="benchmark-tab-indicator" className="absolute bottom-0 left-0 right-0 h-0.5 bg-ey-yellow" />
            )}
          </button>
        ))}
      </div>

      {/* ══════════════════════════════════════════
          TAB CONTENT
         ══════════════════════════════════════════ */}

      {/* ── RULES TAB ── */}
      {activeTab === 'rules' && (benchmark.phase1_status === 'completed' || benchmark.source === 'custom') && (
        <div className="space-y-4">
          {/* Sticky Action Toolbar */}
          <div className="sticky top-16 z-10 rounded-xl border border-dark-border bg-dark-card/95 backdrop-blur-sm p-3">
            <div className="flex flex-wrap items-center gap-2">
              {/* Editable actions */}
              {benchmark.is_editable && (
                <>
                  <button onClick={() => setShowAddRule(true)} disabled={showAddRule}
                    className="inline-flex items-center gap-1 rounded-md bg-ey-yellow px-3 py-1.5 text-xs font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50">
                    <Plus className="h-3 w-3" /> Add Rule
                  </button>
                  <button onClick={handleBulkGenerateAll} disabled={actionLoading || benchmark.phase2_status === 'processing'}
                    className="inline-flex items-center gap-1 rounded-md bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-700 disabled:opacity-50">
                    <Zap className="h-3 w-3" /> Generate All Commands
                  </button>
                  {/* Export dropdown */}
                  <DropdownMenu.Root>
                    <DropdownMenu.Trigger asChild>
                      <button className="inline-flex items-center gap-1 rounded-md border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-overlay hover:text-white">
                        <Download className="h-3 w-3" /> Export <ChevronDown className="h-3 w-3" />
                      </button>
                    </DropdownMenu.Trigger>
                    <DropdownMenu.Portal>
                      <DropdownMenu.Content className="z-50 min-w-[180px] rounded-xl border border-dark-border bg-dark-card p-1 shadow-xl" sideOffset={4}>
                        <DropdownMenu.Item onClick={handleExportBenchmarkFull} className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none cursor-pointer hover:bg-dark-elevated hover:text-white">
                          Export .auditforge.json
                        </DropdownMenu.Item>
                        {benchmark.phase1_status === 'completed' && benchmark.total_rules > 0 && (
                          <DropdownMenu.Item onClick={handleExportRules} className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none cursor-pointer hover:bg-dark-elevated hover:text-white">
                            Export Rules JSON
                          </DropdownMenu.Item>
                        )}
                        {benchmark.phase2_status === 'completed' && (
                          <DropdownMenu.Item onClick={handleExportCommands} className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none cursor-pointer hover:bg-dark-elevated hover:text-white">
                            Export Commands JSON
                          </DropdownMenu.Item>
                        )}
                      </DropdownMenu.Content>
                    </DropdownMenu.Portal>
                  </DropdownMenu.Root>
                  {/* Import dropdown */}
                  <DropdownMenu.Root>
                    <DropdownMenu.Trigger asChild>
                      <button className="inline-flex items-center gap-1 rounded-md border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-overlay hover:text-white">
                        <Upload className="h-3 w-3" /> Import <ChevronDown className="h-3 w-3" />
                      </button>
                    </DropdownMenu.Trigger>
                    <DropdownMenu.Portal>
                      <DropdownMenu.Content className="z-50 min-w-[180px] rounded-xl border border-dark-border bg-dark-card p-1 shadow-xl" sideOffset={4}>
                        <DropdownMenu.Item asChild>
                          <label className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none cursor-pointer hover:bg-dark-elevated hover:text-white">
                            Import .auditforge.json
                            <input ref={benchmarkImportRef} type="file" accept=".json" className="hidden" onChange={handleImportBenchmarkFile} disabled={actionLoading} />
                          </label>
                        </DropdownMenu.Item>
                        <DropdownMenu.Item asChild>
                          <label className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none cursor-pointer hover:bg-dark-elevated hover:text-white">
                            Import Rules JSON
                            <input ref={rulesImportRef} type="file" accept=".json" className="hidden" onChange={handleImportRules} disabled={actionLoading} />
                          </label>
                        </DropdownMenu.Item>
                        {benchmark.phase1_status === 'completed' && !['processing'].includes(benchmark.phase2_status) && (
                          <DropdownMenu.Item asChild>
                            <label className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none cursor-pointer hover:bg-dark-elevated hover:text-white">
                              Import Commands JSON
                              <input ref={commandsImportRef} type="file" accept=".json" className="hidden" onChange={handleImportCommands} disabled={actionLoading} />
                            </label>
                          </DropdownMenu.Item>
                        )}
                      </DropdownMenu.Content>
                    </DropdownMenu.Portal>
                  </DropdownMenu.Root>
                </>
              )}
              {/* Non-editable export (for preloaded benchmarks) */}
              {!benchmark.is_editable && (
                <div className="flex flex-wrap items-center gap-2">
                  {benchmark.phase1_status === 'completed' && benchmark.total_rules > 0 && (
                    <button onClick={handleExportRules} className="inline-flex items-center gap-1 rounded-md border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-overlay hover:text-white">
                      <Download className="h-3 w-3" /> Export Rules
                    </button>
                  )}
                  {benchmark.phase2_status === 'completed' && (
                    <button onClick={handleExportCommands} className="inline-flex items-center gap-1 rounded-md border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-overlay hover:text-white">
                      <Download className="h-3 w-3" /> Export Commands
                    </button>
                  )}
                </div>
              )}
              {/* Search + Filter (always) */}
              <div className="ml-auto flex items-center gap-2">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-dark-muted" />
                  <input type="text" value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder={`Search rules\u2026`}
                    className="rounded-lg border border-dark-border bg-dark-elevated py-1.5 pl-9 pr-3 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:outline-none focus:ring-1 focus:ring-ey-yellow/30" />
                </div>
                <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}
                  className="rounded-lg border border-dark-border bg-dark-elevated px-3 py-1.5 text-sm text-white focus:border-ey-yellow/50 focus:outline-none focus:ring-1 focus:ring-ey-yellow/30">
                  <option value="">All severities</option>
                  <option value="critical">Critical</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
                <span className="rounded bg-dark-overlay px-2 py-1 text-xs text-dark-muted">{rules.length} rules</span>
              </div>
            </div>
          </div>

          {/* Add Rule Form */}
          {showAddRule && benchmark.is_editable && (
            <RuleEditor benchmarkId={benchmarkId} onRuleCreated={handleRuleCreated} onCancel={() => setShowAddRule(false)} existingSections={rules.map(r => r.section_number)} />
          )}

          {/* Rules List */}
          <div className="rounded-xl border border-dark-border bg-dark-card">
            <div className="divide-y divide-dark-border">
              {rules.length === 0 ? (
                <div className="p-8 text-center text-dark-secondary">No rules found matching your criteria.</div>
              ) : (
                rules.map((rule) => (
                  <div key={rule.id}>
                    <button onClick={() => handleExpandRule(rule.id)}
                      className="group flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-dark-elevated min-w-0">
                      <span className="min-w-[60px] shrink-0 text-sm font-mono text-dark-secondary">{rule.section_number}</span>
                      <span className="flex-1 min-w-0 truncate text-sm font-medium text-white">{rule.title}</span>
                      <div className="flex shrink-0 flex-wrap items-center gap-1.5 max-w-[45%] justify-end">
                        {severityBadge(rule.severity)}
                        {/* Inline command status badge */}
                        {(benchmark.phase2_status === 'completed' || benchmark.source === 'custom') && (
                          commandStatusBadge(expandedRule === rule.id ? ruleCommand : undefined)
                        )}
                        {showDiffBadges && diffBadges[rule.section_number] === 'added' && (
                          <span className="animate-pulse rounded bg-emerald-500/20 px-2 py-0.5 text-[10px] font-bold text-emerald-400">NEW</span>
                        )}
                        {showDiffBadges && diffBadges[rule.section_number] === 'modified' && (
                          <span className="animate-pulse rounded bg-amber-500/20 px-2 py-0.5 text-[10px] font-bold text-amber-400">CHANGED</span>
                        )}
                        {rule.assessment_type && <span className="rounded bg-dark-overlay px-2 py-0.5 text-xs text-dark-secondary">{rule.assessment_type}</span>}
                        {rule.tags.slice(0, 3).map((t) => (
                          <span key={t.id} className="rounded bg-sky-500/10 px-2 py-0.5 text-xs text-sky-400 truncate max-w-[120px]">{t.tag_id}</span>
                        ))}
                        {rule.tags.length > 3 && <span className="rounded bg-sky-500/10 px-2 py-0.5 text-xs text-sky-400">+{rule.tags.length - 3}</span>}
                        {rule.source === 'nessus_import' && <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400">imported</span>}
                        {rule.source === 'cis_extract' && <span className="rounded bg-ey-yellow/10 px-2 py-0.5 text-[10px] font-medium text-ey-yellow">CIS</span>}
                        {rule.source === 'manual' && <span className="rounded bg-sky-500/10 px-2 py-0.5 text-[10px] font-medium text-sky-400">manual</span>}
                        {rule.source === 'imported' && <span className="rounded bg-violet-500/10 px-2 py-0.5 text-[10px] font-medium text-violet-400">imported</span>}
                      </div>
                      {benchmark.is_editable && (
                        <button onClick={(e) => { e.stopPropagation(); handleDeleteRule(rule.id, rule.section_number); }} disabled={actionLoading}
                          className="rounded p-1 text-dark-muted hover:bg-red-500/10 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity disabled:opacity-50" title="Delete rule">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {expandedRule === rule.id ? <ChevronUp className="h-4 w-4 text-dark-muted" /> : <ChevronDown className="h-4 w-4 text-dark-muted" />}
                    </button>

                    {/* Expanded Rule Detail */}
                    {expandedRule === rule.id && (
                      <div className="border-t border-dark-border bg-dark-elevated px-4 py-3 space-y-3">
                        <InlineEditField label="Title" value={rule.title} onSave={v => handleSaveRuleField(rule.id, 'title', v)} editable={benchmark?.is_editable ?? false} />
                        <InlineEditField label="Description" value={rule.description || ''} onSave={v => handleSaveRuleField(rule.id, 'description', v)} editable={benchmark?.is_editable ?? false} multiline placeholder="No description — click to add\u2026" />
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                          <InlineEditField label="Severity" value={rule.severity} onSave={v => handleSaveRuleField(rule.id, 'severity', v)} editable={benchmark?.is_editable ?? false}
                            options={[{ value: 'critical', label: 'Critical' }, { value: 'high', label: 'High' }, { value: 'medium', label: 'Medium' }, { value: 'low', label: 'Low' }]} />
                          <InlineEditField label="Profile Applicability" value={rule.profile_applicability || ''} onSave={v => handleSaveRuleField(rule.id, 'profile_applicability', v)} editable={benchmark?.is_editable ?? false} placeholder="e.g. Level 1" />
                          <InlineEditField label="Assessment Type" value={rule.assessment_type || ''} onSave={v => handleSaveRuleField(rule.id, 'assessment_type', v)} editable={benchmark?.is_editable ?? false} placeholder="e.g. Automated" />
                        </div>
                        <InlineEditField label="Rationale" value={rule.rationale || ''} onSave={v => handleSaveRuleField(rule.id, 'rationale', v)} editable={benchmark?.is_editable ?? false} multiline placeholder="No rationale — click to add\u2026" />
                        <InlineEditField label="Remediation" value={rule.remediation_description_raw || ''} onSave={v => handleSaveRuleField(rule.id, 'remediation_description_raw', v)} editable={benchmark?.is_editable ?? false} multiline placeholder="No remediation text — click to add\u2026" />
                        {benchmark?.is_editable && (
                          editingRule?.id === rule.id ? (
                            <RuleEditor benchmarkId={benchmarkId} editRule={rule} onRuleCreated={() => { }}
                              onRuleUpdated={(updated) => { setRules(prev => prev.map(r => r.id === updated.id ? { ...r, ...updated } : r)); setEditingRule(null); setSuccessMsg('Rule updated successfully'); }}
                              onCancel={() => setEditingRule(null)} />
                          ) : (
                            <button onClick={() => setEditingRule(rule)} className="inline-flex items-center gap-1.5 rounded-md border border-ey-yellow/30 bg-ey-yellow/10 px-3 py-1.5 text-xs font-medium text-ey-yellow hover:bg-ey-yellow/20 transition-colors">
                              <Pencil className="h-3 w-3" /> Edit Full Rule
                            </button>
                          )
                        )}
                        {ruleCommand && (
                          <div className="space-y-2">
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-medium text-dark-secondary">Command Status:</span>
                              {statusBadge(ruleCommand.status)}
                              {ruleCommand.is_protected && <span className="rounded bg-purple-500/10 px-2 py-0.5 text-xs text-purple-400">Protected</span>}
                              {ruleCommand.source && <span className="rounded bg-dark-overlay px-2 py-0.5 text-xs text-dark-secondary">{ruleCommand.source}</span>}
                              {ruleCommand.regeneration_count > 0 && <span className="rounded bg-sky-500/10 px-2 py-0.5 text-xs text-sky-400">Regen #{ruleCommand.regeneration_count}</span>}
                            </div>
                            {ruleCommand.audit_command && (
                              <div>
                                <span className="text-xs font-medium text-dark-secondary">Audit Command:</span>
                                <pre className="mt-1 rounded bg-gray-900 p-3 text-xs text-green-400 overflow-x-auto">{ruleCommand.audit_command}</pre>
                              </div>
                            )}
                            {ruleCommand.expected_output_description && (
                              <div>
                                <span className="text-xs font-medium text-dark-secondary">Expected Output:</span>
                                <p className="mt-1 text-sm text-gray-300">{ruleCommand.expected_output_description}</p>
                              </div>
                            )}
                            {ruleCommand.expected_output_regex && (
                              <div>
                                <span className="text-xs font-medium text-dark-secondary">Comparison Expression:</span>
                                <code className="mt-1 block rounded bg-sky-500/10 border border-sky-500/30 p-2 text-xs text-sky-400 font-semibold">{ruleCommand.expected_output_regex}</code>
                              </div>
                            )}
                            {ruleCommand.flag_reason && (
                              <div className="rounded bg-red-500/10 p-2">
                                <span className="text-xs font-medium text-red-400">Flag Reason:</span>
                                <p className="mt-1 text-sm text-red-400">{ruleCommand.flag_reason}</p>
                              </div>
                            )}
                            {/* Command Actions — Primary + Secondary dropdown */}
                            <div className="flex flex-wrap gap-2 pt-2 border-t border-dark-border">
                              {/* Primary: Flag or Regenerate */}
                              {!ruleCommand.is_protected && ruleCommand.status !== 'flagged' && (
                                <button onClick={() => setShowFlagForm(!showFlagForm)}
                                  className="inline-flex items-center gap-1 rounded-md bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-500/20">
                                  <Flag className="h-3 w-3" /> Flag
                                </button>
                              )}
                              {ruleCommand.status === 'flagged' && !ruleCommand.is_protected && (
                                <button onClick={() => handleRegenerateCommand(rule.id)} disabled={actionLoading}
                                  className="inline-flex items-center gap-1 rounded-md bg-orange-500/10 px-3 py-1.5 text-xs font-medium text-orange-400 hover:bg-orange-500/20 disabled:opacity-50">
                                  <RefreshCw className="h-3 w-3" /> Regenerate
                                </button>
                              )}
                              {/* Primary: Verify */}
                              {!ruleCommand.is_protected && (
                                <button onClick={() => handleVerifySingle(rule.id)} disabled={actionLoading}
                                  className="inline-flex items-center gap-1 rounded-md bg-purple-500/10 px-3 py-1.5 text-xs font-medium text-purple-400 hover:bg-purple-500/20 disabled:opacity-50">
                                  <ShieldCheck className="h-3 w-3" /> Verify
                                </button>
                              )}
                              {/* Primary: Live Test */}
                              {ruleCommand.audit_command && (
                                <button onClick={() => setShowTestPanel(showTestPanel === rule.id ? null : rule.id)}
                                  className="inline-flex items-center gap-1 rounded-md bg-sky-500/10 px-3 py-1.5 text-xs font-medium text-sky-400 hover:bg-sky-500/20">
                                  <Activity className="h-3 w-3" /> {showTestPanel === rule.id ? 'Hide' : 'Live'} Test
                                </button>
                              )}
                              {/* Secondary: dropdown */}
                              <DropdownMenu.Root>
                                <DropdownMenu.Trigger asChild>
                                  <button className="inline-flex items-center gap-1 rounded-md bg-dark-elevated px-2.5 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-overlay">
                                    <MoreHorizontal className="h-3.5 w-3.5" />
                                  </button>
                                </DropdownMenu.Trigger>
                                <DropdownMenu.Portal>
                                  <DropdownMenu.Content className="z-50 min-w-[160px] rounded-xl border border-dark-border bg-dark-card p-1 shadow-xl" sideOffset={4}>
                                    {!ruleCommand.is_protected && ['verified', 'generated'].includes(ruleCommand.status) && (
                                      <DropdownMenu.Item onClick={() => handleProtectCommand(rule.id)}
                                        className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none cursor-pointer hover:bg-dark-elevated hover:text-white">
                                        <Lock className="h-3.5 w-3.5" /> Protect
                                      </DropdownMenu.Item>
                                    )}
                                    {ruleCommand.is_protected && (
                                      <DropdownMenu.Item onClick={() => setShowUnlockForm(!showUnlockForm)}
                                        className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none cursor-pointer hover:bg-dark-elevated hover:text-white">
                                        <Unlock className="h-3.5 w-3.5" /> Unlock
                                      </DropdownMenu.Item>
                                    )}
                                    <DropdownMenu.Item onClick={() => handleShowHistory(rule.id)}
                                      className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none cursor-pointer hover:bg-dark-elevated hover:text-white">
                                      <History className="h-3.5 w-3.5" /> {showHistory ? 'Hide' : 'Show'} History
                                    </DropdownMenu.Item>
                                    <DropdownMenu.Item onClick={() => handleShowReports(rule.id)}
                                      className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none cursor-pointer hover:bg-dark-elevated hover:text-white">
                                      <ShieldOff className="h-3.5 w-3.5" /> {showReports ? 'Hide' : 'Show'} Reports
                                    </DropdownMenu.Item>
                                  </DropdownMenu.Content>
                                </DropdownMenu.Portal>
                              </DropdownMenu.Root>
                            </div>

                            {/* Flag Form */}
                            {showFlagForm && (
                              <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 space-y-2">
                                <label className="block text-xs font-medium text-red-400">Flag Reason:</label>
                                <textarea value={flagReason} onChange={(e) => setFlagReason(e.target.value)}
                                  placeholder="Describe why this command is broken\u2026"
                                  className="w-full rounded border border-red-500/30 bg-dark-elevated p-2 text-sm text-white placeholder-dark-muted focus:border-red-500/50 focus:outline-none focus:ring-1 focus:ring-red-500/30" rows={2} />
                                <div className="flex gap-2">
                                  <button onClick={() => handleFlagCommand(rule.id)} disabled={actionLoading || !flagReason.trim()}
                                    className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50">Submit Flag</button>
                                  <button onClick={() => { setShowFlagForm(false); setFlagReason(''); }}
                                    className="rounded-md bg-dark-overlay px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-border">Cancel</button>
                                </div>
                              </div>
                            )}
                            {/* Unlock Form */}
                            {showUnlockForm && (
                              <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 space-y-2">
                                <label className="block text-xs font-medium text-amber-400">Unlock Reason:</label>
                                <textarea value={unlockReason} onChange={(e) => setUnlockReason(e.target.value)}
                                  placeholder="Explain why you are unlocking this protected command\u2026"
                                  className="w-full rounded border border-amber-500/30 bg-dark-elevated p-2 text-sm text-white placeholder-dark-muted focus:border-amber-500/50 focus:outline-none focus:ring-1 focus:ring-amber-500/30" rows={2} />
                                <div className="flex gap-2">
                                  <button onClick={() => handleUnlockCommand(rule.id)} disabled={actionLoading || !unlockReason.trim()}
                                    className="rounded-md bg-yellow-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-yellow-700 disabled:opacity-50">Confirm Unlock</button>
                                  <button onClick={() => { setShowUnlockForm(false); setUnlockReason(''); }}
                                    className="rounded-md bg-dark-overlay px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-border">Cancel</button>
                                </div>
                              </div>
                            )}
                            {/* Command History */}
                            {showHistory && (
                              <div className="rounded-xl border border-dark-border bg-dark-card p-3 space-y-2">
                                <h4 className="text-xs font-medium text-gray-300">Command History ({commandHistory.length} entries)</h4>
                                {commandHistory.length === 0 ? <p className="text-xs text-dark-muted">No previous command versions.</p> : (
                                  commandHistory.map((entry, idx) => (
                                    <div key={idx} className="rounded border border-dark-border bg-dark-elevated p-2 space-y-1">
                                      <div className="flex items-center gap-2 text-xs text-dark-secondary">
                                        <span>Attempt #{idx + 1}</span>
                                        {entry.source && <span className="rounded bg-dark-overlay px-1.5 py-0.5">{entry.source}</span>}
                                        {entry.timestamp && <span>{new Date(entry.timestamp).toLocaleString()}</span>}
                                      </div>
                                      {entry.audit_command && <pre className="rounded bg-gray-900 p-2 text-xs text-green-400 overflow-x-auto">{entry.audit_command}</pre>}
                                      {entry.flag_reason && <p className="text-xs text-red-400">Flag: {entry.flag_reason}</p>}
                                    </div>
                                  ))
                                )}
                              </div>
                            )}
                            {/* Verification Reports */}
                            {showReports && (
                              <div className="rounded-xl border border-dark-border bg-dark-card p-3 space-y-2">
                                <h4 className="text-xs font-medium text-gray-300">Verification Reports ({verificationReports.length})</h4>
                                {verificationReports.length === 0 ? <p className="text-xs text-dark-muted">No verification reports yet. Run verification first.</p> : (
                                  verificationReports.map((report) => (
                                    <div key={report.id} className="flex items-center gap-2 rounded border border-dark-border bg-dark-elevated p-2">
                                      <span className="min-w-[90px] text-xs font-mono text-dark-secondary">{report.level}</span>
                                      {verificationResultBadge(report.result)}
                                      <span className="flex-1 text-xs text-gray-300">{report.message}</span>
                                      {report.auto_fixable && <span className="rounded bg-sky-500/10 px-1.5 py-0.5 text-xs text-sky-400">auto-fixable</span>}
                                    </div>
                                  ))
                                )}
                              </div>
                            )}
                            {/* Live Test Panel */}
                            {showTestPanel === rule.id && (
                              <RuleTestPanel benchmarkId={benchmarkId} ruleId={rule.id} sectionNumber={rule.section_number}
                                hasCommand={!!ruleCommand?.audit_command} onValidated={() => { fetchData(); fetchRules(); }} />
                            )}
                          </div>
                        )}
                        {!ruleCommand && benchmark.phase2_status !== 'completed' && (
                          <p className="text-sm text-dark-muted italic">No audit command generated yet. Run Phase 2 enrichment to generate commands.</p>
                        )}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── PIPELINE TAB ── */}
      {activeTab === 'pipeline' && (
        <div className="space-y-6">
          <h3 className="text-lg font-semibold text-white">Enrichment Pipeline</h3>
          {/* Horizontal stepper */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Phase 1: Parse */}
            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium text-gray-300">Phase 1: Parse</h4>
                {statusBadge(benchmark.phase1_status)}
              </div>
              <p className="mt-2 text-2xl font-bold text-white">{benchmark.total_rules} <span className="text-sm font-normal text-dark-secondary">rules</span></p>
              <div className="mt-3 flex flex-wrap gap-2">
                {benchmark.phase1_status === 'completed' && benchmark.total_rules > 0 && (
                  <button onClick={handleExportRules} className="inline-flex items-center gap-1 rounded-md border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-overlay hover:text-white">
                    <Download className="h-3 w-3" /> Export
                  </button>
                )}
                <label className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-overlay hover:text-white">
                  <Upload className="h-3 w-3" /> Import
                  <input ref={rulesImportRef} type="file" accept=".json" className="hidden" onChange={handleImportRules} disabled={actionLoading} />
                </label>
              </div>
            </div>

            {/* Phase 2: Enrich */}
            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium text-gray-300">Phase 2: Enrich</h4>
                {statusBadge(enrichStatus?.status || benchmark.phase2_status)}
              </div>
              {enrichStatus && enrichStatus.total > 0 && (
                <>
                  <p className="mt-2 text-2xl font-bold text-white">{enrichStatus.processed}<span className="text-xl text-dark-secondary">/{enrichStatus.total}</span></p>
                  {enrichStatus.status === 'processing' && <p className="text-xs text-ey-yellow/80 mt-1 mb-2 font-medium">Processing rule {enrichStatus.processed} of {enrichStatus.total}{'\u2026'}</p>}
                  <div className="mt-2 h-2 w-full rounded-full bg-dark-overlay overflow-hidden">
                    <div className="h-full rounded-full bg-ey-yellow transition-all duration-300 relative overflow-hidden" style={{ width: `${enrichPercent}%` }}>
                      {enrichStatus.status === 'processing' && <div className="absolute inset-0 bg-white/20 animate-pulse" />}
                    </div>
                  </div>
                </>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                {benchmark.phase1_status === 'completed' && !['processing'].includes(benchmark.phase2_status) && benchmark.phase2_status !== 'completed' && (
                  <button onClick={handleEnrich} className="inline-flex items-center gap-1 rounded-md bg-ey-yellow px-3 py-1.5 text-xs font-medium text-black hover:bg-ey-yellow-hover">
                    <Play className="h-3 w-3" /> {benchmark.phase2_status === 'paused' ? 'Resume' : 'Start'}
                  </button>
                )}
                {benchmark.phase2_status === 'processing' && (
                  <button onClick={handlePauseEnrich} className="inline-flex items-center gap-1 rounded-md bg-yellow-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-yellow-700">
                    <Pause className="h-3 w-3" /> Pause
                  </button>
                )}
                {benchmark.phase2_status === 'completed' && (
                  <button onClick={handleExportCommands} className="inline-flex items-center gap-1 rounded-md border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-overlay hover:text-white">
                    <Download className="h-3 w-3" /> Export
                  </button>
                )}
              </div>
            </div>

            {/* Verification */}
            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium text-gray-300">Verify</h4>
                {statusBadge(verifyStatus?.status || benchmark.verification_status)}
              </div>
              {verifyStatus && verifyStatus.total > 0 && (
                <div className="mt-2 flex gap-4">
                  <div><span className="text-2xl font-bold text-emerald-400">{verifyStatus.passed}</span><span className="text-sm text-dark-secondary"> pass</span></div>
                  <div><span className="text-2xl font-bold text-red-400">{verifyStatus.failed}</span><span className="text-sm text-dark-secondary"> fail</span></div>
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                {benchmark.phase2_status === 'completed' && !['processing'].includes(benchmark.verification_status) && (
                  <button onClick={handleVerify} className="inline-flex items-center gap-1.5 rounded-md bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-700">
                    <img src={logoImg} alt="" className="h-3 w-3 object-contain invert brightness-0" />
                    {['completed', 'completed_with_issues', 'overridden'].includes(benchmark.verification_status) ? 'Re-run' : 'Run'}
                  </button>
                )}
                {verifyStatus && verifyStatus.failed > 0 && (
                  <button onClick={handleBulkRegenerate} disabled={actionLoading} className="inline-flex items-center gap-1 rounded-md bg-orange-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-orange-700 disabled:opacity-50">
                    <RefreshCw className="h-3 w-3" /> Regen
                  </button>
                )}
                {['completed', 'completed_with_issues'].includes(benchmark.verification_status) && (
                  <button onClick={handleBulkAccept} disabled={actionLoading} className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
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

            {/* Phase 3: Validate & Correct */}
            <div className={`rounded-xl border p-4 ${benchmark.phase2_status === 'completed' ? 'border-amber-500/30 bg-amber-500/10' : 'border-dark-border bg-dark-card opacity-50'}`}>
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium text-gray-300"><Sparkles className="mr-1 inline h-3.5 w-3.5 text-amber-400" />Validate</h4>
                {validateStatus && validateStatus.status !== 'not_started' ? statusBadge(validateStatus.status) :
                  <span className="rounded-full bg-dark-overlay px-2.5 py-0.5 text-xs font-medium text-dark-secondary">optional</span>}
              </div>
              {validateStatus && validateStatus.total > 0 && (
                <>
                  <div className="mt-2 flex flex-wrap gap-3">
                    <div><span className="text-lg font-bold text-emerald-400">{validateStatus.validated}</span><span className="text-xs text-dark-secondary"> ok</span></div>
                    <div><span className="text-lg font-bold text-amber-400">{validateStatus.corrected}</span><span className="text-xs text-dark-secondary"> fixed</span></div>
                    <div><span className="text-lg font-bold text-red-400">{validateStatus.flagged}</span><span className="text-xs text-dark-secondary"> flagged</span></div>
                  </div>
                  {validateStatus.status === 'processing' && validateStatus.total > 0 && (
                    <div className="mt-2 h-2 w-full rounded-full bg-dark-overlay">
                      <div className="h-2 rounded-full bg-amber-500 transition-all" style={{ width: `${Math.round((validateStatus.processed / validateStatus.total) * 100)}%` }} />
                    </div>
                  )}
                </>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                {benchmark.phase2_status === 'completed' && benchmark.phase3_status !== 'processing' && (
                  <button onClick={handleStartValidation} className="inline-flex items-center gap-1 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700">
                    <Sparkles className="h-3 w-3" /> {benchmark.phase3_status === 'paused' ? 'Resume' : benchmark.phase3_status === 'completed' ? 'Re-run' : 'Run'}
                  </button>
                )}
                {benchmark.phase3_status === 'processing' && (
                  <button onClick={handlePauseValidation} className="inline-flex items-center gap-1 rounded-md bg-yellow-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-yellow-700">
                    <Pause className="h-3 w-3" /> Pause
                  </button>
                )}
                {validateStatus && validateStatus.corrected > 0 && (
                  <button onClick={handleBulkApplyCorrections} disabled={actionLoading} className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
                    <Check className="h-3 w-3" /> Apply All
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Cache Acceleration Stats */}
          {cacheStats && cacheStats.cache_hits > 0 && (
            <div className="rounded-xl border border-dark-border bg-dark-card p-4">
              <div className="flex items-center gap-2 mb-3">
                <Database className="h-4 w-4 text-ey-yellow" />
                <h4 className="text-sm font-medium text-white">Command Cache Acceleration</h4>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="rounded-lg bg-dark-elevated p-3"><div className="text-lg font-bold text-emerald-400">{cacheStats.auto_imported}</div><div className="text-xs text-dark-muted">Auto-imported</div></div>
                <div className="rounded-lg bg-dark-elevated p-3"><div className="text-lg font-bold text-amber-400">{cacheStats.flagged_for_review}</div><div className="text-xs text-dark-muted">Flagged for review</div></div>
                <div className="rounded-lg bg-dark-elevated p-3"><div className="text-lg font-bold text-sky-400">{cacheStats.remaining_for_llm}</div><div className="text-xs text-dark-muted">Sent to LLM</div></div>
                <div className="rounded-lg bg-dark-elevated p-3"><div className="text-lg font-bold text-ey-yellow">{cacheStats.coverage_percent}%</div><div className="text-xs text-dark-muted">Cache coverage</div></div>
              </div>
            </div>
          )}

          {/* AI Severity Classification — only for custom benchmarks */}
          {benchmark.source === 'custom' && mediumRuleCount > 0 && benchmark.phase1_status === 'completed' && benchmark.phase2_status !== 'processing' && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-medium text-white"><Sparkles className="mr-1.5 inline h-4 w-4 text-amber-400" />AI Severity Classification</h4>
                  <p className="text-xs text-dark-secondary mt-1">{mediumRuleCount} rules still have default "medium" severity</p>
                </div>
                <button onClick={handleClassifySeverities} disabled={sevLoading}
                  className="inline-flex items-center gap-1.5 rounded-md bg-amber-600 px-4 py-2 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50">
                  <Sparkles className="h-3.5 w-3.5" /> {sevLoading ? 'Classifying\u2026' : 'Classify with AI'}
                </button>
              </div>
            </div>
          )}

          {/* Migration Readiness Dashboard */}
          <div className="rounded-xl border border-sky-500/30 bg-dark-card overflow-hidden">
            <div className="border-b border-sky-500/20 bg-sky-500/5 p-4">
              <div className="flex items-center gap-2">
                <BarChart3 className="h-5 w-5 text-sky-400" />
                <h3 className="text-lg font-medium text-white">Migration Readiness</h3>
                <button onClick={() => { setReadinessLoading(true); api.getMigrationReadiness(benchmarkId).then(setMigrationReadiness).catch(() => { }).finally(() => setReadinessLoading(false)); }}
                  disabled={readinessLoading}
                  className="ml-auto rounded-md border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs text-gray-300 hover:bg-dark-overlay hover:text-white disabled:opacity-50">
                  <RefreshCw className={`h-3 w-3${readinessLoading ? ' animate-spin' : ''}`} />
                </button>
              </div>
            </div>
            {migrationReadiness ? (
              <div className="p-5 space-y-4">
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm text-dark-secondary">Overall Readiness</span>
                    <div className="flex items-center gap-2">
                      <span className={`text-2xl font-bold ${migrationReadiness.readiness_percentage >= 95 ? 'text-emerald-400' : migrationReadiness.readiness_percentage >= 50 ? 'text-amber-400' : 'text-red-400'}`}>
                        {migrationReadiness.readiness_percentage.toFixed(1)}%
                      </span>
                      <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${migrationReadiness.status === 'ready' ? 'bg-emerald-500/10 text-emerald-400' : migrationReadiness.status === 'partial' ? 'bg-amber-500/10 text-amber-400' : 'bg-red-500/10 text-red-400'}`}>
                        {migrationReadiness.status}
                      </span>
                    </div>
                  </div>
                  <div className="h-3 w-full rounded-full bg-dark-overlay overflow-hidden">
                    <div className={`h-full rounded-full transition-all duration-700 ${migrationReadiness.readiness_percentage >= 95 ? 'bg-emerald-500' : migrationReadiness.readiness_percentage >= 50 ? 'bg-amber-500' : 'bg-red-500'}`}
                      style={{ width: `${Math.min(100, migrationReadiness.readiness_percentage)}%` }} />
                  </div>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                  <div className="rounded-lg border border-dark-border bg-dark-elevated p-3 text-center"><div className="text-2xl font-bold text-white">{migrationReadiness.total_rules}</div><div className="text-xs text-dark-secondary mt-1">Total Rules</div></div>
                  <div className="rounded-lg border border-dark-border bg-dark-elevated p-3 text-center"><div className="text-2xl font-bold text-sky-400">{migrationReadiness.rules_with_commands}</div><div className="text-xs text-dark-secondary mt-1">With Commands</div></div>
                  <div className="rounded-lg border border-dark-border bg-dark-elevated p-3 text-center"><div className="text-2xl font-bold text-emerald-400">{migrationReadiness.rules_validated}</div><div className="text-xs text-dark-secondary mt-1">Validated</div></div>
                  <div className="rounded-lg border border-dark-border bg-dark-elevated p-3 text-center"><div className="text-2xl font-bold text-purple-400">{migrationReadiness.rules_generated}</div><div className="text-xs text-dark-secondary mt-1">AI Generated</div></div>
                  <div className="rounded-lg border border-dark-border bg-dark-elevated p-3 text-center"><div className="text-2xl font-bold text-dark-muted">{migrationReadiness.rules_no_command}</div><div className="text-xs text-dark-secondary mt-1">No Command</div></div>
                  <div className="rounded-lg border border-dark-border bg-dark-elevated p-3 text-center"><div className="text-2xl font-bold text-red-400">{migrationReadiness.rules_flagged}</div><div className="text-xs text-dark-secondary mt-1">Flagged</div></div>
                </div>
                <p className="text-xs text-dark-muted">
                  {migrationReadiness.status === 'ready' ? 'This benchmark is fully ready for production scanning.'
                    : migrationReadiness.status === 'partial' ? 'Some rules still need audit commands or validation.'
                      : 'Most rules lack audit commands. Run Phase 2 enrichment first.'}
                </p>
              </div>
            ) : (
              <div className="p-8 text-center text-dark-secondary"><p className="text-sm">Loading readiness data{'\u2026'}</p></div>
            )}
          </div>
        </div>
      )}

      {/* ── VALIDATION TAB ── */}
      {activeTab === 'validation' && benchmark.phase2_status === 'completed' && (
        <div className="space-y-4">
          <div className="rounded-xl border border-amber-500/30 bg-dark-card">
            <div className="border-b border-amber-500/30 bg-amber-500/5 p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-medium text-white">
                  <Sparkles className="mr-2 inline h-4 w-4 text-amber-400" />Validation Results ({validationResults.length})
                </h3>
                <div className="flex items-center gap-2">
                  <select value={validationFilter} onChange={(e) => setValidationFilter(e.target.value)}
                    className="rounded-lg border border-dark-border bg-dark-elevated px-3 py-1.5 text-sm text-white focus:border-amber-500/50 focus:outline-none focus:ring-1 focus:ring-amber-500/30">
                    <option value="">All statuses</option>
                    <option value="corrected">Corrected</option>
                    <option value="flagged">Flagged</option>
                    <option value="validated">Validated</option>
                  </select>
                  <button onClick={fetchValidationResults} className="rounded-md border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs text-gray-300 hover:bg-dark-overlay hover:text-white">
                    <RefreshCw className="h-3 w-3" />
                  </button>
                  <button onClick={handleBulkDismissCorrections} disabled={actionLoading}
                    className="inline-flex items-center gap-1 rounded-md bg-dark-overlay px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-dark-border disabled:opacity-50">
                    <X className="h-3 w-3" /> Dismiss All
                  </button>
                </div>
              </div>
            </div>
            <div className="divide-y divide-dark-border">
              {validationResults.map((item) => (
                <div key={item.rule_command_id} className="px-4 py-3 space-y-2">
                  <div className="flex items-center gap-3">
                    <span className="min-w-[60px] text-sm font-mono text-dark-secondary">{item.section_number}</span>
                    <span className="flex-1 text-sm font-medium text-white">{item.title}</span>
                    {statusBadge(item.validation_status || 'pending')}
                    {item.validation_confidence && (
                      <span className={`rounded px-2 py-0.5 text-xs font-medium ${item.validation_confidence === 'high' ? 'bg-emerald-500/10 text-emerald-400' : item.validation_confidence === 'medium' ? 'bg-amber-500/10 text-amber-400' : 'bg-red-500/10 text-red-400'}`}>
                        {item.validation_confidence}
                      </span>
                    )}
                  </div>
                  {item.notes && <p className="text-xs text-dark-secondary italic">{item.notes}</p>}
                  {item.corrections.length > 0 && (
                    <div className="space-y-1.5">
                      {item.corrections.map((corr, idx) => (
                        <div key={idx} className="rounded border border-amber-500/30 bg-amber-500/10 p-2">
                          <div className="text-xs font-medium text-amber-400 mb-1">{corr.field}</div>
                          <div className="grid grid-cols-2 gap-2 text-xs">
                            <div><span className="text-dark-secondary">Before: </span><code className="rounded bg-red-500/10 px-1 py-0.5 text-red-400">{corr.old_value || '(empty)'}</code></div>
                            <div><span className="text-dark-secondary">After: </span><code className="rounded bg-emerald-500/10 px-1 py-0.5 text-emerald-400">{corr.new_value}</code></div>
                          </div>
                          {corr.reason && <p className="mt-1 text-xs text-dark-secondary">{corr.reason}</p>}
                        </div>
                      ))}
                    </div>
                  )}
                  {item.validation_status === 'corrected' && (
                    <div className="flex gap-2 pt-1">
                      <button onClick={() => handleApplyCorrection(item.rule_command_id)} disabled={actionLoading}
                        className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
                        <Check className="h-3 w-3" /> Apply
                      </button>
                      <button onClick={() => handleDismissCorrection(item.rule_command_id)} disabled={actionLoading}
                        className="inline-flex items-center gap-1 rounded-md bg-dark-overlay px-3 py-1 text-xs font-medium text-gray-300 hover:bg-dark-border disabled:opacity-50">
                        <X className="h-3 w-3" /> Dismiss
                      </button>
                    </div>
                  )}
                  {item.validation_status === 'flagged' && (
                    <div className="flex gap-2 pt-1">
                      <button onClick={() => handleDismissCorrection(item.rule_command_id)} disabled={actionLoading}
                        className="inline-flex items-center gap-1 rounded-md bg-dark-overlay px-3 py-1 text-xs font-medium text-gray-300 hover:bg-dark-border disabled:opacity-50">
                        <X className="h-3 w-3" /> Dismiss
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── COVERAGE TAB ── */}
      {activeTab === 'coverage' && benchmark && (
        <div className="space-y-6">
          <FrameworkCoveragePanel benchmarkId={benchmark.id} benchmarkName={benchmark.name} />

          {/* How Rule Testing Works */}
          <div className="rounded-xl border border-dark-border bg-dark-card p-5">
            <h3 className="text-sm font-semibold text-white mb-3">How Rule Testing Works</h3>
            <ol className="list-decimal list-inside space-y-2 text-sm text-dark-secondary">
              <li>Go to the <button onClick={() => setActiveTab('rules')} className="text-sky-400 hover:underline">Rules</button> tab and expand any rule.</li>
              <li>Click the <span className="text-sky-400 font-medium">Live Test</span> button to open the test panel.</li>
              <li>Select a target machine and click <span className="text-sky-400 font-medium">Run Test</span> to execute the audit command.</li>
              <li>Review the output and <span className="text-emerald-400 font-medium">Approve</span>, <span className="text-amber-400 font-medium">Correct</span>, or <span className="text-red-400 font-medium">Flag</span> the command.</li>
              <li>Validated commands increase the migration readiness percentage.</li>
            </ol>
          </div>
        </div>
      )}

      {activeTab === 'copilot' && benchmark && (
        <CopilotPanel
          benchmarkId={benchmark.id}
          benchmarkName={benchmark.name}
          platform={benchmark.platform}
          platformFamily={benchmark.platform_family}
          onRulesChanged={() => { fetchRules(); fetchData(); }}
          phase1Status={benchmark.phase1_status}
          enrichStatus={enrichStatus}
          verifyStatus={verifyStatus}
          validateStatus={validateStatus}
        />
      )}

      {/* Delete Rule Confirm */}
      <ConfirmDialog
        open={!!confirmDeleteRule}
        title="Delete Rule"
        message={`Delete rule ${confirmDeleteRule?.section ?? ''}? This cannot be undone.`}
        variant="danger"
        confirmLabel="Delete"
        onConfirm={confirmDeleteRuleAction}
        onCancel={() => setConfirmDeleteRule(null)}
      />
    </div>
  );
}
