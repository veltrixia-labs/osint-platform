import asyncio
import logging
from jobs.main_scheduler import main as scheduler_main
from db.database import engine, Base
from api.routes.backbone import router as backbone_router


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_db():
    logger.info("Initializing Database...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized.")

async def run_one_off_pipeline():
    logger.info("Running one-off full pipeline simulation...")
    from jobs.main_scheduler import pipeline_full_processing
    await pipeline_full_processing()
    logger.info("Completed one-off pipeline simulation.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--init-db", action="store_true", help="Initialize Database")
    parser.add_argument("--run-once", action="store_true", help="Run the pipeline once instead of scheduling")
    
    args = parser.parse_args()
    
    if args.init_db:
        asyncio.run(init_db())
    elif args.run_once:
        asyncio.run(run_one_off_pipeline())
    else:
        # Start the async-native scheduler
        asyncio.run(scheduler_main())
