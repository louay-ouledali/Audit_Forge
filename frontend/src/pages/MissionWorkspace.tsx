import { useEffect, useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import BrandLockup from '@/components/common/BrandLockup';
import {
  ArrowLeft,
  Crosshair,
  Lock,
  Unlock,
  AlertTriangle,
  BarChart3,
  Calendar,
  Bot,
  Activity,
  Server,
  Wifi,
} from 'lucide-react';
import type { Mission, Target, Client, ScanDetail } from '@/types';
import * as api from '@/services/api';
import { STATUS_STYLES, STATUS_LABELS, inputClass } from '@/components/mission/badgeHelpers';
import { useNumericParam } from '@/hooks/useNumericParam';
import { extractApiError } from '@/utils/apiError';

/* ── Tab-level components ──────────────────────────────────── */
import MissionOverview from '@/components/mission/MissionOverview';
import MissionFindings from '@/components/mission/MissionFindings';
import { DEFAULT_FILTER_STATE } from '@/components/mission/MissionFindings';
import type { FindingsFilterState } from '@/components/mission/MissionFindings';
import MissionReports from '@/components/mission/MissionReports';
import TargetsTab from '@/components/targets/TargetsTab';
import ConnectSessionManager from '@/components/connect/ConnectSessionManager';

/* ── Tab types ───────────────────────────────────────────────── */
type MissionTab = 'overview' | 'targets' | 'connect' | 'findings' | 'reports';

export default function MissionWorkspace() {
  const missionId = useNumericParam('id');
  const navigate = useNavigate();

  /* ── Core data ───────────────────────────────────────────── */
  const [mission, setMission] = useState<Mission | null>(null);
  const [client, setClient] = useState<Client | null>(null);
  const [missionTargets, setMissionTargets] = useState<Target[]>([]);
  const [clientTargets, setClientTargets] = useState<Target[]>([]);
  const [scans, setScans] = useState<ScanDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  /* ── Tab state ───────────────────────────────────────────── */
  const [activeTab, setActiveTab] = useState<MissionTab>('overview');

  /* ── Findings filter state (persisted across tab switches) ─ */
  const [findingsFilter, setFindingsFilter] = useState<FindingsFilterState>(DEFAULT_FILTER_STATE);
  const [findingsCount, setFindingsCount] = useState(0);

  /* ── Lock state ──────────────────────────────────────────── */
  const [lockPassword, setLockPassword] = useState('');
  const [showLockDialog, setShowLockDialog] = useState(false);
  const [lockAction, setLockAction] = useState<'lock' | 'unlock'>('lock');
  const [lockLoading, setLockLoading] = useState(false);

  /* ── Fetch data ──────────────────────────────────────────── */
  const fetchData = useCallback(async () => {
    try {
      const [m, scanRes] = await Promise.all([
        api.getMission(missionId),
        api.getScans({ mission_id: missionId }),
      ]);
      setMission(m);
      setScans(scanRes.data);

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
      setError(extractApiError(err, `Failed to ${lockAction} mission`));
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
                className="inline-flex items-center gap-1.5 rounded-lg border border-violet-500/20 bg-violet-500/5 px-2 py-1.5 text-xs font-medium text-dark-secondary hover:bg-violet-500/10 transition-colors"
              >
                <BrandLockup service="lens" size="sm" />
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

      {/* Lock Dialog Modal */}
      {showLockDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setShowLockDialog(false)}>
          <div
            className="mx-4 w-full max-w-md rounded-xl border border-dark-border bg-dark-card p-6 shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center gap-3">
              <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${lockAction === 'lock' ? 'bg-amber-500/10' : 'bg-emerald-500/10'}`}>
                {lockAction === 'lock'
                  ? <Lock className="h-5 w-5 text-amber-400" />
                  : <Unlock className="h-5 w-5 text-emerald-400" />}
              </div>
              <div>
                <h3 className="text-lg font-semibold text-white">{lockAction === 'lock' ? 'Lock Mission' : 'Unlock Mission'}</h3>
                <p className="text-xs text-dark-muted">{mission.name}</p>
              </div>
            </div>
            <p className="mb-4 text-sm text-dark-secondary">
              {lockAction === 'lock'
                ? 'Set a password to lock this mission. Locked missions cannot be modified — no scans, imports, or target changes allowed.'
                : 'Enter the password to unlock this mission and allow modifications.'}
            </p>
            <input
              type="password"
              value={lockPassword}
              onChange={e => setLockPassword(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && lockPassword && handleLock()}
              placeholder="Password"
              autoFocus
              className={`${inputClass} mb-4 w-full`}
            />
            {error && (
              <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-2.5 text-xs text-red-400">
                {error}
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button
                onClick={() => { setShowLockDialog(false); setError(''); }}
                className="rounded-lg border border-dark-border px-4 py-2 text-sm text-dark-secondary hover:bg-dark-elevated"
              >
                Cancel
              </button>
              <button
                onClick={handleLock}
                disabled={!lockPassword || lockLoading}
                className={`rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50 ${
                  lockAction === 'lock'
                    ? 'bg-amber-500 text-black hover:bg-amber-400'
                    : 'bg-emerald-500 text-black hover:bg-emerald-400'
                }`}
              >
                {lockLoading ? 'Processing…' : lockAction === 'lock' ? 'Lock Mission' : 'Unlock Mission'}
              </button>
            </div>
          </div>
        </div>
      )}

      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}<button onClick={() => setError('')} className="ml-2 text-red-300 hover:text-white">×</button></div>}

      {/* Tab Bar */}
      <div className="flex items-center gap-1 border-b border-dark-border overflow-x-auto">
        {([
          { key: 'overview' as const, label: 'Overview', icon: Activity },
          { key: 'targets' as const, label: 'Targets', icon: Server, count: missionTargets.length },
          { key: 'connect' as const, label: 'Forge Connect', icon: Wifi },
          { key: 'findings' as const, label: 'Findings', icon: AlertTriangle, count: findingsCount || undefined },
          { key: 'reports' as const, label: 'Reports', icon: BarChart3 },
        ]).map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex items-center gap-2 whitespace-nowrap border-b-2 px-4 py-3 text-sm font-medium transition-colors ${activeTab === tab.key
              ? (tab.key === 'connect' ? 'border-ey-yellow text-white' : 'border-ey-yellow text-ey-yellow')
              : 'border-transparent text-dark-secondary hover:text-white'
              }`}
          >
            {tab.key === 'connect' ? (
              <BrandLockup service="connect" size="sm" hideText={false} />
            ) : (
              <>
                <tab.icon className="h-4 w-4" />
                {tab.label}
              </>
            )}
            {tab.count !== undefined && <span className="rounded-full bg-dark-elevated px-2 py-0.5 text-xs">{tab.count}</span>}
          </button>
        ))}
      </div>

      {/* ── Tab Content ──────────────────────────────────────── */}
      {activeTab === 'overview' && (
        <MissionOverview
          mission={mission}
          scans={scans}
          missionTargets={missionTargets}
          onScanClick={(scanId) => {
            setFindingsFilter({ ...DEFAULT_FILTER_STATE, selectedScanId: scanId });
            setActiveTab('findings');
          }}
        />
      )}

      {activeTab === 'targets' && (
        <TargetsTab
          missionId={missionId}
          clientId={mission.client_id}
          missionTargets={missionTargets}
          clientTargets={clientTargets}
          onRefresh={fetchData}
          onSwitchTab={(tab) => setActiveTab(tab as typeof activeTab)}
          onSwitchToFindings={(scanId) => {
            setFindingsFilter({ ...DEFAULT_FILTER_STATE, selectedScanId: scanId ?? 'all' });
            setActiveTab('findings');
          }}
          isLocked={!!mission.is_locked}
          clientAdConfigured={client?.ad_configured ?? false}
          clientAdDomain={client?.ad_domain}
        />
      )}

      {activeTab === 'connect' && mission && (
        <ConnectSessionManager
          clientId={mission.client_id}
          missionId={missionId}
        />
      )}

      {activeTab === 'findings' && (
        <MissionFindings
          scans={scans}
          isLocked={!!mission.is_locked}
          filterState={findingsFilter}
          onFilterChange={setFindingsFilter}
          onTotalCount={setFindingsCount}
        />
      )}

      {activeTab === 'reports' && (
        <MissionReports missionId={missionId} missionName={mission?.name} />
      )}
    </div>
  );
}
