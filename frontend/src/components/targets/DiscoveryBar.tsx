import { useState, useEffect, useRef } from 'react';
import { Radar, ChevronUp, ChevronDown, Plus, Wifi, XCircle } from 'lucide-react';
import type { DiscoveredHostEnriched } from '@/types';
import * as api from '@/services/api';
import { inputClass } from '../mission/badgeHelpers';
import DiscoveryHostCard from './DiscoveryHostCard';

/* ── localStorage helpers ──────────────────────────────────── */
const LS_KEY = 'auditforge_last_subnet';
function getSavedSubnet(clientId: number): string {
  try { return localStorage.getItem(`${LS_KEY}_${clientId}`) || ''; }
  catch { return ''; }
}
function saveSubnet(clientId: number, v: string) {
  try { localStorage.setItem(`${LS_KEY}_${clientId}`, v); }
  catch { /* noop */ }
}

/* ── Port → default connection method ─────────────────────── */
function guessConnection(host: DiscoveredHostEnriched): string {
  const ports = new Set((host.open_ports || []).map(p => p.port));
  if (ports.has(5986) || ports.has(5985)) return 'winrm';
  if (ports.has(22)) return 'ssh';
  if (ports.has(5432)) return 'postgresql';
  if (ports.has(1433)) return 'mssql';
  if (ports.has(1521)) return 'oracle';
  return 'ssh';
}

function guessPort(host: DiscoveredHostEnriched): number | null {
  const method = guessConnection(host);
  const portMap: Record<string, number> = { winrm: 5986, ssh: 22, postgresql: 5432, mssql: 1433, oracle: 1521 };
  return portMap[method] ?? null;
}

interface Props {
  clientId: number;
  missionId: number;
  onTargetsAdded: () => Promise<void>;
}

