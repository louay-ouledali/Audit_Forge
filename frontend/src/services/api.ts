import axios from 'axios';
import type { Client, Mission, Target, Settings, Benchmark, BenchmarkStatus, EnrichStatus, VerifyStatus, ValidateStatus, ValidationResultItem, Rule, RuleCommand, LLMStatus, LLMTestResult, CommandHistoryEntry, VerificationReport, GenerateScriptRequest, ScriptPreviewResponse, NetworkScanRequest, NetworkScanResponse, ScanStatus, ScanCancelResponse, ScanDetail, Finding, ImportResultsResponse, ReportGenerateRequest, AISummaryRequest, AISummaryResponse, AnalysisRequest, MissionAnalysisResult, ComparableMission, DiscoveredHost, DiscoveredHostEnriched, DiscoveryProgress, BuilderFindingsResponse, BuilderPreviewRequest, AutoGroupResponse, GroupSummaryRequest, GroupSummaryResponse, SavedReport, ConnectionTestResult, ScanReadiness, PrerequisiteGuide, BenchmarkMatchResult, ScanBatchRequest, ScanBatchResponse, ScanBatchStatus, BenchmarkCatalog, CustomBenchmarkCreate, AIRuleCreateRequest, AIRuleCreateResponse, RuleFullUpdate, RuleTestRequest, RuleTestResponse, RuleValidateRequest, MigrationReadiness, ScanComparison, FrameworkCoverage, FrameworkRulesResponse, BackupInfo, ADConnectionTestResult, ADDiscoverResponse, ADWinRMCheckResult, ADBulkCreateResult, BenchmarkVersionItem, BenchmarkGroupResponse, VersionDiffResponse, CacheAccelerationStats, ConnectSession, ConnectAgent, CopilotChatResponse, CopilotPendingRule, CopilotPipelineResult, CopilotAction } from '@/types';

const api = axios.create({
  baseURL: '/api',
});

export async function getHealth() {
  const { data } = await api.get('/health');
  return data;
}

export async function getDashboardStats(): Promise<{ clients: number; active_missions: number; benchmarks: number; scans: number; total_rules: number }> {
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
export async function getAllTargets(): Promise<Target[]> {
  const { data } = await api.get('/targets');
  return data.data;
}

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

// Version Groups & Diff
export async function getBenchmarkGroups(): Promise<{ data: BenchmarkGroupResponse[]; total: number }> {
  const { data } = await api.get('/benchmarks/groups');
  return data;
}

export async function getBenchmarkGroup(groupId: number): Promise<BenchmarkGroupResponse> {
  const { data } = await api.get(`/benchmarks/groups/${groupId}`);
  return data;
}

export async function getBenchmarkVersions(benchmarkId: number): Promise<{ versions: BenchmarkVersionItem[]; current_id: number; group_id?: number }> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/versions`);
  return data;
}

export async function getBenchmarkDiff(benchmarkId: number, otherId: number): Promise<VersionDiffResponse> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/diff/${otherId}`);
  return data;
}

export async function setBenchmarkBaseline(benchmarkId: number): Promise<{ message: string; benchmark_id: number }> {
  const { data } = await api.post(`/benchmarks/${benchmarkId}/set-baseline`);
  return data;
}

export async function getBenchmarkCacheStats(benchmarkId: number): Promise<CacheAccelerationStats> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/cache-stats`);
  return data;
}

// Phase 2: Custom Benchmark + AI Rule Creation
export async function createCustomBenchmark(payload: CustomBenchmarkCreate): Promise<{ benchmark_id: number; name: string; message: string }> {
  const { data } = await api.post('/benchmarks/create', payload);
  return data;
}

export async function createRuleWithAI(benchmarkId: number, payload: AIRuleCreateRequest): Promise<AIRuleCreateResponse> {
  const { data } = await api.post(`/benchmarks/${benchmarkId}/rules/create`, payload);
  return data;
}

export async function updateRuleFull(benchmarkId: number, ruleId: number, payload: RuleFullUpdate): Promise<Rule> {
  const { data } = await api.put(`/benchmarks/${benchmarkId}/rules/${ruleId}`, payload);
  return data.data;
}

export async function deleteRuleFromBenchmark(benchmarkId: number, ruleId: number): Promise<void> {
  await api.delete(`/benchmarks/${benchmarkId}/rules/${ruleId}`);
}

export async function bulkGenerateCommands(benchmarkId: number): Promise<{ message: string; total_rules: number; status: string }> {
  const { data } = await api.post(`/benchmarks/${benchmarkId}/generate-commands`);
  return data;
}

export async function exportBenchmarkFull(benchmarkId: number): Promise<Blob> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/export`, {
    responseType: 'blob',
  });
  return data;
}

