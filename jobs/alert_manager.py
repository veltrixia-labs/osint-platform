import asyncio
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
from processor.lightweight_topic import STRATEGIC_TOPICS, infer_topic_from_text
from processor.topic_registry import CANONICAL_TOPICS, normalize_canonical_topic

logging.basicConfig(level=logging.INFO)

resolver = LocationResolver()
# [v14.3] Global set to prevent weak-reference garbage collection of background asyncio tasks
_bg_tasks = set()

logger = logging.getLogger(__name__)

# Config from Environment
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ALERT_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# Duplicate suppression: skip same headline within window unless intensity reignites.
ALERT_DEDUP_WINDOW_HOURS = int(os.getenv("ALERT_DEDUP_WINDOW_HOURS", "24"))
REIGNITE_INTENSITY_FACTOR = float(os.getenv("REIGNITE_INTENSITY_FACTOR", "1.1"))
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
    """Prefer news headlines over bare source/entity slugs for Alert Stream titles."""
    label = (sig.target_label or "").strip()
    if label and not _looks_like_source_label(label):
        return label
    for ev in evidence_list:
        title = (ev.get("title") or "").strip()
        if title and not _looks_like_source_label(title):
            return title
    desc = (sig.description or "").strip()
    if desc and len(desc) >= 12:
        return desc[:240]
    return label or "Untitled signal"


def _normalize_alert_title(raw: str | None) -> str:
    """Lowercase collapsed whitespace for dedupe comparisons."""
    if not raw:
        return ""
    return " ".join(raw.strip().lower().split())


def _alert_title_keys(display_label: str, sig_target_label: str | None) -> set[str]:
    keys = {_normalize_alert_title(display_label), _normalize_alert_title(sig_target_label or "")}
    keys.discard("")
    return keys


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

            if internal_topic not in STRATEGIC_TOPICS or topic not in CANONICAL_TOPICS:
                logger.info(
                    "Alert suppressed: topic outside strategic sectors topic=%r target=%r",
                    topic,
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
            
            # 2. Determine Severity (Priority: Critical > Elevated > Watch)
            severity = cls._determine_severity(intensity, spike_delta, domain_count)
            if not severity:
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

            # 3. 24h dedupe by headline (target_label / display_title); allow reignite if intensity ≥ factor × prior.
            suppressed, last_dup_intensity, reignited = await cls._check_recent_duplicate(
                db, display_label, sig.target_label, intensity
            )
            if suppressed:
                continue
            if reignited and last_dup_intensity > 0:
                display_trigger_type = f"{display_trigger_type} (🚨 INTENSITY SPIKE)"
                logger.info(
                    "Duplicate window bypass (reignite): %.2f -> %.2f (prior=%.2f, factor=%.2f)",
                    last_dup_intensity,
                    intensity,
                    last_dup_intensity,
                    REIGNITE_INTENSITY_FACTOR,
                )

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
            
            # Geotagging (Heuristic First) + location entity for Context Briefs enrichment
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
                from jobs.free_alert_feed_generator import persist_free_alert_feed_item

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

                try:
                    await persist_free_alert_feed_item(db, alert_log, commit=False)
                except Exception as brief_err:
                    logger.exception(
                        "Free Alert Feed persist failed for alert %s (alert row will still commit): %s",
                        alert_log.id,
                        brief_err,
                    )
                    await db.rollback()
                    db.add(alert_log)
                    await db.flush()
                    alert_log.metadata_json = dict(meta_base)
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

            last_intensity = float(prev.intensity or 0.0)
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

    try:
        from jobs.free_alert_feed_generator import backfill_missing_free_alerts
        backfill_limit = int(os.getenv("FREE_ALERT_BACKFILL_LIMIT", "30"))
        await backfill_missing_free_alerts(db, limit=backfill_limit)
    except Exception as e:
        logger.exception("free_alert backfill after alert_manager failed: %s", e)
        await db.rollback()

if __name__ == "__main__":
    from db.database import AsyncSessionLocal

    async def main():
        async with AsyncSessionLocal() as session:
            await run_alert_manager(session)

    asyncio.run(main())