"""Severity enricher — cross-benchmark matching + AI fallback.

When importing from tools like Nessus that don't export severity, all findings
land at "medium" by default.  This module fixes that in two phases:

Phase 1 — **Cross-benchmark matching**
    Find the closest pre-loaded benchmark (same platform family) and copy
    severity, commands, and intelligence metadata from its rules into the
    imported rules, matching by section_number.

Phase 2 — **AI severity fallback**
    For imported rules that still lack a meaningful severity (no matching
    preloaded rule), call the LLM to classify each rule's severity based on
    its title and description.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.benchmark import Benchmark
from backend.models.finding import Finding
from backend.models.rule import Rule
from backend.models.rule_command import RuleCommand

logger = logging.getLogger("auditforge.importers.severity_enricher")


# ═══════════════════════════════════════════════════════════════════════════════
#  Data classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EnrichmentResult:
    """Statistics from a severity enrichment run."""

    preloaded_benchmark_id: int | None = None
    preloaded_benchmark_name: str = ""
    rules_enriched_from_preloaded: int = 0
    commands_copied: int = 0
    rules_enriched_by_ai: int = 0
    rules_unchanged: int = 0
    severity_distribution: dict[str, int] = field(default_factory=dict)
    findings_updated: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "preloaded_benchmark_id": self.preloaded_benchmark_id,
            "preloaded_benchmark_name": self.preloaded_benchmark_name,
            "rules_enriched_from_preloaded": self.rules_enriched_from_preloaded,
            "commands_copied": self.commands_copied,
            "rules_enriched_by_ai": self.rules_enriched_by_ai,
            "rules_unchanged": self.rules_unchanged,
            "severity_distribution": self.severity_distribution,
            "findings_updated": self.findings_updated,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════════════════

def enrich_imported_benchmark(
    benchmark_id: int,
    db: Session,
    *,
    scan_id: int | None = None,
    use_ai_fallback: bool = True,
) -> EnrichmentResult:
    """Enrich an imported benchmark's rules with severity + commands.

    Parameters
    ----------
    benchmark_id : int
        The imported benchmark whose rules need enrichment.
    db : Session
        Active SQLAlchemy session (caller manages commit/rollback).
    scan_id : int | None
        If provided, also update Finding.severity for findings in this scan.
    use_ai_fallback : bool
        If True, assign AI-based severity to rules that couldn't be matched
        against any preloaded benchmark.

    Returns
    -------
    EnrichmentResult
        Statistics about what was enriched and how.
    """
    result = EnrichmentResult()

    # Load the imported benchmark
    benchmark = db.query(Benchmark).filter(Benchmark.id == benchmark_id).first()
    if not benchmark:
        logger.warning("Benchmark %d not found — skipping enrichment", benchmark_id)
        return result

    # Skip enrichment for curated benchmarks (they already have proper severities)
    if benchmark.source in ("preloaded", "user_imported"):
        logger.debug("Benchmark %d is curated (%s) — skipping enrichment", benchmark_id, benchmark.source)
        return result

    # ── Phase 1: Cross-benchmark matching ─────────────────────────────────
    closest = _find_closest_preloaded(benchmark, db)
    if closest:
        result.preloaded_benchmark_id = closest.id
        result.preloaded_benchmark_name = closest.name
        logger.info(
            "Enriching benchmark %d (%s) from preloaded %d (%s v%s)",
            benchmark_id, benchmark.name,
            closest.id, closest.name, closest.version,
        )
        enriched, commands_copied = _copy_from_preloaded(
            benchmark_id, closest.id, db,
        )
        result.rules_enriched_from_preloaded = enriched
        result.commands_copied = commands_copied
    else:
        logger.info(
            "No close preloaded benchmark found for %d (%s, family=%s)",
            benchmark_id, benchmark.name, benchmark.platform_family,
        )

    # ── Phase 2: AI severity fallback ─────────────────────────────────────
    if use_ai_fallback:
        still_medium = (
            db.query(Rule)
            .filter(
                Rule.benchmark_id == benchmark_id,
                Rule.severity == "medium",
            )
            .all()
        )
        if still_medium:
            ai_enriched = _enrich_severity_with_ai(still_medium, db)
            result.rules_enriched_by_ai = ai_enriched

    # ── Count remaining unchanged rules ───────────────────────────────────
    result.rules_unchanged = (
        db.query(func.count(Rule.id))
        .filter(Rule.benchmark_id == benchmark_id, Rule.severity == "medium")
        .scalar()
        or 0
    )

    # ── Build severity distribution ───────────────────────────────────────
    severity_rows = (
        db.query(Rule.severity, func.count(Rule.id))
        .filter(Rule.benchmark_id == benchmark_id)
        .group_by(Rule.severity)
        .all()
    )
    result.severity_distribution = {sev: cnt for sev, cnt in severity_rows}

    # ── Phase 3: Sync Finding.severity with enriched Rule.severity ────────
    if scan_id:
        result.findings_updated = _sync_finding_severities(scan_id, benchmark_id, db)

    db.flush()
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 1 — Cross-benchmark matching
# ═══════════════════════════════════════════════════════════════════════════════

def _find_closest_preloaded(
    imported: Benchmark,
    db: Session,
) -> Benchmark | None:
    """Find the closest preloaded benchmark by platform family + product name.

    Strategy:
    1. Filter preloaded benchmarks by the same platform_family.
    2. Extract the product base (e.g. "Windows Server") from both the imported
       benchmark name and each candidate.
    3. Among candidates with the same product base, pick the one whose version
       number is closest (prefer same or newer over older).
    """
    # Get all curated benchmarks in the same family.
    # These can be source="preloaded" OR source="user_imported" (both contain
    # curated rules with proper severities).  We exclude only benchmarks that
    # were themselves reconstructed from Nessus imports.
    family = (imported.platform_family or "").lower()
    if not family:
        return None

    excluded_sources = {"nessus_reconstructed", "imported"}
    preloaded = (
        db.query(Benchmark)
        .filter(
            func.lower(Benchmark.platform_family) == family,
            Benchmark.status != "deleted",
            Benchmark.is_ready == True,  # noqa: E712
            Benchmark.id != imported.id,  # Don't match against self
            ~Benchmark.source.in_(excluded_sources),
        )
        .all()
    )
    if not preloaded:
        return None

    imported_product = _extract_product_info(imported.name)
    logger.debug("Imported product info: %s", imported_product)

    # Score each candidate
    scored: list[tuple[float, Benchmark]] = []
    for candidate in preloaded:
        cand_product = _extract_product_info(candidate.name)
        score = _product_similarity(imported_product, cand_product)
        if score > 0:
            scored.append((score, candidate))

    if not scored:
        # No product-level match — just return the overall closest by family
        # This handles cases where the import is "Windows Server 2012 R2"
        # but we still want to match ANY Windows Server preloaded benchmark
        server_candidates = [
            b for b in preloaded
            if _is_same_product_line(imported.name, b.name)
        ]
        if server_candidates:
            # Pick the oldest (closest to older imports) or newest depending on proximity
            imp_year = _extract_year(imported.name)
            if imp_year:
                best = min(server_candidates, key=lambda b: abs(imp_year - (_extract_year(b.name) or 9999)))
                return best
            return server_candidates[0]
        return None

    # Best = highest score
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


@dataclass
class _ProductInfo:
    """Parsed product information from a benchmark name."""
    raw_name: str = ""
    product_base: str = ""    # e.g. "Windows Server", "Windows 11", "Red Hat Enterprise Linux"
    version_number: int = 0   # e.g. 2019, 2022, 9, 11
    variant: str = ""         # e.g. "Enterprise", "Stand-alone", "R2"


def _extract_product_info(name: str) -> _ProductInfo:
    """Parse a benchmark name into product components.

    Examples:
        "CIS Microsoft Windows Server 2019 Benchmark" → base="Windows Server", num=2019
        "CIS Microsoft Windows 11 Enterprise Benchmark" → base="Windows 11", num=11
        "CIS Red Hat Enterprise Linux 9 Benchmark" → base="Red Hat Enterprise Linux", num=9
        "CIS PostgreSQL 16 Benchmark" → base="PostgreSQL", num=16
    """
    info = _ProductInfo(raw_name=name)

    # Strip common prefixes/suffixes
    cleaned = re.sub(
        r"^(?:CIS|NIST|STIG|DISA)\s+(?:Microsoft\s+)?",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"\s+Benchmark\s*$", "", cleaned, flags=re.IGNORECASE).strip()

    # Try to extract: product_base + version_number + optional variant
    # Pattern: "Windows Server 2019", "Windows 11 Enterprise", "Red Hat Enterprise Linux 9"
    m = re.match(
        r"^(.*?)\s+(\d{1,4})(?:\s+(R\d+|Enterprise|Stand-alone|LTS|\.[\d.]+))?\s*$",
        cleaned,
        re.IGNORECASE,
    )
    if m:
        info.product_base = m.group(1).strip()
        info.version_number = int(m.group(2))
        info.variant = (m.group(3) or "").strip()
    else:
        # Fallback: entire cleaned name is the product
        info.product_base = cleaned
        # Try to extract any number
        nums = re.findall(r"\d+", cleaned)
        if nums:
            info.version_number = int(nums[-1])

    return info


def _product_similarity(a: _ProductInfo, b: _ProductInfo) -> float:
    """Score how similar two product infos are (0 = unrelated, higher = better).

    Matching logic:
    - Same product base (normalized) → base score 100
    - Version proximity bonus: closer versions → higher score
    - Same variant → small bonus
    """
    base_a = a.product_base.lower().strip()
    base_b = b.product_base.lower().strip()

    # Must have the same base product
    if base_a != base_b:
        # Try a more lenient comparison: one contains the other
        # But only if one is not a subset that changes the product identity
        # e.g. "Windows Server" ≠ "Windows" (different product lines)
        if "server" in base_a and "server" not in base_b:
            return 0.0
        if "server" in base_b and "server" not in base_a:
            return 0.0
        if base_a not in base_b and base_b not in base_a:
            # Use word-boundary matching to avoid partial matches (e.g. "win" in "windows")
            import re as _re
            if (not _re.search(rf'\b{_re.escape(base_a)}\b', base_b)
                    and not _re.search(rf'\b{_re.escape(base_b)}\b', base_a)):
                return 0.0

    score = 100.0

    # Version proximity: closer = better (max 50 bonus for exact match)
    if a.version_number and b.version_number:
        distance = abs(a.version_number - b.version_number)
        # For year-based versions (2019, 2022, etc.), distance is in years
        # For simple versions (9, 10, 11), distance is in major versions
        if a.version_number > 100:  # Year-based
            version_bonus = max(0, 50 - distance * 5)  # -5 per year apart
        else:  # Simple numeric
            version_bonus = max(0, 50 - distance * 10)  # -10 per major version
        score += version_bonus
    else:
        score += 10  # Small bonus for generic match

    # Variant match bonus
    if a.variant and b.variant and a.variant.lower() == b.variant.lower():
        score += 10

    return score


def _is_same_product_line(name_a: str, name_b: str) -> bool:
    """Check if two benchmark names refer to the same product line.

    e.g. "Windows Server 2012 R2" and "Windows Server 2019" → True
         "Windows Server 2019" and "Windows 11 Enterprise" → False
    """
    patterns = [
        r"Windows\s+Server",
        r"Windows\s+\d+",
        r"Red\s+Hat\s+Enterprise\s+Linux",
        r"Ubuntu\s+Linux",
        r"PostgreSQL",
        r"SQL\s+Server",
        r"MongoDB",
        r"ESXi",
        r"Palo\s+Alto",
        r"FortiGate",
        r"NGINX",
        r"Apache\s+HTTP",
        r"Apache\s+Tomcat",
        r"Cisco\s+ASA",
        r"Check\s+Point",
        r"Juniper",
        r"Cassandra",
        r"SharePoint",
        r"Oracle\s+Database",
        r"Oracle\s+MySQL",
        r"BIND\s+DNS",
        r"pfSense",
    ]
    for pattern in patterns:
        a_match = bool(re.search(pattern, name_a, re.IGNORECASE))
        b_match = bool(re.search(pattern, name_b, re.IGNORECASE))
        if a_match and b_match:
            return True
        if a_match != b_match:
            return False
    return False


def _extract_year(name: str) -> int | None:
    """Extract a year (2000-2099) or major version from a benchmark name."""
    # Try year first (e.g., "Server 2019")
    m = re.search(r"\b(20\d{2})\b", name)
    if m:
        return int(m.group(1))
    # Try major version (e.g., "Linux 9", "ESXi 8")
    m = re.search(r"\b(\d{1,3})\b(?!\.)", name)
    if m:
        return int(m.group(1))
    return None


def _copy_from_preloaded(
    imported_benchmark_id: int,
    preloaded_benchmark_id: int,
    db: Session,
) -> tuple[int, int]:
    """Copy severity + intelligence + commands from preloaded rules to imported rules.

    Matches rules by section_number.  Only copies data into imported rules that
    currently have default/empty values.

    Returns
    -------
    tuple[int, int]
        (rules_enriched, commands_copied)
    """
    # Load preloaded rules with their commands, indexed by section_number
    preloaded_rules = (
        db.query(Rule)
        .filter(Rule.benchmark_id == preloaded_benchmark_id)
        .all()
    )
    preloaded_map: dict[str, Rule] = {}
    for pr in preloaded_rules:
        if pr.section_number:
            preloaded_map[pr.section_number] = pr

    if not preloaded_map:
        return 0, 0

    # Load imported rules
    imported_rules = (
        db.query(Rule)
        .filter(Rule.benchmark_id == imported_benchmark_id)
        .all()
    )

    rules_enriched = 0
    commands_copied = 0

    for imp_rule in imported_rules:
        pre_rule = preloaded_map.get(imp_rule.section_number)
        if not pre_rule:
            continue

        changed = False

        # ── Copy severity ─────────────────────────────────────
        if imp_rule.severity in (None, "medium", ""):
            if pre_rule.severity and pre_rule.severity != "medium":
                imp_rule.severity = pre_rule.severity
                changed = True

        # ── Copy intelligence fields ──────────────────────────
        if not imp_rule.risk_weight or imp_rule.risk_weight == 5:
            if pre_rule.risk_weight and pre_rule.risk_weight != 5:
                imp_rule.risk_weight = pre_rule.risk_weight
                changed = True

        if not imp_rule.narrative_group and pre_rule.narrative_group:
            imp_rule.narrative_group = pre_rule.narrative_group
            changed = True

        if not imp_rule.security_themes_json and pre_rule.security_themes_json:
            imp_rule.security_themes_json = pre_rule.security_themes_json
            changed = True

        if not imp_rule.attack_chain_tags_json and pre_rule.attack_chain_tags_json:
            imp_rule.attack_chain_tags_json = pre_rule.attack_chain_tags_json
            changed = True

        if not imp_rule.mitre_attack_json and pre_rule.mitre_attack_json:
            imp_rule.mitre_attack_json = pre_rule.mitre_attack_json
            changed = True

        if not imp_rule.related_rules_json and pre_rule.related_rules_json:
            imp_rule.related_rules_json = pre_rule.related_rules_json
            changed = True

        if not imp_rule.group_with_json and pre_rule.group_with_json:
            imp_rule.group_with_json = pre_rule.group_with_json
            changed = True

        if not imp_rule.cis_controls and pre_rule.cis_controls:
            imp_rule.cis_controls = pre_rule.cis_controls
            changed = True

        # ── Copy RuleCommand if the imported rule has none ────
        pre_cmd = pre_rule.commands
        imp_cmd = imp_rule.commands

        if pre_cmd and not imp_cmd:
            new_cmd = RuleCommand(
                rule_id=imp_rule.id,
                audit_command=pre_cmd.audit_command,
                expected_output_regex=pre_cmd.expected_output_regex,
                expected_output_description=pre_cmd.expected_output_description,
                remediation_command=pre_cmd.remediation_command,
                remediation_description=pre_cmd.remediation_description,
                status="inherited",
                source="preloaded_cross_match",
                # Intelligence fields
                empty_output_interpretation=pre_cmd.empty_output_interpretation,
                output_value_map_json=pre_cmd.output_value_map_json,
                fp_conditions_json=pre_cmd.fp_conditions_json,
                remediation_gpo_path=pre_cmd.remediation_gpo_path,
                remediation_risk=pre_cmd.remediation_risk,
                safe_to_automate=pre_cmd.safe_to_automate,
                requires_restart=pre_cmd.requires_restart,
            )
            db.add(new_cmd)
            commands_copied += 1
            changed = True

        if changed:
            rules_enriched += 1

    db.flush()
    logger.info(
        "Cross-benchmark enrichment: %d rules enriched, %d commands copied "
        "(preloaded=%d → imported=%d)",
        rules_enriched, commands_copied,
        preloaded_benchmark_id, imported_benchmark_id,
    )
    return rules_enriched, commands_copied


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 2 — AI severity fallback
# ═══════════════════════════════════════════════════════════════════════════════

# Severity classification prompt template
_AI_SEVERITY_SYSTEM = """You are a cybersecurity expert specializing in CIS Benchmark compliance.
You classify the severity of security configuration rules.

