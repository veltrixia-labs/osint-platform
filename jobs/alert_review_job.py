import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from sqlalchemy.future import select
from sqlalchemy import func
from db.database import AsyncSessionLocal
from db.models import AlertLog

logger = logging.getLogger(__name__)

OUTPUT_PATH = "outputs/alerts_review_summary.md"

async def generate_review_report():
    """Aggregates alert feedback metrics and generates a review summary."""
    async with AsyncSessionLocal() as db:
        logger.info("Generating Refined Alert Effectiveness Review...")
        
        FEEDBACK_LAG_HOURS = 24
        MIN_SAMPLE_SIZE = 5
        now = datetime.now(timezone.utc)
        lag_threshold = now - timedelta(hours=FEEDBACK_LAG_HOURS)
        
        windows = {
            "Last 7 Days": now - timedelta(days=7),
            "Last 30 Days": now - timedelta(days=30)
        }
        
        report_md = "# Alert Effectiveness Review Summary (Refined)\n\n"
        report_md += f"**Report Generated**: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        report_md += f"**Feedback Lag Window**: {FEEDBACK_LAG_HOURS}h (unrated alerts < 24h old are excluded from missing-feedback metrics)\n\n"
        
        for name, threshold in windows.items():
            report_md += f"## {name}\n"
            
            # Fetch all logs for transition checking
            stmt = select(AlertLog).where(AlertLog.triggered_at >= threshold).order_by(AlertLog.triggered_at.desc())
            logs = (await db.execute(stmt)).scalars().all()
            
            if not logs:
                report_md += "No alerts tracked in this period.\n\n"
                continue
            
            # Ensure all logs have tzinfo for comparison (SQLite usually returns naive)
            for l in logs:
                if l.triggered_at and l.triggered_at.tzinfo is None:
                    l.triggered_at = l.triggered_at.replace(tzinfo=timezone.utc)
            
            # Metric Calculation
            total_count = len(logs)
            rated_logs = [l for l in logs if l.feedback_score is not None]
            rated_count = len(rated_logs)
            
            # Missing Feedback (Mature samples only)
            mature_unrated = [l for l in logs if l.feedback_score is None and l.triggered_at <= lag_threshold]
            missing_ratio = (len(mature_unrated) / total_count) * 100 if total_count > 0 else 0
            
            report_md += f"### Overall Metrics\n"
            report_md += f"- **Total Alerts Sent**: {total_count}\n"
            report_md += f"- **Missing Feedback Ratio (Mature)**: {missing_ratio:.1f}% ({len(mature_unrated)} unrated samples > 24h old)\n"
            report_md += f"- **Rated Sample Count (n)**: {rated_count}\n"
            
            if rated_count > 0:
                mean_fb = sum(l.feedback_score for l in rated_logs) / rated_count
                low_score = len([l for l in rated_logs if l.feedback_score <= 2])
                high_score = len([l for l in rated_logs if l.feedback_score >= 4])
                
                report_md += f"- **Mean Feedback Score**: {mean_fb:.2f}/5.0\n"
                report_md += f"- **Low-Score Ratio (Noise)**: {(low_score/rated_count)*100:.1f}%\n"
                report_md += f"- **High-Score Ratio (Value)**: {(high_score/rated_count)*100:.1f}%\n"
                
                # Escalation Success (Refined: W->E, W->C, E->C)
                transitions = []
                for log in logs:
                    prior_stmt = select(AlertLog).where(
                        AlertLog.target_label == log.target_label,
                        AlertLog.triggered_at < log.triggered_at,
                        AlertLog.triggered_at >= log.triggered_at - timedelta(hours=12)
                    ).order_by(AlertLog.triggered_at.desc()).limit(1)
                    prior = (await db.execute(prior_stmt)).scalar_one_or_none()
                    
                    if prior:
                        ORDER = {"watch": 1, "elevated": 2, "critical": 3}
                        curr_v = ORDER.get(log.severity, 0)
                        prior_v = ORDER.get(prior.severity, 0)
                        if curr_v > prior_v:
                            transitions.append(log)
                
                rated_transitions = [t for t in transitions if t.feedback_score is not None]
                if rated_transitions:
                    success = len([t for t in rated_transitions if t.feedback_score >= 4])
                    report_md += f"- **Refined Escalation Success Rate**: {(success/len(rated_transitions))*100:.1f}% ({len(rated_transitions)} rated transitions)\n"
                else:
                    report_md += "- **Refined Escalation Success Rate**: N/A (Insufficient rated transitions)\n"

            # Top Performing Section
            report_md += "\n### Top-Performing Alerts (n >= 5)\n"
            perf_stats = {} # (trigger, severity) -> scores
            for l in rated_logs:
                key = (l.trigger_type, l.severity)
                if key not in perf_stats: perf_stats[key] = []
                perf_stats[key].append(l.feedback_score)
                
            top_found = False
            for (t_type, sev), scores in perf_stats.items():
                if len(scores) >= MIN_SAMPLE_SIZE:
                    mean = sum(scores) / len(scores)
                    noise = len([s for s in scores if s <= 2]) / len(scores)
                    if mean >= 4.0 and noise <= 0.1:
                        report_md += f"- **{t_type.upper()} @ {sev.upper()}**: Mean {mean:.2f}, Noise {noise*100:.1f}% (n={len(scores)})\n"
                        top_found = True
            
            if not top_found:
                report_md += "No high-performing combinations found or insufficient data.\n"

            # Calibration Suggestions
            report_md += "\n### Threshold Calibration Suggestions (n >= 5)\n"
            suggestions_found = False
            for (t_type, sev), scores in perf_stats.items():
                if len(scores) >= MIN_SAMPLE_SIZE:
                    low_ratio = len([s for s in scores if s <= 2]) / len(scores)
                    high_ratio = len([s for s in scores if s >= 4]) / len(scores)
                    
                    if low_ratio > 0.3:
                        # Suggest increase for noise
                        target = "intensity" if "pattern" in t_type else ("spike_delta" if "spike" in t_type else "domain_count")
                        report_md += f"- **Increase**: `{t_type}` @ `{sev}` -> High noise ({(low_ratio*100):.1f}%). Suggest `{target}` threshold +1.\n"
                        suggestions_found = True
                    elif high_ratio >= 0.6:
                        report_md += f"- **Keep**: `{t_type}` @ `{sev}` -> High value ({(high_ratio*100):.1f}%). Thresholds optimal.\n"
                        suggestions_found = True
                else:
                    report_md += f"- `{t_type}` @ `{sev}`: Insufficient data (n={len(scores)}/{MIN_SAMPLE_SIZE})\n"
                    suggestions_found = True # We count "insufficient" as found for visibility
            
            if not suggestions_found:
                report_md += "No calibration data available for this window.\n"
            
            report_md += "\n---\n"

        # 2. Write to file
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write(report_md)
        
        logger.info(f"Review summary generated at: {OUTPUT_PATH}")

if __name__ == "__main__":
    asyncio.run(generate_review_report())
