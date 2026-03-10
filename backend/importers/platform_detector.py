"""Platform detector — determines OS, benchmark, and scheme from various signals.

Consolidates platform detection logic that can be reused across CSV, HTML,
and future importers. Combines signals from:
- Plugin IDs (Nessus compliance plugin → platform)
- Name patterns (CIS/NIST benchmark names)
- OS strings (from scan info plugins or system metadata)
- Reference codes (LEVEL, framework mappings)
- **Finding content heuristics** (keyword scoring from titles/descriptions)
- **AI-powered analysis** (LLM fallback for ambiguous cases)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING

from backend.importers.base import PlatformInfo

if TYPE_CHECKING:
    from backend.importers.base import ParsedFinding

logger = logging.getLogger("auditforge.importers.platform_detector")


# ── Keyword-based content scoring tables ─────────────────────
# Each entry: (regex_pattern, weight)
# Patterns are evaluated case-insensitively against finding content.

_WINDOWS_KEYWORDS: list[tuple[str, int]] = [
    # Registry paths — very strong signal
    (r"\bHKLM\b|HKEY_LOCAL_MACHINE", 6),
    (r"\bHKCU\b|HKEY_CURRENT_USER", 6),
    (r"\bHKEY_", 5),
    # Group Policy — very strong
    (r"Group\s+Policy", 5),
    (r"gpedit\.msc|secpol\.msc|rsop\.msc", 5),
    (r"Computer\s+Configuration\\", 5),
    (r"Administrative\s+Templates", 4),
    # Windows tools
    (r"\bsecedit\b", 4),
    (r"\bauditpol\b", 4),
    (r"\bnet\s+accounts\b", 4),
    (r"Get-ItemProperty|Set-ItemProperty", 4),
    (r"Windows\s+Components", 3),
    (r"Windows\s+Defender|Windows\s+Firewall", 3),
    (r"\bSystem32\b|SysWOW64", 3),
    (r"\.dll\b|\.exe\b", 2),
    (r"\bPowerShell\b", 2),
    (r"\bcmd\.exe\b", 2),
    (r"\bRegistry\b", 2),
    (r"\bWMI\b|Get-WmiObject|Get-CimInstance", 3),
    (r"Local\s+Security\s+Policy", 4),
    (r"User\s+Rights\s+Assignment", 4),
    (r"\bSe\w+Privilege\b", 4),  # SeNetworkLogonRight, etc.
    (r"Event\s+Viewer|Event\s+Log|Security\s+Log", 2),
    (r"\bmsconfig\b|\btaskmgr\b", 2),
]

_LINUX_KEYWORDS: list[tuple[str, int]] = [
    # Filesystem paths — very strong
    (r"/etc/(?:ssh|pam|audit|sysctl|security|default|login)", 6),
    (r"/etc/(?:passwd|shadow|group|sudoers|fstab|hosts)", 5),
    (r"/var/log/", 4),
    (r"/usr/(?:bin|sbin|lib|share)/", 3),
    # Config files
    (r"\bsshd_config\b", 5),
    (r"\bsysctl\.conf\b|sysctl\.d", 5),
    (r"\bauditd\b|auditctl|audit\.rules", 5),
    (r"\bpam\.d\b|pam_\w+\.so", 5),
    # Commands
    (r"\bsystemctl\b", 4),
    (r"\bjournalctl\b", 4),
    (r"\bchmod\b|\bchown\b|\bchgrp\b", 4),
    (r"\bapt\b|\bapt-get\b|\byum\b|\bdnf\b|\bzypper\b", 3),
    (r"\bgrep\b.*?/etc/|cat\s+/etc/", 3),
    (r"\biptables\b|\bnftables\b|\bufw\b|\bfirewalld\b", 3),
    (r"\bcrontab\b|\bcron\.d\b", 3),
    (r"\bgrub\b|grub\.cfg", 3),
    (r"\bumask\b", 2),
    (r"\bstat\s+-[cfL]", 2),
]

_MACOS_KEYWORDS: list[tuple[str, int]] = [
    (r"\bdefaults\s+(?:read|write)\b", 6),
    (r"com\.apple\.", 6),
    (r"\blaunchctl\b", 5),
    (r"\bplutil\b|\bplistbuddy\b", 5),
    (r"\bprofiles\s+(?:list|show|install)\b", 4),
    (r"\bmacOS\b", 3),
    (r"\bDarwin\b", 3),
    (r"/Library/Preferences/", 4),
    (r"/System/Library/", 3),
]

_NETWORK_KEYWORDS: list[tuple[str, int]] = [
    (r"show\s+running-config", 6),
    (r"show\s+version", 4),
    (r"\benable\s+secret\b", 5),
    (r"\bline\s+vty\b", 5),
    (r"\baccess-list\b", 4),
    (r"\bip\s+route\b", 3),
    (r"\binterface\s+(?:Gi|Fa|Eth|Vlan|Loopback)", 4),
    (r"\bIOS\b.*\bCisco\b|\bCisco\b.*\bIOS\b", 4),
    (r"\bNX-?OS\b|\bJunOS\b", 4),
    (r"\brouter\s+(?:ospf|bgp|eigrp)\b", 4),
    (r"\bvlan\s+\d+\b", 2),
]

_DATABASE_KEYWORDS: list[tuple[str, int]] = [
    (r"\bpg_hba\.conf\b|postgresql\.conf", 6),
    (r"\bmy\.cnf\b|mysqld?\.cnf", 6),
    (r"\bsqlplus\b|tnsnames\.ora|listener\.ora", 6),
    (r"\bSELECT\s+.*\bFROM\s+", 3),
    (r"\bGRANT\b.*\bTO\b|\bREVOKE\b.*\bFROM\b", 3),
    (r"\bsql_mode\b|\binformation_schema\b", 3),
    (r"\binitdb\b|\bpg_ctl\b|\bpostgres\b", 4),
]

_CONTAINER_KEYWORDS: list[tuple[str, int]] = [
    (r"\bdocker\s+(?:run|exec|inspect|ps)\b", 6),
    (r"\bDockerfile\b|docker-compose", 5),
    (r"\bkubectl\b", 6),
    (r"\bkubelet\b|\bkube-apiserver\b", 5),
    (r"\bhelm\b.*\bchart\b", 4),
    (r"\bpod\s+security\b|PodSecurityPolicy", 4),
]

_CLOUD_KEYWORDS: list[tuple[str, int]] = [
    (r"\baws\s+(?:s3|ec2|iam|lambda|rds)\b", 6),
    (r"\baz\s+(?:vm|storage|network|ad)\b", 6),
    (r"\bgcloud\s+", 6),
    (r"\bIAM\s+(?:policy|role|user)\b", 3),
    (r"\bS3\s+bucket\b|\bCloudTrail\b|\bCloudWatch\b", 4),
    (r"\bAzure\s+(?:AD|Active Directory|Policy)\b", 4),
]

# Platform family → keyword table and platform name
_PLATFORM_KEYWORD_TABLES: list[tuple[str, str, str, list[tuple[str, int]]]] = [
    # (platform, platform_family, label, keywords)
    ("Windows", "Windows", "Windows", _WINDOWS_KEYWORDS),
    ("Linux", "Unix", "Linux/Unix", _LINUX_KEYWORDS),
    ("macOS", "Unix", "macOS", _MACOS_KEYWORDS),
    ("Cisco", "Network", "Network Device", _NETWORK_KEYWORDS),
    ("PostgreSQL", "Database", "Database", _DATABASE_KEYWORDS),
    ("Docker", "Container", "Container", _CONTAINER_KEYWORDS),
    ("AWS", "Cloud", "Cloud", _CLOUD_KEYWORDS),
]

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

    # DISA STIG without version
    stig_no_ver = re.search(
        r"(?:DISA\s+)?STIG\s+(.*?)(?:\s+Benchmark|\s+v\d|\s*$)",
        name,
        re.IGNORECASE,
    )
    if stig_no_ver and not stig_match:
        product = stig_no_ver.group(1).strip()
        if product:
            info.benchmark_name = f"STIG {product}"
            info.scheme = "STIG"
            _detect_os(product, info)
            return

    # NIST SP 800-53 pattern
    nist_match = re.search(
        r"NIST\s+(?:SP\s+)?800-53\s*(?:Rev\.?\s*(\d+))?\s*(?:v?([\d.]+))?",
        name,
        re.IGNORECASE,
    )
    if nist_match:
        rev = nist_match.group(1) or "5"
        info.benchmark_name = f"NIST SP 800-53 Rev {rev}"
        if nist_match.group(2):
            info.benchmark_version = nist_match.group(2)
        info.scheme = "NIST"
        return

    # ISO 27001/27002 pattern
    iso_match = re.search(
        r"ISO\s+(?:IEC\s+)?2700[12](?::(\d{4}))?",
        name,
        re.IGNORECASE,
    )
    if iso_match:
        year = iso_match.group(1) or "2022"
        info.benchmark_name = f"ISO 27001:{year}"
        info.benchmark_version = year
        info.scheme = "ISO"
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
        version_str = win_match.group(1).strip().title()
        if version_str.lower().startswith("server"):
            info.platform = "Windows Server"
        else:
            info.platform = "Windows"
        info.platform_family = "Windows"
        info.os_version = version_str
        return

    if "windows server" in lower:
        info.platform = "Windows Server"
        info.platform_family = "Windows"
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


# ── Content-based heuristic platform detection ───────────────

# Minimum confidence ratio (winner_score / total_score) to accept a heuristic result
_HEURISTIC_MIN_CONFIDENCE = 0.40
# Minimum absolute score to accept
_HEURISTIC_MIN_SCORE = 8


def detect_platform_from_findings(findings: "list[ParsedFinding]") -> PlatformInfo:
    """Detect platform by scanning finding content for platform-specific keywords.

    Analyses a sample of finding titles, descriptions, solutions, policy_values,
    and actual_values using weighted keyword scoring. This is fast (pure regex,
    no network/LLM calls) and accurate for 95%+ of real-world reports.

    Returns a PlatformInfo with ``platform`` and ``platform_family`` set when
    detection confidence is high enough, or empty strings when inconclusive.
    """
    info = PlatformInfo()

    if not findings:
        return info

    # Build text corpus from a sample of findings (up to 50 for efficiency)
    sample = findings[:50] if len(findings) > 50 else findings
    corpus_parts: list[str] = []
    for f in sample:
        for field in (f.title, f.description, f.solution, f.policy_value, f.actual_value):
            if field:
                corpus_parts.append(field)
    corpus = "\n".join(corpus_parts)

    if not corpus:
        return info

    # Score each platform family
    scores: dict[str, int] = {}
    for platform, family, label, keywords in _PLATFORM_KEYWORD_TABLES:
        score = 0
        for pattern, weight in keywords:
            matches = re.findall(pattern, corpus, re.IGNORECASE)
            score += len(matches) * weight
        if score > 0:
            scores[label] = score

    if not scores:
        logger.debug("Content heuristic: no platform keywords found in %d findings", len(sample))
        return info

    total = sum(scores.values())
    winner_label = max(scores, key=scores.get)  # type: ignore[arg-type]
    winner_score = scores[winner_label]
    confidence = winner_score / total if total > 0 else 0

    logger.info(
        "Content heuristic scores: %s → winner='%s' (score=%d, confidence=%.0f%%)",
        {k: v for k, v in sorted(scores.items(), key=lambda x: -x[1])},
        winner_label, winner_score, confidence * 100,
    )

    if winner_score < _HEURISTIC_MIN_SCORE:
        logger.info("Content heuristic: score %d below threshold %d, inconclusive", winner_score, _HEURISTIC_MIN_SCORE)
        return info

    if confidence < _HEURISTIC_MIN_CONFIDENCE:
        logger.info(
            "Content heuristic: confidence %.0f%% below threshold %.0f%%, inconclusive",
            confidence * 100, _HEURISTIC_MIN_CONFIDENCE * 100,
        )
        return info

    # Map the winner label back to platform/family
    for platform, family, label, _ in _PLATFORM_KEYWORD_TABLES:
        if label == winner_label:
            info.platform = platform
            info.platform_family = family
            break

    # Refine: if winner is Windows, check whether it's Windows Server
    if info.platform == "Windows":
        server_signals = len(re.findall(
            r"\bwindows\s+server\b|\bserver\s+\d{4}\b|\bmember\s+server\b|\bdomain\s+controller\b",
            corpus, re.IGNORECASE,
        ))
        if server_signals >= 2:
            info.platform = "Windows Server"

    # Try to detect specific OS version from the corpus
    if info.platform and not info.os_version:
        temp = PlatformInfo()
        _detect_os(corpus, temp)
        if temp.os_version:
            info.os_version = temp.os_version
        # Also promote platform to Server when os_version says so
        if temp.platform and "Server" in temp.platform and "Server" not in info.platform:
            info.platform = temp.platform

    return info


# ── AI-powered platform detection ────────────────────────────

_AI_PLATFORM_SYSTEM_PROMPT = """You are a security audit platform detector. Analyse the provided sample of compliance audit finding titles and determine the target platform.

