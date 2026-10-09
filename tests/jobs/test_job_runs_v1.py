"""job_runs v1 (jobs/run_recorder.py, jobs/main_scheduler.py): every scheduled run leaves a record.

Unit tests need no database. Tests that read job_runs request `db_client`, which skips them loudly
without TEST_DATABASE_URL; each one uses a unique job name and deletes its own rows.
"""
import logging
import re
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text

import db.database as dbm
from db.models import JobRun, SystemMetric
import jobs.main_scheduler as ms
import jobs.run_recorder as rr
from jobs.cleanup_job import purge_old_job_runs

ROOT = Path(__file__).resolve().parents[2]


# --- helpers -------------------------------------------------------------------------------------

def _name(tag):
    return f"test_jr_{tag}_{uuid.uuid4().hex[:8]}"


async def _rows(job_name):
    async with dbm.AsyncSessionLocal() as s:
        return (await s.execute(select(JobRun).where(JobRun.job_name == job_name)
                                .order_by(JobRun.started_at))).scalars().all()


async def _cleanup(*names):
    async with dbm.AsyncSessionLocal() as s:
        await s.execute(delete(JobRun).where(JobRun.job_name.in_(names)))
        await s.commit()


class _DiskFull(Exception):
    """Shape of asyncpg.exceptions.DiskFullError: carries SQLSTATE 53100."""
    sqlstate = "53100"


@asynccontextmanager
async def _dummy_session():
    class _S:
        def expire_all(self):
            pass
    yield _S()


# --- unit: scrubbing, disk-full detection, result convention ------------------------------------

def test_scrub_removes_every_secret_shape_and_truncates():
    planted = ("boom sk_live_ABCdef123SECRET rk_live_ZZZ999SECRET sk_test_TTT111SECRET "
               "whsec_WHSECRET42 postgresql+asyncpg://user:pw@db.example.com:5432/prod "
               "Authorization: Bearer eyJhbGciOi.SECRETTOKEN")
    out = rr.scrub(planted)
    for secret in ("ABCdef123SECRET", "ZZZ999SECRET", "TTT111SECRET", "WHSECRET42", "user:pw@",
                   "db.example.com", "SECRETTOKEN"):
        assert secret not in out
    assert "sk_live_[redacted]" in out and "postgres://[redacted]" in out
    long = rr.scrub("x" * 5000)
    assert len(long) <= rr.MAX_MESSAGE_CHARS and long.endswith("[truncated]")
    assert rr.scrub(None) is None


def test_is_disk_full_follows_wrapped_exceptions():
    inner = _DiskFull("could not extend file")

    class _SAError(Exception):
        pass

    wrapped = _SAError("(sqlalchemy) wrapped")
    wrapped.orig = inner
    assert rr.is_disk_full(inner)
    assert rr.is_disk_full(wrapped)
    try:
        try:
            raise inner
        except _DiskFull as e:
            raise RuntimeError("context") from e
    except RuntimeError as outer:
        assert rr.is_disk_full(outer)
    assert not rr.is_disk_full(RuntimeError("No space left on device"))


@pytest.mark.parametrize("ret,expected", [
    (None, ("success", None)),
    ({"status": "ok"}, ("success", None)),          # the Pro stream's own vocabulary: not ours
    ({"status": "degraded", "message": "x"}, ("degraded", "x")),
    ({"status": "skipped_paused", "message": "p"}, ("skipped_paused", "p")),
    ({"status": "failed", "message": "no"}, ("success", None)),  # a job cannot declare 'failed'
    ([1, 2], ("success", None)),
])
def test_result_status_convention(ret, expected):
    assert rr.result_status(ret) == expected


# --- unit: recording never breaks a job ---------------------------------------------------------

async def test_recording_failure_does_not_stop_the_job(monkeypatch, caplog):
    class _Broken:
        def AsyncSessionLocal(self):
            raise RuntimeError("db down postgres://u:p@host/db")

    monkeypatch.setattr(rr, "dbm", _Broken())
    ran = []

    async def job():
        ran.append(True)
        return None

    with caplog.at_level(logging.WARNING, logger=rr.logger.name):
        await ms.safe_run(_name("recfail"), job)  # must not raise
    assert ran == [True]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("job_runs: could not record" in m for m in warnings)
    assert not any("u:p@host" in m for m in warnings)  # the scrubber covers the log line too


