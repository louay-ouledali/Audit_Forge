"""On-demand security checks against parsed device configurations.

Universal checks (platform-agnostic) plus platform-specific checks.
Each check returns a list of SecurityFinding dicts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class SecurityFinding:
    check_id: str
    severity: str  # "critical", "high", "medium", "low", "info"
    title: str
    description: str
    remediation: str
    matched_lines: list[str]


def run_security_checks(raw_config: str, format_id: str) -> list[SecurityFinding]:
    """Run all applicable security checks against a raw config string."""
    findings: list[SecurityFinding] = []
    lines = raw_config.splitlines()

    # Universal checks
    findings.extend(_check_weak_snmp(lines))
    findings.extend(_check_no_ntp(lines, format_id))
    findings.extend(_check_no_syslog(lines, format_id))
    findings.extend(_check_no_banner(lines, format_id))
    findings.extend(_check_weak_crypto(lines))
    findings.extend(_check_cleartext_passwords(lines))

    # Platform-specific
    if format_id in ("ios", "unknown"):
        findings.extend(_check_ios_telnet(lines))
        findings.extend(_check_ios_ssh_v1(lines))
        findings.extend(_check_ios_no_aaa(lines))
        findings.extend(_check_ios_http_server(lines))

    if format_id == "fortios":
        findings.extend(_check_forti_admin_http(lines))

    return findings


# ── Universal checks ──────────────────────────────────────────────


def _check_weak_snmp(lines: list[str]) -> list[SecurityFinding]:
    weak = ["public", "private", "community"]
    matched = []
    for line in lines:
        stripped = line.strip().lower()
        if "snmp" in stripped and "community" in stripped:
            for w in weak:
                if w in stripped:
                    matched.append(line.strip())
                    break
    if matched:
        return [SecurityFinding(
            check_id="SEC-SNMP-WEAK",
            severity="high",
            title="Weak SNMP community string detected",
            description="Default or weak SNMP community strings (public/private) allow unauthorized device monitoring and management.",
            remediation="Replace default community strings with complex, unique values. Consider migrating to SNMPv3 with authentication and encryption.",
            matched_lines=matched,
        )]
    return []


def _check_no_ntp(lines: list[str], format_id: str) -> list[SecurityFinding]:
    ntp_patterns = {
        "ios": r"ntp server",
        "fortios": r"set ntpserver|set type ntp",
        "junos": r"set system ntp server",
        "checkpoint": r"set ntp",
        "panos_xml": r"<ntp-server",
        "pfsense_xml": r"<timeservers>",
    }
    pattern = ntp_patterns.get(format_id, r"ntp")
    text = "\n".join(lines)
    if not re.search(pattern, text, re.IGNORECASE):
        return [SecurityFinding(
            check_id="SEC-NTP-MISSING",
            severity="medium",
            title="No NTP configuration detected",
            description="Without NTP, device timestamps may drift, making log correlation and forensic analysis unreliable.",
            remediation="Configure at least two NTP servers for time synchronization.",
            matched_lines=[],
        )]
    return []


def _check_no_syslog(lines: list[str], format_id: str) -> list[SecurityFinding]:
    syslog_patterns = {
        "ios": r"logging host|logging server",
        "fortios": r"set server\s+\S+|config log syslogd",
        "junos": r"set system syslog host",
        "checkpoint": r"set syslog",
        "panos_xml": r"<syslog>",
        "pfsense_xml": r"<syslog>|<remoteserver>",
    }
    pattern = syslog_patterns.get(format_id, r"syslog|logging")
    text = "\n".join(lines)
    if not re.search(pattern, text, re.IGNORECASE):
        return [SecurityFinding(
            check_id="SEC-SYSLOG-MISSING",
            severity="medium",
            title="No remote syslog configuration detected",
            description="Without remote logging, audit trails exist only on the device and can be lost or tampered with.",
            remediation="Configure remote syslog to a centralized log management system.",
            matched_lines=[],
        )]
    return []


def _check_no_banner(lines: list[str], format_id: str) -> list[SecurityFinding]:
    banner_patterns = {
        "ios": r"^banner\s+(login|motd|exec)",
        "fortios": r"set pre-login-banner|set post-login-banner",
        "junos": r"set system login message",
        "checkpoint": r"set message-of-the-day",
    }
    pattern = banner_patterns.get(format_id)
    if pattern is None:
        return []
    text = "\n".join(lines)
    if not re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
        return [SecurityFinding(
            check_id="SEC-BANNER-MISSING",
            severity="low",
            title="No login banner configured",
            description="A login banner provides legal notice to unauthorized users and is required by many compliance frameworks.",
            remediation="Configure a login banner with appropriate legal warning text.",
            matched_lines=[],
        )]
    return []


def _check_weak_crypto(lines: list[str]) -> list[SecurityFinding]:
    weak_patterns = [
        (r"\bdes\b", "DES"),
        (r"\b3des\b", "3DES"),
        (r"\bmd5\b", "MD5"),
        (r"\bsha1\b", "SHA-1"),
        (r"diffie-hellman-group1", "DH-Group1"),
        (r"diffie-hellman-group2\b", "DH-Group2"),
    ]
    matched = []
    algos_found = set()
    for line in lines:
        stripped = line.strip().lower()
        # Skip comment lines
        if stripped.startswith(("!", "#", "/*")):
            continue
        for pat, name in weak_patterns:
            if re.search(pat, stripped):
                algos_found.add(name)
                matched.append(line.strip())
                break

    if algos_found:
        return [SecurityFinding(
            check_id="SEC-CRYPTO-WEAK",
            severity="high",
            title=f"Weak cryptographic algorithms detected: {', '.join(sorted(algos_found))}",
            description="Weak or deprecated cryptographic algorithms are in use, which may be vulnerable to known attacks.",
            remediation="Migrate to strong algorithms: AES-256 for encryption, SHA-256+ for hashing, DH Group 14+ for key exchange.",
            matched_lines=matched[:10],  # Limit to first 10
        )]
    return []


def _check_cleartext_passwords(lines: list[str]) -> list[SecurityFinding]:
    matched = []
    for line in lines:
        stripped = line.strip()
        # IOS: "password 0 ..." or "enable password ..."
        if re.match(r"(enable\s+)?password\s+0\s+", stripped):
            matched.append(stripped)
        # "password" followed by a clear string (no "7" or "5" hash type)
        if re.match(r"username\s+\S+\s+password\s+0\s+", stripped):
            matched.append(stripped)

    if matched:
        return [SecurityFinding(
            check_id="SEC-CLEARTEXT-PASS",
            severity="critical",
            title="Cleartext passwords found in configuration",
            description="Passwords stored in cleartext can be read by anyone with access to the configuration file.",
            remediation="Use password encryption (e.g., 'service password-encryption' for IOS) and replace cleartext passwords with hashed versions.",
            matched_lines=matched,
        )]
    return []


# ── IOS-specific checks ──────────────────────────────────────────


def _check_ios_telnet(lines: list[str]) -> list[SecurityFinding]:
    matched = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"transport input.*\btelnet\b", stripped):
            matched.append(stripped)
    if matched:
        return [SecurityFinding(
            check_id="SEC-IOS-TELNET",
            severity="high",
            title="Telnet enabled on VTY lines",
            description="Telnet transmits credentials in cleartext, allowing network eavesdropping attacks.",
            remediation="Replace 'transport input telnet' with 'transport input ssh' on all VTY lines.",
            matched_lines=matched,
        )]
    return []


def _check_ios_ssh_v1(lines: list[str]) -> list[SecurityFinding]:
    for line in lines:
        if re.match(r"ip ssh version 1", line.strip()):
            return [SecurityFinding(
                check_id="SEC-IOS-SSHV1",
                severity="high",
                title="SSH version 1 enabled",
                description="SSH v1 has known cryptographic weaknesses and should not be used.",
                remediation="Configure 'ip ssh version 2' to enforce SSHv2 only.",
                matched_lines=[line.strip()],
            )]
    return []


def _check_ios_no_aaa(lines: list[str]) -> list[SecurityFinding]:
    text = "\n".join(lines)
    if not re.search(r"aaa new-model", text):
        return [SecurityFinding(
            check_id="SEC-IOS-NO-AAA",
            severity="high",
            title="AAA not enabled",
            description="Without AAA (Authentication, Authorization, Accounting), the device lacks centralized access control and audit logging.",
            remediation="Enable 'aaa new-model' and configure appropriate authentication methods.",
            matched_lines=[],
        )]
    return []


def _check_ios_http_server(lines: list[str]) -> list[SecurityFinding]:
    matched = []
    for line in lines:
        stripped = line.strip()
        if stripped == "ip http server":
            matched.append(stripped)
    if matched:
        return [SecurityFinding(
            check_id="SEC-IOS-HTTP",
            severity="medium",
            title="HTTP management server enabled",
            description="HTTP management transmits credentials in cleartext. Use HTTPS instead.",
            remediation="Disable 'ip http server' and enable 'ip http secure-server' for HTTPS management.",
            matched_lines=matched,
        )]
    return []


# ── FortiOS-specific checks ──────────────────────────────────────


def _check_forti_admin_http(lines: list[str]) -> list[SecurityFinding]:
    matched = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"set admin-https-redirect\s+disable", stripped, re.IGNORECASE):
            matched.append(stripped)
        if re.match(r"set admin-port\s+80", stripped):
            matched.append(stripped)
    if matched:
        return [SecurityFinding(
            check_id="SEC-FORTI-HTTP-ADMIN",
            severity="medium",
            title="FortiGate HTTP admin access not redirected to HTTPS",
            description="Administrative HTTP access without HTTPS redirect exposes credentials.",
            remediation="Enable 'set admin-https-redirect enable' under config system global.",
            matched_lines=matched,
        )]
    return []
