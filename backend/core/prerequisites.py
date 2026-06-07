"""Prerequisite guides for target preparation.

Connection-method-aware, per-platform guides with downloadable script
references. Used by GET /targets/{target_id}/prerequisites.
"""

from __future__ import annotations

from typing import Any

# Script filenames (served by GET /scripts/{filename})
SCRIPT_WIN_WINRM = "Enable_WinRM.ps1"
SCRIPT_WIN_OPENSSH = "Enable_OpenSSH_Windows.ps1"
SCRIPT_LINUX_SSH = "enable_ssh_linux.sh"
SCRIPT_NETWORK_SSH = "network_device_ssh_setup.txt"


def _step(
    title: str,
    description: str,
    command: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "command": command,
        "notes": notes,
    }


# WINDOWS — WinRM (primary)

_WINDOWS_WINRM: dict[str, Any] = {
    "platform": "windows",
    "connection_method": "winrm",
    "download_script": SCRIPT_WIN_WINRM,
    "steps": [
        _step(
            "Enable WinRM",
            "Run this on the target machine (elevated PowerShell):",
            "Enable-PSRemoting -Force\nwinrm quickconfig -q",
            "For domain environments, WinRM can be enabled via GPO:\n"
            "Computer Config → Policies → Admin Templates → Windows Components "
            "→ WinRM Service → Allow remote server management.",
        ),
        _step(
            "Configure HTTPS Listener (recommended)",
            "Create a self-signed certificate and HTTPS listener:",
            (
                "$cert = New-SelfSignedCertificate -DnsName $env:COMPUTERNAME "
                "-CertStoreLocation Cert:\\LocalMachine\\My\n"
                "New-Item WSMan:\\localhost\\Listener -Transport HTTPS -Address * "
                "-CertificateThumbPrint $cert.Thumbprint -Force"
            ),
            "For production, use a CA-signed certificate instead.",
        ),
        _step(
            "Open Firewall Ports",
            "Ensure WinRM ports (5985 HTTP, 5986 HTTPS) are open:",
            "New-NetFirewallRule -Name 'WinRM-HTTPS' -DisplayName 'WinRM HTTPS' "
            "-Protocol TCP -LocalPort 5986 -Action Allow",
            "If using HTTP only, also allow port 5985.",
        ),
        _step(
            "Verify WinRM",
            "Confirm a listener is active:",
            "winrm enumerate winrm/config/listener",
            "You should see at least one HTTPS (or HTTP) listener.",
        ),
    ],
    "alternative": {
        "method": "usb",
        "description": (
            "If WinRM cannot be enabled, use the USB air-gap workflow "
            "to export audit scripts and run them locally on the target."
        ),
    },
    "fallback": {
        "method": "ssh",
        "description": (
            "If WinRM is blocked by policy, you can use OpenSSH as an "
            "alternative. Download the OpenSSH setup script instead."
        ),
        "download_script": SCRIPT_WIN_OPENSSH,
    },
}

# WINDOWS — SSH / OpenSSH (fallback)

_WINDOWS_SSH: dict[str, Any] = {
    "platform": "windows",
    "connection_method": "ssh",
    "download_script": SCRIPT_WIN_OPENSSH,
    "steps": [
        _step(
            "Install OpenSSH Server",
            "Run this on the target (elevated PowerShell):",
            "Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0",
            "Requires Windows 10 1809+ or Windows Server 2019+. "
            "If the capability command fails, try: winget install Microsoft.OpenSSH.Server",
        ),
        _step(
            "Start and Enable sshd",
            "Set the SSH service to auto-start:",
            "Set-Service -Name sshd -StartupType Automatic\nStart-Service sshd",
        ),
        _step(
            "Set PowerShell as Default SSH Shell",
            "AuditForge sends PowerShell commands, so set it as the default shell:",
            'New-ItemProperty -Path "HKLM:\\SOFTWARE\\OpenSSH" -Name DefaultShell '
            '-Value "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -PropertyType String -Force',
            "Without this, commands will run in cmd.exe which may cause audit failures.",
        ),
        _step(
            "Open Firewall Port",
            "Ensure port 22 is open:",
            "New-NetFirewallRule -Name 'OpenSSH-In' -DisplayName 'OpenSSH SSH' "
            "-Protocol TCP -LocalPort 22 -Action Allow",
        ),
        _step(
            "Verify SSH",
            "Confirm sshd is listening:",
            "Get-NetTCPConnection -LocalPort 22 -State Listen",
        ),
    ],
    "alternative": {
        "method": "usb",
        "description": (
            "If neither WinRM nor SSH can be enabled, use the USB air-gap workflow."
        ),
    },
    "fallback": {
        "method": "winrm",
        "description": (
            "WinRM is the recommended protocol for Windows. "
            "Download the WinRM setup script if you prefer it."
        ),
        "download_script": SCRIPT_WIN_WINRM,
    },
}

# LINUX — SSH

