"""
Daily OpenSanctions ingestion + PageRank recomputation.

Stream-parses the FollowTheMoney bulk dump line-by-line (so peak RSS stays
low even on the 150 MB+ file), filters via the G20 + conflict-state allowlist,
upserts into the `stakeholders` table by `opensanctions_id`, then runs the
PageRank batch recompute to refresh `network_score` cache.

Safe re-run semantics:
  • Existing stakeholder with same `opensanctions_id` gets in-place update.
  • `domain` is set on insert only — once a backbone entity is curated by
    a human, we don't overwrite their domain assignment.
  • Soft cap at `MAX_ENTITIES` (50k) prevents DB bloat even if upstream
    expands the dump.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, Iterator, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models import Stakeholder, Dependency
from data_sources.opensanctions_client import (
    extract_relationships,
    stream_dump,
)
from analysis.sanctions_network import recompute_network_scores

logger = logging.getLogger(__name__)

MAX_ENTITIES = 50_000
COMMIT_BATCH_SIZE = 1_000


async def _upsert_entity_batch(
    session: AsyncSession,
    batch: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Insert or update a batch of normalised OpenSanctions entities."""
    if not batch:
        return {"inserted": 0, "updated": 0}
    inserted = 0
    updated = 0
    ids = [e["opensanctions_id"] for e in batch if e.get("opensanctions_id")]
    existing_rows = list((
        await session.execute(
            select(Stakeholder).where(Stakeholder.opensanctions_id.in_(ids))
        )
    ).scalars().all())
    by_id = {row.opensanctions_id: row for row in existing_rows}

    for entity in batch:
        os_id = entity.get("opensanctions_id")
        if not os_id:
            continue
        existing = by_id.get(os_id)
        if existing is None:
            session.add(Stakeholder(
                opensanctions_id=os_id,
                name=entity["name"],
                country=entity.get("country"),
                sector=entity.get("sector"),
                domain=entity.get("domain") or "global_market_intelligence",
                description=entity.get("description"),
                sanctioned_status=bool(entity.get("sanctioned_status")),
                sanction_program=entity.get("sanction_program"),
                pep_score=entity.get("pep_score"),
                # Auto-provisioned (deletable) so the entity lifecycle job can
                # prune stale rows. Backbone entities are seeded separately.
                is_auto_provisioned=True,
            ))
            inserted += 1
        else:
            existing.name = entity["name"]
            existing.country = entity.get("country") or existing.country
            existing.sector = entity.get("sector") or existing.sector
            # Do NOT clobber description if upstream is empty
            if entity.get("description"):
                existing.description = entity["description"]
            existing.sanctioned_status = bool(entity.get("sanctioned_status"))
            existing.sanction_program = entity.get("sanction_program")
            existing.pep_score = entity.get("pep_score")
            updated += 1

    await session.commit()
    return {"inserted": inserted, "updated": updated}


async def _ingest_entities(
    source_iter: Iterator[Dict[str, Any]],
    *,
    max_entities: int = MAX_ENTITIES,
    commit_batch_size: int = COMMIT_BATCH_SIZE,
) -> Dict[str, int]:
    """Stream batches into the DB; honour the soft cap on total rows."""
    totals = {"seen": 0, "inserted": 0, "updated": 0}
    batch: List[Dict[str, Any]] = []
    relationship_pairs: List[Dict[str, Any]] = []

    async with AsyncSessionLocal() as session:
        for entity in source_iter:
            if totals["seen"] >= max_entities:
                break
            batch.append(entity)
            relationship_pairs.extend(extract_relationships(entity))
            totals["seen"] += 1
            if len(batch) >= commit_batch_size:
                stats = await _upsert_entity_batch(session, batch)
                totals["inserted"] += stats["inserted"]
                totals["updated"] += stats["updated"]
                batch = []

        if batch:
            stats = await _upsert_entity_batch(session, batch)
            totals["inserted"] += stats["inserted"]
            totals["updated"] += stats["updated"]

        edges_persisted = await _upsert_relationships(session, relationship_pairs)

    totals["relationships_persisted"] = edges_persisted
    return totals


async def _upsert_relationships(
    session: AsyncSession,
    relationship_pairs: List[Dict[str, Any]],
) -> int:
    """
    Persist OpenSanctions edges into the Dependency table. Both endpoints
    must already exist as Stakeholders (otherwise we silently skip — the next
    sync cycle will eventually pick the missing endpoint up).
    """
    if not relationship_pairs:
        return 0
    needed_ids = {r["source_opensanctions_id"] for r in relationship_pairs}
    needed_ids.update(r["target_opensanctions_id"] for r in relationship_pairs)
    rows = list((
        await session.execute(
            select(Stakeholder).where(Stakeholder.opensanctions_id.in_(needed_ids))
        )
    ).scalars().all())
    id_to_uuid = {r.opensanctions_id: r.id for r in rows}

    persisted = 0
    for rel in relationship_pairs:
        src_uuid = id_to_uuid.get(rel["source_opensanctions_id"])
        tgt_uuid = id_to_uuid.get(rel["target_opensanctions_id"])
        if not src_uuid or not tgt_uuid or src_uuid == tgt_uuid:
            continue
        # idempotent: rely on the (source_id, target_id) UNIQUE constraint
        existing = (
            await session.execute(
                select(Dependency).where(
                    Dependency.source_id == src_uuid,
                    Dependency.target_id == tgt_uuid,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(Dependency(
                source_id=src_uuid,
                target_id=tgt_uuid,
                dependency_type=rel.get("dependency_type") or "associate",
                exposure_weight=float(rel.get("exposure_weight") or 0.5),
            ))
            persisted += 1
    await session.commit()
    return persisted


async def run_sanctions_sync() -> Dict[str, Any]:
    """
    Entry point for the daily scheduler. Streams the latest OpenSanctions
    dump, upserts entities + relationships, recomputes PageRank centrality.

    Failures are caught and logged — the sync job is non-critical for the
    OSINT pipeline and must never crash the scheduler.
    """
    started = datetime.utcnow()
    logger.info("OpenSanctions sync starting…")
    summary: Dict[str, Any] = {"started_at": started.isoformat() + "Z"}

    try:
        totals = await _ingest_entities(stream_dump())
        summary.update(totals)
    except Exception as exc:
        logger.error("OpenSanctions ingest failed: %s", exc, exc_info=True)
        summary["ingest_error"] = str(exc)

    # Recompute PageRank regardless — even if the dump was empty, existing
    # rows benefit from a fresh score (their topology may have changed via
    # other ingestion paths).
    try:
        async with AsyncSessionLocal() as session:
            pr_summary = await recompute_network_scores(session)
        summary["pagerank"] = pr_summary
    except Exception as exc:
        logger.error("PageRank recompute failed: %s", exc, exc_info=True)
        summary["pagerank_error"] = str(exc)

    summary["completed_at"] = datetime.utcnow().isoformat() + "Z"
    duration = (datetime.utcnow() - started).total_seconds()
    summary["duration_seconds"] = round(duration, 2)
    logger.info("OpenSanctions sync done in %.1fs: %s", duration, summary)
    return summary
