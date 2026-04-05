import { useState, useEffect, useRef, useCallback } from 'react';
import { Monitor, Terminal, Wifi, WifiOff, Play, Loader2, CheckCircle2, AlertTriangle, BarChart3, RotateCcw } from 'lucide-react';
import type { ConnectAgent, Benchmark } from '@/types';
import * as api from '@/services/api';
import { AgentWSClient } from '@/services/wsAgent';
import type { AgentEvent } from '@/services/wsAgent';
import { useToast } from '@/components/common/Toast';

interface Props {
  sessionId: number;
  isActive: boolean;
}

interface ScanProgress {
  scanId: number;
  completed: number;
  total: number;
  currentRule?: string;
}

interface ScanResult {
  scanId: number;
  pass: number;
  fail: number;
  error: number;
}

export default function ConnectedAgentsPanel({ sessionId, isActive }: Props) {
  const [agents, setAgents] = useState<ConnectAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [selectedBenchmark, setSelectedBenchmark] = useState<number | null>(null);
  const [scanProgress, setScanProgress] = useState<Record<number, ScanProgress>>({});
  const [scanResults, setScanResults] = useState<Record<number, ScanResult>>({});
  const wsRef = useRef<AgentWSClient | null>(null);
  const toast = useToast();

  // Derived scanning state — true while ANY agent has active progress
  const scanning = Object.keys(scanProgress).length > 0;
  const hasResults = Object.keys(scanResults).length > 0 && !scanning;

  // Load agents + benchmarks
  useEffect(() => {
    const load = async () => {
      try {
        const [agts, bms] = await Promise.all([
          api.getConnectAgents(sessionId),
          api.getBenchmarks(),
        ]);
        setAgents(agts);
        setBenchmarks(bms);
      } catch { /* ignore */ }
      finally { setLoading(false); }
    };
    load();
  }, [sessionId]);

  // Restore benchmark selection from sessionStorage
  useEffect(() => {
    const saved = sessionStorage.getItem(`af_benchmark_${sessionId}`);
    if (saved) {
      const id = Number(saved);
      if (!isNaN(id)) setSelectedBenchmark(id);
    }
  }, [sessionId]);

  // Poll agents every 3 seconds
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const agts = await api.getConnectAgents(sessionId);
        setAgents(_prev => {
          return agts.map(a => {
            const prog = scanProgress[a.id];
            const result = scanResults[a.id];
            if (result) return { ...a, status: 'completed' as const };
            if (prog) return { ...a, status: 'scanning' as const };
            return a;
          });
        });
      } catch { /* ignore */ }
    }, 3000);
    return () => clearInterval(interval);
  }, [sessionId, scanProgress, scanResults]);

  // WebSocket for real-time updates
  useEffect(() => {
    if (!isActive) return;

    const ws = new AgentWSClient(sessionId);
    wsRef.current = ws;

    // One-shot refresh after WS connects to catch any gap
    ws.onStatus((status) => {
      if (status === 'connected') {
        api.getConnectAgents(sessionId).then(agts => {
          setAgents(_prev => {
            return agts.map(a => {
              if (scanProgress[a.id]) return { ...a, status: 'scanning' as const };
              if (scanResults[a.id]) return { ...a, status: 'completed' as const };
              return a;
            });
          });
        }).catch(() => {});
      }
    });

    ws.onEvent((event: AgentEvent) => {
      const agentId = (event.payload as { agent_id?: number })?.agent_id;

      if (event.type === 'agent_connected') {
        setAgents(prev => {
          const existing = prev.find(a => a.id === agentId);
          if (existing) {
            return prev.map(a => a.id === agentId
              ? { ...a, status: 'connected' as const, hostname: event.payload.hostname, os_type: event.payload.os_type }
              : a
            );
          }
          return [...prev, {
            id: agentId!,
            session_id: sessionId,
            hostname: event.payload.hostname,
            ip_address: event.payload.ip_address,
            os_type: event.payload.os_type,
            os_version: null,
            status: 'connected',
            connected_at: new Date().toISOString(),
            disconnected_at: null,
            target_id: null,
            system_info: null,
          }];
        });
      }

      if (event.type === 'agent_disconnected') {
        setAgents(prev => prev.map(a =>
          a.id === agentId ? { ...a, status: 'disconnected' as const } : a
        ));
      }

      if (event.type === 'agent_system_info') {
        const p = event.payload;
        setAgents(prev => prev.map(a =>
          a.id === agentId
            ? { ...a, hostname: p.hostname || a.hostname, os_type: p.os || a.os_type, os_version: p.os_version || a.os_version }
            : a
        ));
      }

      if (event.type === 'scan_progress') {
        const p = event.payload;
        setScanProgress(prev => ({
          ...prev,
          [agentId!]: { scanId: p.scan_id, completed: p.completed, total: p.total, currentRule: p.current_rule },
        }));
        setAgents(prev => prev.map(a =>
          a.id === agentId && a.status !== 'scanning' ? { ...a, status: 'scanning' as const } : a
        ));
      }

      if (event.type === 'scan_complete') {
        const p = event.payload;
        setScanResults(prev => ({
          ...prev,
          [agentId!]: { scanId: p.scan_id, pass: p.pass, fail: p.fail, error: p.error },
        }));
        setScanProgress(prev => {
          const next = { ...prev };
          delete next[agentId!];
          return next;
        });
        setAgents(prev => prev.map(a =>
          a.id === agentId ? { ...a, status: 'completed' as const } : a
        ));
        toast.success('Scan completed');
      }
    });

    ws.connect();
    return () => ws.disconnect();
  }, [sessionId, isActive]);

  // Persist benchmark selection
  const handleBenchmarkChange = useCallback((id: number) => {
    setSelectedBenchmark(id);
    sessionStorage.setItem(`af_benchmark_${sessionId}`, String(id));
  }, [sessionId]);

  const handleResetForNewScan = useCallback(() => {
    setScanResults({});
    setScanProgress({});
    setAgents(prev => prev.map(a =>
      a.status === 'completed' ? { ...a, status: 'connected' as const } : a
    ));
  }, []);

  const handleScanAll = useCallback(async () => {
    if (!selectedBenchmark) { toast.error('Select a benchmark first'); return; }
    // Reset completed agents and clear previous results
    setScanResults({});
    setScanProgress({});
    setAgents(prev => prev.map(a =>
      a.status === 'completed' ? { ...a, status: 'connected' as const } : a
    ));
    try {
      const res = await api.startAgentScan(sessionId, selectedBenchmark);
      toast.success(`${res.scan_ids.length} scan(s) started`);
      setAgents(prev => prev.map(a =>
        a.status === 'connected' ? { ...a, status: 'scanning' as const } : a
      ));
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || 'Failed to start scan');
    }
  }, [selectedBenchmark, sessionId, toast]);

  const handleScanAgent = useCallback(async (agentId: number) => {
    if (!selectedBenchmark) { toast.error('Select a benchmark first'); return; }
    setScanResults(prev => { const next = { ...prev }; delete next[agentId]; return next; });
    try {
      await api.startAgentScan(sessionId, selectedBenchmark, [agentId]);
      toast.success('Scan started');
      setAgents(prev => prev.map(a =>
        a.id === agentId ? { ...a, status: 'scanning' as const } : a
      ));
    } catch {
      toast.error('Failed to start scan');
    }
  }, [selectedBenchmark, sessionId, toast]);

  const connectedCount = agents.filter(a => ['connected', 'scanning', 'completed'].includes(a.status)).length;
  const scannable = agents.filter(a => a.status === 'connected').length;

  // Filter benchmarks by connected agents' OS types
  const agentOsTypes = new Set(
    agents
      .filter(a => ['connected', 'scanning', 'completed'].includes(a.status) && a.os_type)
      .map(a => a.os_type!.toLowerCase())
  );
  const relevantFamilies = new Set<string>();
  agentOsTypes.forEach(os => {
    if (os.includes('windows')) relevantFamilies.add('windows');
    else relevantFamilies.add('linux');
  });
  const relevantBenchmarks = benchmarks.filter(b =>
    relevantFamilies.has(b.platform_family) && b.is_ready
  );

  // Auto-select first relevant benchmark (only if nothing saved/selected)
  useEffect(() => {
    if (relevantBenchmarks.length === 0) return;

    // Check if current selection is still valid
    if (selectedBenchmark && relevantBenchmarks.find(b => b.id === selectedBenchmark)) return;

    // Check sessionStorage
    const saved = sessionStorage.getItem(`af_benchmark_${sessionId}`);
    if (saved) {
      const id = Number(saved);
      if (!isNaN(id) && relevantBenchmarks.find(b => b.id === id)) {
        setSelectedBenchmark(id);
        return;
      }
    }

    // Fall back to first
    setSelectedBenchmark(relevantBenchmarks[0].id);
  }, [relevantBenchmarks.length, agents.length]);

  const statusIcon = (status: string) => {
    switch (status) {
      case 'connected': return <Wifi className="h-4 w-4 text-emerald-400" />;
      case 'scanning': return <Loader2 className="h-4 w-4 animate-spin text-amber-400" />;
      case 'completed': return <CheckCircle2 className="h-4 w-4 text-sky-400" />;
      case 'disconnected': return <WifiOff className="h-4 w-4 text-red-400" />;
      default: return <AlertTriangle className="h-4 w-4 text-dark-muted" />;
    }
  };

  const statusBadge = (status: string) => {
    const map: Record<string, string> = {
      connected: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20',
      scanning: 'bg-amber-500/10 text-amber-400 ring-amber-500/20',
      completed: 'bg-sky-500/10 text-sky-400 ring-sky-500/20',
      disconnected: 'bg-red-500/10 text-red-400 ring-red-500/20',
      pending: 'bg-dark-overlay text-dark-muted ring-dark-border',
    };
    return map[status] || map.pending;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-6">
        <Loader2 className="h-5 w-5 animate-spin text-ey-yellow" />
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <div className="text-center py-8">
        <WifiOff className="mx-auto h-8 w-8 text-dark-muted mb-2" />
        <p className="text-sm text-dark-secondary">No agents have connected yet</p>
        <p className="text-xs text-dark-muted mt-1">Share the portal URL with targets to get started</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Scan controls */}
      {isActive && connectedCount > 0 && (
        <div className="flex items-center gap-3 rounded-lg bg-dark-card border border-dark-border p-3">
          <BarChart3 className="h-4 w-4 text-ey-yellow shrink-0" />
          <select
            value={selectedBenchmark || ''}
            onChange={e => handleBenchmarkChange(Number(e.target.value))}
            className="flex-1 rounded-lg border border-dark-border bg-dark-elevated px-3 py-1.5 text-sm text-white focus:border-ey-yellow/50 focus:outline-none"
          >
            {relevantBenchmarks.length === 0 && (
              <option value="">No benchmarks match connected agents</option>
            )}
            {relevantBenchmarks.map(b => (
              <option key={b.id} value={b.id}>{b.name} ({b.platform})</option>
            ))}
          </select>

          {/* New Scan button — shown after results when no progress active */}
          {hasResults && (
            <button
              onClick={handleResetForNewScan}
              className="flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-dark-secondary hover:text-ey-yellow hover:border-ey-yellow/30 transition-colors"
            >
              <RotateCcw className="h-3.5 w-3.5" /> New Scan
            </button>
          )}

          <button
            onClick={handleScanAll}
            disabled={scanning || !selectedBenchmark || scannable === 0}
            className="flex items-center gap-1.5 rounded-lg bg-ey-yellow px-4 py-1.5 text-sm font-semibold text-black hover:bg-ey-yellow-hover transition-colors disabled:opacity-50"
          >
            {scanning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {scanning ? 'Scanning...' : `Scan All (${scannable})`}
          </button>
        </div>
      )}

      {/* Agent list */}
      <div className="space-y-2">
        {agents.map(agent => {
          const progress = scanProgress[agent.id];
          const result = scanResults[agent.id];
          const total = result ? result.pass + result.fail + result.error : 0;
          const compliance = total > 0 ? Math.round((result!.pass / total) * 100) : 0;

          return (
            <div key={agent.id}
              className="rounded-lg border border-dark-border bg-dark-card p-3 transition-colors"
            >
              <div className="flex items-center gap-3">
                {/* OS icon */}
                <div className="rounded-lg bg-dark-elevated p-2">
                  {agent.os_type === 'windows'
                    ? <Monitor className="h-5 w-5 text-sky-400" />
                    : <Terminal className="h-5 w-5 text-emerald-400" />
                  }
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-white truncate">
                      {agent.hostname || 'Unknown Host'}
                    </span>
                    {statusIcon(agent.status)}
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ring-1 ring-inset ${statusBadge(agent.status)}`}>
                      {agent.status}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-0.5">
                    {agent.ip_address && <span className="text-xs text-dark-muted font-mono">{agent.ip_address}</span>}
                    {agent.os_version && <span className="text-xs text-dark-muted">{agent.os_version}</span>}
                    {agent.connected_at && (
                      <span className="text-xs text-dark-muted">
                        Connected {new Date(agent.connected_at).toLocaleTimeString()}
                      </span>
                    )}
                  </div>
                </div>

                {/* Per-agent scan button */}
                {isActive && agent.status === 'connected' && !progress && !result && (
                  <button
                    onClick={() => handleScanAgent(agent.id)}
                    className="rounded-lg border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-dark-secondary hover:text-ey-yellow hover:border-ey-yellow/30 transition-colors flex items-center gap-1"
                  >
                    <Play className="h-3 w-3" /> Scan
                  </button>
                )}

                {/* Completed: show compliance */}
                {result && (
                  <div className="flex items-center gap-2">
                    <span className={`text-lg font-bold ${compliance >= 70 ? 'text-emerald-400' : compliance >= 40 ? 'text-amber-400' : 'text-red-400'}`}>
                      {compliance}%
                    </span>
                  </div>
                )}
              </div>

              {/* Scan progress bar */}
              {progress && (
                <div className="mt-3">
                  <div className="flex items-center justify-between text-xs text-dark-muted mb-1">
                    <span>Scanning... {progress.currentRule && `(${progress.currentRule})`}</span>
                    <span>{progress.completed}/{progress.total}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-dark-elevated overflow-hidden">
                    <div
                      className="h-full rounded-full bg-ey-yellow transition-all duration-300"
                      style={{ width: `${progress.total > 0 ? (progress.completed / progress.total) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              )}

              {/* Scan results breakdown */}
              {result && (
                <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                  <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/10 py-1.5 px-2">
                    <p className="text-sm font-bold text-emerald-400">{result.pass}</p>
                    <p className="text-[10px] text-dark-muted">Pass</p>
                  </div>
                  <div className="rounded-lg bg-red-500/5 border border-red-500/10 py-1.5 px-2">
                    <p className="text-sm font-bold text-red-400">{result.fail}</p>
                    <p className="text-[10px] text-dark-muted">Fail</p>
                  </div>
                  <div className="rounded-lg bg-amber-500/5 border border-amber-500/10 py-1.5 px-2">
                    <p className="text-sm font-bold text-amber-400">{result.error}</p>
                    <p className="text-[10px] text-dark-muted">Error</p>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
