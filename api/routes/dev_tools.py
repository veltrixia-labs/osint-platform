"""
Development and controlled production utilities for Pro Structural Brief regeneration.
"""

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from jobs.pro_brief_regenerator import (
    CORE_PRO_DOMAINS,
    audit_pro_structural_reports,
    regenerate_pro_structural_briefs,
)
from db.database import AsyncSessionLocal

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


def _regen_allowed(x_pro_regen_secret: Optional[str]) -> bool:
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
    """
    Inspect pro_structural rows (counts, latest created_at, payload schema version).
    Allowed locally (ALLOW_DEV_TIER_OVERRIDE) or in production with X-Pro-Regen-Secret.
    """
    if not _regen_allowed(x_pro_regen_secret):
        raise HTTPException(
            status_code=403,
            detail="Access denied. Use local dev override or X-Pro-Regen-Secret.",
        )
    async with AsyncSessionLocal() as db:
        return await audit_pro_structural_reports(db)


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
    """
    Regenerate Pro Structural Briefs for core domains.

    - Local: ALLOW_DEV_TIER_OVERRIDE=true and ENV!=production
    - Production: set PRO_BRIEF_REGEN_SECRET and pass header X-Pro-Regen-Secret

    Example:
      curl -X POST "https://osint-platform.onrender.com/api/dev/generate-pro-structural-briefs?purge=true" \\
        -H "X-Pro-Regen-Secret: $PRO_BRIEF_REGEN_SECRET"
    """
    if not _regen_allowed(x_pro_regen_secret):
        raise HTTPException(
            status_code=403,
            detail=(
                "Dev tools disabled. Local: ALLOW_DEV_TIER_OVERRIDE=true, ENV!=production. "
                "Production: PRO_BRIEF_REGEN_SECRET + X-Pro-Regen-Secret."
            ),
        )

    domain_list: List[str] = DEFAULT_DOMAINS
    if domains:
        domain_list = [d.strip() for d in domains.split(",") if d.strip()]

    return await regenerate_pro_structural_briefs(
        domains=domain_list,
        purge_first=purge,
    )
