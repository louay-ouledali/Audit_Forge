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
            if tens > 0:
                parts.append(f"{hundreds}[0-{tens - 1}]\\d")
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
    """Return (key_path, value_name) from audit/remediation text."""
    m = _REG_PATH_RE.search(text)
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
        num_regex = _regex_lte(threshold)
    else:
        num_regex = _regex_gte(threshold)

    # Build a targeted command that outputs ONLY the numeric value
    escaped_label_ps = field_label.replace("'", "''")
    audit_cmd = (
        f"(net accounts | Select-String '{escaped_label_ps}').Line "
        f"-replace '\\D',''"
    )

    return {
        "audit_command": audit_cmd,
        "expected_output_regex": f"^{num_regex}$",
        "expected_output_description": f"{field_label} value (number only, must meet threshold {threshold})",
        "remediation_command": "",
        "remediation_description": f"Set {field_label} to the required value via Group Policy.",
    }


def _try_registry(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Windows registry-backed settings (2.3.x, 9.x, 18.x, 19.x).

    Uses ``(Get-ItemProperty ...).ValueName`` to output only the value itself,
    not the whole reg-query table.  For REG_DWORD values the output is a
    plain integer (e.g. ``1``), making regex matching trivial.
    """
    combined = (
        (rule.get("audit_description_raw") or "")
        + " "
        + (rule.get("remediation_description_raw") or "")
    )
    reg = _extract_registry(combined)
    if not reg:
        return None

    key_path, value_name = reg

    # Convert HKLM\ to PowerShell registry drive path HKLM:\
    ps_key_path = key_path.replace("HKLM\\", "HKLM:\\", 1)

    threshold = _extract_threshold(combined)

    if threshold is not None:
        # Numeric threshold → output just the number, regex matches >= or <=
        title_lower = (rule.get("title") or "").lower()
        is_max = "maximum" in title_lower or "or fewer" in title_lower or "or less" in title_lower
        if is_max:
            num_regex = _regex_lte(threshold)
        else:
            num_regex = _regex_gte(threshold)
        regex = f"^{num_regex}$"
    else:
        # Check for Enabled/Disabled pattern (REG_DWORD 1 = Enabled, 0 = Disabled)
        title_lower = (rule.get("title") or "").lower()
        if "enabled" in title_lower or "is set to 'on" in title_lower:
            regex = "^1$"
        elif "disabled" in title_lower or "is set to 'off" in title_lower:
            regex = "^0$"
        else:
            regex = r"^\d+$"

    audit_cmd = (
        f"(Get-ItemProperty -Path '{ps_key_path}' "
        f"-Name '{value_name}' -ErrorAction Stop).{value_name}"
    )

    return {
        "audit_command": audit_cmd,
        "expected_output_regex": regex,
        "expected_output_description": f"Registry value {value_name} (single value output)",
        "remediation_command": "",
        "remediation_description": f"Set {key_path}\\{value_name} via Group Policy or reg add.",
    }


def _try_auditpol(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Windows audit-policy rules (17.x)."""
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

    title_lower = (rule.get("title") or "").lower()
    if "success and failure" in title_lower:
        regex = "Success and Failure"
    elif "success" in title_lower:
        regex = "Success"
    elif "failure" in title_lower:
        regex = "Failure"
    else:
        regex = "Success|Failure"

    return {
        "audit_command": f'auditpol /get /subcategory:"{guid}"',
        "expected_output_regex": regex,
        "expected_output_description": f"Audit policy subcategory {guid} is configured",
        "remediation_command": "",
        "remediation_description": "Configure via Advanced Audit Policy in Group Policy.",
    }


def _try_windows_service(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Windows service rules (5.x).

    Uses ``Get-Service … | Select-Object -ExpandProperty StartType``
    which outputs a single word like ``Disabled`` or ``Automatic``.
    """
    section = rule.get("section_number", "")
    if not section.startswith("5."):
        return None

    title_lower = (rule.get("title") or "").lower()
    # Extract service name from title like "Ensure 'Print Spooler (Spooler)' is set to 'Disabled'"
    svc_match = re.search(r"\((\w+)\)", rule.get("title") or "")
    if not svc_match:
        return None

    svc_name = svc_match.group(1)
    if "disabled" in title_lower:
        regex = "^(?:Disabled|Stopped)$"
    else:
        regex = "^(?:Running|Automatic)$"

    return {
        "audit_command": f"(Get-Service -Name {svc_name} -ErrorAction Stop).StartType",
        "expected_output_regex": regex,
        "expected_output_description": f"Service {svc_name} start type (single value)",
        "remediation_command": "",
        "remediation_description": f"Set service {svc_name} startup type via Group Policy or sc.exe.",
    }


def _try_secedit(rule: dict[str, Any]) -> dict[str, str] | None:
    """Match Windows user rights assignment rules (2.2.x)."""
    section = rule.get("section_number", "")
    if not section.startswith("2.2."):
        return None

    title = rule.get("title") or ""
    # Extract the right name, e.g. "Access this computer from the network"
    right_match = re.search(r"Ensure '([^']+)'", title)
    if not right_match:
        return None

    right_name = right_match.group(1)
    # Map common right names to secedit policy keys
    # We use a generic approach: export secpol and grep for a pattern
    pattern_word = right_name.split()[0] if right_name else "Se"
    return {
        "audit_command": (
            "secedit /export /cfg C:\\Windows\\Temp\\secpol.cfg /quiet; "
            f'Select-String -Path C:\\Windows\\Temp\\secpol.cfg -Pattern "{pattern_word}"'
        ),
        "expected_output_regex": re.escape(pattern_word),
        "expected_output_description": f"User rights assignment: {right_name}",
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
        "expected_output_regex": f"^{re.escape(expected_val)}$",
        "expected_output_description": f"{param} value (expected: {expected_val})",
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
        regex = "^(?:disabled|masked|not-found|inactive)$"
    else:
        regex = "^enabled$"

    return {
        "audit_command": f"systemctl is-enabled {svc_name} 2>/dev/null || echo not-found",
        "expected_output_regex": regex,
        "expected_output_description": f"Service {svc_name} state (single value)",
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
        regex = f"{re.escape(perms)}\\s+root\\s+root"
    else:
        regex = r"[0-6][0-4][0-4]\s+root\s+root"

    return {
        "audit_command": f"stat -c '%a %U %G' {filepath}",
        "expected_output_regex": regex,
        "expected_output_description": f"File {filepath} permissions and ownership",
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
        key_match = re.search(r"ensure\s+'?([^']+?)'?\s+is\s+set", title_lower)
        key_name = key_match.group(1).strip() if key_match else pattern
        regex = f"{re.escape(key_name)}\\s+{re.escape(expected_val)}"
    else:
        regex = re.escape(pattern.strip("^$"))

    return {
        "audit_command": f"grep -E '{pattern}' {filepath}",
        "expected_output_regex": regex,
        "expected_output_description": f"Config check in {filepath}",
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
            num_regex = _regex_lte(threshold)
        else:
            num_regex = _regex_gte(threshold)
        regex = f"^{num_regex}$"
    else:
        regex = r"^\d+$"

    return {
        "audit_command": f"awk '/^{field_name}/ {{print $2}}' /etc/login.defs",
        "expected_output_regex": regex,
        "expected_output_description": f"{field_name} value (number only, threshold {threshold})",
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
            "expected_output_regex": re.escape(option),
            "expected_output_description": f"{mount_point} has {option} option set",
            "remediation_command": "",
            "remediation_description": f"Add {option} to {mount_point} mount options in /etc/fstab.",
        }

    return {
        "audit_command": f"findmnt -n {mount_point}",
        "expected_output_regex": re.escape(mount_point),
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
            regex = "not-installed|no packages found|not installed"
        else:
            cmd = f"dpkg-query -s {pkg_name} 2>/dev/null | grep -i status"
            regex = "install ok installed"
    else:
        # Fallback: try rpm
        if is_not_installed:
            cmd = f"rpm -q {pkg_name} 2>&1"
            regex = "not installed"
        else:
            cmd = f"rpm -q {pkg_name}"
            regex = pkg_name

    return {
        "audit_command": cmd,
        "expected_output_regex": regex,
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
        "expected_output_regex": re.escape(search_term) if search_term else ".",
        "expected_output_description": f"Network config check: {search_term}",
        "remediation_command": "",
        "remediation_description": f"Configure the required setting in device configuration.",
    }


# ---------------------------------------------------------------------------
# Master dispatcher
# ---------------------------------------------------------------------------

# Template chains by platform family – tried in order, first match wins
_WINDOWS_TEMPLATES = [
    _try_net_accounts,
    _try_auditpol,
    _try_windows_service,
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
