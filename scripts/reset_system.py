import asyncio
import logging
import os
import sys
from sqlalchemy import delete

# Add project root to path
sys.path.append(os.getcwd())

from db.database import AsyncSessionLocal
from db.models import (
    Item, RawItem, ItemTopic, AnalysisCache, EventCluster, 
    TrendSignal, AlertLog, AlertDelivery, SignalRanking, 
    Report, ArticleOutput, PdfJob, ExternalPost, 
    ReportTriggerLog, AnalystProfile, Topic
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ResetSystem")

async def wipe_operational_data():
    logger.info("--- STARTING MASTER SYSTEM RESET ---")
    
    # Order of deletion matters due to foreign keys (Bottom-up)
    tables_to_wipe = [
        AlertDelivery,
        AlertLog,
        ReportTriggerLog,
        ExternalPost,
        PdfJob,
        ArticleOutput,
        SignalRanking,
        Report,
        TrendSignal,
        AnalysisCache,
        ItemTopic,
        Item,
        RawItem,
        EventCluster
    ]
    
    async with AsyncSessionLocal() as session:
        for table in tables_to_wipe:
            try:
                name = table.__tablename__
                logger.info(f"Wiping table: {name}...")
                await session.execute(delete(table))
            except Exception as e:
                logger.error(f"Failed to wipe {table}: {e}")
        
        await session.commit()
        logger.info("--- DATABASE WIPE COMPLETED ---")

    # Clear AI Safety Devices (Circuit Breaker)
    metric_path = os.path.join(os.getcwd(), "outputs", "health_metrics.json")
    if os.path.exists(metric_path):
        try:
            os.remove(metric_path)
            logger.info(f"Reset AI Health Metrics: {metric_path} deleted.")
        except Exception as e:
            logger.error(f"Failed to delete health metrics: {e}")
    else:
        logger.info("No existing health metrics found (Clean State).")

if __name__ == "__main__":
    asyncio.run(wipe_operational_data())
