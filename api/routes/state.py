"""
api/routes/state.py

External Alert Stream API — GET /api/state

Public, read-only, unauthenticated endpoint designed for external
media art integrations and third-party polling clients.

Contract
--------
GET /api/state[?since=<ISO-8601>&limit=<int>]

Response shape:
  {
    "entropy":     float,           # system-wide tension score [0.0, 1.0]
    "diff":        [ AlertItem ],   # alerts created after `since` (all if omitted)
    "last_cursor": str,             # ISO-8601 — pass as `since` on next poll
  }

AlertItem shape:
  {
    "id":        str,               # UUID of AlertLog row
    "timestamp": str,               # ISO-8601 of triggered_at
    "lat":       float | null,      # location_lat (null when unresolved)
    "lon":       float | null,      # location_lng renamed to lon
    "severity":  "crit"|"elev"|"watch",
    "domain":    str,               # short domain label (energy, market, …)
  }

CORS
----
Access-Control-Allow-Origin: * is set as a per-response header only.
The global CORSMiddleware in api/main.py is NOT modified (it uses
allow_credentials=True which is incompatible with a wildcard origin globally).

Polling Guidance
----------------
Recommended poll interval: 10 s.
Clients MUST advance their `since` cursor to the returned `last_cursor`
value to avoid re-fetching already-seen alerts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import asc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from analysis.market_entropy import compute_market_entropy
from analysis.pro_domain_config import infer_domain_from_topic
from db.database import get_db
from db.models import AlertLog

logger = logging.getLogger(__name__)

router = APIRouter(tags=["state"])

# ── Domain short-label mapping ────────────────────────────────────────────────
# Maps the 6 canonical domain IDs returned by infer_domain_from_topic() to the
# abbreviated labels expected by the external art installation.
_DOMAIN_SHORT_MAP: dict[str, str] = {
    "energy_resource_risk":          "energy",
    "global_market_intelligence":    "market",
    "ai_semiconductor_intelligence": "ai_semi",
    "defense_technology":            "defense",
    "supply_chain_intelligence":     "supply_chain",
    "crypto_geopolitics":            "crypto",
}

# ── Severity abbreviation mapping ─────────────────────────────────────────────
# AlertLog.severity stores full strings; the external API uses 3-char codes.
_SEV_MAP: dict[str, str] = {
    "critical": "crit",
    "elevated": "elev",
    "watch":    "watch",
}


def _to_short_domain(topic: str | None) -> str:
    """Resolve an AlertLog.topic string to a short domain label."""
    full = infer_domain_from_topic(topic or "")
    return _DOMAIN_SHORT_MAP.get(full, "global")


def _serialise_alert(a: AlertLog) -> dict:
    """Serialise one AlertLog row to the external AlertItem schema."""
    return {
        "id":        str(a.id),
        "timestamp": a.triggered_at.isoformat(),
        "lat":       a.location_lat,          # float or None
        "lon":       a.location_lng,          # renamed from DB column 'lng'
        "severity":  _SEV_MAP.get(a.severity or "", "watch"),
        "domain":    _to_short_domain(a.topic),
    }


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/state")
async def get_state(
    response: Response,
    since: Optional[datetime] = Query(
        None,
        description=(
            "ISO-8601 cursor timestamp. Only alerts with triggered_at > since "
            "are returned. Omit for the initial fetch."
        ),
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description="Maximum number of diff alerts to return per poll (1–200).",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Public state snapshot for external media art integration.

    Returns the system-wide entropy score and a cursor-based diff of
    recent alerts, suitable for 10-second polling intervals.
    """
    # ── 1. Entropy — 24-hour Shannon entropy over 6 strategic domains ─────────
    try:
        entropy_payload = await compute_market_entropy(db)
        entropy: float = float(entropy_payload.get("entropy_normalised", 0.0))
    except Exception as exc:
        logger.warning("compute_market_entropy failed: %s", exc, exc_info=True)
        entropy = 0.0

    # ── 2. Diff query — triggered_at > since, suppressed == False ─────────────
    stmt = (
        select(AlertLog)
        .where(AlertLog.suppressed == False)  # noqa: E712  — exclude merged dupes
    )

    if since is not None:
        # Normalise to UTC-aware before comparison to avoid tz-naive mismatch
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        stmt = stmt.where(AlertLog.triggered_at > since)  # strict > (cursor exclusivity)

    stmt = stmt.order_by(asc(AlertLog.triggered_at)).limit(limit)

    try:
        alerts = list((await db.execute(stmt)).scalars().all())
    except Exception as exc:
        logger.error("Alert diff query failed: %s", exc, exc_info=True)
        alerts = []

    diff = [_serialise_alert(a) for a in alerts]

    # Advance the cursor to the newest returned alert's timestamp.
    # If no alerts returned, preserve the caller's cursor (or now as fallback).
    if alerts:
        last_cursor = alerts[-1].triggered_at.isoformat()
    elif since is not None:
        last_cursor = since.isoformat()
    else:
        last_cursor = datetime.now(timezone.utc).isoformat()

    # ── 3. Response headers ───────────────────────────────────────────────────
    # Cache-Control: force clients and proxies to always fetch fresh state.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    # CORS: wildcard for unauthenticated public polling clients.
    # NOTE: This is intentionally set here, NOT in the global CORSMiddleware,
    # because that middleware uses allow_credentials=True which is incompatible
    # with a wildcard origin. Only this endpoint carries the open CORS policy.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"

    return {
        "entropy":     round(entropy, 4),
        "diff":        diff,
        "last_cursor": last_cursor,
    }
