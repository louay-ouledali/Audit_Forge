"""
Active Directory LDAP Connector
================================
Uses ldap3 to query AD domain controllers for computer objects.
Supports LDAP (389) and LDAPS (636) with optional OU filtering.
"""
from __future__ import annotations

import asyncio
import logging
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ADComputer:
    """Represents a computer discovered via AD LDAP."""
    cn: str
    dns_hostname: str | None = None
    ip_address: str | None = None
    operating_system: str | None = None
    os_version: str | None = None
    distinguished_name: str | None = None
    when_created: datetime | None = None
    last_logon: datetime | None = None
    enabled: bool = True
    ou_path: str | None = None


@dataclass
class ADConnectionResult:
    """Result of an AD connection test."""
    success: bool
    domain_name: str | None = None
    domain_dn: str | None = None
    dc_hostname: str | None = None
    forest_name: str | None = None
    computer_count: int = 0
    error: str | None = None


@dataclass
class ADDiscoveryResult:
    """Result of an AD computer discovery."""
    success: bool
    computers: list[ADComputer] = field(default_factory=list)
    total_found: int = 0
    error: str | None = None


def _import_ldap3():
    """Lazy import ldap3 to avoid hard dependency."""
    try:
        import ldap3
        return ldap3
    except ImportError:
        raise ImportError(
            "ldap3 is required for AD discovery. "
            "Install it with: pip install ldap3>=2.9.0"
        )


def _windows_filetime_to_datetime(ft: int) -> datetime | None:
    """Convert Windows FILETIME (100-ns intervals since 1601-01-01) to Python datetime."""
    if not ft or ft == 0 or ft == 9223372036854775807:  # Never logged on
        return None
    try:
        # Windows epoch offset: 116444736000000000
        epoch_diff = 116444736000000000
        timestamp = (ft - epoch_diff) / 10_000_000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OSError, ValueError, OverflowError):
        return None


def _extract_ou_path(dn: str) -> str | None:
    """Extract the OU path from a distinguished name."""
    if not dn:
        return None
    # Remove the CN= part, keep everything after the first comma
    parts = dn.split(",", 1)
    return parts[1] if len(parts) > 1 else None


def _domain_to_dn(domain: str) -> str:
    """Convert a domain name to a distinguished name base.
    e.g. 'corp.example.com' -> 'DC=corp,DC=example,DC=com'
    """
    return ",".join(f"DC={part}" for part in domain.split("."))


def _resolve_hostname(hostname: str) -> str | None:
    """Resolve a hostname to an IP address."""
    if not hostname:
        return None
    try:
        return socket.gethostbyname(hostname)
    except (socket.gaierror, socket.herror):
        return None


def _is_computer_enabled(uac_value: int | None) -> bool:
    """Check if the computer account is enabled based on userAccountControl flags."""
    if uac_value is None:
        return True
    # Bit 1 (0x0002) = ACCOUNTDISABLE
    return not bool(uac_value & 0x0002)


