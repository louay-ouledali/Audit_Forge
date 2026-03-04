"""Platform detector — determines OS, benchmark, and scheme from various signals.

Consolidates platform detection logic that can be reused across CSV, HTML,
and future importers. Combines signals from:
- Plugin IDs (Nessus compliance plugin → platform)
- Name patterns (CIS/NIST benchmark names)
- OS strings (from scan info plugins or system metadata)
- Reference codes (LEVEL, framework mappings)
"""

from __future__ import annotations

import logging
import re

from backend.importers.base import PlatformInfo

logger = logging.getLogger("auditforge.importers.platform_detector")

# ── Plugin ID → Platform mapping ────────────────────────────────

_PLUGIN_PLATFORM_MAP = {
    "21156": ("Windows", "Windows"),
    "21157": ("Linux", "Unix"),
    "33929": (None, None),          # PCI DSS — platform-agnostic
    "33930": (None, None),          # CIS — platform determined from name
}


def detect_platform_from_plugin(plugin_id: str, name: str = "") -> PlatformInfo:
    """Create a PlatformInfo from a Nessus plugin ID and optional finding name.

    This gives a fast preliminary detection. The name column refines it.
    """
    info = PlatformInfo(source_tool="nessus")

    platform_entry = _PLUGIN_PLATFORM_MAP.get(plugin_id)
    if platform_entry:
        plat, fam = platform_entry
        if plat:
            info.platform = plat
        if fam:
            info.platform_family = fam

    if name:
        _refine_from_name(name, info)

    return info


def detect_platform_from_text(text: str) -> PlatformInfo:
    """Detect platform from a free-text string (e.g., scan output, OS field)."""
    info = PlatformInfo()
    _detect_os(text, info)
    return info


def detect_benchmark_from_name(name: str) -> PlatformInfo:
    """Detect benchmark name, version, and platform from a Nessus check name.

    The Nessus "Name" column for compliance checks often embeds the
    benchmark origin. This is especially visible in the audit file name
    or the plugin description.
    """
    info = PlatformInfo(source_tool="nessus")
    _refine_from_name(name, info)
    return info


def merge_platform_info(base: PlatformInfo, *others: PlatformInfo) -> PlatformInfo:
    """Merge multiple PlatformInfo objects, keeping the most specific values.

    Later sources override earlier ones only if they provide non-empty values.
    """
    result = PlatformInfo(
        platform=base.platform,
        platform_family=base.platform_family,
        os_version=base.os_version,
        benchmark_name=base.benchmark_name,
        benchmark_version=base.benchmark_version,
        profile_level=base.profile_level,
        hostname=base.hostname,
        ip_address=base.ip_address,
        source_tool=base.source_tool,
        scheme=base.scheme,
    )

    for other in others:
        if other.platform and not result.platform:
            result.platform = other.platform
        if other.platform_family and not result.platform_family:
            result.platform_family = other.platform_family
        if other.os_version and not result.os_version:
            result.os_version = other.os_version
        if other.benchmark_name:
            result.benchmark_name = other.benchmark_name
        if other.benchmark_version:
            result.benchmark_version = other.benchmark_version
        if other.profile_level and not result.profile_level:
            result.profile_level = other.profile_level
        if other.hostname and not result.hostname:
            result.hostname = other.hostname
        if other.ip_address and not result.ip_address:
            result.ip_address = other.ip_address
        if other.source_tool and not result.source_tool:
            result.source_tool = other.source_tool
        if other.scheme and not result.scheme:
            result.scheme = other.scheme

    return result


# ── Build search queries for benchmark matching ──────────────────

def build_benchmark_search_terms(info: PlatformInfo) -> list[str]:
    """Generate a list of search terms for finding a matching benchmark in the DB.

    Returns terms in order of specificity (most specific first).
    """
    terms: list[str] = []

    # Full benchmark name if available
    if info.benchmark_name:
        terms.append(info.benchmark_name)

    # Construct partial names
    if info.platform and info.os_version:
        terms.append(f"{info.platform} {info.os_version}")
    if info.platform:
        terms.append(info.platform)

    return terms


# ── Private helpers ─────────────────────────────────────────────


