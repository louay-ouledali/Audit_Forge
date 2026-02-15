import { useEffect, useRef, useState } from 'react';
import { Save, CheckCircle2, XCircle, Download, Upload, Database, AlertTriangle, Zap, Loader2 } from 'lucide-react';
import type { Settings as SettingsType } from '@/types';
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
  const [llmTestResult, setLlmTestResult] = useState<{ success: boolean; response?: string | null; response_time_ms?: number; model?: string; error?: string } | null>(null);
  const restoreFileRef = useRef<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await api.getSettings();
        setSettings({ ...defaultSettings, ...data });
      } catch {
        // keep defaults
      } finally {
        setLoading(false);
      }
    })();
  }, []);

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
      setLlmTestResult({ success: false, error: 'Failed to reach backend. Is the server running?' });
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
    // Reset input so the same file can be selected again
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

  if (loading) {
    return <div className="flex items-center justify-center py-12 text-gray-500">Loading…</div>;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {toast && (
        <div
          className={`flex items-center gap-2 rounded-lg border p-3 text-sm ${
            toast.type === 'success'
              ? 'border-green-200 bg-green-50 text-green-700'
              : 'border-red-200 bg-red-50 text-red-700'
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
      <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
        <h3 className="text-lg font-semibold text-gray-900">LLM Configuration</h3>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-gray-700">LLM Mode</legend>
          <div className="flex gap-6">
            {['offline', 'online'].map((mode) => (
              <label key={mode} className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="radio"
                  name="llm_mode"
                  value={mode}
                  checked={settings.llm_mode === mode}
                  onChange={() => handleChange('llm_mode', mode)}
                  className="text-blue-600 focus:ring-blue-500"
                />
                {mode === 'offline' ? 'Offline (Ollama)' : 'Online (Cloud API)'}
              </label>
            ))}
          </div>
          <p className="text-xs text-gray-500">
            {settings.llm_mode === 'offline'
              ? 'Uses a local Ollama instance. You can run cloud models through Ollama too — see the setup guide.'
              : 'Connects directly to a cloud API (OpenAI, Mistral, Groq, OpenRouter, or any OpenAI-compatible endpoint).'}
          </p>
        </fieldset>

        {/* ── Offline (Ollama) Settings ── */}
        {settings.llm_mode === 'offline' && (
          <>
            <div>
              <label className="block text-sm font-medium text-gray-700">Ollama Model</label>
              <input
                value={settings.llm_offline_model}
                onChange={(e) => handleChange('llm_offline_model', e.target.value)}
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                placeholder="e.g. qwen2.5:7b, mistral, llama3.1:8b"
              />
              <p className="mt-1 text-xs text-gray-500">
                The model tag as shown by <code className="rounded bg-gray-100 px-1">ollama list</code>.
                Default: <code className="rounded bg-gray-100 px-1">qwen2.5:7b</code>
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">Ollama URL</label>
              <input
                value={settings.llm_ollama_url}
                onChange={(e) => handleChange('llm_ollama_url', e.target.value)}
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                placeholder="http://localhost:11434"
              />
              <p className="mt-1 text-xs text-gray-500">
                Default: <code className="rounded bg-gray-100 px-1">http://localhost:11434</code>.
                Use <code className="rounded bg-gray-100 px-1">http://host.docker.internal:11434</code> if
                running inside Docker.
              </p>
            </div>
          </>
        )}

        {/* ── Online (Cloud API) Settings ── */}
        {settings.llm_mode === 'online' && (
          <>
            <div>
              <label className="block text-sm font-medium text-gray-700">Provider</label>
              <select
                value={settings.llm_online_provider}
                onChange={(e) => handleChange('llm_online_provider', e.target.value)}
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
              >
                <option value="">Select a provider…</option>
                <option value="openai">OpenAI</option>
                <option value="mistral">Mistral AI</option>
                <option value="groq">Groq</option>
                <option value="openrouter">OpenRouter</option>
                <option value="custom">Custom (OpenAI-compatible)</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">API Key</label>
              <input
                type="password"
                value={settings.llm_online_api_key_encrypted}
                onChange={(e) => handleChange('llm_online_api_key_encrypted', e.target.value)}
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                placeholder="sk-…"
              />
              <p className="mt-1 text-xs text-gray-500">
                Your API key for the selected provider. Stored in the local database.
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700">Model</label>
              <input
                value={settings.llm_online_model}
                onChange={(e) => handleChange('llm_online_model', e.target.value)}
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
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
                <label className="block text-sm font-medium text-gray-700">Custom Base URL</label>
                <input
                  value={settings.llm_online_base_url}
                  onChange={(e) => handleChange('llm_online_base_url', e.target.value)}
                  className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                  placeholder="https://your-endpoint.com/v1"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Full base URL for the OpenAI-compatible API (must support <code className="rounded bg-gray-100 px-1">/chat/completions</code>).
                </p>
              </div>
            )}
          </>
        )}

        {/* Test LLM Connection */}
        <div className="border-t border-gray-200 pt-4">
          <button
            onClick={handleTestLLM}
            disabled={testingLLM}
            className="inline-flex items-center gap-2 rounded-lg border border-blue-300 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-50"
          >
            {testingLLM ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
            {testingLLM ? 'Testing…' : 'Test LLM Connection'}
          </button>

          {llmTestResult && (
            <div
              className={`mt-3 rounded-lg border p-3 text-sm ${
                llmTestResult.success
                  ? 'border-green-200 bg-green-50 text-green-700'
                  : 'border-red-200 bg-red-50 text-red-700'
              }`}
            >
              {llmTestResult.success ? (
                <div className="space-y-1">
                  <div className="flex items-center gap-2 font-medium">
                    <CheckCircle2 className="h-4 w-4" /> LLM is working
                  </div>
                  <div>Model: <code className="rounded bg-white/60 px-1">{llmTestResult.model}</code></div>
                  <div>Response time: <strong>{llmTestResult.response_time_ms}ms</strong></div>
                  <div className="text-xs text-green-600 italic">&quot;{llmTestResult.response}&quot;</div>
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
      <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
        <h3 className="text-lg font-semibold text-gray-900">Per-Task Model Overrides</h3>
        <p className="text-sm text-gray-500">
          Optionally use a different model for specific tasks. Leave empty to use the global model configured above.
          {settings.llm_mode === 'offline'
            ? ' Enter an Ollama model tag (e.g. qwen2.5:14b).'
            : ' Enter a cloud model name (e.g. gpt-4o, mistral-large-latest).'}
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {TASK_FIELDS.map((field) => (
            <div key={field.key}>
              <label className="block text-sm font-medium text-gray-700">{field.label}</label>
              <input
                value={settings[field.key] || ''}
                onChange={(e) => handleChange(field.key, e.target.value)}
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                placeholder="(use global model)"
              />
              <p className="mt-1 text-xs text-gray-500">{field.help}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Verification */}
      <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
        <h3 className="text-lg font-semibold text-gray-900">Verification</h3>

        <label className="flex items-center gap-3">
          <input
            type="checkbox"
            checked={settings.verification_enabled === 'true'}
            onChange={(e) => handleChange('verification_enabled', e.target.checked ? 'true' : 'false')}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-700">Enable verification</span>
        </label>

        <label className="flex items-center gap-3">
          <input
            type="checkbox"
            checked={settings.verification_auto_protect_passing === 'true'}
            onChange={(e) =>
              handleChange('verification_auto_protect_passing', e.target.checked ? 'true' : 'false')
            }
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-700">Auto-protect passing checks</span>
        </label>
      </section>

      {/* Scan Defaults */}
      <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
        <h3 className="text-lg font-semibold text-gray-900">Scan Defaults</h3>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-gray-700">Default Scan Mode</legend>
          <div className="flex gap-6">
            {['network', 'script_export'].map((mode) => (
              <label key={mode} className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="radio"
                  name="default_scan_mode"
                  value={mode}
                  checked={settings.default_scan_mode === mode}
                  onChange={() => handleChange('default_scan_mode', mode)}
                  className="text-blue-600 focus:ring-blue-500"
                />
                {mode === 'network' ? 'Network' : 'Script Export'}
              </label>
            ))}
          </div>
        </fieldset>
      </section>

      {/* Database Backup & Restore */}
      <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-gray-600" />
          <h3 className="text-lg font-semibold text-gray-900">Database Backup &amp; Restore</h3>
        </div>
        <p className="text-sm text-gray-500">
          Create a full backup of your AditForge database or restore from a previous backup.
        </p>

        <div className="flex flex-col gap-3 sm:flex-row">
          <button
            onClick={handleBackup}
            disabled={backingUp}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            {backingUp ? 'Creating backup…' : 'Download Backup'}
          </button>

          <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
            <Upload className="h-4 w-4" />
            {restoring ? 'Restoring…' : 'Restore from Backup'}
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

        <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-600 flex-shrink-0" />
            <p className="text-xs text-amber-700">
              Restoring a backup will replace <strong>all current data</strong>. A safety backup of the
              current database will be created automatically. The application should be restarted after
              restoring.
            </p>
          </div>
        </div>
      </section>

      {/* Restore Confirmation Dialog */}
      {showRestoreConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="mx-4 w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <div className="flex items-center gap-3 mb-4">
              <AlertTriangle className="h-6 w-6 text-amber-500" />
              <h4 className="text-lg font-semibold text-gray-900">Confirm Restore</h4>
            </div>
            <p className="text-sm text-gray-600 mb-2">
              Are you sure you want to restore the database from{' '}
              <strong>{restoreFileRef.current?.name}</strong>?
            </p>
            <p className="text-sm text-red-600 mb-4">
              This will replace all current data. A safety backup will be created first.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => { setShowRestoreConfirm(false); restoreFileRef.current = null; }}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
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
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          <Save className="h-4 w-4" />
          {saving ? 'Saving…' : 'Save Settings'}
        </button>
      </div>
    </div>
  );
}