def test_connection(
    dc_host: str,
    domain: str,
    username: str,
    password: str,
    use_ssl: bool = True,
) -> ADConnectionResult:
    """Test connection to an AD domain controller.

    Returns domain information if successful.
    """
    ldap3 = _import_ldap3()

    port = 636 if use_ssl else 389
    server_kwargs: dict[str, Any] = {
        "host": dc_host,
        "port": port,
        "get_info": ldap3.ALL,
        "connect_timeout": 10,
    }
    if use_ssl:
        server_kwargs["use_ssl"] = True
        tls = ldap3.Tls(validate=0)  # Allow self-signed certs in enterprise
        server_kwargs["tls"] = tls

    try:
        server = ldap3.Server(**server_kwargs)

        # Build the bind DN — prefer NTLM (DOMAIN\user) over UPN for security
        bind_user = username
        if "\\" not in username and "@" not in username:
            # Default to NTLM format (DOMAIN\user) which is safer than
            # SIMPLE bind with UPN (user@domain) over non-TLS connections.
            short_domain = domain.split(".")[0].upper()
            bind_user = f"{short_domain}\\{username}"

        conn = ldap3.Connection(
            server,
            user=bind_user,
            password=password,
            authentication=ldap3.NTLM if "\\" in bind_user else ldap3.SIMPLE,
            auto_bind=True,
            raise_exceptions=True,
        )

        # Get domain info from RootDSE
        domain_dn = _domain_to_dn(domain)
        forest_name = None
        dc_hostname = dc_host

        if server.info:
            if hasattr(server.info, "other"):
                other = server.info.other
                if "defaultNamingContext" in other:
                    domain_dn = other["defaultNamingContext"][0]
                if "dnsHostName" in other:
                    dc_hostname = other["dnsHostName"][0]
                if "rootDomainNamingContext" in other:
                    root_nc = other["rootDomainNamingContext"][0]
                    # Convert DC=corp,DC=example,DC=com -> corp.example.com
                    forest_name = ".".join(
                        p.split("=")[1] for p in root_nc.split(",")
                        if "=" in p
                    )

        # Quick count of computer objects
        search_base = domain_dn
        conn.search(
            search_base=search_base,
            search_filter="(objectClass=computer)",
            search_scope=ldap3.SUBTREE,
            attributes=[],
            paged_size=1,
        )
        # For a count, we do a paged search and read the total
        computer_count = 0
        try:
            conn.search(
                search_base=search_base,
                search_filter="(objectClass=computer)",
                search_scope=ldap3.SUBTREE,
                attributes=["cn"],
                paged_size=500,
            )
            computer_count = len(conn.entries)
            # Continue paging
            cookie = conn.result.get("controls", {}).get(
                "1.2.840.113556.1.4.319", {}
            ).get("value", {}).get("cookie")
            while cookie:
                conn.search(
                    search_base=search_base,
                    search_filter="(objectClass=computer)",
                    search_scope=ldap3.SUBTREE,
                    attributes=["cn"],
                    paged_size=500,
                    paged_cookie=cookie,
                )
                computer_count += len(conn.entries)
                cookie = conn.result.get("controls", {}).get(
                    "1.2.840.113556.1.4.319", {}
                ).get("value", {}).get("cookie")
        except Exception:
            pass  # Count is optional

        conn.unbind()

        return ADConnectionResult(
            success=True,
            domain_name=domain,
            domain_dn=domain_dn,
            dc_hostname=dc_hostname,
            forest_name=forest_name,
            computer_count=computer_count,
        )
    except Exception as e:
        logger.warning("AD connection test failed for %s: %s", dc_host, e)
        error_msg = str(e)
        if "invalidCredentials" in error_msg:
            error_msg = "Invalid credentials. Check username and password."
        elif "connect" in error_msg.lower() or "timeout" in error_msg.lower():
            error_msg = f"Cannot reach {dc_host}:{port}. Check hostname and network connectivity."
        return ADConnectionResult(success=False, error=error_msg)


