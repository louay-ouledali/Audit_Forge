from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.config import PROJECT_ROOT
from backend.core.phase1_parser import compute_pdf_hash, run_phase1
from backend.core.phase2_enricher import is_paused, request_pause, run_phase2  # UNUSED: 'is_paused' — safe to remove
from backend.core.phase3_validator import (
    apply_corrections as phase3_apply,
    clear_pause as phase3_clear_pause,  # UNUSED — safe to remove
    dismiss_corrections as phase3_dismiss,
    is_paused as phase3_is_paused,  # UNUSED — safe to remove
    request_pause as phase3_request_pause,
    run_phase3,
)
from backend.core.verification_engine import run_verification
from backend.database import get_db
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand
from backend.models.rule_tag import RuleTag
from backend.models.verification_report import VerificationReport
from backend.schemas.benchmark import (
    BenchmarkDetailEnvelope,
    BenchmarkImportResponse,
    BenchmarkListResponse,
    BenchmarkResponse,
    BenchmarkStatusResponse,
    EnrichStatusResponse,
    ValidateStatusResponse,
    ValidationResultsResponse,
    ValidationResultItem,
    ValidationCorrection,
    VerifyStatusResponse,
    CustomBenchmarkCreate,
    CustomBenchmarkResponse,
    AIRuleCreateRequest,
    AIRuleCreateResponse,
    BulkGenerateRequest,
    BulkGenerateResponse,
    BenchmarkExportResponse,  # UNUSED — safe to remove
    RuleTestRequest,
    RuleTestResponse,
    RuleValidateRequest,
    MigrationReadinessResponse,
    ScanComparisonItem,  # UNUSED — safe to remove
    ScanComparisonResponse,  # UNUSED — safe to remove
)
from backend.schemas.rule import VerificationReportResponse, VerificationResultsResponse, RuleResponse, RuleFullUpdate

logger = logging.getLogger("auditforge.api.benchmarks")

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])

BENCHMARKS_DIR = PROJECT_ROOT / "benchmarks"
BENCHMARKS_DIR.mkdir(exist_ok=True)


@router.get("/catalog")
def get_benchmark_catalog(db: Session = Depends(get_db)):
    """Return benchmarks organized into a hierarchical catalog.

    Structure: Category → Vendor → Product Line → Benchmarks
    The classifier uses intelligent pattern matching on benchmark names.
    """
    from backend.core.benchmark_classifier import build_catalog

    benchmarks = db.query(Benchmark).order_by(Benchmark.id.desc()).all()
    benchmark_dicts = []
    for b in benchmarks:
        benchmark_dicts.append({
            "id": b.id,
            "name": b.name,
            "version": b.version,
            "platform": b.platform,
            "platform_family": b.platform_family,
            "total_rules": b.total_rules or 0,
            "phase1_status": b.phase1_status or "pending",
            "phase2_status": b.phase2_status or "pending",
            "verification_status": b.verification_status or "pending",
            "is_ready": b.is_ready or False,
            "source": b.source or "user_imported",
            "import_date": b.import_date.isoformat() if b.import_date else None,
        })
    return build_catalog(benchmark_dicts)


@router.get("", response_model=BenchmarkListResponse)
def list_benchmarks(db: Session = Depends(get_db)):
    benchmarks = db.query(Benchmark).order_by(Benchmark.id.desc()).all()
    return {"data": [BenchmarkResponse.model_validate(b) for b in benchmarks], "total": len(benchmarks)}


