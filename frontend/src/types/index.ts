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
  // Lock info
  is_locked: boolean;
  locked_at: string | null;
  locked_by: string | null;
}

export interface Target {
  id: number;
  client_id: number;
  hostname: string | null;
  ip_address: string | null;
  mac_address: string | null;
  target_type: string;
  os_details: string | null;
  connection_method: string | null;
  ssh_username: string | null;
  ssh_key_path: string | null;
  ssh_password?: string | null;
  port: number | null;
  notes: string | null;
  created_at: string;
  // Phase 1 enrichment fields
  platform_subtype: string | null;
  default_benchmark_id: number | null;
  connection_status: 'ok' | 'failed' | 'untested' | null;
  connection_error: string | null;
  last_connection_test: string | null;
  db_name: string | null;
  db_instance: string | null;
  has_enable_password: boolean;
  device_type: string | null;
  // Computed fields from API
  last_scan_compliance: number | null;
  last_scan_date: string | null;
  scan_count: number;
  default_benchmark_name: string | null;
}

// ── Target Connection & Readiness types ──────────────────────

export interface ConnectionTestResult {
  target_id: number;
  status: 'ok' | 'failed';
  message: string;
  response_time_ms: number | null;
  connection_method: string | null;
  error_details: string | null;
}

export interface ScanReadinessCheck {
  check: string;
  status: 'ok' | 'warning' | 'error';
  message: string;
}

export interface ScanReadiness {
  target_id: number;
  ready: boolean;
  checks: ScanReadinessCheck[];
  blockers: string[];
  suggestions: string[];
}

export interface PrerequisiteStep {
  title: string;
  description: string;
  command: string | null;
  notes: string | null;
}

export interface PrerequisiteAlternative {
  method: string;
  description: string;
}

export interface PrerequisiteFallback {
  method: string;
  description: string;
  download_script: string | null;
}

export interface PrerequisiteGuide {
  platform: string;
  connection_method: string;
  download_script: string | null;
  steps: PrerequisiteStep[];
  alternative: PrerequisiteAlternative | null;
  fallback: PrerequisiteFallback | null;
}

export interface BenchmarkMatchResult {
  benchmark_id: number;
  benchmark_name: string;
  score: number;
  reason: string;
}

// ── Scan Batch types ─────────────────────────────────────────

export interface ScanBatchRequest {
  mission_id: number;
  target_ids?: number[] | null;
  benchmark_overrides?: Record<string, number> | null;
  skip_untestable?: boolean;
  concurrency?: number;
}

export interface ScanBatchItemResponse {
  id: number;
  target_id: number;
  target_hostname: string | null;
  target_ip: string | null;
  benchmark_id: number | null;
  benchmark_name: string | null;
  scan_id: number | null;
  status: string;
  skip_reason: string | null;
  error_message: string | null;
}

export interface ScanBatchResponse {
  batch_id: number;
  status: string;
  total_targets: number;
  scannable: number;
  skipped: number;
  items: ScanBatchItemResponse[];
}

export interface ScanBatchStatus {
  batch_id: number;
  status: string;
  total_targets: number;
  completed_targets: number;
  failed_targets: number;
  skipped_targets: number;
  items: ScanBatchItemResponse[];
}

export interface DiscoveredHostEnriched extends DiscoveredHost {
  already_added?: boolean;
  existing_target_id?: number | null;
  already_assigned?: boolean;
  suggested_benchmark?: string | null;
  suggested_benchmark_id?: number | null;
  match_method?: 'mac' | 'ip' | '';
}

// ── Target Enriched (client-side enrichment) ─────────────────

export interface TargetEnriched extends Target {
  isScanning: boolean;
  scanProgress?: ScanStatus;
  readiness?: ScanReadiness;
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
  phase3_status: string | null;
  is_ready: boolean;
  status: string;
  notes: string | null;
  // Smart Import Phase 1 additions
  is_editable?: boolean;
  parent_benchmark_id?: number | null;
  migration_readiness?: number | null;
  source?: string;
  source_details?: string | null;
}

// ── Benchmark Catalog (hierarchical classification) ──

