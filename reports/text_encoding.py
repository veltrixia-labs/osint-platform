"""
UTF-8 text repair for report payloads and API responses.

Fixes classic mojibake where UTF-8 bytes were interpreted as Latin-1/CP1252
(e.g. 共有 displayed as å…±æœ‰) and strips replacement glyphs from broken feeds.
"""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any, Mapping

# Common accent fragments when UTF-8/Latin-1 round-trips fail in RSS pipelines
_ACCENT_FRAGMENT_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bd\s+vu\b", re.I), "déjà vu"),
    (re.compile(r"\bd\s+j\s+a\b", re.I), "déjà"),
    (re.compile(r"\bdeja\s+vu\b", re.I), "déjà vu"),
    (re.compile(r"\bDj\s+vu\b"), "Déjà vu"),
    (re.compile(r"\bdj\s+vu\b", re.I), "déjà vu"),
]


def repair_utf8_mojibake(value: str) -> str:
    """Attempt Latin-1 → UTF-8 repair when the string looks mis-decoded."""
    if not value or not isinstance(value, str):
        return value
    if not _looks_like_mojibake(value):
        return value
    try:
        repaired = value.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return value
    if repaired and repaired != value:
        return repair_utf8_mojibake(repaired)
    return repaired


def _looks_like_mojibake(value: str) -> bool:
    for ch in value:
        o = ord(ch)
        if 0x80 <= o <= 0xFF:
            return True
        if ch in ("â", "Ã", "æ", "œ", "å", "…"):
            return True
    return False


def decode_response_text(raw: bytes, *, encoding: str = "utf-8") -> str:
    """Decode HTTP/RSS body bytes with UTF-8 preference."""
    if not raw:
        return ""
    try:
        return raw.decode(encoding, errors="strict")
    except UnicodeDecodeError:
        return raw.decode(encoding, errors="replace")


def sanitize_unicode_text(value: str) -> str:
    """Normalize UTF-8 text for DB/API/UI (mojibake repair, NFC, strip replacement glyphs)."""
    if not value or not isinstance(value, str):
        return value
    text = repair_utf8_mojibake(value)
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\ufffd", "")
    for pattern, replacement in _ACCENT_FRAGMENT_FIXES:
        text = pattern.sub(replacement, text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def sanitize_unicode_tree(data: Any) -> Any:
    """Recursively repair strings in dict/list payloads before JSON persistence."""
    if isinstance(data, str):
        return sanitize_unicode_text(data)
    if isinstance(data, Mapping):
        return {k: sanitize_unicode_tree(v) for k, v in data.items()}
    if isinstance(data, list):
        return [sanitize_unicode_tree(v) for v in data]
    if isinstance(data, tuple):
        return tuple(sanitize_unicode_tree(v) for v in data)
    return data
