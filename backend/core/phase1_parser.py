"""Phase 1: CIS PDF → structured rules.

Uses a *hybrid* approach:
 1. Regex/heuristic extraction pulls deterministic fields (section, title,
    profile, audit, remediation, default value, references) straight from the
    PDF text — no LLM needed.
 2. LLM is used *only* for metadata detection (title, version, platform) and
    for the few fields that genuinely need judgement (severity, categories,
    assessment_type).

This makes parsing 10-100× faster and eliminates the truncated-JSON problem
that plagued the previous "send huge chunks to LLM" approach.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from backend.ai.benchmark_ai import detect_benchmark_metadata
from backend.core.exceptions import BenchmarkTooLargeError, EmptyBenchmarkError, PDFParseError
from backend.core.rule_categorizer import TAG_KEYWORDS, auto_tag_rule
from backend.database import SessionLocal
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_tag import RuleTag

logger = logging.getLogger("auditforge.phase1")

# Maximum PDF file size in bytes (200 MB)
MAX_PDF_SIZE_BYTES = 200 * 1024 * 1024
MAX_PDF_PAGES = 5000

# How many rules to send per LLM call for severity/category enrichment
ENRICHMENT_BATCH_SIZE = 10
LLM_CALL_COOLDOWN = 2.0

# ────────────────────────── PDF helpers ──────────────────────────


def compute_pdf_hash(pdf_path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def validate_pdf_file(pdf_path: Path) -> None:
    if not pdf_path.exists():
        raise PDFParseError(f"PDF file not found: {pdf_path}")
    if not pdf_path.is_file():
        raise PDFParseError(f"Path is not a file: {pdf_path}")
    file_size = pdf_path.stat().st_size
    if file_size == 0:
        raise PDFParseError("PDF file is empty (0 bytes)")
    if file_size > MAX_PDF_SIZE_BYTES:
        raise BenchmarkTooLargeError(
            f"PDF too large ({file_size / 1024 / 1024:.1f} MB). Max {MAX_PDF_SIZE_BYTES / 1024 / 1024:.0f} MB"
        )


def extract_text_from_pdf(pdf_path: Path) -> list[dict[str, Any]]:
    import fitz
    validate_pdf_file(pdf_path)
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        raise PDFParseError(f"Failed to open PDF: {exc}", detail=str(exc)) from exc

    pages: list[dict[str, Any]] = []
    try:
        if len(doc) > MAX_PDF_PAGES:
            raise BenchmarkTooLargeError(f"PDF has {len(doc)} pages (limit {MAX_PDF_PAGES})")
        if len(doc) == 0:
            raise PDFParseError("PDF contains no pages")
        for i in range(len(doc)):
            try:
                text = doc.load_page(i).get_text("text")
            except Exception:
                text = ""
            pages.append({"page_number": i + 1, "text": text})
    finally:
        doc.close()
    return pages


def extract_first_pages_text(pages: list[dict[str, Any]], n: int = 5) -> str:
    return "\n\n".join(p["text"] for p in pages[:n])


# ────────────────────────── Page classification ──────────────────────────

# Patterns that indicate a page is a cover / TOC / front-matter page
_TOC_INDICATORS = re.compile(
    r"table\s+of\s+contents|"
    r"\.{4,}|"  # dotted leaders in TOC
    r"^contents$|"
    r"all\s+rights\s+reserved|"
    r"terms\s+of\s+use|"
    r"acknowledgements?|"
    r"^cis\s+(benchmarks?|center)\s",
    re.IGNORECASE | re.MULTILINE,
)

_APPENDIX_INDICATORS = re.compile(
    r"^appendix\b|^annex\b|^cis\s+controls|^references$|^bibliography$",
    re.IGNORECASE | re.MULTILINE,
)


def _is_skippable_page(text: str, page_num: int) -> bool:
    """Return True if this page is cover, TOC, front-matter, or appendix."""
    stripped = text.strip()
    # Very short pages (footers only, blank)
    if len(stripped) < 80:
        return True
    # First few pages are almost always cover/TOC
    if page_num <= 2:
        return True
    # TOC-style pages
    if _TOC_INDICATORS.search(stripped):
        # But only if the page does NOT contain an actual rule heading
        if not re.search(r"^\d+\.\d+(?:\.\d+)+\s+", stripped, re.MULTILINE):
            return True
    # Appendix / back-matter pages
    if _APPENDIX_INDICATORS.search(stripped):
        if not re.search(r"^\d+\.\d+(?:\.\d+)+\s+", stripped, re.MULTILINE):
            return True
    return False


def filter_content_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove cover, TOC, intro, appendix pages.  Keep only rule-bearing pages."""
    content: list[dict[str, Any]] = []
    for p in pages:
        if not _is_skippable_page(p["text"], p["page_number"]):
            content.append(p)
    logger.info(
        "Page filter: %d/%d pages kept (skipped cover/TOC/appendix)",
        len(content), len(pages),
    )
    return content


