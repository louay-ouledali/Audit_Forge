"""Network discovery — advanced host fingerprinting & identification.

Uses pure-Python TCP probing, banner grabbing, SMB/NTLM fingerprinting,
SNMP sysDescr, UPnP/SSDP, mDNS, MAC OUI lookup, hostname heuristics,
and deep HTTP inspection — all without external dependencies (no nmap/scapy).

Detection layers (in priority order):
  1. **SMB/NTLM negotiation** → exact Windows version + build + domain
  2. **SNMP sysDescr** → exact device model & firmware (network devices)
  3. **SSH / FTP / Telnet / SMTP banners** → OS family + version
  4. **HTTP deep inspection** → Server header, <title>, login page text
  5. **UPnP SSDP** → manufacturer, model, firmware for routers & IoT
  6. **mDNS** → Apple devices, Chromecasts, printers
  7. **MAC OUI** → vendor from NIC manufacturer (ARP table)
  8. **Hostname heuristics** → pattern matching (TP-Link, NETGEAR, etc.)
  9. **Port-based heuristics** → fallback OS family guess

Each layer contributes to a confidence-weighted result. The highest-confidence
detection wins.  All detections are aggregated into:
  - **os_version**: e.g. "Windows 11 Pro 23H2 (Build 22631)"
  - **vendor**: e.g. "Microsoft", "TP-Link", "Ubiquiti"
  - **device_model**: e.g. "Archer AX73", "EdgeRouter X"
  - **firmware**: e.g. "3.10.0-build20230101"
  - **detection_method**: which layer provided the winning detection
  - **confidence**: 0-100 score
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import struct
import subprocess
import sys
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
    os_version: str = ""       # e.g. "Windows 11 Pro 23H2 (Build 22631)"
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
    # ── Samsung ──
    "00:16:6C": "Samsung", "A0:82:1F": "Samsung", "C4:73:1E": "Samsung",
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

def _get_mac_from_arp(ip: str) -> str:
    """Read the local ARP table to find the MAC address for an IP."""
    try:
        if sys.platform == "win32":
            output = subprocess.check_output(
                ["arp", "-a", ip], timeout=5, text=True, stderr=subprocess.DEVNULL
            )
            # Windows ARP output: "  192.168.1.1  aa-bb-cc-dd-ee-ff  dynamic"
            mac_m = re.search(r"([\da-fA-F]{2}[:-]){5}[\da-fA-F]{2}", output)
            if mac_m:
                return mac_m.group(0).upper().replace("-", ":")
        else:
            # Linux / macOS
            output = subprocess.check_output(
                ["arp", "-n", ip], timeout=5, text=True, stderr=subprocess.DEVNULL
            )
            mac_m = re.search(r"([\da-fA-F]{2}:){5}[\da-fA-F]{2}", output)
            if mac_m:
                return mac_m.group(0).upper()
            # Fallback: /proc/net/arp
            try:
                with open("/proc/net/arp", "r") as f:
                    for line in f:
                        if ip in line:
                            mac_m2 = re.search(r"([\da-fA-F]{2}:){5}[\da-fA-F]{2}", line)
                            if mac_m2:
                                return mac_m2.group(0).upper()
            except FileNotFoundError:
                pass
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
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
    """Send SSDP M-SEARCH and optionally fetch the device description XML.

    Returns dict with: vendor, device_model, os_version, firmware,
    detection_method, confidence. Empty dict on failure.
    """
    result: dict[str, Any] = {}

    msearch = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {ip}:1900\r\n"
        "MAN: \"ssdp:discover\"\r\n"
        "MX: 1\r\n"
        "ST: upnp:rootdevice\r\n"
        "\r\n"
    ).encode()

    loop = asyncio.get_event_loop()
    try:
        transport, _ = await asyncio.wait_for(
            loop.create_datagram_endpoint(
                lambda: asyncio.DatagramProtocol(),
                remote_addr=(ip, 1900),
            ),
            timeout=timeout,
        )
    except Exception:
        return result

    try:
        transport.sendto(msearch)

        # Wait for response
        data = None
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            await asyncio.sleep(0.15)
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
    """Send mDNS query to discover Apple/Google/printer devices.

    Returns dict with: vendor, device_model, detection_method, confidence.
    """
    result: dict[str, Any] = {}

    # Build a minimal mDNS query for _services._dns-sd._udp.local
    # DNS query for _http._tcp.local (PTR)
    query_name = b"\x05_http\x04_tcp\x05local\x00"
    # DNS header: ID=0, flags=0, QD=1, AN=0, NS=0, AR=0
    dns_header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    # Question: name + type PTR (12) + class IN (1) with unicast bit
    question = query_name + struct.pack(">HH", 12, 0x8001)
    mdns_query = dns_header + question

    loop = asyncio.get_event_loop()
    try:
        transport, _ = await asyncio.wait_for(
            loop.create_datagram_endpoint(
                lambda: asyncio.DatagramProtocol(),
                remote_addr=(ip, 5353),
            ),
            timeout=timeout,
        )
    except Exception:
        return result

    try:
        transport.sendto(mdns_query)
        data = None
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            await asyncio.sleep(0.15)
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
            # Try to find printer model
            for brand in ("hp", "brother", "epson", "canon", "xerox", "lexmark", "ricoh"):
                if brand in resp_text:
                    result["vendor"] = brand.capitalize()
                    result["confidence"] = 65
                    break

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

    try:
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

    # Layer 2: SNMP sysDescr (only if port 161 is open)
    snmp_task = None
    if 161 in port_numbers:
        snmp_task = asyncio.create_task(_snmp_sysdescr(ip))

    # Layer 4: UPnP/SSDP (try for all hosts — many respond even without port 1900 in scan)
    upnp_task = asyncio.create_task(_upnp_discover(ip))

    # Layer 5: mDNS
    mdns_task = asyncio.create_task(_mdns_probe(ip))

    # Layer 6: HTTP deep inspection (for any HTTP port)
    http_task = None
    for hport in (80, 443, 8080, 8443, 8000, 8888):
        if hport in port_numbers:
            http_task = asyncio.create_task(_http_deep_inspect(ip, hport))
            break

    # Wait for all async tasks
    all_tasks = [t for t in [smb_task, snmp_task, upnp_task, mdns_task, http_task] if t]
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

    # Layer 3: MAC OUI (synchronous)
    mac = _get_mac_from_arp(ip)
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

    # ── Merge: pick highest confidence for each field ──
    best: dict[str, Any] = {
        "os_version": "",
        "vendor": "",
        "device_model": "",
        "firmware": "",
        "mac_address": mac or "",
        "domain": "",
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
    """Scan a single host: port probe → banner grab → multi-layer fingerprint."""
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

        # Banner grabbing
        banners = await _grab_banners(ip, open_ports)

        # Multi-layer fingerprinting
        fp = await _fingerprint_host(ip, hostname, open_ports, banners, os_guess)

        # Use SMB/NTLM hostname if rDNS failed
        if not hostname and fp.get("hostname_override"):
            hostname = fp["hostname_override"]

        return DiscoveredHost(
            ip=ip,
            hostname=hostname,
            open_ports=open_ports,
            os_guess=os_guess,
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
