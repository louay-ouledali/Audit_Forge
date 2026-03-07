/**
 * ADDiscovery – Active Directory computer discovery panel.
 *
 * Connects to a domain controller via LDAP, discovers computers,
 * checks WinRM status, and bulk-creates targets.
 */
import { useState, useCallback, useMemo } from 'react';
import {
  Network,
  Search,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Monitor,
  Server,
  Shield,
  ChevronDown,
  ChevronUp,
  Wifi,
  WifiOff,
  Plus,
  RefreshCw,
  FileDown,
  Lock,
  Unlock,
} from 'lucide-react';
import * as api from '@/services/api';
import type { ADComputer, ADWinRMCheckResult } from '@/types';
import { extractApiError } from '@/utils/apiError';

interface Props {
  clientId: number;
  missionId: number;
  clientAdConfigured: boolean;
  clientAdDomain?: string | null;
  onTargetsCreated: () => void;
  isLocked: boolean;
}

type ADComputerEnriched = ADComputer & {
  selected: boolean;
  winrm?: ADWinRMCheckResult;
  winrmChecking?: boolean;
};

const inputClass =
  'w-full rounded-lg border border-dark-border bg-dark-elevated px-3 py-2 text-sm text-white placeholder-dark-muted focus:border-ey-yellow/50 focus:outline-none focus:ring-1 focus:ring-ey-yellow/30 transition-colors';

