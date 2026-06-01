"""
Phase 7.2 — Integration tests for the dedicated Spatial Engine API.

Hit `pro_spatial_router` over the FastAPI ASGI transport (no real socket),
asserting both the response contract and the absence of the
`RuntimeError: Event loop is closed` artifact that the legacy TestClient
+ asyncpg combo used to raise on consecutive runs.

These tests pass without any database fixture data — endpoints return
empty payloads when the spatial tables are unseeded, which is itself a
valid contract (status 200, `nodes=[]`, etc.).
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.asyncio


async def test_global_spatial_contagion_returns_well_formed_json(client):
    resp = await client.get("/api/pro/domains/global/spatial-contagion")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    # Always-present envelope fields
    assert body["domain_id"] == "global"
    assert isinstance(body["nodes"], list)
    assert isinstance(body["edges"], list)
    assert "epicenter_impact_score" in body
    assert "edge_intensity" in body
    assert body["schema_version"].startswith("spatial_engine")


async def test_global_spatial_contagion_node_shape_when_populated(client):
    """When the seed has run, every node carries the fields the frontend
    reads to drive the criticality filter + critical-label TextLayer."""
    resp = await client.get("/api/pro/domains/global/spatial-contagion")
    assert resp.status_code == 200
    body = resp.json()
    for node in body["nodes"]:
        assert {"id", "name", "lat", "lon", "impact_score", "type"} <= node.keys()
        assert node["type"] in {"epicenter", "affected"}
        assert isinstance(node["impact_score"], (int, float))
    for edge in body["edges"]:
        assert {"source_lat", "source_lon", "target_lat", "target_lon",
                "intensity", "target_order"} <= edge.keys()
        assert edge["target_order"] in {1, 2, 3}


async def test_fragility_history_envelope(client):
    resp = await client.get("/api/pro/domains/energy/fragility-history?days=1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["domain_id"] == "energy"
    assert body["days"] == 1
    assert isinstance(body["series"], list)
    assert "warning_count" in body
    # latest_spatial_contagion is null OR a well-formed payload
    latest = body.get("latest_spatial_contagion")
    if latest is not None:
        assert isinstance(latest["nodes"], list)
        assert isinstance(latest["edges"], list)


async def test_fragility_history_rejects_bad_days(client):
    """days > _MAX_HISTORY_DAYS (90) must 4xx — protects against table sweep."""
    resp = await client.get("/api/pro/domains/energy/fragility-history?days=9999")
    assert resp.status_code in (400, 422)


async def test_consecutive_polling_does_not_leak_loop(client):
    """The original bug: 'Event loop is closed' on the 2nd or 3rd call.
    Hit the endpoint several times in a tight loop. If the session-scoped
    loop fixture works, all of these succeed; if not, this test fails."""
    for _ in range(6):
        resp = await client.get("/api/pro/domains/global/spatial-contagion")
        assert resp.status_code == 200
