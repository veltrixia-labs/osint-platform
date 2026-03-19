import asyncio
import logging
from db.database import engine, Base
from jobs.main_scheduler import register_jobs, run_async, pipeline_full_processing

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_db():
    logger.info("Initializing Database...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized.")

async def run_one_off_pipeline():
    logger.info("Running one-off full pipeline simulation...")
    await pipeline_full_processing()
    from jobs.main_scheduler import weekly_reports
    await weekly_reports()
    logger.info("Completed one-off pipeline simulation.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--init-db", action="store_true", help="Initialize Database")
    parser.add_argument("--run-once", action="store_true", help="Run the pipeline once instead of scheduling")
    
    args = parser.parse_args()
    
    if args.init_db:
        asyncio.run(init_db())
        
    if args.run_once:
        asyncio.run(run_one_off_pipeline())
    elif not args.init_db:
        # start scheduler
        import time
        import schedule
        from jobs.main_scheduler import register_jobs
        register_jobs()
        logger.info("Scheduler started...")
        while True:
            schedule.run_pending()
            time.sleep(60)
