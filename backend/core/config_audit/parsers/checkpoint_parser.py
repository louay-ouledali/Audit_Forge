"""Check Point Gaia OS configuration parser.

Handles ``set``-command format configurations (``clish -c 'show configuration'``).
Simulates ``show configuration`` and ``clish -c`` commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.core.config_audit.parsers.base import (
    BaseConfigParser,
    InterfaceInfo,
    ParsedConfigResult,
    RouteInfo,
    TopologyData,
)

# Commands that require live device
_RUNTIME_COMMANDS = frozenset({
    "fw stat", "fw ver", "cpstat", "cphaprob stat",
    "show asset", "show version", "show uptime",
    "cpca_client", "cpprod_util",
})


@dataclass
class CheckPointParsedConfig(ParsedConfigResult):
    """Check Point-specific parsed config."""
    set_lines: list[str] = field(default_factory=list)
    sections: dict[str, list[str]] = field(default_factory=dict)


class CheckPointConfigParser(BaseConfigParser):

    def parse(self, raw_text: str) -> CheckPointParsedConfig:
        lines = raw_text.splitlines()

        set_lines = []
        sections: dict[str, list[str]] = {}
        hostname = None

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("set "):
                set_lines.append(stripped)

                # Extract section key (first two tokens after "set")
                parts = stripped.split()
                if len(parts) >= 3:
                    section = parts[1]
                    sections.setdefault(section, [])
                    sections[section].append(stripped)

                # Hostname
                m = re.match(r"set hostname\s+(\S+)", stripped)
                if m:
                    hostname = m.group(1)

        return CheckPointParsedConfig(
            format_id="checkpoint",
            hostname=hostname,
            raw_lines=lines,
            set_lines=set_lines,
            sections=sections,
        )

    def simulate(self, command: str, parsed: ParsedConfigResult) -> str | None:
        if not isinstance(parsed, CheckPointParsedConfig):
            return None

        cmd_stripped = command.strip()
        if not cmd_stripped:
            return None

        # Runtime-only
        cmd_lower = cmd_stripped.lower()
        for rt_cmd in _RUNTIME_COMMANDS:
            if cmd_lower.startswith(rt_cmd):
                return None

        base, stages = self._parse_pipeline(cmd_stripped)
        base_lower = base.lower().strip()

        text = self._resolve_base_command(base_lower, base, parsed)
        if text is None:
            return None

        if not stages:
            return text

        return self._apply_stages(text, stages)

    def _resolve_base_command(
        self, base_lower: str, base: str, parsed: CheckPointParsedConfig
    ) -> str | None:
        """Resolve a base command to config text."""

        # "show configuration" (bare) -> all set lines
        if base_lower in ("show configuration", "show config"):
            return "\n".join(parsed.set_lines)

        # "show configuration <section>" -> filtered lines
        m = re.match(r"show\s+configuration\s+(.+)", base, re.IGNORECASE)
        if m:
            section = m.group(1).strip()
            return self._filter_by_section(section, parsed)

        # "clish -c 'show configuration'" -> unwrap
        m = re.match(r"clish\s+-c\s+['\"](.+?)['\"]", base, re.IGNORECASE)
        if m:
            inner = m.group(1).strip()
            return self.simulate(inner, parsed)

        # "show <section>" -> try to return matching set lines
        m = re.match(r"show\s+(.+)", base_lower)
        if m:
            section = m.group(1).strip()
            return self._filter_by_section(section, parsed)

        return None

    def _filter_by_section(
        self, section: str, parsed: CheckPointParsedConfig
    ) -> str | None:
        """Filter set lines by section prefix."""
        section_lower = section.lower()
        matching = [
            sl for sl in parsed.set_lines
            if sl.lower().startswith(f"set {section_lower}")
        ]
        if matching:
            return "\n".join(matching)

        # Partial match
        matching = [
            sl for sl in parsed.set_lines
            if section_lower in sl.lower()
        ]
        if matching:
            return "\n".join(matching)

        return None

    def extract_topology(self, parsed: ParsedConfigResult) -> TopologyData:
        if not isinstance(parsed, CheckPointParsedConfig):
            return TopologyData()

        interfaces: list[InterfaceInfo] = []
        routes: list[RouteInfo] = []
        vpn_peers: list[str] = []

        # Extract interfaces
        # set interface eth0 ipv4-address 10.0.0.1 mask-length 24
        for sl in parsed.set_lines:
            m = re.match(
                r"set interface (\S+) ipv4-address (\S+) mask-length (\d+)", sl
            )
            if m:
                name = m.group(1)
                ip = m.group(2)
                prefix = int(m.group(3))
                mask = self._prefix_to_mask(prefix)
                interfaces.append(InterfaceInfo(name=name, ip=ip, mask=mask))

        # Extract static routes
        # set static-route <dest>/<prefix> nexthop gateway address <gw> on
        for sl in parsed.set_lines:
            m = re.match(
                r"set static-route (\S+)/(\d+) nexthop gateway address (\S+)", sl
            )
            if m:
                network = m.group(1)
                prefix = int(m.group(2))
                mask = self._prefix_to_mask(prefix)
                routes.append(RouteInfo(
                    network=network, mask=mask, gateway=m.group(3),
                ))

        return TopologyData(interfaces=interfaces, routes=routes, vpn_peers=vpn_peers)

    @staticmethod
    def _prefix_to_mask(prefix: int) -> str:
        bits = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
        return f"{(bits >> 24) & 0xFF}.{(bits >> 16) & 0xFF}.{(bits >> 8) & 0xFF}.{bits & 0xFF}"
