"""Network discovery — scan a subnet to find live hosts and identify their type.

Uses pure-Python TCP probing and banner grabbing (no external dependencies
like nmap/scapy) so it works inside a minimal Docker container.

Banner grabbing reads the first response bytes from open services (SSH, HTTP,
FTP, Telnet, SMTP, SMB, databases) to extract:
  - **os_version**: e.g. "Ubuntu 22.04", "Windows 11", "Cisco IOS 15.7"
  - **vendor**: e.g. "Canonical", "Microsoft", "Cisco", "PostgreSQL Global"
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("auditforge.discovery")

# Well-known ports to probe and what they indicate
# fmt: off
PROBE_PORTS: list[tuple[int, str, str]] = [
    # (port, service_name, platform_hint)
    (22,    "SSH",          "linux"),
    (135,   "MSRPC",        "windows"),
    (139,   "NetBIOS",      "windows"),
    (445,   "SMB",          "windows"),
    (3389,  "RDP",          "windows"),
    (5985,  "WinRM-HTTP",   "windows"),
    (5986,  "WinRM-HTTPS",  "windows"),
    (80,    "HTTP",         "unknown"),
    (443,   "HTTPS",        "unknown"),
    (161,   "SNMP",         "network"),
    (23,    "Telnet",       "network"),
    (830,   "NETCONF",      "network"),
    (1433,  "MSSQL",        "database"),
    (5432,  "PostgreSQL",   "database"),
    (1521,  "Oracle",       "database"),
    (3306,  "MySQL",        "database"),
    (8080,  "HTTP-Alt",     "unknown"),
    (8443,  "HTTPS-Alt",    "unknown"),
    (53,    "DNS",          "network"),
    (514,   "Syslog",       "network"),
]
# fmt: on

# Concurrency limits
MAX_CONCURRENT_HOSTS = 50
MAX_CONCURRENT_PORTS = 20
TCP_CONNECT_TIMEOUT = 1.5  # seconds per port probe
BANNER_READ_TIMEOUT = 3.0  # seconds to wait for a service banner
BANNER_MAX_BYTES = 1024    # max bytes to read from a banner

# Ports that send a banner immediately upon connection (no request needed)
BANNER_PORTS_PASSIVE = {22, 21, 23, 25, 110, 143}  # SSH, FTP, Telnet, SMTP, POP3, IMAP
# Ports that need an HTTP request to get a useful banner
BANNER_PORTS_HTTP = {80, 443, 8080, 8443}
# Database ports that send a banner or respond to a probe
BANNER_PORTS_DB = {3306, 5432}  # MySQL greeting, PostgreSQL


@dataclass
class DiscoveredHost:
    """Represents a single discovered host on the network."""
    ip: str
    hostname: str = ""
    open_ports: list[dict[str, Any]] = field(default_factory=list)
    os_guess: str = "unknown"  # windows | linux | network | database | unknown
    os_version: str = ""       # e.g. "Ubuntu 22.04", "Windows Server 2022"
    vendor: str = ""           # e.g. "Canonical", "Microsoft", "Cisco"
    banners: dict[int, str] = field(default_factory=dict)  # port → raw banner
    connection_methods: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "hostname": self.hostname,
            "open_ports": self.open_ports,
            "os_guess": self.os_guess,
            "os_version": self.os_version,
            "vendor": self.vendor,
            "banners": self.banners,
            "connection_methods": self.connection_methods,
        }


async def _probe_port(ip: str, port: int, timeout: float = TCP_CONNECT_TIMEOUT) -> bool:
    """Try to open a TCP connection to ip:port. Returns True if open."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False


async def _reverse_dns(ip: str) -> str:
    """Attempt a reverse DNS lookup. Returns hostname or empty string."""
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: socket.gethostbyaddr(ip)),
            timeout=2.0,
        )
        return result[0]
    except (socket.herror, socket.gaierror, asyncio.TimeoutError, OSError):
        return ""


# ── Banner Grabbing ──────────────────────────────────────────

