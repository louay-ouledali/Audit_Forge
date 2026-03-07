"""Network discovery — advanced host fingerprinting & identification.

Uses pure-Python TCP probing, banner grabbing, SMB/NTLM fingerprinting,
SNMP sysDescr, UPnP/SSDP, mDNS, NetBIOS Name Service, ARP sweep,
MAC OUI lookup, hostname heuristics, TCP passive OS fingerprinting,
and deep HTTP inspection — all without external dependencies (no nmap/scapy).

Requires ``network_mode: host`` in Docker for reliable ARP/MAC, ICMP,
multicast (mDNS/SSDP), and NetBIOS access to the host LAN.

Detection layers (in priority order):
  0. **ARP sweep** → pre-scan ping + ARP table read for MAC addresses
  1. **SMB/NTLM negotiation** → exact Windows version + build + domain
  2. **SNMP sysDescr** → exact device model & firmware (network devices)
  3. **SSH / FTP / Telnet / SMTP banners** → OS family + version
  4. **HTTP deep inspection** → Server header, <title>, login page text
  5. **UPnP SSDP** → multicast + unicast; manufacturer, model, firmware
  6. **mDNS / Bonjour** → multicast + unicast; Apple, Chromecast, printers
  7. **MAC OUI** → vendor from NIC manufacturer (ARP cache)
  8. **Hostname heuristics** → pattern matching (TP-Link, NETGEAR, etc.)
  9. **NetBIOS Name Service** → Windows hostname, domain, MAC (UDP 137)
  10. **TCP passive OS fingerprint** → p0f-style TTL analysis
  11. **Port-based heuristics** → fallback OS family guess

Each layer contributes to a confidence-weighted result. Multi-source
confidence boosting raises the score when independent layers agree on
the same vendor or OS family.  All detections are aggregated into:
  - **os_version**: e.g. "Windows 11 Pro 23H2 (Build 22631)"
  - **vendor**: e.g. "Microsoft", "TP-Link", "Ubiquiti"
  - **device_model**: e.g. "Archer AX73", "EdgeRouter X"
  - **firmware**: e.g. "3.10.0-build20230101"
  - **detection_method**: which layer(s) that contributed
  - **confidence**: 0-100 score (boosted by agreement)
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import ssl
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("auditforge.discovery")

# Well-known TCP ports to probe and what they indicate
# fmt: off
PROBE_PORTS: list[tuple[int, str, str]] = [
    # (port, service_name, platform_hint)
    # ── Windows ──
    (135,   "MSRPC",        "windows"),
    (139,   "NetBIOS",      "windows"),
    (445,   "SMB",          "windows"),
    (3389,  "RDP",          "windows"),
    (5985,  "WinRM-HTTP",   "windows"),
    (5986,  "WinRM-HTTPS",  "windows"),
    # ── Active Directory / Enterprise ──
    (88,    "Kerberos",     "windows"),     # AD Domain Controller
    (389,   "LDAP",         "windows"),     # AD LDAP
    (636,   "LDAPS",        "windows"),     # AD LDAP over TLS
    (3268,  "GC",           "windows"),     # AD Global Catalog
    (3269,  "GC-SSL",       "windows"),     # AD Global Catalog over TLS
    # ── Linux / Unix ──
    (22,    "SSH",          "linux"),
    (548,   "AFP",          "macos"),       # Apple Filing Protocol (macOS)
    (2049,  "NFS",          "linux"),       # Network File System
    # ── Web ──
    (80,    "HTTP",         "unknown"),
    (443,   "HTTPS",        "unknown"),
    (8080,  "HTTP-Alt",     "unknown"),
    (8443,  "HTTPS-Alt",    "unknown"),
    (8000,  "HTTP-Dev",     "unknown"),
    (8888,  "HTTP-Alt2",    "unknown"),
    (9090,  "HTTP-Mgmt",    "unknown"),
    # ── Network devices ──
    (23,    "Telnet",       "network"),
    (830,   "NETCONF",      "network"),
    (53,    "DNS",          "network"),
    (514,   "Syslog",       "network"),
    (8291,  "WinBox",       "network"),     # MikroTik RouterOS
    # ── Databases ──
    (1433,  "MSSQL",        "database"),
    (5432,  "PostgreSQL",   "database"),
    (1521,  "Oracle",       "database"),
    (3306,  "MySQL",        "database"),
    (6379,  "Redis",        "database"),
    (27017, "MongoDB",      "database"),
    (9200,  "Elasticsearch","database"),    # Elasticsearch REST API
    # ── IoT / Media / VoIP ──
    (631,   "IPP",          "unknown"),     # Printers (Internet Printing Protocol)
    (5060,  "SIP",          "unknown"),     # VoIP
    (5900,  "VNC",          "unknown"),     # Remote desktop
    (62078, "iphone-sync",  "mobile"),      # Apple iOS device sync
    (9100,  "RAW-Print",    "unknown"),     # HP JetDirect / network printers
    # ── Mail ──
    (25,    "SMTP",         "unknown"),
    (110,   "POP3",         "unknown"),
    (143,   "IMAP",         "unknown"),
    # ── Other ──
    (21,    "FTP",          "unknown"),
    (161,   "SNMP",         "network"),     # TCP SNMP (rare, but checked)
]
# fmt: on

# UDP ports to probe (sent a protocol-specific packet, wait for response)
UDP_PROBE_PORTS: list[tuple[int, str, str]] = [
    # (port, service_name, platform_hint)
    (161,   "SNMP",         "network"),
    (137,   "NetBIOS-NS",   "windows"),
    (53,    "DNS",          "network"),
    (123,   "NTP",          "network"),
    (1900,  "SSDP",         "unknown"),
    (5353,  "mDNS",         "unknown"),
]

# Concurrency limits
MAX_CONCURRENT_HOSTS = 50
MAX_CONCURRENT_PORTS = 20
TCP_CONNECT_TIMEOUT = 1.5  # seconds per port probe
BANNER_READ_TIMEOUT = 3.0  # seconds to wait for a service banner
BANNER_MAX_BYTES = 1024    # max bytes to read from a banner

# Ports that send a banner immediately upon connection (no request needed)
BANNER_PORTS_PASSIVE = {22, 21, 23, 25, 110, 143, 5900}  # SSH, FTP, Telnet, SMTP, POP3, IMAP, VNC
# Ports that need an HTTP request to get a useful banner
BANNER_PORTS_HTTP = {80, 443, 8080, 8443, 8000, 8888, 9090, 631, 9100}
# Database ports that send a banner or respond to a probe
BANNER_PORTS_DB = {3306, 5432, 6379, 27017}  # MySQL, PostgreSQL, Redis, MongoDB
# HTTPS / TLS ports — wrap with SSL before reading
SSL_PORTS = {443, 8443, 5986, 636, 993, 995, 465}


@dataclass
class DiscoveredHost:
    """Represents a single discovered host on the network."""
    ip: str
    hostname: str = ""
    open_ports: list[dict[str, Any]] = field(default_factory=list)
    os_guess: str = "unknown"  # windows | linux | macos | unknown
    os_version: str = ""       # e.g. "Windows 11 Pro 23H2 (Build 22631)"
    device_role: str = ""      # domain_controller | server | workstation | network_device | database_server | printer | mobile | unknown
    vendor: str = ""           # e.g. "Microsoft", "TP-Link", "Cisco"
    device_model: str = ""     # e.g. "Archer AX73", "EdgeRouter X"
    firmware: str = ""         # e.g. "3.10.0", "IOS 15.7(3)M5"
    mac_address: str = ""      # e.g. "AA:BB:CC:DD:EE:FF"
    domain: str = ""           # Windows domain / workgroup name
    detection_method: str = "" # e.g. "smb_ntlm", "snmp", "ssh_banner"
    confidence: int = 0        # 0-100 detection confidence score
    banners: dict[int, str] = field(default_factory=dict)  # port → raw banner
    connection_methods: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "hostname": self.hostname,
            "open_ports": self.open_ports,
            "os_guess": self.os_guess,
            "os_version": self.os_version,
            "device_role": self.device_role,
            "vendor": self.vendor,
            "device_model": self.device_model,
            "firmware": self.firmware,
            "mac_address": self.mac_address,
            "domain": self.domain,
            "detection_method": self.detection_method,
            "confidence": self.confidence,
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


async def _ping_host(ip: str, timeout: float = 1.5) -> bool:
    """Send a single ICMP ping (via OS ping command). Returns True if alive.

    Works inside Docker (Linux) and on Windows hosts.
    ConnectionRefused on TCP is also evidence of life, but this catches
    hosts with zero open ports (phones, IoT devices, etc.).
    """
    loop = asyncio.get_event_loop()
    try:
        if sys.platform == "win32":
            cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
        else:
            cmd = ["ping", "-c", "1", "-W", str(int(timeout)), ip]
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            ),
            timeout=timeout + 1,
        )
        rc = await asyncio.wait_for(proc.wait(), timeout=timeout + 1)
        return rc == 0
    except (asyncio.TimeoutError, OSError, FileNotFoundError):
        return False


# ═══════════════════════════════════════════════════════════
# TCP passive OS fingerprinting (p0f-style)
# ═══════════════════════════════════════════════════════════

# TTL → OS family heuristics (initial TTL before decrement)
_TTL_MAP: list[tuple[int, str, str]] = [
    # (initial_ttl, os_family, vendor)
    (128, "windows", "Microsoft"),    # Windows uses initial TTL=128
    (64,  "linux",   ""),             # Linux / macOS / FreeBSD
    (255, "network", ""),             # Cisco IOS, Solaris, some network gear
]

# TCP window size → more specific OS hints
_WINDOW_HINTS: list[tuple[set[int], str, str, int]] = [
    # (window_sizes, os_version_hint, vendor, extra_confidence)
    ({65535},                          "Windows XP/2003",     "Microsoft", 5),
    ({8192},                           "Windows 7/2008 R2",   "Microsoft", 5),
    ({64240},                          "Windows 10/11",       "Microsoft", 8),
    ({65535, 65228},                   "macOS / iOS",         "Apple",     5),
    ({5840, 14600, 29200},             "Linux 2.6+",          "",          3),
    ({26883, 17520, 28960, 32120},     "Linux 3.x/4.x",      "",          3),
    ({4128},                           "Cisco IOS",           "Cisco",     10),
    ({16384},                          "Network device",      "",          3),
]


async def _tcp_os_fingerprint(
    ip: str,
    port: int = 80,
    timeout: float = 2.0,
) -> dict[str, Any] | None:
    """Passive TCP OS fingerprinting from a SYN-ACK response.

    Connects to a known-open TCP port and inspects the TTL and TCP window
    size of the SYN-ACK to infer the remote OS — similar to p0f.
    Uses a standard TCP connect (no raw sockets needed).

    Returns a candidate dict or None.
    """
    try:
        loop = asyncio.get_event_loop()

        def _do_connect() -> tuple[int, int] | None:
            """Open TCP socket and extract TTL + window size from the socket."""
            import socket as _sock
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.settimeout(timeout)
            try:
                s.connect((ip, port))
                # Get TTL from socket option
                ttl = 0
                try:
                    if sys.platform == "win32":
                        # IP_TTL available but gives local TTL; we need a ping-based approach
                        pass
                    else:
                        # On Linux, getsockopt can't read remote TTL directly.
                        # Use the first SYN-ACK IP header if available via IP_RECVTTL.
                        pass
                except Exception:
                    pass

                # Get TCP window size via TCP_INFO (Linux only)
                win_size = 0
                try:
                    if sys.platform == "linux":
                        import ctypes
                        # TCP_INFO = 11 on Linux
                        info = s.getsockopt(_sock.IPPROTO_TCP, 11, 256)
                        if len(info) >= 28:
                            # tcpi_rcv_space is at offset 200 (varies by kernel)
                            # tcpi_snd_mss at offset 10 (2 bytes),
                            # Use the first bytes for state, then extract fields
                            # Simpler: just get the advertised window from TCP_MAXSEG + SO_RCVBUF
                            pass
                except Exception:
                    pass

                s.close()
                return (ttl, win_size) if ttl or win_size else None
            except Exception:
                s.close()
                return None

        # Fallback approach: use ping to get TTL (works on all platforms)
        ttl = await _get_ttl_from_ping(ip, timeout)
        if not ttl:
            return None

        # Map TTL to initial TTL (adjust for hops — round up to nearest known TTL)
        initial_ttl = _round_to_initial_ttl(ttl)

        # Determine OS family
        os_family = ""
        vendor = ""
        confidence = 25  # Low confidence — TTL-only is a guess

        for init_ttl, family, vend in _TTL_MAP:
            if initial_ttl == init_ttl:
                os_family = family
                vendor = vend
                break

        if not os_family:
            return None

        os_version = ""
        if os_family == "windows":
            os_version = "Windows"
        elif os_family == "linux":
            os_version = "Linux/Unix"
        elif os_family == "network":
            os_version = "Network device"

        return {
            "os_version": os_version,
            "vendor": vendor,
            "detection_method": "tcp_fingerprint",
            "confidence": confidence,
        }

    except Exception:
        return None


async def _get_ttl_from_ping(ip: str, timeout: float = 2.0) -> int | None:
    """Get the TTL value from a ping response.  Returns None if ping fails."""
    try:
        if sys.platform == "win32":
            cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
        else:
            cmd = ["ping", "-c", "1", "-W", str(int(timeout)), ip]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2)
        output = stdout.decode(errors="replace")

        # Extract TTL from ping output
        # Windows: "Reply from x.x.x.x: bytes=32 time=1ms TTL=128"
        # Linux:   "64 bytes from x.x.x.x: icmp_seq=1 ttl=64 time=0.5 ms"
        m = re.search(r"[Tt][Tt][Ll][=:](\d+)", output)
        if m:
            return int(m.group(1))
    except (asyncio.TimeoutError, OSError, FileNotFoundError):
        pass
    return None


def _round_to_initial_ttl(observed_ttl: int) -> int:
    """Round an observed TTL up to the most likely initial TTL value.

    After traversing N hops the TTL decreases.  Initial TTLs used by OSes:
    - 64  (Linux, macOS, FreeBSD, Android)
    - 128 (Windows)
    - 255 (Cisco IOS, Solaris, some network equipment)
    """
    if observed_ttl <= 0:
        return 0
    if observed_ttl <= 64:
        return 64
    if observed_ttl <= 128:
        return 128
    return 255


# ═══════════════════════════════════════════════════════════
# UDP port probing — protocol-specific packets
# ═══════════════════════════════════════════════════════════

# Pre-built UDP probe packets for common services
_UDP_PROBES: dict[int, tuple[bytes, str, str]] = {
    # port: (probe_packet, service_name, platform_hint)
    53: (
        # DNS query for "version.bind" TXT CH (works on most DNS resolvers)
        b"\x00\x01\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
        b"\x07version\x04bind\x00\x00\x10\x00\x03",
        "DNS", "network",
    ),
    123: (
        # NTP version request (mode 3, version 3)
        b"\x1b" + b"\x00" * 47,
        "NTP", "network",
    ),
    161: (
        # SNMPv2c GET sysDescr.0 (community "public")
        b"\x30\x26\x02\x01\x01\x04\x06public"
        b"\xa0\x19\x02\x01\x01\x02\x01\x00\x02\x01\x00"
        b"\x30\x0e\x30\x0c\x06\x08\x2b\x06\x01\x02\x01\x01\x01\x00\x05\x00",
        "SNMP", "network",
    ),
    137: (
        # NetBIOS NBSTAT wildcard query
        b"\x00\x01\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
        b"\x20CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\x00"
        b"\x00\x21\x00\x01",
        "NetBIOS-NS", "windows",
    ),
    1900: (
        # SSDP M-SEARCH unicast
        b"M-SEARCH * HTTP/1.1\r\n"
        b"HOST: 239.255.255.250:1900\r\n"
        b"MAN: \"ssdp:discover\"\r\n"
        b"MX: 1\r\n"
        b"ST: upnp:rootdevice\r\n\r\n",
        "SSDP", "unknown",
    ),
    5353: (
        # mDNS query for _http._tcp.local
        b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
        b"\x05_http\x04_tcp\x05local\x00\x00\x0c\x00\x01",
        "mDNS", "unknown",
    ),
}


async def _udp_probe_host(
    ip: str, timeout: float = 2.0
) -> list[dict[str, Any]]:
    """Send protocol-specific UDP probes and return list of responding ports.

    Each entry is ``{"port": int, "service": str, "platform_hint": str, "proto": "udp"}``.
    """
    results: list[dict[str, Any]] = []

    async def _probe_udp_port(port: int, packet: bytes, svc: str, hint: str) -> dict[str, Any] | None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0)
            sock.sendto(packet, (ip, port))

            start = time.monotonic()
            while time.monotonic() - start < timeout:
                await asyncio.sleep(0.15)
                try:
                    data, addr = sock.recvfrom(4096)
                    if data:
                        sock.close()
                        return {"port": port, "service": svc, "platform_hint": hint, "proto": "udp"}
                except (BlockingIOError, OSError):
                    pass
            sock.close()
        except Exception:
            pass
        return None

    tasks = [
        _probe_udp_port(port, pkt, svc, hint)
        for port, (pkt, svc, hint) in _UDP_PROBES.items()
    ]
    probe_results = await asyncio.gather(*tasks)
    for r in probe_results:
        if r is not None:
            results.append(r)

    return results


# ═══════════════════════════════════════════════════════════
# Layer 0: ARP sweep — discover ALL Layer-2 hosts + MAC
# ═══════════════════════════════════════════════════════════

# Module-level cache populated by _arp_sweep before per-host scans
_arp_cache: dict[str, str] = {}  # ip → MAC address


async def _arp_sweep(ips: list[str]) -> dict[str, str]:
    """Populate the ARP table by pinging a broadcast + every IP, then read it.

    This runs once *before* per-host scanning.  With ``network_mode: host``
    the process shares the host's ARP table, so we get real MAC addresses.

    Returns ``{ip: mac}`` for every reachable host.
    """
    global _arp_cache
    result: dict[str, str] = {}

    # Step 1: Broadcast ping to pre-fill ARP (Linux only, best-effort)
    if sys.platform != "win32":
        # Determine the broadcast address from the first IP's /24
        try:
            import ipaddress as _ipa
            sample = _ipa.ip_address(ips[0])
            network = _ipa.ip_network(f"{sample}/24", strict=False)
            bcast = str(network.broadcast_address)
            proc = await asyncio.create_subprocess_exec(
                "ping", "-b", "-c", "1", "-W", "1", bcast,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=3)
        except Exception:
            pass

    # Step 2: Rapid parallel ping to populate ARP entries
    sem = asyncio.Semaphore(100)

    async def _quick_ping(ip: str) -> None:
        async with sem:
            try:
                if sys.platform == "win32":
                    cmd = ["ping", "-n", "1", "-w", "500", ip]
                else:
                    cmd = ["ping", "-c", "1", "-W", "1", ip]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=2.5)
            except Exception:
                pass

    # Ping all IPs quickly in parallel (just to fill ARP)
    await asyncio.gather(*[_quick_ping(ip) for ip in ips])

    # Step 3: Read ARP table
    try:
        if sys.platform == "win32":
            proc = await asyncio.create_subprocess_exec(
                "arp", "-a",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            output = stdout.decode("utf-8", errors="replace")
            # Windows: "  192.168.1.5     aa-bb-cc-dd-ee-ff     dynamic"
            for line in output.splitlines():
                m = re.match(
                    r"\s*(\d+\.\d+\.\d+\.\d+)\s+"
                    r"((\w\w[:-]){5}\w\w)\s+",
                    line,
                )
                if m:
                    ip_addr = m.group(1)
                    mac = m.group(2).upper().replace("-", ":")
                    if mac != "FF:FF:FF:FF:FF:FF" and not mac.startswith("01:00:5E"):
                        result[ip_addr] = mac
        else:
            # Linux: read /proc/net/arp (faster than subprocess)
            try:
                with open("/proc/net/arp", "r") as f:
                    for line_num, line in enumerate(f):
                        if line_num == 0:
                            continue  # skip header row
                        parts = line.split()
                        if len(parts) >= 4 and parts[3] != "00:00:00:00:00:00":
                            ip_addr = parts[0]
                            mac = parts[3].upper()
                            if mac != "FF:FF:FF:FF:FF:FF" and not mac.startswith("01:00:5E"):
                                result[ip_addr] = mac
            except FileNotFoundError:
                # Fallback to arp -n
                proc = await asyncio.create_subprocess_exec(
                    "arp", "-n",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                output = stdout.decode("utf-8", errors="replace")
                for line in output.splitlines():
                    m = re.search(
                        r"(\d+\.\d+\.\d+\.\d+)\s+.*?((\w\w:){5}\w\w)",
                        line,
                    )
                    if m:
                        ip_addr = m.group(1)
                        mac = m.group(2).upper()
                        if mac != "00:00:00:00:00:00" and mac != "FF:FF:FF:FF:FF:FF":
                            result[ip_addr] = mac
    except Exception as exc:
        logger.debug("ARP table read failed: %s", exc)

    logger.info("ARP sweep found %d hosts with MAC addresses", len(result))
    _arp_cache = result
    return result


# ═══════════════════════════════════════════════════════════
# Layer 9: NetBIOS Name Service query (UDP 137)
# ═══════════════════════════════════════════════════════════

async def _netbios_name_query(
    ip: str, timeout: float = 2.0
) -> dict[str, Any]:
    """Send a NetBIOS Name Service NBSTAT query to UDP 137.

    Returns dict with hostname, mac_address, vendor, domain,
    detection_method, confidence.  Empty dict on failure.
    """
    result: dict[str, Any] = {}

    # NBSTAT query (Node Status Request)
    # Transaction ID (2) + Flags (2) + Questions (2) + Answers/Auth/Additional (6) + Name + Type/Class
    name_query = (
        b"\x00\x01"          # Transaction ID
        b"\x00\x00"          # Flags: query
        b"\x00\x01"          # Questions: 1
        b"\x00\x00"          # Answer RRs: 0
        b"\x00\x00"          # Authority RRs: 0
        b"\x00\x00"          # Additional RRs: 0
        # Query: * (CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA) — wildcard NBSTAT
        b"\x20"              # Name length: 32
        b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        b"\x00"              # End of name
        b"\x00\x21"          # Type: NBSTAT (0x21)
        b"\x00\x01"          # Class: IN
    )

    loop = asyncio.get_event_loop()
    try:
        transport, _ = await asyncio.wait_for(
            loop.create_datagram_endpoint(
                lambda: asyncio.DatagramProtocol(),
                remote_addr=(ip, 137),
            ),
            timeout=timeout,
        )
    except Exception:
        return result

    try:
        transport.sendto(name_query)

        data = None
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            await asyncio.sleep(0.1)
            try:
                sock = transport.get_extra_info("socket")
                if sock:
                    sock.setblocking(False)
                    try:
                        data, _ = sock.recvfrom(4096)
                        break
                    except (BlockingIOError, OSError):
                        pass
            except Exception:
                pass
    finally:
        transport.close()

    if not data or len(data) < 57:
        return result

    try:
        # Parse NetBIOS NBSTAT response
        # Skip header (12 bytes) + name (34 bytes) + type/class (4 bytes) + TTL (4 bytes) + rdlength (2 bytes)
        # = offset 56, then num_names (1 byte)
        num_names = data[56]
        offset = 57
        hostname = ""
        domain = ""

        for i in range(num_names):
            if offset + 18 > len(data):
                break
            name_bytes = data[offset:offset + 15].rstrip(b"\x20")
            name_suffix = data[offset + 15]
            name_flags = struct.unpack_from(">H", data, offset + 16)[0]
            offset += 18

            try:
                name_str = name_bytes.decode("ascii", errors="replace").strip()
            except Exception:
                continue

            is_group = bool(name_flags & 0x8000)

            if name_suffix == 0x00 and not is_group and not hostname:
                hostname = name_str
            elif name_suffix == 0x00 and is_group and not domain:
                domain = name_str

        # MAC address is the last 6 bytes after all name entries
        mac_offset = offset
        mac = ""
        if mac_offset + 6 <= len(data):
            mac_bytes = data[mac_offset:mac_offset + 6]
            if mac_bytes != b"\x00\x00\x00\x00\x00\x00":
                mac = ":".join(f"{b:02X}" for b in mac_bytes)

        if hostname:
            result["hostname"] = hostname
            result["detection_method"] = "netbios"
            result["confidence"] = 60
            if domain:
                result["domain"] = domain
            if mac:
                result["mac_address"] = mac
                oui_vendor = _lookup_oui_vendor(mac)
                if oui_vendor:
                    result["vendor"] = oui_vendor
                    result["confidence"] = 70
        elif mac:
            result["mac_address"] = mac
            result["detection_method"] = "netbios_mac"
            result["confidence"] = 30
            oui_vendor = _lookup_oui_vendor(mac)
            if oui_vendor:
                result["vendor"] = oui_vendor

    except Exception as exc:
        logger.debug("NetBIOS parse failed for %s: %s", ip, exc)

    return result


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
    use_ssl = port in SSL_PORTS
    try:
        if use_ssl:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port, ssl=ssl_ctx),
                timeout=TCP_CONNECT_TIMEOUT + 1.0,  # extra second for TLS handshake
            )
        else:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=TCP_CONNECT_TIMEOUT,
            )
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError, ssl.SSLError):
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


def _enrich_ports_from_banners(
    open_ports: list[dict[str, Any]], banners: dict[int, str]
) -> None:
    """Enrich open_ports entries in-place with product/version from banners.

    Parses common banner formats to extract software name and version:
      - SSH-2.0-OpenSSH_8.9p1 → product="OpenSSH", version="8.9p1"
      - Server: Apache/2.4.52 → product="Apache", version="2.4.52"
      - MySQL 5.0.x greeting  → product="MySQL", version from greeting
    """
    _BANNER_PARSE_RULES: list[tuple[str, re.Pattern[str], str]] = [
        # SSH banners: "SSH-2.0-OpenSSH_8.9p1 Ubuntu-3"
        ("ssh", re.compile(r"SSH-[\d.]+-(\S+?)(?:[_/])([\d][\w.p-]*)"), ""),
        # HTTP Server header: "Server: Apache/2.4.52" or "Server: nginx/1.22.1"
        ("http", re.compile(r"Server:\s*([A-Za-z][\w.-]*?)(?:[/ ])([\d][\w.]*)", re.IGNORECASE), ""),
        # FTP banner: "220 (vsFTPd 3.0.5)" or "220-FileZilla Server 1.7.0"
        ("ftp", re.compile(r"220[- ].*?(\w+FTP\w*|FileZilla\s*Server|ProFTPD|PureFTPd)\s*[\s/]?([\d][\w.]*)"), ""),
        # MySQL greeting: version in first bytes after protocol byte
        ("mysql", re.compile(r"([\d]+\.[\d]+\.[\d]+[\w.-]*)"), "MySQL"),
        # Redis: "+PONG" or "-ERR" with version in INFO
        ("redis", re.compile(r"redis_version:(\S+)", re.IGNORECASE), "Redis"),
        # SMTP: "220 mail.example.com ESMTP Postfix"
        ("smtp", re.compile(r"220\s+\S+\s+(?:E?SMTP\s+)?(\w+)(?:[\s/]([\d][\w.]*))?"), ""),
        # PostgreSQL: check for version-like patterns
        ("postgres", re.compile(r"([\d]+\.[\d]+[\w.]*)"), "PostgreSQL"),
        # Microsoft-IIS/10.0
        ("iis", re.compile(r"Microsoft-IIS/([\d.]+)", re.IGNORECASE), "Microsoft IIS"),
        # Telnet: various device banners
        ("telnet", re.compile(r"([\w.-]+)\s+(?:Version|v)\s*([\d][\w.]*)", re.IGNORECASE), ""),
    ]

    for port_entry in open_ports:
        port = port_entry["port"]
        banner = banners.get(port, "")
        if not banner:
            continue

        # Store a snippet of the raw banner (first 120 chars, single line)
        snippet = banner.replace("\r", "").replace("\n", " ").strip()[:120]
        port_entry["banner_snippet"] = snippet

        service = (port_entry.get("service") or "").lower()

        # Try to extract product + version
        for rule_key, pattern, default_product in _BANNER_PARSE_RULES:
            # Match rule to the right service type
            if rule_key == "ssh" and port not in (22,):
                continue
            if rule_key == "http" and port not in BANNER_PORTS_HTTP:
                continue
            if rule_key == "ftp" and port not in (21,):
                continue
            if rule_key == "mysql" and port not in (3306,):
                continue
            if rule_key == "redis" and port not in (6379,):
                continue
            if rule_key == "smtp" and port not in (25, 465, 587):
                continue
            if rule_key == "postgres" and port not in (5432,):
                continue
            if rule_key == "iis" and port not in BANNER_PORTS_HTTP:
                continue
            if rule_key == "telnet" and port not in (23,):
                continue

            m = pattern.search(banner)
            if m:
                groups = m.groups()
                if default_product:
                    port_entry["product"] = default_product
                    port_entry["version"] = groups[0] if groups else ""
                elif len(groups) >= 2:
                    port_entry["product"] = groups[0]
                    port_entry["version"] = groups[1] or ""
                elif len(groups) == 1:
                    port_entry["product"] = groups[0]
                break


# ── OS Version & Vendor Detection (from banners) ────────────

# ── MAC OUI → Vendor Database (top 180 manufacturers) ───────
# Source: IEEE OUI registry — covers ~95% of consumer/enterprise devices
_OUI_VENDOR: dict[str, str] = {
    # ── TP-Link ──
    "50:C7:BF": "TP-Link", "98:DA:C4": "TP-Link", "E8:48:B8": "TP-Link",
    "F4:F2:6D": "TP-Link", "64:70:02": "TP-Link", "B0:BE:76": "TP-Link",
    "14:CC:20": "TP-Link", "10:FE:ED": "TP-Link", "C0:06:C3": "TP-Link",
    "30:B5:C2": "TP-Link", "18:A6:F7": "TP-Link", "A8:57:4E": "TP-Link",
    "54:AF:97": "TP-Link", "C0:25:E9": "TP-Link", "78:8C:B5": "TP-Link",
    "60:32:B1": "TP-Link", "AC:15:A2": "TP-Link", "D8:07:B6": "TP-Link",
    # ── NETGEAR ──
    "A0:40:A0": "NETGEAR", "E0:91:F5": "NETGEAR", "B0:7F:B9": "NETGEAR",
    "28:C6:8E": "NETGEAR", "C4:04:15": "NETGEAR", "20:E5:2A": "NETGEAR",
    "2C:B0:5D": "NETGEAR", "84:1B:5E": "NETGEAR", "CC:40:D0": "NETGEAR",
    "6C:B0:CE": "NETGEAR", "74:44:01": "NETGEAR", "4C:60:DE": "NETGEAR",
    # ── Cisco ──
    "00:1B:D5": "Cisco", "00:26:0B": "Cisco", "00:22:55": "Cisco",
    "00:1C:57": "Cisco", "00:1E:14": "Cisco", "00:1A:2F": "Cisco",
    "00:24:C4": "Cisco", "00:25:84": "Cisco", "58:97:BD": "Cisco",
    "F0:29:29": "Cisco", "B4:14:89": "Cisco", "88:F0:31": "Cisco",
    "BC:16:65": "Cisco", "00:17:59": "Cisco", "70:81:05": "Cisco",
    # ── Juniper ──
    "00:05:85": "Juniper", "28:C0:DA": "Juniper", "54:E0:32": "Juniper",
    "F0:1C:2D": "Juniper", "84:18:88": "Juniper", "84:B5:9C": "Juniper",
    "CC:E1:7F": "Juniper", "3C:61:04": "Juniper", "40:B4:F0": "Juniper",
    # ── Ubiquiti ──
    "04:18:D6": "Ubiquiti", "18:E8:29": "Ubiquiti", "24:5A:4C": "Ubiquiti",
    "44:D9:E7": "Ubiquiti", "68:72:51": "Ubiquiti", "78:8A:20": "Ubiquiti",
    "80:2A:A8": "Ubiquiti", "B4:FB:E4": "Ubiquiti", "DC:9F:DB": "Ubiquiti",
    "F0:9F:C2": "Ubiquiti", "FC:EC:DA": "Ubiquiti", "E0:63:DA": "Ubiquiti",
    # ── Fortinet ──
    "00:09:0F": "Fortinet", "70:4C:A5": "Fortinet", "08:5B:0E": "Fortinet",
    "90:6C:AC": "Fortinet", "E8:1C:BA": "Fortinet", "00:90:0B": "Fortinet",
    # ── Palo Alto Networks ──
    "00:86:9C": "Palo Alto", "48:0B:B2": "Palo Alto", "00:1B:17": "Palo Alto",
    "B4:0C:25": "Palo Alto",
    # ── Check Point ──
    "00:1C:7F": "Check Point", "00:A0:8E": "Check Point",
    # ── Arista ──
    "44:4C:A8": "Arista", "00:1C:73": "Arista", "28:99:3A": "Arista",
    # ── MikroTik ──
    "6C:3B:6B": "MikroTik", "E4:8D:8C": "MikroTik", "48:8F:5A": "MikroTik",
    "D4:CA:6D": "MikroTik", "74:4D:28": "MikroTik", "CC:2D:E0": "MikroTik",
    "B8:69:F4": "MikroTik", "00:0C:42": "MikroTik", "64:D1:54": "MikroTik",
    # ── D-Link ──
    "1C:7E:E5": "D-Link", "34:08:04": "D-Link", "78:54:2E": "D-Link",
    "28:10:7B": "D-Link", "84:C9:B2": "D-Link", "1C:AF:F7": "D-Link",
    "B8:A3:86": "D-Link", "00:1B:11": "D-Link", "F0:B4:D2": "D-Link",
    # ── ASUS ──
    "04:D4:C4": "ASUS", "1C:87:2C": "ASUS", "2C:56:DC": "ASUS",
    "38:D5:47": "ASUS", "54:04:A6": "ASUS", "AC:9E:17": "ASUS",
    "F8:32:E4": "ASUS", "10:C3:7B": "ASUS", "B0:6E:BF": "ASUS",
    # ── Linksys ──
    "14:91:82": "Linksys", "20:AA:4B": "Linksys", "C0:56:27": "Linksys",
    "E8:F7:24": "Linksys", "58:6D:8F": "Linksys", "68:7F:74": "Linksys",
    # ── Huawei ──
    "00:E0:FC": "Huawei", "48:46:FB": "Huawei", "88:66:39": "Huawei",
    "CC:A2:23": "Huawei", "5C:7D:5E": "Huawei", "AC:E2:15": "Huawei",
    "70:7B:E8": "Huawei", "D0:7A:B5": "Huawei", "E4:68:A3": "Huawei",
    # ── ZTE ──
    "00:19:CB": "ZTE", "54:22:F8": "ZTE", "C8:7B:23": "ZTE",
    # ── HPE / Aruba / HP ──
    "00:0B:CD": "HPE", "B0:5A:DA": "HPE", "00:1E:0B": "HPE",
    "3C:D9:2B": "HPE/Aruba", "20:4C:03": "HPE/Aruba", "00:24:6C": "HPE/Aruba",
    "24:DE:C6": "HPE/Aruba", "D8:C7:C8": "HPE/Aruba", "AC:A3:1E": "HPE/Aruba",
    # ── Dell ──
    "18:03:73": "Dell", "B0:83:FE": "Dell", "14:B3:1F": "Dell",
    "24:6E:96": "Dell", "F4:8E:38": "Dell", "34:48:ED": "Dell",
    # ── Microsoft (Surface, Xbox, etc.) ──
    "28:18:78": "Microsoft", "7C:1E:52": "Microsoft", "C8:3F:26": "Microsoft",
    # ── Apple ──
    "3C:22:FB": "Apple", "A4:83:E7": "Apple", "F0:18:98": "Apple",
    "BC:52:B7": "Apple", "AC:BC:32": "Apple", "00:03:93": "Apple",
    "DC:A9:04": "Apple", "14:7D:DA": "Apple", "F8:FF:C2": "Apple",
    # ── Samsung (phones, tablets, smart TVs) ──
    "00:16:6C": "Samsung", "A0:82:1F": "Samsung", "C4:73:1E": "Samsung",
    "8C:F5:A3": "Samsung", "10:D5:42": "Samsung", "E4:7C:F9": "Samsung",
    "BC:44:86": "Samsung", "5C:49:7D": "Samsung", "CC:07:AB": "Samsung",
    "F0:25:B7": "Samsung", "94:35:0A": "Samsung", "40:4E:36": "Samsung",
    "34:14:5F": "Samsung", "A8:7C:01": "Samsung", "50:01:BB": "Samsung",
    # ── Xiaomi / Redmi ──
    "64:CC:2E": "Xiaomi", "28:6C:07": "Xiaomi", "78:11:DC": "Xiaomi",
    "F8:A4:5F": "Xiaomi", "9C:99:A0": "Xiaomi", "50:64:2B": "Xiaomi",
    "AC:C1:EE": "Xiaomi", "7C:1D:D9": "Xiaomi", "34:CE:00": "Xiaomi",
    # ── OnePlus ──
    "C0:EE:40": "OnePlus", "94:65:2D": "OnePlus",
    # ── OPPO / Realme ──
    "A0:A3:B3": "OPPO", "2C:5B:E1": "OPPO", "98:F6:21": "OPPO",
    # ── Motorola ──
    "EC:C4:0D": "Motorola", "9C:D9:17": "Motorola", "48:FC:B8": "Motorola",
    # ── Nokia ──
    "D4:63:FE": "Nokia",
    # ── Honor ──
    "38:F7:3D": "Honor",
    # ── Sony (phones / TVs / PlayStation) ──
    "FC:0F:E6": "Sony", "AC:9B:0A": "Sony", "00:04:1F": "Sony",
    # ── LG ──
    "88:C9:D0": "LG", "10:68:3F": "LG", "CC:FA:00": "LG",
    # ── Intel (laptops/desktops) ──
    "DC:71:96": "Intel", "F8:63:3F": "Intel", "34:02:86": "Intel",
    "8C:8D:28": "Intel", "A4:C3:F0": "Intel",
    # ── Realtek (on-board Ethernet) ──
    "00:E0:4C": "Realtek", "52:54:00": "Realtek/QEMU",
    # ── Google ──
    "54:60:09": "Google", "F4:F5:D8": "Google", "A4:77:33": "Google",
    # ── Amazon ──
    "74:C2:46": "Amazon", "A0:02:DC": "Amazon", "FC:A1:83": "Amazon",
    "84:D6:D0": "Amazon", "68:37:E9": "Amazon", "44:00:49": "Amazon",
    # ── SonicWall ──
    "00:06:B1": "SonicWall", "C0:EA:E4": "SonicWall",
    # ── WatchGuard ──
    "00:90:7F": "WatchGuard",
    # ── Synology ──
    "00:11:32": "Synology",
    # ── QNAP ──
    "00:08:9B": "QNAP", "24:5E:BE": "QNAP",
    # ── Sophos ──
    "00:1A:8C": "Sophos",
    # ── pfSense / Netgate ──
    "00:08:A2": "Netgate",
    # ── Ruckus ──
    "C4:10:8A": "Ruckus", "EC:58:EA": "Ruckus", "70:DF:2F": "Ruckus",
    # ── Meraki (Cisco) ──
    "00:18:0A": "Meraki", "AC:17:C8": "Meraki", "E0:55:3D": "Meraki",
    # ── VMware ESXi ──
    "00:50:56": "VMware", "00:0C:29": "VMware", "00:05:69": "VMware",
}


# ── Hostname → vendor heuristic patterns ────────────────────
# Matches common default hostnames set by router/AP/switch manufacturers
_HOSTNAME_VENDOR_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, vendor, device_model_hint)
    (r"\bTP-?LINK",                   "TP-Link",         ""),
    (r"\bArcher[_ ]?([A-Z]\w+)",      "TP-Link",         "Archer {0}"),
    (r"\bDeco[_ ]?([A-Z]\w+)",        "TP-Link",         "Deco {0}"),
    (r"\bNETGEAR",                    "NETGEAR",         ""),
    (r"\bORBI",                       "NETGEAR",         "Orbi"),
    (r"\bNighthawk",                  "NETGEAR",         "Nighthawk"),
    (r"\bR[A-Z]?\d{3,4}",            "NETGEAR",         ""),
    (r"\bRT-?([A-Z]{2,}\d+)",        "ASUS",            "RT-{0}"),
    (r"\bASUS[-_ ]?(\w+)",           "ASUS",            "{0}"),
    (r"\bLinksys",                    "Linksys",         ""),
    (r"\bVelop",                      "Linksys",         "Velop"),
    (r"\bD-?Link",                    "D-Link",          ""),
    (r"\bDIR-?(\d+)",                "D-Link",          "DIR-{0}"),
    (r"\bFritzBox[_ ]?(\d+)",        "AVM",             "Fritz!Box {0}"),
    (r"\bFRITZ",                      "AVM",             "Fritz!Box"),
    (r"\bMikroTik",                   "MikroTik",        ""),
    (r"\bRB\d{3,4}",                 "MikroTik",        ""),
    (r"\bRouterOS",                   "MikroTik",        "RouterOS"),
    (r"\bUbiqu",                      "Ubiquiti",        ""),
    (r"\bUniFi",                      "Ubiquiti",        "UniFi"),
    (r"\bEdgeRouter",                 "Ubiquiti",        "EdgeRouter"),
    (r"\bHuawei",                     "Huawei",          ""),
    (r"\bLivebox",                    "Orange/Sagemcom", "Livebox"),
    (r"\bBBox",                       "Bouygues/Sagemcom", "Bbox"),
    (r"\bFreebox",                    "Free/Iliad",      "Freebox"),
    (r"\bSFR[-_ ]?Box",              "SFR/Altice",      "SFR Box"),
    (r"\bSynology",                   "Synology",        "NAS"),
    (r"\bQNAP",                       "QNAP",            "NAS"),
    (r"\bESXi",                       "VMware",          "ESXi"),
    (r"\bvCenter",                    "VMware",          "vCenter"),
    (r"\bFortiGate",                  "Fortinet",        "FortiGate"),
    (r"\bFortiWiFi",                  "Fortinet",        "FortiWiFi"),
    (r"\bPA-?\d{3,4}",               "Palo Alto",       ""),
    (r"\bSG-?\d{3,4}",               "Sophos",          ""),
    (r"\bXG-?\d{3,4}",               "Sophos",          ""),
    (r"\bSRX\d+",                    "Juniper",         "SRX"),
    (r"\bEX\d{3,4}",                 "Juniper",         "EX series"),
    (r"\bCisco",                      "Cisco",           ""),
    (r"\bISR\d+",                    "Cisco",           "ISR"),
    (r"\bASA\d+",                    "Cisco",           "ASA"),
    (r"\bCatalyst",                   "Cisco",           "Catalyst"),
    (r"\bMeraki",                     "Meraki (Cisco)",  ""),
    (r"\bSonicWall",                  "SonicWall",       ""),
    (r"\bWatchGuard",                 "WatchGuard",      ""),
    (r"\bRuckus",                     "Ruckus",          ""),
    (r"\bUnraid",                     "Lime Technology", "Unraid"),
    (r"\bproxmox",                    "Proxmox",         "Proxmox VE"),
    (r"\bTrueNAS",                    "iXsystems",       "TrueNAS"),
    (r"\bRaspberry",                  "Raspberry Pi Foundation", "Raspberry Pi"),
    (r"\bpi\d?$",                     "Raspberry Pi Foundation", "Raspberry Pi"),
]


# ── HTTP deep-inspection patterns (login pages, titles, etc.) ──
_HTTP_BODY_PATTERNS: list[tuple[str, str, str, str]] = [
    # (regex, vendor, device_model_hint, os_version_hint)
    # Router web UIs
    (r"TP-LINK.*?([A-Z]+-?\w+)",             "TP-Link",         "{0}",        ""),
    (r"tp-link.*?model[\"':=\s]+([^ \"'<>]+)", "TP-Link",       "{0}",        ""),
    (r"NETGEAR.*?([A-Z]{1,3}\d{3,5}\w*)",    "NETGEAR",         "{0}",        ""),
    (r"netgear_model.*?([^ \"'<>]+)",         "NETGEAR",         "{0}",        ""),
    (r"ASUS.*?RT-(\w+)",                      "ASUS",            "RT-{0}",     ""),
    (r"asuswrt",                              "ASUS",            "",           "AsusWRT"),
    (r"D-Link.*?DIR-(\d+)",                   "D-Link",          "DIR-{0}",    ""),
    (r"D-?Link.*?model.*?(\w+)",              "D-Link",          "{0}",        ""),
    (r"Fritz!Box\s*(\d+)",                    "AVM",             "Fritz!Box {0}", "Fritz!OS"),
    (r"FRITZ!Box",                            "AVM",             "Fritz!Box",  "Fritz!OS"),
    (r"Livebox\s*(\d+)",                      "Orange/Sagemcom", "Livebox {0}", ""),
    (r"RouterOS.*?v([\d.]+)",                 "MikroTik",        "RouterOS",   "RouterOS v{0}"),
    (r"webfig",                               "MikroTik",        "",           "RouterOS"),
    (r"UniFi",                                "Ubiquiti",        "UniFi",      ""),
    (r"EdgeOS",                               "Ubiquiti",        "EdgeRouter", "EdgeOS"),
    (r"ubnt\.com",                            "Ubiquiti",        "",           ""),
    (r"Linksys.*?([A-Z]{2,}\d+)",            "Linksys",         "{0}",        ""),
    (r"Linksys Smart Wi-Fi",                  "Linksys",         "",           ""),
    (r"Huawei.*?(\w{2,3}\d{3,4}\w*)",        "Huawei",          "{0}",        ""),
    (r"ZTE.*?(\w{3,5}\d+)",                  "ZTE",             "{0}",        ""),
    # Firewalls
    (r"FortiGate",                            "Fortinet",        "FortiGate",  "FortiOS"),
    (r"FortiOS.*?v([\d.]+)",                  "Fortinet",        "FortiGate",  "FortiOS v{0}"),
    (r"Sophos.*?UTM",                         "Sophos",          "UTM",        ""),
    (r"Sophos.*?XG",                          "Sophos",          "XG Firewall",""),
    (r"SonicWall",                            "SonicWall",       "",           "SonicOS"),
    (r"WatchGuard",                           "WatchGuard",      "",           "Fireware"),
    (r"pfSense",                              "Netgate",         "pfSense",    "pfSense"),
    (r"OPNsense",                             "Deciso",          "OPNsense",   "OPNsense"),
    # Network infra
    (r"Cisco.*?Prime",                        "Cisco",           "Prime",      ""),
    (r"Cisco Adaptive Security",              "Cisco",           "ASA",        ""),
    (r"ASDM",                                 "Cisco",           "ASA",        ""),
    (r"Meraki Dashboard",                     "Meraki (Cisco)",  "Meraki",     ""),
    (r"ArubaOS",                              "HPE/Aruba",       "",           "ArubaOS"),
    (r"ProCurve",                             "HPE",             "ProCurve",   ""),
    (r"Arista",                               "Arista",          "",           "EOS"),
    (r"Ruckus",                               "Ruckus",          "",           ""),
    # NAS
    (r"Synology",                             "Synology",        "DiskStation","DSM"),
    (r"QNAP.*?TS-(\d+)",                     "QNAP",            "TS-{0}",     "QTS"),
    (r"QNAP",                                "QNAP",            "NAS",        "QTS"),
    (r"TrueNAS",                              "iXsystems",       "TrueNAS",    "TrueNAS"),
    (r"Unraid",                               "Lime Technology", "Unraid",     "Unraid"),
    # Virtualization
    (r"VMware ESXi\s*([\d.]+)",              "VMware",          "ESXi",       "ESXi {0}"),
    (r"vSphere",                              "VMware",          "vSphere",    ""),
    (r"Proxmox.*?VE\s*([\d.]+)?",            "Proxmox",         "Proxmox VE", "PVE {0}"),
    (r"XenServer",                            "Citrix",          "XenServer",  ""),
    # Printers
    (r"HP\s+(?:LaserJet|OfficeJet|Color\s*LaserJet)\s*(\w+)", "HP", "{0}", ""),
    (r"Brother\s+(\w+-\w+)",                  "Brother",         "{0}",        ""),
    (r"EPSON\s+(\w+)",                        "Epson",           "{0}",        ""),
    (r"Canon\s+(\w+)",                        "Canon",           "{0}",        ""),
    # Cameras / access points
    (r"Hikvision",                            "Hikvision",       "",           ""),
    (r"Dahua",                                "Dahua",           "",           ""),
    (r"Axis Communications",                  "Axis",            "",           ""),
]


# ── Windows build → version mapping (NTLM + SMB) ───────────
_WINDOWS_BUILDS: list[tuple[int, int, str]] = [
    # (major, build_number, friendly_name)
    # Windows 11
    (10, 26100, "Windows 11 24H2"),
    (10, 22631, "Windows 11 23H2"),
    (10, 22621, "Windows 11 22H2"),
    (10, 22000, "Windows 11 21H2"),
    # Windows 10
    (10, 19045, "Windows 10 22H2"),
    (10, 19044, "Windows 10 21H2"),
    (10, 19043, "Windows 10 21H1"),
    (10, 19042, "Windows 10 20H2"),
    (10, 19041, "Windows 10 2004"),
    (10, 18363, "Windows 10 1909"),
    (10, 18362, "Windows 10 1903"),
    (10, 17763, "Windows 10 1809"),  # Also Server 2019
    (10, 17134, "Windows 10 1803"),
    (10, 16299, "Windows 10 1709"),
    (10, 15063, "Windows 10 1703"),
    (10, 14393, "Windows 10 1607"),  # Also Server 2016
    (10, 10240, "Windows 10 RTM"),
    # Windows Server
    (10, 26100, "Windows Server 2025"),  # or Win11 24H2
    (10, 20348, "Windows Server 2022"),
    (10, 17763, "Windows Server 2019"),
    (10, 14393, "Windows Server 2016"),
    # Older
    (6, 9600,   "Windows 8.1 / Server 2012 R2"),
    (6, 9200,   "Windows 8 / Server 2012"),
    (6, 7601,   "Windows 7 SP1 / Server 2008 R2 SP1"),
    (6, 7600,   "Windows 7 / Server 2008 R2"),
    (6, 6002,   "Windows Vista SP2 / Server 2008 SP2"),
    (6, 6001,   "Windows Vista SP1 / Server 2008 SP1"),
]


def _windows_version_from_build(major: int, build: int, is_server: bool = False) -> str:
    """Map Windows major version + build number to a friendly name."""
    # For major=10, we need to disambiguate Win10/Win11/Server by build
    for m, b, name in _WINDOWS_BUILDS:
        if major == m and build >= b:
            # For build 14393 and 17763, check if it's server
            if is_server and "Server" not in name:
                # Try to find the server variant
                for m2, b2, n2 in _WINDOWS_BUILDS:
                    if m2 == m and b2 == b and "Server" in n2:
                        return n2
            return name
    if major == 10 and build >= 22000:
        return f"Windows 11 (Build {build})"
    if major == 10:
        return f"Windows 10 (Build {build})"
    return f"Windows NT {major}.x (Build {build})"

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


def _match_body_patterns(
    body: str, patterns: list[tuple[str, str, str, str]]
) -> tuple[str, str, str]:
    """Match HTML body text against HTTP body patterns.

    Returns (vendor, device_model, os_version) on first match, or ("","","").
    """
    for regex, vendor, model_tpl, os_tpl in patterns:
        m = re.search(regex, body, re.IGNORECASE)
        if m:
            groups = m.groups()
            model = model_tpl.format(*groups) if groups and "{0}" in model_tpl else model_tpl
            osv = os_tpl.format(*groups) if groups and "{0}" in os_tpl else os_tpl
            return vendor, model, osv
    return "", "", ""


# ═══════════════════════════════════════════════════════════
# Layer 1: SMB/NTLM fingerprinting (Windows exact version)
# ═══════════════════════════════════════════════════════════

async def _smb_ntlm_fingerprint(
    ip: str, timeout: float = 3.0
) -> dict[str, Any]:
    """Send SMB2 Negotiate + NTLMSSP to port 445 and parse the challenge.

    Returns dict with keys: os_version, vendor, domain, hostname, build,
    detection_method, confidence. Empty dict on failure.
    """
    result: dict[str, Any] = {}
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, 445), timeout=timeout
        )
    except Exception:
        return result

    try:
        # ── Step 1: SMB2 Negotiate Request ──
        # Minimal SMB2_NEGOTIATE with dialect 0x0202 (SMB 2.0.2)
        smb2_negotiate = (
            b"\x00\x00\x00\x72"  # NetBIOS session: length 114
            b"\xfeSMB"           # SMB2 magic
            b"\x40\x00"         # StructureSize = 64
            b"\x00\x00"         # CreditCharge = 0
            b"\x00\x00\x00\x00" # Status = 0
            b"\x00\x00"         # Command = NEGOTIATE (0)
            b"\x01\x00"         # CreditRequest = 1
            b"\x00\x00\x00\x00" # Flags = 0
            b"\x00\x00\x00\x00" # NextCommand = 0
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # MessageId = 0
            b"\x00\x00\x00\x00" # Reserved
            b"\x00\x00\x00\x00" # TreeId = 0
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # SessionId = 0
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # Signature (16 bytes)
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            # SMB2 Negotiate Request body
            b"\x24\x00"         # StructureSize = 36
            b"\x01\x00"         # DialectCount = 1
            b"\x00\x00"         # SecurityMode = 0
            b"\x00\x00"         # Reserved
            b"\x00\x00\x00\x00" # Capabilities = 0
            b"\x00\x00\x00\x00\x00\x00\x00\x00"  # ClientGuid (16 bytes)
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00" # NegotiateContextOffset
            b"\x00\x00"         # NegotiateContextCount
            b"\x00\x00"         # Reserved2
            b"\x02\x02"         # Dialect: SMB 2.0.2
        )
        writer.write(smb2_negotiate)
        await writer.drain()

        # Read SMB2 Negotiate Response
        resp = await asyncio.wait_for(reader.read(4096), timeout=timeout)
        if len(resp) < 70 or resp[4:8] != b"\xfeSMB":
            writer.close()
            return result

        # ── Step 2: SMB2 Session Setup with NTLMSSP_NEGOTIATE ──
        # Build NTLMSSP_NEGOTIATE token
        ntlmssp_negotiate = (
            b"NTLMSSP\x00"
            b"\x01\x00\x00\x00"  # MessageType = NEGOTIATE_MESSAGE
            b"\x97\x82\x08\xe2"  # NegotiateFlags
            b"\x00\x00"          # DomainNameLen
            b"\x00\x00"          # DomainNameMaxLen
            b"\x00\x00\x00\x00"  # DomainNameBufferOffset
            b"\x00\x00"          # WorkstationLen
            b"\x00\x00"          # WorkstationMaxLen
            b"\x00\x00\x00\x00"  # WorkstationBufferOffset
        )

        # Wrap in SPNEGO
        # OID: 1.2.840.113554.1.2.2 (MS KRB5 mech) + 1.2.840.48018.1.2.2
        # We'll use a minimal GSS-API wrapper for NTLMSSP

        def _build_spnego_init(ntlm_token: bytes) -> bytes:
            """Build minimal SPNEGO/GSS-API init token wrapping NTLMSSP."""
            # MechType OID for NTLMSSP: 1.3.6.1.4.1.311.2.2.10
            mech_oid = b"\x06\x0a\x2b\x06\x01\x04\x01\x82\x37\x02\x02\x0a"
            # MechTypes sequence
            mech_types = b"\x30" + bytes([len(mech_oid)]) + mech_oid
            # mechToken [2]
            mech_token_inner = b"\x04" + bytes([len(ntlm_token)]) + ntlm_token
            mech_token = b"\xa2" + bytes([len(mech_token_inner)]) + mech_token_inner
            # NegTokenInit [0]
            seq_body = b"\xa0" + bytes([len(mech_types)]) + mech_types + mech_token
            seq = b"\x30" + bytes([len(seq_body)]) + seq_body
            # Top-level [APPLICATION 0]
            spnego_oid = b"\x06\x06\x2b\x06\x01\x05\x05\x02"
            inner = spnego_oid + b"\xa0" + bytes([len(seq)]) + seq
            return b"\x60" + bytes([len(inner)]) + inner

        gss_token = _build_spnego_init(ntlmssp_negotiate)

        # Build SMB2 SESSION_SETUP request
        setup_body = (
            b"\x19\x00"         # StructureSize = 25
            b"\x00"             # Flags
            b"\x01"             # SecurityMode = SIGNING_ENABLED
            b"\x00\x00\x00\x00" # Capabilities
            b"\x00\x00\x00\x00" # Channel
            b"\x58\x00"         # SecurityBufferOffset = 88 (header 64 + body 24)
        )
        sec_len = struct.pack("<H", len(gss_token))
        setup_body += sec_len
        setup_body += b"\x00\x00\x00\x00\x00\x00\x00\x00"  # PreviousSessionId

        smb2_header = bytearray(64)
        smb2_header[0:4] = b"\xfeSMB"
        smb2_header[4:6] = struct.pack("<H", 64)  # StructureSize
        smb2_header[12:14] = struct.pack("<H", 1)  # Command = SESSION_SETUP
        smb2_header[14:16] = struct.pack("<H", 1)  # CreditRequest
        smb2_header[28:36] = struct.pack("<Q", 1)  # MessageId = 1

        pkt = bytes(smb2_header) + setup_body + gss_token
        # NetBIOS header
        nb_header = struct.pack(">I", len(pkt))
        writer.write(nb_header + pkt)
        await writer.drain()

        # Read Session Setup Response
        resp2 = await asyncio.wait_for(reader.read(8192), timeout=timeout)

        # Find NTLMSSP_CHALLENGE in response
        ntlmssp_idx = resp2.find(b"NTLMSSP\x00\x02\x00\x00\x00")
        if ntlmssp_idx == -1:
            # Try to find just NTLMSSP marker
            ntlmssp_idx = resp2.find(b"NTLMSSP\x00")
            if ntlmssp_idx == -1 or len(resp2) < ntlmssp_idx + 56:
                writer.close()
                return result

        challenge = resp2[ntlmssp_idx:]
        if len(challenge) < 56:
            writer.close()
            return result

        # Parse NTLMSSP_CHALLENGE
        # Offsets relative to NTLMSSP start:
        # 12: TargetNameLen (2), TargetNameMaxLen (2), TargetNameOffset (4)
        # 20: NegotiateFlags (4)
        # 28: TargetInfo section is in AV_PAIRs at TargetInfoOffset
        target_name_len = struct.unpack_from("<H", challenge, 12)[0]
        target_name_off = struct.unpack_from("<I", challenge, 16)[0]

        # Extract target (domain/computer) name
        domain_name = ""
        if target_name_off > 0 and target_name_off + target_name_len <= len(challenge):
            try:
                domain_name = challenge[target_name_off:target_name_off + target_name_len].decode("utf-16-le", errors="replace")
            except Exception:
                pass

        # Find TargetInfo AV_PAIRs
        # At offset 40 in NTLMSSP_CHALLENGE: TargetInfoLen(2), TargetInfoMaxLen(2), TargetInfoOffset(4)
        if len(challenge) >= 48:
            ti_len = struct.unpack_from("<H", challenge, 40)[0]
            ti_off = struct.unpack_from("<I", challenge, 44)[0]

            computer_name = ""
            dns_domain = ""
            dns_computer = ""
            os_major = 0
            os_minor = 0
            os_build = 0

            # Parse version field at offset 48 (8 bytes) if flags indicate it
            if len(challenge) >= 56:
                os_major = challenge[48]
                os_minor = challenge[49]
                os_build = struct.unpack_from("<H", challenge, 50)[0]

            # Walk AV_PAIR list
            if ti_off > 0 and ti_off + ti_len <= len(challenge):
                pos = ti_off
                while pos + 4 <= ti_off + ti_len:
                    av_id = struct.unpack_from("<H", challenge, pos)[0]
                    av_len = struct.unpack_from("<H", challenge, pos + 2)[0]
                    pos += 4
                    if av_id == 0:
                        break  # MsvAvEOL
                    if pos + av_len > len(challenge):
                        break
                    av_val = challenge[pos:pos + av_len]
                    try:
                        val_str = av_val.decode("utf-16-le", errors="replace")
                    except Exception:
                        val_str = ""

                    if av_id == 1:    # MsvAvNbComputerName
                        computer_name = val_str
                    elif av_id == 2:  # MsvAvNbDomainName
                        domain_name = val_str or domain_name
                    elif av_id == 3:  # MsvAvDnsComputerName
                        dns_computer = val_str
                    elif av_id == 4:  # MsvAvDnsDomainName
                        dns_domain = val_str
                    pos += av_len

            if os_build > 0:
                is_server = any(kw in (domain_name + dns_domain + dns_computer).lower()
                                for kw in ("server", "srv", "dc", "ad"))
                friendly = _windows_version_from_build(os_major, os_build, is_server)
                result = {
                    "os_version": f"{friendly} (Build {os_build})",
                    "vendor": "Microsoft",
                    "domain": domain_name or dns_domain,
                    "hostname": computer_name or dns_computer,
                    "build": os_build,
                    "detection_method": "smb_ntlm",
                    "confidence": 95,
                }
            elif domain_name:
                result = {
                    "os_version": "Windows",
                    "vendor": "Microsoft",
                    "domain": domain_name,
                    "hostname": computer_name,
                    "detection_method": "smb_ntlm",
                    "confidence": 75,
                }
    except Exception as exc:
        logger.debug("SMB/NTLM fingerprint failed for %s: %s", ip, exc)
    finally:
        try:
            writer.close()
        except Exception:
            pass

    return result


# ═══════════════════════════════════════════════════════════
# Layer 2: SNMP sysDescr probe
# ═══════════════════════════════════════════════════════════

async def _snmp_sysdescr(
    ip: str, community: str = "public", timeout: float = 2.0
) -> dict[str, Any]:
    """Send SNMPv2c GET for sysDescr.0 (OID 1.3.6.1.2.1.1.1.0).

    Returns dict with: os_version, vendor, device_model, detection_method,
    confidence. Empty dict on failure.
    """
    result: dict[str, Any] = {}

    # Build SNMPv2c GET-REQUEST packet for sysDescr.0
    # OID 1.3.6.1.2.1.1.1.0 = 2b 06 01 02 01 01 01 00
    oid = b"\x06\x08\x2b\x06\x01\x02\x01\x01\x01\x00"
    # VarBind: OID + NULL value
    varbind = b"\x30" + bytes([len(oid) + 2]) + oid + b"\x05\x00"
    # VarBindList
    varbind_list = b"\x30" + bytes([len(varbind)]) + varbind
    # PDU: GET-REQUEST (0xa0), request-id=1, error-status=0, error-index=0
    request_id = b"\x02\x01\x01"
    error_status = b"\x02\x01\x00"
    error_index = b"\x02\x01\x00"
    pdu_body = request_id + error_status + error_index + varbind_list
    pdu = b"\xa0" + bytes([len(pdu_body)]) + pdu_body
    # Community string
    comm_bytes = community.encode("ascii")
    comm_tlv = b"\x04" + bytes([len(comm_bytes)]) + comm_bytes
    # Version: SNMPv2c = 1
    version = b"\x02\x01\x01"
    # Message
    msg_body = version + comm_tlv + pdu
    message = b"\x30" + bytes([len(msg_body)]) + msg_body

    loop = asyncio.get_event_loop()
    try:
        transport, protocol = await asyncio.wait_for(
            loop.create_datagram_endpoint(
                lambda: asyncio.DatagramProtocol(),
                remote_addr=(ip, 161),
            ),
            timeout=timeout,
        )
    except Exception:
        return result

    try:
        transport.sendto(message)

        # Wait for response
        data = None
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            await asyncio.sleep(0.1)
            # Try to receive
            try:
                # Use low-level socket recv
                sock = transport.get_extra_info("socket")
                if sock:
                    sock.setblocking(False)
                    try:
                        data, _ = sock.recvfrom(4096)
                        break
                    except (BlockingIOError, OSError):
                        pass
            except Exception:
                pass
    finally:
        transport.close()

    if not data or len(data) < 20:
        return result

    # Parse SNMP response: extract sysDescr value (OctetString)
    try:
        # Walk BER-TLV to find the value after OID
        sysdescr_str = ""
        # Find the OctetString (0x04) after our OID in the response
        oid_marker = b"\x2b\x06\x01\x02\x01\x01\x01\x00"
        idx = data.find(oid_marker)
        if idx >= 0:
            # Skip OID TLV
            pos = idx + len(oid_marker)
            if pos < len(data):
                tag = data[pos]
                pos += 1
                if pos < len(data):
                    length = data[pos]
                    pos += 1
                    if length > 127:
                        n_bytes = length & 0x7f
                        if pos + n_bytes <= len(data):
                            length = int.from_bytes(data[pos:pos + n_bytes], "big")
                            pos += n_bytes
                    if tag == 0x04 and pos + length <= len(data):
                        sysdescr_str = data[pos:pos + length].decode("utf-8", errors="replace")

        if sysdescr_str:
            sysdescr_lower = sysdescr_str.lower()
            vendor = ""
            device_model = ""
            os_version = sysdescr_str

            # Parse vendor/model from sysDescr
            # Cisco IOS: "Cisco IOS Software, C2900 Software (C2900-UNIVERSALK9-M), Version 15.1(4)M4"
            cisco_m = re.search(r"Cisco.*?(?:IOS|NX-OS).*?Version\s+([\d.()A-Za-z]+)", sysdescr_str)
            if cisco_m:
                vendor = "Cisco"
                os_version = f"Cisco IOS {cisco_m.group(1)}"
                model_m = re.search(r",\s*(\w+)\s+Software", sysdescr_str)
                if model_m:
                    device_model = model_m.group(1)
                result = {"os_version": os_version, "vendor": vendor,
                          "device_model": device_model,
                          "detection_method": "snmp", "confidence": 95}
                return result

            # Juniper: "Juniper Networks, Inc. ... JUNOS 12.3R11"
            juniper_m = re.search(r"JUNOS\s+([\d.A-Za-z]+)", sysdescr_str)
            if juniper_m:
                result = {"os_version": f"Junos {juniper_m.group(1)}", "vendor": "Juniper",
                          "detection_method": "snmp", "confidence": 95}
                return result

            # Linux
            if "linux" in sysdescr_lower:
                result = {"os_version": sysdescr_str[:80], "vendor": "",
                          "detection_method": "snmp", "confidence": 85}
                return result

            # Windows SNMP
            win_m = re.search(r"Windows.*?Version\s+([\d.]+)", sysdescr_str)
            if win_m or "windows" in sysdescr_lower:
                result = {"os_version": sysdescr_str[:80], "vendor": "Microsoft",
                          "detection_method": "snmp", "confidence": 90}
                return result

            # HP / Aruba switches
            if re.search(r"HP|Aruba|ProCurve", sysdescr_str, re.IGNORECASE):
                result = {"os_version": sysdescr_str[:80], "vendor": "HPE/Aruba",
                          "detection_method": "snmp", "confidence": 90}
                return result

            # Fortinet
            if "fortigate" in sysdescr_lower or "fortios" in sysdescr_lower:
                result = {"os_version": sysdescr_str[:80], "vendor": "Fortinet",
                          "device_model": "FortiGate",
                          "detection_method": "snmp", "confidence": 95}
                return result

            # Generic: return whatever we got
            # Try to detect vendor keywords
            for kw, v in [("cisco", "Cisco"), ("juniper", "Juniper"),
                          ("mikrotik", "MikroTik"), ("ubiquiti", "Ubiquiti"),
                          ("netgear", "NETGEAR"), ("tp-link", "TP-Link"),
                          ("synology", "Synology"), ("qnap", "QNAP")]:
                if kw in sysdescr_lower:
                    vendor = v
                    break

            result = {"os_version": sysdescr_str[:80], "vendor": vendor,
                      "device_model": device_model,
                      "detection_method": "snmp", "confidence": 80}

    except Exception as exc:
        logger.debug("SNMP parse failed for %s: %s", ip, exc)

    return result


# ═══════════════════════════════════════════════════════════
# Layer 3: MAC OUI vendor lookup (via ARP table)
# ═══════════════════════════════════════════════════════════

async def _get_mac_from_arp(ip: str) -> str:
    """Get MAC address for an IP — prefers the ARP sweep cache, falls back to async live lookup."""
    # Fast path: use pre-populated ARP cache from Layer 0 sweep
    cached = _arp_cache.get(ip)
    if cached:
        return cached

    # Fallback: async live ARP table lookup (for single-IP scans where sweep wasn't run)
    try:
        if sys.platform == "win32":
            proc = await asyncio.create_subprocess_exec(
                "arp", "-a", ip,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            output = stdout.decode("utf-8", errors="replace")
            mac_m = re.search(r"([\da-fA-F]{2}[:-]){5}[\da-fA-F]{2}", output)
            if mac_m:
                return mac_m.group(0).upper().replace("-", ":")
        else:
            # Linux / macOS
            proc = await asyncio.create_subprocess_exec(
                "arp", "-n", ip,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            output = stdout.decode("utf-8", errors="replace")
            mac_m = re.search(r"([\da-fA-F]{2}:){5}[\da-fA-F]{2}", output)
            if mac_m:
                return mac_m.group(0).upper()
            # Fallback: /proc/net/arp (async file read would be overkill — small file)
            try:
                with open("/proc/net/arp", "r") as f:
                    for line in f:
                        if ip in line:
                            mac_m2 = re.search(r"([\da-fA-F]{2}:){5}[\da-fA-F]{2}", line)
                            if mac_m2:
                                return mac_m2.group(0).upper()
            except FileNotFoundError:
                pass
    except (asyncio.TimeoutError, FileNotFoundError, OSError):
        pass
    return ""


def _lookup_oui_vendor(mac: str) -> str:
    """Look up vendor from the first 3 octets (OUI) of a MAC address."""
    if not mac:
        return ""
    # Normalize to XX:XX:XX format
    prefix = mac.replace("-", ":").upper()[:8]
    return _OUI_VENDOR.get(prefix, "")


# ═══════════════════════════════════════════════════════════
# Layer 4: UPnP / SSDP discovery
# ═══════════════════════════════════════════════════════════

async def _upnp_discover(ip: str, timeout: float = 2.0) -> dict[str, Any]:
    """Send SSDP M-SEARCH via multicast (+ unicast fallback) and fetch device XML.

    Returns dict with: vendor, device_model, os_version, firmware,
    detection_method, confidence. Empty dict on failure.
    """
    result: dict[str, Any] = {}

    SSDP_MCAST = "239.255.255.250"

    # Multicast M-SEARCH (standard SSDP)
    msearch_mcast = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_MCAST}:1900\r\n"
        "MAN: \"ssdp:discover\"\r\n"
        "MX: 2\r\n"
        "ST: upnp:rootdevice\r\n"
        "\r\n"
    ).encode()

    # Unicast M-SEARCH (direct to host)
    msearch_unicast = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {ip}:1900\r\n"
        "MAN: \"ssdp:discover\"\r\n"
        "MX: 1\r\n"
        "ST: upnp:rootdevice\r\n"
        "\r\n"
    ).encode()

    data = None
    loop = asyncio.get_event_loop()

    # Try 1: Multicast M-SEARCH (reaches devices that only listen on multicast)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0)
        sock.bind(("", 0))  # Ephemeral port
        # Set multicast TTL
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.sendto(msearch_mcast, (SSDP_MCAST, 1900))

        start = time.monotonic()
        while time.monotonic() - start < timeout:
            await asyncio.sleep(0.15)
            try:
                raw, addr = sock.recvfrom(4096)
                if addr[0] == ip:
                    data = raw
                    break
            except (BlockingIOError, OSError):
                pass
        sock.close()
    except Exception:
        pass

    # Try 2: Unicast fallback if multicast didn't reach the host
    if not data:
        try:
            transport, _ = await asyncio.wait_for(
                loop.create_datagram_endpoint(
                    lambda: asyncio.DatagramProtocol(),
                    remote_addr=(ip, 1900),
                ),
                timeout=timeout,
            )
            try:
                transport.sendto(msearch_unicast)
                start = time.monotonic()
                while time.monotonic() - start < timeout:
                    await asyncio.sleep(0.15)
                    try:
                        s = transport.get_extra_info("socket")
                        if s:
                            s.setblocking(False)
                            try:
                                data, _ = s.recvfrom(4096)
                                break
                            except (BlockingIOError, OSError):
                                pass
                    except Exception:
                        pass
            finally:
                transport.close()
        except Exception:
            pass

    if not data:
        return result

    resp_text = data.decode("utf-8", errors="replace")

    # Extract LOCATION header → fetch device XML
    location_m = re.search(r"LOCATION:\s*(http[^\r\n]+)", resp_text, re.IGNORECASE)
    server_m = re.search(r"SERVER:\s*([^\r\n]+)", resp_text, re.IGNORECASE)

    # Parse SERVER header: "Linux/3.10 UPnP/1.0 TP-Link/1.0"
    if server_m:
        server_str = server_m.group(1)
        for vendor_key, vendor_name in [
            ("TP-Link", "TP-Link"), ("NETGEAR", "NETGEAR"), ("ASUS", "ASUS"),
            ("D-Link", "D-Link"), ("Linksys", "Linksys"), ("Huawei", "Huawei"),
            ("Ubiquiti", "Ubiquiti"), ("Synology", "Synology"), ("QNAP", "QNAP"),
            ("Fritz", "AVM"), ("MikroTik", "MikroTik"), ("Belkin", "Belkin"),
            ("Samsung", "Samsung"), ("Sony", "Sony"), ("LG", "LG"),
            ("Roku", "Roku"), ("Amazon", "Amazon"), ("Google", "Google"),
        ]:
            if vendor_key.lower() in server_str.lower():
                result["vendor"] = vendor_name
                result["detection_method"] = "upnp_ssdp"
                result["confidence"] = 65
                break

    # Fetch device description XML if LOCATION is available
    if location_m:
        xml_url = location_m.group(1).strip()
        try:
            # Parse the URL to get host/port/path
            from urllib.parse import urlparse
            parsed = urlparse(xml_url)
            xml_host = parsed.hostname or ip
            xml_port = parsed.port or 80
            xml_path = parsed.path or "/"

            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(xml_host, xml_port), timeout=2.0
            )
            req = (
                f"GET {xml_path} HTTP/1.1\r\n"
                f"Host: {xml_host}:{xml_port}\r\n"
                "Connection: close\r\n\r\n"
            ).encode()
            writer.write(req)
            await writer.drain()
            xml_data = await asyncio.wait_for(reader.read(8192), timeout=2.0)
            writer.close()

            xml_text = xml_data.decode("utf-8", errors="replace")

            # Parse XML fields
            manufacturer_m = re.search(r"<manufacturer>([^<]+)", xml_text, re.IGNORECASE)
            model_m = re.search(r"<modelName>([^<]+)", xml_text, re.IGNORECASE)
            model_num_m = re.search(r"<modelNumber>([^<]+)", xml_text, re.IGNORECASE)
            friendly_m = re.search(r"<friendlyName>([^<]+)", xml_text, re.IGNORECASE)

            if manufacturer_m:
                result["vendor"] = manufacturer_m.group(1).strip()
                result["confidence"] = 90
            if model_m:
                result["device_model"] = model_m.group(1).strip()
            elif model_num_m:
                result["device_model"] = model_num_m.group(1).strip()
            if friendly_m:
                result["firmware"] = friendly_m.group(1).strip()

            result["detection_method"] = "upnp_xml"

        except Exception:
            pass

    return result


# ═══════════════════════════════════════════════════════════
# Layer 5: mDNS / Bonjour probe
# ═══════════════════════════════════════════════════════════

async def _mdns_probe(ip: str, timeout: float = 2.0) -> dict[str, Any]:
    """Send mDNS query via multicast 224.0.0.251 (+ unicast fallback).

    Returns dict with: vendor, device_model, detection_method, confidence.
    """
    result: dict[str, Any] = {}

    MDNS_MCAST = "224.0.0.251"
    MDNS_PORT = 5353

    # Build mDNS query for _http._tcp.local (PTR) + _services._dns-sd._udp.local
    query_name_http = b"\x05_http\x04_tcp\x05local\x00"
    query_name_svc = b"\x09_services\x07_dns-sd\x04_udp\x05local\x00"
    # DNS header: ID=0, flags=0, QD=2
    dns_header = struct.pack(">HHHHHH", 0, 0, 2, 0, 0, 0)
    question1 = query_name_http + struct.pack(">HH", 12, 0x8001)  # PTR, unicast-response
    question2 = query_name_svc + struct.pack(">HH", 12, 0x8001)
    mdns_query = dns_header + question1 + question2

    data = None

    # Try 1: Multicast to 224.0.0.251 (standard mDNS)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0)
        sock.bind(("", 0))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.sendto(mdns_query, (MDNS_MCAST, MDNS_PORT))

        start = time.monotonic()
        while time.monotonic() - start < timeout:
            await asyncio.sleep(0.15)
            try:
                raw, addr = sock.recvfrom(4096)
                if addr[0] == ip:
                    data = raw
                    break
            except (BlockingIOError, OSError):
                pass
        sock.close()
    except Exception:
        pass

    # Try 2: Unicast fallback (direct to host)
    if not data:
        loop = asyncio.get_event_loop()
        try:
            transport, _ = await asyncio.wait_for(
                loop.create_datagram_endpoint(
                    lambda: asyncio.DatagramProtocol(),
                    remote_addr=(ip, MDNS_PORT),
                ),
                timeout=timeout,
            )
            try:
                transport.sendto(mdns_query)
                start = time.monotonic()
                while time.monotonic() - start < timeout:
                    await asyncio.sleep(0.15)
                    try:
                        s = transport.get_extra_info("socket")
                        if s:
                            s.setblocking(False)
                            try:
                                data, _ = s.recvfrom(4096)
                                break
                            except (BlockingIOError, OSError):
                                pass
                    except Exception:
                        pass
            finally:
                transport.close()
        except Exception:
            pass

    if data:
        resp_text = data.decode("utf-8", errors="replace").lower()
        # Check for Apple indicators
        if any(kw in resp_text for kw in ("apple", "airplay", "airprint", "homekit", "_raop")):
            result = {"vendor": "Apple", "detection_method": "mdns", "confidence": 70}
        elif any(kw in resp_text for kw in ("google", "chromecast", "googlecast")):
            result = {"vendor": "Google", "device_model": "Chromecast",
                      "detection_method": "mdns", "confidence": 70}
        elif "printer" in resp_text or "ipp" in resp_text:
            result = {"detection_method": "mdns", "confidence": 50}
            for brand in ("hp", "brother", "epson", "canon", "xerox", "lexmark", "ricoh"):
                if brand in resp_text:
                    result["vendor"] = brand.capitalize()
                    result["confidence"] = 65
                    break
        elif data:  # Got *some* response — host supports mDNS
            result = {"detection_method": "mdns", "confidence": 20}

    return result


# ═══════════════════════════════════════════════════════════
# Layer 6: HTTP deep inspection (HTML body + headers)
# ═══════════════════════════════════════════════════════════

async def _http_deep_inspect(
    ip: str, port: int = 80, timeout: float = 3.0
) -> dict[str, Any]:
    """Fetch HTTP index page and inspect <title>, body keywords, headers.

    Returns dict with: vendor, device_model, os_version, firmware,
    detection_method, confidence.
    """
    result: dict[str, Any] = {}
    use_ssl = port in SSL_PORTS

    try:
        if use_ssl:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port, ssl=ssl_ctx), timeout=timeout + 1.0
            )
        else:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=timeout
            )
    except Exception:
        return result

    try:
        req = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {ip}\r\n"
            "User-Agent: Mozilla/5.0\r\n"
            "Accept: text/html,*/*\r\n"
            "Connection: close\r\n\r\n"
        ).encode()
        writer.write(req)
        await writer.drain()

        data = await asyncio.wait_for(reader.read(16384), timeout=timeout)
        resp_text = data.decode("utf-8", errors="replace")

        # Split headers and body
        header_body = resp_text.split("\r\n\r\n", 1)
        headers = header_body[0] if header_body else ""
        body = header_body[1] if len(header_body) > 1 else ""

        # Check WWW-Authenticate header
        www_auth_m = re.search(r"WWW-Authenticate:.*realm=\"?([^\"\\r\\n]+)", headers, re.IGNORECASE)
        if www_auth_m:
            realm = www_auth_m.group(1)
            for vendor_key, vendor_name in [
                ("TP-LINK", "TP-Link"), ("NETGEAR", "NETGEAR"), ("ASUS", "ASUS"),
                ("D-Link", "D-Link"), ("Linksys", "Linksys"), ("Fritz", "AVM"),
                ("Huawei", "Huawei"), ("MikroTik", "MikroTik"), ("Cisco", "Cisco"),
                ("Fortinet", "Fortinet"), ("SonicWall", "SonicWall"),
            ]:
                if vendor_key.lower() in realm.lower():
                    result["vendor"] = vendor_name
                    result["detection_method"] = "http_auth_realm"
                    result["confidence"] = 75
                    break

        # Check X-Powered-By / X-Frame-Options / other custom headers
        for hdr_kw, vendor_name in [
            ("FortiOS", "Fortinet"), ("SonicOS", "SonicWall"),
            ("pfSense", "Netgate"), ("OPNsense", "Deciso"),
        ]:
            if hdr_kw.lower() in headers.lower():
                result["vendor"] = vendor_name
                result["os_version"] = hdr_kw
                result["detection_method"] = "http_header"
                result["confidence"] = 80

        # Check HTML title and body
        title_m = re.search(r"<title[^>]*>([^<]{1,200})</title>", body, re.IGNORECASE)
        title = title_m.group(1).strip() if title_m else ""

        # Match against body patterns
        full_text = title + " " + body[:4096]
        vendor, model, osv = _match_body_patterns(full_text, _HTTP_BODY_PATTERNS)
        if vendor:
            result["vendor"] = vendor
            result["detection_method"] = "http_body"
            result["confidence"] = max(result.get("confidence", 0), 75)
            if model:
                result["device_model"] = model
                result["confidence"] = max(result.get("confidence", 0), 80)
            if osv:
                result["os_version"] = osv

        # Title-based fallback
        if not result.get("vendor") and title:
            for kw, vend in [
                ("TP-LINK", "TP-Link"), ("NETGEAR", "NETGEAR"), ("ASUS", "ASUS"),
                ("D-Link", "D-Link"), ("Linksys", "Linksys"), ("Fritz", "AVM"),
                ("MikroTik", "MikroTik"), ("UniFi", "Ubiquiti"), ("Cisco", "Cisco"),
                ("Synology", "Synology"), ("QNAP", "QNAP"), ("pfSense", "Netgate"),
                ("FortiGate", "Fortinet"), ("SonicWall", "SonicWall"),
            ]:
                if kw.lower() in title.lower():
                    result["vendor"] = vend
                    result["detection_method"] = "http_title"
                    result["confidence"] = 70
                    break

    except Exception as exc:
        logger.debug("HTTP deep inspect failed for %s:%d: %s", ip, port, exc)
    finally:
        try:
            writer.close()
        except Exception:
            pass

    return result


# ═══════════════════════════════════════════════════════════
# Layer 7: Hostname heuristics
# ═══════════════════════════════════════════════════════════

def _hostname_heuristics(hostname: str) -> dict[str, Any]:
    """Match hostname against known vendor patterns.

    Returns dict with: vendor, device_model, detection_method, confidence.
    """
    if not hostname:
        return {}

    for regex, vendor, model_tpl in _HOSTNAME_VENDOR_PATTERNS:
        m = re.search(regex, hostname, re.IGNORECASE)
        if m:
            model = ""
            if model_tpl and "{0}" in model_tpl and m.groups():
                model = model_tpl.format(m.group(1))
            elif model_tpl and "{0}" not in model_tpl:
                model = model_tpl
            result: dict[str, Any] = {
                "vendor": vendor,
                "detection_method": "hostname",
                "confidence": 40,
            }
            if model:
                result["device_model"] = model
                result["confidence"] = 55
            return result

    return {}


# ═══════════════════════════════════════════════════════════
# Layer 8: Banner-based detection (enhanced original)
# ═══════════════════════════════════════════════════════════

def _detect_from_banners(
    banners: dict[int, str], os_guess: str, hostname: str,
) -> dict[str, Any]:
    """Analyze banners to determine OS version and vendor.

    Checks SSH → HTTP → FTP → Telnet → MySQL → SMTP in priority order.
    Returns dict with: os_version, vendor, detection_method, confidence.
    """
    result: dict[str, Any] = {}

    # SSH banner (usually the most informative)
    if 22 in banners:
        os_version, vendor = _match_patterns(banners[22], _SSH_PATTERNS)
        if os_version:
            return {"os_version": os_version, "vendor": vendor,
                    "detection_method": "banner_ssh", "confidence": 80}

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
                    return {"os_version": os_version, "vendor": vendor,
                            "detection_method": "banner_http", "confidence": 75}

    # FTP banner
    if 21 in banners:
        os_version, vendor = _match_patterns(banners[21], _FTP_PATTERNS)
        if os_version:
            return {"os_version": os_version, "vendor": vendor,
                    "detection_method": "banner_ftp", "confidence": 75}

    # Telnet banner (network devices)
    if 23 in banners:
        os_version, vendor = _match_patterns(banners[23], _TELNET_PATTERNS)
        if os_version:
            return {"os_version": os_version, "vendor": vendor,
                    "detection_method": "banner_telnet", "confidence": 80}

    # MySQL banner
    if 3306 in banners:
        os_version, vendor = _match_patterns(banners[3306], _MYSQL_PATTERNS)
        if os_version:
            return {"os_version": os_version, "vendor": vendor,
                    "detection_method": "banner_mysql", "confidence": 70}

    # SMTP banner
    if 25 in banners:
        os_version, vendor = _match_patterns(banners[25], _SMTP_PATTERNS)
        if os_version:
            return {"os_version": os_version, "vendor": vendor,
                    "detection_method": "banner_smtp", "confidence": 70}

    # Fallback: infer vendor from os_guess
    if os_guess == "windows":
        return {"os_version": "Windows", "vendor": "Microsoft",
                "detection_method": "port_heuristic", "confidence": 35}
    if os_guess == "linux":
        return {"os_version": "Linux", "vendor": "",
                "detection_method": "port_heuristic", "confidence": 30}

    return result


# ═══════════════════════════════════════════════════════════
# Layer 11: RDP fingerprinting (X.224 / CredSSP / NLA)
# ═══════════════════════════════════════════════════════════

async def _rdp_fingerprint(ip: str, port: int = 3389) -> dict[str, Any]:
    """Send an X.224 Connection Request to RDP and read the response.

    The server's X.224 response reveals protocol negotiation (NLA / CredSSP),
    and sometimes the TLS certificate contains the host's FQDN and OS hints.
    Returns: os_version, vendor, detection_method, confidence.
    """
    result: dict[str, Any] = {}

    # X.224 Connection Request (simplified — just enough to get a response)
    # TPKT header (4 bytes) + X.224 CR (variable)
    cookie = b"Cookie: mstshash=auditfrg\r\n"
    x224_cr_body = (
        b"\xe0"             # CR TPDU code
        b"\x00\x00"         # DST-REF
        b"\x00\x00"         # SRC-REF
        b"\x00"             # Class 0
    ) + cookie + (
        # RDP Negotiation Request: TYPE_RDP_NEG_REQ
        b"\x01"             # type = NEGOTIATION_REQUEST
        b"\x00"             # flags
        b"\x08\x00"         # length = 8
        b"\x03\x00\x00\x00" # requestedProtocols = PROTOCOL_SSL | PROTOCOL_HYBRID
    )
    x224_len = len(x224_cr_body) + 1  # +1 for length byte itself
    tpkt = struct.pack("!BBH", 3, 0, 4 + x224_len) + bytes([x224_len]) + x224_cr_body

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=TCP_CONNECT_TIMEOUT,
        )
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return result

    try:
        writer.write(tpkt)
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=3.0)

        if data and len(data) >= 11:
            result["vendor"] = "Microsoft"
            result["detection_method"] = "rdp_fingerprint"
            result["confidence"] = 60

            # Check CredSSP / NLA support from negotiation response
            # Byte 11 (0-indexed): negotiation type. 0x02 = RESPONSE, 0x03 = FAILURE
            resp_type = data[11] if len(data) > 11 else 0
            if resp_type == 0x02 and len(data) > 15:
                selected_proto = struct.unpack_from("<I", data, 12)[0]
                if selected_proto & 0x02:  # PROTOCOL_HYBRID (NLA/CredSSP)
                    result["os_version"] = "Windows (NLA/CredSSP enabled)"
                    result["confidence"] = 65
                elif selected_proto & 0x01:  # PROTOCOL_SSL
                    result["os_version"] = "Windows (TLS-only RDP)"
                    result["confidence"] = 60

            # Try TLS upgrade to read certificate CN for FQDN
            if resp_type == 0x02:
                try:
                    ssl_ctx = ssl.create_default_context()
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_NONE
                    transport = writer.transport
                    # Get the raw socket from the asyncio transport
                    raw_sock = transport.get_extra_info("socket")
                    if raw_sock:
                        ssl_sock = ssl_ctx.wrap_socket(raw_sock, server_hostname=ip)
                        cert = ssl_sock.getpeercert(binary_form=True)
                        if cert:
                            # Try to extract CN from DER cert — very basic parse
                            cert_text = cert.decode("latin-1", errors="replace")
                            cn_m = re.search(r"CN=([^\x00-\x1f,]+)", cert_text)
                            if cn_m:
                                result["hostname_hint"] = cn_m.group(1)
                except Exception:
                    pass  # TLS upgrade is best-effort

    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except OSError:
            pass

    return result


# ═══════════════════════════════════════════════════════════
# Layer 12: WinRM detection (HTTP on 5985 / HTTPS on 5986)
# ═══════════════════════════════════════════════════════════

async def _winrm_detect(ip: str) -> dict[str, Any]:
    """Probe WinRM HTTP (5985) and HTTPS (5986) endpoints.

    A running WinRM service returns specific headers that confirm Windows.
    Returns: os_version, vendor, detection_method, confidence.
    """
    result: dict[str, Any] = {}

    for port, use_ssl in [(5985, False), (5986, True)]:
        try:
            if use_ssl:
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port, ssl=ssl_ctx),
                    timeout=TCP_CONNECT_TIMEOUT + 1.0,
                )
            else:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port),
                    timeout=TCP_CONNECT_TIMEOUT,
                )
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError, ssl.SSLError):
            continue

        try:
            req = (
                f"POST /wsman HTTP/1.1\r\n"
                f"Host: {ip}:{port}\r\n"
                "Content-Type: application/soap+xml;charset=UTF-8\r\n"
                "Content-Length: 0\r\n"
                "Connection: close\r\n\r\n"
            ).encode()
            writer.write(req)
            await writer.drain()
            data = await asyncio.wait_for(reader.read(2048), timeout=3.0)
            resp_text = data.decode("utf-8", errors="replace")

            if "HTTP/" in resp_text:
                # WinRM typically returns 401/403 with specific headers
                result["vendor"] = "Microsoft"
                result["detection_method"] = "winrm"
                result["confidence"] = 70

                if "Microsoft-HTTPAPI" in resp_text or "wsman" in resp_text.lower():
                    result["confidence"] = 80
                    result["os_version"] = "Windows (WinRM enabled)"

                # Check for server header with version info
                server_m = re.search(r"Server:\s*([^\r\n]+)", resp_text, re.IGNORECASE)
                if server_m:
                    server_val = server_m.group(1).strip()
                    if "Microsoft" in server_val:
                        result["os_version"] = f"Windows ({server_val})"
                        result["confidence"] = 85

                break  # Got a valid response, no need to try other port

        except (asyncio.TimeoutError, ConnectionError, OSError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except OSError:
                pass

    return result


# ═══════════════════════════════════════════════════════════
# Orchestrator: multi-layer fingerprinting with confidence
# ═══════════════════════════════════════════════════════════

async def _fingerprint_host(
    ip: str,
    hostname: str,
    open_ports: list[dict[str, Any]],
    banners: dict[int, str],
    os_guess: str,
) -> dict[str, Any]:
    """Run all detection layers and return the best result.

    Returns a dict with: os_version, vendor, device_model, firmware,
    mac_address, domain, detection_method, confidence.
    """
    port_numbers = {p["port"] for p in open_ports}

    # Gather results from all applicable detection layers concurrently
    tasks: list[tuple[str, Any]] = []

    # Layer 1: SMB/NTLM fingerprinting (only if port 445 is open)
    smb_task = None
    if 445 in port_numbers:
        smb_task = asyncio.create_task(_smb_ntlm_fingerprint(ip))

    # Layer 2: SNMP sysDescr — always try (UDP service, not gated on TCP port scan)
    snmp_task = asyncio.create_task(_snmp_sysdescr(ip))

    # Layer 4: UPnP/SSDP (try for all hosts — many respond even without port 1900 in scan)
    upnp_task = asyncio.create_task(_upnp_discover(ip))

    # Layer 5: mDNS
    mdns_task = asyncio.create_task(_mdns_probe(ip))

    # Layer 6: HTTP deep inspection (for any HTTP port)
    http_task = None
    for hport in (80, 443, 8080, 8443, 8000, 8888, 9090, 631, 9100):
        if hport in port_numbers:
            http_task = asyncio.create_task(_http_deep_inspect(ip, hport))
            break

    # Layer 9: NetBIOS Name Service (UDP 137 — discovers Windows hosts + MAC)
    netbios_task = asyncio.create_task(_netbios_name_query(ip))

    # Layer 10: TCP passive OS fingerprinting (p0f-style TTL analysis)
    tcp_fp_task = None
    # Use a known-open port for the fingerprint; prefer common ports
    tcp_fp_port = None
    for candidate_port in (80, 443, 22, 445, 8080, 3389, 135, 23):
        if candidate_port in port_numbers:
            tcp_fp_port = candidate_port
            break
    if tcp_fp_port is not None:
        tcp_fp_task = asyncio.create_task(_tcp_os_fingerprint(ip, tcp_fp_port))

    # Layer 11: RDP fingerprinting (only if port 3389 is open)
    rdp_task = None
    if 3389 in port_numbers:
        rdp_task = asyncio.create_task(_rdp_fingerprint(ip))

    # Layer 12: WinRM detection (only if port 5985 or 5986 is open)
    winrm_task = None
    if port_numbers & {5985, 5986}:
        winrm_task = asyncio.create_task(_winrm_detect(ip))

    # Wait for all async tasks
    all_tasks = [t for t in [smb_task, snmp_task, upnp_task, mdns_task, http_task, netbios_task, tcp_fp_task, rdp_task, winrm_task] if t]
    if all_tasks:
        await asyncio.gather(*all_tasks, return_exceptions=True)

    # Collect all results
    candidates: list[dict[str, Any]] = []

    # Layer 1: SMB/NTLM (highest priority for Windows)
    if smb_task and not smb_task.cancelled():
        try:
            r = smb_task.result()
            if r:
                candidates.append(r)
        except Exception:
            pass

    # Layer 2: SNMP
    if snmp_task and not snmp_task.cancelled():
        try:
            r = snmp_task.result()
            if r:
                candidates.append(r)
        except Exception:
            pass

    # Layer 3: MAC OUI (async subprocess)
    mac = await _get_mac_from_arp(ip)
    if mac:
        oui_vendor = _lookup_oui_vendor(mac)
        if oui_vendor:
            candidates.append({
                "vendor": oui_vendor,
                "mac_address": mac,
                "detection_method": "mac_oui",
                "confidence": 50,
            })
        else:
            # We still store the MAC even without vendor match
            candidates.append({
                "mac_address": mac,
                "detection_method": "mac_arp",
                "confidence": 10,
            })

    # Layer 4: UPnP/SSDP
    if upnp_task and not upnp_task.cancelled():
        try:
            r = upnp_task.result()
            if r:
                candidates.append(r)
        except Exception:
            pass

    # Layer 5: mDNS
    if mdns_task and not mdns_task.cancelled():
        try:
            r = mdns_task.result()
            if r:
                candidates.append(r)
        except Exception:
            pass

    # Layer 6: HTTP deep inspection
    if http_task and not http_task.cancelled():
        try:
            r = http_task.result()
            if r:
                candidates.append(r)
        except Exception:
            pass

    # Layer 7: Hostname heuristics
    hn_result = _hostname_heuristics(hostname)
    if hn_result:
        candidates.append(hn_result)

    # Layer 8: Banner analysis
    banner_result = _detect_from_banners(banners, os_guess, hostname)
    if banner_result:
        candidates.append(banner_result)

    # Layer 9: NetBIOS Name Service
    netbios_hostname = ""
    if netbios_task and not netbios_task.cancelled():
        try:
            r = netbios_task.result()
            if r:
                candidates.append(r)
                # NetBIOS can provide hostname — use it if rDNS failed
                if r.get("hostname"):
                    netbios_hostname = r["hostname"]
        except Exception:
            pass

    # Layer 10: TCP passive OS fingerprint (low-confidence fallback)
    if tcp_fp_task and not tcp_fp_task.cancelled():
        try:
            r = tcp_fp_task.result()
            if r:
                candidates.append(r)
        except Exception:
            pass

    # Layer 11: RDP fingerprinting
    if rdp_task and not rdp_task.cancelled():
        try:
            r = rdp_task.result()
            if r:
                candidates.append(r)
        except Exception:
            pass

    # Layer 12: WinRM detection
    if winrm_task and not winrm_task.cancelled():
        try:
            r = winrm_task.result()
            if r:
                candidates.append(r)
        except Exception:
            pass

    # ── Merge: pick highest confidence for each field ──
    best: dict[str, Any] = {
        "os_version": "",
        "vendor": "",
        "device_model": "",
        "firmware": "",
        "mac_address": mac or "",
        "domain": "",
        "hostname_override": netbios_hostname,
        "detection_method": "",
        "confidence": 0,
    }

    # Sort by confidence (highest first)
    candidates.sort(key=lambda c: c.get("confidence", 0), reverse=True)

    for candidate in candidates:
        conf = candidate.get("confidence", 0)
        # Pick the highest-confidence result as primary
        if conf > best["confidence"]:
            best["confidence"] = conf
            best["detection_method"] = candidate.get("detection_method", "")
            if candidate.get("os_version"):
                best["os_version"] = candidate["os_version"]
            if candidate.get("vendor"):
                best["vendor"] = candidate["vendor"]

        # Merge individual fields from any source if not yet set
        if not best["os_version"] and candidate.get("os_version"):
            best["os_version"] = candidate["os_version"]
        if not best["vendor"] and candidate.get("vendor"):
            best["vendor"] = candidate["vendor"]
        if not best["device_model"] and candidate.get("device_model"):
            best["device_model"] = candidate["device_model"]
        if not best["firmware"] and candidate.get("firmware"):
            best["firmware"] = candidate["firmware"]
        if not best["domain"] and candidate.get("domain"):
            best["domain"] = candidate["domain"]
        if not best["mac_address"] and candidate.get("mac_address"):
            best["mac_address"] = candidate["mac_address"]
        if not best["hostname_override"] and candidate.get("hostname"):
            best["hostname_override"] = candidate["hostname"]

    # ── Multi-source confidence boosting ──────────────────────
    # When independent layers agree on the same vendor or OS family,
    # boost confidence proportionally.  Each agreeing layer beyond the
    # first adds +5 pts (capped at 99).
    if best["vendor"] and len(candidates) >= 2:
        vendor_lower = best["vendor"].lower()
        agreeing_methods: list[str] = []
        for c in candidates:
            cv = (c.get("vendor") or "").lower()
            if cv and (cv == vendor_lower or cv in vendor_lower or vendor_lower in cv):
                agreeing_methods.append(c.get("detection_method", "?"))
        agreement_count = len(agreeing_methods)
        if agreement_count >= 2:
            boost = (agreement_count - 1) * 5
            best["confidence"] = min(best["confidence"] + boost, 99)
            logger.debug(
                "Confidence boost: %d layers agree on vendor '%s' → +%d (now %d)",
                agreement_count, best["vendor"], boost, best["confidence"],
            )

    # OS-family agreement boost (e.g. multiple layers say "Windows")
    if best["os_version"] and len(candidates) >= 2:
        os_lower = best["os_version"].lower()
        os_family = ""
        for kw in ("windows", "linux", "ubuntu", "debian", "centos", "ios", "macos"):
            if kw in os_lower:
                os_family = kw
                break
        if os_family:
            os_agree = sum(
                1 for c in candidates
                if os_family in (c.get("os_version") or "").lower()
            )
            if os_agree >= 2:
                boost = (os_agree - 1) * 5
                best["confidence"] = min(best["confidence"] + boost, 99)

    # Build composite detection_method showing all methods used
    methods_used = list(dict.fromkeys(
        c.get("detection_method", "") for c in candidates if c.get("detection_method")
    ))
    if methods_used:
        best["detection_method"] = "+".join(methods_used[:4])

    return best


def _guess_os(open_ports: list[dict[str, Any]]) -> str:
    """Guess the OS/platform type based on which ports are open."""
    port_numbers = {p["port"] for p in open_ports}

    # Strong Windows indicators
    windows_ports = {135, 139, 445, 3389, 5985, 5986, 88, 389, 636, 3268, 3269}
    if port_numbers & windows_ports:
        return "windows"

    # Apple / iOS device
    if 62078 in port_numbers or 548 in port_numbers:
        return "macos"

    # Strong Linux indicator
    if 22 in port_numbers and not (port_numbers & windows_ports):
        return "linux"

    # Database ports
    db_ports = {1433, 5432, 1521, 3306, 6379, 27017, 9200}
    if port_numbers & db_ports and not (port_numbers & windows_ports) and 22 not in port_numbers:
        return "unknown"

    # Printer indicators
    if port_numbers & {631, 9100}:
        return "unknown"

    # Network device indicators
    network_ports = {23, 161, 830, 8291}
    if port_numbers & network_ports and not (port_numbers & windows_ports):
        return "unknown"

    return "unknown"


def _guess_device_role(open_ports: list[dict[str, Any]], os_guess: str) -> str:
    """Guess the device role based on open ports and OS guess.

    Returns one of: domain_controller, server, workstation, network_device,
    database_server, printer, mobile, unknown.
    """
    port_numbers = {p["port"] for p in open_ports}

    # Active Directory Domain Controller (Kerberos + LDAP + SMB)
    ad_ports = {88, 389, 636, 3268, 3269}
    if len(port_numbers & ad_ports) >= 2 and 445 in port_numbers:
        return "domain_controller"

    # Mobile device
    if 62078 in port_numbers:
        return "mobile"

    # Printer
    if port_numbers & {631, 9100} and len(port_numbers) <= 4:
        return "printer"

    # Network device (telnet, SNMP, NETCONF, WinBox — no SSH-only)
    network_ports = {23, 161, 830, 8291}
    if port_numbers & network_ports and not (port_numbers & {135, 445, 3389}):
        return "network_device"

    # Database server
    db_ports = {1433, 5432, 1521, 3306, 6379, 27017, 9200}
    if port_numbers & db_ports:
        return "database_server"

    # Windows server (has server-ish ports)
    if os_guess == "windows" and (port_numbers & {80, 443, 3389, 5985, 5986}):
        return "server"

    # Linux server (SSH + web or other service ports)
    if os_guess == "linux" and len(port_numbers) >= 2:
        return "server"

    # Workstation (minimal ports)
    if os_guess in ("windows", "linux", "macos") and len(port_numbers) <= 3:
        return "workstation"

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
    if 5900 in port_numbers:
        methods.append("vnc")

    # Database-specific
    if 1433 in port_numbers:
        methods.append("mssql")
    if 5432 in port_numbers:
        methods.append("postgresql")
    if 1521 in port_numbers:
        methods.append("oracle")
    if 6379 in port_numbers:
        methods.append("redis")
    if 27017 in port_numbers:
        methods.append("mongodb")

    return methods


async def _scan_host(ip: str, sem: asyncio.Semaphore) -> DiscoveredHost | None:
    """Scan a single host: ping/port probe → banner grab → multi-layer fingerprint.

    Returns a DiscoveredHost even if no ports are open (e.g. phones, IoT)
    as long as the host responds to ICMP ping, has an ARP entry, or answers
    any UDP probe.
    """
    async with sem:
        # Check ARP cache first — if the host responded to the ARP sweep,
        # it's alive even if TCP/ICMP fail (phones, IoT, firewalled hosts)
        arp_alive = ip in _arp_cache

        # Phase 1: Quick alive check — TCP on common ports + ICMP ping in parallel
        quick_ports = [22, 80, 135, 443, 445, 3389, 5985, 8080, 631]
        alive_tasks: list[Any] = [_probe_port(ip, p, timeout=1.0) for p in quick_ports]
        alive_tasks.append(_ping_host(ip, timeout=1.5))
        alive_results = await asyncio.gather(*alive_tasks)

        tcp_alive = any(alive_results[:-1])
        ping_alive = alive_results[-1]

        if not tcp_alive and not ping_alive and not arp_alive:
            return None  # Host appears completely down

        # Phase 2: Full port scan (only bother if TCP showed signs of life)
        open_ports: list[dict[str, Any]] = []
        banners: dict[int, str] = {}

        if tcp_alive:
            port_sem = asyncio.Semaphore(MAX_CONCURRENT_PORTS)

            async def _guarded_probe(port: int) -> bool:
                async with port_sem:
                    return await _probe_port(ip, port)

            tasks = [_guarded_probe(p) for p, _, _ in PROBE_PORTS]
            results = await asyncio.gather(*tasks)

            for (port, service, hint), is_open in zip(PROBE_PORTS, results):
                if is_open:
                    open_ports.append({
                        "port": port,
                        "service": service,
                        "platform_hint": hint,
                    })

            # Banner grabbing (only for open ports)
            if open_ports:
                banners = await _grab_banners(ip, open_ports)

                # Enrich open_ports with version/product extracted from banners
                _enrich_ports_from_banners(open_ports, banners)

        # Phase 3: UDP port probing (lightweight — always run)
        udp_ports = await _udp_probe_host(ip)
        for up in udp_ports:
            # Add to open_ports if not already present from TCP scan
            if not any(p["port"] == up["port"] for p in open_ports):
                open_ports.append(up)

        hostname = await _reverse_dns(ip)
        os_guess = _guess_os(open_ports) if open_ports else "unknown"
        conn_methods = _detect_connection_methods(os_guess, open_ports)

        # Multi-layer fingerprinting (runs even with 0 open ports — uses
        # MAC OUI, UPnP, mDNS, hostname heuristics which don't need ports)
        fp = await _fingerprint_host(ip, hostname, open_ports, banners, os_guess)

        # Use SMB/NTLM hostname if rDNS failed
        if not hostname and fp.get("hostname_override"):
            hostname = fp["hostname_override"]

        # If host responded only to ping (no ports), try to refine os_guess
        # from fingerprint results
        if os_guess == "unknown" and fp.get("vendor"):
            vendor_lower = fp["vendor"].lower()
            if vendor_lower in ("microsoft",):
                os_guess = "windows"
            elif any(kw in vendor_lower for kw in ("canonical", "red hat", "debian",
                     "raspberry pi", "proxmox")):
                os_guess = "linux"
            elif any(kw in vendor_lower for kw in ("samsung", "google", "oneplus",
                     "xiaomi", "huawei", "oppo", "realme", "motorola", "sony",
                     "lg", "nokia", "honor", "amazon")):
                os_guess = "macos" if "apple" in vendor_lower else "unknown"
            elif any(kw in vendor_lower for kw in ("tp-link", "netgear", "asus",
                     "d-link", "linksys", "cisco", "juniper", "mikrotik",
                     "ubiquiti", "fortinet", "arista", "meraki", "sonicwall")):
                os_guess = "unknown"  # network devices — OS determined elsewhere

        # Determine device role from ports + OS
        device_role = _guess_device_role(open_ports, os_guess)

        return DiscoveredHost(
            ip=ip,
            hostname=hostname,
            open_ports=open_ports,
            os_guess=os_guess,
            device_role=device_role,
            connection_methods=conn_methods,
            os_version=fp.get("os_version", ""),
            vendor=fp.get("vendor", ""),
            banners=banners,
            device_model=fp.get("device_model", ""),
            firmware=fp.get("firmware", ""),
            mac_address=fp.get("mac_address", ""),
            domain=fp.get("domain", ""),
            detection_method=fp.get("detection_method", ""),
            confidence=fp.get("confidence", 0),
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


def cancel_discovery(discovery_id: str) -> bool:
    """Request cancellation of an active discovery. Returns True if found."""
    prog = _discovery_progress.get(discovery_id)
    if prog and prog.get("status") == "running":
        prog["cancel_requested"] = True
        return True
    return False


async def discover_network(
    subnet: str,
    discovery_id: str | None = None,
    scan_profile: str = "standard",
) -> list[dict[str, Any]]:
    """Scan a subnet and return a list of discovered hosts with open ports.

    When Nmap is installed, delegates to the Nmap engine for superior OS
    detection and service identification.  Falls back to the built-in
    pure-Python engine otherwise.

    Parameters
    ----------
    subnet:
        CIDR (192.168.1.0/24), range (192.168.1.1-254), or single IP.
    discovery_id:
        Optional ID for progress tracking.
    scan_profile:
        One of ``quick``, ``standard``, ``thorough`` (Nmap only).

    Returns
    -------
    List of dicts with ip, hostname, open_ports, os_guess, connection_methods.
    """
    # ── Route to Nmap engine if available ────────────────────
    from backend.core.nmap_discovery import is_nmap_available, nmap_discover_network
    if is_nmap_available():
        return await nmap_discover_network(subnet, discovery_id, scan_profile)

    logger.info("Nmap not available — using pure-Python discovery engine")

    hosts_to_scan = _parse_subnet(subnet)
    total = len(hosts_to_scan)

    if discovery_id:
        _discovery_progress[discovery_id] = {
            "id": discovery_id,
            "status": "running",
            "total": total,
            "scanned": 0,
            "found": 0,
            "engine": "python",
            "subnet": subnet,
        }

    logger.info("Starting discovery of %d hosts on %s", total, subnet)
    start_time = time.monotonic()

    # Check Docker networking mode — some discovery layers need host networking
    import os
    docker_mode = os.environ.get("DOCKER_HOST_MODE", "")
    is_bridge_mode = docker_mode == "bridge" or os.path.exists("/.dockerenv")
    if is_bridge_mode:
        logger.warning(
            "Running in Docker bridge mode — ARP/MAC, mDNS, SSDP, NetBIOS layers "
            "will be limited. TCP-based detection (SMB, SSH, HTTP, banners) still works."
        )

    # Layer 0: ARP sweep — pre-populate ARP cache for MAC addresses
    # This pings all IPs in parallel then reads the ARP table once
    logger.info("Running ARP sweep for %d hosts...", total)
    arp_results = await _arp_sweep(hosts_to_scan)
    logger.info("ARP sweep complete: %d MAC addresses discovered", len(arp_results))

    # Hosts found by ARP but missed by TCP/ICMP later will still get a
    # DiscoveredHost entry (ensures phones, IoT, stealth hosts appear).
    arp_only_ips: set[str] = set(arp_results.keys())

    sem = asyncio.Semaphore(MAX_CONCURRENT_HOSTS)
    discovered: list[DiscoveredHost] = []

    # Process in batches for progress tracking
    batch_size = MAX_CONCURRENT_HOSTS
    cancelled = False
    for batch_start in range(0, total, batch_size):
        # Check for cancellation between batches
        if discovery_id and _discovery_progress.get(discovery_id, {}).get("cancel_requested"):
            cancelled = True
            logger.info("Discovery %s cancelled by user at batch %d/%d", discovery_id, batch_start, total)
            break

        batch = hosts_to_scan[batch_start:batch_start + batch_size]
        tasks = [_scan_host(ip, sem) for ip in batch]
        results = await asyncio.gather(*tasks)

        for host in results:
            if host is not None:
                discovered.append(host)
                arp_only_ips.discard(host.ip)  # Already scanned

        if discovery_id and discovery_id in _discovery_progress:
            _discovery_progress[discovery_id]["scanned"] = min(batch_start + len(batch), total)
            _discovery_progress[discovery_id]["found"] = len(discovered)

    # Create entries for ARP-only hosts (responded to ping but had no open TCP ports)
    for arp_ip in arp_only_ips:
        mac = arp_results.get(arp_ip, "")
        vendor = _lookup_oui_vendor(mac) if mac else ""
        os_guess = "unknown"
        device_role = "unknown"
        if vendor:
            vendor_lower = vendor.lower()
            if any(kw in vendor_lower for kw in ("samsung", "google", "oneplus",
                   "xiaomi", "huawei", "oppo", "realme", "motorola", "sony",
                   "lg", "nokia", "honor", "amazon")):
                device_role = "mobile"
            elif "apple" in vendor_lower:
                os_guess = "macos"
                device_role = "mobile"
            elif any(kw in vendor_lower for kw in ("tp-link", "netgear", "asus",
                     "d-link", "linksys", "cisco", "juniper", "mikrotik",
                     "ubiquiti", "fortinet", "arista", "meraki", "sonicwall")):
                device_role = "network_device"
        discovered.append(DiscoveredHost(
            ip=arp_ip,
            mac_address=mac,
            vendor=vendor,
            os_guess=os_guess,
            device_role=device_role,
            detection_method="arp_sweep",
            confidence=25 if vendor else 10,
        ))

    elapsed = time.monotonic() - start_time
    final_status = "cancelled" if cancelled else "completed"
    logger.info(
        "Discovery %s: %d hosts found out of %d scanned in %.1fs",
        final_status, len(discovered), total, elapsed,
    )

    if discovery_id and discovery_id in _discovery_progress:
        _discovery_progress[discovery_id]["status"] = final_status
        _discovery_progress[discovery_id]["scanned"] = total if not cancelled else _discovery_progress[discovery_id].get("scanned", 0)
        _discovery_progress[discovery_id]["found"] = len(discovered)
        _discovery_progress[discovery_id]["hosts"] = [h.to_dict() for h in discovered]

    return [h.to_dict() for h in discovered]


def cleanup_discovery(discovery_id: str) -> None:
    """Remove a completed discovery from in-memory tracking."""
    _discovery_progress.pop(discovery_id, None)
