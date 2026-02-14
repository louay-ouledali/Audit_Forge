"""
Central registry of all LLM prompt templates used by AditForge.
Naming convention: {MODULE}_{PURPOSE}
"""

PHASE1_METADATA_SYSTEM = """You extract CIS Benchmark metadata. Return a JSON object with exactly these keys:
title (string), version (string), platform (snake_case string), platform_family (one of: linux, windows, network, database, other), profiles (array of strings).
Example: {"title":"CIS Ubuntu 22.04 Benchmark","version":"v2.0.0","platform":"linux_ubuntu_2204","platform_family":"linux","profiles":["Level 1 - Server","Level 2 - Server"]}"""

PHASE1_METADATA_DETECTION = """Extract metadata as a JSON object from this CIS Benchmark text:

{first_pages_text}
"""

PHASE1_RULES_SYSTEM = """You extract CIS benchmark rules from PDF text. Return a JSON array of rule objects. If no rules found, return [].
Each rule object has keys: section (the section number like "5.2.4"), title (string), description (string), rationale (string), profile_applicability (array of strings), assessment_type ("automated" or "manual"), audit_description_raw (string, copied exactly from PDF), remediation_description_raw (string, copied exactly from PDF), default_value (string or null), references (array), severity ("critical","high","medium","low"), categories (array of strings).
{category_instruction}
The section field MUST contain the numeric section number (e.g. "1.1.1", "5.2.4"). Copy audit/remediation text EXACTLY. Do NOT invent commands."""

PHASE1_RULE_EXTRACTION = """Extract CIS benchmark rules as a JSON array from this text:

{pdf_section_text}
"""

PHASE1_CATEGORY_INSTRUCTION = """
For the "categories" field, choose from these values:
password_policy, user_accounts, ssh_configuration, network_security,
filesystem_permissions, audit_logging, service_hardening, encryption_tls,
patch_updates, database_security, network_device.
A rule can belong to multiple categories. If unsure, use an empty array [].
"""

PHASE1_CATEGORY_INSTRUCTION_DISABLED = """
For the "categories" field, always use an empty array [].
"""

