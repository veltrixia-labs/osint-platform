"""GET /api/items orders by ordered_at (published_at clamped to created_at) and returns it.

Needs TEST_DATABASE_URL (`db_client` skips loudly without it). Rows are tagged and removed.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete


def _session():
    import db.database as dbm
    return dbm.AsyncSessionLocal()


async def test_items_ordered_by_publication_clamped_and_reported(db_client):
    from db.models import Item
    now = datetime.now(timezone.utc)
    tag = uuid.uuid4().hex[:8]
    spec = {  # name: (published_at, created_at)
        "late":    (now - timedelta(hours=25), now - timedelta(minutes=5)),   # arrived a day late
        "fresh":   (now - timedelta(hours=1),  now - timedelta(minutes=50)),
        "older":   (now - timedelta(hours=2),  now - timedelta(hours=2)),
        "future":  (now + timedelta(days=2),   now - timedelta(hours=3)),    # clamped to created_at
        "nopub":   (None,                      now - timedelta(minutes=30)), # falls back to created_at
    }
    ids = {}
    async with _session() as s:
        for name, (pub, created) in spec.items():
            i = uuid.uuid4(); ids[name] = str(i)
            s.add(Item(id=i, dedup_key=f"order-{tag}-{name}", title=f"order {tag} {name}",
                       category="global_market_intelligence", source_id="test_order",
                       published_at=pub, created_at=created))
        await s.commit()
    try:
        resp = await db_client.get("/api/items", params={"topic": "global_market_intelligence", "limit": 300})
        assert resp.status_code == 200, resp.text
        mine = [r for r in resp.json() if r["id"] in ids.values()]
        by_id = {v: k for k, v in ids.items()}
        assert [by_id[r["id"]] for r in mine] == ["nopub", "fresh", "older", "future", "late"]
        oa = {by_id[r["id"]]: datetime.fromisoformat(r["ordered_at"]) for r in mine}
        assert oa["late"] == spec["late"][0]                  # publication time, not ingest
        assert oa["future"] == spec["future"][1]              # clamped: never later than created_at
        assert oa["nopub"] == spec["nopub"][1]                # NULL published_at -> created_at
        assert all(mine[i]["ordered_at"] >= mine[i + 1]["ordered_at"] for i in range(len(mine) - 1))
    finally:
        async with _session() as s:
            await s.execute(delete(Item).where(Item.source_id == "test_order"))
            await s.commit()
