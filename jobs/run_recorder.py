"""Run records for scheduled jobs: one `job_runs` row per run (job_runs v1, vault audit §12.86(b)).

WHY. Before this, a scheduled job's only trace was a log line. safe_run logged "Finished" whether
the job worked, swallowed its own error, returned early, or was skipped; nothing was stored, so a
job that failed twice a day for five months (entity_lifecycle, §12.78) was noticed by no one.

HOW A RECORD SURVIVES THE JOB. Each write uses its OWN short session and commits at once:
  * a 'running' row is inserted and committed BEFORE the job starts;
  * the outcome is written in a second short session AFTER it returns or raises.
The job's own session is never touched, so a rollback inside the job cannot erase its record
(the trap `stripe_events` falls into: its record shares the failing transaction, §12.80).

RECORDING NEVER BREAKS A JOB. Every write is wrapped: a failure is logged at WARNING and swallowed.
If the 'running' insert failed, the outcome is still attempted as a complete row.

RETURN-VALUE CONVENTION. A job that returns a dict whose "status" is one of RESULT_STATUSES gets
that status and its "message" recorded. Anything else, including None, is recorded as 'success'.

The session factory is looked up at call time (db.database.AsyncSessionLocal), not imported, so
tests that rebind it to a test engine are honoured.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Tuple

import db.database as dbm
from db.models import JobRun

logger = logging.getLogger(__name__)

STATUSES = ("running", "success", "failed", "degraded", "skipped_overlap", "skipped_paused", "cancelled")
RESULT_STATUSES = ("success", "degraded", "skipped_paused")
MAX_MESSAGE_CHARS = 2000
DISK_FULL_SQLSTATE = "53100"

# Secrets that can appear in an exception's text. Scrubbed before anything is stored.
_SCRUBBERS = (
    (re.compile(r"\b(sk|rk)_(live|test)_[A-Za-z0-9]+"), r"\1_\2_[redacted]"),
    (re.compile(r"\bwhsec_[A-Za-z0-9]+"), "whsec_[redacted]"),
    (re.compile(r"\bpostgres(?:ql)?(?:\+[a-z0-9]+)?://\S+", re.IGNORECASE), "postgres://[redacted]"),
    (re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE), "Bearer [redacted]"),
)


def scrub(text: Optional[str]) -> Optional[str]:
    """Remove known secret shapes, then truncate. Scrubbing runs first, so truncation can never
    leave the start of a key behind."""
    if text is None:
        return None
    out = str(text)
    for pattern, replacement in _SCRUBBERS:
        out = pattern.sub(replacement, out)
    if len(out) > MAX_MESSAGE_CHARS:
        out = out[: MAX_MESSAGE_CHARS - 15] + " …[truncated]"
    return out


def is_disk_full(exc: BaseException) -> bool:
    """True when the exception, or anything it wraps, carries SQLSTATE 53100 (disk_full).
    Walks SQLAlchemy's .orig and the __cause__/__context__ chain; asyncpg exposes .sqlstate,
    psycopg2 .pgcode."""
    seen = set()
    stack = [exc]
    while stack:
        e = stack.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        if getattr(e, "sqlstate", None) == DISK_FULL_SQLSTATE or getattr(e, "pgcode", None) == DISK_FULL_SQLSTATE:
            return True
        stack.extend([getattr(e, "orig", None), e.__cause__, e.__context__])
    return False


def result_status(ret: Any) -> Tuple[str, Optional[str]]:
    if isinstance(ret, dict) and ret.get("status") in RESULT_STATUSES:
        msg = ret.get("message")
        return ret["status"], (None if msg is None else str(msg))
    return "success", None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _insert(job_name: str, status: str, started_at: datetime,
                  finished_at: Optional[datetime] = None, message: Optional[str] = None) -> Optional[uuid.UUID]:
    run_id = uuid.uuid4()  # job_runs.id has no server default in production (§12.86(b))
    try:
        async with dbm.AsyncSessionLocal() as session:
            session.add(JobRun(id=run_id, job_name=job_name, status=status, started_at=started_at,
                               finished_at=finished_at, error_message=scrub(message)))
            await session.commit()
        return run_id
    except Exception as e:  # never let recording break a job
        logger.warning("job_runs: could not record %s=%s: %s", job_name, status, scrub(f"{type(e).__name__}: {e}"))
        return None


async def _finish(run_id: Optional[uuid.UUID], job_name: str, status: str, started_at: datetime,
                  message: Optional[str]) -> None:
    finished_at = _now()
    if run_id is None:
        # The 'running' insert failed. Still try to leave the outcome behind.
        await _insert(job_name, status, started_at, finished_at, message)
        return
    try:
        async with dbm.AsyncSessionLocal() as session:
            row = await session.get(JobRun, run_id)
            if row is None:
                raise LookupError(f"job_runs row {run_id} not found")
            row.status = status
            row.finished_at = finished_at
            row.error_message = scrub(message)
            await session.commit()
    except Exception as e:
        logger.warning("job_runs: could not finish %s=%s: %s", job_name, status, scrub(f"{type(e).__name__}: {e}"))


async def record_skip(job_name: str, status: str, message: Optional[str] = None) -> None:
    """A run that did not start (an overlap skip). One complete row."""
    t = _now()
    await _insert(job_name, status, t, t, message)


async def run_recorded(job_name: str, coro_func: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
    """Run `coro_func` with a job_runs record around it. Re-raises whatever the job raises, so the
    caller's behaviour (safe_run's FATAL log, main()'s self-healing) is unchanged."""
    started_at = _now()
    run_id = await _insert(job_name, "running", started_at)
    try:
        ret = await coro_func(*args, **kwargs)
    except asyncio.CancelledError:
        # A deploy or shutdown is stopping the process. Best effort: the write itself may be
        # cancelled; a row left 'running' is reported as orphaned by scripts/check_job_runs.py.
        try:
            await asyncio.shield(_finish(run_id, job_name, "cancelled", started_at, "cancelled"))
        except BaseException:
            pass
        raise
    except Exception as e:
        await _finish(run_id, job_name, "failed", started_at, f"{type(e).__name__}: {e}")
        raise
    status, message = result_status(ret)
    await _finish(run_id, job_name, status, started_at, message)
    return ret
