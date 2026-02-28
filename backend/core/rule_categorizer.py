"""Keyword-based auto-tagger for rule functional categories.

Improvements over v1:
 - Weighted scoring (title keywords count 3×, description 2×, raw fields 1×)
 - Multi-tag support with primary/secondary ranking
 - Expanded keyword list covering Windows, macOS, and more Linux topics
 - CIS section-number prefix mapping as a strong fallback
 - Smarter display name prettification
"""

from __future__ import annotations

import re

# ── Weight multipliers per source field ──
WEIGHT_TITLE = 3
WEIGHT_DESCRIPTION = 2
WEIGHT_RAW = 1

TAG_KEYWORDS: dict[str, list[str]] = {
    "password_policy": [
        "password", "passphrase", "pam_pwquality", "pam_unix", "minlen", "maxdays",
        "mindays", "warndays", "inactive", "remember=", "complexity", "lockout",
        "account lockout", "faillock", "pam_tally", "maxretries",
        "password policy", "password must meet", "minimum password length",
        "password history", "password age", "credential",
    ],
    "user_accounts": [
        "useradd", "userdel", "usermod", "root", "uid 0", "sudo", "sudoers",
        "wheel", "nologin", "service account", "system account", "shadow",
        "login.defs", "/etc/passwd", "/etc/group", "administrator",
        "guest account", "local accounts", "user right", "user rights",
        "logon", "privilege", "group membership",
    ],
    "ssh_configuration": [
        "sshd", "sshd_config", "authorized_keys", "hostbased",
        "pubkey", "permitroot", "maxauthtries", "x11forwarding",
        "clientalive", "logingracetime", "macs", "kexalgorithms",
        "ssh protocol", "ssh server", "openssh",
    ],
    "network_security": [
        "firewall", "iptables", "nftables", "ufw", "ip_forward", "icmp",
        "tcp_syncookies", "accept_redirects", "accept_source_route", "rp_filter",
        "log_martians", "tcp_wrappers", "hosts.allow", "hosts.deny",
        "wireless", "wifi", "ipv6", "net.ipv4", "net.ipv6",
        "windows firewall", "windows defender firewall", "netsh",
        "network interface", "network bridge", "ip forwarding",
        "network access", "remote desktop", "rdp", "smb signing",
    ],
    "filesystem_permissions": [
        "chmod", "chown", "chgrp", "file permission", "file ownership", "sticky bit",
        "suid", "sgid", "world-writable", "world-readable", "umask", "fstab",
        "noexec", "nosuid", "nodev", "mount", "/tmp", "/var/tmp",
        "partition", "/home", "/var/log", "separate partition",
        "acl", "access control list", "ntfs permission", "file system",
    ],
    "audit_logging": [
        "auditd", "audit.rules", "rsyslog", "syslog-ng", "journald", "logrotate",
        "audit_backlog", "scope.rules", "logins.rules", "time-change",
        "system-locale", "privileged", "mounts", "immutable",
        "aide", "tripwire", "file integrity",
        "event log", "security log", "audit policy", "advanced audit",
        "object access", "logon events", "account management",
        "process creation", "command line", "powershell logging",
        "script block logging", "module logging",
    ],
    "service_hardening": [
        "systemctl disable", "systemctl mask", "avahi", "cups", "dhcpd",
        "slapd", "nfs", "rpcbind", "named", "vsftpd", "httpd", "dovecot",
        "smbd", "squid", "snmpd", "xinetd", "chargen", "daytime", "discard",
        "time service", "rsh", "talk", "telnet", "tftp",
        "unnecessary service", "disable service", "not installed",
        "is not enabled", "removed", "purge", "ensure.*is not installed",
    ],
    "encryption_tls": [
        "encrypt", "tls", "ssl", "certificate", "crypto", "cipher", "grub",
        "luks", "dm-crypt", "gpg", "openssl", "key management", "pki",
        "fips", "aes", "sha256", "sha512",
        "bitlocker", "efi", "secure boot", "uefi",
    ],
    "patch_updates": [
        "update", "upgrade", "patch", "apt-get", "yum update", "dnf update",
        "gpgcheck", "repo_gpgcheck", "package signing", "security update",
        "windows update", "wsus", "hotfix", "software update",
    ],
    "access_control": [
        "apparmor", "selinux", "mac policy", "mandatory access",
        "restrict", "deny", "allow", "privilege escalation",
        "banner", "warning banner", "login banner", "motd", "/etc/issue",
        "screen lock", "screen saver", "idle timeout", "session timeout",
        "lock out", "inactivity", "cron", "at.allow", "at.deny",
        "cron.allow", "cron.deny",
    ],
    "kernel_hardening": [
        "sysctl", "kernel", "core dump", "aslr", "randomize_va_space",
        "dmesg_restrict", "kptr_restrict", "yama", "ptrace",
        "exec-shield", "nx", "address space layout",
    ],
    "time_synchronization": [
        "chrony", "ntp", "ntpd", "timesyncd", "time synchronization",
        "time server", "w32time", "ntp server",
    ],
    "database_security": [
        "pg_hba.conf", "postgresql.conf", "listener.ora", "sqlnet.ora",
        "audit trail", "tablespace", "mysql", "mariadb", "mongodb",
        "oracle database", "sql server", "mssql",
    ],
    "network_device": [
        "access-list", "vty", "management plane",
        "control plane", "aaa authentication", "radius server", "tacacs",
        "snmp community", "snmp-server", "show running-config",
        "router ospf", "router bgp", "cisco", "juniper", "arista",
    ],
    "windows_security": [
        "registry", "local group policy", "gpedit", "secpol", "secedit",
        "wmi", "defender", "antivirus", "antispyware",
        "uac", "user account control", "smartscreen",
        "windows security", "security center", "applocker",
        "device guard", "credential guard", "exploit protection",
        "attack surface reduction", "asr rules",
    ],
}