export interface CatalogBenchmark {
  id: number;
  name: string;
  version: string;
  platform: string;
  platform_family: string;
  total_rules: number;
  phase1_status: string;
  phase2_status: string;
  verification_status: string;
  is_ready: boolean;
  source: string;
  import_date: string | null;
}

export interface ProductLine {
  name: string;
  icon: string;
  benchmarks: CatalogBenchmark[];
}

export interface CatalogVendor {
  name: string;
  icon: string;
  benchmark_count: number;
  product_lines: ProductLine[];
}

export interface CatalogCategory {
  name: string;
  icon: string;
  benchmark_count: number;
  vendors: CatalogVendor[];
}

export interface BenchmarkCatalog {
  categories: CatalogCategory[];
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
  template_matched: number;
  llm_generated: number;
  status: string;
}

// ── Phase 2: Custom Benchmark + AI Rule Creation ──

export interface CustomBenchmarkCreate {
  name: string;
  version?: string;
  platform?: string;
  platform_family?: string;
}

export interface AIRuleCreateRequest {
  section_number: string;
  title: string;
  description?: string;
  rationale?: string;
  severity?: string;
  profile_applicability?: string;
  generate_commands?: boolean;
}

export interface AIRuleCreateResponse {
  rule_id: number;
  section_number: string;
  title: string;
  commands_generated: boolean;
  message: string;
}

export interface RuleFullUpdate {
  title?: string;
  description?: string;
  rationale?: string;
  profile_applicability?: string;
  assessment_type?: string;
  default_value?: string;
  audit_description_raw?: string;
  remediation_description_raw?: string;
  severity?: string;
  enabled?: boolean;
}

// ── Phase 3: Rule Testing, Validation, Migration Readiness ──

export interface RuleTestRequest {
  target_id: number;
  timeout?: number;
}

export interface RuleTestResponse {
  rule_id: number;
  section_number: string;
  audit_command: string;
  stdout: string;
  stderr: string;
  exit_code: number;
  execution_time_ms: number;
  expected_output_regex: string | null;
  match_result: string;
  match_details: string | null;
}

export interface RuleValidateRequest {
  validation_status: string;
  notes?: string;
  corrected_command?: string;
  corrected_regex?: string;
}

export interface MigrationReadiness {
  benchmark_id: number;
  benchmark_name: string;
  total_rules: number;
  rules_with_commands: number;
  rules_validated: number;
  rules_generated: number;
  rules_no_command: number;
  rules_flagged: number;
  readiness_percentage: number;
  status: string;
}

export interface ScanComparisonItem {
  section_number: string;
  title: string;
  scan_a_status: string | null;
  scan_b_status: string | null;
  changed: boolean;
  severity: string | null;
}

