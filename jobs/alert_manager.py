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

logger = logging.getLogger(__name__)

# Config from Environment
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ALERT_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
ALERT_COOLDOWN_HOURS = 12

# Severity Thresholds (Phase 22)
# Evaluation Priority: Critical > Elevated > Watch
SEVERITY_CONFIG = {
    "critical": {"min_intensity": 8.5, "min_spike": 4.0, "min_domains": 8},
    "elevated": {"min_intensity": 7.0, "min_spike": 3.0, "min_domains": 5},
    "watch":    {"min_intensity": 5.5, "min_spike": 0.0, "min_domains": 3}
}

class AlertManager:
    @classmethod
    async def evaluate_and_send(cls, db, new_signals: List[TrendSignal]):
        """Evaluates new signals for alerts with tiered severity and escalation logic."""
        # Phase 24: We now proceed with scoring and logging even if Telegram is disabled
        # Original: if not ALERT_ENABLED: return

        for sig in new_signals:
            if sig.trend_type != "risk_pattern":
                continue

            # 1. Gather Metrics for Severity
            spike_delta = await cls._get_spike_delta(db, sig)
            domain_count = await cls._get_domain_count(db, sig)
            
            # 2. Determine Severity (Priority: Critical > Elevated > Watch)
            severity = cls._determine_severity(sig.intensity_score, spike_delta, domain_count)
            if not severity:
                continue

            # 3. Escalation-Aware Deduplication
            # Allows if (no previous alert in 12h) OR (previous alert had lower severity)
            # 4. Intelligence Scoring (Phase 24)
            from jobs.alert_scoring import calculate_alert_score
            intel_score, breakdown = await calculate_alert_score(db, sig.intensity_score, spike_delta, domain_count, "pattern_risk", sig.target_label)
            
            # 5. Personalization & Multi-Analyst Routing (Phase 25)
            from jobs.personalization_service import get_target_analysts
            targets = await get_target_analysts(db, sig.target_label, intel_score, severity, breakdown)
            
            if not targets:
                logger.info(f"Alert for {sig.target_label} suppressed: No analysts matched criteria (Score: {intel_score:.2f})")
                continue

            # 6. Fetch additional context for linking
            report_id, anchor = await cls._get_latest_report_link(db, sig)
            
            # 7. Create Master Alert Log Entry
            # (We still log the master entry for search/reference)
            alert_log = AlertLog(
                target_label=sig.target_label,
                topic=sig.topic,
                trigger_type="pattern_risk",
                severity=severity,
                intensity=sig.intensity_score,
                intelligence_score=intel_score,
                section_anchor=anchor,
                related_report_id=report_id,
                metadata_json={
                    "spike_delta": round(float(spike_delta), 2),
                    "domain_count": domain_count,
                    "scoring_breakdown": breakdown
                }
            )
            db.add(alert_log)
            await db.flush() # Need actual ID for delivery logs

            # 8. Route to Targeted Analysts
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
    async def _get_domain_count(cls, db, sig: TrendSignal) -> int:
        """Counts unique media domains in supporting clusters."""
        titles = sig.metrics_json.get("supporting_events", [])
        if not titles: return 0
        stmt = select(Item.source_url).where(Item.title.in_(titles))
        urls = (await db.execute(stmt)).scalars().all()
        return len({urlparse(u).netloc for u in urls if u})

    @classmethod
    async def _is_suppressed(cls, db, target_label: str, new_severity: str) -> bool:
        """Escalation-aware suppression logic."""
        cooldown_threshold = datetime.now(timezone.utc) - timedelta(hours=ALERT_COOLDOWN_HOURS)
        
        # Find the most recent alert for this pattern in the window
        stmt = select(AlertLog).where(
            AlertLog.target_label == target_label,
            AlertLog.triggered_at >= cooldown_threshold
        ).order_by(AlertLog.triggered_at.desc()).limit(1)
        
        last_alert = (await db.execute(stmt)).scalar_one_or_none()
        if not last_alert:
            return False # No previous alert, not suppressed
            
        # Severity Order Map for comparison
        ORDER = {"watch": 1, "elevated": 2, "critical": 3}
        
        if ORDER[new_severity] > ORDER.get(last_alert.severity, 0):
            logger.info(f"Escalating alert for {target_label}: {last_alert.severity} -> {new_severity}")
            return False # New severity is higher, allow escalation alert
            
        return True # Same or lower severity, suppress

    @classmethod
    async def _get_latest_report_link(cls, db, sig: TrendSignal) -> Tuple[Optional[uuid.UUID], Optional[str]]:
        """Finds the most recent report containing this pattern to create a deep link."""
        # Stable Anchor aligned with skeleton_builder.py's format: "### Pattern: {p['label']}"
        # Markdown anchors for headers are usually slugified. We'll provide the raw pattern for linking.
        anchor = f"#pattern-{sig.target_label.lower().replace(' ', '-')}"
        
        stmt = select(Report).order_by(Report.created_at.desc()).limit(1)
        report = (await db.execute(stmt)).scalar_one_or_none()
        
        if report:
            return report.id, anchor
        return None, None

    @classmethod
    async def _send_personalized_alert(cls, db, profile: AnalystProfile, alert_log: AlertLog, sig: TrendSignal, personal_score: float, is_broadcast: bool):
        """Formats and sends a personalized alert to a specific analyst (Phase 25)."""
        from db.models import AnalystProfile, AlertDelivery
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
        
        # Substack Deep Link (Disabled - Phase 14 Decoupling)
        # if alert_log.related_report_id:
        #     try:
        #         from integrations.substack_client import get_substack_url
        #         stmt = select(Report).where(Report.id == alert_log.related_report_id)
        #         report = (await db.execute(stmt)).scalar_one_or_none()
        #         
        #         if report and report.substack_slug:
        #             direct_url = get_substack_url(report.substack_slug, utm_source="telegram_alert", utm_medium="alert")
        #             msg += f"<b>Deep Link</b>: <a href='{direct_url}{alert_log.section_anchor}'>View in Report</a>\n\n"
        #     except (ImportError, AttributeError):
        #         logger.warning("Substack client or get_substack_url not available for deep linking.")
        #     except Exception as e:
        #         logger.error(f"Error generating deep link: {e}")
            
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