PHASE2_COMMAND_SYSTEM = """You convert CIS audit procedures into executable shell commands for automated security auditing.
Return a JSON object: {{"rules": [...]}}, where "rules" is an array of objects, one per input rule, in the SAME order.
Each object MUST have these keys: section_number (string), audit_command (string), expected_output_regex (string), expected_output_description (string), remediation_command (string), remediation_description (string).

ABSOLUTE RULES — VIOLATIONS WILL CAUSE FAILURES:
1. Every value MUST be a plain string, NEVER an array or list.
2. audit_command = a SINGLE non-interactive, read-only command line. No GUI tools.
3. The command MUST run when pasted directly into the platform's default shell.
4. Keep ALL string values SHORT (under 100 chars). No prose in values.
5. expected_output_regex = a short Python-compatible regex matching compliant output.

══════════════════════════════════════════════════════════
COMMAND PURPOSE — CRITICAL
══════════════════════════════════════════════════════════
The audit command must RETRIEVE THE RAW VALUE from the system.
It must NOT test compliance or make boolean pass/fail decisions.

GOOD: net accounts                  ← retrieves all password policy values
BAD:  if ((net accounts | ...) -ge 14) {{ "PASS" }} else {{ "FAIL" }}

GOOD: reg query HKLM\\path /v Value  ← retrieves the registry value
BAD:  if ((Get-ItemProperty ...).Value -eq 1) {{ "Compliant" }}

GOOD: sysctl net.ipv4.ip_forward    ← retrieves the kernel parameter
BAD:  test $(sysctl -n net.ipv4.ip_forward) -eq 0 && echo PASS

The command's ONLY job is to print the current system value.
Our engine then compares the output against expected_output_regex.

══════════════════════════════════════════════════════════
REGEX QUALITY — CRITICAL
══════════════════════════════════════════════════════════
The regex must match the ACTUAL TEXT the command will print, NOT the English
description from the CIS rule.  It is used by a Python re.search() call against
the command's stdout — therefore it must be a valid Python regular expression.

GOOD regex: Minimum password length\\s+(?:1[4-9]|[2-9]\\d|\\d{{3,}})
BAD  regex: 14 or more password
BAD  regex: Enabled or greater
BAD  regex: 24 or more characters

For NUMERIC THRESHOLDS (e.g. "14 or more"):
  Build a regex range.  Example for >= 14: (?:1[4-9]|[2-9]\\d|\\d{{3,}})
  Example for >= 24: (?:2[4-9]|[3-9]\\d|\\d{{3,}})
  Example for <= 30: (?:[0-9]|[12]\\d|30)

For EXACT VALUES (e.g. REG_DWORD 0x00000001):
  Match the exact value: REG_DWORD\\s+0x0*1\\b

For STATUS STRINGS (e.g. "Disabled", "Success and Failure"):
  Match the exact word: disabled  OR  Success and Failure

NEVER produce a regex that is just the CIS rule's English description.

═══════════════════════════════════════════════════════════
WINDOWS — PowerShell is the default shell
═══════════════════════════════════════════════════════════
SYNTAX:
• NEVER use && — PowerShell does not support it. Use ; to chain commands.
• reg query paths must NOT have quotes: reg query HKLM\\SOFTWARE\\Path /v Value
• Do NOT wrap the entire command in quotes.
• Do NOT write If/Else or try/catch — just the retrieval command.

COMMAND PATTERNS BY CIS SECTION:
• 1.1.x Password Policy / 1.2.x Account Lockout → net accounts
  Output lines: "Minimum password length                  14"
  Regex example (>=14): Minimum password length\\s+(?:1[4-9]|[2-9]\\d|\\d{{3,}})
• 2.2.x User Rights Assignment → secedit /export /cfg C:\\Windows\\Temp\\secpol.cfg /quiet; Select-String -Path C:\\Windows\\Temp\\secpol.cfg -Pattern "SeRight"
• 2.3.x Security Options → reg query (use the registry path from CIS text)
• 5.x System Services → Get-Service -Name ServiceName | Select-Object -ExpandProperty StartType
  Output: "Disabled"
  Regex: Disabled
• 9.x Firewall → reg query HKLM\\SOFTWARE\\Policies\\Microsoft\\WindowsFirewall\\...
  Or: Get-NetFirewallProfile -Name Domain | Select-Object Enabled
• 17.x Audit Policy → auditpol /get /subcategory:"{{GUID}}" (copy GUID from CIS text)
  Output: "  Credential Validation    Success and Failure"
  Regex: Success and Failure|Success
• 18.x/19.x Admin Templates → reg query HKLM\\path /v ValueName
  Output: ValueName    REG_DWORD    0x00000001
  Regex: ValueName\\s+REG_DWORD\\s+0x0*1\\b

REGISTRY PATH RULES:
• CIS text says "HKLM\\KEY\\Path:ValueName" → command: reg query HKLM\\KEY\\Path /v ValueName
  (split at last colon — before = key path, after = value name)

═══════════════════════════════════════════════════════════
LINUX — bash is the default shell
═══════════════════════════════════════════════════════════
SYNTAX:
• Chain with && or ;
• All commands assume root or sudo. Do NOT add sudo prefix.
• Do NOT use If/then/else — just the retrieval command.

COMMAND PATTERNS BY CIS SECTION:
• Filesystem config (1.x) → mount | grep /tmp ; grep -E '\\s/tmp\\s' /etc/fstab
• Kernel parameters (3.x network) → sysctl net.ipv4.ip_forward
  Output: "net.ipv4.ip_forward = 0"
  Regex: net\\.ipv4\\.ip_forward\\s*=\\s*0
• Kernel params from file → grep -r 'net.ipv4.ip_forward' /etc/sysctl.conf /etc/sysctl.d/
• Package installed → dpkg-query -s packagename 2>/dev/null | grep -i status  (Debian/Ubuntu)
  Or: rpm -q packagename  (RHEL/CentOS)
• Package NOT installed → dpkg-query -W -f='${{Status}}' packagename 2>&1 | grep -c 'not-installed'
• Service status → systemctl is-enabled servicename
  Output: "disabled" or "enabled"
  Regex: disabled
• Service running → systemctl is-active servicename
• File permissions → stat -c '%a %U %G' /etc/ssh/sshd_config
  Output: "600 root root"
  Regex: [0-6][0-4]0\\s+root\\s+root
• File content → grep -E '^PermitRootLogin' /etc/ssh/sshd_config
  Output: "PermitRootLogin no"
  Regex: PermitRootLogin\\s+no
• Cron / at → stat -c '%a' /etc/crontab
• PAM config → grep -E 'pam_pwquality' /etc/pam.d/common-password
• Password policy → grep -E '^PASS_MAX_DAYS' /etc/login.defs
  Output: "PASS_MAX_DAYS   365"
  Regex: PASS_MAX_DAYS\\s+[0-9]+
• Audit rules → auditctl -l | grep -E 'time-change|identity|system-locale'
  Or: grep -r 'something' /etc/audit/rules.d/
• User/group → awk -F: '($3 == 0) {{ print $1 }}' /etc/passwd
• Firewall (UFW) → ufw status verbose
• Firewall (iptables) → iptables -L -n
• Firewall (nftables) → nft list ruleset

═══════════════════════════════════════════════════════════
NETWORK DEVICES — SSH CLI (Cisco IOS/NX-OS/ASA, Juniper, etc.)
═══════════════════════════════════════════════════════════
SYNTAX:
• Commands run in privileged EXEC mode (enable mode already).
• Use show commands only. NEVER use configure terminal.
• Pipe filtering: show running-config | include pattern (Cisco)
  Or: show configuration | match pattern (Juniper)

COMMAND PATTERNS:
• Running config section → show running-config | section line vty
• Specific setting → show running-config | include service password-encryption
  Output: "service password-encryption"
  Regex: service password-encryption
• Access lists → show access-lists
• Interfaces → show ip interface brief
• NTP → show ntp associations ; show running-config | include ntp
• Logging → show running-config | include logging
• SNMP → show running-config | include snmp-server
• SSH → show ip ssh
• AAA → show running-config | section aaa
• Banner → show running-config | include banner
• VTY config → show running-config | section line vty
"""

