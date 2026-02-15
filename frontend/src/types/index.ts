export interface Client {
  id: number;
  name: string;
  industry: string | null;
  contact_name: string | null;
  contact_email: string | null;
  notes: string | null;
  created_at: string;
  mission_count: number;
}

export interface Mission {
  id: number;
  client_id: number;
  name: string;
  description: string | null;
  start_date: string | null;
  end_date: string | null;
  status: string;
  notes: string | null;
  created_at: string;
  target_count: number;
  client_name?: string | null;
}

export interface Target {
  id: number;
  mission_id: number;
  hostname: string | null;
  ip_address: string | null;
  target_type: string;
  os_details: string | null;
  connection_method: string | null;
  ssh_username: string | null;
  ssh_key_path: string | null;
  port: number | null;
  notes: string | null;
  created_at: string;
}

export interface Settings {
  [key: string]: string;
}

export interface Benchmark {
  id: number;
  name: string;
  version: string;
  platform: string;
  platform_family: string;
  import_date: string | null;
  pdf_filename: string | null;
  total_rules: number;
  phase1_status: string;
  phase2_status: string;
  verification_status: string;
  is_ready: boolean;
  status: string;
  notes: string | null;
}

export interface BenchmarkStatus {
  id: number;
  phase1_status: string;
  phase2_status: string;
  verification_status: string;
  is_ready: boolean;
  total_rules: number;
}

export interface EnrichStatus {
  total: number;
  processed: number;
  status: string;
}

export interface VerifyStatus {
  status: string;
  total: number;
  passed: number;
  failed: number;
}

export interface Rule {
  id: number;
  benchmark_id: number;
  section_number: string;
  title: string;
  description: string | null;
  severity: string;
  assessment_type: string | null;
  enabled: boolean;
  tags: RuleTag[];
}

export interface RuleTag {
  id: number;
  tag_id: string;
  source: string;
}

export interface RuleCommand {
  id: number;
  rule_id: number;
  audit_command: string | null;
  expected_output_regex: string | null;
  expected_output_description: string | null;
  remediation_command: string | null;
  remediation_description: string | null;
  status: string;
  source: string;
  is_protected: boolean;
  protection_reason: string | null;
  protected_at: string | null;
  verified_at: string | null;
  verification_notes: string | null;
  flagged_at: string | null;
  flag_reason: string | null;
  regeneration_count: number;
  last_regenerated_at: string | null;
}

export interface CommandHistoryEntry {
  audit_command: string | null;
  expected_output_regex: string | null;
  flag_reason: string | null;
  source: string | null;
  timestamp: string | null;
}

export interface VerificationReport {
  id: number;
  rule_command_id: number;
  level: string;
  result: string;
  message: string | null;
  details: string | null;
  auto_fixable: boolean;
  run_at: string | null;
}

export interface LLMStatus {
  available: boolean;
  mode: string;
  model: string;
  error: string | null;
}

export interface LLMTestResult {
  success: boolean;
  response: string | null;
  response_time_ms: number;
  model?: string;
  error?: string;
}

// ── Script Export (USB) types ─────────────────────────────────

export interface GenerateScriptRequest {
  benchmark_id: number;
  target_id?: number | null;
  preset_id?: number | null;
  selected_rule_ids?: number[] | null;
  category_filter?: string[] | null;
  severity_filter?: string[] | null;
  profile_filter?: string | null;
}

export interface ScriptPreviewRule {
  id: number;
  section_number: string;
  title: string | null;
  severity: string | null;
}

export interface ScriptPreviewResponse {
  total_rules: number;
  rules: ScriptPreviewRule[];
}

// ── Network Scan types ───────────────────────────────────────

export interface NetworkScanRequest {
  target_id: number;
  benchmark_id: number;
  preset_id?: number | null;
  selected_rule_ids?: number[] | null;
  category_filter?: string[] | null;
  severity_filter?: string[] | null;
  profile_filter?: string | null;
}

export interface NetworkScanResponse {
  scan_id: number;
  status: string;
}

export interface ScanStatus {
  scan_id: number;
  status: string;
  progress: number;
  total: number;
  current_rule: string;
  passed: number;
  failed: number;
  errors: number;
  compliance_percentage: number;
}

export interface ScanCancelResponse {
  scan_id: number;
  status: string;
  message: string;
}

// ── Module 8: Findings & Import types ────────────────────────

export interface ScanDetail {
  id: number;
  target_id: number;
  benchmark_id: number;
  scan_mode: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  results_imported_at: string | null;
  total_rules_checked: number;
  passed: number;
  failed: number;
  errors: number;
  not_applicable: number;
  manual_review: number;
  compliance_percentage: number | null;
  notes: string | null;
  created_at: string | null;
}

export interface Finding {
  id: number;
  scan_id: number;
  rule_id: number;
  status: string;
  actual_output: string | null;
  expected_output: string | null;
  severity: string | null;
  ai_advice: string | null;
  ai_advice_generated_at: string | null;
  auditor_notes: string | null;
  auditor_override: string | null;
  created_at: string | null;
  section_number: string | null;
  rule_title: string | null;
}

export interface ImportResultsResponse {
  findings_created: number;
  passed: number;
  failed: number;
  errors: number;
  compliance_percentage: number;
  scan_id?: number;
}

// ── Module 11: Report Generation types ───────────────────────

export interface ReportGenerateRequest {
  scope: 'scan' | 'target' | 'mission' | 'custom';
  scope_id?: number;
  scan_ids?: number[];
  format: 'pdf' | 'excel' | 'csv' | 'html';
  include_ai_summary: boolean;
  include_passed_rules: boolean;
  title?: string;
}

export interface AISummaryRequest {
  scope: 'scan' | 'target' | 'mission';
  scope_id: number;
}

export interface AISummaryResponse {
  summary: string;
}

// ── Module 12: Post-Mission AI Analysis types ────────────────

export interface AnalysisRequest {
  analysis_type: 'cross_target' | 'cross_mission' | 'category_analysis';
  compare_mission_id?: number | null;
}

export interface MissionAnalysisResult {
  id: number;
  mission_id: number;
  analysis_type: string;
  compared_mission_id: number | null;
  result: Record<string, unknown>;
  llm_model_used: string | null;
  generated_at: string | null;
}

export interface ComparableMission {
  id: number;
  name: string;
  start_date: string | null;
  end_date: string | null;
  compliance: number | null;
}
