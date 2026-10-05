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
import re
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from api.gating import get_effective_tier, TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE
from api.auth import get_optional_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Relationships"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
GRAPH_PATH = BASE_DIR / "data" / "scenarios" / "relationship_graph.json"
COORDS_PATH = BASE_DIR / "data" / "scenarios" / "node_coordinates.json"

_FULL_TIERS = {TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE}
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}

# ─── English-only projection ──────────────────────────────────────────────────
# The product surface is English. The vault is authored bilingually — aliases, titles, node
# role one-liners and edge desc/basis prose are frequently Japanese — so the projection happens
# HERE rather than in the client: a client-side filter still ships the CJK over the wire, where
# anything that reads the response (a cache, a log, a future consumer) sees it.
#
# ★ It DROPS fields rather than transliterating them. A romanised Japanese title is a new string
#   nobody authored and nobody verified; the vault's discipline is that a value either has a
#   source or is absent. The client falls back to humanize(id), which is derived from the node's
#   own identifier and asserts nothing.
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_LEAD_TAG = re.compile(r"^((?:\[[^\]]*\])+)")


def _has_cjk(v: Any) -> bool:
    return isinstance(v, str) and bool(_CJK.search(v))


def _englishise(full: Dict[str, Any]) -> Dict[str, Any]:
    """Strip every CJK-bearing string from the payload. Returns a NEW dict; counts are logged."""
    dropped = {"aliases": 0, "title": 0, "role": 0, "desc": 0, "basis_short_reduced": 0,
               "basis_short_dropped": 0}
    nodes = []
    for n in full.get("nodes", []):
        m = dict(n)
        if "aliases" in m:
            keep = [a for a in (m["aliases"] or []) if not _has_cjk(a)]
            dropped["aliases"] += len(m["aliases"] or []) - len(keep)
            m["aliases"] = keep
        if _has_cjk(m.get("title")):
            m.pop("title", None); dropped["title"] += 1
        if _has_cjk(m.get("role")):
            m.pop("role", None); dropped["role"] += 1
        nodes.append(m)
    edges = []
    for e in full.get("edges", []):
        m = dict(e)
        if "desc" in m:                      # never served, either tier
            m.pop("desc", None); dropped["desc"] += 1
        bs = m.get("basis_short")
        if _has_cjk(bs):
            tag = _LEAD_TAG.match(bs or "")
            if tag:
                m["basis_short"] = tag.group(1); dropped["basis_short_reduced"] += 1
            else:
                m.pop("basis_short", None); dropped["basis_short_dropped"] += 1
        edges.append(m)
    out = {"meta": dict(full.get("meta") or {}), "nodes": nodes, "edges": edges}
    out["meta"]["language"] = "en"
    out["meta"]["english_only"] = True
    logger.info("relationship_graph english projection: %s", dropped)
    _CACHE["dropped"] = dropped          # kept on the cache for diagnostics, NOT in the response
    return out


# Free-tier field masks. Structure and search surface only.
_FREE_NODE_KEYS = ("id", "type", "domain", "country", "title", "aliases", "listing")
_FREE_EDGE_KEYS = ("s", "t", "type", "role")

# In-process cache — the file is static between deploys. Keyed by mtime_ns so a redeploy that
# replaces the file is picked up without a restart.
_CACHE: Dict[str, Any] = {"mtime": None, "full": None, "free": None, "dropped": None}


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
            raw = json.load(f)
        full = _englishise(raw)              # ★ English projection BEFORE the tier mask
        full["meta"]["tier"] = "pro"
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


def _require_pro(tier: str, detail: str) -> None:
    """Mirrors impact_roster.py:64-66 exactly — same 403, same shape, same sibling module."""
    if tier not in _FULL_TIERS:
        raise HTTPException(status_code=403, detail=detail)


@router.get("/relationships")
async def get_relationship_graph(tier: str = Depends(_get_current_tier)):
    """303 node objects + 1535 edges. Full provenance on Pro; structure only on free.

    ★ GATED AT THE ROUTE FROM 2026-10-05. It was open to every caller, including anonymous
      ones, which served 172,174 bytes of the vault's graph TOPOLOGY — all 303 node ids and all
      1535 edges — to anybody who knew the URL. The mask was doing its job (no weights, no
      weight_source, no verify_status, no source, no desc), so this was never a provenance leak;
      what changed is that the decision of 2026-10-05 gives Free no map, so nothing below Pro
      consumes it and the exposure no longer buys anything.

    ★ THE FREE BRANCH BELOW IS DELIBERATELY LEFT IN PLACE AND UNREACHED. The masking logic is
      not touched: when the Free surface is designed, the gate is what moves, not the mask. An
      unreachable-but-correct mask is a far better starting point than a deleted one.
    """
    _require_pro(tier, "Pro subscription required for the relationship graph.")
    cache = _load()
    payload = cache["full"] if tier in _FULL_TIERS else cache["free"]
    return Response(
        content=json.dumps(payload, ensure_ascii=False),
        media_type="application/json",
        headers=_NO_STORE_HEADERS,
    )


@router.get("/relationships/coordinates")
async def get_relationship_coordinates():
    """Display-only lat/lng for the globe view. Open to all tiers — a coordinate is not provenance.

    ★ This is the vault's `_bridge/node_coordinates.json`, whose own note reads: "Presentation
      layer only. Coordinates are NOT graph structure and never enter canonical .md." It carries
      lat/lng/type/city and nothing else — no impact, no weight, no scenario membership.
    """
    if not COORDS_PATH.exists():
        raise HTTPException(status_code=503, detail="Coordinates not available.")
    with open(COORDS_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return Response(content=json.dumps(payload, ensure_ascii=False),
                    media_type="application/json", headers=_NO_STORE_HEADERS)
