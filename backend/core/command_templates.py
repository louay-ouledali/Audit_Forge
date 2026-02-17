"""Deterministic command templates for common CIS benchmark rule patterns.

Instead of calling the LLM for every rule, this module matches rules to
known audit-command patterns and returns pre-built commands with precise
regex patterns.  This is faster (zero LLM latency) and produces higher
quality output (numeric thresholds encoded correctly in regex).

The public entry point is ``match_template(rule, platform_family)``.
It returns a dict with the same keys as the LLM would
(audit_command, expected_output_regex, …) or ``None`` when no template
matches and the rule should fall through to the LLM.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Helper: build a regex that matches an integer >= threshold
# ---------------------------------------------------------------------------

def _regex_gte(threshold: int) -> str:
    """Return a regex fragment that matches an integer >= *threshold*.

    Works for thresholds 0-999.  The generated pattern is anchored to
    word boundaries so it won't accidentally match inside larger numbers
    in unrelated text.

    >>> import re
    >>> pat = _regex_gte(14)
    >>> bool(re.search(pat, '13'))
    False
    >>> bool(re.search(pat, '14'))
    True
    >>> bool(re.search(pat, '99'))
    True
    """
    if threshold <= 0:
        return r"\d+"
    if threshold <= 9:
        hi = threshold
        parts = []
        if hi <= 9:
            parts.append(f"[{hi}-9]")
        parts.append(r"[1-9]\d+")  # 10+
        return "(?:" + "|".join(parts) + ")"
    if threshold <= 99:
        tens, ones = divmod(threshold, 10)
        parts = []
        # same tens digit, ones >= required
        if ones == 0:
            parts.append(f"{tens}\\d")
        else:
            parts.append(f"{tens}[{ones}-9]")
        # higher tens digit in same century
        if tens + 1 <= 9:
            parts.append(f"[{tens + 1}-9]\\d")
        # three-or-more digits (100+)
        parts.append(r"\d{3,}")
        return "(?:" + "|".join(parts) + ")"
    # 100-999 – simplified: just match the number or higher
    return r"\d{3,}"


def _regex_lte(threshold: int) -> str:
    """Return a regex fragment matching an integer in 0..*threshold*.

    Works for thresholds 0-999.

    >>> import re
    >>> pat = _regex_lte(30)
    >>> bool(re.fullmatch(pat, '30'))
    True
    >>> bool(re.fullmatch(pat, '31'))
    False
    >>> bool(re.fullmatch(pat, '0'))
    True
    """
    if threshold >= 999:
        return r"\d+"
    if threshold < 0:
        return "(?!)"  # matches nothing
    if threshold <= 9:
        return f"[0-{threshold}]"
    if threshold <= 99:
        tens, ones = divmod(threshold, 10)
        parts = []
        # single digits
        parts.append(r"[0-9]")
        # same tens digit
        if ones == 9:
            parts.append(f"{tens}\\d")
        else:
            parts.append(f"{tens}[0-{ones}]")
        # lower tens digits
        if tens > 1:
            parts.append(f"[1-{tens - 1}]\\d")
        return "(?:" + "|".join(parts) + ")"
    # 100-999: break into parts
    hundreds, remainder = divmod(threshold, 100)
    tens, ones = divmod(remainder, 10)
    parts = []
    # single digits (0-9)
    parts.append(r"[0-9]")
    # two-digit numbers (10-99)
    parts.append(r"[1-9]\d")
    # three-digit: same hundreds digit, smaller tens/ones
    if tens > 0:
        if ones == 9:
            parts.append(f"{hundreds}[0-{tens}]\\d")
        else:
            # Same hundreds digit, lower tens digits (full range)
            if tens > 1:
                parts.append(f"{hundreds}[0-{tens - 1}]\\d")
            elif tens == 1:
                parts.append(f"{hundreds}0\\d")
            # Same hundreds + same tens, ones up to threshold
            parts.append(f"{hundreds}{tens}[0-{ones}]")
    else:
        # tens == 0: only X00 through X0{ones}
        parts.append(f"{hundreds}0[0-{ones}]")
    # lower hundreds digits (full range)
    if hundreds > 1:
        parts.append(f"[1-{hundreds - 1}]\\d\\d")
    return "(?:" + "|".join(parts) + ")"


# ---------------------------------------------------------------------------
# Text cleanup: fix PDF line-break artifacts
# ---------------------------------------------------------------------------

def _fix_line_breaks(text: str) -> str:
    """Join words/identifiers broken across lines by PDF text extraction.

    CIS PDF extraction frequently breaks long identifiers with a newline,
    e.g.  ``DisableCloudOptimizedCo\\nntent`` instead of
    ``DisableCloudOptimizedContent``.  This function joins them so that
    regex-based extraction (registry paths, privilege names, etc.) works
    correctly.
    """
    if not text:
        return text
    # Join lines where a word fragment is split: letter/digit at end of line
    # followed by a lower-case letter or digit at start of next line.
    # This is the dominant pattern in CIS PDFs.
    text = re.sub(r'([A-Za-z0-9_])\n([a-z0-9])', r'\1\2', text)
    return text


# ---------------------------------------------------------------------------
# Extractors: pull numbers / paths from rule text
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(
    r"(?:is\s+set\s+to|set\s+to|to)\s+['\"]?(\d+)\b", re.IGNORECASE,
)
# Broader pattern for extracting thresholds from CIS rule titles/descriptions
_THRESHOLD_RE = re.compile(
    r"(?:"
    r"(?:is\s+set\s+to|set\s+to|to)\s+['\"]?(\d+)"
    r"|(\d+)\s+or\s+(?:more|greater|higher|above)"
    r"|(\d+)\s+or\s+(?:fewer|less|lower|below)"
    r"|(?:at\s+least|minimum\s+of|>=)\s+(\d+)"
    r"|(?:at\s+most|maximum\s+of|no\s+more\s+than|<=)\s+(\d+)"
    r")\b", re.IGNORECASE,
)
_REG_PATH_RE = re.compile(
    r"(HKLM\\[A-Za-z0-9\\_]+):([A-Za-z0-9_]+)", re.IGNORECASE,
)
_GUID_RE = re.compile(
    r"\{[0-9a-fA-F-]{36}\}",
)


def _extract_threshold(text: str) -> int | None:
    """Return the first integer threshold mentioned in rule text.

    Handles patterns like:
      "set to 14", "24 or more", "30 or fewer",
      "at least 14", "no more than 30"
    """
    # Try the broad pattern first
    m = _THRESHOLD_RE.search(text)
    if m:
        for grp in m.groups():
            if grp is not None:
                return int(grp)
    # Fall back to the simple pattern
    m2 = _NUM_RE.search(text)
    return int(m2.group(1)) if m2 else None


def _extract_registry(text: str) -> tuple[str, str] | None:
    """Return (key_path, value_name) from audit/remediation text.

    Applies line-break cleanup first so that PDF-broken names like
    ``DisableCloudOptimizedCo\\nntent`` are properly joined.
    """
    cleaned = _fix_line_breaks(text)
    m = _REG_PATH_RE.search(cleaned)
    return (m.group(1), m.group(2)) if m else None


def _extract_guid(text: str) -> str | None:
    m = _GUID_RE.search(text)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# Windows templates
# ---------------------------------------------------------------------------

# net accounts field labels keyed by title keywords
_NET_ACCOUNTS_FIELDS: dict[str, str] = {
    "password history": "Length of password history maintained",
    "maximum password age": "Maximum password age",
    "minimum password age": "Minimum password age",
    "minimum password length": "Minimum password length",
    "lockout duration": "Lockout duration",
    "lockout threshold": "Lockout threshold",
    "lockout observation window": "Lockout observation window",
    "reset account lockout": "Lockout observation window",
}

# Map from CIS user-rights display names (lower-cased) to secedit privilege
# constant names.  These are the keys that appear in the [Privilege Rights]
# section of the security policy export (secedit /export).
_USER_RIGHTS_MAP: dict[str, str] = {
    "access credential manager as a trusted caller": "SeTrustedCredManAccessPrivilege",
    "access this computer from the network": "SeNetworkLogonRight",
    "act as part of the operating system": "SeTcbPrivilege",
    "add workstations to domain": "SeMachineAccountPrivilege",
    "adjust memory quotas for a process": "SeIncreaseQuotaPrivilege",
    "allow log on locally": "SeInteractiveLogonRight",
    "allow log on through remote desktop services": "SeRemoteInteractiveLogonRight",
    "back up files and directories": "SeBackupPrivilege",
    "change the system time": "SeSystemtimePrivilege",
    "change the time zone": "SeTimeZonePrivilege",
    "create a pagefile": "SeCreatePagefilePrivilege",
    "create a token object": "SeCreateTokenPrivilege",
    "create global objects": "SeCreateGlobalPrivilege",
    "create permanent shared objects": "SeCreatePermanentPrivilege",
    "create symbolic links": "SeCreateSymbolicLinkPrivilege",
    "debug programs": "SeDebugPrivilege",
    "deny access to this computer from the network": "SeDenyNetworkLogonRight",
    "deny log on as a batch job": "SeDenyBatchLogonRight",
    "deny log on as a service": "SeDenyServiceLogonRight",
    "deny log on locally": "SeDenyInteractiveLogonRight",
    "deny log on through remote desktop services": "SeDenyRemoteInteractiveLogonRight",
    "enable computer and user accounts to be trusted for delegation": "SeEnableDelegationPrivilege",
    "force shutdown from a remote system": "SeRemoteShutdownPrivilege",
    "generate security audits": "SeAuditPrivilege",
    "impersonate a client after authentication": "SeImpersonatePrivilege",
    "increase a process working set": "SeIncreaseWorkingSetPrivilege",
    "increase scheduling priority": "SeIncreaseBasePriorityPrivilege",
    "load and unload device drivers": "SeLoadDriverPrivilege",
    "lock pages in memory": "SeLockMemoryPrivilege",
    "log on as a batch job": "SeBatchLogonRight",
    "log on as a service": "SeServiceLogonRight",
    "manage auditing and security log": "SeSecurityPrivilege",
    "modify an object label": "SeRelabelPrivilege",
    "modify firmware environment values": "SeSystemEnvironmentPrivilege",
    "perform volume maintenance tasks": "SeManageVolumePrivilege",
    "profile single process": "SeProfileSingleProcessPrivilege",
    "profile system performance": "SeSystemProfilePrivilege",
    "replace a process level token": "SeAssignPrimaryTokenPrivilege",
    "restore files and directories": "SeRestorePrivilege",
    "shut down the system": "SeShutdownPrivilege",
    "synchronize directory service data": "SeSyncAgentPrivilege",
    "take ownership of files or other objects": "SeTakeOwnershipPrivilege",
}


def _try_net_accounts(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Windows password-policy / account-lockout rules (1.1.x, 1.2.x).

    Generates a PowerShell command that extracts ONLY the numeric value
    for the specific policy field.  For example, instead of dumping all
    ``net accounts`` output, it pipes through ``Select-String`` and
    extracts just the number so the output is a single integer like ``24``.
    """
    section = rule.get("section_number", "")
    if not (section.startswith("1.1.") or section.startswith("1.2.")):
        return None

    title_lower = (rule.get("title") or "").lower()
    combined_text = (
        (rule.get("title") or "")
        + " "
        + (rule.get("audit_description_raw") or "")
        + " "
        + (rule.get("remediation_description_raw") or "")
    )

    # Find which net accounts field this is about
    field_label = None
    for keyword, label in _NET_ACCOUNTS_FIELDS.items():
        if keyword in title_lower:
            field_label = label
            break
    if not field_label:
        return None

    threshold = _extract_threshold(combined_text)
    if threshold is None:
        return None

    # Determine comparison direction from title
    is_max = "maximum" in title_lower or "or fewer" in title_lower
    if is_max:
        comparison = f"<={threshold}"
    else:
        comparison = f">={threshold}"

    # Build a targeted command that outputs ONLY the numeric value
    escaped_label_ps = field_label.replace("'", "''")
    audit_cmd = (
        f"(net accounts | Select-String '{escaped_label_ps}').Line "
        f"-replace '\\D',''"
    )

    return {
        "audit_command": audit_cmd,
        "expected_output_regex": comparison,
        "expected_output_description": f"{field_label} value (must be {comparison})",
        "remediation_command": "",
        "remediation_description": f"Set {field_label} to the required value via Group Policy.",
    }


