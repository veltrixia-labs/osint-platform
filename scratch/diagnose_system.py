import asyncio
import uuid
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy import desc
from db.database import AsyncSessionLocal
from db.models import JobRun, AlertLog, RawItem, Item

async def run_diagnostics():
    async with AsyncSessionLocal() as session:
        print("=== OSINT PLATFORM DIAGNOSTICS ===")
        
        # 1. Job Status
        jr_stmt = select(JobRun).order_by(desc(JobRun.started_at)).limit(5)
        jobs = (await session.execute(jr_stmt)).scalars().all()
        print("\n--- Recent Job Runs ---")
        if not jobs:
            print("No jobs found in job_runs table.")
        for j in jobs:
            print(f"[{j.started_at}] {j.job_name}: {j.status} (Error: {j.error_message})")

        # 2. Raw Data Ingestion
        raw_stmt = select(RawItem).order_by(desc(RawItem.fetched_at)).limit(1)
        latest_raw = (await session.execute(raw_stmt)).scalar_one_or_none()
        print("\n--- Data Ingestion ---")
        if latest_raw:
            print(f"Latest Raw Item Fetched: {latest_raw.fetched_at} from {latest_raw.source_system}")
        else:
            print("No raw items found.")

        # 3. Alert Generation
        alert_stmt = select(AlertLog).order_by(desc(AlertLog.triggered_at)).limit(1)
        latest_alert = (await session.execute(alert_stmt)).scalar_one_or_none()
        print("\n--- Alert Generation ---")
        if latest_alert:
            print(f"Latest Alert: {latest_alert.target_label} at {latest_alert.triggered_at} (Status: {latest_alert.status})")
        else:
            print("No alerts found.")

        # 4. Processing Delay Check
        now = datetime.now(timezone.utc)
        if latest_raw and (now - latest_raw.fetched_at).total_seconds() > 3600:
            print(f"\nWARNING: No new data for {int((now - latest_raw.fetched_at).total_seconds()/60)} minutes.")
        
        if latest_alert and (now - latest_alert.triggered_at).total_seconds() > 3600:
            print(f"WARNING: No new alerts for {int((now - latest_alert.triggered_at).total_seconds()/60)} minutes.")

if __name__ == "__main__":
    asyncio.run(run_diagnostics())
