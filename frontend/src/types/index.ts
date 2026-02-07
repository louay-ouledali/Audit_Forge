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
