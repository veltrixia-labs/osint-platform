"""Pro Relationship Graph — read-only API over the vault's relationship_graph.json.

The vault writes it with _bridge/export_relationships.py and it is copied here as a STATIC FILE:
no load job, no DB table, no join. That is deliberate — the file is reference data whose whole
value is that every edge carries the provenance the vault authored for it (weight_source,
verify_status, source URL, retrieved, as_of, basis_short).

★ impact_score, order-3 and coordinates are NOT in this file and must not be joined to it. Those
belong to the chokepoint-scenario surface (the five payloads + impact_roster), which is unchanged.
See the vault's CLAUDE.md §5 and _ARTIFACT_MANIFEST.md §9.
"""
import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from api.gating import get_effective_tier, TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE
from api.auth import get_optional_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pro", tags=["Pro Relationships"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
GRAPH_PATH = BASE_DIR / "data" / "scenarios" / "relationship_graph.json"

_ALLOWED_TIERS = {TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE}
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


async def _get_current_tier(
    current_user: Optional[Any] = Depends(get_optional_current_user),
) -> str:
    user = None
    if current_user is not None:
        user = current_user[0] if isinstance(current_user, tuple) else current_user
    return await get_effective_tier(user)


@router.get("/relationships")
async def get_relationship_graph(tier: str = Depends(_get_current_tier)):
    """The full relationship graph: 303 node objects + 1535 edges with provenance."""
    if tier not in _ALLOWED_TIERS:
        raise HTTPException(status_code=403, detail="Pro tier required for the relationship graph.")
    if not GRAPH_PATH.exists():
        logger.error("relationship_graph.json missing at %s", GRAPH_PATH)
        raise HTTPException(status_code=503, detail="Relationship graph not available.")
    with open(GRAPH_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return Response(
        content=json.dumps(payload, ensure_ascii=False),
        media_type="application/json",
        headers=_NO_STORE_HEADERS,
    )