def _refine_from_name(name: str, info: PlatformInfo) -> None:
    """Extract benchmark/platform info from a Nessus Name column value."""

    # CIS benchmark pattern
    cis_match = re.search(
        r"CIS\s+(.*?)\s+Benchmark\s+v?([\d.]+)",
        name,
        re.IGNORECASE,
    )
    if cis_match:
        product = cis_match.group(1).strip()
        info.benchmark_name = f"CIS {product} Benchmark"
        info.benchmark_version = cis_match.group(2)
        info.scheme = "CIS"
        _detect_os(product, info)
        return

    # CIS without explicit "Benchmark" word — require v-prefix on version to
    # avoid matching year numbers like "2012" in product names
    cis_short = re.search(
        r"CIS\s+((?:Microsoft|Red\s+Hat|Ubuntu|Debian|SUSE|Oracle|Cisco|Docker|Kubernetes|Amazon)\s+.*?)\s+v([\d.]+)",
        name,
        re.IGNORECASE,
    )
    if cis_short:
        product = cis_short.group(1).strip()
        info.benchmark_name = f"CIS {product} Benchmark"
        info.benchmark_version = cis_short.group(2)
        info.scheme = "CIS"
        _detect_os(product, info)
        return

    # DISA STIG pattern
    stig_match = re.search(r"STIG\s+(.*?)\s+v?([\d.]+)", name, re.IGNORECASE)
    if stig_match:
        info.benchmark_name = f"STIG {stig_match.group(1).strip()}"
        info.benchmark_version = stig_match.group(2)
        info.scheme = "STIG"
        _detect_os(stig_match.group(1), info)
        return

    # Audit filename pattern: CIS_MS_SERVER_2012_R2_Level_1_v2.6.0.audit
    # Already normalised by callers but handle common underscore format too
    audit_match = re.search(
        r"CIS\s+(?:Microsoft\s+)?((?:Windows\s+)?(?:Server\s+)?(?:\d{4}(?:\s+R2)?|[\w]+(?:\s+\w+)*))"
        r"\s+(?:Level\s+\d+\s+)?v([\d.]+)",
        name,
        re.IGNORECASE,
    )
    if audit_match:
        product = audit_match.group(1).strip()
        info.benchmark_name = f"CIS Microsoft {product} Benchmark"
        info.benchmark_version = audit_match.group(2)
        info.scheme = "CIS"
        _detect_os(product, info)
        return

    # Generic platform detection from text
    _detect_os(name, info)


def _detect_os(text: str, info: PlatformInfo) -> None:
    """Detect OS/platform from a free-text string."""
    lower = text.lower()

    # Windows variants
    win_match = re.search(
        r"(?:microsoft\s+)?windows\s+(server\s+\d{4}(?:\s+r2)?|1[01]|8\.1?)\s*(enterprise|standalone|member\s+server|domain\s+controller)?",
        lower,
    )
    if win_match:
        info.platform = "Windows"
        info.platform_family = "Windows"
        info.os_version = win_match.group(1).strip().title()
        return

    if "windows" in lower:
        info.platform = "Windows"
        info.platform_family = "Windows"
        return

    # Linux distros
    linux_patterns = [
        (r"ubuntu\s+([\d.]+)", "Ubuntu", "Unix"),
        (r"(?:red\s*hat|rhel)\s+([\d.]+)?", "Red Hat", "Unix"),
        (r"centos\s+([\d.]+)?", "CentOS", "Unix"),
        (r"debian\s+([\d.]+)?", "Debian", "Unix"),
        (r"suse\s+([\d.]+)?", "SUSE", "Unix"),
        (r"amazon\s+linux\s*([\d.]+)?", "Amazon Linux", "Unix"),
        (r"oracle\s+linux\s*([\d.]+)?", "Oracle Linux", "Unix"),
        (r"fedora\s+([\d.]+)?", "Fedora", "Unix"),
    ]
    for pattern, plat_name, family in linux_patterns:
        m = re.search(pattern, lower)
        if m:
            info.platform = plat_name
            info.platform_family = family
            if m.group(1):
                info.os_version = m.group(1)
            return

    if "linux" in lower:
        info.platform = "Linux"
        info.platform_family = "Unix"
        return

    # Network devices
    network_patterns = [
        (r"cisco\s+(ios|asa|nx-?os|firepower)", "Cisco", "Network"),
        (r"juniper\s+(junos|srx)", "Juniper", "Network"),
        (r"palo\s+alto", "Palo Alto", "Network"),
        (r"fortinet|fortigate", "Fortinet", "Network"),
    ]
    for pattern, plat_name, family in network_patterns:
        if re.search(pattern, lower):
            info.platform = plat_name
            info.platform_family = family
            return

    # macOS
    if any(x in lower for x in ("macos", "mac os", "apple", "darwin", "osx")):
        info.platform = "macOS"
        info.platform_family = "Unix"
        return

    # Database platforms
    db_patterns = [
        (r"oracle\s+database|oracle\s+\d+[cgi]", "Oracle", "Database"),
        (r"mysql\s*([\d.]+)?", "MySQL", "Database"),
        (r"postgres(?:ql)?\s*([\d.]+)?", "PostgreSQL", "Database"),
        (r"ms\s*sql|sql\s*server", "MSSQL", "Database"),
        (r"mongodb\s*([\d.]+)?", "MongoDB", "Database"),
    ]
    for pattern, plat_name, family in db_patterns:
        if re.search(pattern, lower):
            info.platform = plat_name
            info.platform_family = family
            return

    # Containers / Cloud
    if "docker" in lower:
        info.platform = "Docker"
        info.platform_family = "Container"
    elif "kubernetes" in lower or "k8s" in lower:
        info.platform = "Kubernetes"
        info.platform_family = "Container"
    elif any(x in lower for x in ("aws", "amazon web")):
        info.platform = "AWS"
        info.platform_family = "Cloud"
    elif "azure" in lower:
        info.platform = "Azure"
        info.platform_family = "Cloud"
    elif any(x in lower for x in ("gcp", "google cloud")):
        info.platform = "GCP"
        info.platform_family = "Cloud"