Return a JSON object with exactly these keys:
- platform: string (e.g. "Windows", "Linux", "macOS", "Cisco", "PostgreSQL", "Docker", "AWS")
- platform_family: string (one of: "Windows", "Unix", "Network", "Database", "Container", "Cloud", "other")
- os_version: string or null (e.g. "Server 2012 R2", "11 Enterprise", "22.04", null)
- benchmark_name: string or null (e.g. "CIS Microsoft Windows 11 Enterprise Benchmark", null)
- benchmark_version: string or null (e.g. "3.0.0", null)
- confidence: string (one of: "high", "medium", "low")

Only use information visible in the finding titles. Do NOT guess.
Example: {"platform":"Windows","platform_family":"Windows","os_version":"Server 2019","benchmark_name":"CIS Microsoft Windows Server 2019 Benchmark","benchmark_version":null,"confidence":"high"}"""


def detect_platform_with_ai(findings: "list[ParsedFinding]") -> PlatformInfo:
    """Use the configured LLM to detect platform from finding content.

    Sends a compact sample of finding titles to the LLM and parses the
    structured JSON response into a PlatformInfo.

    This is called as a fallback when heuristic detection is inconclusive.
    Handles the sync→async bridge internally.
    """
    info = PlatformInfo()

    if not findings:
        return info

    # Build a compact sample of finding titles (first 30)
    sample = findings[:30] if len(findings) > 30 else findings
    titles = []
    for f in sample:
        line = f"""{f.section_number} {f.title}"""
        if f.description:
            # Include first 100 chars of description for more context
            desc_snippet = f.description[:100].replace("\n", " ")
            line += f" | {desc_snippet}"
        titles.append(line)

    prompt = "Analyse these compliance audit finding titles and detect the target platform:\n\n" + "\n".join(titles)

    try:
        from backend.ai.llm_manager import llm_manager

        # Bridge sync→async: try to get the running event loop; if none, create one
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're inside an async context (e.g. FastAPI) — run in a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    asyncio.run,
                    llm_manager.invoke_json(
                        prompt,
                        system_prompt=_AI_PLATFORM_SYSTEM_PROMPT,
                        timeout=60.0,
                        task="analysis",
                    ),
                ).result(timeout=90)
        else:
            result = asyncio.run(
                llm_manager.invoke_json(
                    prompt,
                    system_prompt=_AI_PLATFORM_SYSTEM_PROMPT,
                    timeout=60.0,
                    task="analysis",
                )
            )

        if isinstance(result, list):
            result = result[0] if result else {}
        if not isinstance(result, dict):
            logger.warning("AI platform detection returned unexpected type: %s", type(result))
            return info

        logger.info(
            "AI platform detection result: platform=%s, family=%s, os=%s, benchmark=%s, confidence=%s",
            result.get("platform"), result.get("platform_family"),
            result.get("os_version"), result.get("benchmark_name"),
            result.get("confidence"),
        )

        if result.get("platform"):
            info.platform = result["platform"]
        if result.get("platform_family"):
            info.platform_family = result["platform_family"]
        if result.get("os_version"):
            info.os_version = result["os_version"]
        if result.get("benchmark_name"):
            info.benchmark_name = result["benchmark_name"]
        if result.get("benchmark_version"):
            info.benchmark_version = result["benchmark_version"]

    except Exception as exc:
        logger.warning("AI platform detection failed (non-fatal): %s", exc)

    return info


def enrich_platform_info(
    platform_info: PlatformInfo,
    findings: "list[ParsedFinding]",
    *,
    use_ai: bool = True,
) -> PlatformInfo:
    """Three-layer platform enrichment — the main entry point.

    Called after parsing to ensure platform detection works even when the
    audit filename is generic or missing.

    Layers (in order):
    1. **Content heuristic** — scan finding content for keyword patterns
       (always runs to validate / correct the parser's initial detection)
    2. **AI fallback** — ask the LLM to analyse finding titles (optional,
       only when heuristic is inconclusive)
    3. **Current info** — keep parser's detection as the baseline

    The content heuristic OVERRIDES the parser's platform when:
    - The parser found NO platform
    - The heuristic disagrees with the parser (content is ground truth)

    Benchmark name/version from the parser are always preserved since
    the heuristic doesn't attempt benchmark identification.
    """
    # Layer 1: Always run the content heuristic (validates parser detection)
    heuristic_info = detect_platform_from_findings(findings)

    if heuristic_info.platform:
        # Heuristic found a platform — check for agreement/conflict
        if not platform_info.platform:
            # Parser found nothing → use heuristic
            logger.info(
                "Heuristic fills missing platform: %s / %s",
                heuristic_info.platform, heuristic_info.platform_family,
            )
            platform_info = merge_platform_info(platform_info, heuristic_info)
        elif platform_info.platform_family != heuristic_info.platform_family:
            # CONFLICT: parser says one family, content says another
            # Content is ground truth — override
            logger.warning(
                "Platform CONFLICT: parser detected '%s/%s' but content "
                "heuristic detected '%s/%s' — trusting content (ground truth)",
                platform_info.platform, platform_info.platform_family,
                heuristic_info.platform, heuristic_info.platform_family,
            )
            platform_info.platform = heuristic_info.platform
            platform_info.platform_family = heuristic_info.platform_family
            if heuristic_info.os_version and not platform_info.os_version:
                platform_info.os_version = heuristic_info.os_version
        else:
            logger.info(
                "Platform confirmed by heuristic: %s / %s",
                platform_info.platform, platform_info.platform_family,
            )

    # If still no platform, try AI fallback
    if use_ai and (not platform_info.platform or not platform_info.platform_family):
        logger.info("Heuristic inconclusive — invoking AI platform detection")
        ai_info = detect_platform_with_ai(findings)
        if ai_info.platform:
            logger.info(
                "AI enrichment: platform=%s, family=%s, benchmark=%s",
                ai_info.platform, ai_info.platform_family, ai_info.benchmark_name,
            )
            platform_info = merge_platform_info(platform_info, ai_info)

    if not platform_info.platform:
        logger.warning(
            "Platform detection failed: all layers returned no result for %d findings",
            len(findings),
        )

    return platform_info