# --- unit: ingest reports failed sources ---------------------------------------------------------

async def test_ingest_returns_degraded_with_failed_sources(monkeypatch):
    import jobs.ingest_job as ij

    sources = [{"source_id": "ok_feed"}, {"source_id": "bad_feed"}, {"source_id": "full_disk_feed"}]
    monkeypatch.setattr(ij, "load_sources_from_yaml", lambda: sources)

    async def _sync(db, srcs):
        return None

    async def _fetch(src):
        if src["source_id"] == "bad_feed":
            raise ValueError("feed broke")
        return [{"title": "t"}]

    async def _ingest(db, src, items):
        if src["source_id"] == "full_disk_feed":
            raise _DiskFull("could not extend file")
        return 1

    monkeypatch.setattr(ij, "sync_sources_to_db", _sync)
    monkeypatch.setattr(ij, "fetch_feed", _fetch)
    monkeypatch.setattr(ij, "ingest_feed_for_source", _ingest)

    class _DB:
        async def commit(self): pass
        async def rollback(self): pass
        def expire_all(self): pass

    result = await ij.run_ingest(_DB())
    assert result["status"] == "degraded"
    msg = result["message"]
    assert msg.startswith("disk_full: SQLSTATE 53100")
    assert "2 of 3 sources failed" in msg and "bad_feed (ValueError)" in msg and "full_disk_feed (_DiskFull)" in msg
    assert "total new rows=1" in msg


# --- unit: feature switches are real reads ------------------------------------------------------

