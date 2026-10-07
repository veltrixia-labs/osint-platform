"""purge_items_by_id (jobs/cleanup_job.py): the one-off delete of stale-on-arrival items.

The lookback-parser tests need no database. The guard tests need TEST_DATABASE_URL (the
`db_client` fixture skips them, loudly, without one) and clean up every row they create.
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from jobs.cleanup_job import normalize_lookback_hours, purge_items_by_id


# --- the lookback is read from normalize.py's own source ---------------------------------

def test_lookback_matches_normalize_source():
    # processor/normalize.py run_normalize: `lookback = … - timedelta(hours=12)`
    assert normalize_lookback_hours() == 12.0


def _write(tmp_path, body):
    p = tmp_path / "normalize.py"
    p.write_text("from datetime import timedelta, datetime\n" + body, encoding="utf-8")
    return str(p)


def test_lookback_refuses_ambiguous_source(tmp_path):
    path = _write(tmp_path, (
        "async def run_normalize(db):\n"
        "    lookback = datetime.now() - timedelta(hours=12)\n"
        "    lookback = datetime.now() - timedelta(hours=6)\n"))
    with pytest.raises(RuntimeError):
        normalize_lookback_hours(path)


def test_lookback_refuses_non_literal(tmp_path):
    path = _write(tmp_path, (
        "H = 12\n"
        "async def run_normalize(db):\n"
        "    lookback = datetime.now() - timedelta(hours=H)\n"))
    with pytest.raises(RuntimeError):
        normalize_lookback_hours(path)


def test_lookback_refuses_missing_function(tmp_path):
    with pytest.raises(RuntimeError):
        normalize_lookback_hours(_write(tmp_path, "def other():\n    pass\n"))


# --- the guards, against a real database ---------------------------------------------------

def _session():
    import db.database as dbm  # rebound to the test engine by conftest's _test_engine
    return dbm.AsyncSessionLocal()


async def _make(session, *, stale=True, raw_age_h=13.0, with_raw=True, tag):
    from db.models import Item, RawItem
    now = datetime.now(timezone.utc)
    url = f"https://example.test/{tag}/{uuid.uuid4()}"
    item = Item(id=uuid.uuid4(), dedup_key=f"test-{uuid.uuid4()}", source_id="test_src", source_url=url,
                title=f"purge test {tag}", category="global_market_intelligence",
                published_at=now - timedelta(days=200 if stale else 1), created_at=now)
    session.add(item)
    if with_raw:
        payload = {"link": url, "title": item.title}
        session.add(RawItem(id=uuid.uuid4(), fetched_at=now, source_system="rss", source_endpoint="test",
                            source_id="test_src", payload_json=payload,
                            payload_hash=hashlib.sha256(json.dumps(payload).encode()).hexdigest(),
                            created_at=now - timedelta(hours=raw_age_h)))
    await session.commit()
    return str(item.id), url


async def _cleanup(urls):
    from db.models import Item, RawItem, AnalysisCache, SystemMetric
    async with _session() as s:
        for u in urls:
            await s.execute(delete(Item).where(Item.source_url == u))
            await s.execute(delete(RawItem).where(RawItem.source_id == "test_src"))
        await s.execute(delete(SystemMetric).where(SystemMetric.metric_key == "oneoff_item_purge_result"))
        await s.commit()


async def _present(ids):
    from db.models import Item
    async with _session() as s:
        return len((await s.execute(select(Item.id).where(Item.id.in_(ids)))).all())


async def test_dry_run_is_read_only_and_deletes_nothing(db_client):
    async with _session() as s:
        a = await _make(s, tag="dry1"); b = await _make(s, tag="dry2")
    try:
        async with _session() as s:
            r = await purge_items_by_id(s, [a[0], b[0]], expected_count=2)
        assert r["status"] == "dry_run_ok", r
        assert r["transaction_read_only"] == "on"
        assert r["deleted"] == 0 and r["backing_raw_rows"] == 2
        assert r["references"] == {"analysis_cache": 0, "item_topics": 0, "signal_rankings": 0}
        assert await _present([a[0], b[0]]) == 2
    finally:
        await _cleanup([a[1], b[1]])


@pytest.mark.parametrize("case", ["count", "not_stale", "raw_too_new", "no_raw", "reference", "missing_id"])
async def test_each_guard_refuses_and_deletes_nothing(db_client, case):
    from db.models import AnalysisCache
    async with _session() as s:
        a = await _make(s, tag=f"g-{case}-a",
                        stale=(case != "not_stale"),
                        raw_age_h=(1.0 if case == "raw_too_new" else 13.0),
                        with_raw=(case != "no_raw"))
        b = await _make(s, tag=f"g-{case}-b")
        if case == "reference":
            s.add(AnalysisCache(item_id=uuid.UUID(a[0]), model_name="t")); await s.commit()
    ids = [a[0], b[0]]
    expected = 2
    if case == "count":
        expected = 3
    if case == "missing_id":
        ids.append(str(uuid.uuid4())); expected = 3
    try:
        async with _session() as s:
            r = await purge_items_by_id(s, ids, expected_count=expected, dry_run=False)
        assert r["status"] == "refused", r
        assert r["deleted"] == 0 and r["problems"]
        assert await _present([a[0], b[0]]) == 2          # nothing deleted, not even the valid one
    finally:
        await _cleanup([a[1], b[1]])


async def test_execute_deletes_items_only_and_records_result(db_client):
    from db.models import RawItem, SystemMetric
    async with _session() as s:
        a = await _make(s, tag="ex1"); b = await _make(s, tag="ex2")
    try:
        async with _session() as s:
            r = await purge_items_by_id(s, [a[0], b[0]], expected_count=2, dry_run=False)
        assert r["status"] == "deleted" and r["deleted"] == 2, r
        assert await _present([a[0], b[0]]) == 0
        async with _session() as s:
            raws = (await s.execute(select(RawItem.id).where(RawItem.source_id == "test_src"))).all()
            assert len(raws) == 2                          # (e) raw_items untouched
            rec = (await s.execute(select(SystemMetric.metric_value).where(
                SystemMetric.metric_key == "oneoff_item_purge_result"))).scalar()
        assert json.loads(rec)["status"] == "deleted"
    finally:
        await _cleanup([a[1], b[1]])
