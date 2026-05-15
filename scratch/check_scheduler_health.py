import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import SystemMetric
from sqlalchemy import select

async def check_health():
    async with AsyncSessionLocal() as db:
        print("=" * 80)
        print(f"SCHEDULER HEALTH MONITOR - {datetime.now(timezone.utc).isoformat()}")
        print("=" * 80)
        
        stmt = select(SystemMetric).where(SystemMetric.metric_key == "scheduler_heartbeat")
        res = await db.execute(stmt)
        metric = res.scalar_one_or_none()
        
        if not metric:
            print("[CRITICAL] scheduler_heartbeat metric not found in DB!")
            sys.exit(1)
            
        hb_str = metric.metric_value
        try:
            hb_dt = datetime.fromisoformat(hb_str)
            if hb_dt.tzinfo is None:
                hb_dt = hb_dt.replace(tzinfo=timezone.utc)
        except Exception as e:
            print(f"[ERROR] Failed to parse heartbeat '{hb_str}': {e}")
            sys.exit(1)
            
        now = datetime.now(timezone.utc)
        diff = now - hb_dt
        
        print(f"Last Heartbeat: {hb_dt.isoformat()}")
        print(f"Time Since Last: {diff}")
        
        if diff > timedelta(minutes=60):
            print(f"[CRITICAL] Scheduler has been dead for {diff}!")
        elif diff > timedelta(minutes=15):
            print(f"[WARNING] Scheduler heartbeat is lagging: {diff}")
        else:
            print(f"[OK] Scheduler is healthy (Heartbeat within last {diff}).")
            
        # Also check last full run
        stmt_run = select(SystemMetric).where(SystemMetric.metric_key == "scheduler_last_full_run")
        res_run = await db.execute(stmt_run)
        metric_run = res_run.scalar_one_or_none()
        if metric_run:
            print(f"Last Full Run:  {metric_run.metric_value}")

if __name__ == "__main__":
    asyncio.run(check_health())
