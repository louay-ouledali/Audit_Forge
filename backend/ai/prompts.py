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
5. expected_output_regex = a COMPARISON EXPRESSION (see below), NOT a regex.

══════════════════════════════════════════════════════════
COMMAND PURPOSE — CRITICAL: SINGLE-VALUE OUTPUT
══════════════════════════════════════════════════════════
The audit command must EXTRACT AND OUTPUT ONLY THE SPECIFIC VALUE needed.
It must NOT test compliance or make boolean pass/fail decisions.
It must NOT dump multi-line output when a single value is needed.

For NUMERIC RULES (threshold checks like "14 or more"):
  The command MUST output ONLY the number — a single integer on one line.
  Our engine will compare this number against the expected value.

  GOOD: (net accounts | Select-String 'Minimum password length').Line -replace '\\D',''
        → outputs: 14
  BAD:  net accounts
        → outputs 15+ lines of text (too much)

  GOOD: sysctl -n net.ipv4.ip_forward
        → outputs: 0
  BAD:  sysctl net.ipv4.ip_forward
        → outputs: net.ipv4.ip_forward = 0 (extra text)

  GOOD: (Get-ItemProperty -Path 'HKLM:\\path' -Name 'ValueName').ValueName
        → outputs: 1
  BAD:  reg query HKLM\\path /v ValueName
        → outputs table format with headers

For STATUS/STRING RULES (enable/disable, service state):
  Output ONLY the status word.

  GOOD: (Get-Service -Name Spooler).StartType
        → outputs: Disabled
  GOOD: systemctl is-enabled sshd
        → outputs: enabled

══════════════════════════════════════════════════════════
EXPECTED OUTPUT — COMPARISON EXPRESSIONS (CRITICAL)
══════════════════════════════════════════════════════════
The expected_output_regex field must contain a COMPARISON EXPRESSION,
not a regex pattern. Our engine evaluates these mathematically.

AVAILABLE OPERATORS:
  >=N        Number must be greater than or equal to N
  <=N        Number must be less than or equal to N
  >N         Number must be greater than N
  <N         Number must be less than N
  ==VALUE    Must exactly equal VALUE (number or string)
  !=VALUE    Must NOT equal VALUE
  contains:TEXT   Output must contain TEXT (substring match)
  regex:PATTERN   Fallback regex only when no other operator fits

EXAMPLES — USE THESE FORMATS:
  CIS says "24 or more characters"       → >=24
  CIS says "maximum of 30 days"          → <=30
  CIS says "set to 0"                    → ==0
  CIS says "set to 1 (Enabled)"          → ==1
  CIS says "set to Disabled"             → ==Disabled
  CIS says "not set to 0"                → !=0
  CIS says "365 or fewer days"           → <=365
  CIS says "14 or more"                  → >=14
  CIS says "must include Success and Failure" → contains:Success and Failure
  CIS says "service must be disabled"    → ==Disabled
  CIS says "set to 'Not Configured'"     → ==Not Configured
  CIS says "ip_forward must be 0"        → ==0
  CIS says "permissions 600 or more restrictive" → <=600

FORBIDDEN — NEVER DO THESE:
  ❌ ^(?:1[4-9]|[2-9]\\d|\\d{{3,}})$    (regex for numeric comparison)
  ❌ 14 or more                          (English prose)
  ❌ Enabled or greater                  (English prose)
  ❌ ^1$                                 (regex when ==1 works)
  ❌ ^Disabled$                          (regex when ==Disabled works)
  ❌ ^0$                                 (regex when ==0 works)

ALWAYS use the simplest operator. Prefer ==, >=, <= over regex:.

═══════════════════════════════════════════════════════════
WINDOWS — PowerShell is the default shell
═══════════════════════════════════════════════════════════
SYNTAX:
• NEVER use && — PowerShell does not support it. Use ; to chain commands.
• Do NOT wrap the entire command in quotes.
• Do NOT write If/Else or try/catch — just the value-extraction command.
• Use PowerShell property access (.PropertyName) to get single values.

