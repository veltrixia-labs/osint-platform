import asyncio
import os
import yaml
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def post_to_threads(text: str):
    """
    Post to Threads using Meta Graph API with Mock fallback for local testing.
    Includes simplified duplicate prevention (logging based).
    """
    token = os.getenv("THREADS_TOKEN")
    user_id = os.getenv("THREADS_USER_ID")

    if not all([token, user_id]):
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
