"""False positive detection engine — heuristic + pattern-based analysis of audit findings.

Examines each finding and assigns a confidence score (0-100) indicating how
likely the FAIL result is a false positive.  Signals are combined to produce
a human-readable reason and an overall confidence level.

Detection strategies:
  1. Output-vs-expected near-miss  (numeric, string, GPO, and list comparisons)
  2. Empty / error / timeout output — with error-type classification
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
from difflib import SequenceMatcher

logger = logging.getLogger("auditforge.fp_detector")

# ── Confidence thresholds ──
HIGH_CONFIDENCE = 70     # Strong FP signal
MEDIUM_CONFIDENCE = 45   # Moderate FP signal
LOW_CONFIDENCE = 20      # Weak FP signal

# ── Configurable near-miss settings ──
NEAR_MISS_NUMERIC_THRESHOLD_PCT: float = 10.0   # % deviation for numeric near-miss
NEAR_MISS_STRING_SIMILARITY_MIN: float = 0.75    # SequenceMatcher ratio threshold
NEAR_MISS_LIST_SUBSET_MIN_PCT: float = 70.0      # % of expected items present

# ── GPO / Boolean equivalence maps ──
_GPO_ENABLED_VALUES = frozenset({
    "enabled", "1", "true", "yes", "on", "success", "success and failure",
    "success, failure", "allow",
})
_GPO_DISABLED_VALUES = frozenset({
    "disabled", "0", "false", "no", "off", "no auditing", "not configured",
    "none", "deny", "block",
})
_GPO_EQUIVALENCES: dict[str, frozenset[str]] = {
    "enabled":  _GPO_ENABLED_VALUES,
    "disabled": _GPO_DISABLED_VALUES,
}


@dataclass
class FPSignal:
    """A single false-positive signal."""
    reason: str
    confidence: int  # 0-100
    category: str    # near_miss | empty_output | access_denied | not_found |
                     #   timeout | command_error | multi_value | edge_case |
                     #   override | default_match | cross_finding


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


def _normalize_for_compare(text: str) -> str:
    """Normalize a string for fuzzy comparison — lowercase, strip, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    # Strip surrounding quotes
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()
    return text


def _split_value_list(text: str) -> list[str]:
    """Split a GPO / registry multi-value string into individual items.

    Handles: comma-separated, semicolon-separated, newline-separated,
    "and"-separated, "or"-separated lists.
    """
    # Normalise separators
    normalised = re.sub(r'\s*[;|]\s*', ',', text)
    normalised = re.sub(r'\s+and\s+', ',', normalised, flags=re.IGNORECASE)
    normalised = re.sub(r'\s+or\s+', ',', normalised, flags=re.IGNORECASE)
    normalised = re.sub(r'\r?\n', ',', normalised)
    items = [i.strip() for i in normalised.split(',') if i.strip()]
    return items


def _gpo_equivalent(actual_val: str, expected_val: str) -> bool:
    """Check if two GPO/boolean values are semantically equivalent."""
    a = actual_val.lower().strip()
    e = expected_val.lower().strip()
    if a == e:
        return True
    # Check in same equivalence group
    for _group_key, group_vals in _GPO_EQUIVALENCES.items():
        if a in group_vals and e in group_vals:
            return True
    return False


# ═══════════════════════════════════════════════════════════
#  Individual detection strategies
# ═══════════════════════════════════════════════════════════

# ── Error-type classification patterns ──
_ACCESS_DENIED_PATTERNS = [
    re.compile(r"access.?denied", re.IGNORECASE),
    re.compile(r"permission.?denied", re.IGNORECASE),
    re.compile(r"UnauthorizedAccess", re.IGNORECASE),
    re.compile(r"insufficient.?privilege", re.IGNORECASE),
    re.compile(r"requires elevation", re.IGNORECASE),
    re.compile(r"run as administrator", re.IGNORECASE),
]

