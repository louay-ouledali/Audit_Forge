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
ENRICHMENT_BATCH_SIZE = 3
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
    r"^contents$|"
    r"all\s+rights\s+reserved|"
    r"terms\s+of\s+use|"
    r"acknowledgements?|"
    r"^cis\s+(benchmarks?|center)\s",
    re.IGNORECASE | re.MULTILINE,
)

# Dotted leaders (e.g. "1.1.1 Ensure ........ 42") are checked separately
# so we can count them more carefully — pages with real rule *bodies* often
# mention "CIS Controls" which previously matched the appendix filter.
_DOTTED_LEADER_LINE = re.compile(r"\.{5,}")

_APPENDIX_INDICATORS = re.compile(
    r"^appendix\b|^annex\b|^references$|^bibliography$",
    re.IGNORECASE | re.MULTILINE,
)

# Pattern to detect a real CIS rule heading anywhere on a page
_RULE_HEADING_ON_PAGE = re.compile(
    r"^\d+\.\d+(?:\.\d+)*\s+",
    re.MULTILINE,
)

# Pattern to detect CIS field markers (indicates real rule content)
_FIELD_MARKER_ON_PAGE = re.compile(
    r"^(?:Profile\s+Applicability|Description|Rationale|Audit|Remediation|Default\s+Value)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _is_skippable_page(text: str, page_num: int) -> bool:
    """Return True if this page is cover, TOC, front-matter, or appendix."""
    stripped = text.strip()
    # Very short pages (footers only, blank)
    if len(stripped) < 60:
        return True
    # First few pages are almost always cover/TOC
    if page_num <= 2:
        return True

    has_rule_heading = bool(_RULE_HEADING_ON_PAGE.search(stripped))
    has_field_marker = bool(_FIELD_MARKER_ON_PAGE.search(stripped))
    has_rule_content = has_rule_heading or has_field_marker

    # TOC-style pages — skip only if there's no rule content
    if _TOC_INDICATORS.search(stripped) and not has_rule_content:
        return True

    # Pages that are mostly dotted leaders (TOC lines like "1.1.1 Ensure .. 42")
    # Count lines with dotted leaders vs total lines
    lines = stripped.splitlines()
    if len(lines) > 3:
        dotted_lines = sum(1 for ln in lines if _DOTTED_LEADER_LINE.search(ln))
        if dotted_lines / len(lines) > 0.4 and not has_field_marker:
            return True

    # Appendix / back-matter pages — skip only if there's no rule content
    if _APPENDIX_INDICATORS.search(stripped) and not has_rule_content:
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


# ────────────────── PDF text cleaning ──────────────────

# Common PDF extraction artifacts to remove before rule segmentation
_PAGE_NUMBER_LINE = re.compile(
    r"^\s*(?:Page\s+)?\d{1,4}\s*(?:\|.*)?$",  # "Page 42" or standalone "42" or "42 | CIS ..."
    re.MULTILINE,
)

_RUNNING_HEADER = re.compile(
    r"^(?:CIS\s+(?:Microsoft|Apple|Ubuntu|Debian|Red\s*Hat|SUSE|Oracle|Cisco|"
    r"Amazon|Google|Windows|macOS|Linux|Docker|Kubernetes|PostgreSQL|MySQL|"
    r"MongoDB|Apache|Nginx|IIS).*Benchmark.*v\d+\.\d+\.\d+.*$)",
    re.MULTILINE | re.IGNORECASE,
)

_EXCESSIVE_BLANK_LINES = re.compile(r"\n{4,}")


def _clean_pdf_text(text: str) -> str:
    """Remove common PDF extraction artefacts that break rule segmentation.

    - Standalone page numbers (e.g. "42", "Page 42")
    - Running headers/footers (e.g. "CIS Microsoft Windows 11 Benchmark v5.0.0")
    - Excessive blank lines collapsed to double newlines
    """
    text = _PAGE_NUMBER_LINE.sub("", text)
    text = _RUNNING_HEADER.sub("", text)
    text = _EXCESSIVE_BLANK_LINES.sub("\n\n", text)
    return text


# ────────────────── Regex-based rule segmentation ──────────────────

# CIS rule heading:  "1.1.1 Ensure …" or "18.9.4.2 (L1) Ensure …" or "5.1 (L2) Ensure …"
# Must have at least 2 numeric parts (X.Y) — chapter headers with only 2 parts
# are filtered out later by the no-field-marker and no-audit-remediation checks.
# Also handles profile markers like (L1), (L2), (BL), (NG), and (Automated)/(Manual).
# Allows optional leading whitespace (PDF extraction artifacts).
_RULE_HEADING = re.compile(
    r"^\s{0,4}"                           # allow small leading whitespace from PDF
    r"(\d{1,2}(?:\.\d{1,3}){1,})"        # section number with ≥2 levels
    r"\s+"                                # space after section
    r"(?:\((?:L[12]|BL|NG)\)\s+)?"       # optional profile marker like (L1)
    r"(?:\((?:Automated|Manual)\)\s+)?"   # optional assessment marker before title
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


# Heuristic score for how "real" a rule body looks.
# TOC entries, chapter intros, and noise score low; actual rules score high.
_FIELD_MARKER_BODY = re.compile(
    r"(?:^|\n)\s*(?:Profile\s+Applicability|Description|Rationale|Impact|"
    r"Audit|Remediation|Default\s+Value|References|CIS\s+Controls)"
    r"\s*:?\s*(?:$|\n)",
    re.IGNORECASE,
)


def _rule_body_score(body: str) -> int:
    """Score how much a body looks like a real CIS rule (higher = more real).

    Used to pick the richest version when a section number appears multiple
    times (TOC + real rule body).
    """
    score = 0
    # Count field markers present
    markers = len(_FIELD_MARKER_BODY.findall(body))
    score += markers * 10
    # Longer bodies are more likely to be real rules
    score += min(len(body) // 50, 20)
    # Penalise dotted leaders (TOC)
    dotted_lines = sum(1 for ln in body.splitlines() if _DOTTED_LEADER_LINE.search(ln))
    score -= dotted_lines * 5
    return score


# Regex that detects a CIS field marker at the start of a line
_TITLE_STOP_PATTERN = re.compile(
    r"^\s*(?:Profile\s+Applicability|Description|Rationale|Impact|"
    r"Audit|Remediation|Default\s+Value|References|CIS\s+Controls|"
    r"Additional\s+Information)\s*:?\s*$",
    re.IGNORECASE,
)

# Matches text that looks like a continuation of a truncated title.
# CIS titles follow the pattern: Ensure 'Setting Name' is set to 'Value'
# A continuation line will typically be short text that completes the sentence.
_TITLE_CONTINUATION_RE = re.compile(
    r"^[A-Za-z0-9'\"\(\)\-_.,/ ]+$",
)


def _extend_title_from_body(title: str, body: str) -> tuple[str, str]:
    """Extend a truncated CIS rule title by consuming continuation lines from body.

    CIS PDF extraction often puts the recommended value on a new line, truncating
    the title.  For example:
      Title line:  "Ensure 'Enforce password history' is set to '24 or more"
      Next line:   "password(s) remembered' (Automated)"

    This function detects incomplete titles (ending mid-quote, mid-sentence) and
    appends continuation lines from the body until the title is complete.

    Returns (extended_title, remaining_body).
    """
    if not body:
        return title, body

    # Heuristics for "title looks complete":
    # - Ends with a closing single quote followed by optional whitespace
    # - Ends with (Automated) or (Manual)
    # - Ends with a closing paren
    # If the title already looks complete, don't touch it.
    title_stripped = title.rstrip()
    if re.search(r"'\s*$", title_stripped):
        # Ends with closing quote — likely complete
        return title, body
    if re.search(r"\((?:Automated|Manual)\)\s*$", title_stripped):
        return title, body

    # Title appears truncated — try to grab continuation lines from body
    lines = body.split("\n")
    consumed = 0

    for line in lines:
        stripped_line = line.strip()

        # Stop at empty lines
        if not stripped_line:
            break

        # Stop at field markers (Profile Applicability, Description, etc.)
        if _TITLE_STOP_PATTERN.match(line):
            break

        # Stop at what looks like another section heading
        if re.match(r"^\d+\.\d+(?:\.\d+)*\s+", stripped_line):
            break

        # Stop if the line is too long (real body text, not a title fragment)
        if len(stripped_line) > 80:
            break

        # Stop if the line contains content that's clearly body text
        if re.search(r"(?:navigate|this\s+setting|registry|the\s+following|"
                      r"recommended\s+configuration|group\s+policy)\b",
                      stripped_line, re.IGNORECASE):
            break

        # Looks like a title continuation — append it
        title = title.rstrip() + " " + stripped_line
        consumed += 1

        # If we now have a complete-looking title, stop
        if re.search(r"'\s*(?:\((?:Automated|Manual)\))?\s*$", title):
            break
        if re.search(r"\((?:Automated|Manual)\)\s*$", title):
            break

        # Safety: don't consume more than 3 lines
        if consumed >= 3:
            break

    if consumed > 0:
        # Strip (Automated)/(Manual) from the extended title
        title = re.sub(r"\s*\((?:Automated|Manual)\)\s*$", "", title).strip()
        # Remove consumed lines from body
        body = "\n".join(lines[consumed:]).strip()

    return title, body


def _normalize_title(title: str) -> str:
    """Normalise a CIS rule title by stripping the leading 'Ensure' verb.

    CIS rules almost always start with *Ensure*, *Configure*, or *Verify*.
    The user prefers leaner titles, so we remove the leading verb when it
    adds no information.  The rest of the title is left unchanged.

    Examples
    --------
    >>> _normalize_title("Ensure 'Enforce password history' is set to '24'")
    "'Enforce password history' is set to '24'"
    >>> _normalize_title("Configure 'Audit Logon Events'")
    "'Audit Logon Events'"
    >>> _normalize_title("Verify 'Log on as a batch job' is set to 'Administrators'")
    "'Log on as a batch job' is set to 'Administrators'"
    """
    stripped = re.sub(
        r"^(?:Ensure|Configure|Verify)\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )
    # Capitalise first letter if it isn't a quote
    if stripped and stripped[0].islower() and stripped[0] != "'":
        stripped = stripped[0].upper() + stripped[1:]
    return stripped


def segment_rules_from_text(all_text: str) -> list[dict[str, str]]:
    """Split the full PDF text into individual rule text blocks.

    Returns list of dicts with keys 'section', 'title', 'body'.
    Filters out TOC entries and empty headings.
    """
    headings = list(_RULE_HEADING.finditer(all_text))
    if not headings:
        return []

    # First pass: collect all candidate rule blocks
    candidates: list[dict[str, str]] = []

    for idx, match in enumerate(headings):
        section = match.group(1)
        title = match.group(2).strip()
        # Strip trailing (Automated)/(Manual) from title if captured
        title = re.sub(r"\s*\((?:Automated|Manual)\)\s*$", "", title)
        start = match.end()
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(all_text)
        body = all_text[start:end].strip()

        # ── Fix truncated titles ──
        # CIS PDFs often wrap long titles across multiple lines.  The regex
        # captures only the first line.  We extend the title by consuming
        # continuation lines from the top of the body — lines that are NOT
        # a field marker, NOT another section heading, and NOT empty.
        title, body = _extend_title_from_body(title, body)

        # ── Normalise title (strip 'Ensure' / 'Configure' / 'Verify') ──
        title = _normalize_title(title)

        # ── Filter out obvious TOC entries and noise ──
        # Skip empty or very short bodies (TOC line items)
        if len(body) < 30:
            continue
        # Skip bodies that are mostly dots (TOC dotted leaders)
        non_ws = body.replace(" ", "").replace("\t", "")
        dots_ratio = non_ws.count(".") / max(len(non_ws), 1)
        if dots_ratio > 0.3 and len(body) < 200:
            continue
        # Must contain at least one CIS field marker to be a real rule.
        # Check both standalone-line markers AND inline markers (e.g. "Audit: ...")
        has_field_marker = bool(re.search(
            r"(?:^|\n)\s*(?:Profile\s+Applicability|Description|Audit|Remediation|"
            r"Default\s+Value|Rationale|Impact)\s*:?",
            body, re.IGNORECASE,
        ))
        if not has_field_marker:
            continue

        candidates.append({"section": section, "title": title, "body": body})

    # Second pass: deduplicate — keep the RICHEST version (most field markers + longest)
    best: dict[str, dict[str, str]] = {}
    for cand in candidates:
        section = cand["section"]
        existing = best.get(section)
        if existing is None:
            best[section] = cand
        else:
            # Keep whichever scores higher (more field markers, longer body)
            if _rule_body_score(cand["body"]) > _rule_body_score(existing["body"]):
                best[section] = cand

    return list(best.values())


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
    for line in refs_text.splitlines():
        line = line.strip()
        if line and len(line) > 2:
            references.append(line)

    # Parse CIS Controls separately (e.g. "v8  4.1, 4.8" or "v8\n4.1\n4.8")
    cis_controls: list[str] = []
    if cis_text:
        for line in cis_text.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("v") and len(line) <= 4:
                continue  # Skip version labels like "v8"
            # Extract control IDs like "4.1", "6.3", "16.8"
            ctrl_ids = re.findall(r"\b(\d{1,2}\.\d{1,2})\b", line)
            if ctrl_ids:
                cis_controls.extend(ctrl_ids)
            elif line and len(line) > 2:
                cis_controls.append(line)

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
        "cis_controls": cis_controls if cis_controls else None,
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
        all_text = _clean_pdf_text(all_text)
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
            cis_ctrls = rule_data.get("cis_controls")
            if isinstance(cis_ctrls, list):
                cis_ctrls = json.dumps(cis_ctrls)

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
                cis_controls=cis_ctrls,
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
