"""
Development and controlled production utilities for Pro data sync and rebuild.
"""

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from db.database import AsyncSessionLocal
from jobs.external_data_sync import run_pro_macro_data_sync
from jobs.pro_brief_regenerator import (
    CORE_PRO_DOMAINS,
    audit_pro_structural_reports,
    regenerate_pro_structural_briefs,
    run_pro_platform_rebuild,
)

router = APIRouter(prefix="/dev", tags=["Dev Tools"])

DEFAULT_DOMAINS = CORE_PRO_DOMAINS


def _dev_tools_allowed() -> bool:
    """Local-only unrestricted access."""
    env_name = os.environ.get("ENV", "development").lower()
    allow = os.environ.get("ALLOW_DEV_TIER_OVERRIDE", "false").lower() == "true"
    return env_name != "production" and allow


def _regen_secret_configured() -> bool:
    return bool(os.environ.get("PRO_BRIEF_REGEN_SECRET", "").strip())


def _verify_regen_secret(x_pro_regen_secret: Optional[str]) -> None:
    expected = os.environ.get("PRO_BRIEF_REGEN_SECRET", "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="PRO_BRIEF_REGEN_SECRET is not configured on this server.",
        )
    if not x_pro_regen_secret or x_pro_regen_secret.strip() != expected:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Pro-Regen-Secret header.")


def _ops_allowed(x_pro_regen_secret: Optional[str]) -> bool:
    if _dev_tools_allowed():
        return True
    if _regen_secret_configured() and x_pro_regen_secret:
        try:
            _verify_regen_secret(x_pro_regen_secret)
            return True
        except HTTPException:
            return False
    return False


@router.get("/pro-structural-audit")
async def pro_structural_audit(
    x_pro_regen_secret: Optional[str] = Header(None, alias="X-Pro-Regen-Secret"),
) -> Dict[str, Any]:
    """Inspect pro_structural rows (counts, schema version, macro card density)."""
    if not _ops_allowed(x_pro_regen_secret):
        raise HTTPException(
            status_code=403,
            detail="Access denied. Use local dev override or X-Pro-Regen-Secret.",
        )
    async with AsyncSessionLocal() as db:
        return await audit_pro_structural_reports(db)


@router.post("/sync-pro-macro-data")
@router.get("/sync-pro-macro-data")
async def sync_pro_macro_data(
    full: bool = Query(False, description="Run full daily pipeline (all sources)"),
    x_pro_regen_secret: Optional[str] = Header(None, alias="X-Pro-Regen-Secret"),
) -> Dict[str, Any]:
    """
    Force one-shot sync of FRED/BLS/BEA/EIA/OPEC/Comtrade (+ market prices per domain).

    Priority series include WTI (DCOILWTICO), GPR/GPRH/GPRHT/GPRA, and EIA inventories.
    """
    if not _ops_allowed(x_pro_regen_secret):
        raise HTTPException(status_code=403, detail="Access denied for macro sync.")
    return await run_pro_macro_data_sync(
        full_pipeline=full,
        skip_inter_step_delay=True,
        sync_market_data=True,
    )


@router.post("/generate-pro-structural-briefs")
@router.get("/generate-pro-structural-briefs")
async def generate_pro_structural_briefs(
    purge: bool = Query(False, description="Delete existing pro_structural rows for target domains first"),
    domains: Optional[str] = Query(
        None,
        description="Comma-separated domain_ids; default = all 6 strategic domains",
    ),
    x_pro_regen_secret: Optional[str] = Header(None, alias="X-Pro-Regen-Secret"),
) -> Dict[str, Any]:
    """Regenerate Pro Structural Briefs (optional purge) from current DB observations."""
    if not _ops_allowed(x_pro_regen_secret):
        raise HTTPException(status_code=403, detail="Access denied for brief regeneration.")

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
    """
    End-to-end production rebuild: sync external data → purge → regenerate Pro V2 briefs.

    Example:
      curl -X POST "https://osint-platform.onrender.com/api/dev/rebuild-pro-platform?purge=true" \\
        -H "X-Pro-Regen-Secret: $PRO_BRIEF_REGEN_SECRET"
    """
    if not _ops_allowed(x_pro_regen_secret):
        raise HTTPException(status_code=403, detail="Access denied for platform rebuild.")

    domain_list: Optional[List[str]] = None
    if domains:
        domain_list = [d.strip() for d in domains.split(",") if d.strip()]

    return await run_pro_platform_rebuild(
        purge_first=purge,
        sync_macro_first=sync_macro,
        full_macro_pipeline=full_macro,
        domains=domain_list,
    )
