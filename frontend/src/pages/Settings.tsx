import { useEffect, useState } from 'react';
import { Save, CheckCircle2, XCircle } from 'lucide-react';
import type { Settings as SettingsType } from '@/types';
import * as api from '@/services/api';

const defaultSettings: SettingsType = {
  llm_mode: 'offline',
  llm_offline_model: '',
  llm_ollama_url: '',
  llm_online_provider: '',
  llm_online_model: '',
  verification_enabled: 'true',
  verification_auto_protect_passing: 'false',
  default_scan_mode: 'network',
};

export default function Settings() {
  const [settings, setSettings] = useState<SettingsType>(defaultSettings);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
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
                {mode.charAt(0).toUpperCase() + mode.slice(1)}
              </label>
            ))}
          </div>
        </fieldset>

        <div>
          <label className="block text-sm font-medium text-gray-700">Offline Model</label>
          <input
            value={settings.llm_offline_model}
            onChange={(e) => handleChange('llm_offline_model', e.target.value)}
            className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
            placeholder="e.g. mistral"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">Ollama URL</label>
          <input
            value={settings.llm_ollama_url}
            onChange={(e) => handleChange('llm_ollama_url', e.target.value)}
            className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
            placeholder="http://localhost:11434"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">Online Provider</label>
          <input
            value={settings.llm_online_provider}
            onChange={(e) => handleChange('llm_online_provider', e.target.value)}
            className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
            placeholder="e.g. openai"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">Online Model</label>
          <input
            value={settings.llm_online_model}
            onChange={(e) => handleChange('llm_online_model', e.target.value)}
            className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 focus:outline-none"
            placeholder="e.g. gpt-4o"
          />
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
