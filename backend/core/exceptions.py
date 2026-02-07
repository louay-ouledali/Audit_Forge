"""Custom exception hierarchy for AditForge.

Provides structured error types so that API handlers and background tasks
can distinguish transient failures (worth retrying) from permanent ones
and return meaningful error information to callers.
"""

from __future__ import annotations


class AuditForgeError(Exception):
    """Base exception for all AditForge errors."""

    def __init__(self, message: str, detail: str | None = None) -> None:
        self.message = message
        self.detail = detail
        super().__init__(message)


# ── Connection errors ────────────────────────────────────────


class ConnectionFailedError(AuditForgeError):
    """Raised when a target connection cannot be established."""


class ConnectionTimeoutError(AuditForgeError):
    """Raised when a target connection attempt times out."""


# ── LLM errors ───────────────────────────────────────────────


class LLMError(AuditForgeError):
    """Base exception for LLM-related failures."""


class LLMTimeoutError(LLMError):
    """Raised when an LLM call exceeds the configured timeout."""


class LLMUnavailableError(LLMError):
    """Raised when the LLM service is unreachable."""


class LLMResponseError(LLMError):
    """Raised when the LLM returns an unparseable or invalid response."""


# ── PDF / Benchmark errors ───────────────────────────────────


class BenchmarkError(AuditForgeError):
    """Base exception for benchmark processing failures."""


class PDFParseError(BenchmarkError):
    """Raised when a PDF cannot be parsed or is malformed."""


class EmptyBenchmarkError(BenchmarkError):
    """Raised when a benchmark contains no extractable rules."""


class BenchmarkTooLargeError(BenchmarkError):
    """Raised when a benchmark exceeds the configured size limit."""


# ── Scan errors ──────────────────────────────────────────────


class ScanError(AuditForgeError):
    """Base exception for scan execution failures."""


class ScanCancelledError(ScanError):
    """Raised when a scan is cancelled by the user."""


# ── Database errors ──────────────────────────────────────────


class BackupError(AuditForgeError):
    """Raised when a database backup or restore operation fails."""
