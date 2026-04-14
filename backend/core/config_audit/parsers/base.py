"""Parser base classes and shared data structures for config audit."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ── Topology data structures ─────────────────────────────────────

@dataclass
class InterfaceInfo:
    name: str
    nameif: str | None = None
    ip: str | None = None
    mask: str | None = None
    status: str | None = None
    security_level: int | None = None
    vlan: int | None = None
    description: str | None = None


@dataclass
class RouteInfo:
    network: str
    mask: str = ""
    gateway: str | None = None
    interface: str | None = None


@dataclass
class TopologyData:
    interfaces: list[InterfaceInfo] = field(default_factory=list)
    routes: list[RouteInfo] = field(default_factory=list)
    vpn_peers: list[str] = field(default_factory=list)


# ── Parser base ──────────────────────────────────────────────────

@dataclass
class ParsedConfigResult:
    """Minimal shared result.  Platform-specific data stays in subclass attributes."""
    format_id: str
    hostname: str | None
    raw_lines: list[str]
    platform_version: str | None = None


class BaseConfigParser(ABC):
    """Abstract base class for all config parsers."""

    @abstractmethod
    def parse(self, raw_text: str) -> ParsedConfigResult:
        """Parse raw config text into a platform-specific result."""
        ...

    @abstractmethod
    def simulate(self, command: str, parsed: ParsedConfigResult) -> str | None:
        """Simulate a CLI command against the parsed config.

        Returns the simulated command output as a string, or ``None`` if
        the command cannot be answered from config (requires live execution).
        """
        ...

    def extract_topology(self, parsed: ParsedConfigResult) -> TopologyData:
        """Extract topology-relevant data from the parsed config.

        Default implementation returns empty topology data; parsers
        override as needed.
        """
        return TopologyData()

    # ── Shared utilities ─────────────────────────────────────────

    @staticmethod
    def _grep_lines(lines: list[str], pattern: str, *, case_insensitive: bool = True) -> list[str]:
        """Grep *lines* by regex *pattern*."""
        flags = re.IGNORECASE if case_insensitive else 0
        try:
            rx = re.compile(pattern, flags)
        except re.error:
            # Treat as a literal substring match if regex is invalid
            pat_lower = pattern.lower() if case_insensitive else pattern
            return [
                l for l in lines
                if (pat_lower in (l.lower() if case_insensitive else l))
            ]
        return [l for l in lines if rx.search(l)]

    @staticmethod
    def _parse_pipeline(command: str) -> tuple[str, list[tuple[str, str]]]:
        """Split a CLI command into base command and pipeline stages.

        Returns ``(base_command, [(stage_type, argument), ...])``.

        Supported stage types: ``"include"``, ``"exclude"``, ``"section"``,
        ``"begin"``, ``"match"``, ``"except"``, ``"count"``, ``"display"``,
        ``"grep"``.
        """
        # Split on the first " | " (space-pipe-space) to avoid matching
        # pipes inside arguments or filenames
        parts = re.split(r"\s+\|\s+", command)
        base = parts[0].strip()
        stages: list[tuple[str, str]] = []
        for part in parts[1:]:
            part = part.strip()
            if not part:
                continue
            tokens = part.split(None, 1)
            stage_type = tokens[0].lower()
            arg = tokens[1] if len(tokens) > 1 else ""
            stages.append((stage_type, arg))
        return base, stages

    @staticmethod
    def _apply_stages(text: str, stages: list[tuple[str, str]]) -> str | None:
        """Apply common pipeline stages to *text*.

        Returns the final output string.  Returns ``None`` only if a
        stage is unrecognised (caller should fall back to live execution).
        """
        lines = text.splitlines()

        for stage_type, arg in stages:
            if stage_type in ("include", "match", "grep"):
                try:
                    rx = re.compile(arg, re.IGNORECASE)
                except re.error:
                    lines = [l for l in lines if arg.lower() in l.lower()]
                else:
                    lines = [l for l in lines if rx.search(l)]

            elif stage_type in ("exclude", "except"):
                try:
                    rx = re.compile(arg, re.IGNORECASE)
                except re.error:
                    lines = [l for l in lines if arg.lower() not in l.lower()]
                else:
                    lines = [l for l in lines if not rx.search(l)]

            elif stage_type == "begin":
                found = False
                new_lines: list[str] = []
                try:
                    rx = re.compile(arg, re.IGNORECASE)
                except re.error:
                    for l in lines:
                        if not found and arg.lower() in l.lower():
                            found = True
                        if found:
                            new_lines.append(l)
                else:
                    for l in lines:
                        if not found and rx.search(l):
                            found = True
                        if found:
                            new_lines.append(l)
                lines = new_lines

            elif stage_type == "count":
                return f"Count: {len(lines)} lines"

            elif stage_type == "display":
                # Handled by platform-specific parsers (e.g., JunOS "display set")
                # Pass through — the parser's simulate() should handle this before
                # falling into _apply_stages
                pass

            elif stage_type == "section":
                # IOS-specific — handled in IOS parser
                pass

            else:
                # Unknown stage — cannot simulate
                return None

        return "\n".join(lines)


class FallbackConfigParser(BaseConfigParser):
    """Minimal parser that only supports raw text grep.

    Handles ``show running-config | include X`` for any IOS-like config.
    """

    def parse(self, raw_text: str) -> ParsedConfigResult:
        lines = raw_text.splitlines()
        hostname = None
        for line in lines:
            m = re.match(r"^hostname\s+(\S+)", line)
            if m:
                hostname = m.group(1)
                break
        return ParsedConfigResult(
            format_id="unknown",
            hostname=hostname,
            raw_lines=lines,
        )

    def simulate(self, command: str, parsed: ParsedConfigResult) -> str | None:
        cmd_lower = command.lower().strip()

        # Only handle "show running-config" variants
        if not any(cmd_lower.startswith(p) for p in (
            "show running-config", "show run", "show startup-config",
        )):
            return None

        base, stages = self._parse_pipeline(command)

        # Bare "show running-config" -> full text
        if not stages:
            return "\n".join(parsed.raw_lines)

        return self._apply_stages("\n".join(parsed.raw_lines), stages)
