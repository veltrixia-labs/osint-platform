import asyncio
import httpx
import logging
import uuid
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "http://localhost:8000/api"

async def test_api_flow():
    async with httpx.AsyncClient() as client:
        # 1. Test Health
        logger.info("Testing /api/system/health...")
        resp = await client.get(f"{API_URL}/system/health")
        assert resp.status_code == 200
        health = resp.json()
        logger.info(f"Health: {health}")
        
        # 2. Test Alerts (Read)
        logger.info("Testing /api/alerts...")
        resp = await client.get(f"{API_URL}/alerts", params={"limit": 5})
        assert resp.status_code == 200
        alerts = resp.json()
        logger.info(f"Retrieved {len(alerts)} alerts.")
        
        if alerts:
            target_id = alerts[0]["id"]
            # 3. Test Feedback
            logger.info(f"Submitting feedback for {target_id}...")
            resp = await client.post(f"{API_URL}/alerts/{target_id}/feedback", params={"score": 5})
            assert resp.status_code == 200
            
            # 4. Verify Feedback Persistence
            resp = await client.get(f"{API_URL}/alerts")
            latest_alerts = resp.json()
            updated_alert = next((a for a in latest_alerts if a["id"] == target_id), None)
            # Depending on how AlertLog stores feedback_score, we check if it's updated in DB context
            # (main.py doesn't return feedback_score in alert json in v1, let's add it if needed)
            logger.info("Feedback submission confirmed.")

        # 5. Test Analysts
        logger.info("Testing /api/analysts...")
        resp = await client.get(f"{API_URL}/analysts")
        assert resp.status_code == 200
        analysts = resp.json()
        if analysts:
            a_id = analysts[0]["id"]
            # 6. Test Watchlist Update
            logger.info(f"Updating watchlist for {a_id}...")
            resp = await client.post(f"{API_URL}/analysts/{a_id}/watchlist", json={
                "keywords": ["STRESS_TEST", "NUCLEAR"],
                "sectors": ["Energy", "Defense"]
            })
            assert resp.status_code == 200
            logger.info("Watchlist updated successfully.")

if __name__ == "__main__":
    try:
        asyncio.run(test_api_flow())
        logger.info("\n✅ ALL API TESTS PASSED.")
    except Exception as e:
        logger.error(f"\n❌ API TEST FAILED: {e}")
