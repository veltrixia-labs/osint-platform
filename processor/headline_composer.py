"""
High-context OSINT headline composer.

Transforms flat, repetitive cluster labels ("Iran oil attack") into distinct,
analyst-grade headlines by blending three semantic dimensions extracted from the
aggregated source material:

  • Mechanism / Method     — HOW it happened (drone strike, cyber payload, …)
  • Granular Asset/Location — micro-geography (Kharg Island, Strait of Hormuz, …)
  • Strategic Trajectory    — the analyst implication, keyed to the domain

Deterministic + dependency-free (no LLM): the same inputs always produce the same
headline, so it is safe to run at ingest AND to backfill historical rows. When the
dimensions can't be extracted, it falls back to the richest real article headline,
and only as a last resort to a trajectory-blended entity clause — the bare generic
noun-pair is never emitted.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Mechanism keyword groups → canonical phrase. First match (top-down) wins, so
# more specific / higher-signal mechanisms are listed first.
_MECHANISMS: List[tuple[tuple[str, ...], str]] = [
    (("drone", "uav", "uas", "loitering muniti"), "Drone strike"),
    (("missile", "ballistic", "cruise missile", "telemetry", "rocket"), "Missile strike"),
    (("cyber", "malware", "ransomware", "hacك", "hacked", "breach", "payload", "ddos", "intrusion"), "Cyber payload"),
    (("naval", "blockade", "interdict", "interception", "warship", "frigate", "seized", "seizure", "boarding"), "Naval interception"),
    (("airstrike", "air strike", "air raid", "bombard", "shelling"), "Airstrike"),
    (("explosion", "blast", "detonation", "ignite", "fire at", "ablaze"), "Blast and fire"),
    (("sanction", "embargo", "export control", "blacklist"), "Sanctions escalation"),
    (("pipeline", "rupture", "leak", "spill", "outage"), "Infrastructure rupture"),
    (("protest", "walkout", "strike action", "unrest", "riot"), "Civil unrest"),
    (("seize", "raid", "incursion", "assault", "attack", "strike"), "Armed strike"),
]

# Micro-geography gazetteer — checked longest-first so multi-word sites win over
# bare country names. Extend freely as new corridors enter the feed.
_MICRO_LOCATIONS: List[str] = [
    "Strait of Hormuz", "Hormuz Strait", "Bab el-Mandeb", "Strait of Malacca",
    "Malacca Strait", "South China Sea", "Taiwan Strait", "Gulf of Oman",
    "Persian Gulf", "Panama Canal", "Suez Canal", "Red Sea",
    "Kharg Island", "Bandar Abbas", "Ras Tanura", "Jebel Ali", "Fujairah",
    "Strasbourg", "Hormuz",
]

# Asset nouns (used when no named micro-location is present).
_ASSET_NOUNS: List[str] = [
    "crude terminal", "oil terminal", "export terminal", "refinery",
    "extraction hub", "tank farm", "pipeline", "naval base", "container port",
    "power grid", "data center", "foundry", "tanker",
]

# Strategic trajectory clause, keyed to the canonical strategic domain id.
_TRAJECTORY: Dict[str, str] = {
    "energy_resource_risk": "sparking energy-supply friction",
    "global_market_intelligence": "rattling cross-asset risk sentiment",
    "defense_technology": "raising retaliatory-escalation risk",
    "supply_chain_intelligence": "threatening shipping-lane continuity",
    "crypto_geopolitics": "pressuring digital-asset liquidity",
    "ai_semiconductor_intelligence": "straining the tech supply chain",
}
_DEFAULT_TRAJECTORY = "elevating systemic risk"

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'.-]+")


def _stable_index(text: str, n: int) -> int:
    """Deterministic 0..n-1 selector (no PRNG → reproducible at ingest + backfill)."""
    if n <= 1:
        return 0
    return sum(ord(c) for c in text) % n


def _find_first(text_lower: str, candidates: List[str]) -> Optional[str]:
    for cand in sorted(candidates, key=len, reverse=True):
        if cand.lower() in text_lower:
            return cand
    return None


def _find_mechanism(text_lower: str) -> Optional[str]:
    for keywords, phrase in _MECHANISMS:
        if any(k in text_lower for k in keywords):
            return phrase
    return None


def is_generic_label(label: str) -> bool:
    """
    True for flat, repetitive cluster labels (e.g. "Iran oil attack") that dilute
    the feed: short word-count, no rich punctuation, and no extractable mechanism
    or micro-location. Real article headlines are longer / context-rich and pass.
    """
    if not label:
        return True
    s = label.strip()
    words = _WORD_RE.findall(s)
    if len(words) >= 7:
        return False  # long enough to be a real, specific headline
    # A *named* micro-location denotes genuine specificity — but only when it is
    # MULTI-WORD ("Strait of Hormuz"). A BARE single-token geo anchor ("Hormuz")
    # does NOT: short synthetic labels like "Hormuz oil sanction" / "Hormuz security
    # attack" must still read as generic so the composer upgrades them from real
    # evidence (otherwise the lone gazetteer hit on "Hormuz" let them pass as-is).
    # A bare mechanism word ("attack"/"strike") also does NOT confer specificity.
    loc = _find_first(s.lower(), _MICRO_LOCATIONS)
    if loc and len(loc.split()) >= 2:
        return False
    return len(words) <= 5


def _lead_entity(label: str) -> str:
    words = _WORD_RE.findall(label or "")
    return words[0].title() if words else ""


# Per-domain salient vocabulary — used to pick the evidence headline that matches
# THIS cluster's specific angle (oil vs shipping vs crypto vs ceasefire), so two
# clusters sharing a "Hormuz" context surface their differential facts, not the
# same popular article.
_DOMAIN_KEYWORDS: Dict[str, frozenset] = {
    "energy_resource_risk": frozenset({
        "oil", "crude", "gas", "lng", "barrel", "barrels", "opec", "refinery",
        "pipeline", "tanker", "tankers", "energy", "fuel", "spr", "diesel", "gasoline"}),
    "global_market_intelligence": frozenset({
        "price", "prices", "market", "markets", "stock", "stocks", "asset", "assets",
        "etf", "bond", "bonds", "yield", "equity", "selloff", "slump", "rally",
        "inflation", "recession", "futures", "index"}),
    "supply_chain_intelligence": frozenset({
        "ship", "ships", "shipping", "sailor", "sailors", "crew", "port", "ports",
        "blockade", "canal", "strait", "cargo", "freight", "vessel", "vessels",
        "logistics", "posidonia", "maritime", "container"}),
    "crypto_geopolitics": frozenset({
        "crypto", "bitcoin", "btc", "ether", "ethereum", "token", "tokens",
        "stablecoin", "digital", "blockchain", "exchange"}),
    "defense_technology": frozenset({
        "strike", "strikes", "military", "missile", "missiles", "drone", "drones",
        "attack", "attacks", "forces", "troops", "airstrike", "warship", "navy", "war"}),
    "ai_semiconductor_intelligence": frozenset({
        "chip", "chips", "semiconductor", "semiconductors", "ai", "gpu", "foundry",
        "tsmc", "nvidia", "lithography", "wafer"}),
}


def _best_real_headline(
    titles: List[str], *, context_tokens: frozenset = frozenset(), domain: Optional[str] = None
) -> Optional[str]:
    """Pick the specific source headline that best fits THIS cluster's angle.

    Scored by overlap with the cluster's salient vocabulary (target-label tokens +
    the domain keyword set) so distinct clusters that merely share a "Hormuz"
    context surface DIFFERENT, angle-specific headlines instead of the same longest
    or first shared article. Richness and source order break ties. Generic/slug
    titles are ignored.
    """
    salient = set(context_tokens) | set(_DOMAIN_KEYWORDS.get(domain or "", frozenset()))
    best: Optional[str] = None
    best_score = -1.0
    for idx, t in enumerate(titles):
        t = (t or "").strip()
        if not t or is_generic_label(t):
            continue
        words = _WORD_RE.findall(t.lower())
        relevance = len(set(words) & salient)
        # Angle relevance dominates; richer headline next; earlier (higher-ranked
        # evidence) as a small tiebreak.
        score = relevance * 100 + min(len(words), 24) - idx * 0.5
        if score > best_score:
            best, best_score = t, score
    return best


def compose_headline(
    *,
    target_label: str,
    description: str = "",
    evidence_list: Optional[List[Dict[str, Any]]] = None,
    domain: Optional[str] = None,
) -> str:
    """Compose a distinct, context-blended headline (see module docstring)."""
    titles = [
        (e.get("title") or "").strip()
        for e in (evidence_list or [])
        if isinstance(e, dict) and (e.get("title") or "").strip()
    ]
    blob = " . ".join([target_label or "", description or "", *titles])
    blob_low = blob.lower()
    trajectory = _TRAJECTORY.get(domain or "", _DEFAULT_TRAJECTORY)

    # 1) Prefer a SPECIFIC real source headline chosen by THIS cluster's DOMAIN
    #    angle (oil vs shipping vs crypto vs ...). Scoring on domain keywords —
    #    NOT the shared geo anchor — reflects each cluster's differential facts, so
    #    two clusters sharing a "Hormuz" context no longer collapse to one string.
    real = _best_real_headline(titles, domain=domain)
    if real:
        return real if len(real) <= 160 else real[:157].rstrip() + "..."

    # 2) Fallback ONLY when no usable real headline exists: synthesize an
    #    analyst-grade line. ASCII-safe separators (commas, not em-dashes) so
    #    titles never trip Windows cp932 console/log encoders on this stack.
    mechanism = _find_mechanism(blob_low)
    place = _find_first(blob_low, _MICRO_LOCATIONS) or _find_first(blob_low, _ASSET_NOUNS)
    if mechanism and place:
        return f"{mechanism} at {place}, {trajectory}"
    if mechanism:
        ent = _lead_entity(target_label)
        return f"{mechanism}{(' near ' + ent) if ent else ''}, {trajectory}"
    if place:
        return f"Escalation at {place}, {trajectory}"

    ent = _lead_entity(target_label)
    return f"{ent or 'Cross-sector'} pressure signal, {trajectory}"