def discover_computers(
    dc_host: str,
    domain: str,
    username: str,
    password: str,
    use_ssl: bool = True,
    ou_filter: str | None = None,
    resolve_dns: bool = True,
) -> ADDiscoveryResult:
    """Discover computer objects in Active Directory.

    Args:
        dc_host: Domain controller hostname or IP
        domain: AD domain name (e.g. corp.example.com)
        username: Username (DOMAIN\\user or user@domain)
        password: Password
        use_ssl: Use LDAPS (636) instead of LDAP (389)
        ou_filter: Optional OU to limit search (e.g. "OU=Servers,DC=corp,DC=example,DC=com")
        resolve_dns: Whether to resolve DNS hostnames to IP addresses
    """
    ldap3 = _import_ldap3()

    port = 636 if use_ssl else 389
    server_kwargs: dict[str, Any] = {
        "host": dc_host,
        "port": port,
        "connect_timeout": 15,
    }
    if use_ssl:
        server_kwargs["use_ssl"] = True
        tls = ldap3.Tls(validate=0)
        server_kwargs["tls"] = tls

    try:
        server = ldap3.Server(**server_kwargs)

        bind_user = username
        if "\\" not in username and "@" not in username:
            short_domain = domain.split(".")[0].upper()
            bind_user = f"{short_domain}\\{username}"

        conn = ldap3.Connection(
            server,
            user=bind_user,
            password=password,
            authentication=ldap3.NTLM if "\\" in bind_user else ldap3.SIMPLE,
            auto_bind=True,
            raise_exceptions=True,
        )

        # Determine search base
        search_base = ou_filter if ou_filter else _domain_to_dn(domain)

        # Attributes to fetch
        attrs = [
            "cn",
            "dNSHostName",
            "operatingSystem",
            "operatingSystemVersion",
            "distinguishedName",
            "whenCreated",
            "lastLogonTimestamp",
            "userAccountControl",
        ]

        # LDAP filter for computer objects
        ldap_filter = "(&(objectClass=computer)(objectCategory=computer))"

        # Paged search for large domains
        all_entries: list = []
        conn.search(
            search_base=search_base,
            search_filter=ldap_filter,
            search_scope=ldap3.SUBTREE,
            attributes=attrs,
            paged_size=500,
        )
        all_entries.extend(conn.entries)

        # Handle paging
        cookie = conn.result.get("controls", {}).get(
            "1.2.840.113556.1.4.319", {}
        ).get("value", {}).get("cookie")
        while cookie:
            conn.search(
                search_base=search_base,
                search_filter=ldap_filter,
                search_scope=ldap3.SUBTREE,
                attributes=attrs,
                paged_size=500,
                paged_cookie=cookie,
            )
            all_entries.extend(conn.entries)
            cookie = conn.result.get("controls", {}).get(
                "1.2.840.113556.1.4.319", {}
            ).get("value", {}).get("cookie")

        conn.unbind()

        # Parse entries into ADComputer objects
        computers: list[ADComputer] = []
        for entry in all_entries:
            try:
                cn = str(entry.cn) if hasattr(entry, "cn") else "Unknown"
                dns_hostname = str(entry.dNSHostName) if hasattr(entry, "dNSHostName") and entry.dNSHostName.value else None
                os_str = str(entry.operatingSystem) if hasattr(entry, "operatingSystem") and entry.operatingSystem.value else None
                os_ver = str(entry.operatingSystemVersion) if hasattr(entry, "operatingSystemVersion") and entry.operatingSystemVersion.value else None
                dn = str(entry.distinguishedName) if hasattr(entry, "distinguishedName") and entry.distinguishedName.value else None

                # Parse whenCreated
                when_created = None
                if hasattr(entry, "whenCreated") and entry.whenCreated.value:
                    wc = entry.whenCreated.value
                    if isinstance(wc, datetime):
                        when_created = wc.replace(tzinfo=timezone.utc) if wc.tzinfo is None else wc

                # Parse lastLogonTimestamp (Windows FILETIME)
                last_logon = None
                if hasattr(entry, "lastLogonTimestamp") and entry.lastLogonTimestamp.value:
                    lt = entry.lastLogonTimestamp.value
                    if isinstance(lt, int):
                        last_logon = _windows_filetime_to_datetime(lt)
                    elif isinstance(lt, datetime):
                        last_logon = lt.replace(tzinfo=timezone.utc) if lt.tzinfo is None else lt

                # Check if enabled
                uac = None
                if hasattr(entry, "userAccountControl") and entry.userAccountControl.value:
                    uac = int(entry.userAccountControl.value)
                enabled = _is_computer_enabled(uac)

                # Resolve IP
                ip_address = None
                if resolve_dns and dns_hostname:
                    ip_address = _resolve_hostname(dns_hostname)

                computers.append(ADComputer(
                    cn=cn,
                    dns_hostname=dns_hostname,
                    ip_address=ip_address,
                    operating_system=os_str,
                    os_version=os_ver,
                    distinguished_name=dn,
                    when_created=when_created,
                    last_logon=last_logon,
                    enabled=enabled,
                    ou_path=_extract_ou_path(dn) if dn else None,
                ))
            except Exception as e:
                logger.warning("Failed to parse AD entry: %s", e)
                continue

        return ADDiscoveryResult(
            success=True,
            computers=computers,
            total_found=len(computers),
        )

    except Exception as e:
        logger.error("AD discovery failed: %s", e)
        return ADDiscoveryResult(success=False, error=str(e))


