import { useState } from 'react';
import { Monitor, Terminal, Network, Database, HelpCircle, Plus, Check, Shield, Wifi, Smartphone, Clock, Sparkles, Server, ChevronDown, ChevronUp } from 'lucide-react';
import type { DiscoveredHostEnriched } from '@/types';

/* ── Static Tailwind class maps (avoids purging of dynamic classes) ── */
const ACCENT_CLASSES = {
  'sky-400':     { bg: 'bg-sky-400/10',     text: 'text-sky-400',     border: 'border-sky-400/20' },
  'emerald-400': { bg: 'bg-emerald-400/10', text: 'text-emerald-400', border: 'border-emerald-400/20' },
  'purple-400':  { bg: 'bg-purple-400/10',  text: 'text-purple-400',  border: 'border-purple-400/20' },
  'orange-400':  { bg: 'bg-orange-400/10',  text: 'text-orange-400',  border: 'border-orange-400/20' },
  'pink-400':    { bg: 'bg-pink-400/10',    text: 'text-pink-400',    border: 'border-pink-400/20' },
  'gray-400':    { bg: 'bg-gray-400/10',    text: 'text-gray-400',    border: 'border-gray-400/20' },
  'amber-400':   { bg: 'bg-amber-400/10',   text: 'text-amber-400',   border: 'border-amber-400/20' },
} as const;

type AccentKey = keyof typeof ACCENT_CLASSES;

/* ── OS → icon / accent mapping ────────────────────────────── */
const OS_CONFIG: Record<string, { icon: typeof Monitor; accent: AccentKey; label: string }> = {
  windows: { icon: Monitor,      accent: 'sky-400',     label: 'Windows' },
  linux:   { icon: Terminal,     accent: 'emerald-400', label: 'Linux' },
  macos:   { icon: Monitor,     accent: 'gray-400',    label: 'macOS' },
};

/* ── Device role → badge label ─────────────────────────────── */
const ROLE_CONFIG: Record<string, { icon: typeof Server; accent: AccentKey; label: string }> = {
  domain_controller: { icon: Shield,   accent: 'amber-400',  label: 'Domain Controller' },
  server:            { icon: Server,   accent: 'purple-400', label: 'Server' },
  workstation:       { icon: Monitor,  accent: 'sky-400',    label: 'Workstation' },
  network_device:    { icon: Network,  accent: 'purple-400', label: 'Network' },
  database_server:   { icon: Database, accent: 'orange-400', label: 'Database' },
  printer:           { icon: Wifi,     accent: 'gray-400',   label: 'Printer' },
  mobile:            { icon: Smartphone, accent: 'pink-400', label: 'Mobile' },
};

function getOsConfig(os: string) {
  const key = (os || '').toLowerCase();
  for (const [k, v] of Object.entries(OS_CONFIG)) {
    if (key.includes(k)) return v;
  }
  return { icon: HelpCircle, accent: 'gray-400' as AccentKey, label: os || 'Unknown' };
}

function getRoleConfig(role: string) {
  return ROLE_CONFIG[(role || '').toLowerCase()] || null;
}

/* ── Detection method → friendly label ─────────────────────── */
function formatDetectionMethod(method: string): string {
  if (!method) return '';
  return method
    .split('+')
    .map(m => {
      switch (m) {
        case 'nmap': return 'Nmap';
        case 'nmap_os': return 'Nmap OS';
        case 'http': return 'HTTP Banner';
        case 'smb_ntlm': return 'SMB/NTLM';
        case 'snmp': return 'SNMP';
        case 'mac_oui': return 'MAC OUI';
        case 'mac_arp': return 'ARP';
        case 'upnp_ssdp': return 'UPnP';
        case 'upnp_xml': return 'UPnP XML';
        case 'mdns': return 'mDNS';
        case 'http_body': return 'HTTP';
        case 'http_title': return 'HTTP Title';
        case 'http_header': return 'HTTP Header';
        case 'http_auth_realm': return 'HTTP Auth';
        case 'hostname': return 'Hostname';
        case 'banner_ssh': return 'SSH';
        case 'banner_http': return 'HTTP Server';
        case 'banner_ftp': return 'FTP';
        case 'banner_telnet': return 'Telnet';
        case 'banner_mysql': return 'MySQL';
        case 'banner_smtp': return 'SMTP';
        case 'port_heuristic': return 'Ports';
        case 'tcp_fingerprint': return 'TCP/TTL';
        case 'arp_sweep': return 'ARP';
        case 'netbios': return 'NetBIOS';
        default: return m;
      }
    })
    .join(' + ');
}

