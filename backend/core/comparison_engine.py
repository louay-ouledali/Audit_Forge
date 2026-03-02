"""Comparison engine — evaluates structured comparison expressions against command output.

Replaces fragile regex patterns with human-readable, mathematically sound
comparison expressions.

Supported expression formats:
    >=24       Numeric: actual value >= 24
    <=30       Numeric: actual value <= 30
    >0         Numeric: actual value > 0
    <90        Numeric: actual value < 90
    ==1        Exact match (string or number)
    !=0        Not equal
    !=         Bare not-equal (output must not be empty)
    not_empty  Output must not be empty or whitespace-only
    contains:Success and Failure   Substring check (case-insensitive)
    not_contains:PrivilegeName     Negative substring check (PASS when absent)
    regex:^some_pattern$           Fallback to regex matching

Compound expressions (AND):
    <=365&&!=0   Both conditions must pass (e.g. "365 or fewer, but not 0")
    >=1&&<=14    Range check (value between 1 and 14)
    Multiple && separators are supported: >=1&&<=90&&!=0

Legacy support:
    If the expression doesn't match any operator prefix, it is treated
    as a regex pattern for backward compatibility with existing rules.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from backend.core.text_utils import normalize_unicode

logger = logging.getLogger("auditforge.comparison")

# Operator prefix pattern: >=, <=, >, <, ==, !=, contains:, not_contains:, regex:, not_empty
_OPERATOR_RE = re.compile(
    r"^(?P<op>>=|<=|!=|==|>|<)"
    r"\s*(?P<value>.*)$"
)

_PREFIX_RE = re.compile(
    r"^(?P<prefix>contains|not_contains|regex):"
    r"\s*(?P<value>.+)$",
    re.IGNORECASE,
)


@dataclass
class ComparisonResult:
    """Result of evaluating a comparison expression."""
    matched: bool
    expression: str
    actual_value: str
    explanation: str


def parse_expression_type(expression: str) -> str:
    """Return the type of expression: 'numeric', 'exact', 'not_equal', 'not_empty', 'contains', 'not_contains', 'regex', 'compound', or 'legacy_regex'.

    Useful for UI display and validation.
    """
    if not expression or not expression.strip():
        return "empty"
    expr = expression.strip()

    # Compound expression support (&&)
    if "&&" in expr:
        sub_exprs = [s.strip() for s in expr.split("&&") if s.strip()]
        if len(sub_exprs) > 1:
            return "compound"

    # Check for not_empty keyword
    if expr.lower() == "not_empty":
        return "not_empty"

    m = _OPERATOR_RE.match(expr)
    if m:
        op = m.group("op")
        if op in (">=", "<=", ">", "<"):
            return "numeric"
        if op == "==":
            return "exact"
        if op == "!=":
            return "not_equal"

    m = _PREFIX_RE.match(expr)
    if m:
        return m.group("prefix").lower()

    return "legacy_regex"


def evaluate(expression: str, actual_output: str) -> ComparisonResult:
    """Evaluate a comparison expression against actual command output.

    Parameters
    ----------
    expression : str
        The expected-output expression (e.g. ``">=24"``, ``"==Disabled"``).
        Compound expressions joined by ``&&`` are also supported
        (e.g. ``"<=365&&!=0"``).
    actual_output : str
        The raw stdout from the audit command.

    Returns
    -------
    ComparisonResult
        Whether the output matches and a human-readable explanation.
    """
    if not expression or not expression.strip():
        return ComparisonResult(
            matched=True,
            expression=expression or "",
            actual_value=actual_output.strip(),
            explanation="No expected output defined - accepted by default",
        )

    expr = expression.strip()
    actual = actual_output.strip()

    # ── Compound expression support (&&) ─────────────────────────────────
    if "&&" in expr:
        sub_exprs = [s.strip() for s in expr.split("&&") if s.strip()]
        if len(sub_exprs) > 1:
            results: list[ComparisonResult] = []
            for sub in sub_exprs:
                results.append(evaluate(sub, actual_output))
            all_pass = all(r.matched for r in results)
            parts = [r.explanation for r in results]
            return ComparisonResult(
                matched=all_pass,
                expression=expr,
                actual_value=actual,
                explanation=f"{'PASS' if all_pass else 'FAIL'}: compound — " + " AND ".join(parts),
            )

    # --- Collapse doubled prefixes (e.g. "regex:regex:..." -> "regex:...") ---
    expr = re.sub(r'^((?:contains|not_contains|regex):)\1+', r'\1', expr, flags=re.IGNORECASE)

    # --- Check for not_empty keyword ---
    if expr.lower() == "not_empty":
        # Strip whitespace AND NUL bytes (Windows REG_SZ can contain \x00)
        cleaned = actual.strip().strip('\x00')
        matched = bool(cleaned)
        return ComparisonResult(
            matched=matched,
            expression=expr,
            actual_value=actual,
            explanation=f"{'PASS' if matched else 'FAIL'}: output is {'non-empty' if matched else 'empty'}",
        )

    # --- Try operator-based expressions first ---
    m = _OPERATOR_RE.match(expr)
    if m:
        op = m.group("op")
        expected_val = m.group("value").strip()

        if op in (">=", "<=", ">", "<"):
            return _evaluate_numeric(op, expected_val, actual, expr)
        if op == "==":
            return _evaluate_exact(expected_val, actual, expr)
        if op == "!=":
            return _evaluate_not_equal(expected_val, actual, expr)
    # --- Try prefix-based expressions ---
    m = _PREFIX_RE.match(expr)
    if m:
        prefix = m.group("prefix").lower()
        value = m.group("value").strip()

        if prefix == "contains":
            return _evaluate_contains(value, actual, expr)
        if prefix == "not_contains":
            return _evaluate_not_contains(value, actual, expr)
        if prefix == "regex":
            return _evaluate_regex(value, actual, expr)

    # --- Legacy fallback: treat as regex ---
    return _evaluate_regex(expr, actual, f"regex:{expr}")


def _extract_number(text: str) -> float | None:
    """Extract a number from text output.

    Handles:
    - Plain integers: "14"
    - Negative integers: "-1"
    - Floats: "14.5"
    - Numbers with surrounding whitespace: "  14  "
    - Numbers embedded in short text: "Value: 14" (extracts last number)
    """
    text = text.strip()

    # Fast path: entire output is a number
    try:
        return float(text)
    except ValueError:
        pass

    # Try to find a number in the text (take the last one, as it's usually the value)
    matches = re.findall(r"-?\d+(?:\.\d+)?", text)
    if matches:
        try:
            return float(matches[-1])
        except ValueError:
            pass

    return None


def _evaluate_numeric(
    op: str, expected_str: str, actual: str, full_expr: str
) -> ComparisonResult:
    """Evaluate a numeric comparison (>=, <=, >, <)."""
    try:
        expected_num = float(expected_str)
    except ValueError:
        return ComparisonResult(
            matched=False,
            expression=full_expr,
            actual_value=actual,
            explanation=f"Invalid numeric threshold in expression: '{expected_str}'",
        )

    actual_num = _extract_number(actual)
    if actual_num is None:
        return ComparisonResult(
            matched=False,
            expression=full_expr,
            actual_value=actual,
            explanation=f"Could not extract a number from output: '{actual[:100]}'",
        )

    # Perform the comparison
    if op == ">=":
        matched = actual_num >= expected_num
        desc = f"{actual_num:g} >= {expected_num:g}"
    elif op == "<=":
        matched = actual_num <= expected_num
        desc = f"{actual_num:g} <= {expected_num:g}"
    elif op == ">":
        matched = actual_num > expected_num
        desc = f"{actual_num:g} > {expected_num:g}"
    elif op == "<":
        matched = actual_num < expected_num
        desc = f"{actual_num:g} < {expected_num:g}"
    else:
        matched = False
        desc = f"Unknown operator: {op}"

    return ComparisonResult(
        matched=matched,
        expression=full_expr,
        actual_value=actual,
        explanation=f"{'PASS' if matched else 'FAIL'}: {desc}",
    )


def _evaluate_exact(
    expected: str, actual: str, full_expr: str
) -> ComparisonResult:
    """Evaluate an exact-match comparison (==)."""
    # Try numeric comparison first (e.g., "==1" should match "1" and " 1 ")
    try:
        exp_num = float(expected)
        act_num = _extract_number(actual)
        if act_num is not None:
            matched = act_num == exp_num
            return ComparisonResult(
                matched=matched,
                expression=full_expr,
                actual_value=actual,
                explanation=f"{'PASS' if matched else 'FAIL'}: {act_num:g} == {exp_num:g}",
            )
    except ValueError:
        pass

    # String comparison (case-insensitive)
    matched = actual.strip().lower() == expected.strip().lower()
    return ComparisonResult(
        matched=matched,
        expression=full_expr,
        actual_value=actual,
        explanation=f"{'PASS' if matched else 'FAIL'}: '{actual.strip()}' == '{expected}'",
    )


def _evaluate_not_equal(
    expected: str, actual: str, full_expr: str
) -> ComparisonResult:
    """Evaluate a not-equal comparison (!=).

    Special case: bare ``!=`` (empty expected value) means "must not be empty".
    """
    # Bare != with no value means "output must not be empty"
    if not expected.strip():
        matched = bool(actual.strip())
        return ComparisonResult(
            matched=matched,
            expression=full_expr,
            actual_value=actual,
            explanation=f"{'PASS' if matched else 'FAIL'}: output is {'non-empty' if matched else 'empty'}",
        )

    # Try numeric first
    try:
        exp_num = float(expected)
        act_num = _extract_number(actual)
        if act_num is not None:
            matched = act_num != exp_num
            return ComparisonResult(
                matched=matched,
                expression=full_expr,
                actual_value=actual,
                explanation=f"{'PASS' if matched else 'FAIL'}: {act_num:g} != {exp_num:g}",
            )
    except ValueError:
        pass

    # String comparison (case-insensitive)
    matched = actual.strip().lower() != expected.strip().lower()
    return ComparisonResult(
        matched=matched,
        expression=full_expr,
        actual_value=actual,
        explanation=f"{'PASS' if matched else 'FAIL'}: '{actual.strip()}' != '{expected}'",
    )


def _evaluate_contains(
    expected: str, actual: str, full_expr: str
) -> ComparisonResult:
    """Evaluate a substring check (contains:)."""
    matched = expected.lower() in actual.lower()
    return ComparisonResult(
        matched=matched,
        expression=full_expr,
        actual_value=actual,
        explanation=f"{'PASS' if matched else 'FAIL'}: output {'contains' if matched else 'does not contain'} '{expected}'",
    )


def _evaluate_not_contains(
    expected: str, actual: str, full_expr: str
) -> ComparisonResult:
    """Evaluate a negative substring check (not_contains:).

    PASS when the expected substring is NOT present in the output.
    Useful for secedit "No One" rules where the privilege line must be absent.
    """
    matched = expected.lower() not in actual.lower()
    return ComparisonResult(
        matched=matched,
        expression=full_expr,
        actual_value=actual,
        explanation=f"{'PASS' if matched else 'FAIL'}: output {'does not contain' if matched else 'contains'} '{expected}'",
    )


def _evaluate_regex(
    pattern: str, actual: str, full_expr: str
) -> ComparisonResult:
    """Evaluate a regex match."""
    try:
        matched = bool(re.search(pattern, actual, re.MULTILINE | re.IGNORECASE))
    except re.error as exc:
        return ComparisonResult(
            matched=False,
            expression=full_expr,
            actual_value=actual,
            explanation=f"Invalid regex pattern: {exc}",
        )

    return ComparisonResult(
        matched=matched,
        expression=full_expr,
        actual_value=actual,
        explanation=f"{'PASS' if matched else 'FAIL'}: regex {'matched' if matched else 'no match'} - /{pattern}/",
    )


def validate_expression(expression: str) -> str | None:
    """Validate a comparison expression. Returns an error message or None if valid.

    Use this during post-processing and verification to reject bad expressions.
    """
    if not expression or not expression.strip():
        return None  # Empty is acceptable

    expr = expression.strip()

    # Compound expression support (&&)
    if "&&" in expr:
        sub_exprs = [s.strip() for s in expr.split("&&") if s.strip()]
        if len(sub_exprs) < 2:
            return "Compound expression '&&' requires at least two sub-expressions"
        for sub in sub_exprs:
            err = validate_expression(sub)
            if err:
                return f"In compound sub-expression '{sub}': {err}"
        return None

    # not_empty keyword
    if expr.lower() == "not_empty":
        return None  # Valid

    # Check operator expressions
    m = _OPERATOR_RE.match(expr)
    if m:
        op = m.group("op")
        value = m.group("value").strip()
        if op in (">=", "<=", ">", "<"):
            try:
                float(value)
            except ValueError:
                return f"Numeric operator '{op}' requires a number, got: '{value}'"
        return None  # Valid

    # Check prefix expressions
    m = _PREFIX_RE.match(expr)
    if m:
        prefix = m.group("prefix").lower()
        value = m.group("value").strip()
        if prefix == "regex":
            try:
                re.compile(value)
            except re.error as exc:
                return f"Invalid regex in expression: {exc}"
        return None  # Valid

    # Legacy regex — validate it compiles
    try:
        re.compile(expr)
    except re.error as exc:
        return f"Invalid regex pattern: {exc}"

    # Check for English-phrase patterns (same as existing verification)
    english_patterns = [
        (r"^\d+\s+or\s+(?:more|fewer|greater|less)", "Looks like English text, not a comparison expression"),
        (r"enabled\s+or\s+greater", "Looks like English text, not a comparison expression"),
        (r"(?:should|must|needs?\s+to)\b", "Contains English prose, not a comparison expression"),
        (r"\bshould\s+be\b", "Contains 'should be' - use ==, >=, <= instead"),
        (r"\bor\s+(?:higher|lower|above|below)\b", "Contains 'or higher/lower' - use >=, <= instead"),
        (r"\bat\s+least\s+\d+", "Contains 'at least N' - use >=N instead"),
        (r"\bno\s+more\s+than\b", "Contains 'no more than' - use <= instead"),
        (r"\bgreater\s+than\b", "Contains 'greater than' - use > instead"),
        (r"\bless\s+than\b", "Contains 'less than' - use < instead"),
    ]
    for pattern, message in english_patterns:
        if re.search(pattern, expr, re.IGNORECASE):
            return f"{message}: '{expr}'"

    return None


def format_expression_display(expression: str) -> str:
    """Return a human-friendly description of the expression for UI display.

    Examples:
        ">=24"  →  "Value must be ≥ 24"
        "==1"   →  "Value must equal 1"
        "==Disabled"  →  "Value must equal 'Disabled'"
        "contains:Success and Failure"  →  "Output must contain 'Success and Failure'"
        "<=365&&!=0"  →  "Value must be ≤ 365 AND Value must not equal 0"
    """
    if not expression or not expression.strip():
        return "No expected output"

    expr = expression.strip()

    # Compound expression support (&&)
    if "&&" in expr:
        sub_exprs = [s.strip() for s in expr.split("&&") if s.strip()]
        if len(sub_exprs) > 1:
            parts = [format_expression_display(sub) for sub in sub_exprs]
            return " AND ".join(parts)

    # Check for not_empty keyword
    if expr.lower() == "not_empty":
        return "Output must not be empty"

    m = _OPERATOR_RE.match(expr)
    if m:
        op = m.group("op")
        value = m.group("value").strip()
        op_symbols = {">=": "≥", "<=": "≤", ">": ">", "<": "<", "==": "=", "!=": "≠"}
        symbol = op_symbols.get(op, op)

        # Handle bare != (no value)
        if op == "!=" and not value:
            return "Output must not be empty"

        try:
            float(value)
            return f"Value must be {symbol} {value}"
        except ValueError:
            if op == "==":
                return f"Value must equal '{value}'"
            if op == "!=":
                return f"Value must not equal '{value}'"
            return f"Value {symbol} '{value}'"

    m = _PREFIX_RE.match(expr)
    if m:
        prefix = m.group("prefix").lower()
        value = m.group("value").strip()
        if prefix == "contains":
            return f"Output must contain '{value}'"
        if prefix == "not_contains":
            return f"Output must NOT contain '{value}'"
        if prefix == "regex":
            return f"Output must match pattern: {value}"

    return f"Output must match: {expr}"