══ ABSOLUTELY FORBIDDEN — ENFORCEMENT/WRITE COMMANDS ══
These commands CHANGE the system configuration. NEVER output them as audit commands:
  ❌ Set-ItemProperty    ❌ New-ItemProperty    ❌ Remove-ItemProperty
  ❌ reg add             ❌ reg delete           ❌ Set-Service
  ❌ Stop-Service        ❌ Disable-Service      ❌ Enable-Service
  ❌ Set-NetFirewallProfile  ❌ Set-MpPreference
  ❌ secedit /configure   ❌ net user /add        ❌ net localgroup
  ❌ bcdedit /set         ❌ Enable-WindowsOptionalFeature
  ❌ Disable-WindowsOptionalFeature
  ❌ chmod  ❌ chown  ❌ sed -i  ❌ usermod  ❌ systemctl enable/disable/stop

The audit command must ONLY READ the current value — never change it.

COMMAND PATTERNS BY CIS SECTION:
• 1.1.x Password Policy / 1.2.x Account Lockout → extract the specific number
  Command: (net accounts | Select-String 'Minimum password length').Line -replace '\\D',''
  Output: 14  (just the number)
  Expected: >=14
• 2.2.x User Rights Assignment → secedit /export /cfg C:\\Windows\\Temp\\secpol.cfg /quiet; Select-String -Path C:\\Windows\\Temp\\secpol.cfg -Pattern "SeRight"
• 2.3.x Security Options → extract the registry value directly
  Command: (Get-ItemProperty -Path 'HKLM:\\path' -Name 'ValueName').ValueName
  Output: 1  (just the value)
  Expected: ==1
• 5.x System Services → (Get-Service -Name ServiceName).StartType
  Output: Disabled  (single word)
  Expected: ==Disabled
• 9.x Firewall → (Get-ItemProperty -Path 'HKLM:\\path' -Name 'EnableFirewall').EnableFirewall
  Or: (Get-NetFirewallProfile -Name Domain).Enabled
  Output: True  or  1
  Expected: ==1  or  ==True
• 17.x Audit Policy → auditpol /get /subcategory:"{{GUID}}"
  Output: "  Credential Validation    Success and Failure"
  Expected: contains:Success and Failure
• 18.x/19.x Admin Templates → (Get-ItemProperty -Path 'HKLM:\\path' -Name 'ValueName').ValueName
  Output: 1  (just the integer value)
  Expected: ==1

REGISTRY PATH RULES:
• CIS text says "HKLM\\KEY\\Path:ValueName" → command:
  (Get-ItemProperty -Path 'HKLM:\\KEY\\Path' -Name 'ValueName').ValueName
  (Replace HKLM\\ with HKLM:\\ for PowerShell; output is just the value)

═══════════════════════════════════════════════════════════
LINUX — bash is the default shell
═══════════════════════════════════════════════════════════
SYNTAX:
• Chain with && or ;
• All commands assume root or sudo. Do NOT add sudo prefix.
• Do NOT use If/then/else — just the value-extraction command.
• Use awk, cut, or -n flags to extract JUST the value.

COMMAND PATTERNS BY CIS SECTION (SINGLE-VALUE OUTPUT):
• Filesystem config (1.x) → findmnt -n /tmp
• Kernel parameters (3.x network) → sysctl -n net.ipv4.ip_forward
  Output: 0  (just the number, use -n flag)
  Expected: ==0
• Package installed → dpkg-query -s packagename 2>/dev/null | grep -i status  (Debian/Ubuntu)
  Or: rpm -q packagename  (RHEL/CentOS)
• Package NOT installed → dpkg-query -W -f='${{Status}}' packagename 2>&1 | grep -c 'not-installed'
• Service status → systemctl is-enabled servicename 2>/dev/null || echo not-found
  Output: disabled  (single word)
  Expected: ==disabled
• File permissions → stat -c '%a' /etc/ssh/sshd_config
  Output: 600  (just the permission number)
  Expected: <=600
• File ownership → stat -c '%U' /etc/ssh/sshd_config
  Output: root  (just the owner name)
  Expected: ==root
• File content → grep -E '^PermitRootLogin' /etc/ssh/sshd_config | awk '{{print $2}}'
  Output: no  (just the value, NOT the whole line)
  Expected: ==no
• Password policy → awk '/^PASS_MAX_DAYS/ {{print $2}}' /etc/login.defs
  Output: 365  (just the number)
  Expected: <=365