export interface ScanComparison {
  scan_a_id: number;
  scan_b_id: number;
  scan_a_benchmark: string | null;
  scan_b_benchmark: string | null;
  scan_a_date: string | null;
  scan_b_date: string | null;
  total_rules_compared: number;
  rules_improved: number;
  rules_regressed: number;
  rules_unchanged: number;
  rules_new: number;
  rules_removed: number;
  items: ScanComparisonItem[];
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
  rationale: string | null;
  profile_applicability: string | null;
  assessment_type: string | null;
  default_value: string | null;
  audit_description_raw: string | null;
  remediation_description_raw: string | null;
  severity: string;
  enabled: boolean;
  tags: RuleTag[];
  // Smart Import Phase 1 additions
  source?: string | null;
  framework_mappings?: string | null;
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

export interface DiscoveredHost {
  ip: string;
  hostname: string;
  open_ports: { port: number; service: string; platform_hint: string }[];
  os_guess: string;
  connection_methods: string[];
  os_version: string;
  vendor: string;
  banners: Record<number, string>;
  device_model: string;
  firmware: string;
  mac_address: string;
  domain: string;
  detection_method: string;
  confidence: number;
  first_seen?: string | null;
  last_seen?: string | null;
  is_new?: boolean;
}

export interface DiscoveryProgress {
  id: string;
  status: string;
  total: number;
  scanned: number;
  found: number;
  hosts?: DiscoveredHost[];
  error?: string;
}

export interface NetworkScanRequest {
  target_id: number;
  benchmark_id: number;
  mission_id?: number | null;
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
  error_message?: string;
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
  mission_id: number | null;
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
  // Enriched naming fields
  benchmark_name?: string | null;
  benchmark_version?: string | null;
  target_hostname?: string | null;
  target_ip?: string | null;
  mission_name?: string | null;
  client_name?: string | null;
}

export interface Finding {
  id: number;
  scan_id: number;
  rule_id: number;
  status: string;
  actual_output: string | null;
  expected_output: string | null;
  expected_output_display: string | null;
  evaluation_explanation: string | null;
  severity: string | null;
  ai_advice: string | null;
  ai_advice_generated_at: string | null;
  auditor_notes: string | null;
  auditor_override: string | null;
  created_at: string | null;
  section_number: string | null;
  rule_title: string | null;
  // Override fields
  auditor_status_override: string | null;
  auditor_severity_override: string | null;
  auditor_description: string | null;
  auditor_remediation: string | null;
  override_reason: string | null;
  overridden_at: string | null;
}

export interface SavedReport {
  id: number;
  mission_id: number;
  title: string;
  format: string;
  config_json: Record<string, unknown> | null;
  created_at: string | null;
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
  excluded_rule_ids?: number[];
  groups?: RuleGroup[];
  audience?: string;
  sections?: Record<string, boolean>;
  group_summaries?: Record<string, string>;
}

export interface AISummaryRequest {
  scope: 'scan' | 'target' | 'mission' | 'custom';
  scope_id?: number;
  scan_ids?: number[];
}

export interface AISummaryResponse {
  summary: string;
}

// ── Report Builder types ─────────────────────────────────────

export interface BuilderFinding {
  finding_id: number;
  rule_id: number;
  scan_id: number;
  section_number: string;
  rule_title: string;
  description: string;
  severity: string;
  status: string;
  target_hostname: string;
  benchmark_name: string;
}

export interface BuilderFindingsResponse {
  data: BuilderFinding[];
  total: number;
}

export interface BuilderPreviewRequest {
  scan_ids: number[];
  excluded_rule_ids?: number[];
  include_passed_rules: boolean;
  title?: string;
  groups?: RuleGroup[];
  audience?: string;
  sections?: Record<string, boolean>;
  group_summaries?: Record<string, string>;
}

// ── Phase 2: Grouping & Audience ─────────────────────────────

export interface RuleGroup {
  name: string;
  rule_ids: number[];
}

export interface AutoGroupResponse {
  groups: RuleGroup[];
  total_rules: number;
  total_groups: number;
}

export interface GroupSummaryRequest {
  group_name: string;
  rule_ids: number[];
  scan_ids: number[];
  audience: string;
}

export interface GroupSummaryResponse {
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

// ── Phase 3: Validate & Correct types ────────────────────────

export interface ValidateStatus {
  status: string;
  total: number;
  processed: number;
  validated: number;
  corrected: number;
  flagged: number;
}

export interface ValidationCorrection {
  field: string;
  old_value: string;
  new_value: string;
  reason: string;
}

export interface ValidationResultItem {
  rule_command_id: number;
  rule_id: number;
  section_number: string;
  title: string;
  validation_status: string | null;
  validation_confidence: string | null;
  corrections: ValidationCorrection[];
  notes: string | null;
  audit_command: string | null;
  expected_output_regex: string | null;
}

// ── Phase 4: Framework Coverage + Platform Expansion ─────────

export interface FrameworkCoverageItem {
  key: string;
  name: string;
  category: string;
  description: string;
  controls_mapped: number;
  rules_covered: number;
  coverage_percentage: number;
  sample_controls: string[];
}

export interface FrameworkCoverage {
  benchmark_id: number;
  benchmark_name: string;
  total_rules: number;
  rules_with_framework_mappings: number;
  overall_score: number;
  framework_count: number;
  frameworks: FrameworkCoverageItem[];
}

export interface FrameworkRuleItem {
  rule_id: number;
  section_number: string;
  title: string;
  severity: string;
  controls: string[];
}

export interface FrameworkRulesResponse {
  benchmark_id: number;
  framework_key: string;
  framework_name: string;
  rules: FrameworkRuleItem[];
  total: number;
}

export interface BackupInfo {
  filename: string;
  size_mb: number;
  created_at: string;
}
