import asyncio
import re
import uuid
import logging
import os
import httpx
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.future import select
from sqlalchemy import desc, or_
from db.models import TrendSignal, EventCluster, Item, AlertLog, Report, AnalystProfile
from urllib.parse import urlparse
from processor.location_resolver import LocationResolver
from processor.lightweight_topic import infer_topic_from_text
from processor.topic_registry import CANONICAL_TOPICS, normalize_canonical_topic
from analysis.intensity_pressure import (
    decayed_domain_baseline,
    percentage_from_ratio,
    severity_from_percentage,
)
from analysis.pro_domain_config import infer_domain_from_topic
from processor.headline_composer import compose_headline, is_generic_label

logging.basicConfig(level=logging.INFO)

resolver = LocationResolver()
# [v14.3] Global set to prevent weak-reference garbage collection of background asyncio tasks
_bg_tasks = set()

logger = logging.getLogger(__name__)

# Config from Environment
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ALERT_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# Duplicate suppression: skip same headline within window unless intensity
# reignites. The env vars allow operators to TIGHTEN these guardrails (longer
# window, higher reignite factor) but never loosen them — the floors below are
# the institutional-grade defaults required by Pro report consumers.
_PRO_MIN_DEDUP_WINDOW_HOURS = 24      # cluster window floor
_PRO_MIN_REIGNITE_FACTOR    = 1.5     # 1.5x prior intensity to re-trigger

_raw_dedup_window = int(os.getenv("ALERT_DEDUP_WINDOW_HOURS", str(_PRO_MIN_DEDUP_WINDOW_HOURS)))
_raw_reignite_factor = float(os.getenv("REIGNITE_INTENSITY_FACTOR", str(_PRO_MIN_REIGNITE_FACTOR)))

ALERT_DEDUP_WINDOW_HOURS = max(_raw_dedup_window, _PRO_MIN_DEDUP_WINDOW_HOURS)
REIGNITE_INTENSITY_FACTOR = max(_raw_reignite_factor, _PRO_MIN_REIGNITE_FACTOR)

if _raw_dedup_window < _PRO_MIN_DEDUP_WINDOW_HOURS:
    logging.getLogger(__name__).warning(
        "ALERT_DEDUP_WINDOW_HOURS=%s was below the Pro-grade floor (%sh); clamped.",
        _raw_dedup_window, _PRO_MIN_DEDUP_WINDOW_HOURS,
    )
if _raw_reignite_factor < _PRO_MIN_REIGNITE_FACTOR:
    logging.getLogger(__name__).warning(
        "REIGNITE_INTENSITY_FACTOR=%s was below the Pro-grade floor (%.2fx); clamped.",
        _raw_reignite_factor, _PRO_MIN_REIGNITE_FACTOR,
    )

RECENT_ALERTS_FETCH_LIMIT = int(os.getenv("ALERT_DEDUP_FETCH_LIMIT", "400"))

ALLOWED_TREND_BASE_TYPES = frozenset({
    "risk_pattern",
    "risk_acceleration",
    "entity_heat",
    "sector_surge",
    "sustained_event",
})


def _is_allowed_trend_type(trend_type: str) -> bool:
    """Accept base trend types and trend_engine merge suffixes (e.g. risk_acceleration_merged)."""
    if trend_type in ALLOWED_TREND_BASE_TYPES:
        return True
    if trend_type.endswith("_merged"):
        base = trend_type[: -len("_merged")]
        return base in ALLOWED_TREND_BASE_TYPES
    return False


def _base_trend_type(trend_type: str) -> str:
    if trend_type.endswith("_merged"):
        return trend_type[: -len("_merged")]
    return trend_type


def _resolve_signal_topic(sig: TrendSignal) -> str:
    """Keyword / existing topic only — no LLM classification required."""
    text = f"{sig.target_label or ''} {sig.description or ''}"
    return infer_topic_from_text(text, raw_topic=sig.topic)


def _looks_like_source_label(label: str) -> bool:
    """True when label is likely a source slug (reddit, technip) rather than a headline."""
    if not label:
        return True
    s = label.strip()
    if len(s) < 4:
        return True
    if " " not in s and s.islower() and len(s) <= 28:
        return True
    if "." in s and " " not in s and len(s) <= 48:
        return True
    return False


def _resolve_display_label(sig: TrendSignal, evidence_list: List[Dict[str, str]]) -> str:
    """
    High-context Alert Stream headline. A genuinely rich, specific label passes
    through untouched; flat generic cluster labels ("Iran oil attack") and source
    slugs are upgraded by the headline composer, which blends mechanism +
    micro-geography + strategic trajectory (with a rich-source-headline fallback).
    """
    label = (sig.target_label or "").strip()
    if label and not _looks_like_source_label(label) and not is_generic_label(label):
        return label
    domain = infer_domain_from_topic(sig.topic or "", text=label)
    composed = compose_headline(
        target_label=label,
        description=(sig.description or ""),
        evidence_list=evidence_list or [],
        domain=domain,
    )
    return composed or label or "Untitled signal"