async def async_test_connection(
    dc_host: str,
    domain: str,
    username: str,
    password: str,
    use_ssl: bool = True,
) -> ADConnectionResult:
    """Async wrapper for test_connection."""
    return await asyncio.to_thread(
        test_connection, dc_host, domain, username, password, use_ssl
    )


async def async_discover_computers(
    dc_host: str,
    domain: str,
    username: str,
    password: str,
    use_ssl: bool = True,
    ou_filter: str | None = None,
    resolve_dns: bool = True,
) -> ADDiscoveryResult:
    """Async wrapper for discover_computers."""
    return await asyncio.to_thread(
        discover_computers, dc_host, domain, username, password, use_ssl, ou_filter, resolve_dns
    )


def check_winrm_port(host: str, port: int = 5985, timeout: float = 3.0) -> bool:
    """Quick TCP probe to check if WinRM port is open."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


async def async_check_winrm(
    host: str,
    timeout: float = 3.0,
) -> dict[str, Any]:
    """Check WinRM availability on both HTTP and HTTPS ports."""
    http_open = await asyncio.to_thread(check_winrm_port, host, 5985, timeout)
    https_open = await asyncio.to_thread(check_winrm_port, host, 5986, timeout)
    return {
        "host": host,
        "winrm_http": http_open,
        "winrm_https": https_open,
        "winrm_available": http_open or https_open,
        "recommended_port": 5986 if https_open else (5985 if http_open else None),
    }


# Benchmark Matching

# Map AD operatingSystem strings to our benchmark platform keys
_OS_PATTERNS: list[tuple[str, str, str]] = [
    # (regex_pattern, target_type, platform_subtype)
    (r"Windows 11.*Enterprise", "windows", "windows_11_enterprise"),
    (r"Windows 11.*Pro", "windows", "windows_11_pro"),
    (r"Windows 11", "windows", "windows_11"),
    (r"Windows 10.*Enterprise", "windows", "windows_10_enterprise"),
    (r"Windows 10", "windows", "windows_10"),
    (r"Windows Server 2025", "windows", "server_2025"),
    (r"Windows Server 2022", "windows", "server_2022"),
    (r"Windows Server 2019", "windows", "server_2019"),
    (r"Windows Server 2016", "windows", "server_2016"),
    (r"Windows Server 2012 R2", "windows", "server_2012r2"),
    (r"Windows Server 2012", "windows", "server_2012"),
    (r"Red Hat|RHEL", "linux", "rhel"),
    (r"Ubuntu", "linux", "ubuntu"),
    (r"CentOS", "linux", "centos"),
    (r"Debian", "linux", "debian"),
    (r"SUSE|SLES", "linux", "suse"),
]


def match_os_to_platform(os_string: str | None) -> dict[str, str | None]:
    """Match an AD operatingSystem string to a target type and platform subtype.

    Returns:
        Dict with keys: target_type, platform_subtype, confidence
        confidence is "exact", "close", or "none"
    """
    if not os_string:
        return {"target_type": None, "platform_subtype": None, "confidence": "none"}

    for pattern, target_type, subtype in _OS_PATTERNS:
        if re.search(pattern, os_string, re.IGNORECASE):
            return {
                "target_type": target_type,
                "platform_subtype": subtype,
                "confidence": "exact",
            }

    # Fallback heuristics
    os_lower = os_string.lower()
    if "windows" in os_lower:
        return {"target_type": "windows", "platform_subtype": None, "confidence": "close"}
    if any(k in os_lower for k in ("linux", "ubuntu", "centos", "red hat", "debian")):
        return {"target_type": "linux", "platform_subtype": None, "confidence": "close"}

    return {"target_type": None, "platform_subtype": None, "confidence": "none"}


def match_benchmark(
    os_string: str | None,
    benchmarks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find the best matching benchmark for a given OS string.

    Args:
        os_string: The AD operatingSystem string
        benchmarks: List of benchmark dicts with keys: id, name, platform, version

    Returns:
        Best matching benchmark dict or None
    """
    platform_info = match_os_to_platform(os_string)
    if platform_info["confidence"] == "none":
        return None

    subtype = platform_info["platform_subtype"] or ""
    target_type = platform_info["target_type"] or ""

    best_match = None
    best_score = 0

    # Database-family benchmarks should never match AD-discovered Windows hosts
    _DB_KEYWORDS = {"sql server", "postgresql", "oracle database", "mysql",
                    "mongodb", "cassandra", "mariadb", "redis"}

    for bm in benchmarks:
        bm_name = (bm.get("name") or "").lower()
        bm_platform = (bm.get("platform") or "").lower()

        # Skip database benchmarks for OS matching — they should only be
        # suggested when a database port is discovered, not from AD OS string
        if any(kw in bm_name for kw in _DB_KEYWORDS):
            continue

        score = 0
        # Check if benchmark matches the target type
        if target_type and target_type in bm_platform:
            score += 1
        elif target_type and target_type in bm_name:
            score += 1

        # Check for specific platform subtype match
        if subtype:
            subtype_parts = subtype.replace("_", " ").split()
            for part in subtype_parts:
                if part in bm_name:
                    score += 2

        if score > best_score:
            best_score = score
            best_match = bm

    if best_match and best_score >= 1:
        return {
            **best_match,
            "match_confidence": platform_info["confidence"],
            "match_score": best_score,
        }
    return None


