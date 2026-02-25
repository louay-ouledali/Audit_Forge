import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import {
  BarChart3,
  Download,
  FileText,
  FileSpreadsheet,
  FileCode2,
  Globe,
  Loader2,
  Sparkles,
} from 'lucide-react';
import type { ScanDetail, Client, Mission, Target, ReportGenerateRequest } from '@/types';
import * as api from '@/services/api';

const FORMAT_OPTIONS = [
  { value: 'pdf', label: 'PDF Report', icon: FileText, description: 'Professional PDF with charts and badges' },
  { value: 'excel', label: 'Excel Workbook', icon: FileSpreadsheet, description: 'Multi-sheet Excel with filters' },
  { value: 'csv', label: 'CSV Export', icon: FileCode2, description: 'Flat CSV of all findings' },
  { value: 'html', label: 'HTML Dashboard', icon: Globe, description: 'Interactive self-contained HTML' },
] as const;

const SCOPE_OPTIONS = [
  { value: 'scan', label: 'Single Scan', description: 'All findings from one scan' },
  { value: 'target', label: 'Target Summary', description: 'All scans for one target' },
  { value: 'mission', label: 'Mission Report', description: 'All targets in a mission' },
  { value: 'custom', label: 'Multi-Scan', description: 'Select multiple scans to combine' },
] as const;

const FILE_EXTENSIONS: Record<string, string> = { pdf: 'pdf', excel: 'xlsx', csv: 'csv', html: 'html' };
const CONTENT_TYPES: Record<string, string> = {
  pdf: 'application/pdf',
  excel: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  csv: 'text/csv',
  html: 'text/html',
};

