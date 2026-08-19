"""
Rule-based Pro Structural Brief compiler helpers: dynamic titles, timeline
correlation, institutional-grade noise filters, and structured section
builders for Cascading Impacts / Tail Risks / Quantitative Evidence.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from reports.text_encoding import sanitize_unicode_text

# === Strict signal/noise thresholds ==========================================
# Bumped to institutional grade: any item below these scores is dropped before
# it can reach the Pro brief. Values are intentionally NOT environment-driven
# so production reports cannot silently degrade.
MIN_ALERT_CORRELATION: float = 0.30           # was 0.22
MIN_NEWS_CORRELATION: float = 0.35            # was 0.28
MIN_MACRO_TIMELINE_CORRELATION: float = 0.22  # was 0.18

# Lower bound on the structural correlation a news item must have BEFORE the
# sensationalism filter is even applied. Below this, the item is rejected
# regardless of phrasing.
MIN_PUBLISHABLE_CORRELATION: float = 0.25

# Re-trigger gate: a previously-suppressed alert may only re-enter the report
# pipeline if its new intensity is at least 1.5x the prior peak.
PRO_REPORT_REIGNITE_FACTOR: float = 1.5
# Cluster window for "related alert" lookups in the Pro pipeline. Anything
# outside this window is treated as a separate event regime.
PRO_REPORT_CLUSTER_WINDOW_HOURS: int = 24

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


_FEED_PREFIX_RE = re.compile(
    r"^(?:"
    r"Rocket Report|Breaking(?:\s+News)?|Live(?:\s+Updates)?|Update|Exclusive|Watch|"
    r"Alert|News Alert|Daily Report|Morning Brief|Opinion|Analysis|"
    r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+Report"
    r")\s*:\s*",
    re.I,
)

_DOMAIN_THEME_PREFIX: Dict[str, str] = {
    "energy_resource_risk": "Strategic Energy Repricing",
    "global_market_intelligence": "Global Market Structural Shift",
    "ai_semiconductor_intelligence": "Semiconductor Supply Structural Pressure",
    "supply_chain_intelligence": "Supply Chain Structural Disruption",
    "crypto_geopolitics": "Digital Asset Geopolitical Repricing",
    "defense_technology": "Strategic Aerospace Escalation",
}

_DOMAIN_EXPOSURE_HOOK: Dict[str, str] = {
    "energy_resource_risk": "Assessing Crude Corridor & Refining Utilization Exposure",
    "global_market_intelligence": "Assessing Cross-Asset Risk Transmission & Liquidity Exposure",
    "ai_semiconductor_intelligence": "Assessing Fab Capacity & Export-Control Exposure",
    "supply_chain_intelligence": "Assessing Logistics Bottleneck & Inventory Exposure",
    "crypto_geopolitics": "Assessing Stablecoin Rails & Regulatory Transmission Exposure",
    "defense_technology": "Assessing Aerospace Escalation & Defense Supply Exposure",
}

_RAW_FEED_VERB_RE = re.compile(
    r"\b(claims?|says?|said|reports?|according to|announces?|launches?|taps|partners?|"
    r"unveils?|files|beats|misses|earnings|IPO)\b",
    re.I,
)

_GEO_TOKENS = frozenset(
    {
        "russia",
        "europe",
        "european",
        "china",
        "ukraine",
        "middle",
        "east",
        "hormuz",
        "strait",
        "nato",
        "iran",
        "israel",
        "taiwan",
        "korea",
        "india",
        "belarus",
        "logistics",
        "aerospace",
        "semiconductor",
        "energy",
        "oil",
        "crude",
    }
)


def strip_feed_artifacts(text: str) -> str:
    """Remove RSS/channel prefixes and trailing feed clutter from a headline."""
    t = sanitize_unicode_text(text or "")
    while True:
        match = _FEED_PREFIX_RE.match(t)
        if not match:
            break
        t = t[match.end() :].strip()
    if ";" in t:
        t = t.split(";", 1)[0].strip()
    t = re.sub(r"\s+[-–—]\s+[^.!?]{0,80}$", "", t).strip()
    return t


def _exposure_hook_from_headline(headline: str, domain_id: str) -> str:
    if _RAW_FEED_VERB_RE.search(headline):
        return _DOMAIN_EXPOSURE_HOOK.get(domain_id, "Cross-Sector Structural Exposure Assessment")

    lower = headline.lower()
    geo_hits = [tok for tok in _GEO_TOKENS if tok in lower]
    if "europe" in lower and ("russia" in lower or "belarus" in lower):
        return "Assessing Russia-Europe Logistics & Security Exposure"
    if "hormuz" in lower or "strait" in lower:
        return "Assessing Maritime Chokepoint & Energy Corridor Exposure"
    if len(geo_hits) >= 2:
        a, b = geo_hits[0].title(), geo_hits[1].title()
        return f"Assessing {a}-{b} Structural Exposure"
    if geo_hits:
        return f"Assessing {geo_hits[0].title()} Sector & Supply-Chain Exposure"

    hook = re.sub(
        r"\b(claims?|says?|said|reports?|according to|announces?|launches?)\b.*",
        "",
        headline,
        flags=re.I,
    ).strip(" ,:-")
    if len(hook) >= 20:
        return f"Assessing {hook[:72]}"
    return "Cross-Sector Structural Exposure Assessment"


def synthesize_structural_title(raw_headline: str, context: Dict[str, Any]) -> str:
    """
    Convert a raw OSINT headline into an objective macro-structural intelligence title.
    """
    domain = context.get("domain") or {}
    domain_id = (domain.get("domain_id") or "global_market_intelligence").strip()
    theme = _DOMAIN_THEME_PREFIX.get(domain_id, f"{domain.get('display_name', 'Structural')} Assessment")
    core = strip_feed_artifacts(raw_headline)
    if not core or len(core) < 8:
        return _title_clip(f"{theme}: Cross-Sector Exposure Assessment")
    hook = _exposure_hook_from_headline(core, domain_id)
    return _title_clip(f"{theme}: {hook}")


def build_dynamic_structural_title(context: Dict[str, Any]) -> str:
    """
    Context title from anchor OSINT signal + structural macro pressure (not generic sector template).
    """
    domain = context.get("domain") or {}
    sig = context.get("signal") or {}
    timeline = context.get("event_timeline") or []

    trigger_title = sanitize_unicode_text(sig.get("title") or "")
    if trigger_title and len(trigger_title) >= 12:
        generic = trigger_title.lower().startswith("structural impact brief")
        if not generic:
            return synthesize_structural_title(trigger_title, context)

    for ev in timeline:
        if ev.get("type") == "trigger" and ev.get("title"):
            t = sanitize_unicode_text(ev["title"])
            if t and len(t) >= 12:
                return synthesize_structural_title(t, context)

    domain_name = sanitize_unicode_text(domain.get("display_name") or "Structural Risk")

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
    """Keep only news rows that are both structurally relevant AND not sensationalist."""
    out: List[dict] = []
    for item in items or []:
        title = item.get("title") or item.get("headline") or item.get("text") or ""
        score = structural_correlation_score(str(title), vocabulary, trigger_tokens=trigger_tokens)
        if score < MIN_NEWS_CORRELATION:
            continue
        if is_sensationalist(str(title)) and score < 0.55:
            # Only retain sensationalist phrasing when correlation is strong
            # enough to overcome the credibility penalty.
            continue
        if not is_credible_source(item):
            continue
        out.append(item)
    return out


# === Institutional tone & credibility filters ================================

# Dramatic / clickbait adjectives and verbs that flag low-credibility framing.
_SENSATIONAL_TOKENS: Set[str] = frozenset({
    "shocking", "shock", "shocked",
    "explosive", "explode", "explodes",
    "stunning", "stunned",
    "unprecedented",
    "panic", "panicking",
    "meltdown", "crashing", "plunging",
    "skyrocketing", "soaring", "rocketing",
    "doomed", "doomsday",
    "catastrophic", "catastrophe",
    "bombshell",
    "outrage", "outraged",
    "insane", "crazy",
    "viral",
    "you won't believe", "you wont believe",
    "must see", "must-see",
    "jaw-dropping", "jaw dropping",
    "mind-blowing", "mind blowing",
    "shake up the world",
})

# Sources we will not accept as supporting evidence regardless of score.
_LOW_CREDIBILITY_DOMAINS: Set[str] = frozenset({
    "facebook.com", "twitter.com", "x.com", "tiktok.com",
    "reddit.com",  # raw social aggregator (Pro reports require reporting outlets)
    "rumormillnews.com", "infowars.com", "naturalnews.com",
    "beforeitsnews.com",
})


def is_sensationalist(text: str) -> bool:
    """True if the text contains clickbait/dramatic phrasing typical of low-signal feeds."""
    if not text:
        return False
    lower = text.lower()
    for phrase in _SENSATIONAL_TOKENS:
        # multi-word phrases checked as substring, single tokens as word match
        if " " in phrase or "-" in phrase:
            if phrase in lower:
                return True
        else:
            if re.search(rf"\b{re.escape(phrase)}\b", lower):
                return True
    # Excess punctuation is another sensationalism marker.
    if text.count("!") >= 2 or text.count("?!") >= 1:
        return True
    if re.search(r"[A-Z]{6,}", text):  # SHOUTING tokens of 6+ chars
        return True
    return False


def is_credible_source(item: dict) -> bool:
    """Reject items pointing exclusively to known-low-credibility domains."""
    url = (item.get("url") or item.get("link") or item.get("source_url") or "").lower()
    if not url:
        return True  # missing url is not itself a credibility failure
    for bad in _LOW_CREDIBILITY_DOMAINS:
        if bad in url:
            return False
    return True


# Adjective downgrades used by `enforce_institutional_tone`. Mapping is
# deliberately conservative — we lower the temperature, not the meaning.
_TONE_SUBSTITUTIONS: List[tuple] = [
    (r"\bshocking(ly)?\b",                "notable"),
    (r"\bexplosi(ve|vely|on|ons)\b",      "sharp move"),
    (r"\bexplod(e|es|ed|ing)\b",          "moved sharply"),
    (r"\bstunning(ly)?\b",                "marked"),
    (r"\bunprecedented(ly)?\b",   "elevated"),
    (r"\bcatastrophic(ally)?\b",  "severe"),
    (r"\bskyrocket(ing|ed|s)?\b", "rising sharply"),
    (r"\bsoar(ing|ed|s)?\b",      "rising"),
    (r"\bplung(e|ed|ing|es)\b",   "decline"),
    (r"\bcrash(ing|ed|es)?\b",    "decline"),
    (r"\bmeltdown\b",             "dislocation"),
    (r"\bpanic(king|ked)?\b",     "stress"),
    (r"\bbombshell\b",            "material development"),
    (r"\boutrage(ous|d)?\b",      "contested"),
    (r"\binsane(ly)?\b",          "extreme"),
    (r"\bcrazy\b",                "anomalous"),
    (r"\bdoom(ed|sday)?\b",       "downside scenario"),
    # punctuation
    (r"!!+", "."),
    (r"\?!", "?"),
]


def enforce_institutional_tone(text: str) -> str:
    """Rewrite sensational adjectives to neutral, institutional-grade phrasing."""
    if not text:
        return text
    out = text
    for pattern, replacement in _TONE_SUBSTITUTIONS:
        out = re.sub(pattern, replacement, out, flags=re.I)
    # Collapse double spaces caused by punctuation downgrades.
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out


# === Structured section builders =============================================

def _quantitative_strength_label(corr: Optional[float]) -> str:
    """Map a clipped Pearson correlation to a qualitative strength label."""
    if corr is None:
        return "—"
    a = abs(corr)
    if a >= 0.7:
        return "Strong"
    if a >= 0.4:
        return "Moderate"
    if a >= 0.2:
        return "Weak"
    return "Negligible"


def build_cascading_impacts(
    domain_config: Dict[str, Any],
    macro_observations: Optional[List[dict]] = None,
    cross_domain_spillover: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """
    Compose a 3-tier cascading impact map purely from existing domain config
    plus observed macro moves — no LLM, no speculation.

    Tier 1 (direct): exposure_matrix_details with sensitivity == "high".
    Tier 2 (downstream): exposure_matrix_details medium + transmission_channels.
    Tier 3 (systemic spillover): cross-domain hand-offs derived from
        `cross_domain_spillover` (defaults to a curated map).
    """
    exposure = domain_config.get("exposure_matrix_details") or []
    channels = domain_config.get("transmission_channels") or []
    domain_id = (domain_config.get("domain_id") or "").strip()

    spillover_map = cross_domain_spillover or _DEFAULT_CROSS_DOMAIN_SPILLOVER

    tier1: List[dict] = []
    tier2: List[dict] = []
    for row in exposure:
        if not isinstance(row, dict):
            continue
        sensitivity = (row.get("sensitivity") or "").lower()
        entry = {
            "target": sanitize_unicode_text(row.get("target") or ""),
            "transmission": sanitize_unicode_text(row.get("transmission") or ""),
            "rationale": enforce_institutional_tone(
                sanitize_unicode_text(row.get("reason") or "")
            ),
            "sensitivity": sensitivity or "unspecified",
        }
        if sensitivity == "high":
            tier1.append(entry)
        else:
            tier2.append(entry)

    tier2_channels = [
        {"channel": sanitize_unicode_text(c), "note": "Indirect mechanism"}
        for c in channels
        if isinstance(c, str) and c.strip()
    ]

    tier3 = [
        {
            "spillover_domain": sd,
            "mechanism": enforce_institutional_tone(
                f"Output volatility in {domain_id} transmits to {sd} "
                f"through shared input pricing and risk-on/risk-off rotation."
            ),
        }
        for sd in spillover_map.get(domain_id, [])
    ]

    # Highlight any macro series that has moved >= 3% in lookback — flag as
    # active reinforcement of the cascade.
    macro_pressure: List[dict] = []
    for obs in macro_observations or []:
        chg = obs.get("change_pct")
        if chg is None:
            continue
        if abs(float(chg)) >= 3.0:
            macro_pressure.append({
                "series_id": obs.get("series_id"),
                "display_name": obs.get("display_name") or obs.get("series_id"),
                "change_pct": float(chg),
                "latest_date": obs.get("latest_date"),
                "span_days": obs.get("span_days"),
            })

    return {
        "tier_1_direct": tier1,
        "tier_2_downstream": tier2,
        "tier_2_channels": tier2_channels,
        "tier_3_systemic": tier3,
        "active_macro_pressure": macro_pressure,
    }


_DEFAULT_CROSS_DOMAIN_SPILLOVER: Dict[str, List[str]] = {
    "energy_resource_risk": [
        "supply_chain_intelligence", "global_market_intelligence",
    ],
    "supply_chain_intelligence": [
        "ai_semiconductor_intelligence", "defense_technology",
    ],
    "ai_semiconductor_intelligence": [
        "supply_chain_intelligence", "defense_technology",
    ],
    "defense_technology": [
        "energy_resource_risk", "ai_semiconductor_intelligence",
    ],
    "global_market_intelligence": [
        "crypto_geopolitics", "supply_chain_intelligence",
    ],
    "crypto_geopolitics": [
        "global_market_intelligence",
    ],
}


def build_tail_risk_scenarios(
    domain_config: Dict[str, Any],
    macro_observations: Optional[List[dict]] = None,
    quantitative_evidence: Optional[Dict[str, Any]] = None,
) -> List[dict]:
    """
    Surface low-probability / high-impact contrarian scenarios.
    Sources:
      1. balanced_interpretations.invalidating_conditions (from config)
      2. macro extreme moves (>= 5% lookback) — flagged as regime-break candidates
      3. quantitative_evidence: a strong (|corr| >= 0.5) but short-lag transmission
         is flagged as a contrarian acceleration risk.
    """
    out: List[dict] = []

    bi = domain_config.get("balanced_interpretations") or {}
    for cond in bi.get("invalidating_conditions") or []:
        if not isinstance(cond, str):
            continue
        out.append({
            "type": "thesis_invalidator",
            "scenario": enforce_institutional_tone(sanitize_unicode_text(cond)),
            "probability": "low",
            "impact": "high",
            "source": "domain_config.invalidating_conditions",
        })

    volatility_view = bi.get("volatility_view")
    if isinstance(volatility_view, str) and volatility_view.strip():
        out.append({
            "type": "stress_case",
            "scenario": enforce_institutional_tone(sanitize_unicode_text(volatility_view)),
            "probability": "moderate",
            "impact": "high",
            "source": "domain_config.balanced_interpretations.volatility_view",
        })

    for obs in macro_observations or []:
        chg = obs.get("change_pct")
        if chg is None:
            continue
        try:
            c = float(chg)
        except (TypeError, ValueError):
            continue
        if abs(c) >= 5.0:
            label = obs.get("display_name") or obs.get("series_id") or "Macro series"
            out.append({
                "type": "regime_break",
                "scenario": (
                    f"{label} moved {c:+.2f}% in the lookback window — a "
                    "magnitude consistent with regime-break risk if persistent."
                ),
                "probability": "moderate",
                "impact": "high",
                "source": f"macro:{obs.get('series_id')}",
            })

    qe = quantitative_evidence or {}
    corr = qe.get("correlation")
    lag = qe.get("lag_days")
    if isinstance(corr, (int, float)) and abs(corr) >= 0.5 and isinstance(lag, int) and 0 < lag <= 3:
        out.append({
            "type": "transmission_acceleration",
            "scenario": (
                f"Cross-correlation of {corr:+.2f} at a {lag}-day lag is short "
                "enough to compress decision windows; downside surprises in the "
                "macro signal would propagate to the sector within the trading week."
            ),
            "probability": "low",
            "impact": "high",
            "source": "macro_transmission_engine",
        })

    return out


def build_quantitative_evidence_matrix(
    macro_observations: Optional[List[dict]] = None,
    market_prices: Optional[List[dict]] = None,
    quantitative_evidence: Optional[Dict[str, Any]] = None,
    related_events: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Structured numeric block summarising the mathematics behind the brief.
    Values are clipped / sanitised so the matrix is safe to render verbatim.
    """
    qe = quantitative_evidence or {}

    # Top macro moves (largest |change_pct|, up to 5).
    macro_rows = []
    for obs in sorted(
        (m for m in macro_observations or [] if m.get("change_pct") is not None),
        key=lambda m: abs(float(m.get("change_pct") or 0.0)),
        reverse=True,
    )[:5]:
        macro_rows.append({
            "series_id": obs.get("series_id"),
            "display_name": obs.get("display_name") or obs.get("series_id"),
            "latest_value": obs.get("latest_value"),
            "change_pct": round(float(obs.get("change_pct")), 3),
            "latest_date": obs.get("latest_date"),
            "span_days": obs.get("span_days"),
        })

    # Top market moves (largest |percent_change|, up to 5).
    market_rows = []
    for p in sorted(
        (x for x in market_prices or [] if x.get("percent_change") is not None),
        key=lambda x: abs(float(x.get("percent_change") or 0.0)),
        reverse=True,
    )[:5]:
        market_rows.append({
            "symbol": p.get("symbol"),
            "asset_class": p.get("asset_class"),
            "latest_close": p.get("latest_close"),
            "percent_change": round(float(p.get("percent_change")), 3),
            "latest_date": p.get("latest_date"),
            "span_days": p.get("span_days"),
        })

    # Alert intensity stats from related events.
    intensities = []
    for ev in related_events or []:
        val = getattr(ev, "intensity", None)
        if val is None and isinstance(ev, dict):
            val = ev.get("intensity")
        if isinstance(val, (int, float)):
            intensities.append(float(val))
    intensity_stats = None
    if intensities:
        intensity_stats = {
            "count": len(intensities),
            "max": round(max(intensities), 2),
            "mean": round(sum(intensities) / len(intensities), 2),
        }

    # Transmission block (from macro_transmission engine).
    transmission_block = None
    if qe:
        # Defensive clip — the engine already clips, but never trust upstream.
        corr = qe.get("correlation")
        if isinstance(corr, (int, float)):
            corr = max(-1.0, min(1.0, float(corr)))
        beta = qe.get("beta")
        beta_val = float(beta) if isinstance(beta, (int, float)) else None
        transmission_block = {
            "source_series": qe.get("source"),
            "target_topic": qe.get("target"),
            "lag_days": qe.get("lag_days"),
            "correlation": round(corr, 3) if isinstance(corr, float) else corr,
            "correlation_strength": _quantitative_strength_label(corr if isinstance(corr, float) else None),
            "beta_log_return": round(beta_val, 4) if beta_val is not None else None,
            "sample_size": qe.get("sample_size"),
            "include_inverse": qe.get("include_inverse"),
            "methodology": "Log-return CCF on z-scored signals; correlation clipped to [-1, 1].",
        }

    return {
        "transmission": transmission_block,
        "top_macro_moves": macro_rows,
        "top_market_moves": market_rows,
        "alert_intensity_stats": intensity_stats,
        "schema_version": "quant_evidence_v1",
    }


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
