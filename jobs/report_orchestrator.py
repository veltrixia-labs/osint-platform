"""
jobs/report_orchestrator.py
Parallel report generation orchestrator:
  - run_all_reports: populates a task queue for all topics + global
  - report_worker:   async worker that processes one report task with timeout

Separated from report_generator.py to isolate the concurrency/queue logic
from the core generation pipeline, making each component easier to test
and reason about independently.
"""
import asyncio
import logging
from typing import Dict

from db.database import AsyncSessionLocal
from jobs.report_generator import run_report_generation, TOPIC_CONFIG

logger = logging.getLogger(__name__)

NUM_WORKERS = 3
REPORT_TASK_DEADLINE = 240.0
EXPECTED_CATEGORIES = 7  # 6 topics + 1 global


async def report_worker(queue: asyncio.Queue, results_collector: Dict[str, str]):
    """Async worker: pulls report tasks from queue and runs them with a timeout."""
    while True:
        task = await queue.get()
        if task is None:
            queue.task_done()
            break

        args = task
        topic_key = args[2] or "global"

        try:
            async with AsyncSessionLocal() as session:
                teaser, status, reason = await asyncio.wait_for(
                    run_report_generation(session, *args[:3], auto_post_threads=args[3]),
                    timeout=REPORT_TASK_DEADLINE
                )
                results_collector[topic_key] = status
                logger.info(f"Report finished: {topic_key} | Status: {status}")
        except Exception as e:
            logger.error(f"Worker failed category {topic_key}: {e}")
            results_collector[topic_key] = "failed"
        finally:
            queue.task_done()


async def run_all_reports(
    db,
    report_type: str = "weekly_global",
    period_days: int = 7,
    auto_post_threads: bool = False
):
    """
    Dispatches one report generation task per topic (+ global) to a worker pool.
    Uses an asyncio.Queue with NUM_WORKERS concurrent workers.
    Each task tuple: (report_type, period_days, topic_or_None, auto_post_threads)
    """
    from llm.client import get_metrics_summary

    if report_type in ("daily", "daily_global"):
        logger.info("Free daily reports are deprecated. Skipping orchestration.")
        return

    queue: asyncio.Queue = asyncio.Queue()
    results_collector: Dict[str, str] = {}

    # Populate queue: global first, then per-topic
    queue.put_nowait((report_type, period_days, None, auto_post_threads))
    for t in TOPIC_CONFIG.keys():
        queue.put_nowait((report_type, period_days, t, auto_post_threads))

    workers = [
        asyncio.create_task(report_worker(queue, results_collector))
        for _ in range(NUM_WORKERS)
    ]
    await queue.join()

    # Signal workers to stop
    for _ in range(NUM_WORKERS):
        queue.put_nowait(None)
    await asyncio.gather(*workers)

    # Logging Summary
    success_count = sum(1 for v in results_collector.values() if v == "success")
    degraded_count = sum(1 for v in results_collector.values() if v == "degraded")
    failed_count = sum(1 for v in results_collector.values() if v == "failed")

    logger.info("--- Report Generation Summary ---")
    logger.info(f"Categories Processed: {len(results_collector)} / {EXPECTED_CATEGORIES}")
    logger.info(f"Results: {results_collector}")
    logger.info(f"Success: {success_count}, Degraded: {degraded_count}, Failed: {failed_count}")

    if len(results_collector) < EXPECTED_CATEGORIES or failed_count > 0:
        logger.warning("!!! INCOMPLETE REPORT JOB DETECTED !!! Missing or failed categories.")

    logger.info(get_metrics_summary())
