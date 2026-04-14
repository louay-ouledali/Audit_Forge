"""Juniper JunOS configuration parser.

Handles both brace-format (``{ ... }``) and set-format configurations.
Simulates ``show configuration [path]`` commands with pipeline stages
including ``| display set``, ``| match``, ``| except``, ``| count``.
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
    "show interfaces terse",
    "show route",
    "show system uptime",
    "show system alarm",
    "show chassis",
    "show version",
    "show bgp summary",
    "show ospf neighbor",
    "show security flow",
    "show log",
})


@dataclass
class JunOSParsedConfig(ParsedConfigResult):
    """JunOS-specific parsed config."""
    set_lines: list[str] = field(default_factory=list)
    brace_text: str = ""
    sections: dict[str, str] = field(default_factory=dict)


class JunOSConfigParser(BaseConfigParser):

    def parse(self, raw_text: str) -> JunOSParsedConfig:
        lines = raw_text.splitlines()

        # Detect format: set-format vs brace-format
        set_count = sum(1 for l in lines if l.strip().startswith("set "))
        brace_count = sum(1 for l in lines if "{" in l or "}" in l)

        if set_count > brace_count:
            # Set format
            set_lines = [l.strip() for l in lines if l.strip().startswith("set ")]
            brace_text = self._set_to_brace(set_lines)
        else:
            # Brace format — convert to set format for uniform querying
            brace_text = raw_text
            set_lines = self._brace_to_set(lines)

        # Extract hostname
        hostname = None
        for sl in set_lines:
            m = re.match(r"set system host-name\s+(\S+)", sl)
            if m:
                hostname = m.group(1)
                break

        # Build sections from set lines
        sections: dict[str, str] = {}
        for sl in set_lines:
            # First two tokens after "set" = top-level section
            m = re.match(r"set\s+(\S+)", sl)
            if m:
                top = m.group(1)
                sections.setdefault(top, [])
                sections[top].append(sl)

        section_text = {k: "\n".join(v) for k, v in sections.items()}

        return JunOSParsedConfig(
            format_id="junos",
            hostname=hostname,
            raw_lines=lines,
            set_lines=set_lines,
            brace_text=brace_text if brace_count > set_count else "",
            sections=section_text,
        )

    def _brace_to_set(self, lines: list[str]) -> list[str]:
        """Convert brace-format config to set-format lines."""
        set_lines: list[str] = []
        path_stack: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("/*"):
                continue

            # Handle "keyword {" on same line
            if stripped.endswith("{"):
                token = stripped[:-1].strip()
                if token:
                    path_stack.append(token)
                continue

            if stripped == "}":
                if path_stack:
                    path_stack.pop()
                continue

            # Lines with embedded braces: "foo { bar baz; }"
            if "{" in stripped and "}" in stripped:
                m = re.match(r"(\S+)\s*\{(.+)\}", stripped)
                if m:
                    prefix = m.group(1)
                    inner = m.group(2).strip().rstrip(";")
                    path = " ".join(path_stack + [prefix])
                    for part in inner.split(";"):
                        part = part.strip()
                        if part:
                            set_lines.append(f"set {path} {part}")
                continue

            # Remove trailing semicolons
            if stripped.endswith(";"):
                stripped = stripped[:-1].strip()

            if stripped and path_stack:
                path = " ".join(path_stack)
                set_lines.append(f"set {path} {stripped}")
            elif stripped:
                set_lines.append(f"set {stripped}")

        return set_lines

    def _set_to_brace(self, set_lines: list[str]) -> str:
        """Convert set-format lines back to approximate brace format."""
        # Simplified: just return the set lines as-is since most
        # simulation works on set_lines directly
        return "\n".join(set_lines)

    def simulate(self, command: str, parsed: ParsedConfigResult) -> str | None:
        if not isinstance(parsed, JunOSParsedConfig):
            return None

        cmd_stripped = command.strip()
        if not cmd_stripped:
            return None

        # Runtime-only
        base_lower = cmd_stripped.lower().split("|")[0].strip()
        for rt_cmd in _RUNTIME_COMMANDS:
            if base_lower.startswith(rt_cmd):
                return None

        # Only handle "show configuration" commands
        if not base_lower.startswith("show configuration"):
            return None

        base, stages = self._parse_pipeline(cmd_stripped)
        base_lower = base.lower().strip()

        # Check if "display set" is in the pipeline
        display_set = False
        remaining_stages = []
        for stype, sarg in stages:
            if stype == "display" and sarg.lower() == "set":
                display_set = True
            else:
                remaining_stages.append((stype, sarg))

        # Extract config path from base command
        m = re.match(r"show\s+configuration\s*(.*)", base, re.IGNORECASE)
        config_path = m.group(1).strip() if m else ""

        # Get the relevant text
        if display_set or not parsed.brace_text:
            # Use set-format lines
            text = self._get_set_text(config_path, parsed)
        else:
            # Use brace-format (extract section from brace_text)
            text = self._get_brace_text(config_path, parsed)

        if text is None:
            # Fall back to set lines filtered by path
            text = self._get_set_text(config_path, parsed)

        if text is None:
            return None

        if not remaining_stages:
            return text

        return self._apply_junos_stages(text, remaining_stages)

    def _get_set_text(self, path: str, parsed: JunOSParsedConfig) -> str | None:
        """Get set-format text for a config path."""
        if not path:
            return "\n".join(parsed.set_lines)

        # Filter set lines by path
        path_lower = path.lower()
        path_parts = path_lower.split()
        matching = []

        for sl in parsed.set_lines:
            sl_lower = sl.lower()
            # "set <path> ..." matches if set line starts with "set <path_parts>"
            prefix = "set " + " ".join(path_parts)
            if sl_lower.startswith(prefix):
                matching.append(sl)

        if matching:
            return "\n".join(matching)
        return None

    def _get_brace_text(self, path: str, parsed: JunOSParsedConfig) -> str | None:
        """Extract a section from brace-format text."""
        if not path:
            return parsed.brace_text

        # Simple extraction: look for the path as a section header
        lines = parsed.brace_text.splitlines()
        path_parts = path.split()
        in_section = False
        depth = 0
        result: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not in_section:
                # Check if this line starts the section we want
                if self._line_matches_path(stripped, path_parts):
                    in_section = True
                    depth = 1
                    result.append(line)
                    continue
            else:
                result.append(line)
                if "{" in stripped:
                    depth += stripped.count("{")
                if "}" in stripped:
                    depth -= stripped.count("}")
                if depth <= 0:
                    break

        if result:
            return "\n".join(result)
        return None

    @staticmethod
    def _line_matches_path(line: str, path_parts: list[str]) -> bool:
        """Check if a line contains all path parts in order."""
        line_lower = line.lower().rstrip(" {")
        tokens = line_lower.split()
        idx = 0
        for part in path_parts:
            found = False
            while idx < len(tokens):
                if tokens[idx] == part:
                    found = True
                    idx += 1
                    break
                idx += 1
            if not found:
                return False
        return True

    def _apply_junos_stages(
        self, text: str, stages: list[tuple[str, str]]
    ) -> str | None:
        """Apply JunOS-specific pipeline stages."""
        lines = text.splitlines()

        for stage_type, arg in stages:
            if stage_type in ("match", "include", "grep"):
                try:
                    rx = re.compile(arg, re.IGNORECASE)
                    lines = [l for l in lines if rx.search(l)]
                except re.error:
                    lines = [l for l in lines if arg.lower() in l.lower()]

            elif stage_type in ("except", "exclude"):
                try:
                    rx = re.compile(arg, re.IGNORECASE)
                    lines = [l for l in lines if not rx.search(l)]
                except re.error:
                    lines = [l for l in lines if arg.lower() not in l.lower()]

            elif stage_type == "count":
                return f"Count: {len(lines)} lines"

            elif stage_type == "find":
                # Like "begin" — start from first match
                found = False
                new_lines: list[str] = []
                for l in lines:
                    if not found and arg.lower() in l.lower():
                        found = True
                    if found:
                        new_lines.append(l)
                lines = new_lines

            else:
                return None

        return "\n".join(lines)

    def extract_topology(self, parsed: ParsedConfigResult) -> TopologyData:
        if not isinstance(parsed, JunOSParsedConfig):
            return TopologyData()

        interfaces: list[InterfaceInfo] = []
        routes: list[RouteInfo] = []
        vpn_peers: list[str] = []

        # Extract interfaces from set lines
        iface_ips: dict[str, tuple[str | None, str | None]] = {}
        iface_desc: dict[str, str] = {}

        for sl in parsed.set_lines:
            # set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24
            m = re.match(
                r"set interfaces (\S+) unit (\d+) family inet address (\S+)", sl
            )
            if m:
                name = f"{m.group(1)}.{m.group(2)}"
                addr = m.group(3)
                ip = addr.split("/")[0] if "/" in addr else addr
                prefix = int(addr.split("/")[1]) if "/" in addr else 32
                mask = self._prefix_to_mask(prefix)
                iface_ips[name] = (ip, mask)

            # set interfaces ge-0/0/0 description "..."
            m = re.match(r'set interfaces (\S+) description "?([^"]+)"?', sl)
            if m:
                iface_desc[m.group(1)] = m.group(2).strip()

        for name, (ip, mask) in iface_ips.items():
            base_name = name.split(".")[0]
            interfaces.append(InterfaceInfo(
                name=name, ip=ip, mask=mask,
                description=iface_desc.get(base_name),
            ))

        # Extract static routes
        for sl in parsed.set_lines:
            # set routing-options static route 0.0.0.0/0 next-hop 10.0.0.1
            m = re.match(
                r"set routing-options static route (\S+) next-hop (\S+)", sl
            )
            if m:
                dest = m.group(1)
                network = dest.split("/")[0] if "/" in dest else dest
                mask_str = ""
                if "/" in dest:
                    mask_str = self._prefix_to_mask(int(dest.split("/")[1]))
                routes.append(RouteInfo(
                    network=network, mask=mask_str, gateway=m.group(2),
                ))

        # Extract IKE gateways (VPN peers)
        for sl in parsed.set_lines:
            m = re.match(r"set security ike gateway \S+ address (\S+)", sl)
            if m:
                vpn_peers.append(m.group(1))

        return TopologyData(interfaces=interfaces, routes=routes, vpn_peers=vpn_peers)

    @staticmethod
    def _prefix_to_mask(prefix: int) -> str:
        bits = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
        return f"{(bits >> 24) & 0xFF}.{(bits >> 16) & 0xFF}.{(bits >> 8) & 0xFF}.{bits & 0xFF}"
