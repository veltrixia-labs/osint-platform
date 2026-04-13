import sys, asyncio
sys.path.insert(0, '.')
from db.database import AsyncSessionLocal
from db.models import AlertLog, Stakeholder
from sqlalchemy.future import select

async def check():
    async with AsyncSessionLocal() as db:
        # 1. Check recent alerts and their cascading impact data
        stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(5)
        alerts = (await db.execute(stmt)).scalars().all()
        print("=== RECENT ALERTS: Impact Data Check ===")
        for a in alerts:
            impacts = a.metadata_json.get('cascading_impacts', []) if a.metadata_json else []
            sources = list(set(i.get('source', 'unknown') for i in impacts))
            print(f"[{a.topic}] {(a.target_label or '')[:50]}")
            print(f"  impacts={len(impacts)}, sources={sources}")
            if impacts:
                s = impacts[0]
                name = s.get('entity_name', 'N/A')
                lat = s.get('location_lat')
                sid = s.get('stakeholder_id')
                print(f"  sample: name={name}, lat={lat}, stakeholder_id={sid}")
            print()

        # 2. Verify backbone stakeholders have coords
        print("=== BACKBONE STAKEHOLDERS: Coordinate Check ===")
        backbone = (await db.execute(
            select(Stakeholder).where(Stakeholder.is_auto_provisioned == False).limit(10)
        )).scalars().all()
        for s in backbone:
            print(f"  [{s.sector}] {s.name}: lat={s.location_lat}, lng={s.location_lng}")

asyncio.run(check())
