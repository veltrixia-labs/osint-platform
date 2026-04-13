"""
[v10.21] Backbone Stakeholder Importer
=======================================
Reads all `data/backbone/*.json` files and idempotently loads them into the
`stakeholders` and `dependencies` tables.

Run once (and re-run safely at any time — it uses Upsert logic):
    python scripts/import_backbone.py

Key behaviours:
- Backbone entities: is_auto_provisioned=False  (永続保護, never pruned)
- Upsert by name: duplicate names are updated, not duplicated
- Dependency resolution: run in a second pass after all stakeholders are present
- Token-safe: no LLM calls made here — pure structured data ingestion
"""

import asyncio
import glob
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# --- Path bootstrap ---
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy.future import select
from sqlalchemy import update
from db.database import AsyncSessionLocal
from db.models import Stakeholder, Dependency

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backbone-importer")

# ── Sector → Domain mapping ─────────────────────────────────────────────────
SECTOR_TO_DOMAIN: dict[str, str] = {
    "ENERGY":    "energy",
    "MARKET":    "market",
    "CRYPTO":    "crypto",
    "AI/TECH":   "ai_semi",
    "AITECH":    "ai_semi",
    "AI_TECH":   "ai_semi",
    "DEFENSE":   "defense",
    "DEFENCE":   "defense",
    "TRADE":     "supply_chain",
}

def resolve_domain(sector: str) -> str:
    """Map the JSON sector label to the internal domain code."""
    key = sector.strip().upper().replace(" ", "").replace("-", "")
    return SECTOR_TO_DOMAIN.get(key, "global")

# ── File discovery ───────────────────────────────────────────────────────────
def find_backbone_files() -> list[Path]:
    pattern = str(ROOT / "data" / "backbone" / "*.json")
    files = [Path(p) for p in glob.glob(pattern)]
    if not files:
        logger.error(f"No backbone JSON files found under: {ROOT / 'data' / 'backbone'}")
    return files

# ── Phase 1: Upsert Stakeholders ────────────────────────────────────────────
async def upsert_stakeholders(db, entities: list[dict], sector_override: str | None = None) -> dict[str, uuid.UUID]:
    """Insert or update stakeholders. Returns {name: uuid} mapping."""
    name_to_id: dict[str, uuid.UUID] = {}

    for ent in entities:
        name = (ent.get("name") or "").strip()
        if not name:
            logger.warning(f"Skipping entity with missing name: {ent}")
            continue

        sector = sector_override or ent.get("sector", "GLOBAL")
        domain = resolve_domain(sector)
        location = ent.get("location", {})
        lat = location.get("lat")
        lng = location.get("lng")
        ticker_raw = ent.get("ticker")
        ticker = None if ticker_raw in (None, "null", "NULL", "") else str(ticker_raw)

        # -- Check existing (use first() to tolerate pre-existing duplicates) --
        stmt = select(Stakeholder).where(Stakeholder.name == name).limit(1)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update fields that might have been improved in new backbone data
            existing.ticker       = ticker or existing.ticker
            existing.sector       = sector
            existing.domain       = domain
            existing.country      = ent.get("country") or existing.country
            existing.description  = ent.get("description") or existing.description
            existing.location_lat = lat if lat is not None else existing.location_lat
            existing.location_lng = lng if lng is not None else existing.location_lng
            existing.is_auto_provisioned = False   # Mark as backbone — protected
            name_to_id[name] = existing.id
            logger.debug(f"  [UPDATE] {name}")
        else:
            new_s = Stakeholder(
                id=uuid.uuid4(),
                name=name,
                ticker=ticker,
                sector=sector,
                domain=domain,
                country=ent.get("country", "Unknown"),
                description=ent.get("description", ""),
                location_lat=lat,
                location_lng=lng,
                is_auto_provisioned=False,   # ← Backbone = 永続保護
                strategic_score=0.5,         # Bootstrap score (will be refined by LearningLoop)
                hit_count=0,
                last_hit_at=None,
            )
            db.add(new_s)
            name_to_id[name] = new_s.id
            logger.debug(f"  [CREATE] {name}")

    await db.flush()  # Persist before dependency resolution
    return name_to_id