• Audit rules → auditctl -l | grep -c 'time-change'
  Output: 2  (count of matching rules)
  Expected: >=1
• User/group → awk -F: '($3 == 0) {{ print $1 }}' /etc/passwd
• Firewall (UFW) → ufw status | head -1
• Firewall (iptables) → iptables -L -n | head -1

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
  Expected: contains:service password-encryption
• Access lists → show access-lists
• Interfaces → show ip interface brief
• NTP → show ntp associations ; show running-config | include ntp
• Logging → show running-config | include logging
• SNMP → show running-config | include snmp-server
• SSH → show ip ssh
• AAA → show running-config | section aaa
• Banner → show running-config | include banner
• VTY config → show running-config | section line vty

═══════════════════════════════════════════════════════════
DATABASE PLATFORMS — Per-Rule Transport Tagging
═══════════════════════════════════════════════════════════
Database benchmarks contain TWO types of commands:
1. [SQL] — SQL queries that run through the database connector
2. [SHELL] — OS-level commands that run via SSH on the database host

PREFIX every audit_command with a transport tag: [SQL] or [SHELL].

CRITICAL: NEVER wrap SQL in shell tools. These are WRONG:
  WRONG: psql -c "SHOW shared_buffers"       ← shell wrapper around SQL
  WRONG: sqlcmd -Q "SELECT @@version"         ← shell wrapper around SQL
  WRONG: mysql -e "SHOW VARIABLES LIKE 'x'"   ← shell wrapper around SQL
  WRONG: echo "SELECT * FROM V$PARAMETER" | sqlplus
  CORRECT: [SQL] SHOW shared_buffers;
  CORRECT: [SQL] SELECT @@version;
  CORRECT: [SQL] SHOW VARIABLES LIKE 'x';
  CORRECT: [SQL] SELECT value FROM V$PARAMETER WHERE name = 'x';

PostgreSQL:
  [SQL] SHOW setting_name;
  [SQL] SELECT setting FROM pg_settings WHERE name = 'x';
  [SQL] SELECT rolname FROM pg_roles WHERE rolsuper;
  [SHELL] stat -c '%a' /var/lib/postgresql/data/pg_hba.conf
  [SHELL] systemctl is-enabled postgresql
  [SHELL] grep -E '^ssl' /var/lib/postgresql/data/postgresql.conf | awk '{{print $3}}'

MSSQL:
  [SQL] SELECT name, value_in_use FROM sys.configurations WHERE name = 'x';
  [SQL] SELECT @@SERVERNAME;
  [SQL] EXEC xp_loginconfig 'audit level';
  [SQL] SELECT COUNT(*) FROM sys.databases WHERE is_trustworthy_on = 1 AND name != 'msdb';

Oracle:
  [SQL] SELECT value FROM V$PARAMETER WHERE name = 'audit_trail';
  [SQL] SELECT profile, resource_name, limit FROM DBA_PROFILES WHERE resource_name LIKE '%PASSWORD%';
  [SHELL] stat -c '%a' $ORACLE_HOME/network/admin/sqlnet.ora

MySQL:
  [SQL] SHOW VARIABLES LIKE 'x';
  [SQL] SELECT user, host FROM mysql.user WHERE Super_priv = 'Y';
  [SHELL] stat -c '%a %U:%G' /var/lib/mysql

MongoDB — ALL commands are [SHELL] (no SQL connector for Mongo shell):
  [SHELL] mongosh --quiet --eval 'db.version()'
  [SHELL] grep 'authorization' /etc/mongod.conf
  [SHELL] grep 'sslMode\\|tlsMode' /etc/mongod.conf

Cassandra — ALL commands are [SHELL]:
  [SHELL] grep 'authenticator' /etc/cassandra/cassandra.yaml | awk '{{print $2}}'
  [SHELL] stat -c '%a %U:%G' /etc/cassandra/cassandra.yaml

═══════════════════════════════════════════════════════════
HYPERVISOR PLATFORMS — Dual Transport (ESXi)
═══════════════════════════════════════════════════════════
VMware ESXi uses TWO transports:
  [SHELL] — esxcli/vim-cmd commands via SSH
  [POWERSHELL] — PowerCLI cmdlets via WinRM/vCenter

