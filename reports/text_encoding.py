"""
UTF-8 text repair for report payloads and API responses.

Fixes classic mojibake where UTF-8 bytes were interpreted as Latin-1/CP1252
(e.g. 共有 displayed as å…±æœ‰).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping, MutableMapping, Sequence


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


def sanitize_unicode_text(value: str) -> str:
    """Normalize UTF-8 text for DB/API/UI (mojibake repair, NFC, strip replacement glyphs)."""
    if not value or not isinstance(value, str):
        return value
    text = repair_utf8_mojibake(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\ufffd", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
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
