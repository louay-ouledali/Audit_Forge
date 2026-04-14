"""Platform family normalization — single source of truth.

Consolidates the various "Unix"→"linux", "Windows"→"windows" mappings
scattered across command_templates, phase2_enricher, verification_engine, etc.
"""

from __future__ import annotations

# Canonical family names (lowercase)
_ALIASES: dict[str, str] = {
    "unix": "linux",
    "macos": "linux",
    "mac": "linux",
    "darwin": "linux",
    "redhat": "linux",
    "centos": "linux",
    "ubuntu": "linux",
    "debian": "linux",
    "suse": "linux",
    "amazon linux": "linux",
    "win": "windows",
    "microsoft": "windows",
    "mssql": "database",
    "sql server": "database",
    "postgresql": "database",
    "postgres": "database",
    "mysql": "database",
    "mariadb": "database",
    "oracle db": "database",
    "mongodb": "database",
    "cassandra": "database",
    "cisco": "network",
    "juniper": "network",
    "paloalto": "network",
    "palo alto": "network",
    "fortinet": "network",
    "fortigate": "network",
    "docker": "container",
    "kubernetes": "container",
    "k8s": "container",
    "aws": "cloud",
    "azure": "cloud",
    "gcp": "cloud",
    "google cloud": "cloud",
    "vmware": "other",
    "esxi": "other",
}

VALID_FAMILIES = frozenset({
    "linux", "windows", "network", "database",
    "container", "cloud", "middleware", "other",
})


def normalize_platform_family(raw: str | None, default: str = "linux") -> str:
    """Return a canonical lowercase platform family string.

    >>> normalize_platform_family("Unix")
    'linux'
    >>> normalize_platform_family("Windows")
    'windows'
    >>> normalize_platform_family(None)
    'linux'
    """
    if not raw:
        return default
    lowered = raw.strip().lower()
    if lowered in VALID_FAMILIES:
        return lowered
    return _ALIASES.get(lowered, default)
