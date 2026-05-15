import asyncio
import sys
import os
import logging
from datetime import datetime, timezone, timedelta
from collections import Counter
from typing import List, Dict, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import AlertLog, Report, Item, RawItem, Topic
from jobs.pro_automation_manager import ProAutomationManager
from jobs.pro_brief_trigger_policy import should_generate_pro_brief, get_alert_quality_metrics
from sqlalchemy import select, func, desc, or_, and_

# Configure basic logging to avoid noise
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_detailed_diagnostics():
    async with AsyncSessionLocal() as db:
        print("=" * 100)
        print(f"PRO AUTOMATION DEEP DIAGNOSTICS - {datetime.now(timezone.utc).isoformat()}")
        print("=" * 100)

        # 1. Environment Status
        enabled = os.getenv("ENABLE_PRO_AUTOMATION", "false")
        dry_run = os.getenv("PRO_AUTOMATION_DRY_RUN", "true")
        domains_env = os.getenv("PRO_AUTOMATION_ENABLED_DOMAINS", "")
        enabled_domains = [d.strip() for d in domains_env.split(",") if d.strip()]
        
        print(f"ENV STATUS:")
        print(f"  ENABLE_PRO_AUTOMATION: {enabled}")
        print(f"  PRO_AUTOMATION_DRY_RUN: {dry_run}")
        print(f"  ENABLED_DOMAINS: {enabled_domains}")

        # 2. Pipeline Growth Audit (RSS/Ingest)
        print(f"\n[PIPELINE AUDIT] Data Ingestion Volume:")
        for days in [7, 14, 30]:
            lookback = datetime.now(timezone.utc) - timedelta(days=days)
            raw_count = (await db.execute(select(func.count(RawItem.id)).where(RawItem.created_at >= lookback))).scalar()
            item_count = (await db.execute(select(func.count(Item.id)).where(Item.created_at >= lookback))).scalar()
            alert_count = (await db.execute(select(func.count(AlertLog.id)).where(AlertLog.triggered_at >= lookback))).scalar()
            print(f"  Last {days:2} Days: RawItems={raw_count:5} | Items={item_count:5} | Alerts={alert_count:5}")

        # 3. Alert Statistics by Domain
        print(f"\n[ALERT STATS] By Enabled Domain (Last 30 Days):")
        for d in enabled_domains:
            counts = {}
            for days in [7, 14, 30]:
                lookback = datetime.now(timezone.utc) - timedelta(days=days)
                stmt = select(func.count(AlertLog.id)).where(
                    AlertLog.topic == d,
                    AlertLog.triggered_at >= lookback
                )
                counts[days] = (await db.execute(stmt)).scalar()
            print(f"  {d:35}: 7d={counts[7]:3} | 14d={counts[14]:3} | 30d={counts[30]:3}")

        # 4. Detailed Alert Audit (Enabled Domains Only)
        print(f"\n[ALERT AUDIT] Individual Evaluation (Last 30 Days, Enabled Domains):")
        lookback_30 = datetime.now(timezone.utc) - timedelta(days=30)
        stmt_audit = select(AlertLog).where(
            AlertLog.topic.in_(enabled_domains),
            AlertLog.triggered_at >= lookback_30
        ).order_by(desc(AlertLog.triggered_at))
        
        audit_alerts = (await db.execute(stmt_audit)).scalars().all()
        
        skip_reasons_counter = Counter()
        planned_count = 0
        watch_promoted_count = 0
        
        if not audit_alerts:
            print("  No alerts found in enabled domains for the last 30 days.")
        else:
            header = f"{'ID':<38} | {'Topic':<25} | {'Sev':<8} | {'Fid':<4} | {'Evid':<4} | {'Data':<4} | {'Score':<5} | {'Status'}"
            print(header)
            print("-" * len(header))
            
            for alert in audit_alerts:
                # Manual evaluation using the policy
                should_gen, reasons, diag = await should_generate_pro_brief(db, alert)
                
                metrics = diag.get("metrics", {})
                fid_val = alert.is_high_fidelity or (alert.fidelity_score or 0) >= 0.8
                fid_marker = "Y" if fid_val else "N"
                
                evid_val = metrics.get("evidence_count", 0) >= 3 or metrics.get("related_news_count", 0) >= 3
                evid_marker = "Y" if evid_val else "N"
                
                data_marker = "Y" if diag.get("passed_data_gate") else "N"
                score_marker = f"{alert.intelligence_score or 0:0.2f}"
                
                status_str = "READY" if should_gen else "SKIPPED"
                if should_gen:
                    planned_count += 1
                    if diag.get("passed_global_market_relaxed_gate"):
                        watch_promoted_count += 1
                        status_str = f"READY (GM Relaxed: {diag.get('relaxed_gate_reason', 'N/A')})"
                    elif alert.severity.lower() == "watch":
                        watch_promoted_count += 1
                        status_str = "READY (Watch Promoted)"
                else:
                    reason = reasons[0] if reasons else "Unknown"
                    skip_reasons_counter[reason] += 1
                    status_str = f"SKIP ({reason})"

                print(f"{str(alert.id):<38} | {alert.topic:<25} | {alert.severity:<8} | {fid_marker:<4} | {evid_marker:<4} | {data_marker:<4} | {score_marker:<5} | {status_str}")
                
                if not should_gen:
                    print(f"    -> Reasons: {reasons}")
                    print(f"    -> Gates: Fid={fid_marker}, Evid={evid_marker}, Data={data_marker}, Score={score_marker}")
                    print(f"    -> Duplicates: Structural={diag.get('duplicate_structural_brief', False)}, General={diag.get('duplicate_general_report', False)}")
                print("-" * len(header))

        # 5. Skip Reason Summary
        print(f"\n[SUMMARY] Candidates & Skips:")
        print(f"  - Total Candidates Slated: {planned_count}")
        print(f"  - Watch Alerts Promoted  : {watch_promoted_count}")
        print(f"\n[SUMMARY] Skip Reason Ranking (Last 30 Days):")
        if not skip_reasons_counter:
            print("  No skips recorded in the audit set.")
        for reason, count in skip_reasons_counter.most_common():
            print(f"  - {reason:65}: {count}")

        # 6. Duplicate Report Check Detail
        print(f"\n[DUPLICATE CHECK] Recent Pro Reports in DB (Last 72h):")
        window_72 = datetime.now(timezone.utc) - timedelta(hours=72)
        stmt_rep = select(Report).where(
            Report.plan_required == "pro",
            Report.created_at >= window_72
        ).order_by(desc(Report.created_at))
        reps = (await db.execute(stmt_rep)).scalars().all()
        
        if not reps:
            print("  No recent Pro reports found.")
        else:
            for r in reps:
                is_structural = r.report_type == "pro_structural" or (r.title and r.title.startswith("Structural"))
                type_str = "[STRUCTURAL]" if is_structural else "[GENERAL]"
                print(f"    - {type_str:12} ID: {r.id} | Topic: {r.topic_code:25} | Created: {r.created_at}")

        # 7. Overall Automation Simulation Result
        print(f"\n[SIMULATION] Final Manager Verdict (Limit 5):")
        manager = ProAutomationManager(db)
        results = await manager.run_once(limit=5, dry_run=True)
        print(f"  Candidates Found: {results['candidates_found']}")
        print(f"  Planned to Generate: {results['generated_count']}")
        print(f"  Skipped Count: {results['skipped_count']}")
        
        if results['generated_reports']:
            print("  Slated Candidates:")
            for r in results['generated_reports']:
                print(f"    - {r['title']} (Alert: {r['alert_id']})")

        print("\n" + "=" * 100)
        print("Deep diagnostics complete.")
        print("=" * 100)

if __name__ == "__main__":
    asyncio.run(run_detailed_diagnostics())
