"""
Central registry of all LLM prompt templates used by AditForge.
Naming convention: {MODULE}_{PURPOSE}
"""

PHASE1_METADATA_DETECTION = """
You are analyzing a CIS Benchmark PDF. Based on the following text extracted
from the first pages of the document, identify:

1. title: The full benchmark name (e.g., "CIS Ubuntu Linux 22.04 LTS Benchmark")
2. version: The version number (e.g., "v2.0.0")
3. platform: A snake_case identifier for this specific platform
   (e.g., "linux_ubuntu_2204", "windows_11", "cisco_ios_17", "oracle_19c")
4. platform_family: One of: "linux", "windows", "network", "database", "mobile",
   "container", "cloud", "other"
5. profiles: Array of profile names found in the benchmark
   (e.g., ["Level 1 - Server", "Level 2 - Server", "Level 1 - Workstation"])

Return ONLY a valid JSON object with these 5 keys. No other text.

--- BEGIN TEXT ---
{first_pages_text}
--- END TEXT ---
"""

PHASE1_RULE_EXTRACTION = """
You are a CIS Benchmark parser. Your job is to extract structured rule data
from CIS benchmark PDF content.

For each auditable rule found in the section below, extract:

1. section: The section number exactly as written (e.g., "5.2.4")
2. title: The rule title exactly as written
3. description: The description/overview text
4. rationale: The rationale text explaining why this matters
5. profile_applicability: Array of profiles this applies to
6. assessment_type: "automated" or "manual"
7. audit_description_raw: The audit/assessment instructions EXACTLY as written
   in the PDF. Copy the text faithfully. Do NOT modify, interpret, or generate commands.
8. remediation_description_raw: The remediation instructions EXACTLY as written
   in the PDF. Copy faithfully. Do NOT modify.
9. default_value: The default value if mentioned, or null
10. references: Array of reference IDs (CCE, NIST, etc.)
11. severity: Estimate: "critical", "high", "medium", or "low"
{category_instruction}

IMPORTANT:
- Extract text FAITHFULLY. Do NOT generate or interpret commands.
- If a section has no auditable rules (just intro text), return an empty array.
- Return ONLY a valid JSON array of rule objects. No other text.

--- BEGIN SECTION ---
{pdf_section_text}
--- END SECTION ---
"""

PHASE1_CATEGORY_INSTRUCTION = """
12. categories: Array of functional categories this rule belongs to. Choose from:
    - "password_policy": password strength, history, expiration, complexity, lockout
    - "user_accounts": user management, root/admin access, sudo, service accounts
    - "ssh_configuration": SSH server/client hardening
    - "network_security": firewall, IP forwarding, network parameters, protocols
    - "filesystem_permissions": file permissions, ownership, mount options
    - "audit_logging": system auditing, log configuration, log integrity
    - "service_hardening": disabling/securing unnecessary services
    - "encryption_tls": encryption at rest/transit, TLS, certificates
    - "patch_updates": system updates, package manager security
    - "database_security": DB-specific auth, authorization, audit
    - "network_device": router/switch configs, ACLs, management plane
    A rule can belong to multiple categories. If unsure, return an empty array.
"""

PHASE1_CATEGORY_INSTRUCTION_DISABLED = """
12. categories: Return an empty array []. Category detection will be handled separately.
"""

PHASE2_COMMAND_GENERATION = """
You are a cybersecurity auditor and system administrator expert.

Platform: {platform} ({platform_family})

For each of the following CIS benchmark rules, generate the exact commands
needed to audit compliance on the target system.

For each rule, provide:

1. audit_command: The exact command to run on the target system.
   - For Linux targets: bash commands
   - For Windows targets: PowerShell commands
   - For Cisco IOS: IOS CLI commands (privileged EXEC, NOT config mode)
   - For Juniper: JunOS operational mode commands (NOT configuration mode)
   - For Fortinet: FortiOS CLI commands (NOT config mode)
   - For PostgreSQL: SQL queries (SELECT/SHOW only)
   - For Oracle: SQL queries (SELECT from v$ and dba_ views only)
   - For MSSQL: T-SQL queries (SELECT/EXEC sp_configure only)
   - For other platforms: the most appropriate read-only check command

   CRITICAL: Commands MUST be READ-ONLY. NEVER modify the system.
   No writes, installs, service changes, file modifications, or configuration changes.
   Commands must be non-interactive (no prompts or user input).
   Commands should handle errors gracefully (2>/dev/null, || true, -ErrorAction SilentlyContinue).

2. expected_output_regex: A Python-compatible regex (used with re.search()) that
   matches the COMPLIANT output. If the regex matches, the rule PASSES.

3. expected_output_description: Short human-readable description of compliant output.

4. remediation_command: Command to fix the misconfiguration (advisory only, never auto-executed).

5. remediation_description: Step-by-step human-readable fix instructions.

RULES TO PROCESS:
{rules_json}

Return ONLY a valid JSON array with one object per rule, in the same order.
Each object: audit_command, expected_output_regex, expected_output_description,
remediation_command, remediation_description.
"""

