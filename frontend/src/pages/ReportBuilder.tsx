import { useEffect, useMemo, useState, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import {
  Search,
  Download,
  Eye,
  FileText,
  FileSpreadsheet,
  FileCode2,
  Globe,
  Loader2,
  ShieldCheck,
  ShieldX,
  ShieldAlert,
  Filter,
  ListChecks,
  ListX,
  RotateCcw,
  Sparkles,
  FolderPlus,
  Trash2,
  Pencil,
  Users,
  RefreshCw,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Plus,
  LayoutGrid,
  List,
  CheckCircle2,
  SlidersHorizontal,
  BarChart3,
  Layers,
  ToggleLeft,
  ToggleRight,
  Zap,
} from 'lucide-react';
import type { ScanDetail, BuilderFinding, ReportGenerateRequest, RuleGroup } from '@/types';
import * as api from '@/services/api';
import RulePill from '@/components/report/RulePill';

interface ReportBuilderProps {
  missionId?: number;
  missionName?: string;
}

/* ─── Constants ───────────────────────────────────────────────── */

const SEV_COLORS: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  high: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  low: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  informational: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
};

const SEV_DOT: Record<string, string> = {
  critical: 'bg-red-400',
  high: 'bg-orange-400',
  medium: 'bg-yellow-400',
  low: 'bg-blue-400',
  informational: 'bg-gray-400',
};

const SEV_ORDER = ['critical', 'high', 'medium', 'low', 'informational'];

const STATUS_ICONS: Record<string, typeof ShieldCheck> = { PASS: ShieldCheck, FAIL: ShieldX };
const STATUS_COLORS: Record<string, string> = { PASS: 'text-emerald-400', FAIL: 'text-red-400' };

const FORMATS = [
  { value: 'pdf', label: 'PDF', icon: FileText, desc: 'Professional PDF with charts & badges' },
  { value: 'html', label: 'HTML', icon: Globe, desc: 'Interactive dashboard with live search' },
  { value: 'excel', label: 'Excel', icon: FileSpreadsheet, desc: 'Multi-sheet workbook with filters' },
  { value: 'csv', label: 'CSV', icon: FileCode2, desc: 'Flat data for further processing' },
] as const;

const FILE_EXT: Record<string, string> = { pdf: 'pdf', excel: 'xlsx', csv: 'csv', html: 'html' };
const MIME: Record<string, string> = {
  pdf: 'application/pdf',
  excel: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  csv: 'text/csv',
  html: 'text/html',
};

const AUDIENCES = [
  { value: 'executive', label: 'Executive', icon: '📊', desc: 'Summaries, charts, business impact & top recommendations — no raw findings', secs: { executive_summary: true, charts: true, business_impact: true, findings_register: false, findings_detail: false, recommendations: true, device_profiles: false, audit_scope: true, categories: false, per_target: false, methodology: false, false_positives: false } },
  { value: 'technical', label: 'Technical', icon: '🔧', desc: 'Everything — device profiles, methodology, FP analysis, all findings', secs: { executive_summary: true, charts: true, business_impact: false, findings_register: true, findings_detail: true, recommendations: true, device_profiles: true, audit_scope: true, categories: true, per_target: true, methodology: true, false_positives: true } },
  { value: 'compliance', label: 'Compliance', icon: '📋', desc: 'All controls & evidence — categories, per-target, methodology, no device profiles', secs: { executive_summary: true, charts: true, business_impact: false, findings_register: true, findings_detail: true, recommendations: true, device_profiles: false, audit_scope: true, categories: true, per_target: true, methodology: true, false_positives: true } },
] as const;

const REPORT_PRESETS = [
  { id: 'exec', label: 'Executive Board', icon: '👔', desc: 'Summaries, charts & top critical/high risks only', audience: 'executive', format: 'pdf', includePassed: false, aiSummary: true, severityFilter: 'critical,high' },
  { id: 'tech', label: 'Technical Deep-Dive', icon: '💻', desc: 'Everything — all severities, full detail, device profiles', audience: 'technical', format: 'html', includePassed: true, aiSummary: false, severityFilter: 'all' },
  { id: 'comp', label: 'Compliance Audit', icon: '📋', desc: 'Full evidence for every control — all severities', audience: 'compliance', format: 'pdf', includePassed: true, aiSummary: true, severityFilter: 'all' },
] as const;

/* Section toggle groups — used by the Customize tab to render grouped toggles */
const SEC_GROUPS: { label: string; icon: string; keys: string[] }[] = [
  { label: 'Core', icon: '📊', keys: ['executive_summary', 'charts', 'audit_scope'] },
  { label: 'Findings', icon: '📝', keys: ['findings_register', 'findings_detail', 'recommendations'] },
  { label: 'Analysis', icon: '🔍', keys: ['business_impact', 'false_positives', 'per_target'] },
  { label: 'Technical', icon: '🔧', keys: ['device_profiles', 'categories', 'methodology'] },
];

const SEC_LABELS: Record<string, string> = {
  executive_summary: 'Executive Summary',
  charts: 'Charts & Diagrams',
  business_impact: 'Business Impact Analysis',
  findings_register: 'Findings Register',
  findings_detail: 'Detailed Findings',
  recommendations: 'Recommendations',
  device_profiles: 'Device Profiles & Ports',
  audit_scope: 'Audit Scope',
  categories: 'Rule Categories',
  per_target: 'Per-Target Breakdown',
  methodology: 'Audit Methodology',
  false_positives: 'False Positive Analysis',
};

const QUICK_FILTERS = [
  { id: 'all', label: 'All Rules', icon: ListChecks, sev: 'all', status: 'all' },
  { id: 'fail', label: 'Failures Only', icon: ShieldX, sev: 'all', status: 'FAIL' },
  { id: 'critical-high', label: 'Critical + High', icon: ShieldAlert, sev: 'critical,high', status: 'all' },
  { id: 'action', label: 'Action Required', icon: Zap, sev: 'critical,high', status: 'FAIL' },
] as const;

type WorkspaceTab = 'rules' | 'organize' | 'customize';
type ScanViewMode = 'card' | 'list';

const TABS: { id: WorkspaceTab; label: string; icon: typeof Filter }[] = [
  { id: 'rules', label: 'Rules', icon: Filter },
  { id: 'organize', label: 'Organize', icon: Layers },
  { id: 'customize', label: 'Customize', icon: SlidersHorizontal },
];

/* ─── Component ───────────────────────────────────────────────── */

