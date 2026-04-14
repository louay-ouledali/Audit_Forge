import { useState, useCallback, useEffect } from 'react';
import type { Target, Benchmark } from '@/types';
import * as api from '@/services/api';

/* ── Form state (write-only fields like passwords start blank) ── */
export interface TargetFormState {
  hostname: string;
  ip_address: string;
  target_type: string;
  connection_method: string;
  port: string;
  ssh_username: string;
  ssh_password: string;
  ssh_key_path: string;
  platform_subtype: string;
  default_benchmark_id: number | null;
  device_type: string;
  enable_password: string;
  db_name: string;
  db_instance: string;
  notes: string;
  config_pull_method: string;
  config_upload_text: string;
  verify_tls: boolean;
}

/* Default port map */
const PORT_MAP: Record<string, number> = {
  winrm: 5986,
  ssh: 22,
  postgresql: 5432,
  mssql: 1433,
  oracle: 1521,
  mysql: 3306,
  mongodb: 27017,
};

export function defaultPortFor(method: string): number {
  return PORT_MAP[method.toLowerCase()] ?? 22;
}

/* Build initial form state from target */
function initForm(t: Target): TargetFormState {
  return {
    hostname: t.hostname ?? '',
    ip_address: t.ip_address ?? '',
    target_type: t.target_type || 'linux',
    connection_method: t.connection_method ?? '',
    port: t.port?.toString() ?? '',
    ssh_username: t.ssh_username ?? '',
    ssh_password: '',                     // never pre-filled (write-only)
    ssh_key_path: t.ssh_key_path ?? '',
    platform_subtype: t.platform_subtype ?? '',
    default_benchmark_id: t.default_benchmark_id,
    device_type: t.device_type ?? '',
    enable_password: '',                  // never pre-filled
    db_name: t.db_name ?? '',
    db_instance: t.db_instance ?? '',
    notes: t.notes ?? '',
    config_pull_method: t.config_pull_method ?? 'auto',
    config_upload_text: '',
    verify_tls: t.verify_tls !== false,  // default true
  };
}

export function useTargetForm(target: Target | null, onSaved: () => Promise<void>) {
  const [form, setForm] = useState<TargetFormState>(
    target ? initForm(target) : ({} as TargetFormState),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [loadingBenchmarks, setLoadingBenchmarks] = useState(false);

  // Reset form when target changes
  useEffect(() => {
    if (target) setForm(initForm(target));
  }, [target?.id]);

  // Fetch benchmarks once
  useEffect(() => {
    let cancelled = false;
    setLoadingBenchmarks(true);
    api.getBenchmarks().then(list => {
      if (!cancelled) {
        setBenchmarks(list.filter(b => b.is_ready));
        setLoadingBenchmarks(false);
      }
    }).catch(() => {
      if (!cancelled) setLoadingBenchmarks(false);
    });
    return () => { cancelled = true; };
  }, []);

  const setField = useCallback(<K extends keyof TargetFormState>(key: K, value: TargetFormState[K]) => {
    setForm(prev => ({ ...prev, [key]: value }));
    setError('');
    setSuccess('');
  }, []);

  // Auto-fill port when connection_method changes
  const setConnectionMethod = useCallback((method: string) => {
    setForm(prev => ({
      ...prev,
      connection_method: method,
      port: PORT_MAP[method.toLowerCase()]?.toString() ?? prev.port,
    }));
  }, []);

  const handleSave = useCallback(async () => {
    if (!target) return;
    setSaving(true);
    setError('');
    setSuccess('');

    // Build payload — only include changed / non-empty fields
    const payload: Record<string, unknown> = {};
    if (form.hostname !== (target.hostname ?? '')) payload.hostname = form.hostname || null;
    if (form.ip_address !== (target.ip_address ?? '')) payload.ip_address = form.ip_address || null;
    if (form.connection_method !== (target.connection_method ?? ''))
      payload.connection_method = form.connection_method || null;
    if (form.port !== (target.port?.toString() ?? ''))
      payload.port = form.port ? parseInt(form.port, 10) : null;
    if (form.ssh_username !== (target.ssh_username ?? ''))
      payload.ssh_username = form.ssh_username || null;
    if (form.ssh_password) payload.ssh_password = form.ssh_password;           // write-only
    if (form.ssh_key_path !== (target.ssh_key_path ?? ''))
      payload.ssh_key_path = form.ssh_key_path || null;
    if (form.platform_subtype !== (target.platform_subtype ?? ''))
      payload.platform_subtype = form.platform_subtype || null;
    if (form.default_benchmark_id !== target.default_benchmark_id)
      payload.default_benchmark_id = form.default_benchmark_id;
    if (form.device_type !== (target.device_type ?? ''))
      payload.device_type = form.device_type || null;
    if (form.enable_password) payload.enable_password = form.enable_password;  // write-only
    if (form.db_name !== (target.db_name ?? '')) payload.db_name = form.db_name || null;
    if (form.db_instance !== (target.db_instance ?? ''))
      payload.db_instance = form.db_instance || null;
    if (form.notes !== (target.notes ?? '')) payload.notes = form.notes || null;
    if (form.config_pull_method !== (target.config_pull_method ?? 'auto'))
      payload.config_pull_method = form.config_pull_method;
    const targetVerifyTls = target.verify_tls !== false;
    if (form.verify_tls !== targetVerifyTls) payload.verify_tls = form.verify_tls;

    if (Object.keys(payload).length === 0 && !form.config_upload_text) {
      setSaving(false);
      setSuccess('No changes to save.');
      return;
    }

    try {
      if (Object.keys(payload).length > 0) {
        await api.updateTarget(target.id, payload as Partial<Target>);
      }

      // Upload config if provided
      if (form.config_upload_text.trim()) {
        await api.uploadConfig(target.id, form.config_upload_text.trim());
        setField('config_upload_text', '');
      }

      setSuccess('Target saved successfully.');
      await onSaved();
    } catch {
      setError('Failed to save target configuration.');
    } finally {
      setSaving(false);
    }
  }, [form, target, onSaved]);

  return {
    form,
    setField,
    setConnectionMethod,
    benchmarks,
    loadingBenchmarks,
    saving,
    error,
    success,
    handleSave,
    setError,
    setSuccess,
  };
}
