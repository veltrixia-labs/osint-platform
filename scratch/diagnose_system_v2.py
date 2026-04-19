import asyncio
import uuid
import sys
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy import desc
from db.database import AsyncSessionLocal
from db.models import JobRun, AlertLog, RawItem, Item

async def run_diagnostics():
    async with AsyncSessionLocal() as session:
        print("=== OSINT PLATFORM DIAGNOSTICS ===")
        
        # Helper to handle potential naive/aware comparison
        def get_delta_minutes(dt):
            if not dt: return 0
            now = datetime.now(timezone.utc)
            if dt.tzinfo is None:
                # SQLite fallback
                return int((datetime.now() - dt).total_seconds() / 60)
            return int((now - dt).total_seconds() / 60)

        # 1. Job Status
        jr_stmt = select(JobRun).order_by(desc(JobRun.started_at)).limit(10)
        jobs = (await session.execute(jr_stmt)).scalars().all()
        print("\n--- Recent Job Runs ---")
        if not jobs:
            print("No jobs found in job_runs table.")
        for j in jobs:
            status_indicator = "✅" if j.status == 'success' else "❌"
            print(f"{status_indicator} [{j.started_at}] {j.job_name}: {j.status} (ErrMsg: {j.error_message})")

        # 2. Raw Data Ingestion
        raw_stmt = select(RawItem).order_by(desc(RawItem.fetched_at)).limit(1)
        latest_raw = (await session.execute(raw_stmt)).scalar_one_or_none()
        print("\n--- Data Ingestion ---")
        if latest_raw:
            delta = get_delta_minutes(latest_raw.fetched_at)
            print(f"Latest Raw Item Fetched: {latest_raw.fetched_at} ({delta} min ago)")
            print(f"Source: {latest_raw.source_system}")
        else:
            print("No raw items found.")

        # 3. Alert Generation
        alert_stmt = select(AlertLog).order_by(desc(AlertLog.triggered_at)).limit(1)
        latest_alert = (await session.execute(alert_stmt)).scalar_one_or_none()
        print("\n--- Alert Generation ---")
        if latest_alert:
            delta = get_delta_minutes(latest_alert.triggered_at)
            print(f"Latest Alert: {latest_alert.target_label} at {latest_alert.triggered_at} ({delta} min ago)")
        else:
            print("No alerts found.")

        # 4. In-Process Items
        item_stmt = select(Item).order_by(desc(Item.created_at)).limit(1)
        latest_item = (await session.execute(item_stmt)).scalar_one_or_none()
        print("\n--- Processed Items ---")
        if latest_item:
            print(f"Latest Item: {latest_item.title[:50]}... at {latest_item.created_at}")

        print("\n=== END DIAGNOSTICS ===")

if __name__ == "__main__":
    asyncio.run(run_diagnostics())
