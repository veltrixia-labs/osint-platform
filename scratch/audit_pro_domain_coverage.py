import asyncio
import sys
import os
import json
from datetime import datetime
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from analysis.pro_structural_context import build_pro_structural_context
from reports.pro_structural_report_builder import build_pro_structural_report

DOMAINS = [
    "global_market_intelligence",
    "ai_semiconductor_intelligence",
    "defense_technology",
    "supply_chain_intelligence",
    "crypto_geopolitics"
]

async def audit_domain_coverage():
    async with AsyncSessionLocal() as db:
        summary = {}
        
        for domain_id in DOMAINS:
            print(f"Auditing domain: {domain_id}...")
            
            # Use a dummy alert/topic for context generation
            context = await build_pro_structural_context(
                db, 
                domain_id=domain_id,
                lookback_days=30
            )
            
            # Generate Report
            report_md = build_pro_structural_report(context)
            
            # Save Report
            filename = f"pro_domain_{domain_id.replace('_intelligence', '')}.md"
            if "crypto" in domain_id: filename = "pro_domain_crypto_report.md"
            elif "defense" in domain_id: filename = "pro_domain_defense_report.md"
            elif "supply" in domain_id: filename = "pro_domain_supply_chain_report.md"
            elif "global" in domain_id: filename = "pro_domain_global_market_report.md"
            elif "ai" in domain_id: filename = "pro_domain_ai_semiconductor_report.md"
            
            output_path = os.path.join("scratch", filename)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report_md)
            
            # Collect Stats
            s_ctx = context.get("structural_context", {})
            m_ctx = context.get("market_confirmation", {})
            
            prices = m_ctx.get("latest_prices", [])
            stats = {
                "macro_observations": len(s_ctx.get("macro_observations", [])),
                "trade_flows": len(s_ctx.get("trade_flows", [])),
                "industry_stats": len(s_ctx.get("industry_stats", [])),
                "market_instruments": len(prices),
                "unknown_asset_class": len([p for p in prices if p.get("asset_class") == "unknown"]),
                "price_changes": len([p for p in prices if p.get("percent_change") is not None]),
                "data_notes": len(context.get("data_notes", [])),
                "watch_indicators_val": len([i for i in context.get("watch_indicators", []) if i.get("latest_value") is not None])
            }
            summary[domain_id] = stats
            
        # Save Summary Stats
        summary_path = os.path.join("scratch", "pro_domain_audit_stats.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=4)
            
        print("\n" + "=" * 50)
        print("AUDIT COMPLETED")
        print("=" * 50)
        for d, s in summary.items():
            print(f"{d}: Macro={s['macro_observations']}, Trade={s['trade_flows']}, Market={s['market_instruments']} (Changes={s['price_changes']}), UnknownClass={s['unknown_asset_class']}")

if __name__ == "__main__":
    asyncio.run(audit_domain_coverage())