def _code_reads():
    files = subprocess.run(["git", "ls-files", "jobs", "processor", "analysis", "llm", "reports",
                            "data_sources", "config", "db"], capture_output=True, text=True, cwd=ROOT).stdout.split()
    reads = []
    for f in files:
        if not f.endswith(".py"):
            continue
        for i, line in enumerate((ROOT / f).read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if f == "jobs/main_scheduler.py" and line.lstrip().startswith('("'):
                continue  # the registry itself
            for m in re.finditer(r"""os\.(?:getenv|environ\.get)\(\s*["']([A-Z0-9_]+)["']\s*(?:,\s*["']([^"']*)["'])?""", line):
                reads.append((m.group(1), m.group(2), f, i))
    return reads


def test_every_feature_switch_is_read_with_the_same_default():
    reads = _code_reads()
    for name, default, parse in ms.FEATURE_SWITCHES:
        sites = [r for r in reads if r[0] == name]
        assert sites, f"{name} is in FEATURE_SWITCHES but nothing reads it"
        if default is None:
            assert any(r[1] is None for r in sites), f"{name}: a read without default expected"
        else:
            assert any(r[1] == default for r in sites), f"{name}: no read site uses default {default!r}: {sites}"


def test_switch_line_lists_every_switch_and_no_secrets(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM_IMPORTANCE", "TRUE")
    monkeypatch.delenv("SCHEDULER_PAUSED", raising=False)
    line = ms.feature_switch_line()
    for name, _, _ in ms.FEATURE_SWITCHES:
        assert f" {name}=" in line
    assert "ENABLE_LLM_IMPORTANCE=True(set)" in line          # parsed the way alert_manager parses it
    assert "SCHEDULER_PAUSED=False(default)" in line
    assert "PRO_DISABLE_DUPLICATE_GUARDS=" in line
    for dead in ("ENABLE_PRO_AUTOMATION=", "PRO_AUTOMATION_DRY_RUN=", "PRO_REGEN_AFTER_SYNC="):
        assert dead not in line                                # never read on the scheduler's path (§12.77(c))
    assert not re.search(r"KEY|SECRET|TOKEN|PASSWORD|_URL", line)


# --- database: the records themselves ------------------------------------------------------------

async def test_success_is_recorded(db_client):
    name = _name("ok")

    async def job():
        return None

    try:
        await ms.safe_run(name, job)
        rows = await _rows(name)
        assert [r.status for r in rows] == ["success"]
        assert rows[0].finished_at is not None and rows[0].finished_at >= rows[0].started_at
        assert rows[0].error_message is None
    finally:
        await _cleanup(name)


async def test_raising_job_is_recorded_failed_and_safe_run_still_swallows(db_client):
    name = _name("fail")

    async def job():
        raise ValueError("it broke")

    try:
        await ms.safe_run(name, job)  # safe_run's swallow-and-continue is unchanged
        rows = await _rows(name)
        assert [r.status for r in rows] == ["failed"]
        assert rows[0].error_message == "ValueError: it broke"
    finally:
        await _cleanup(name)


async def test_degraded_return_is_recorded(db_client):
    name = _name("deg")

    async def job():
        return {"status": "degraded", "message": "2 of 5 things failed"}

    try:
        await ms.safe_run(name, job)
        rows = await _rows(name)
        assert [(r.status, r.error_message) for r in rows] == [("degraded", "2 of 5 things failed")]
    finally:
        await _cleanup(name)


@pytest.mark.parametrize("exc,expected_prefix", [
    (_DiskFull("DiskFullError: could not extend file"), "disk_full: SQLSTATE 53100"),
    (OSError("No space left on device"), "disk_full: matched by message text"),
])
async def test_pipeline_disk_full_is_degraded_and_names_disk_full(db_client, monkeypatch, exc, expected_prefix):
    name = _name("disk")

    async def _ingest(session):
        raise exc

    monkeypatch.setattr(ms, "run_ingest", _ingest)
    monkeypatch.setattr(ms, "AsyncSessionLocal", _dummy_session)
    try:
        await ms.safe_run(name, ms.pipeline_full_processing)
        rows = await _rows(name)
        assert [r.status for r in rows] == ["degraded"]
        assert rows[0].error_message.startswith(expected_prefix)
    finally:
        await _cleanup(name)


async def test_pipeline_pending_rollback_is_degraded(db_client, monkeypatch):
    name = _name("pr")

    async def _ingest(session):
        raise RuntimeError("PendingRollbackError: this session is in a rollback state")

    monkeypatch.setattr(ms, "run_ingest", _ingest)
    monkeypatch.setattr(ms, "AsyncSessionLocal", _dummy_session)
    try:
        await ms.safe_run(name, ms.pipeline_full_processing)
        rows = await _rows(name)
        assert [r.status for r in rows] == ["degraded"]
        assert rows[0].error_message.startswith("pending_rollback:")
    finally:
        await _cleanup(name)


async def test_paused_pipeline_is_skipped_paused(db_client, monkeypatch):
    name = _name("paused")
    monkeypatch.setenv("SCHEDULER_PAUSED", "true")
    try:
        await ms.safe_run(name, ms.pipeline_full_processing)
        rows = await _rows(name)
        assert [(r.status, r.error_message) for r in rows] == [("skipped_paused", "SCHEDULER_PAUSED=true")]
    finally:
        await _cleanup(name)


async def test_overlap_skip_is_recorded(db_client):
    name = _name("overlap")
    ran = []

    async def job():
        ran.append(True)

    ms._running_tasks.add(name)
    try:
        await ms.safe_run(name, job)
        assert ran == []
        rows = await _rows(name)
        assert [r.status for r in rows] == ["skipped_overlap"]
        assert rows[0].finished_at is not None
    finally:
        ms._running_tasks.discard(name)
        await _cleanup(name)


async def test_record_survives_the_jobs_own_rollback(db_client):
    name = _name("rollback")
    metric_key = f"test_jr_metric_{uuid.uuid4().hex[:8]}"

    async def job():
        async with dbm.AsyncSessionLocal() as s:
            s.add(SystemMetric(metric_key=metric_key, metric_value="should vanish"))
            await s.flush()                     # written inside the job's transaction...
            raise RuntimeError("job failed after writing")  # ...and rolled back with it

    try:
        await ms.safe_run(name, job)
        async with dbm.AsyncSessionLocal() as s:
            metric = (await s.execute(select(SystemMetric).where(SystemMetric.metric_key == metric_key))).scalar_one_or_none()
        assert metric is None                   # the job's work was rolled back
        rows = await _rows(name)
        assert [r.status for r in rows] == ["failed"]  # its record was not
    finally:
        await _cleanup(name)


async def test_planted_key_never_reaches_the_row(db_client):
    name = _name("scrub")

    async def job():
        raise RuntimeError("stripe said no to sk_live_PLANTED0123456789 via postgresql://admin:hunter2@db/prod")

    try:
        await ms.safe_run(name, job)
        rows = await _rows(name)
        msg = rows[0].error_message
        assert rows[0].status == "failed"
        assert "PLANTED0123456789" not in msg and "hunter2" not in msg
        assert "sk_live_[redacted]" in msg
    finally:
        await _cleanup(name)


async def test_startup_steps_are_recorded(db_client, monkeypatch):
    started = datetime.now(timezone.utc)

    async def _pipeline():
        return None

    async def _pro():
        return {"inserted_count": 0, "status": "ok", "elapsed_sec": 0}

    async def _noop(session):
        return None

    monkeypatch.setattr(ms, "pipeline_full_processing", _pipeline)
    monkeypatch.setattr(ms, "pro_automation_wrapper", _pro)
    monkeypatch.setattr(ms, "run_db_size_check", _noop)
    monkeypatch.setattr(ms, "enforce_metadata_limits", _noop)
    monkeypatch.setattr(ms, "audit_metadata_sizes", _noop)
    monkeypatch.setattr(ms, "AsyncSessionLocal", _dummy_session)
    monkeypatch.delenv("SCHEDULER_SKIP_STARTUP_PIPELINE", raising=False)
    monkeypatch.setenv("PRO_AUTOMATION_ON_STARTUP", "true")

    await ms.run_startup_checks()
    async with dbm.AsyncSessionLocal() as s:
        rows = (await s.execute(select(JobRun).where(
            JobRun.job_name.in_(["startup_pipeline", "startup_pro_compile"]),
            JobRun.started_at >= started))).scalars().all()
        try:
            assert sorted((r.job_name, r.status) for r in rows) == [
                ("startup_pipeline", "success"), ("startup_pro_compile", "success")]
        finally:
            await s.execute(delete(JobRun).where(JobRun.id.in_([r.id for r in rows])))
            await s.commit()


async def test_retention_deletes_only_rows_older_than_30_days(db_client):
    name = _name("ret")
    now = datetime.now(timezone.utc)
    old_id, new_id = uuid.uuid4(), uuid.uuid4()
    async with dbm.AsyncSessionLocal() as s:
        s.add_all([
            JobRun(id=old_id, job_name=name, status="success", started_at=now - timedelta(days=31)),
            JobRun(id=new_id, job_name=name, status="success", started_at=now - timedelta(days=29)),
        ])
        await s.commit()
    try:
        async with dbm.AsyncSessionLocal() as s:
            deleted = await purge_old_job_runs(s)
        assert deleted >= 1
        assert [r.id for r in await _rows(name)] == [new_id]
    finally:
        await _cleanup(name)


async def test_check_job_runs_report(db_client):
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_job_runs", ROOT / "scripts" / "check_job_runs.py")
    cjr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cjr)

    now = datetime.now(timezone.utc)
    ids = []
    async with dbm.AsyncSessionLocal() as s:
        for job, status, ago in [("pipeline", "success", 2), ("pipeline", "failed", 3),
                                  ("pipeline", "running", 60), ("cleanup", "degraded", 10)]:
            rid = uuid.uuid4()
            ids.append(rid)
            s.add(JobRun(id=rid, job_name=job, status=status, started_at=now - timedelta(minutes=ago)))
        await s.commit()
    try:
        async with dbm.engine.connect() as conn:
            await conn.execute(text("set transaction read only"))
            jobs, _events = await cjr.build_report(conn)
        by = {r["job_name"]: r for r in jobs}
        assert by["pipeline"]["overdue"] is False and by["pipeline"]["failed_24h"] >= 1
        assert by["pipeline"]["orphaned"] >= 1            # running for 60 min > 2 x 15 min
        assert by["cleanup"]["overdue"] is True           # degraded does not count as success
        assert by["cleanup"]["degraded_24h"] >= 1
    finally:
        async with dbm.AsyncSessionLocal() as s:
            await s.execute(delete(JobRun).where(JobRun.id.in_(ids)))
            await s.commit()
