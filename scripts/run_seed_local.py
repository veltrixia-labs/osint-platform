import asyncio
import os
import sys
from db.database import AsyncSessionLocal
from db.seeding import seed_admin

async def main():
    if not os.getenv("ADMIN_PASSWORD"):
        os.environ["ADMIN_PASSWORD"] = "admin_test_password"
    
    async with AsyncSessionLocal() as session:
        await seed_admin(session)
        print("Seeding completed.")

if __name__ == "__main__":
    sys.path.append(os.getcwd())
    asyncio.run(main())
