"""Keyword-based auto-tagger for rule functional categories."""

from __future__ import annotations

import re

TAG_KEYWORDS: dict[str, list[str]] = {
    "password_policy": [
        "password", "passphrase", "pam_pwquality", "pam_unix", "minlen", "maxdays",
        "mindays", "warndays", "inactive", "remember=", "complexity", "lockout",
        "account lockout", "faillock", "pam_tally", "maxretries",
    ],
    "user_accounts": [
        "useradd", "userdel", "usermod", "root", "uid 0", "sudo", "sudoers",
        "wheel", "nologin", "service account", "system account", "shadow",
        "login.defs", "/etc/passwd", "/etc/group", "administrator",
    ],
    "ssh_configuration": [
        "ssh", "sshd", "sshd_config", "authorized_keys", "hostbased",
        "pubkey", "permitroot", "maxauthtries", "x11forwarding", "banner",
        "clientalive", "logingracetime", "macs", "kexalgorithms", "ciphers",
    ],
    "network_security": [
        "firewall", "iptables", "nftables", "ufw", "ip_forward", "icmp",
        "tcp_syncookies", "accept_redirects", "accept_source_route", "rp_filter",
        "log_martians", "tcp_wrappers", "hosts.allow", "hosts.deny",
        "wireless", "wifi", "ipv6", "net.ipv4", "net.ipv6",
    ],
    "filesystem_permissions": [
        "chmod", "chown", "chgrp", "file permission", "file ownership", "sticky bit",
        "suid", "sgid", "world-writable", "world-readable", "umask", "fstab",
        "noexec", "nosuid", "nodev", "mount", "/tmp", "/var/tmp",
    ],
    "audit_logging": [
        "auditd", "audit.rules", "rsyslog", "syslog-ng", "journald", "logrotate",
        "audit_backlog", "scope.rules", "logins.rules", "time-change",
        "system-locale", "privileged", "mounts", "delete", "immutable",
        "aide", "tripwire", "file integrity",
    ],
    "service_hardening": [
        "systemctl disable", "systemctl mask", "avahi", "cups", "dhcpd",
        "slapd", "nfs", "rpcbind", "named", "vsftpd", "httpd", "dovecot",
        "smbd", "squid", "snmpd", "xinetd", "chargen", "daytime", "discard",
        "echo", "time service", "rsh", "talk", "telnet", "tftp",
    ],
    "encryption_tls": [
        "encrypt", "tls", "ssl", "certificate", "crypto", "cipher", "grub",
        "luks", "dm-crypt", "gpg", "openssl", "key management", "pki",
        "fips", "aes", "sha256", "sha512",
    ],
    "patch_updates": [
        "update", "upgrade", "patch", "apt-get", "yum update", "dnf update",
        "gpgcheck", "repo_gpgcheck", "package signing", "security update",
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
}


def auto_tag_rule(title: str, description: str = "", audit_raw: str = "", remediation_raw: str = "") -> list[str]:
    """Return list of tag_ids matched by keywords against rule text.
    
    Searches the concatenation of title + description + audit_raw + remediation_raw
    against keyword lists. Case-insensitive. Any single keyword match is sufficient.
    """
    combined = f"{title} {description} {audit_raw} {remediation_raw}".lower()
    matched: list[str] = []
    for tag_id, keywords in TAG_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in combined:
                matched.append(tag_id)
                break
    return matched
