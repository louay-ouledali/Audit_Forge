import { Server, Calendar, Flag, Activity, Play, CheckCircle2 } from 'lucide-react';
import type { ScanDetail, Target, Mission } from '@/types';
import { scanStatusBadge } from './badgeHelpers';

interface Props {
  mission: Mission;
  scans: ScanDetail[];
  missionTargets: Target[];
}

export default function MissionOverview({ mission, scans, missionTargets }: Props) {
  // Sort scans chronologically by creation or start time
  const sortedScans = [...scans].sort((a, b) => {
    const timeA = new Date(a.started_at || a.created_at || 0).getTime();
    const timeB = new Date(b.started_at || b.created_at || 0).getTime();
    return timeA - timeB;
  });

  return (
    <div className="space-y-6">
      {/* execution timeline */}
      <div className="rounded-xl border border-dark-border bg-dark-card p-6 shadow-sm relative overflow-hidden">
        <div className="absolute top-0 right-0 p-4 opacity-5">
          <Calendar className="h-32 w-32" />
        </div>
        <h3 className="mb-6 flex items-center gap-2 text-sm font-semibold text-white uppercase tracking-wider relative z-10">
          <Activity className="h-4 w-4 text-ey-yellow" /> Mission Timeline
        </h3>

        <div className="relative z-10 mx-auto max-w-4xl">
          {/* Timeline track */}
          <div className="absolute left-[15px] top-4 bottom-4 w-0.5 bg-dark-border/50 sm:left-1/2 sm:-translate-x-1/2" />

          <div className="space-y-8 relative">
            {/* Start Node */}
            <div className="relative flex flex-col sm:flex-row items-start sm:items-center justify-between sm:odd:flex-row-reverse group">
              <div className="hidden sm:block sm:w-1/2" />
              <div className="absolute left-0 sm:left-1/2 flex h-8 w-8 -translate-x-0 sm:-translate-x-1/2 items-center justify-center rounded-full border-4 border-dark-card bg-emerald-500/20 shadow-sm z-10">
                <Flag className="h-4 w-4 text-emerald-400" />
              </div>
              <div className="ml-12 sm:ml-0 sm:w-1/2 sm:pr-10 text-left sm:text-right">
                <div className="rounded-lg bg-emerald-500/10 border border-emerald-500/20 p-3 inline-block transition-colors group-hover:border-emerald-500/40">
                  <h4 className="text-sm font-bold text-white mb-0.5">Mission Started</h4>
                  <p className="text-xs text-emerald-400/80 font-medium">
                    {mission.start_date ? new Date(mission.start_date).toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' }) : 'Date unknown'}
                  </p>
                </div>
              </div>
            </div>

            {/* Scans Nodes */}
            {sortedScans.length > 0 ? sortedScans.slice(0, 10).map((scan, i) => (
              <div key={scan.id} className="relative flex flex-col sm:flex-row items-start sm:items-center justify-between sm:odd:flex-row-reverse group">
                <div className="hidden sm:block sm:w-1/2" />
                <div className="absolute left-0 sm:left-1/2 flex h-8 w-8 -translate-x-0 sm:-translate-x-1/2 items-center justify-center rounded-full border-4 border-dark-card bg-sky-500/20 shadow-sm z-10 transition-transform group-hover:scale-110">
                  <Play className="h-3.5 w-3.5 text-sky-400" />
                </div>
                <div className={`ml-12 sm:ml-0 sm:w-1/2 ${i % 2 === 0 ? 'sm:pl-10 text-left' : 'sm:pr-10 text-left sm:text-right'}`}>
                  <div className="rounded-lg bg-dark-elevated border border-dark-border/50 p-3 shadow-sm transition-all group-hover:border-sky-500/30 group-hover:-translate-y-0.5 w-full max-w-[280px] sm:max-w-none">
                    <div className="flex justify-between items-start gap-3 mb-1.5 flex-col md:flex-row">
                      <h4 className="text-sm font-bold text-white truncate max-w-full">
                        {scan.target_hostname || `Target #${scan.target_id}`}
                      </h4>
                      {scan.compliance_percentage != null && (
                        <span className={`text-xs font-bold shrink-0 px-1.5 py-0.5 rounded-md ${scan.compliance_percentage >= 80 ? 'bg-emerald-500/10 text-emerald-400' : scan.compliance_percentage >= 50 ? 'bg-amber-500/10 text-amber-400' : 'bg-red-500/10 text-red-400'}`}>
                          {scan.compliance_percentage}%
                        </span>
                      )}
                    </div>
                    <div className="flex justify-between items-center text-xs">
                      <span className="text-dark-secondary truncate pr-2 max-w-[150px]">{scan.benchmark_name || 'Scan execution'}</span>
                      <span className="text-dark-muted shrink-0 bg-dark-overlay px-1.5 py-0.5 rounded uppercase text-[10px]">{scan.scan_mode}</span>
                    </div>
                  </div>
                  <div className={`text-[11px] font-medium text-dark-muted mt-1.5 ml-1 sm:ml-0 ${i % 2 !== 0 ? 'sm:text-right sm:pr-1' : 'sm:pl-1'}`}>
                    {scan.started_at ? new Date(scan.started_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : 'Unknown time'}
                  </div>
                </div>
              </div>
            )) : (
              <div className="relative flex flex-col sm:flex-row items-start sm:items-center justify-between sm:odd:flex-row-reverse group opacity-50">
                <div className="hidden sm:block sm:w-1/2" />
                <div className="absolute left-0 sm:left-1/2 flex h-8 w-8 -translate-x-0 sm:-translate-x-1/2 items-center justify-center rounded-full border-4 border-dark-card bg-dark-elevated shadow-sm z-10">
                  <div className="h-2 w-2 rounded-full bg-dark-muted" />
                </div>
                <div className="ml-12 sm:ml-0 sm:w-1/2 sm:pr-10 text-left sm:text-right">
                  <div className="rounded-lg bg-dark-card border border-dark-border border-dashed p-3 inline-block">
                    <p className="text-xs text-dark-muted font-medium">Awaiting first scan execution...</p>
                  </div>
                </div>
              </div>
            )}

            {/* End / Current Node */}
            <div className={`relative flex flex-col sm:flex-row items-start sm:items-center justify-between sm:odd:flex-row-reverse group`}>
              <div className="hidden sm:block sm:w-1/2" />
              <div className="absolute left-0 sm:left-1/2 flex h-8 w-8 -translate-x-0 sm:-translate-x-1/2 items-center justify-center rounded-full border-4 border-dark-card bg-ey-yellow/20 shadow-sm z-10">
                {mission.status === 'completed' ? <CheckCircle2 className="h-4 w-4 text-ey-yellow" /> : <div className="h-2 w-2 rounded-full bg-ey-yellow animate-pulse" />}
              </div>
              <div className="ml-12 sm:ml-0 sm:w-1/2 sm:pl-10 text-left">
                <div className={`rounded-lg ${mission.status === 'completed' ? 'bg-ey-yellow/10 border-ey-yellow/30' : 'bg-dark-elevated border-dark-border'} border p-3 inline-block transition-colors`}>
                  <h4 className="text-sm font-bold text-white mb-0.5">{mission.status === 'completed' ? 'Mission Completed' : 'Present'}</h4>
                  <p className="text-xs text-dark-secondary font-medium">
                    {mission.status === 'completed' && mission.end_date
                      ? new Date(mission.end_date).toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' })
                      : 'Ongoing mission'}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Recent Scans */}
        <div className="rounded-xl border border-dark-border bg-dark-card p-5">
          <h3 className="mb-4 text-sm font-semibold text-white uppercase tracking-wider">Recent Scans</h3>
          {sortedScans.length === 0 ? (
            <p className="text-sm text-dark-muted border-2 border-dashed border-dark-border rounded-lg p-6 text-center">No scans yet. Go to the Scans tab to run your first scan.</p>
          ) : (
            <div className="space-y-2">
              {[...sortedScans].reverse().slice(0, 5).map(s => (
                <div key={s.id} className="flex items-center justify-between rounded-lg bg-dark-elevated/50 px-3 py-2 border border-dark-border/50">
                  <div className="text-sm min-w-0 pr-4">
                    <p className="text-white font-medium truncate">{s.target_hostname || s.target_ip || `Target #${s.target_id}`}</p>
                    <p className="text-xs text-dark-secondary truncate mt-0.5">{s.benchmark_name || 'Unknown benchmark'}</p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {s.compliance_percentage !== null && (
                      <span className={`text-xs font-bold ${(s.compliance_percentage || 0) >= 80 ? 'text-emerald-400' : (s.compliance_percentage || 0) >= 50 ? 'text-amber-400' : 'text-red-400'}`}>
                        {s.compliance_percentage?.toFixed(1)}%
                      </span>
                    )}
                    {scanStatusBadge(s.status)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Assigned Targets */}
        <div className="rounded-xl border border-dark-border bg-dark-card p-5">
          <h3 className="mb-4 text-sm font-semibold text-white uppercase tracking-wider flex items-center justify-between">
            <span>Assigned Targets</span>
            <span className="bg-dark-elevated text-dark-secondary px-2 py-0.5 rounded-full text-xs font-bold">{missionTargets.length}</span>
          </h3>
          {missionTargets.length === 0 ? (
            <p className="text-sm text-dark-muted border-2 border-dashed border-dark-border rounded-lg p-6 text-center">No targets assigned. Go to the Targets tab to assign targets.</p>
          ) : (
            <div className="space-y-2 max-h-[300px] overflow-y-auto custom-scrollbar pr-1">
              {missionTargets.map(t => (
                <div key={t.id} className="flex items-center gap-3 rounded-lg bg-dark-elevated/50 px-3 py-2 border border-dark-border/50">
                  <div className="h-8 w-8 rounded-lg bg-sky-500/10 flex items-center justify-center shrink-0">
                    <Server className="h-4 w-4 text-sky-400" />
                  </div>
                  <div className="text-sm min-w-0">
                    <p className="text-white font-medium truncate">{t.hostname || t.ip_address || `Target #${t.id}`}</p>
                    <p className="text-xs text-dark-secondary mt-0.5 truncate uppercase tracking-wider">{t.target_type} • {t.connection_method || 'N/A'}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
