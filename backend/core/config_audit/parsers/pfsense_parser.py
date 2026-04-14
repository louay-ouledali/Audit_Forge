"""pfSense XML configuration parser.

Parses pfSense ``config.xml`` exports and simulates commands that
CIS benchmark rules use (grep/awk against raw XML text).
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


@dataclass
class PfSenseParsedConfig(ParsedConfigResult):
    """pfSense-specific parsed config with XML tree."""
    xml_tree: object = None  # lxml.etree._Element
    xml_text: str = ""


class PfSenseConfigParser(BaseConfigParser):

    def parse(self, raw_text: str) -> PfSenseParsedConfig:
        from lxml import etree

        xml_text = raw_text.strip()
        root = etree.fromstring(xml_text.encode("utf-8"))

        hostname = None
        hn_elem = root.find(".//system/hostname")
        if hn_elem is not None and hn_elem.text:
            hostname = hn_elem.text.strip()
            # Also check domain
            domain_elem = root.find(".//system/domain")
            if domain_elem is not None and domain_elem.text:
                hostname = f"{hostname}.{domain_elem.text.strip()}"

        lines = raw_text.splitlines()

        return PfSenseParsedConfig(
            format_id="pfsense_xml",
            hostname=hostname,
            raw_lines=lines,
            xml_tree=root,
            xml_text=xml_text,
        )

    def simulate(self, command: str, parsed: ParsedConfigResult) -> str | None:
        if not isinstance(parsed, PfSenseParsedConfig):
            return None

        cmd_stripped = command.strip()
        if not cmd_stripped:
            return None

        # pfSense rules typically use grep/awk/cat against config.xml
        # or use pfSsh.php commands that need live access
        cmd_lower = cmd_stripped.lower()

        # Live-only commands
        if any(kw in cmd_lower for kw in ("pfctl", "pfssh.php", "pkg info",
                                            "sockstat", "pfssl", "sysctl")):
            return None

        # "cat /cf/conf/config.xml" -> full XML
        if "cat" in cmd_lower and "config.xml" in cmd_lower:
            base, stages = self._parse_pipeline(cmd_stripped)
            text = parsed.xml_text
            if not stages:
                return text
            return self._apply_stages(text, stages)

        # grep-style commands against config.xml
        # e.g., grep -c "<hasync>" /cf/conf/config.xml
        m = re.match(r"grep\s+(.+?)\s+/cf/conf/config\.xml", cmd_stripped)
        if m:
            grep_args = m.group(1)
            return self._simulate_grep(grep_args, parsed)

        # awk commands against config.xml
        if "awk" in cmd_lower and "config.xml" in cmd_lower:
            # Best effort: extract pattern, grep for it
            m_awk = re.match(r".*awk\s+['\"]([^'\"]+)['\"]", cmd_stripped)
            if m_awk:
                pattern = m_awk.group(1)
                # Try to extract a meaningful grep from the awk expression
                m_p = re.search(r"/([^/]+)/", pattern)
                if m_p:
                    lines = self._grep_lines(parsed.raw_lines, m_p.group(1))
                    return "\n".join(lines)
            return None

        # xmllint / xpath queries
        if "xmllint" in cmd_lower:
            m_xpath = re.search(r"--xpath\s+['\"]([^'\"]+)['\"]", cmd_stripped)
            if m_xpath:
                return self._xpath_query(m_xpath.group(1), parsed)
            return None

        # General pipeline: cat config.xml | grep X | wc -l etc.
        if "config.xml" in cmd_lower:
            base, stages = self._parse_pipeline(cmd_stripped)
            text = parsed.xml_text
            if stages:
                return self._apply_stages(text, stages)
            return text

        return None

    def _simulate_grep(self, grep_args: str, parsed: PfSenseParsedConfig) -> str | None:
        """Simulate grep against XML text."""
        count_mode = False
        case_insensitive = False
        pattern = grep_args

        # Parse grep flags
        parts = grep_args.split()
        flags: list[str] = []
        pat_parts: list[str] = []

        for part in parts:
            if part.startswith("-"):
                flags.append(part)
            else:
                pat_parts.append(part)

        if "-c" in flags:
            count_mode = True
        if "-i" in flags:
            case_insensitive = True

        pattern = " ".join(pat_parts).strip("'\"")

        re_flags = re.IGNORECASE if case_insensitive else 0
        try:
            rx = re.compile(pattern, re_flags)
        except re.error:
            rx = None

        matching = []
        for line in parsed.raw_lines:
            if rx and rx.search(line):
                matching.append(line)
            elif not rx and pattern in (line.lower() if case_insensitive else line):
                matching.append(line)

        if count_mode:
            return str(len(matching))

        return "\n".join(matching)

    def _xpath_query(self, xpath: str, parsed: PfSenseParsedConfig) -> str | None:
        """Execute an XPath query against the XML tree."""
        from lxml import etree

        root = parsed.xml_tree
        if root is None:
            return None

        try:
            results = root.xpath(xpath)
            if isinstance(results, list):
                parts = []
                for r in results:
                    if hasattr(r, "text") and r.text:
                        parts.append(r.text)
                    elif isinstance(r, str):
                        parts.append(r)
                    else:
                        parts.append(
                            etree.tostring(r, pretty_print=True, encoding="unicode")
                        )
                return "\n".join(parts).strip()
            return str(results)
        except Exception:
            return None

    def extract_topology(self, parsed: ParsedConfigResult) -> TopologyData:
        if not isinstance(parsed, PfSenseParsedConfig):
            return TopologyData()

        root = parsed.xml_tree
        if root is None:
            return TopologyData()

        interfaces: list[InterfaceInfo] = []
        routes: list[RouteInfo] = []

        # Extract interfaces from <interfaces>
        ifaces_elem = root.find("interfaces")
        if ifaces_elem is not None:
            for iface in ifaces_elem:
                name = iface.tag  # wan, lan, opt1, etc.
                ip = mask = None
                descr = None
                status = "up"

                ipaddr = iface.find("ipaddr")
                if ipaddr is not None and ipaddr.text:
                    ip = ipaddr.text.strip()

                subnet = iface.find("subnet")
                if subnet is not None and subnet.text:
                    try:
                        prefix = int(subnet.text.strip())
                        mask = self._prefix_to_mask(prefix)
                    except ValueError:
                        pass

                descr_elem = iface.find("descr")
                if descr_elem is not None and descr_elem.text:
                    descr = descr_elem.text.strip()

                enable_elem = iface.find("enable")
                if enable_elem is None:
                    status = "down"

                interfaces.append(InterfaceInfo(
                    name=name, ip=ip, mask=mask,
                    description=descr, status=status,
                ))

        # Extract static routes from <staticroutes>
        routes_elem = root.find("staticroutes")
        if routes_elem is not None:
            for route in routes_elem.findall("route"):
                network_elem = route.find("network")
                gw_elem = route.find("gateway")

                if network_elem is not None and network_elem.text:
                    dest = network_elem.text.strip()
                    network = dest.split("/")[0] if "/" in dest else dest
                    mask_str = ""
                    if "/" in dest:
                        mask_str = self._prefix_to_mask(int(dest.split("/")[1]))

                    gw = None
                    if gw_elem is not None and gw_elem.text:
                        gw = gw_elem.text.strip()

                    routes.append(RouteInfo(
                        network=network, mask=mask_str, gateway=gw,
                    ))

        return TopologyData(interfaces=interfaces, routes=routes)

    @staticmethod
    def _prefix_to_mask(prefix: int) -> str:
        bits = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
        return f"{(bits >> 24) & 0xFF}.{(bits >> 16) & 0xFF}.{(bits >> 8) & 0xFF}.{bits & 0xFF}"
