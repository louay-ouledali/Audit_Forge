"""Config sanitizer — strips sensitive data before LLM format detection.

Replaces IP addresses with ``10.0.0.X``, hostnames with ``DEVICE-01``,
and secrets/passwords with ``REDACTED``.  Preserves vendor keywords so
the LLM can still identify the config format.
"""

from __future__ import annotations

import re

# Pre-compiled patterns
_IP_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
_SECRET_KEYWORDS = re.compile(
    r"(password|secret|key|community|pre-shared-key|auth-password|"
    r"priv-password|snmp-server community|enable secret|enable password|"
    r"crypto isakmp key)\s+\S+",
    re.IGNORECASE,
)
_HOSTNAME_RE = re.compile(
    r"^(hostname|set hostname|sysname|set system host-name)\s+(\S+)",
    re.IGNORECASE | re.MULTILINE,
)


def sanitize_config(raw_text: str, max_lines: int = 200) -> str:
    """Sanitize a config snippet for safe LLM consumption.

    Parameters
    ----------
    raw_text:
        Raw configuration text.
    max_lines:
        Maximum number of lines to return (from the start).

    Returns
    -------
    Sanitized text with sensitive data replaced.
    """
    lines = raw_text.splitlines()[:max_lines]
    text = "\n".join(lines)

    # Replace hostnames
    _counter = {"ip": 1, "host": 1}

    def _replace_hostname(m: re.Match) -> str:
        prefix = m.group(1)
        idx = _counter["host"]
        _counter["host"] += 1
        return f"{prefix} DEVICE-{idx:02d}"

    text = _HOSTNAME_RE.sub(_replace_hostname, text)

    # Replace secrets/passwords
    def _replace_secret(m: re.Match) -> str:
        keyword = m.group(1)
        return f"{keyword} REDACTED"

    text = _SECRET_KEYWORDS.sub(_replace_secret, text)

    # Replace IP addresses (preserve structure like /24 suffixes)
    ip_map: dict[str, str] = {}

    def _replace_ip(m: re.Match) -> str:
        original = m.group(1)
        # Skip subnet masks (255.x.x.x) and common non-sensitive IPs
        octets = original.split(".")
        if octets[0] == "255" or original in ("0.0.0.0", "127.0.0.1"):
            return original
        if original not in ip_map:
            idx = _counter["ip"]
            _counter["ip"] += 1
            ip_map[original] = f"10.0.0.{idx}"
        return ip_map[original]

    text = _IP_RE.sub(_replace_ip, text)

    return text