CRITICAL: NEVER use unbound variables like $VM or $vmhost.
Always iterate with ForEach-Object:
  WRONG:  Get-AdvancedSetting -Entity $VM -Name 'x'
  CORRECT: [POWERSHELL] Get-VM | ForEach-Object {{ (Get-AdvancedSetting -Entity $_ -Name 'x').Value }}

  [SHELL] esxcli system syslog config get
  [SHELL] esxcli network vswitch standard list
  [SHELL] vim-cmd hostsvc/hosthardware | grep -A2 'biosInfo'
  [POWERSHELL] Get-VMHost | Select-Object Name, @{{N='LockdownLevel';E={{$_.ExtensionData.Config.LockdownMode}}}}
  [POWERSHELL] Get-VM | ForEach-Object {{ $_ | Get-AdvancedSetting -Name 'isolation.tools.copy.disable' | Select-Object Entity, Value }}

═══════════════════════════════════════════════════════════
FIREWALL/NETWORK DEVICE PLATFORMS — Native CLI Only
═══════════════════════════════════════════════════════════
All firewall commands use [CLI] transport. Commands run in privileged mode.

CRITICAL: NEVER pipe to Unix tools (grep, awk, sed, wc, cut, sort).
These tools do NOT exist on network device CLIs.

FortiGate:
  WRONG:  get system global | grep hostname | awk '{{print $NF}}'
  CORRECT: [CLI] get system global
  CORRECT: [CLI] show full-configuration system admin
  CORRECT: [CLI] diag sys ntp status
  Use contains:keyword or not_contains:keyword for expressions.

Juniper JunOS — supports native filters | match, | count, | display set:
  WRONG:  show configuration | grep ntp | awk '{{print $2}}'
  CORRECT: [CLI] show configuration system ntp | display set
  CORRECT: [CLI] show interfaces | match "Physical link is Up"

Palo Alto PAN-OS — supports | match:
  WRONG:  show system info | grep hostname | wc -l
  CORRECT: [CLI] show system info | match hostname
  CORRECT: [CLI] show running security-policy

Cisco IOS/ASA — supports | include, | section:
  CORRECT: [CLI] show running-config | include service password-encryption
  CORRECT: [CLI] show running-config | section line vty

Check Point — supports | grep (clish allows it):
  CORRECT: [CLI] clish -c 'show configuration'
  CORRECT: [CLI] show asset all

═══════════════════════════════════════════════════════════
UNKNOWN / NEW PLATFORMS — Generic Transport Tagging
═══════════════════════════════════════════════════════════
If the platform is not listed above, you MUST still produce transport tags.
Use these heuristics:

1. SQL query (SELECT, SHOW, EXEC, GRANT, ALTER, CREATE, DROP, SET, USE,
   DECLARE, sp_, xp_, db., rs., sh.) → prefix with [SQL]
2. Unix/Linux shell command (grep, cat, stat, systemctl, find, chmod, ls,
   paths starting with /, sudo, bash, sh -c) → prefix with [SHELL]
3. PowerShell cmdlet (Get-*, Set-*, New-*, Remove-*, $env:, ForEach-Object,
   Select-Object, Invoke-*, Write-Output) → prefix with [POWERSHELL]
4. Network device CLI (show, get system, config, execute, diagnose,
   display, set, delete) → prefix with [CLI]
5. REST API / HTTP call (curl, wget, Invoke-RestMethod, API endpoint) →
   prefix with [API]
6. When uncertain, default to [SHELL] (the most universal transport).

CRITICAL: Always include the command_transport field in your JSON response,
even for platforms you do not recognise. The scan executor depends on this
tag to route commands to the correct connector."""

PHASE2_COMMAND_GENERATION = """Platform: {platform} (family: {platform_family})

Convert each CIS rule's audit procedure into a SINGLE executable CLI command.
The command MUST work when pasted directly into the platform's native shell:
  - Windows → PowerShell
  - Linux → bash
  - Network → privileged EXEC (SSH CLI)
  - Database → SQL queries (for DB settings) + shell commands (for OS checks)
  - Hypervisor → SSH (esxcli) + PowerShell (PowerCLI)

