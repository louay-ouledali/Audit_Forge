"""FortiOS (FortiGate) configuration parser.

Handles ``config...end`` block structure and simulates ``get`` / ``show``
commands used by FortiGate CIS benchmark rules.
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

# Commands that require live device (cannot be answered from config)
_RUNTIME_COMMANDS = frozenset({
    "diagnose", "diag", "execute", "fnsysctl",
})


@dataclass
class _ConfigBlock:
    """A parsed ``config ... end`` block."""
    path: str  # e.g. "system global"
    entries: dict[str, str]  # set key -> value (flat) or sub-blocks
    raw_text: str


@dataclass
class FortiOSParsedConfig(ParsedConfigResult):
    """FortiOS-specific parsed config."""
    blocks: dict[str, _ConfigBlock] = field(default_factory=dict)
    edits: dict[str, list[dict[str, str]]] = field(default_factory=dict)


class FortiOSConfigParser(BaseConfigParser):

    def parse(self, raw_text: str) -> FortiOSParsedConfig:
        lines = raw_text.splitlines()

        hostname = None
        blocks: dict[str, _ConfigBlock] = {}
        edits: dict[str, list[dict[str, str]]] = {}

        # State machine for parsing config...end blocks
        block_stack: list[str] = []
        current_path: str | None = None
        current_lines: list[str] = []
        current_settings: dict[str, str] = {}
        edit_name: str | None = None
        edit_entries: list[dict[str, str]] = []
        edit_settings: dict[str, str] = {}

        for line in lines:
            stripped = line.strip()

            # config <path>
            m = re.match(r"^config\s+(.+)", stripped)
            if m:
                path_part = m.group(1).strip()
                if current_path is None:
                    current_path = path_part
                    current_lines = [stripped]
                    current_settings = {}
                    edit_entries = []
                else:
                    # Nested block — just capture lines
                    current_lines.append(stripped)
                block_stack.append(path_part)
                continue

            # end
            if stripped == "end":
                if block_stack:
                    block_stack.pop()
                if not block_stack and current_path is not None:
                    # Close edit if open
                    if edit_name is not None:
                        edit_entries.append(edit_settings.copy())
                        edit_name = None
                        edit_settings = {}

                    current_lines.append(stripped)
                    blocks[current_path] = _ConfigBlock(
                        path=current_path,
                        entries=current_settings.copy(),
                        raw_text="\n".join(current_lines),
                    )
                    if edit_entries:
                        edits[current_path] = edit_entries
                    current_path = None
                    current_lines = []
                    current_settings = {}
                    edit_entries = []
                else:
                    current_lines.append(stripped)
                continue

            # next (end of edit block)
            if stripped == "next":
                if edit_name is not None:
                    edit_entries.append(edit_settings.copy())
                    edit_name = None
                    edit_settings = {}
                current_lines.append(stripped)
                continue

            # edit "<name>"
            m = re.match(r'^edit\s+"?([^"]+)"?', stripped)
            if m:
                if edit_name is not None:
                    edit_entries.append(edit_settings.copy())
                edit_name = m.group(1)
                edit_settings = {"_name": edit_name}
                current_lines.append(stripped)
                continue

            # set <key> <value>
            m = re.match(r"^set\s+(\S+)\s+(.*)", stripped)
            if m:
                key, value = m.group(1), m.group(2).strip().strip('"')
                if edit_name is not None:
                    edit_settings[key] = value
                elif current_path is not None:
                    current_settings[key] = value
                current_lines.append(stripped)
                continue

            # unset <key>
            m = re.match(r"^unset\s+(\S+)", stripped)
            if m:
                key = m.group(1)
                if edit_name is not None:
                    edit_settings[key] = ""
                elif current_path is not None:
                    current_settings[key] = ""
                current_lines.append(stripped)
                continue

            current_lines.append(stripped)

        # Extract hostname from system global
        global_block = blocks.get("system global")
        if global_block and "hostname" in global_block.entries:
            hostname = global_block.entries["hostname"]

        return FortiOSParsedConfig(
            format_id="fortios",
            hostname=hostname,
            raw_lines=lines,
            blocks=blocks,
            edits=edits,
        )

    def simulate(self, command: str, parsed: ParsedConfigResult) -> str | None:
        if not isinstance(parsed, FortiOSParsedConfig):
            return None

        cmd_stripped = command.strip()
        if not cmd_stripped:
            return None

        # Check runtime-only
        first_word = cmd_stripped.split()[0].lower()
        if first_word in _RUNTIME_COMMANDS:
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
        self, base_lower: str, base: str, parsed: FortiOSParsedConfig
    ) -> str | None:
        """Resolve the base command to config text."""

        # "get system global" -> format as "key         : value"
        m = re.match(r"get\s+(.+)", base_lower)
        if m:
            path = m.group(1).strip()
            block = parsed.blocks.get(path)
            if block:
                return self._format_get_output(block)
            return None

        # "show full-configuration" (bare) -> full config
        if base_lower in ("show full-configuration", "show full-config"):
            return "\n".join(parsed.raw_lines)

        # "show full-configuration <path>" -> specific block
        m = re.match(r"show\s+full-configuration\s+(.+)", base, re.IGNORECASE)
        if m:
            path = m.group(1).strip()
            block = parsed.blocks.get(path)
            if block:
                return block.raw_text
            # Try partial match
            for bpath, bdata in parsed.blocks.items():
                if bpath.startswith(path):
                    return bdata.raw_text
            return None

        # "config system global" -> block text only
        m = re.match(r"config\s+(.+)", base_lower)
        if m:
            path = m.group(1).strip()
            block = parsed.blocks.get(path)
            if block:
                return block.raw_text
            return None

        return None

    @staticmethod
    def _format_get_output(block: _ConfigBlock) -> str:
        """Format a block as ``get`` command output (key : value lines)."""
        lines = []
        for key, value in block.entries.items():
            # FortiOS get output uses padded alignment
            lines.append(f"{key:<30}: {value}")
        return "\n".join(lines)

    def extract_topology(self, parsed: ParsedConfigResult) -> TopologyData:
        if not isinstance(parsed, FortiOSParsedConfig):
            return TopologyData()

        interfaces: list[InterfaceInfo] = []
        routes: list[RouteInfo] = []
        vpn_peers: list[str] = []

        # Extract interfaces from "system interface" edits
        for entry in parsed.edits.get("system interface", []):
            name = entry.get("_name", "")
            ip_str = entry.get("ip", "")
            ip = mask = None
            if ip_str:
                parts = ip_str.split()
                if len(parts) >= 2:
                    ip, mask = parts[0], parts[1]
            status = "down" if entry.get("status") == "down" else "up"
            interfaces.append(InterfaceInfo(
                name=name, ip=ip, mask=mask, status=status,
                description=entry.get("alias"),
                vlan=int(entry["vlanid"]) if "vlanid" in entry else None,
            ))

        # Extract static routes from "router static" edits
        for entry in parsed.edits.get("router static", []):
            dst = entry.get("dst", "0.0.0.0 0.0.0.0")
            parts = dst.split()
            network = parts[0] if parts else "0.0.0.0"
            mask = parts[1] if len(parts) > 1 else "0.0.0.0"
            routes.append(RouteInfo(
                network=network, mask=mask,
                gateway=entry.get("gateway"),
                interface=entry.get("device"),
            ))

        # Extract VPN peers from "vpn ipsec phase1-interface" edits
        for entry in parsed.edits.get("vpn ipsec phase1-interface", []):
            peer = entry.get("remote-gw")
            if peer:
                vpn_peers.append(peer)

        return TopologyData(interfaces=interfaces, routes=routes, vpn_peers=vpn_peers)