# Remote WinRM Enablement

def generate_enable_winrm_script(targets: list[str], domain: str, username: str) -> str:
    """Generate a PowerShell script that an admin can run to enable WinRM on remote machines.

    This is the fallback method when direct WMI enablement isn't possible.
    The script uses Invoke-Command via WMI/DCOM to enable WinRM on each target.
    """
    target_list = ", ".join(f'"{t}"' for t in targets)
    script = f'''# AuditForge - Enable WinRM on Remote Targets
# Run this script as Domain Admin on a machine with network access to targets
# Domain: {domain}
# Generated for: {username}

$ErrorActionPreference = "Continue"
$targets = @({target_list})
$credential = Get-Credential -Message "Enter Domain Admin credentials for {domain}"

$results = @()
foreach ($target in $targets) {{
    Write-Host "Processing $target..." -ForegroundColor Cyan
    try {{
        # Method 1: Try psexec-style via WMI
        $result = Invoke-WmiMethod -Class Win32_Process -Name Create `
            -ArgumentList "cmd /c winrm quickconfig -quiet -force" `
            -ComputerName $target `
            -Credential $credential `
            -ErrorAction Stop

        if ($result.ReturnValue -eq 0) {{
            Write-Host "  [OK] WinRM enable command sent via WMI" -ForegroundColor Green

            # Wait for WinRM to start
            Start-Sleep -Seconds 5

            # Configure WinRM for remote management
            # NOTE: We use Kerberos/NTLM auth (not Basic), and do NOT enable
            # AllowUnencrypted — WinRM over HTTPS is strongly recommended.
            Invoke-WmiMethod -Class Win32_Process -Name Create `
                -ArgumentList "powershell -Command Enable-PSRemoting -Force -SkipNetworkProfileCheck" `
                -ComputerName $target `
                -Credential $credential `
                -ErrorAction SilentlyContinue

            $results += [PSCustomObject]@{{ Target=$target; Status="Success"; Method="WMI" }}
        }} else {{
            throw "WMI Process Create returned $($result.ReturnValue)"
        }}
    }} catch {{
        Write-Host "  [WARN] WMI method failed: $_" -ForegroundColor Yellow
        try {{
            # Method 2: Try via scheduled task
            $action = New-ScheduledTaskAction -Execute "powershell.exe" `
                -Argument "-Command Enable-PSRemoting -Force -SkipNetworkProfileCheck; winrm quickconfig -quiet -force"
            $taskName = "AuditForge_EnableWinRM"

            Register-ScheduledTask -TaskName $taskName -Action $action `
                -RunLevel Highest -Force `
                -CimSession (New-CimSession -ComputerName $target -Credential $credential) `
                -ErrorAction Stop

            Start-ScheduledTask -TaskName $taskName `
                -CimSession (New-CimSession -ComputerName $target -Credential $credential)

            Start-Sleep -Seconds 10

            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false `
                -CimSession (New-CimSession -ComputerName $target -Credential $credential) `
                -ErrorAction SilentlyContinue

            Write-Host "  [OK] WinRM enabled via Scheduled Task" -ForegroundColor Green
            $results += [PSCustomObject]@{{ Target=$target; Status="Success"; Method="ScheduledTask" }}
        }} catch {{
            Write-Host "  [FAIL] Could not enable WinRM: $_" -ForegroundColor Red
            $results += [PSCustomObject]@{{ Target=$target; Status="Failed"; Method="None"; Error=$_.ToString() }}
        }}
    }}
}}

Write-Host "`n=== Results ===" -ForegroundColor Yellow
$results | Format-Table -AutoSize

# Verify WinRM connectivity
Write-Host "`nVerifying WinRM connectivity..." -ForegroundColor Cyan
foreach ($target in $targets) {{
    try {{
        Test-WSMan -ComputerName $target -Credential $credential -ErrorAction Stop | Out-Null
        Write-Host "  $target : WinRM OK" -ForegroundColor Green
    }} catch {{
        Write-Host "  $target : WinRM NOT responding" -ForegroundColor Red
    }}
}}
'''
    return script


