import { Server } from 'lucide-react';
import type { ScanDetail, Target } from '@/types';
import { scanStatusBadge } from './badgeHelpers';

interface Props {
  scans: ScanDetail[];
  missionTargets: Target[];
}

export default function MissionOverview({ scans, missionTargets }: Props) {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      {/* Recent Scans */}
      <div className="rounded-xl border border-dark-border bg-dark-card p-5">
        <h3 className="mb-3 text-sm font-semibold text-white uppercase tracking-wider">Recent Scans</h3>
        {scans.length === 0 ? (
          <p className="text-sm text-dark-muted">No scans yet. Go to the Scans tab to run your first scan.</p>
        ) : (
          <div className="space-y-2">
            {scans.slice(0, 5).map(s => (
              <div key={s.id} className="flex items-center justify-between rounded-lg bg-dark-elevated/50 px-3 py-2">
                <div className="text-sm">
                  <span className="text-white">{s.target_hostname || s.target_ip || `Target #${s.target_id}`}</span>
                  <span className="mx-2 text-dark-muted">•</span>
                  <span className="text-dark-secondary">{s.benchmark_name || 'Unknown benchmark'}</span>
                </div>
                <div className="flex items-center gap-2">
                  {s.compliance_percentage !== null && (
                    <span className={`text-xs font-medium ${(s.compliance_percentage || 0) >= 80 ? 'text-emerald-400' : (s.compliance_percentage || 0) >= 50 ? 'text-amber-400' : 'text-red-400'}`}>
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
        <h3 className="mb-3 text-sm font-semibold text-white uppercase tracking-wider">Assigned Targets</h3>
        {missionTargets.length === 0 ? (
          <p className="text-sm text-dark-muted">No targets assigned. Go to the Targets tab to assign targets.</p>
        ) : (
          <div className="space-y-2">
            {missionTargets.map(t => (
              <div key={t.id} className="flex items-center gap-3 rounded-lg bg-dark-elevated/50 px-3 py-2">
                <Server className="h-4 w-4 text-sky-400" />
                <div className="text-sm">
                  <span className="text-white">{t.hostname || t.ip_address || `Target #${t.id}`}</span>
                  <span className="ml-2 text-xs text-dark-muted">{t.target_type} • {t.connection_method || 'N/A'}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