export default function ReportBuilder({ missionId: propMissionId, missionName: propMissionName }: ReportBuilderProps = {}) {
  const location = useLocation();
  const locState = location.state as { missionId?: number; missionName?: string } | null;
  const initialMissionId = propMissionId ?? locState?.missionId;
  const initialMissionName = propMissionName ?? locState?.missionName;
  const [scopedMissionId, setScopedMissionId] = useState<number | undefined>(initialMissionId);
  const [scopedMissionName, setScopedMissionName] = useState<string | undefined>(initialMissionName);

  /* ── Scan State ───────────────────────────────────────────── */
  const [scans, setScans] = useState<ScanDetail[]>([]);
  const [loadingScans, setLoadingScans] = useState(true);
  const [selectedScanIds, setSelectedScanIds] = useState<number[]>([]);
  const [scanView, setScanView] = useState<ScanViewMode>('card');

  /* ── Rules & Findings ─────────────────────────────────────── */
  const [findings, setFindings] = useState<BuilderFinding[]>([]);
  const [excludedRuleIds, setExcludedRuleIds] = useState<Set<number>>(new Set());
  const [loadingFindings, setLoadingFindings] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [quickFilter, setQuickFilter] = useState<string>('all');

  /* ── Groups ───────────────────────────────────────────────── */
  const [groups, setGroups] = useState<RuleGroup[]>([]);
  const [loadingAutoGroup, setLoadingAutoGroup] = useState(false);
  const [editingGroupIdx, setEditingGroupIdx] = useState<number | null>(null);
  const [editingGroupName, setEditingGroupName] = useState('');
  const [collapsedGroups, setCollapsedGroups] = useState<Set<number>>(new Set());
  const [dragState, setDragState] = useState<{ ruleId: number; fromGroup: number } | null>(null);

  /* ── Audience & AI ────────────────────────────────────────── */
  const [audience, setAudience] = useState('technical');
  const [sections, setSections] = useState<Record<string, boolean>>({
    executive_summary: true, charts: true, business_impact: false, findings_register: true,
    findings_detail: true, recommendations: true, device_profiles: true, audit_scope: true,
    categories: true, per_target: true, methodology: true, false_positives: true,
  });
  const [groupSummaries, setGroupSummaries] = useState<Record<string, string>>({});
  const [loadingSummaryFor, setLoadingSummaryFor] = useState<string | null>(null);
  const [includeAiSummary, setIncludeAiSummary] = useState(false);
  const [previewingSummary, setPreviewingSummary] = useState(false);
  const [aiSummaryPreview, setAiSummaryPreview] = useState('');

  /* ── Workspace & Export ───────────────────────────────────── */
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('rules');
  const [previewHtml, setPreviewHtml] = useState('');
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [exportFormat, setExportFormat] = useState('pdf');
  const [exporting, setExporting] = useState(false);
  const [customTitle, setCustomTitle] = useState('');
  const [includePassedRules, setIncludePassedRules] = useState(true);

  /* ── Feedback ─────────────────────────────────────────────── */
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  /* ── Effects ──────────────────────────────────────────────── */

  useEffect(() => {
    if (location.pathname === '/reports') {
      setLoadingScans(true);
      const params = scopedMissionId ? { mission_id: scopedMissionId } : undefined;
      api.getScans(params).then(res => setScans(res.data)).catch(() => setError('Failed to load scans')).finally(() => setLoadingScans(false));
    }
  }, [location.pathname, scopedMissionId]);

  useEffect(() => { if (!error) return; const t = setTimeout(() => setError(''), 5000); return () => clearTimeout(t); }, [error]);
  useEffect(() => { if (!success) return; const t = setTimeout(() => setSuccess(''), 5000); return () => clearTimeout(t); }, [success]);

  useEffect(() => {
    if (selectedScanIds.length === 0) { setFindings([]); setExcludedRuleIds(new Set()); setGroups([]); return; }
    setLoadingFindings(true); setError('');
    api.getBuilderFindings(selectedScanIds)
      .then(res => { setFindings(res.data); setExcludedRuleIds(new Set()); setGroups([]); setGroupSummaries({}); })
      .catch(() => setError('Failed to load findings'))
      .finally(() => setLoadingFindings(false));
  }, [selectedScanIds]);

  /* ── Computed ─────────────────────────────────────────────── */

  const completedScans = useMemo(() => scans.filter(s => s.status === 'completed' || s.status === 'imported'), [scans]);

  const uniqueRules = useMemo(() => {
    const map = new Map<number, BuilderFinding>();
    findings.forEach(f => { if (!map.has(f.rule_id)) map.set(f.rule_id, f); });
    return Array.from(map.values());
  }, [findings]);

  const ruleMap = useMemo(() => {
    const m = new Map<number, BuilderFinding>();
    uniqueRules.forEach(r => m.set(r.rule_id, r));
    return m;
  }, [uniqueRules]);

  const availableSeverities = useMemo(() => [...new Set(uniqueRules.map(r => r.severity))].sort(), [uniqueRules]);
  const availableStatuses = useMemo(() => [...new Set(uniqueRules.map(r => r.status))].sort(), [uniqueRules]);

  const filteredRules = useMemo(() => {
    let result = uniqueRules;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(r =>
        r.rule_title.toLowerCase().includes(q) ||
        r.section_number.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q),
      );
    }
    if (severityFilter !== 'all') {
      const sevs = severityFilter.split(',');
      result = result.filter(r => sevs.includes(r.severity));
    }
    if (statusFilter !== 'all') result = result.filter(r => r.status === statusFilter);
    return result;
  }, [uniqueRules, searchQuery, severityFilter, statusFilter]);

  const includedRuleIds = useMemo(
    () => new Set(uniqueRules.filter(r => !excludedRuleIds.has(r.rule_id)).map(r => r.rule_id)),
    [uniqueRules, excludedRuleIds],
  );

  const selectedCount = uniqueRules.length - excludedRuleIds.size;
  const totalCount = uniqueRules.length;

  const stats = useMemo(() => {
    const included = uniqueRules.filter(r => !excludedRuleIds.has(r.rule_id));
    const passed = included.filter(r => r.status === 'PASS').length;
    const failed = included.filter(r => r.status === 'FAIL').length;
    const other = included.length - passed - failed;
    const compliance = included.length > 0 ? Math.round((passed / included.length) * 100) : 0;
    const bySev: Record<string, number> = {};
    included.forEach(r => { bySev[r.severity] = (bySev[r.severity] || 0) + 1; });
    return { total: included.length, passed, failed, other, compliance, bySev };
  }, [uniqueRules, excludedRuleIds]);

  const selectedTargets = useMemo(() => {
    const sel = scans.filter(s => selectedScanIds.includes(s.id));
    return [...new Set(sel.map(s => s.target_hostname || s.target_ip || `Target #${s.target_id}`))];
  }, [scans, selectedScanIds]);

  const ungroupedRuleIds = useMemo(() => {
    const grouped = new Set(groups.flatMap(g => g.rule_ids));
    return [...includedRuleIds].filter(id => !grouped.has(id));
  }, [includedRuleIds, groups]);

  const smartTitle = useMemo(() => {
    if (selectedScanIds.length === 0) return 'Report title (auto-generated if blank)';
    const sel = scans.filter(s => selectedScanIds.includes(s.id));
    const clients = [...new Set(sel.map(s => s.client_name).filter(Boolean))];
    const missions = [...new Set(sel.map(s => s.mission_name).filter(Boolean))];
    if (clients.length === 1 && missions.length === 1) return `${clients[0]} — ${missions[0]} Audit Report`;
    if (clients.length === 1) return `${clients[0]} Audit Report`;
    if (selectedTargets.length === 1) return `${selectedTargets[0]} Audit Report`;
    return `Multi-Scan Audit (${selectedScanIds.length} scans)`;
  }, [scans, selectedScanIds, selectedTargets]);

  const compColor = stats.compliance >= 80 ? 'text-emerald-400' : stats.compliance >= 50 ? 'text-yellow-400' : 'text-red-400';
  const compBg = stats.compliance >= 80 ? 'bg-emerald-500' : stats.compliance >= 50 ? 'bg-yellow-500' : 'bg-red-500';

  /* ── Handler Functions ────────────────────────────────────── */

  const toggleRule = useCallback((ruleId: number) => {
    setExcludedRuleIds(prev => { const n = new Set(prev); if (n.has(ruleId)) n.delete(ruleId); else n.add(ruleId); return n; });
  }, []);
  const selectAll = useCallback(() => setExcludedRuleIds(new Set()), []);
  const deselectAll = useCallback(() => setExcludedRuleIds(new Set(uniqueRules.map(r => r.rule_id))), [uniqueRules]);
  const selectFiltered = useCallback(() => {
    setExcludedRuleIds(prev => { const n = new Set(prev); filteredRules.forEach(r => n.delete(r.rule_id)); return n; });
  }, [filteredRules]);
  const deselectFiltered = useCallback(() => {
    setExcludedRuleIds(prev => { const n = new Set(prev); filteredRules.forEach(r => n.add(r.rule_id)); return n; });
  }, [filteredRules]);

  function applyQuickFilter(f: typeof QUICK_FILTERS[number]) {
    setQuickFilter(f.id); setSeverityFilter(f.sev); setStatusFilter(f.status);
  }
  function toggleScan(id: number) {
    setSelectedScanIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  }
  function selectAllScans() { setSelectedScanIds(completedScans.map(s => s.id)); }

  /* ── Group management ─────────────────────────────────────── */
  async function handleAutoGroup() {
    setLoadingAutoGroup(true); setError('');
    try {
      const excluded = excludedRuleIds.size > 0 ? [...excludedRuleIds] : undefined;
      const res = await api.autoGroupRules(selectedScanIds, excluded);
      setGroups(res.groups); setGroupSummaries({}); setCollapsedGroups(new Set());
    } catch { setError('Auto-grouping failed'); } finally { setLoadingAutoGroup(false); }
  }
  function addNewGroup() { setGroups(prev => [...prev, { name: `Group ${prev.length + 1}`, rule_ids: [] }]); }
  function deleteGroup(idx: number) {
    const name = groups[idx]?.name;
    setGroups(prev => prev.filter((_, i) => i !== idx));
    if (name) setGroupSummaries(prev => { const n = { ...prev }; delete n[name]; return n; });
  }
  function startRenameGroup(idx: number) { setEditingGroupIdx(idx); setEditingGroupName(groups[idx].name); }
  function finishRenameGroup() {
    if (editingGroupIdx !== null && editingGroupName.trim())
      setGroups(prev => prev.map((g, i) => (i === editingGroupIdx ? { ...g, name: editingGroupName.trim() } : g)));
    setEditingGroupIdx(null); setEditingGroupName('');
  }
  function toggleCollapse(idx: number) {
    setCollapsedGroups(prev => { const n = new Set(prev); if (n.has(idx)) n.delete(idx); else n.add(idx); return n; });
  }
  function moveRuleToGroup(ruleId: number, from: number, to: number) {
    setGroups(prev => prev.map((g, i) => {
      if (i === from) return { ...g, rule_ids: g.rule_ids.filter(id => id !== ruleId) };
      if (i === to) return { ...g, rule_ids: [...g.rule_ids, ruleId] };
      return g;
    }));
  }
  function addRuleToGroup(ruleId: number, gIdx: number) {
    setGroups(prev => prev.map((g, i) => (i === gIdx ? { ...g, rule_ids: [...g.rule_ids, ruleId] } : g)));
  }
  function removeRuleFromGroup(ruleId: number, gIdx: number) {
    setGroups(prev => prev.map((g, i) => (i === gIdx ? { ...g, rule_ids: g.rule_ids.filter(id => id !== ruleId) } : g)));
  }
  function moveGroupUp(idx: number) {
    if (idx <= 0) return;
    setGroups(prev => { const n = [...prev];[n[idx - 1], n[idx]] = [n[idx], n[idx - 1]]; return n; });
  }
  function moveGroupDown(idx: number) {
    if (idx >= groups.length - 1) return;
    setGroups(prev => { const n = [...prev];[n[idx], n[idx + 1]] = [n[idx + 1], n[idx]]; return n; });
  }

  /* ── Audience & AI ────────────────────────────────────────── */
  function applyAudience(preset: typeof AUDIENCES[number]) {
    setAudience(preset.value);
    setSections({ ...preset.secs });
    // Reset filter settings from corresponding preset to avoid stale state
    const matchingPreset = REPORT_PRESETS.find(p => p.audience === preset.value);
    if (matchingPreset) {
      setIncludePassedRules(matchingPreset.includePassed);
      setSeverityFilter(matchingPreset.severityFilter);
    }
  }
  function applyPreset(preset: typeof REPORT_PRESETS[number]) {
    setAudience(preset.audience);
    const audObj = AUDIENCES.find(a => a.value === preset.audience);
    if (audObj) setSections({ ...audObj.secs });
    setExportFormat(preset.format);
    setIncludePassedRules(preset.includePassed);
    setIncludeAiSummary(preset.aiSummary);
    setSeverityFilter(preset.severityFilter);
    setSuccess(`Applied ${preset.label} preset`);
  }
  function toggleSection(key: string) { setSections(prev => ({ ...prev, [key]: !prev[key] })); }

  async function generateGroupSummary(groupName: string, ruleIds: number[]) {
    setLoadingSummaryFor(groupName); setError('');
    try {
      const res = await api.getGroupSummary({ group_name: groupName, rule_ids: ruleIds, scan_ids: selectedScanIds, audience });
      setGroupSummaries(prev => ({ ...prev, [groupName]: res.summary }));
    } catch { setError(`Failed to generate summary for "${groupName}"`); } finally { setLoadingSummaryFor(null); }
  }
  async function generateAllSummaries() {
    for (const g of groups) { if (g.rule_ids.length > 0) await generateGroupSummary(g.name, g.rule_ids); }
  }
  async function handlePreviewAiSummary() {
    if (selectedScanIds.length === 0) return;
    setPreviewingSummary(true); setError('');
    try {
      const result = await api.generateAISummary({ scope: 'custom', scan_ids: selectedScanIds });
      setAiSummaryPreview(result.summary);
    } catch { setError('Failed to generate AI summary. Check LLM configuration.'); } finally { setPreviewingSummary(false); }
  }

  /* ── Drag & Drop ──────────────────────────────────────────── */
  function handleDragStart(ruleId: number, fromGroup: number) { setDragState({ ruleId, fromGroup }); }
  function handleDragOver(e: React.DragEvent) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }
  function handleDrop(toGroupIdx: number) {
    if (!dragState) return;
    if (dragState.fromGroup === toGroupIdx) return;
    if (dragState.fromGroup === -1) addRuleToGroup(dragState.ruleId, toGroupIdx);
    else moveRuleToGroup(dragState.ruleId, dragState.fromGroup, toGroupIdx);
    setDragState(null);
  }
  function handleDropToUngrouped() {
    if (!dragState || dragState.fromGroup === -1) return;
    removeRuleFromGroup(dragState.ruleId, dragState.fromGroup);
    setDragState(null);
  }

  /* ── Preview & Export ─────────────────────────────────────── */
  const handlePreview = useCallback(async () => {
    if (selectedScanIds.length === 0) return;
    setLoadingPreview(true); setError('');
    try {
      const html = await api.getBuilderPreview({
        scan_ids: selectedScanIds,
        excluded_rule_ids: excludedRuleIds.size > 0 ? [...excludedRuleIds] : undefined,
        include_passed_rules: includePassedRules,
        title: customTitle || undefined,
        groups: groups.length > 0 ? groups : undefined,
        audience, sections,
        group_summaries: Object.keys(groupSummaries).length > 0 ? groupSummaries : undefined,
        severity_filter: severityFilter !== 'all' ? severityFilter.split(',') : undefined,
      });
      setPreviewHtml(html);
    } catch { setError('Failed to generate preview'); } finally { setLoadingPreview(false); }
  }, [selectedScanIds, excludedRuleIds, includePassedRules, customTitle, groups, audience, sections, groupSummaries, severityFilter]);

  useEffect(() => {
    if (selectedScanIds.length === 0) return;
    const timer = setTimeout(() => { handlePreview(); }, 800);
    return () => clearTimeout(timer);
  }, [handlePreview, selectedScanIds]);

  async function handleExport() {
    if (selectedScanIds.length === 0 || selectedCount === 0) return;
    setExporting(true); setError(''); setSuccess('');
    try {
      const payload: ReportGenerateRequest = {
        scope: 'custom', scan_ids: selectedScanIds,
        format: exportFormat as ReportGenerateRequest['format'],
        include_ai_summary: includeAiSummary, include_passed_rules: includePassedRules,
        title: customTitle || undefined,
        excluded_rule_ids: excludedRuleIds.size > 0 ? [...excludedRuleIds] : undefined,
        groups: groups.length > 0 ? groups : undefined,
        audience, sections,
        group_summaries: Object.keys(groupSummaries).length > 0 ? groupSummaries : undefined,
        severity_filter: severityFilter !== 'all' ? severityFilter.split(',') : undefined,
      };
      const blob = await api.generateReport(payload);
      const ext = FILE_EXT[exportFormat] || 'bin';
      const date = new Date().toISOString().slice(0, 10);
      let name = customTitle ? customTitle.replace(/[^a-zA-Z0-9_-]/g, '_').substring(0, 60) : `builder_${selectedScanIds.length}scans`;
      const filename = `${name}_${date}.${ext}`;
      const url = URL.createObjectURL(new Blob([blob], { type: MIME[exportFormat] }));
      const a = document.createElement('a'); a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
      setSuccess(`Report exported as ${filename}`);
    } catch { setError('Export failed'); } finally { setExporting(false); }
  }

  /* ═══════════════════════════════════════════════════════════════ */
  /*  RENDER                                                        */
  /* ═══════════════════════════════════════════════════════════════ */

  return (
    <div className="space-y-5 overflow-x-hidden">

      {/* ── Banners ───────────────────────────────────────────── */}
      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400 animate-in fade-in">{error}</div>}
      {success && <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-400 animate-in fade-in">{success}</div>}

      {/* ── Header ────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-ey-yellow/15 border border-ey-yellow/30">
              <BarChart3 className="h-5 w-5 text-ey-yellow" />
            </div>
            Report Studio
          </h1>
          <p className="mt-1.5 text-sm text-dark-secondary ml-[52px]">
            {scopedMissionName
              ? <>Reporting for mission <span className="text-ey-yellow font-medium">{scopedMissionName}</span></>
              : 'Build, customize, and export professional audit reports'
            }
          </p>
        </div>
      </div>

      {/* ── Mission scope banner ─────────────────────────────── */}
      {scopedMissionId && (
        <div className="flex items-center justify-between rounded-lg border border-ey-yellow/20 bg-ey-yellow/5 px-4 py-2.5">
          <div className="flex items-center gap-2 text-sm">
            <Layers className="h-4 w-4 text-ey-yellow" />
            <span className="text-dark-secondary">Scoped to mission:</span>
            <span className="text-white font-medium">{scopedMissionName || `#${scopedMissionId}`}</span>
          </div>
          <button
            onClick={() => { setScopedMissionId(undefined); setScopedMissionName(undefined); setSelectedScanIds([]); }}
            className="text-xs text-dark-secondary hover:text-ey-yellow transition-colors"
          >
            Show all scans
          </button>
        </div>
      )}

      {/* ── Loading state ─────────────────────────────────────── */}
      {loadingScans ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-ey-yellow" />
          <span className="ml-3 text-sm text-dark-secondary">Loading scans…</span>
        </div>
      ) : completedScans.length === 0 ? (
        /* ── No scans empty state ─────────────────────────────── */
        <div className="rounded-2xl border-2 border-dashed border-dark-border p-16 text-center">
          <FileText className="h-16 w-16 mx-auto text-dark-muted opacity-20 mb-4" />
          <h3 className="text-lg font-semibold text-white mb-2">No Completed Scans</h3>
          <p className="text-sm text-dark-secondary max-w-md mx-auto mb-2">
            Complete at least one scan to start building reports.
          </p>
          <p className="text-xs text-dark-muted">Go to a Mission Workspace → run a scan → import results</p>
        </div>
      ) : (
        <>
          {/* ═══════════════════════════════════════════════════════ */}
          {/*  SCAN SOURCE PICKER                                    */}
          {/* ═══════════════════════════════════════════════════════ */}
          <div className="rounded-xl border border-dark-border bg-dark-card">
            {/* Header bar */}
            <div className="flex items-center justify-between px-5 py-3 border-b border-dark-border">
              <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-ey-yellow" />
                Data Sources
                {selectedScanIds.length > 0 && (
                  <span className="ml-1 rounded-full bg-ey-yellow/15 px-2 py-0.5 text-xs font-medium text-ey-yellow">
                    {selectedScanIds.length} selected
                  </span>
                )}
              </h2>
              <div className="flex items-center gap-2">
                {selectedScanIds.length > 0 && (
                  <button onClick={() => setSelectedScanIds([])} className="text-xs text-dark-secondary hover:text-red-400 transition-colors">Clear</button>
                )}
                {selectedScanIds.length < completedScans.length && (
                  <button onClick={selectAllScans} className="text-xs text-dark-secondary hover:text-ey-yellow transition-colors">Select All</button>
                )}
                <div className="h-4 w-px bg-dark-border mx-1" />
                <div className="flex rounded-lg border border-dark-border overflow-hidden">
                  <button
                    onClick={() => setScanView('card')}
                    className={`p-1.5 transition-colors ${scanView === 'card' ? 'bg-ey-yellow/15 text-ey-yellow' : 'bg-dark-elevated text-dark-muted hover:text-white'}`}
                    title="Card view"
                  >
                    <LayoutGrid className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => setScanView('list')}
                    className={`p-1.5 transition-colors ${scanView === 'list' ? 'bg-ey-yellow/15 text-ey-yellow' : 'bg-dark-elevated text-dark-muted hover:text-white'}`}
                    title="List view"
                  >
                    <List className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </div>

            {/* Scan cards / list */}
            <div className="p-4">
              {scanView === 'card' ? (
                /* ── Card View ─────────────────────────────────── */
                <div className="flex gap-3 overflow-x-auto pb-2 snap-x snap-mandatory scrollbar-thin scrollbar-thumb-dark-border scrollbar-track-transparent max-w-full">
                  {completedScans.map(scan => {
                    const selected = selectedScanIds.includes(scan.id);
                    const comp = scan.compliance_percentage ?? 0;
                    const compC = comp >= 80 ? 'text-emerald-400' : comp >= 50 ? 'text-yellow-400' : 'text-red-400';
                    const compBgC = comp >= 80 ? 'bg-emerald-500' : comp >= 50 ? 'bg-yellow-500' : 'bg-red-500';
                    return (
                      <button
                        key={scan.id}
                        onClick={() => toggleScan(scan.id)}
                        className={`flex-shrink-0 w-[230px] snap-start rounded-xl border-2 p-4 text-left transition-all ${selected
                          ? 'border-ey-yellow bg-ey-yellow/5 shadow-lg shadow-ey-yellow/5'
                          : 'border-dark-border bg-dark-elevated hover:border-dark-secondary'
                          }`}
                      >
                        <div className="flex items-start justify-between mb-1">
                          <h3 className="text-sm font-semibold text-white truncate flex-1 pr-2">
                            {scan.target_hostname || scan.target_ip || `Scan #${scan.id}`}
                          </h3>
                          <div className={`flex-shrink-0 w-5 h-5 rounded-md border-2 flex items-center justify-center transition-colors ${selected ? 'border-ey-yellow bg-ey-yellow' : 'border-dark-border bg-dark-elevated'
                            }`}>
                            {selected && <CheckCircle2 className="h-3 w-3 text-black" />}
                          </div>
                        </div>
                        <p className="text-[11px] text-dark-secondary truncate mb-0.5">{scan.benchmark_name || scan.scan_mode}</p>
                        {(scan.client_name || scan.mission_name) && (
                          <p className="text-[11px] text-dark-muted truncate mb-2">
                            {scan.client_name && <span>{scan.client_name}</span>}
                            {scan.client_name && scan.mission_name && <span> · </span>}
                            {scan.mission_name && <span>{scan.mission_name}</span>}
                          </p>
                        )}
                        <div className="flex items-center gap-2 mb-2">
                          <div className="flex-1 h-1.5 rounded-full bg-dark-border overflow-hidden">
                            <div className={`h-full rounded-full transition-all duration-500 ${compBgC}`} style={{ width: `${comp}%` }} />
                          </div>
                          <span className={`text-xs font-bold flex-shrink-0 ${compC}`}>{comp}%</span>
                        </div>
                        <div className="flex items-center gap-3 text-[11px]">
                          <span className="text-emerald-400 font-medium">✓ {scan.passed}</span>
                          <span className="text-red-400 font-medium">✗ {scan.failed}</span>
                          {scan.errors > 0 && <span className="text-yellow-400">⚠ {scan.errors}</span>}
                        </div>
                      </button>
                    );
                  })}
                </div>
              ) : (
                /* ── List View ──────────────────────────────────── */
                <div className="max-h-[220px] overflow-y-auto rounded-lg border border-dark-border divide-y divide-dark-border">
                  {completedScans.map(scan => {
                    const selected = selectedScanIds.includes(scan.id);
                    const comp = scan.compliance_percentage ?? 0;
                    const compC = comp >= 80 ? 'text-emerald-400' : comp >= 50 ? 'text-yellow-400' : 'text-red-400';
                    const compBgC = comp >= 80 ? 'bg-emerald-500' : comp >= 50 ? 'bg-yellow-500' : 'bg-red-500';
                    return (
                      <label key={scan.id} className={`flex items-center gap-4 px-4 py-2.5 cursor-pointer transition-colors ${selected ? 'bg-ey-yellow/5' : 'hover:bg-dark-elevated'}`}>
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-dark-border bg-dark-elevated text-ey-yellow focus:ring-ey-yellow/50 accent-ey-yellow"
                          checked={selected}
                          onChange={() => toggleScan(scan.id)}
                        />
                        <span className="text-sm font-medium text-white truncate flex-1 min-w-0">{scan.target_hostname || scan.target_ip || `Scan #${scan.id}`}</span>
                        <span className="text-xs text-dark-secondary truncate flex-1 min-w-0 hidden sm:block">{scan.benchmark_name || scan.scan_mode}</span>
                        <div className="hidden sm:flex items-center gap-2 flex-shrink-0 w-24">
                          <div className="flex-1 h-1.5 rounded-full bg-dark-border overflow-hidden">
                            <div className={`h-full rounded-full ${compBgC}`} style={{ width: `${comp}%` }} />
                          </div>
                          <span className={`text-xs font-bold ${compC}`}>{comp}%</span>
                        </div>
                        <span className={`sm:hidden text-xs font-bold flex-shrink-0 ${compC}`}>{comp}%</span>
                        <div className="hidden md:flex gap-2 text-[11px] flex-shrink-0">
                          <span className="text-emerald-400">✓{scan.passed}</span>
                          <span className="text-red-400">✗{scan.failed}</span>
                        </div>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Target coverage footer */}
            {selectedTargets.length > 0 && (
              <div className="flex items-center gap-2 px-5 py-2.5 border-t border-dark-border flex-wrap">
                <span className="text-[11px] text-dark-muted">Targets covered:</span>
                {selectedTargets.map(t => (
                  <span key={t} className="rounded-full bg-dark-elevated border border-dark-border px-2 py-0.5 text-[11px] text-dark-secondary">{t}</span>
                ))}
              </div>
            )}
          </div>

          {/* ═══════════════════════════════════════════════════════ */}
          {/*  CONTENT (only when scans selected)                    */}
          {/* ═══════════════════════════════════════════════════════ */}
          {selectedScanIds.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card/30 p-10 text-center">
              <BarChart3 className="h-10 w-10 mx-auto text-dark-muted opacity-20 mb-3" />
              <h3 className="text-base font-semibold text-white mb-1">Select Data Sources</h3>
              <p className="text-sm text-dark-secondary">Pick one or more scans above to start building your report</p>
            </div>
          ) : (
            <>
              {/* ─── Composition Stats Bar ─────────────────────── */}
              {loadingFindings ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-ey-yellow" />
                  <span className="ml-2 text-sm text-dark-secondary">Loading rules…</span>
                </div>
              ) : stats.total > 0 && (
                <div className="rounded-xl border border-dark-border bg-dark-card p-4">
                  <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-5 gap-3 mb-3">
                    <div className="rounded-lg bg-dark-elevated p-3 text-center">
                      <div className="text-xl font-bold text-white">{stats.total}</div>
                      <div className="text-[11px] text-dark-secondary mt-0.5">Rules Included</div>
                    </div>
                    <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/20 p-3 text-center">
                      <div className="text-xl font-bold text-emerald-400">{stats.passed}</div>
                      <div className="text-[11px] text-dark-secondary mt-0.5">Passed</div>
                    </div>
                    <div className="rounded-lg bg-red-500/5 border border-red-500/20 p-3 text-center">
                      <div className="text-xl font-bold text-red-400">{stats.failed}</div>
                      <div className="text-[11px] text-dark-secondary mt-0.5">Failed</div>
                    </div>
                    <div className="rounded-lg bg-dark-elevated p-3 text-center">
                      <div className={`text-xl font-bold ${compColor}`}>{stats.compliance}%</div>
                      <div className="text-[11px] text-dark-secondary mt-0.5">Compliance</div>
                    </div>
                    <div className="rounded-lg bg-dark-elevated p-3 col-span-2 sm:col-span-4 xl:col-span-1">
                      <div className="text-[11px] text-dark-secondary mb-1.5">Severity Breakdown</div>
                      <div className="flex flex-wrap gap-x-3 gap-y-1">
                        {SEV_ORDER.map(sev => {
                          const count = stats.bySev[sev] || 0;
                          if (count === 0) return null;
                          return (
                            <div key={sev} className="flex items-center gap-1">
                              <div className={`w-2.5 h-2.5 rounded-sm ${SEV_DOT[sev]}`} />
                              <span className="text-xs text-white font-medium">{count}</span>
                              <span className="text-[10px] text-dark-muted uppercase">{sev.slice(0, 4)}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 h-2 rounded-full bg-dark-border overflow-hidden">
                      <div className={`h-full rounded-full transition-all duration-700 ${compBg}`} style={{ width: `${stats.compliance}%` }} />
                    </div>
                    <span className="text-xs text-dark-secondary whitespace-nowrap">{stats.compliance}% compliant</span>
                  </div>
                </div>
              )}

              {/* ─── Template Presets ───────────────────────────── */}
              <div className="flex bg-dark-card border border-dark-border rounded-lg overflow-x-auto p-2 gap-2 mb-2 custom-scrollbar items-center">
                <div className="flex items-center px-3 border-r border-dark-border mr-2 shrink-0">
                  <span className="text-sm font-semibold text-white flex items-center gap-1.5"><Sparkles className="h-4 w-4 text-ey-yellow" /> Template Presets</span>
                </div>
                {REPORT_PRESETS.map(preset => (
                  <button key={preset.id} onClick={() => applyPreset(preset)}
                    title={preset.desc}
                    className="flex shrink-0 items-center justify-center gap-1.5 px-4 py-1.5 border border-dark-border rounded-lg bg-dark-elevated hover:bg-dark-overlay hover:border-dark-secondary transition-colors">
                    <span>{preset.icon}</span>
                    <span className="text-xs font-medium text-white">{preset.label}</span>
                  </button>
                ))}
              </div>

              {/* ─── Split Pane Layout ──────────────────────────── */}
              <div className="flex flex-col xl:flex-row gap-6 items-start">

                {/* Left Pane: Builder Controls */}
                <div className="flex-1 w-full xl:w-5/12 flex flex-col gap-6">

                  {/* ─── Tab Navigation (Left Pane) ────────────────── */}
                  <div className="rounded-xl border border-dark-border bg-dark-card overflow-hidden">
                    <div className="flex border-b border-dark-border overflow-x-auto custom-scrollbar">
                      {TABS.map(tab => {
                        const Icon = tab.icon;
                        const isActive = activeTab === tab.id;
                        let badge = '';
                        if (tab.id === 'rules') badge = `${selectedCount}`;
                        if (tab.id === 'organize') badge = `${groups.length}`;
                        return (
                          <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`relative flex items-center gap-2 px-5 py-3.5 text-sm font-medium transition-colors ${isActive ? 'text-ey-yellow' : 'text-dark-secondary hover:text-white'
                              }`}
                          >
                            <Icon className="h-4 w-4" />
                            <span className="hidden sm:inline">{tab.label}</span>
                            {badge && badge !== '0' && (
                              <span className={`rounded-full px-1.5 py-0 text-[10px] font-medium ${isActive ? 'bg-ey-yellow/15 text-ey-yellow' : 'bg-dark-elevated text-dark-muted'
                                }`}>{badge}</span>
                            )}
                            {isActive && <div className="absolute bottom-0 left-2 right-2 h-0.5 rounded-full bg-ey-yellow" />}
                          </button>
                        );
                      })}
                    </div>

                    <div className="p-5">

                      {/* ══════════════════════════════════════════════ */}
                      {/*  TAB: Rules                                   */}
                      {/* ══════════════════════════════════════════════ */}
                      {activeTab === 'rules' && (
                        <div>
                          {/* Quick Filter Presets */}
                          <div className="flex flex-wrap gap-2 mb-4">
                            {QUICK_FILTERS.map(f => {
                              const QIcon = f.icon;
                              const isActive = quickFilter === f.id;
                              return (
                                <button
                                  key={f.id}
                                  onClick={() => applyQuickFilter(f)}
                                  className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-all ${isActive
                                    ? 'border-ey-yellow/40 bg-ey-yellow/10 text-ey-yellow'
                                    : 'border-dark-border bg-dark-elevated text-dark-secondary hover:text-white hover:border-dark-secondary'
                                    }`}
                                >
                                  <QIcon className="h-3 w-3" />
                                  {f.label}
                                </button>
                              );
                            })}
                          </div>

                          {/* Search + Filters + Bulk Ops */}
                          <div className="flex flex-wrap items-center gap-3 mb-3">
                            <div className="relative flex-1 min-w-0">
                              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-dark-muted" />
                              <input
                                type="text"
                                placeholder="Search by title, section, or description…"
                                className="w-full rounded-lg border border-dark-border bg-dark-elevated pl-9 pr-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                                value={searchQuery}
                                onChange={e => { setSearchQuery(e.target.value); setQuickFilter(''); }}
                              />
                            </div>
                            <select className="rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white focus:border-ey-yellow/50 focus:outline-none" value={severityFilter} onChange={e => { setSeverityFilter(e.target.value); setQuickFilter(''); }}>
                              <option value="all">All Severity</option>
                              {availableSeverities.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
                            </select>
                            <select className="rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white focus:border-ey-yellow/50 focus:outline-none" value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setQuickFilter(''); }}>
                              <option value="all">All Status</option>
                              {availableStatuses.map(s => <option key={s} value={s}>{s}</option>)}
                            </select>
                            <div className="flex gap-1">
                              <button onClick={selectAll} className="rounded-md bg-dark-elevated px-2 py-1.5 text-xs text-dark-secondary hover:text-white transition-colors" title="Select all"><ListChecks className="h-3.5 w-3.5" /></button>
                              <button onClick={deselectAll} className="rounded-md bg-dark-elevated px-2 py-1.5 text-xs text-dark-secondary hover:text-white transition-colors" title="Deselect all"><ListX className="h-3.5 w-3.5" /></button>
                              <button onClick={() => { setExcludedRuleIds(new Set()); setSearchQuery(''); setSeverityFilter('all'); setStatusFilter('all'); setQuickFilter('all'); }} className="rounded-md bg-dark-elevated px-2 py-1.5 text-xs text-dark-secondary hover:text-white transition-colors" title="Reset"><RotateCcw className="h-3.5 w-3.5" /></button>
                            </div>
                          </div>

                          {/* Filtered bulk ops */}
                          {(searchQuery || severityFilter !== 'all' || statusFilter !== 'all') && (
                            <div className="flex gap-2 mb-3">
                              <button onClick={selectFiltered} className="rounded-md bg-emerald-500/10 border border-emerald-500/30 px-2.5 py-1 text-xs text-emerald-400 hover:bg-emerald-500/20 transition-colors">
                                Select filtered ({filteredRules.length})
                              </button>
                              <button onClick={deselectFiltered} className="rounded-md bg-red-500/10 border border-red-500/30 px-2.5 py-1 text-xs text-red-400 hover:bg-red-500/20 transition-colors">
                                Deselect filtered
                              </button>
                            </div>
                          )}

                          {/* Rules list */}
                          {filteredRules.length === 0 ? (
                            <div className="flex flex-col items-center justify-center py-12 text-dark-muted">
                              <Search className="h-8 w-8 mb-2 opacity-40" />
                              <p className="text-sm">No rules match your filters</p>
                            </div>
                          ) : (
                            <div className="max-h-[440px] overflow-y-auto rounded-lg border border-dark-border divide-y divide-dark-border">
                              {filteredRules.map(rule => {
                                const isIncluded = !excludedRuleIds.has(rule.rule_id);
                                const StIcon = STATUS_ICONS[rule.status] || ShieldAlert;
                                const stColor = STATUS_COLORS[rule.status] || 'text-dark-muted';
                                const sevClass = SEV_COLORS[rule.severity] || SEV_COLORS.medium;
                                return (
                                  <label key={rule.rule_id} className={`flex items-start gap-3 px-3 py-2.5 cursor-pointer transition-colors ${isIncluded ? 'hover:bg-dark-elevated' : 'bg-dark-elevated/40 opacity-50'}`}>
                                    <input type="checkbox" className="mt-1 h-4 w-4 rounded border-dark-border bg-dark-elevated text-ey-yellow focus:ring-ey-yellow/50 accent-ey-yellow" checked={isIncluded} onChange={() => toggleRule(rule.rule_id)} />
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center gap-2 flex-wrap">
                                        <span className="text-xs font-mono text-dark-muted">{rule.section_number}</span>
                                        <span className="text-sm font-medium text-white truncate">{rule.rule_title}</span>
                                      </div>
                                      <div className="flex items-center gap-2 mt-1">
                                        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${sevClass}`}>{rule.severity}</span>
                                        <span className={`inline-flex items-center gap-1 text-xs ${stColor}`}><StIcon className="h-3.5 w-3.5" />{rule.status}</span>
                                        {rule.target_hostname && <span className="text-xs text-dark-muted">· {rule.target_hostname}</span>}
                                      </div>
                                    </div>
                                  </label>
                                );
                              })}
                            </div>
                          )}

                          {/* Footer stats */}
                          {totalCount > 0 && (
                            <div className="mt-3 flex items-center justify-between text-xs text-dark-secondary">
                              <span>Showing {filteredRules.length} of {totalCount} rules{(searchQuery || severityFilter !== 'all' || statusFilter !== 'all') ? ' (filtered)' : ''}</span>
                              <span>
                                <span className="text-emerald-400 font-medium">{selectedCount}</span> included ·{' '}
                                <span className="text-red-400 font-medium">{excludedRuleIds.size}</span> excluded
                              </span>
                            </div>
                          )}
                        </div>
                      )}

                      {/* ══════════════════════════════════════════════ */}
                      {/*  TAB: Organize                                */}
                      {/* ══════════════════════════════════════════════ */}
                      {activeTab === 'organize' && (
                        <div>
                          {/* Toolbar */}
                          <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
                            <div>
                              <p className="text-sm text-dark-secondary">
                                Group your <span className="text-white font-medium">{selectedCount}</span> rules into report sections. Drag rules between groups or use AI.
                              </p>
                            </div>
                            <div className="flex gap-2">
                              <button onClick={handleAutoGroup} disabled={loadingAutoGroup || selectedCount === 0}
                                className="flex items-center gap-2 rounded-lg border border-purple-500/30 bg-purple-500/10 px-3 py-2 text-sm font-medium text-purple-400 transition-colors hover:bg-purple-500/20 disabled:cursor-not-allowed disabled:opacity-50">
                                {loadingAutoGroup ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                                {loadingAutoGroup ? 'Grouping…' : 'AI Auto-Group'}
                              </button>
                              <button onClick={addNewGroup} className="flex items-center gap-2 rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm font-medium text-dark-secondary hover:text-white transition-colors">
                                <Plus className="h-4 w-4" /> New Group
                              </button>
                              {groups.length > 0 && (
                                <button onClick={() => { setGroups([]); setGroupSummaries({}); }} className="flex items-center gap-2 rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm font-medium text-dark-secondary hover:text-red-400 transition-colors">
                                  <RotateCcw className="h-4 w-4" /> Clear
                                </button>
                              )}
                            </div>
                          </div>

                          {/* Groups content */}
                          {groups.length === 0 ? (
                            <div className="rounded-xl border-2 border-dashed border-dark-border p-10 text-center">
                              <FolderPlus className="h-12 w-12 mx-auto text-dark-muted opacity-20 mb-4" />
                              <h3 className="text-base font-semibold text-white mb-2">No Groups Yet</h3>
                              <p className="text-sm text-dark-secondary max-w-md mx-auto mb-3">
                                Click "AI Auto-Group" to automatically categorize rules, or "New Group" to create groups manually.
                              </p>
                              <p className="text-xs text-dark-muted">You can skip this step — rules will appear ungrouped in the report.</p>
                            </div>
                          ) : (
                            <div className="space-y-3">
                              {groups.map((group, gIdx) => (
                                <div key={gIdx} onDragOver={handleDragOver} onDrop={() => handleDrop(gIdx)}
                                  className={`rounded-xl border bg-dark-card transition-all ${dragState ? 'border-ey-yellow/30 bg-ey-yellow/5' : 'border-dark-border'}`}>
                                  {/* Group header */}
                                  <div className="flex items-center gap-3 px-4 py-3 border-b border-dark-border">
                                    <button onClick={() => toggleCollapse(gIdx)} className="text-dark-secondary hover:text-white">
                                      {collapsedGroups.has(gIdx) ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                                    </button>
                                    {editingGroupIdx === gIdx ? (
                                      <input autoFocus className="flex-1 rounded border border-ey-yellow/40 bg-dark-elevated px-2 py-1 text-sm text-white focus:outline-none"
                                        value={editingGroupName} onChange={e => setEditingGroupName(e.target.value)}
                                        onBlur={finishRenameGroup} onKeyDown={e => e.key === 'Enter' && finishRenameGroup()} />
                                    ) : (
                                      <h3 className="flex-1 text-sm font-semibold text-white">{group.name}</h3>
                                    )}
                                    <span className="rounded-full bg-dark-elevated px-2 py-0.5 text-xs text-dark-secondary">{group.rule_ids.length} rule{group.rule_ids.length !== 1 ? 's' : ''}</span>
                                    <div className="flex items-center gap-1">
                                      <button onClick={() => moveGroupUp(gIdx)} disabled={gIdx === 0} className="p-1 text-dark-muted hover:text-white disabled:opacity-30"><ChevronUp className="h-3.5 w-3.5" /></button>
                                      <button onClick={() => moveGroupDown(gIdx)} disabled={gIdx === groups.length - 1} className="p-1 text-dark-muted hover:text-white disabled:opacity-30"><ChevronDown className="h-3.5 w-3.5" /></button>
                                      <button onClick={() => startRenameGroup(gIdx)} className="p-1 text-dark-muted hover:text-ey-yellow"><Pencil className="h-3.5 w-3.5" /></button>
                                      <button onClick={() => deleteGroup(gIdx)} className="p-1 text-dark-muted hover:text-red-400"><Trash2 className="h-3.5 w-3.5" /></button>
                                    </div>
                                  </div>
                                  {/* Group rules */}
                                  {!collapsedGroups.has(gIdx) && (
                                    <div className="p-3 space-y-1.5 min-h-[40px]">
                                      {group.rule_ids.length === 0 ? (
                                        <p className="text-xs text-dark-muted text-center py-3">Drag rules here or use auto-group</p>
                                      ) : group.rule_ids.map(rid => <RulePill key={rid} ruleId={rid} groupIdx={gIdx} rule={ruleMap.get(rid)} onDragStart={handleDragStart} onRemove={removeRuleFromGroup} />)}
                                    </div>
                                  )}
                                </div>
                              ))}

                              {/* Ungrouped rules */}
                              {ungroupedRuleIds.length > 0 && (
                                <div onDragOver={handleDragOver} onDrop={handleDropToUngrouped}
                                  className="rounded-xl border border-dashed border-dark-border bg-dark-card">
                                  <div className="flex items-center gap-2 px-4 py-3 border-b border-dark-border">
                                    <h3 className="text-sm font-semibold text-dark-secondary">Ungrouped Rules</h3>
                                    <span className="rounded-full bg-dark-elevated px-2 py-0.5 text-xs text-dark-muted">{ungroupedRuleIds.length}</span>
                                  </div>
                                  <div className="p-3 space-y-1.5 max-h-[300px] overflow-y-auto">
                                    {ungroupedRuleIds.map(rid => <RulePill key={rid} ruleId={rid} groupIdx={-1} rule={ruleMap.get(rid)} onDragStart={handleDragStart} onRemove={removeRuleFromGroup} />)}
                                  </div>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      )}

                      {/* ══════════════════════════════════════════════ */}
                      {/*  TAB: Customize                               */}
                      {/* ══════════════════════════════════════════════ */}
                      {activeTab === 'customize' && (
                        <div className="grid grid-cols-1 gap-6">
                          <div className="space-y-5">
                            {/* Audience Presets */}
                            <div>
                              <h3 className="flex items-center gap-2 text-sm font-semibold text-white mb-3">
                                <Users className="h-4 w-4 text-ey-yellow" /> Target Audience
                              </h3>
                              <div className="space-y-2">
                                {AUDIENCES.map(preset => (
                                  <button key={preset.value} onClick={() => applyAudience(preset)}
                                    className={`w-full flex items-start gap-3 rounded-lg border-2 p-3 text-left transition-all ${audience === preset.value
                                      ? 'border-ey-yellow bg-ey-yellow/10'
                                      : 'border-dark-border hover:border-dark-secondary'}`}>
                                    <span className="text-xl flex-shrink-0">{preset.icon}</span>
                                    <div>
                                      <span className={`block text-sm font-medium ${audience === preset.value ? 'text-ey-yellow' : 'text-white'}`}>{preset.label}</span>
                                      <span className="block text-xs text-dark-muted mt-0.5">{preset.desc}</span>
                                    </div>
                                  </button>
                                ))}
                              </div>
                            </div>

                            {/* Section Toggles — grouped */}
                            <div>
                              <h3 className="text-sm font-semibold text-white mb-3">Report Sections</h3>
                              <div className="space-y-4">
                                {SEC_GROUPS.map(group => (
                                  <div key={group.label}>
                                    <div className="flex items-center justify-between mb-1.5">
                                      <span className="text-xs font-semibold uppercase tracking-wider text-dark-secondary">{group.label}</span>
                                      <button onClick={() => {
                                        const allOn = group.keys.every(k => sections[k]);
                                        const patch: Record<string, boolean> = {};
                                        group.keys.forEach(k => { patch[k] = !allOn; });
                                        setSections(prev => ({ ...prev, ...patch }));
                                      }} className="text-[10px] text-dark-muted hover:text-ey-yellow transition-colors">
                                        {group.keys.every(k => sections[k]) ? 'Deselect all' : 'Select all'}
                                      </button>
                                    </div>
                                    <div className="space-y-1">
                                      {group.keys.map(key => (
                                        <button key={key} onClick={() => toggleSection(key)}
                                          className="w-full flex items-center justify-between rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 transition-colors hover:border-dark-secondary">
                                          <span className="text-sm text-white">{SEC_LABELS[key]}</span>
                                          {sections[key] ? <ToggleRight className="h-5 w-5 text-ey-yellow" /> : <ToggleLeft className="h-5 w-5 text-dark-muted" />}
                                        </button>
                                      ))}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>

                            {/* AI Executive Summary */}
                            <div className="rounded-lg border border-dark-border bg-dark-elevated p-4">
                              <h3 className="flex items-center gap-2 text-sm font-semibold text-white mb-2">
                                <Sparkles className="h-4 w-4 text-purple-400" /> AI Executive Summary
                              </h3>
                              <p className="text-xs text-dark-secondary mb-3">Auto-generate a high-level summary of audit findings.</p>
                              <label className="flex items-center gap-2 cursor-pointer mb-3">
                                <input type="checkbox" className="h-4 w-4 rounded border-dark-border bg-dark-elevated text-ey-yellow accent-ey-yellow"
                                  checked={includeAiSummary} onChange={e => setIncludeAiSummary(e.target.checked)} />
                                <span className="text-sm text-gray-300">Include in exported report</span>
                              </label>
                              <button onClick={handlePreviewAiSummary} disabled={previewingSummary || selectedScanIds.length === 0}
                                className="flex items-center gap-2 rounded-lg border border-purple-500/30 bg-purple-500/10 px-3 py-1.5 text-xs text-purple-400 hover:bg-purple-500/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                                {previewingSummary ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                                {previewingSummary ? 'Generating…' : 'Preview Summary'}
                              </button>
                              {aiSummaryPreview && (
                                <div className="mt-3 rounded-lg border border-purple-500/20 bg-purple-500/5 p-3 text-xs text-gray-300 whitespace-pre-wrap leading-relaxed max-h-[200px] overflow-y-auto">
                                  {aiSummaryPreview}
                                </div>
                              )}
                            </div>
                          </div>

                          {/* AI Group Summaries */}
                          <div>
                            <div className="flex items-center justify-between mb-3 border-t border-dark-border pt-5">
                              <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
                                <Sparkles className="h-4 w-4 text-purple-400" /> AI Section Summaries
                              </h3>
                              {groups.length > 0 && (
                                <button onClick={generateAllSummaries} disabled={loadingSummaryFor !== null}
                                  className="flex items-center gap-2 rounded-lg border border-purple-500/30 bg-purple-500/10 px-3 py-1.5 text-xs font-medium text-purple-400 hover:bg-purple-500/20 disabled:opacity-50">
                                  {loadingSummaryFor !== null ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                                  Generate All
                                </button>
                              )}
                            </div>

                            {groups.length === 0 ? (
                              <div className="flex flex-col items-center justify-center py-12 text-dark-muted rounded-xl border-2 border-dashed border-dark-border">
                                <FolderPlus className="h-10 w-10 mb-3 opacity-20" />
                                <p className="text-sm">Create groups in the Organize tab to generate per-section AI summaries</p>
                                <p className="text-xs text-dark-muted mt-1">Summaries are optional</p>
                              </div>
                            ) : (
                              <div className="space-y-3">
                                {groups.map(group => (
                                  <div key={group.name} className="rounded-lg border border-dark-border bg-dark-elevated p-4">
                                    <div className="flex items-center justify-between mb-2">
                                      <div className="flex items-center gap-2">
                                        <h4 className="text-sm font-semibold text-white">{group.name}</h4>
                                        <span className="text-xs text-dark-muted">{group.rule_ids.length} rules</span>
                                      </div>
                                      <button onClick={() => generateGroupSummary(group.name, group.rule_ids)}
                                        disabled={loadingSummaryFor !== null || group.rule_ids.length === 0}
                                        className="flex items-center gap-1 rounded-md border border-purple-500/30 bg-purple-500/10 px-2 py-1 text-xs text-purple-400 hover:bg-purple-500/20 disabled:opacity-50">
                                        {loadingSummaryFor === group.name ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
                                        {groupSummaries[group.name] ? 'Regenerate' : 'Generate'}
                                      </button>
                                    </div>
                                    {groupSummaries[group.name] ? (
                                      <div className="rounded-lg border border-purple-500/20 bg-purple-500/5 p-3">
                                        <textarea
                                          className="w-full bg-transparent text-xs text-gray-300 leading-relaxed resize-y min-h-[60px] max-h-[200px] border-none focus:outline-none focus:ring-0 p-0"
                                          value={groupSummaries[group.name]}
                                          onChange={e => setGroupSummaries(prev => ({ ...prev, [group.name]: e.target.value }))}
                                          rows={3}
                                        />
                                        <button onClick={() => setGroupSummaries(prev => { const n = { ...prev }; delete n[group.name]; return n; })}
                                          className="mt-2 text-xs text-dark-muted hover:text-red-400 transition-colors">Remove summary</button>
                                      </div>
                                    ) : (
                                      <p className="text-xs text-dark-muted italic">No summary yet. Click "Generate" to create an AI summary.</p>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}

                            <div className="mt-4 rounded-lg border border-dark-border bg-dark-card/50 p-3 text-xs text-dark-secondary">
                              <span className="font-medium text-white">Audience:</span>{' '}
                              {AUDIENCES.find(p => p.value === audience)?.label || audience} — AI summaries will be tailored accordingly.
                            </div>
                          </div>
                        </div>
                      )}

                    </div>
                  </div>

                  {/* ═══════════════════════════════════════════════════ */}
                  {/*  EXPORT BAR (Bottom of left pane)                  */}
                  {/* ═══════════════════════════════════════════════════ */}
                  <div className="rounded-xl border border-dark-border bg-dark-card p-5 space-y-4">
                    {/* Row 1: Title, Audience, Checkboxes */}
                    <div className="flex flex-wrap items-end gap-4">
                      <div className="flex-1 min-w-0">
                        <label className="block text-xs font-medium text-dark-secondary mb-1.5">Report Title</label>
                        <input
                          type="text"
                          className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                          placeholder={smartTitle}
                          value={customTitle}
                          onChange={e => setCustomTitle(e.target.value)}
                        />
                      </div>
                      <div className="flex items-center gap-4 pb-0.5">
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input type="checkbox" className="h-4 w-4 rounded border-dark-border bg-dark-elevated text-ey-yellow accent-ey-yellow"
                            checked={includePassedRules} onChange={e => setIncludePassedRules(e.target.checked)} />
                          <span className="text-xs text-gray-300 whitespace-nowrap">Include passed</span>
                        </label>
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input type="checkbox" className="h-4 w-4 rounded border-dark-border bg-dark-elevated text-ey-yellow accent-ey-yellow"
                            checked={includeAiSummary} onChange={e => setIncludeAiSummary(e.target.checked)} />
                          <span className="text-xs text-gray-300 whitespace-nowrap">AI Summary</span>
                        </label>
                        <span className="text-[11px] text-dark-muted border-l border-dark-border pl-3">
                          {AUDIENCES.find(a => a.value === audience)?.icon} {audience}
                        </span>
                      </div>
                    </div>

                    {/* Row 2: Format + Preview + Export */}
                    <div className="flex items-center justify-between flex-wrap gap-3">
                      <div className="flex flex-wrap gap-2">
                        {FORMATS.map(f => {
                          const FIcon = f.icon;
                          return (
                            <button key={f.value} onClick={() => setExportFormat(f.value)} title={f.desc}
                              className={`flex items-center gap-1.5 rounded-lg border-2 px-2.5 py-1.5 text-sm font-medium transition-all ${exportFormat === f.value
                                ? 'border-ey-yellow bg-ey-yellow/10 text-ey-yellow shadow-sm shadow-ey-yellow/10'
                                : 'border-dark-border text-dark-secondary hover:border-dark-secondary hover:text-white'
                                }`}>
                              <FIcon className="h-4 w-4" />
                              <span className="hidden sm:inline">{f.label}</span>
                            </button>
                          );
                        })}
                      </div>
                      <div className="flex gap-2">
                        <button onClick={handleExport} disabled={exporting || selectedCount === 0}
                          className="flex items-center gap-2 rounded-lg bg-ey-yellow px-5 py-2 text-sm font-bold text-black hover:bg-ey-yellow-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                          {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                          {exporting ? 'Exporting…' : `Export ${exportFormat.toUpperCase()}`}
                        </button>
                      </div>

                      {/* Config summary line with page estimate */}
                      <p className="text-[11px] text-dark-muted pt-1 border-t border-dark-border mt-3">
                        {selectedScanIds.length} scan(s) · {selectedCount} rules · {groups.length || 'No'} groups · {audience} audience
                        {Object.keys(groupSummaries).length > 0 && ` · ${Object.keys(groupSummaries).length} AI summaries`}
                        {exportFormat === 'pdf' && selectedCount > 0 && (
                          <span className="ml-2 text-ey-yellow font-medium">
                            ≈ {Math.max(5, Math.ceil(selectedCount * 0.45) + 8 + (includePassedRules ? Math.ceil((findings.filter(f => f.status === 'PASS').length || 0) * 0.3) : 0))} pages
                          </span>
                        )}
                      </p>
                    </div>
                    {/* End Export Bar */}
                  </div>
                </div>
                {/* End Left Pane */}

                {/* Right Pane: Live Preview */}
                  <div className="flex-1 w-full xl:w-7/12 flex flex-col border border-dark-border bg-dark-card rounded-xl overflow-hidden sticky top-6 shadow-xl" style={{ height: 'calc(100vh - 150px)' }}>
                    <div className="flex items-center justify-between p-4 border-b border-dark-border bg-dark-elevated shrink-0">
                      <div className="flex items-center gap-3">
                        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                          <Eye className="h-4 w-4 text-ey-yellow" /> Live Preview
                        </h3>
                        {loadingPreview && (
                          <span className="flex items-center gap-1.5 rounded-full bg-ey-yellow/10 px-2 py-0.5 text-[10px] font-medium text-ey-yellow font-mono">
                            <Loader2 className="h-3 w-3 animate-spin" /> updating...
                          </span>
                        )}
                      </div>
                      <button onClick={handlePreview} disabled={loadingPreview} className="text-xs text-dark-secondary hover:text-white transition-colors flex items-center gap-1">
                        <RefreshCw className={`h-3.5 w-3.5 ${loadingPreview ? 'animate-spin' : ''}`} /> Refresh
                      </button>
                    </div>
                    <div className="flex-1 w-full relative bg-[#0B0F19]">
                      {!previewHtml ? (
                        <div className="absolute inset-0 flex flex-col items-center justify-center text-dark-muted p-10 text-center">
                          <FileText className="h-10 w-10 mb-4 opacity-15" />
                          <p className="text-sm">Configuring report...</p>
                          <p className="text-xs text-dark-muted mt-1">Live preview will appear momentarily</p>
                        </div>
                      ) : (
                        <iframe
                          srcDoc={previewHtml}
                          title="Live Report Preview"
                          className={`w-full h-full border-0 transition-opacity duration-300 ${loadingPreview ? 'opacity-50' : 'opacity-100'}`}
                          style={{ backgroundColor: 'white' }}
                          sandbox="allow-scripts allow-same-origin"
                        />
                      )}
                    </div>
                  </div>

                </div>
              {/* End Split Pane Layout */}
            </>
          )}
        </>
      )}
    </div>
  );
}
