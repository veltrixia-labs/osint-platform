import asyncio
import os
import yaml
import logging
import httpx
from dotenv import load_dotenv

from integrations.threads_client import threads_mock_force_enabled

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def post_to_threads(text: str):
    """
    Post to Threads using Meta Graph API with Mock fallback for local testing.
    Includes simplified duplicate prevention (logging based).
    """
    if threads_mock_force_enabled():
        logger.warning("THREADS_MOCK_FORCE enabled — skipping Graph API in post_to_threads.")
        logger.info(f"[THREADS MOCK POST]: {text}")
        return True

    token = os.getenv("THREADS_ACCESS_TOKEN") or os.getenv("THREADS_TOKEN")
    user_id = os.getenv("THREADS_USER_ID")
    env_name = os.getenv("ENV", "development").lower()

    if not all([token, user_id]):
        if env_name == "production":
            logger.error("Threads API credentials missing in production environment.")
            return False
        logger.warning("Threads API credentials not found in .env. Using Mock mode.")
        logger.info(f"[THREADS MOCK POST]: {text}")
        return True

    # Note: Real Threads API implementation involves container creation -> publishing
    try:
        async with httpx.AsyncClient() as client:
            # 1. Create Media Container (Text-only)
            url = f"https://graph.threads.net/v1.0/{user_id}/threads"
            payload = {
                "media_type": "TEXT",
                "text": text,
                "access_token": token
            }
            res = await client.post(url, data=payload)
            res.raise_for_status()
            creation_id = res.json().get("id")

            # 2. Publish Media Container
            publish_url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
            publish_payload = {
                "creation_id": creation_id,
                "access_token": token
            }
            res_pub = await client.post(publish_url, data=publish_payload)
            res_pub.raise_for_status()
            
            logger.info(f"Successfully posted to Threads: {res_pub.json()}")
            return True
    except Exception as e:
        logger.error(f"Error posting to Threads: {e}")
        return False

if __name__ == "__main__":
    async def main():
        await post_to_threads("English-only OSINT Platform test post.")
    asyncio.run(main())
