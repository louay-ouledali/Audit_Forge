"""Shared error-detection patterns for scan result evaluation.

These patterns mirror the PowerShell template's ``Test-ExecutionError`` and
``Test-NotConfigured`` functions so that **all** evaluation paths (network
scan, USB import, marker import) classify results identically.

Three categories:
1. **Execution errors** – the audit command itself could not run (missing
   cmdlet, access denied, etc.).  These map to ``ERROR``.
2. **Not configured** – a registry key / property / GPO path does not exist.
   In CIS benchmarks this typically means the policy is *Not Configured*,
   which is non-compliant → ``FAIL``.  We evaluate with an empty string so
   the comparison engine applies the expected expression against ``""``.
3. **Service not found** – the Windows service is not installed.  We treat
   this as ``Disabled`` for CIS checks like "Ensure X is disabled".
"""

from __future__ import annotations

import re

# ── Execution-error patterns (→ ERROR) ─────────────────────────
# These indicate the command could not execute at all.
EXECUTION_ERROR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"is not recognized as the name of a cmdlet", re.IGNORECASE),
    re.compile(r"CommandNotFoundException", re.IGNORECASE),
    re.compile(r"Access is denied", re.IGNORECASE),
    re.compile(r"Access to the path .+ is denied", re.IGNORECASE),
    re.compile(r"UnauthorizedAccessException", re.IGNORECASE),
    re.compile(r"PermissionDenied", re.IGNORECASE),
    re.compile(r"Error 0x00000522", re.IGNORECASE),
    re.compile(r"error occurred:", re.IGNORECASE),
    re.compile(r"secedit.+/export.+failed", re.IGNORECASE),
    re.compile(r"The term .+ is not recognized", re.IGNORECASE),
    re.compile(r"is not recognized as (?:an )?internal or external command", re.IGNORECASE),
    re.compile(r"command not found", re.IGNORECASE),
    re.compile(r"FullyQualifiedErrorId", re.IGNORECASE),
    re.compile(r"CategoryInfo\s*:", re.IGNORECASE),
]

# ── Not-configured patterns (→ FAIL with empty-string eval) ────
# A missing registry key, property, or GPO path.
NOT_CONFIGURED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Cannot find path", re.IGNORECASE),
    re.compile(r"does not exist at path", re.IGNORECASE),
    re.compile(r"Property .+ does not exist", re.IGNORECASE),
    re.compile(r"ObjectNotFound:", re.IGNORECASE),
    re.compile(r"ItemNotFoundException", re.IGNORECASE),
    re.compile(r"PathNotFound", re.IGNORECASE),
]

# ── Service-not-found patterns ─────────────────────────────────
SERVICE_NOT_FOUND_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Cannot find any service", re.IGNORECASE),
    re.compile(r"No service with service name", re.IGNORECASE),
    re.compile(r"service .+ was not found", re.IGNORECASE),
]

# ── Module-not-found patterns (Linux kernel modules) ──────────
# "FATAL: Module X not found" means the module binary doesn't even
# exist on disk — this is *more* secure than just blacklisting it.
MODULE_NOT_FOUND_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"FATAL:\s*Module\s+\S+\s+not found", re.IGNORECASE),
    re.compile(r"Module\s+\S+\s+not found in directory", re.IGNORECASE),
    re.compile(r"modprobe:\s*FATAL", re.IGNORECASE),
]


def is_execution_error(text: str) -> bool:
    """Return True if *text* contains markers of a genuine execution failure."""
    if not text:
        return False
    return any(p.search(text) for p in EXECUTION_ERROR_PATTERNS)


def is_not_configured(text: str) -> bool:
    """Return True if *text* indicates a missing registry key / GPO path."""
    if not text:
        return False
    return any(p.search(text) for p in NOT_CONFIGURED_PATTERNS)


def is_service_not_found(text: str) -> bool:
    """Return True if *text* indicates the queried Windows service doesn't exist."""
    if not text:
        return False
    return any(p.search(text) for p in SERVICE_NOT_FOUND_PATTERNS)


def is_module_not_found(text: str) -> bool:
    """Return True if *text* indicates a Linux kernel module doesn't exist."""
    if not text:
        return False
    return any(p.search(text) for p in MODULE_NOT_FOUND_PATTERNS)


def classify_output(text: str) -> str:
    """Classify output into a category.

    Returns one of:
    - ``"execution_error"`` – command could not run
    - ``"not_configured"`` – registry/GPO path missing
    - ``"service_not_found"`` – Windows service not installed
    - ``"module_not_found"`` – Linux kernel module doesn't exist
    - ``"normal"`` – regular command output
    """
    if not text or not text.strip():
        return "normal"
    # Check module_not_found BEFORE execution_error because
    # "FATAL" could match a generic error pattern.
    if is_module_not_found(text):
        return "module_not_found"
    if is_execution_error(text):
        return "execution_error"
    if is_not_configured(text):
        return "not_configured"
    if is_service_not_found(text):
        return "service_not_found"
    return "normal"
