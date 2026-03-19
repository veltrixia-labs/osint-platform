import os
import asyncio
import httpx
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class ThreadsClient:
    def __init__(
        self, 
        access_token: str, 
        user_id: str,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None
    ):
        self.access_token = access_token
        self.user_id = user_id
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = "https://graph.threads.net/v1.0"

    async def _request_with_retry(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Helper for exponential backoff retries on transient errors."""
        max_retries = 3
        backoff = 2
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.request(method, url, **kwargs)
                    if response.status_code in [429, 500, 502, 503, 504]:
                        raise httpx.HTTPStatusError("Transient error", request=response.request, response=response)
                    return response
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                if attempt == max_retries - 1:
                    raise e
                wait = backoff ** (attempt + 1)
                logger.warning(f"Threads API transient error: {e}. Retrying in {wait}s...")
                await asyncio.sleep(wait)
        return None # Should not reach here

    async def refresh_access_token(self) -> Optional[str]:
        """Refreshes a long-lived access token (valid for 60 days)."""
        if not self.app_secret:
            logger.error("Cannot refresh token: THREADS_APP_SECRET missing.")
            return None
            
        url = "https://graph.threads.net/refresh_access_token"
        params = {
            "grant_type": "th_refresh_token",
            "access_token": self.access_token
        }
        try:
            response = await self._request_with_retry("GET", url, params=params)
            if response.status_code == 200:
                data = response.json()
                new_token = data.get("access_token")
                if new_token:
                    self.access_token = new_token
                    logger.info("Threads access token refreshed successfully.")
                    return new_token
            logger.error(f"Failed to refresh Threads token: {response.text}")
        except Exception as e:
            logger.error(f"Error during token refresh: {e}")
        return None

    async def create_text_container(self, text: str) -> Optional[str]:
        """Creates a media container for a text Threads post."""
        url = f"{self.base_url}/{self.user_id}/threads"
        params = {
            "media_type": "TEXT",
            "text": text,
            "access_token": self.access_token
        }
        try:
            response = await self._request_with_retry("POST", url, params=params)
            if response.status_code == 200:
                data = response.json()
                return data.get("id")
            logger.error(f"Failed to create Threads container: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error creating Threads container: {e}")
        return None

    async def get_container_status(self, container_id: str) -> str:
        """Polls the status of the media container."""
        url = f"{self.base_url}/{container_id}"
        params = {
            "fields": "status,error_message",
            "access_token": self.access_token
        }
        try:
            response = await self._request_with_retry("GET", url, params=params)
            if response.status_code == 200:
                data = response.json()
                return data.get("status", "IN_PROGRESS")
            logger.error(f"Failed to get Threads container status: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error checking Threads container status: {e}")
        return "ERROR"

    async def publish_container(self, container_id: str) -> Optional[str]:
        """Publishes the finished media container."""
        url = f"{self.base_url}/{self.user_id}/threads_publish"
        params = {
            "creation_id": container_id,
            "access_token": self.access_token
        }
        try:
            response = await self._request_with_retry("POST", url, params=params)
            if response.status_code == 200:
                data = response.json()
                return data.get("id")
            logger.error(f"Failed to publish Threads container: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error publishing Threads container: {e}")
        return None

    async def post_thread(self, text: str, poll_interval: int = 2, max_retries: int = 15) -> Dict:
        """High-level flow to post a thread with status polling."""
        result = {
            "success": False,
            "container_id": None,
            "media_id": None,
            "published_at": None,
            "error": None
        }

        # 1. Create
        container_id = await self.create_text_container(text)
        if not container_id:
            result["error"] = "Failed to create container"
            return result
        
        result["container_id"] = container_id

        # 2. Poll
        status = "IN_PROGRESS"
        for i in range(max_retries):
            status = await self.get_container_status(container_id)
            if status == "FINISHED":
                break
            if status == "ERROR":
                result["error"] = "Container status returned ERROR"
                return result
            await asyncio.sleep(poll_interval)
        
        if status != "FINISHED":
            result["error"] = f"Timed out waiting for FINISHED (current: {status})"
            return result

        # 3. Publish
        media_id = await self.publish_container(container_id)
        if media_id:
            result["success"] = True
            result["media_id"] = media_id
            result["published_at"] = datetime.now(timezone.utc).isoformat()
        else:
            result["error"] = "Failed to publish container"
        
        return result
