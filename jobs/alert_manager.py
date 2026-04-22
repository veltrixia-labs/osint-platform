import asyncio
import uuid
import logging
import os
import httpx
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.future import select
from sqlalchemy import desc, func, or_
from db.models import TrendSignal, EventCluster, Item, AlertLog, Report, AnalystProfile
from urllib.parse import urlparse
from processor.location_resolver import LocationResolver

resolver = LocationResolver()
# [v14.3] Global set to prevent weak-reference garbage collection of background asyncio tasks
_bg_tasks = set()

logger = logging.getLogger(__name__)

# Config from Environment
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ALERT_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
ALERT_COOLDOWN_HOURS = 12

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

        ALLOWED_TYPES = ["risk_pattern", "risk_acceleration", "entity_heat", "sector_surge", "sustained_event"]
        
        # [v10.37] STRATEGIC THINK-TANK CALIBRATION: Only allow 6 core sectors
        STRATEGIC_TOPICS = [
            "energy_resource_risk",
            "global_market_intelligence",
            "crypto_geopolitics",
            "ai_semiconductor_intelligence",
            "defense_technology",
            "supply_chain_intelligence"
        ]

        for sig in new_signals:
            if sig.trend_type not in ALLOWED_TYPES:
                continue

            # Skip general news or non-strategic topics for Tactical Alerts
            if sig.topic not in STRATEGIC_TOPICS:
                logger.info(f"Signal suppressed: Topic '{sig.topic}' falls outside the 6 Strategic OSINT Sectors.")
                continue

            # Map the signal's trend_type to an appropriate display trigger_type
            trigger_type_map = {
                "risk_pattern": "pattern_risk",
                "risk_acceleration": "acceleration",
                "entity_heat": "entity_surge",
                "sector_surge": "sector_surge",
                "sustained_event": "event_continuation"
            }
            display_trigger_type = trigger_type_map.get(sig.trend_type, "pattern_risk")

            # 1. Gather Metrics for Severity
            domain_count, evidence_list = await cls._get_evidence_metrics(db, sig)
            
            # CRITICAL: Suppress alerts ONLY if zero evidence AND intensity is low
            # (User Requirement: Relaxed filtering for high-signal alerts)
            if domain_count == 0 and sig.intensity_score < 8.0:
                logger.info(f"Alert for {sig.target_label} suppressed: Zero evidence sources and low intensity ({sig.intensity_score}).")
                continue

            spike_delta = await cls._get_spike_delta(db, sig)
            
            # 2. Determine Severity (Priority: Critical > Elevated > Watch)
            severity = cls._determine_severity(sig.intensity_score, spike_delta, domain_count)
            if not severity or severity == "watch":
                logger.debug(f"Signal for {sig.target_label} kept as Report Source (Severity: {severity}).")
                continue

            # 3. Escalation & Intensification-Aware Deduplication
            suppressed, is_spike, last_intensity = await cls._check_suppression(db, sig.target_label, sig.topic, display_trigger_type, severity, sig.intensity_score)
            if suppressed:
                continue

            if is_spike:
                display_trigger_type = f"{display_trigger_type} (🚨 INTENSITY SPIKE)"
                logger.info(f"Intensification detected for {sig.target_label}: {last_intensity} -> {sig.intensity_score}")

            # 4. Intelligence Scoring (Phase 24)
            from jobs.alert_scoring import calculate_alert_score
            intel_score, breakdown = await calculate_alert_score(db, sig.intensity_score, spike_delta, domain_count, display_trigger_type, sig.target_label)
            
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
            # Mark as confirmed if we found evidence domains, otherwise pending
            status = "confirmed" if domain_count > 0 else "pending_evidence"
            
            # Geotagging (Heuristic First)
            coords = resolver.resolve_heuristically(f"{sig.target_label} {sig.description}")
            lat, lng = coords if coords else (None, None)
            

            alert_log = AlertLog(
                target_label=sig.target_label,
                topic=sig.topic,
                trigger_type=display_trigger_type,
                severity=severity,
                intensity=sig.intensity_score,
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
                metadata_json={
                    "spike_delta": round(float(spike_delta), 2),
                    "domain_count": domain_count,
                    "evidence_list": evidence_list, # Requirement #2
                    "scoring_breakdown": breakdown
                }
            )
            db.add(alert_log)
            await db.flush() # Need actual ID for delivery logs

            # --- Phase 4: Cascading Impact Discovery [v13.5 - Autonomous Push] ---
            # Instead of waiting for a scout, we trigger the AI discovery pipeline IMMEDIATELY.
            from sqlalchemy.orm.attributes import flag_modified
            from processor.impact_discovery import ImpactDiscoveryEngine
            
            alert_log.metadata_json["backbone_discovery_status"] = "processing"
            alert_log.metadata_json["backbone_discovery_ts"] = datetime.now(timezone.utc).isoformat()
            flag_modified(alert_log, "metadata_json")
            await db.commit() 
            await db.refresh(alert_log)

            # Fire-and-forget background task
            title = alert_log.target_label
            summary = alert_log.metadata_json.get("description", f"Automated trigger on {alert_log.topic}")
            task = asyncio.create_task(ImpactDiscoveryEngine(None).run_discovery(uuid.uuid4(), title, summary, alert_log.id))
            
            # [v14.3] Add to global set and bind callback to prevent premature garbage collection
            _bg_tasks.add(task)
            task.add_done_callback(_bg_tasks.discard)
            
            logger.info(f"[Antigravity] Direct AI Analysis triggered for {alert_log.id}")

            if not targets:
                logger.info(f"Alert for {sig.target_label} logged as system-wide.")
            else:
                for profile, personal_score, is_broadcast in targets:
                    await cls._send_personalized_alert(db, profile, alert_log, sig, personal_score, is_broadcast)

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
    async def _get_evidence_metrics(cls, db, sig: TrendSignal) -> Tuple[int, List[Dict[str, str]]]:
        """Counts unique media domains and returns list of source metadata with fallback matching."""
        titles = sig.metrics_json.get("supporting_events", [])
        cluster_id = sig.metrics_json.get("cluster_id")
        
        if not titles and not cluster_id: 
            return 0, []
        
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
        
        for item in items:
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
        return domain_count, evidence_list

    @classmethod
    async def _check_suppression(cls, db, target_label: str, topic: str, trigger_type: str, new_severity: str, current_intensity: float) -> Tuple[bool, bool, float]:
        """Escalation and intensification-aware suppression logic."""
        cooldown_threshold = datetime.now(timezone.utc) - timedelta(hours=ALERT_COOLDOWN_HOURS)
        
        # Find the most recent alert matching the composite key in the window
        # We check both the base trigger_type and the spiked version
        stmt = select(AlertLog).where(
            AlertLog.target_label == target_label,
            AlertLog.topic == topic,
            AlertLog.triggered_at >= cooldown_threshold
        ).order_by(AlertLog.triggered_at.desc()).limit(1)
        
        last_alert = (await db.execute(stmt)).scalar_one_or_none()
        if not last_alert:
            return False, False, 0.0 # Not suppressed
            
        # Severity Order Map for comparison
        ORDER = {"watch": 1, "elevated": 2, "critical": 3}
        
        # 1. ESCALATION: Allow only if new severity is STRICTLY HIGHER than last severity
        if ORDER[new_severity] > ORDER.get(last_alert.severity, 0):
            logger.info(f"Escalating alert for {target_label} ({topic}): {last_alert.severity} -> {new_severity}")
            return False, False, last_alert.intensity

        # 2. INTENSIFICATION: Allow if intensity increased by 1.5x
        last_intensity = last_alert.intensity or 0.0
        if current_intensity > (last_intensity * 1.5) and current_intensity > 2.0:
            logger.info(f"Intensifying alert for {target_label}: {last_intensity} -> {current_intensity}")
            return False, True, last_intensity
            
        logger.info(f"Alert suppressed for {target_label} ({topic}): Already issued {last_alert.severity} within cooldown.")
        return True, False, last_intensity

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
    limit = datetime.now(timezone.utc) - timedelta(minutes=15)
    stmt = select(TrendSignal).where(TrendSignal.created_at >= limit)
    new_sigs = (await db.execute(stmt)).scalars().all()
    
    if new_sigs:
        await AlertManager.evaluate_and_send(db, new_sigs)
        await db.commit()