_NOT_FOUND_PATTERNS = [
    re.compile(r"(?:ObjectNotFound|ItemNotFoundException)", re.IGNORECASE),
    re.compile(r"cannot find path", re.IGNORECASE),
    re.compile(r"no such file", re.IGNORECASE),
    re.compile(r"RegistryKey .+ does not exist", re.IGNORECASE),
    re.compile(r"Property .+ does not exist", re.IGNORECASE),
    re.compile(r"Get-ItemProperty\s*:", re.IGNORECASE),
    re.compile(r"the system cannot find the file specified", re.IGNORECASE),
    re.compile(r"WMI:\s*Invalid namespace", re.IGNORECASE),
    re.compile(r"not.?found", re.IGNORECASE),
    re.compile(r"does not exist", re.IGNORECASE),
]

_TIMEOUT_PATTERNS = [
    re.compile(r"timed?\s*out", re.IGNORECASE),
    re.compile(r"connection refused", re.IGNORECASE),
    re.compile(r"RPC server.+unavailable", re.IGNORECASE),
    re.compile(r"network.?path.+not found", re.IGNORECASE),
    re.compile(r"WinRM.+cannot", re.IGNORECASE),
    re.compile(r"connection.+reset", re.IGNORECASE),
]

_COMMAND_ERROR_PATTERNS = [
    re.compile(r"is not recognized as", re.IGNORECASE),
    re.compile(r"command not found", re.IGNORECASE),
    re.compile(r"the term .+ is not recognized", re.IGNORECASE),
    re.compile(r"MethodInvocationException", re.IGNORECASE),
    re.compile(r"CommandNotFoundException", re.IGNORECASE),
    re.compile(r"(?<!no\s)error:", re.IGNORECASE),
    re.compile(r"exception", re.IGNORECASE),
    re.compile(r"FullyQualifiedErrorId", re.IGNORECASE),
]


def _detect_empty_output(finding: dict) -> FPSignal | None:
    """Detect when actual output is empty, whitespace, or looks like a command error.

    Returns a signal with a **specific error-type category** so downstream
    consumers can distinguish *why* the output is problematic:

        access_denied  – permission / elevation issues  (conf 72)
        not_found      – path / registry / object missing (conf 62)
        timeout        – connectivity / RPC failures      (conf 74)
        command_error  – script or cmdlet failures        (conf 68)
        empty_output   – blank / whitespace only          (conf 75)
    """
    actual = (finding.get("actual_output") or "").strip()

    if not actual:
        return FPSignal(
            reason="Actual output is empty — command may have failed silently or returned no data",
            confidence=75,
            category="empty_output",
        )

    # ── Access denied (likely privilege issue, not real config state) ──
    for pattern in _ACCESS_DENIED_PATTERNS:
        if pattern.search(actual):
            return FPSignal(
                reason="Access denied / insufficient privileges — output may not reflect actual configuration",
                confidence=72,
                category="access_denied",
            )

    # ── Timeout / connectivity (remote collection failure) ──
    for pattern in _TIMEOUT_PATTERNS:
        if pattern.search(actual):
            return FPSignal(
                reason="Timeout or connection failure — data collection did not complete",
                confidence=74,
                category="timeout",
            )

    # ── Object / path not found (may mean feature absent, not misconfigured) ──
    for pattern in _NOT_FOUND_PATTERNS:
        if pattern.search(actual):
            return FPSignal(
                reason="Object or path not found — feature may not be installed or registry key absent",
                confidence=62,
                category="not_found",
            )

    # ── Command / script execution error ──
    for pattern in _COMMAND_ERROR_PATTERNS:
        if pattern.search(actual):
            return FPSignal(
                reason="Command or script execution error — audit check itself may be faulty",
                confidence=68,
                category="command_error",
            )

    return None


