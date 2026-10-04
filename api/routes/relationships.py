"""Relationship graph — read-only API over the vault's relationship_graph.json.

The vault writes it with _bridge/export_relationships.py and it is copied here as a STATIC FILE:
no load job, no DB table, no join. That is deliberate — the file is reference data whose whole
value is that every edge carries the provenance the vault authored for it.

★ OPEN TO ALL TIERS, MASKED BY TIER. The free tier gets the STRUCTURE (who relates to whom, and
how) and the search surface. Pro gets the structure plus the PROVENANCE — weight, unit,
weight_source, verify_status, source, retrieved, as_of, materiality, desc, basis_short — which is
the part that took the work and is the part worth paying for.

★ The mask OMITS fields rather than nulling them. A free response must not look like a Pro
response with gaps: a missing `weight_source` key means "not served at this tier", whereas a
present-but-null one means "this edge has no recorded source", and those are different claims.
The vault spends its time keeping exactly that distinction (CLAUDE.md §2, §5).

★ impact_score, order-3 and coordinates are NOT in this file and must not be joined to it.
See the vault's CLAUDE.md §5 and _ARTIFACT_MANIFEST.md §9.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from api.gating import get_effective_tier, TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE
from api.auth import get_optional_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Relationships"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
GRAPH_PATH = BASE_DIR / "data" / "scenarios" / "relationship_graph.json"

_FULL_TIERS = {TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE}
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}

# Free-tier field masks. Structure and search surface only.
_FREE_NODE_KEYS = ("id", "type", "domain", "country", "title", "aliases", "listing")
_FREE_EDGE_KEYS = ("s", "t", "type", "role")

# In-process cache — the file is static between deploys. Keyed by mtime_ns so a redeploy that
# replaces the file is picked up without a restart.
_CACHE: Dict[str, Any] = {"mtime": None, "full": None, "free": None}


def _mask_free(full: Dict[str, Any]) -> Dict[str, Any]:
    meta = dict(full.get("meta") or {})
    meta["tier"] = "free"
    meta["masked"] = True
    meta["note"] = (
        "FREE tier: structure only. Per-edge provenance (weight, unit, weight_source, "
        "verify_status, source, retrieved, as_of, materiality, desc, basis_short) is omitted, "
        "not nulled — an absent key means 'not served at this tier', which is a different claim "
        "from a present null. " + str(meta.get("note", ""))
    )
    for k in ("weight_source_counts", "verify_status_counts", "weight_states"):
        meta.pop(k, None)
    return {
        "meta": meta,
        "nodes": [{k: n[k] for k in _FREE_NODE_KEYS if k in n} for n in full.get("nodes", [])],
        "edges": [{k: e[k] for k in _FREE_EDGE_KEYS if k in e} for e in full.get("edges", [])],
    }


def _load() -> Dict[str, Any]:
    if not GRAPH_PATH.exists():
        logger.error("relationship_graph.json missing at %s", GRAPH_PATH)
        raise HTTPException(status_code=503, detail="Relationship graph not available.")
    mtime = GRAPH_PATH.stat().st_mtime_ns
    if _CACHE["mtime"] != mtime:
        with open(GRAPH_PATH, "r", encoding="utf-8") as f:
            full = json.load(f)
        full.setdefault("meta", {})["tier"] = "pro"
        _CACHE.update({"mtime": mtime, "full": full, "free": _mask_free(full)})
        logger.info(
            "relationship_graph loaded: %d nodes / %d edges",
            len(full.get("nodes", [])), len(full.get("edges", [])),
        )
    return _CACHE


async def _get_current_tier(
    current_user: Optional[Any] = Depends(get_optional_current_user),
) -> str:
    user = None
    if current_user is not None:
        user = current_user[0] if isinstance(current_user, tuple) else current_user
    return await get_effective_tier(user)


@router.get("/relationships")
async def get_relationship_graph(tier: str = Depends(_get_current_tier)):
    """303 node objects + 1535 edges. Full provenance on Pro; structure only on free."""
    cache = _load()
    payload = cache["full"] if tier in _FULL_TIERS else cache["free"]
    return Response(
        content=json.dumps(payload, ensure_ascii=False),
        media_type="application/json",
        headers=_NO_STORE_HEADERS,
    )
