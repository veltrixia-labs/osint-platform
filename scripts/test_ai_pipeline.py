import asyncio
import logging
import sys
import os
import uuid
from datetime import datetime, timezone

# Add project root to path
sys.path.append(os.getcwd())

from db.database import AsyncSessionLocal
from db.models import Item, Topic
from llm.client import generate_analysis

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("AI_Diagnostic")

async def test_llm_connectivity():
    logger.info("--- STARTING AI CONNECTIVITY DIAGNOSTIC (SINGLE ITEM) ---")
    
    # 1. Mock "Energy Risk" Item
    mock_item = Item(
        id=uuid.uuid4(),
        title="OPEC+ Announces Unexpected Crude Oil Output Cut",
        summary="OPEC members agreed to a voluntary cut of 1M barrels per day to stabilize market pricing as global demand shifts.",
        source_name="OSINT Diagnostic Tool",
        source_url="https://example.com/diagnostic",
        published_at=datetime.now(timezone.utc),
        rough_category="energy_resource_risk",
        lightweight_score=8.5
    )
    
    # 2. Test All Providers
    test_prompts = {
        "system": "You are an OSINT Intelligence Analyst. Answer with 'READY' if you receive this.",
        "user": "System check."
    }
    
    target_providers = ["gemini", "openai", "deepseek", "ollama"]
    
    for p_name in target_providers:
        logger.info(f"--- Testing Provider: {p_name.upper()} ---")
        try:
            res = await generate_analysis(test_prompts["system"], test_prompts["user"], preferred_model=p_name, is_batch=False)
            if res and "## Mock Analysis" not in res and res != "__DEGRADED_MODE__":
                logger.info(f"✅ {p_name.upper()}: SUCCESS")
                logger.info(f"Response: {res[:50]}...")
            else:
                logger.warning(f"❌ {p_name.upper()}: FAILED (Blocked or Degraded)")
        except Exception as e:
            logger.error(f"💥 {p_name.upper()}: CRASHED - {e}")

    logger.info("--- AI CONNECTIVITY DIAGNOSTIC COMPLETED ---")

if __name__ == "__main__":
    asyncio.run(test_llm_connectivity())
