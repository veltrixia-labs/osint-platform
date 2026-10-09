"""check_job_runs: did each scheduled job run, and how did it end? READ-ONLY.

    python scripts/check_job_runs.py            # uses DATABASE_URL (config.settings)

Opens one connection with default_transaction_read_only=on and statement_timeout=15s, asserts
transaction_read_only = on, and refuses to continue otherwise. Writes nothing. No alerting.

Per job (from job_runs, written by jobs/run_recorder.py):
  last success, expected gap, overdue (no success within the gap), and over the last 24 h the
  counts of failed / degraded / orphaned / skipped runs.

  orphaned = status 'running' and started more than 2 x the expected gap ago (the job's duration
             is not known in advance, so the gap bounds it; a killed process leaves such rows).
  overdue  = no 'success' row within the expected gap. 'degraded' does not count as success.

EXPECTED_GAP mirrors register_jobs() in jobs/main_scheduler.py with slack; it is a reading aid,
not a source of truth. Startup steps have no gap: only their last run is shown.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EXPECTED_GAP = {
    "pipeline": timedelta(minutes=15),
    "threads_publisher": timedelta(minutes=30),
    "pro_automation": timedelta(minutes=45),
    "cleanup": timedelta(minutes=75),
    "monthly_trend": timedelta(minutes=75),
    "health_check": timedelta(hours=7),
    "daily_report": timedelta(hours=26),
    "ops_monitoring": timedelta(hours=26),
    "external_data_sync": timedelta(hours=26),
    "entity_lifecycle": timedelta(hours=26),
    "pro_structural_retention": timedelta(hours=26),
    "market_price_sync": timedelta(hours=26),
    "cftc_sync": timedelta(days=8),
}
EVENT_JOBS = ("startup_pipeline", "startup_pro_compile")
ORPHAN_EVENT_AFTER = timedelta(hours=2)

REPORT_SQL = """
with expected(job_name, gap) as (select * from unnest(cast(:names as text[]), cast(:gaps as interval[])))
select e.job_name,
       e.gap,
       max(r.started_at) filter (where r.status = 'success')                                   as last_success,
       coalesce(max(r.started_at) filter (where r.status = 'success') < now() - e.gap, true)    as overdue,
       count(*) filter (where r.status = 'failed'   and r.started_at > now() - interval '24 hours') as failed_24h,
       count(*) filter (where r.status = 'degraded' and r.started_at > now() - interval '24 hours') as degraded_24h,
       count(*) filter (where r.status = 'running'  and r.started_at < now() - 2 * e.gap)           as orphaned,
       count(*) filter (where left(r.status, 8) = 'skipped_' and r.started_at > now() - interval '24 hours') as skipped_24h
from expected e left join job_runs r on r.job_name = e.job_name
group by e.job_name, e.gap
order by overdue desc, failed_24h desc, e.job_name
"""

EVENT_SQL = """
select job_name, status, started_at, finished_at, left(coalesce(error_message, ''), 200) as message,
       (status = 'running' and started_at < now() - cast(:orphan as interval)) as orphaned
from (select *, row_number() over (partition by job_name order by started_at desc) as rn
      from job_runs where job_name = any(cast(:names as text[]))) t
where rn = 1 order by job_name
"""


async def build_report(conn):
    """Run both queries on an open connection. Returns (job_rows, event_rows) as lists of dicts."""
    from sqlalchemy import text

    names = list(EXPECTED_GAP)
    gaps = list(EXPECTED_GAP.values())  # asyncpg binds timedelta to interval
    jobs = (await conn.execute(text(REPORT_SQL), {"names": names, "gaps": gaps})).mappings().all()
    events = (await conn.execute(text(EVENT_SQL), {"names": list(EVENT_JOBS),
                                                    "orphan": ORPHAN_EVENT_AFTER})).mappings().all()
    return [dict(r) for r in jobs], [dict(r) for r in events]


async def main() -> int:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from db.database import get_engine_args

    db_url, connect_args, _ = get_engine_args(use_asyncpg=True)
    connect_args = dict(connect_args)
    connect_args["server_settings"] = {"default_transaction_read_only": "on", "statement_timeout": "15s"}
    engine = create_async_engine(db_url, connect_args=connect_args, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as conn:
            ro = (await conn.execute(text("show transaction_read_only"))).scalar()
            if ro != "on":
                print("ABORT: the session is not read-only")
                return 2
            now = (await conn.execute(text("select now()"))).scalar()
            jobs, events = await build_report(conn)
    finally:
        await engine.dispose()

    print(f"check_job_runs  now={now:%Y-%m-%d %H:%M:%SZ}  (read-only)")
    print(f"{'job':26} {'gap':>9} {'last success (UTC)':20} {'overdue':7} {'failed':>6} {'degraded':>8} {'orphaned':>8} {'skipped':>7}")
    for r in jobs:
        last = r["last_success"].strftime("%Y-%m-%d %H:%M") if r["last_success"] else "never"
        gap = r["gap"]
        gap_s = f"{int(gap.total_seconds() // 3600)}h{int(gap.total_seconds() % 3600 // 60):02d}m"
        print(f"{r['job_name']:26} {gap_s:>9} {last:20} {('YES' if r['overdue'] else 'no'):7} "
              f"{r['failed_24h']:>6} {r['degraded_24h']:>8} {r['orphaned']:>8} {r['skipped_24h']:>7}")
    print("startup steps (last run):")
    if not events:
        print("  none recorded")
    for e in events:
        print(f"  {e['job_name']:24} {e['status']:16} started={e['started_at']:%Y-%m-%d %H:%M:%S}"
              f"{'  ORPHANED' if e['orphaned'] else ''}  {e['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
