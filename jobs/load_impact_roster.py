"""
Impact-roster loader — reads the vault's cascade output (`_shock_impacts.json`)
joined to the Merton PD slice (`_slice_pd_v29.json`) and loads a (scenario,
entity) impact roster into ``impact_roster_rows``.

Both artifacts live OUTSIDE this repo (the 300-node graph, its weights and its
sources stay private in the vault). The source directory therefore comes ONLY
from the env var IMPACT_ROSTER_SOURCE_DIR — there is no default path and no
repo-relative fallback.

DRY-RUN BY DEFAULT. Writing to the DB requires an explicit ``--commit`` flag:
there is deliberately no way to write by accident.

    IMPACT_ROSTER_SOURCE_DIR=/path/to/intelligence_map/_validation \
        python -m jobs.load_impact_roster            # dry-run: prints, writes nothing
    IMPACT_ROSTER_SOURCE_DIR=... python -m jobs.load_impact_roster --commit
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete

from db.database import AsyncSessionLocal
from db.models import ImpactRosterLoad, ImpactRosterRow

logger = logging.getLogger(__name__)

IMPACTS_FILE = "_shock_impacts.json"
# PD slice pin: v15 -> v29 on 2026-09-04.
#
# WHY IT MOVED. The v15 pin was set at 1f776b9 (2026-07-29) with no reason
# recorded — not here, not in that commit. v29 already existed when it was set:
# it is present in the vault tree at fee4779, the vault's HEAD on that date. How
# much older it was is not recoverable, so no age is claimed here — every slice
# entered the vault's history in its initial commit (bfb1f08, 2026-07-10) and
# v29's mtime has since been overwritten by regeneration. Note also that v25 has
# never existed: the sequence is v12..v24, v26..v29.
#
# On 2026-08-29 six firms' total_debt was corrected against primary filings —
# Maersk, Hapag-Lloyd, COSCO, Sinopec, SUMCO, Kawasaki_Heavy (vault 17e5d6d,
# 9df966f, e2a447d, 127e04f, 4fc1db9, aab981b). Those corrections cannot reach
# v15: its generator, _validation/model_slice_v15.py:70, is gated
# `GATE_OK=(ENT==239)` and hard-exits at :76, against a vault now at 302 nodes.
# v15 is frozen by construction, so the product has been serving a
# pre-correction pd.
#
# WHAT MOVING THE PIN ACTUALLY CHANGES — measured by running build_rows()
# read-only against both slices, not argued:
#   - 100 rows either way. No row appears, none disappears; base_seen and the
#     skipped-variant list are identical.
#   - Exactly ONE row differs: china_re / Kawasaki_Heavy_Industries.
#       debt         4.11    -> 3.766
#       asset_value  20.11   -> 19.766
#       d2           2.79314 -> 2.92499
#       pd           0.00261 -> 0.00172
#     All four move together; the Merton inputs are why pd moves.
#   - No pd_category changes anywhere. as_of is "2026-07-03" in both slices, so
#     pd_source_as_of is unchanged.
#   - v15 is a strict subset of v29 (156 of 199 entities; nothing in v15 is
#     absent from v29).
# The other five corrected firms move in the slice but not in the roster: none
# appears in any of the 13 base scenarios, so no loaded row carries them.
PD_FILE = "_slice_pd_v29.json"

# The 13 base scenarios. The 11 variant keys (*_revenue, *_revenue_roster,
# *_2hop) are supply-side / routing detail, NOT top-level scenarios, and are
# skipped — visibly (recorded in scenarios_skipped and printed), never silently.
BASE_SCENARIOS = [
    "china_re", "hormuz", "grain", "phosphate_lever", "eda_lever",
    "materials_lever", "euv_lever", "duv_lever", "lithium", "nickel",
    "cobalt", "potash", "soybean",
]

# pd_category is derived ONLY from the excluded node's `reason` prefix. An
# unknown prefix RAISES — we never bucket an unrecognised case into 'other'.
_PD_CATEGORY_BY_PREFIX = {
    "PD~0:": "measured_negligible",      # PD computed, effectively zero (net-cash)
    "EXCLUDE:": "not_measurable",        # no market cap (SOE / private / segment)
    "MERTON HELD:": "model_inapplicable",  # Merton not applied (captive-finance D)
}


class LoaderError(Exception):
    """A recoverable, user-facing failure — main() reports it and exits non-zero."""


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_variant(key: str) -> bool:
    return key.endswith("_revenue") or key.endswith("_revenue_roster") or key.endswith("_2hop")


def _pd_category(status: Optional[str], reason: Optional[str]) -> Optional[str]:
    if status == "computable":
        return "computable"
    r = reason or ""
    for prefix, category in _PD_CATEGORY_BY_PREFIX.items():
        if r.startswith(prefix):
            return category
    raise LoaderError(
        f"Unknown PD reason prefix (status={status!r}): {reason!r} — refusing to "
        "bucket an unrecognised case. Add the prefix explicitly if it is real."
    )


def resolve_source() -> Tuple[str, str, str]:
    """Resolve the source dir + both artifact paths from the env var only."""
    src = os.environ.get("IMPACT_ROSTER_SOURCE_DIR")
    if not src:
        raise LoaderError(
            "IMPACT_ROSTER_SOURCE_DIR is not set. There is no default path — the "
            "artifacts deliberately live outside this repo. Set it to the vault's "
            "_validation directory."
        )
    src = os.path.abspath(os.path.expanduser(src))
    impacts_path = os.path.join(src, IMPACTS_FILE)
    pd_path = os.path.join(src, PD_FILE)
    for p in (impacts_path, pd_path):
        if not os.path.isfile(p):
            raise LoaderError(f"Required artifact not found: {p}")
    return src, impacts_path, pd_path


def build_rows(
    impacts: Dict[str, Any], pd_doc: Dict[str, Any], load_id: uuid.UUID
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """
    Pure: (impacts, pd_doc) -> (row_dicts, base_seen, variant_skipped).
    No DB, no ORM. Join is EXACT entity-name match — no case/underscore fixups.
    Nulls stay null.
    """
    nodes = pd_doc["nodes"]
    as_of = pd_doc.get("as_of")

    variant_skipped = sorted(k for k in impacts if _is_variant(k))
    base_seen = [k for k in BASE_SCENARIOS if k in impacts]

    rows: List[Dict[str, Any]] = []
    for scenario in BASE_SCENARIOS:
        block = impacts.get(scenario)
        if not isinstance(block, dict):
            continue  # scenario absent or non-dict — nothing to load
        for entity, impact in block.items():
            if not isinstance(impact, (int, float)):
                continue
            node = nodes.get(entity)  # EXACT match only
            if node is None:
                pd_fields = dict(
                    entity_kind="region_or_hub",
                    pd=None, pd_status=None, pd_category=None, pd_reason=None,
                    asset_value=None, debt=None, sigma=None, d2=None, bucket=None,
                )
            else:
                pd_fields = dict(
                    entity_kind="firm",
                    pd=node.get("pd"),
                    pd_status=node.get("status"),
                    pd_category=_pd_category(node.get("status"), node.get("reason")),
                    pd_reason=node.get("reason"),
                    asset_value=node.get("V"),
                    debt=node.get("D"),
                    sigma=node.get("sigma"),
                    d2=node.get("d2"),
                    bucket=node.get("bucket"),
                )
            row = dict(
                load_id=load_id,
                scenario=scenario,
                scenario_kind="base",
                entity=entity,
                impact=float(impact),
                pd_source_as_of=as_of,
            )
            row.update(pd_fields)
            rows.append(row)
    return rows, base_seen, variant_skipped


def _summarise(rows: List[Dict[str, Any]], base_seen: List[str], variant_skipped: List[str]) -> Dict[str, Any]:
    loaded = sorted({r["scenario"] for r in rows})
    empty = [s for s in base_seen if s not in loaded]
    by_kind = Counter(r["entity_kind"] for r in rows)
    by_category = Counter(r["pd_category"] for r in rows if r["entity_kind"] == "firm")
    firms_with_pd = sum(1 for r in rows if r["entity_kind"] == "firm" and r["pd"] is not None)
    return {
        "rows": len(rows),
        "base_seen": len(base_seen),
        "scenarios_loaded": loaded,
        "scenarios_empty": empty,
        "variant_skipped": variant_skipped,
        "by_kind": dict(by_kind),
        "by_category": dict(by_category),
        "firms_with_pd": firms_with_pd,
    }


def _print_summary(summary: Dict[str, Any], rows: List[Dict[str, Any]], *, commit: bool) -> None:
    banner = "COMMITTED" if commit else "DRY RUN — nothing written"
    print(f"\n=== impact-roster loader: {banner} ===")
    print(f"  base scenarios seen: {summary['base_seen']}")
    print(f"  scenarios loaded ({len(summary['scenarios_loaded'])}): {summary['scenarios_loaded']}")
    print(f"  scenarios empty ({len(summary['scenarios_empty'])}): {summary['scenarios_empty']}")
    print(f"  variant keys skipped ({len(summary['variant_skipped'])}): {summary['variant_skipped']}")
    print(f"  rows: {summary['rows']}  by entity_kind: {summary['by_kind']}")
    print(f"  firm rows by pd_category: {summary['by_category']}")
    print(f"  firms with a non-null pd: {summary['firms_with_pd']}")

    # One verbatim sample per shape, for transparency.
    def _first(pred):
        return next((r for r in rows if pred(r)), None)
    samples = [
        ("computable firm", _first(lambda r: r["entity_kind"] == "firm" and r["pd"] is not None)),
        ("pd-null firm", _first(lambda r: r["entity_kind"] == "firm" and r["pd"] is None)),
        ("region_or_hub", _first(lambda r: r["entity_kind"] == "region_or_hub")),
    ]
    print("\n  sample rows (verbatim, load_id elided):")
    for label, r in samples:
        if r is None:
            print(f"    {label}: (none)")
            continue
        shown = {k: v for k, v in r.items() if k != "load_id"}
        print(f"    {label}: {json.dumps(shown, ensure_ascii=False)}")
    print()


async def run(commit: bool) -> Dict[str, Any]:
    started = datetime.now(timezone.utc)
    src, impacts_path, pd_path = resolve_source()
    with open(impacts_path, "r", encoding="utf-8") as fh:
        impacts = json.load(fh)
    with open(pd_path, "r", encoding="utf-8") as fh:
        pd_doc = json.load(fh)

    load_id = uuid.uuid4()
    rows, base_seen, variant_skipped = build_rows(impacts, pd_doc, load_id)
    summary = _summarise(rows, base_seen, variant_skipped)

    if not commit:
        # Dry-run writes NOTHING — not even the load row — and opens no DB session.
        _print_summary(summary, rows, commit=False)
        return summary

    impacts_sha = _sha256(impacts_path)
    pd_sha = _sha256(pd_path)
    as_of = pd_doc.get("as_of")
    loaded_scenarios = summary["scenarios_loaded"]

    # A run that requested scenarios but wrote zero rows must NOT record success.
    if rows:
        status = "success"
        error_message = None
    else:
        status = "partial"
        error_message = (
            "Zero rows written: no base scenario yielded an impacted entity "
            f"(base scenarios seen={len(base_seen)})."
        )

    async with AsyncSessionLocal() as session:
        # Idempotent: delete existing rows for the base scenarios processed this
        # run, then insert. Mirrors load_scenarios.py's delete-then-insert per key;
        # never truncates the whole table. Deleting the full base set (not only
        # loaded) also clears a scenario that has since gone empty.
        if base_seen:
            await session.execute(
                delete(ImpactRosterRow).where(ImpactRosterRow.scenario.in_(base_seen))
            )
        for r in rows:
            session.add(ImpactRosterRow(id=uuid.uuid4(), **r))

        finished = datetime.now(timezone.utc)
        session.add(
            ImpactRosterLoad(
                id=load_id,
                started_at=started,
                finished_at=finished,
                status=status,
                source_dir=src,
                impacts_sha256=impacts_sha,
                pd_sha256=pd_sha,
                pd_source_as_of=as_of,
                scenarios_seen=len(base_seen),
                scenarios_loaded=len(loaded_scenarios),
                scenarios_skipped=",".join(variant_skipped) or None,
                rows_written=len(rows),
                error_message=error_message,
            )
        )
        await session.commit()

    summary["load_status"] = status
    _print_summary(summary, rows, commit=True)
    logger.info("impact-roster load %s: status=%s rows=%s", load_id, status, len(rows))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Load the vault's impact roster (impact x Merton PD) into impact_roster_rows."
    )
    ap.add_argument(
        "--commit",
        action="store_true",
        help="actually write to the DB. Default is a dry-run that writes nothing.",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run(commit=args.commit))
    except LoaderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
