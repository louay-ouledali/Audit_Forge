"""Benchmark classification engine.

Classifies CIS benchmarks into a hierarchical taxonomy:
  Category → Vendor/Platform → Product Line → Individual Benchmarks

The classifier uses the benchmark name, platform, and platform_family fields
to determine placement. It's designed to handle the naming patterns of CIS
benchmark PDFs after Phase 1 parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field  # UNUSED: 'field' — safe to remove


# ═══════════════════════════════════════════════════════════════════════════════
#  Taxonomy definitions
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ClassificationResult:
    category: str          # e.g. "Operating Systems"
    category_icon: str     # e.g. "monitor"
    vendor: str            # e.g. "Microsoft Windows"
    vendor_icon: str       # e.g. "windows"
    product_line: str      # e.g. "Windows 11"
    product_line_icon: str # e.g. "laptop"


# Each rule: (name_regex, platform_family_match, category, cat_icon, vendor, vendor_icon, product_line, product_icon)
# First match wins. Order from most specific to least specific.
CLASSIFICATION_RULES: list[tuple[str, str | None, str, str, str, str, str, str]] = [
    # ── Operating Systems: Windows Desktop ──
    (r"Windows 11 Enterprise", None, "Operating Systems", "monitor", "Microsoft Windows", "windows", "Windows 11 Enterprise", "laptop"),
    (r"Windows 11 Stand", None, "Operating Systems", "monitor", "Microsoft Windows", "windows", "Windows 11 Standalone", "laptop"),
    (r"Windows 11(?! S)", None, "Operating Systems", "monitor", "Microsoft Windows", "windows", "Windows 11", "laptop"),
    (r"Windows 10 Enterprise", None, "Operating Systems", "monitor", "Microsoft Windows", "windows", "Windows 10 Enterprise", "laptop"),
    (r"Windows 10", None, "Operating Systems", "monitor", "Microsoft Windows", "windows", "Windows 10", "laptop"),

    # ── Operating Systems: Windows Server ──
    (r"Windows Server 2025", None, "Operating Systems", "monitor", "Microsoft Windows", "windows", "Windows Server 2025", "server"),
    (r"Windows Server 2022", None, "Operating Systems", "monitor", "Microsoft Windows", "windows", "Windows Server 2022", "server"),
    (r"Windows Server 2019", None, "Operating Systems", "monitor", "Microsoft Windows", "windows", "Windows Server 2019", "server"),
    (r"Windows Server 2016", None, "Operating Systems", "monitor", "Microsoft Windows", "windows", "Windows Server 2016", "server"),
    (r"Windows Server 2012", None, "Operating Systems", "monitor", "Microsoft Windows", "windows", "Windows Server 2012", "server"),
    (r"Windows Server", None, "Operating Systems", "monitor", "Microsoft Windows", "windows", "Windows Server", "server"),

    # ── Operating Systems: Linux ──
    (r"Red Hat Enterprise Linux|RHEL", None, "Operating Systems", "monitor", "Linux", "linux", "Red Hat Enterprise Linux", "redhat"),
    (r"Ubuntu", None, "Operating Systems", "monitor", "Linux", "linux", "Ubuntu", "ubuntu"),
    (r"Debian", None, "Operating Systems", "monitor", "Linux", "linux", "Debian", "debian"),
    (r"AlmaLinux", None, "Operating Systems", "monitor", "Linux", "linux", "AlmaLinux", "almalinux"),
    (r"Rocky Linux", None, "Operating Systems", "monitor", "Linux", "linux", "Rocky Linux", "rocky"),
    (r"Oracle Linux", None, "Operating Systems", "monitor", "Linux", "linux", "Oracle Linux", "oracle"),
    (r"Amazon Linux", None, "Operating Systems", "monitor", "Linux", "linux", "Amazon Linux", "aws"),
    (r"SUSE|SLES", None, "Operating Systems", "monitor", "Linux", "linux", "SUSE Linux", "suse"),
    (r"CentOS", None, "Operating Systems", "monitor", "Linux", "linux", "CentOS", "centos"),

    # ── Operating Systems: macOS / Unix ──
    (r"macOS|Apple macOS", None, "Operating Systems", "monitor", "Apple", "apple", "macOS", "apple"),
    (r"FreeBSD", None, "Operating Systems", "monitor", "Unix", "unix", "FreeBSD", "freebsd"),
    (r"Solaris", None, "Operating Systems", "monitor", "Oracle", "oracle", "Oracle Solaris", "sun"),
    (r"AIX", None, "Operating Systems", "monitor", "IBM", "ibm", "IBM AIX", "ibm"),

    # ── Operating Systems: VMware ──
    (r"VMware ESXi", None, "Operating Systems", "monitor", "VMware", "vmware", "VMware ESXi", "vmware"),

    # ── Server Software: Databases ──
    (r"Microsoft SQL Server", None, "Server Software", "server", "Microsoft", "windows", "Microsoft SQL Server", "database"),
    (r"PostgreSQL", None, "Server Software", "server", "PostgreSQL", "postgresql", "PostgreSQL", "database"),
    (r"Oracle MySQL|MySQL Community|MySQL Enterprise", None, "Server Software", "server", "Oracle", "oracle", "MySQL", "database"),
    (r"Oracle Database", None, "Server Software", "server", "Oracle", "oracle", "Oracle Database", "database"),
    (r"MongoDB", None, "Server Software", "server", "MongoDB", "mongodb", "MongoDB", "database"),
    (r"MariaDB", None, "Server Software", "server", "MariaDB", "mariadb", "MariaDB", "database"),
    (r"IBM Db2|IBM DB2", None, "Server Software", "server", "IBM", "ibm", "IBM Db2", "database"),
    (r"Apache Cassandra", None, "Server Software", "server", "Apache", "apache", "Apache Cassandra", "database"),
    (r"SingleStore", None, "Server Software", "server", "SingleStore", "singlestore", "SingleStore", "database"),
    (r"YugabyteDB", None, "Server Software", "server", "YugabyteDB", "yugabyte", "YugabyteDB", "database"),
    (r"Snowflake", None, "Server Software", "server", "Snowflake", "snowflake", "Snowflake", "database"),

    # ── Server Software: Web Servers ──
    (r"NGINX", None, "Server Software", "server", "NGINX", "nginx", "NGINX", "globe"),
    (r"Apache HTTP Server", None, "Server Software", "server", "Apache", "apache", "Apache HTTP Server", "globe"),
    (r"Apache Tomcat", None, "Server Software", "server", "Apache", "apache", "Apache Tomcat", "globe"),
    (r"Microsoft IIS", None, "Server Software", "server", "Microsoft", "windows", "Microsoft IIS", "globe"),
    (r"IBM WebSphere", None, "Server Software", "server", "IBM", "ibm", "IBM WebSphere", "globe"),

    # ── Server Software: DNS ──
    (r"BIND DNS", None, "Server Software", "server", "ISC", "dns", "BIND DNS Server", "globe"),

    # ── Server Software: Containers / Virtualization ──
    (r"Docker", None, "Server Software", "server", "Docker", "docker", "Docker", "container"),
    (r"Kubernetes Benchmark", None, "Server Software", "server", "Kubernetes", "kubernetes", "Kubernetes", "container"),
    (r"EKS", None, "Server Software", "server", "AWS", "aws", "Amazon EKS", "container"),
    (r"AKS", None, "Server Software", "server", "Microsoft", "windows", "Azure AKS", "container"),
    (r"GKE", None, "Server Software", "server", "Google", "google", "Google GKE", "container"),
    (r"OpenShift", None, "Server Software", "server", "Red Hat", "redhat", "OpenShift", "container"),
    (r"VMware vSphere", None, "Server Software", "server", "VMware", "vmware", "VMware vSphere", "vmware"),

    # ── Server Software: Collaboration ──
    (r"SharePoint", None, "Server Software", "server", "Microsoft", "windows", "Microsoft SharePoint", "collaboration"),
    (r"Exchange Server", None, "Server Software", "server", "Microsoft", "windows", "Microsoft Exchange Server", "email"),

    # ── Network Devices ──
    (r"Cisco ASA", None, "Network Devices", "network", "Cisco", "cisco", "Cisco ASA Firewall", "firewall"),
    (r"Cisco Firepower", None, "Network Devices", "network", "Cisco", "cisco", "Cisco Firepower", "firewall"),
    (r"Cisco IOS XE", None, "Network Devices", "network", "Cisco", "cisco", "Cisco IOS XE", "router"),
    (r"Cisco IOS XR", None, "Network Devices", "network", "Cisco", "cisco", "Cisco IOS XR", "router"),
    (r"Cisco NX-OS|Cisco NX OS", None, "Network Devices", "network", "Cisco", "cisco", "Cisco NX-OS", "switch"),
    (r"Cisco Firewall", None, "Network Devices", "network", "Cisco", "cisco", "Cisco Firewall", "firewall"),
    (r"Cisco", None, "Network Devices", "network", "Cisco", "cisco", "Cisco", "network"),
    (r"Palo Alto Firewall 11", None, "Network Devices", "network", "Palo Alto Networks", "paloalto", "Palo Alto Firewall 11", "firewall"),
    (r"Palo Alto Firewall 10", None, "Network Devices", "network", "Palo Alto Networks", "paloalto", "Palo Alto Firewall 10", "firewall"),
    (r"Palo Alto", None, "Network Devices", "network", "Palo Alto Networks", "paloalto", "Palo Alto Firewall", "firewall"),
    (r"FortiGate|Fortigate", None, "Network Devices", "network", "Fortinet", "fortinet", "FortiGate", "firewall"),
    (r"Check Point", None, "Network Devices", "network", "Check Point", "checkpoint", "Check Point Firewall", "firewall"),
    (r"Juniper", None, "Network Devices", "network", "Juniper", "juniper", "Juniper", "router"),
    (r"pfSense", None, "Network Devices", "network", "Netgate", "netgate", "pfSense", "firewall"),
    (r"Sophos", None, "Network Devices", "network", "Sophos", "sophos", "Sophos Firewall", "firewall"),
    (r"F5 Networks|F5", None, "Network Devices", "network", "F5", "f5", "F5 Networks", "loadbalancer"),
    (r"HPE Aruba|Aruba", None, "Network Devices", "network", "HPE Aruba", "aruba", "Aruba Switch", "switch"),
    (r"ExtremeNetworks|Extreme", None, "Network Devices", "network", "Extreme Networks", "extreme", "Extreme SLX-OS", "switch"),

    # ── Cloud Providers ──
    (r"Microsoft Azure", None, "Cloud Providers", "cloud", "Microsoft", "windows", "Microsoft Azure", "azure"),
    (r"Amazon Web Services|AWS Foundations", None, "Cloud Providers", "cloud", "Amazon", "aws", "AWS", "aws"),
    (r"Google Cloud|GCP", None, "Cloud Providers", "cloud", "Google", "google", "Google Cloud Platform", "gcp"),
    (r"Oracle Cloud", None, "Cloud Providers", "cloud", "Oracle", "oracle", "Oracle Cloud", "oracle"),
    (r"IBM Cloud", None, "Cloud Providers", "cloud", "IBM", "ibm", "IBM Cloud", "ibm"),
    (r"Alibaba Cloud", None, "Cloud Providers", "cloud", "Alibaba", "alibaba", "Alibaba Cloud", "alibaba"),
    (r"DigitalOcean", None, "Cloud Providers", "cloud", "DigitalOcean", "digitalocean", "DigitalOcean", "digitalocean"),
    (r"Tencent Cloud", None, "Cloud Providers", "cloud", "Tencent", "tencent", "Tencent Cloud", "tencent"),

    # ── Cloud Services ──
    (r"Microsoft 365", None, "Cloud Providers", "cloud", "Microsoft", "windows", "Microsoft 365", "m365"),
    (r"Google Workspace", None, "Cloud Providers", "cloud", "Google", "google", "Google Workspace", "google"),
    (r"Dynamics 365", None, "Cloud Providers", "cloud", "Microsoft", "windows", "Dynamics 365", "dynamics"),

    # ── Desktop Software ──
    (r"Google Chrome", None, "Desktop Software", "app-window", "Google", "google", "Google Chrome", "chrome"),
    (r"Mozilla Firefox", None, "Desktop Software", "app-window", "Mozilla", "firefox", "Mozilla Firefox", "firefox"),
    (r"Microsoft Office", None, "Desktop Software", "app-window", "Microsoft", "windows", "Microsoft Office", "office"),
    (r"Safari", None, "Desktop Software", "app-window", "Apple", "apple", "Safari", "safari"),
    (r"Visual Studio Code", None, "Desktop Software", "app-window", "Microsoft", "windows", "VS Code", "vscode"),

    # ── DevSecOps ──
    (r"GitHub", None, "DevSecOps", "git-branch", "GitHub", "github", "GitHub", "github"),
    (r"GitLab", None, "DevSecOps", "git-branch", "GitLab", "gitlab", "GitLab", "gitlab"),

    # ── Mobile Devices ──
    (r"Apple iOS|iPadOS", None, "Mobile Devices", "smartphone", "Apple", "apple", "Apple iOS/iPadOS", "apple"),
    (r"Android", None, "Mobile Devices", "smartphone", "Google", "google", "Android", "android"),
]

# Fallback classification by platform_family when name doesn't match
FAMILY_FALLBACK: dict[str, tuple[str, str, str, str]] = {
    "windows": ("Operating Systems", "monitor", "Microsoft Windows", "windows"),
    "linux": ("Operating Systems", "monitor", "Linux", "linux"),
    "network": ("Network Devices", "network", "Other Network", "network"),
    "database": ("Server Software", "server", "Other Database", "database"),
    "other": ("Other", "box", "Other", "box"),
}


def classify_benchmark(name: str, platform: str, platform_family: str) -> ClassificationResult:
    """Classify a single benchmark by its name and platform metadata.
    
    Tries pattern matching on the benchmark name first, then falls back
    to the platform_family field.
    """
    for pattern, family_match, cat, cat_icon, vendor, vendor_icon, product, product_icon in CLASSIFICATION_RULES:
        if family_match and platform_family != family_match:
            continue
        if re.search(pattern, name, re.IGNORECASE):
            return ClassificationResult(
                category=cat,
                category_icon=cat_icon,
                vendor=vendor,
                vendor_icon=vendor_icon,
                product_line=product,
                product_line_icon=product_icon,
            )

    # Fallback
    fb = FAMILY_FALLBACK.get(platform_family, FAMILY_FALLBACK["other"])
    return ClassificationResult(
        category=fb[0],
        category_icon=fb[1],
        vendor=fb[2],
        vendor_icon=fb[3],
        product_line=name.replace("CIS ", "").replace(" Benchmark", ""),
        product_line_icon="box",
    )


def build_catalog(benchmarks: list[dict]) -> dict:
    """Build the full hierarchical catalog from a list of benchmark dicts.

    Input: list of dicts with keys: id, name, version, platform, platform_family,
           total_rules, phase1_status, phase2_status, verification_status, is_ready,
           source, import_date, framework, group_id, is_baseline

    Output: nested dict structure for the frontend:
    {
      "categories": [
        {
          "name": "Operating Systems",
          "icon": "monitor",
          "benchmark_count": 12,
          "vendors": [
            {
              "name": "Microsoft Windows",
              "icon": "windows",
              "benchmark_count": 7,
              "product_lines": [
                {
                  "name": "Windows Server 2022",
                  "icon": "server",
                  "version_count": 2,
                  "benchmarks": [ { ...benchmark data... } ]
                }
              ]
            }
          ]
        }
      ]
    }
    """
    # Phase 1: Classify each benchmark
    classified: list[tuple[ClassificationResult, dict]] = []
    for b in benchmarks:
        cl = classify_benchmark(b["name"], b.get("platform", ""), b.get("platform_family", ""))
        classified.append((cl, b))

    # Phase 2: Build tree
    cat_tree: dict[str, dict] = {}  # category_name -> {icon, vendors: {vendor_name -> {icon, products: {line -> [benchmarks]}}}}

    for cl, b in classified:
        if cl.category not in cat_tree:
            cat_tree[cl.category] = {"icon": cl.category_icon, "vendors": {}}

        vendors = cat_tree[cl.category]["vendors"]
        if cl.vendor not in vendors:
            vendors[cl.vendor] = {"icon": cl.vendor_icon, "products": {}}

        products = vendors[cl.vendor]["products"]
        if cl.product_line not in products:
            products[cl.product_line] = {"icon": cl.product_line_icon, "benchmarks": []}

        products[cl.product_line]["benchmarks"].append(b)

    # Phase 3: Convert to sorted list structure
    # Category display order
    CATEGORY_ORDER = [
        "Operating Systems", "Server Software", "Network Devices",
        "Cloud Providers", "Desktop Software", "DevSecOps", "Mobile Devices", "Other",
    ]

    categories: list[dict] = []
    for cat_name in CATEGORY_ORDER:
        if cat_name not in cat_tree:
            continue
        cat_data = cat_tree[cat_name]
        vendors_list: list[dict] = []
        total_benchmarks = 0

        for vendor_name in sorted(cat_data["vendors"].keys()):
            vendor_data = cat_data["vendors"][vendor_name]
            products_list: list[dict] = []
            vendor_benchmark_count = 0

            for product_name in sorted(vendor_data["products"].keys()):
                product_data = vendor_data["products"][product_name]
                # Sort benchmarks by version descending
                sorted_benchmarks = sorted(
                    product_data["benchmarks"],
                    key=lambda x: x.get("version", ""),
                    reverse=True,
                )
                # Collect unique group_ids to count distinct versions
                group_ids = {b.get("group_id") for b in sorted_benchmarks if b.get("group_id")}
                version_count = len(group_ids) if group_ids else len(sorted_benchmarks)
                # Collect unique frameworks present
                frameworks = sorted({b.get("framework", "cis") for b in sorted_benchmarks})
                products_list.append({
                    "name": product_name,
                    "icon": product_data["icon"],
                    "version_count": version_count,
                    "frameworks": frameworks,
                    "benchmarks": sorted_benchmarks,
                })
                vendor_benchmark_count += len(sorted_benchmarks)

            vendors_list.append({
                "name": vendor_name,
                "icon": vendor_data["icon"],
                "benchmark_count": vendor_benchmark_count,
                "product_lines": products_list,
            })
            total_benchmarks += vendor_benchmark_count

        categories.append({
            "name": cat_name,
            "icon": cat_data["icon"],
            "benchmark_count": total_benchmarks,
            "vendors": vendors_list,
        })

    # Add any categories not in CATEGORY_ORDER
    for cat_name, cat_data in cat_tree.items():
        if cat_name not in CATEGORY_ORDER:
            vendors_list = []
            total = 0
            for vendor_name in sorted(cat_data["vendors"].keys()):
                vendor_data = cat_data["vendors"][vendor_name]
                products_list = []
                vc = 0
                for product_name in sorted(vendor_data["products"].keys()):
                    product_data = vendor_data["products"][product_name]
                    sorted_b = sorted(product_data["benchmarks"], key=lambda x: x.get("version", ""), reverse=True)
                    grp_ids = {b.get("group_id") for b in sorted_b if b.get("group_id")}
                    products_list.append({
                        "name": product_name,
                        "icon": product_data["icon"],
                        "version_count": len(grp_ids) if grp_ids else len(sorted_b),
                        "frameworks": sorted({b.get("framework", "cis") for b in sorted_b}),
                        "benchmarks": sorted_b,
                    })
                    vc += len(product_data["benchmarks"])
                vendors_list.append({
                    "name": vendor_name,
                    "icon": vendor_data["icon"],
                    "benchmark_count": vc,
                    "product_lines": products_list,
                })
                total += vc
            categories.append({
                "name": cat_name,
                "icon": cat_data["icon"],
                "benchmark_count": total,
                "vendors": vendors_list,
            })

    return {"categories": categories}
