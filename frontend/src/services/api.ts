import axios from 'axios';
import type { Client, Mission, Target, Settings, Benchmark, BenchmarkStatus, EnrichStatus, VerifyStatus, Rule, RuleCommand, LLMStatus, CommandHistoryEntry, VerificationReport, NetworkScanRequest, NetworkScanResponse, ScanStatus, ScanCancelResponse } from '@/types';

const api = axios.create({
  baseURL: '/api',
});

export async function getHealth() {
  const { data } = await api.get('/health');
  return data;
}

// Clients
export async function getClients(): Promise<Client[]> {
  const { data } = await api.get('/clients');
  return data.data;
}

export async function getClient(id: number): Promise<Client> {
  const { data } = await api.get(`/clients/${id}`);
  return data.data;
}

export async function createClient(payload: Partial<Client>): Promise<Client> {
  const { data } = await api.post('/clients', payload);
  return data.data;
}

export async function updateClient(id: number, payload: Partial<Client>): Promise<Client> {
  const { data } = await api.put(`/clients/${id}`, payload);
  return data.data;
}

export async function deleteClient(id: number): Promise<void> {
  await api.delete(`/clients/${id}`);
}

// Missions
export async function getMissions(clientId: number): Promise<Mission[]> {
  const { data } = await api.get(`/clients/${clientId}/missions`);
  return data.data;
}

export async function createMission(payload: Partial<Mission>): Promise<Mission> {
  const { data } = await api.post('/missions', payload);
  return data.data;
}

export async function updateMission(id: number, payload: Partial<Mission>): Promise<Mission> {
  const { data } = await api.put(`/missions/${id}`, payload);
  return data.data;
}

export async function deleteMission(id: number): Promise<void> {
  await api.delete(`/missions/${id}`);
}

// Targets
export async function getTargets(missionId: number): Promise<Target[]> {
  const { data } = await api.get(`/missions/${missionId}/targets`);
  return data.data;
}

export async function createTarget(payload: Partial<Target>): Promise<Target> {
  const { data } = await api.post('/targets', payload);
  return data.data;
}

export async function updateTarget(id: number, payload: Partial<Target>): Promise<Target> {
  const { data } = await api.put(`/targets/${id}`, payload);
  return data.data;
}

export async function deleteTarget(id: number): Promise<void> {
  await api.delete(`/targets/${id}`);
}

// Settings
export async function getSettings(): Promise<Settings> {
  const { data } = await api.get('/settings');
  return data.data;
}

export async function updateSettings(payload: Settings): Promise<Settings> {
  const { data } = await api.put('/settings', payload);
  return data.data;
}

// Benchmarks
export async function getBenchmarks(): Promise<Benchmark[]> {
  const { data } = await api.get('/benchmarks');
  return data.data;
}

export async function getBenchmark(id: number): Promise<Benchmark> {
  const { data } = await api.get(`/benchmarks/${id}`);
  return data.data;
}

export async function importBenchmark(file: File): Promise<{ benchmark_id: number; status: string; message: string }> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post('/benchmarks/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function deleteBenchmark(id: number): Promise<void> {
  await api.delete(`/benchmarks/${id}`);
}

export async function getBenchmarkStatus(id: number): Promise<BenchmarkStatus> {
  const { data } = await api.get(`/benchmarks/${id}/status`);
  return data;
}

export async function getBenchmarkRules(id: number, params?: { category?: string; severity?: string; search?: string }): Promise<Rule[]> {
  const { data } = await api.get(`/benchmarks/${id}/rules`, { params });
  return data.data;
}

// Enrichment
export async function startEnrichment(benchmarkId: number): Promise<void> {
  await api.post(`/benchmarks/${benchmarkId}/enrich`);
}

export async function pauseEnrichment(benchmarkId: number): Promise<void> {
  await api.post(`/benchmarks/${benchmarkId}/enrich/pause`);
}

export async function getEnrichmentStatus(benchmarkId: number): Promise<EnrichStatus> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/enrich/status`);
  return data;
}

// Verification
export async function startVerification(benchmarkId: number): Promise<void> {
  await api.post(`/benchmarks/${benchmarkId}/verify`);
}

export async function getVerificationStatus(benchmarkId: number): Promise<VerifyStatus> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/verify/status`);
  return data;
}

export async function getVerificationResults(
  benchmarkId: number,
  params?: { level?: string; result?: string },
): Promise<{ data: VerificationReport[]; total: number }> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/verify/results`, { params });
  return data;
}

export async function bulkAcceptCommands(benchmarkId: number): Promise<{ message: string; count: number }> {
  const { data } = await api.post(`/benchmarks/${benchmarkId}/verify/bulk-accept`);
  return data;
}

export async function overrideVerification(benchmarkId: number): Promise<void> {
  await api.post(`/benchmarks/${benchmarkId}/verify/override`);
}

export async function bulkRegenerateCommands(benchmarkId: number): Promise<{ message: string; count: number }> {
  const { data } = await api.post(`/benchmarks/${benchmarkId}/commands/bulk-regenerate`);
  return data;
}

// Rules
export async function getRule(id: number): Promise<Rule> {
  const { data } = await api.get(`/rules/${id}`);
  return data.data;
}

export async function getRuleCommand(ruleId: number): Promise<RuleCommand | null> {
  const { data } = await api.get(`/rules/${ruleId}/command`);
  return data.data;
}

export async function flagCommand(ruleId: number, reason: string, errorOutput?: string): Promise<RuleCommand> {
  const { data } = await api.post(`/rules/${ruleId}/command/flag`, {
    reason,
    error_output: errorOutput,
  });
  return data.data;
}

export async function regenerateCommand(ruleId: number, systemInfo?: string): Promise<RuleCommand> {
  const { data } = await api.post(`/rules/${ruleId}/command/regenerate`, {
    system_info: systemInfo,
  });
  return data.data;
}

export async function protectCommand(ruleId: number, reason?: string): Promise<RuleCommand> {
  const { data } = await api.post(`/rules/${ruleId}/command/protect`, {
    reason: reason || 'Manually protected by auditor',
  });
  return data.data;
}

export async function unlockCommand(ruleId: number, reason: string): Promise<RuleCommand> {
  const { data } = await api.post(`/rules/${ruleId}/command/unlock`, { reason });
  return data.data;
}

export async function getCommandHistory(ruleId: number): Promise<CommandHistoryEntry[]> {
  const { data } = await api.get(`/rules/${ruleId}/command/history`);
  return data.data;
}

export async function verifySingleCommand(ruleId: number): Promise<RuleCommand> {
  const { data } = await api.post(`/rules/${ruleId}/command/verify`);
  return data.data;
}

export async function getCommandVerificationReports(ruleId: number): Promise<VerificationReport[]> {
  const { data } = await api.get(`/rules/${ruleId}/command/verification-reports`);
  return data.data;
}

// LLM
export async function getLLMStatus(): Promise<LLMStatus> {
  const { data } = await api.get('/llm/status');
  return data;
}

// Network Scans
export async function startNetworkScan(payload: NetworkScanRequest): Promise<NetworkScanResponse> {
  const { data } = await api.post('/scans/network', payload);
  return data;
}

export async function getScanStatus(scanId: number): Promise<ScanStatus> {
  const { data } = await api.get(`/scans/${scanId}/status`);
  return data;
}

export async function cancelScan(scanId: number): Promise<ScanCancelResponse> {
  const { data } = await api.post(`/scans/${scanId}/cancel`);
  return data;
}
