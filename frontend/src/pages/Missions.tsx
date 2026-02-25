import { useEffect, useState, useMemo, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Plus, Pencil, Trash2, Search, Crosshair, Calendar, X, Building2, ChevronDown, ChevronUp, Activity, Server, Shield, Loader2 } from 'lucide-react';
import type { Client, Mission, Target, ScanDetail } from '@/types';
import * as api from '@/services/api';

interface MissionForm {
  client_id: number | '';
  name: string;
  description: string;
  start_date: string;
  end_date: string;
  status: string;
}

const emptyForm: MissionForm = {
  client_id: '',
  name: '',
  description: '',
  start_date: '',
  end_date: '',
  status: 'in_progress',
};

const STATUS_STYLES: Record<string, string> = {
  in_progress: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20',
  completed: 'bg-sky-500/10 text-sky-400 ring-sky-500/20',
  cancelled: 'bg-dark-overlay text-dark-secondary ring-dark-border',
};

const STATUS_LABELS: Record<string, string> = {
  in_progress: 'In Progress',
  completed: 'Completed',
  cancelled: 'Cancelled',
};

export default function Missions() {
  const navigate = useNavigate();
  const location = useLocation();
  const [missions, setMissions] = useState<Mission[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<MissionForm>(emptyForm);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');

  // Mission log (expanded detail) state
  const [expandedMissionId, setExpandedMissionId] = useState<number | null>(null);
  const [missionTargets, setMissionTargets] = useState<Target[]>([]);
  const [missionScans, setMissionScans] = useState<ScanDetail[]>([]);
  const [logLoading, setLogLoading] = useState(false);

  const inputClass = 'block w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none';

  const fetchData = async () => {
    try {
      const [m, c] = await Promise.all([api.getAllMissions(), api.getClients()]);
      setMissions(m);
      setClients(c);
    } catch {
      setError('Failed to load missions');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (location.pathname === '/missions') fetchData();
  }, [location.pathname]);

  const filteredMissions = useMemo(() => {
    let result = missions;
    if (statusFilter) {
      result = result.filter((m) => m.status === statusFilter);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (m) =>
          m.name.toLowerCase().includes(q) ||
          (m.client_name ?? '').toLowerCase().includes(q) ||
          (m.description ?? '').toLowerCase().includes(q),
      );
    }
    return result;
  }, [missions, search, statusFilter]);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { in_progress: 0, completed: 0, cancelled: 0 };
    for (const m of missions) {
      counts[m.status] = (counts[m.status] || 0) + 1;
    }
    return counts;
  }, [missions]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!form.client_id) {
      setError('Please select a client');
      return;
    }
    try {
      const payload = {
        ...form,
        client_id: Number(form.client_id),
        start_date: form.start_date || null,
        end_date: form.end_date || null,
      };
      if (editingId) {
        await api.updateMission(editingId, payload);
      } else {
        await api.createMission(payload);
      }
      setShowForm(false);
      setEditingId(null);
      setForm(emptyForm);
      await fetchData();
    } catch {
      setError(editingId ? 'Failed to update mission' : 'Failed to create mission');
    }
  };

  const handleEdit = (mission: Mission) => {
    setForm({
      client_id: mission.client_id,
      name: mission.name,
      description: mission.description ?? '',
      start_date: mission.start_date ?? '',
      end_date: mission.end_date ?? '',
      status: mission.status,
    });
    setEditingId(mission.id);
    setShowForm(true);
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Are you sure you want to delete this mission?')) return;
    try {
      await api.deleteMission(id);
      await fetchData();
    } catch {
      setError('Failed to delete mission');
    }
  };

  const handleCancel = () => {
    setShowForm(false);
    setEditingId(null);
    setForm(emptyForm);
    setError('');
  };

  // Toggle mission log expand and load targets + scans
  const toggleMissionLog = useCallback(async (missionId: number) => {
    if (expandedMissionId === missionId) {
      setExpandedMissionId(null);
      return;
    }
    setExpandedMissionId(missionId);
    setLogLoading(true);
    setMissionTargets([]);
    setMissionScans([]);
    try {
      const [targets, scansRes] = await Promise.all([
        api.getTargets(missionId),
        api.getScans({ mission_id: missionId }),
      ]);
      setMissionTargets(targets);
      setMissionScans(scansRes.data);
    } catch {
      // silently ignore — log section will show empty
    } finally {
      setLogLoading(false);
    }
  }, [expandedMissionId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-ey-yellow border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Missions</h2>
          <p className="mt-1 text-sm text-dark-secondary">
            {missions.length} mission{missions.length !== 1 ? 's' : ''} total
          </p>
        </div>
        <button
          onClick={() => { setShowForm(true); setEditingId(null); setForm(emptyForm); }}
          className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2.5 text-sm font-semibold text-black shadow-sm transition-colors hover:bg-ey-yellow-hover"
        >
          <Plus className="h-4 w-4" />
          New Mission
        </button>
      </div>

      {/* Status filter chips */}
      {missions.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setStatusFilter('')}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
              !statusFilter
                ? 'bg-ey-yellow/15 text-ey-yellow ring-1 ring-ey-yellow/30'
                : 'bg-dark-card text-dark-secondary hover:bg-dark-elevated hover:text-white'
            }`}
          >
            All ({missions.length})
          </button>
          {Object.entries(STATUS_LABELS).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setStatusFilter(statusFilter === key ? '' : key)}
              className={`rounded-full px-3 py-1.5 text-xs font-medium ring-1 ring-inset transition-colors ${
                statusFilter === key
                  ? STATUS_STYLES[key]
                  : 'bg-dark-card text-dark-secondary ring-dark-border hover:bg-dark-elevated'
              }`}
            >
              {label} ({statusCounts[key] || 0})
            </button>
          ))}
        </div>
      )}

      {/* Search */}
      {missions.length > 0 && (
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-dark-muted" />
          <input
            type="text"
            placeholder="Search missions by name, client, description\u2026"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-dark-border bg-dark-card py-2.5 pl-10 pr-4 text-sm text-white placeholder:text-dark-muted focus:border-ey-yellow/50 focus:outline-none focus:ring-1 focus:ring-ey-yellow/30"
          />
          {search && (
            <button onClick={() => setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-dark-muted hover:text-white">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      {/* Create/Edit Form — Modal overlay */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <form
            onSubmit={handleSubmit}
            className="w-full max-w-lg rounded-xl border border-dark-border bg-dark-card p-6 shadow-2xl space-y-5"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-white">
                {editingId ? 'Edit Mission' : 'New Mission'}
              </h3>
              <button type="button" onClick={handleCancel} className="rounded-md p-1 text-dark-muted hover:bg-dark-elevated hover:text-white">
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="mb-1 block text-sm font-medium text-gray-300">Client *</label>
                <select
                  name="client_id"
                  value={form.client_id}
                  onChange={handleChange}
                  required
                  className={inputClass}
                >
                  <option value="">Select a client\u2026</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
              <div className="sm:col-span-2">
                <label className="mb-1 block text-sm font-medium text-gray-300">Name *</label>
                <input
                  name="name"
                  value={form.name}
                  onChange={handleChange}
                  required
                  placeholder="e.g. Q1 2026 Security Audit"
                  className={inputClass}
                />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-1 block text-sm font-medium text-gray-300">Description</label>
                <textarea
                  name="description"
                  value={form.description}
                  onChange={handleChange}
                  rows={2}
                  placeholder="Brief description of the mission scope\u2026"
                  className={inputClass}
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">Start Date</label>
                <input
                  name="start_date"
                  type="date"
                  value={form.start_date}
                  onChange={handleChange}
                  className={inputClass}
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-300">End Date</label>
                <input
                  name="end_date"
                  type="date"
                  value={form.end_date}
                  onChange={handleChange}
                  className={inputClass}
                />
              </div>
              {editingId && (
                <div className="sm:col-span-2">
                  <label className="mb-1 block text-sm font-medium text-gray-300">Status</label>
                  <select
                    name="status"
                    value={form.status}
                    onChange={handleChange}
                    className={inputClass}
                  >
                    <option value="in_progress">In Progress</option>
                    <option value="completed">Completed</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>
              )}
            </div>

            <div className="flex justify-end gap-3 border-t border-dark-border pt-4">
              <button
                type="button"
                onClick={handleCancel}
                className="rounded-lg border border-dark-border px-4 py-2 text-sm font-medium text-gray-300 hover:bg-dark-elevated"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="rounded-lg bg-ey-yellow px-5 py-2 text-sm font-semibold text-black shadow-sm hover:bg-ey-yellow-hover"
              >
                {editingId ? 'Save Changes' : 'Create Mission'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Mission Cards */}
      {filteredMissions.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-16 text-center">
          <Crosshair className="mx-auto h-12 w-12 text-dark-muted" />
          <h3 className="mt-4 text-base font-medium text-white">
            {search || statusFilter ? 'No matching missions' : 'No missions yet'}
          </h3>
          <p className="mt-1 text-sm text-dark-secondary">
            {search || statusFilter
              ? 'Try adjusting your filters.'
              : 'Create your first mission to get started.'}
          </p>
          {!search && !statusFilter && (
            <button
              onClick={() => { setShowForm(true); setEditingId(null); setForm(emptyForm); }}
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover"
            >
              <Plus className="h-4 w-4" />
              Add Mission
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {filteredMissions.map((mission) => (
            <div
              key={mission.id}
              className="group relative glow-card rounded-xl border border-dark-border bg-dark-card p-5 transition-all"
            >
              {/* Actions */}
              <div className="absolute right-3 top-3 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                <button
                  onClick={(e) => { e.stopPropagation(); handleEdit(mission); }}
                  className="rounded-md p-1.5 text-dark-muted hover:bg-ey-yellow/10 hover:text-ey-yellow"
                  title="Edit"
                >
                  <Pencil className="h-4 w-4" />
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); handleDelete(mission.id); }}
                  className="rounded-md p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400"
                  title="Delete"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>

              {/* Card body */}
              <div className="flex items-start gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-ey-yellow/10 text-ey-yellow">
                  <Crosshair className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate text-sm font-semibold text-white">
                      {mission.name}
                    </h3>
                    <span
                      className={`inline-flex shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${
                        STATUS_STYLES[mission.status] ?? STATUS_STYLES.in_progress
                      }`}
                    >
                      {STATUS_LABELS[mission.status] ?? mission.status}
                    </span>
                  </div>

                  <button
                    onClick={() => navigate(`/clients/${mission.client_id}`)}
                    className="mt-1 flex items-center gap-1 text-xs text-ey-yellow hover:text-ey-yellow-hover"
                  >
                    <Building2 className="h-3 w-3" />
                    {mission.client_name ?? `Client #${mission.client_id}`}
                  </button>

                  {mission.description && (
                    <p className="mt-2 line-clamp-2 text-xs text-dark-secondary">{mission.description}</p>
                  )}

                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-dark-border pt-3">
                    {(mission.start_date || mission.end_date) && (
                      <div className="flex items-center gap-1 text-xs text-dark-muted">
                        <Calendar className="h-3 w-3" />
                        {mission.start_date ?? '\u2014'} \u2192 {mission.end_date ?? '\u2014'}
                      </div>
                    )}
                    <span className="text-xs text-dark-muted">
                      {mission.target_count} target{mission.target_count !== 1 ? 's' : ''}
                    </span>
                    {/* Mission Log toggle */}
                    <button
                      onClick={(e) => { e.stopPropagation(); toggleMissionLog(mission.id); }}
                      className="ml-auto inline-flex items-center gap-1 text-xs text-ey-yellow hover:text-ey-yellow-hover transition-colors"
                    >
                      <Activity className="h-3 w-3" />
                      Mission Log
                      {expandedMissionId === mission.id ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                    </button>
                  </div>
                </div>
              </div>

              {/* Mission Log — expanded detail panel */}
              {expandedMissionId === mission.id && (
                <div className="mt-4 border-t border-dark-border pt-4 space-y-3">
                  {logLoading ? (
                    <div className="flex items-center justify-center py-4">
                      <Loader2 className="h-5 w-5 animate-spin text-ey-yellow" />
                    </div>
                  ) : (
                    <>
                      {/* Targets */}
                      {missionTargets.length > 0 && (
                        <div>
                          <h4 className="flex items-center gap-1.5 text-xs font-semibold text-gray-300 uppercase tracking-wider mb-2">
                            <Server className="h-3 w-3 text-ey-yellow" />
                            Targets ({missionTargets.length})
                          </h4>
                          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                            {missionTargets.map((t) => (
                              <div key={t.id} className="flex items-center gap-2 rounded-lg bg-dark-elevated px-3 py-2 text-xs">
                                <span className="font-medium text-white">{t.hostname || t.ip_address || `Target #${t.id}`}</span>
                                {t.hostname && t.ip_address && <span className="text-dark-muted">({t.ip_address})</span>}
                                <span className="ml-auto rounded bg-dark-overlay px-1.5 py-0.5 text-[10px] text-dark-secondary">{t.target_type}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Scans / Activity */}
                      <div>
                        <h4 className="flex items-center gap-1.5 text-xs font-semibold text-gray-300 uppercase tracking-wider mb-2">
                          <Shield className="h-3 w-3 text-ey-yellow" />
                          Scan Activity ({missionScans.length})
                        </h4>
                        {missionScans.length === 0 ? (
                          <p className="text-xs text-dark-muted italic px-1">No scans yet for this mission.</p>
                        ) : (
                          <div className="space-y-1.5">
                            {missionScans.slice(0, 10).map((s) => {
                              const label = [
                                s.benchmark_name ? (s.benchmark_name.replace(/^CIS\s+/, '') + (s.benchmark_version ? ` ${s.benchmark_version}` : '')) : null,
                                s.target_hostname || s.target_ip,
                              ].filter(Boolean).join(' \u2014 ') || `Scan #${s.id}`;

                              return (
                                <div key={s.id} className="flex items-center gap-3 rounded-lg bg-dark-elevated px-3 py-2 text-xs">
                                  <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${
                                    s.status === 'completed' ? 'bg-emerald-400' :
                                    s.status === 'running' ? 'bg-sky-400 animate-pulse' :
                                    s.status === 'failed' ? 'bg-red-400' : 'bg-dark-muted'
                                  }`} />
                                  <span className="font-medium text-white truncate flex-1">{label}</span>
                                  <span className="text-dark-muted whitespace-nowrap">{s.scan_mode}</span>
                                  {s.compliance_percentage != null && (
                                    <span className={`font-mono ${s.compliance_percentage >= 70 ? 'text-emerald-400' : s.compliance_percentage >= 40 ? 'text-amber-400' : 'text-red-400'}`}>
                                      {s.compliance_percentage.toFixed(0)}%
                                    </span>
                                  )}
                                  <span className="text-dark-muted whitespace-nowrap">
                                    {s.started_at ? new Date(s.started_at).toLocaleDateString() : s.created_at ? new Date(s.created_at).toLocaleDateString() : ''}
                                  </span>
                                </div>
                              );
                            })}
                            {missionScans.length > 10 && (
                              <p className="text-xs text-dark-muted italic px-1">…and {missionScans.length - 10} more</p>
                            )}
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