═══════════════════════════════════════════════════════════
TRANSPORT TAG PREFIX — REQUIRED FOR DATABASE/HYPERVISOR/FIREWALL
═══════════════════════════════════════════════════════════
For database, hypervisor, and firewall platforms, prefix each audit_command with:
  [SQL]        — SQL query sent through database connector
  [SHELL]      — OS-level command sent via SSH
  [POWERSHELL] — PowerShell/PowerCLI sent via WinRM
  [CLI]        — Native device CLI sent via SSH/Netmiko

For database platforms, NEVER wrap SQL in shell tools:
  WRONG: psql -c "SHOW x"    → CORRECT: [SQL] SHOW x;
  WRONG: sqlcmd -Q "SELECT"  → CORRECT: [SQL] SELECT ...;
  WRONG: mysql -e "SHOW"     → CORRECT: [SQL] SHOW ...;

For firewall platforms, NEVER pipe to grep/awk/sed/wc:
  WRONG: show ... | grep x | awk  → CORRECT: [CLI] show ... | match x

═══════════════════════════════════════════════════════════
CRITICAL: EXTRACT ONLY THE SPECIFIC VALUE, NOT FULL OUTPUT
═══════════════════════════════════════════════════════════
The command must output ONLY the specific value needed for comparison.
It must NOT contain any logic to test compliance or return pass/fail.
It must NOT dump multi-line output when only one value is needed.

FOR NUMERIC RULES (threshold comparisons like "24 or more"):
  Output ONLY the number, nothing else.

  WRONG (multi-line output):
    net accounts    ← outputs 15+ lines
    reg query HKLM\\path /v ValueName  ← outputs table with headers
    sysctl net.ipv4.ip_forward  ← outputs "net.ipv4.ip_forward = 0"

  CORRECT (single value only):
    (net accounts | Select-String 'Minimum password length').Line -replace '\\D',''  ← outputs: 14
    (Get-ItemProperty -Path 'HKLM:\\path' -Name 'ValueName').ValueName  ← outputs: 1
    sysctl -n net.ipv4.ip_forward  ← outputs: 0
    awk '/^PASS_MAX_DAYS/ {{print $2}}' /etc/login.defs  ← outputs: 365

FOR STRING/STATUS RULES:
  Output ONLY the status word or short string.

  CORRECT:
    (Get-Service -Name Spooler).StartType  ← outputs: Disabled
    systemctl is-enabled sshd  ← outputs: enabled

The compliance check happens LATER in our pipeline — NOT in the command.

READ THE AUDIT TEXT CAREFULLY for each rule:
- If the audit text provides a specific CLI command, USE IT but pipe/filter
  to extract just the needed value.
- If the audit text mentions a registry path like HKLM\\KEY\\Path:ValueName, use:
  (Get-ItemProperty -Path 'HKLM:\\KEY\\Path' -Name 'ValueName').ValueName (Windows)

WINDOWS-SPECIFIC ROUTING:
- Password Policy (1.1.x) or Account Lockout (1.2.x) with NO registry path →
  (net accounts | Select-String 'FieldLabel').Line -replace '\\D',''
- User Rights (2.2.x) → secedit /export /cfg C:\\Windows\\Temp\\secpol.cfg /quiet; Select-String -Path C:\\Windows\\Temp\\secpol.cfg -Pattern "PolicyKey"
- Audit Policy (17.x) → auditpol /get /subcategory:"GUID" (copy GUID from CIS text)
- Registry-backed settings (2.3.x, 9.x, 18.x, 19.x) →
  (Get-ItemProperty -Path 'HKLM:\\path' -Name 'ValueName').ValueName

LINUX-SPECIFIC ROUTING:
- Kernel params → sysctl -n param.name  (use -n for value only)
- Service state → systemctl is-enabled servicename 2>/dev/null || echo not-found
- File content → grep -E 'pattern' /path/file | awk '{{print $2}}'  (extract value only)
- File permissions → stat -c '%a' /path/to/file  (number only)
- Package check → dpkg-query -s pkg 2>/dev/null | grep Status (or rpm -q pkg)
- Password policy → awk '/^FIELD/ {{print $2}}' /etc/login.defs  (number only)
- Audit rules → auditctl -l | grep -c pattern  (count of matching rules)