export default function Reports() {
  const [format, setFormat] = useState<string>('pdf');
  const [scope, setScope] = useState<string>('scan');
  const [scopeId, setScopeId] = useState<number | ''>('');

  const [includeAiSummary, setIncludeAiSummary] = useState(false);
  const [includePassedRules, setIncludePassedRules] = useState(true);
  const [customTitle, setCustomTitle] = useState('');
  const [selectedScanIds, setSelectedScanIds] = useState<number[]>([]);

  const [generating, setGenerating] = useState(false);
  const [previewingSummary, setPreviewingSummary] = useState(false);
  const [aiSummaryPreview, setAiSummaryPreview] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const [scans, setScans] = useState<ScanDetail[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<number | ''>('');
  const [selectedMissionId, setSelectedMissionId] = useState<number | ''>('');
  const location = useLocation();

  const selectClass = 'w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none';

  useEffect(() => {
    if (location.pathname === '/reports') {
      api.getScans().then((res) => setScans(res.data)).catch(() => setError('Failed to load scans'));
      api.getClients().then((res) => setClients(res)).catch(() => setError('Failed to load clients'));
    }
  }, [location.pathname]);

  useEffect(() => {
    if (selectedClientId) {
      api.getMissions(selectedClientId as number).then(setMissions).catch(() => {});
    } else {
      setMissions([]);
    }
    setSelectedMissionId('');
    setTargets([]);
    setScopeId('');
  }, [selectedClientId]);

  useEffect(() => {
    if (selectedMissionId) {
      api.getTargets(selectedMissionId as number).then(setTargets).catch(() => {});
      if (scope === 'mission') setScopeId(selectedMissionId as number);
    } else {
      setTargets([]);
    }
  }, [selectedMissionId, scope]);

  useEffect(() => {
    setScopeId('');
    setSelectedScanIds([]);
  }, [scope]);

  async function handleGenerate() {
    if (scope === 'custom') {
      if (selectedScanIds.length === 0) { setError('Please select at least one scan.'); return; }
    } else if (!scopeId) {
      setError('Please select a scope item.'); return;
    }
    setError(''); setSuccess(''); setGenerating(true);
    try {
      const payload: ReportGenerateRequest = {
        scope: scope as ReportGenerateRequest['scope'],
        scope_id: scope !== 'custom' ? (scopeId as number) : undefined,
        scan_ids: scope === 'custom' ? selectedScanIds : undefined,
        format: format as ReportGenerateRequest['format'],
        include_ai_summary: includeAiSummary,
        include_passed_rules: includePassedRules,
        title: customTitle || undefined,
      };
      const blob = await api.generateReport(payload);
      const ext = FILE_EXTENSIONS[format] || 'bin';
      const filename = `report.${ext}`;
      const url = URL.createObjectURL(new Blob([blob], { type: CONTENT_TYPES[format] }));
      const a = document.createElement('a'); a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
      setSuccess(`Report generated and downloaded as ${filename}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Report generation failed');
    } finally {
      setGenerating(false);
    }
  }

  async function handlePreviewAISummary() {
    if (!scopeId) { setError('Please select a scope item first.'); return; }
    setError(''); setPreviewingSummary(true);
    try {
      const result = await api.generateAISummary({
        scope: scope as 'scan' | 'target' | 'mission',
        scope_id: scopeId as number,
      });
      setAiSummaryPreview(result.summary);
    } catch {
      setError('Failed to generate AI summary. Check LLM configuration.');
    } finally {
      setPreviewingSummary(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Report Builder</h1>
          <p className="mt-1 text-sm text-dark-secondary">Generate audit reports in multiple formats</p>
        </div>
        <BarChart3 className="h-8 w-8 text-ey-yellow/60" />
      </div>

      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">{error}</div>}
      {success && <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-400">{success}</div>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left: Configuration */}
        <div className="lg:col-span-2 space-y-6">
          {/* Format Selection — Card Grid */}
          <div className="rounded-xl border border-dark-border bg-dark-card p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">Report Format</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {FORMAT_OPTIONS.map((opt) => {
                const Icon = opt.icon;
                return (
                  <button
                    key={opt.value}
                    onClick={() => setFormat(opt.value)}
                    className={`flex flex-col items-center rounded-lg border-2 p-4 transition-all ${
                      format === opt.value
                        ? 'border-ey-yellow bg-ey-yellow/10 text-ey-yellow'
                        : 'border-dark-border bg-dark-elevated text-dark-secondary hover:border-dark-secondary'
                    }`}
                  >
                    <Icon className="mb-2 h-6 w-6" />
                    <span className="text-sm font-medium">{opt.label}</span>
                    <span className="mt-1 text-center text-xs text-dark-muted">{opt.description}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Scope Selection — Card Grid */}
          <div className="rounded-xl border border-dark-border bg-dark-card p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">Report Scope</h2>
            <div className="grid grid-cols-2 gap-3 mb-4 sm:grid-cols-4">
              {SCOPE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setScope(opt.value)}
                  className={`rounded-lg border-2 p-3 text-left transition-all ${
                    scope === opt.value
                      ? 'border-ey-yellow bg-ey-yellow/10'
                      : 'border-dark-border hover:border-dark-secondary'
                  }`}
                >
                  <span className={`block text-sm font-medium ${scope === opt.value ? 'text-ey-yellow' : 'text-white'}`}>{opt.label}</span>
                  <span className="block text-xs text-dark-muted">{opt.description}</span>
                </button>
              ))}
            </div>

            {/* Scope-specific selection */}
            {scope === 'scan' && (
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Select Scan</label>
                <select className={selectClass} value={scopeId} onChange={(e) => setScopeId(e.target.value ? Number(e.target.value) : '')}>
                  <option value="">Select a scan...</option>
                  {scans.map((s) => (
                    <option key={s.id} value={s.id}>
                      Scan #{s.id} \u2014 {s.scan_mode} ({s.status}) \u2014 {s.compliance_percentage != null ? `${s.compliance_percentage}%` : 'N/A'}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {(scope === 'target' || scope === 'mission') && (
              <div className="space-y-3">
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-300">Client</label>
                  <select className={selectClass} value={selectedClientId} onChange={(e) => setSelectedClientId(e.target.value ? Number(e.target.value) : '')}>
                    <option value="">Select a client...</option>
                    {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-300">Mission</label>
                  <select className={selectClass} value={selectedMissionId} onChange={(e) => { const val = e.target.value ? Number(e.target.value) : ''; setSelectedMissionId(val); if (scope === 'mission' && val) setScopeId(val); }}>
                    <option value="">Select a mission...</option>
                    {missions.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.status})</option>)}
                  </select>
                </div>
                {scope === 'target' && (
                  <div>
                    <label className="mb-1 block text-sm font-medium text-gray-300">Target</label>
                    <select className={selectClass} value={scopeId} onChange={(e) => setScopeId(e.target.value ? Number(e.target.value) : '')}>
                      <option value="">Select a target...</option>
                      {targets.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.hostname || t.ip_address || `Target #${t.id}`} ({t.target_type})
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
            )}

            {/* Custom multi-scan selector */}
            {scope === 'custom' && (
              <div>
                <label className="mb-2 block text-sm font-medium text-gray-300">
                  Select Scans ({selectedScanIds.length} selected)
                </label>
                {scans.length === 0 ? (
                  <p className="text-sm text-dark-secondary">No completed scans available.</p>
                ) : (
                  <div className="max-h-56 overflow-y-auto rounded-lg border border-dark-border divide-y divide-dark-border">
                    {scans.filter(s => s.status === 'completed').map((s) => (
                      <label
                        key={s.id}
                        className={`flex items-center gap-3 px-3 py-2.5 cursor-pointer transition-colors ${
                          selectedScanIds.includes(s.id) ? 'bg-ey-yellow/10' : 'hover:bg-dark-elevated'
                        }`}
                      >
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-dark-border bg-dark-elevated text-ey-yellow focus:ring-ey-yellow/50 accent-ey-yellow"
                          checked={selectedScanIds.includes(s.id)}
                          onChange={(e) => {
                            if (e.target.checked) setSelectedScanIds(prev => [...prev, s.id]);
                            else setSelectedScanIds(prev => prev.filter(id => id !== s.id));
                          }}
                        />
                        <div className="flex-1 min-w-0">
                          <span className="text-sm font-medium text-white">Scan #{s.id}</span>
                          <span className="ml-2 text-xs text-dark-secondary">{s.scan_mode}</span>
                          {s.compliance_percentage != null && (
                            <span className={`ml-2 text-xs font-semibold ${
                              s.compliance_percentage >= 80 ? 'text-emerald-400' : s.compliance_percentage >= 50 ? 'text-yellow-400' : 'text-red-400'
                            }`}>
                              {s.compliance_percentage}%
                            </span>
                          )}
                        </div>
                      </label>
                    ))}
                  </div>
                )}
                {selectedScanIds.length > 0 && (
                  <button onClick={() => setSelectedScanIds([])} className="mt-2 text-xs text-ey-yellow hover:text-ey-yellow-hover">
                    Clear selection
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Options */}
          <div className="rounded-xl border border-dark-border bg-dark-card p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">Options</h2>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Report Title (optional)</label>
                <input
                  type="text"
                  className="w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none"
                  placeholder="e.g. Q1 2026 Acme Corp Audit"
                  value={customTitle}
                  onChange={(e) => setCustomTitle(e.target.value)}
                />
              </div>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-dark-border bg-dark-elevated text-ey-yellow focus:ring-ey-yellow/50 accent-ey-yellow"
                  checked={includePassedRules}
                  onChange={(e) => setIncludePassedRules(e.target.checked)}
                />
                <span className="text-sm text-gray-300">Include passed rules in the report</span>
              </label>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-dark-border bg-dark-elevated text-ey-yellow focus:ring-ey-yellow/50 accent-ey-yellow"
                  checked={includeAiSummary}
                  onChange={(e) => setIncludeAiSummary(e.target.checked)}
                />
                <span className="text-sm text-gray-300">Include AI-generated executive summary</span>
              </label>
            </div>
          </div>
        </div>

        {/* Right: Actions & Preview */}
        <div className="space-y-6">
          {/* Generate Button */}
          <div className="rounded-xl border border-dark-border bg-dark-card p-6">
            <button
              onClick={handleGenerate}
              disabled={generating || (scope === 'custom' ? selectedScanIds.length === 0 : !scopeId)}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-ey-yellow px-4 py-3 text-sm font-medium text-black transition-colors hover:bg-ey-yellow-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {generating ? <Loader2 className="h-5 w-5 animate-spin" /> : <Download className="h-5 w-5" />}
              {generating ? 'Generating...' : 'Generate Report'}
            </button>
            <p className="mt-2 text-center text-xs text-dark-muted">
              {format.toUpperCase()} \u00B7 {SCOPE_OPTIONS.find((o) => o.value === scope)?.label}
              {scope === 'custom' ? ` \u00B7 ${selectedScanIds.length} scans` : scopeId ? ` \u00B7 ID: ${scopeId}` : ''}
            </p>
          </div>

          {/* AI Summary Preview */}
          <div className="rounded-xl border border-dark-border bg-dark-card p-6">
            <h3 className="mb-3 text-sm font-semibold text-white">AI Executive Summary</h3>
            <p className="mb-3 text-xs text-dark-muted">
              Preview the AI-generated executive summary before including it in the report.
            </p>
            <button
              onClick={handlePreviewAISummary}
              disabled={previewingSummary || !scopeId}
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-purple-500/30 bg-purple-500/10 px-4 py-2 text-sm font-medium text-purple-400 transition-colors hover:bg-purple-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {previewingSummary ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {previewingSummary ? 'Generating...' : 'Preview AI Summary'}
            </button>
            {aiSummaryPreview && (
              <div className="mt-3 rounded-lg border border-purple-500/20 bg-purple-500/5 p-3 text-xs text-gray-300 whitespace-pre-wrap">
                {aiSummaryPreview}
              </div>
            )}
          </div>

          {/* Format Guide */}
          <div className="rounded-xl border border-dark-border bg-dark-elevated p-6">
            <h3 className="mb-2 text-sm font-semibold text-white">Format Guide</h3>
            <ul className="space-y-2 text-xs text-dark-secondary">
              <li><strong className="text-gray-300">PDF</strong> \u2014 Professional A4 layout with cover page, SVG charts (donut, severity bars, per-target compliance), severity badges, and detailed finding cards. Best for sharing with clients.</li>
              <li><strong className="text-gray-300">Excel</strong> \u2014 4 sheets: Executive Summary, Findings, Compliance by Target, Compliance by Category. With auto-filters and color coding.</li>
              <li><strong className="text-gray-300">CSV</strong> \u2014 Flat export for further processing in any tool.</li>
              <li><strong className="text-gray-300">HTML</strong> \u2014 Interactive dashboard with Chart.js charts, live search, multi-filter, grouping, sortable columns, and expandable detail rows.</li>
            </ul>
            <div className="mt-3 pt-3 border-t border-dark-border">
              <h4 className="text-xs font-semibold text-gray-300 mb-1">Multi-Scan Scope</h4>
              <p className="text-xs text-dark-muted">Use the "Multi-Scan" scope to combine findings from multiple scans into a single report. Great for comparing results across targets or benchmarks.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
