import asyncio
import uuid
from sqlalchemy.future import select
from db.database import AsyncSessionLocal
from db.models import Stakeholder, Dependency, Prediction
from processor.impact_calculator import ImpactCalculator

async def audit_data_and_metrics():
    print("--- [Antigravity Audit] v10.18.2 ---")
    async with AsyncSessionLocal() as db:
        # 1. Check Dependencies
        stmt = select(Dependency)
        deps = (await db.execute(stmt)).scalars().all()
        print(f"Total Dependencies in DB: {len(deps)}")
        
        # 2. Check BAE Systems (from user screenshot)
        bae_stmt = select(Stakeholder).where(Stakeholder.name.ilike("%BAE%"))
        bae = (await db.execute(bae_stmt)).scalar_one_or_none()
        
        if bae:
            print(f"Found Stakeholder: {bae.name} ({bae.id})")
            indices = await ImpactCalculator.evaluate_sociographic_indices(db, bae.id)
            print(f"Calculated Indices for {bae.name}:")
            print(f"  Resilience: {indices['resilience']}")
            print(f"  Contagion: {indices['contagion']}")
            print(indices)
        else:
            print("Stakeholder 'BAE Systems' not found in DB.")

        # 3. Check recent predictions
        pred_stmt = select(Prediction).order_by(Prediction.created_at.desc()).limit(5)
        preds = (await db.execute(pred_stmt)).scalars().all()
        print(f"Recent Predictions count: {len(preds)}")
        for p in preds:
            print(f"  - Prediction for {p.target_id}: Alpha={p.predicted_alpha}, Confidence={p.confidence_score}")

if __name__ == "__main__":
    asyncio.run(audit_data_and_metrics())