_LINUX_SSH: dict[str, Any] = {
    "platform": "linux",
    "connection_method": "ssh",
    "download_script": SCRIPT_LINUX_SSH,
    "steps": [
        _step(
            "Ensure SSH Server is Running",
            "Verify sshd is active:",
            "sudo systemctl status sshd",
            "Install with:\n"
            "  Debian/Ubuntu: sudo apt install openssh-server\n"
            "  RHEL/CentOS:   sudo dnf install openssh-server\n"
            "  SUSE:          sudo zypper install openssh",
        ),
        _step(
            "Configure Sudo Access",
            "The audit user needs passwordless sudo for accurate results:",
            "echo 'audituser ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/auditforge\n"
            "sudo chmod 0440 /etc/sudoers.d/auditforge",
            "Replace 'audituser' with the actual SSH username.",
        ),
        _step(
            "Open Firewall Port",
            "Ensure SSH port (22) is open:",
            "# Ubuntu/Debian (UFW)\nsudo ufw allow 22/tcp\n\n"
            "# RHEL/CentOS (firewalld)\nsudo firewall-cmd --add-service=ssh --permanent\n"
            "sudo firewall-cmd --reload",
        ),
        _step(
            "Key-Based Auth (optional, recommended)",
            "Copy your public key to the target for passwordless login:",
            "ssh-copy-id audituser@TARGET_IP",
            "Then set auth method to 'SSH Key' in AuditForge target settings.",
        ),
    ],
    "alternative": {
        "method": "usb",
        "description": (
            "If SSH cannot be used, export a Bash audit script via the USB "
            "workflow and run it locally on the target."
        ),
    },
    "fallback": None,
}

# NETWORK DEVICES — per-vendor

_NETWORK_GENERIC: dict[str, Any] = {
    "platform": "network",
    "connection_method": "ssh (netmiko)",
    "download_script": SCRIPT_NETWORK_SSH,
    "steps": [
        _step(
            "Enable SSH on the Device",
            "Most network devices support SSH. The commands vary by vendor:",
            "! Cisco IOS example:\nconf t\n  ip domain-name example.com\n"
            "  crypto key generate rsa modulus 2048\n  ip ssh version 2\n"
            "  line vty 0 15\n    transport input ssh\n  end",
            "Download the full reference file for Cisco, Juniper, Palo Alto, "
            "FortiGate, Arista, HP ProCurve, and MikroTik commands.",
        ),
        _step(
            "Create Audit User",
            "Create a local user with read-access privilege:",
            "! Cisco IOS:\nusername auditforge privilege 15 secret <password>\n\n"
            "! Juniper:\nset system login user auditforge class super-user",
            "Use privilege level 15 (Cisco) or super-user class (Juniper) "
            "for full audit read access.",
        ),
        _step(
            "Configure Enable Password (if needed)",
            "Some CIS benchmarks require enable mode. Set the enable password "
            "in AuditForge target settings under 'Enable Password'.",
            notes=(
                "The enable password is encrypted and stored separately from SSH credentials."
            ),
        ),
    ],
    "alternative": {
        "method": "none",
        "description": (
            "Network devices require a live SSH session to run show/config commands. "
            "USB air-gap is not supported."
        ),
    },
    "fallback": None,
}

# Vendor-specific overrides (network)
_NETWORK_CISCO: dict[str, Any] = {
    **_NETWORK_GENERIC,
    "vendor": "cisco",
    "steps": [
        _step(
            "Enable SSH on Cisco IOS",
            "Configure SSH on the device:",
            "conf t\n  hostname SWITCH01\n  ip domain-name auditforge.local\n"
            "  crypto key generate rsa modulus 2048\n  ip ssh version 2\n"
            "  line vty 0 15\n    login local\n    transport input ssh\n  end\n"
            "write memory",
        ),
        _step(
            "Create Audit User (privilege 15)",
            "Create a local user with full read access:",
            "conf t\n  username auditforge privilege 15 secret 0 <CHANGE_PASSWORD>\nend",
            "Privilege 15 grants access to all show commands.",
        ),
        _step(
            "Verify SSH",
            "Confirm SSH is working:",
            "show ip ssh\nshow ssh",
        ),
        *_NETWORK_GENERIC["steps"][2:],  # Enable password step
    ],
}

_NETWORK_JUNIPER: dict[str, Any] = {
    **_NETWORK_GENERIC,
    "vendor": "juniper",
    "steps": [
        _step(
            "SSH on Juniper",
            "SSH is enabled by default on Junos. Create an audit user:",
            "configure\nset system login user auditforge class super-user "
            "authentication plain-text-password\n"
            "set system services ssh protocol-version v2\ncommit and-quit",
            "Enter the password when prompted.",
        ),
        _step(
            "Verify SSH",
            "Confirm SSH services are active:",
            "show system services\nshow configuration system login",
        ),
        *_NETWORK_GENERIC["steps"][2:],
    ],
}

_NETWORK_PALOALTO: dict[str, Any] = {
    **_NETWORK_GENERIC,
    "vendor": "palo_alto",
    "steps": [
        _step(
            "SSH on Palo Alto",
            "SSH is enabled by default on the management interface. Create an admin:",
            "configure\nset mgt-config users auditforge permissions role-based "
            "superreader yes\nset mgt-config users auditforge password\ncommit",
            "Enter the password when prompted.",
        ),
        *_NETWORK_GENERIC["steps"][2:],
    ],
}

