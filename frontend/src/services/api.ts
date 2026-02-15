import axios from 'axios';
import type { Client, Mission, Target, Settings, Benchmark, BenchmarkStatus, EnrichStatus, VerifyStatus, Rule, RuleCommand, LLMStatus, CommandHistoryEntry, VerificationReport, GenerateScriptRequest, ScriptPreviewResponse, NetworkScanRequest, NetworkScanResponse, ScanStatus, ScanCancelResponse, ScanDetail, Finding, ImportResultsResponse, ReportGenerateRequest, AISummaryRequest, AISummaryResponse, AnalysisRequest, MissionAnalysisResult, ComparableMission } from '@/types';

const api = axios.create({
  baseURL: '/api',
});

export async function getHealth() {
  const { data } = await api.get('/health');
  return data;
}

export async function getDashboardStats(): Promise<{ clients: number; active_missions: number; benchmarks: number; scans: number }> {
  const { data } = await api.get('/stats');
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
export async function getAllMissions(): Promise<Mission[]> {
  const { data } = await api.get('/missions');
  return data.data;
}

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

export async function getMission(id: number): Promise<Mission> {
  const { data } = await api.get(`/missions/${id}`);
  return data.data;
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
  const { data } = await api.put('/settings', { settings: payload });
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

// Phase Export / Import
export async function exportRules(benchmarkId: number): Promise<Blob> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/rules/export`, {
    responseType: 'blob',
  });
  return data;
}

export async function importRules(benchmarkId: number, file: File): Promise<{ message: string; rules_imported: number }> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post(`/benchmarks/${benchmarkId}/rules/import`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function exportCommands(benchmarkId: number): Promise<Blob> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/commands/export`, {
    responseType: 'blob',
  });
  return data;
}

export async function importCommands(benchmarkId: number, file: File): Promise<{ message: string; created: number; updated: number; skipped: number }> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post(`/benchmarks/${benchmarkId}/commands/import`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
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

export async function testLLM(): Promise<{ success: boolean; response: string | null; response_time_ms: number; model?: string; error?: string }> {
  const { data } = await api.post('/llm/test');
  return data;
}

// Script Export (USB)
export async function generateScript(payload: GenerateScriptRequest): Promise<Blob> {
  const { data } = await api.post('/scans/generate-script', payload, {
    responseType: 'blob',
  });
  return data;
}

export async function previewScript(payload: GenerateScriptRequest): Promise<ScriptPreviewResponse> {
  const { data } = await api.post('/scans/generate-script/preview', payload);
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

// ── Module 8: Scans CRUD ─────────────────────────────────────

export async function getScans(params?: { mission_id?: number; target_id?: number; status?: string }): Promise<{ data: ScanDetail[]; total: number }> {
  const { data } = await api.get('/scans', { params });
  return data;
}

export async function getScan(id: number): Promise<ScanDetail> {
  const { data } = await api.get(`/scans/${id}`);
  return data.data;
}

export async function deleteScan(id: number): Promise<void> {
  await api.delete(`/scans/${id}`);
}

// ── Module 8: Findings ───────────────────────────────────────

export async function getScanFindings(scanId: number, params?: { status?: string; severity?: string }): Promise<{ data: Finding[]; total: number }> {
  const { data } = await api.get(`/scans/${scanId}/findings`, { params });
  return data;
}

export async function getFinding(id: number): Promise<Finding> {
  const { data } = await api.get(`/findings/${id}`);
  return data;
}

export async function updateFinding(id: number, payload: { auditor_notes?: string; auditor_override?: string }): Promise<Finding> {
  const { data } = await api.put(`/findings/${id}`, payload);
  return data;
}

export async function generateAIAdvice(findingId: number): Promise<{ advice: string; generated_at: string }> {
  const { data } = await api.post(`/findings/${findingId}/ai-advice`);
  return data;
}

// ── Module 8: Result Import ──────────────────────────────────

export async function importResults(scanId: number, file: File): Promise<ImportResultsResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post(`/scans/${scanId}/import-results`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function importWithNewScan(targetId: number, benchmarkId: number, file: File): Promise<ImportResultsResponse> {
  const formData = new FormData();
  formData.append('target_id', targetId.toString());
  formData.append('benchmark_id', benchmarkId.toString());
  formData.append('file', file);
  const { data } = await api.post('/scans/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

// ── Module 11: Report Generation ─────────────────────────────

export async function generateReport(payload: ReportGenerateRequest): Promise<Blob> {
  const { data } = await api.post('/reports/generate', payload, {
    responseType: 'blob',
  });
  return data;
}

export async function generateAISummary(payload: AISummaryRequest): Promise<AISummaryResponse> {
  const { data } = await api.post('/reports/ai-summary', payload);
  return data;
}

// ── Module 12: Post-Mission AI Analysis ──────────────────────

export async function runMissionAnalysis(missionId: number, payload: AnalysisRequest): Promise<MissionAnalysisResult> {
  const { data } = await api.post(`/missions/${missionId}/analyze`, payload);
  return data.data;
}

export async function getMissionAnalyses(missionId: number): Promise<{ data: MissionAnalysisResult[]; total: number }> {
  const { data } = await api.get(`/missions/${missionId}/analyses`);
  return data;
}

export async function getMissionAnalysis(missionId: number, analysisId: number): Promise<MissionAnalysisResult> {
  const { data } = await api.get(`/missions/${missionId}/analyses/${analysisId}`);
  return data.data;
}

export async function deleteMissionAnalysis(missionId: number, analysisId: number): Promise<void> {
  await api.delete(`/missions/${missionId}/analyses/${analysisId}`);
}

export async function getComparableMissions(clientId: number): Promise<ComparableMission[]> {
  const { data } = await api.get(`/clients/${clientId}/missions/comparable`);
  return data.data;
}

// ── Database Backup & Restore ────────────────────────────────

export async function createBackup(): Promise<Blob> {
  const { data } = await api.post('/settings/backup', null, {
    responseType: 'blob',
  });
  return data;
}

export async function restoreBackup(file: File): Promise<{ message: string; tables_restored: number }> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post('/settings/restore', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}