export default function DiscoveryBar({ clientId, missionId, onTargetsAdded }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [subnet, setSubnet] = useState(() => getSavedSubnet(clientId));
  const [discovering, setDiscovering] = useState(false);
  const [discoveredHosts, setDiscoveredHosts] = useState<DiscoveredHostEnriched[]>([]);
  const [addingIp, setAddingIp] = useState<string | null>(null);
  const [addingAll, setAddingAll] = useState(false);
  const [error, setError] = useState('');
  const [progress, setProgress] = useState<{ scanned: number; total: number; found: number } | null>(null);
  const discoveryIdRef = useRef<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Persist subnet preference
  useEffect(() => { if (subnet) saveSubnet(clientId, subnet); }, [subnet, clientId]);

  /* ── Discover ────────────────────────────────────────────── */
  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  // Cleanup on unmount
  useEffect(() => () => stopPolling(), []);

  const handleDiscover = async () => {
    if (!subnet.trim()) return;
    setDiscovering(true);
    setError('');
    setDiscoveredHosts([]);
    setProgress(null);

    try {
      // Start async discovery
      const { discovery_id } = await api.startDiscoveryAsync(subnet.trim());
      discoveryIdRef.current = discovery_id;

      // Poll for progress every 1.5 seconds
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.getDiscoveryStatus(discovery_id);
          setProgress({ scanned: status.scanned, total: status.total, found: status.found });

          if (status.status === 'completed' || status.status === 'cancelled') {
            stopPolling();
            discoveryIdRef.current = null;

            // Fetch enriched results
            const result = await api.discoverNetworkEnhanced(subnet.trim(), missionId);
            setDiscoveredHosts(result.hosts || []);
            if (!result.hosts || result.hosts.length === 0) {
              setError(status.status === 'cancelled'
                ? 'Discovery was cancelled.'
                : `No devices found on ${subnet}. Check that the subnet is reachable.`);
            }
            setDiscovering(false);
            setProgress(null);
          } else if (status.status === 'failed') {
            stopPolling();
            discoveryIdRef.current = null;
            setError(status.error || 'Discovery failed.');
            setDiscovering(false);
            setProgress(null);
          }
        } catch {
          // Ignore transient poll errors
        }
      }, 1500);
    } catch (err: any) {
      // Fallback: if async endpoint fails, use synchronous discover
      try {
        const result = await api.discoverNetworkEnhanced(subnet.trim(), missionId);
        setDiscoveredHosts(result.hosts || []);
        if (!result.hosts || result.hosts.length === 0) {
          setError(`No devices found on ${subnet}. Check that the subnet is reachable.`);
        }
      } catch (err2: any) {
        setError(err2?.response?.data?.detail || 'Discovery failed. Check subnet format and network connectivity.');
      }
      setDiscovering(false);
      setProgress(null);
    }
  };

  const handleCancel = async () => {
    const id = discoveryIdRef.current;
    if (id) {
      try {
        await api.cancelDiscovery(id);
      } catch {
        // Ignore — the cancel is best-effort
      }
    }
  };

  /* ── Add single host as target → assign to mission ─────── */
  const handleAddHost = async (host: DiscoveredHostEnriched) => {
    setAddingIp(host.ip);
    try {
      const osGuess = (host.os_guess || 'linux').toLowerCase();
      const role = (host.device_role || '').toLowerCase();
      const targetType = role === 'network_device' ? 'network'
        : role === 'database_server' ? 'database'
        : role === 'mobile' ? 'mobile'
        : osGuess.includes('windows') ? 'windows'
        : osGuess.includes('macos') ? 'macos'
        : 'linux';

      const connMethod = guessConnection(host);
      const port = guessPort(host);
      const portsNote = (host.open_ports || []).map(p => `${p.port}/${p.service || p.platform_hint || ''}`).join(', ');
      const detailParts: string[] = [];
      if (host.vendor) detailParts.push(`Vendor: ${host.vendor}`);
      if (host.os_version) detailParts.push(`OS: ${host.os_version}`);
      if (portsNote) detailParts.push(`Ports: ${portsNote}`);
      const notes = detailParts.join(' | ') || null;

      // 1. Create target under the client
      const newTarget = await api.createTarget({
        client_id: clientId,
        hostname: host.hostname || null,
        ip_address: host.ip,
        mac_address: host.mac_address || null,
        target_type: targetType,
        connection_method: connMethod,
        port,
        notes: notes,
        default_benchmark_id: host.suggested_benchmark_id ?? null,
      });

      // 2. Assign to mission
      await api.assignTargetToMission(missionId, newTarget.id);

      // 3. Auto-match benchmark (fire-and-forget)
      api.matchTargetBenchmark(newTarget.id).catch(() => {});

      // 4. Update host state to reflect it's now added + assigned
      setDiscoveredHosts(prev =>
        prev.map(h =>
          h.ip === host.ip
            ? { ...h, already_added: true, existing_target_id: newTarget.id, already_assigned: true }
            : h,
        ),
      );

      await onTargetsAdded();
    } catch (err: any) {
      setError(err?.response?.data?.detail || `Failed to add ${host.ip}`);
    } finally {
      setAddingIp(null);
    }
  };

  /* ── Add All un-added hosts ────────────────────────────── */
  const notAddedHosts = discoveredHosts.filter(h => !h.already_added && !h.already_assigned);

  const handleAddAll = async () => {
    if (notAddedHosts.length === 0) return;
    setAddingAll(true);
    for (const host of notAddedHosts) {
      await handleAddHost(host);
    }
    setAddingAll(false);
  };

  /* ── Collapsed state ─────────────────────────────────────── */
  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="flex w-full items-center gap-3 rounded-xl border border-dashed border-dark-border bg-dark-card/50 p-4 text-left transition-all hover:border-ey-yellow/30 hover:bg-dark-card group"
      >
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-ey-yellow/10 group-hover:bg-ey-yellow/20 transition-colors">
          <Radar className="h-5 w-5 text-ey-yellow" />
        </div>
        <div className="flex-1">
          <p className="text-sm font-semibold text-white">Network Discovery</p>
          <p className="text-xs text-dark-muted">Scan your network to find devices automatically</p>
        </div>
        <ChevronDown className="h-5 w-5 text-dark-muted group-hover:text-ey-yellow transition-colors" />
      </button>
    );
  }

  /* ── Expanded state ──────────────────────────────────────── */
  return (
    <div className="rounded-xl border border-ey-yellow/20 bg-dark-card shadow-lg shadow-ey-yellow/5 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-dark-border px-5 py-3.5">
        <div className="flex items-center gap-3">
          <Radar className="h-5 w-5 text-ey-yellow" />
          <div>
            <p className="text-sm font-semibold text-white">Network Discovery</p>
            <p className="text-xs text-dark-muted">Scan your network to find devices automatically</p>
          </div>
        </div>
        <button onClick={() => setExpanded(false)} className="text-dark-muted hover:text-white transition-colors">
          <ChevronUp className="h-5 w-5" />
        </button>
      </div>

      {/* Body */}
      <div className="p-5 space-y-4">
        {/* Input row */}
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <input
              type="text"
              value={subnet}
              onChange={e => setSubnet(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleDiscover(); }}
              placeholder="192.168.1.0/24 or single IP or comma-separated"
              className={`${inputClass} pr-10`}
              disabled={discovering}
            />
            <Wifi className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-dark-muted" />
          </div>
          <button
            onClick={handleDiscover}
            disabled={discovering || !subnet.trim()}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-ey-yellow px-5 py-2 text-sm font-semibold text-black transition-colors hover:bg-ey-yellow-hover disabled:opacity-50 whitespace-nowrap"
          >
            {discovering ? (
              <>
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-black border-t-transparent" />
                Scanning…
              </>
            ) : (
              <>
                <Radar className="h-4 w-4" />
                Discover
              </>
            )}
          </button>
          {notAddedHosts.length > 0 && (
            <button
              onClick={handleAddAll}
              disabled={addingAll}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-ey-yellow/30 bg-ey-yellow/10 px-4 py-2 text-sm font-medium text-ey-yellow transition-colors hover:bg-ey-yellow/20 disabled:opacity-50 whitespace-nowrap"
            >
              {addingAll ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-ey-yellow border-t-transparent" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Add All ({notAddedHosts.length})
            </button>
          )}
        </div>

        {/* Discovery progress */}
        {discovering && (
          <div className="space-y-3 rounded-lg border border-dark-border bg-dark-elevated p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="relative">
                  <div className="h-10 w-10 animate-ping rounded-full bg-ey-yellow/20 absolute" />
                  <div className="h-10 w-10 flex items-center justify-center relative">
                    <Radar className="h-5 w-5 text-ey-yellow animate-pulse" />
                  </div>
                </div>
                <div>
                  <p className="text-sm font-medium text-white">Scanning network…</p>
                  {progress ? (
                    <p className="text-xs text-dark-muted">
                      {progress.scanned}/{progress.total} hosts scanned • {progress.found} found
                    </p>
                  ) : (
                    <p className="text-xs text-dark-muted">Initializing…</p>
                  )}
                </div>
              </div>
              <button
                onClick={handleCancel}
                className="flex items-center gap-1.5 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-400 transition-colors hover:bg-red-500/20"
              >
                <XCircle className="h-3.5 w-3.5" />
                Cancel
              </button>
            </div>
            {progress && progress.total > 0 && (
              <div className="space-y-1">
                <div className="h-2 w-full rounded-full bg-dark-border overflow-hidden">
                  <div
                    className="h-full rounded-full bg-ey-yellow transition-all duration-500"
                    style={{ width: `${Math.round((progress.scanned / progress.total) * 100)}%` }}
                  />
                </div>
                <p className="text-right text-[10px] text-dark-muted">
                  {Math.round((progress.scanned / progress.total) * 100)}%
                </p>
              </div>
            )}
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-400">
            {error}
          </div>
        )}

        {/* Results grid */}
        {discoveredHosts.length > 0 && !discovering && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
            {discoveredHosts.map(host => (
              <DiscoveryHostCard
                key={host.ip}
                host={host}
                onAdd={handleAddHost}
                adding={addingIp === host.ip || addingAll}
              />
            ))}
          </div>
        )}

        {/* Empty state after completed scan */}
        {discoveredHosts.length === 0 && !discovering && !error && subnet && (
          <p className="py-4 text-center text-sm text-dark-muted">
            Enter a subnet and click Discover to scan for devices.
          </p>
        )}
      </div>
    </div>
  );
}
