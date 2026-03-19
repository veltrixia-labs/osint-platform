import asyncio
import aiosqlite

async def add_suppressed_column():
    async with aiosqlite.connect("osint.db") as db:
        try:
            await db.execute("ALTER TABLE alert_logs ADD COLUMN suppressed BOOLEAN DEFAULT 0")
            await db.commit()
            print("Successfully added 'suppressed' column to 'alert_logs'.")
        except Exception as e:
            if "duplicate column name" in str(e).lower():
                print("'suppressed' column already exists.")
            else:
                print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(add_suppressed_column())