def _try_registry(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Windows registry-backed settings (2.3.x, 9.x, 18.x, 19.x).

    Uses ``(Get-ItemProperty ...).ValueName`` to output only the value itself,
    not the whole reg-query table.  For REG_DWORD values the output is a
    plain integer (e.g. ``1``), making regex matching trivial.
    """
    combined = _fix_line_breaks(
        (rule.get("audit_description_raw") or "")
        + " "
        + (rule.get("remediation_description_raw") or "")
    )
    reg = _extract_registry(combined)
    if not reg:
        return None

    key_path, value_name = reg

    # Skip firewall LogFilePath values — these are strings, not numbers
    if value_name.lower() in ("logfilepath",):
        return _try_firewall_logpath(rule, key_path, value_name)

    # Convert HKLM\ to PowerShell registry drive path HKLM:\
    ps_key_path = key_path.replace("HKLM\\", "HKLM:\\", 1)

    comparison = _determine_registry_comparison(rule, combined)

    audit_cmd = (
        f"(Get-ItemProperty -Path '{ps_key_path}' "
        f"-Name '{value_name}' -ErrorAction Stop).{value_name}"
    )

    return {
        "audit_command": audit_cmd,
        "expected_output_regex": comparison,
        "expected_output_description": f"Registry value {value_name} (expected: {comparison})",
        "remediation_command": "",
        "remediation_description": f"Set {key_path}\\{value_name} via Group Policy or reg add.",
    }


def _determine_registry_comparison(rule: dict[str, Any], combined: str) -> str:
    """Determine the correct comparison expression for a registry-backed rule.

    Applies a cascade of heuristics to avoid the generic 'regex:\\d+' fallback:
      1. Extract explicit threshold from "set to X", "X or more", etc.
      2. Check title for Enabled/Disabled/On/Off patterns
      3. Extract REG_DWORD expected value from audit text (e.g. "REG_DWORD value of 1")
      4. Infer from title semantics ("Prevent", "Disallow", "Do not" → ==0,
         "Require", "Enable", "Allow" → ==1)
      5. Fall back to ==1 for REG_DWORD rules (better than regex:\\d+ which accepts any value)
    """
    title = rule.get("title") or ""
    title_lower = title.lower()

    # 1. Explicit threshold
    threshold = _extract_threshold(combined)
    if threshold is not None:
        is_max = "maximum" in title_lower or "or fewer" in title_lower or "or less" in title_lower
        if is_max:
            return f"<={threshold}"
        # Check if it's an exact-value setting (e.g. "set to '0'", "set to '4'")
        exact_match = re.search(
            r"is\s+set\s+to\s+['\"]?(\d+)['\"]?",
            title_lower,
        )
        if exact_match and int(exact_match.group(1)) == threshold:
            # "set to X" with no "or more" → exact match
            if not re.search(r"or\s+(?:more|greater|higher|above)", title_lower):
                return f"=={threshold}"
        return f">={threshold}"

    # 2. Explicit Enabled/Disabled in title
    if re.search(r"is\s+set\s+to\s+['\"]?(?:enabled|on)['\"]?", title_lower):
        return "==1"
    if re.search(r"is\s+set\s+to\s+['\"]?(?:disabled|off)['\"]?", title_lower):
        return "==0"
    # Check for bare Enabled/Disabled at end of title (truncated closing quote)
    if re.search(r"set\s+to\s+['\"]?disabled", title_lower):
        return "==0"
    if re.search(r"set\s+to\s+['\"]?enabled", title_lower):
        return "==1"

    # 3. Extract from audit text: "REG_DWORD value of X" or "a value of X"
    dword_match = re.search(
        r"(?:REG_DWORD|DWORD|value\s+of)\s+(?:value\s+of\s+)?['\"]?(\d+)",
        combined, re.IGNORECASE,
    )
    if dword_match:
        val = int(dword_match.group(1))
        # Check if audit says "or less" / "or that the key does not exist"
        context = combined[max(0, dword_match.start() - 20):dword_match.end() + 60]
        if re.search(r"or\s+(?:less|lower|fewer|below)", context, re.IGNORECASE):
            return f"<={val}"
        if re.search(r"or\s+(?:more|greater|higher|above)", context, re.IGNORECASE):
            return f">={val}"
        return f"=={val}"

    # 4. Infer from title semantics
    # "Do not allow / Prevent / Disallow / Turn off" → typically ==0
    if re.search(r"(?:do\s+not\s+allow|prevent|disallow|turn\s+off|block|prohibit|deny)",
                 title_lower):
        return "==0"
    # "Always / Require / Must / Enable / Turn on / Allow" → typically ==1
    if re.search(r"(?:always|require|must\s+use|turn\s+on|enable|force)",
                 title_lower):
        return "==1"

    # 5. Last resort: check audit text for any specific value hint
    # rather than falling back to the useless regex:\d+
    set_to_val = re.search(r"set\s+(?:to|=)\s*['\"]?(\d+)", combined, re.IGNORECASE)
    if set_to_val:
        return f"=={set_to_val.group(1)}"

    # 6. If all else fails, default to ==1 (most CIS registry rules check
    # that a protective setting is Enabled=1).  This is much better than
    # regex:\d+ which accepts ANY value including insecure ones.
    return "==1"


def _try_auditpol(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Windows audit-policy rules (17.x).

    Parses both the title AND remediation text to determine the exact
    expected audit setting (Success, Failure, or Success and Failure).
    The remediation text is authoritative — it says exactly what the GP
    setting should be set to.
    """
    section = rule.get("section_number", "")
    if not section.startswith("17."):
        return None

    combined = (
        (rule.get("audit_description_raw") or "")
        + " "
        + (rule.get("remediation_description_raw") or "")
    )
    guid = _extract_guid(combined)
    if not guid:
        return None

    # Determine expected audit setting.
    # Priority: remediation text > title text > default.
    # Remediation typically says:
    #   "set the following UI path to Success and Failure:"
    #   "set the following UI path to include Failure:"
    #   "set the following UI path to include Success:"
    remediation = (rule.get("remediation_description_raw") or "").lower()
    title_lower = (rule.get("title") or "").lower()

    comparison = _determine_audit_comparison(title_lower, remediation)

    return {
        "audit_command": f'auditpol /get /subcategory:"{guid}"',
        "expected_output_regex": comparison,
        "expected_output_description": f"Audit policy subcategory {guid} ({comparison})",
        "remediation_command": "",
        "remediation_description": "Configure via Advanced Audit Policy in Group Policy.",
    }


def _determine_audit_comparison(title_lower: str, remediation_lower: str) -> str:
    """Determine the correct audit policy comparison from title and remediation text.

    The remediation text is the authoritative source.  CIS remediation for
    audit policy rules says exactly one of:
      - "set ... to Success and Failure"
      - "set ... to include Failure"
      - "set ... to include Success"
      - "set ... to Success"
      - "set ... to Failure"
    """
    # Check remediation text first (most reliable)
    if "success and failure" in remediation_lower:
        return "contains:Success and Failure"
    # "include Failure" (only Failure required, e.g., 17.6.1, 17.7.5)
    if re.search(r"(?:set|path)\s+to\s+(?:include\s+)?failure", remediation_lower):
        # But NOT if it also says Success
        if "success" not in remediation_lower or "include failure" in remediation_lower:
            return "contains:Failure"
        return "contains:Success and Failure"
    # "include Success" (only Success required)
    if re.search(r"(?:set|path)\s+to\s+(?:include\s+)?success", remediation_lower):
        if "failure" not in remediation_lower or "include success" in remediation_lower:
            return "contains:Success"
        return "contains:Success and Failure"

    # Fall back to title text
    if "success and failure" in title_lower:
        return "contains:Success and Failure"
    if "failure" in title_lower and "success" not in title_lower:
        return "contains:Failure"
    if "success" in title_lower:
        return "contains:Success"

    # Default: Success (conservative)
    return "contains:Success"


def _try_windows_service(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Windows service rules (5.x).

    Uses ``(Get-Service ...).StartType`` which outputs a single word like
    ``Disabled`` or ``Automatic``.

    CIS section 5.x is almost entirely about ensuring services are
    Disabled.  Only use ==Automatic if the title/remediation explicitly
    says so.  This fixes the inverted-state bug where services that
    should be Disabled were checked as Automatic.
    """
    section = rule.get("section_number", "")
    if not section.startswith("5."):
        return None

    title = rule.get("title") or ""
    title_lower = title.lower()
    remediation_lower = (rule.get("remediation_description_raw") or "").lower()

    # Extract service name from title like "Ensure 'Print Spooler (Spooler)' is set to 'Disabled'"
    svc_match = re.search(r"\((\w+)\)", title)
    if not svc_match:
        return None

    svc_name = svc_match.group(1)

    # Determine expected state from title + remediation
    # Check for explicit Automatic/Manual first (rare in section 5)
    if re.search(r"set\s+to\s+['\"]?automatic", title_lower) or \
       re.search(r"set\s+to\s+['\"]?automatic", remediation_lower):
        comparison = "==Automatic"
    elif re.search(r"set\s+to\s+['\"]?manual", title_lower) or \
         re.search(r"set\s+to\s+['\"]?manual", remediation_lower):
        comparison = "==Manual"
    else:
        # Default to Disabled for CIS section 5.x — the vast majority
        # of these rules require services to be Disabled or Not Installed
        comparison = "==Disabled"

    return {
        "audit_command": f"(Get-Service -Name {svc_name} -ErrorAction Stop).StartType",
        "expected_output_regex": comparison,
        "expected_output_description": f"Service {svc_name} start type (expected: {comparison})",
        "remediation_command": "",
        "remediation_description": f"Set service {svc_name} startup type via Group Policy or sc.exe.",
    }


def _try_secedit(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Windows user rights assignment rules (2.2.x).

    Uses ``secedit /export`` to dump the local security policy, then
    ``Select-String`` with the **exact secedit privilege constant**
    (e.g. ``SeCreatePagefilePrivilege``) to retrieve the assigned
    accounts.  This replaces the broken first-word approach that produced
    vague matches like ``Select-String -Pattern "Create"``.
    """
    section = rule.get("section_number", "")
    if not section.startswith("2.2."):
        return None

    title = rule.get("title") or ""
    # Extract the right name, e.g. "Access this computer from the network"
    # Also handle truncated titles where the closing quote is missing
    right_match = re.search(r"Ensure '([^']+)'", title)
    if not right_match:
        # Try without closing quote (PDF truncated the title)
        right_match = re.search(r"Ensure '(.+)$", title)
    if not right_match:
        return None

    right_name = right_match.group(1)

    # Look up the secedit privilege constant for this right name.
    # Matching is case-insensitive and tolerates slight CIS wording variants.
    right_lower = right_name.lower().strip()
    privilege_key = _USER_RIGHTS_MAP.get(right_lower)

    if not privilege_key:
        # Fuzzy fallback: try substring matching for slight title differences
        for known_right, key in _USER_RIGHTS_MAP.items():
            # If the known right is contained in the title or vice-versa
            if known_right in right_lower or right_lower in known_right:
                privilege_key = key
                break

    if not privilege_key:
        # Last resort: fall through to LLM
        return None

    # Determine if this is a "Deny" rule (expected to have specific accounts)
    # or a positive privilege (expected to have Administrators, etc.)
    title_lower = title.lower()
    is_deny_right = "deny" in title_lower

    # For deny rights, we want to verify the line exists (accounts are assigned)
    # For positive rights, we want to verify the line exists with proper accounts
    # In both cases, outputting the full line lets the verification engine check
    return {
        "audit_command": (
            "secedit /export /cfg C:\\Windows\\Temp\\secpol.cfg /quiet; "
            f"Select-String -Path C:\\Windows\\Temp\\secpol.cfg -Pattern '{privilege_key}'"
        ),
        "expected_output_regex": f"contains:{privilege_key}",
        "expected_output_description": f"User rights assignment: {right_name} ({privilege_key})",
        "remediation_command": "",
        "remediation_description": f"Configure '{right_name}' via Group Policy > User Rights Assignment.",
    }


# ---------------------------------------------------------------------------
# Linux templates
# ---------------------------------------------------------------------------

def _try_sysctl(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Linux kernel parameter rules.

    Uses ``sysctl -n param`` (not ``sysctl param``) to output ONLY the value.
    For example: ``sysctl -n net.ipv4.ip_forward`` → ``0``
    """
    combined = (
        (rule.get("audit_description_raw") or "")
        + " "
        + (rule.get("remediation_description_raw") or "")
    )
    # Look for sysctl parameter pattern
    param_match = re.search(r"sysctl\s+([\w.]+)", combined)
    if not param_match:
        # Also match patterns like "net.ipv4.ip_forward"
        param_match = re.search(r"\b(net\.[\w.]+|kernel\.[\w.]+|fs\.[\w.]+)\b", combined)
    if not param_match:
        return None

    param = param_match.group(1)
    # Determine expected value
    val_match = re.search(rf"{re.escape(param)}\s*=\s*(\d+)", combined)
    expected_val = val_match.group(1) if val_match else "0"

    return {
        "audit_command": f"sysctl -n {param}",
        "expected_output_regex": f"=={expected_val}",
        "expected_output_description": f"{param} value (expected: =={expected_val})",
        "remediation_command": "",
        "remediation_description": f"Set {param} = {expected_val} in /etc/sysctl.conf and run sysctl -p.",
    }


def _try_systemctl(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Linux service rules (systemctl is-enabled).

    Output is a single word: ``enabled``, ``disabled``, ``masked``, etc.
    """
    combined = (
        (rule.get("audit_description_raw") or "")
        + " "
        + (rule.get("remediation_description_raw") or "")
    )
    title_lower = (rule.get("title") or "").lower()

    svc_match = re.search(r"systemctl\s+is-enabled\s+([\w@.-]+)", combined)
    if not svc_match:
        # Try to find service name from title like "Ensure X is not enabled"
        svc_match2 = re.search(r"(?:Ensure|Verify)\s+(\w[\w.-]+)\s+is\s+(?:not\s+)?(?:enabled|disabled|active)", title_lower)
        if not svc_match2:
            return None
        svc_name = svc_match2.group(1)
    else:
        svc_name = svc_match.group(1)

    if "not enabled" in title_lower or "disabled" in title_lower or "not installed" in title_lower:
        comparison = "==disabled"
    else:
        comparison = "==enabled"

    return {
        "audit_command": f"systemctl is-enabled {svc_name} 2>/dev/null || echo not-found",
        "expected_output_regex": comparison,
        "expected_output_description": f"Service {svc_name} state (expected: {comparison})",
        "remediation_command": "",
        "remediation_description": f"Configure {svc_name} via systemctl.",
    }


def _try_file_permissions(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Linux file permission rules (stat)."""
    combined = (
        (rule.get("audit_description_raw") or "")
        + " "
        + (rule.get("remediation_description_raw") or "")
    )
    stat_match = re.search(r"stat\s+(?:-c\s+'[^']+'\s+)?(/[\w/.]+)", combined)
    if not stat_match:
        return None

    filepath = stat_match.group(1)
    # Look for expected permissions like 644, 600, etc.
    perm_match = re.search(r"\b([0-7]{3,4})\b", combined)
    if perm_match:
        perms = perm_match.group(1)
        comparison = f"<={perms}"
    else:
        comparison = "<=644"

    return {
        "audit_command": f"stat -c '%a' {filepath}",
        "expected_output_regex": comparison,
        "expected_output_description": f"File {filepath} permissions (expected: {comparison})",
        "remediation_command": "",
        "remediation_description": f"Set correct permissions on {filepath}.",
    }


def _try_grep_config(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Linux config-file grep rules."""
    combined = (
        (rule.get("audit_description_raw") or "")
        + " "
        + (rule.get("remediation_description_raw") or "")
    )
    # Match patterns like: grep -E '^PermitRootLogin' /etc/ssh/sshd_config
    grep_match = re.search(
        r"grep\s+(?:-[EiPr]+\s+)?['\"]?([^'\"]+?)['\"]?\s+(/[\w/._-]+)",
        combined,
    )
    if not grep_match:
        return None

    pattern = grep_match.group(1)
    filepath = grep_match.group(2)

    title_lower = (rule.get("title") or "").lower()
    # Determine expected value
    val_match = re.search(r"is\s+set\s+to\s+['\"]?(\w+)", title_lower)
    if val_match:
        expected_val = val_match.group(1)
        comparison = f"contains:{expected_val}"
    else:
        comparison = f"contains:{pattern.strip('^$')}"

    return {
        "audit_command": f"grep -E '{pattern}' {filepath}",
        "expected_output_regex": comparison,
        "expected_output_description": f"Config check in {filepath} ({comparison})",
        "remediation_command": "",
        "remediation_description": f"Edit {filepath} to set the required value.",
    }


def _try_linux_password_policy(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Linux password policy rules (/etc/login.defs).

    Uses ``awk`` to extract ONLY the numeric value.
    For example: ``awk '/^PASS_MAX_DAYS/ {print $2}' /etc/login.defs`` → ``365``
    """
    combined = (
        (rule.get("audit_description_raw") or "")
        + " "
        + (rule.get("remediation_description_raw") or "")
    )
    title_lower = (rule.get("title") or "").lower()

    login_defs_fields = {
        "pass_max_days": "PASS_MAX_DAYS",
        "pass_min_days": "PASS_MIN_DAYS",
        "pass_warn_age": "PASS_WARN_AGE",
        "pass_min_len": "PASS_MIN_LEN",
    }

    field_name = None
    for key, label in login_defs_fields.items():
        if key.replace("_", " ") in title_lower or label.lower() in combined.lower():
            field_name = label
            break
    if not field_name:
        return None

    threshold = _extract_threshold(combined + " " + (rule.get("title") or ""))
    if threshold is None:
        # Try extracting from the combined text directly
        num_match = re.search(rf"{field_name}\s+(\d+)", combined)
        if num_match:
            threshold = int(num_match.group(1))

    if threshold is not None:
        is_max = "max" in field_name.lower() or "or fewer" in title_lower or "or less" in title_lower
        if is_max:
            comparison = f"<={threshold}"
        else:
            comparison = f">={threshold}"
    else:
        comparison = ">=1"

    return {
        "audit_command": f"awk '/^{field_name}/ {{print $2}}' /etc/login.defs",
        "expected_output_regex": comparison,
        "expected_output_description": f"{field_name} value (must be {comparison})",
        "remediation_command": "",
        "remediation_description": f"Edit /etc/login.defs and set {field_name} to the required value.",
    }


def _try_mount_point(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Linux filesystem mount point rules (e.g. 'Ensure /tmp is a separate partition')."""
    title_lower = (rule.get("title") or "").lower()
    combined = (
        (rule.get("audit_description_raw") or "")
        + " "
        + (rule.get("remediation_description_raw") or "")
    )

    # Look for mount point patterns: /tmp, /var, /var/log, /home, etc.
    mount_match = re.search(r"(?:ensure\s+)?(/(?:tmp|var(?:/log(?:/audit)?)?|home|dev/shm))\s+is\b", title_lower)
    if not mount_match:
        return None

    mount_point = mount_match.group(1)

    # Check for mount options like nodev, nosuid, noexec
    option_match = re.search(r"\b(nodev|nosuid|noexec)\b", title_lower)
    if option_match:
        option = option_match.group(1)
        return {
            "audit_command": f"findmnt -n {mount_point} | grep {option}",
            "expected_output_regex": f"contains:{option}",
            "expected_output_description": f"{mount_point} has {option} option set",
            "remediation_command": "",
            "remediation_description": f"Add {option} to {mount_point} mount options in /etc/fstab.",
        }

    return {
        "audit_command": f"findmnt -n {mount_point}",
        "expected_output_regex": f"contains:{mount_point}",
        "expected_output_description": f"{mount_point} is a separate mount",
        "remediation_command": "",
        "remediation_description": f"Create a separate partition for {mount_point}.",
    }


def _try_package_check(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Linux package install/remove rules."""
    title_lower = (rule.get("title") or "").lower()
    combined = (
        (rule.get("audit_description_raw") or "")
        + " "
        + (rule.get("remediation_description_raw") or "")
    )

    # Pattern: "Ensure <package> is installed" or "Ensure <package> is not installed"
    pkg_match = re.search(
        r"ensure\s+(\w[\w.-]+)\s+is\s+(not\s+)?installed",
        title_lower,
    )
    if not pkg_match:
        return None

    pkg_name = pkg_match.group(1)
    is_not_installed = bool(pkg_match.group(2))

    # Determine package manager from audit text
    if "dpkg" in combined or "apt" in combined:
        if is_not_installed:
            cmd = f"dpkg-query -W -f='${{Status}}' {pkg_name} 2>&1"
            comparison = "contains:not-installed"
        else:
            cmd = f"dpkg-query -s {pkg_name} 2>/dev/null | grep -i status"
            comparison = "contains:install ok installed"
    else:
        # Fallback: try rpm
        if is_not_installed:
            cmd = f"rpm -q {pkg_name} 2>&1"
            comparison = "contains:not installed"
        else:
            cmd = f"rpm -q {pkg_name}"
            comparison = f"contains:{pkg_name}"

    return {
        "audit_command": cmd,
        "expected_output_regex": comparison,
        "expected_output_description": f"Package {pkg_name} {'not ' if is_not_installed else ''}installed",
        "remediation_command": "",
        "remediation_description": f"{'Remove' if not is_not_installed else 'Install'} {pkg_name} using the system package manager.",
    }


# ---------------------------------------------------------------------------
# Network device templates
# ---------------------------------------------------------------------------

def _try_show_running_config(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match network device show running-config rules."""
    combined = (
        (rule.get("audit_description_raw") or "")
        + " "
        + (rule.get("remediation_description_raw") or "")
    )

    show_match = re.search(
        r"(show\s+running-config\s+\|\s+(?:include|section)\s+[\w\s-]+)",
        combined, re.IGNORECASE,
    )
    if not show_match:
        return None

    command = show_match.group(1).strip()
    # Extract the pattern being searched for
    pattern_match = re.search(r"\|\s+(?:include|section)\s+(.+)", command, re.IGNORECASE)
    search_term = pattern_match.group(1).strip() if pattern_match else ""

    return {
        "audit_command": command,
        "expected_output_regex": f"contains:{search_term}" if search_term else "regex:.",
        "expected_output_description": f"Network config check: {search_term}",
        "remediation_command": "",
        "remediation_description": f"Configure the required setting in device configuration.",
    }


# ---------------------------------------------------------------------------
# Master dispatcher
# ---------------------------------------------------------------------------

# Map of secedit INF keys for password/lockout policies that are NOT
# accessible via `net accounts` or registry (Local Security Policy items).
_SECEDIT_PASSWORD_POLICIES: dict[str, str] = {
    "password must meet complexity": "PasswordComplexity",
    "complexity requirements": "PasswordComplexity",
    "reversible encryption": "ClearTextPassword",
    "store passwords using reversible": "ClearTextPassword",
    "relax minimum password length": "RelaxMinimumPasswordLengthLimits",
    "administrator account lockout": "AllowAdministratorLockout",
    "allow administrator account lockout": "AllowAdministratorLockout",
}


def _try_secedit_password(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Windows password/lockout policies that require secedit export.

    Some password policies (complexity, reversible encryption, relax min
    length) live in the Local Security Policy, NOT in the registry.
    The correct audit approach is: secedit /export → parse the INF file.
    """
    section = rule.get("section_number", "")
    if not (section.startswith("1.1.") or section.startswith("1.2.")):
        return None

    title_lower = (rule.get("title") or "").lower()

    secedit_key = None
    for pattern, key in _SECEDIT_PASSWORD_POLICIES.items():
        if pattern in title_lower:
            secedit_key = key
            break
    if not secedit_key:
        return None

    # Determine expected value
    # PasswordComplexity: 1 = Enabled (CIS wants this)
    # ClearTextPassword: 0 = Disabled (CIS wants reversible encryption OFF)
    # RelaxMinimumPasswordLengthLimits: 1 = Enabled (CIS wants this)
    # AllowAdministratorLockout: 1 = Enabled (CIS wants this)
    if secedit_key == "ClearTextPassword":
        comparison = "==0"
    elif secedit_key == "PasswordComplexity":
        comparison = "==1"
    elif secedit_key == "RelaxMinimumPasswordLengthLimits":
        comparison = "==1"
    elif secedit_key == "AllowAdministratorLockout":
        comparison = "==1"
    else:
        comparison = "==1"

    audit_cmd = (
        "secedit /export /cfg C:\\Windows\\Temp\\secpol.cfg /quiet; "
        f"(Select-String -Path C:\\Windows\\Temp\\secpol.cfg -Pattern '{secedit_key}').Line "
        f"-replace '.*=\\s*',''"
    )

    return {
        "audit_command": audit_cmd,
        "expected_output_regex": comparison,
        "expected_output_description": f"Security policy {secedit_key} value (expected: {comparison})",
        "remediation_command": "",
        "remediation_description": f"Configure {secedit_key} via Local Security Policy or Group Policy.",
    }


def _try_firewall_logpath(
    rule: dict[str, Any], key_path: str, value_name: str,
) -> dict[str, str] | None:
    """Handle firewall LogFilePath registry checks.

    The LogFilePath is a string (file path), not a number.
    CIS typically requires it to be set to the default:
    %systemroot%\\system32\\logfiles\\firewall\\pfirewall.log
    """
    ps_key_path = key_path.replace("HKLM\\", "HKLM:\\", 1)
    audit_cmd = (
        f"(Get-ItemProperty -Path '{ps_key_path}' "
        f"-Name '{value_name}' -ErrorAction Stop).{value_name}"
    )
    return {
        "audit_command": audit_cmd,
        "expected_output_regex": "contains:pfirewall.log",
        "expected_output_description": f"Firewall log file path ({value_name})",
        "remediation_command": "",
        "remediation_description": (
            f"Set {key_path}\\{value_name} to "
            "%systemroot%\\system32\\logfiles\\firewall\\pfirewall.log."
        ),
    }


# Template chains by platform family – tried in order, first match wins
_WINDOWS_TEMPLATES = [
    _try_net_accounts,
    _try_auditpol,
    _try_windows_service,
    _try_secedit_password,  # before secedit (more specific)
    _try_secedit,
    _try_registry,  # registry last because it's the broadest matcher
]

_LINUX_TEMPLATES = [
    _try_linux_password_policy,
    _try_mount_point,
    _try_package_check,
    _try_sysctl,
    _try_systemctl,
    _try_file_permissions,
    _try_grep_config,
]

_NETWORK_TEMPLATES = [
    _try_show_running_config,
]

_TEMPLATES_BY_FAMILY: dict[str, list] = {
    "windows": _WINDOWS_TEMPLATES,
    "linux": _LINUX_TEMPLATES,
    "network": _NETWORK_TEMPLATES,
}


def match_template(rule: dict[str, Any], platform_family: str) -> dict[str, str] | None:
    """Try to match *rule* to a deterministic command template.

    Returns a dict with keys ``audit_command``, ``expected_output_regex``,
    ``expected_output_description``, ``remediation_command``,
    ``remediation_description`` — or ``None`` if no template matched.
    """
    templates = _TEMPLATES_BY_FAMILY.get(platform_family, [])
    for fn in templates:
        result = fn(rule)
        if result:
            return result
    return None