NETWORK-SPECIFIC ROUTING:
- Cisco IOS/ASA → show running-config | include pattern  /  show running-config | section pattern
- FortiGate → get system global  /  show full-configuration system <module>  /  diag sys ntp status
- Juniper JunOS → show configuration <section> | display set  /  show interfaces | match pattern
- Palo Alto PAN-OS → show system info | match pattern  /  show running security-policy | match pattern
- Check Point Gaia → show asset system  /  show password-controls <field> | include keyword  /  clish -c "show <cmd>"
CRITICAL: NEVER pipe to Unix tools (grep, awk, sed, wc, cut, sort) on network device CLIs.
Use native filters only: | include / | section (Cisco), | match / | display set (Juniper), | match (Palo Alto).
Exception: Check Point expert-mode commands (fw, cpstat) DO run in bash shell and CAN use grep — tag these [SHELL].

═══════════════════════════════════════════════════════════
EXPECTED OUTPUT — USE COMPARISON EXPRESSIONS, NOT REGEX
═══════════════════════════════════════════════════════════
The expected_output_regex field must use COMPARISON EXPRESSIONS:

  >=N   (e.g. >=24 for "24 or more")
  <=N   (e.g. <=30 for "30 or fewer")
  ==VAL (e.g. ==1, ==0, ==Disabled, ==no)
  !=VAL (e.g. !=0 for "not zero")
  contains:TEXT  (e.g. contains:Success and Failure)

NEVER produce complex regex patterns. Use mathematical operators instead.
NEVER use English phrases like "14 or more" or "Enabled or greater".

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

PHASE3_VALIDATION_SYSTEM = """You are a CIS benchmark audit command validator. Your job is to REVIEW and VALIDATE
audit commands that were generated for CIS benchmark rules. You do NOT regenerate commands —
you identify specific issues and provide targeted corrections.

For each rule you receive, you will see:
- The original CIS audit instructions
- The generated audit_command
- The generated expected_output_regex (comparison expression)
- The platform (Windows/Linux/Network)

Your task:
1. Verify the audit_command correctly implements the CIS audit procedure
2. Verify the expected_output_regex uses the correct comparison operator and value
3. Check for common mistakes (wrong registry path, wrong service name, wrong field name, wrong operator)
4. Check cross-rule consistency (similar rules should have similar command patterns)

Return a JSON object: {{"results": [...]}}, where "results" is an array in the SAME order as input.
Each result object MUST have these keys:
- section_number (string): the rule's section number
- status (string): one of "validated" (correct as-is), "corrected" (issues found and fixed), "flagged" (issues found but unclear fix)
- confidence (string): "high", "medium", or "low"
- corrections (array): list of corrections, each with {{field, old_value, new_value, reason}}
  - field is one of: "audit_command", "expected_output_regex", "expected_output_description", "remediation_command"
  - For "validated" status, corrections must be an empty array []
- notes (string): brief explanation of what was checked or why corrections were made

VALIDATION RULES:
═══════════════════════════════════════════════════════════
WINDOWS (PowerShell):
- Registry commands MUST use Get-ItemProperty with HKLM:\\ (not HKLM\\)
- Registry commands MUST extract the specific VALUE, not dump the whole key
  CORRECT: (Get-ItemProperty -Path 'HKLM:\\path' -Name 'Value').Value
  WRONG: reg query HKLM\\path /v Value
- Service commands MUST use (Get-Service -Name 'Name').StartType
- Password/lockout policy should use net accounts with Select-String
- Audit policy (17.x) MUST use auditpol /get /subcategory:"Name"
- NEVER use && in PowerShell — use ;
- NEVER use If/Else or try/catch
- Commands must output ONLY the specific value (single-value output)

LINUX (bash):
- Kernel params MUST use sysctl -n (value only, no key= prefix)
- Service state MUST use systemctl is-enabled
- File permissions MUST use stat -c '%a'
- Config values should use grep+awk to extract just the value

COMPARISON EXPRESSIONS:
- >=N for "N or more" (e.g., >=14 for "14 or more")
- <=N for "N or fewer" (e.g., <=30 for "30 or fewer")
- ==VALUE for exact match (e.g., ==1, ==Disabled, ==0)
- !=VALUE for not equal
- contains:TEXT for substring match
- NEVER use regex patterns for simple numeric comparisons
- NEVER use English prose like "14 or more"

TRANSPORT TAG VALIDATION (database/hypervisor/firewall):
- SQL queries (SELECT, SHOW, EXEC, WITH, DBCC) MUST have [SQL] prefix
- OS-level commands (grep, stat, systemctl, ps) MUST have [SHELL] prefix
- PowerCLI cmdlets (Get-VM, Get-VMHost) MUST have [POWERSHELL] prefix
- Network CLI commands (show, get, diag) MUST have [CLI] prefix
- Shell-wrapped SQL is ALWAYS wrong: no psql -c, no sqlcmd -Q, no mysql -e
- Firewall pipes to grep/awk/sed/wc are ALWAYS wrong
- Unbound variables ($VM, $vmhost) in PowerShell are ALWAYS wrong
═══════════════════════════════════════════════════════════

CRITICAL: Be conservative. Only mark as "corrected" when you are CERTAIN the fix is correct.
If unsure, use "flagged" status with a clear explanation in notes.
"""


