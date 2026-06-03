"""
READ-ONLY clustering-quality audit. Makes NO writes (SELECT only, no commit).

Measures cluster COHERENCE the way the ingestion engine actually evaluates it:
for each alert's evidence item, score it against the AGGREGATE of the OTHER
evidence titles (leave-one-out cluster centroid) using the SAME function
cluster_items uses — analysis.clustering.calculate_merge_confidence — and flag it
"loose" only if it falls below the real merge floor (0.40), i.e. it would NOT have
merged into the rest of its own cluster.

This replaces the earlier (misleading) metric that scored each evidence title
against the single COMPOSED headline. A composed headline is just one article's
specific wording, so siblings of the same event scored "loose" against it even
though the cluster is coherent — inflating the rate. Scoring against the cluster
centroid is the honest measure.

Usage (repo root, DATABASE_URL / .env):  py -3 scripts/audit_clustering.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, desc

from db.database import AsyncSessionLocal
from db.models import AlertLog
from jobs.alert_manager import _strip_distinctifiers, _event_tokens
from analysis.clustering import (
    GEO_ENTITIES, extract_entities, calculate_merge_confidence, CATEGORY_THRESHOLDS,
)

# Geo-anchor tokens (single words from the gazetteer) — used to detect evidence
# bound to a cluster by ONLY a shared geo anchor and nothing else.
_GEO_TOKENS = {w for g in GEO_ENTITIES for w in g.split()}

# An evidence item is "loose" if it would not have merged into the rest of its own
# cluster — i.e. its confidence vs the other members is below the live merge floor.
COHERENCE_MIN = CATEGORY_THRESHOLDS.get("default", 0.40)
MIN_EVIDENCE = 3          # only audit clusters with real corroboration
MAX_EVIDENCE = 30         # bound the leave-one-out cost per cluster


class _It:
    """Minimal Item stand-in: calculate_merge_confidence only reads .title."""
    def __init__(self, title: str):
        self.title = title


def _evidence_titles(a: AlertLog) -> list[str]:
    meta = a.metadata_json if isinstance(a.metadata_json, dict) else {}
    out = []
    for e in (meta.get("evidence_list") or []):
        if isinstance(e, dict):
            t = _strip_distinctifiers(str(e.get("title") or "")).strip()
            if t:
                out.append(t)
    return out


async def main() -> None:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(AlertLog)
            .where(AlertLog.suppressed == False)  # noqa: E712
            .order_by(desc(AlertLog.triggered_at))
            .limit(400)
        )).scalars().all()

    audited = 0
    clusters_with_loose = 0
    total_evidence = 0
    total_loose = 0
    total_anchor_only = 0     # bound to the cluster by ONLY a geo anchor (true over-merge)
    multi_geo = 0
    offenders: list[tuple] = []

    for a in rows:
        titles = _evidence_titles(a)[:MAX_EVIDENCE]
        if len(titles) < MIN_EVIDENCE:
            continue
        audited += 1

        # Pre-tokenize for the geo-anchor-only test (significant tokens per title).
        toks = [_event_tokens(t) for t in titles]

        loose = []
        geos: set[str] = set()
        for i, title in enumerate(titles):
            others = [_It(t) for j, t in enumerate(titles) if j != i]
            # Same evaluation cluster_items uses: item vs the cluster aggregate.
            score = calculate_merge_confidence([_It(title)], others)["score"]
            geos |= extract_entities(title)["geo"]
            total_evidence += 1

            # TRUE single-anchor over-merge test: does this item share ANY non-geo
            # significant token with the rest of the cluster? If not, it is bound
            # purely by a shared geo anchor (or nothing) -> genuine over-merge.
            centroid = set().union(*(toks[j] for j in range(len(toks)) if j != i)) if len(toks) > 1 else set()
            shared_nongeo = (toks[i] & centroid) - _GEO_TOKENS
            anchor_only = not shared_nongeo
            if anchor_only:
                total_anchor_only += 1

            if score < COHERENCE_MIN:
                total_loose += 1
                loose.append((round(score, 3), "ANCHOR-ONLY" if anchor_only else "shares-context", title[:64]))

        if len(geos) > 2:   # Phase 3 multi-geo veto caps clusters at 2 theaters
            multi_geo += 1
        if loose:
            clusters_with_loose += 1
            offenders.append((len(loose), len(titles), a.topic, (a.target_label or "")[:54], sorted(geos), loose))

    print("=" * 78)
    print("CLUSTERING COHERENCE AUDIT  (READ-ONLY — no DB writes)")
    print(f"Metric: evidence vs cluster centroid via calculate_merge_confidence; "
          f"loose = score < {COHERENCE_MIN}")
    print("=" * 78)
    print(f"Active alerts scanned (latest 400):        {len(rows)}")
    print(f"Clusters audited (>= {MIN_EVIDENCE} evidence):          {audited}")
    if audited:
        print(f"  ...with >=1 loosely-bound source:          {clusters_with_loose}"
              f" ({100*clusters_with_loose/audited:.0f}%)")
    print(f"  ...spanning >2 distinct GEO anchors:       {multi_geo}")
    print(f"Evidence items inspected:                   {total_evidence}")
    if total_evidence:
        print(f"  ...loose vs centroid (score < {COHERENCE_MIN}):     {total_loose}"
              f" ({100*total_loose/total_evidence:.1f}%)   <- over-inclusive (calibration)")
        print(f"  ...TRUE single-anchor over-merge:         {total_anchor_only}"
              f" ({100*total_anchor_only/total_evidence:.1f}%)   <- bound by ONLY a geo anchor")

    offenders.sort(reverse=True)
    print("\nTOP 12 LEAST-COHERENT CLUSTERS:")
    for n_loose, n_ev, topic, label, geos, loose in offenders[:12]:
        print(f"\n  [{topic}] {label!r}  ({n_loose}/{n_ev} loose; geos={geos})")
        for score, flag, title in loose[:4]:
            print(f"      score={score:<5} [{flag:<14}] :: {title!r}")


if __name__ == "__main__":
    asyncio.run(main())