# ────────────────── Regex-based rule segmentation ──────────────────

# CIS rule heading:  "1.1.1 Ensure …" or "18.9.4.2 (L1) Ensure …"
# Must have at least 3 numeric parts (X.Y.Z) to distinguish from chapter headings.
_RULE_HEADING = re.compile(
    r"^(\d{1,2}(?:\.\d{1,3}){2,})\s+"   # section number with ≥3 levels
    r"(?:\((?:L[12]|BL|NG)\)\s+)?"       # optional profile marker like (L1)
    r"(.+)",                              # title text
    re.MULTILINE,
)

# Sub-section markers inside a single rule
_FIELD_MARKERS = re.compile(
    r"^(Profile\s+Applicability|Description|Rationale|Impact|"
    r"Audit|Remediation|Default\s+Value|References|"
    r"CIS\s+Controls|Additional\s+Information)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def segment_rules_from_text(all_text: str) -> list[dict[str, str]]:
    """Split the full PDF text into individual rule text blocks.

    Returns list of dicts with keys 'section', 'title', 'body'.
    Filters out TOC entries and empty headings.
    """
    headings = list(_RULE_HEADING.finditer(all_text))
    if not headings:
        return []

    rules: list[dict[str, str]] = []
    for idx, match in enumerate(headings):
        section = match.group(1)
        title = match.group(2).strip()
        start = match.end()
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(all_text)
        body = all_text[start:end].strip()

        # ── Filter out TOC entries and noise ──
        # Skip empty or very short bodies (TOC line items)
        if len(body) < 80:
            continue
        # Skip bodies that are mostly dots (TOC dotted leaders)
        dots_ratio = body.count(".") / max(len(body), 1)
        if dots_ratio > 0.3:
            continue
        # Must contain at least one CIS field marker to be a real rule
        if not re.search(
            r"Profile Applicability|Description|Audit|Remediation",
            body, re.IGNORECASE,
        ):
            continue

        rules.append({"section": section, "title": title, "body": body})
    return rules


def _extract_field(body: str, start_marker: str, end_markers: list[str]) -> str:
    """Extract text between start_marker and the next end_marker.

    Handles both 'Marker:' on its own line and 'Marker:' followed by text.
    """
    # First try: marker as a standalone line
    pattern = re.compile(
        rf"^{start_marker}\s*:?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    m = pattern.search(body)
    if not m:
        # Second try: marker followed by text on the same line
        pattern2 = re.compile(
            rf"^{start_marker}\s*:\s*(.+)",
            re.IGNORECASE | re.MULTILINE,
        )
        m2 = pattern2.search(body)
        if not m2:
            return ""
        # Found inline — extract from after ":" to next marker
        text_start = m2.start() + len(m2.group(0)) - len(m2.group(1))
        m = m2  # use for position reference below
    else:
        text_start = m.end()

    # Find the next field marker
    next_pos = len(body)
    for em in end_markers:
        em_pattern = re.compile(
            rf"^{em}\s*:?\s*$|^{em}\s*:\s",
            re.IGNORECASE | re.MULTILINE,
        )
        em_match = em_pattern.search(body, text_start)
        if em_match and em_match.start() < next_pos:
            next_pos = em_match.start()
    return body[text_start:next_pos].strip()


_ALL_FIELD_NAMES = [
    "Profile Applicability", "Description", "Rationale", "Impact",
    "Audit", "Remediation", "Default Value", "References",
    "CIS Controls", "Additional Information",
]


def parse_rule_fields(raw: dict[str, str]) -> dict[str, Any]:
    """Parse a raw rule block into structured fields using regex only (no LLM)."""
    body = raw["body"]
    section = raw["section"]
    title = raw["title"]

    # Profile Applicability
    profile_text = _extract_field(body, "Profile Applicability", _ALL_FIELD_NAMES)
    profiles: list[str] = []
    if profile_text:
        for line in profile_text.splitlines():
            line = line.strip().lstrip("•-● ")
            if line and len(line) > 3:
                profiles.append(line)

    # Description
    description = _extract_field(body, "Description", _ALL_FIELD_NAMES)

    # Rationale
    rationale = _extract_field(body, "Rationale", _ALL_FIELD_NAMES)

    # Audit
    audit = _extract_field(body, "Audit", _ALL_FIELD_NAMES)

    # Remediation
    remediation = _extract_field(body, "Remediation", _ALL_FIELD_NAMES)

    # Default Value
    default_value = _extract_field(body, "Default Value", _ALL_FIELD_NAMES) or None

    # References / CIS Controls
    refs_text = _extract_field(body, "References", _ALL_FIELD_NAMES)
    cis_text = _extract_field(body, "CIS Controls", _ALL_FIELD_NAMES)
    references: list[str] = []
    for line in (refs_text + "\n" + cis_text).splitlines():
        line = line.strip()
        if line and len(line) > 2:
            references.append(line)

    # Assessment type — check for "(Automated)" or "(Manual)" in title or body
    assessment_type = "automated"
    if re.search(r"\bmanual\b", title, re.IGNORECASE) or re.search(r"\(Manual\)", body[:200]):
        assessment_type = "manual"

    # Severity heuristic based on keywords
    severity = _estimate_severity(title, description, audit)

    # Categories from keyword auto-tagger
    categories: list[str] = []

    return {
        "section": section,
        "title": re.sub(r"\s*\((Automated|Manual)\)\s*", "", title).strip(),
        "description": description,
        "rationale": rationale,
        "profile_applicability": profiles,
        "assessment_type": assessment_type,
        "audit_description_raw": audit,
        "remediation_description_raw": remediation,
        "default_value": default_value,
        "references": references,
        "severity": severity,
        "categories": categories,
    }


def _estimate_severity(title: str, description: str, audit: str) -> str:
    """Heuristic severity based on keywords in the rule text."""
    combined = (title + " " + description + " " + audit).lower()
    critical_kw = [
        "root access", "remote code", "privilege escalation", "disable firewall",
        "no authentication", "world-writable", "unauthenticated",
    ]
    high_kw = [
        "password", "encrypt", "ssh", "firewall", "audit log", "sudo",
        "admin", "tls", "certificate", "access control", "selinux", "apparmor",
    ]
    low_kw = [
        "banner", "motd", "ntp", "time synchronization", "hostname",
    ]
    for kw in critical_kw:
        if kw in combined:
            return "critical"
    for kw in high_kw:
        if kw in combined:
            return "high"
    for kw in low_kw:
        if kw in combined:
            return "low"
    return "medium"


# ────────────────── Main Phase 1 pipeline ──────────────────


def _deduplicate_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate rules by section number, keeping the richest version."""
    best: dict[str, dict[str, Any]] = {}
    for rule in rules:
        section = rule.get("section", "")
        if not section:
            continue
        existing = best.get(section)
        if existing is None:
            best[section] = rule
        else:
            # Keep the version with more audit content
            new_len = len(rule.get("audit_description_raw", "") or "")
            old_len = len(existing.get("audit_description_raw", "") or "")
            if new_len > old_len:
                best[section] = rule
    return list(best.values())


async def run_phase1(benchmark_id: int, pdf_path: Path) -> None:
    """Execute Phase 1 parsing for a benchmark.  Runs as a background task.

    New approach:
      1. Extract PDF text
      2. Classify & skip title/TOC/appendix pages
      3. Detect metadata via LLM (1 call)
      4. Segment individual rules via regex (no LLM)
      5. Parse each rule's fields via regex (no LLM)
      6. Save to DB
    """
    db = SessionLocal()
    try:
        benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
        if not benchmark:
            logger.error("Benchmark %d not found", benchmark_id)
            return

        benchmark.phase1_status = "processing"
        db.commit()

        # ── Step 1: Extract text ──
        logger.info("[Phase1 B%d] Extracting PDF text …", benchmark_id)
        try:
            pages = extract_text_from_pdf(pdf_path)
        except (PDFParseError, BenchmarkTooLargeError) as exc:
            benchmark.phase1_status = "failed"
            benchmark.notes = str(exc)
            db.commit()
            return

        total_chars = sum(len(p.get("text", "")) for p in pages)
        if total_chars < 100:
            benchmark.phase1_status = "failed"
            benchmark.notes = "PDF has no extractable text (may be scanned/OCR needed)."
            db.commit()
            return

        logger.info("[Phase1 B%d] %d pages, %d chars total", benchmark_id, len(pages), total_chars)

        # ── Step 2: Metadata via LLM (only LLM call in the pipeline) ──
        logger.info("[Phase1 B%d] Detecting metadata via LLM …", benchmark_id)
        first_text = extract_first_pages_text(pages, n=5)
        try:
            metadata = await detect_benchmark_metadata(first_text)
        except Exception as exc:
            logger.error("[Phase1 B%d] Metadata detection failed: %s", benchmark_id, exc)
            metadata = {
                "title": "Unknown Benchmark", "version": "unknown",
                "platform": "unknown", "platform_family": "other", "profiles": [],
            }

        benchmark.name = metadata.get("title", benchmark.name)
        benchmark.version = metadata.get("version", benchmark.version)
        benchmark.platform = metadata.get("platform", benchmark.platform)
        benchmark.platform_family = metadata.get("platform_family", benchmark.platform_family)
        db.commit()
        logger.info(
            "[Phase1 B%d] Metadata: %s v%s (%s/%s)",
            benchmark_id, benchmark.name, benchmark.version,
            benchmark.platform, benchmark.platform_family,
        )

        # ── Step 3: Segment individual rules via regex ──
        all_text = "\n\n".join(p["text"] for p in pages)
        raw_rules = segment_rules_from_text(all_text)
        logger.info("[Phase1 B%d] Regex segmenter found %d rule headings", benchmark_id, len(raw_rules))

        if not raw_rules:
            benchmark.phase1_status = "completed"
            benchmark.total_rules = 0
            benchmark.notes = (
                "No CIS-formatted rules found. The PDF may use a non-standard "
                "format or lack numbered rule sections (X.Y.Z)."
            )
            db.commit()
            logger.warning("[Phase1 B%d] Zero rule headings found", benchmark_id)
            return

        # ── Step 5: Parse each rule's fields (pure regex, no LLM) ──
        parsed_rules: list[dict[str, Any]] = []
        for raw in raw_rules:
            try:
                parsed = parse_rule_fields(raw)
                # Skip rules that have no audit and no remediation (likely chapter headers)
                if not parsed["audit_description_raw"] and not parsed["remediation_description_raw"]:
                    continue
                parsed_rules.append(parsed)
            except Exception as exc:
                logger.warning("[Phase1 B%d] Failed to parse rule %s: %s", benchmark_id, raw.get("section"), exc)

        parsed_rules = _deduplicate_rules(parsed_rules)
        logger.info("[Phase1 B%d] Parsed %d valid rules (with audit/remediation)", benchmark_id, len(parsed_rules))

        if not parsed_rules:
            benchmark.phase1_status = "completed"
            benchmark.total_rules = 0
            benchmark.notes = "Rule headings found but none had audit/remediation content."
            db.commit()
            return

        # ── Step 6: Save to database ──
        for rule_data in parsed_rules:
            profile_app = rule_data.get("profile_applicability", [])
            if isinstance(profile_app, list):
                profile_app = json.dumps(profile_app)
            refs = rule_data.get("references", [])
            if isinstance(refs, list):
                refs = json.dumps(refs)

            rule = Rule(
                benchmark_id=benchmark_id,
                section_number=rule_data.get("section", ""),
                title=rule_data.get("title", ""),
                description=rule_data.get("description"),
                rationale=rule_data.get("rationale"),
                profile_applicability=profile_app,
                assessment_type=rule_data.get("assessment_type"),
                default_value=rule_data.get("default_value"),
                references_json=refs,
                audit_description_raw=rule_data.get("audit_description_raw"),
                remediation_description_raw=rule_data.get("remediation_description_raw"),
                severity=rule_data.get("severity", "medium"),
                enabled=True,
            )
            db.add(rule)
            db.flush()

            # Auto-tag
            keyword_tags = auto_tag_rule(
                rule.title or "", rule.description or "",
                rule.audit_description_raw or "", rule.remediation_description_raw or "",
            )
            for tag_id in keyword_tags:
                db.add(RuleTag(rule_id=rule.id, tag_id=tag_id, source="auto"))

        db.commit()

        benchmark.total_rules = len(parsed_rules)
        benchmark.phase1_status = "completed"
        db.commit()
        logger.info(
            "[Phase1 B%d] ✓ Completed: %d rules extracted and saved",
            benchmark_id, len(parsed_rules),
        )

    except Exception as exc:
        logger.error("[Phase1 B%d] FAILED: %s", benchmark_id, exc, exc_info=True)
        db.rollback()
        try:
            benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
            if benchmark:
                benchmark.phase1_status = "failed"
                benchmark.notes = str(exc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
