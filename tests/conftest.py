"""
Phase 7.2 — Session-scoped async fixtures for the test suite.

The TestClient-based integration tests that pre-dated this file repeatedly
raised `RuntimeError: Event loop is closed` because pytest-asyncio created
a fresh event loop per test, but asyncpg's pooled connections (and the
SQLAlchemy AsyncEngine that owns them) survived across tests and tried
to schedule callbacks on the now-dead loop.

Three changes fix it:

  1. `pytest.ini` sets `asyncio_default_fixture_loop_scope = session` so
     a single loop owns the whole run.
  2. The `client` fixture below uses `httpx.AsyncClient` over the FastAPI
     ASGI transport — no real socket, no per-test cleanup races.
  3. We swap the production DB engine's pool for `NullPool` *for the test
     session only*, so each request opens its own asyncpg connection and
     no statement-cache state leaks between tests (the secondary
     `InterfaceError: another operation is in progress` symptom).

Tests pull `client` in and `await client.get(...)`; nothing else is needed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import AsyncIterator

import pytest_asyncio

# Ensure the project root is on sys.path so `api.main`, `db`, etc. are
# importable when pytest is invoked from any directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# Ensure the dev tier override fires for tests that hit gated routes.
os.environ.setdefault("ENV", "development")
os.environ.setdefault("ALLOW_DEV_TIER_OVERRIDE", "true")
os.environ.setdefault("LOCAL_DEV_TIER", "pro")


@pytest_asyncio.fixture(scope="session")
async def _test_engine():
    """Rebind the AsyncSessionLocal factory to a NullPool-backed engine for
    the duration of the test session, then restore the original on teardown.

    NullPool guarantees a fresh asyncpg connection per request, so prepared
    statement caches can't outlive a single test.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
    from sqlalchemy.pool import NullPool

    from db import database as db_module
    from db.database import get_engine_args

    db_url, connect_args, _ = get_engine_args(use_asyncpg=True)
    test_engine = create_async_engine(
        db_url,
        echo=False,
        connect_args=connect_args,
        poolclass=NullPool,
    )
    test_session = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False,
    )

    original_engine = db_module.engine
    original_factory = db_module.AsyncSessionLocal
    db_module.engine = test_engine
    db_module.AsyncSessionLocal = test_session

    try:
        yield test_engine
    finally:
        await test_engine.dispose()
        db_module.engine = original_engine
        db_module.AsyncSessionLocal = original_factory


@pytest_asyncio.fixture(scope="session")
async def client(_test_engine) -> AsyncIterator["object"]:
    """Async HTTP client bound directly to the FastAPI app via ASGI.

    Session-scoped so the underlying engine isn't torn down between tests.
    """
    # Imported lazily so module collection doesn't touch the DB engine
    # unless a test actually requests this fixture.
    import httpx
    # Re-assert the project root on sys.path — pytest-asyncio session-scope
    # fixtures run inside a thread-local event loop that may not inherit the
    # sys.path mutation from the module-level block above.
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    from api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as ac:
        yield ac
