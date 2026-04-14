"""Palo Alto Networks PAN-OS XML configuration parser.

Parses PAN-OS XML config files and simulates ``show`` commands used
by PAN-OS CIS benchmark rules.
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
    "show system info",
    "show high-availability",
    "show jobs all",
    "show session info",
    "debug",
    "request",
})


@dataclass
class PANOSParsedConfig(ParsedConfigResult):
    """PAN-OS-specific parsed config with lxml tree."""
    xml_tree: object = None  # lxml.etree._Element
    xml_text: str = ""


class PANOSConfigParser(BaseConfigParser):

    def parse(self, raw_text: str) -> PANOSParsedConfig:
        from lxml import etree

        xml_text = raw_text.strip()
        root = etree.fromstring(xml_text.encode("utf-8"))

        hostname = None
        # Try <deviceconfig><system><hostname>
        hn_elem = root.find(".//deviceconfig/system/hostname")
        if hn_elem is not None and hn_elem.text:
            hostname = hn_elem.text.strip()

        lines = raw_text.splitlines()

        return PANOSParsedConfig(
            format_id="panos_xml",
            hostname=hostname,
            raw_lines=lines,
            xml_tree=root,
            xml_text=xml_text,
        )

    def simulate(self, command: str, parsed: ParsedConfigResult) -> str | None:
        if not isinstance(parsed, PANOSParsedConfig):
            return None

        cmd_stripped = command.strip()
        if not cmd_stripped:
            return None

        # Runtime-only
        base_lower = cmd_stripped.lower().split("|")[0].strip()
        for rt_cmd in _RUNTIME_COMMANDS:
            if base_lower.startswith(rt_cmd):
                return None

        if not base_lower.startswith("show "):
            return None

        base, stages = self._parse_pipeline(cmd_stripped)
        base_lower = base.lower().strip()

        text = self._resolve_base_command(base_lower, parsed)
        if text is None:
            return None

        if not stages:
            return text

        return self._apply_stages(text, stages)

    def _resolve_base_command(
        self, base_lower: str, parsed: PANOSParsedConfig
    ) -> str | None:
        """Resolve a show command to XML content."""
        from lxml import etree

        root = parsed.xml_tree
        if root is None:
            return None

        # "show config running" -> full XML
        if base_lower in ("show config running", "show config"):
            return parsed.xml_text

        # "show config running <xpath>" or "show <path>"
        m = re.match(r"show\s+(?:config\s+running\s+)?(.+)", base_lower)
        if not m:
            return None

        path = m.group(1).strip()

        # Convert dotted/space path to XPath: "deviceconfig system" -> ".//deviceconfig/system"
        xpath = ".//" + path.replace(" ", "/")

        try:
            elements = root.xpath(xpath)
            if not elements:
                # Try with hyphens
                xpath_hyphens = ".//" + path.replace(" ", "-")
                elements = root.xpath(xpath_hyphens)

            if elements:
                parts = []
                for elem in elements:
                    parts.append(
                        etree.tostring(elem, pretty_print=True, encoding="unicode")
                    )
                return "\n".join(parts).strip()
        except Exception:
            pass

        # Try searching for elements containing the path keywords
        keywords = path.split()
        if keywords:
            last = keywords[-1]
            try:
                elements = root.xpath(f".//{last}")
                if elements:
                    parts = []
                    for elem in elements:
                        parts.append(
                            etree.tostring(elem, pretty_print=True, encoding="unicode")
                        )
                    return "\n".join(parts).strip()
            except Exception:
                pass

        return None

    def extract_topology(self, parsed: ParsedConfigResult) -> TopologyData:
        if not isinstance(parsed, PANOSParsedConfig):
            return TopologyData()

        root = parsed.xml_tree
        if root is None:
            return TopologyData()

        interfaces: list[InterfaceInfo] = []
        routes: list[RouteInfo] = []
        vpn_peers: list[str] = []

        # Extract interfaces from <network><interface>
        for iface_type in root.xpath(".//network/interface/*"):
            type_name = iface_type.tag  # ethernet, loopback, tunnel, etc.
            for entry in iface_type:
                name = entry.get("name", entry.tag)
                full_name = f"{type_name}/{name}"

                ip = mask = None
                # Check for <ip><entry name="x.x.x.x/y"/>
                ip_entries = entry.xpath(".//ip/entry")
                if ip_entries:
                    ip_str = ip_entries[0].get("name", "")
                    if "/" in ip_str:
                        ip = ip_str.split("/")[0]
                        prefix = int(ip_str.split("/")[1])
                        mask = self._prefix_to_mask(prefix)

                comment = None
                comment_elem = entry.find("comment")
                if comment_elem is not None:
                    comment = comment_elem.text

                interfaces.append(InterfaceInfo(
                    name=full_name, ip=ip, mask=mask,
                    description=comment,
                ))

        # Extract static routes from <network><virtual-router>
        for vr in root.xpath(".//network/virtual-router/entry"):
            for route in vr.xpath(".//routing-table/ip/static-route/entry"):
                dest = None
                dest_elem = route.find("destination")
                if dest_elem is not None:
                    dest = dest_elem.text

                nexthop = None
                nh_elem = route.find(".//nexthop/ip-address")
                if nh_elem is not None:
                    nexthop = nh_elem.text

                iface = None
                iface_elem = route.find(".//nexthop/next-vr")
                if iface_elem is None:
                    iface_elem = route.find("interface")
                if iface_elem is not None:
                    iface = iface_elem.text

                if dest:
                    network = dest.split("/")[0] if "/" in dest else dest
                    mask_str = ""
                    if "/" in dest:
                        mask_str = self._prefix_to_mask(int(dest.split("/")[1]))
                    routes.append(RouteInfo(
                        network=network, mask=mask_str,
                        gateway=nexthop, interface=iface,
                    ))

        # Extract IKE gateways (VPN peers)
        for gw in root.xpath(".//network/ike/gateway/entry"):
            peer_elem = gw.find(".//peer-address/ip")
            if peer_elem is not None and peer_elem.text:
                vpn_peers.append(peer_elem.text.strip())

        return TopologyData(interfaces=interfaces, routes=routes, vpn_peers=vpn_peers)

    @staticmethod
    def _prefix_to_mask(prefix: int) -> str:
        """Convert CIDR prefix length to dotted-decimal mask."""
        bits = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
        return f"{(bits >> 24) & 0xFF}.{(bits >> 16) & 0xFF}.{(bits >> 8) & 0xFF}.{bits & 0xFF}"