# ── Phase 2: Resolve & upsert Dependencies ──────────────────────────────────
async def upsert_dependencies(db, entities: list[dict], name_to_id: dict[str, uuid.UUID]) -> tuple[int, int]:
    created = 0
    skipped = 0

    for ent in entities:
        source_name = (ent.get("name") or "").strip()
        source_id = name_to_id.get(source_name)
        if not source_id:
            continue

        for dep in ent.get("top_dependencies", []):
            target_name = (dep.get("target") or "").strip()
            if not target_name:
                continue

            # Best-effort fuzzy lookup: exact first, then case-insensitive
            target_id = name_to_id.get(target_name)
            if not target_id:
                stmt = select(Stakeholder).where(
                    Stakeholder.name.ilike(f"%{target_name[:30]}%")
                )
                result = (await db.execute(stmt)).scalar_one_or_none()
                if result:
                    target_id = result.id

            if not target_id:
                # Target not in backbone — will be resolved when auto-provisioned later
                logger.debug(f"  [DEP SKIP] Target not found: {target_name}")
                skipped += 1
                continue

            if source_id == target_id:
                skipped += 1
                continue

            weight = float(dep.get("weight", 0.5))
            dep_type = dep.get("type", "dependency")

            # Upsert: check for existing pair
            stmt = select(Dependency).where(
                Dependency.source_id == source_id,
                Dependency.target_id == target_id,
            )
            existing_dep = (await db.execute(stmt)).scalar_one_or_none()

            if existing_dep:
                existing_dep.exposure_weight = weight
                existing_dep.dependency_type = dep_type
                skipped += 1
            else:
                new_dep = Dependency(
                    id=uuid.uuid4(),
                    source_id=source_id,
                    target_id=target_id,
                    dependency_type=dep_type,
                    exposure_weight=weight,
                    beta_correlation=min(1.0 + weight, 2.0),       # Heuristic: high weight = high correlation
                    substitution_elasticity=max(0.0, 1.0 - weight), # High weight = low substitutability
                )
                db.add(new_dep)
                created += 1

    await db.flush()
    return created, skipped

# ── Main runner ──────────────────────────────────────────────────────────────
async def run_import():
    files = find_backbone_files()
    if not files:
        return

    logger.info(f"{'='*60}")
    logger.info(f"[Backbone Importer v10.21] Found {len(files)} file(s):")
    for f in files:
        logger.info(f"  {f.name}")
    logger.info(f"{'='*60}")

    total_entities = 0
    total_deps_created = 0
    total_deps_skipped = 0
    all_entities: list[dict] = []

    async with AsyncSessionLocal() as db:
        # ── Phase 1: Load all entities first ──
        for f in files:
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)

                if not isinstance(data, list):
                    logger.warning(f"Skipping {f.name}: expected a JSON array at root.")
                    continue

                # Detect sector from first entity if not explicit in filename
                sector_hint = None
                if data:
                    sector_hint = data[0].get("sector")

                logger.info(f"\n[{f.name}] Loading {len(data)} entities (sector hint: {sector_hint})...")
                name_map = await upsert_stakeholders(db, data, sector_override=None)
                total_entities += len(name_map)
                all_entities.extend(data)
                logger.info(f"  → {len(name_map)} upserted.")

            except Exception as e:
                logger.error(f"Failed to load {f.name}: {e}", exc_info=True)

        await db.commit()
        logger.info(f"\n✅ Phase 1 complete — {total_entities} stakeholders committed.")

        # ── Phase 2: Build name→id map from DB (includes all just-inserted) ──
        logger.info("\nBuilding complete name→id map for dependency resolution...")
        name_to_id: dict[str, uuid.UUID] = {}
        all_stakes_result = await db.execute(select(Stakeholder))
        for s in all_stakes_result.scalars().all():
            name_to_id[s.name] = s.id
        logger.info(f"  → {len(name_to_id)} entities indexed.")

        # ── Phase 3: Resolve dependencies ──
        logger.info("\nResolving dependencies...")
        created, skipped = await upsert_dependencies(db, all_entities, name_to_id)
        total_deps_created += created
        total_deps_skipped += skipped
        await db.commit()

    logger.info(f"\n{'='*60}")
    logger.info(f"[Backbone Importer] COMPLETE")
    logger.info(f"  Stakeholders upserted : {total_entities}")
    logger.info(f"  Dependencies created  : {total_deps_created}")
    logger.info(f"  Dependencies skipped  : {total_deps_skipped}")
    logger.info(f"  (Skipped = already exist or target not in backbone)")
    logger.info(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(run_import())
