import { useEffect, useState, useMemo, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Crosshair,
  Lock,
  Unlock,
  Play,
  AlertTriangle,
  BarChart3,
  Calendar,
  Bot,
  Activity,
  Server,
} from 'lucide-react';
import type { Mission, Target, Client, ScanDetail, Benchmark } from '@/types';
import * as api from '@/services/api';
import { STATUS_STYLES, STATUS_LABELS, inputClass } from '@/components/mission/badgeHelpers';

/* ── Tab-level components ──────────────────────────────────── */
import MissionOverview from '@/components/mission/MissionOverview';
import MissionFindings from '@/components/mission/MissionFindings';
import MissionReports from '@/components/mission/MissionReports';
import TargetsTab from '@/components/targets/TargetsTab';
import ScansTab from '@/components/mission/ScansTab';

/* ── Tab types ───────────────────────────────────────────────── */
type MissionTab = 'overview' | 'targets' | 'scans' | 'findings' | 'reports';

export default function MissionWorkspace() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const missionId = Number(id);

  /* ── Core data ───────────────────────────────────────────── */
  const [mission, setMission] = useState<Mission | null>(null);
  const [client, setClient] = useState<Client | null>(null);
  const [missionTargets, setMissionTargets] = useState<Target[]>([]);
  const [clientTargets, setClientTargets] = useState<Target[]>([]);
  const [scans, setScans] = useState<ScanDetail[]>([]);
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  /* ── Tab state ───────────────────────────────────────────── */
  const [activeTab, setActiveTab] = useState<MissionTab>('overview');

  /* ── Lock state ──────────────────────────────────────────── */
  const [lockPassword, setLockPassword] = useState('');
  const [showLockDialog, setShowLockDialog] = useState(false);
  const [lockAction, setLockAction] = useState<'lock' | 'unlock'>('lock');
  const [lockLoading, setLockLoading] = useState(false);

  /* ── Fetch data ──────────────────────────────────────────── */
  const fetchData = useCallback(async () => {
    try {
      const [m, scanRes, bms] = await Promise.all([
        api.getMission(missionId),
        api.getScans({ mission_id: missionId }),
        api.getBenchmarks(),
      ]);
      setMission(m);
      setScans(scanRes.data);
      setBenchmarks(bms.filter(b => b.is_ready));

      const targets = await api.getTargets(missionId);
      setMissionTargets(targets);

      if (m.client_id) {
        const [c, ct] = await Promise.all([
          api.getClient(m.client_id),
          api.getClientTargets(m.client_id),
        ]);
        setClient(c);
        setClientTargets(ct);
      }
    } catch {
      setError('Failed to load mission data');
    } finally {
      setLoading(false);
    }
  }, [missionId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  /* ── Auto-dismiss errors ───────────────────────────────────── */
  useEffect(() => {
    if (!error) return;
    const timer = setTimeout(() => setError(''), 5000);
    return () => clearTimeout(timer);
  }, [error]);

  /* ── Lock/Unlock ─────────────────────────────────────────── */
  const handleLock = async () => {
    if (!lockPassword) return;
    setLockLoading(true);
    try {
      if (lockAction === 'lock') {
        const updated = await api.lockMission(missionId, lockPassword);
        setMission(updated);
      } else {
        const updated = await api.unlockMission(missionId, lockPassword);
        setMission(updated);
      }
      setShowLockDialog(false);
      setLockPassword('');
    } catch (err: any) {
      setError(err?.response?.data?.detail || `Failed to ${lockAction} mission`);
    } finally {
      setLockLoading(false);
    }
  };

  /* ── Compliance stats ────────────────────────────────────── */
  const stats = useMemo(() => {
    const completed = scans.filter(s => s.status === 'completed' || s.status === 'imported');
    const totalPassed = completed.reduce((sum, s) => sum + s.passed, 0);
    const totalFailed = completed.reduce((sum, s) => sum + s.failed, 0);
    const avgCompliance = completed.length > 0
      ? completed.reduce((sum, s) => sum + (s.compliance_percentage || 0), 0) / completed.length
      : 0;
    return { totalPassed, totalFailed, avgCompliance };
  }, [scans]);

  /* ── Loading / Not found ─────────────────────────────────── */
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-ey-yellow border-t-transparent" />
      </div>
    );
  }

  if (!mission) {
    return (
      <div className="py-12 text-center text-dark-secondary">
        Mission not found.{' '}
        <button onClick={() => navigate('/clients')} className="text-ey-yellow hover:underline">Go back</button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Back button */}
      <button
        onClick={() => navigate(client ? `/clients/${client.id}` : '/clients')}
        className="inline-flex items-center gap-1 text-sm text-dark-secondary hover:text-ey-yellow transition-colors"
      >
        <ArrowLeft className="h-4 w-4" /> Back to {client?.name || 'Client'}
      </button>

      {/* Mission Header Card */}
      <div className="relative overflow-hidden rounded-xl border border-dark-border bg-dark-card p-6">
        <div className="absolute inset-0 bg-gradient-to-br from-ey-yellow/5 via-transparent to-transparent" />
        <div className="relative">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-ey-yellow/10">
                  <Crosshair className="h-5 w-5 text-ey-yellow" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-xl font-bold text-white">{mission.name}</h2>
                    {mission.is_locked && <Lock className="h-4 w-4 text-amber-400" />}
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ring-1 ring-inset ${STATUS_STYLES[mission.status] || STATUS_STYLES.in_progress}`}>
                      {STATUS_LABELS[mission.status] || mission.status}
                    </span>
                  </div>
                  {client && <p className="text-sm text-dark-secondary">Client: {client.name}</p>}
                </div>
              </div>
              {mission.description && <p className="mt-3 text-sm text-dark-muted">{mission.description}</p>}
              <div className="mt-2 flex flex-wrap gap-4 text-xs text-dark-muted">
                {mission.start_date && <span className="flex items-center gap-1"><Calendar className="h-3 w-3" /> Start: {mission.start_date}</span>}
                {mission.end_date && <span className="flex items-center gap-1"><Calendar className="h-3 w-3" /> End: {mission.end_date}</span>}
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  setLockAction(mission.is_locked ? 'unlock' : 'lock');
                  setShowLockDialog(true);
                  setLockPassword('');
                }}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${mission.is_locked
                  ? 'border-amber-500/30 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20'
                  : 'border-dark-border bg-dark-elevated text-dark-secondary hover:bg-dark-elevated hover:text-white'
                  }`}
              >
                {mission.is_locked ? <Unlock className="h-3.5 w-3.5" /> : <Lock className="h-3.5 w-3.5" />}
                {mission.is_locked ? 'Unlock' : 'Lock'}
              </button>
              <button
                onClick={() => navigate(`/missions/${missionId}/analysis`)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-xs font-medium text-dark-secondary hover:text-white transition-colors"
              >
                <Bot className="h-3.5 w-3.5" /> AI Analysis
              </button>
            </div>
          </div>

          {/* Stats Row */}
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
            {[
              { label: 'Targets', value: missionTargets.length, color: 'text-sky-400' },
              { label: 'Scans', value: scans.length, color: 'text-purple-400' },
              { label: 'Passed', value: stats.totalPassed, color: 'text-emerald-400' },
              { label: 'Failed', value: stats.totalFailed, color: 'text-red-400' },
              { label: 'Compliance', value: stats.avgCompliance > 0 ? `${stats.avgCompliance.toFixed(1)}%` : '—', color: 'text-ey-yellow' },
            ].map(s => (
              <div key={s.label} className="rounded-lg bg-dark-elevated/50 p-3 text-center">
                <p className={`text-lg font-bold ${s.color}`}>{s.value}</p>
                <p className="text-[10px] text-dark-muted">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Lock Dialog */}
      {showLockDialog && (
        <div className="rounded-xl border border-dark-border bg-dark-card p-6">
          <h3 className="mb-3 text-lg font-semibold text-white">{lockAction === 'lock' ? 'Lock Mission' : 'Unlock Mission'}</h3>
          <p className="mb-4 text-sm text-dark-secondary">
            {lockAction === 'lock'
              ? 'Set a password to lock this mission. Locked missions cannot be modified.'
              : 'Enter the password to unlock this mission.'}
          </p>
          <div className="flex items-center gap-3">
            <input
              type="password"
              value={lockPassword}
              onChange={e => setLockPassword(e.target.value)}
              placeholder="Password"
              className={`${inputClass} max-w-xs`}
            />
            <button
              onClick={handleLock}
              disabled={!lockPassword || lockLoading}
              className="rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-black hover:bg-ey-yellow-hover disabled:opacity-50"
            >
              {lockLoading ? 'Processing…' : lockAction === 'lock' ? 'Lock' : 'Unlock'}
            </button>
            <button onClick={() => setShowLockDialog(false)} className="rounded-lg border border-dark-border px-4 py-2 text-sm text-dark-secondary hover:bg-dark-elevated">
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}<button onClick={() => setError('')} className="ml-2 text-red-300 hover:text-white">×</button></div>}

      {/* Tab Bar */}
      <div className="flex items-center gap-1 border-b border-dark-border overflow-x-auto">
        {([
          { key: 'overview' as const, label: 'Overview', icon: Activity },
          { key: 'targets' as const, label: 'Targets', icon: Server, count: missionTargets.length },
          { key: 'scans' as const, label: 'Scans', icon: Play, count: scans.length },
          { key: 'findings' as const, label: 'Findings', icon: AlertTriangle },
          { key: 'reports' as const, label: 'Reports', icon: BarChart3 },
        ]).map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex items-center gap-2 whitespace-nowrap border-b-2 px-4 py-3 text-sm font-medium transition-colors ${activeTab === tab.key
              ? 'border-ey-yellow text-ey-yellow'
              : 'border-transparent text-dark-secondary hover:text-white'
              }`}
          >
            <tab.icon className="h-4 w-4" />
            {tab.label}
            {tab.count !== undefined && <span className="rounded-full bg-dark-elevated px-2 py-0.5 text-xs">{tab.count}</span>}
          </button>
        ))}
      </div>

      {/* ── Tab Content ──────────────────────────────────────── */}
      {activeTab === 'overview' && (
        <MissionOverview mission={mission} scans={scans} missionTargets={missionTargets} />
      )}

      {activeTab === 'targets' && (
        <TargetsTab
          missionId={missionId}
          clientId={mission.client_id}
          missionTargets={missionTargets}
          clientTargets={clientTargets}
          onRefresh={fetchData}
        />
      )}

      {activeTab === 'scans' && (
        <ScansTab
          missionId={missionId}
          missionTargets={missionTargets}
          scans={scans}
          benchmarks={benchmarks}
          client={client}
          mission={mission}
          onRefresh={fetchData}
          onError={setError}
        />
      )}

      {activeTab === 'findings' && (
        <MissionFindings scans={scans} />
      )}

      {activeTab === 'reports' && (
        <MissionReports missionId={String(missionId)} missionName={mission?.name} />
      )}
    </div>
  );
}
