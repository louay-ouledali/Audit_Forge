import axios from 'axios';
import type { Client, Mission, Target, Settings, Benchmark, BenchmarkStatus, EnrichStatus, VerifyStatus, ValidateStatus, ValidationResultItem, Rule, RuleCommand, LLMStatus, LLMTestResult, CommandHistoryEntry, VerificationReport, GenerateScriptRequest, ScriptPreviewResponse, NetworkScanRequest, NetworkScanResponse, ScanStatus, ScanCancelResponse, ScanDetail, Finding, ImportResultsResponse, ReportGenerateRequest, AISummaryRequest, AISummaryResponse, AnalysisRequest, MissionAnalysisResult, ComparableMission, DiscoveredHost, DiscoveredHostEnriched, DiscoveryProgress, BuilderFindingsResponse, BuilderPreviewRequest, AutoGroupResponse, GroupSummaryRequest, GroupSummaryResponse, SavedReport, ConnectionTestResult, ScanReadiness, PrerequisiteGuide, BenchmarkMatchResult, ScanBatchRequest, ScanBatchResponse, ScanBatchStatus, BenchmarkCatalog } from '@/types';

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

// Mission Locking
export async function lockMission(missionId: number, password: string): Promise<Mission> {
  const { data } = await api.post(`/missions/${missionId}/lock`, { password });
  return data.data;
}

export async function unlockMission(missionId: number, password: string): Promise<Mission> {
  const { data } = await api.post(`/missions/${missionId}/unlock`, { password });
  return data.data;
}

export async function verifyMissionLock(missionId: number, password: string): Promise<{ valid: boolean; message: string }> {
  const { data } = await api.post(`/missions/${missionId}/verify-lock`, { password });
  return data;
}

// Targets
export async function getTargets(missionId: number): Promise<Target[]> {
  const { data } = await api.get(`/missions/${missionId}/targets`);
  return data.data;
}

export async function getClientTargets(clientId: number): Promise<Target[]> {
  const { data } = await api.get(`/clients/${clientId}/targets`);
  return data.data;
}

export async function assignTargetToMission(missionId: number, targetId: number): Promise<void> {
  await api.post(`/missions/${missionId}/targets/${targetId}`);
}

export async function unassignTargetFromMission(missionId: number, targetId: number): Promise<void> {
  await api.delete(`/missions/${missionId}/targets/${targetId}`);
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

export async function getBenchmarkCatalog(): Promise<BenchmarkCatalog> {
  const { data } = await api.get('/benchmarks/catalog');
  return data;
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

// Phase 3: Validate & Correct (optional)
export async function startValidation(benchmarkId: number): Promise<void> {
  await api.post(`/benchmarks/${benchmarkId}/validate`);
}

export async function pauseValidation(benchmarkId: number): Promise<void> {
  await api.post(`/benchmarks/${benchmarkId}/validate/pause`);
}

export async function getValidationStatus(benchmarkId: number): Promise<ValidateStatus> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/validate/status`);
  return data;
}

export async function getValidationResults(
  benchmarkId: number,
  params?: { status_filter?: string },
): Promise<{ data: ValidationResultItem[]; total: number }> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/validate/results`, { params });
  return data;
}

export async function applyCorrection(benchmarkId: number, ruleCommandId: number): Promise<void> {
  await api.post(`/benchmarks/${benchmarkId}/validate/apply/${ruleCommandId}`);
}

export async function dismissCorrection(benchmarkId: number, ruleCommandId: number): Promise<void> {
  await api.post(`/benchmarks/${benchmarkId}/validate/dismiss/${ruleCommandId}`);
}

export async function bulkApplyCorrections(benchmarkId: number): Promise<{ message: string; count: number }> {
  const { data } = await api.post(`/benchmarks/${benchmarkId}/validate/bulk-apply`);
  return data;
}

