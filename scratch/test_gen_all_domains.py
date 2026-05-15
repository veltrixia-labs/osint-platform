import asyncio
from sqlalchemy import select
from db.database import AsyncSessionLocal
from db.models import AlertLog
from jobs.pro_report_generator import run_pro_structural_report_generation
import json

DOMAINS = [
    "global_market_intelligence",
    "ai_semiconductor_intelligence",
    "supply_chain_intelligence",
    "crypto_geopolitics",
    "defense_technology"
]

async def gen():
    async with AsyncSessionLocal() as session:
        for domain in DOMAINS:
            stmt = select(AlertLog).where(
                AlertLog.topic == domain
            ).order_by(AlertLog.triggered_at.desc()).limit(1)
            res = await session.execute(stmt)
            alert = res.scalar_one_or_none()
            
            if alert:
                print(f"Generating for {domain} (Alert: {alert.id})")
                report = await run_pro_structural_report_generation(alert_id=str(alert.id))
                if report and report.structured_payload:
                    sp = report.structured_payload
                    out_path = f"scratch/pro_structured_{domain}_test.md"
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(f"# Report ID: {report.id}\n")
                        f.write(f"Domain: {domain}\n\n")
                        f.write(f"## Exec Summary\n{sp.get('executive_summary', '')}\n\n")
                        f.write(f"## Key Findings\n{sp.get('key_findings', [])}\n\n")
                        f.write(f"## Signal Classification\n{sp.get('signal_classification', {})}\n\n")
                        f.write(f"## Geo Context\n{sp.get('geo_context', {})}\n\n")
                        f.write(f"## Market Breakdown\n")
                        for g in sp.get("market_confirmation", {}).get("breakdown", []):
                            f.write(f"- {g.get('group')}: {g.get('status')} ({g.get('description', '')})\n")
                        
                        f.write(f"\n## Divergence Check\n{sp.get('divergence_check', {})}\n\n")
                        
                        f.write("## Macro Observations\n")
                        for m in sp.get("structural_context", {}).get("macro_observations", []):
                            f.write(f"- {m.get('series_id')} -> {m.get('display_name')}\n")
                            
                    print(f"  -> Saved to {out_path}")
            else:
                print(f"No alert found for {domain}. Available topics:")
                res = await session.execute(select(AlertLog.topic).distinct())
                print([r[0] for r in res.fetchall()])

asyncio.run(gen())