export async function importBenchmarkFile(benchmarkId: number, file: File): Promise<{ message: string; rules_imported: number; commands_imported: number }> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post(`/benchmarks/${benchmarkId}/import-benchmark`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

// ── Phase 3: Rule Testing, Validation, Migration Readiness ──

export async function testRuleCommand(benchmarkId: number, ruleId: number, payload: RuleTestRequest): Promise<RuleTestResponse> {
  const { data } = await api.post(`/benchmarks/${benchmarkId}/rules/${ruleId}/test`, payload);
  return data;
}

export async function validateRuleCommand(benchmarkId: number, ruleId: number, payload: RuleValidateRequest): Promise<{ message: string; validation_status: string }> {
  const { data } = await api.post(`/benchmarks/${benchmarkId}/rules/${ruleId}/validate`, payload);
  return data;
}

export async function getMigrationReadiness(benchmarkId: number): Promise<MigrationReadiness> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/migration-readiness`);
  return data;
}

// Framework Coverage
export async function getFrameworkCoverage(benchmarkId: number): Promise<FrameworkCoverage> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/framework-coverage`);
  return data;
}

export async function getFrameworkRules(benchmarkId: number, frameworkKey: string): Promise<FrameworkRulesResponse> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/framework-coverage/${frameworkKey}/rules`);
  return data;
}

// Backups
export async function listBackups(): Promise<BackupInfo[]> {
  const { data } = await api.get('/settings/backups');
  return data;
}

export async function restoreFromBackup(filename: string): Promise<{ message: string }> {
  const { data } = await api.post(`/settings/backups/${filename}/restore`);
  return data;
}

export async function compareScans(scanAId: number, scanBId: number): Promise<ScanComparison> {
  const { data } = await api.get(`/scans/compare/${scanAId}/${scanBId}`);
  return data;
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

// AI Severity Classification
export interface SeverityEnrichResult {
  message: string;
  benchmark_id: number;
  rules_to_classify: number;
}

export interface SeverityEnrichStatus {
  benchmark_id: number;
  total_rules: number;
  medium_count: number;
  classified: number;
  severity_distribution: Record<string, number>;
}

export async function startSeverityEnrichment(benchmarkId: number): Promise<SeverityEnrichResult> {
  const { data } = await api.post(`/benchmarks/${benchmarkId}/enrich-severities`);
  return data;
}

export async function getSeverityEnrichStatus(benchmarkId: number): Promise<SeverityEnrichStatus> {
  const { data } = await api.get(`/benchmarks/${benchmarkId}/enrich-severities/status`);
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

export async function startDiscoveryAsync(subnet: string, scanProfile?: string): Promise<{ discovery_id: string; status: string; engine: string }> {
  const payload: Record<string, unknown> = { subnet };
  if (scanProfile) payload.scan_profile = scanProfile;
  const { data } = await api.post('/scans/discover', payload);
  return data;
}

export async function getDiscoveryStatus(discoveryId: string): Promise<DiscoveryProgress> {
  const { data } = await api.get(`/scans/discover/${discoveryId}/status`);
  return data;
}

export async function cancelDiscovery(discoveryId: string): Promise<{ status: string }> {
  const { data } = await api.post(`/scans/discover/${discoveryId}/cancel`);
  return data;
}

export async function getDiscoveryResultsEnriched(discoveryId: string, missionId?: number): Promise<{ hosts: DiscoveredHostEnriched[]; total_scanned: number; engine?: string; status: string }> {
  const params: Record<string, unknown> = {};
  if (missionId) params.mission_id = missionId;
  const { data } = await api.get(`/scans/discover/${discoveryId}/results`, { params });
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
  const { data } = await api.get(`/scans/${scanId}/findings`, { params: { ...params, limit: 10000 } });
  return data;
}

export async function getFinding(id: number): Promise<Finding> {
  const { data } = await api.get(`/findings/${id}`);
  return data;
}

export async function updateFinding(id: number, payload: {
  auditor_notes?: string;
  auditor_override?: string;
  auditor_status_override?: string;
  auditor_severity_override?: string;
  auditor_description?: string;
  auditor_remediation?: string;
  override_reason?: string;
}): Promise<Finding> {
  const { data } = await api.put(`/findings/${id}`, payload);
  return data;
}

export async function generateAIAdvice(findingId: number, force = false): Promise<{ advice: string; generated_at: string }> {
  const { data } = await api.post(`/findings/${findingId}/ai-advice`, null, { params: force ? { force: true } : undefined });
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
  // Smart Import Phase 1 additions
  benchmark_reconstructed?: boolean;
  rules_matched?: number;
  rules_created?: number;
  fp_suspects?: number;
  migration_readiness?: number;
  import_record_id?: number | null;
  not_applicable?: number;
  warnings?: string[];
  // Severity enrichment
  enrichment_source?: string;
  enrichment_source_id?: number | null;
  rules_enriched?: number;
  commands_inherited?: number;
  severity_distribution?: Record<string, number>;
  findings_severity_updated?: number;
}

export interface SmartImportPreviewResponse {
  format: string;
  filename: string;
  platform?: string;
  platform_family?: string;
  os_version?: string;
  benchmark_name?: string;
  benchmark_version?: string;
  benchmark_exists?: boolean;
  existing_benchmark_id?: number | null;
  existing_benchmark_name?: string | null;
  hostname?: string;
  ip_address?: string;
  profile_level?: string;
  total_findings?: number;
  total_rules?: number;
  passed?: number;
  failed?: number;
  not_applicable?: number;
  errors?: number;
  scheme?: string;
  source_tool?: string;
  message?: string;
  // Unknown format fields
  is_unknown?: boolean;
  ai_parseable?: boolean;
}

export async function smartImportPreview(file: File, clientId?: number | null): Promise<SmartImportPreviewResponse> {
  const formData = new FormData();
  formData.append('file', file);
  if (clientId) formData.append('client_id', clientId.toString());
  const { data } = await api.post('/scans/smart-import/preview', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function smartImport(
  file: File,
  missionId?: number | null,
  clientId?: number | null,
  options?: {
    targetId?: number | null;
    runFpDetection?: boolean;
    allowBenchmarkCreation?: boolean;
  },
): Promise<SmartImportResponse> {
  const formData = new FormData();
  formData.append('file', file);
  if (missionId) formData.append('mission_id', missionId.toString());
  if (clientId) formData.append('client_id', clientId.toString());
  if (options?.targetId) formData.append('target_id', options.targetId.toString());
  if (options?.runFpDetection !== undefined) formData.append('run_fp_detection', String(options.runFpDetection));
  if (options?.allowBenchmarkCreation !== undefined) formData.append('allow_benchmark_creation', String(options.allowBenchmarkCreation));
  const { data } = await api.post('/scans/smart-import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

// ── Unknown Benchmark Import (AI reverse engineering) ────────

export interface UnknownImportPlatformDetection {
  platform: string;
  platform_family: string;
  confidence: number;
  reasoning: string;
  benchmark_title: string;
  version: string;
}

export interface UnknownImportExtractedRule {
  section_number: string;
  title: string;
  description: string;
  severity: string;
  has_cache_match: boolean;
  cache_confidence: number;
}

export interface UnknownImportResult {
  job_id: string;
  status: string;
  platform_detection: UnknownImportPlatformDetection | null;
  extracted_rules: UnknownImportExtractedRule[];
  total_rules: number;
  cache_matches: number;
  cache_match_percent: number;
  error: string | null;
}

export interface UnknownImportConfirmResponse {
  message: string;
  benchmark_id: number;
  benchmark_name: string;
  total_rules: number;
  commands_auto_imported: number;
  commands_flagged: number;
}

export async function startUnknownImport(file: File): Promise<UnknownImportResult> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post('/benchmarks/import/unknown', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function getUnknownImportStatus(jobId: string): Promise<UnknownImportResult> {
  const { data } = await api.get(`/benchmarks/import/unknown/status/${jobId}`);
  return data;
}

export async function confirmUnknownImport(payload: {
  job_id: string;
  platform: string;
  platform_family?: string;
  benchmark_title?: string;
  version?: string;
}): Promise<UnknownImportConfirmResponse> {
  const { data } = await api.post('/benchmarks/import/unknown/confirm', payload);
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

export function getScriptDownloadUrl(filename: string): string {
  return `${api.defaults.baseURL}/scripts/${encodeURIComponent(filename)}`;
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

export async function discoverNetworkEnhanced(subnet: string, missionId?: number, scanProfile?: string): Promise<{ hosts: DiscoveredHostEnriched[]; total_scanned: number; engine?: string }> {
  const payload: Record<string, unknown> = { subnet };
  if (missionId) payload.mission_id = missionId;
  if (scanProfile) payload.scan_profile = scanProfile;
  const { data } = await api.post('/scans/discover/scan', payload);
  return data;
}

export async function getDiscoverProfiles(): Promise<{ engine: string; profiles: Record<string, { label: string; description: string }> }> {
  const { data } = await api.get('/scans/discover/profiles');
  return data;
}

export async function getAgentStatus(): Promise<{ engine: string; available: boolean; detail: string }> {
  const { data } = await api.get('/scans/discover/agent-status');
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

// ── AD Discovery ─────────────────────────────────────────────

export async function adTestConnection(payload: {
  client_id: number;
  dc_host?: string;
  domain?: string;
  username?: string;
  password?: string;
  use_ssl?: boolean;
}): Promise<ADConnectionTestResult> {
  const { data } = await api.post('/ad/test-connection', payload);
  return data;
}

export async function adDiscover(payload: {
  client_id: number;
  dc_host?: string;
  domain?: string;
  username?: string;
  password?: string;
  use_ssl?: boolean;
  ou_filter?: string;
  resolve_dns?: boolean;
}): Promise<ADDiscoverResponse> {
  const { data } = await api.post('/ad/discover', payload);
  return data;
}

export async function adCheckWinRM(hosts: string[], timeout?: number): Promise<{
  results: ADWinRMCheckResult[];
  total: number;
  available: number;
}> {
  const { data } = await api.post('/ad/check-winrm', { hosts, timeout });
  return data;
}

export async function adEnableWinRM(clientId: number, targetHosts: string[]): Promise<{
  results: { host: string; success: boolean; method: string; error?: string; script?: string }[];
  total: number;
  successes: number;
  fallback_script: string | null;
}> {
  const { data } = await api.post('/ad/enable-winrm', { client_id: clientId, target_hosts: targetHosts });
  return data;
}

export async function adBulkCreateTargets(payload: {
  client_id: number;
  mission_id: number;
  computers: Record<string, unknown>[];
  auto_scan?: boolean;
}): Promise<ADBulkCreateResult> {
  const { data } = await api.post('/ad/bulk-create-targets', payload);
  return data;
}

export async function adGenerateWinRMScript(clientId: number, targetHosts: string[]): Promise<{ script: string }> {
  const { data } = await api.post('/ad/generate-winrm-script', { client_id: clientId, target_hosts: targetHosts });
  return data;
}

// ── AuditForge Connect ──────────────────────────────────────────

export async function createConnectSession(payload: {
  client_id: number;
  mission_id?: number;
  expires_in_hours?: number;
  max_agent_lifetime_seconds?: number;
  notes?: string;
}): Promise<ConnectSession> {
  const { data } = await api.post('/connect/sessions', payload);
  return data.data;
}

export async function getConnectSessions(clientId?: number, missionId?: number): Promise<ConnectSession[]> {
  const params: Record<string, number> = {};
  if (clientId) params.client_id = clientId;
  if (missionId) params.mission_id = missionId;
  const { data } = await api.get('/connect/sessions', { params });
  return data.data;
}

export async function getConnectSession(sessionId: number): Promise<ConnectSession> {
  const { data } = await api.get(`/connect/sessions/${sessionId}`);
  return data.data;
}

export async function terminateConnectSession(sessionId: number): Promise<void> {
  await api.delete(`/connect/sessions/${sessionId}`);
}

export async function validateEnrollmentCode(code: string): Promise<{
  valid: boolean;
  session_id: number | null;
  client_name: string | null;
  expires_at: string | null;
}> {
  const { data } = await api.get(`/connect/portal/${code}`);
  return data.data;
}

export async function getConnectAgents(sessionId: number): Promise<ConnectAgent[]> {
  const { data } = await api.get(`/connect/sessions/${sessionId}/agents`);
  return data.data;
}

export async function startAgentScan(sessionId: number, benchmarkId: number, agentIds?: number[]): Promise<{ scan_ids: number[] }> {
  const { data } = await api.post(`/connect/sessions/${sessionId}/scan`, {
    benchmark_id: benchmarkId,
    agent_ids: agentIds || null,
  });
  return data.data;
}

export function getAgentScriptUrl(code: string, platform: 'windows' | 'linux'): string {
  // Pass the browser's hostname so the backend bakes the correct server_host into the agent script
  const host = window.location.hostname;
  return `/api/connect/agent/${code}/${platform}?host=${encodeURIComponent(host)}`;
}

export function getEnableScriptUrl(code: string, platform: 'windows' | 'linux'): string {
  return `/api/connect/portal/${code}/enable-script/${platform}`;
}

export function getUsbScriptUrl(code: string, platform: 'windows' | 'linux'): string {
  return `/api/connect/portal/${code}/usb-script/${platform}`;
}

// ── Forge Copilot ──────────────────────────────────────────
// Types re-exported from @/types
export type { CopilotChatResponse, CopilotPendingRule, CopilotPipelineResult, CopilotAction };

export async function copilotChat(benchmarkId: number, message: string, conversationId?: string, signal?: AbortSignal): Promise<CopilotChatResponse> {
  const { data } = await api.post(`/copilot/${benchmarkId}/chat`, { message, conversation_id: conversationId }, { signal });
  return data;
}

export async function copilotGenerateBenchmark(benchmarkId: number, description: string, platform?: string, platformFamily?: string, signal?: AbortSignal): Promise<CopilotPipelineResult> {
  const { data } = await api.post(`/copilot/${benchmarkId}/generate-benchmark`, {
    description,
    platform: platform || undefined,
    platform_family: platformFamily || undefined,
  }, { signal });
  return data;
}

export async function copilotApprove(benchmarkId: number, ruleIds: number[], action: 'approve' | 'reject'): Promise<{ approved?: number; rejected?: number }> {
  const { data } = await api.post(`/copilot/${benchmarkId}/approve`, { rule_ids: ruleIds, action });
  return data;
}

export async function copilotApproveWithEdits(benchmarkId: number, ruleId: number, edits: Record<string, string>): Promise<any> {
  const { data } = await api.post(`/copilot/${benchmarkId}/approve-with-edits`, { rule_id: ruleId, edits, action: 'approve' });
  return data;
}

export async function copilotGetPending(benchmarkId: number): Promise<{ count: number; rules: CopilotPendingRule[] }> {
  const { data } = await api.get(`/copilot/${benchmarkId}/pending`);
  return data;
}

export async function copilotConfirmBatchEdit(benchmarkId: number, ruleIds: number[], fieldName: string, newValue: string, confirmed: boolean): Promise<any> {
  const { data } = await api.post(`/copilot/${benchmarkId}/confirm-batch-edit`, {
    rule_ids: ruleIds,
    field_name: fieldName,
    new_value: newValue,
    confirmed,
  });
  return data;
}
