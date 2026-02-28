import { useEffect, useState, useMemo, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Plus,
  Pencil,
  Trash2,
  Search,
  X,
  Server,
  Crosshair,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Lock,
  Building2,
  Mail,
  User,
  Calendar,
  Monitor,
  Globe,
  Play,
  Activity,
} from 'lucide-react';
import type { Client, Mission, Target, ScanDetail } from '@/types';
import * as api from '@/services/api';

/* ── Status styling ──────────────────────────────────────────── */
const STATUS_STYLES: Record<string, string> = {
  in_progress: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20',
  completed: 'bg-sky-500/10 text-sky-400 ring-sky-500/20',
  cancelled: 'bg-dark-overlay text-dark-secondary ring-dark-border',
};
const STATUS_LABELS: Record<string, string> = { in_progress: 'In Progress', completed: 'Completed', cancelled: 'Cancelled' };

const TARGET_ICONS: Record<string, typeof Monitor> = { windows: Monitor, linux: Server, network: Globe };

/* ── Tab type ────────────────────────────────────────────────── */
type WorkspaceTab = 'missions' | 'targets';

/* ── Target form ─────────────────────────────────────────────── */
interface TargetForm {
  hostname: string;
  ip_address: string;
  target_type: string;
  connection_method: string;
  ssh_username: string;
  ssh_password: string;
  port: string;
  notes: string;
}
const emptyTargetForm: TargetForm = { hostname: '', ip_address: '', target_type: 'windows', connection_method: 'ssh', ssh_username: '', ssh_password: '', port: '', notes: '' };

/* ── Mission form ────────────────────────────────────────────── */
interface MissionForm {
  name: string;
  description: string;
  status: string;
  start_date: string;
  end_date: string;
}
const emptyMissionForm: MissionForm = { name: '', description: '', status: 'in_progress', start_date: '', end_date: '' };

const inputClass = 'block w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none';

