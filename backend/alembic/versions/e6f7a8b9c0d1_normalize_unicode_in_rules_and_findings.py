"""normalize_unicode_in_rules_and_findings

Replaces typographic Unicode characters (smart quotes, em dashes, bullets,
non-breaking spaces, etc.) with plain ASCII equivalents across all text
fields in the rules and findings tables.

Revision ID: e6f7a8b9c0d1
Revises: d5a1b2c3e4f5
Create Date: 2026-02-26
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "e6f7a8b9c0d1"
down_revision = "d5a1b2c3e4f5"
branch_labels = None
depends_on = None

# Unicode replacement map
_REPLACEMENTS: list[tuple[str, str]] = [
    ("\u201C", '"'),   # left double quote
    ("\u201D", '"'),   # right double quote
    ("\u201E", '"'),   # double low-9 quote
    ("\u2018", "'"),   # left single quote
    ("\u2019", "'"),   # right single quote
    ("\u201A", "'"),   # single low-9 quote
    ("\u00AB", '"'),   # left angle quote
    ("\u00BB", '"'),   # right angle quote
    ("\u2014", " - "), # em dash
    ("\u2013", "-"),   # en dash
    ("\u2010", "-"),   # hyphen
    ("\u2011", "-"),   # non-breaking hyphen
    ("\u2012", "-"),   # figure dash
    ("\u2022", "-"),   # bullet
    ("\u25AA", "-"),   # small black square
    ("\u25CF", "-"),   # black circle
    ("\u25A0", "-"),   # black square
    ("\u2026", "..."), # ellipsis
    ("\u2122", "(TM)"),# trademark
    ("\u00AE", "(R)"), # registered
    ("\u00B4", "'"),   # acute accent
    ("\u2192", "->"),  # right arrow
    ("\u00A0", " "),   # NBSP
    ("\u2002", " "),   # en space
    ("\u2003", " "),   # em space
    ("\u202F", " "),   # narrow NBSP
    ("\u200B", ""),    # zero-width space
    ("\uFEFF", ""),    # BOM
]


def _apply_replacements(conn, table: str, columns: list[str]) -> int:
    """Run REPLACE() for each unicode char across each column."""
    total = 0
    for col in columns:
        for old_char, new_char in _REPLACEMENTS:
            # SQLite REPLACE function
            result = conn.execute(
                sa.text(
                    f"UPDATE {table} SET {col} = REPLACE({col}, :old, :new) "
                    f"WHERE {col} LIKE '%' || :old || '%'"
                ),
                {"old": old_char, "new": new_char},
            )
            total += result.rowcount
    return total


def upgrade() -> None:
    conn = op.get_bind()

    # Clean rules table
    rule_cols = [
        "title", "description", "rationale",
        "remediation_description_raw", "default_value",
    ]
    r_count = _apply_replacements(conn, "rules", rule_cols)

    # Clean findings table
    finding_cols = [
        "actual_output", "expected_output",
        "evaluation_explanation", "ai_advice", "auditor_notes",
    ]
    f_count = _apply_replacements(conn, "findings", finding_cols)

    print(f"  Unicode normalisation: {r_count} rule field updates, {f_count} finding field updates")


def downgrade() -> None:
    # Not reversible — original Unicode characters are not preserved
    pass