async def _grab_banner(ip: str, port: int) -> str:
    """Connect to ip:port and read a service banner.

    For passive ports (SSH, FTP, Telnet…) we just read the first response.
    For HTTP ports we send a minimal HEAD request to get Server header.
    For MySQL (3306) we read the greeting packet.
    Returns the raw banner string (up to BANNER_MAX_BYTES), or "".
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=TCP_CONNECT_TIMEOUT,
        )
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return ""

    banner = ""
    try:
        if port in BANNER_PORTS_HTTP:
            # Send a HEAD request
            request = (
                f"HEAD / HTTP/1.0\r\nHost: {ip}\r\n"
                f"User-Agent: AuditForge-Discovery/1.0\r\n\r\n"
            )
            writer.write(request.encode())
            await writer.drain()
            data = await asyncio.wait_for(
                reader.read(BANNER_MAX_BYTES), timeout=BANNER_READ_TIMEOUT
            )
            banner = data.decode("utf-8", errors="replace")
        elif port == 5432:
            # PostgreSQL: send a cancel-request code that prompts a response
            cancel = struct.pack("!II", 16, 80877102)
            writer.write(cancel)
            await writer.drain()
            data = await asyncio.wait_for(
                reader.read(BANNER_MAX_BYTES), timeout=BANNER_READ_TIMEOUT
            )
            banner = data.decode("utf-8", errors="replace")
        else:
            # Passive banner (SSH, FTP, Telnet, SMTP, MySQL greeting…)
            data = await asyncio.wait_for(
                reader.read(BANNER_MAX_BYTES), timeout=BANNER_READ_TIMEOUT
            )
            banner = data.decode("utf-8", errors="replace")
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except OSError:
            pass

    return banner.strip()


async def _grab_banners(ip: str, open_ports: list[dict[str, Any]]) -> dict[int, str]:
    """Grab banners from interesting open ports concurrently."""
    interesting = set()
    for p in open_ports:
        port = p["port"]
        if port in BANNER_PORTS_PASSIVE or port in BANNER_PORTS_HTTP or port in BANNER_PORTS_DB:
            interesting.add(port)

    if not interesting:
        return {}

    tasks = {port: asyncio.create_task(_grab_banner(ip, port)) for port in interesting}
    banners: dict[int, str] = {}
    for port, task in tasks.items():
        try:
            result = await task
            if result:
                banners[port] = result
        except Exception:
            pass
    return banners


# ── OS Version & Vendor Detection (from banners) ────────────

# SSH banner patterns: "SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.4"
_SSH_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, os_version_template, vendor)
    (r"OpenSSH[_\s]([\d.]+).*Ubuntu",          "Ubuntu (OpenSSH {0})",    "Canonical"),
    (r"OpenSSH[_\s]([\d.]+).*Debian",          "Debian (OpenSSH {0})",    "Debian Project"),
    (r"OpenSSH[_\s]([\d.]+).*el(\d+)",         "RHEL/CentOS {1} (OpenSSH {0})", "Red Hat"),
    (r"OpenSSH[_\s]([\d.]+).*FreeBSD",         "FreeBSD (OpenSSH {0})",   "FreeBSD Foundation"),
    (r"OpenSSH_for_Windows_([\d.]+)",           "Windows (OpenSSH {0})",   "Microsoft"),
    (r"OpenSSH[_\s]([\d.]+)",                  "OpenSSH {0}",             ""),
    (r"dropbear[_\s]([\d.]+)",                 "Dropbear {0}",            ""),
    (r"Cisco[_\s-]([\d.]+)",                   "Cisco IOS {0}",           "Cisco"),
    (r"ROSSSH",                                 "MikroTik RouterOS",       "MikroTik"),
    (r"FortiSSH",                               "FortiOS",                "Fortinet"),
]

# HTTP Server header patterns
_HTTP_PATTERNS: list[tuple[str, str, str]] = [
    (r"Microsoft-IIS/([\d.]+)",            "Windows (IIS {0})",            "Microsoft"),
    (r"Microsoft-HTTPAPI/([\d.]+)",        "Windows (HTTP API {0})",       "Microsoft"),
    (r"Apache/([\d.]+).*Ubuntu",           "Ubuntu (Apache {0})",          "Canonical"),
    (r"Apache/([\d.]+).*Debian",           "Debian (Apache {0})",          "Debian Project"),
    (r"Apache/([\d.]+).*CentOS",           "CentOS (Apache {0})",          "Red Hat"),
    (r"Apache/([\d.]+).*Win(?:32|64)",     "Windows (Apache {0})",         "Apache Foundation"),
    (r"Apache/([\d.]+)",                   "Apache {0}",                   "Apache Foundation"),
    (r"nginx/([\d.]+)",                    "nginx {0}",                    "F5/nginx"),
    (r"lighttpd/([\d.]+)",                 "lighttpd {0}",                 "lighttpd"),
    (r"Cisco",                             "Cisco Device",                 "Cisco"),
    (r"ArubaOS",                           "Aruba Device",                 "HPE/Aruba"),
    (r"Boa/([\d.]+)",                      "Embedded (Boa {0})",           ""),
]

# FTP banner patterns
_FTP_PATTERNS: list[tuple[str, str, str]] = [
    (r"Microsoft FTP Service",             "Windows (FTP)",                "Microsoft"),
    (r"vsFTPd ([\d.]+)",                   "Linux (vsFTPd {0})",           ""),
    (r"ProFTPD ([\d.]+)",                  "ProFTPD {0}",                  ""),
    (r"FileZilla Server ([\d.]+)",         "Windows (FileZilla {0})",      "FileZilla"),
]

# Telnet banner patterns
_TELNET_PATTERNS: list[tuple[str, str, str]] = [
    (r"Cisco IOS.*Version ([\d.()A-Za-z]+)", "Cisco IOS {0}",            "Cisco"),
    (r"Juniper Networks",                     "Junos OS",                 "Juniper"),
    (r"User Access Verification",             "Cisco Device",             "Cisco"),
    (r"MikroTik",                             "MikroTik RouterOS",        "MikroTik"),
    (r"HP ProCurve",                          "HP ProCurve Switch",       "HPE"),
    (r"Arista",                               "Arista EOS",               "Arista"),
]

# MySQL greeting pattern
_MYSQL_PATTERNS: list[tuple[str, str, str]] = [
    (r"([\d.]+)-MariaDB",                  "MariaDB {0}",                  "MariaDB"),
    (r"mysql[_\s]?([\d.]+)",               "MySQL {0}",                    "Oracle/MySQL"),
    (r"([\d.]+)",                           "MySQL {0}",                    "Oracle/MySQL"),
]

# SMTP banner patterns
_SMTP_PATTERNS: list[tuple[str, str, str]] = [
    (r"Microsoft ESMTP.*MAIL Service",      "Windows (Exchange)",           "Microsoft"),
    (r"Postfix",                            "Linux (Postfix)",              ""),
    (r"Exim ([\d.]+)",                      "Exim {0}",                     ""),
]


def _match_patterns(
    banner: str, patterns: list[tuple[str, str, str]]
) -> tuple[str, str]:
    """Try each regex pattern against the banner.

    Returns (os_version, vendor) on first match, or ("", "").
    """
    for regex, os_tpl, vendor in patterns:
        m = re.search(regex, banner, re.IGNORECASE)
        if m:
            groups = m.groups()
            os_version = os_tpl.format(*groups) if groups else os_tpl
            return os_version, vendor
    return "", ""


def _detect_os_version_and_vendor(
    banners: dict[int, str],
    os_guess: str,
    hostname: str,
) -> tuple[str, str]:
    """Analyze banners to determine OS version and vendor.

    Checks SSH → HTTP → FTP → Telnet → MySQL → SMTP in priority order.
    """
    os_version = ""
    vendor = ""

    # SSH banner (usually the most informative)
    if 22 in banners:
        os_version, vendor = _match_patterns(banners[22], _SSH_PATTERNS)
        if os_version:
            return os_version, vendor

    # HTTP Server header
    for port in (80, 443, 8080, 8443):
        if port in banners:
            header_banner = banners[port]
            server_match = re.search(
                r"Server:\s*(.+)", header_banner, re.IGNORECASE
            )
            if server_match:
                server_val = server_match.group(1).strip()
                os_version, vendor = _match_patterns(server_val, _HTTP_PATTERNS)
                if os_version:
                    return os_version, vendor

    # FTP banner
    if 21 in banners:
        os_version, vendor = _match_patterns(banners[21], _FTP_PATTERNS)
        if os_version:
            return os_version, vendor

    # Telnet banner (network devices)
    if 23 in banners:
        os_version, vendor = _match_patterns(banners[23], _TELNET_PATTERNS)
        if os_version:
            return os_version, vendor

    # MySQL banner
    if 3306 in banners:
        os_version, vendor = _match_patterns(banners[3306], _MYSQL_PATTERNS)
        if os_version:
            return os_version, vendor

    # SMTP banner
    if 25 in banners:
        os_version, vendor = _match_patterns(banners[25], _SMTP_PATTERNS)
        if os_version:
            return os_version, vendor

    # Fallback: infer vendor from os_guess + hostname
    if os_guess == "windows":
        return "Windows", "Microsoft"
    if os_guess == "linux":
        return "Linux", ""

    return os_version, vendor


def _guess_os(open_ports: list[dict[str, Any]]) -> str:
    """Guess the OS/platform type based on which ports are open."""
    port_numbers = {p["port"] for p in open_ports}
    hints = [p["platform_hint"] for p in open_ports]

    # Strong Windows indicators
    windows_ports = {135, 139, 445, 3389, 5985, 5986}
    if port_numbers & windows_ports:
        return "windows"

    # Strong Linux indicator
    if 22 in port_numbers and not (port_numbers & windows_ports):
        return "linux"

    # Database
    db_ports = {1433, 5432, 1521, 3306}
    if port_numbers & db_ports and not (port_numbers & windows_ports) and 22 not in port_numbers:
        return "database"

    # Network device indicators
    network_ports = {23, 161, 830}
    if port_numbers & network_ports and not (port_numbers & windows_ports):
        return "network"

    return "unknown"


def _detect_connection_methods(os_guess: str, open_ports: list[dict[str, Any]]) -> list[str]:
    """Suggest available connection methods based on open ports."""
    port_numbers = {p["port"] for p in open_ports}
    methods = []

    if 22 in port_numbers:
        methods.append("ssh")
    if 5985 in port_numbers or 5986 in port_numbers:
        methods.append("winrm")
    if 23 in port_numbers:
        methods.append("telnet")
    if 161 in port_numbers:
        methods.append("snmp")

    # Database-specific
    if 1433 in port_numbers:
        methods.append("mssql")
    if 5432 in port_numbers:
        methods.append("postgresql")
    if 1521 in port_numbers:
        methods.append("oracle")

    return methods


async def _scan_host(ip: str, sem: asyncio.Semaphore) -> DiscoveredHost | None:
    """Scan a single host for open ports."""
    async with sem:
        # First, do a quick check on the most common ports to see if host is alive
        quick_ports = [22, 80, 135, 443, 445, 3389, 5985]
        quick_tasks = [_probe_port(ip, p, timeout=1.0) for p in quick_ports]
        quick_results = await asyncio.gather(*quick_tasks)

        if not any(quick_results):
            return None  # Host appears down

        # Host is alive — probe all ports
        port_sem = asyncio.Semaphore(MAX_CONCURRENT_PORTS)

        async def _guarded_probe(port: int) -> bool:
            async with port_sem:
                return await _probe_port(ip, port)

        tasks = [_guarded_probe(p) for p, _, _ in PROBE_PORTS]
        results = await asyncio.gather(*tasks)

        open_ports = []
        for (port, service, hint), is_open in zip(PROBE_PORTS, results):
            if is_open:
                open_ports.append({
                    "port": port,
                    "service": service,
                    "platform_hint": hint,
                })

        if not open_ports:
            return None

        hostname = await _reverse_dns(ip)
        os_guess = _guess_os(open_ports)
        conn_methods = _detect_connection_methods(os_guess, open_ports)

        # Banner grabbing + OS/vendor detection
        banners = await _grab_banners(ip, open_ports)
        os_version, vendor = _detect_os_version_and_vendor(
            banners, os_guess, hostname
        )

        return DiscoveredHost(
            ip=ip,
            hostname=hostname,
            open_ports=open_ports,
            os_guess=os_guess,
            connection_methods=conn_methods,
            os_version=os_version,
            vendor=vendor,
            banners=banners,
        )


def _parse_subnet(subnet_str: str) -> list[str]:
    """Parse a subnet string and return a list of host IPs to scan.

    Supports CIDR notation (192.168.1.0/24), ranges (192.168.1.1-254),
    and single IPs.
    """
    subnet_str = subnet_str.strip()

    # CIDR notation
    if "/" in subnet_str:
        try:
            network = ipaddress.ip_network(subnet_str, strict=False)
            # Skip network and broadcast addresses for /24 and smaller
            if network.prefixlen >= 24:
                return [str(ip) for ip in network.hosts()]
            # For larger subnets, limit to first 1024 hosts
            hosts = []
            for ip in network.hosts():
                hosts.append(str(ip))
                if len(hosts) >= 1024:
                    break
            return hosts
        except ValueError:
            raise ValueError(f"Invalid CIDR notation: {subnet_str}")

    # Range notation: 192.168.1.1-254
    if "-" in subnet_str:
        parts = subnet_str.split("-")
        if len(parts) == 2:
            base_ip = parts[0].strip()
            end = parts[1].strip()
            try:
                # Full IP range: 192.168.1.1-192.168.1.254
                start_ip = ipaddress.ip_address(base_ip)
                if "." in end:
                    end_ip = ipaddress.ip_address(end)
                else:
                    # Short range: 192.168.1.1-254
                    octets = base_ip.rsplit(".", 1)
                    end_ip = ipaddress.ip_address(f"{octets[0]}.{end}")

                hosts = []
                current = start_ip
                while current <= end_ip and len(hosts) < 1024:
                    hosts.append(str(current))
                    current = ipaddress.ip_address(int(current) + 1)
                return hosts
            except ValueError:
                raise ValueError(f"Invalid IP range: {subnet_str}")

    # Single IP
    try:
        ipaddress.ip_address(subnet_str)
        return [subnet_str]
    except ValueError:
        pass

    # Try DNS resolution for hostnames
    try:
        resolved = socket.gethostbyname(subnet_str)
        return [resolved]
    except (socket.gaierror, socket.herror):
        pass

    raise ValueError(f"Invalid IP address or subnet: {subnet_str}")


# In-memory progress tracking for active discoveries
_discovery_progress: dict[str, dict[str, Any]] = {}


def get_discovery_progress(discovery_id: str) -> dict[str, Any] | None:
    """Return current progress for an active discovery, or None."""
    return _discovery_progress.get(discovery_id)


async def discover_network(
    subnet: str,
    discovery_id: str | None = None,
) -> list[dict[str, Any]]:
    """Scan a subnet and return a list of discovered hosts with open ports.

    Parameters
    ----------
    subnet:
        CIDR (192.168.1.0/24), range (192.168.1.1-254), or single IP.
    discovery_id:
        Optional ID for progress tracking.

    Returns
    -------
    List of dicts with ip, hostname, open_ports, os_guess, connection_methods.
    """
    hosts_to_scan = _parse_subnet(subnet)
    total = len(hosts_to_scan)

    if discovery_id:
        _discovery_progress[discovery_id] = {
            "id": discovery_id,
            "status": "running",
            "total": total,
            "scanned": 0,
            "found": 0,
        }

    logger.info("Starting discovery of %d hosts on %s", total, subnet)
    start_time = time.monotonic()

    sem = asyncio.Semaphore(MAX_CONCURRENT_HOSTS)
    discovered: list[DiscoveredHost] = []

    # Process in batches for progress tracking
    batch_size = MAX_CONCURRENT_HOSTS
    for batch_start in range(0, total, batch_size):
        batch = hosts_to_scan[batch_start:batch_start + batch_size]
        tasks = [_scan_host(ip, sem) for ip in batch]
        results = await asyncio.gather(*tasks)

        for host in results:
            if host is not None:
                discovered.append(host)

        if discovery_id and discovery_id in _discovery_progress:
            _discovery_progress[discovery_id]["scanned"] = min(batch_start + len(batch), total)
            _discovery_progress[discovery_id]["found"] = len(discovered)

    elapsed = time.monotonic() - start_time
    logger.info(
        "Discovery completed: %d hosts found out of %d scanned in %.1fs",
        len(discovered), total, elapsed,
    )

    if discovery_id and discovery_id in _discovery_progress:
        _discovery_progress[discovery_id]["status"] = "completed"
        _discovery_progress[discovery_id]["scanned"] = total
        _discovery_progress[discovery_id]["found"] = len(discovered)
        _discovery_progress[discovery_id]["hosts"] = [h.to_dict() for h in discovered]

    return [h.to_dict() for h in discovered]


def cleanup_discovery(discovery_id: str) -> None:
    """Remove a completed discovery from in-memory tracking."""
    _discovery_progress.pop(discovery_id, None)
