"""Text normalization utilities — clean Unicode artifacts from PDF extraction and report data.

CIS benchmark PDFs contain typographic characters (smart quotes, em dashes,
bullets, non-breaking spaces, etc.) that look malformed or inconsistent when
displayed in the web UI or exported reports.  This module provides a single
``normalize_unicode`` function that replaces them with their plain-ASCII
equivalents.
"""

from __future__ import annotations

import re
import unicodedata

# Character-level replacements
_UNICODE_MAP: dict[str, str] = {
    # Smart / curly quotes → ASCII
    "\u2018": "'",   # left single quote
    "\u2019": "'",   # right single quote (apostrophe)
    "\u201A": "'",   # single low-9 quote
    "\u201C": '"',   # left double quote
    "\u201D": '"',   # right double quote
    "\u201E": '"',   # double low-9 quote
    "\u00AB": '"',   # left-pointing double angle
    "\u00BB": '"',   # right-pointing double angle

    # Dashes → ASCII hyphen / double-hyphen
    "\u2010": "-",   # hyphen
    "\u2011": "-",   # non-breaking hyphen
    "\u2012": "-",   # figure dash
    "\u2013": "-",   # en dash
    "\u2014": " - ", # em dash → spaced hyphen for readability

    # Spaces → regular space
    "\u00A0": " ",   # non-breaking space
    "\u2002": " ",   # en space
    "\u2003": " ",   # em space
    "\u2004": " ",   # three-per-em space
    "\u2005": " ",   # four-per-em space
    "\u2006": " ",   # six-per-em space
    "\u2007": " ",   # figure space
    "\u2008": " ",   # punctuation space
    "\u2009": " ",   # thin space
    "\u200A": " ",   # hair space
    "\u200B": "",    # zero-width space (remove)
    "\u202F": " ",   # narrow no-break space
    "\u205F": " ",   # medium mathematical space
    "\uFEFF": "",    # BOM / zero-width no-break space

    # Bullets / symbols → ASCII
    "\u2022": "-",   # bullet
    "\u2023": "-",   # triangular bullet
    "\u25AA": "-",   # small black square
    "\u25CF": "-",   # black circle
    "\u25CB": "-",   # white circle
    "\u25A0": "-",   # black square
    "\u25B6": ">",   # right-pointing triangle
    "\u25BA": ">",   # right-pointing pointer

    # Misc
    "\u2026": "...", # horizontal ellipsis
    "\u2122": "(TM)",# trademark
    "\u00AE": "(R)", # registered
    "\u00A9": "(C)", # copyright
    "\u00B4": "'",   # acute accent
    "\u2192": "->",  # right arrow
    "\u2190": "<-",  # left arrow

    # Windows-specific control chars sometimes in PowerShell output
    "\r\n": "\n",    # CRLF → LF
}

# Build a single-pass translation table for simple 1-char replacements
_TRANS_TABLE = str.maketrans({
    k: v for k, v in _UNICODE_MAP.items() if len(k) == 1
})

# Multi-char replacements (e.g. "\r\n")
_MULTI_CHAR_REPLACEMENTS = {
    k: v for k, v in _UNICODE_MAP.items() if len(k) > 1
}

# Collapse multiple consecutive spaces into one
_MULTI_SPACE = re.compile(r"  +")


def normalize_unicode(text: str | None) -> str:
    """Replace typographic Unicode characters with plain ASCII equivalents.

    Safe to call on any text — returns the original string (or empty) if
    there is nothing to normalise.
    """
    if not text:
        return text or ""

    # Multi-char replacements first
    for old, new in _MULTI_CHAR_REPLACEMENTS.items():
        text = text.replace(old, new)

    # Single-char translation (fast)
    text = text.translate(_TRANS_TABLE)

    # NFKC normalisation (decomposes ligatures, compatibility chars)
    text = unicodedata.normalize("NFKC", text)

    # Collapse runs of spaces left behind by replacements
    text = _MULTI_SPACE.sub(" ", text)

    return text


# Smart output truncation

def smart_truncate(text: str | None, max_chars: int = 400) -> dict:
    """Intelligently truncate long audit output, preserving context.

    Unlike a blind ``text[:300]`` slice, this function:
      - Preserves the **first 2 lines** and **last 2 lines** of multi-line output
      - Breaks at word boundaries when possible
      - Returns metadata about what was removed

    Returns
    -------
    dict
        ``{"text": str, "truncated": bool, "original_length": int, "lines_hidden": int}``
    """
    if not text:
        return {"text": "", "truncated": False, "original_length": 0, "lines_hidden": 0}

    original_length = len(text)
    if original_length <= max_chars:
        return {"text": text, "truncated": False, "original_length": original_length, "lines_hidden": 0}

    lines = text.splitlines()

    # For multi-line output: keep first 2 + last 2 lines if that fits
    if len(lines) > 5:
        head = lines[:2]
        tail = lines[-2:]
        head_text = "\n".join(head)
        tail_text = "\n".join(tail)
        combined = f"{head_text}\n[...{len(lines) - 4} lines hidden...]\n{tail_text}"
        if len(combined) <= max_chars + 80:  # allow slight overflow for readability
            return {
                "text": combined,
                "truncated": True,
                "original_length": original_length,
                "lines_hidden": len(lines) - 4,
            }

    # Fall back to character-level truncation at the last word boundary
    # Keep ~75% from the start and ~25% from the end
    head_budget = int(max_chars * 0.70)
    tail_budget = max_chars - head_budget - 30  # 30 chars for the indicator

    head_part = text[:head_budget]
    # Try to break at a word boundary
    last_space = head_part.rfind(' ')
    last_newline = head_part.rfind('\n')
    break_at = max(last_space, last_newline)
    if break_at > head_budget * 0.5:
        head_part = head_part[:break_at]

    tail_part = text[-tail_budget:] if tail_budget > 20 else ""
    if tail_part:
        first_space = tail_part.find(' ')
        first_newline = tail_part.find('\n')
        candidates = [x for x in (first_space, first_newline) if x >= 0]
        if candidates and min(candidates) < len(tail_part) * 0.3:
            tail_part = tail_part[min(candidates) + 1:]

    hidden_chars = original_length - len(head_part) - len(tail_part)
    indicator = f" [...{hidden_chars} chars hidden...] "

    result_text = head_part + indicator + tail_part if tail_part else head_part + f" [...truncated, {original_length} chars total]"

    return {
        "text": result_text.strip(),
        "truncated": True,
        "original_length": original_length,
        "lines_hidden": 0,
    }