async def async_enable_winrm_via_wmi(
    target_host: str,
    dc_host: str,
    domain: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    """Try to enable WinRM on a target machine via WMI through the domain controller.

    This requires the DC to have WinRM enabled and the user to have WMI access.
    Falls back to generating a script if direct enablement fails.
    """
    return await asyncio.to_thread(
        _enable_winrm_via_wmi, target_host, dc_host, domain, username, password
    )


def _enable_winrm_via_wmi(
    target_host: str,
    dc_host: str,
    domain: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    """Synchronous WinRM enablement via WMI."""
    try:
        import winrm as pywinrm
    except ImportError:
        return {
            "success": False,
            "method": "script_fallback",
            "error": "pywinrm not available for WMI relay",
            "script": generate_enable_winrm_script([target_host], domain, username),
        }

    try:
        # Connect to DC via WinRM, then use WMI to enable WinRM on target
        bind_user = username if "\\" in username else f"{domain.split('.')[0].upper()}\\{username}"

        session = pywinrm.Session(
            dc_host,
            auth=(bind_user, password),
            transport="ntlm",
            server_cert_validation="ignore",
        )

        # Use PowerShell on the DC to invoke WMI on the target
        ps_cmd = f'''
        try {{
            $result = Invoke-WmiMethod -Class Win32_Process -Name Create `
                -ArgumentList "cmd /c winrm quickconfig -quiet -force" `
                -ComputerName "{target_host}" -ErrorAction Stop
            if ($result.ReturnValue -eq 0) {{
                Write-Output "SUCCESS"
            }} else {{
                Write-Output "FAILED:ReturnValue=$($result.ReturnValue)"
            }}
        }} catch {{
            Write-Output "FAILED:$($_.Exception.Message)"
        }}
        '''
        result = session.run_ps(ps_cmd)
        output = result.std_out.decode("utf-8", errors="replace").strip()

        if "SUCCESS" in output:
            return {
                "success": True,
                "method": "wmi",
                "message": f"WinRM enable command sent to {target_host} via WMI",
            }
        else:
            return {
                "success": False,
                "method": "script_fallback",
                "error": f"WMI enablement returned: {output}",
                "script": generate_enable_winrm_script([target_host], domain, username),
            }

    except Exception as e:
        logger.warning("WMI WinRM enablement failed for %s: %s", target_host, e)
        return {
            "success": False,
            "method": "script_fallback",
            "error": str(e),
            "script": generate_enable_winrm_script([target_host], domain, username),
        }
