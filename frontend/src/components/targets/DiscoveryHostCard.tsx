import { Monitor, Terminal, Network, Database, HelpCircle, Plus, Check } from 'lucide-react';
import type { DiscoveredHostEnriched } from '@/types';

/* ── OS → icon / accent mapping ────────────────────────────── */
const OS_CONFIG: Record<string, { icon: typeof Monitor; accent: string; label: string }> = {
  windows: { icon: Monitor,   accent: 'sky-400',     label: 'Windows' },
  linux:   { icon: Terminal,   accent: 'emerald-400', label: 'Linux' },
  network: { icon: Network,    accent: 'purple-400',  label: 'Network' },
  database:{ icon: Database,   accent: 'orange-400',  label: 'Database' },
};

function getOsConfig(os: string) {
  const key = (os || '').toLowerCase();
  for (const [k, v] of Object.entries(OS_CONFIG)) {
    if (key.includes(k)) return v;
  }
  return { icon: HelpCircle, accent: 'gray-400', label: os || 'Unknown' };
}

interface Props {
  host: DiscoveredHostEnriched;
  /** Called when user clicks "Add to Client", returns the created target id */
  onAdd: (host: DiscoveredHostEnriched) => Promise<void>;
  adding?: boolean;
}

export default function DiscoveryHostCard({ host, onAdd, adding }: Props) {
  const cfg = getOsConfig(host.os_guess);
  const Icon = cfg.icon;
  const alreadyAssigned = host.already_assigned;
  const alreadyAdded = host.already_added && !alreadyAssigned;

  return (
    <div
      className={`
        group relative rounded-xl border bg-dark-card p-4 transition-all duration-200
        animate-in slide-in-from-bottom-2 fade-in
        ${alreadyAssigned
          ? 'border-emerald-500/30 bg-emerald-500/5'
          : alreadyAdded
            ? 'border-sky-500/30 bg-sky-500/5'
            : 'border-dark-border hover:border-dark-border/80 hover:shadow-lg hover:shadow-black/20'}
      `}
    >
      {/* Top row: Icon + IP + Hostname */}
      <div className="flex items-start gap-3">
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-${cfg.accent}/10 border border-${cfg.accent}/20`}>
          <Icon className={`h-4 w-4 text-${cfg.accent}`} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-bold text-white">{host.ip}</p>
          <p className="truncate text-xs text-dark-muted">
            {host.hostname || 'No hostname'}
          </p>
        </div>
      </div>

      {/* OS label */}
      <div className="mt-3 flex items-center gap-2">
        <span className={`inline-flex items-center rounded-full bg-${cfg.accent}/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-${cfg.accent}`}>
          {cfg.label}
        </span>
      </div>

      {/* Open ports */}
      {host.open_ports && host.open_ports.length > 0 && (
        <div className="mt-2">
          <p className="text-[10px] text-dark-muted mb-1">Ports:</p>
          <div className="flex flex-wrap gap-1">
            {host.open_ports.slice(0, 5).map(p => (
              <span key={p.port} className="rounded bg-dark-elevated px-1.5 py-0.5 text-[10px] text-dark-secondary font-mono">
                {p.port}{p.service ? `/${p.service}` : ''}
              </span>
            ))}
            {host.open_ports.length > 5 && (
              <span className="text-[10px] text-dark-muted">+{host.open_ports.length - 5}</span>
            )}
          </div>
        </div>
      )}

      {/* Suggested benchmark */}
      {host.suggested_benchmark && (
        <p className="mt-2 truncate text-[10px] text-dark-muted" title={host.suggested_benchmark}>
          Benchmark: <span className="text-dark-secondary">{host.suggested_benchmark}</span>
        </p>
      )}

      {/* Action button */}
      <div className="mt-3">
        {alreadyAssigned ? (
          <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-400">
            <Check className="h-3.5 w-3.5" /> Assigned to mission
          </div>
        ) : alreadyAdded ? (
          <div className="flex items-center gap-1.5 text-xs font-medium text-sky-400">
            <Check className="h-3.5 w-3.5" /> Already in client
          </div>
        ) : (
          <button
            onClick={() => onAdd(host)}
            disabled={adding}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-ey-yellow/30 bg-ey-yellow/10 px-3 py-1.5 text-xs font-semibold text-ey-yellow transition-colors hover:bg-ey-yellow/20 disabled:opacity-50"
          >
            {adding ? (
              <div className="h-3 w-3 animate-spin rounded-full border-2 border-ey-yellow border-t-transparent" />
            ) : (
              <Plus className="h-3 w-3" />
            )}
            Add to Client
          </button>
        )}
      </div>
    </div>
  );
}