# ── CIS section-number prefix mapping (common across CIS benchmarks) ──
# When keyword matching fails, section numbering provides strong category hints.
CIS_SECTION_MAP: dict[str, str] = {
    "1.1":  "filesystem_permissions",   # Filesystem configuration
    "1.2":  "patch_updates",            # Software updates
    "1.3":  "access_control",           # Mandatory access control
    "1.4":  "encryption_tls",           # Secure boot / UEFI
    "1.5":  "kernel_hardening",         # Additional hardening
    "1.6":  "access_control",           # Mandatory access control
    "1.7":  "access_control",           # Warning banners
    "1.8":  "access_control",           # GNOME display manager
    "2":    "service_hardening",        # Services
    "3":    "network_security",         # Network configuration
    "4":    "audit_logging",            # Logging and auditing
    "4.1":  "audit_logging",
    "4.2":  "audit_logging",
    "5":    "access_control",           # Access, authentication, authorization
    "5.1":  "access_control",           # Cron
    "5.2":  "ssh_configuration",        # SSH
    "5.3":  "password_policy",          # PAM / password
    "5.4":  "user_accounts",            # User accounts
    "5.5":  "user_accounts",
    "6":    "filesystem_permissions",   # System maintenance
    "6.1":  "filesystem_permissions",
    "6.2":  "user_accounts",
}

# ── Pretty names ──
DISPLAY_NAMES: dict[str, str] = {
    "password_policy":         "Password Policy",
    "user_accounts":           "User Accounts & Privileges",
    "ssh_configuration":       "SSH Configuration",
    "network_security":        "Network Security",
    "filesystem_permissions":  "Filesystem & Permissions",
    "audit_logging":           "Audit & Logging",
    "service_hardening":       "Service Hardening",
    "encryption_tls":          "Encryption & TLS",
    "patch_updates":           "Patch Management",
    "access_control":          "Access Control",
    "kernel_hardening":        "Kernel Hardening",
    "time_synchronization":    "Time Synchronization",
    "database_security":       "Database Security",
    "network_device":          "Network Device Configuration",
    "windows_security":        "Windows Security",
}


def _count_matches(text: str, keywords: list[str]) -> int:
    """Count how many distinct keywords match within *text*."""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def auto_tag_rule(
    title: str,
    description: str = "",
    audit_raw: str = "",
    remediation_raw: str = "",
    section_number: str = "",
) -> list[str]:
    """Return list of tag_ids ranked by weighted relevance score.

    Scoring:
      title match      → +WEIGHT_TITLE  per keyword hit
      description match → +WEIGHT_DESCRIPTION per keyword hit
      raw fields match  → +WEIGHT_RAW per keyword hit

    Falls back to CIS section-number mapping when no keyword matches.
    """
    scores: dict[str, int] = {}

    for tag_id, keywords in TAG_KEYWORDS.items():
        score = 0
        score += _count_matches(title, keywords) * WEIGHT_TITLE
        score += _count_matches(description, keywords) * WEIGHT_DESCRIPTION
        score += _count_matches(audit_raw, keywords) * WEIGHT_RAW
        score += _count_matches(remediation_raw, keywords) * WEIGHT_RAW
        if score > 0:
            scores[tag_id] = score

    if scores:
        # Return tags sorted by descending score
        return sorted(scores, key=lambda t: scores[t], reverse=True)

    # Fallback: CIS section-number prefix mapping
    if section_number:
        for prefix in sorted(CIS_SECTION_MAP, key=len, reverse=True):
            if section_number.startswith(prefix + ".") or section_number == prefix:
                return [CIS_SECTION_MAP[prefix]]

    return []


def prettify_category(tag_id: str) -> str:
    """Convert a tag_id to a human-readable display name."""
    return DISPLAY_NAMES.get(tag_id, tag_id.replace("_", " ").title())