def _distinctify_title(title: str, evidence_list: List[Dict[str, str]]) -> str:
    """Append a source-driven micro-distinctifier so a re-fired (reignited) alert
    never carries a byte-identical headline to its predecessor on the timeline."""
    dom = ""
    for ev in (evidence_list or []):
        d = (ev.get("domain") or "").strip()
        if d:
            dom = d.replace("www.", "")
            break
    return f"{title} (via {dom})" if dom else f"{title} (re-escalation)"


def _normalize_alert_title(raw: str | None) -> str:
    """Lowercase collapsed whitespace for dedupe comparisons."""
    if not raw:
        return ""
    return " ".join(raw.strip().lower().split())


def _alert_title_keys(display_label: str, sig_target_label: str | None) -> set[str]:
    keys = {_normalize_alert_title(display_label), _normalize_alert_title(sig_target_label or "")}
    keys.discard("")
    return keys


# Window over which two feeds composing to the SAME elite headline must be
# differentiated rather than emitted as byte-identical rows.
HEADLINE_DIVERSIFY_WINDOW_HOURS = 6


def _diversify_headline(
    title: str,
    evidence_list: List[Dict[str, str]],
    used_keys: set[str],
) -> str:
    """Return a headline whose normalized key is NOT already in *used_keys*.

    Different premium feeds (nytimes.com, decrypt.co) can have the composer
    synthesize an identical string. To guarantee 100% individual row clarity we
    first append a source anchor ("… (via decrypt.co)"), then — only if that
    still collides (same source, same window) — a bounded numeric variant.
    """
    if _normalize_alert_title(title) not in used_keys:
        return title
    anchored = _distinctify_title(title, evidence_list)
    if _normalize_alert_title(anchored) not in used_keys:
        return anchored
    for n in range(2, 50):
        candidate = f"{anchored} #{n}"
        if _normalize_alert_title(candidate) not in used_keys:
            return candidate
    return anchored


# ── Event clustering ─────────────────────────────────────────────────────────
# Group articles about the SAME underlying event into one master alert instead
# of spamming the stream with near-duplicate rows.
CLUSTER_WINDOW_HOURS = 24
CLUSTER_SIM_THRESHOLD = 0.6                         # Jaccard on significant tokens → same event (high = precision over recall: only near-identical events cluster, never loosely-related geopolitics)
CLUSTER_OVERLAP_THRESHOLD = 0.75                    # containment (overlap-coef): one headline's core is >=75% inside the other → force-cluster despite trailing text
CLUSTER_MIN_SHARED = 4                              # min shared CORE tokens before the overlap path may fire (blocks short coincidental merges)
CLUSTER_ESCALATION_FACTOR = REIGNITE_INTENSITY_FACTOR  # ≥1.5× master intensity breaks through as new alert
CLUSTER_MAX_EVIDENCE = 40                           # cap merged corroborating sources on a master

_EVENT_STOPWORDS = frozenset({
    # >=4-char fillers
    "the", "and", "for", "with", "from", "into", "over", "under", "after", "before",
    "says", "said", "amid", "this", "that", "these", "those", "its", "their", "new",
    "more", "than", "out", "off", "via", "not", "will", "would", "could", "should",
    "may", "might", "report", "reports", "about", "have", "has", "had", "are", "was",
    "were", "been", "being", "they", "them", "what", "when", "where", "which", "while",
    # 3-char fillers (now that 3-char tokens are kept for short key terms like oil/gas)
    "you", "but", "all", "can", "her", "his", "him", "she", "who", "why", "how", "now",
    "one", "two", "get", "got", "let", "saw", "per", "see", "use", "due", "set", "amid",
})


def _stem(token: str) -> str:
    """Crude suffix stemmer so morphological variants match (seizes/seized→seiz,
    iran/iranian→iran). Conservative: only strips when a >=3-char root remains."""
    for suf in ("ians", "ian", "ing", "ied", "ies", "ed", "es", "s"):
        if token.endswith(suf) and len(token) - len(suf) >= 3:
            return token[: -len(suf)]
    return token


# Trailing distinctifiers appended by _distinctify_title / _diversify_headline
# ("(via decrypt.co)", "[via nyt]", "(re-escalation)", " #2"). These MUST be
# stripped before tokenizing — otherwise their unique tokens dilute the
# containment/Jaccard score and let near-identical headlines slip the cluster
# guard (the "Bessent … (via nytimes.com)" vs "… (via decrypt.co)" leak).
# "(via domain)" / "[via domain]" can appear ANYWHERE (e.g. target_label and
# display_title are concatenated for matching, so the tag occurs mid-string) —
# strip every occurrence. re-escalation / #N are only ever trailing.
_VIA_RE = re.compile(r"\s*[\(\[]\s*via\b[^\)\]]*[\)\]]", re.IGNORECASE)
_TRAIL_RE = re.compile(r"(?:\s*\(\s*re-?escalation\s*\)|\s*#\d+)\s*$", re.IGNORECASE)


