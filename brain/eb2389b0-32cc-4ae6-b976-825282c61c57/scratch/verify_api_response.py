import asyncio
import httpx
import json

async def test_api():
    async with httpx.AsyncClient() as client:
        # Note: rate limit might apply, but let's try local
        # If the server isn't running, this will fail.
        # I'll check the DB directly instead to see what's being stored.
        pass

if __name__ == '__main__':
    # Instead of HTTP, let's check the DB content of the serialized row
    from db.database import AsyncSessionLocal
    from db.models import AlertLog
    from sqlalchemy import select
    from api.routes.free_feed import _serialize, _extract_free_alert

    async def check_db():
        async with AsyncSessionLocal() as db:
            stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(1)
            row = (await db.execute(stmt)).scalar_one_or_none()
            if row:
                fa = _extract_free_alert(row)
                serialized = _serialize(row, fa)
                print(json.dumps(serialized, indent=2))
            else:
                print("No AlertLog found")

    asyncio.run(check_db())
