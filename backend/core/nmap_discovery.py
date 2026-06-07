"""Nmap-based network discovery engine.

Primary discovery pipeline using Nmap for OS detection, service/version
identification, and port scanning.  Falls back to the pure-Python engine
in ``network_discovery.py`` when Nmap is unavailable.

Requires the ``nmap`` binary installed in the system PATH and the
``python-nmap`` pip package.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import shutil
import time
from typing import Any

logger = logging.getLogger("auditforge.discovery.nmap")

# Nmap availability cache

_nmap_available: bool | None = None  # None = not yet checked


def is_nmap_available() -> bool:
    """Check whether the ``nmap`` binary is on PATH.  Cached after first call."""
    global _nmap_available
    if _nmap_available is None:
        nmap_path = shutil.which("nmap")
        # On Windows, also check the bundled nmap in the install directory
        if nmap_path is None and os.name == "nt":
            from backend.frozen_paths import FROZEN, BUNDLE_DIR
            if FROZEN:
                # Installed: nmap/ is a sibling of server/ under the install dir
                install_nmap = BUNDLE_DIR.parent.parent / "nmap" / "nmap.exe"
                if install_nmap.exists():
                    nmap_path = str(install_nmap)
                    # Add to PATH so python-nmap can also find it
                    os.environ["PATH"] = str(install_nmap.parent) + os.pathsep + os.environ.get("PATH", "")
        _nmap_available = nmap_path is not None
        if _nmap_available:
            logger.info("Nmap binary found at %s — using Nmap discovery engine", nmap_path)
        else:
            logger.warning("Nmap binary NOT found — will fall back to pure-Python discovery")
    return _nmap_available


# Docker bridge detection

_docker_bridge: bool | None = None


def _is_docker_bridge() -> bool:
    """Detect if we're running inside a Docker bridge-mode container.

    In bridge mode, raw-packet Nmap scans (SYN, ICMP, OS fingerprint) get
    NATted by the Docker gateway and produce either ghost hosts or garbage
    OS matches.  TCP-connect scans (``-sT``) use the kernel TCP stack and
    work correctly through NAT.
    """
    global _docker_bridge
    if _docker_bridge is not None:
        return _docker_bridge

    in_docker = os.path.exists("/.dockerenv")
    if not in_docker:
        _docker_bridge = False
        return False

    # Check if we're in host network mode — if so, raw scans work fine
    # In host mode, the container shares the host's network namespace
    # and /sys/class/net/docker0 does NOT exist inside the container.
    host_mode = os.environ.get("NETWORK_MODE", "").lower() == "host"
    if host_mode:
        _docker_bridge = False
        return False

    _docker_bridge = True
    logger.info(
        "Docker bridge network detected — will use TCP-connect scans "
        "(-sT -Pn) instead of raw-packet scans for external subnets"
    )
    return True


def _subnet_is_external(subnet: str) -> bool:
    """Return True if *subnet* is NOT on the container's Docker bridge network.

    When scanning the Docker bridge network itself (e.g. 172.20.0.0/24),
    raw-packet scans work fine because there's no NAT involved.  Only
    external LAN subnets (e.g. the user's home 192.168.1.0/24) need the
    TCP-connect workaround.
    """
    import socket
    import struct  # UNUSED — safe to remove

    try:
        # Get the container's own IP address
        hostname = socket.gethostname()
        container_ip = socket.gethostbyname(hostname)
    except Exception:
        # Can't determine — assume external to be safe
        return True

    try:
        container_net = ipaddress.ip_interface(f"{container_ip}/16").network
        # Parse target subnet
        if "/" in subnet:
            target_net = ipaddress.ip_network(subnet, strict=False)
        else:
            # Single IP or range like "192.168.1.1-50"
            first_ip = subnet.split("-")[0].strip()
            target_net = ipaddress.ip_network(f"{first_ip}/24", strict=False)

        return not target_net.overlaps(container_net)
    except Exception:
        return True


# Scan profiles
# Phase 2 profiles: run Nmap only on live hosts found by the fast probe.
# Since we already know which hosts are alive, we use -Pn (skip discovery).

SCAN_PROFILES: dict[str, dict[str, Any]] = {
    "quick": {
        "label": "Quick Scan",
        "args": "-sT -Pn -T4 --top-ports 100 --host-timeout 30s --max-retries 1",
        "description": "Fast port scan on live hosts. ~30 seconds for a /24.",
    },
    "standard": {
        "label": "Standard (+ services)",
        "args": "-sT -Pn -sV -T4 --top-ports 200 --host-timeout 60s --max-retries 1 --version-intensity 3",
        "description": "Service version detection. ~1 minute for a /24. Recommended.",
    },
    "thorough": {
        "label": "Thorough (deep)",
        "args": "-sT -Pn -sV -T3 --top-ports 1000 --host-timeout 120s --max-retries 2 --version-intensity 5",
        "description": "Deep scan on 1000 ports per host. ~3 minutes for a /24.",
    },
}

DEFAULT_PROFILE = "standard"


# Port → service name lookup
# Used to label ports found by the fast TCP probe that Nmap didn't
# identify.  Prevents ugly "PORT-5985" → shows "WinRM-HTTP" instead.
_PORT_SERVICE_MAP: dict[int, str] = {
    20: "FTP-DATA", 21: "FTP", 22: "SSH", 23: "TELNET", 25: "SMTP",
    53: "DNS", 67: "DHCP", 68: "DHCP", 69: "TFTP", 80: "HTTP",
    88: "KERBEROS", 110: "POP3", 111: "RPCBIND", 123: "NTP",
    135: "MSRPC", 137: "NETBIOS-NS", 138: "NETBIOS-DGM",
    139: "NETBIOS-SSN", 143: "IMAP", 161: "SNMP", 162: "SNMPTRAP",
    389: "LDAP", 443: "HTTPS", 445: "MICROSOFT-DS", 464: "KPASSWD",
    465: "SMTPS", 514: "SYSLOG", 548: "AFP", 554: "RTSP",
    587: "SUBMISSION", 593: "HTTP-RPC", 631: "IPP", 636: "LDAPS",
    873: "RSYNC", 993: "IMAPS", 995: "POP3S",
    1433: "MSSQL", 1521: "ORACLE", 1723: "PPTP", 1883: "MQTT",
    2049: "NFS", 3268: "LDAP-GC", 3269: "LDAPS-GC",
    3306: "MYSQL", 3389: "RDP", 5000: "UPNP",
    5353: "MDNS", 5432: "POSTGRESQL", 5555: "ADB",
    5900: "VNC", 5985: "WINRM-HTTP", 5986: "WINRM-HTTPS",
    6379: "REDIS", 8000: "HTTP-ALT", 8008: "CHROMECAST",
    8080: "HTTP-PROXY", 8443: "HTTPS-ALT", 8883: "MQTT-TLS",
    8888: "HTTP-ALT2", 9090: "HTTP-MGMT", 9100: "RAW-PRINT",
    9200: "ELASTICSEARCH", 9295: "PS-REMOTEPLAY",
    27017: "MONGODB", 62078: "IPHONE-SYNC",
}


# Fast TCP discovery ports
# Broad list of ports likely to be open on home/enterprise networks.
# These are used in the Phase 1 fast-probe to find live hosts.
DISCOVERY_PORTS = [
    21, 22, 23, 25, 53, 80, 110, 111, 135, 139, 143,
    443, 445, 554, 631, 993, 995, 1433, 1521, 1723, 1883,
    3306, 3389, 5000, 5353, 5432, 5900, 5985, 5986,
    6379, 8000, 8080, 8443, 8888, 9090, 9100, 62078,
]

# Trimmed list used only for the fast host-discovery probe.
# We just need to detect if a host is alive — Nmap handles the rest.
# Includes consumer-device ports: 5555 (ADB Wi-Fi), 8008 (Chromecast),
# 9295 (PlayStation Remote Play).
_FAST_PROBE_PORTS = [
    22, 23, 53, 80, 135, 139, 443, 445, 554,
    3389, 5000, 5555, 5900, 5985, 8008, 8080, 8443, 9100, 9295, 62078,
]


# Phase 1: Fast parallel TCP host discovery

async def _fast_host_discovery(
    ips: list[str],
    ports: list[int] | None = None,
    timeout: float = 0.6,
    concurrency: int = 500,
    discovery_id: str | None = None,
) -> dict[str, list[int]]:
    """Rapidly probe *ips* with asyncio TCP connects.

    Returns ``{ip: [open_port, ...]}`` for each host with at least one
    open port.  Completes a full /24 x 17 ports in ~5-8 seconds.
    """
    from backend.core.network_discovery import _discovery_progress

    if ports is None:
        ports = _FAST_PROBE_PORTS

    sem = asyncio.Semaphore(concurrency)
    results: dict[str, list[int]] = {}
    probed = 0
    total_probes = len(ips) * len(ports)

    async def _probe(ip: str, port: int) -> None:
        nonlocal probed
        async with sem:
            try:
                _r, w = await asyncio.wait_for(
                    asyncio.open_connection(ip, port), timeout=timeout
                )
                w.close()
                results.setdefault(ip, []).append(port)
            except Exception:
                pass
            finally:
                probed += 1

    # Update progress periodically
    async def _progress_updater() -> None:
        while probed < total_probes:
            await asyncio.sleep(0.5)
            if discovery_id and discovery_id in _discovery_progress:
                pct = probed / max(total_probes, 1)
                _discovery_progress[discovery_id]["scanned"] = int(pct * len(ips))

    # Launch all probes + progress updater
    tasks = [_probe(ip, port) for ip in ips for port in ports]
    progress_task = asyncio.create_task(_progress_updater())

    await asyncio.gather(*tasks)
    progress_task.cancel()

    logger.info(
        "Fast probe: %d probes (%d hosts x %d ports) → %d live hosts",
        total_probes, len(ips), len(ports), len(results),
    )
    return results


# HTTP banner fingerprinting

_VENDOR_PATTERNS: list[tuple[str, str]] = [
    # (regex_pattern, vendor_name)
    ("rtk web", "Realtek"),
    ("tp-link", "TP-Link"),
    ("tplink", "TP-Link"),
    ("netgear", "Netgear"),
    ("asus", "ASUS"),
    ("linksys", "Linksys"),
    ("d-link", "D-Link"),
    ("dlink", "D-Link"),
    ("ubiquiti", "Ubiquiti"),
    ("unifi", "Ubiquiti"),
    ("mikrotik", "MikroTik"),
    ("routeros", "MikroTik"),
    ("synology", "Synology"),
    ("qnap", "QNAP"),
    ("hikvision", "Hikvision"),
    ("dahua", "Dahua"),
    ("cisco", "Cisco"),
    ("aruba", "Aruba"),
    ("fortinet", "Fortinet"),
    ("fortigate", "Fortinet"),
    ("huawei", "Huawei"),
    ("zyxel", "ZyXEL"),
    ("buffalo", "Buffalo"),
    ("belkin", "Belkin"),
    ("openwrt", "OpenWrt"),
    ("dd-wrt", "DD-WRT"),
    ("pfsense", "pfSense"),
    ("apache", "Apache"),
    ("nginx", "nginx"),
    ("lighttpd", "lighttpd"),
    ("iis", "Microsoft"),
    ("microsoft", "Microsoft"),
    ("fritz!box", "AVM"),
    ("fritzbox", "AVM"),
    ("raspberry", "Raspberry Pi"),
    ("esp32", "Espressif"),
    ("esp8266", "Espressif"),
    ("shelly", "Shelly"),
    ("tasmota", "Tasmota"),
]


async def _http_banner_grab(
    ip: str, port: int = 80, timeout: float = 4.0
) -> dict[str, str]:
    """Grab HTTP headers and a snippet of the HTML body.

    Returns dict with optional keys: server, title, vendor, raw_banner.
    """
    result: dict[str, str] = {}
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
    except Exception:
        return result

    try:
        use_tls = port in (443, 8443)
        req = (
            b"GET / HTTP/1.0\r\n"
            b"Host: " + ip.encode() + b"\r\n"
            b"User-Agent: AuditForge/1.0\r\n"
            b"Connection: close\r\n\r\n"
        )
        writer.write(req)
        await writer.drain()
        data = await asyncio.wait_for(reader.read(4096), timeout=timeout)
        writer.close()

        text = data.decode("utf-8", errors="replace")
        result["raw_banner"] = text[:500]

        # Extract Server header
        import re
        server_match = re.search(r"Server:\s*(.+?)[\r\n]", text, re.IGNORECASE)
        if server_match:
            result["server"] = server_match.group(1).strip()[:100]

        # Extract HTML <title>
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        if title_match:
            result["title"] = title_match.group(1).strip()[:100]

        # Match vendor from server + title + body
        combined = text.lower()
        for pattern, vendor in _VENDOR_PATTERNS:
            if pattern in combined:
                result["vendor"] = vendor
                break

    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass

    return result


# OS mapping

def _nmap_os_to_os_guess(os_name: str) -> str:
    """Map an Nmap OS name string to our canonical os_guess value."""
    lower = os_name.lower()
    if "windows" in lower:
        return "windows"
    if any(kw in lower for kw in ("linux", "ubuntu", "debian", "centos",
                                   "red hat", "fedora", "suse", "alpine",
                                   "arch", "raspberry", "android")):
        return "linux"
    if any(kw in lower for kw in ("mac os", "macos", "os x", "darwin", "ios")):
        return "macos"
    if any(kw in lower for kw in ("cisco", "juniper", "mikrotik", "routeros",
                                   "fortios", "panos", "arista", "vyos")):
        return "network"
    return "unknown"


def _nmap_service_to_platform_hint(service_name: str, product: str) -> str:
    """Derive a platform hint from Nmap service/product info."""
    svc = service_name.lower()
    prod = product.lower()

    if svc in ("msrpc", "netbios-ssn", "microsoft-ds") or "windows" in prod or "iis" in prod:
        return "windows"
    if svc in ("ssh",) and any(kw in prod for kw in ("openssh", "dropbear")):
        return "linux"
    if svc in ("afp",) or "apple" in prod:
        return "macos"
    if any(kw in svc for kw in ("mysql", "postgresql", "oracle", "ms-sql", "redis", "mongodb", "elasticsearch")):
        return "database"
    if any(kw in svc for kw in ("telnet", "snmp", "netconf")):
        return "network"
    if any(kw in svc for kw in ("http", "ssl", "https")):
        return "unknown"
    return "unknown"


# Main Nmap discovery function

async def nmap_discover_network(
    subnet: str,
    discovery_id: str | None = None,
    scan_profile: str = DEFAULT_PROFILE,
) -> list[dict[str, Any]]:
    """Run Nmap-based network discovery on *subnet*.

    Parameters
    ----------
    subnet : str
        CIDR (e.g. ``192.168.1.0/24``), range (``192.168.1.1-50``), or
        single IP.
    discovery_id : str | None
        Optional ID used for progress tracking via ``_discovery_progress``.
    scan_profile : str
        One of ``quick``, ``standard``, ``thorough``.

    Returns
    -------
    list[dict]
        List of host dicts matching the :class:`DiscoveredHost.to_dict()` shape.
    """
    import nmap  # python-nmap

    from backend.core.network_discovery import (
        DiscoveredHost,
        _arp_cache,
        _arp_sweep,
        _detect_connection_methods,
        _discovery_progress,
        _guess_device_role,
        _guess_os,
        _hostname_heuristics,
        _lookup_oui_vendor,
        _netbios_name_query,
        _parse_subnet,
        _ping_host,  # UNUSED — safe to remove
        _smb_ntlm_fingerprint,
        _udp_probe_host,
    )

    profile = SCAN_PROFILES.get(scan_profile, SCAN_PROFILES[DEFAULT_PROFILE])
    nmap_args: str = profile["args"]

    # Parse subnet into individual hosts (for progress counting)
    try:
        all_ips = _parse_subnet(subnet)
    except ValueError:
        all_ips = []  # let Nmap handle the parsing itself

    total = len(all_ips) if all_ips else 0

    if discovery_id:
        _discovery_progress[discovery_id] = {
            "id": discovery_id,
            "status": "running",
            "total": total,
            "scanned": 0,
            "found": 0,
            "engine": "nmap",
            "subnet": subnet,
        }

    logger.info(
        "Starting Nmap discovery on %s [profile=%s, args='%s']",
        subnet, scan_profile, nmap_args,
    )
    start_time = time.monotonic()

    # Phase 0: ARP sweep (same as pure-Python — fills MAC cache)
    if all_ips:
        logger.info("Running ARP sweep for %d hosts...", len(all_ips))
        await _arp_sweep(all_ips)

    # Phase 1: Fast async TCP probe to find live hosts
    # Instead of scanning 254 hosts with Nmap (5+ min), we do a fast
    # parallel TCP probe (3-5 sec) to identify which hosts are alive,
    # then run Nmap only on those live hosts.
    live_hosts: dict[str, list[int]] = {}
    udp_alive: dict[str, list[dict[str, Any]]] = {}  # ip → UDP port results
    if len(all_ips) > 5:
        logger.info("Phase 1: fast TCP probe on %d hosts...", len(all_ips))
        if discovery_id and discovery_id in _discovery_progress:
            _discovery_progress[discovery_id]["status"] = "probing"
        live_hosts = await _fast_host_discovery(
            all_ips, discovery_id=discovery_id,
        )

        # Phase 1b: UDP probe for consumer devices
        # Phones, TVs, game consoles, IoT have zero open TCP ports but
        # respond to mDNS (5353), SSDP (1900), NetBIOS (137), etc.
        # UDP unicast works through Docker bridge NAT.
        logger.info("Phase 1b: UDP probe on %d hosts...", len(all_ips))
        udp_sem = asyncio.Semaphore(50)

        async def _udp_scan(ip: str) -> tuple[str, list[dict[str, Any]]]:
            async with udp_sem:
                ports = await _udp_probe_host(ip, timeout=2.0)
                return ip, ports

        udp_tasks = [_udp_scan(ip) for ip in all_ips]
        udp_results = await asyncio.gather(*udp_tasks)
        for ip, ports in udp_results:
            if ports:
                udp_alive[ip] = ports
                # Mark host as alive if not already found by TCP
                if ip not in live_hosts:
                    live_hosts[ip] = []

        logger.info(
            "Phase 1b: %d hosts responded to UDP probes", len(udp_alive)
        )

        live_ips = sorted(live_hosts.keys(),
                          key=lambda x: int(x.split(".")[-1]))
        logger.info(
            "Phase 1 total: %d live hosts (TCP + UDP): %s",
            len(live_ips), live_ips,
        )

        if not live_ips:
            # No live hosts found
            elapsed = time.monotonic() - start_time
            logger.info("No live hosts found in %.1fs", elapsed)
            if discovery_id and discovery_id in _discovery_progress:
                _discovery_progress[discovery_id].update(
                    status="completed", scanned=total, found=0, hosts=[],
                )
            return []

        # Use live IPs for Phase 2 (Nmap scan)
        scan_target = " ".join(live_ips)
    else:
        # Small target (single IP or <6 hosts) — skip fast probe,
        # but still run UDP probes for service labeling
        scan_target = subnet
        live_ips = all_ips or [subnet]
        for ip in live_ips:
            ports = await _udp_probe_host(ip, timeout=2.0)
            if ports:
                udp_alive[ip] = ports
                live_hosts.setdefault(ip, [])

    # Phase 2: Run Nmap on live hosts only
    if discovery_id and discovery_id in _discovery_progress:
        _discovery_progress[discovery_id]["status"] = "scanning"
        _discovery_progress[discovery_id]["scanned"] = total  # probing done

    nm = nmap.PortScanner()
    all_results: dict[str, dict] = {}

    def _run_nmap() -> None:
        nm.scan(hosts=scan_target, arguments=nmap_args)

    try:
        logger.info(
            "Phase 2: Nmap scan on %d live hosts [%s]",
            len(live_ips), nmap_args,
        )
        await asyncio.to_thread(_run_nmap)
        for hip in nm.all_hosts():
            all_results[hip] = nm[hip]
    except Exception as exc:
        logger.error("Nmap scan failed: %s", exc)
        if discovery_id and discovery_id in _discovery_progress:
            _discovery_progress[discovery_id]["status"] = "failed"
            _discovery_progress[discovery_id]["error"] = str(exc)
        raise

    # Parse Nmap results + merge fast-probe data
    discovered: list[DiscoveredHost] = []

    # Build a set of all hosts to process: Nmap results + fast-probe-only hosts
    # Some hosts respond to fast probe but Nmap marks all their ports "filtered"
    all_host_ips = set(all_results.keys())
    for ip in live_hosts:
        if ip not in all_host_ips:
            all_host_ips.add(ip)

    scanned_hosts = sorted(all_host_ips, key=lambda x: int(x.split(".")[-1]))
    total = max(total, len(scanned_hosts))

    if discovery_id and discovery_id in _discovery_progress:
        _discovery_progress[discovery_id]["total"] = total
        _discovery_progress[discovery_id]["scanned"] = total
        _discovery_progress[discovery_id]["status"] = "enriching"

    for idx, host_ip in enumerate(scanned_hosts):
        if discovery_id and _discovery_progress.get(discovery_id, {}).get("cancel_requested"):
            logger.info("Nmap discovery %s cancelled during enrichment", discovery_id)
            break

        # Gather Nmap data (if available)
        host_data = all_results.get(host_ip)
        nmap_up = host_data is not None and host_data.state() == "up"

        # Extract OS information
        os_version = ""
        os_guess = "unknown"
        os_confidence = 0
        vendor = ""

        if host_data:
            os_matches = host_data.get("osmatch", [])
            if os_matches:
                best_match = os_matches[0]
                os_version = best_match.get("name", "")
                os_confidence = int(best_match.get("accuracy", 0))
                os_guess = _nmap_os_to_os_guess(os_version)
                os_classes = best_match.get("osclass", [])
                if os_classes:
                    vendor = os_classes[0].get("vendor", "")

        # Extract open ports from Nmap
        open_ports: list[dict[str, Any]] = []
        nmap_open_port_nums: set[int] = set()

        if host_data:
            for proto in ("tcp", "udp"):
                port_info = host_data.get(proto, {})
                for port_num, port_data in port_info.items():
                    if port_data.get("state") != "open":
                        continue
                    nmap_open_port_nums.add(int(port_num))

                    svc_name = port_data.get("name", "")
                    product = port_data.get("product", "")
                    version = port_data.get("version", "")
                    extra_info = port_data.get("extrainfo", "")
                    platform_hint = _nmap_service_to_platform_hint(svc_name, product)

                    port_entry: dict[str, Any] = {
                        "port": int(port_num),
                        "service": svc_name.upper() if svc_name else f"PORT-{port_num}",
                        "platform_hint": platform_hint,
                        "proto": proto,
                    }
                    if product:
                        port_entry["product"] = product
                    if version:
                        port_entry["version"] = version
                    snippet_parts = [p for p in (product, version, extra_info) if p]
                    if snippet_parts:
                        port_entry["banner_snippet"] = " ".join(snippet_parts)[:120]

                    open_ports.append(port_entry)

        # Merge ports from fast probe that Nmap missed
        if host_ip in live_hosts:
            for fp_port in live_hosts[host_ip]:
                if fp_port not in nmap_open_port_nums:
                    svc_label = _PORT_SERVICE_MAP.get(fp_port, f"PORT-{fp_port}")
                    open_ports.append({
                        "port": fp_port,
                        "service": svc_label,
                        "platform_hint": "unknown",
                        "proto": "tcp",
                    })

        # Merge UDP ports from Phase 1b
        existing_ports = {p["port"] for p in open_ports}
        if host_ip in udp_alive:
            for udp_entry in udp_alive[host_ip]:
                if udp_entry["port"] not in existing_ports:
                    open_ports.append(udp_entry)
                    existing_ports.add(udp_entry["port"])

        # Skip hosts with no open ports at all
        if not open_ports:
            continue

        # Determine OS guess from ports if Nmap didn't detect OS
        if os_guess == "unknown" and open_ports:
            os_guess = _guess_os(open_ports)

        # Extract hostname
        hostname = ""
        if host_data:
            hostnames_list = host_data.get("hostnames", [])
            if hostnames_list:
                for hn in hostnames_list:
                    name = hn.get("name", "")
                    if name:
                        hostname = name
                        break

        # Extract MAC address
        mac_address = ""
        if host_data:
            addresses = host_data.get("addresses", {})
            if "mac" in addresses:
                mac_address = addresses["mac"].upper()

        # Fall back to ARP cache
        if not mac_address and host_ip in _arp_cache:
            mac_address = _arp_cache[host_ip]

        # MAC OUI vendor (supplement Nmap)
        if mac_address and not vendor:
            oui_vendor = _lookup_oui_vendor(mac_address)
            if oui_vendor:
                vendor = oui_vendor

        # Nmap-provided vendor
        if host_data and not vendor:
            nmap_vendor = host_data.get("vendor", {})
            if nmap_vendor:
                for v in nmap_vendor.values():
                    if v:
                        vendor = v
                        break

        # Determine device role + connection methods
        device_role = _guess_device_role(open_ports, os_guess)
        connection_methods = _detect_connection_methods(os_guess, open_ports)

        # Detection method string
        detection_parts = ["nmap"]
        if host_data and host_data.get("osmatch"):
            detection_parts.append("nmap_os")

        host = DiscoveredHost(
            ip=host_ip,
            hostname=hostname,
            open_ports=open_ports,
            os_guess=os_guess,
            os_version=os_version,
            device_role=device_role,
            vendor=vendor,
            device_model="",
            firmware="",
            mac_address=mac_address,
            domain="",
            detection_method="+".join(detection_parts),
            confidence=os_confidence if os_confidence else (40 if open_ports else 15),
            banners={},
            connection_methods=connection_methods,
        )

        discovered.append(host)

    if discovery_id and discovery_id in _discovery_progress:
        _discovery_progress[discovery_id]["found"] = len(discovered)

    # Phase 3: Targeted enrichment
    logger.info("Enriching %d hosts with targeted probes...", len(discovered))

    for host in discovered:
        if discovery_id and _discovery_progress.get(discovery_id, {}).get("cancel_requested"):
            break

        port_numbers = {p["port"] for p in host.open_ports}
        enriched = False

        # Layer: SMB/NTLM — exact Windows build + AD domain
        # Use 10s timeout (Docker NAT adds latency)
        if 445 in port_numbers:
            if host.os_guess in ("windows", "unknown"):
                try:
                    smb = await _smb_ntlm_fingerprint(host.ip, timeout=10.0)
                    if smb:
                        if smb.get("os_version") and (
                            not host.os_version or "build" not in host.os_version.lower()
                        ):
                            host.os_version = smb["os_version"]
                            host.confidence = max(host.confidence, smb.get("confidence", 0))
                            enriched = True
                        if smb.get("domain"):
                            host.domain = smb["domain"]
                            enriched = True
                        if smb.get("vendor") and not host.vendor:
                            host.vendor = smb["vendor"]
                        if not host.hostname and smb.get("hostname_override"):
                            host.hostname = smb["hostname_override"]
                        if host.os_guess == "unknown":
                            host.os_guess = "windows"
                except Exception:
                    pass

        # Layer: NetBIOS — hostname + domain + MAC (10s timeout)
        if host.os_guess == "windows":
            try:
                nb = await _netbios_name_query(host.ip, timeout=8.0)
                if nb:
                    if nb.get("domain") and not host.domain:
                        host.domain = nb["domain"]
                        enriched = True
                    if nb.get("hostname") and not host.hostname:
                        host.hostname = nb["hostname"]
                    if nb.get("mac_address") and not host.mac_address:
                        host.mac_address = nb["mac_address"]
                        # Re-try vendor lookup with newly discovered MAC
                        if not host.vendor:
                            oui = _lookup_oui_vendor(nb["mac_address"])
                            if oui:
                                host.vendor = oui
            except Exception:
                pass

        # Layer: HTTP banner — vendor identification for routers/IoT
        if not host.vendor and (80 in port_numbers or 443 in port_numbers):
            http_port = 80 if 80 in port_numbers else 443
            try:
                banner = await _http_banner_grab(host.ip, http_port, timeout=5.0)
                if banner:
                    if banner.get("vendor") and not host.vendor:
                        host.vendor = banner["vendor"]
                        enriched = True
                    if banner.get("server"):
                        # Add server header as a hint
                        host.banners["http_server"] = banner["server"]
                    if banner.get("title"):
                        host.banners["http_title"] = banner["title"]
                        if not host.hostname:
                            host.hostname = banner["title"][:50]
            except Exception:
                pass

        # Layer: Hostname heuristics — IoT vendor patterns
        if host.hostname and not host.vendor:
            try:
                hn = _hostname_heuristics(host.hostname)
                if hn and hn.get("vendor"):
                    host.vendor = hn["vendor"]
                    if hn.get("device_model"):
                        host.device_model = hn["device_model"]
                    enriched = True
            except Exception:
                pass

        if enriched:
            if "smb_ntlm" not in host.detection_method and host.domain:
                host.detection_method += "+smb_ntlm"
            if "netbios" not in host.detection_method and host.domain:
                host.detection_method += "+netbios"
            if "http" not in host.detection_method and host.banners.get("http_server"):
                host.detection_method += "+http"

    # Finalise
    elapsed = time.monotonic() - start_time
    cancelled = (
        discovery_id
        and _discovery_progress.get(discovery_id, {}).get("cancel_requested")
    )
    final_status = "cancelled" if cancelled else "completed"

    logger.info(
        "Nmap discovery %s: %d hosts found in %.1fs",
        final_status, len(discovered), elapsed,
    )

    if discovery_id and discovery_id in _discovery_progress:
        _discovery_progress[discovery_id]["status"] = final_status
        _discovery_progress[discovery_id]["scanned"] = total
        _discovery_progress[discovery_id]["found"] = len(discovered)
        _discovery_progress[discovery_id]["hosts"] = [h.to_dict() for h in discovered]

    return [h.to_dict() for h in discovered]
