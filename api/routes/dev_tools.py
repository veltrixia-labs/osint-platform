"""
Development and controlled production utilities for Pro data sync and rebuild.

Production: set PRO_BRIEF_REGEN_SECRET and pass header X-Pro-Regen-Secret on every call.
"""

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from db.database import AsyncSessionLocal
from jobs.pro_backfill_pipeline import (
    audit_external_data_coverage,
    run_backfill_and_rebuild,
    run_sync_external_data,
)
from jobs.pro_brief_regenerator import (
    CORE_PRO_DOMAINS,
    audit_pro_structural_reports,
    regenerate_pro_structural_briefs,
    run_pro_platform_rebuild,
)

router = APIRouter(prefix="/dev", tags=["Dev Tools"])

DEFAULT_DOMAINS = CORE_PRO_DOMAINS


def _dev_tools_allowed() -> bool:
    env_name = os.environ.get("ENV", "development").lower()
    allow = os.environ.get("ALLOW_DEV_TIER_OVERRIDE", "false").lower() == "true"
    return env_name != "production" and allow


def _regen_secret_configured() -> bool:
    return bool(os.environ.get("PRO_BRIEF_REGEN_SECRET", "").strip())


def _require_ops_auth(x_pro_regen_secret: Optional[str]) -> None:
    """Local dev override OR production secret header (required in production)."""
    if _dev_tools_allowed():
        return
    if not _regen_secret_configured():
        raise HTTPException(
            status_code=503,
            detail="PRO_BRIEF_REGEN_SECRET is not configured on this server.",
        )
    expected = os.environ.get("PRO_BRIEF_REGEN_SECRET", "").strip()
    if not x_pro_regen_secret or x_pro_regen_secret.strip() != expected:
        raise HTTPException(
            status_code=403,
            detail="Invalid or missing X-Pro-Regen-Secret header.",
        )


@router.get("/external-data-coverage")
async def external_data_coverage(
    x_pro_regen_secret: Optional[str] = Header(None, alias="X-Pro-Regen-Secret"),
) -> Dict[str, Any]:
    """Count priority FRED/EIA/OPEC series rows in external_observations."""
    _require_ops_auth(x_pro_regen_secret)
    async with AsyncSessionLocal() as db:
        return await audit_external_data_coverage(db)


@router.get("/pro-structural-audit")
async def pro_structural_audit(
    x_pro_regen_secret: Optional[str] = Header(None, alias="X-Pro-Regen-Secret"),
) -> Dict[str, Any]:
    _require_ops_auth(x_pro_regen_secret)
    async with AsyncSessionLocal() as db:
        return await audit_pro_structural_reports(db)


@router.post("/sync-external-data")
@router.get("/sync-external-data")
async def sync_external_data(
    full: bool = Query(
        False,
        description="Run full daily EXTERNAL_SYNC_STEPS (estat/ecb/bcb/asean included)",
    ),
    rebuild: bool = Query(
        False,
        description="After sync, purge and regenerate pro_structural briefs (V2)",
    ),
    purge: bool = Query(True, description="When rebuild=true, delete old pro_structural rows first"),
    domains: Optional[str] = Query(None, description="Comma-separated domain_ids for rebuild"),
    x_pro_regen_secret: Optional[str] = Header(None, alias="X-Pro-Regen-Secret"),
) -> Dict[str, Any]:
    """
    Force external macro/market backfill into PostgreSQL (UPSERT via ExternalDataFetcher).

    Priority: WTI (DCOILWTICO), GPR*, EIA inventories, OPEC/Comtrade crude flows, BLS/BEA.

    With rebuild=true: chains sync → purge → generate-pro-structural-briefs internally.
    """
    _require_ops_auth(x_pro_regen_secret)

    sync_result = await run_sync_external_data(full_pipeline=full, include_market=True)

    if not rebuild:
        return sync_result

    domain_list: Optional[List[str]] = None
    if domains:
        domain_list = [d.strip() for d in domains.split(",") if d.strip()]

    regen_result = await regenerate_pro_structural_briefs(
        domains=domain_list,
        purge_first=purge,
    )

    return {
        "status": "ok",
        "pipeline": "sync_external_data_then_rebuild",
        "sync": sync_result,
        "regeneration": regen_result,
    }


@router.post("/sync-pro-macro-data")
@router.get("/sync-pro-macro-data")
async def sync_pro_macro_data(
    full: bool = Query(False, description="Run full daily pipeline (all sources)"),
    x_pro_regen_secret: Optional[str] = Header(None, alias="X-Pro-Regen-Secret"),
) -> Dict[str, Any]:
    """Alias for Pro-priority sync (backward compatible)."""
    _require_ops_auth(x_pro_regen_secret)
    return await run_sync_external_data(full_pipeline=full, include_market=True)


@router.post("/backfill-and-rebuild")
@router.get("/backfill-and-rebuild")
async def backfill_and_rebuild(
    purge: bool = Query(True, description="Purge pro_structural before regeneration"),
    full: bool = Query(False, description="Use full daily external sync pipeline"),
    domains: Optional[str] = Query(None, description="Comma-separated domain_ids"),
    x_pro_regen_secret: Optional[str] = Header(None, alias="X-Pro-Regen-Secret"),
) -> Dict[str, Any]:
    """
    One-shot production pipeline: backfill external data → purge → Pro V2 regeneration.

    Example:
      curl -X POST "https://osint-platform.onrender.com/api/dev/backfill-and-rebuild?purge=true" \\
        -H "X-Pro-Regen-Secret: $PRO_BRIEF_REGEN_SECRET"
    """
    _require_ops_auth(x_pro_regen_secret)

    domain_list: Optional[List[str]] = None
    if domains:
        domain_list = [d.strip() for d in domains.split(",") if d.strip()]

    return await run_backfill_and_rebuild(
        purge_first=purge,
        full_sync=full,
        domains=domain_list,
    )


@router.post("/generate-pro-structural-briefs")
@router.get("/generate-pro-structural-briefs")
async def generate_pro_structural_briefs(
    purge: bool = Query(False, description="Delete existing pro_structural rows first"),
    domains: Optional[str] = Query(None, description="Comma-separated domain_ids"),
    x_pro_regen_secret: Optional[str] = Header(None, alias="X-Pro-Regen-Secret"),
) -> Dict[str, Any]:
    _require_ops_auth(x_pro_regen_secret)

    domain_list: List[str] = DEFAULT_DOMAINS
    if domains:
        domain_list = [d.strip() for d in domains.split(",") if d.strip()]

    return await regenerate_pro_structural_briefs(
        domains=domain_list,
        purge_first=purge,
    )


@router.post("/rebuild-pro-platform")
@router.get("/rebuild-pro-platform")
async def rebuild_pro_platform(
    purge: bool = Query(True, description="Purge existing pro_structural briefs before regen"),
    sync_macro: bool = Query(True, description="Run macro/market sync before regeneration"),
    full_macro: bool = Query(False, description="Use full external sync pipeline (slower)"),
    domains: Optional[str] = Query(None, description="Comma-separated domain_ids"),
    x_pro_regen_secret: Optional[str] = Header(None, alias="X-Pro-Regen-Secret"),
) -> Dict[str, Any]:
    """Backward-compatible alias for run_pro_platform_rebuild."""
    _require_ops_auth(x_pro_regen_secret)

    domain_list: Optional[List[str]] = None
    if domains:
        domain_list = [d.strip() for d in domains.split(",") if d.strip()]

    return await run_pro_platform_rebuild(
        purge_first=purge,
        sync_macro_first=sync_macro,
        full_macro_pipeline=full_macro,
        domains=domain_list,
    )
