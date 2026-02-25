import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import {
  Save, CheckCircle2, XCircle, Download, Upload, Database,
  AlertTriangle, Zap, Loader2, Trash2,
} from 'lucide-react';
import type { Settings as SettingsType, LLMTestResult } from '@/types';
import * as api from '@/services/api';

const defaultSettings: SettingsType = {
  llm_mode: 'offline',
  llm_offline_model: '',
  llm_ollama_url: '',
  llm_online_provider: '',
  llm_online_model: '',
  llm_online_base_url: '',
  llm_online_api_key_encrypted: '',
  verification_enabled: 'true',
  verification_auto_protect_passing: 'false',
  default_scan_mode: 'network',
  llm_task_phase1_parsing_model: '',
  llm_task_phase2_commands_model: '',
  llm_task_verification_model: '',
  llm_task_reports_model: '',
  llm_task_analysis_model: '',
};

const TASK_FIELDS = [
  { key: 'llm_task_phase1_parsing_model', label: 'Phase 1 — Rule Parsing', help: 'Extracts CIS rules from PDF benchmark' },
  { key: 'llm_task_phase2_commands_model', label: 'Phase 2 — Command Generation', help: 'Generates audit commands and regex' },
  { key: 'llm_task_verification_model', label: 'Verification', help: 'Verifies command quality' },
  { key: 'llm_task_reports_model', label: 'Reports & AI Advice', help: 'Executive summaries, remediation advice' },
  { key: 'llm_task_analysis_model', label: 'Post-Mission Analysis', help: 'Cross-target/mission comparison' },
] as const;