export async function bulkDismissCorrections(benchmarkId: number): Promise<{ message: string; count: number }> {
  const { data } = await api.post(`/benchmarks/${benchmarkId}/validate/bulk-dismiss`);
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

export async function testLLM(): Promise<LLMTestResult> {
  const { data } = await api.post('/llm/test');
  return data;
}

// LLM Cache
export async function getCacheStats(): Promise<{ total_entries: number; total_hits: number }> {
  const { data } = await api.get('/llm/cache/stats');
  return data;
}

export async function clearLLMCache(task?: string): Promise<{ deleted: number }> {
  const params = task ? { task } : {};
  const { data } = await api.delete('/llm/cache', { params });
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

// Network Discovery
export async function discoverNetwork(subnet: string): Promise<{ hosts: DiscoveredHost[]; total_scanned: number }> {
  const { data } = await api.post('/scans/discover/scan', { subnet });
  return data;
}

export async function startDiscoveryAsync(subnet: string): Promise<{ discovery_id: string; status: string }> {
  const { data } = await api.post('/scans/discover', { subnet });
  return data;
}

export async function getDiscoveryStatus(discoveryId: string): Promise<DiscoveryProgress> {
  const { data } = await api.get(`/scans/discover/${discoveryId}/status`);
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

export async function importWithNewScan(targetId: number, benchmarkId: number, file: File, missionId?: number | null): Promise<ImportResultsResponse> {
  const formData = new FormData();
  formData.append('target_id', targetId.toString());
  formData.append('benchmark_id', benchmarkId.toString());
  if (missionId) formData.append('mission_id', missionId.toString());
  formData.append('file', file);
  const { data } = await api.post('/scans/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export interface SmartImportResponse extends ImportResultsResponse {
  target_id: number;
  target_hostname: string | null;
  target_ip: string | null;
  benchmark_id: number;
  benchmark_name: string;
  target_created: boolean;
}

export async function smartImport(file: File, missionId?: number | null, clientId?: number | null): Promise<SmartImportResponse> {
  const formData = new FormData();
  formData.append('file', file);
  if (missionId) formData.append('mission_id', missionId.toString());
  if (clientId) formData.append('client_id', clientId.toString());
  const { data } = await api.post('/scans/smart-import', formData, {
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

// ── Report Builder ───────────────────────────────────────────

export async function getBuilderFindings(scanIds: number[]): Promise<BuilderFindingsResponse> {
  const { data } = await api.post('/reports/builder/findings', { scan_ids: scanIds });
  return data;
}

export async function getBuilderPreview(payload: BuilderPreviewRequest): Promise<string> {
  const { data } = await api.post('/reports/builder/preview', payload, {
    responseType: 'text',
    headers: { Accept: 'text/html' },
  });
  return data;
}

export async function autoGroupRules(scanIds: number[], excludedRuleIds?: number[]): Promise<AutoGroupResponse> {
  const { data } = await api.post('/reports/builder/auto-group', {
    scan_ids: scanIds,
    excluded_rule_ids: excludedRuleIds,
  });
  return data;
}

export async function getGroupSummary(payload: GroupSummaryRequest): Promise<GroupSummaryResponse> {
  const { data } = await api.post('/reports/builder/group-summary', payload);
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

// ── Target Connection & Readiness ────────────────────────────

export async function testTargetConnection(targetId: number): Promise<ConnectionTestResult> {
  const { data } = await api.post(`/targets/${targetId}/test-connection`);
  return data;
}

export async function getTargetScanReadiness(targetId: number): Promise<ScanReadiness> {
  const { data } = await api.get(`/targets/${targetId}/scan-readiness`);
  return data;
}

export async function getTargetPrerequisites(targetId: number): Promise<PrerequisiteGuide> {
  const { data } = await api.get(`/targets/${targetId}/prerequisites`);
  return data;
}

export async function matchTargetBenchmark(targetId: number): Promise<BenchmarkMatchResult[]> {
  const { data } = await api.post(`/targets/${targetId}/benchmark-match`);
  return data.matches;
}

export async function getTargetLastScan(targetId: number): Promise<ScanDetail | null> {
  try {
    const { data } = await api.get(`/targets/${targetId}/last-scan`);
    return data.data || null;
  } catch {
    return null;
  }
}

// ── Scan Batch Operations ────────────────────────────────────

export async function startScanBatch(payload: ScanBatchRequest): Promise<ScanBatchResponse> {
  const { data } = await api.post('/scans/batch', payload);
  return data;
}

export async function getScanBatchStatus(batchId: number): Promise<ScanBatchStatus> {
  const { data } = await api.get(`/scans/batch/${batchId}/status`);
  return data;
}

export async function cancelScanBatch(batchId: number): Promise<void> {
  await api.post(`/scans/batch/${batchId}/cancel`);
}

// ── Enhanced Discovery (with mission context) ────────────────

export async function discoverNetworkEnhanced(subnet: string, missionId?: number): Promise<{ hosts: DiscoveredHostEnriched[]; total_scanned: number }> {
  const payload: Record<string, unknown> = { subnet };
  if (missionId) payload.mission_id = missionId;
  const { data } = await api.post('/scans/discover/scan', payload);
  return data;
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

// ── Saved Reports ────────────────────────────────────────────

export async function getSavedReports(missionId?: number): Promise<SavedReport[]> {
  const params = missionId ? { mission_id: missionId } : {};
  const { data } = await api.get('/saved-reports', { params });
  return data.data;
}

export async function createSavedReport(payload: { mission_id: number; title: string; format: string; config_json?: Record<string, unknown> }): Promise<SavedReport> {
  const { data } = await api.post('/saved-reports', payload);
  return data.data;
}

export async function deleteSavedReport(id: number): Promise<void> {
  await api.delete(`/saved-reports/${id}`);
}
