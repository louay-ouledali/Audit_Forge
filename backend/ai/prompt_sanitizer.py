"""Prompt sanitizer — strip injection patterns from user-controlled fields
before they are interpolated into LLM prompts.

This addresses H10: prevent prompt injection via uploaded PDFs, rule titles,
copilot messages, and other user-influenced data that gets `.format()`-ed
into system/context prompts.

Usage::

    from backend.ai.prompt_sanitizer import sanitize_field

    safe = sanitize_field(user_input, max_length=500)
"""

from __future__ import annotations

import re

# Patterns that attempt to override system instructions or inject new roles
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    # Role injection attempts
    re.compile(r"\b(system|assistant)\s*:", re.IGNORECASE),
    # Direct instruction overrides
    re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    # New instruction injection
    re.compile(r"(new|updated|revised)\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"act\s+as\s+(a\s+)?different", re.IGNORECASE),
    # Backtick/markdown fence role overrides
    re.compile(r"```\s*(system|assistant)\s*\n", re.IGNORECASE),
]

# Replacement for matched patterns — neutralizes without removing content
_REPLACEMENT = "[filtered]"


def sanitize_field(value: str, max_length: int = 500) -> str:
    """Sanitize a user-controlled field before LLM prompt interpolation.

    - Strips known injection patterns
    - Truncates to *max_length* characters
    - Returns the cleaned string
    """
    if not value:
        return value

    result = value
    for pattern in _INJECTION_PATTERNS:
        result = pattern.sub(_REPLACEMENT, result)

    if len(result) > max_length:
        result = result[:max_length]

    return result


def sanitize_chat_message(message: str, max_length: int = 4000) -> str:
    """Lighter sanitization for direct chat messages.

    Chat messages are the legitimate user input channel — we only strip
    the most dangerous patterns (role injection, instruction overrides)
    without being overly aggressive.
    """
    if not message:
        return message

    result = message
    for pattern in _INJECTION_PATTERNS:
        result = pattern.sub(_REPLACEMENT, result)

    if len(result) > max_length:
        result = result[:max_length]

    return result
