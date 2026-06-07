"""Import orchestrator — full pipeline for Smart Import.

Coordinates all steps of the import flow:
1. Detect file format (CSV / HTML / JSON / ZIP)
2. Parse findings using the appropriate parser
3. Detect platform information
4. Resolve or reconstruct benchmark
5. Resolve or create target
6. Create scan + findings
7. (Optional) Run false-positive detection
8. Create ImportRecord for audit trail
9. Return ImportResult with full statistics
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.importers.base import ImportResult, ParsedFinding, PlatformInfo
from backend.importers.csv_parser import (
    detect_nessus_csv,
    extract_rules_from_findings,
    parse_nessus_csv,
)
from backend.importers.html_parser import detect_nessus_html, parse_nessus_html
from backend.importers.nessus_xml_parser import (
    detect_nessus_xml,
    parse_nessus_xml,
    extract_rules_from_findings as extract_rules_from_nessus_xml,
)
from backend.importers.qualys_parser import (
    detect_qualys_csv,
    detect_qualys_xml,
    parse_qualys_csv,
    parse_qualys_xml,
)
from backend.importers.openvas_parser import detect_openvas_xml, parse_openvas_xml
from backend.importers.stig_parser import (
    detect_stig_xccdf,
    detect_stig_ckl,
    parse_stig_xccdf,
    parse_stig_ckl,
    extract_rules_from_stig,
)
from backend.importers.nist_parser import (
    detect_nist_json,
    detect_nist_csv,
    detect_nist_xml,
    parse_nist_json,
    parse_nist_csv,
    parse_nist_xml,
    extract_rules_from_nist,
)
from backend.importers.iso_parser import (
    detect_iso_json,
    detect_iso_csv,
    parse_iso_json,
    parse_iso_csv,
    extract_rules_from_iso,
)
from backend.importers.xccdf_parser import (
    detect_xccdf,
    parse_xccdf,
    extract_rules_from_xccdf,
)
from backend.importers.benchmark_resolver import resolve_benchmark
from backend.importers.platform_detector import enrich_platform_info
from backend.importers.severity_enricher import enrich_imported_benchmark
from backend.models.benchmark import Benchmark
from backend.models.finding import Finding
from backend.models.rule import Rule
from backend.models.scan import Scan
from backend.models.target import Target

logger = logging.getLogger("auditforge.importers.import_orchestrator")

MAX_OUTPUT_LENGTH = 4000


class ImportOrchestrator:
    """Orchestrates the full Smart Import pipeline."""

    def __init__(self, db: Session):
        self.db = db

    def detect_format(self, content: str, filename: str = "") -> str:
        """Detect the format of the uploaded file content.

        Returns one of: 'nessus_csv', 'nessus_html', 'nessus_xml',
                        'qualys_csv', 'qualys_xml', 'openvas_xml',
                        'stig_xccdf', 'stig_ckl', 'nist_json', 'nist_csv',
                        'nist_xml', 'iso_json', 'iso_csv', 'xccdf',
                        'auditforge_json', 'auditforge_zip', 'unknown'
        """
        if not content:
            return "unknown"

        stripped = content.strip()
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        # Check for Nessus CSV (Plugin ID + Description headers)
        if detect_nessus_csv(content):
            return "nessus_csv"

        # Check for .nessus XML (NessusClientData_v2)
        if detect_nessus_xml(content) or ext == "nessus":
            return "nessus_xml"

        # Check for Nessus HTML (characteristic CSS/structure)
        if detect_nessus_html(content):
            return "nessus_html"

        # Check for Qualys CSV
        if detect_qualys_csv(content):
            return "qualys_csv"

        # Check for Qualys XML
        if detect_qualys_xml(content):
            return "qualys_xml"

        # Check for OpenVAS/GVM XML
        if detect_openvas_xml(content):
            return "openvas_xml"

        # Check for DISA STIG CKL (before generic XCCDF)
        if detect_stig_ckl(content):
            return "stig_ckl"

        # Check for DISA STIG XCCDF (before generic XCCDF)
        if detect_stig_xccdf(content):
            return "stig_xccdf"

        # Check for NIST 800-53 XML
        if detect_nist_xml(content):
            return "nist_xml"

        # Check for generic XCCDF/SCAP (after STIG-specific check)
        if detect_xccdf(content):
            return "xccdf"

        # Check for NIST 800-53 JSON (before generic JSON)
        if detect_nist_json(content):
            return "nist_json"

        # Check for ISO 27001 JSON
        if detect_iso_json(content):
            return "iso_json"

        # Check for NIST 800-53 CSV (before generic CSV)
        if detect_nist_csv(content):
            return "nist_csv"

        # Check for ISO 27001 CSV
        if detect_iso_csv(content):
            return "iso_csv"

        # Check for AuditForge JSON
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                data = json.loads(stripped)
                if isinstance(data, list) and data and "rule_id" in data[0]:
                    return "auditforge_json"
                if isinstance(data, dict) and "system_info" in data:
                    return "auditforge_json"
            except (json.JSONDecodeError, TypeError, IndexError):
                pass

        return "unknown"

    def preview(
        self,
        content: str,
        filename: str = "",
        client_id: int | None = None,
    ) -> dict[str, Any]:
        """Preview what an import would produce WITHOUT creating anything.

        Used by the frontend ImportPreviewModal to show auto-detected info.
        """
        fmt = self.detect_format(content, filename)

        if fmt == "nessus_csv":
            findings, platform_info = parse_nessus_csv(content)
            extracted_rules = extract_rules_from_findings(findings)

            # Enrich platform from content if audit filename detection was weak
            platform_info = enrich_platform_info(platform_info, findings, use_ai=False)

            # Count statuses
            counts = _count_statuses(findings)

            # Check if a benchmark already exists
            benchmark_exists = False
            existing_benchmark: Benchmark | None = None
            if platform_info.benchmark_name:
                from backend.importers.benchmark_resolver import _try_exact_match, _try_fuzzy_match
                existing_benchmark = _try_exact_match(platform_info, self.db)
                if not existing_benchmark:
                    existing_benchmark = _try_fuzzy_match(platform_info, self.db)
                benchmark_exists = existing_benchmark is not None

            return {
                "format": fmt,
                "filename": filename,
                "platform": platform_info.platform,
                "platform_family": platform_info.platform_family,
                "os_version": platform_info.os_version,
                "benchmark_name": platform_info.benchmark_name or "Unknown benchmark",
                "benchmark_version": platform_info.benchmark_version or "unknown",
                "benchmark_exists": benchmark_exists,
                "existing_benchmark_id": existing_benchmark.id if existing_benchmark else None,
                "existing_benchmark_name": existing_benchmark.name if existing_benchmark else None,
                "hostname": platform_info.hostname or platform_info.ip_address or "Unknown host",
                "ip_address": platform_info.ip_address,
                "profile_level": platform_info.profile_level,
                "total_findings": len(findings),
                "total_rules": len(extracted_rules),
                "passed": counts.get("PASS", 0),
                "failed": counts.get("FAIL", 0),
                "not_applicable": counts.get("NOT_APPLICABLE", 0),
                "errors": counts.get("ERROR", 0) + counts.get("MANUAL_REVIEW", 0),
                "scheme": platform_info.scheme or "CIS",
                "source_tool": "nessus",
            }

        if fmt == "nessus_html":
            findings, platform_info = parse_nessus_html(content)
            extracted_rules = extract_rules_from_findings(findings)

            # Enrich platform from content if audit filename detection was weak
            platform_info = enrich_platform_info(platform_info, findings, use_ai=False)

            counts = _count_statuses(findings)

            benchmark_exists = False
            existing_benchmark: Benchmark | None = None
            if platform_info.benchmark_name:
                from backend.importers.benchmark_resolver import _try_exact_match, _try_fuzzy_match
                existing_benchmark = _try_exact_match(platform_info, self.db)
                if not existing_benchmark:
                    existing_benchmark = _try_fuzzy_match(platform_info, self.db)
                benchmark_exists = existing_benchmark is not None

            return {
                "format": fmt,
                "filename": filename,
                "platform": platform_info.platform,
                "platform_family": platform_info.platform_family,
                "os_version": platform_info.os_version,
                "benchmark_name": platform_info.benchmark_name or "Unknown benchmark",
                "benchmark_version": platform_info.benchmark_version or "unknown",
                "benchmark_exists": benchmark_exists,
                "existing_benchmark_id": existing_benchmark.id if existing_benchmark else None,
                "existing_benchmark_name": existing_benchmark.name if existing_benchmark else None,
                "hostname": platform_info.hostname or platform_info.ip_address or "Unknown host",
                "ip_address": platform_info.ip_address,
                "profile_level": platform_info.profile_level,
                "total_findings": len(findings),
                "total_rules": len(extracted_rules),
                "passed": counts.get("PASS", 0),
                "failed": counts.get("FAIL", 0),
                "not_applicable": counts.get("NOT_APPLICABLE", 0),
                "errors": counts.get("ERROR", 0) + counts.get("MANUAL_REVIEW", 0),
                "scheme": platform_info.scheme or "CIS",
                "source_tool": "nessus",
            }

        if fmt in ("nessus_xml", "qualys_csv", "qualys_xml", "openvas_xml"):
            # Parse with appropriate parser
            if fmt == "nessus_xml":
                findings, platform_info = parse_nessus_xml(content)
                extracted_rules = extract_rules_from_nessus_xml(findings)
            elif fmt == "qualys_csv":
                findings, platform_info = parse_qualys_csv(content)
                extracted_rules = []
            elif fmt == "qualys_xml":
                findings, platform_info = parse_qualys_xml(content)
                extracted_rules = []
            else:  # openvas_xml
                findings, platform_info = parse_openvas_xml(content)
                extracted_rules = []

            # Enrich platform from content if detection was weak
            platform_info = enrich_platform_info(platform_info, findings, use_ai=False)

            counts = _count_statuses(findings)

            # Check existing benchmark
            benchmark_exists = False
            existing_benchmark: Benchmark | None = None
            if platform_info.benchmark_name:
                from backend.importers.benchmark_resolver import _try_exact_match, _try_fuzzy_match
                existing_benchmark = _try_exact_match(platform_info, self.db)
                if not existing_benchmark:
                    existing_benchmark = _try_fuzzy_match(platform_info, self.db)
                benchmark_exists = existing_benchmark is not None

            source_tool = {
                "nessus_xml": "nessus",
                "qualys_csv": "qualys",
                "qualys_xml": "qualys",
                "openvas_xml": "openvas",
            }.get(fmt, "unknown")

            return {
                "format": fmt,
                "filename": filename,
                "platform": platform_info.platform,
                "platform_family": platform_info.platform_family,
                "os_version": platform_info.os_version,
                "benchmark_name": platform_info.benchmark_name or "Unknown benchmark",
                "benchmark_version": platform_info.benchmark_version or "unknown",
                "benchmark_exists": benchmark_exists,
                "existing_benchmark_id": existing_benchmark.id if existing_benchmark else None,
                "existing_benchmark_name": existing_benchmark.name if existing_benchmark else None,
                "hostname": platform_info.hostname or platform_info.ip_address or "Unknown host",
                "ip_address": platform_info.ip_address,
                "profile_level": platform_info.profile_level,
                "total_findings": len(findings),
                "total_rules": len(extracted_rules),
                "passed": counts.get("PASS", 0),
                "failed": counts.get("FAIL", 0),
                "not_applicable": counts.get("NOT_APPLICABLE", 0),
                "errors": counts.get("ERROR", 0) + counts.get("MANUAL_REVIEW", 0),
                "scheme": platform_info.scheme or "CIS",
                "source_tool": source_tool,
            }

        # Multi-framework preview (STIG, NIST, ISO, XCCDF)
        _framework_formats = {
            "stig_xccdf", "stig_ckl", "nist_json", "nist_csv", "nist_xml",
            "iso_json", "iso_csv", "xccdf",
        }
        if fmt in _framework_formats:
            _parser_map = {
                "stig_xccdf": (parse_stig_xccdf, extract_rules_from_stig, "stig_xccdf"),
                "stig_ckl": (parse_stig_ckl, extract_rules_from_stig, "stig_ckl"),
                "nist_json": (parse_nist_json, extract_rules_from_nist, "nist_oscal"),
                "nist_csv": (parse_nist_csv, extract_rules_from_nist, "nist_csv"),
                "nist_xml": (parse_nist_xml, extract_rules_from_nist, "nist_xml"),
                "iso_json": (parse_iso_json, extract_rules_from_iso, "iso_json"),
                "iso_csv": (parse_iso_csv, extract_rules_from_iso, "iso_csv"),
                "xccdf": (parse_xccdf, extract_rules_from_xccdf, "xccdf"),
            }
            parse_fn, extract_fn, source_tool = _parser_map[fmt]
            findings, platform_info = parse_fn(content)
            extracted_rules = extract_fn(findings)

            counts = _count_statuses(findings)

            benchmark_exists = False
            existing_benchmark: Benchmark | None = None
            if platform_info.benchmark_name:
                from backend.importers.benchmark_resolver import _try_exact_match, _try_fuzzy_match
                existing_benchmark = _try_exact_match(platform_info, self.db)
                if not existing_benchmark:
                    existing_benchmark = _try_fuzzy_match(platform_info, self.db)
                benchmark_exists = existing_benchmark is not None

            return {
                "format": fmt,
                "filename": filename,
                "platform": platform_info.platform,
                "platform_family": platform_info.platform_family,
                "os_version": platform_info.os_version,
                "benchmark_name": platform_info.benchmark_name or "Unknown benchmark",
                "benchmark_version": platform_info.benchmark_version or "unknown",
                "benchmark_exists": benchmark_exists,
                "existing_benchmark_id": existing_benchmark.id if existing_benchmark else None,
                "existing_benchmark_name": existing_benchmark.name if existing_benchmark else None,
                "hostname": platform_info.hostname or platform_info.ip_address or "Unknown host",
                "ip_address": platform_info.ip_address,
                "profile_level": platform_info.profile_level,
                "total_findings": len(findings),
                "total_rules": len(extracted_rules),
                "passed": counts.get("PASS", 0),
                "failed": counts.get("FAIL", 0),
                "not_applicable": counts.get("NOT_APPLICABLE", 0),
                "errors": counts.get("ERROR", 0) + counts.get("MANUAL_REVIEW", 0),
                "scheme": platform_info.scheme or "unknown",
                "source_tool": source_tool,
            }

        return {
            "format": fmt,
            "filename": filename,
            "is_unknown": True,
            "message": "Format not automatically recognized. AI-powered analysis available.",
            "ai_parseable": True,
            "platform": "unknown",
            "platform_family": "other",
            "benchmark_name": "Unknown Benchmark",
            "benchmark_version": "unknown",
            "total_findings": 0,
            "total_rules": 0,
            "scheme": "custom",
            "source_tool": "unknown",
        }

    def execute(
        self,
        content: str,
        filename: str = "",
        *,
        client_id: int | None = None,
        mission_id: int | None = None,
        target_id: int | None = None,
        run_fp_detection: bool = True,
        allow_benchmark_creation: bool = True,
    ) -> ImportResult:
        """Execute the full Smart Import pipeline.

        Parameters
        ----------
        content : str
            File content (CSV, HTML, or JSON).
        filename : str
            Original filename (used for format hints).
        client_id : int | None
            Client ID to assign the target to.
        mission_id : int | None
            Mission ID to link the scan to.
        target_id : int | None
            Existing target ID (skip target creation).
        run_fp_detection : bool
            Run false-positive detection after import.
        allow_benchmark_creation : bool
            Allow creating a new benchmark if none matches.

        Returns
        -------
        ImportResult
            Full import statistics and references.
        """
        result = ImportResult()
        fmt = self.detect_format(content, filename)

        # Step 1: Parse
        if fmt == "nessus_csv":
            findings, platform_info = parse_nessus_csv(content)
            extracted_rules = extract_rules_from_findings(findings)
        elif fmt == "nessus_html":
            findings, platform_info = parse_nessus_html(content)
            extracted_rules = extract_rules_from_findings(findings)
        elif fmt == "nessus_xml":
            findings, platform_info = parse_nessus_xml(content)
            extracted_rules = extract_rules_from_nessus_xml(findings)
        elif fmt == "qualys_csv":
            findings, platform_info = parse_qualys_csv(content)
            extracted_rules = []
        elif fmt == "qualys_xml":
            findings, platform_info = parse_qualys_xml(content)
            extracted_rules = []
        elif fmt == "openvas_xml":
            findings, platform_info = parse_openvas_xml(content)
            extracted_rules = []
        elif fmt == "stig_xccdf":
            findings, platform_info = parse_stig_xccdf(content)
            extracted_rules = extract_rules_from_stig(findings)
        elif fmt == "stig_ckl":
            findings, platform_info = parse_stig_ckl(content)
            extracted_rules = extract_rules_from_stig(findings)
        elif fmt == "nist_json":
            findings, platform_info = parse_nist_json(content)
            extracted_rules = extract_rules_from_nist(findings)
        elif fmt == "nist_csv":
            findings, platform_info = parse_nist_csv(content)
            extracted_rules = extract_rules_from_nist(findings)
        elif fmt == "nist_xml":
            findings, platform_info = parse_nist_xml(content)
            extracted_rules = extract_rules_from_nist(findings)
        elif fmt == "iso_json":
            findings, platform_info = parse_iso_json(content)
            extracted_rules = extract_rules_from_iso(findings)
        elif fmt == "iso_csv":
            findings, platform_info = parse_iso_csv(content)
            extracted_rules = extract_rules_from_iso(findings)
        elif fmt == "xccdf":
            findings, platform_info = parse_xccdf(content)
            extracted_rules = extract_rules_from_xccdf(findings)
        else:
            raise ValueError(
                f"Unsupported format: '{fmt}'. Smart Import accepts "
                "Nessus CSV/HTML/XML, Qualys CSV/XML, OpenVAS XML, "
                "DISA STIG XCCDF/CKL, NIST 800-53 JSON/CSV/XML, "
                "ISO 27001 JSON/CSV, and generic XCCDF/SCAP exports."
            )

        # Step 1b: Enrich platform detection from content
        # Three-layer detection: parser info → content heuristics → AI fallback
        platform_info = enrich_platform_info(platform_info, findings, use_ai=True)

        result.platform_info = platform_info

        # Step 2: Resolve client_id
        if not client_id and mission_id:
            from backend.models.mission import Mission
            m = self.db.query(Mission).filter(Mission.id == mission_id).first()
            if m:
                client_id = m.client_id

        if not client_id:
            raise ValueError("client_id or mission_id is required for Smart Import.")

        # Step 3: Resolve benchmark
        resolver_result = resolve_benchmark(
            platform_info,
            extracted_rules,
            self.db,
            allow_create=allow_benchmark_creation,
        )
        benchmark = resolver_result.benchmark
        result.benchmark_id = benchmark.id
        result.benchmark_name = benchmark.name
        result.benchmark_reconstructed = resolver_result.created
        result.rules_matched = resolver_result.rules_matched
        result.rules_created = resolver_result.rules_created
        result.migration_readiness = resolver_result.migration_readiness

        # Step 4: Resolve or create target
        target: Target | None = None

        if target_id:
            target = self.db.query(Target).filter(Target.id == target_id).first()
            if not target:
                raise ValueError(f"Target ID {target_id} not found.")
        else:
            target = self._resolve_or_create_target(
                platform_info, client_id, benchmark.id
            )

        result.target_id = target.id
        result.target_hostname = target.hostname or target.ip_address or ""
        result.target_created = not bool(target_id)

        # Link target to mission if needed
        if mission_id:
            self._ensure_mission_target(mission_id, target.id)

        # Step 4b: Store open ports from import
        if platform_info.open_ports:
            self._upsert_discovery_cache_ports(platform_info, target)

        # Step 5: Create scan
        scan = Scan(
            target_id=target.id,
            benchmark_id=benchmark.id,
            mission_id=mission_id,
            scan_mode="import",
            status="pending",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(scan)
        self.db.flush()
        result.scan_id = scan.id

        # Step 6: Create findings
        stats = self._create_findings(findings, scan.id, benchmark.id, platform_info.source_tool or "nessus")
        result.findings_created = stats["findings_created"]
        result.passed = stats["passed"]
        result.failed = stats["failed"]
        result.errors = stats["errors"]
        result.not_applicable = stats["not_applicable"]
        total_checked = result.passed + result.failed + result.errors + result.not_applicable
        result.compliance_percentage = round(result.passed / total_checked * 100, 1) if total_checked > 0 else 0.0

        # Step 6b: Enrich severity from preloaded benchmarks
        # Phase 1 only (instant cross-benchmark matching, no LLM).
        # AI severity classification runs later via Phase 2 or manual trigger.
        enrichment = enrich_imported_benchmark(
            benchmark.id,
            self.db,
            scan_id=scan.id,
            use_ai_fallback=False,
        )
        result.enrichment_source = enrichment.preloaded_benchmark_name
        result.enrichment_source_id = enrichment.preloaded_benchmark_id
        result.rules_enriched = enrichment.rules_enriched_from_preloaded + enrichment.rules_enriched_by_ai
        result.commands_inherited = enrichment.commands_copied
        result.severity_distribution = enrichment.severity_distribution
        result.findings_severity_updated = enrichment.findings_updated

        if enrichment.preloaded_benchmark_name:
            logger.info(
                "Severity enrichment: %d rules enriched from '%s', %d by AI, %d commands inherited",
                enrichment.rules_enriched_from_preloaded,
                enrichment.preloaded_benchmark_name,
                enrichment.rules_enriched_by_ai,
                enrichment.commands_copied,
            )

        # Finalize scan
        scan.status = "completed"
        scan.completed_at = datetime.now(timezone.utc)
        scan.results_imported_at = datetime.now(timezone.utc)
        scan.total_rules = benchmark.total_rules or len(extracted_rules)
        scan.total_rules_checked = total_checked
        scan.passed = result.passed
        scan.failed = result.failed
        scan.errors = result.errors
        scan.not_applicable = result.not_applicable
        scan.compliance_percentage = result.compliance_percentage

        # Step 7: Run FP detection
        if run_fp_detection and result.failed > 0:
            result.fp_suspects = self._run_fp_detection(scan.id)

        # Step 8: Create ImportRecord
        result.import_record_id = self._create_import_record(
            scan_id=scan.id,
            benchmark_id=benchmark.id,
            target_id=target.id,
            filename=filename,
            fmt=fmt,
            platform_info=platform_info,
            stats=stats,
        )

        self.db.commit()

        logger.info(
            "Smart Import complete: scan=%d, benchmark='%s' (id=%d, %s), "
            "target='%s' (id=%d, %s), findings=%d (P:%d F:%d E:%d NA:%d), "
            "FP suspects=%d",
            scan.id,
            benchmark.name, benchmark.id,
            "reconstructed" if result.benchmark_reconstructed else "matched",
            target.hostname, target.id,
            "created" if result.target_created else "existing",
            result.findings_created,
            result.passed, result.failed, result.errors, result.not_applicable,
            result.fp_suspects,
        )

        return result

    # Private methods

    def _resolve_or_create_target(
        self,
        info: PlatformInfo,
        client_id: int,
        benchmark_id: int,
    ) -> Target:
        """Find an existing target by hostname/IP or create a new one."""
        target: Target | None = None

        # Try by hostname
        if info.hostname:
            target = (
                self.db.query(Target)
                .filter(Target.client_id == client_id, Target.hostname.ilike(info.hostname))
                .first()
            )

        # Try by IP
        if not target and info.ip_address:
            target = (
                self.db.query(Target)
                .filter(Target.client_id == client_id, Target.ip_address == info.ip_address)
                .first()
            )

        if target:
            return target

        # Create new target
        target_type = "windows"
        if info.platform_family == "Unix":
            target_type = "linux"
        elif info.platform_family == "Network":
            target_type = "network"
        elif info.platform_family == "Database":
            target_type = "database"

        target = Target(
            client_id=client_id,
            hostname=info.hostname or info.ip_address or "imported-target",
            ip_address=info.ip_address or None,
            target_type=target_type,
            os_details=f"{info.platform} {info.os_version}".strip() or None,
            default_benchmark_id=benchmark_id,
        )
        self.db.add(target)
        self.db.flush()
        return target

    def _ensure_mission_target(self, mission_id: int, target_id: int) -> None:
        """Ensure the target is linked to the mission."""
        from backend.models.mission_target import MissionTarget

        exists = (
            self.db.query(MissionTarget)
            .filter(MissionTarget.mission_id == mission_id, MissionTarget.target_id == target_id)
            .first()
        )
        if not exists:
            self.db.add(MissionTarget(mission_id=mission_id, target_id=target_id))
            self.db.flush()

    def _upsert_discovery_cache_ports(
        self,
        info: PlatformInfo,
        target: Target,
    ) -> None:
        """Create or update a DiscoveryCache entry with open port data from import.

        Keyed on IP address so the report generator can find it during
        device-profile building (which looks up DiscoveryCache by MAC then IP).
        """
        from backend.models.discovery_cache import DiscoveryCache

        ip = info.ip_address or target.ip_address
        if not ip:
            logger.debug("No IP address available — skipping port cache upsert")
            return

        cache_row = (
            self.db.query(DiscoveryCache)
            .filter(DiscoveryCache.ip_address == ip)
            .first()
        )

        if cache_row:
            # Merge imported ports with any existing port data
            existing = cache_row.open_ports
            existing_set = {(p["port"], p.get("protocol", "tcp")) for p in existing}
            for p in info.open_ports:
                key = (p["port"], p.get("protocol", "tcp"))
                if key not in existing_set:
                    existing.append(p)
                    existing_set.add(key)
            cache_row.open_ports = existing
            cache_row.last_seen = datetime.now(timezone.utc)
        else:
            # Build os_version without duplicating the platform prefix
            _os_ver = (info.os_version or "").strip()
            _os_platform = (info.platform or "").strip()
            if _os_ver and _os_platform and _os_ver.lower().startswith(_os_platform.lower()):
                # os_version already contains the platform name
                _final_os_ver = _os_ver
            elif _os_ver and _os_platform:
                _final_os_ver = f"{_os_platform} {_os_ver}"
            else:
                _final_os_ver = _os_ver or _os_platform or None

            cache_row = DiscoveryCache(
                ip_address=ip,
                hostname=info.hostname or target.hostname,
                os_guess=info.platform or None,
                os_version=_final_os_ver,
                detection_method="nessus_import",
                confidence=70,
            )
            cache_row.open_ports = info.open_ports
            self.db.add(cache_row)

        self.db.flush()
        logger.info(
            "Stored %d open ports in DiscoveryCache for %s",
            len(info.open_ports), ip,
        )

    def _create_findings(
        self,
        parsed_findings: list[ParsedFinding],
        scan_id: int,
        benchmark_id: int,
        source_tool: str = "nessus",
    ) -> dict[str, int]:
        """Create Finding records from parsed findings.

        Tries to match each finding to an existing Rule by section_number.
        If no Rule is found, a stub rule is created on-the-fly so that NO
        finding is ever silently dropped — every imported result must appear
        in the findings list.
        """
        passed = failed = errors = not_applicable = 0
        findings_created = 0
        rules_auto_created = 0

        # Preload rule lookup for this benchmark
        rules = (
            self.db.query(Rule)
            .filter(Rule.benchmark_id == benchmark_id)
            .all()
        )
        rule_map: dict[str, Rule] = {r.section_number: r for r in rules if r.section_number}

        for pf in parsed_findings:
            rule = rule_map.get(pf.section_number) if pf.section_number else None

            if not rule:
                # Auto-create a stub rule so the finding is never dropped
                rule = Rule(
                    benchmark_id=benchmark_id,
                    section_number=pf.section_number or f"_auto_{findings_created}",
                    title=pf.title or "Imported finding",
                    description=pf.description or "",
                    severity=pf.severity or "medium",
                    source=f"{source_tool}_import_auto",
                )
                self.db.add(rule)
                self.db.flush()
                # Cache so duplicates reuse the same rule
                if pf.section_number:
                    rule_map[pf.section_number] = rule
                rules_auto_created += 1

            # Build actual_output from Nessus values
            actual_output = pf.actual_value
            if not actual_output and pf.raw_plugin_output:
                actual_output = pf.raw_plugin_output

            # Build expected_output from Nessus policy value
            expected_output = pf.policy_value

            import_metadata = json.dumps({
                "plugin_id": pf.plugin_id,
                "source_row": pf.source_row_index,
                "original_status": pf.status,
            }) if pf.plugin_id else None

            finding = Finding(
                scan_id=scan_id,
                rule_id=rule.id,
                status=pf.status,
                actual_output=actual_output[:MAX_OUTPUT_LENGTH] if actual_output else "",
                expected_output=expected_output,
                severity=pf.severity or rule.severity,
                import_source=source_tool,
                import_metadata=import_metadata,
            )
            self.db.add(finding)
            findings_created += 1

            if pf.status == "PASS":
                passed += 1
            elif pf.status == "FAIL":
                failed += 1
            elif pf.status == "NOT_APPLICABLE":
                not_applicable += 1
            else:
                errors += 1

        self.db.flush()

        # Update benchmark rule count if rules were auto-created
        if rules_auto_created:
            benchmark = self.db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
            if benchmark:
                actual_count = self.db.query(Rule).filter(Rule.benchmark_id == benchmark_id).count()
                benchmark.total_rules = actual_count
            logger.info(
                "Auto-created %d stub rules for benchmark %d to avoid dropping findings",
                rules_auto_created, benchmark_id,
            )

        return {
            "findings_created": findings_created,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "not_applicable": not_applicable,
        }

    def _run_fp_detection(self, scan_id: int) -> int:
        """Run false-positive detection on FAIL findings for this scan."""
        try:
            from backend.core.false_positive_detector import analyze_finding

            fail_findings = (
                self.db.query(Finding)
                .filter(Finding.scan_id == scan_id, Finding.status == "FAIL")
                .all()
            )

            suspects = 0
            for f in fail_findings:
                finding_dict = {
                    "id": f.id,
                    "status": f.status,
                    "actual_output": f.actual_output or "",
                    "expected_output": f.expected_output or "",
                    "severity": f.severity or "medium",
                }
                analysis = analyze_finding(finding_dict)
                if analysis.is_suspect:
                    suspects += 1

            return suspects

        except Exception as exc:
            logger.warning("FP detection failed for scan %d: %s", scan_id, exc)
            return 0

    def _create_import_record(
        self,
        scan_id: int,
        benchmark_id: int,
        target_id: int,
        filename: str,
        fmt: str,
        platform_info: PlatformInfo,
        stats: dict[str, int],
    ) -> int | None:
        """Create an ImportRecord for audit trail."""
        try:
            from backend.models.import_record import ImportRecord

            record = ImportRecord(
                scan_id=scan_id,
                benchmark_id=benchmark_id,
                target_id=target_id,
                source_filename=filename,
                source_format=fmt,
                source_tool=platform_info.source_tool,
                platform_detected=platform_info.platform,
                benchmark_detected=platform_info.benchmark_name,
                version_detected=platform_info.benchmark_version,
                findings_imported=stats.get("findings_created", 0),
                metadata_json=json.dumps(platform_info.to_dict()),
            )
            self.db.add(record)
            self.db.flush()
            return record.id

        except Exception as exc:
            logger.warning("Failed to create ImportRecord: %s", exc)
            return None

def _count_statuses(findings: list[ParsedFinding]) -> dict[str, int]:
    """Count findings by status."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.status] = counts.get(f.status, 0) + 1
    return counts