def _strip_distinctifiers(text: str) -> str:
    """Remove source-anchor "(via …)" tags (anywhere) + trailing re-escalation/#N
    suffixes so two variants of the same headline tokenize identically."""
    s = _VIA_RE.sub("", text or "")
    prev = None
    while s != prev:
        prev = s
        s = _TRAIL_RE.sub("", s)
    return s.strip()


def _event_tokens(text: str) -> set[str]:
    """Significant, stemmed lowercase tokens (>=3 chars, non-stopword) for event
    matching — so paraphrases of the SAME event share most of their token set.
    Trailing (via …)/(re-escalation)/#N distinctifiers are stripped first."""
    cleaned = _strip_distinctifiers(text)
    return {
        _stem(t) for t in re.findall(r"[a-z0-9]+", cleaned.lower())
        if len(t) >= 3 and t not in _EVENT_STOPWORDS
    }


def _event_similarity(a: set[str], b: set[str]) -> float:
    """Combined event-match score in [0,1].

    Jaccard by default — but when two headlines share a strong CORE
    (>= CLUSTER_MIN_SHARED tokens) and one is highly contained in the other
    (overlap coefficient >= CLUSTER_OVERLAP_THRESHOLD), the higher score wins.
    That fuzzy/containment path is what catches close variants whose only
    difference is trailing text ("…Lebanon invasion" vs "…Lebanon invasion
    (via bbc.com)"), which a strict Jaccard would let slip through.
    """
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    jaccard = inter / len(a | b)
    overlap = inter / min(len(a), len(b))      # containment of the smaller set
    if inter >= CLUSTER_MIN_SHARED and overlap >= CLUSTER_OVERLAP_THRESHOLD:
        return max(jaccard, overlap)
    return jaccard


def _raw_intensity_for_alert(alert_log: AlertLog) -> float:
    """Uncapped intensity for dedupe / reignite (never the asymptotic UI index)."""
    meta = alert_log.metadata_json if isinstance(alert_log.metadata_json, dict) else {}
    raw = meta.get("raw_intensity")
    if raw is not None:
        return float(raw)
    return float(alert_log.intensity or 0.0)


def _prior_alert_title_keys(alert_log: AlertLog) -> set[str]:
    meta = alert_log.metadata_json if isinstance(alert_log.metadata_json, dict) else {}
    disp = meta.get("display_title") or ""
    keys = {_normalize_alert_title(alert_log.target_label), _normalize_alert_title(disp)}
    keys.discard("")
    return keys


def _physical_intensity(sig: TrendSignal) -> float:
    """Intensity from rule-based signal engine (cluster size, source authority, keywords)."""
    meta = sig.metrics_json if isinstance(sig.metrics_json, dict) else {}
    base = float(sig.intensity_score or 0.0)
    cluster_n = int(meta.get("supporting_cluster_count") or 0)
    if cluster_n >= 5:
        base = max(base, 2.6)
    if cluster_n >= 10:
        base = max(base, 3.0)
    return base


# Severity Thresholds (Phase 22 - Calibrated for Restoration)
# Evaluation Priority: Critical > Elevated > Watch
SEVERITY_CONFIG = {
    "critical": {"min_intensity": 8.0, "min_spike": 4.0, "min_domains": 8},
    "elevated": {"min_intensity": 4.5, "min_spike": 3.0, "min_domains": 3},
    "watch":    {"min_intensity": 2.5, "min_spike": 0.0, "min_domains": 2} # Used as Report Source only
}

