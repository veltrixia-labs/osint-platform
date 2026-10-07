"""The stale-on-arrival filter in processor/normalize.py, through the real run_normalize.

Needs TEST_DATABASE_URL (the `db_client` fixture skips, loudly, without it). Every row a test
creates is tagged with a unique URL and removed afterwards.
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from config.settings import settings
from processor.normalize import run_normalize

SEMI = "TSMC expands advanced semiconductor chip fabrication capacity in Arizona amid export controls"
FED = "Federal Reserve raises interest rates as inflation persists in bond markets"
SUMMARY = "Details of the announcement and the market reaction across the sector this week."


def _session():
    import db.database as dbm  # rebound to the test engine by conftest
    return dbm.AsyncSessionLocal()


async def _raw(s, *, title, age_days, tag):
    from db.models import RawItem
    now = datetime.now(timezone.utc)
    url = f"https://example.test/stale/{tag}/{uuid.uuid4()}"
    payload = {"link": url, "title": f"{title} {tag}", "summary": SUMMARY,
               "published": (now - timedelta(days=age_days)).isoformat()}
    s.add(RawItem(id=uuid.uuid4(), fetched_at=now, source_system="rss", source_endpoint="test",
                  source_id="test_stale", source_group=None, payload_json=payload,
                  payload_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()))
    await s.commit()
    return url


def _key(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


async def _state(urls):
    from db.models import IngestRejection, Item
    async with _session() as s:
        items = {r[0] for r in (await s.execute(select(Item.source_url).where(Item.source_url.in_(urls)))).all()}
        rej = {r.dedup_key: r for r in (await s.execute(select(IngestRejection).where(
            IngestRejection.dedup_key.in_([_key(u) for u in urls] + ["config:stale_on_arrival_invariant"])))).scalars()}
    return items, rej


async def _cleanup(urls):
    from db.models import IngestRejection, Item, RawItem
    async with _session() as s:
        await s.execute(delete(Item).where(Item.source_url.in_(urls)))
        await s.execute(delete(RawItem).where(RawItem.source_id == "test_stale"))
        await s.execute(delete(IngestRejection).where(IngestRejection.dedup_key.in_(
            [_key(u) for u in urls] + ["config:stale_on_arrival_invariant"])))
        await s.commit()


async def _normalize():
    async with _session() as s:
        await run_normalize(s)


async def test_stale_entry_is_rejected_and_recorded_fresh_one_is_created(db_client):
    tag = uuid.uuid4().hex[:8]
    async with _session() as s:
        fresh = await _raw(s, title=SEMI, age_days=0, tag=f"fresh{tag}")
        edge = await _raw(s, title=FED, age_days=13, tag=f"edge{tag}")       # inside 14 days: created
        stale = await _raw(s, title=SEMI + " update", age_days=20, tag=f"stale{tag}")
    urls = [fresh, edge, stale]
    try:
        await _normalize()
        items, rej = await _state(urls)
        assert fresh in items and edge in items
        assert stale not in items
        r = rej[_key(stale)]
        assert r.reason == "stale_on_arrival" and r.threshold_days == settings.stale_on_arrival_days
        assert r.source_id == "test_stale" and r.source_url == stale
        assert _key(fresh) not in rej and _key(edge) not in rej
        first = r.first_rejected_at

        # normalize re-reads the same raw rows next cycle: still ONE row, only last_rejected_at moves
        await _normalize()
        items, rej = await _state(urls)
        assert stale not in items
        assert len([k for k in rej if k == _key(stale)]) == 1
        assert rej[_key(stale)].first_rejected_at == first
        assert rej[_key(stale)].last_rejected_at >= first
    finally:
        await _cleanup(urls)


async def test_old_entry_whose_item_exists_is_a_duplicate_not_a_rejection(db_client):
    """A feed that keeps serving an entry past the threshold, while its item still exists, is
    an ordinary duplicate and must not be recorded."""
    from db.models import Item
    tag = uuid.uuid4().hex[:8]
    async with _session() as s:
        url = await _raw(s, title=SEMI + " followup", age_days=20, tag=f"dup{tag}")
        s.add(Item(id=uuid.uuid4(), dedup_key=_key(url), source_id="test_stale", source_url=url,
                   title="existing", published_at=datetime.now(timezone.utc) - timedelta(days=20)))
        await s.commit()
    try:
        await _normalize()
        _, rej = await _state([url])
        assert _key(url) not in rej
    finally:
        await _cleanup([url])


async def test_invariant_broken_filter_not_applied_and_refusal_recorded(db_client, monkeypatch):
    monkeypatch.setattr(settings, "stale_on_arrival_days", settings.raw_retention_days)  # == retention
    tag = uuid.uuid4().hex[:8]
    async with _session() as s:
        stale = await _raw(s, title=FED + " outlook", age_days=20, tag=f"inv{tag}")
    try:
        await _normalize()
        items, rej = await _state([stale])
        assert stale in items                                   # filter NOT applied
        assert _key(stale) not in rej
        cfg = rej["config:stale_on_arrival_invariant"]          # ...and the refusal is recorded
        assert "NOT applied" in cfg.reason and cfg.threshold_days == settings.raw_retention_days
    finally:
        await _cleanup([stale])


async def test_retention_deletes_rejections_by_last_rejected_at(db_client):
    """90 days after the entry was LAST seen, through the existing retention job."""
    from db.models import IngestRejection
    from jobs.cleanup_job import run_retention_cleanup
    now = datetime.now(timezone.utc)
    old, recent = f"test-old-{uuid.uuid4()}", f"test-recent-{uuid.uuid4()}"
    async with _session() as s:
        s.add(IngestRejection(dedup_key=old, reason="stale_on_arrival",
                              first_rejected_at=now - timedelta(days=200), last_rejected_at=now - timedelta(days=100)))
        s.add(IngestRejection(dedup_key=recent, reason="stale_on_arrival",   # first seen long ago, re-seen lately
                              first_rejected_at=now - timedelta(days=200), last_rejected_at=now - timedelta(days=10)))
        await s.commit()
    try:
        async with _session() as s:
            dry = await run_retention_cleanup(s, dry_run=True)
        assert dry["ingest_rejections"] >= 1
        async with _session() as s:
            assert len((await s.execute(select(IngestRejection.dedup_key).where(
                IngestRejection.dedup_key.in_([old, recent])))).all()) == 2       # dry run deleted nothing
            await run_retention_cleanup(s, dry_run=False)
        async with _session() as s:
            left = {r[0] for r in (await s.execute(select(IngestRejection.dedup_key).where(
                IngestRejection.dedup_key.in_([old, recent])))).all()}
        assert left == {recent}
    finally:
        async with _session() as s:
            await s.execute(delete(IngestRejection).where(IngestRejection.dedup_key.in_([old, recent])))
            await s.commit()
