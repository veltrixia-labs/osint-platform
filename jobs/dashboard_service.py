import logging
import os
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from sqlalchemy import func, desc
from db.models import AlertLog, Report, TrendSignal

logger = logging.getLogger(__name__)

async def generate_dashboard_report(db) -> str:
    """
    Generates a comprehensive analyst dashboard report in Markdown.
    """
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)
    
    # 1. Recent Alerts (Top by Score)
    stmt_recent = select(AlertLog).where(
        AlertLog.triggered_at >= seven_days_ago
    ).order_by(desc(AlertLog.intelligence_score)).limit(10)
    recent_alerts = (await db.execute(stmt_recent)).scalars().all()
    
    # 2. Feedback Distribution
    stmt_feedback = select(
        AlertLog.feedback_score,
        func.count(AlertLog.id)
    ).where(
        AlertLog.feedback_score.isnot(None),
        AlertLog.triggered_at >= seven_days_ago
    ).group_by(AlertLog.feedback_score)
    feedback_stats = (await db.execute(stmt_feedback)).all()
    feedback_map = {score: count for score, count in feedback_stats}
    
    # 3. Trigger Performance Summary
    stmt_trigger = select(
        AlertLog.trigger_type,
        func.avg(AlertLog.feedback_score),
        func.avg(AlertLog.intelligence_score),
        func.count(AlertLog.id)
    ).where(
        AlertLog.triggered_at >= seven_days_ago
    ).group_by(AlertLog.trigger_type)
    trigger_performance = (await db.execute(stmt_trigger)).all()

    # 4. Personalized Analyst Highlights (Phase 25)
    from db.models import AnalystProfile, AlertDelivery
    stmt_analysts = select(AnalystProfile).where(AnalystProfile.is_active == True)
    analysts = (await db.execute(stmt_analysts)).scalars().all()
    
    # 5. Construct Markdown
    md = "# Analyst Intelligence Dashboard\n\n"
    md += f"**Report Generated**: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
    md += f"**Window**: Last 7 Days\n\n"
    
    md += "## 📈 System Health\n"
    total_alerts = sum(f[3] for f in trigger_performance) if trigger_performance else 0
    rated_alerts = sum(feedback_map.values())
    md += f"- **Total Alerts Triggered**: {total_alerts}\n"
    md += f"- **Analysts Feedback Rate**: {(rated_alerts/total_alerts*100):.1f}%" if total_alerts > 0 else "N/A"
    md += "\n\n"

    md += "## 👤 Personalized Watchlist Monitoring\n"
    if not analysts:
        md += "_No active analyst profiles found._\n"
    else:
        for p in analysts:
            md += f"### Analyst Profile: {p.telegram_chat_id[:10]}...\n"
            watchlist_str = ", ".join((p.watch_sectors or []) + (p.watch_keywords or []) + (p.watch_entities or []))
            md += f"**Watchlists**: {watchlist_str if watchlist_str else 'Global'}\n\n"
            
            # Fetch recent deliveries for this analyst
            stmt_delivery = select(AlertLog, AlertDelivery).join(AlertDelivery).where(
                AlertDelivery.analyst_id == p.id,
                AlertDelivery.delivered_at >= seven_days_ago
            ).order_by(desc(AlertDelivery.delivered_at)).limit(3)
            deliveries = (await db.execute(stmt_delivery)).all()
            
            if not deliveries:
                md += "_No personalized matches in the last 7 days._\n\n"
            else:
                md += "| Pattern | P-Score | Status |\n"
                md += "| :--- | :--- | :--- |\n"
                for al, ad in deliveries:
                    md += f"| {al.target_label} | {ad.relevance_score:.2f} | {ad.status.upper()} |\n"
                md += "\n"

    md += "## 🚨 Top Intelligence Alerts (Recent Master Log)\n"
    if not recent_alerts:
        md += "_No alerts triggered in the last 7 days._\n"
    else:
        md += "| Pattern | Severity | Score | Feedback |\n"
        md += "| :--- | :--- | :--- | :--- |\n"
        for a in recent_alerts:
            fb = a.feedback_score if a.feedback_score else "-"
            md += f"| {a.target_label} | {a.severity.upper()} | {a.intelligence_score:.2f} | {fb} |\n"
    md += "\n"

    md += "## 📊 Feedback Distribution (1-5 Scale)\n"
    for i in range(1, 6):
        count = feedback_map.get(i, 0)
        bar = "█" * (count if count < 20 else 20) + (">" if count >= 20 else "")
        md += f"- **[{i}]**: {bar} ({count})\n"
    md += "\n"

    md += "## 🧪 Trigger Reliability\n"
    md += "| Trigger Type | Avg Score | Avg Feedback | Volume |\n"
    md += "| :--- | :--- | :--- | :--- |\n"
    for tp in trigger_performance:
        avg_fb = f"{tp[1]:.2f}" if tp[1] is not None else "N/A"
        avg_score = f"{tp[2]:.2f}" if tp[2] is not None else "N/A"
        md += f"| {tp[0]} | {avg_score} | {avg_fb} | {tp[3]} |\n"
    md += "\n"

    # Save to outputs
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path = os.path.join(base_dir, "outputs", "analyst_dashboard.md")
    os.makedirs(os.path.join(base_dir, "outputs"), exist_ok=True)
    with open(out_path, "w", encoding='utf-8') as f:
        f.write(md)
    
    logger.info(f"Analyst dashboard generated at: {out_path}")
    return md
