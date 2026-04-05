"""Fix command quality issues across all preloaded benchmark packs.

Applies targeted fixes for:
1. Oracle 23ai: Strip shell pipes from SQL commands (11 rules)
2. Tomcat 10.1: Add auto-discovery preamble for $CATALINA_HOME (58 rules)
3. Apache HTTP: Add auto-discovery preamble for $APACHE_PREFIX (10 rules)
4. BIND DNS: Add auto-discovery preamble for $BIND_HOME (5 rules)
5. Check Point: Add auto-discovery preamble for $FWDIR (1 rule)
6. Juniper: Replace echo stubs on CLI transport with Manual assessment (3 rules)
7. SharePoint: Add PSSnapin preamble (rules missing it)
8. MSSQL 2019/2017: Fix ==sa -> !=sa expression inversion
9. MongoDB 3.2: Fix version expression contains:4.4 -> contains:3.2
10. Cassandra: Fix grep --- syntax
11. ESXi 7/8: Fix unbound $VM/$vmhost in PowerShell rules
"""

import json
import os
import re
import sys

PACKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "backend", "preloaded")


def load_pack(filename: str) -> dict:
    path = os.path.join(PACKS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_pack(filename: str, data: dict) -> None:
    path = os.path.join(PACKS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def fix_oracle_23ai() -> int:
    """Strip shell pipes from SQL-transport commands in Oracle 23ai."""
    filename = None
    for f in os.listdir(PACKS_DIR):
        if "oracle_database_23ai" in f and f.endswith(".auditforge.json"):
            filename = f
            break
    if not filename:
        print("  SKIP: Oracle 23ai pack not found")
        return 0

    data = load_pack(filename)
    fixed = 0
    shell_pipe_re = re.compile(r'\s*\|\s*(?:grep|awk|sed|wc|cut|sort|head|tail|tr|uniq)\b.*$')

    for rule in data.get("rules", []):
        if rule.get("command_transport") != "sql":
            continue
        cmd = rule.get("audit_command", "")
        if not cmd:
            continue
        if shell_pipe_re.search(cmd):
            # Strip everything from the first shell pipe onward
            # But first, find where the SQL ends (after the last SQL statement)
            cleaned = shell_pipe_re.sub("", cmd).rstrip().rstrip(";").rstrip('"').rstrip("'").strip()
            if cleaned and cleaned != cmd:
                rule["audit_command"] = cleaned
                fixed += 1
                print(f"  Fixed {rule.get('section_number')}: stripped shell pipe from SQL")

    if fixed:
        save_pack(filename, data)
    return fixed


TOMCAT_PREAMBLE = (
    'CATALINA_HOME=$(ps aux 2>/dev/null | grep -oP \'catalina\\.home=\\K\\S+\' | head -1); '
    '[ -z "$CATALINA_HOME" ] && CATALINA_HOME=$(find /opt /usr/local /var -maxdepth 4 '
    '-name "catalina.sh" -type f 2>/dev/null | head -1 | sed \'s|/bin/catalina.sh||\'); '
    '[ -z "$CATALINA_HOME" ] && CATALINA_HOME="/opt/tomcat"; '
    'CATALINA_BASE=${CATALINA_BASE:-$CATALINA_HOME}; '
)


def fix_tomcat() -> int:
    """Add auto-discovery preamble for $CATALINA_HOME in Tomcat pack."""
    filename = None
    for f in os.listdir(PACKS_DIR):
        if "tomcat" in f.lower() and f.endswith(".auditforge.json"):
            filename = f
            break
    if not filename:
        print("  SKIP: Tomcat pack not found")
        return 0

    data = load_pack(filename)
    fixed = 0

    for rule in data.get("rules", []):
        cmd = rule.get("audit_command", "")
        if not cmd:
            continue
        if "$CATALINA_HOME" in cmd or "$CATALINA_BASE" in cmd:
            # Don't double-apply
            if "ps aux 2>/dev/null | grep -oP" in cmd:
                continue
            rule["audit_command"] = TOMCAT_PREAMBLE + cmd
            fixed += 1

    if fixed:
        save_pack(filename, data)
    print(f"  Fixed {fixed} Tomcat rules with auto-discovery preamble")
    return fixed


APACHE_PREAMBLE = (
    'APACHE_PREFIX=$(apachectl -V 2>/dev/null | grep -oP \'HTTPD_ROOT="\\K[^"]+\'); '
    '[ -z "$APACHE_PREFIX" ] && APACHE_PREFIX=$(httpd -V 2>/dev/null | grep -oP \'HTTPD_ROOT="\\K[^"]+\'); '
    '[ -z "$APACHE_PREFIX" ] && APACHE_PREFIX="/etc/httpd"; '
)


def fix_apache_http() -> int:
    """Add auto-discovery preamble for $APACHE_PREFIX in Apache HTTP pack."""
    filename = None
    for f in os.listdir(PACKS_DIR):
        if "apache_http" in f.lower() and f.endswith(".auditforge.json"):
            filename = f
            break
    if not filename:
        print("  SKIP: Apache HTTP pack not found")
        return 0

    data = load_pack(filename)
    fixed = 0

    for rule in data.get("rules", []):
        cmd = rule.get("audit_command", "")
        if not cmd:
            continue
        if "$APACHE_PREFIX" in cmd:
            if "apachectl -V 2>/dev/null" in cmd:
                continue
            rule["audit_command"] = APACHE_PREAMBLE + cmd
            fixed += 1

    if fixed:
        save_pack(filename, data)
    print(f"  Fixed {fixed} Apache HTTP rules with auto-discovery preamble")
    return fixed


BIND_PREAMBLE = (
    'BIND_HOME=$(named-checkconf -t / -p 2>/dev/null | grep -oP \'directory "\\K[^"]+\' || echo "/etc/bind"); '
    'RUNDIR="/run/named"; DYNDIR="$BIND_HOME/dynamic"; SLAVEDIR="$BIND_HOME/slaves"; '
    'DATADIR="$BIND_HOME/data"; LOGDIR="/var/log/named"; '
)


def fix_bind_dns() -> int:
    """Add auto-discovery preamble for $BIND_HOME etc. in BIND DNS pack."""
    filename = None
    for f in os.listdir(PACKS_DIR):
        if "bind_dns" in f.lower() and f.endswith(".auditforge.json"):
            filename = f
            break
    if not filename:
        print("  SKIP: BIND DNS pack not found")
        return 0

    data = load_pack(filename)
    fixed = 0
    bind_vars = {"$BIND_HOME", "$RUNDIR", "$DYNDIR", "$SLAVEDIR", "$DATADIR", "$LOGDIR"}

    for rule in data.get("rules", []):
        cmd = rule.get("audit_command", "")
        if not cmd:
            continue
        if any(v in cmd for v in bind_vars):
            if "named-checkconf" in cmd:
                continue
            rule["audit_command"] = BIND_PREAMBLE + cmd
            fixed += 1

    if fixed:
        save_pack(filename, data)
    print(f"  Fixed {fixed} BIND DNS rules with auto-discovery preamble")
    return fixed


def fix_checkpoint() -> int:
    """Add auto-discovery preamble for $FWDIR in Check Point pack."""
    filename = None
    for f in os.listdir(PACKS_DIR):
        if "check_point" in f.lower() and f.endswith(".auditforge.json"):
            filename = f
            break
    if not filename:
        print("  SKIP: Check Point pack not found")
        return 0

    data = load_pack(filename)
    fixed = 0

    for rule in data.get("rules", []):
        cmd = rule.get("audit_command", "")
        if not cmd:
            continue
        if "$FWDIR" in cmd:
            if "source /etc/profile" in cmd:
                continue
            rule["audit_command"] = (
                'source /etc/profile.d/CP.sh 2>/dev/null; '
                'FWDIR=${FWDIR:-/opt/CPshrd-R81/fw1}; '
                + cmd
            )
            fixed += 1

    if fixed:
        save_pack(filename, data)
    print(f"  Fixed {fixed} Check Point rule(s) with $FWDIR preamble")
    return fixed


def fix_juniper() -> int:
    """Replace echo stubs on CLI transport with Manual assessment in Juniper."""
    filename = None
    for f in os.listdir(PACKS_DIR):
        if "juniper" in f.lower() and f.endswith(".auditforge.json"):
            filename = f
            break
    if not filename:
        print("  SKIP: Juniper pack not found")
        return 0

    data = load_pack(filename)
    fixed = 0

    for rule in data.get("rules", []):
        cmd = rule.get("audit_command", "")
        transport = rule.get("command_transport", "")
        if transport == "cli" and cmd.strip().startswith("echo "):
            rule["audit_command"] = ""
            rule["expected_output_expression"] = ""
            rule["assessment_type"] = "Manual"
            fixed += 1
            print(f"  Fixed {rule.get('section_number')}: echo stub -> Manual assessment")

    if fixed:
        save_pack(filename, data)
    return fixed


SP_SNAPIN = 'if (-not (Get-PSSnapin Microsoft.SharePoint.PowerShell -EA SilentlyContinue)) { Add-PSSnapin Microsoft.SharePoint.PowerShell }; '


def fix_sharepoint() -> int:
    """Add PSSnapin preamble to SharePoint commands that need it."""
    filename = None
    for f in os.listdir(PACKS_DIR):
        if "sharepoint" in f.lower() and f.endswith(".auditforge.json"):
            filename = f
            break
    if not filename:
        print("  SKIP: SharePoint pack not found")
        return 0

    data = load_pack(filename)
    fixed = 0

    for rule in data.get("rules", []):
        cmd = rule.get("audit_command", "")
        if not cmd:
            continue
        if re.search(r'(?i)\b(?:Get|Set|New|Remove|Mount|Dismount)-SP[A-Z]', cmd):
            if "Add-PSSnapin" not in cmd:
                rule["audit_command"] = SP_SNAPIN + cmd
                fixed += 1

    if fixed:
        save_pack(filename, data)
    print(f"  Fixed {fixed} SharePoint rules with PSSnapin preamble")
    return fixed


def fix_mssql_sa_inversion() -> int:
    """Fix ==sa -> !=sa expression in MSSQL 2019 and 2017."""
    fixed = 0
    for f in os.listdir(PACKS_DIR):
        if ("sql_server_2019" in f.lower() or "sql_server_2017" in f.lower()) \
                and f.endswith(".auditforge.json"):
            data = load_pack(f)
            for rule in data.get("rules", []):
                expr = rule.get("expected_output_expression", "")
                title = rule.get("title", "").lower()
                if expr == "==sa" and "renamed" in title:
                    rule["expected_output_expression"] = "!=sa"
                    fixed += 1
                    print(f"  Fixed {rule.get('section_number')} in {f}: ==sa -> !=sa")
            save_pack(f, data)
    return fixed


def fix_mongodb_version() -> int:
    """Fix contains:4.4 -> contains:3.2 in MongoDB 3.2 pack."""
    filename = None
    for f in os.listdir(PACKS_DIR):
        if "mongodb_3_2" in f.lower() and f.endswith(".auditforge.json"):
            filename = f
            break
    if not filename:
        print("  SKIP: MongoDB 3.2 pack not found")
        return 0

    data = load_pack(filename)
    fixed = 0

    for rule in data.get("rules", []):
        expr = rule.get("expected_output_expression", "")
        if expr == "contains:4.4":
            rule["expected_output_expression"] = "contains:3.2"
            fixed += 1
            print(f"  Fixed {rule.get('section_number')}: contains:4.4 -> contains:3.2")

    if fixed:
        save_pack(filename, data)
    return fixed


def fix_cassandra_grep() -> int:
    """Fix grep --- syntax in Cassandra pack."""
    filename = None
    for f in os.listdir(PACKS_DIR):
        if "cassandra" in f.lower() and f.endswith(".auditforge.json"):
            filename = f
            break
    if not filename:
        print("  SKIP: Cassandra pack not found")
        return 0

    data = load_pack(filename)
    fixed = 0

    for rule in data.get("rules", []):
        cmd = rule.get("audit_command", "")
        if 'grep -v "---"' in cmd or "grep -v '---'" in cmd or "grep --- " in cmd:
            # Add -- end-of-options separator
            new_cmd = cmd.replace('grep -v "---"', 'grep -v -- "---"')
            new_cmd = new_cmd.replace("grep -v '---'", "grep -v -- '---'")
            new_cmd = new_cmd.replace("grep --- ", "grep -- '---' ")
            if new_cmd != cmd:
                rule["audit_command"] = new_cmd
                fixed += 1
                print(f"  Fixed {rule.get('section_number')}: grep --- -> grep -- '---'")

    if fixed:
        save_pack(filename, data)
    return fixed


def fix_esxi_unbound_vm() -> int:
    """Fix unbound $VM/$vmhost in ESXi PowerShell rules."""
    fixed = 0
    for f in os.listdir(PACKS_DIR):
        if "esxi" not in f.lower() or not f.endswith(".auditforge.json"):
            continue

        data = load_pack(f)
        pack_fixed = 0

        for rule in data.get("rules", []):
            cmd = rule.get("audit_command", "")
            transport = rule.get("command_transport", "")
            if transport != "powershell":
                continue

            # Fix bare $VM usage (not inside a ForEach or defined as variable)
            if re.search(r'\$VM\b', cmd) and 'ForEach' not in cmd and '$VM =' not in cmd:
                # Replace Get-VM -Name $VM with Get-VM | ForEach-Object pattern
                if 'Get-VM -Name $VM' in cmd:
                    new_cmd = cmd.replace(
                        'Get-VM -Name $VM',
                        'Get-VM | ForEach-Object { $vm = $_; $vm'
                    )
                    # Close the ForEach block
                    if new_cmd.endswith(')'):
                        new_cmd = new_cmd + ' }'
                    else:
                        new_cmd = new_cmd + ' }'
                    rule["audit_command"] = new_cmd
                    pack_fixed += 1
                elif '($VM |' in cmd or '($VM|' in cmd:
                    # Mark as manual - too complex to auto-fix
                    rule["assessment_type"] = "Manual"
                    rule["audit_command"] = ""
                    rule["expected_output_expression"] = ""
                    pack_fixed += 1

            # Fix bare $vmhost usage
            if re.search(r'\$vmhost\b', cmd, re.IGNORECASE) and 'ForEach' not in cmd:
                if '$vmhost =' not in cmd.lower():
                    rule["assessment_type"] = "Manual"
                    rule["audit_command"] = ""
                    rule["expected_output_expression"] = ""
                    pack_fixed += 1

        if pack_fixed:
            save_pack(f, data)
            print(f"  Fixed {pack_fixed} ESXi rules in {f}")
        fixed += pack_fixed

    return fixed


def main():
    print("=" * 60)
    print("AuditForge Command Quality Fixer")
    print("=" * 60)
    print()

    total_fixed = 0

    print("1. Oracle 23ai — strip shell pipes from SQL commands")
    total_fixed += fix_oracle_23ai()
    print()

    print("2. Tomcat 10.1 — add auto-discovery preamble for $CATALINA_HOME")
    total_fixed += fix_tomcat()
    print()

    print("3. Apache HTTP — add auto-discovery preamble for $APACHE_PREFIX")
    total_fixed += fix_apache_http()
    print()

    print("4. BIND DNS — add auto-discovery preamble for $BIND_HOME")
    total_fixed += fix_bind_dns()
    print()

    print("5. Check Point — add preamble for $FWDIR")
    total_fixed += fix_checkpoint()
    print()

    print("6. Juniper — replace echo stubs on CLI transport")
    total_fixed += fix_juniper()
    print()

    print("7. SharePoint — add PSSnapin preamble")
    total_fixed += fix_sharepoint()
    print()

    print("8. MSSQL 2019/2017 — fix ==sa inversion")
    total_fixed += fix_mssql_sa_inversion()
    print()

    print("9. MongoDB 3.2 — fix version expression")
    total_fixed += fix_mongodb_version()
    print()

    print("10. Cassandra — fix grep --- syntax")
    total_fixed += fix_cassandra_grep()
    print()

    print("11. ESXi 7/8 — fix unbound $VM/$vmhost")
    total_fixed += fix_esxi_unbound_vm()
    print()

    print("=" * 60)
    print(f"TOTAL: {total_fixed} rules fixed across all packs")
    print("=" * 60)


if __name__ == "__main__":
    main()
