import asyncio
import os
import sys
sys.path.append(os.getcwd())
from sqlalchemy.future import select
from db.database import AsyncSessionLocal
from db.models import EventCluster

async def baseline_metrics():
    async with AsyncSessionLocal() as session:
        stmt = select(EventCluster)
        clusters = (await session.execute(stmt)).scalars().all()
        
        if not clusters:
            print("No clusters found in DB.")
            return

        total_articles = sum(c.article_count for c in clusters)
        total_clusters = len(clusters)
        singletons = [c for c in clusters if c.article_count == 1]
        
        avg_items = total_articles / total_clusters if total_clusters > 0 else 0
        singleton_pct = (len(singletons) / total_clusters) * 100 if total_clusters > 0 else 0
        
        print(f"--- Clustering Baseline ---")
        print(f"Total Clusters: {total_clusters}")
        print(f"Total Articles: {total_articles}")
        print(f"Avg Items / Cluster: {avg_items:.2f}")
        print(f"Singletons: {len(singletons)} ({singleton_pct:.2f}%)")
        print(f"Max items in one cluster: {max(c.article_count for c in clusters)}")

if __name__ == "__main__":
    asyncio.run(baseline_metrics())
