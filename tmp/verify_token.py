import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

async def verify_threads():
    token = os.getenv("THREADS_ACCESS_TOKEN")
    base_url = "https://graph.threads.net/v1.0"
    url = f"{base_url}/me"
    params = {
        "fields": "id,username",
        "access_token": token
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(verify_threads())