Severity definitions:
- **critical**: Rules that directly prevent remote code execution, privilege escalation,
  or complete system compromise. Failures expose the system to immediate attack.
  Examples: disabling the firewall, allowing anonymous authentication, running services as SYSTEM.

- **high**: Rules that significantly weaken security posture. Failures enable lateral movement,
  data exfiltration, or substantial privilege escalation if combined with another vulnerability.
  Examples: weak password policies, unencrypted remote access, missing audit logging for auth events.

- **medium**: Rules that moderately improve security. Failures increase attack surface or reduce
  visibility but require additional conditions to exploit.
  Examples: banner text configuration, non-critical audit policies, session timeout settings.

- **low**: Rules that represent best-practice hardening or defense-in-depth measures.
  Failures have minimal direct security impact.
  Examples: cosmetic settings, informational logging, optional hardening that's rarely exploited.

Return ONLY a JSON array of objects with keys: "section_number" (string) and "severity" (string).
The severity MUST be one of: "critical", "high", "medium", "low".
Do NOT include any explanation — return ONLY the JSON array."""

_AI_SEVERITY_BATCH = """Classify the severity of each CIS compliance rule below.

Rules:
{rules_json}

Return a JSON array like:
[{{"section_number": "1.1.1", "severity": "high"}}, ...]"""


def _enrich_severity_with_ai(
    rules: list[Rule],
    db: Session,
    batch_size: int = 25,
) -> int:
    """Use LLM to assign severity to rules that still have 'medium' default.

    Processes rules in batches to avoid token limits.

    Returns
    -------
    int
        Number of rules whose severity was updated by AI.
    """
    try:
        from backend.ai.llm_manager import llm_manager
    except Exception:
        logger.warning("LLM manager not available — skipping AI severity enrichment")
        return 0

    if not rules:
        return 0

    total_updated = 0

    for i in range(0, len(rules), batch_size):
        batch = rules[i : i + batch_size]
        rules_data = [
            {
                "section_number": r.section_number,
                "title": r.title or "",
                "description": (r.description or "")[:300],  # Truncate for token economy
            }
            for r in batch
        ]

        prompt = _AI_SEVERITY_BATCH.format(rules_json=json.dumps(rules_data, indent=2))

        try:
            response = llm_manager.invoke_json(
                prompt=prompt,
                system_prompt=_AI_SEVERITY_SYSTEM,
                timeout=60,
                task="analysis",
            )
        except Exception as exc:
            logger.warning("AI severity batch %d failed: %s", i // batch_size, exc)
            continue

        if not response:
            continue

        # Parse response — expect a list of {section_number, severity}
        severity_list = response if isinstance(response, list) else response.get("rules", response)
        if not isinstance(severity_list, list):
            logger.warning("AI returned unexpected format: %s", type(severity_list))
            continue

        # Build a section→severity lookup
        ai_map: dict[str, str] = {}
        valid_severities = {"critical", "high", "medium", "low"}
        for item in severity_list:
            if isinstance(item, dict):
                sn = str(item.get("section_number", ""))
                sev = str(item.get("severity", "")).lower()
                if sn and sev in valid_severities:
                    ai_map[sn] = sev

        # Apply to rules
        for rule in batch:
            ai_sev = ai_map.get(rule.section_number)
            if ai_sev and ai_sev != "medium":
                rule.severity = ai_sev
                total_updated += 1
                # Tag the source so we know this was AI-assigned
                if not rule.source:
                    rule.source = "ai_severity"
                elif "ai_severity" not in (rule.source or ""):
                    rule.source = f"{rule.source}+ai_severity"

    db.flush()
    logger.info("AI severity enrichment: %d rules updated", total_updated)
    return total_updated


# ═══════════════════════════════════════════════════════════════════════════════
#  Phase 3 — Sync Finding.severity with enriched Rule.severity
# ═══════════════════════════════════════════════════════════════════════════════

def _sync_finding_severities(
    scan_id: int,
    benchmark_id: int,
    db: Session,
) -> int:
    """Update Finding.severity to match the rule's enriched severity.

    Only updates findings whose severity is still "medium" (the original default).

    Returns
    -------
    int
        Number of findings updated.
    """
    # Get all rules with non-medium severity for this benchmark
    rules_with_severity = (
        db.query(Rule.id, Rule.severity)
        .filter(
            Rule.benchmark_id == benchmark_id,
            Rule.severity != "medium",
            Rule.severity.isnot(None),
        )
        .all()
    )
    if not rules_with_severity:
        return 0

    rule_severity_map: dict[int, str] = {r.id: r.severity for r in rules_with_severity}

    # Get findings in this scan that are still "medium"
    medium_findings = (
        db.query(Finding)
        .filter(
            Finding.scan_id == scan_id,
            Finding.severity == "medium",
        )
        .all()
    )

    updated = 0
    for finding in medium_findings:
        new_sev = rule_severity_map.get(finding.rule_id)
        if new_sev:
            finding.severity = new_sev
            updated += 1

    db.flush()
    logger.info(
        "Synced %d finding severities for scan %d", updated, scan_id,
    )
    return updated
