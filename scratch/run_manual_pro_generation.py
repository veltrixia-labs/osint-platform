import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath("."))
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import desc, func, select
from db.database import AsyncSessionLocal
from db.models import AlertLog, Report
from jobs.pro_report_generator import run_pro_structural_report_generation
DOMAINS = ["energy_resource_risk","global_market_intelligence","ai_semiconductor_intelligence","supply_chain_intelligence","crypto_geopolitics","defense_technology"]
async def best_alert(db, domain_id):
    stmt = select(AlertLog).where(AlertLog.topic == domain_id, AlertLog.suppressed == False).order_by(desc(AlertLog.triggered_at)).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()
async def main():
    async with AsyncSessionLocal() as db:
        before = (await db.execute(select(func.count(Report.id)).where(Report.report_type == "pro_structural"))).scalar() or 0
    print("before", before)
    for domain_id in DOMAINS:
        async with AsyncSessionLocal() as db:
            alert = await best_alert(db, domain_id)
        alert_id = str(alert.id) if alert else None
        print("gen", domain_id, alert_id)
        report = await run_pro_structural_report_generation(alert_id=alert_id, domain_id=domain_id)
        print("ok", report.id, report.title)
    async with AsyncSessionLocal() as db:
        after = (await db.execute(select(func.count(Report.id)).where(Report.report_type == "pro_structural"))).scalar() or 0
    print("after", after, "delta", after-before)
asyncio.run(main())
