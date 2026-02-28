"""False positive detection engine — heuristic + pattern-based analysis of audit findings.

Examines each finding and assigns a confidence score (0-100) indicating how
likely the FAIL result is a false positive.  Signals are combined to produce
a human-readable reason and an overall confidence level.

Detection strategies:
  1. Output-vs-expected near-miss  (actual value close to threshold)
  2. Empty / error / timeout output  (command failed, not a real FAIL)
  3. Multi-value output ambiguity  (multiple lines when single expected)
  4. Known Windows / Linux edge-case patterns
  5. Auditor override signals  (manual overrides suggest prior FP)
  6. Default-value match  (actual matches documented default)
  7. Cross-finding consistency  (same rule passes on similar targets)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("auditforge.fp_detector")

# ── Confidence thresholds ──
HIGH_CONFIDENCE = 70     # Strong FP signal
MEDIUM_CONFIDENCE = 45   # Moderate FP signal
LOW_CONFIDENCE = 20      # Weak FP signal


@dataclass
class FPSignal:
    """A single false-positive signal."""
    reason: str
    confidence: int  # 0-100
    category: str    # near_miss | empty_output | multi_value | edge_case | override | default_match | cross_finding


@dataclass
class FPAnalysis:
    """Result of false-positive analysis for one finding."""
    is_suspect: bool = False
    confidence: int = 0          # 0-100 overall confidence it's a FP
    confidence_label: str = ""   # "Low" / "Medium" / "High"
    signals: list[FPSignal] = field(default_factory=list)
    summary: str = ""            # Human-readable one-liner

    @property
    def top_reason(self) -> str:
        if not self.signals:
            return ""
        return max(self.signals, key=lambda s: s.confidence).reason


def _try_parse_number(text: str) -> float | None:
    """Extract a number from text, handling common audit output formats."""
    if not text:
        return None
    cleaned = text.strip().strip('%').strip()
    # Handle comma-separated numbers
    cleaned = cleaned.replace(',', '')
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _extract_numbers(text: str) -> list[float]:
    """Extract all numbers from a text string."""
    return [float(m) for m in re.findall(r'-?\d+\.?\d*', text)]


# ═══════════════════════════════════════════════════════════
#  Individual detection strategies
# ═══════════════════════════════════════════════════════════

def _detect_empty_output(finding: dict) -> FPSignal | None:
    """Detect when actual output is empty, whitespace, or looks like a command error."""
    actual = (finding.get("actual_output") or "").strip()
    if not actual:
        return FPSignal(
            reason="Actual output is empty - command may have failed or returned no data",
            confidence=75,
            category="empty_output",
        )
    # Common error patterns
    error_patterns = [
        r"(?i)access.?denied",
        r"(?i)permission.?denied",
        r"(?i)not.?found",
        r"(?i)is not recognized",
        r"(?i)command not found",
        r"(?i)cannot find path",
        r"(?i)ObjectNotFound",
        r"(?i)error:",
        r"(?i)exception",
        r"(?i)timed?\s*out",
        r"(?i)connection refused",
        r"(?i)no such file",
        r"(?i)the term .+ is not recognized",
        r"(?i)Get-ItemProperty\s*:\s*",
        r"(?i)RegistryKey .+ does not exist",
        r"(?i)Property .+ does not exist",
    ]
    for pattern in error_patterns:
        if re.search(pattern, actual):
            return FPSignal(
                reason=f"Actual output contains an error/access-denied pattern - may not reflect real config",
                confidence=70,
                category="empty_output",
            )
    return None


def _detect_near_miss(finding: dict) -> FPSignal | None:
    """Detect when the actual value is very close to the expected threshold."""
    expected_raw = (finding.get("expected_output") or "").strip()
    actual_raw = (finding.get("actual_output") or "").strip()

    if not expected_raw or not actual_raw:
        return None

    actual_num = _try_parse_number(actual_raw)
    if actual_num is None:
        return None

    # Parse comparison expression
    m = re.match(r'^(>=|<=|>|<|==|!=)\s*(.+)$', expected_raw)
    if not m:
        return None

    op, val_str = m.group(1), m.group(2)
    expected_num = _try_parse_number(val_str)
    if expected_num is None:
        return None

    # Calculate how close the actual is to the threshold
    if expected_num == 0:
        # For zero thresholds, any non-zero value that's very small is a near-miss
        if op in ('==', '<=', '<') and abs(actual_num) <= 1:
            return FPSignal(
                reason=f"Near-miss: actual value ({actual_num}) is very close to expected threshold ({expected_raw})",
                confidence=40,
                category="near_miss",
            )
        return None

    diff_pct = abs(actual_num - expected_num) / abs(expected_num) * 100

    # Check if it's within 10% of the threshold
    if diff_pct <= 10:
        confidence = 55 if diff_pct <= 5 else 35
        return FPSignal(
            reason=f"Near-miss: actual value ({actual_num}) is within {diff_pct:.0f}% of threshold ({expected_raw})",
            confidence=confidence,
            category="near_miss",
        )

    return None


def _detect_multi_value_output(finding: dict) -> FPSignal | None:
    """Detect when output has multiple lines suggesting ambiguous comparison."""
    actual = (finding.get("actual_output") or "").strip()
    if not actual:
        return None

    lines = [l.strip() for l in actual.splitlines() if l.strip()]
    if len(lines) > 3:
        return FPSignal(
            reason=f"Multi-line output ({len(lines)} lines) - comparison may be unreliable for single-value rules",
            confidence=50,
            category="multi_value",
        )
    return None


def _detect_edge_case_patterns(finding: dict) -> FPSignal | None:
    """Detect known OS-specific edge cases that commonly produce false positives."""
    actual = (finding.get("actual_output") or "").strip().lower()
    title = (finding.get("rule_title") or "").lower()
    section = (finding.get("section_number") or "")

    # Windows: "Not Configured" often means "using secure default"
    if "not configured" in actual or "not defined" in actual:
        return FPSignal(
            reason="'Not Configured' / 'Not Defined' - may use secure OS default rather than explicit policy",
            confidence=55,
            category="edge_case",
        )

    # Windows: Registry key doesn't exist (may mean feature not installed)
    if any(p in actual for p in ["does not exist", "property cannot be found", "itemnotfound"]):
        return FPSignal(
            reason="Registry key/property not found - feature may not be installed (N/A rather than FAIL)",
            confidence=60,
            category="edge_case",
        )

    # Services that may be legitimately absent
    if "cannot find any service" in actual or "get-service" in actual and "cannot" in actual:
        return FPSignal(
            reason="Service not found - may not be installed on this system",
            confidence=65,
            category="edge_case",
        )

    # Linux: Package not installed checks
    if "is not installed" in actual or "no packages found" in actual:
        if any(kw in title for kw in ["ensure", "removed", "disabled", "not installed"]):
            return FPSignal(
                reason="Package not installed - for removal rules this may be a correct PASS state",
                confidence=70,
                category="edge_case",
            )

    return None


def _detect_override_signal(finding: dict) -> FPSignal | None:
    """Check if auditor has already flagged this as potential FP."""
    override = (finding.get("auditor_override") or "").lower()
    notes = (finding.get("auditor_notes") or "").lower()

    if override == "false_positive":
        return FPSignal(
            reason="Auditor has marked this finding as a false positive",
            confidence=90,
            category="override",
        )
    if override == "accepted_risk":
        return FPSignal(
            reason="Auditor has marked this as an accepted risk",
            confidence=40,
            category="override",
        )
    if notes and any(kw in notes for kw in ["false positive", "fp", "not applicable", "n/a"]):
        return FPSignal(
            reason="Auditor notes suggest this may be a false positive",
            confidence=60,
            category="override",
        )
    return None


def _detect_default_value_match(finding: dict) -> FPSignal | None:
    """Detect when actual output matches the documented default value."""
    default = (finding.get("default_value") or "").strip()
    actual = (finding.get("actual_output") or "").strip()

    if not default or not actual:
        return None

    if actual.lower() == default.lower():
        return FPSignal(
            reason=f"Actual output matches the CIS-documented default value ('{default}') - may be intended baseline",
            confidence=35,
            category="default_match",
        )
    return None


# ═══════════════════════════════════════════════════════════
#  Cross-finding consistency check
# ═══════════════════════════════════════════════════════════

def _detect_cross_finding_inconsistency(finding: dict, all_findings: list[dict]) -> FPSignal | None:
    """Flag if the same rule passes on other targets but fails here."""
    rule_id = finding.get("_rule_id")
    scan_id = finding.get("scan_id")
    if not rule_id:
        return None

    same_rule = [
        f for f in all_findings
        if f.get("_rule_id") == rule_id and f.get("scan_id") != scan_id
    ]
    if not same_rule:
        return None

    pass_count = sum(1 for f in same_rule if f.get("status") == "PASS")
    total = len(same_rule)

    if total > 0 and pass_count == total:
        return FPSignal(
            reason=f"Same rule passes on {pass_count} other target(s) - inconsistency suggests potential FP",
            confidence=55,
            category="cross_finding",
        )
    elif total >= 2 and pass_count / total >= 0.7:
        return FPSignal(
            reason=f"Same rule passes on {pass_count}/{total} other scans ({round(pass_count/total*100)}%) - partial inconsistency",
            confidence=35,
            category="cross_finding",
        )
    return None


# ═══════════════════════════════════════════════════════════
#  Main analysis entry
# ═══════════════════════════════════════════════════════════

def analyze_finding(finding: dict, all_findings: list[dict] | None = None) -> FPAnalysis:
    """Run all FP detection strategies on a single finding.

    Parameters
    ----------
    finding : dict
        A finding dict from aggregate_report_data (must have status, actual_output, etc.)
    all_findings : list[dict] | None
        All findings in the report, used for cross-finding consistency check.

    Returns
    -------
    FPAnalysis
        Analysis result with signals, confidence, and summary.
    """
    # Only analyze FAILed findings
    if (finding.get("status") or "").upper() != "FAIL":
        return FPAnalysis()

    signals: list[FPSignal] = []

    # Run each detector
    for detector in [
        lambda f: _detect_empty_output(f),
        lambda f: _detect_near_miss(f),
        lambda f: _detect_multi_value_output(f),
        lambda f: _detect_edge_case_patterns(f),
        lambda f: _detect_override_signal(f),
        lambda f: _detect_default_value_match(f),
    ]:
        sig = detector(finding)
        if sig:
            signals.append(sig)

    # Cross-finding check (needs all findings)
    if all_findings:
        sig = _detect_cross_finding_inconsistency(finding, all_findings)
        if sig:
            signals.append(sig)

    if not signals:
        return FPAnalysis()

    # Combine signals: take weighted average, boosted if multiple signals agree
    confidences = [s.confidence for s in signals]
    avg_confidence = sum(confidences) / len(confidences)
    max_confidence = max(confidences)

    # Multi-signal boost: more signals = higher confidence
    boost = min(len(signals) - 1, 3) * 8  # +8 per additional signal, max +24
    overall = min(int(max(avg_confidence, max_confidence) + boost), 99)

    if overall >= HIGH_CONFIDENCE:
        label = "High"
    elif overall >= MEDIUM_CONFIDENCE:
        label = "Medium"
    else:
        label = "Low"

    # Build summary
    top = max(signals, key=lambda s: s.confidence)
    summary = f"[{label} confidence] {top.reason}"
    if len(signals) > 1:
        summary += f" (+{len(signals)-1} other signal{'s' if len(signals) > 2 else ''})"

    return FPAnalysis(
        is_suspect=True,
        confidence=overall,
        confidence_label=label,
        signals=signals,
        summary=summary,
    )


def analyze_findings(findings: list[dict]) -> dict[int, FPAnalysis]:
    """Analyze all findings and return a dict of finding_index -> FPAnalysis.

    Only FAIL findings appear in the result dict.
    """
    results: dict[int, FPAnalysis] = {}
    for idx, f in enumerate(findings):
        analysis = analyze_finding(f, all_findings=findings)
        if analysis.is_suspect:
            results[idx] = analysis
    return results


def enrich_findings_with_fp(findings: list[dict]) -> tuple[list[dict], dict]:
    """Add false-positive analysis data to each finding and return summary stats.

    Mutates findings in-place (adds 'fp_analysis' key) and returns:
      - enriched findings list
      - summary dict with counts and breakdown
    """
    fp_results = analyze_findings(findings)

    total_suspects = 0
    high_confidence = 0
    medium_confidence = 0
    low_confidence = 0
    by_category: dict[str, int] = {}

    for idx, analysis in fp_results.items():
        findings[idx]["fp_analysis"] = {
            "is_suspect": True,
            "confidence": analysis.confidence,
            "confidence_label": analysis.confidence_label,
            "summary": analysis.summary,
            "top_reason": analysis.top_reason,
            "signal_count": len(analysis.signals),
            "signals": [
                {"reason": s.reason, "confidence": s.confidence, "category": s.category}
                for s in analysis.signals
            ],
        }
        total_suspects += 1
        if analysis.confidence_label == "High":
            high_confidence += 1
        elif analysis.confidence_label == "Medium":
            medium_confidence += 1
        else:
            low_confidence += 1

        for s in analysis.signals:
            by_category[s.category] = by_category.get(s.category, 0) + 1

    # Ensure non-suspect findings have empty fp_analysis
    for idx, f in enumerate(findings):
        if "fp_analysis" not in f:
            f["fp_analysis"] = {"is_suspect": False}

    summary = {
        "total_suspects": total_suspects,
        "high_confidence": high_confidence,
        "medium_confidence": medium_confidence,
        "low_confidence": low_confidence,
        "by_category": by_category,
    }

    return findings, summary