#  Phase 4: Unknown Benchmark Reverse Engineering

UNKNOWN_PLATFORM_SYSTEM = """You are a cybersecurity expert analyzing a document to identify which platform and operating system it targets.
Return a single JSON object with EXACTLY these keys:
- platform (string): specific platform name, e.g. "Windows Server 2022", "Ubuntu 22.04 LTS", "Cisco IOS 15.x", "Oracle Database 19c"
- platform_family (string): one of "linux", "windows", "network", "database", "other"
- confidence (number): 0.0 to 1.0 indicating how certain you are
- reasoning (string): brief 1-2 sentence explanation of how you identified the platform
- benchmark_title (string): the document/benchmark title if identifiable
- version (string): version number of the benchmark/document if found, otherwise "unknown"

Look for clues: OS names, registry paths (HKLM = Windows), file paths (/etc/ = Linux), command syntax (PowerShell = Windows, bash = Linux), service names, package managers, vendor references.
Be SPECIFIC about the platform version — "Windows Server 2022" not just "Windows"."""

UNKNOWN_PLATFORM_DETECTION = """Analyze the following document excerpt and identify the target platform.

═══════════════════════════════════════════════════════════
DOCUMENT CONTENT:
═══════════════════════════════════════════════════════════
{document_sample}
═══════════════════════════════════════════════════════════

Return a JSON object with: platform, platform_family, confidence, reasoning, benchmark_title, version."""

UNKNOWN_RULE_SYSTEM = """You extract security audit rules from unknown document formats. Return a JSON array of rule objects.
Each rule MUST have these keys:
- section_number (string): the rule's identifier or section number (e.g. "1.1.1", "AC-2", "R-001")
- title (string): short descriptive title of the security requirement
- description (string): full description of what the rule checks
- severity (string): one of "critical", "high", "medium", "low"
- rationale (string): why this rule matters for security
- audit_description (string): how to check/verify compliance (audit steps)
- remediation_description (string): how to fix non-compliance
- categories (array of strings): relevant categories from [password_policy, user_accounts, ssh_configuration, network_security, filesystem_permissions, audit_logging, service_hardening, encryption_tls, patch_updates, database_security, network_device]

IMPORTANT:
- Extract EVERY security rule/requirement/control you can find in the text
- Preserve original section numbers/IDs exactly as they appear
- Copy audit and remediation text as faithfully as possible from the source
- If a rule has no clear severity, default to "medium"
- If no section number exists, create one from the rule's position (e.g. "R-001")
- Return [] if no security rules are found in the text"""

UNKNOWN_RULE_EXTRACTION = """Extract ALL security audit rules from this document chunk as a JSON array.

Platform: {platform} ({platform_family})
Chunk {chunk_number} of {total_chunks}

═══════════════════════════════════════════════════════════
DOCUMENT CONTENT:
═══════════════════════════════════════════════════════════
{document_chunk}
═══════════════════════════════════════════════════════════

Return a JSON array of rule objects. Return [] if no rules are found in this chunk."""