export default function ClientWorkspace() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const clientId = Number(id);

  /* ── Data state ──────────────────────────────────────────── */
  const [client, setClient] = useState<Client | null>(null);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  /* ── Tab state ───────────────────────────────────────────── */
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('missions');
  const [search, setSearch] = useState('');

  /* ── Status filter ───────────────────────────────────────── */
  const [statusFilter, setStatusFilter] = useState<string>('all');

  /* ── Mission log (expandable panels) ─────────────────────── */
  const [expandedMissionId, setExpandedMissionId] = useState<number | null>(null);
  const [missionScans, setMissionScans] = useState<Record<number, ScanDetail[]>>({});
  const [missionTargets, setMissionTargets] = useState<Record<number, Target[]>>({});
  const [loadingLog, setLoadingLog] = useState<number | null>(null);

  /* ── Mission form state ──────────────────────────────────── */
  const [showMissionForm, setShowMissionForm] = useState(false);
  const [editingMissionId, setEditingMissionId] = useState<number | null>(null);
  const [missionForm, setMissionForm] = useState<MissionForm>(emptyMissionForm);

  /* ── Target form state ───────────────────────────────────── */
  const [showTargetForm, setShowTargetForm] = useState(false);
  const [editingTargetId, setEditingTargetId] = useState<number | null>(null);
  const [targetForm, setTargetForm] = useState<TargetForm>(emptyTargetForm);

  /* ── Fetch data ──────────────────────────────────────────── */
  const fetchData = useCallback(async () => {
    try {
      const [c, m, t] = await Promise.all([
        api.getClient(clientId),
        api.getMissions(clientId),
        api.getClientTargets(clientId),
      ]);
      setClient(c);
      setMissions(m);
      setTargets(t);
    } catch {
      setError('Failed to load client data');
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  /* ── Auto-dismiss errors after 5s ──────────────────────────── */
  useEffect(() => {
    if (!error) return;
    const timer = setTimeout(() => setError(''), 5000);
    return () => clearTimeout(timer);
  }, [error]);

  /* ── Status counts ────────────────────────────────────────── */
  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { all: missions.length, in_progress: 0, completed: 0, cancelled: 0 };
    missions.forEach(m => { counts[m.status] = (counts[m.status] || 0) + 1; });
    return counts;
  }, [missions]);

  /* ── Filtered lists ──────────────────────────────────────── */
  const filteredMissions = useMemo(() => {
    let list = missions;
    if (statusFilter !== 'all') list = list.filter(m => m.status === statusFilter);
    if (!search.trim()) return list;
    const q = search.toLowerCase();
    return list.filter(m =>
      m.name.toLowerCase().includes(q) ||
      (m.description ?? '').toLowerCase().includes(q),
    );
  }, [missions, search, statusFilter]);

  const filteredTargets = useMemo(() => {
    if (!search.trim()) return targets;
    const q = search.toLowerCase();
    return targets.filter(t =>
      (t.hostname ?? '').toLowerCase().includes(q) ||
      (t.ip_address ?? '').toLowerCase().includes(q) ||
      t.target_type.toLowerCase().includes(q),
    );
  }, [targets, search]);

  /* ── Mission CRUD ────────────────────────────────────────── */
  /* ── Toggle mission log (expand/collapse) ────────────────── */
  const toggleMissionLog = async (missionId: number) => {
    if (expandedMissionId === missionId) {
      setExpandedMissionId(null);
      return;
    }
    setExpandedMissionId(missionId);
    if (!missionScans[missionId]) {
      setLoadingLog(missionId);
      try {
        const [scansRes, tgts] = await Promise.all([
          api.getScans({ mission_id: missionId }),
          api.getTargets(missionId),
        ]);
        setMissionScans(prev => ({ ...prev, [missionId]: scansRes.data }));
        setMissionTargets(prev => ({ ...prev, [missionId]: tgts }));
      } catch { /* ignore */ }
      setLoadingLog(null);
    }
  };

  const handleMissionSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      const payload = { ...missionForm, client_id: clientId, start_date: missionForm.start_date || null, end_date: missionForm.end_date || null };
      if (editingMissionId) await api.updateMission(editingMissionId, payload);
      else await api.createMission(payload);
      setShowMissionForm(false);
      setEditingMissionId(null);
      setMissionForm(emptyMissionForm);
      await fetchData();
    } catch {
      setError(editingMissionId ? 'Failed to update mission' : 'Failed to create mission');
    }
  };

  const handleEditMission = (mission: Mission) => {
    setMissionForm({
      name: mission.name,
      description: mission.description ?? '',
      status: mission.status || 'in_progress',
      start_date: mission.start_date ?? '',
      end_date: mission.end_date ?? '',
    });
    setEditingMissionId(mission.id);
    setShowMissionForm(true);
  };

  const handleDeleteMission = async (missionId: number) => {
    if (!window.confirm('Delete this mission and all associated data?')) return;
    try { await api.deleteMission(missionId); await fetchData(); }
    catch { setError('Failed to delete mission'); }
  };

  /* ── Target CRUD ─────────────────────────────────────────── */
  const handleTargetSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      const payload: Partial<Target> & { client_id: number; ssh_password?: string } = {
        client_id: clientId,
        hostname: targetForm.hostname || null,
        ip_address: targetForm.ip_address || null,
        target_type: targetForm.target_type,
        connection_method: targetForm.connection_method || null,
        ssh_username: targetForm.ssh_username || null,
        port: targetForm.port ? parseInt(targetForm.port) : null,
        notes: targetForm.notes || null,
        ssh_password: targetForm.ssh_password || undefined,
      };
      if (editingTargetId) await api.updateTarget(editingTargetId, payload);
      else await api.createTarget(payload);
      setShowTargetForm(false);
      setEditingTargetId(null);
      setTargetForm(emptyTargetForm);
      await fetchData();
    } catch {
      setError(editingTargetId ? 'Failed to update target' : 'Failed to create target');
    }
  };

  const handleEditTarget = (target: Target) => {
    setTargetForm({
      hostname: target.hostname ?? '',
      ip_address: target.ip_address ?? '',
      target_type: target.target_type,
      connection_method: target.connection_method ?? 'ssh',
      ssh_username: target.ssh_username ?? '',
      ssh_password: '',
      port: target.port?.toString() ?? '',
      notes: target.notes ?? '',
    });
    setEditingTargetId(target.id);
    setShowTargetForm(true);
  };

  const handleDeleteTarget = async (targetId: number) => {
    if (!window.confirm('Delete this target?')) return;
    try { await api.deleteTarget(targetId); await fetchData(); }
    catch { setError('Failed to delete target'); }
  };

  const cancelMissionForm = () => { setShowMissionForm(false); setEditingMissionId(null); setMissionForm(emptyMissionForm); };
  const cancelTargetForm = () => { setShowTargetForm(false); setEditingTargetId(null); setTargetForm(emptyTargetForm); };

  /* ── Loading / Not found ─────────────────────────────────── */
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-ey-yellow border-t-transparent" />
      </div>
    );
  }

  if (!client) {
    return (
      <div className="py-12 text-center text-dark-secondary">
        Client not found.{' '}
        <button onClick={() => navigate('/clients')} className="text-ey-yellow hover:underline">Go back</button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Back button */}
      <button onClick={() => navigate('/clients')} className="inline-flex items-center gap-1 text-sm text-dark-secondary hover:text-ey-yellow transition-colors">
        <ArrowLeft className="h-4 w-4" /> Back to Clients
      </button>

      {/* Client Header Card */}
      <div className="relative overflow-hidden rounded-xl border border-dark-border bg-dark-card p-6">
        <div className="absolute inset-0 bg-gradient-to-br from-ey-yellow/5 via-transparent to-transparent" />
        <div className="relative flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-ey-yellow/10">
                <Building2 className="h-5 w-5 text-ey-yellow" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-white">{client.name}</h2>
                {client.industry && <p className="text-sm text-dark-secondary">{client.industry}</p>}
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-4 text-sm">
              {client.contact_name && (
                <div className="flex items-center gap-1.5 text-dark-secondary">
                  <User className="h-3.5 w-3.5" /> {client.contact_name}
                </div>
              )}
              {client.contact_email && (
                <div className="flex items-center gap-1.5 text-dark-secondary">
                  <Mail className="h-3.5 w-3.5" /> {client.contact_email}
                </div>
              )}
            </div>
            {client.notes && <p className="mt-3 text-sm text-dark-muted">{client.notes}</p>}
          </div>

          {/* Stats */}
          <div className="flex gap-6">
            <div className="text-center">
              <p className="text-2xl font-bold text-white">{missions.length}</p>
              <p className="text-xs text-dark-secondary">Missions</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-white">{targets.length}</p>
              <p className="text-xs text-dark-secondary">Targets</p>
            </div>
          </div>
        </div>
      </div>

      {/* Tab Bar */}
      <div className="flex items-center gap-4 border-b border-dark-border">
        {([
          { key: 'missions' as const, label: 'Missions', icon: Crosshair, count: missions.length },
          { key: 'targets' as const, label: 'Targets', icon: Server, count: targets.length },
        ]).map(tab => (
          <button
            key={tab.key}
            onClick={() => { setActiveTab(tab.key); setSearch(''); }}
            className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
              activeTab === tab.key
                ? 'border-ey-yellow text-ey-yellow'
                : 'border-transparent text-dark-secondary hover:text-white'
            }`}
          >
            <tab.icon className="h-4 w-4" />
            {tab.label}
            <span className="rounded-full bg-dark-elevated px-2 py-0.5 text-xs">{tab.count}</span>
          </button>
        ))}
      </div>

      {/* Search + New button */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-dark-muted" />
          <input
            type="text"
            placeholder={activeTab === 'missions' ? 'Search missions…' : 'Search targets…'}
            value={search}
            onChange={e => setSearch(e.target.value)}
            className={`${inputClass} pl-10`}
          />
          {search && (
            <button onClick={() => setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-dark-muted hover:text-white">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <button
          onClick={() => activeTab === 'missions' ? (setShowMissionForm(true), setEditingMissionId(null), setMissionForm(emptyMissionForm)) : (setShowTargetForm(true), setEditingTargetId(null), setTargetForm(emptyTargetForm))}
          className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2.5 text-sm font-semibold text-black shadow-sm transition-colors hover:bg-ey-yellow-hover"
        >
          <Plus className="h-4 w-4" /> New {activeTab === 'missions' ? 'Mission' : 'Target'}
        </button>
      </div>

      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}<button onClick={() => setError('')} className="ml-2 text-red-300 hover:text-white">×</button></div>}

      {/* ── Missions Tab ───────────────────────────────────── */}
      {activeTab === 'missions' && (
        <>
          {/* Status Filter Chips */}
          <div className="flex flex-wrap gap-2">
            {(['all', 'in_progress', 'completed', 'cancelled'] as const).map(key => {
              const labels: Record<string, string> = { all: 'All', in_progress: 'In Progress', completed: 'Completed', cancelled: 'Cancelled' };
              const colors: Record<string, string> = {
                all: statusFilter === 'all' ? 'bg-ey-yellow text-black' : 'bg-dark-elevated text-dark-secondary hover:text-white',
                in_progress: statusFilter === 'in_progress' ? 'bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-500/40' : 'bg-dark-elevated text-dark-secondary hover:text-white',
                completed: statusFilter === 'completed' ? 'bg-sky-500/20 text-sky-400 ring-1 ring-sky-500/40' : 'bg-dark-elevated text-dark-secondary hover:text-white',
                cancelled: statusFilter === 'cancelled' ? 'bg-dark-overlay text-dark-secondary ring-1 ring-dark-border' : 'bg-dark-elevated text-dark-secondary hover:text-white',
              };
              return (
                <button
                  key={key}
                  onClick={() => setStatusFilter(key)}
                  className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors ${colors[key]}`}
                >
                  {labels[key]}
                  <span className="rounded-full bg-black/20 px-1.5 py-0.5 text-[10px]">{statusCounts[key] || 0}</span>
                </button>
              );
            })}
          </div>

          {/* Mission Form Modal */}
          {showMissionForm && (
            <div className="rounded-xl border border-dark-border bg-dark-card p-6">
              <h3 className="mb-4 text-lg font-semibold text-white">{editingMissionId ? 'Edit Mission' : 'New Mission'}</h3>
              <form onSubmit={handleMissionSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <label className="mb-1 block text-xs font-medium text-dark-secondary">Name *</label>
                  <input name="name" value={missionForm.name} onChange={e => setMissionForm({ ...missionForm, name: e.target.value })} required className={inputClass} placeholder="Q1 2025 Audit" />
                </div>
                <div className="sm:col-span-2">
                  <label className="mb-1 block text-xs font-medium text-dark-secondary">Description</label>
                  <textarea name="description" value={missionForm.description} onChange={e => setMissionForm({ ...missionForm, description: e.target.value })} rows={2} className={inputClass} placeholder="Mission scope and objectives…" />
                </div>
                {editingMissionId && (
                  <div>
                    <label className="mb-1 block text-xs font-medium text-dark-secondary">Status</label>
                    <select value={missionForm.status} onChange={e => setMissionForm({ ...missionForm, status: e.target.value })} className={inputClass}>
                      <option value="in_progress">In Progress</option>
                      <option value="completed">Completed</option>
                      <option value="cancelled">Cancelled</option>
                    </select>
                  </div>
                )}
                <div>
                  <label className="mb-1 block text-xs font-medium text-dark-secondary">Start Date</label>
                  <input type="date" value={missionForm.start_date} onChange={e => setMissionForm({ ...missionForm, start_date: e.target.value })} className={inputClass} />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-dark-secondary">End Date</label>
                  <input type="date" value={missionForm.end_date} onChange={e => setMissionForm({ ...missionForm, end_date: e.target.value })} className={inputClass} />
                </div>
                <div className="flex gap-2 sm:col-span-2">
                  <button type="submit" className="rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover">
                    {editingMissionId ? 'Update' : 'Create'}
                  </button>
                  <button type="button" onClick={cancelMissionForm} className="rounded-lg border border-dark-border px-4 py-2 text-sm text-dark-secondary hover:bg-dark-elevated hover:text-white">
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Mission Cards */}
          {filteredMissions.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-12 text-center">
              <Crosshair className="mx-auto h-10 w-10 text-dark-muted" />
              <p className="mt-3 text-dark-secondary">No missions yet. Create one to get started.</p>
            </div>
          ) : (
            <div className="grid gap-3">
              {filteredMissions.map(mission => (
                <div key={mission.id} className="rounded-xl border border-dark-border bg-dark-card transition-all hover:border-dark-border/80 hover:bg-dark-elevated/50">
                  <div className="group flex items-center justify-between p-4">
                    <div
                      className="flex flex-1 cursor-pointer items-center gap-4"
                      onClick={() => navigate(`/missions/${mission.id}`)}
                    >
                      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-dark-elevated">
                        <Crosshair className="h-5 w-5 text-ey-yellow" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <h4 className="font-medium text-white truncate">{mission.name}</h4>
                          {mission.is_locked && <Lock className="h-3.5 w-3.5 text-amber-400" />}
                          <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ring-1 ring-inset ${STATUS_STYLES[mission.status] || STATUS_STYLES.in_progress}`}>
                            {STATUS_LABELS[mission.status] || mission.status}
                          </span>
                        </div>
                        <div className="mt-1 flex items-center gap-3 text-xs text-dark-muted">
                          {mission.description && <span className="truncate max-w-xs">{mission.description}</span>}
                          <span className="flex items-center gap-1"><Server className="h-3 w-3" /> {mission.target_count} targets</span>
                          {mission.start_date && <span className="flex items-center gap-1"><Calendar className="h-3 w-3" /> {mission.start_date}</span>}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={(e) => { e.stopPropagation(); toggleMissionLog(mission.id); }}
                        className="rounded p-1.5 text-dark-muted hover:bg-dark-elevated hover:text-white"
                        title="Show mission log"
                      >
                        {expandedMissionId === mission.id ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                      </button>
                      <button onClick={() => handleEditMission(mission)} className="rounded p-1.5 text-dark-muted hover:bg-dark-elevated hover:text-white" title="Edit">
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button onClick={() => handleDeleteMission(mission.id)} className="rounded p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400" title="Delete">
                        <Trash2 className="h-4 w-4" />
                      </button>
                      <button onClick={() => navigate(`/missions/${mission.id}`)} className="rounded p-1.5 text-dark-muted hover:text-ey-yellow" title="Open Mission">
                        <ChevronRight className="h-5 w-5" />
                      </button>
                    </div>
                  </div>

                  {/* Expandable Mission Log */}
                  {expandedMissionId === mission.id && (
                    <div className="border-t border-dark-border bg-dark-elevated/30 px-4 py-3 space-y-3">
                      {loadingLog === mission.id ? (
                        <div className="flex items-center gap-2 text-sm text-dark-secondary">
                          <div className="h-4 w-4 animate-spin rounded-full border-2 border-ey-yellow border-t-transparent" />
                          Loading mission log…
                        </div>
                      ) : (
                        <>
                          {/* Targets section */}
                          <div>
                            <h5 className="text-xs font-semibold text-dark-secondary uppercase tracking-wider mb-1 flex items-center gap-1">
                              <Server className="h-3 w-3" /> Assigned Targets ({(missionTargets[mission.id] || []).length})
                            </h5>
                            {(missionTargets[mission.id] || []).length === 0 ? (
                              <p className="text-xs text-dark-muted">No targets assigned</p>
                            ) : (
                              <div className="flex flex-wrap gap-2">
                                {(missionTargets[mission.id] || []).map(t => (
                                  <span key={t.id} className="inline-flex items-center gap-1 rounded-full bg-dark-elevated px-2.5 py-0.5 text-xs text-dark-secondary">
                                    <Server className="h-3 w-3 text-sky-400" />
                                    {t.hostname || t.ip_address || `#${t.id}`}
                                    <span className="text-dark-muted">({t.target_type})</span>
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>

                          {/* Scans section */}
                          <div>
                            <h5 className="text-xs font-semibold text-dark-secondary uppercase tracking-wider mb-1 flex items-center gap-1">
                              <Activity className="h-3 w-3" /> Scan Activity ({(missionScans[mission.id] || []).length})
                            </h5>
                            {(missionScans[mission.id] || []).length === 0 ? (
                              <p className="text-xs text-dark-muted">No scans yet</p>
                            ) : (
                              <div className="space-y-1">
                                {(missionScans[mission.id] || []).slice(0, 5).map(s => (
                                  <div key={s.id} className="flex items-center justify-between rounded-lg bg-dark-elevated/50 px-3 py-1.5 text-xs">
                                    <div className="flex items-center gap-2">
                                      <Play className="h-3 w-3 text-dark-muted" />
                                      <span className="text-white">{s.target_hostname || s.target_ip || `Target #${s.target_id}`}</span>
                                      <span className="text-dark-muted">•</span>
                                      <span className="text-dark-secondary">{s.benchmark_name || 'Unknown'}</span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                      {s.compliance_percentage != null && (
                                        <span className={`font-medium ${
                                          (s.compliance_percentage || 0) >= 80 ? 'text-emerald-400' :
                                          (s.compliance_percentage || 0) >= 50 ? 'text-amber-400' : 'text-red-400'
                                        }`}>{s.compliance_percentage.toFixed(1)}%</span>
                                      )}
                                      <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ${
                                        (s.status === 'completed' || s.status === 'imported') ? 'bg-emerald-500/10 text-emerald-400' :
                                        s.status === 'running' ? 'bg-sky-500/10 text-sky-400' :
                                        s.status === 'failed' ? 'bg-red-500/10 text-red-400' :
                                        'bg-dark-overlay text-dark-secondary'
                                      }`}>{s.status}</span>
                                    </div>
                                  </div>
                                ))}
                                {(missionScans[mission.id] || []).length > 5 && (
                                  <p className="text-xs text-dark-muted text-center">+ {(missionScans[mission.id] || []).length - 5} more scans</p>
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
        </>
      )}

      {/* ── Targets Tab ────────────────────────────────────── */}
      {activeTab === 'targets' && (
        <>
          {/* Target Form Modal */}
          {showTargetForm && (
            <div className="rounded-xl border border-dark-border bg-dark-card p-6">
              <h3 className="mb-4 text-lg font-semibold text-white">{editingTargetId ? 'Edit Target' : 'New Target'}</h3>
              <form onSubmit={handleTargetSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-medium text-dark-secondary">Hostname</label>
                  <input value={targetForm.hostname} onChange={e => setTargetForm({ ...targetForm, hostname: e.target.value })} className={inputClass} placeholder="server01.local" />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-dark-secondary">IP Address</label>
                  <input value={targetForm.ip_address} onChange={e => setTargetForm({ ...targetForm, ip_address: e.target.value })} className={inputClass} placeholder="192.168.1.100" />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-dark-secondary">Type *</label>
                  <select value={targetForm.target_type} onChange={e => setTargetForm({ ...targetForm, target_type: e.target.value })} className={inputClass}>
                    <option value="windows">Windows</option>
                    <option value="linux">Linux</option>
                    <option value="network">Network</option>
                    <option value="database">Database</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-dark-secondary">Connection Method</label>
                  <select value={targetForm.connection_method} onChange={e => setTargetForm({ ...targetForm, connection_method: e.target.value })} className={inputClass}>
                    <option value="ssh">SSH</option>
                    <option value="winrm">WinRM</option>
                    <option value="local">Local</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-dark-secondary">SSH Username</label>
                  <input value={targetForm.ssh_username} onChange={e => setTargetForm({ ...targetForm, ssh_username: e.target.value })} className={inputClass} placeholder="admin" />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-dark-secondary">SSH Password</label>
                  <input type="password" value={targetForm.ssh_password} onChange={e => setTargetForm({ ...targetForm, ssh_password: e.target.value })} className={inputClass} placeholder="••••••••" />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-dark-secondary">Port</label>
                  <input value={targetForm.port} onChange={e => setTargetForm({ ...targetForm, port: e.target.value })} className={inputClass} placeholder="22" />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-dark-secondary">Notes</label>
                  <input value={targetForm.notes} onChange={e => setTargetForm({ ...targetForm, notes: e.target.value })} className={inputClass} placeholder="Optional notes…" />
                </div>
                <div className="flex gap-2 sm:col-span-2">
                  <button type="submit" className="rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover">
                    {editingTargetId ? 'Update' : 'Create'}
                  </button>
                  <button type="button" onClick={cancelTargetForm} className="rounded-lg border border-dark-border px-4 py-2 text-sm text-dark-secondary hover:bg-dark-elevated hover:text-white">
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Target Cards */}
          {filteredTargets.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card p-12 text-center">
              <Server className="mx-auto h-10 w-10 text-dark-muted" />
              <p className="mt-3 text-dark-secondary">No targets yet. Add one to this client.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {filteredTargets.map(target => {
                const TargetIcon = TARGET_ICONS[target.target_type] || Server;
                return (
                  <div key={target.id} className="rounded-xl border border-dark-border bg-dark-card p-4 transition-all hover:border-dark-border/80 hover:bg-dark-elevated/50">
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-3">
                        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-dark-elevated">
                          <TargetIcon className="h-4 w-4 text-sky-400" />
                        </div>
                        <div>
                          <h4 className="text-sm font-medium text-white">{target.hostname || target.ip_address || `Target #${target.id}`}</h4>
                          <p className="text-xs text-dark-muted">{target.target_type} • {target.connection_method || 'N/A'}</p>
                        </div>
                      </div>
                      <div className="flex gap-1">
                        <button onClick={() => handleEditTarget(target)} className="rounded p-1 text-dark-muted hover:bg-dark-elevated hover:text-white">
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button onClick={() => handleDeleteTarget(target.id)} className="rounded p-1 text-dark-muted hover:bg-red-500/10 hover:text-red-400">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                    {target.ip_address && target.hostname && (
                      <p className="mt-2 text-xs text-dark-muted">{target.ip_address}{target.port ? `:${target.port}` : ''}</p>
                    )}
                    {target.notes && <p className="mt-1 text-xs text-dark-muted truncate">{target.notes}</p>}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