PHASE2_COMMAND_GENERATION = """Platform: {platform} (family: {platform_family})

Convert each CIS rule's audit procedure into a SINGLE executable CLI command.
The command MUST work when pasted directly into the platform's native shell:
  - Windows → PowerShell
  - Linux → bash
  - Network → privileged EXEC (SSH CLI)

═══════════════════════════════════════════════════════════
CRITICAL: RETRIEVE RAW VALUES, DO NOT TEST COMPLIANCE
═══════════════════════════════════════════════════════════
The command must ONLY retrieve the current system setting.
It must NOT contain any logic to test compliance or return pass/fail.

WRONG approach (testing compliance):
  if ((net accounts | Select-String 'Minimum password length').Line -match '(\\d+)') {{ if ([int]$matches[1] -ge 14) {{ "PASS" }} else {{ "FAIL" }} }}
  test $(sysctl -n net.ipv4.ip_forward) -eq 0 && echo PASS || echo FAIL

CORRECT approach (retrieving the raw value):
  net accounts
  sysctl net.ipv4.ip_forward

The compliance check happens LATER in our pipeline — NOT in the command.

READ THE AUDIT TEXT CAREFULLY for each rule:
- If the audit text provides a specific CLI command, USE IT (adapt syntax for the shell).
- If the audit text only describes a GUI path, translate it to the CLI equivalent.
- If the audit text mentions a registry path like HKLM\\KEY\\Path:ValueName, use:
  reg query HKLM\\KEY\\Path /v ValueName (Windows)

WINDOWS-SPECIFIC ROUTING:
- Password Policy (1.1.x) or Account Lockout (1.2.x) with NO registry path → net accounts
- User Rights (2.2.x) → secedit /export /cfg C:\\Windows\\Temp\\secpol.cfg /quiet; Select-String -Path C:\\Windows\\Temp\\secpol.cfg -Pattern "PolicyKey"
- Audit Policy (17.x) → auditpol /get /subcategory:"GUID" (copy GUID from CIS text)
- Registry-backed settings (2.3.x, 9.x, 18.x, 19.x) → reg query HKLM\\path /v ValueName

LINUX-SPECIFIC ROUTING:
- Kernel params → sysctl param.name
- Service state → systemctl is-enabled servicename
- File content → grep -E 'pattern' /path/to/config
- File permissions → stat -c '%a %U %G' /path/to/file
- Package check → dpkg-query -s pkg 2>/dev/null | grep Status (or rpm -q pkg)
- Audit rules → auditctl -l | grep pattern

NETWORK-SPECIFIC ROUTING:
- Config checking → show running-config | include pattern
- Section checking → show running-config | section pattern

REGEX REMINDER:
The expected_output_regex MUST match the literal text the command prints.
For numeric thresholds like "14 or more", use a numeric regex range:
  >=14 → (?:1[4-9]|[2-9]\\d|\\d{{3,}})
  >=24 → (?:2[4-9]|[3-9]\\d|\\d{{3,}})
NEVER use English phrases like "14 or more" or "Enabled or greater" as regex.

RULES:
{rules_json}

Return {{"rules": [...]}} with one object per rule, same order. Every value must be a plain string."""

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

COMMAND_REGENERATION_SYSTEM = """You fix CIS benchmark audit commands that failed. Return a JSON object with: audit_command, expected_output_regex, expected_output_description, remediation_command, remediation_description, explanation.

CRITICAL: The audit command must RETRIEVE THE RAW VALUE from the system.
It must NOT contain any compliance testing logic (no if/else, no pass/fail).
Our engine compares the raw output against expected_output_regex separately.

GOOD: net accounts                  ← retrieves all password policy values
BAD:  if (...) {{ "PASS" }} else {{ "FAIL" }}   ← testing compliance directly

Commands must be READ-ONLY, non-interactive, and work when pasted into the platform shell.

REGEX QUALITY:
• The regex must match ACTUAL command output text, NOT the English rule description.
• For numeric thresholds (e.g. >=14): use (?:1[4-9]|[2-9]\\d|\\d{{3,}})
• For exact values (REG_DWORD): use ValueName\\s+REG_DWORD\\s+0x0*1\\b
• NEVER produce regex like "14 or more" or "Enabled or greater".

WINDOWS (PowerShell):
• NEVER use && — use ; to chain commands
• reg query paths: NO quotes, e.g. reg query HKLM\\PATH /v ValueName
• 1.1.x/1.2.x password/lockout → net accounts
• 2.2.x user rights → secedit /export then Select-String
• 17.x audit policy → auditpol /get /subcategory:"GUID"
• 18.x/19.x/2.3.x/9.x → reg query

LINUX (bash):
• sysctl for kernel params, grep for config files, systemctl for services
• stat -c '%a %U %G' for permissions, auditctl -l for audit rules

NETWORK (SSH CLI):
• show running-config | include/section pattern"""

COMMAND_REGENERATION = """
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

Generate a corrected audit command that addresses the failure. Do NOT repeat previously failed approaches.
"""