_NETWORK_FORTINET: dict[str, Any] = {
    **_NETWORK_GENERIC,
    "vendor": "fortinet",
    "steps": [
        _step(
            "SSH on FortiGate",
            "Enable SSH on the management interface and create an admin:",
            'config system admin\n  edit "auditforge"\n    set accprofile "super_admin_readonly"\n'
            "    set password <CHANGE_PASSWORD>\n  next\nend\n\n"
            "config system interface\n  edit port1\n    set allowaccess ping https ssh\n  next\nend",
        ),
        *_NETWORK_GENERIC["steps"][2:],
    ],
}

# DATABASE

_DATABASE_GENERIC: dict[str, Any] = {
    "platform": "database",
    "connection_method": "direct",
    "download_script": None,
    "steps": [
        _step(
            "Create Audit Database User",
            "Create a read-only user for audit purposes:",
            "-- PostgreSQL:\nCREATE USER auditforge WITH PASSWORD 'secure_password';\n"
            "GRANT CONNECT ON DATABASE mydb TO auditforge;\n"
            "GRANT SELECT ON ALL TABLES IN SCHEMA public TO auditforge;\n\n"
            "-- MSSQL:\nCREATE LOGIN auditforge WITH PASSWORD = 'secure_password';\n"
            "USE mydb;\nCREATE USER auditforge FOR LOGIN auditforge;\n"
            "EXEC sp_addrolemember 'db_datareader', 'auditforge';",
            "Adjust for your DBMS (PostgreSQL, Oracle, MSSQL).",
        ),
        _step(
            "Configure Connection String",
            "Set the database connection details in AuditForge target settings.",
            notes="Format: postgresql://user:pass@host:port/dbname",
        ),
        _step(
            "Open Network Access",
            "Ensure the database port is accessible from the AuditForge server.",
            notes=(
                "Default ports: PostgreSQL=5432, Oracle=1521, MSSQL=1433.\n"
                "PostgreSQL: edit pg_hba.conf to allow remote connections.\n"
                "MSSQL: enable TCP/IP in SQL Server Configuration Manager."
            ),
        ),
    ],
    "alternative": {
        "method": "none",
        "description": (
            "Database audits require a direct network connection. "
            "USB scripts are not supported for database targets."
        ),
    },
    "fallback": None,
}


# Public API

# Lookup table: (platform, connection_method|None) → guide
_GUIDES: dict[tuple[str, str | None], dict[str, Any]] = {
    # Windows
    ("windows", "winrm"):    _WINDOWS_WINRM,
    ("windows", "ssh"):      _WINDOWS_SSH,
    ("windows", None):       _WINDOWS_WINRM,  # default
    # Linux
    ("linux", "ssh"):        _LINUX_SSH,
    ("linux", None):         _LINUX_SSH,
    # Network — vendor-specific
    ("network", None):       _NETWORK_GENERIC,
    ("cisco_ios", None):     _NETWORK_CISCO,
    ("cisco_nxos", None):    _NETWORK_CISCO,
    ("juniper", None):       _NETWORK_JUNIPER,
    ("palo_alto", None):     _NETWORK_PALOALTO,
    ("fortinet", None):      _NETWORK_FORTINET,
    ("arista", None):        _NETWORK_GENERIC,
    ("hp_procurve", None):   _NETWORK_GENERIC,
    # Database
    ("database", None):      _DATABASE_GENERIC,
    ("postgresql", None):    _DATABASE_GENERIC,
    ("oracle", None):        _DATABASE_GENERIC,
    ("mssql", None):         _DATABASE_GENERIC,
}

# Platform normalization
_PLATFORM_ALIASES: dict[str, str] = {
    "cisco_ios": "network",
    "cisco_nxos": "network",
    "juniper": "network",
    "palo_alto": "network",
    "fortinet": "network",
    "arista": "network",
    "hp_procurve": "network",
    "postgresql": "database",
    "oracle": "database",
    "mssql": "database",
}


def get_prerequisite_guide(
    target_type: str,
    connection_method: str | None = None,
) -> dict[str, Any]:
    """Return the prerequisite guide for a given platform and connection method.

    Lookup priority:
      1. Exact (target_type, connection_method)
      2. Exact (target_type, None) — default for that platform
      3. Aliased platform (target_type, None)
      4. Empty fallback
    """
    ttype = (target_type or "").lower().strip()
    conn = (connection_method or "").lower().strip() or None

    # Try exact match
    guide = _GUIDES.get((ttype, conn))
    if guide:
        return guide

    # Try platform default
    guide = _GUIDES.get((ttype, None))
    if guide:
        return guide

    # Try alias
    alias = _PLATFORM_ALIASES.get(ttype)
    if alias:
        guide = _GUIDES.get((alias, conn)) or _GUIDES.get((alias, None))
        if guide:
            return guide

    # Empty fallback
    return {
        "platform": ttype,
        "connection_method": connection_method or "unknown",
        "download_script": None,
        "steps": [],
        "alternative": None,
        "fallback": None,
    }