def _detect_near_miss(finding: dict) -> FPSignal | None:
    """Detect when the actual value is very close to the expected value.

    Supports four comparison modes (tried in order):
      1. **Numeric comparison** — actual number within configurable % of threshold
      2. **GPO / boolean equivalence** — "Enabled"≈"1"≈"True", etc.
      3. **List / set comparison** — expected list mostly present in actual
      4. **String similarity** — fuzzy SequenceMatcher ratio above threshold
    """
    expected_raw = (finding.get("expected_output") or "").strip()
    actual_raw = (finding.get("actual_output") or "").strip()

    if not expected_raw or not actual_raw:
        return None

    # ── Mode 1: Numeric comparison (operator-based) ──
    sig = _near_miss_numeric(actual_raw, expected_raw)
    if sig:
        return sig

    # ── Mode 2: GPO / boolean equivalence ──
    sig = _near_miss_gpo(actual_raw, expected_raw)
    if sig:
        return sig

    # ── Mode 3: List / set comparison ──
    sig = _near_miss_list(actual_raw, expected_raw)
    if sig:
        return sig

    # ── Mode 4: String similarity (fall-through) ──
    sig = _near_miss_string(actual_raw, expected_raw)
    if sig:
        return sig

    return None


def _near_miss_numeric(actual_raw: str, expected_raw: str) -> FPSignal | None:
    """Numeric near-miss: actual number within threshold % of expected operator value."""
    actual_num = _try_parse_number(actual_raw)
    if actual_num is None:
        return None

    # Parse comparison expression: ">= 14", "<= 900", "== 1", etc.
    m = re.match(r'^(>=|<=|>|<|==|!=)\s*(.+)$', expected_raw)
    if not m:
        # Also try plain numbers: "14", "900"
        expected_num = _try_parse_number(expected_raw)
        if expected_num is None:
            return None
        # Treat plain number as "== expected"
        if expected_num == 0:
            if abs(actual_num) <= 1:
                return FPSignal(
                    reason=f"Near-miss (numeric): actual ({actual_num}) very close to expected ({expected_raw})",
                    confidence=40,
                    category="near_miss",
                )
            return None
        diff_pct = abs(actual_num - expected_num) / abs(expected_num) * 100
        if diff_pct <= NEAR_MISS_NUMERIC_THRESHOLD_PCT:
            confidence = 55 if diff_pct <= 5 else 35
            return FPSignal(
                reason=f"Near-miss (numeric): actual ({actual_num}) within {diff_pct:.0f}% of expected ({expected_raw})",
                confidence=confidence,
                category="near_miss",
            )
        return None

    op, val_str = m.group(1), m.group(2)
    expected_num = _try_parse_number(val_str)
    if expected_num is None:
        return None

    # For zero thresholds, any very small non-zero value is a near-miss
    if expected_num == 0:
        if op in ('==', '<=', '<') and abs(actual_num) <= 1:
            return FPSignal(
                reason=f"Near-miss (numeric): actual ({actual_num}) very close to zero threshold ({expected_raw})",
                confidence=40,
                category="near_miss",
            )
        return None

    diff_pct = abs(actual_num - expected_num) / abs(expected_num) * 100

    if diff_pct <= NEAR_MISS_NUMERIC_THRESHOLD_PCT:
        confidence = 55 if diff_pct <= 5 else 35
        return FPSignal(
            reason=f"Near-miss (numeric): actual ({actual_num}) within {diff_pct:.0f}% of threshold ({expected_raw})",
            confidence=confidence,
            category="near_miss",
        )

    return None