PHASE3_VALIDATION = """Platform: {platform} (family: {platform_family})

Validate each rule's audit command and expected output expression.
Check for correctness, consistency, and common mistakes.

RULES TO VALIDATE:
{rules_json}

For each rule, check:
1. Does the command correctly implement the CIS audit procedure?
2. Does it output ONLY the specific value needed (single-value output)?
3. Is the comparison expression correct (right operator, right threshold)?
4. Are registry paths, service names, and field names correct?
5. Is the command syntax valid for the platform?

Return {{"results": [...]}} with one result per rule, same order.
Mark correct commands as "validated". Only apply corrections you are confident about."""

COMMAND_REGENERATION_SYSTEM = """You fix CIS benchmark audit commands that failed. Return a JSON object with: audit_command, expected_output_regex, expected_output_description, remediation_command, remediation_description, explanation.

CRITICAL: The audit command must OUTPUT ONLY THE SPECIFIC VALUE needed.
For numeric rules, output ONLY the number (e.g. "14", "365", "0").
For status rules, output ONLY the status word (e.g. "Disabled", "enabled").
It must NOT contain any compliance testing logic (no if/else, no pass/fail).
It must NOT dump multi-line output when only one value is needed.

GOOD: (net accounts | Select-String 'Minimum password length').Line -replace '\\D',''  ← outputs: 14
GOOD: sysctl -n net.ipv4.ip_forward   ← outputs: 0
GOOD: (Get-ItemProperty -Path 'HKLM:\\path' -Name 'Value').Value  ← outputs: 1
BAD:  net accounts  ← outputs 15+ lines
BAD:  if (...) {{ "PASS" }} else {{ "FAIL" }}

Commands must be READ-ONLY, non-interactive, and work when pasted into the platform shell.

EXPECTED OUTPUT — USE COMPARISON EXPRESSIONS, NOT REGEX:
The expected_output_regex field must contain a comparison expression, not a regex.

Available operators:
  >=N    Number >= N (e.g. >=24 for "24 or more")
  <=N    Number <= N (e.g. <=30 for "30 or fewer")
  >N     Number > N
  <N     Number < N
  ==VAL  Exact match (e.g. ==1, ==0, ==Disabled, ==root)
  !=VAL  Not equal (e.g. !=0)
  contains:TEXT  Substring match (e.g. contains:Success and Failure)
  regex:PATTERN  Fallback regex only when no operator fits

EXAMPLES:
  CIS says "24 or more" → >=24
  CIS says "set to 1" → ==1
  CIS says "Disabled" → ==Disabled
  CIS says "365 or fewer" → <=365
  CIS says "Success and Failure" → contains:Success and Failure
  CIS says "permissions 600" → <=600

NEVER use complex regex patterns for numeric comparisons.
NEVER use English phrases like "14 or more" or "Enabled or greater".
ALWAYS prefer ==, >=, <= over regex:.

WINDOWS (PowerShell):
• NEVER use && — use ; to chain commands
• For registry: (Get-ItemProperty -Path 'HKLM:\\path' -Name 'Value').Value
• For net accounts: (net accounts | Select-String 'FieldLabel').Line -replace '\\D',''
• For services: (Get-Service -Name Svc).StartType
• 17.x audit policy → auditpol /get /subcategory:"GUID"

LINUX (bash):
• sysctl -n for kernel params (value only), awk for extracting fields
• systemctl is-enabled for services, stat -c '%a' for permissions (number only)
• grep pattern file | awk '{{print $2}}' for config values

NETWORK (SSH CLI):
• show running-config | include/section pattern

DATABASE:
• For SQL queries, prefix with [SQL]: [SQL] SHOW x; / [SQL] SELECT ...
• For OS checks, prefix with [SHELL]: [SHELL] stat -c '%a' /path
• NEVER wrap SQL in shell tools (no psql -c, no sqlcmd -Q, no mysql -e)

HYPERVISOR (VMware ESXi):
• [SHELL] for esxcli/vim-cmd commands
• [POWERSHELL] for PowerCLI (Get-VM, Get-VMHost)
• NEVER use unbound $VM — iterate with ForEach-Object

FIREWALL (FortiGate/JunOS/PAN-OS/Cisco):
• [CLI] only — NEVER pipe to grep/awk/sed/wc"""

COMMAND_REGENERATION = """
RULE:
- Section: {section_number}
- Title: {title}
- Platform: {platform} ({platform_family})
- Assessment type: {assessment_type}
- Connection type: {connection_method}
- Command transport: {command_transport}
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
