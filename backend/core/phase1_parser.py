"""Phase 1: CIS PDF → structured rules using LLM extraction."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.ai.benchmark_ai import detect_benchmark_metadata, extract_rules_from_section
from backend.core.rule_categorizer import TAG_KEYWORDS, auto_tag_rule
from backend.database import SessionLocal
from backend.models.benchmark import Benchmark
from backend.models.rule import Rule
from backend.models.rule_tag import RuleTag

logger = logging.getLogger("auditforge.phase1")


def compute_pdf_hash(pdf_path: Path) -> str:
    """Compute SHA-256 hash of a PDF file."""
    sha256 = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def extract_text_from_pdf(pdf_path: Path) -> list[dict[str, Any]]:
    """Extract text from PDF, returning list of {page_number, text} dicts."""
    import fitz  # PyMuPDF

    pages: list[dict[str, Any]] = []
    doc = fitz.open(str(pdf_path))
    try:
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text("text")
            pages.append({"page_number": page_num + 1, "text": text})
    finally:
        doc.close()
    return pages


def extract_first_pages_text(pages: list[dict[str, Any]], n: int = 5) -> str:
    """Get concatenated text from first N pages."""
    texts = [p["text"] for p in pages[:n]]
    return "\n\n".join(texts)


def split_into_sections(pages: list[dict[str, Any]]) -> list[str]:
    """Split PDF pages into processable section chunks (~3-5 pages each).
    
    CIS PDFs have numbered sections (e.g., "1 Initial Setup", "2 Services").
    We split on major section boundaries. If no clear sections are detected,
    fall back to fixed page grouping.
    """
    all_text = "\n\n".join(p["text"] for p in pages)
    # Try to split on major section headings (top-level numbered sections)
    # Pattern: line starting with a single digit followed by a space and words
    section_pattern = re.compile(r"^(\d+(?:\.\d+)?)\s+[A-Z][^\n]{5,}", re.MULTILINE)
    matches = list(section_pattern.finditer(all_text))

    if len(matches) >= 3:
        # Split at major section boundaries
        sections: list[str] = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(all_text)
            chunk = all_text[start:end].strip()
            if len(chunk) > 100:  # Skip very short chunks
                sections.append(chunk)
        # If sections are too large, split them further
        result: list[str] = []
        max_chunk_size = 12000  # ~3-4 pages worth of text
        for section in sections:
            if len(section) > max_chunk_size:
                # Split large sections into smaller chunks
                words = section.split()
                current_chunk: list[str] = []
                current_size = 0
                for word in words:
                    current_chunk.append(word)
                    current_size += len(word) + 1
                    if current_size >= max_chunk_size:
                        result.append(" ".join(current_chunk))
                        current_chunk = []
                        current_size = 0
                if current_chunk:
                    result.append(" ".join(current_chunk))
            else:
                result.append(section)
        return result if result else [all_text]
    else:
        # Fallback: group pages in chunks of 4
        chunks: list[str] = []
        page_group: list[str] = []
        for i, page in enumerate(pages):
            page_group.append(page["text"])
            if len(page_group) >= 4:
                chunks.append("\n\n".join(page_group))
                page_group = []
        if page_group:
            chunks.append("\n\n".join(page_group))
        return chunks


def _deduplicate_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate rules based on section number."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for rule in rules:
        section = rule.get("section", "")
        if section and section not in seen:
            seen.add(section)
            unique.append(rule)
    return unique


async def run_phase1(benchmark_id: int, pdf_path: Path) -> None:
    """Execute Phase 1 parsing for a benchmark. Runs as a background task."""
    db = SessionLocal()
    try:
        benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
        if not benchmark:
            logger.error("Benchmark %d not found", benchmark_id)
            return

        benchmark.phase1_status = "processing"
        db.commit()

        # Step 1: Extract text from PDF
        logger.info("Phase 1: Extracting text from PDF for benchmark %d", benchmark_id)
        pages = extract_text_from_pdf(pdf_path)
        if not pages:
            benchmark.phase1_status = "failed"
            benchmark.notes = "Failed to extract text from PDF"
            db.commit()
            return

        # Step 2: Detect metadata from first pages
        logger.info("Phase 1: Detecting metadata for benchmark %d", benchmark_id)
        first_text = extract_first_pages_text(pages)
        try:
            metadata = await detect_benchmark_metadata(first_text)
        except Exception as exc:
            logger.error("Metadata detection failed: %s", exc)
            benchmark.phase1_status = "failed"
            benchmark.notes = f"Metadata detection failed: {exc}"
            db.commit()
            return

        benchmark.name = metadata.get("title", benchmark.name)
        benchmark.version = metadata.get("version", benchmark.version)
        benchmark.platform = metadata.get("platform", benchmark.platform)
        benchmark.platform_family = metadata.get("platform_family", benchmark.platform_family)
        db.commit()

        # Step 3: Split into sections
        logger.info("Phase 1: Splitting PDF into sections for benchmark %d", benchmark_id)
        sections = split_into_sections(pages)
        logger.info("Phase 1: Got %d sections to process", len(sections))

        # Step 4: Get category detection setting
        from backend.models.app_settings import AppSettings
        cat_setting = db.query(AppSettings).filter(AppSettings.key == "llm_category_detection").first()
        category_detection = cat_setting.value == "true" if cat_setting else True

        # Step 5: Process each section through LLM
        all_rules: list[dict[str, Any]] = []
        for i, section_text in enumerate(sections):
            logger.info("Phase 1: Processing section %d/%d for benchmark %d", i + 1, len(sections), benchmark_id)
            try:
                extracted = await extract_rules_from_section(section_text, category_detection)
                all_rules.extend(extracted)
            except Exception as exc:
                logger.warning("Failed to process section %d: %s", i + 1, exc)
                continue

        # Step 6: Deduplicate rules
        all_rules = _deduplicate_rules(all_rules)
        logger.info("Phase 1: Extracted %d unique rules for benchmark %d", len(all_rules), benchmark_id)

        # Step 7: Save rules and tags to database
        for rule_data in all_rules:
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
            db.flush()  # Get rule.id

            # Collect tags from LLM + keyword auto-tagger
            llm_categories: list[str] = rule_data.get("categories", [])
            keyword_tags = auto_tag_rule(
                rule.title or "",
                rule.description or "",
                rule.audit_description_raw or "",
                rule.remediation_description_raw or "",
            )
            # Deduplicate: merge LLM + keyword tags
            all_tags: set[str] = set()
            for tag in llm_categories:
                if isinstance(tag, str) and tag in TAG_KEYWORDS:
                    all_tags.add(tag)
            for tag in keyword_tags:
                all_tags.add(tag)

            for tag_id in all_tags:
                db.add(RuleTag(rule_id=rule.id, tag_id=tag_id, source="auto"))

        db.commit()

        # Step 8: Update benchmark
        benchmark.total_rules = len(all_rules)
        benchmark.phase1_status = "completed"
        db.commit()
        logger.info("Phase 1 completed for benchmark %d: %d rules extracted", benchmark_id, len(all_rules))

    except Exception as exc:
        logger.error("Phase 1 failed for benchmark %d: %s", benchmark_id, exc, exc_info=True)
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