ANALYSIS_CROSS_TARGET = """
You are analyzing configuration audit results from multiple targets within
the same organization.

MISSION: {mission_name}
CLIENT: {client_name}

TARGETS AND THEIR FINDINGS:
{targets_findings}

Analyze the findings and identify:

1. SYSTEMIC ISSUES: Misconfigurations that appear across multiple targets.
   Group them and explain the likely root cause (e.g., shared Group Policy,
   common deployment template, shared configuration management).

2. OUTLIERS: Targets that are significantly less compliant than others.
   Highlight what makes them different.

3. CRITICAL RISK CHAINS: Combinations of misconfigurations across different
   targets that together create a higher risk than individually.
   (e.g., weak SSH config on a jump host + permissive firewall on internal servers)

4. PRIORITIZED REMEDIATION PLAN: Suggest the order in which the client should
   fix issues, considering:
   - Impact (severity x number of affected targets)
   - Effort (easy quick wins vs. complex changes)
   - Dependencies (fix X before Y)

Return ONLY a valid JSON object with these keys:
{{
  "systemic_issues": [
    {{
      "title": "...",
      "affected_targets": ["hostname1", "hostname2"],
      "affected_rules": ["5.2.4", "5.2.5"],
      "likely_cause": "...",
      "severity": "high",
      "recommendation": "..."
    }}
  ],
  "outliers": [
    {{
      "target": "hostname",
      "compliance": 45.2,
      "average_compliance": 72.1,
      "notable_gaps": ["...", "..."],
      "recommendation": "..."
    }}
  ],
  "risk_chains": [
    {{
      "title": "...",
      "description": "...",
      "involved_targets": ["...", "..."],
      "involved_rules": ["...", "..."],
      "combined_risk": "critical",
      "recommendation": "..."
    }}
  ],
  "remediation_plan": [
    {{
      "priority": 1,
      "action": "...",
      "targets": ["..."],
      "rules": ["..."],
      "effort": "low",
      "impact": "high",
      "rationale": "..."
    }}
  ]
}}
"""

ANALYSIS_CROSS_MISSION = """
You are comparing configuration audit results between two audit engagements
for the same client.

CLIENT: {client_name}

PREVIOUS MISSION: {previous_mission_name} ({previous_date})
  Overall Compliance: {previous_compliance}%
  Findings: {previous_critical} critical, {previous_high} high,
            {previous_medium} medium, {previous_low} low

CURRENT MISSION: {current_mission_name} ({current_date})
  Overall Compliance: {current_compliance}%
  Findings: {current_critical} critical, {current_high} high,
            {current_medium} medium, {current_low} low

CHANGES IN DETAIL:
Rules that improved (FAIL -> PASS): {rules_improved}
Rules that regressed (PASS -> FAIL): {rules_regressed}
Rules still failing: {rules_still_failing}
New targets: {new_targets}
Removed targets: {removed_targets}

Analyze and provide:

1. IMPROVEMENT SUMMARY: What got better, quantified
2. REGRESSION ALERTS: What got worse, with severity assessment
3. PERSISTENT ISSUES: Critical/high findings that remain unfixed — flag these strongly
4. NEW RISKS: Issues introduced since the last audit
5. TREND ASSESSMENT: Is the client's security posture improving overall?
6. RECOMMENDATIONS: What should the client focus on before the next audit

Return ONLY a valid JSON object with these keys:
{{
  "improvement_summary": {{ "description": "...", "improved_count": 0, "details": ["..."] }},
  "regression_alerts": [{{ "rule": "...", "severity": "...", "description": "..." }}],
  "persistent_issues": [{{ "rule": "...", "severity": "...", "description": "..." }}],
  "new_risks": [{{ "rule": "...", "severity": "...", "description": "..." }}],
  "trend_assessment": {{ "direction": "improving", "confidence": "high", "summary": "..." }},
  "recommendations": [{{ "priority": 1, "action": "...", "rationale": "..." }}]
}}
"""

ANALYSIS_CATEGORY = """
Analyze the following compliance scores by category for a client audit:

CLIENT: {client_name}
MISSION: {mission_name}

COMPLIANCE BY CATEGORY (across all targets):
{categories_data}

Provide:
1. STRENGTHS: Categories with high compliance — what the client is doing well
2. WEAKNESSES: Categories with low compliance — areas of concern
3. QUICK WINS: Categories where a small number of fixes would significantly improve the score
4. STRATEGIC RECOMMENDATIONS: High-level security program recommendations based on the pattern
   (e.g., "Consider implementing a centralized logging solution" if audit_logging is weak)

Return ONLY a valid JSON object with these keys:
{{
  "strengths": [{{ "category": "...", "compliance": 95.0, "description": "..." }}],
  "weaknesses": [{{ "category": "...", "compliance": 30.0, "description": "..." }}],
  "quick_wins": [{{ "category": "...", "current_compliance": 60.0, "potential_compliance": 85.0, "fix_count": 3, "description": "..." }}],
  "strategic_recommendations": [{{ "priority": 1, "recommendation": "...", "rationale": "...", "related_categories": ["..."] }}]
}}
"""

COMMAND_REGENERATION = """
A CIS benchmark audit command failed during execution. Generate a FIXED version.

RULE:
- Section: {section_number}
- Title: {title}
- Platform: {platform} ({platform_family})
- Assessment type: {assessment_type}
- CIS audit instructions: {audit_description_raw}
- CIS remediation instructions: {remediation_description_raw}

FAILED COMMAND: {current_audit_command}
EXPECTED REGEX: {current_expected_output_regex}

AUDITOR'S FLAG REASON: {flag_reason}

{error_section}
{system_info_section}
{history_section}

REQUIREMENTS:
1. READ-ONLY only — never modify the system
2. Must work on {platform}
3. Address the specific failure described
4. Do NOT repeat previously failed approaches
5. Non-interactive, handles errors gracefully

Return ONLY a valid JSON object:
{{
    "audit_command": "the fixed command",
    "expected_output_regex": "Python regex for compliant output",
    "expected_output_description": "what compliant output looks like",
    "remediation_command": "advisory fix command",
    "remediation_description": "how to fix",
    "explanation": "what was wrong and what you changed"
}}
"""