@router.post("/import", response_model=BenchmarkImportResponse)
async def import_benchmark(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Sanitize filename to prevent path traversal
    safe_filename = Path(file.filename).name
    if not safe_filename or safe_filename.startswith(".") or "/" in file.filename or "\\" in file.filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Save to benchmarks directory
    pdf_path = BENCHMARKS_DIR / safe_filename
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Compute hash for dedup
    pdf_hash = compute_pdf_hash(pdf_path)
    existing = db.query(Benchmark).filter(Benchmark.pdf_hash == pdf_hash).first()
    if existing:
        pdf_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=409,
            detail=f"This PDF has already been imported as benchmark '{existing.name}' (ID: {existing.id})",
        )

    # Create benchmark record
    benchmark = Benchmark(
        name=safe_filename.replace(".pdf", ""),
        version="unknown",
        platform="unknown",
        platform_family="other",
        pdf_filename=safe_filename,
        pdf_hash=pdf_hash,
        phase1_status="pending",
    )
    db.add(benchmark)
    db.commit()
    db.refresh(benchmark)

    # Start Phase 1 as background task
    background_tasks.add_task(run_phase1, benchmark.id, pdf_path)

    return BenchmarkImportResponse(benchmark_id=benchmark.id)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: Custom Benchmark Creation
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/create", response_model=CustomBenchmarkResponse, status_code=201)
def create_custom_benchmark(
    payload: CustomBenchmarkCreate,
    db: Session = Depends(get_db),
):
    """Create a new custom (editable) benchmark.

    Custom benchmarks start empty and can have rules added manually
    or imported from other benchmarks via the Benchmark Studio.
    """
    benchmark = Benchmark(
        name=payload.name,
        version=payload.version,
        platform=payload.platform,
        platform_family=payload.platform_family,
        source="custom",
        is_editable=True,
        phase1_status="completed",  # no PDF to parse
        total_rules=0,
    )
    db.add(benchmark)
    db.commit()
    db.refresh(benchmark)
    logger.info("Custom benchmark created: id=%d, name='%s'", benchmark.id, benchmark.name)
    return CustomBenchmarkResponse(benchmark_id=benchmark.id, name=benchmark.name)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: AI-Assisted Rule Creation (within a benchmark)
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/{benchmark_id}/rules/create", response_model=AIRuleCreateResponse, status_code=201)
async def create_rule_with_ai(
    benchmark_id: int,
    payload: AIRuleCreateRequest,
    db: Session = Depends(get_db),
):
    """Create a new rule in an editable benchmark, optionally generating AI commands."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if not benchmark.is_editable:
        raise HTTPException(status_code=400, detail="Only editable benchmarks can have rules added manually")

    # Check for duplicate section_number
    existing = (
        db.query(Rule)
        .filter(Rule.benchmark_id == benchmark_id, Rule.section_number == payload.section_number)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Section {payload.section_number} already exists in this benchmark",
        )

    # Create the rule
    rule = Rule(
        benchmark_id=benchmark_id,
        section_number=payload.section_number,
        title=payload.title,
        description=payload.description,
        rationale=payload.rationale,
        severity=payload.severity,
        profile_applicability=payload.profile_applicability,
        source="manual",
        enabled=True,
    )
    db.add(rule)
    db.flush()

    # Update benchmark rule count
    benchmark.total_rules = (benchmark.total_rules or 0) + 1

    commands_generated = False

    if payload.generate_commands:
        try:
            from backend.ai.benchmark_ai import generate_commands_for_batch

            rules_batch = [{
                "section_number": rule.section_number,
                "title": rule.title,
                "audit_description_raw": payload.description or "",
                "remediation_description_raw": payload.rationale or "",
            }]

            results = await generate_commands_for_batch(
                rules_batch,
                platform=benchmark.platform,
                platform_family=benchmark.platform_family,
            )

            if results:
                result = results[0]
                cmd = RuleCommand(
                    rule_id=rule.id,
                    audit_command=result.get("audit_command", ""),
                    expected_output_regex=result.get("expected_output_regex", ""),
                    expected_output_description=result.get("expected_output_description", ""),
                    remediation_command=result.get("remediation_command", ""),
                    remediation_description=result.get("remediation_description", ""),
                    status="generated",
                    source=result.get("source", "llm_generated"),
                )
                db.add(cmd)
                commands_generated = True
        except Exception as exc:
            logger.warning("AI command generation failed for rule %s: %s", rule.section_number, exc)

    db.commit()
    db.refresh(rule)

    return AIRuleCreateResponse(
        rule_id=rule.id,
        section_number=rule.section_number,
        title=rule.title,
        commands_generated=commands_generated,
    )


@router.put("/{benchmark_id}/rules/{rule_id}", response_model=dict)
def update_rule_full(
    benchmark_id: int,
    rule_id: int,
    payload: RuleFullUpdate,
    db: Session = Depends(get_db),
):
    """Full rule update for editable benchmarks — allows editing all text fields."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if not benchmark.is_editable:
        raise HTTPException(status_code=400, detail="Only rules in editable benchmarks can be fully edited")

    rule = db.query(Rule).filter(Rule.id == rule_id, Rule.benchmark_id == benchmark_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found in this benchmark")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)

    db.commit()
    db.refresh(rule)
    return {"data": RuleResponse.model_validate(rule), "message": "Rule updated"}


@router.delete("/{benchmark_id}/rules/{rule_id}")
def delete_rule_from_benchmark(
    benchmark_id: int,
    rule_id: int,
    db: Session = Depends(get_db),
):
    """Delete a rule from an editable benchmark."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if not benchmark.is_editable:
        raise HTTPException(status_code=400, detail="Only rules in editable benchmarks can be deleted")

    rule = db.query(Rule).filter(Rule.id == rule_id, Rule.benchmark_id == benchmark_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found in this benchmark")

    db.delete(rule)
    benchmark.total_rules = max(0, (benchmark.total_rules or 0) - 1)
    db.commit()
    return {"message": f"Rule {rule.section_number} deleted"}


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: Bulk AI Command Generation
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/{benchmark_id}/generate-commands", response_model=BulkGenerateResponse)
async def bulk_generate_commands(
    benchmark_id: int,
    background_tasks: BackgroundTasks,
    payload: BulkGenerateRequest | None = None,
    db: Session = Depends(get_db),
):
    """Start bulk AI command generation for all rules without commands.

    Uses the existing Phase 2 enrichment pipeline (generate_commands_for_batch)
    to create audit + remediation commands for every rule that doesn't have one yet.
    """
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    if benchmark.phase2_status == "processing":
        raise HTTPException(status_code=409, detail="Enrichment is already running")

    # Count rules without commands
    rules_needing_commands = (
        db.query(Rule)
        .outerjoin(RuleCommand, Rule.id == RuleCommand.rule_id)
        .filter(Rule.benchmark_id == benchmark_id, RuleCommand.id.is_(None))
        .count()
    )

    if rules_needing_commands == 0:
        return BulkGenerateResponse(
            message="All rules already have commands",
            total_rules=benchmark.total_rules or 0,
            commands_generated=0,
            status="already_complete",
        )

    # Start enrichment via existing Phase 2 pipeline
    benchmark.phase2_status = "processing"
    db.commit()

    background_tasks.add_task(run_phase2, benchmark_id)

    return BulkGenerateResponse(
        message=f"Started command generation for {rules_needing_commands} rules",
        total_rules=rules_needing_commands,
        status="started",
    )


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: Benchmark Export (.auditforge.json)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/{benchmark_id}/export")
def export_benchmark(benchmark_id: int, db: Session = Depends(get_db)):
    """Export a complete benchmark as .auditforge.json (rules + commands + metadata)."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    rules = db.query(Rule).filter(Rule.benchmark_id == benchmark_id).order_by(Rule.section_number).all()
    commands = {
        rc.rule_id: rc
        for rc in db.query(RuleCommand).filter(
            RuleCommand.rule_id.in_([r.id for r in rules])
        ).all()
    }

    export_data = {
        "format": "auditforge_benchmark",
        "format_version": "2.0",
        "export_date": datetime.now(timezone.utc).isoformat(),
        "benchmark": {
            "name": benchmark.name,
            "version": benchmark.version,
            "platform": benchmark.platform,
            "platform_family": benchmark.platform_family,
            "source": benchmark.source,
            "total_rules": benchmark.total_rules,
        },
        "rules": [],
    }

    for rule in rules:
        rule_data: dict = {
            "section_number": rule.section_number,
            "title": rule.title,
            "description": rule.description,
            "rationale": rule.rationale,
            "profile_applicability": rule.profile_applicability,
            "assessment_type": rule.assessment_type,
            "default_value": rule.default_value,
            "audit_description_raw": rule.audit_description_raw,
            "remediation_description_raw": rule.remediation_description_raw,
            "severity": rule.severity,
            "framework_mappings": rule.framework_mappings,
        }

        cmd = commands.get(rule.id)
        if cmd:
            rule_data["command"] = {
                "audit_command": cmd.audit_command,
                "expected_output_regex": cmd.expected_output_regex,
                "expected_output_description": cmd.expected_output_description,
                "remediation_command": cmd.remediation_command,
                "remediation_description": cmd.remediation_description,
                "source": cmd.source,
                "status": cmd.status,
            }

        export_data["rules"].append(rule_data)

    content = json.dumps(export_data, indent=2, default=str)
    safe_name = benchmark.name.replace(" ", "_")
    filename = f"{safe_name}_v{benchmark.version}.auditforge.json"

    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{benchmark_id}/import-benchmark")
async def import_benchmark_file(
    benchmark_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Import rules (and commands) from an .auditforge.json file into this benchmark.

    Only allowed for editable benchmarks.
    """
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if not benchmark.is_editable:
        raise HTTPException(status_code=400, detail="Only editable benchmarks can import rules")

    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")

    if data.get("format") != "auditforge_benchmark":
        raise HTTPException(status_code=400, detail="Invalid file format — expected auditforge_benchmark")

    rules_data = data.get("rules", [])
    if not rules_data:
        raise HTTPException(status_code=400, detail="No rules found in file")

    # Get existing section numbers to avoid duplicates
    existing_sections = set(
        r.section_number
        for r in db.query(Rule.section_number).filter(Rule.benchmark_id == benchmark_id).all()
    )

    imported = 0
    commands_imported = 0

    for rd in rules_data:
        sec = rd.get("section_number", "")
        if not sec or sec in existing_sections:
            continue

        rule = Rule(
            benchmark_id=benchmark_id,
            section_number=sec,
            title=rd.get("title", sec),
            description=rd.get("description"),
            rationale=rd.get("rationale"),
            profile_applicability=rd.get("profile_applicability"),
            assessment_type=rd.get("assessment_type"),
            default_value=rd.get("default_value"),
            audit_description_raw=rd.get("audit_description_raw"),
            remediation_description_raw=rd.get("remediation_description_raw"),
            severity=rd.get("severity", "medium"),
            framework_mappings=rd.get("framework_mappings"),
            source="imported",
        )
        db.add(rule)
        db.flush()
        imported += 1
        existing_sections.add(sec)

        cmd_data = rd.get("command")
        if cmd_data:
            cmd = RuleCommand(
                rule_id=rule.id,
                audit_command=cmd_data.get("audit_command", ""),
                expected_output_regex=cmd_data.get("expected_output_regex", ""),
                expected_output_description=cmd_data.get("expected_output_description", ""),
                remediation_command=cmd_data.get("remediation_command", ""),
                remediation_description=cmd_data.get("remediation_description", ""),
                source=cmd_data.get("source", "imported"),
                status=cmd_data.get("status", "generated"),
            )
            db.add(cmd)
            commands_imported += 1

    benchmark.total_rules = (benchmark.total_rules or 0) + imported
    db.commit()

    logger.info(
        "Imported %d rules (%d with commands) into benchmark %d",
        imported, commands_imported, benchmark_id,
    )

    return {
        "message": f"Imported {imported} rules ({commands_imported} with commands)",
        "rules_imported": imported,
        "commands_imported": commands_imported,
    }


# ── Phase 3: Rule Testing, Validation, Migration Readiness ──────────────────


@router.post("/{benchmark_id}/rules/{rule_id}/test", response_model=RuleTestResponse)
async def test_rule_command(
    benchmark_id: int,
    rule_id: int,
    req: RuleTestRequest,
    db: Session = Depends(get_db),
):
    """Test a rule's audit command against a live target via the connector infrastructure."""
    import re as _re

    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    rule = db.query(Rule).filter(Rule.id == rule_id, Rule.benchmark_id == benchmark_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found in this benchmark")

    cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule_id).first()
    if not cmd or not cmd.audit_command:
        raise HTTPException(status_code=400, detail="Rule has no audit command to test")

    # Load target
    from backend.models.target import Target
    target = db.query(Target).filter(Target.id == req.target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")

    # Decrypt password if needed
    if target.ssh_password_encrypted:
        try:
            from backend.utils.crypto import decrypt_value
            target._decrypted_password = decrypt_value(target.ssh_password_encrypted)
        except Exception:
            target._decrypted_password = None

    # Get connector and execute
    from backend.connectors import get_connector
    try:
        connector = get_connector(
            target.target_type,
            target.connection_method,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"No connector available: {exc}")

    try:
        await connector.connect(target)
        result = await connector.execute(cmd.audit_command, timeout=req.timeout)
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=f"Connection failed: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Command execution error: {exc}")
    finally:
        try:
            await connector.disconnect()
        except Exception:
            pass

    # Compare output with expected_output_regex
    match_result = "unknown"
    match_details = None
    if cmd.expected_output_regex and result.stdout:
        try:
            regex = cmd.expected_output_regex.strip()
            # Handle comparison operators: ==value, >=value, <=value
            if regex.startswith("=="):
                expected = regex[2:].strip()
                if result.stdout.strip() == expected:
                    match_result = "pass"
                    match_details = f"Exact match: '{expected}'"
                else:
                    match_result = "fail"
                    match_details = f"Expected '{expected}', got '{result.stdout.strip()}'"
            elif regex.startswith(">=") or regex.startswith("<="):
                op = regex[:2]
                expected_val = regex[2:].strip()
                try:
                    actual_num = float(result.stdout.strip())
                    expected_num = float(expected_val)
                    if (op == ">=" and actual_num >= expected_num) or (op == "<=" and actual_num <= expected_num):
                        match_result = "pass"
                    else:
                        match_result = "fail"
                    match_details = f"Comparison {op}: actual={actual_num}, expected={expected_num}"
                except ValueError:
                    match_result = "error"
                    match_details = "Cannot compare — non-numeric values"
            elif _re.search(regex, result.stdout, _re.IGNORECASE | _re.MULTILINE):
                match_result = "pass"
                match_details = f"Regex matched: {regex}"
            else:
                match_result = "fail"
                match_details = f"Regex did not match: {regex}"
        except _re.error as exc:
            match_result = "error"
            match_details = f"Invalid regex: {exc}"
    elif not cmd.expected_output_regex:
        match_result = "pass" if result.exit_code == 0 else "fail"
        match_details = "No regex — using exit code"

    # Store test timestamp on command
    from datetime import datetime, timezone
    cmd.verified_at = datetime.now(timezone.utc)
    cmd.verification_notes = f"Tested against target {target.hostname or target.ip_address}: {match_result}"
    db.commit()

    return RuleTestResponse(
        rule_id=rule_id,
        section_number=rule.section_number,
        audit_command=cmd.audit_command,
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        execution_time_ms=result.execution_time_ms,
        expected_output_regex=cmd.expected_output_regex,
        match_result=match_result,
        match_details=match_details,
    )


@router.post("/{benchmark_id}/rules/{rule_id}/validate")
async def validate_rule_command(
    benchmark_id: int,
    rule_id: int,
    req: RuleValidateRequest,
    db: Session = Depends(get_db),
):
    """Mark a rule command as validated/corrected/flagged after testing."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    rule = db.query(Rule).filter(Rule.id == rule_id, Rule.benchmark_id == benchmark_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found in this benchmark")

    cmd = db.query(RuleCommand).filter(RuleCommand.rule_id == rule_id).first()
    if not cmd:
        raise HTTPException(status_code=400, detail="Rule has no command to validate")

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    if req.validation_status not in ("validated", "corrected", "flagged"):
        raise HTTPException(status_code=400, detail="Invalid validation_status. Must be validated/corrected/flagged.")

    # Apply corrections if provided
    if req.corrected_command:
        cmd.audit_command = req.corrected_command
    if req.corrected_regex:
        cmd.expected_output_regex = req.corrected_regex

    cmd.validation_status = req.validation_status
    cmd.validation_notes = req.notes
    cmd.validated_at = now
    cmd.validation_confidence = "high" if req.validation_status == "validated" else "medium"

    if req.validation_status == "validated":
        cmd.status = "validated"
        cmd.verified_at = now
    elif req.validation_status == "corrected":
        cmd.status = "validated"
        cmd.verified_at = now
    elif req.validation_status == "flagged":
        cmd.flagged_at = now
        cmd.flag_reason = req.notes

    db.commit()

    # Recalculate migration readiness
    _update_migration_readiness(benchmark_id, db)

    return {
        "message": f"Rule {rule.section_number} marked as {req.validation_status}",
        "rule_id": rule_id,
        "validation_status": req.validation_status,
    }


@router.get("/{benchmark_id}/migration-readiness", response_model=MigrationReadinessResponse)
def get_migration_readiness(
    benchmark_id: int,
    db: Session = Depends(get_db),
):
    """Calculate migration readiness for a benchmark."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    return _compute_migration_readiness(benchmark, db)


def _compute_migration_readiness(benchmark: Benchmark, db: Session) -> MigrationReadinessResponse:
    """Compute migration readiness statistics."""
    from sqlalchemy import func

    total_rules = db.query(func.count(Rule.id)).filter(
        Rule.benchmark_id == benchmark.id,
        Rule.enabled == True,
    ).scalar() or 0

    if total_rules == 0:
        return MigrationReadinessResponse(
            benchmark_id=benchmark.id,
            benchmark_name=benchmark.name,
            total_rules=0,
            status="not_ready",
        )

    # Rules WITH a command
    rules_with_cmd = (
        db.query(func.count(Rule.id))
        .filter(Rule.benchmark_id == benchmark.id, Rule.enabled == True)
        .join(RuleCommand, RuleCommand.rule_id == Rule.id)
        .scalar() or 0
    )

    # Rules with VALIDATED commands
    rules_validated = (
        db.query(func.count(Rule.id))
        .filter(Rule.benchmark_id == benchmark.id, Rule.enabled == True)
        .join(RuleCommand, RuleCommand.rule_id == Rule.id)
        .filter(RuleCommand.validation_status.in_(["validated", "corrected"]))
        .scalar() or 0
    )

    # Rules with flagged commands
    rules_flagged = (
        db.query(func.count(Rule.id))
        .filter(Rule.benchmark_id == benchmark.id, Rule.enabled == True)
        .join(RuleCommand, RuleCommand.rule_id == Rule.id)
        .filter(RuleCommand.validation_status == "flagged")
        .scalar() or 0
    )

    rules_no_cmd = total_rules - rules_with_cmd
    rules_generated = rules_with_cmd - rules_validated - rules_flagged

    # Readiness = validated / total (only fully validated commands count)
    readiness = round((rules_validated / total_rules) * 100, 1) if total_rules > 0 else 0.0

    if readiness >= 95:
        status = "ready"
    elif readiness >= 50:
        status = "partial"
    else:
        status = "not_ready"

    return MigrationReadinessResponse(
        benchmark_id=benchmark.id,
        benchmark_name=benchmark.name,
        total_rules=total_rules,
        rules_with_commands=rules_with_cmd,
        rules_validated=rules_validated,
        rules_generated=rules_generated,
        rules_no_command=rules_no_cmd,
        rules_flagged=rules_flagged,
        readiness_percentage=readiness,
        status=status,
    )


def _update_migration_readiness(benchmark_id: int, db: Session):
    """Recalculate and persist migration_readiness on the benchmark."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        return
    stats = _compute_migration_readiness(benchmark, db)
    benchmark.migration_readiness = stats.readiness_percentage
    db.commit()


@router.get("/{benchmark_id}", response_model=BenchmarkDetailEnvelope)
def get_benchmark(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return {"data": BenchmarkResponse.model_validate(benchmark), "message": "success"}


@router.get("/{benchmark_id}/status", response_model=BenchmarkStatusResponse)
def get_benchmark_status(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return BenchmarkStatusResponse(
        id=benchmark.id,
        phase1_status=benchmark.phase1_status or "pending",
        phase2_status=benchmark.phase2_status or "pending",
        verification_status=benchmark.verification_status or "pending",
        is_ready=benchmark.is_ready or False,
        total_rules=benchmark.total_rules or 0,
    )


@router.delete("/{benchmark_id}")
def delete_benchmark(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    # Delete PDF file if exists
    if benchmark.pdf_filename:
        pdf_path = BENCHMARKS_DIR / benchmark.pdf_filename
        pdf_path.unlink(missing_ok=True)
    db.delete(benchmark)
    db.commit()
    return {"data": None, "message": "Benchmark deleted"}


@router.get("/{benchmark_id}/rules", response_model=dict)
def list_benchmark_rules(
    benchmark_id: int,
    category: str | None = Query(None),
    profile: str | None = Query(None),
    severity: str | None = Query(None),
    search: str | None = Query(None),
    db: Session = Depends(get_db),
):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    query = db.query(Rule).filter(Rule.benchmark_id == benchmark_id)

    if severity:
        query = query.filter(Rule.severity == severity)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Rule.title.ilike(search_term)) | (Rule.section_number.ilike(search_term))
        )
    if category:
        from backend.models.rule_tag import RuleTag
        query = query.join(RuleTag).filter(RuleTag.tag_id == category)
    if profile:
        query = query.filter(Rule.profile_applicability.ilike(f"%{profile}%"))

    rules = query.order_by(Rule.section_number).all()

    from backend.schemas.rule import RuleResponse, RuleTagResponse
    result = []
    for r in rules:
        rule_resp = RuleResponse.model_validate(r)
        rule_resp.tags = [RuleTagResponse.model_validate(t) for t in r.tags]
        result.append(rule_resp)

    return {"data": result, "total": len(result)}


# ── Phase 1: Export / Import Rules ──


@router.get("/{benchmark_id}/rules/export")
def export_rules(benchmark_id: int, db: Session = Depends(get_db)):
    """Export all Phase 1 rules as a downloadable JSON file."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    rules = (
        db.query(Rule)
        .filter(Rule.benchmark_id == benchmark_id)
        .order_by(Rule.section_number)
        .all()
    )

    export_data = {
        "export_type": "phase1_rules",
        "benchmark": {
            "name": benchmark.name,
            "version": benchmark.version,
            "platform": benchmark.platform,
            "platform_family": benchmark.platform_family,
        },
        "total_rules": len(rules),
        "rules": [],
    }
    for r in rules:
        tags = [{"tag_id": t.tag_id, "source": t.source} for t in r.tags]
        export_data["rules"].append(
            {
                "section_number": r.section_number,
                "title": r.title,
                "description": r.description,
                "rationale": r.rationale,
                "profile_applicability": r.profile_applicability,
                "assessment_type": r.assessment_type,
                "default_value": r.default_value,
                "references_json": r.references_json,
                "cis_controls": r.cis_controls,
                "audit_description_raw": r.audit_description_raw,
                "remediation_description_raw": r.remediation_description_raw,
                "severity": r.severity or "medium",
                "enabled": r.enabled if r.enabled is not None else True,
                "tags": tags,
            }
        )

    content = json.dumps(export_data, indent=2, ensure_ascii=False)
    safe_name = benchmark.name.replace(" ", "_")[:60]
    filename = f"{safe_name}_phase1_rules.json"

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/{benchmark_id}/rules/import")
async def import_rules(
    benchmark_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Import Phase 1 rules from a JSON file, replacing any existing rules."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files are accepted")

    raw = await file.read()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    if data.get("export_type") != "phase1_rules":
        raise HTTPException(
            status_code=400,
            detail="Invalid file: expected export_type 'phase1_rules'",
        )

    rules_list = data.get("rules", [])
    if not rules_list:
        raise HTTPException(status_code=400, detail="No rules found in file")

    # Optionally update benchmark metadata from the export
    bm_meta = data.get("benchmark", {})
    if bm_meta.get("platform"):
        benchmark.platform = bm_meta["platform"]
    if bm_meta.get("platform_family"):
        benchmark.platform_family = bm_meta["platform_family"]
    if bm_meta.get("version"):
        benchmark.version = bm_meta["version"]

    # Delete existing rules (cascade deletes commands, tags, etc.)
    db.query(Rule).filter(Rule.benchmark_id == benchmark_id).delete()
    db.flush()


    created_count = 0
    for item in rules_list:
        section = item.get("section_number")
        title = item.get("title")
        if not section or not title:
            continue  # skip malformed entries

        rule = Rule(
            benchmark_id=benchmark_id,
            section_number=section,
            title=title,
            description=item.get("description"),
            rationale=item.get("rationale"),
            profile_applicability=item.get("profile_applicability"),
            assessment_type=item.get("assessment_type"),
            default_value=item.get("default_value"),
            references_json=item.get("references_json"),
            cis_controls=item.get("cis_controls"),
            audit_description_raw=item.get("audit_description_raw"),
            remediation_description_raw=item.get("remediation_description_raw"),
            severity=item.get("severity", "medium"),
            enabled=item.get("enabled", True),
        )
        db.add(rule)
        db.flush()  # get rule.id for tags

        for tag_data in item.get("tags", []):
            tag = RuleTag(
                rule_id=rule.id,
                tag_id=tag_data.get("tag_id", ""),
                source=tag_data.get("source", "imported"),
            )
            db.add(tag)

        created_count += 1

    benchmark.total_rules = created_count
    benchmark.phase1_status = "completed"
    db.commit()

    return {
        "message": f"Imported {created_count} rules",
        "rules_imported": created_count,
        "benchmark_id": benchmark_id,
    }


# ── Phase 2: Export / Import Commands ──


@router.get("/{benchmark_id}/commands/export")
def export_commands(benchmark_id: int, db: Session = Depends(get_db)):
    """Export all Phase 2 commands (with their rule context) as a downloadable JSON file."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    rules = (
        db.query(Rule)
        .filter(Rule.benchmark_id == benchmark_id)
        .order_by(Rule.section_number)
        .all()
    )

    export_data = {
        "export_type": "phase2_commands",
        "benchmark": {
            "name": benchmark.name,
            "version": benchmark.version,
            "platform": benchmark.platform,
            "platform_family": benchmark.platform_family,
        },
        "total_rules": len(rules),
        "rules": [],
    }
    for r in rules:
        cmd = r.commands
        rule_entry: dict = {
            "section_number": r.section_number,
            "title": r.title,
        }
        if cmd:
            rule_entry["command"] = {
                "audit_command": cmd.audit_command,
                "expected_output_regex": cmd.expected_output_regex,
                "expected_output_description": cmd.expected_output_description,
                "remediation_command": cmd.remediation_command,
                "remediation_description": cmd.remediation_description,
                "source": cmd.source or "imported",
                "status": cmd.status or "generated",
            }
        else:
            rule_entry["command"] = None
        export_data["rules"].append(rule_entry)

    content = json.dumps(export_data, indent=2, ensure_ascii=False)
    safe_name = benchmark.name.replace(" ", "_")[:60]
    filename = f"{safe_name}_phase2_commands.json"

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/{benchmark_id}/commands/import")
async def import_commands(
    benchmark_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Import Phase 2 commands from a JSON file, matching by section_number."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files are accepted")

    raw = await file.read()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    if data.get("export_type") != "phase2_commands":
        raise HTTPException(
            status_code=400,
            detail="Invalid file: expected export_type 'phase2_commands'",
        )

    rules_list = data.get("rules", [])
    if not rules_list:
        raise HTTPException(status_code=400, detail="No rules found in file")

    # Build lookup: section_number → Rule
    existing_rules = (
        db.query(Rule)
        .filter(Rule.benchmark_id == benchmark_id)
        .all()
    )
    rule_map = {r.section_number: r for r in existing_rules}

    if not rule_map:
        raise HTTPException(
            status_code=400,
            detail="No rules exist for this benchmark. Import Phase 1 rules first.",
        )


    now = datetime.now(timezone.utc)
    created = 0
    updated = 0
    skipped = 0

    for item in rules_list:
        section = item.get("section_number")
        cmd_data = item.get("command")
        if not section or not cmd_data:
            skipped += 1
            continue

        rule = rule_map.get(section)
        if not rule:
            skipped += 1
            continue

        if rule.commands:
            # Update existing command (unless protected)
            cmd = rule.commands
            if cmd.is_protected:
                skipped += 1
                continue
            cmd.audit_command = cmd_data.get("audit_command", cmd.audit_command)
            cmd.expected_output_regex = cmd_data.get("expected_output_regex", cmd.expected_output_regex)
            cmd.expected_output_description = cmd_data.get("expected_output_description", cmd.expected_output_description)
            cmd.remediation_command = cmd_data.get("remediation_command", cmd.remediation_command)
            cmd.remediation_description = cmd_data.get("remediation_description", cmd.remediation_description)
            cmd.source = cmd_data.get("source", "imported")
            cmd.status = cmd_data.get("status", "generated")
            cmd.updated_at = now
            updated += 1
        else:
            # Create new command
            cmd = RuleCommand(
                rule_id=rule.id,
                audit_command=cmd_data.get("audit_command"),
                expected_output_regex=cmd_data.get("expected_output_regex"),
                expected_output_description=cmd_data.get("expected_output_description"),
                remediation_command=cmd_data.get("remediation_command"),
                remediation_description=cmd_data.get("remediation_description"),
                source=cmd_data.get("source", "imported"),
                status=cmd_data.get("status", "generated"),
                created_at=now,
            )
            db.add(cmd)
            created += 1

    benchmark.phase2_status = "completed"
    benchmark.enrichment_stats = json.dumps(
        {"total": len(rule_map), "processed": len(rule_map)}
    )
    db.commit()

    return {
        "message": f"Imported commands: {created} created, {updated} updated, {skipped} skipped",
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "benchmark_id": benchmark_id,
    }


# ── Phase 2: Enrichment ──

@router.post("/{benchmark_id}/enrich")
async def start_enrichment(
    benchmark_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if benchmark.phase1_status != "completed":
        raise HTTPException(status_code=400, detail="Phase 1 must be completed before enrichment")

    # Allow re-triggering from any state except active processing
    # (stale "processing" from crashed containers is handled by resetting first)
    if benchmark.phase2_status == "processing":
        # Reset stale processing state so we can re-trigger
        benchmark.phase2_status = "pending"
        db.commit()

    background_tasks.add_task(run_phase2, benchmark.id)
    return {"message": "Phase 2 enrichment started", "benchmark_id": benchmark_id}


@router.post("/{benchmark_id}/enrich/pause")
def pause_enrichment(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if benchmark.phase2_status != "processing":
        raise HTTPException(status_code=400, detail="Phase 2 is not currently running")
    request_pause(benchmark_id)
    return {"message": "Phase 2 pause requested", "benchmark_id": benchmark_id}


@router.get("/{benchmark_id}/enrich/status", response_model=EnrichStatusResponse)
def get_enrichment_status(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    stats = {}
    if benchmark.enrichment_stats:
        try:
            stats = json.loads(benchmark.enrichment_stats)
        except (json.JSONDecodeError, TypeError):
            pass

    return EnrichStatusResponse(
        total=stats.get("total", benchmark.total_rules or 0),
        processed=stats.get("processed", 0),
        template_matched=stats.get("template_matched", 0),
        llm_generated=stats.get("llm_generated", 0),
        status=benchmark.phase2_status or "pending",
    )


# ── AI Severity Classification (manual trigger) ──

@router.post("/{benchmark_id}/enrich-severities")
async def enrich_severities(
    benchmark_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Manually trigger AI severity classification for rules still at 'medium'."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    medium_count = (
        db.query(func.count(Rule.id))
        .filter(Rule.benchmark_id == benchmark_id, Rule.severity == "medium")
        .scalar()
    )
    if not medium_count:
        return {
            "message": "No rules with default severity to classify",
            "benchmark_id": benchmark_id,
            "rules_to_classify": 0,
        }

    background_tasks.add_task(_run_severity_enrichment, benchmark_id)
    return {
        "message": "AI severity classification started",
        "benchmark_id": benchmark_id,
        "rules_to_classify": medium_count,
    }


@router.get("/{benchmark_id}/enrich-severities/status")
def get_severity_enrichment_status(
    benchmark_id: int,
    db: Session = Depends(get_db),
):
    """Check how many rules still have default 'medium' severity."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    total_rules = (
        db.query(func.count(Rule.id))
        .filter(Rule.benchmark_id == benchmark_id)
        .scalar()
    )
    medium_count = (
        db.query(func.count(Rule.id))
        .filter(Rule.benchmark_id == benchmark_id, Rule.severity == "medium")
        .scalar()
    )
    severity_dist = dict(
        db.query(Rule.severity, func.count(Rule.id))
        .filter(Rule.benchmark_id == benchmark_id)
        .group_by(Rule.severity)
        .all()
    )
    return {
        "benchmark_id": benchmark_id,
        "total_rules": total_rules,
        "medium_count": medium_count,
        "classified": total_rules - medium_count,
        "severity_distribution": severity_dist,
    }


