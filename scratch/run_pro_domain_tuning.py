import asyncio
import sys
import os
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, desc, func
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import AlertLog, Report
from analysis.pro_structural_context import build_pro_structural_context
from reports.pro_structural_report_builder import build_pro_structural_report
from analysis.pro_domain_config import PRO_DOMAIN_CONFIG

async def get_best_alert_for_domain(db, domain_id: str) -> Optional[AlertLog]:
    """Find the best candidate alert for a domain in the last 30 days."""
    stmt = select(AlertLog).where(
        AlertLog.topic == domain_id,
        AlertLog.triggered_at >= datetime.now(timezone.utc) - timedelta(days=30),
        AlertLog.suppressed == False
    ).order_by(desc(AlertLog.intelligence_score), desc(AlertLog.triggered_at)).limit(1)
    
    result = await db.execute(stmt)
    return result.scalar_one_or_none()

async def generate_manual_reports():
    domains = [
        "global_market_intelligence",
        "ai_semiconductor_intelligence",
        "supply_chain_intelligence",
        "crypto_geopolitics",
        "defense_technology"
    ]
    
    filenames = {
        "global_market_intelligence": "scratch/pro_manual_global_market_report.md",
        "ai_semiconductor_intelligence": "scratch/pro_manual_ai_semiconductor_report.md",
        "supply_chain_intelligence": "scratch/pro_manual_supply_chain_report.md",
        "crypto_geopolitics": "scratch/pro_manual_crypto_report.md",
        "defense_technology": "scratch/pro_manual_defense_report.md"
    }
    
    summary_data = []

    async with AsyncSessionLocal() as db:
        for domain_id in domains:
            print(f"\nProcessing domain: {domain_id}")
            
            # 1. Find best alert
            alert = await get_best_alert_for_domain(db, domain_id)
            alert_info = "None (Domain-only mode)"
            if alert:
                alert_info = f"ID: {alert.id} | Sev: {alert.severity} | Score: {alert.intelligence_score} | Title: {alert.target_label}"
            
            print(f"  Alert: {alert_info}")
            
            # 2. Build Context
            print(f"  Building context for {domain_id}...")
            context = await build_pro_structural_context(db, alert_log=alert, domain_id=domain_id)
            
            # 3. Build Report
            print(f"  Building report for {domain_id}...")
            report_md = build_pro_structural_report(context)
            
            # 4. Save Markdown
            file_path = filenames.get(domain_id)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(report_md)
            print(f"  Saved to {file_path}")
            
            # 5. Extract summary stats
            sc = context.get("structural_context", {})
            mc = context.get("market_confirmation", {})
            watch = context.get("watch_indicators", [])
            
            macro_count = len(sc.get("macro_observations", []))
            trade_count = len(sc.get("trade_flows", []))
            industry_count = len(sc.get("industry_stats", []))
            market_count = len(mc.get("latest_prices", []))
            
            missing_series = context.get("diagnostics", {}).get("missing_series", [])
            
            summary_data.append({
                "domain_id": domain_id,
                "alert": alert_info,
                "file": file_path,
                "macro_count": macro_count,
                "trade_count": trade_count,
                "industry_count": industry_count,
                "market_count": market_count,
                "watch_count": len(watch),
                "missing": missing_series
            })

    # Generate Summary MD
    summary_md = "# Pro Manual Domain Tuning Summary\n\n"
    summary_md += f"Generated At: {datetime.now(timezone.utc).isoformat()}\n\n"
    
    for item in summary_data:
        summary_md += f"## Domain: {item['domain_id']}\n"
        summary_md += f"- **Target Alert**: {item['alert']}\n"
        summary_md += f"- **Report File**: [{os.path.basename(item['file'])}]({item['file']})\n"
        summary_md += "- **Data Coverage**:\n"
        summary_md += f"  - Macro Observations: {item['macro_count']}\n"
        summary_md += f"  - Trade Flows: {item['trade_count']}\n"
        summary_md += f"  - Industry Stats: {item['industry_count']}\n"
        summary_md += f"  - Market Confirmation: {item['market_count']}\n"
        summary_md += f"  - Watch Indicators: {item['watch_count']}\n"
        summary_md += "- **Missing Data**:\n"
        if item['missing']:
            for m in item['missing']:
                summary_md += f"  - {m}\n"
        else:
            summary_md += "  - None\n"
        summary_md += "\n"
        summary_md += "### Preliminary Evaluation\n"
        summary_md += "- **Status**: [PENDING EVALUATION]\n"
        summary_md += "- **Improvement Needed**: \n"
        summary_md += "\n---\n\n"
    
    with open("scratch/pro_manual_domain_tuning_summary.md", "w", encoding="utf-8") as f:
        f.write(summary_md)
    print("\nSummary saved to scratch/pro_manual_domain_tuning_summary.md")

if __name__ == "__main__":
    asyncio.run(generate_manual_reports())