/* ── Relative time helper ──────────────────────────────────── */
function formatRelativeTime(isoStr: string | null | undefined): string {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    const now = Date.now();
    const diffMs = now - d.getTime();
    if (diffMs < 0) return 'just now';
    const mins = Math.floor(diffMs / 60_000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days === 1) return 'yesterday';
    if (days < 30) return `${days}d ago`;
    return d.toLocaleDateString();
  } catch {
    return '';
  }
}

interface Props {
  host: DiscoveredHostEnriched;
  /** Called when user clicks "Add to Client", returns the created target id */
  onAdd: (host: DiscoveredHostEnriched) => Promise<void>;
  adding?: boolean;
}

export default function DiscoveryHostCard({ host, onAdd, adding }: Props) {
  const cfg = getOsConfig(host.os_guess);
  const accentCls = ACCENT_CLASSES[cfg.accent];
  const Icon = cfg.icon;
  const roleCfg = getRoleConfig(host.device_role);
  const alreadyAssigned = host.already_assigned;
  const alreadyAdded = host.already_added && !alreadyAssigned;
  const detectionLabel = formatDetectionMethod(host.detection_method || '');
  const lastSeenLabel = formatRelativeTime(host.last_seen);
  const isNew = host.is_new === true;
  const [portsExpanded, setPortsExpanded] = useState(false);

  const PORTS_COLLAPSED_LIMIT = 6;
  const showExpandButton = (host.open_ports?.length ?? 0) > PORTS_COLLAPSED_LIMIT;
  const visiblePorts = portsExpanded ? host.open_ports : host.open_ports?.slice(0, PORTS_COLLAPSED_LIMIT);

  return (
    <div
      className={`
        group relative rounded-xl border bg-dark-card p-4 transition-all duration-200
        animate-in slide-in-from-bottom-2 fade-in
        ${alreadyAssigned
          ? 'border-emerald-500/30 bg-emerald-500/5'
          : alreadyAdded
            ? 'border-sky-500/30 bg-sky-500/5'
            : isNew
              ? 'border-amber-400/40 bg-amber-400/5'
              : 'border-dark-border hover:border-dark-border/80 hover:shadow-lg hover:shadow-black/20'}
      `}
    >
      {/* NEW badge */}
      {isNew && !alreadyAssigned && !alreadyAdded && (
        <div className="absolute -right-1 -top-1 flex items-center gap-0.5 rounded-full bg-amber-500 px-1.5 py-0.5 text-[9px] font-bold uppercase text-black shadow-lg shadow-amber-500/30">
          <Sparkles className="h-2.5 w-2.5" />
          NEW
        </div>
      )}
      {/* Top row: Icon + IP + Hostname + Domain */}
      <div className="flex items-start gap-3">
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${accentCls.bg} ${accentCls.border}`}>
          <Icon className={`h-4 w-4 ${accentCls.text}`} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-bold text-white">{host.ip}</p>
          <p className="truncate text-xs text-dark-muted">
            {host.hostname || 'No hostname'}
            {host.domain && <span className="text-dark-muted/60"> • {host.domain}</span>}
          </p>
        </div>
      </div>

      {/* OS label + version + vendor + model */}
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span className={`inline-flex items-center rounded-full ${accentCls.bg} px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${accentCls.text}`}>
          {cfg.label}
        </span>
        {roleCfg && (() => {
          const roleAccent = ACCENT_CLASSES[roleCfg.accent];
          return (
            <span className={`inline-flex items-center gap-0.5 rounded-full ${roleAccent.bg} px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${roleAccent.text}`}>
              <roleCfg.icon className="h-2.5 w-2.5" />
              {roleCfg.label}
            </span>
          );
        })()}
        {host.os_version && (
          <span className="truncate text-[10px] text-dark-secondary" title={host.os_version}>
            {host.os_version}
          </span>
        )}
      </div>

      {/* Vendor + Model + Firmware row */}
      {(host.vendor || host.device_model || host.firmware) && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {host.vendor && (
            <span className="inline-flex items-center gap-1 rounded-full bg-dark-elevated px-2 py-0.5 text-[10px] text-dark-muted" title={`Vendor: ${host.vendor}`}>
              <Shield className="h-2.5 w-2.5" />
              {host.vendor}
            </span>
          )}
          {host.device_model && (
            <span className="inline-flex items-center gap-1 rounded-full bg-dark-elevated px-2 py-0.5 text-[10px] text-dark-secondary font-medium" title={`Model: ${host.device_model}`}>
              <Wifi className="h-2.5 w-2.5" />
              {host.device_model}
            </span>
          )}
          {host.firmware && (
            <span className="truncate text-[10px] text-dark-muted/70" title={`Firmware: ${host.firmware}`}>
              FW: {host.firmware}
            </span>
          )}
        </div>
      )}

      {/* MAC address */}
      {host.mac_address ? (
        <p className="mt-1 text-[10px] text-dark-muted/60 font-mono" title="MAC address">
          {host.mac_address}
        </p>
      ) : (
        <p className="mt-1 text-[10px] text-dark-muted/40 italic" title="MAC addresses are not visible through Docker Desktop NAT">
          MAC: unavailable (Docker NAT)
        </p>
      )}

      {/* Open ports */}
      {host.open_ports && host.open_ports.length > 0 && (
        <div className="mt-2">
          <p className="text-[10px] text-dark-muted mb-1">
            Ports ({host.open_ports.length}):
          </p>
          <div className="flex flex-wrap gap-1">
            {(visiblePorts || []).map(p => (
              <span
                key={`${p.port}-${p.proto || 'tcp'}`}
                className="rounded bg-dark-elevated px-1.5 py-0.5 text-[10px] text-dark-secondary font-mono"
                title={p.banner_snippet || `${p.port}/${p.service || ''}${p.proto === 'udp' ? ' (UDP)' : ''}`}
              >
                {p.port}{p.service ? `/${p.service}` : ''}{p.proto === 'udp' ? '/udp' : ''}
                {p.product && p.version
                  ? ` (${p.product} ${p.version})`
                  : p.product
                    ? ` (${p.product})`
                    : ''}
              </span>
            ))}
          </div>
          {showExpandButton && (
            <button
              onClick={() => setPortsExpanded(prev => !prev)}
              className="mt-1 flex items-center gap-0.5 text-[10px] text-dark-muted hover:text-dark-secondary transition-colors"
            >
              {portsExpanded ? (
                <>
                  <ChevronUp className="h-3 w-3" /> Show less
                </>
              ) : (
                <>
                  <ChevronDown className="h-3 w-3" /> Show all {host.open_ports.length} ports
                </>
              )}
            </button>
          )}
        </div>
      )}

      {/* Detection method + Last seen */}
      {(detectionLabel || lastSeenLabel) && (
        <div className="mt-1.5 flex items-center justify-between">
          {detectionLabel && (
            <p className="text-[9px] text-dark-muted/50" title={`Detected via: ${detectionLabel}`}>
              via {detectionLabel}
            </p>
          )}
          {lastSeenLabel && (
            <p className="flex items-center gap-0.5 text-[9px] text-dark-muted/50" title={`Last seen: ${host.last_seen || ''}`}>
              <Clock className="h-2.5 w-2.5" />
              {lastSeenLabel}
            </p>
          )}
        </div>
      )}

      {/* Suggested benchmark */}
      {host.suggested_benchmark && (
        <p className="mt-1.5 truncate text-[10px] text-dark-muted" title={host.suggested_benchmark}>
          Benchmark: <span className="text-dark-secondary">{host.suggested_benchmark}</span>
        </p>
      )}

      {/* Action button */}
      <div className="mt-3">
        {alreadyAssigned ? (
          <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-400">
            <Check className="h-3.5 w-3.5" />
            <span>Assigned to mission</span>
            {host.match_method === 'mac' && (
              <span className="text-[9px] text-emerald-400/60 font-normal">(matched by MAC)</span>
            )}
          </div>
        ) : alreadyAdded ? (
          <div className="flex items-center gap-1.5 text-xs font-medium text-sky-400">
            <Check className="h-3.5 w-3.5" />
            <span>Already in client</span>
            {host.match_method === 'mac' && (
              <span className="text-[9px] text-sky-400/60 font-normal">(matched by MAC)</span>
            )}
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