export default function ADDiscovery({
  clientId,
  missionId,
  clientAdConfigured,
  clientAdDomain,
  onTargetsCreated,
  isLocked,
}: Props) {
  // Panel state
  const [expanded, setExpanded] = useState(false);
  const [step, setStep] = useState<'connect' | 'discover' | 'results'>('connect');

  // Connection form
  const [dcHost, setDcHost] = useState('');
  const [domain, setDomain] = useState(clientAdDomain || '');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [useSsl, setUseSsl] = useState(true);
  const [ouFilter, setOuFilter] = useState('');
  const [useStored, setUseStored] = useState(clientAdConfigured);

  // Connection test
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    domain_name?: string;
    dc_hostname?: string;
    forest_name?: string;
    computer_count?: number;
    error?: string;
  } | null>(null);

  // Discovery
  const [discovering, setDiscovering] = useState(false);
  const [computers, setComputers] = useState<ADComputerEnriched[]>([]);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  // WinRM check
  const [checkingWinRM, setCheckingWinRM] = useState(false);

  // Bulk create
  const [creating, setCreating] = useState(false);

  // Filter
  const [searchFilter, setSearchFilter] = useState('');
  const [osFilter, setOsFilter] = useState<string>('all');
  const [winrmFilter, setWinrmFilter] = useState<string>('all');

  // Build credentials payload
  const getCredentials = useCallback(() => {
    if (useStored && clientAdConfigured) {
      return { client_id: clientId };
    }
    return {
      client_id: clientId,
      dc_host: dcHost,
      domain,
      username,
      password,
      use_ssl: useSsl,
    };
  }, [useStored, clientAdConfigured, clientId, dcHost, domain, username, password, useSsl]);

  // ── Test Connection ────────────────────────────────────
  const handleTestConnection = useCallback(async () => {
    setTesting(true);
    setError('');
    setTestResult(null);
    try {
      const result = await api.adTestConnection(getCredentials());
      setTestResult(result);
      if (result.success) {
        setStep('discover');
      }
    } catch (err) {
      setError(extractApiError(err, 'Connection test failed'));
    } finally {
      setTesting(false);
    }
  }, [getCredentials]);

  // ── Discover Computers ─────────────────────────────────
  const handleDiscover = useCallback(async () => {
    setDiscovering(true);
    setError('');
    setComputers([]);
    try {
      const creds = getCredentials();
      const result = await api.adDiscover({
        ...creds,
        ou_filter: ouFilter || undefined,
        resolve_dns: true,
      });
      if (!result.success) {
        setError(result.error || 'Discovery failed');
        return;
      }
      setComputers(
        result.computers.map((c) => ({ ...c, selected: c.enabled }))
      );
      setStep('results');
    } catch (err) {
      setError(extractApiError(err, 'Discovery failed'));
    } finally {
      setDiscovering(false);
    }
  }, [getCredentials, ouFilter]);

  // ── Check WinRM ────────────────────────────────────────
  const handleCheckWinRM = useCallback(async () => {
    const hosts = computers
      .filter((c) => c.selected && (c.ip_address || c.dns_hostname))
      .map((c) => c.ip_address || c.dns_hostname!);
    if (hosts.length === 0) return;

    setCheckingWinRM(true);
    setComputers((prev) =>
      prev.map((c) => ({
        ...c,
        winrmChecking: c.selected && !!(c.ip_address || c.dns_hostname),
      }))
    );

    try {
      const result = await api.adCheckWinRM(hosts);
      const resultMap = new Map(result.results.map((r) => [r.host, r]));

      setComputers((prev) =>
        prev.map((c) => {
          const host = c.ip_address || c.dns_hostname;
          const wr = host ? resultMap.get(host) : undefined;
          return { ...c, winrm: wr, winrmChecking: false };
        })
      );
    } catch (err) {
      setError(extractApiError(err, 'WinRM check failed'));
      setComputers((prev) => prev.map((c) => ({ ...c, winrmChecking: false })));
    } finally {
      setCheckingWinRM(false);
    }
  }, [computers]);

  // ── Enable WinRM ───────────────────────────────────────
  const handleEnableWinRM = useCallback(async () => {
    const hosts = computers
      .filter(
        (c) =>
          c.selected &&
          c.winrm &&
          !c.winrm.winrm_available &&
          (c.ip_address || c.dns_hostname)
      )
      .map((c) => c.ip_address || c.dns_hostname!);
    if (hosts.length === 0) return;

    try {
      const result = await api.adEnableWinRM(clientId, hosts);
      if (result.fallback_script) {
        // Download the fallback script
        const blob = new Blob([result.fallback_script], {
          type: 'text/plain',
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'Enable_WinRM_AD.ps1';
        a.click();
        URL.revokeObjectURL(url);
        setSuccessMsg(
          `WinRM: ${result.successes}/${result.total} enabled directly. Script downloaded for the rest.`
        );
      } else {
        setSuccessMsg(
          `WinRM enabled on ${result.successes}/${result.total} hosts.`
        );
      }
      // Re-check WinRM
      await handleCheckWinRM();
    } catch (err) {
      setError(extractApiError(err, 'WinRM enablement failed'));
    }
  }, [computers, clientId, handleCheckWinRM]);

  // ── Download WinRM Script ──────────────────────────────
  const handleDownloadScript = useCallback(async () => {
    const hosts = computers
      .filter((c) => c.selected && (c.ip_address || c.dns_hostname))
      .map((c) => c.ip_address || c.dns_hostname!);
    if (hosts.length === 0) return;

    try {
      const result = await api.adGenerateWinRMScript(clientId, hosts);
      const blob = new Blob([result.script], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'Enable_WinRM_AD.ps1';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(extractApiError(err, 'Script generation failed'));
    }
  }, [computers, clientId]);

  // ── Bulk Create Targets ────────────────────────────────
  const handleBulkCreate = useCallback(async () => {
    const selected = computers.filter((c) => c.selected);
    if (selected.length === 0) return;

    setCreating(true);
    setError('');
    try {
      const result = await api.adBulkCreateTargets({
        client_id: clientId,
        mission_id: missionId,
        computers: selected.map((c) => ({
          cn: c.cn,
          dns_hostname: c.dns_hostname,
          ip_address: c.ip_address,
          operating_system: c.operating_system,
          os_version: c.os_version,
          distinguished_name: c.distinguished_name,
          matched_benchmark_id: c.matched_benchmark_id,
        })),
      });
      const parts = [`${result.total_created} targets created`];
      if (result.total_skipped > 0)
        parts.push(`${result.total_skipped} skipped (already exist)`);
      if (result.total_errors > 0)
        parts.push(`${result.total_errors} errors`);
      setSuccessMsg(parts.join(', '));
      onTargetsCreated();
    } catch (err) {
      setError(extractApiError(err, 'Target creation failed'));
    } finally {
      setCreating(false);
    }
  }, [computers, clientId, missionId, onTargetsCreated]);

  // ── Selection helpers ──────────────────────────────────
  const toggleAll = useCallback(
    (checked: boolean) =>
      setComputers((prev) => prev.map((c) => ({ ...c, selected: checked }))),
    []
  );

  const toggleOne = useCallback(
    (idx: number) =>
      setComputers((prev) =>
        prev.map((c, i) => (i === idx ? { ...c, selected: !c.selected } : c))
      ),
    []
  );

  // ── Filtered / stats ──────────────────────────────────
  const filteredComputers = useMemo(() => {
    return computers.filter((c) => {
      if (searchFilter) {
        const q = searchFilter.toLowerCase();
        const match =
          c.cn.toLowerCase().includes(q) ||
          (c.dns_hostname || '').toLowerCase().includes(q) ||
          (c.ip_address || '').toLowerCase().includes(q) ||
          (c.operating_system || '').toLowerCase().includes(q);
        if (!match) return false;
      }
      if (osFilter !== 'all') {
        if (osFilter === 'windows' && c.target_type !== 'windows') return false;
        if (osFilter === 'linux' && c.target_type !== 'linux') return false;
        if (osFilter === 'unknown' && c.target_type !== null) return false;
      }
      if (winrmFilter !== 'all') {
        if (winrmFilter === 'available' && !c.winrm?.winrm_available) return false;
        if (winrmFilter === 'unavailable' && c.winrm?.winrm_available !== false)
          return false;
        if (winrmFilter === 'unchecked' && c.winrm !== undefined) return false;
      }
      return true;
    });
  }, [computers, searchFilter, osFilter, winrmFilter]);

  const selectedCount = computers.filter((c) => c.selected).length;
  const winrmAvailable = computers.filter((c) => c.winrm?.winrm_available).length;
  const winrmChecked = computers.filter((c) => c.winrm !== undefined).length;

  if (isLocked) return null;

  return (
    <div className="rounded-xl border border-blue-500/20 bg-dark-card shadow-lg">
      {/* ── Header / Toggle ────────────────────────────────── */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-5 py-3.5 text-left transition-colors hover:bg-dark-elevated/50"
      >
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-blue-500/10 p-2">
            <Network className="h-5 w-5 text-blue-400" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">
              Active Directory Discovery
            </h3>
            <p className="text-xs text-dark-secondary">
              {clientAdConfigured
                ? `Credentials stored for ${clientAdDomain}`
                : 'Connect to a domain controller to discover targets'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {computers.length > 0 && (
            <span className="rounded-full bg-blue-500/20 px-2.5 py-0.5 text-xs font-medium text-blue-400">
              {computers.length} discovered
            </span>
          )}
          {expanded ? (
            <ChevronUp className="h-5 w-5 text-dark-muted" />
          ) : (
            <ChevronDown className="h-5 w-5 text-dark-muted" />
          )}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-dark-border/50 px-5 py-4 space-y-4">
          {/* Error / Success Banners */}
          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400 flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span className="flex-1">{error}</span>
              <button
                onClick={() => setError('')}
                className="text-red-300 hover:text-white"
              >
                ×
              </button>
            </div>
          )}
          {successMsg && (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-400 flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span className="flex-1">{successMsg}</span>
              <button
                onClick={() => setSuccessMsg('')}
                className="text-emerald-300 hover:text-white"
              >
                ×
              </button>
            </div>
          )}

          {/* ── Step 1: Connection Form ───────────────────── */}
          {(step === 'connect' || step === 'discover') && (
            <div className="space-y-3">
              {/* Toggle between stored and manual creds */}
              {clientAdConfigured && (
                <div className="flex items-center gap-3 text-sm">
                  <label className="flex items-center gap-2 cursor-pointer text-dark-secondary hover:text-white">
                    <input
                      type="checkbox"
                      checked={useStored}
                      onChange={(e) => setUseStored(e.target.checked)}
                      className="rounded border-dark-border"
                    />
                    Use stored credentials ({clientAdDomain})
                  </label>
                </div>
              )}

              {!useStored && (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  <div>
                    <label className="block text-xs text-dark-secondary mb-1">
                      Domain Controller
                    </label>
                    <input
                      type="text"
                      value={dcHost}
                      onChange={(e) => setDcHost(e.target.value)}
                      placeholder="dc01.corp.example.com"
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-dark-secondary mb-1">
                      Domain
                    </label>
                    <input
                      type="text"
                      value={domain}
                      onChange={(e) => setDomain(e.target.value)}
                      placeholder="corp.example.com"
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-dark-secondary mb-1">
                      Username
                    </label>
                    <input
                      type="text"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="DOMAIN\\admin or admin@domain"
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-dark-secondary mb-1">
                      Password
                    </label>
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••"
                      className={inputClass}
                    />
                  </div>
                  <div className="flex items-end gap-4">
                    <label className="flex items-center gap-2 cursor-pointer text-sm text-dark-secondary hover:text-white pb-2">
                      <input
                        type="checkbox"
                        checked={useSsl}
                        onChange={(e) => setUseSsl(e.target.checked)}
                        className="rounded border-dark-border"
                      />
                      {useSsl ? (
                        <Lock className="h-3.5 w-3.5 text-emerald-400" />
                      ) : (
                        <Unlock className="h-3.5 w-3.5 text-amber-400" />
                      )}
                      LDAPS (SSL)
                    </label>
                  </div>
                </div>
              )}

              {/* OU Filter */}
              <div className="flex gap-3 items-end">
                <div className="flex-1">
                  <label className="block text-xs text-dark-secondary mb-1">
                    OU Filter{' '}
                    <span className="text-dark-muted">(optional)</span>
                  </label>
                  <input
                    type="text"
                    value={ouFilter}
                    onChange={(e) => setOuFilter(e.target.value)}
                    placeholder="OU=Servers,DC=corp,DC=example,DC=com"
                    className={inputClass}
                  />
                </div>
              </div>

              {/* Test Connection Result */}
              {testResult && testResult.success && (
                <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
                  <div className="flex items-center gap-2 text-sm text-emerald-400 mb-2">
                    <CheckCircle2 className="h-4 w-4" />
                    Connected to {testResult.dc_hostname}
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs text-dark-secondary">
                    <div>
                      <span className="text-dark-muted">Domain:</span>{' '}
                      <span className="text-white">
                        {testResult.domain_name}
                      </span>
                    </div>
                    <div>
                      <span className="text-dark-muted">Forest:</span>{' '}
                      <span className="text-white">
                        {testResult.forest_name || '—'}
                      </span>
                    </div>
                    <div>
                      <span className="text-dark-muted">Computers:</span>{' '}
                      <span className="text-white">
                        {testResult.computer_count}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* Buttons */}
              <div className="flex gap-2">
                <button
                  onClick={handleTestConnection}
                  disabled={testing || (!useStored && (!dcHost || !domain || !username || !password))}
                  className="inline-flex items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-sm font-medium text-blue-400 transition-colors hover:bg-blue-500/20 disabled:opacity-50"
                >
                  {testing ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Shield className="h-4 w-4" />
                  )}
                  Test Connection
                </button>

                {step === 'discover' && (
                  <button
                    onClick={handleDiscover}
                    disabled={discovering}
                    className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-semibold text-black shadow-sm transition-colors hover:bg-ey-yellow-hover disabled:opacity-50"
                  >
                    {discovering ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Search className="h-4 w-4" />
                    )}
                    Discover Computers
                  </button>
                )}
              </div>
            </div>
          )}

          {/* ── Step 2: Results Table ─────────────────────── */}
          {step === 'results' && computers.length > 0 && (
            <div className="space-y-3">
              {/* Summary Bar */}
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <span className="text-dark-secondary">
                  <span className="text-white font-semibold">
                    {computers.length}
                  </span>{' '}
                  computers discovered
                </span>
                <span className="text-dark-muted">|</span>
                <span className="text-dark-secondary">
                  <span className="text-ey-yellow font-semibold">
                    {selectedCount}
                  </span>{' '}
                  selected
                </span>
                {winrmChecked > 0 && (
                  <>
                    <span className="text-dark-muted">|</span>
                    <span className="text-dark-secondary">
                      WinRM:{' '}
                      <span className="text-emerald-400 font-semibold">
                        {winrmAvailable}
                      </span>
                      /{winrmChecked} reachable
                    </span>
                  </>
                )}
              </div>

              {/* Filters */}
              <div className="flex flex-wrap gap-2">
                <input
                  type="text"
                  value={searchFilter}
                  onChange={(e) => setSearchFilter(e.target.value)}
                  placeholder="Search..."
                  className={`${inputClass} !w-48`}
                />
                <select
                  value={osFilter}
                  onChange={(e) => setOsFilter(e.target.value)}
                  className={`${inputClass} !w-36`}
                >
                  <option value="all">All OS</option>
                  <option value="windows">Windows</option>
                  <option value="linux">Linux</option>
                  <option value="unknown">Unknown</option>
                </select>
                <select
                  value={winrmFilter}
                  onChange={(e) => setWinrmFilter(e.target.value)}
                  className={`${inputClass} !w-40`}
                >
                  <option value="all">All WinRM</option>
                  <option value="available">WinRM Available</option>
                  <option value="unavailable">WinRM Unavailable</option>
                  <option value="unchecked">Not Checked</option>
                </select>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={handleCheckWinRM}
                  disabled={checkingWinRM || selectedCount === 0}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-xs font-medium text-blue-400 hover:bg-blue-500/20 disabled:opacity-50"
                >
                  {checkingWinRM ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Wifi className="h-3.5 w-3.5" />
                  )}
                  Check WinRM
                </button>
                <button
                  onClick={handleEnableWinRM}
                  disabled={selectedCount === 0}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-400 hover:bg-amber-500/20 disabled:opacity-50"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Enable WinRM
                </button>
                <button
                  onClick={handleDownloadScript}
                  disabled={selectedCount === 0}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-dark-secondary hover:text-white disabled:opacity-50"
                >
                  <FileDown className="h-3.5 w-3.5" />
                  WinRM Script
                </button>
                <div className="flex-1" />
                <button
                  onClick={() => {
                    setStep('discover');
                    setComputers([]);
                  }}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-dark-border bg-dark-elevated px-3 py-1.5 text-xs font-medium text-dark-secondary hover:text-white"
                >
                  <Search className="h-3.5 w-3.5" />
                  Re-discover
                </button>
                <button
                  onClick={handleBulkCreate}
                  disabled={creating || selectedCount === 0}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-ey-yellow px-4 py-1.5 text-xs font-semibold text-black shadow-sm hover:bg-ey-yellow-hover disabled:opacity-50"
                >
                  {creating ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Plus className="h-3.5 w-3.5" />
                  )}
                  Create {selectedCount} Targets
                </button>
              </div>

              {/* Table */}
              <div className="overflow-x-auto rounded-lg border border-dark-border/50">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-dark-border/50 bg-dark-elevated text-left text-dark-muted">
                      <th className="px-3 py-2 w-8">
                        <input
                          type="checkbox"
                          checked={
                            selectedCount === filteredComputers.length &&
                            filteredComputers.length > 0
                          }
                          onChange={(e) => toggleAll(e.target.checked)}
                          className="rounded border-dark-border"
                        />
                      </th>
                      <th className="px-3 py-2">Computer</th>
                      <th className="px-3 py-2">IP Address</th>
                      <th className="px-3 py-2">OS</th>
                      <th className="px-3 py-2">Benchmark</th>
                      <th className="px-3 py-2 text-center">WinRM</th>
                      <th className="px-3 py-2">OU</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-dark-border/30">
                    {filteredComputers.map((comp, idx) => {
                      const realIdx = computers.indexOf(comp);
                      return (
                        <tr
                          key={comp.cn + idx}
                          className={`transition-colors hover:bg-dark-elevated/50 ${!comp.enabled ? 'opacity-50' : ''
                            }`}
                        >
                          <td className="px-3 py-2">
                            <input
                              type="checkbox"
                              checked={comp.selected}
                              onChange={() => toggleOne(realIdx)}
                              className="rounded border-dark-border"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-2">
                              {comp.target_type === 'windows' ? (
                                <Monitor className="h-3.5 w-3.5 text-blue-400 shrink-0" />
                              ) : (
                                <Server className="h-3.5 w-3.5 text-orange-400 shrink-0" />
                              )}
                              <div>
                                <div className="text-white font-medium">
                                  {comp.cn}
                                </div>
                                {comp.dns_hostname && comp.dns_hostname !== comp.cn && (
                                  <div className="text-dark-muted truncate max-w-[200px]">
                                    {comp.dns_hostname}
                                  </div>
                                )}
                              </div>
                              {!comp.enabled && (
                                <span className="rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] text-red-400">
                                  Disabled
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="px-3 py-2 font-mono text-dark-secondary">
                            {comp.ip_address || '—'}
                          </td>
                          <td className="px-3 py-2 text-dark-secondary max-w-[200px] truncate">
                            {comp.operating_system || '—'}
                          </td>
                          <td className="px-3 py-2">
                            {comp.matched_benchmark_name ? (
                              <span className="inline-flex items-center gap-1 rounded bg-emerald-500/10 px-1.5 py-0.5 text-emerald-400">
                                <CheckCircle2 className="h-3 w-3" />
                                <span className="truncate max-w-[150px]">
                                  {comp.matched_benchmark_name}
                                </span>
                              </span>
                            ) : comp.os_confidence === 'close' ? (
                              <span className="text-amber-400">~partial</span>
                            ) : (
                              <span className="text-dark-muted">—</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-center">
                            {comp.winrmChecking ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-400 mx-auto" />
                            ) : comp.winrm ? (
                              comp.winrm.winrm_available ? (
                                <div className="flex items-center justify-center gap-1 text-emerald-400">
                                  <Wifi className="h-3.5 w-3.5" />
                                  <span className="text-[10px]">
                                    {comp.winrm.winrm_https ? 'HTTPS' : 'HTTP'}
                                  </span>
                                </div>
                              ) : (
                                <WifiOff className="h-3.5 w-3.5 text-red-400 mx-auto" />
                              )
                            ) : (
                              <span className="text-dark-muted">—</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-dark-muted truncate max-w-[180px]">
                            {comp.ou_path || '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {filteredComputers.length === 0 && (
                  <div className="py-8 text-center text-sm text-dark-muted">
                    No computers match the current filters.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
