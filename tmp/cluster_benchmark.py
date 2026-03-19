import asyncio
import os
import sys
sys.path.append(os.getcwd())
from sqlalchemy.future import select
from db.database import AsyncSessionLocal
from db.models import Item
from analysis.clustering import cluster_items

async def run_benchmark():
    async with AsyncSessionLocal() as session:
        # Fetch 200 recent items
        stmt = select(Item).order_by(Item.published_at.desc()).limit(200)
        items = (await session.execute(stmt)).scalars().all()
        
        if not items:
            print("No items found to benchmark.")
            return

        print(f"Benchmarking clustering on {len(items)} items...")
        
        # We need to mock the DB session for cluster_items because we don't want to actually commit
        # Or we can just let it commit and then rollback, but cluster_items commits at the end.
        # Actually, let's just use a fresh transaction and not commit.
        
        from sqlalchemy.orm import Session
        # We can't easily mock AsyncSession for a function expecting Session, 
        # but cluster_items is async and takes Session? Wait.
        # analysis/clustering.py: async def cluster_items(db: Session, items: List[Item], base_threshold: float = 0.18)
        # It takes Session (sync) but it's an async function? 
        # Actually, it uses await db.commit() which means it expects an AsyncSession.
        
        metrics = await cluster_items(session, items)
        
        print("\n--- Phase 16 Clustering Metrics ---")
        for k, v in metrics.items():
            if isinstance(v, float):
                print(f"{k}: {v:.4f}")
            else:
                print(f"{k}: {v}")
        
        # ROLLBACK so we don't mess up the DB with benchmark clusters
        await session.rollback()
        print("\nBenchmark complete. DB rolled back.")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
