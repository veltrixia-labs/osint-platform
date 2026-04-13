"""
[v10.21] Entity Lifecycle Management Engine
=============================================
Calculates Strategic Score for all stakeholders and prunes low-value
auto-provisioned entities to keep the DB within capacity limits.

Strategic Score Formula:
    score = (frequency_score * 0.4) + (accuracy_score * 0.3) + (depth_score * 0.3) - age_penalty

Rules:
    - is_auto_provisioned=False (Backbone) → PROTECTED, never pruned
    - Pruning only after: score < PRUNE_THRESHOLD AND last_hit > PRUNE_DAYS AND dep_count <= 3
    - 2-stage: first mark score=-1 (warn), delete on next cycle if still -1
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.future import select
from sqlalchemy import func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models import Stakeholder, Dependency, Prediction

logger = logging.getLogger(__name__)

# ── Tuning Constants ─────────────────────────────────────────────────────────
PRUNE_THRESHOLD   = 0.2    # Strategic Score below this → candidate for pruning
PRUNE_DAYS        = 30     # Days since last_hit_at to consider pruning
MAX_PRUNE_PER_RUN = 20     # Safety cap: max entities pruned in a single cycle
DEPTH_THRESHOLD   = 3      # Entities with more deps than this → protected


class EntityLifecycleEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Score Calculation ────────────────────────────────────────────────────

    async def recalculate_scores(self) -> int:
        """Recalculate strategic_score for all stakeholders. Returns # updated."""
        logger.info("[Lifecycle] Recalculating Strategic Scores for all stakeholders...")
        
        all_stakes = (await self.db.execute(select(Stakeholder))).scalars().all()
        updated = 0

        for s in all_stakes:
            score = await self._compute_score(s)
            s.strategic_score = score
            updated += 1

        await self.db.flush()
        logger.info(f"[Lifecycle] Scores recalculated for {updated} stakeholders.")
        return updated

    async def _compute_score(self, s: Stakeholder) -> float:
        """Multi-dimensional strategic score (0.0–1.0)."""
        
        # 1. Frequency Score: how many predictions reference this entity
        pred_count_result = await self.db.execute(
            select(func.count(Prediction.id)).where(Prediction.target_id == s.id)
        )
        pred_count = pred_count_result.scalar() or 0
        frequency_score = min(1.0, pred_count / 20.0)  # Normalize: 20 = max expected

        # 2. Accuracy Score: based on prediction evaluation accuracy
        eval_result = await self.db.execute(
            select(Prediction).where(
                Prediction.target_id == s.id,
                Prediction.is_evaluated == True,
                Prediction.actual_alpha != None
            )
        )
        evaluated = eval_result.scalars().all()
        if evaluated:
            errors = [abs((p.actual_alpha or 0) - (p.predicted_alpha or 0)) for p in evaluated]
            avg_error = sum(errors) / len(errors)
            accuracy_score = max(0.0, 1.0 - (avg_error / 10.0))  # Error of 10% = score 0
        else:
            accuracy_score = 0.3  # Default for unevaluated entities

        # 3. Depth Score: how many dependency connections (in + out)
        dep_result = await self.db.execute(
            select(func.count(Dependency.id)).where(
                (Dependency.source_id == s.id) | (Dependency.target_id == s.id)
            )
        )
        dep_count = dep_result.scalar() or 0
        depth_score = min(1.0, dep_count / 10.0)  # 10 deps = max score

        # 4. Age Penalty: reduce score the longer since last hit
        age_penalty = 0.0
        if s.last_hit_at:
            days_since = (datetime.now(timezone.utc) - s.last_hit_at).days
            age_penalty = min(0.3, days_since / 100.0)  # Max 0.3 penalty at 100 days
        elif s.is_auto_provisioned:
            age_penalty = 0.15  # Moderate penalty for newly auto-added, never-hit entities

        raw_score = (frequency_score * 0.4) + (accuracy_score * 0.3) + (depth_score * 0.3) - age_penalty
        return max(0.0, min(1.0, raw_score))

    # ── Pruning ──────────────────────────────────────────────────────────────

    async def run_pruning(self, db_pressure_critical: bool = False) -> int:
        """
        Identify and remove low-value auto-provisioned entities.
        Uses 2-stage soft-delete: score=-1 first, then physical delete on next run.
        Returns number of entities deleted.
        """
        logger.info("[Lifecycle] Starting entity pruning scan...")
        now = datetime.now(timezone.utc)
        prune_threshold_date = now - timedelta(days=PRUNE_DAYS)
        
        # Find stage-2 candidates (already marked score=-1 last cycle → delete now)
        hard_delete_stmt = select(Stakeholder).where(
            Stakeholder.is_auto_provisioned == True,
            Stakeholder.strategic_score == -1.0,
        )
        hard_candidates = (await self.db.execute(hard_delete_stmt)).scalars().all()
        deleted = 0

        for s in hard_candidates[:MAX_PRUNE_PER_RUN]:
            # Final safety: check dep count again before deleting
            dep_count = (await self.db.execute(
                select(func.count(Dependency.id)).where(
                    (Dependency.source_id == s.id) | (Dependency.target_id == s.id)
                )
            )).scalar() or 0

            if dep_count > DEPTH_THRESHOLD:
                # Promoted to protected — too many connections
                logger.info(f"[Lifecycle] PROTECT (deps={dep_count}): {s.name}")
                s.strategic_score = max(0.3, s.strategic_score)  # Reset
                continue

            logger.info(f"[Lifecycle] PRUNING: {s.name} (score={s.strategic_score:.2f}, deps={dep_count})")
            await self.db.delete(s)
            deleted += 1

        # Stage-1: Mark new candidates as score=-1 (soft delete warning)
        soft_delete_stmt = select(Stakeholder).where(
            Stakeholder.is_auto_provisioned == True,
            Stakeholder.strategic_score < PRUNE_THRESHOLD,
            Stakeholder.strategic_score >= 0.0,   # Skip already-marked
            (Stakeholder.last_hit_at == None) | (Stakeholder.last_hit_at < prune_threshold_date),
        )
        soft_candidates = (await self.db.execute(soft_delete_stmt)).scalars().all()

        soft_marked = 0
        for s in soft_candidates:
            # Extra safety: skip if dep count is high
            dep_count = (await self.db.execute(
                select(func.count(Dependency.id)).where(
                    (Dependency.source_id == s.id) | (Dependency.target_id == s.id)
                )
            )).scalar() or 0

            if dep_count > DEPTH_THRESHOLD:
                continue

            logger.info(f"[Lifecycle] SOFT-MARK (will delete next cycle): {s.name} (score={s.strategic_score:.2f})")
            s.strategic_score = -1.0
            soft_marked += 1

        await self.db.flush()
        logger.info(f"[Lifecycle] Pruning: {deleted} deleted, {soft_marked} soft-marked for next cycle.")
        return deleted

    # ── Reporting ────────────────────────────────────────────────────────────

    async def get_score_summary(self) -> dict:
        """Returns a summary of the stakeholder distribution for monitoring."""
        all_stakes = (await self.db.execute(select(Stakeholder))).scalars().all()
        backbone = [s for s in all_stakes if not s.is_auto_provisioned]
        tactical = [s for s in all_stakes if s.is_auto_provisioned]
        high_score = [s for s in all_stakes if (s.strategic_score or 0) >= 0.6]
        flagged = [s for s in all_stakes if (s.strategic_score or 0) == -1.0]

        return {
            "total": len(all_stakes),
            "backbone": len(backbone),
            "tactical_auto": len(tactical),
            "high_score": len(high_score),
            "soft_delete_flagged": len(flagged),
        }


# ── Scheduler Entry Points ───────────────────────────────────────────────────

async def run_entity_lifecycle(db_pressure_critical: bool = False):
    """Main entry point called by the scheduler."""
    logger.info("[Lifecycle] Starting Entity Lifecycle Management...")
    async with AsyncSessionLocal() as db:
        engine_inst = EntityLifecycleEngine(db)
        
        # 1. Recalculate all scores
        await engine_inst.recalculate_scores()
        
        # 2. Prune (always, but more aggressively under critical DB pressure)
        deleted = await engine_inst.run_pruning(db_pressure_critical=db_pressure_critical)
        
        # 3. Log summary
        summary = await engine_inst.get_score_summary()
        logger.info(f"[Lifecycle] Summary: {summary}")
        
        await db.commit()
        logger.info(f"[Lifecycle] Complete. Deleted {deleted} low-value tactical nodes.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(run_entity_lifecycle())
