import { useEffect, useState, useRef, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import {
  Shield, Download, Monitor, Terminal, CheckCircle2, XCircle, AlertTriangle,
  Loader2, Wifi, WifiOff, Clock, ChevronDown, ChevronUp, Cpu, Globe, Lock,
  BarChart3, Usb,
} from 'lucide-react';
import * as api from '@/services/api';
import { PortalWSClient } from '@/services/wsAgent';
import type { AgentEvent, PortalInitScan } from '@/services/wsAgent';
import logoImg from '@/assets/logo.png';

type PortalStep = 'loading' | 'invalid' | 'choose' | 'instructions' | 'connected' | 'scanning' | 'done';

interface AgentInfo {
  hostname: string | null;
  os_type: string | null;
  os_version: string | null;
  ip_addresses: string[];
  open_ports: number[];
}

interface ScanProgress {
  completed: number;
  total: number;
  currentRule?: string;
}

interface ScanResult {
  pass: number;
  fail: number;
  error: number;
  compliancePercentage: number;
  benchmarkName: string;
  totalRulesChecked: number;
}

const STORAGE_KEY = (code: string) => `af_portal_${code}`;

export default function ConnectPortal() {
  const { code } = useParams<{ code: string }>();
  const [step, setStep] = useState<PortalStep>('loading');
  const [clientName, setClientName] = useState('');
  const [expiresAt, setExpiresAt] = useState('');
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [platform, setPlatform] = useState<'windows' | 'linux'>('windows');
  const [agentInfo, setAgentInfo] = useState<AgentInfo | null>(null);
  const [scanProgress, setScanProgress] = useState<ScanProgress | null>(null);
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [showAllPorts, setShowAllPorts] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const wsRef = useRef<PortalWSClient | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Detect OS
  useEffect(() => {
    const ua = navigator.userAgent.toLowerCase();
    if (ua.includes('linux') || ua.includes('mac')) setPlatform('linux');
  }, []);

  // Handle WebSocket events
  const handleWsEvent = useCallback((event: AgentEvent) => {
    if (event.type === 'portal_init') {
      const { agents, last_scan } = event.payload;
      const myAgent = agents.find(a => a.status !== 'pending');
      if (myAgent) {
        // Populate agent info from system_info
        const si = myAgent.system_info as Record<string, unknown> | null;
        setAgentInfo({
          hostname: myAgent.hostname,
          os_type: myAgent.os_type,
          os_version: myAgent.os_version,
          ip_addresses: (si?.ip_addresses as string[]) || [],
          open_ports: (si?.open_ports as number[]) || [],
        });

        // Resolve step from agent status
        if (myAgent.status === 'connected') setStep('connected');
        else if (myAgent.status === 'scanning') setStep('scanning');
        else if (myAgent.status === 'completed' || myAgent.status === 'disconnected') {
          setStep('done');
        }
      } else {
        // No active agent — check if user already downloaded
        const saved = sessionStorage.getItem(STORAGE_KEY(code || ''));
        if (saved) {
          try {
            const cached = JSON.parse(saved);
            if (cached.downloadStarted) {
              setStep('instructions');
              return;
            }
          } catch { /* ignore */ }
        }
        setStep('choose');
      }

      // Populate scan results from last_scan snapshot
      if (last_scan) {
        setScanResult(scanResultFromInit(last_scan));
      }
    }

    if (event.type === 'agent_connected') {
      setStep('connected');
    }

    if (event.type === 'agent_system_info') {
      const p = event.payload;
      setAgentInfo({
        hostname: p.hostname,
        os_type: p.os,
        os_version: p.os_version,
        ip_addresses: p.ip_addresses || [],
        open_ports: p.open_ports || [],
      });
    }

    if (event.type === 'scan_progress') {
      setStep('scanning');
      setScanProgress({
        completed: event.payload.completed,
        total: event.payload.total,
        currentRule: event.payload.current_rule,
      });
    }

    if (event.type === 'scan_complete') {
      const p = event.payload;
      const total = p.pass + p.fail + p.error;
      setStep('done');
      setScanProgress(null);
      setScanResult({
        pass: p.pass,
        fail: p.fail,
        error: p.error,
        compliancePercentage: p.compliance_percentage ?? (total > 0 ? Math.round((p.pass / total) * 100) : 0),
        benchmarkName: p.benchmark_name ?? 'CIS Benchmark',
        totalRulesChecked: p.total_rules_checked ?? total,
      });
    }

    if (event.type === 'agent_disconnected') {
      // If we're done, stay done. Otherwise note disconnection.
      setStep(prev => prev === 'done' ? 'done' : 'done');
    }
  }, [code]);

  // Connect WebSocket
  const connectWS = useCallback((enrollmentCode: string) => {
    if (wsRef.current) wsRef.current.disconnect();
    const ws = new PortalWSClient(enrollmentCode);
    wsRef.current = ws;
    ws.onEvent(handleWsEvent);
    // Fallback polling if WS doesn't connect
    ws.onStatus((status) => {
      if (status === 'error' || status === 'disconnected') {
        startFallbackPolling();
      }
    });
    ws.connect();
  }, [handleWsEvent]);

  // Fallback HTTP polling (same as original approach)
  const startFallbackPolling = useCallback(() => {
    if (!sessionId || pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const agents = await api.getConnectAgents(sessionId);
        const myAgent = agents.find(a => a.status !== 'pending');
        if (myAgent) {
          if (myAgent.status === 'connected') setStep('connected');
          if (myAgent.status === 'scanning') setStep('scanning');
          if (myAgent.status === 'completed') {
            setStep('done');
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }
      } catch { /* ignore */ }
    }, 3000);
  }, [sessionId]);

  // Validate enrollment code on mount
  useEffect(() => {
    if (!code) { setStep('invalid'); return; }

    // Check sessionStorage for persisted state
    const saved = sessionStorage.getItem(STORAGE_KEY(code));
    if (saved) {
      try {
        const cached = JSON.parse(saved);
        setSessionId(cached.sessionId);
        setClientName(cached.clientName || '');
        setExpiresAt(cached.expiresAt || '');
        if (cached.platform) setPlatform(cached.platform);
        // Don't set step — WebSocket portal_init will resolve it
        connectWS(code);
        return;
      } catch { /* fall through */ }
    }

    // First visit — validate enrollment code
    api.validateEnrollmentCode(code).then(res => {
      if (res.valid && res.session_id) {
        setSessionId(res.session_id);
        setClientName(res.client_name || '');
        setExpiresAt(res.expires_at || '');
        setStep('choose');
        // Connect WebSocket immediately to receive events
        connectWS(code);
      } else {
        setStep('invalid');
      }
    }).catch(() => setStep('invalid'));

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (wsRef.current) wsRef.current.disconnect();
    };
  }, [code]);

  const persistState = (extra: Record<string, unknown> = {}) => {
    if (!code) return;
    sessionStorage.setItem(STORAGE_KEY(code), JSON.stringify({
      sessionId, clientName, expiresAt, platform, ...extra,
    }));
  };

  const handleDownload = () => {
    if (!code) return;
    const url = api.getAgentScriptUrl(code, platform);
    window.open(url, '_blank');
    setStep('instructions');
    persistState({ downloadStarted: true });
  };

  const formatExpiry = (iso: string) => {
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
  };

  const complianceColor = (pct: number) =>
    pct >= 70 ? 'text-emerald-400' : pct >= 40 ? 'text-amber-400' : 'text-red-400';

  const complianceBg = (pct: number) =>
    pct >= 70 ? 'bg-emerald-400' : pct >= 40 ? 'bg-amber-400' : 'bg-red-400';

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white flex flex-col">
      {/* Header */}
      <header className="border-b border-white/10 bg-[#12121a] px-6 py-4">
        <div className="mx-auto flex max-w-3xl items-center gap-3">
          <img src={logoImg} alt="AuditForge" className="h-8 w-8" />
          <div>
            <h1 className="text-lg font-bold text-[#ffe600]">AuditForge Connect</h1>
            <p className="text-xs text-gray-400">Secure Configuration Review Portal</p>
          </div>
          {clientName && (
            <div className="ml-auto rounded-full bg-white/5 px-3 py-1 text-xs font-medium text-gray-300 ring-1 ring-white/10">
              {clientName}
            </div>
          )}
        </div>
      </header>

      {/* Main */}
      <main className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-xl space-y-6">

          {/* Loading */}
          {step === 'loading' && (
            <Card>
              <div className="flex flex-col items-center gap-4 py-8">
                <Loader2 className="h-8 w-8 animate-spin text-[#ffe600]" />
                <p className="text-gray-400">Validating enrollment code...</p>
              </div>
            </Card>
          )}

          {/* Invalid code */}
          {step === 'invalid' && (
            <Card>
              <div className="flex flex-col items-center gap-4 py-8 text-center">
                <XCircle className="h-12 w-12 text-red-400" />
                <h2 className="text-xl font-bold">Invalid or Expired Code</h2>
                <p className="text-sm text-gray-400 max-w-sm">
                  The enrollment code <code className="rounded bg-white/10 px-2 py-0.5 font-mono text-[#ffe600]">{code}</code> is not valid
                  or has expired. Please contact your auditor for a new code.
                </p>
              </div>
            </Card>
          )}

          {/* Step 1: Choose platform */}
          {step === 'choose' && (
            <Card>
              <div className="text-center mb-6">
                <Shield className="mx-auto h-10 w-10 text-[#ffe600] mb-3" />
                <h2 className="text-xl font-bold">Connect This Device</h2>
                <p className="mt-2 text-sm text-gray-400">
                  Download and run the AuditForge agent to connect this device for a configuration review.
                  The agent only makes an outbound connection — no ports are opened on this device.
                </p>
                {expiresAt && (
                  <p className="mt-2 text-xs text-gray-500 flex items-center justify-center gap-1">
                    <Clock className="h-3 w-3" /> Session expires: {formatExpiry(expiresAt)}
                  </p>
                )}
              </div>

              <div className="mb-6">
                <p className="mb-3 text-sm font-medium text-gray-300">Select your operating system:</p>
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { key: 'windows' as const, label: 'Windows', icon: Monitor, desc: 'PowerShell script (.ps1)' },
                    { key: 'linux' as const, label: 'Linux / macOS', icon: Terminal, desc: 'Bash script (.sh)' },
                  ].map(opt => (
                    <button
                      key={opt.key}
                      onClick={() => setPlatform(opt.key)}
                      className={`flex flex-col items-center gap-2 rounded-xl border p-5 transition-all ${
                        platform === opt.key
                          ? 'border-[#ffe600]/40 bg-[#ffe600]/5 ring-2 ring-[#ffe600]/30'
                          : 'border-white/10 bg-white/[0.02] hover:border-white/20'
                      }`}
                    >
                      <opt.icon className={`h-8 w-8 ${platform === opt.key ? 'text-[#ffe600]' : 'text-gray-500'}`} />
                      <span className={`text-sm font-semibold ${platform === opt.key ? 'text-[#ffe600]' : 'text-gray-300'}`}>{opt.label}</span>
                      <span className="text-xs text-gray-500">{opt.desc}</span>
                    </button>
                  ))}
                </div>
              </div>

              <button
                onClick={handleDownload}
                className="w-full rounded-xl bg-[#ffe600] py-3 text-sm font-bold text-black hover:bg-[#e6cf00] transition-colors flex items-center justify-center gap-2 shadow-lg shadow-[#ffe600]/10"
              >
                <Download className="h-4 w-4" />
                Download & Connect
              </button>

              <div className="mt-4 rounded-lg bg-white/[0.03] border border-white/5 p-3">
                <p className="text-xs text-gray-500 leading-relaxed">
                  <strong className="text-gray-400">Security info:</strong> The agent makes a single outbound WebSocket connection.
                  It never opens any ports or listens for incoming connections. When the audit completes, the agent
                  self-terminates and leaves no trace on your device.
                </p>
              </div>
            </Card>
          )}

          {/* Step 2: Instructions (waiting for agent to connect) */}
          {step === 'instructions' && (
            <Card>
              <div className="text-center mb-6">
                <Loader2 className="mx-auto h-8 w-8 animate-spin text-[#ffe600] mb-3" />
                <h2 className="text-lg font-bold">Waiting for Agent Connection</h2>
                <p className="mt-2 text-sm text-gray-400">
                  Run the downloaded script on this device to establish the connection.
                </p>
              </div>

              <div className="rounded-lg bg-[#1a1a24] border border-white/10 p-4 font-mono text-sm">
                {platform === 'windows' ? (
                  <div>
                    <p className="text-gray-500 text-xs mb-2"># Open PowerShell as Administrator and run:</p>
                    <p className="text-emerald-400">Set-ExecutionPolicy Bypass -Scope Process -Force</p>
                    <p className="text-emerald-400">.\auditforge_agent.ps1</p>
                  </div>
                ) : (
                  <div>
                    <p className="text-gray-500 text-xs mb-2"># In terminal, run:</p>
                    <p className="text-emerald-400">chmod +x auditforge_agent.sh</p>
                    <p className="text-emerald-400">sudo ./auditforge_agent.sh</p>
                  </div>
                )}
              </div>

              <div className="mt-4 flex items-center gap-2 rounded-lg bg-amber-500/5 border border-amber-500/20 p-3">
                <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
                <p className="text-xs text-amber-300/80">
                  The script must run with elevated privileges to collect system configuration data.
                </p>
              </div>
            </Card>
          )}

          {/* Device info card — shown in connected/scanning/done */}
          {agentInfo && ['connected', 'scanning', 'done'].includes(step) && (
            <Card>
              <div className="flex items-center gap-3 mb-4">
                <div className="rounded-lg bg-white/5 p-2">
                  <Cpu className="h-5 w-5 text-[#ffe600]" />
                </div>
                <div>
                  <p className="text-sm font-semibold">{agentInfo.hostname || 'This Device'}</p>
                  <p className="text-xs text-gray-400">
                    {agentInfo.os_type === 'windows' ? 'Windows' : 'Linux'}
                    {agentInfo.os_version && ` — ${agentInfo.os_version}`}
                  </p>
                </div>
              </div>

              {agentInfo.ip_addresses.length > 0 && (
                <div className="mb-3">
                  <p className="text-[10px] uppercase tracking-wider text-gray-500 mb-1 flex items-center gap-1">
                    <Globe className="h-3 w-3" /> IP Addresses
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {agentInfo.ip_addresses.map((ip, i) => (
                      <span key={i} className="rounded bg-white/5 px-2 py-0.5 text-xs font-mono text-gray-300 ring-1 ring-white/10">
                        {ip}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {agentInfo.open_ports.length > 0 && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-gray-500 mb-1 flex items-center gap-1">
                    <Lock className="h-3 w-3" /> Open Ports ({agentInfo.open_ports.length})
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {(showAllPorts ? agentInfo.open_ports : agentInfo.open_ports.slice(0, 15)).map((port, i) => (
                      <span key={i} className="rounded bg-white/5 px-2 py-0.5 text-xs font-mono text-gray-300 ring-1 ring-white/10">
                        {port}
                      </span>
                    ))}
                    {!showAllPorts && agentInfo.open_ports.length > 15 && (
                      <button onClick={() => setShowAllPorts(true)}
                        className="text-[10px] text-[#ffe600] hover:underline">
                        +{agentInfo.open_ports.length - 15} more
                      </button>
                    )}
                  </div>
                </div>
              )}
            </Card>
          )}

          {/* Step 3: Connected — waiting for auditor */}
          {step === 'connected' && (
            <Card>
              <div className="flex flex-col items-center gap-3 py-4">
                <div className="rounded-full bg-emerald-500/10 p-3">
                  <Wifi className="h-8 w-8 text-emerald-400" />
                </div>
                <h2 className="text-lg font-bold text-emerald-400">Connected</h2>
                <p className="text-sm text-gray-400 text-center">
                  Your device is connected and ready for review. The auditor will start the scan shortly.
                </p>
                <div className="flex items-center gap-2 mt-2">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                  </span>
                  <span className="text-xs text-emerald-400 font-medium">Live connection active</span>
                </div>
              </div>
            </Card>
          )}

          {/* Step 4: Scanning in progress */}
          {step === 'scanning' && (
            <Card>
              <div className="flex flex-col items-center gap-3 py-4">
                <Loader2 className="h-8 w-8 animate-spin text-[#ffe600]" />
                <h2 className="text-lg font-bold">Scan in Progress</h2>
                <p className="text-sm text-gray-400 text-center">
                  The auditor is scanning your device's configuration. This may take a few minutes.
                </p>

                {scanProgress ? (
                  <div className="w-full mt-4">
                    <div className="flex items-center justify-between text-xs text-gray-400 mb-1.5">
                      <span>
                        {scanProgress.currentRule
                          ? `Checking ${scanProgress.currentRule}...`
                          : 'Scanning...'}
                      </span>
                      <span className="font-mono">{scanProgress.completed}/{scanProgress.total}</span>
                    </div>
                    <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-[#ffe600] transition-all duration-500"
                        style={{ width: `${scanProgress.total > 0 ? (scanProgress.completed / scanProgress.total) * 100 : 0}%` }}
                      />
                    </div>
                    <p className="mt-1.5 text-center text-[10px] text-gray-500">
                      {scanProgress.total > 0
                        ? `${Math.round((scanProgress.completed / scanProgress.total) * 100)}% complete`
                        : 'Starting...'}
                    </p>
                  </div>
                ) : (
                  <div className="w-full mt-4 h-2 rounded-full bg-white/5 overflow-hidden">
                    <div className="h-full rounded-full bg-[#ffe600] animate-pulse" style={{ width: '30%' }} />
                  </div>
                )}
              </div>
            </Card>
          )}

          {/* Step 5: Done — results dashboard */}
          {step === 'done' && (
            <Card>
              <div className="flex flex-col items-center gap-3 py-4">
                <div className="rounded-full bg-emerald-500/10 p-3">
                  <CheckCircle2 className="h-10 w-10 text-emerald-400" />
                </div>
                <h2 className="text-xl font-bold">Review Complete</h2>

                {scanResult ? (
                  <>
                    <p className="text-xs text-gray-500 mb-1">{scanResult.benchmarkName}</p>

                    {/* Compliance score */}
                    <div className="relative w-32 h-32 my-2">
                      <svg className="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
                        <circle cx="50" cy="50" r="40" fill="none" stroke="currentColor"
                          className="text-white/5" strokeWidth="8" />
                        <circle cx="50" cy="50" r="40" fill="none"
                          className={complianceBg(scanResult.compliancePercentage)}
                          strokeWidth="8" strokeLinecap="round"
                          strokeDasharray={`${scanResult.compliancePercentage * 2.51} 251`}
                        />
                      </svg>
                      <div className="absolute inset-0 flex items-center justify-center">
                        <span className={`text-2xl font-bold ${complianceColor(scanResult.compliancePercentage)}`}>
                          {scanResult.compliancePercentage}%
                        </span>
                      </div>
                    </div>

                    <p className="text-xs text-gray-500">{scanResult.totalRulesChecked} rules checked</p>

                    {/* Pass / Fail / Error grid */}
                    <div className="w-full grid grid-cols-3 gap-2 mt-3 text-center">
                      <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/10 py-2 px-3">
                        <p className="text-lg font-bold text-emerald-400">{scanResult.pass}</p>
                        <p className="text-[10px] text-gray-500">Pass</p>
                      </div>
                      <div className="rounded-lg bg-red-500/5 border border-red-500/10 py-2 px-3">
                        <p className="text-lg font-bold text-red-400">{scanResult.fail}</p>
                        <p className="text-[10px] text-gray-500">Fail</p>
                      </div>
                      <div className="rounded-lg bg-amber-500/5 border border-amber-500/10 py-2 px-3">
                        <p className="text-lg font-bold text-amber-400">{scanResult.error}</p>
                        <p className="text-[10px] text-gray-500">Error</p>
                      </div>
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-gray-400 text-center">
                    The configuration review of your device has been completed.
                  </p>
                )}

                <div className="w-full mt-4 flex items-center gap-2 rounded-lg bg-white/[0.03] border border-white/5 p-3">
                  <WifiOff className="h-4 w-4 text-gray-500 shrink-0" />
                  <p className="text-xs text-gray-500">
                    Agent disconnected. Zero processes, zero open ports, zero traces remain.
                  </p>
                </div>
              </div>
            </Card>
          )}

          {/* Tools section — shown in connected and done steps */}
          {code && ['connected', 'done'].includes(step) && (
            <div className="rounded-2xl border border-white/10 bg-[#12121a] overflow-hidden">
              <button
                onClick={() => setShowTools(!showTools)}
                className="w-full flex items-center justify-between px-6 py-3 hover:bg-white/[0.02] transition-colors"
              >
                <span className="text-sm font-medium text-gray-400 flex items-center gap-2">
                  <BarChart3 className="h-4 w-4" /> Additional Tools
                </span>
                {showTools ? <ChevronUp className="h-4 w-4 text-gray-500" /> : <ChevronDown className="h-4 w-4 text-gray-500" />}
              </button>
              {showTools && (
                <div className="px-6 pb-5 space-y-3 border-t border-white/5 pt-4">
                  <p className="text-xs text-gray-500 mb-2">
                    Download scripts to help with future reviews of this device.
                  </p>

                  {/* WinRM/SSH enablement script */}
                  <a
                    href={api.getEnableScriptUrl(code, platform)}
                    download
                    className="w-full rounded-lg border border-white/10 bg-white/[0.02] hover:border-white/20 p-3 flex items-center gap-3 transition-colors block"
                  >
                    <Lock className="h-5 w-5 text-sky-400 shrink-0" />
                    <div>
                      <p className="text-sm font-medium text-gray-200">
                        {platform === 'windows' ? 'Enable WinRM' : 'Enable SSH'} Script
                      </p>
                      <p className="text-[10px] text-gray-500">
                        {platform === 'windows'
                          ? 'Enables Windows Remote Management for direct scanning'
                          : 'Installs and configures SSH for direct scanning'}
                      </p>
                    </div>
                    <Download className="h-4 w-4 text-gray-500 ml-auto" />
                  </a>

                  {/* USB audit package — only when a scan has been run */}
                  {scanResult && (
                    <a
                      href={api.getUsbScriptUrl(code, platform)}
                      download
                      className="w-full rounded-lg border border-white/10 bg-white/[0.02] hover:border-white/20 p-3 flex items-center gap-3 transition-colors block"
                    >
                      <Usb className="h-5 w-5 text-amber-400 shrink-0" />
                      <div>
                        <p className="text-sm font-medium text-gray-200">USB Review Package</p>
                        <p className="text-[10px] text-gray-500">
                          Offline review script for air-gapped environments
                        </p>
                      </div>
                      <Download className="h-4 w-4 text-gray-500 ml-auto" />
                    </a>
                  )}
                </div>
              )}
            </div>
          )}

        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-white/5 py-4 text-center text-xs text-gray-600">
        AuditForge Connect &mdash; Secured outbound-only connection
      </footer>
    </div>
  );
}

function scanResultFromInit(ls: PortalInitScan): ScanResult {
  return {
    pass: ls.passed,
    fail: ls.failed,
    error: ls.errors,
    compliancePercentage: ls.compliance_percentage,
    benchmarkName: ls.benchmark_name,
    totalRulesChecked: ls.passed + ls.failed + ls.errors,
  };
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-[#12121a] p-6 shadow-2xl shadow-black/50">
      {children}
    </div>
  );
}
