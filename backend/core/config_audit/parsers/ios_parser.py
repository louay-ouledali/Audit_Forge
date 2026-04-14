"""Cisco IOS / ASA / NX-OS configuration parser.

Uses ``ciscoconfparse2`` for config section extraction and provides
full pipeline simulation for ``| include``, ``| exclude``, ``| section``,
``| begin``, and ``| count``.
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

# Runtime-only commands that require live device access
_RUNTIME_COMMANDS = frozenset({
    "show version",
    "show failover",
    "show crypto key mypubkey rsa",
    "show crypto key mypubkey",
    "show interface ip brief",
    "show ip interface brief",
    "show int ip brief",
    "show clock",
    "show logging",
    "show ntp status",
    "show ntp associations",
    "show processes",
    "show environment",
    "show inventory",
    "show access-lists",
    "show ip access-lists",
    "show snmp",
})


@dataclass
class IOSParsedConfig(ParsedConfigResult):
    """IOS-specific parsed config with ciscoconfparse2 object."""
    confparse: object = None  # CiscoConfParse instance (typed loosely to avoid import-time dep)
    sections: dict[str, str] = field(default_factory=dict)


class IOSConfigParser(BaseConfigParser):

    def parse(self, raw_text: str) -> IOSParsedConfig:
        lines = raw_text.splitlines()

        # Extract hostname
        hostname = None
        for line in lines:
            m = re.match(r"^hostname\s+(\S+)", line)
            if m:
                hostname = m.group(1)
                break

        ccp = None
        sections: dict[str, str] = {}

        try:
            from ciscoconfparse2 import CiscoConfParse
            ccp = CiscoConfParse(lines)

            # Extract named sections (parent objects that start with specific keywords)
            for keyword in ("interface", "router", "crypto", "policy-map",
                            "class-map", "object-group", "access-list", "line"):
                try:
                    parents = ccp.find_objects(rf"^{keyword}\s")
                    for parent in parents:
                        section_name = parent.text.strip()
                        child_lines = [c.text for c in parent.children]
                        sections[section_name] = "\n".join([parent.text] + child_lines)
                except Exception:
                    continue
        except ImportError:
            # Fallback: extract sections with simple indent-based parsing
            sections = self._extract_sections_simple(lines)

        return IOSParsedConfig(
            format_id="ios",
            hostname=hostname,
            raw_lines=lines,
            confparse=ccp,
            sections=sections,
        )

    @staticmethod
    def _extract_sections_simple(lines: list[str]) -> dict[str, str]:
        """Simple indent-based section extraction when ciscoconfparse2 is unavailable."""
        sections: dict[str, str] = {}
        current_parent: str | None = None
        current_lines: list[str] = []
        for line in lines:
            stripped = line.rstrip()
            if stripped == "!" or stripped == "":
                if current_parent:
                    sections[current_parent] = "\n".join(current_lines)
                    current_parent = None
                    current_lines = []
                continue
            if not line.startswith((" ", "\t")) and stripped:
                if current_parent:
                    sections[current_parent] = "\n".join(current_lines)
                current_parent = stripped
                current_lines = [stripped]
            elif current_parent:
                current_lines.append(stripped)
        if current_parent:
            sections[current_parent] = "\n".join(current_lines)
        return sections

    def simulate(self, command: str, parsed: ParsedConfigResult) -> str | None:
        if not isinstance(parsed, IOSParsedConfig):
            return None

        cmd_stripped = command.strip()
        if not cmd_stripped:
            return None

        # Check if this is a runtime-only command
        base_lower = cmd_stripped.lower().split("|")[0].strip()
        for rt_cmd in _RUNTIME_COMMANDS:
            if base_lower.startswith(rt_cmd):
                return None

        # Only handle "show" commands for config simulation
        if not base_lower.startswith("show "):
            return None

        base, stages = self._parse_pipeline(cmd_stripped)
        base_lower = base.lower().strip()

        # Resolve the initial text based on the base command
        text = self._resolve_base_command(base_lower, base, parsed)
        if text is None:
            return None

        # Process stages
        if not stages:
            return text

        return self._apply_ios_stages(text, stages, parsed)

    def _resolve_base_command(
        self, base_lower: str, base: str, parsed: IOSParsedConfig
    ) -> str | None:
        """Resolve the base 'show' command to config text."""
        # show running-config / show run (bare)
        if base_lower in ("show running-config", "show run", "show startup-config"):
            return "\n".join(parsed.raw_lines)

        # show run <subsection> — e.g., "show run interface GigabitEthernet0/0"
        m = re.match(r"show\s+(?:running-config|run)\s+(.+)", base, re.IGNORECASE)
        if m:
            subsection = m.group(1).strip()
            return self._extract_section(subsection, parsed)

        # show ip route → runtime only (routing table is dynamic)
        if "show ip route" in base_lower:
            return None

        # show running-config variants handled above; any other "show" → None
        return None

    def _extract_section(self, name: str, parsed: IOSParsedConfig) -> str | None:
        """Extract a named section from the config."""
        # Try exact match in sections dict
        for section_name, section_text in parsed.sections.items():
            if section_name.lower() == name.lower() or section_name.lower().startswith(name.lower()):
                return section_text

        # Try ciscoconfparse2 find
        try:
            ccp = parsed.confparse
            parents = ccp.find_objects(rf"^{re.escape(name)}")
            if parents:
                parent = parents[0]
                child_lines = [c.text for c in parent.children]
                return "\n".join([parent.text] + child_lines)
        except Exception:
            pass

        return None

    def _apply_ios_stages(
        self, text: str, stages: list[tuple[str, str]], parsed: IOSParsedConfig
    ) -> str | None:
        """Apply IOS-specific pipeline stages."""
        lines = text.splitlines()

        for stage_type, arg in stages:
            if stage_type in ("include", "match", "grep"):
                try:
                    rx = re.compile(arg, re.IGNORECASE)
                    lines = [l for l in lines if rx.search(l)]
                except re.error:
                    lines = [l for l in lines if arg.lower() in l.lower()]

            elif stage_type in ("exclude", "except"):
                try:
                    rx = re.compile(arg, re.IGNORECASE)
                    lines = [l for l in lines if not rx.search(l)]
                except re.error:
                    lines = [l for l in lines if arg.lower() not in l.lower()]

            elif stage_type == "section":
                # Extract the named section from confparse
                section_text = self._extract_section(arg, parsed)
                if section_text:
                    lines = section_text.splitlines()
                else:
                    lines = []

            elif stage_type == "begin":
                found = False
                new_lines: list[str] = []
                try:
                    rx = re.compile(arg, re.IGNORECASE)
                except re.error:
                    rx = None
                for l in lines:
                    if not found:
                        if rx and rx.search(l):
                            found = True
                        elif not rx and arg.lower() in l.lower():
                            found = True
                    if found:
                        new_lines.append(l)
                lines = new_lines

            elif stage_type == "count":
                return str(len(lines))

            else:
                return None

        return "\n".join(lines)

    def extract_topology(self, parsed: ParsedConfigResult) -> TopologyData:
        if not isinstance(parsed, IOSParsedConfig):
            return TopologyData()

        interfaces: list[InterfaceInfo] = []
        routes: list[RouteInfo] = []
        vpn_peers: list[str] = []

        # Extract interfaces
        for section_name, section_text in parsed.sections.items():
            if not section_name.lower().startswith("interface "):
                continue
            iface_name = section_name.split(None, 1)[1] if " " in section_name else section_name
            ip = mask = nameif = description = None
            security_level = None
            status = "up"

            for line in section_text.splitlines():
                line = line.strip()
                m = re.match(r"ip address (\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)", line)
                if m:
                    ip, mask = m.group(1), m.group(2)
                m = re.match(r"nameif\s+(\S+)", line)
                if m:
                    nameif = m.group(1)
                m = re.match(r"security-level\s+(\d+)", line)
                if m:
                    security_level = int(m.group(1))
                m = re.match(r"description\s+(.+)", line)
                if m:
                    description = m.group(1).strip()
                if line.lower() == "shutdown":
                    status = "down"

            interfaces.append(InterfaceInfo(
                name=iface_name, nameif=nameif, ip=ip, mask=mask,
                status=status, security_level=security_level, description=description,
            ))

        # Extract static routes
        for line in parsed.raw_lines:
            m = re.match(
                r"ip route (\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)",
                line.strip()
            )
            if m:
                routes.append(RouteInfo(
                    network=m.group(1), mask=m.group(2), gateway=m.group(3),
                ))
            # ASA route format: route <nameif> <net> <mask> <gw>
            m = re.match(
                r"route\s+\S+\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)",
                line.strip()
            )
            if m:
                routes.append(RouteInfo(
                    network=m.group(1), mask=m.group(2), gateway=m.group(3),
                ))

        # Extract VPN peers
        for line in parsed.raw_lines:
            m = re.match(r".*(?:set peer|tunnel-group)\s+(\d+\.\d+\.\d+\.\d+)", line.strip())
            if m:
                vpn_peers.append(m.group(1))

        return TopologyData(interfaces=interfaces, routes=routes, vpn_peers=vpn_peers)