export default function Settings() {
  const [settings, setSettings] = useState<SettingsType>(defaultSettings);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [backingUp, setBackingUp] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [showRestoreConfirm, setShowRestoreConfirm] = useState(false);
  const [testingLLM, setTestingLLM] = useState(false);
  const [llmTestResult, setLlmTestResult] = useState<LLMTestResult | null>(null);
  const restoreFileRef = useRef<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const location = useLocation();

  /* Cache stats */
  const [cacheStats, setCacheStats] = useState<{ total_entries: number; total_hits: number } | null>(null);

  useEffect(() => {
    if (location.pathname !== '/settings') return;
    (async () => {
      try {
        const [data, cache] = await Promise.all([api.getSettings(), api.getCacheStats().catch(() => null)]);
        setSettings({ ...defaultSettings, ...data });
        if (cache) setCacheStats(cache);
      } catch {
        // keep defaults
      } finally {
        setLoading(false);
      }
    })();
  }, [location.pathname]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(timer);
  }, [toast]);

  const handleChange = (key: string, value: string) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateSettings(settings);
      setToast({ type: 'success', message: 'Settings saved successfully' });
    } catch {
      setToast({ type: 'error', message: 'Failed to save settings' });
    } finally {
      setSaving(false);
    }
  };

  const handleTestLLM = async () => {
    setTestingLLM(true);
    setLlmTestResult(null);
    try {
      const result = await api.testLLM();
      setLlmTestResult(result);
    } catch {
      setLlmTestResult({ success: false, error: 'Failed to reach backend. Is the server running?', response: null, response_time_ms: 0 });
    } finally {
      setTestingLLM(false);
    }
  };

  const handleBackup = async () => {
    setBackingUp(true);
    try {
      const blob = await api.createBackup();
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      const filename = `auditforge_backup_${timestamp}.db`;
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      setToast({ type: 'success', message: 'Backup downloaded successfully' });
    } catch {
      setToast({ type: 'error', message: 'Failed to create backup' });
    } finally {
      setBackingUp(false);
    }
  };

  const handleRestoreFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    restoreFileRef.current = file;
    setShowRestoreConfirm(true);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleRestoreConfirm = async () => {
    const file = restoreFileRef.current;
    if (!file) return;
    setShowRestoreConfirm(false);
    setRestoring(true);
    try {
      const result = await api.restoreBackup(file);
      setToast({ type: 'success', message: `${result.message} (${result.tables_restored} tables)` });
    } catch {
      setToast({ type: 'error', message: 'Failed to restore backup' });
    } finally {
      setRestoring(false);
      restoreFileRef.current = null;
    }
  };

  const handleClearCache = async () => {
    try {
      const r = await api.clearLLMCache();
      setToast({ type: 'success', message: `Cleared ${r.deleted} cache entries` });
      setCacheStats({ total_entries: 0, total_hits: cacheStats?.total_hits ?? 0 });
    } catch {
      setToast({ type: 'error', message: 'Clear cache failed' });
    }
  };

  const inputClass = 'mt-1 block w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none';
  const selectClass = inputClass;
  const labelClass = 'block text-sm font-medium text-gray-300';
  const helpClass = 'mt-1 text-xs text-dark-muted';
  const codeClass = 'rounded bg-dark-elevated px-1 text-ey-yellow/80 font-mono text-[11px]';

  if (loading) {
    return <div className="flex items-center justify-center py-12 text-dark-secondary">Loading…</div>;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {toast && (
        <div
          className={`flex items-center gap-2 rounded-lg border p-3 text-sm ${
            toast.type === 'success'
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
              : 'border-red-500/30 bg-red-500/10 text-red-400'
          }`}
        >
          {toast.type === 'success' ? (
            <CheckCircle2 className="h-4 w-4" />
          ) : (
            <XCircle className="h-4 w-4" />
          )}
          {toast.message}
        </div>
      )}

      {/* LLM Configuration */}
      <section className="rounded-xl border border-dark-border bg-dark-card p-6 space-y-4">
        <h3 className="text-lg font-semibold text-white">LLM Configuration</h3>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-gray-300">LLM Mode</legend>
          <div className="flex gap-6">
            {['offline', 'online'].map((mode) => (
              <label key={mode} className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                <input
                  type="radio"
                  name="llm_mode"
                  value={mode}
                  checked={settings.llm_mode === mode}
                  onChange={() => handleChange('llm_mode', mode)}
                  className="text-ey-yellow focus:ring-ey-yellow/50 accent-ey-yellow"
                />
                {mode === 'offline' ? 'Offline (Ollama)' : 'Online (Cloud API)'}
              </label>
            ))}
          </div>
          <p className={helpClass}>
            {settings.llm_mode === 'offline'
              ? 'Uses a local Ollama instance. You can run cloud models through Ollama too \u2014 see the setup guide.'
              : 'Connects directly to a cloud API (OpenAI, Mistral, Groq, OpenRouter, or any OpenAI-compatible endpoint).'}
          </p>
        </fieldset>

        {/* Offline (Ollama) Settings */}
        {settings.llm_mode === 'offline' && (
          <>
            <div>
              <label className={labelClass}>Ollama Model</label>
              <input
                value={settings.llm_offline_model}
                onChange={(e) => handleChange('llm_offline_model', e.target.value)}
                className={inputClass}
                placeholder="e.g. qwen2.5:7b, mistral, llama3.1:8b"
              />
              <p className={helpClass}>
                The model tag as shown by <code className={codeClass}>ollama list</code>.
                Default: <code className={codeClass}>qwen2.5:7b</code>
              </p>
            </div>

            <div>
              <label className={labelClass}>Ollama URL</label>
              <input
                value={settings.llm_ollama_url}
                onChange={(e) => handleChange('llm_ollama_url', e.target.value)}
                className={inputClass}
                placeholder="http://localhost:11434"
              />
              <p className={helpClass}>
                Default: <code className={codeClass}>http://localhost:11434</code>.
                Use <code className={codeClass}>http://host.docker.internal:11434</code> if
                running inside Docker.
              </p>
            </div>
          </>
        )}

        {/* Online (Cloud API) Settings */}
        {settings.llm_mode === 'online' && (
          <>
            <div>
              <label className={labelClass}>Provider</label>
              <select
                value={settings.llm_online_provider}
                onChange={(e) => handleChange('llm_online_provider', e.target.value)}
                className={selectClass}
              >
                <option value="">Select a provider\u2026</option>
                <option value="openai">OpenAI</option>
                <option value="mistral">Mistral AI</option>
                <option value="groq">Groq</option>
                <option value="openrouter">OpenRouter</option>
                <option value="custom">Custom (OpenAI-compatible)</option>
              </select>
            </div>

            <div>
              <label className={labelClass}>API Key</label>
              <input
                type="password"
                value={settings.llm_online_api_key_encrypted}
                onChange={(e) => handleChange('llm_online_api_key_encrypted', e.target.value)}
                className={inputClass}
                placeholder="sk-\u2026"
              />
              <p className={helpClass}>
                Your API key for the selected provider. Stored in the local database.
              </p>
            </div>

            <div>
              <label className={labelClass}>Model</label>
              <input
                value={settings.llm_online_model}
                onChange={(e) => handleChange('llm_online_model', e.target.value)}
                className={inputClass}
                placeholder={
                  settings.llm_online_provider === 'openai'
                    ? 'e.g. gpt-4o, gpt-4o-mini'
                    : settings.llm_online_provider === 'mistral'
                    ? 'e.g. mistral-large-latest'
                    : settings.llm_online_provider === 'groq'
                    ? 'e.g. llama-3.1-70b-versatile'
                    : settings.llm_online_provider === 'openrouter'
                    ? 'e.g. meta-llama/llama-3.1-70b-instruct'
                    : 'e.g. gpt-4o'
                }
              />
            </div>

            {settings.llm_online_provider === 'custom' && (
              <div>
                <label className={labelClass}>Custom Base URL</label>
                <input
                  value={settings.llm_online_base_url}
                  onChange={(e) => handleChange('llm_online_base_url', e.target.value)}
                  className={inputClass}
                  placeholder="https://your-endpoint.com/v1"
                />
                <p className={helpClass}>
                  Full base URL for the OpenAI-compatible API (must support <code className={codeClass}>/chat/completions</code>).
                </p>
              </div>
            )}
          </>
        )}

        {/* Test LLM Connection */}
        <div className="border-t border-dark-border pt-4">
          <button
            onClick={handleTestLLM}
            disabled={testingLLM}
            className="inline-flex items-center gap-2 rounded-lg border border-ey-yellow/30 bg-ey-yellow/10 px-4 py-2 text-sm font-medium text-ey-yellow hover:bg-ey-yellow/20 disabled:opacity-50"
          >
            {testingLLM ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
            {testingLLM ? 'Testing\u2026' : 'Test LLM Connection'}
          </button>

          {llmTestResult && (
            <div
              className={`mt-3 rounded-lg border p-3 text-sm ${
                llmTestResult.success
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                  : 'border-red-500/30 bg-red-500/10 text-red-400'
              }`}
            >
              {llmTestResult.success ? (
                <div className="space-y-1">
                  <div className="flex items-center gap-2 font-medium">
                    <CheckCircle2 className="h-4 w-4" /> LLM is working
                  </div>
                  <div>Model: <code className={codeClass}>{llmTestResult.model}</code></div>
                  <div>Response time: <strong>{llmTestResult.response_time_ms}ms</strong></div>
                  <div className="text-xs text-emerald-500/70 italic">&quot;{llmTestResult.response}&quot;</div>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <XCircle className="h-4 w-4" />
                  {llmTestResult.error || 'Connection failed'}
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {/* Per-Task Model Overrides */}
      <section className="rounded-xl border border-dark-border bg-dark-card p-6 space-y-4">
        <h3 className="text-lg font-semibold text-white">Per-Task Model Overrides</h3>
        <p className="text-sm text-dark-secondary">
          Optionally use a different model for specific tasks. Leave empty to use the global model configured above.
          {settings.llm_mode === 'offline'
            ? ' Enter an Ollama model tag (e.g. qwen2.5:14b).'
            : ' Enter a cloud model name (e.g. gpt-4o, mistral-large-latest).'}
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {TASK_FIELDS.map((field) => (
            <div key={field.key}>
              <label className={labelClass}>{field.label}</label>
              <input
                value={settings[field.key] || ''}
                onChange={(e) => handleChange(field.key, e.target.value)}
                className={inputClass}
                placeholder="(use global model)"
              />
              <p className={helpClass}>{field.help}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Verification */}
      <section className="rounded-xl border border-dark-border bg-dark-card p-6 space-y-4">
        <h3 className="text-lg font-semibold text-white">Verification</h3>

        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={settings.verification_enabled === 'true'}
            onChange={(e) => handleChange('verification_enabled', e.target.checked ? 'true' : 'false')}
            className="h-4 w-4 rounded border-dark-border bg-dark-elevated text-ey-yellow focus:ring-ey-yellow/50 accent-ey-yellow"
          />
          <span className="text-sm text-gray-300">Enable verification</span>
        </label>

        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={settings.verification_auto_protect_passing === 'true'}
            onChange={(e) =>
              handleChange('verification_auto_protect_passing', e.target.checked ? 'true' : 'false')
            }
            className="h-4 w-4 rounded border-dark-border bg-dark-elevated text-ey-yellow focus:ring-ey-yellow/50 accent-ey-yellow"
          />
          <span className="text-sm text-gray-300">Auto-protect passing checks</span>
        </label>
      </section>

      {/* Scan Defaults */}
      <section className="rounded-xl border border-dark-border bg-dark-card p-6 space-y-4">
        <h3 className="text-lg font-semibold text-white">Scan Defaults</h3>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-gray-300">Default Scan Mode</legend>
          <div className="flex gap-6">
            {['network', 'script_export'].map((mode) => (
              <label key={mode} className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
                <input
                  type="radio"
                  name="default_scan_mode"
                  value={mode}
                  checked={settings.default_scan_mode === mode}
                  onChange={() => handleChange('default_scan_mode', mode)}
                  className="text-ey-yellow focus:ring-ey-yellow/50 accent-ey-yellow"
                />
                {mode === 'network' ? 'Network' : 'Script Export'}
              </label>
            ))}
          </div>
        </fieldset>
      </section>

      {/* LLM Cache */}
      {cacheStats && (
        <section className="rounded-xl border border-dark-border bg-dark-card p-6 space-y-4">
          <h3 className="text-lg font-semibold text-white">LLM Cache</h3>
          <div className="flex items-center gap-6">
            <div>
              <p className="text-2xl font-bold text-white">{cacheStats.total_entries}</p>
              <p className="text-xs text-dark-muted">cached entries</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-white">{cacheStats.total_hits}</p>
              <p className="text-xs text-dark-muted">total hits</p>
            </div>
            <button
              onClick={handleClearCache}
              className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-dark-secondary hover:bg-dark-overlay hover:text-white"
            >
              <Trash2 className="h-3.5 w-3.5" /> Clear Cache
            </button>
          </div>
        </section>
      )}

      {/* Database Backup & Restore */}
      <section className="rounded-xl border border-dark-border bg-dark-card p-6 space-y-4">
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-ey-yellow" />
          <h3 className="text-lg font-semibold text-white">Database Backup &amp; Restore</h3>
        </div>
        <p className="text-sm text-dark-secondary">
          Create a full backup of your AuditForge database or restore from a previous backup.
        </p>

        <div className="flex flex-col gap-3 sm:flex-row">
          <button
            onClick={handleBackup}
            disabled={backingUp}
            className="inline-flex items-center gap-2 rounded-lg border border-dark-border bg-dark-elevated px-4 py-2 text-sm font-medium text-gray-300 hover:bg-dark-overlay hover:text-white disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            {backingUp ? 'Creating backup\u2026' : 'Download Backup'}
          </button>

          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-dark-border bg-dark-elevated px-4 py-2 text-sm font-medium text-gray-300 hover:bg-dark-overlay hover:text-white">
            <Upload className="h-4 w-4" />
            {restoring ? 'Restoring\u2026' : 'Restore from Backup'}
            <input
              ref={fileInputRef}
              type="file"
              accept=".db,.sqlite,.sqlite3,.backup"
              className="hidden"
              onChange={handleRestoreFileSelect}
              disabled={restoring}
            />
          </label>
        </div>

        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-400 flex-shrink-0" />
            <p className="text-xs text-amber-300/90">
              Restoring a backup will replace <strong>all current data</strong>. A safety backup of the
              current database will be created automatically. The application should be restarted after
              restoring.
            </p>
          </div>
        </div>
      </section>

      {/* Restore Confirmation Dialog */}
      {showRestoreConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="mx-4 w-full max-w-md rounded-xl border border-dark-border bg-dark-card p-6 shadow-2xl">
            <div className="flex items-center gap-3 mb-4">
              <AlertTriangle className="h-6 w-6 text-amber-400" />
              <h4 className="text-lg font-semibold text-white">Confirm Restore</h4>
            </div>
            <p className="text-sm text-gray-300 mb-2">
              Are you sure you want to restore the database from{' '}
              <strong className="text-white">{restoreFileRef.current?.name}</strong>?
            </p>
            <p className="text-sm text-red-400 mb-4">
              This will replace all current data. A safety backup will be created first.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => { setShowRestoreConfirm(false); restoreFileRef.current = null; }}
                className="rounded-lg border border-dark-border px-4 py-2 text-sm font-medium text-gray-300 hover:bg-dark-elevated"
              >
                Cancel
              </button>
              <button
                onClick={handleRestoreConfirm}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
              >
                Restore
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex justify-end">
        <button
          onClick={handleSave}
          disabled={saving}
          className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-6 py-2.5 text-sm font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50"
        >
          <Save className="h-4 w-4" />
          {saving ? 'Saving\u2026' : 'Save Settings'}
        </button>
      </div>
    </div>
  );
}