class AlertManager:
    @classmethod
    async def evaluate_and_send(cls, db, new_signals: List[TrendSignal]):
        """Evaluates new signals for alerts with tiered severity and escalation logic."""
        # Phase 24: We now proceed with scoring and logging even if Telegram is disabled
        # Original: if not ALERT_ENABLED: return

        # Diversification guard: seed the keys of active (unsuppressed) headlines in
        # the last HEADLINE_DIVERSIFY_WINDOW_HOURS so two feeds that compose to an
        # identical elite headline get a source anchor instead of a duplicate row.
        batch_headline_keys = await cls._recent_headline_keys(db)

        for sig in new_signals:
            if not _is_allowed_trend_type(sig.trend_type):
                logger.info(
                    "Alert suppressed: disallowed trend_type=%r target=%r topic=%r",
                    sig.trend_type,
                    sig.target_label,
                    sig.topic,
                )
                continue

            internal_topic = _resolve_signal_topic(sig)
            topic = normalize_canonical_topic(
                internal_topic,
                trend_type=sig.trend_type,
            )
            intensity = _physical_intensity(sig)

            if topic not in CANONICAL_TOPICS:
                logger.info(
                    "Alert suppressed: topic outside strategic sectors topic=%r internal=%r target=%r",
                    topic,
                    internal_topic,
                    sig.target_label,
                )
                continue

            # Map the signal's trend_type to an appropriate display trigger_type
            trigger_type_map = {
                "risk_pattern": "pattern_risk",
                "risk_acceleration": "acceleration",
                "entity_heat": "entity_surge",
                "sector_surge": "sector_surge",
                "sustained_event": "event_continuation",
            }
            base_type = _base_trend_type(sig.trend_type)
            display_trigger_type = trigger_type_map.get(base_type, "pattern_risk")

            # 1. Gather Metrics for Severity
            domain_count, evidence_list, related_item_ids = await cls._get_evidence_metrics(db, sig)
            display_label = _resolve_display_label(sig, evidence_list)
            evidence_count = len(evidence_list)

            # No URL-backed sources → noise (strict).
            if domain_count == 0 or evidence_count == 0:
                logger.info(
                    "Alert suppressed: no evidence URLs (domain_count=%s evidence_count=%s) "
                    "target=%r topic=%r trend_type=%r",
                    domain_count,
                    evidence_count,
                    sig.target_label,
                    topic,
                    sig.trend_type,
                )
                continue

            spike_delta = await cls._get_spike_delta(db, sig)

            # 2. Creation floor (unchanged): keep alert volume stable — only
            #    signals that clear the platform minimums get logged at all.
            legacy_severity = cls._determine_severity(intensity, spike_delta, domain_count)
            if not legacy_severity:
                logger.info(
                    "Alert suppressed: no severity (intensity=%.2f, spike=%.2f, domains=%s) "
                    "target=%r topic=%r",
                    intensity,
                    spike_delta,
                    domain_count,
                    sig.target_label,
                    topic,
                )
                continue

            # 2b. Calibrated label: distributed ratio-% vs the alert's OWN strategic
            #     domain baseline → 3-tier gate (1.5x=50% ELEVATED, >=80% CRITICAL).
            #     Falls back to the legacy tier on cold-start (no per-domain history).
            now_utc = datetime.now(timezone.utc)
            alert_domain = infer_domain_from_topic(topic, text=display_label or sig.target_label or "")
            intensity_pct = await cls._domain_intensity_pct(db, alert_domain, intensity, now_utc)
            severity = severity_from_percentage(intensity_pct) if intensity_pct is not None else legacy_severity

            # 3. Event clustering (24h): if this signal is the SAME underlying event
            #    as an active master alert, absorb it as a corroborating source
            #    instead of creating a near-duplicate row. A >=1.5x intensity surge
            #    vs the master breaks through and emits a fresh escalated alert.
            master, escalated = await cls._find_event_cluster(
                db, sig, display_label, topic, intensity
            )
            if master is not None:
                if escalated:
                    # In-place BUMP: a >=1.5x surge refreshes the master's intensity/
                    # severity/pct and re-surfaces it (triggered_at = now) — it does
                    # NOT mint a new row (that was the "CRITICAL flood" cause).
                    await cls._bump_master(
                        db, master, sig, evidence_list, intensity, intensity_pct, severity, now_utc
                    )
                else:
                    await cls._absorb_into_master(db, master, sig, evidence_list, display_label)
                continue

            # 3b. Cross-source diversification — never emit two byte-identical
            # active headlines (different feeds can compose to the same string).
            display_label = _diversify_headline(display_label, evidence_list, batch_headline_keys)
            batch_headline_keys |= _alert_title_keys(display_label, sig.target_label)

            # 4. Intelligence Scoring (Phase 24)
            from jobs.alert_scoring import calculate_alert_score
            intel_score, breakdown = await calculate_alert_score(
                db, intensity, spike_delta, domain_count, display_trigger_type, sig.target_label
            )
            
            # 5. Personalization & Multi-Analyst Routing (Phase 25)
            from jobs.personalization_service import get_target_analysts
            targets = await get_target_analysts(db, sig.target_label, intel_score, severity, breakdown)
            
            # 6. Fetch additional context for linking
            report_id, anchor = await cls._get_latest_report_link(db, sig)
            
            # 7. Signal Fidelity & Master Alert Log Entry (Phase 2)
            # Fidelity is a measure of cross-domain verification (0.0-1.0)
            fidelity_score = min(1.0, (domain_count / 10.0) + 0.2) if domain_count > 0 else 0.1
            is_high_fidelity = fidelity_score >= 0.7 or (severity == "critical" and domain_count >= 3)

            is_system_wide = len(targets) == 0
            status = "confirmed"
            
            # Geotagging (Heuristic First) + location entity enrichment
            loc_text = f"{sig.target_label} {sig.description or ''}"
            loc_detail = resolver.resolve_heuristically_detailed(loc_text.strip())
            if loc_detail:
                coords = (loc_detail.lat, loc_detail.lng)
            else:
                coords = resolver.resolve_heuristically(loc_text.strip())
            lat, lng = coords if coords else (None, None)

            meta_base: dict = {
                    "spike_delta": round(float(spike_delta), 2),
                    "domain_count": domain_count,
                    "evidence_list": evidence_list, # Requirement #2
                    "scoring_breakdown": breakdown,
                    "related_item_ids": related_item_ids,
                    "description": sig.description or "",
                    "display_title": display_label,
                    "internal_topic": internal_topic,
                    "raw_intensity": round(float(intensity), 3),
                    "intensity_pct": round(float(intensity_pct), 1) if intensity_pct is not None else None,
            }
            if loc_detail:
                meta_base["location_entity_id"] = loc_detail.entity_id
                meta_base["location_resolution"] = {
                    "entity_id": loc_detail.entity_id,
                    "display_name": loc_detail.display_name,
                    "confidence": loc_detail.confidence,
                    "match_type": loc_detail.match_type,
                    "matched_text": loc_detail.matched_text,
                }

            try:
                from sqlalchemy.orm.attributes import flag_modified
                from processor.impact_discovery import ImpactDiscoveryEngine

                alert_log = AlertLog(
                    target_label=display_label,
                    topic=topic,
                    trigger_type=display_trigger_type,
                    severity=severity,
                    intensity=intensity,
                    intelligence_score=intel_score,
                    fidelity_score=fidelity_score,
                    is_high_fidelity=is_high_fidelity,
                    section_anchor=anchor,
                    related_report_id=report_id,
                    status=status,
                    is_system_wide=is_system_wide,
                    supporting_events_count=len(evidence_list),
                    location_lat=lat,
                    location_lng=lng,
                    metadata_json=dict(meta_base),
                )
                db.add(alert_log)
                await db.flush()

                alert_log.metadata_json["backbone_discovery_status"] = "processing"
                alert_log.metadata_json["backbone_discovery_ts"] = datetime.now(
                    timezone.utc
                ).isoformat()
                flag_modified(alert_log, "metadata_json")

                await db.commit()
                try:
                    await db.refresh(alert_log)
                except Exception as refresh_err:
                    logger.warning(
                        "Could not refresh alert_log %s after commit: %s",
                        alert_log.id,
                        refresh_err,
                    )

                title = alert_log.target_label
                summary = alert_log.metadata_json.get(
                    "description", f"Automated trigger on {alert_log.topic}"
                )
                enable_ai_discovery = os.getenv("ENABLE_AI_DISCOVERY", "false").lower() == "true"
                if enable_ai_discovery:
                    logger.info(f"[Antigravity] Direct AI Analysis triggered for {alert_log.id}")
                    task = asyncio.create_task(
                        ImpactDiscoveryEngine(None).run_discovery(
                            uuid.uuid4(), title, summary, alert_log.id
                        )
                    )
                    _bg_tasks.add(task)
                    task.add_done_callback(_bg_tasks.discard)

                if not targets:
                    logger.info(f"Alert for {sig.target_label} logged as system-wide.")
                else:
                    for profile, personal_score, is_broadcast in targets:
                        await cls._send_personalized_alert(
                            db, profile, alert_log, sig, personal_score, is_broadcast
                        )
            except Exception as alert_err:
                logger.exception(
                    "Alert pipeline failed for target=%r (rolled back, continuing): %s",
                    sig.target_label,
                    alert_err,
                )
                await db.rollback()
                continue

    @classmethod
    def _determine_severity(cls, intensity: float, spike: float, domains: int) -> Optional[str]:
        """Priority evaluation: Critical -> Elevated -> Watch."""
        # Critical
        if intensity >= SEVERITY_CONFIG["critical"]["min_intensity"] or \
           (spike >= SEVERITY_CONFIG["critical"]["min_spike"] and domains >= SEVERITY_CONFIG["critical"]["min_domains"]):
            return "critical"
        
        # Elevated
        if intensity >= SEVERITY_CONFIG["elevated"]["min_intensity"] or \
           (spike >= SEVERITY_CONFIG["elevated"]["min_spike"] and domains >= SEVERITY_CONFIG["elevated"]["min_domains"]):
            return "elevated"
            
        # Watch
        if intensity >= SEVERITY_CONFIG["watch"]["min_intensity"] or \
           domains >= SEVERITY_CONFIG["watch"]["min_domains"]:
            return "watch"
            
        return None

    @classmethod
    async def _domain_intensity_pct(cls, db, domain: str, raw_current: float, now: datetime) -> Optional[float]:
        """
        Distributed intensity % for an incoming alert, measured against its OWN
        strategic domain's decayed baseline (the same per-domain model Trend Flow
        uses). Returns None on cold-start (no prior same-domain activity) so the
        caller can fall back to the legacy tier.
        """
        window = now - timedelta(hours=48)
        rows = (await db.execute(
            select(AlertLog).where(
                AlertLog.triggered_at >= window,
                AlertLog.suppressed.is_(False),
            )
        )).scalars().all()
        priors = [
            r for r in rows
            if infer_domain_from_topic(r.topic or "", r.target_label or "") == domain
        ]
        baseline = decayed_domain_baseline(priors, now=now)
        # Data-Maturity Guardrail: cold-start (no reliable domain history) stays
        # UNCOMPUTED (None) → the row persists for baseline-building but is held
        # out of the live feed until it has a mathematically valid ratio.
        if baseline <= 0:
            return None
        return percentage_from_ratio(raw_current / baseline)

    @classmethod
    async def _get_spike_delta(cls, db, sig: TrendSignal) -> float:
        """Calculates intensity delta over the last 24h."""
        one_day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        stmt = select(TrendSignal).where(
            TrendSignal.target_label == sig.target_label,
            TrendSignal.created_at >= one_day_ago,
            TrendSignal.id != sig.id
        ).order_by(TrendSignal.intensity_score.asc()).limit(1)
        
        baseline_sig = (await db.execute(stmt)).scalar_one_or_none()
        if not baseline_sig:
            return 0.0
        return sig.intensity_score - baseline_sig.intensity_score

    @classmethod
    async def _get_evidence_metrics(cls, db, sig: TrendSignal) -> Tuple[int, List[Dict[str, str]], List[str]]:
        """Counts unique media domains and returns list of source metadata and item IDs."""
        titles = sig.metrics_json.get("supporting_events", [])
        cluster_id = sig.metrics_json.get("cluster_id")
        
        if not titles and not cluster_id: 
            return 0, [], []
        
        # 1. Cluster-ID Strategy (Most Reliable) - New for Restoration
        items = []
        if cluster_id:
            try:
                from db.models import EventCluster
                # Find items associated with this cluster
                # Assuming Cluster -> Item relationship exists or items have cluster_id
                # (Checking models.py, Item has cluster_id)
                import uuid
                stmt = select(Item).where(Item.cluster_id == uuid.UUID(cluster_id))
                items = (await db.execute(stmt)).scalars().all()
                if items:
                    logger.info(f"Resolved {len(items)} evidence items via cluster_id {cluster_id}")
            except Exception as e:
                logger.error(f"Failed cluster_id evidence lookup: {e}")

        # 2. Exact Match Strategy (Fallback if no cluster_id or no items found)
        if not items:
            stmt = select(Item).where(Item.title.in_(titles))
            items = (await db.execute(stmt)).scalars().all()
        
        # 3. Fallback: Keyword Overlap / Label Containment
        if not items:
            logger.info(f"No exact title matches for {sig.target_label}, attempting fallback...")
            # Try to match items whose titles contain the target_label (useful for entity heat)
            fallback_stmt = select(Item).where(Item.title.ilike(f"%{sig.target_label}%")).limit(5)
            items = (await db.execute(fallback_stmt)).scalars().all()
            
            if not items:
                # Further fallback: check if any supporting titles match partially
                # This handles cases where TrendSignal target_label is fragmented
                for title_fragment in titles[:3]:
                    if len(title_fragment) < 5: continue
                    f_stmt = select(Item).where(Item.title.ilike(f"%{title_fragment}%")).limit(3)
                    f_items = (await db.execute(f_stmt)).scalars().all()
                    if f_items:
                        items.extend(f_items)
                        break

        evidence_list = []
        seen_urls = set()
        related_item_ids = []
        
        for item in items:
            if item.id and str(item.id) not in related_item_ids:
                related_item_ids.append(str(item.id))
                
            if not item.source_url or item.source_url in seen_urls:
                continue
            
            seen_urls.add(item.source_url)
            domain = urlparse(item.source_url).netloc
            evidence_list.append({
                "title": item.title or "Verified Signal Source",
                "domain": domain,
                "url": item.source_url
            })
            
        domain_count = len({e["domain"] for e in evidence_list})
        return domain_count, evidence_list, related_item_ids

    @classmethod
    async def _check_recent_duplicate(
        cls,
        db,
        display_label: str,
        sig_target_label: str | None,
        new_intensity: float,
    ) -> Tuple[bool, float, bool]:
        """
        Returns (suppress, last_matching_intensity, reignited).

        If an alert with the same normalized headline exists within ALERT_DEDUP_WINDOW_HOURS,
        skip unless new_intensity >= REIGNITE_INTENSITY_FACTOR * prior intensity (and prior > 0).
        """
        window_start = datetime.now(timezone.utc) - timedelta(hours=ALERT_DEDUP_WINDOW_HOURS)
        new_keys = _alert_title_keys(display_label, sig_target_label)
        if not new_keys:
            return False, 0.0, False

        stmt = (
            select(AlertLog)
            .where(AlertLog.triggered_at >= window_start)
            .order_by(desc(AlertLog.triggered_at))
            .limit(RECENT_ALERTS_FETCH_LIMIT)
        )
        rows = (await db.execute(stmt)).scalars().all()

        for prev in rows:
            prev_keys = _prior_alert_title_keys(prev)
            if not prev_keys & new_keys:
                continue

            last_intensity = _raw_intensity_for_alert(prev)
            if last_intensity <= 0:
                logger.info(
                    "Alert suppressed: duplicate headline within %sh (prior intensity unset) display=%r",
                    ALERT_DEDUP_WINDOW_HOURS,
                    display_label[:80],
                )
                return True, last_intensity, False

            if new_intensity >= last_intensity * REIGNITE_INTENSITY_FACTOR:
                return False, last_intensity, True

            factor = REIGNITE_INTENSITY_FACTOR
            logger.info(
                "Alert suppressed: duplicate headline within %sh "
                "(intensity %.2f vs prior %.2f; %s)",
                ALERT_DEDUP_WINDOW_HOURS,
                new_intensity,
                last_intensity,
                f"need ≥{factor:.2f}× prior",
            )
            return True, last_intensity, False

        return False, 0.0, False

    @classmethod
    async def _recent_headline_keys(cls, db) -> set[str]:
        """Normalized headline keys of active (unsuppressed) alerts within the
        diversification window — seeds the per-run cross-source uniqueness guard."""
        window_start = datetime.now(timezone.utc) - timedelta(hours=HEADLINE_DIVERSIFY_WINDOW_HOURS)
        stmt = (
            select(AlertLog)
            .where(AlertLog.triggered_at >= window_start, AlertLog.suppressed == False)  # noqa: E712
            .order_by(desc(AlertLog.triggered_at))
            .limit(RECENT_ALERTS_FETCH_LIMIT)
        )
        rows = (await db.execute(stmt)).scalars().all()
        keys: set[str] = set()
        for r in rows:
            keys |= _prior_alert_title_keys(r)
        return keys

    @classmethod
    async def _find_event_cluster(cls, db, sig, display_label, topic, new_intensity):
        """Find an active master alert (same topic, last CLUSTER_WINDOW_HOURS) that
        represents the SAME underlying event as the incoming signal.

        Returns (master_alert | None, is_escalation). `is_escalation` is True when
        the new signal is a >= CLUSTER_ESCALATION_FACTOR (1.5x) intensity surge vs
        the master — in which case the caller emits a fresh escalated alert instead
        of absorbing it.
        """
        # Cluster on the HEADLINE only — descriptions share heavy boilerplate
        # vocabulary (e.g. Middle-East geopolitics) that falsely inflates overlap
        # and chains distinct events together.
        incoming = _event_tokens(f"{display_label} {sig.target_label or ''}")
        if not incoming:
            return None, False

        # No topic silo: the SAME event is often classified into different topics
        # across runs (e.g. an Iran headline → DEFENSE one tick, MARKET the next),
        # which left cross-topic duplicates. Title-only matching makes cross-topic
        # clustering safe — near-identical headlines are the same event regardless
        # of categorization. (`topic` kept in the signature for call-site compat.)
        _ = topic
        window_start = datetime.now(timezone.utc) - timedelta(hours=CLUSTER_WINDOW_HOURS)
        stmt = (
            select(AlertLog)
            .where(
                AlertLog.triggered_at >= window_start,
                AlertLog.suppressed == False,  # noqa: E712
            )
            .order_by(desc(AlertLog.triggered_at))
            .limit(RECENT_ALERTS_FETCH_LIMIT)
        )
        rows = (await db.execute(stmt)).scalars().all()

        best, best_sim = None, 0.0
        for prev in rows:
            meta = prev.metadata_json if isinstance(prev.metadata_json, dict) else {}
            prev_text = f"{prev.target_label or ''} {meta.get('display_title', '')}"
            sim = _event_similarity(incoming, _event_tokens(prev_text))
            if sim > best_sim:
                best, best_sim = prev, sim

        if best is None or best_sim < CLUSTER_SIM_THRESHOLD:
            return None, False

        master_intensity = _raw_intensity_for_alert(best)
        escalated = master_intensity > 0 and new_intensity >= master_intensity * CLUSTER_ESCALATION_FACTOR
        return best, escalated

    @classmethod
    async def _absorb_into_master(cls, db, master, sig, evidence_list, incoming_label):
        """Merge the incoming signal's sources into an existing master alert as
        corroboration — no new row. Dedupes evidence by URL/title and only ever
        RAISES the master's confidence (intensity is never lowered)."""
        from sqlalchemy.orm.attributes import flag_modified

        meta = dict(master.metadata_json) if isinstance(master.metadata_json, dict) else {}
        existing = list(meta.get("evidence_list") or [])
        seen = {
            (e.get("url") or e.get("link") or e.get("title") or "").strip()
            for e in existing if isinstance(e, dict)
        }
        added = 0
        for ev in (evidence_list or []):
            if not isinstance(ev, dict):
                continue
            key = (ev.get("url") or ev.get("link") or ev.get("title") or "").strip()
            if key and key in seen:
                continue
            existing.append(ev)
            if key:
                seen.add(key)
            added += 1

        meta["evidence_list"] = existing[:CLUSTER_MAX_EVIDENCE]
        meta["corroboration_count"] = int(meta.get("corroboration_count", 0) or 0) + 1
        meta["last_corroborated_at"] = datetime.now(timezone.utc).isoformat()
        master.metadata_json = meta
        master.supporting_events_count = len(meta["evidence_list"])
        flag_modified(master, "metadata_json")
        await db.flush()
        logger.info(
            "Event clustered: absorbed %r into master %s (+%d new source(s), %d total)",
            (incoming_label or "")[:60], str(master.id), added, len(meta["evidence_list"]),
        )

    @classmethod
    async def _bump_master(cls, db, master, sig, evidence_list, intensity, intensity_pct, severity, now):
        """Escalation in-place bump: absorb the new sources, then refresh the
        master's intensity / severity / intensity_pct and set triggered_at = now so
        it re-surfaces at the top of the stream — WITHOUT minting a duplicate row."""
        from sqlalchemy.orm.attributes import flag_modified

        await cls._absorb_into_master(db, master, sig, evidence_list, master.target_label)

        meta = dict(master.metadata_json) if isinstance(master.metadata_json, dict) else {}
        meta["raw_intensity"] = round(float(intensity), 3)
        if intensity_pct is not None:
            meta["intensity_pct"] = round(float(intensity_pct), 1)
        master.metadata_json = meta
        master.intensity = intensity
        if severity:
            master.severity = severity
        master.triggered_at = now
        flag_modified(master, "metadata_json")
        await db.flush()
        logger.info(
            "Cluster escalation BUMP (in place): master %s → intensity %.2f pct=%s, re-surfaced @ %s",
            str(master.id), intensity, intensity_pct, now.isoformat(),
        )

    @classmethod
    async def _get_latest_report_link(cls, db, sig: TrendSignal) -> Tuple[Optional[uuid.UUID], Optional[str]]:
        """Finds the most recent report of the SAME TOPIC to create a valid context link."""
        # Mapping frontend topic slugs to DB topic_codes if needed
        # Assuming sig.topic (e.g. 'geopolitical') matches Report.topic_code or sub-slug
        anchor = f"#pattern-{sig.target_label.lower().replace(' ', '-')}"
        
        # Priority 1: Topic-specific match
        stmt = select(Report).where(
            or_(
                Report.topic_code == sig.topic,
                Report.title.ilike(f"%{sig.target_label}%")
            )
        ).order_by(Report.created_at.desc()).limit(1)
        
        report = (await db.execute(stmt)).scalar_one_or_none()
        
        if report:
            logger.info(f"Resolved context mapping: Alert for {sig.target_label} -> Report {report.id} ({report.topic_code})")
            return report.id, anchor
        
        # No matching context found, return null to avoid deceptive linking
        logger.info(f"No specific context report found for {sig.target_label} ({sig.topic}). Disabling deep link.")
        return None, None

    @classmethod
    async def _send_personalized_alert(cls, db, profile: AnalystProfile, alert_log: AlertLog, sig: TrendSignal, personal_score: float, is_broadcast: bool):
        """Formats and sends a personalized alert to a specific analyst (Phase 25)."""
        from db.models import AlertDelivery
        icons = {"critical": "🚨🚨 CRITICAL", "elevated": "🚨 ELEVATED", "watch": "👀 WATCH"}
        severity = alert_log.severity
        header = icons.get(severity, "WATCH")
        
        # Add Broadcast Tag
        broadcast_tag = " (📢 BROADCAST)" if is_broadcast else ""
        
        source_count = sig.metrics_json.get("supporting_cluster_count", "N/A")
        supporting = sig.metrics_json.get("supporting_events", [])
        signals_md = "\n".join([f"• {s}" for s in supporting[:2]])
        
        msg = f"<b>{header}</b>{broadcast_tag} (P-Score: {personal_score:.2f})\n\n"
        msg += f"<b>Pattern</b>: {sig.target_label}\n"
        msg += f"<b>System Intensity</b>: {sig.intensity_score}/10.0\n"
        msg += f"<b>Evidence</b>: {source_count} signals\n\n"
        
        msg += f"<b>Key Signals</b>:\n{signals_md}\n\n"
        msg += f"#OSINT #RiskIntel #{sig.target_label.replace(' ', '')} #{severity}"

        # Track Delivery
        delivery = AlertDelivery(
            alert_log_id=alert_log.id,
            analyst_id=profile.id,
            status="delivered",
            relevance_score=personal_score
        )
        db.add(delivery)

        if not ALERT_ENABLED:
            logger.info(f"Telegram delivery skipped (disabled) for analyst {profile.id}: {sig.target_label}")
            return

        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": profile.telegram_chat_id, "text": msg, "parse_mode": "HTML"}
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=10.0)
                if resp.status_code != 200:
                    logger.error(f"Failed to send alert to {profile.telegram_chat_id}: {resp.text}")
                    delivery.status = "failed"
                    delivery.suppression_reason = resp.text
        except Exception as e:
            logger.error(f"Failed to send alert to {profile.telegram_chat_id}: {e}")
            delivery.status = "failed"
            delivery.suppression_reason = str(e)

async def run_alert_manager(db):
    """Refined entry point for Phase 22."""
    logger.info("Starting alert manager")

    limit = datetime.now(timezone.utc) - timedelta(hours=30)
    stmt = select(TrendSignal).where(TrendSignal.created_at >= limit)
    new_sigs = (await db.execute(stmt)).scalars().all()

    logger.info(f"Found {len(new_sigs)} TrendSignals since {limit.isoformat()}")

    if new_sigs:
        try:
            await AlertManager.evaluate_and_send(db, new_sigs)
        except Exception as e:
            logger.exception("evaluate_and_send failed (pipeline continues): %s", e)
            await db.rollback()
        logger.info("Alert manager finished")
    else:
        logger.info("No TrendSignals found. Nothing to alert.")

if __name__ == "__main__":
    from db.database import AsyncSessionLocal

    async def main():
        async with AsyncSessionLocal() as session:
            await run_alert_manager(session)

    asyncio.run(main())