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
  Activity,
  LayoutDashboard,
  BarChart3,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer } from 'recharts';
import type { Client, Mission, Target, ScanDetail } from '@/types';
import * as api from '../services/api';
import logoImg from '../assets/logo.png';

/* ── Status styling ──────────────────────────────────────────── */
const STATUS_STYLES: Record<string, string> = {
  in_progress: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20',
  completed: 'bg-sky-500/10 text-sky-400 ring-sky-500/20',
  cancelled: 'bg-dark-overlay text-dark-secondary ring-dark-border',
};
const STATUS_LABELS: Record<string, string> = { in_progress: 'In Progress', completed: 'Completed', cancelled: 'Cancelled' };

const TARGET_ICONS: Record<string, typeof Monitor> = { windows: Monitor, linux: Server, network: Globe };

/* ── Tab type ────────────────────────────────────────────────── */
type WorkspaceTab = 'overview' | 'missions' | 'targets';

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

const inputClass = 'block w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:ring-1 focus:ring-ey-yellow/30 focus:outline-none transition-all';

export default function ClientWorkspace() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const clientId = Number(id);

  /* ── Data state ──────────────────────────────────────────── */
  const [client, setClient] = useState<Client | null>(null);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [clientScans, setClientScans] = useState<ScanDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  /* ── Tab state ───────────────────────────────────────────── */
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('overview');
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
      const [c, m, t, allScans] = await Promise.all([
        api.getClient(clientId),
        api.getMissions(clientId),
        api.getClientTargets(clientId),
        api.getScans({})
      ]);
      setClient(c);
      setMissions(m);
      setTargets(t);

      // Filter scans that belong to this client's missions or targets
      const missionIds = m.map(mission => mission.id);
      const targetIds = t.map(target => target.id);
      const filteredScans = allScans.data.filter(s =>
        (s.mission_id && missionIds.includes(s.mission_id)) ||
        (s.target_id && targetIds.includes(s.target_id))
      );
      setClientScans(filteredScans);

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

  /* ── Aggregated Dashboard Data ────────────────────────────── */
  const dashboardStats = useMemo(() => {
    const completedScans = clientScans.filter(s => s.status === 'completed' && s.compliance_percentage !== null);

    // Average Compliance
    const avgCompliance = completedScans.length > 0
      ? completedScans.reduce((acc, scan) => acc + (scan.compliance_percentage || 0), 0) / completedScans.length
      : 0;

    // Highest and Lowest Risk Targets based on latest scans
    const latestScansByTarget: Record<number, ScanDetail> = {};
    completedScans.forEach(scan => {
      if (!latestScansByTarget[scan.target_id] || new Date(scan.completed_at!) > new Date(latestScansByTarget[scan.target_id].completed_at!)) {
        latestScansByTarget[scan.target_id] = scan;
      }
    });

    const targetsWithScans = Object.values(latestScansByTarget).sort((a, b) => (a.compliance_percentage || 0) - (b.compliance_percentage || 0));

    return {
      avgCompliance: Math.round(avgCompliance),
      totalScans: clientScans.length,
      passedScans: completedScans.filter(s => (s.compliance_percentage || 0) >= 80).length,
      failedScans: completedScans.filter(s => (s.compliance_percentage || 0) < 50).length,
      lowestComplianceTargets: targetsWithScans.slice(0, 3)
    };
  }, [clientScans]);

  const complianceTrendData = useMemo(() => {
    const completedScans = clientScans.filter(s => s.status === 'completed' && s.completed_at && s.compliance_percentage !== null)
      .sort((a, b) => new Date(a.completed_at!).getTime() - new Date(b.completed_at!).getTime());

    // Group by month or day
    const trend: Record<string, { total: number, count: number }> = {};
    completedScans.forEach(scan => {
      const date = new Date(scan.completed_at!).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      if (!trend[date]) trend[date] = { total: 0, count: 0 };
      trend[date].total += (scan.compliance_percentage || 0);
      trend[date].count += 1;
    });

    return Object.keys(trend).map(date => ({
      date,
      compliance: Math.round(trend[date].total / trend[date].count)
    }));
  }, [clientScans]);

  /* ── Mission CRUD ────────────────────────────────────────── */
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
    <div className="space-y-6 pb-10">
      {/* Back button */}
      <button onClick={() => navigate('/clients')} className="inline-flex items-center gap-1.5 text-sm font-medium text-dark-secondary hover:text-ey-yellow transition-colors">
        <ArrowLeft className="h-4 w-4" /> Back to Clients
      </button>

      {/* Client Header Card */}
      <div className="relative overflow-hidden rounded-2xl border border-dark-border bg-dark-card p-6 shadow-lg">
        <div className="absolute inset-0 bg-gradient-to-br from-ey-yellow/10 via-transparent to-transparent opacity-50" />
        <div className="relative flex flex-col md:flex-row md:items-start justify-between gap-6">
          <div>
            <div className="flex items-center gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-ey-yellow/10 border border-ey-yellow/20 shadow-inner">
                <Building2 className="h-7 w-7 text-ey-yellow" />
              </div>
              <div>
                <h2 className="text-2xl font-bold text-white tracking-tight">{client.name}</h2>
                {client.industry && <p className="text-sm font-medium text-dark-secondary mt-0.5">{client.industry}</p>}
              </div>
            </div>
            <div className="mt-5 flex flex-wrap gap-5 text-sm">
              {client.contact_name && (
                <div className="flex items-center gap-2 text-dark-secondary bg-dark-elevated px-3 py-1.5 rounded-lg border border-dark-border/50">
                  <User className="h-4 w-4 text-dark-muted" /> {client.contact_name}
                </div>
              )}
              {client.contact_email && (
                <div className="flex items-center gap-2 text-dark-secondary bg-dark-elevated px-3 py-1.5 rounded-lg border border-dark-border/50">
                  <Mail className="h-4 w-4 text-dark-muted" /> {client.contact_email}
                </div>
              )}
            </div>
            {client.notes && <p className="mt-4 text-sm text-dark-muted max-w-2xl leading-relaxed">{client.notes}</p>}
          </div>

          {/* Quick Info Stats */}
          <div className="flex gap-4 md:gap-8 self-start md:self-auto bg-dark-elevated/50 p-4 rounded-xl border border-dark-border/50">
            <div className="text-center">
              <p className="text-3xl font-bold text-white">{missions.length}</p>
              <p className="text-xs font-medium text-dark-secondary uppercase tracking-wider mt-1">Missions</p>
            </div>
            <div className="w-px bg-dark-border" />
            <div className="text-center">
              <p className="text-3xl font-bold text-white">{targets.length}</p>
              <p className="text-xs font-medium text-dark-secondary uppercase tracking-wider mt-1">Targets</p>
            </div>
          </div>
        </div>
      </div>

      {/* Tab Bar */}
      <div className="flex items-center gap-2 border-b border-dark-border overflow-x-auto custom-scrollbar pb-px">
        {([
          { key: 'overview' as const, label: 'Overview Dashboard', icon: LayoutDashboard },
          { key: 'missions' as const, label: 'Missions', icon: Crosshair, count: missions.length },
          { key: 'targets' as const, label: 'Targets', icon: Server, count: targets.length },
        ]).map(tab => (
          <button
            key={tab.key}
            onClick={() => { setActiveTab(tab.key); setSearch(''); }}
            className={`flex items-center gap-2 border-b-2 px-5 py-3.5 text-sm font-medium transition-all ${activeTab === tab.key
              ? 'border-ey-yellow text-ey-yellow bg-ey-yellow/5'
              : 'border-transparent text-dark-secondary hover:text-white hover:bg-dark-elevated/50'
              } rounded-t-lg`}
          >
            <tab.icon className={`h-4 w-4 ${activeTab === tab.key ? 'text-ey-yellow' : 'text-dark-muted'}`} />
            {tab.label}
            {tab.count !== undefined && <span className={`rounded-full px-2.5 py-0.5 text-xs ${activeTab === tab.key ? 'bg-ey-yellow/20 text-ey-yellow font-bold' : 'bg-dark-elevated text-dark-secondary'}`}>{tab.count}</span>}
          </button>
        ))}
      </div>

      {/* ── Overview Dashboard Tab ──────────────────────────────── */}
      {activeTab === 'overview' && (
        <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="glow-card rounded-xl border border-dark-border bg-dark-card p-5">
              <h4 className="text-xs font-semibold text-dark-secondary uppercase tracking-wider">Health Score</h4>
              <div className="mt-3 flex items-end gap-2">
                <span className={`text-4xl font-bold ${dashboardStats.avgCompliance >= 80 ? 'text-emerald-400' : dashboardStats.avgCompliance >= 50 ? 'text-amber-400' : 'text-red-400'}`}>
                  {dashboardStats.avgCompliance}%
                </span>
                <span className="text-sm font-medium text-dark-muted mb-1">avg</span>
              </div>
              <div className="mt-4 h-1.5 w-full rounded-full bg-dark-overlay overflow-hidden">
                <div
                  className={`h-full rounded-full ${dashboardStats.avgCompliance >= 80 ? 'bg-emerald-400' : dashboardStats.avgCompliance >= 50 ? 'bg-amber-400' : 'bg-red-400'}`}
                  style={{ width: `${dashboardStats.avgCompliance}%` }}
                />
              </div>
            </div>

            <div className="glow-card rounded-xl border border-dark-border bg-dark-card p-5">
              <h4 className="text-xs font-semibold text-dark-secondary uppercase tracking-wider">Total Scans</h4>
              <div className="mt-3 flex items-center gap-3">
                <Activity className="h-8 w-8 text-sky-400" />
                <span className="text-4xl font-bold text-white">{dashboardStats.totalScans}</span>
              </div>
            </div>

            <div className="glow-card rounded-xl border border-dark-border bg-dark-card p-5">
              <h4 className="text-xs font-semibold text-dark-secondary uppercase tracking-wider">Strong Scans</h4>
              <div className="mt-3 flex items-center gap-3">
                <ShieldCheck className="h-8 w-8 text-emerald-400" />
                <span className="text-4xl font-bold text-white">{dashboardStats.passedScans}</span>
              </div>
            </div>

            <div className="glow-card rounded-xl border border-dark-border bg-dark-card p-5">
              <h4 className="text-xs font-semibold text-dark-secondary uppercase tracking-wider">Critical Scans</h4>
              <div className="mt-3 flex items-center gap-3">
                <ShieldAlert className="h-8 w-8 text-red-400" />
                <span className="text-4xl font-bold text-white">{dashboardStats.failedScans}</span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="col-span-1 lg:col-span-2 glow-card rounded-xl border border-dark-border bg-dark-card p-6">
              <h4 className="flex items-center gap-2 text-sm font-semibold text-white mb-6">
                <BarChart3 className="h-4 w-4 text-ey-yellow" /> Client Compliance Trend
              </h4>
              <div className="h-[250px] w-full">
                {complianceTrendData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={complianceTrendData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <defs>
                        <linearGradient id="colorTrend" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#FFE600" stopOpacity={0.3} />
                          <stop offset="95%" stopColor="#FFE600" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#2A2A2A" vertical={false} />
                      <XAxis dataKey="date" stroke="#666" tick={{ fill: '#888', fontSize: 12 }} axisLine={false} tickLine={false} />
                      <YAxis stroke="#666" tick={{ fill: '#888', fontSize: 12 }} axisLine={false} tickLine={false} domain={[0, 100]} />
                      <RechartsTooltip
                        contentStyle={{ backgroundColor: '#1A1A1A', borderColor: '#333', borderRadius: '8px', color: '#fff' }}
                        itemStyle={{ color: '#FFE600' }}
                        formatter={(value: any) => [`${value}%`, 'Compliance']}
                      />
                      <Area type="monotone" dataKey="compliance" stroke="#FFE600" strokeWidth={2} fillOpacity={1} fill="url(#colorTrend)" />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-full items-center justify-center border-2 border-dashed border-dark-border rounded-lg">
                    <p className="text-sm text-dark-muted">No scan history available to build trend chart.</p>
                  </div>
                )}
              </div>
            </div>

            <div className="col-span-1 glow-card rounded-xl border border-dark-border bg-dark-card p-6 flex flex-col">
              <h4 className="flex items-center gap-2 text-sm font-semibold text-white mb-4">
                <ShieldAlert className="h-4 w-4 text-amber-400" /> Attention Needed
              </h4>
              <p className="text-xs text-dark-secondary mb-4">Lowest compliant targets based on recent scans.</p>

              <div className="flex-1 space-y-3 overflow-y-auto pr-1">
                {dashboardStats.lowestComplianceTargets.length > 0 ? (
                  dashboardStats.lowestComplianceTargets.map(scan => (
                    <div key={scan.id} className="flex flex-col gap-2 rounded-lg border border-dark-border bg-dark-elevated p-3">
                      <div className="flex justify-between items-center">
                        <span className="text-sm font-medium text-white truncate max-w-[150px]">{scan.target_hostname || `Target #${scan.target_id}`}</span>
                        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${(scan.compliance_percentage || 0) < 50 ? 'bg-red-500/10 text-red-400' : 'bg-amber-500/10 text-amber-400'
                          }`}>
                          {scan.compliance_percentage}%
                        </span>
                      </div>
                      <div className="flex justify-between items-center text-xs text-dark-muted">
                        <span className="truncate flex-1 pr-2">{scan.benchmark_name}</span>
                        <span>{new Date(scan.completed_at!).toLocaleDateString()}</span>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="flex h-full flex-col items-center justify-center text-center">
                    <img src={logoImg} alt="logo" className="h-8 w-8 object-contain opacity-50 mb-2 grayscale" />
                    <p className="text-xs text-dark-muted">No low compliance targets found.</p>
                  </div>
                )}
              </div>
              <button onClick={() => { setActiveTab('targets') }} className="mt-4 w-full py-2 text-xs font-semibold text-ey-yellow border border-ey-yellow/30 rounded-lg hover:bg-ey-yellow/10 transition-colors">
                View All Targets
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Utilities for Missions & Targets Tabs */}
      {(activeTab === 'missions' || activeTab === 'targets') && (
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
      )}

      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}<button onClick={() => setError('')} className="ml-2 text-red-300 hover:text-white">×</button></div>}

      {/* ── Missions Tab ───────────────────────────────────── */}
      {activeTab === 'missions' && (
        <div className="animate-in fade-in slide-in-from-bottom-2 duration-300">
          {/* Status Filter Chips */}
          <div className="mb-6 flex flex-wrap gap-2">
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
                  className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-medium transition-colors ${colors[key]}`}
                >
                  <span className="text-sm">{labels[key]}</span>
                  <span className="rounded-full bg-black/20 px-2 py-0.5 text-xs">{statusCounts[key] || 0}</span>
                </button>
              );
            })}
          </div>

          {/* Mission Form Modal */}
          {showMissionForm && (
            <div className="mb-6 rounded-xl border border-dark-border bg-dark-card p-6 shadow-xl animate-in fade-in zoom-in-95 duration-200">
              <h3 className="mb-4 text-lg font-semibold text-white border-b border-dark-border pb-3">{editingMissionId ? 'Edit Mission' : 'New Mission'}</h3>
              <form onSubmit={handleMissionSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <label className="mb-1 block text-sm font-medium text-dark-secondary">Name *</label>
                  <input name="name" value={missionForm.name} onChange={e => setMissionForm({ ...missionForm, name: e.target.value })} required className={inputClass} placeholder="Q1 2025 Audit" />
                </div>
                <div className="sm:col-span-2">
                  <label className="mb-1 block text-sm font-medium text-dark-secondary">Description</label>
                  <textarea name="description" value={missionForm.description} onChange={e => setMissionForm({ ...missionForm, description: e.target.value })} rows={2} className={`${inputClass} resize-none`} placeholder="Mission scope and objectives…" />
                </div>
                {editingMissionId && (
                  <div>
                    <label className="mb-1 block text-sm font-medium text-dark-secondary">Status</label>
                    <select value={missionForm.status} onChange={e => setMissionForm({ ...missionForm, status: e.target.value })} className={inputClass}>
                      <option value="in_progress">In Progress</option>
                      <option value="completed">Completed</option>
                      <option value="cancelled">Cancelled</option>
                    </select>
                  </div>
                )}
                <div className={editingMissionId ? '' : 'sm:col-span-1'}>
                  <label className="mb-1 block text-sm font-medium text-dark-secondary">Start Date</label>
                  <input type="date" value={missionForm.start_date} onChange={e => setMissionForm({ ...missionForm, start_date: e.target.value })} className={inputClass} />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-dark-secondary">End Date</label>
                  <input type="date" value={missionForm.end_date} onChange={e => setMissionForm({ ...missionForm, end_date: e.target.value })} className={inputClass} />
                </div>
                <div className="flex gap-3 justify-end sm:col-span-2 mt-2 pt-4 border-t border-dark-border">
                  <button type="button" onClick={cancelMissionForm} className="rounded-lg border border-dark-border bg-dark-card px-5 py-2 text-sm font-medium text-dark-secondary hover:bg-dark-overlay hover:text-white transition-colors">
                    Cancel
                  </button>
                  <button type="submit" className="rounded-lg bg-ey-yellow px-5 py-2 text-sm font-semibold text-black hover:bg-ey-yellow-hover shadow-lg shadow-ey-yellow/10 transition-all">
                    {editingMissionId ? 'Update Mission' : 'Create Mission'}
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Mission Cards */}
          {filteredMissions.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card/50 p-16 text-center">
              <Crosshair className="mx-auto h-12 w-12 text-dark-muted" />
              <p className="mt-4 font-medium text-white">No missions found</p>
              <p className="mt-1 text-sm text-dark-secondary">Create a mission to start auditing targets.</p>
            </div>
          ) : (
            <div className="grid gap-4">
              {filteredMissions.map(mission => (
                <div key={mission.id} className="glow-card group rounded-xl border border-dark-border bg-dark-card transition-all duration-300 hover:border-dark-hover shadow-sm">
                  <div className="flex items-center justify-between p-5">
                    <div
                      className="flex flex-1 cursor-pointer items-center gap-4 pr-6"
                      onClick={() => navigate(`/missions/${mission.id}`)}
                    >
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-dark-elevated border border-dark-border group-hover:border-ey-yellow/30 transition-colors">
                        <Crosshair className="h-6 w-6 text-ey-yellow" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <h4 className="text-base font-bold text-white truncate group-hover:text-ey-yellow transition-colors">{mission.name}</h4>
                          {mission.is_locked && <Lock className="h-3.5 w-3.5 text-amber-400" />}
                          <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-bold tracking-wide uppercase ${STATUS_STYLES[mission.status] || STATUS_STYLES.in_progress}`}>
                            {STATUS_LABELS[mission.status] || mission.status}
                          </span>
                        </div>
                        <div className="flex items-center gap-4 text-sm text-dark-muted">
                          {mission.description && <span className="truncate max-w-sm hidden md:block text-dark-secondary">{mission.description}</span>}
                          <span className="flex items-center gap-1.5 font-medium"><Server className="h-3.5 w-3.5" /> {mission.target_count} targets</span>
                          {mission.start_date && <span className="flex items-center gap-1.5"><Calendar className="h-3.5 w-3.5" /> {mission.start_date}</span>}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={(e) => { e.stopPropagation(); toggleMissionLog(mission.id); }}
                        className={`rounded-md p-2 transition-colors ${expandedMissionId === mission.id ? 'bg-dark-elevated text-ey-yellow' : 'text-dark-muted hover:bg-dark-elevated hover:text-white'}`}
                        title="Show mission log"
                      >
                        {expandedMissionId === mission.id ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                      </button>
                      <button onClick={(e) => { e.stopPropagation(); handleEditMission(mission); }} className="rounded-md p-2 text-dark-muted hover:bg-ey-yellow/10 hover:text-ey-yellow transition-colors" title="Edit">
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button onClick={(e) => { e.stopPropagation(); handleDeleteMission(mission.id); }} className="rounded-md p-2 text-dark-muted hover:bg-red-500/10 hover:text-red-400 transition-colors" title="Delete">
                        <Trash2 className="h-4 w-4" />
                      </button>
                      <button onClick={() => navigate(`/missions/${mission.id}`)} className="rounded-md p-2 text-dark-muted hover:bg-dark-elevated hover:text-ey-yellow ml-1 transition-colors" title="Open Mission">
                        <ChevronRight className="h-5 w-5" />
                      </button>
                    </div>
                  </div>

                  {/* Expandable Mission Log */}
                  {expandedMissionId === mission.id && (
                    <div className="border-t border-dark-border bg-dark-elevated/30 p-5 space-y-5 rounded-b-xl animate-in slide-in-from-top-2 duration-200">
                      {loadingLog === mission.id ? (
                        <div className="flex items-center justify-center gap-3 text-sm text-dark-secondary py-4">
                          <div className="h-5 w-5 animate-spin rounded-full border-2 border-ey-yellow border-t-transparent" />
                          Loading mission data…
                        </div>
                      ) : (
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                          {/* Targets section */}
                          <div className="bg-dark-card border border-dark-border rounded-lg p-4">
                            <h5 className="text-xs font-bold text-dark-secondary uppercase tracking-widest mb-3 flex items-center gap-2">
                              <Server className="h-4 w-4 text-sky-400" /> Assigned Targets
                              <span className="bg-dark-elevated text-white px-2 py-0.5 rounded-full text-xs ml-auto">{(missionTargets[mission.id] || []).length}</span>
                            </h5>
                            {(missionTargets[mission.id] || []).length === 0 ? (
                              <div className="py-6 text-center border-2 border-dashed border-dark-border rounded-lg">
                                <p className="text-sm text-dark-muted">No targets assigned to this mission.</p>
                              </div>
                            ) : (
                              <div className="flex flex-col gap-2 max-h-48 overflow-y-auto pr-1">
                                {(missionTargets[mission.id] || []).map(t => (
                                  <div key={t.id} className="flex justify-between items-center rounded-md bg-dark-elevated px-3 py-2 text-sm border border-dark-border/50">
                                    <div className="flex items-center gap-2 text-white font-medium">
                                      <Monitor className="h-3.5 w-3.5 text-dark-muted" />
                                      {t.hostname || t.ip_address || `#${t.id}`}
                                    </div>
                                    <span className="text-xs text-dark-secondary uppercase">{t.target_type}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>

                          {/* Scans section */}
                          <div className="bg-dark-card border border-dark-border rounded-lg p-4">
                            <h5 className="text-xs font-bold text-dark-secondary uppercase tracking-widest mb-3 flex items-center gap-2">
                              <Activity className="h-4 w-4 text-amber-400" /> Scan Activity
                              <span className="bg-dark-elevated text-white px-2 py-0.5 rounded-full text-xs ml-auto">{(missionScans[mission.id] || []).length}</span>
                            </h5>
                            {(missionScans[mission.id] || []).length === 0 ? (
                              <div className="py-6 text-center border-2 border-dashed border-dark-border rounded-lg">
                                <p className="text-sm text-dark-muted">No scans run during this mission.</p>
                              </div>
                            ) : (
                              <div className="flex flex-col gap-2 max-h-48 overflow-y-auto pr-1">
                                {(missionScans[mission.id] || []).slice(0, 10).map(s => (
                                  <div key={s.id} className="flex flex-col gap-1 rounded-md bg-dark-elevated px-3 py-2 text-sm border border-dark-border/50">
                                    <div className="flex items-center justify-between">
                                      <span className="font-medium text-white max-w-[150px] truncate">{s.target_hostname || s.target_ip || `Target #${s.target_id}`}</span>
                                      <div className="flex items-center gap-2">
                                        {s.compliance_percentage != null && (
                                          <span className={`font-bold ${(s.compliance_percentage || 0) >= 80 ? 'text-emerald-400' :
                                            (s.compliance_percentage || 0) >= 50 ? 'text-amber-400' : 'text-red-400'
                                            }`}>{s.compliance_percentage.toFixed(0)}%</span>
                                        )}
                                        <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${(s.status === 'completed' || s.status === 'imported') ? 'bg-emerald-500/10 text-emerald-400' :
                                          s.status === 'running' ? 'bg-sky-500/10 text-sky-400' :
                                            s.status === 'failed' ? 'bg-red-500/10 text-red-400' :
                                              'bg-dark-overlay text-dark-secondary'
                                          }`}>{s.status}</span>
                                      </div>
                                    </div>
                                    <div className="flex justify-between items-center text-xs text-dark-muted">
                                      <span className="truncate flex-1">{s.benchmark_name || 'Unknown Benchmark'}</span>
                                      {s.completed_at && <span>{new Date(s.completed_at).toLocaleDateString()}</span>}
                                    </div>
                                  </div>
                                ))}
                                {(missionScans[mission.id] || []).length > 10 && (
                                  <p className="text-xs font-medium text-ey-yellow text-center pt-2 cursor-pointer hover:underline">
                                    View all {(missionScans[mission.id] || []).length} scans
                                  </p>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Targets Tab ────────────────────────────────────── */}
      {activeTab === 'targets' && (
        <div className="animate-in fade-in slide-in-from-bottom-2 duration-300">
          {/* Target Form Modal */}
          {showTargetForm && (
            <div className="mb-6 rounded-xl border border-dark-border bg-dark-card p-6 shadow-xl animate-in fade-in zoom-in-95 duration-200">
              <h3 className="mb-4 text-lg font-semibold text-white border-b border-dark-border pb-3">{editingTargetId ? 'Edit Target' : 'New Target'}</h3>
              <form onSubmit={handleTargetSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-sm font-medium text-dark-secondary">Hostname</label>
                  <input value={targetForm.hostname} onChange={e => setTargetForm({ ...targetForm, hostname: e.target.value })} className={inputClass} placeholder="server01.local" />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-dark-secondary">IP Address</label>
                  <input value={targetForm.ip_address} onChange={e => setTargetForm({ ...targetForm, ip_address: e.target.value })} className={inputClass} placeholder="192.168.1.100" />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-dark-secondary">Type *</label>
                  <select value={targetForm.target_type} onChange={e => setTargetForm({ ...targetForm, target_type: e.target.value })} className={inputClass}>
                    <option value="windows">Windows</option>
                    <option value="linux">Linux</option>
                    <option value="network">Network</option>
                    <option value="database">Database</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-dark-secondary">Connection Method</label>
                  <select value={targetForm.connection_method} onChange={e => setTargetForm({ ...targetForm, connection_method: e.target.value })} className={inputClass}>
                    <option value="ssh">SSH</option>
                    <option value="winrm">WinRM</option>
                    <option value="local">Local</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-dark-secondary">SSH Username</label>
                  <input value={targetForm.ssh_username} onChange={e => setTargetForm({ ...targetForm, ssh_username: e.target.value })} className={inputClass} placeholder="admin" />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-dark-secondary">SSH Password</label>
                  <input type="password" value={targetForm.ssh_password} onChange={e => setTargetForm({ ...targetForm, ssh_password: e.target.value })} className={inputClass} placeholder="••••••••" />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-dark-secondary">Port</label>
                  <input value={targetForm.port} onChange={e => setTargetForm({ ...targetForm, port: e.target.value })} className={inputClass} placeholder="22" />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-dark-secondary">Notes</label>
                  <input value={targetForm.notes} onChange={e => setTargetForm({ ...targetForm, notes: e.target.value })} className={inputClass} placeholder="Optional notes…" />
                </div>
                <div className="flex gap-3 justify-end sm:col-span-2 pt-4 border-t border-dark-border mt-2">
                  <button type="button" onClick={cancelTargetForm} className="rounded-lg border border-dark-border bg-dark-card px-5 py-2 text-sm font-medium text-dark-secondary hover:bg-dark-overlay hover:text-white transition-colors">
                    Cancel
                  </button>
                  <button type="submit" className="rounded-lg bg-ey-yellow px-5 py-2 text-sm font-semibold text-black hover:bg-ey-yellow-hover shadow-lg shadow-ey-yellow/10 transition-all">
                    {editingTargetId ? 'Update Target' : 'Create Target'}
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Target Cards */}
          {filteredTargets.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed border-dark-border bg-dark-card/50 p-16 text-center">
              <Server className="mx-auto h-12 w-12 text-dark-muted" />
              <p className="mt-4 font-medium text-white">No targets found</p>
              <p className="mt-1 text-sm text-dark-secondary">Add targets to this client to begin scanning.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filteredTargets.map((target, index) => {
                const TargetIcon = TARGET_ICONS[target.target_type] || Server;
                return (
                  <div key={target.id} className="glow-card group rounded-xl border border-dark-border bg-dark-card p-5 transition-all duration-300 hover:border-dark-hover shadow-sm" style={{ animationDelay: `${index * 50}ms` }}>
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-4">
                        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-dark-elevated border border-dark-border group-hover:border-sky-500/30 transition-colors">
                          <TargetIcon className="h-6 w-6 text-sky-400" />
                        </div>
                        <div>
                          <h4 className="text-base font-bold text-white group-hover:text-sky-400 transition-colors">{target.hostname || target.ip_address || `Target #${target.id}`}</h4>
                          <span className="inline-block mt-0.5 px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-widest bg-dark-overlay text-dark-secondary border border-dark-border/50">
                            {target.target_type}
                          </span>
                        </div>
                      </div>
                      <div className="flex gap-1 opacity-100 md:opacity-0 group-hover:opacity-100 transition-opacity">
                        <button onClick={() => handleEditTarget(target)} className="rounded-md p-1.5 text-dark-muted hover:bg-ey-yellow/10 hover:text-ey-yellow transition-colors bg-dark-elevated/50 md:bg-transparent">
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button onClick={() => handleDeleteTarget(target.id)} className="rounded-md p-1.5 text-dark-muted hover:bg-red-500/10 hover:text-red-400 transition-colors bg-dark-elevated/50 md:bg-transparent">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </div>

                    <div className="mt-5 space-y-2 text-sm">
                      <div className="flex items-center justify-between border-b border-dark-border/50 pb-2">
                        <span className="text-dark-muted">IP / Port</span>
                        <span className="font-medium text-dark-secondary">{target.ip_address || 'N/A'}{target.port ? `:${target.port}` : ''}</span>
                      </div>
                      <div className="flex items-center justify-between border-b border-dark-border/50 pb-2">
                        <span className="text-dark-muted">Method</span>
                        <span className="font-medium text-dark-secondary uppercase text-xs tracking-wider">{target.connection_method || 'N/A'}</span>
                      </div>
                      {target.notes && (
                        <div className="pt-1">
                          <p className="text-xs text-dark-muted truncate" title={target.notes}>{target.notes}</p>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
