import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useLocation } from 'react-router-dom';
import {
  Save, CheckCircle2, XCircle, Download, Upload, Database,
  AlertTriangle, Zap, Loader2, Trash2, Mail, Building2, KeyRound, Image as ImageIcon, RefreshCw
} from 'lucide-react';
import type { Settings as SettingsType, LLMTestResult } from '@/types';
import * as api from '@/services/api';
import { changePassword } from '@/services/auth';

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
  ui_theme: 'dark',
  smtp_host: '',
  smtp_port: '',
  smtp_username: '',
  smtp_password: '',
  smtp_from: '',
  smtp_use_tls: 'true',
  base_url: '',
  company_name: '',
  company_logo_base64: '',
  auditor_name: '',
  llm_max_tokens: '4096',
  llm_token_budget: '0',
};

const applyTheme = (theme: string) => {
  const normalized = theme === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', normalized);
  localStorage.setItem('auditforge_theme', normalized);
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

  /* Model picker */
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsFetchError, setModelsFetchError] = useState('');

  /* Reset preloaded benchmarks */
  const [resettingPreloaded, setResettingPreloaded] = useState(false);
  const [showResetPreloadedConfirm, setShowResetPreloadedConfirm] = useState(false);

  /* Token usage */
  const [tokenUsage, setTokenUsage] = useState<api.TokenUsageStats | null>(null);

  /* Password change */
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [changingPw, setChangingPw] = useState(false);

  /* Logo preview */
  const logoInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (location.pathname !== '/settings') return;
    (async () => {
      try {
        const [data, cache] = await Promise.all([api.getSettings(), api.getCacheStats().catch(() => null)]);

        // Also fetch token usage stats
        api.getTokenUsage('month').then(u => setTokenUsage(u)).catch(() => {});
        
        // Load ui_theme straight from localStorage since backend might not store it yet
        const localTheme = localStorage.getItem('auditforge_theme') || 'dark';

        const merged = { ...defaultSettings, ...data, ui_theme: localTheme };
        setSettings(merged);
        applyTheme(merged.ui_theme);
        if (cache) setCacheStats(cache);
      } catch {
        // keep defaults
        const localTheme = localStorage.getItem('auditforge_theme') || 'dark';
        applyTheme(localTheme);
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
    if (key === 'ui_theme') {
      applyTheme(value);
    }
    // Clear fetched models when switching mode or provider
    if (key === 'llm_mode' || key === 'llm_online_provider') {
      setAvailableModels([]);
      setModelsFetchError('');
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateSettings(settings);
      setToast({ type: 'success', message: 'Settings saved successfully' });
    } catch (err: any) {
      const detail = err?.response?.data?.detail || 'Failed to save settings';
      setToast({ type: 'error', message: detail });
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
    } catch (err: unknown) {
      let msg = 'Failed to restore backup';
      if (err && typeof err === 'object' && 'response' in err) {
        const axiosErr = err as { response?: { data?: { detail?: string } } };
        if (axiosErr.response?.data?.detail) msg = axiosErr.response.data.detail;
      } else if (err instanceof Error) {
        msg = err.message;
      }
      setToast({ type: 'error', message: msg });
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

  const handleFetchModels = async () => {
    setModelsLoading(true);
    setModelsFetchError('');
    try {
      const result = await api.fetchAvailableModels();
      if (result.error) {
        setModelsFetchError(result.error);
        setAvailableModels([]);
      } else {
        setAvailableModels(result.models);
      }
    } catch {
      setModelsFetchError('Could not fetch models');
      setAvailableModels([]);
    } finally {
      setModelsLoading(false);
    }
  };

  const fetchTokenUsage = async () => {
    try {
      const usage = await api.getTokenUsage('month');
      setTokenUsage(usage);
    } catch { /* silent */ }
  };

  const handleResetTokenUsage = async () => {
    try {
      await api.resetTokenUsage();
      setTokenUsage(null);
      setToast({ type: 'success', message: 'Token usage stats cleared' });
      fetchTokenUsage();
    } catch {
      setToast({ type: 'error', message: 'Failed to reset token usage' });
    }
  };

  const handleResetPreloaded = async () => {
    setResettingPreloaded(true);
    try {
      const result = await api.resetPreloadedBenchmarks();
      setToast({ type: 'success', message: result.message });
      setShowResetPreloadedConfirm(false);
    } catch {
      setToast({ type: 'error', message: 'Failed to reset preloaded benchmarks' });
    } finally {
      setResettingPreloaded(false);
    }
  };

  const handleChangePassword = async () => {
    if (!oldPassword || !newPassword) return;
    setChangingPw(true);
    try {
      await changePassword(oldPassword, newPassword);
      setToast({ type: 'success', message: 'Password changed successfully' });
      setOldPassword('');
      setNewPassword('');
    } catch {
      setToast({ type: 'error', message: 'Password change failed — check your current password' });
    } finally {
      setChangingPw(false);
    }
  };

  const handleLogoUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onloadend = () => {
      const b64 = (reader.result as string).split(',')[1] || '';
      handleChange('company_logo_base64', b64);
    };
    reader.readAsDataURL(file);
    if (logoInputRef.current) logoInputRef.current.value = '';
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
          className={`flex items-center gap-2 rounded-lg border p-3 text-sm ${toast.type === 'success'
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
              ? 'Uses a local Ollama instance. You can run cloud models through Ollama too - see the setup guide.'
              : 'Connects directly to a cloud API (OpenAI, Anthropic, Mistral, Groq, OpenRouter, or any OpenAI-compatible endpoint).'}
          </p>
        </fieldset>

        {/* Offline (Ollama) Settings */}
        {settings.llm_mode === 'offline' && (
          <>
            <div>
              <label className={labelClass}>Ollama Model</label>
              <div className="mt-1 flex gap-2">
                {availableModels.length > 0 ? (
                  <select
                    value={settings.llm_offline_model}
                    onChange={(e) => handleChange('llm_offline_model', e.target.value)}
                    className={selectClass + ' flex-1'}
                  >
                    <option value="">Select a model\u2026</option>
                    {availableModels.map(m => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    value={settings.llm_offline_model}
                    onChange={(e) => handleChange('llm_offline_model', e.target.value)}
                    className={inputClass + ' flex-1'}
                    placeholder="e.g. qwen2.5:7b, mistral, llama3.1:8b"
                  />
                )}
                <button
                  type="button"
                  onClick={handleFetchModels}
                  disabled={modelsLoading}
                  className="flex-shrink-0 inline-flex items-center justify-center rounded-lg border border-dark-border bg-dark-elevated p-2 text-dark-muted hover:text-ey-yellow hover:border-ey-yellow/30 transition-colors disabled:opacity-50"
                  title="Fetch available models"
                >
                  {modelsLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                </button>
              </div>
              <p className={helpClass}>
                Click refresh to fetch models from Ollama, or type a model tag manually.
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
                <option value="anthropic">Anthropic (Claude)</option>
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
              <div className="mt-1 flex gap-2">
                {availableModels.length > 0 ? (
                  <select
                    value={settings.llm_online_model}
                    onChange={(e) => handleChange('llm_online_model', e.target.value)}
                    className={selectClass + ' flex-1'}
                  >
                    <option value="">Select a model\u2026</option>
                    {availableModels.map(m => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    value={settings.llm_online_model}
                    onChange={(e) => handleChange('llm_online_model', e.target.value)}
                    className={inputClass + ' flex-1'}
                    placeholder={
                      settings.llm_online_provider === 'openai'
                        ? 'e.g. gpt-4o, gpt-4o-mini'
                        : settings.llm_online_provider === 'anthropic'
                          ? 'e.g. claude-sonnet-4-20250514'
                          : settings.llm_online_provider === 'mistral'
                            ? 'e.g. mistral-large-latest'
                            : settings.llm_online_provider === 'groq'
                              ? 'e.g. llama-3.1-70b-versatile'
                              : settings.llm_online_provider === 'openrouter'
                                ? 'e.g. meta-llama/llama-3.1-70b-instruct'
                                : 'e.g. gpt-4o'
                    }
                  />
                )}
                <button
                  type="button"
                  onClick={handleFetchModels}
                  disabled={modelsLoading}
                  className="flex-shrink-0 inline-flex items-center justify-center rounded-lg border border-dark-border bg-dark-elevated p-2 text-dark-muted hover:text-ey-yellow hover:border-ey-yellow/30 transition-colors disabled:opacity-50"
                  title="Fetch available models"
                >
                  {modelsLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                </button>
              </div>
              {modelsFetchError && (
                <p className="mt-1 text-xs text-amber-400">{modelsFetchError}</p>
              )}
              <p className={helpClass}>
                Click the refresh button to fetch available models from your provider, or type a model name manually.
              </p>
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
              className={`mt-3 rounded-lg border p-3 text-sm ${llmTestResult.success
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

      {/* Display */}
      <section className="rounded-xl border border-dark-border bg-dark-card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-white">Appearance</h3>
            <p className="text-sm text-gray-400 mt-1">Switch between light and dark themes.</p>
          </div>
          <button
            type="button"
            onClick={() => {
              const newTheme = (settings.ui_theme || 'dark') === 'dark' ? 'light' : 'dark';
              handleChange('ui_theme', newTheme);
            }}
            className={`
              relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-ey-yellow focus:ring-offset-2 focus:ring-offset-dark-bg
              ${(settings.ui_theme || 'dark') === 'light' ? 'bg-ey-yellow' : 'bg-dark-border'}
            `}
            role="switch"
            aria-checked={(settings.ui_theme || 'dark') === 'light'}
          >
            <span
              aria-hidden="true"
              className={`
                pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out
                ${(settings.ui_theme || 'dark') === 'light' ? 'translate-x-5' : 'translate-x-0'}
              `}
            />
          </button>
        </div>
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

      {/* Token Usage & Limits */}
      <section className="rounded-xl border border-dark-border bg-dark-card p-6 space-y-4">
        <h3 className="text-lg font-semibold text-white">Token Usage & Limits</h3>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className={labelClass}>Max Tokens Per Request</label>
            <input
              type="number"
              min={256}
              max={128000}
              step={256}
              value={settings.llm_max_tokens || '4096'}
              onChange={(e) => handleChange('llm_max_tokens', e.target.value)}
              className={inputClass}
            />
            <p className={helpClass}>
              Limits LLM output length per call. Default: 4096. Increase for longer responses (e.g. reports).
            </p>
          </div>

          <div>
            <label className={labelClass}>Monthly Token Budget</label>
            <input
              type="number"
              min={0}
              step={10000}
              value={settings.llm_token_budget || '0'}
              onChange={(e) => handleChange('llm_token_budget', e.target.value)}
              className={inputClass}
            />
            <p className={helpClass}>
              Total token ceiling per month. Set to 0 for unlimited. LLM calls will be blocked once the budget is exhausted.
            </p>
          </div>
        </div>

        {/* Usage stats */}
        {tokenUsage && (
          <div className="border-t border-dark-border pt-4 space-y-3">
            <div className="flex items-center gap-6">
              <div>
                <p className="text-2xl font-bold text-white">{tokenUsage.total_tokens.toLocaleString()}</p>
                <p className="text-xs text-dark-muted">total tokens this month</p>
              </div>
              <div>
                <p className="text-lg font-semibold text-dark-secondary">{tokenUsage.total_input.toLocaleString()}</p>
                <p className="text-xs text-dark-muted">input</p>
              </div>
              <div>
                <p className="text-lg font-semibold text-dark-secondary">{tokenUsage.total_output.toLocaleString()}</p>
                <p className="text-xs text-dark-muted">output</p>
              </div>
              <button
                onClick={handleResetTokenUsage}
                className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-dark-secondary hover:bg-dark-overlay hover:text-white"
              >
                <Trash2 className="h-3.5 w-3.5" /> Reset Stats
              </button>
            </div>

            {/* Budget progress bar */}
            {tokenUsage.budget > 0 && (
              <div>
                <div className="flex items-center justify-between text-xs text-dark-muted mb-1">
                  <span>{tokenUsage.total_tokens.toLocaleString()} / {tokenUsage.budget.toLocaleString()} tokens</span>
                  <span>{tokenUsage.budget_remaining != null ? `${tokenUsage.budget_remaining.toLocaleString()} remaining` : ''}</span>
                </div>
                <div className="h-2 rounded-full bg-dark-elevated overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      (tokenUsage.total_tokens / tokenUsage.budget) > 0.9 ? 'bg-red-500' :
                      (tokenUsage.total_tokens / tokenUsage.budget) > 0.7 ? 'bg-amber-500' : 'bg-emerald-500'
                    }`}
                    style={{ width: `${Math.min(100, (tokenUsage.total_tokens / tokenUsage.budget) * 100)}%` }}
                  />
                </div>
              </div>
            )}

            {/* By provider */}
            {tokenUsage.by_provider.length > 0 && (
              <div className="flex flex-wrap gap-4 text-xs">
                {tokenUsage.by_provider.map(p => (
                  <div key={p.provider} className="flex items-center gap-1.5">
                    <span className="inline-block h-2 w-2 rounded-full bg-ey-yellow/60" />
                    <span className="text-dark-secondary capitalize">{p.provider}:</span>
                    <span className="text-white font-medium">{p.total_tokens.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {/* Email (SMTP) — Forge Sentinel Alerts */}
      <section className="rounded-xl border border-dark-border bg-dark-card p-6 space-y-4">
        <div className="flex items-center gap-2">
          <Mail className="h-5 w-5 text-ey-yellow" />
          <h3 className="text-lg font-semibold text-white">Email (SMTP)</h3>
        </div>
        <p className="text-sm text-dark-secondary">
          Configure SMTP for Forge Sentinel email alerts. Leave empty to disable email notifications.
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className={labelClass}>Application Base URL</label>
            <input
              value={settings.base_url || ''}
              onChange={(e) => handleChange('base_url', e.target.value)}
              className={inputClass}
              placeholder="https://auditforge.example.com"
            />
            <p className="mt-1 text-xs text-dark-muted">
              Used for report download links in email/Slack alerts. Include the protocol (https://).
            </p>
          </div>
          <div>
            <label className={labelClass}>SMTP Host</label>
            <input
              value={settings.smtp_host || ''}
              onChange={(e) => handleChange('smtp_host', e.target.value)}
              className={inputClass}
              placeholder="smtp.gmail.com"
            />
          </div>
          <div>
            <label className={labelClass}>SMTP Port</label>
            <input
              value={settings.smtp_port || ''}
              onChange={(e) => handleChange('smtp_port', e.target.value)}
              className={inputClass}
              placeholder="587"
            />
          </div>
          <div>
            <label className={labelClass}>Username <span className="text-dark-secondary font-normal">(optional)</span></label>
            <input
              value={settings.smtp_username || ''}
              onChange={(e) => handleChange('smtp_username', e.target.value)}
              className={inputClass}
              placeholder="user@example.com"
            />
          </div>
          <div>
            <label className={labelClass}>Password <span className="text-dark-secondary font-normal">(optional)</span></label>
            <input
              type="password"
              value={settings.smtp_password || ''}
              onChange={(e) => handleChange('smtp_password', e.target.value)}
              className={inputClass}
              placeholder="••••••••"
            />
          </div>
          <div>
            <label className={labelClass}>From Address</label>
            <input
              value={settings.smtp_from || ''}
              onChange={(e) => handleChange('smtp_from', e.target.value)}
              className={inputClass}
              placeholder="auditforge@company.com"
            />
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-3 cursor-pointer pb-2">
              <input
                type="checkbox"
                checked={settings.smtp_use_tls === 'true'}
                onChange={(e) => handleChange('smtp_use_tls', e.target.checked ? 'true' : 'false')}
                className="h-4 w-4 rounded border-dark-border bg-dark-elevated text-ey-yellow focus:ring-ey-yellow/50 accent-ey-yellow"
              />
              <span className="text-sm text-gray-300">Use TLS</span>
            </label>
          </div>
        </div>
      </section>

      {/* Branding / White-Label */}
      <section className="rounded-xl border border-dark-border bg-dark-card p-6 space-y-4">
        <div className="flex items-center gap-2">
          <Building2 className="h-5 w-5 text-ey-yellow" />
          <h3 className="text-lg font-semibold text-white">Report Branding</h3>
        </div>
        <p className="text-sm text-dark-secondary">
          White-label your PDF reports with your company name and logo.
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className={labelClass}>Company Name</label>
            <input
              value={settings.company_name || ''}
              onChange={(e) => handleChange('company_name', e.target.value)}
              className={inputClass}
              placeholder="Your Company"
            />
          </div>
          <div>
            <label className={labelClass}>Auditor Name</label>
            <input
              value={settings.auditor_name || ''}
              onChange={(e) => handleChange('auditor_name', e.target.value)}
              className={inputClass}
              placeholder="Auditor / team name"
            />
          </div>
        </div>

        <div>
          <label className={labelClass}>Company Logo</label>
          <div className="mt-2 flex items-center gap-4">
            {settings.company_logo_base64 ? (
              <div className="flex h-16 w-16 items-center justify-center rounded-lg border border-dark-border bg-dark-elevated p-1">
                <img
                  src={`data:image/png;base64,${settings.company_logo_base64}`}
                  alt="Logo preview"
                  className="max-h-14 max-w-14 object-contain"
                />
              </div>
            ) : (
              <div className="flex h-16 w-16 items-center justify-center rounded-lg border border-dashed border-dark-border text-dark-muted">
                <ImageIcon className="h-6 w-6" />
              </div>
            )}
            <div className="flex gap-2">
              <button
                onClick={() => logoInputRef.current?.click()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-dark-secondary hover:text-white"
              >
                <Upload className="h-3.5 w-3.5" />
                Upload Logo
              </button>
              {settings.company_logo_base64 && (
                <button
                  onClick={() => handleChange('company_logo_base64', '')}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-500/10"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Remove
                </button>
              )}
            </div>
            <input
              ref={logoInputRef}
              type="file"
              accept="image/png,image/jpeg,image/svg+xml"
              className="hidden"
              onChange={handleLogoUpload}
            />
          </div>
          <p className={helpClass}>PNG or JPEG recommended. Appears in the PDF report header.</p>
        </div>
      </section>

      {/* Change Password */}
      <section className="rounded-xl border border-dark-border bg-dark-card p-6 space-y-4">
        <div className="flex items-center gap-2">
          <KeyRound className="h-5 w-5 text-ey-yellow" />
          <h3 className="text-lg font-semibold text-white">Change Password</h3>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className={labelClass}>Current Password</label>
            <input
              type="password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              className={inputClass}
              placeholder="Enter current password"
            />
          </div>
          <div>
            <label className={labelClass}>New Password</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className={inputClass}
              placeholder="Enter new password"
            />
          </div>
        </div>
        <button
          onClick={handleChangePassword}
          disabled={!oldPassword || !newPassword || changingPw}
          className="inline-flex items-center gap-2 rounded-lg border border-ey-yellow/30 bg-ey-yellow/10 px-4 py-2 text-sm font-medium text-ey-yellow hover:bg-ey-yellow/20 disabled:opacity-50"
        >
          {changingPw ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
          {changingPw ? 'Changing…' : 'Change Password'}
        </button>
      </section>

      {/* Benchmark Management */}
      <section className="rounded-xl border border-dark-border bg-dark-card p-6 space-y-4">
        <div className="flex items-center gap-2">
          <RefreshCw className="h-5 w-5 text-ey-yellow" />
          <h3 className="text-lg font-semibold text-white">Benchmark Management</h3>
        </div>
        <p className="text-sm text-dark-secondary">
          Reset preloaded benchmarks to their original state. This deletes all preloaded benchmarks
          and re-imports them from the built-in pack files. Custom benchmarks are not affected.
        </p>
        <button
          onClick={() => setShowResetPreloadedConfirm(true)}
          disabled={resettingPreloaded}
          className="inline-flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm font-medium text-amber-400 hover:bg-amber-500/20 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${resettingPreloaded ? 'animate-spin' : ''}`} />
          {resettingPreloaded ? 'Resetting\u2026' : 'Reset Preloaded Benchmarks'}
        </button>
      </section>

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
      {showRestoreConfirm && createPortal(
        <>
          <div className="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm" onClick={() => { setShowRestoreConfirm(false); restoreFileRef.current = null; }} />
          <div className="fixed inset-0 z-[60] flex items-center justify-center" style={{ pointerEvents: 'none' }}>
            <div className="pointer-events-auto mx-4 w-full max-w-md rounded-xl border border-dark-border bg-dark-card p-6 shadow-2xl">
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
        </>,
        document.body,
      )}

      {/* Reset Preloaded Confirmation Dialog */}
      {showResetPreloadedConfirm && createPortal(
        <>
          <div className="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm" onClick={() => setShowResetPreloadedConfirm(false)} />
          <div className="fixed inset-0 z-[60] flex items-center justify-center" style={{ pointerEvents: 'none' }}>
            <div className="pointer-events-auto mx-4 w-full max-w-md rounded-xl border border-dark-border bg-dark-card p-6 shadow-2xl">
              <div className="flex items-center gap-3 mb-4">
                <AlertTriangle className="h-6 w-6 text-amber-400" />
                <h4 className="text-lg font-semibold text-white">Reset Preloaded Benchmarks</h4>
              </div>
              <p className="text-sm text-gray-300 mb-2">
                This will delete all preloaded benchmarks and re-import them from the built-in pack files.
              </p>
              <p className="text-sm text-gray-400 mb-4">
                Custom, user-imported, and Nessus-reconstructed benchmarks will <strong className="text-white">not</strong> be affected.
              </p>
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setShowResetPreloadedConfirm(false)}
                  className="rounded-lg border border-dark-border px-4 py-2 text-sm font-medium text-gray-300 hover:bg-dark-elevated"
                >
                  Cancel
                </button>
                <button
                  onClick={handleResetPreloaded}
                  disabled={resettingPreloaded}
                  className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                >
                  {resettingPreloaded ? 'Resetting\u2026' : 'Reset'}
                </button>
              </div>
            </div>
          </div>
        </>,
        document.body,
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