def _near_miss_gpo(actual_raw: str, expected_raw: str) -> FPSignal | None:
    """GPO / boolean near-miss: detect equivalent GPO values that differ only in representation."""
    a_norm = _normalize_for_compare(actual_raw)
    e_norm = _normalize_for_compare(expected_raw)

    # Strip common wrapping like "Value: Enabled" → "Enabled"
    for prefix in ("value:", "data:", "setting:", "state:"):
        if a_norm.startswith(prefix):
            a_norm = a_norm[len(prefix):].strip()
        if e_norm.startswith(prefix):
            e_norm = e_norm[len(prefix):].strip()

    # If both are in the same GPO group → they're equivalent, strong near-miss
    if _gpo_equivalent(a_norm, e_norm):
        return FPSignal(
            reason=f"Near-miss (GPO): '{actual_raw.strip()}' is semantically equivalent to '{expected_raw.strip()}'",
            confidence=60,
            category="near_miss",
        )

    # Check if actual is in the OPPOSITE GPO group (clearly not a near-miss)
    actual_in_enabled = a_norm in _GPO_ENABLED_VALUES
    actual_in_disabled = a_norm in _GPO_DISABLED_VALUES
    expected_in_enabled = e_norm in _GPO_ENABLED_VALUES
    expected_in_disabled = e_norm in _GPO_DISABLED_VALUES

    if (actual_in_enabled and expected_in_disabled) or (actual_in_disabled and expected_in_enabled):
        # Opposite state — not a near-miss at all
        return None

    return None


def _near_miss_list(actual_raw: str, expected_raw: str) -> FPSignal | None:
    """List / set near-miss: expected list is partially present in actual output."""
    expected_items = _split_value_list(expected_raw)
    if len(expected_items) < 2:
        return None  # Not a list comparison

    actual_items_set = {_normalize_for_compare(i) for i in _split_value_list(actual_raw)}
    if not actual_items_set:
        return None

    expected_norm = [_normalize_for_compare(i) for i in expected_items]
    matched = sum(1 for e in expected_norm if e in actual_items_set)
    match_pct = (matched / len(expected_norm)) * 100

    if match_pct >= NEAR_MISS_LIST_SUBSET_MIN_PCT and match_pct < 100:
        missing = [e for e, en in zip(expected_items, expected_norm) if en not in actual_items_set]
        return FPSignal(
            reason=f"Near-miss (list): {matched}/{len(expected_norm)} expected items present "
                   f"({match_pct:.0f}%), missing: {', '.join(missing[:3])}",
            confidence=45 if match_pct >= 85 else 35,
            category="near_miss",
        )

    # Also check the reverse: actual has extra items beyond expected (superset)
    # This is less of a near-miss but worth noting
    expected_set = set(expected_norm)
    if expected_set.issubset(actual_items_set) and len(actual_items_set) > len(expected_set):
        extra_count = len(actual_items_set) - len(expected_set)
        return FPSignal(
            reason=f"Near-miss (list): actual contains all expected items plus {extra_count} extra — "
                   f"may be over-permissive rather than non-compliant",
            confidence=30,
            category="near_miss",
        )

    return None


def _near_miss_string(actual_raw: str, expected_raw: str) -> FPSignal | None:
    """Fuzzy string near-miss: SequenceMatcher ratio above configurable threshold.

    Only triggers for non-trivial strings (>5 chars) to avoid noisy matches
    on short values like "0" vs "1".
    """
    a_norm = _normalize_for_compare(actual_raw)
    e_norm = _normalize_for_compare(expected_raw)

    # Skip comparison operators — those are handled by numeric mode
    if re.match(r'^[><=!]{1,2}\s', e_norm):
        return None

    # Skip very short strings — too noisy
    if len(a_norm) < 5 or len(e_norm) < 5:
        return None

    # Skip if strings are identical after normalisation
    if a_norm == e_norm:
        return FPSignal(
            reason=f"Near-miss (string): actual matches expected after normalisation (case/whitespace difference)",
            confidence=65,
            category="near_miss",
        )

    ratio = SequenceMatcher(None, a_norm, e_norm).ratio()
    if ratio >= NEAR_MISS_STRING_SIMILARITY_MIN:
        pct = round(ratio * 100)
        return FPSignal(
            reason=f"Near-miss (string): actual is {pct}% similar to expected — "
                   f"minor formatting or value difference",
            confidence=50 if ratio >= 0.9 else 35,
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
