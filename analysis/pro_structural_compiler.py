"""
Rule-based Pro Structural Brief compiler helpers: dynamic titles and timeline correlation.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from reports.text_encoding import sanitize_unicode_text

MIN_ALERT_CORRELATION = 0.22
MIN_NEWS_CORRELATION = 0.28
MIN_MACRO_TIMELINE_CORRELATION = 0.18

_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "into",
        "over",
        "under",
        "about",
        "after",
        "before",
        "risk",
        "alert",
        "news",
        "report",
        "says",
        "said",
        "will",
        "have",
        "been",
        "more",
        "than",
        "their",
        "structural",
        "impact",
        "brief",
        "intelligence",
    }
)


def _tokenize(text: str) -> Set[str]:
    if not text:
        return set()
    lower = text.lower()
    tokens: Set[str] = set()
    for match in re.findall(r"[a-z][a-z0-9\-]{2,}", lower):
        if match not in _STOPWORDS and len(match) >= 3:
            tokens.add(match)
    return tokens


def build_sector_vocabulary(
    config: Dict[str, Any],
    relevance_map: Dict[str, Any],
) -> Dict[str, Any]:
    """Entity/series phrase map for a Pro domain (BEA matrices + market series + exposure)."""
    phrases: Set[str] = set()
    series_ids: Set[str] = set()

    domain_id = (config.get("domain_id") or "").lower()
    for part in re.split(r"[_\s\-]+", domain_id):
        if len(part) >= 4:
            phrases.add(part)

    for key, desc in (relevance_map or {}).items():
        series_ids.add(str(key))
        if isinstance(desc, str):
            phrases |= _tokenize(desc)
        elif isinstance(desc, dict):
            for v in desc.values():
                if isinstance(v, str):
                    phrases |= _tokenize(v)

    for field in ("transmission_channels", "exposure_targets"):
        for item in config.get(field) or []:
            if isinstance(item, str):
                phrases |= _tokenize(item)

    struct = config.get("structural_data") or {}
    for provider_rows in struct.values():
        if isinstance(provider_rows, list):
            for sid in provider_rows:
                series_ids.add(str(sid))
                phrases |= _tokenize(str(sid))

    tmpl = config.get("signal_classification_template") or {}
    for key in ("primary_type", "rationale"):
        val = tmpl.get(key)
        if isinstance(val, str):
            phrases |= _tokenize(val)
    for st in tmpl.get("secondary_types") or []:
        if isinstance(st, str):
            phrases |= _tokenize(st.replace("_", " "))

    for wi in config.get("watch_indicators") or []:
        if isinstance(wi, dict):
            for key in ("indicator", "why_it_matters"):
                if wi.get(key):
                    phrases |= _tokenize(str(wi[key]))

    return {"phrases": phrases, "series_ids": series_ids}


def structural_correlation_score(
    text: str,
    vocabulary: Dict[str, Any],
    *,
    trigger_tokens: Optional[Set[str]] = None,
) -> float:
    """
    Quantified overlap between event text and sector structural vocabulary (0.0–1.0).
    """
    clean = sanitize_unicode_text(text or "")
    if not clean.strip():
        return 0.0

    tokens = _tokenize(clean)
    if not tokens:
        return 0.0

    phrases: Set[str] = vocabulary.get("phrases") or set()
    series_ids: Set[str] = vocabulary.get("series_ids") or set()
    lower = clean.lower()

    phrase_hits = len(tokens & phrases)
    trigger_hits = len(tokens & (trigger_tokens or set()))
    series_hits = sum(1 for sid in series_ids if sid and str(sid).lower() in lower)

    score = 0.0
    score += min(0.45, phrase_hits * 0.11)
    score += min(0.35, trigger_hits * 0.14)
    score += min(0.25, series_hits * 0.12)
    if trigger_hits >= 2:
        score += 0.15
    if phrase_hits >= 3:
        score += 0.1
    return min(1.0, score)


def _title_clip(text: str, max_len: int = 96) -> str:
    clean = sanitize_unicode_text(text or "").strip()
    clean = re.sub(r"\s+", " ", clean)
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rsplit(" ", 1)[0] + "…"


def build_dynamic_structural_title(context: Dict[str, Any]) -> str:
    """
    Context title from anchor OSINT signal + structural macro pressure (not generic sector template).
    """
    domain = context.get("domain") or {}
    sig = context.get("signal") or {}
    pf = context.get("predictive_forecast") or {}
    s_ctx = context.get("structural_context") or {}
    timeline = context.get("event_timeline") or []

    trigger_title = sanitize_unicode_text(sig.get("title") or "")
    if trigger_title and len(trigger_title) >= 12:
        generic = trigger_title.lower().startswith("structural impact brief")
        if not generic:
            return _title_clip(trigger_title)

    for ev in timeline:
        if ev.get("type") == "trigger" and ev.get("title"):
            t = sanitize_unicode_text(ev["title"])
            if t and len(t) >= 12:
                return _title_clip(t)

    macro = (s_ctx.get("macro_observations") or s_ctx.get("macro_display_cards") or [])
    top = macro[0] if macro else {}
    label = sanitize_unicode_text(top.get("display_name") or top.get("series_id") or "")
    chg = top.get("change_pct")
    domain_name = sanitize_unicode_text(domain.get("display_name") or "Structural Risk")

    vectors = pf.get("risk_vectors") or []
    if vectors:
        lead = sanitize_unicode_text(str(vectors[0]))
        lead = re.sub(r"^[^:]+:\s*", "", lead).strip()
        if lead and len(lead) >= 16:
            return _title_clip(lead)

    headline = sanitize_unicode_text(pf.get("headline") or "")
    if headline:
        part = headline.split(":", 1)[-1].strip()
        if len(part) >= 16:
            return _title_clip(part)

    if label and chg is not None:
        try:
            c = float(chg)
        except (TypeError, ValueError):
            c = 0.0
        if c > 0.75:
            verb = "Escalating"
        elif c < -0.75:
            verb = "Easing"
        else:
            verb = "Repricing"
        return _title_clip(f"{verb} {label} — {domain_name} Exposure")

    return _title_clip(f"{domain_name} Structural Risk Outlook")


def filter_correlated_alert_rows(
    rows: List[Any],
    *,
    domain_id: str,
    vocabulary: Dict[str, Any],
    trigger_tokens: Set[str],
    infer_domain_fn,
) -> List[Any]:
    """Keep alerts that map to the domain and pass structural correlation threshold."""
    selected: List[Any] = []
    for row in rows:
        row_domain = infer_domain_fn(row.topic or "")
        label = sanitize_unicode_text(row.target_label or "")
        score = structural_correlation_score(label, vocabulary, trigger_tokens=trigger_tokens)
        if row_domain == domain_id:
            score = max(score, 0.55)
        if score >= MIN_ALERT_CORRELATION:
            selected.append(row)
    return selected


def filter_correlated_news_items(
    items: List[dict],
    vocabulary: Dict[str, Any],
    *,
    trigger_tokens: Set[str],
) -> List[dict]:
    out: List[dict] = []
    for item in items or []:
        title = item.get("title") or item.get("headline") or item.get("text") or ""
        score = structural_correlation_score(str(title), vocabulary, trigger_tokens=trigger_tokens)
        if score >= MIN_NEWS_CORRELATION:
            out.append(item)
    return out


def filter_correlated_timeline_events(events: List[dict]) -> List[dict]:
    """Drop low-correlation timeline rows; preserve trigger and structural macro rows."""
    kept: List[dict] = []
    for ev in events or []:
        source = ev.get("source") or ""
        if ev.get("type") == "trigger" or source in ("alert_log", "primary_signal"):
            kept.append(ev)
            continue
        if source in ("macro_data", "market_data"):
            coeff = ev.get("structural_correlation")
            if coeff is None or float(coeff) >= MIN_MACRO_TIMELINE_CORRELATION:
                kept.append(ev)
            continue
        coeff = ev.get("structural_correlation")
        if coeff is not None and float(coeff) >= MIN_NEWS_CORRELATION:
            kept.append(ev)
    return kept
