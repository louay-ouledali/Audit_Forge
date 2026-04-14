"""SQL read-only guard for audit connectors.

Rejects DML/DDL statements before they reach the database.
Only the *first* SQL keyword is checked — subqueries containing
SELECT inside WHERE clauses are fine.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("auditforge.connectors.sql_guard")

# Keywords that are ALLOWED as the first SQL keyword
_READONLY_KEYWORDS = frozenset({
    "SELECT", "SHOW", "EXPLAIN", "WITH", "DESCRIBE", "DESC",
    "SET",  # e.g. SET search_path, SET ROLE — needed for PG/MySQL discovery
    "PRAGMA",  # SQLite pragmas
})

# Keywords that are BLOCKED when they appear as the first keyword
_BLOCKED_KEYWORDS = frozenset({
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "REPLACE", "MERGE", "GRANT", "REVOKE",
    "EXEC", "EXECUTE", "CALL",
})


def assert_readonly(sql: str) -> None:
    """Raise ValueError if *sql* starts with a blocked DML/DDL keyword.

    This is intentionally conservative — it only looks at the first keyword
    so that legitimate audit queries like
    ``SELECT * FROM t WHERE col IN (SELECT ...)`` pass through.
    """
    stripped = sql.strip()
    if not stripped:
        return

    # Strip leading comments (-- and /* */)
    cleaned = re.sub(r"--[^\n]*", "", stripped)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()
    if not cleaned:
        return

    first_word = cleaned.split()[0].upper().rstrip(";")

    if first_word in _BLOCKED_KEYWORDS:
        logger.warning("SQL guard blocked statement: %.200s", stripped)
        raise ValueError(
            f"Blocked: statement starts with '{first_word}'. "
            "Only read-only queries (SELECT, SHOW, EXPLAIN, …) are permitted."
        )

    # Extra guard: block xp_ extended stored procedures even inside SELECT
    _xp_pattern = re.compile(r'\bxp_\w+\s*\(', re.IGNORECASE)
    if _xp_pattern.search(cleaned):
        logger.warning("SQL guard blocked xp_ stored procedure in: %.200s", stripped)
        raise ValueError(
            "Blocked: xp_ extended stored procedures are not permitted."
        )