def _run_severity_enrichment(benchmark_id: int):
    """Background task: run AI severity classification + sync findings."""
    from backend.database import SessionLocal
    from backend.importers.severity_enricher import (
        _enrich_severity_with_ai,
        _sync_finding_severities,
    )

    db = SessionLocal()
    try:
        medium_rules = (
            db.query(Rule)
            .filter(Rule.benchmark_id == benchmark_id, Rule.severity == "medium")
            .all()
        )
        if not medium_rules:
            return

        updated = _enrich_severity_with_ai(medium_rules, db)
        db.commit()
        logger.info(
            "Manual AI severity classification updated %d rules for benchmark %d",
            updated, benchmark_id,
        )

        # Also sync finding severities for any related scans
        from backend.models.finding import Finding
        scan_ids = (
            db.query(Finding.scan_id)
            .filter(Finding.rule_id.in_([r.id for r in medium_rules]))
            .distinct()
            .all()
        )
        for (scan_id,) in scan_ids:
            _sync_finding_severities(scan_id, benchmark_id, db)
        db.commit()
    except Exception as exc:
        logger.error("Manual AI severity classification failed: %s", exc)
        db.rollback()
    finally:
        db.close()


# ── Verification ──

@router.post("/{benchmark_id}/verify")
async def start_verification(
    benchmark_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if benchmark.phase2_status != "completed":
        raise HTTPException(status_code=400, detail="Phase 2 must be completed before verification")

    background_tasks.add_task(run_verification, benchmark.id)
    return {"message": "Verification started", "benchmark_id": benchmark_id}


@router.get("/{benchmark_id}/verify/status", response_model=VerifyStatusResponse)
def get_verification_status(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    from sqlalchemy import case, func
    row = db.query(
        func.count(RuleCommand.id).label("total"),
        func.sum(case((RuleCommand.status == "verified", 1), else_=0)).label("passed"),
        func.sum(case((RuleCommand.status == "flagged", 1), else_=0)).label("failed"),
    ).join(Rule).filter(Rule.benchmark_id == benchmark_id).one()
    total = row.total or 0
    passed = int(row.passed or 0)
    failed = int(row.failed or 0)

    return VerifyStatusResponse(
        status=benchmark.verification_status or "pending",
        total=total,
        passed=passed,
        failed=failed,
    )


# ── Verification Results ──

@router.get("/{benchmark_id}/verify/results", response_model=VerificationResultsResponse)
def get_verification_results(
    benchmark_id: int,
    level: str | None = Query(None, description="Filter by check level: syntax, safety, cross_reference, regex"),
    result: str | None = Query(None, description="Filter by result: pass, fail, warn, skip"),
    db: Session = Depends(get_db),
):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    query = (
        db.query(VerificationReport)
        .join(RuleCommand, VerificationReport.rule_command_id == RuleCommand.id)
        .join(Rule, RuleCommand.rule_id == Rule.id)
        .filter(Rule.benchmark_id == benchmark_id)
    )

    if level:
        query = query.filter(VerificationReport.level == level)
    if result:
        query = query.filter(VerificationReport.result == result)

    reports = query.order_by(VerificationReport.run_at.desc()).all()
    return {
        "data": [VerificationReportResponse.model_validate(r) for r in reports],
        "total": len(reports),
        "message": "success",
    }


# ── Bulk Regenerate ──

@router.post("/{benchmark_id}/commands/bulk-regenerate")
async def bulk_regenerate_commands(
    benchmark_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    flagged_commands = (
        db.query(RuleCommand)
        .join(Rule)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.status == "flagged",
            RuleCommand.is_protected == False,  # noqa: E712
        )
        .all()
    )

    if not flagged_commands:
        raise HTTPException(status_code=400, detail="No flagged commands to regenerate")

    rule_ids = [cmd.rule_id for cmd in flagged_commands]

    async def _bulk_regenerate(rids: list[int]) -> None:
        from backend.database import SessionLocal
        from backend.ai.benchmark_ai import regenerate_command as ai_regenerate

        db_inner = SessionLocal()
        try:
            for rid in rids:
                rule = db_inner.query(Rule).filter(Rule.id == rid).first()
                if not rule or not rule.commands:
                    continue
                cmd = rule.commands
                if cmd.is_protected or cmd.status != "flagged":
                    continue

                bm = rule.benchmark
                if not bm:
                    continue

                history: list[dict] = []
                if cmd.previous_commands:
                    try:
                        history = json.loads(cmd.previous_commands)
                    except (json.JSONDecodeError, TypeError):
                        history = []

                from datetime import datetime, timezone
                history.append({
                    "audit_command": cmd.audit_command,
                    "expected_output_regex": cmd.expected_output_regex,
                    "flag_reason": cmd.flag_reason,
                    "source": cmd.source,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                try:
                    result = await ai_regenerate(
                        section_number=rule.section_number,
                        title=rule.title,
                        platform=bm.platform,
                        platform_family=bm.platform_family,
                        assessment_type=rule.assessment_type,
                        audit_description_raw=rule.audit_description_raw,
                        remediation_description_raw=rule.remediation_description_raw,
                        current_audit_command=cmd.audit_command,
                        current_expected_output_regex=cmd.expected_output_regex,
                        flag_reason=cmd.flag_reason or "Flagged for regeneration",
                        flag_error_output=cmd.flag_error_output,
                        previous_commands=history,
                    )
                except Exception:
                    logger.warning("Failed to regenerate command for rule %s", rid)
                    continue

                now = datetime.now(timezone.utc)
                cmd.audit_command = result.get("audit_command", cmd.audit_command)
                cmd.expected_output_regex = result.get("expected_output_regex", cmd.expected_output_regex)
                cmd.expected_output_description = result.get("expected_output_description", cmd.expected_output_description)
                cmd.remediation_command = result.get("remediation_command", cmd.remediation_command)
                cmd.remediation_description = result.get("remediation_description", cmd.remediation_description)
                cmd.source = "llm_regenerated"
                cmd.status = "generated"
                cmd.flag_reason = None
                cmd.flag_error_output = None
                cmd.flagged_at = None
                cmd.regeneration_count = (cmd.regeneration_count or 0) + 1
                cmd.last_regenerated_at = now
                cmd.previous_commands = json.dumps(history)
                cmd.updated_at = now
                db_inner.commit()
        except Exception:
            logger.exception("Bulk regeneration failed")
            db_inner.rollback()
        finally:
            db_inner.close()

    background_tasks.add_task(_bulk_regenerate, rule_ids)
    return {
        "message": f"Bulk regeneration started for {len(rule_ids)} commands",
        "benchmark_id": benchmark_id,
        "count": len(rule_ids),
    }


# ── Bulk Accept ──

@router.post("/{benchmark_id}/verify/bulk-accept")
def bulk_accept_commands(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    now = datetime.now(timezone.utc)

    updated = (
        db.query(RuleCommand)
        .join(Rule)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.status.in_(["generated", "pending_review"]),
            RuleCommand.is_protected == False,  # noqa: E712
        )
        .all()
    )

    count = 0
    for cmd in updated:
        cmd.status = "verified"
        cmd.verified_at = now
        cmd.verification_notes = "Bulk accepted by auditor"
        count += 1

    db.commit()
    return {"message": f"Accepted {count} commands", "count": count}


# ── Override Gate ──

@router.post("/{benchmark_id}/verify/override")
def override_verification_gate(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    benchmark.is_ready = True
    if benchmark.verification_status == "completed_with_issues":
        benchmark.verification_status = "overridden"
    db.commit()
    return {"message": "Benchmark marked as ready (verification overridden)", "benchmark_id": benchmark_id}


# ── Bulk Protect ──

@router.post("/{benchmark_id}/commands/bulk-protect")
def bulk_protect_commands(benchmark_id: int, db: Session = Depends(get_db)):
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    now = datetime.now(timezone.utc)

    verified_commands = (
        db.query(RuleCommand)
        .join(Rule)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.status == "verified",
            RuleCommand.is_protected.is_(False),
        )
        .all()
    )

    count = 0
    for cmd in verified_commands:
        cmd.is_protected = True
        cmd.protected_at = now
        cmd.protection_reason = "Bulk protected by auditor"
        cmd.updated_at = now
        count += 1

    db.commit()
    return {"message": f"Protected {count} commands", "protected_count": count}


# ── Phase 3: Validate & Correct (optional) ──

@router.post("/{benchmark_id}/validate")
async def start_validation(
    benchmark_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start Phase 3 validation — optional LLM review of generated commands."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if benchmark.phase2_status != "completed":
        raise HTTPException(status_code=400, detail="Phase 2 must be completed before validation")

    # Allow re-triggering from any state except active processing
    if benchmark.phase3_status == "processing":
        benchmark.phase3_status = "pending"
        db.commit()

    background_tasks.add_task(run_phase3, benchmark.id)
    return {"message": "Phase 3 validation started", "benchmark_id": benchmark_id}


@router.post("/{benchmark_id}/validate/pause")
def pause_validation(benchmark_id: int, db: Session = Depends(get_db)):
    """Pause an in-progress Phase 3 validation."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if benchmark.phase3_status != "processing":
        raise HTTPException(status_code=400, detail="Phase 3 is not currently running")
    phase3_request_pause(benchmark_id)
    return {"message": "Phase 3 pause requested", "benchmark_id": benchmark_id}


@router.get("/{benchmark_id}/validate/status", response_model=ValidateStatusResponse)
def get_validation_status(benchmark_id: int, db: Session = Depends(get_db)):
    """Get Phase 3 validation progress."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    stats: dict = {}
    if benchmark.phase3_stats:
        try:
            stats = json.loads(benchmark.phase3_stats)
        except (json.JSONDecodeError, TypeError):
            pass

    return ValidateStatusResponse(
        status=benchmark.phase3_status or "not_started",
        total=stats.get("total", 0),
        processed=stats.get("processed", 0),
        validated=stats.get("validated", 0),
        corrected=stats.get("corrected", 0),
        flagged=stats.get("flagged", 0),
    )


@router.get("/{benchmark_id}/validate/results", response_model=ValidationResultsResponse)
def get_validation_results(
    benchmark_id: int,
    status_filter: str | None = Query(None, description="Filter by: corrected, flagged, validated"),
    db: Session = Depends(get_db),
):
    """Get Phase 3 validation results with corrections."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    query = (
        db.query(RuleCommand, Rule)
        .join(Rule, RuleCommand.rule_id == Rule.id)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.validation_status.isnot(None),
        )
    )
    if status_filter:
        query = query.filter(RuleCommand.validation_status == status_filter)

    rows = query.order_by(Rule.section_number).all()

    items: list[ValidationResultItem] = []
    for cmd, rule in rows:
        corrections: list[ValidationCorrection] = []
        if cmd.validation_corrections:
            try:
                raw = json.loads(cmd.validation_corrections)
                corrections = [ValidationCorrection(**c) for c in raw]
            except (json.JSONDecodeError, TypeError):
                pass

        items.append(ValidationResultItem(
            rule_command_id=cmd.id,
            rule_id=rule.id,
            section_number=rule.section_number or "",
            title=rule.title or "",
            validation_status=cmd.validation_status,
            validation_confidence=cmd.validation_confidence,
            corrections=corrections,
            notes=cmd.validation_notes,
            audit_command=cmd.audit_command,
            expected_output_regex=cmd.expected_output_regex,
        ))

    return ValidationResultsResponse(
        data=items,
        total=len(items),
    )


@router.post("/{benchmark_id}/validate/apply/{rule_command_id}")
def apply_validation_correction(
    benchmark_id: int,
    rule_command_id: int,
    db: Session = Depends(get_db),
):
    """Apply LLM-suggested corrections for a specific rule command."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    try:
        cmd = phase3_apply(db, rule_command_id)
        return {"message": "Corrections applied", "rule_command_id": cmd.id, "status": cmd.validation_status}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{benchmark_id}/validate/dismiss/{rule_command_id}")
def dismiss_validation_correction(
    benchmark_id: int,
    rule_command_id: int,
    db: Session = Depends(get_db),
):
    """Dismiss LLM corrections for a specific rule command (keep original)."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    try:
        cmd = phase3_dismiss(db, rule_command_id)
        return {"message": "Corrections dismissed", "rule_command_id": cmd.id, "status": cmd.validation_status}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{benchmark_id}/validate/bulk-apply")
def bulk_apply_corrections(benchmark_id: int, db: Session = Depends(get_db)):
    """Apply all high-confidence corrections at once."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    commands = (
        db.query(RuleCommand)
        .join(Rule)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.validation_status == "corrected",
            RuleCommand.validation_confidence == "high",
            RuleCommand.validation_corrections.isnot(None),
        )
        .all()
    )

    count = 0
    for cmd in commands:
        try:
            phase3_apply(db, cmd.id)
            count += 1
        except (ValueError, Exception):
            continue

    return {"message": f"Applied corrections to {count} commands", "count": count}


@router.post("/{benchmark_id}/validate/bulk-dismiss")
def bulk_dismiss_corrections(benchmark_id: int, db: Session = Depends(get_db)):
    """Dismiss all pending corrections."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    now = datetime.now(timezone.utc)
    commands = (
        db.query(RuleCommand)
        .join(Rule)
        .filter(
            Rule.benchmark_id == benchmark_id,
            RuleCommand.validation_status.in_(["corrected", "flagged"]),
        )
        .all()
    )

    count = 0
    for cmd in commands:
        cmd.validation_status = "dismissed"
        cmd.updated_at = now
        count += 1

    db.commit()
    return {"message": f"Dismissed corrections for {count} commands", "count": count}


# ── Framework Coverage Dashboard ──

# Known framework families for categorization
FRAMEWORK_DEFINITIONS = {
    "NIST_800_53": {"name": "NIST 800-53", "category": "Government", "description": "Security and Privacy Controls for Federal Information Systems"},
    "NIST_800_171": {"name": "NIST 800-171", "category": "Government", "description": "Protecting Controlled Unclassified Information"},
    "NIST_CSF": {"name": "NIST CSF", "category": "Government", "description": "Cybersecurity Framework"},
    "HIPAA": {"name": "HIPAA", "category": "Healthcare", "description": "Health Insurance Portability and Accountability Act"},
    "PCI_DSS": {"name": "PCI-DSS", "category": "Financial", "description": "Payment Card Industry Data Security Standard"},
    "SOC_2": {"name": "SOC 2", "category": "Audit", "description": "Service Organization Control 2"},
    "GDPR": {"name": "GDPR", "category": "Privacy", "description": "General Data Protection Regulation"},
    "ISO_27001": {"name": "ISO 27001", "category": "International", "description": "Information Security Management"},
    "CIS_Controls": {"name": "CIS Controls", "category": "Best Practice", "description": "Center for Internet Security Controls"},
    "CIS_CSC": {"name": "CIS Controls", "category": "Best Practice", "description": "CIS Critical Security Controls"},
    "CMMC": {"name": "CMMC", "category": "Government", "description": "Cybersecurity Maturity Model Certification"},
    "MITRE_ATT&CK": {"name": "MITRE ATT&CK", "category": "Threat", "description": "Adversarial Tactics, Techniques & Common Knowledge"},
    "CCE": {"name": "CCE", "category": "Reference", "description": "Common Configuration Enumeration"},
    "CVE": {"name": "CVE", "category": "Vulnerability", "description": "Common Vulnerabilities and Exposures"},
}


@router.get("/{benchmark_id}/framework-coverage")
def get_framework_coverage(benchmark_id: int, db: Session = Depends(get_db)):
    """Get compliance framework coverage analysis for a benchmark.

    Analyzes framework_mappings across all rules and returns:
    - Per-framework coverage summary
    - Controls mapped per framework
    - Overall multi-framework coverage score
    """
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    rules = db.query(Rule).filter(Rule.benchmark_id == benchmark_id).all()
    total_rules = len(rules)

    if total_rules == 0:
        return {
            "benchmark_id": benchmark_id,
            "benchmark_name": benchmark.name,
            "total_rules": 0,
            "frameworks": [],
            "overall_score": 0,
        }

    # Aggregate framework mappings across all rules
    framework_data: dict[str, dict] = {}  # framework_key -> {controls, rule_count, rule_ids}

    for rule in rules:
        mappings = {}
        # Try framework_mappings column first
        if rule.framework_mappings:
            try:
                mappings = json.loads(rule.framework_mappings) if isinstance(rule.framework_mappings, str) else rule.framework_mappings
            except (json.JSONDecodeError, TypeError):
                pass

        # Also check references_json for additional mappings
        if rule.references_json and not mappings:
            try:
                refs = json.loads(rule.references_json) if isinstance(rule.references_json, str) else rule.references_json
                if isinstance(refs, dict):
                    mappings = refs
            except (json.JSONDecodeError, TypeError):
                pass

        for fw_key, controls in mappings.items():
            if not isinstance(controls, list):
                controls = [str(controls)]

            if fw_key not in framework_data:
                framework_data[fw_key] = {
                    "controls": set(),
                    "rule_count": 0,
                    "rule_ids": [],
                }

            framework_data[fw_key]["controls"].update(str(c) for c in controls)
            framework_data[fw_key]["rule_count"] += 1
            framework_data[fw_key]["rule_ids"].append(rule.id)

    # Build response
    frameworks = []
    rules_with_mappings = set()
    for fw_key, data in sorted(framework_data.items(), key=lambda x: x[1]["rule_count"], reverse=True):
        definition = FRAMEWORK_DEFINITIONS.get(fw_key, {})
        coverage_pct = round(data["rule_count"] / total_rules * 100, 1)
        rules_with_mappings.update(data["rule_ids"])

        frameworks.append({
            "key": fw_key,
            "name": definition.get("name", fw_key.replace("_", " ")),
            "category": definition.get("category", "Other"),
            "description": definition.get("description", ""),
            "controls_mapped": len(data["controls"]),
            "rules_covered": data["rule_count"],
            "coverage_percentage": coverage_pct,
            "sample_controls": sorted(data["controls"])[:10],
        })

    overall_score = round(len(rules_with_mappings) / total_rules * 100, 1) if total_rules > 0 else 0

    return {
        "benchmark_id": benchmark_id,
        "benchmark_name": benchmark.name,
        "total_rules": total_rules,
        "rules_with_framework_mappings": len(rules_with_mappings),
        "overall_score": overall_score,
        "framework_count": len(frameworks),
        "frameworks": frameworks,
    }


@router.get("/{benchmark_id}/framework-coverage/{framework_key}/rules")
def get_framework_rules(
    benchmark_id: int,
    framework_key: str,
    db: Session = Depends(get_db),
):
    """Get all rules mapped to a specific framework for a benchmark."""
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    rules = db.query(Rule).filter(Rule.benchmark_id == benchmark_id).all()
    matched_rules = []

    for rule in rules:
        mappings = {}
        if rule.framework_mappings:
            try:
                mappings = json.loads(rule.framework_mappings) if isinstance(rule.framework_mappings, str) else rule.framework_mappings
            except (json.JSONDecodeError, TypeError):
                pass
        if not mappings and rule.references_json:
            try:
                refs = json.loads(rule.references_json) if isinstance(rule.references_json, str) else rule.references_json
                if isinstance(refs, dict):
                    mappings = refs
            except (json.JSONDecodeError, TypeError):
                pass

        if framework_key in mappings:
            controls = mappings[framework_key]
            if not isinstance(controls, list):
                controls = [str(controls)]
            matched_rules.append({
                "rule_id": rule.id,
                "section_number": rule.section_number,
                "title": rule.title,
                "severity": rule.severity,
                "controls": controls,
            })

    definition = FRAMEWORK_DEFINITIONS.get(framework_key, {})
    return {
        "benchmark_id": benchmark_id,
        "framework_key": framework_key,
        "framework_name": definition.get("name", framework_key),
        "rules": matched_rules,
        "total": len(matched_rules),
    }

