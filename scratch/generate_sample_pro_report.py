"""
Generate a sample Pro Structural Brief (v3) markdown file for visual review.

Uses the real local DB + production pipeline:
  build_pro_structural_context → build_dynamic_structural_title → build_pro_structural_report

Optionally seeds scratch-tagged rows when macro/market coverage is too thin, then removes them.

Usage:
  py -u scratch/generate_sample_pro_report.py
  py -u scratch/generate_sample_pro_report.py --domains energy_resource_risk
  py -u scratch/generate_sample_pro_report.py --no-seed
  py -u scratch/generate_sample_pro_report.py --keep-seed
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("ENABLE_PRO_STRUCTURAL_LLM_SHAPING", "false")

from sqlalchemy import delete, desc, select

from analysis.pro_domain_config import get_pro_domain_config, infer_domain_from_topic
from analysis.pro_structural_compiler import build_dynamic_structural_title
from analysis.pro_structural_context import build_pro_structural_context, resolve_latest_domain_alert
from db.database import AsyncSessionLocal
from db.models import AlertLog, ExternalDataSeries, ExternalObservation, MarketDataInstrument, MarketDataPrice
from jobs.pro_report_generator import run_pro_structural_report_generation
from reports.pro_structural_report_builder import build_pro_structural_report, build_pro_structural_report_payload
from reports.text_encoding import sanitize_unicode_tree

SCRATCH_MARKER = "scratch_sample_pro_report_v1"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "sample_pro_report.md")

DEFAULT_DOMAINS = ["energy_resource_risk", "global_market_intelligence"]

DOMAIN_TOPIC = {
    "energy_resource_risk": "ENERGY",
    "global_market_intelligence": "MARKET",
}

DOMAIN_MACRO_SERIES = {
    "energy_resource_risk": [
        ("FRED", "DCOILWTICO", "WTI Crude Oil"),
        ("EIA", "WCESTUS1", "U.S. Crude Inventories"),
        ("FRED", "GASREGW", "Retail Gasoline"),
    ],
    "global_market_intelligence": [
        ("FRED", "DGS10", "10-Year Treasury Yield"),
        ("FRED", "VIXCLS", "CBOE VIX"),
        ("FRED", "DTWEXBGS", "Trade-Weighted USD Index"),
    ],
}

DOMAIN_MARKET_SYMBOLS = {
    "energy_resource_risk": [
        ("XLE", "equity", "Energy Select Sector SPDR"),
        ("USO", "etf", "United States Oil Fund"),
    ],
    "global_market_intelligence": [
        ("SPY", "equity", "SPDR S&P 500 ETF"),
        ("TLT", "etf", "iShares 20+ Year Treasury Bond ETF"),
    ],
}


@dataclass
class SeedBundle:
    alert_ids: List[uuid.UUID] = field(default_factory=list)
    observation_ids: List[uuid.UUID] = field(default_factory=list)
    price_ids: List[uuid.UUID] = field(default_factory=list)
    instrument_ids: List[uuid.UUID] = field(default_factory=list)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _section_stats(ctx: dict) -> Dict[str, Any]:
    ci = ctx.get("cascading_impacts") or {}
    matrix = ctx.get("quantitative_evidence_matrix") or {}
    macro_rows = matrix.get("macro_series") or matrix.get("rows") or []
    return {
        "macro_obs": len((ctx.get("structural_context") or {}).get("macro_observations") or []),
        "market_prices": len((ctx.get("market_confirmation") or {}).get("latest_prices") or []),
        "timeline": len(ctx.get("event_timeline") or []),
        "cascading_t1": len(ci.get("tier_1_direct") or []),
        "cascading_t2": len(ci.get("tier_2_downstream") or []),
        "cascading_t3": len(ci.get("tier_3_systemic") or []),
        "tail_risks": len(ctx.get("tail_risk_scenarios") or []),
        "qe_rows": len(macro_rows) if isinstance(macro_rows, list) else 0,
        "quant_evidence": bool(ctx.get("quantitative_evidence")),
    }


def _is_meaningful(stats: Dict[str, Any]) -> bool:
    has_new_sections = (
        stats["cascading_t1"] >= 1
        and stats["tail_risks"] >= 1
        and (stats["qe_rows"] >= 1 or stats["quant_evidence"])
    )
    has_data = stats["macro_obs"] >= 2 and stats["market_prices"] >= 1
    return has_data and has_new_sections


async def _ensure_series(
    db,
    source: str,
    series_id: str,
    name: str,
) -> ExternalDataSeries:
    stmt = select(ExternalDataSeries).where(
        ExternalDataSeries.source == source,
        ExternalDataSeries.series_id == series_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row:
        return row
    row = ExternalDataSeries(
        source=source,
        series_id=series_id,
        name=name,
        unit="index",
        frequency="daily",
    )
    db.add(row)
    await db.flush()
    return row


async def _ensure_instrument(
    db,
    symbol: str,
    asset_class: str,
    name: str,
) -> MarketDataInstrument:
    stmt = select(MarketDataInstrument).where(
        MarketDataInstrument.provider == "alpha_vantage",
        MarketDataInstrument.symbol == symbol,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row:
        return row
    row = MarketDataInstrument(
        provider="alpha_vantage",
        symbol=symbol,
        name=name,
        asset_class=asset_class,
    )
    db.add(row)
    await db.flush()
    return row


async def seed_domain_data(db, domain_id: str) -> SeedBundle:
    """Inject realistic scratch-tagged macro, market, and alert rows."""
    bundle = SeedBundle()
    topic = DOMAIN_TOPIC.get(domain_id, "MARKET")
    now = datetime.now(timezone.utc)
    today = now.date()

    # Macro: ~95 daily points with a mild uptrend + one recent drawdown spike
    for source, series_id, name in DOMAIN_MACRO_SERIES.get(domain_id, []):
        series = await _ensure_series(db, source, series_id, name)
        base = 72.0 if series_id == "DCOILWTICO" else 420.0 if series_id == "WCESTUS1" else 3.2
        if series_id == "DGS10":
            base = 4.25
        elif series_id == "VIXCLS":
            base = 18.0
        elif series_id == "DTWEXBGS":
            base = 121.0
        elif series_id == "GASREGW":
            base = 3.45
        elif series_id == "SPY":
            base = 520.0

        for day_offset in range(95, -1, -1):
            d = today - timedelta(days=day_offset)
            drift = (95 - day_offset) * 0.02
            shock = -5.5 if day_offset <= 3 and series_id == "DCOILWTICO" else 0.0
            if series_id == "WCESTUS1" and day_offset <= 5:
                shock = -3.2
            if series_id == "VIXCLS" and day_offset <= 4:
                shock = 4.0
            value = base + drift + shock + (day_offset % 7) * 0.05
            obs = ExternalObservation(
                series_ref_id=series.id,
                source=source,
                series_id=series_id,
                date=d,
                value=round(value, 4),
                is_latest=(day_offset == 0),
                raw_json={"_scratch_sample": SCRATCH_MARKER, "domain_id": domain_id},
            )
            db.add(obs)
            bundle.observation_ids.append(obs.id)

    # Market: latest + 30d lookback close
    for symbol, asset_class, name in DOMAIN_MARKET_SYMBOLS.get(domain_id, []):
        inst = await _ensure_instrument(db, symbol, asset_class, name)
        if inst.id not in bundle.instrument_ids:
            bundle.instrument_ids.append(inst.id)
        latest_close = 92.0 if symbol == "XLE" else 75.0 if symbol == "USO" else 528.0 if symbol == "SPY" else 92.5
        prev_close = latest_close * 0.97
        for offset, close in ((0, latest_close), (30, prev_close)):
            px = MarketDataPrice(
                instrument_id=inst.id,
                provider="alpha_vantage",
                symbol=symbol,
                date=today - timedelta(days=offset),
                close=round(close, 2),
                raw_json={"_scratch_sample": SCRATCH_MARKER},
            )
            db.add(px)
            bundle.price_ids.append(px.id)

    headlines = {
        "energy_resource_risk": [
            "Strait transit risk elevates Atlantic crude freight assessments",
            "OPEC+ compliance review signals tighter Q3 export quotas",
            "U.S. Gulf Coast refinery maintenance compresses product supply",
        ],
        "global_market_intelligence": [
            "Cross-asset volatility rises as duration risk reprices globally",
            "Major central banks signal data-dependent tightening bias",
            "Equity factor rotation favors defensives amid macro uncertainty",
        ],
    }
    titles = headlines.get(domain_id, headlines["global_market_intelligence"])

    primary = AlertLog(
        target_label=titles[0],
        topic=topic,
        trigger_type="multi_source",
        severity="elevated",
        triggered_at=now - timedelta(hours=2),
        intensity=7.8,
        intelligence_score=0.82,
        fidelity_score=0.76,
        is_high_fidelity=True,
        status="confirmed",
        metadata_json={
            "_scratch_sample": SCRATCH_MARKER,
            "display_title": titles[0],
            "evidence_list": [
                {
                    "title": titles[0],
                    "domain": "reuters.com",
                    "url": "https://www.reuters.com/world/sample-energy-route-risk",
                },
                {
                    "title": "Inventory draw tightens Atlantic crude balance",
                    "domain": "eia.gov",
                    "url": "https://www.eia.gov/sample-weekly-petroleum",
                },
            ],
            "free_alert": {
                "related_news": [
                    {
                        "title": titles[1],
                        "url": "https://www.ft.com/content/sample-opec-review",
                        "published": (now - timedelta(hours=6)).isoformat(),
                    },
                    {
                        "title": titles[2],
                        "url": "https://www.bloomberg.com/news/sample-refinery",
                        "published": (now - timedelta(hours=14)).isoformat(),
                    },
                ],
            },
        },
    )
    db.add(primary)
    bundle.alert_ids.append(primary.id)

    # Historical alerts for macro transmission engine (weekly over 90d)
    for week in range(1, 14):
        hist = AlertLog(
            target_label=f"{topic} structural pressure week {week}",
            topic=topic,
            trigger_type="spike",
            severity="watch",
            triggered_at=now - timedelta(days=7 * week),
            intensity=4.0 + (week % 5) * 0.6,
            intelligence_score=0.45 + week * 0.02,
            fidelity_score=0.5,
            suppressed=False,
            metadata_json={"_scratch_sample": SCRATCH_MARKER},
        )
        db.add(hist)
        bundle.alert_ids.append(hist.id)

    await db.commit()
    _log(f"  Seeded scratch data for {domain_id}: "
         f"{len(bundle.observation_ids)} obs, {len(bundle.price_ids)} prices, "
         f"{len(bundle.alert_ids)} alerts")
    return bundle


async def cleanup_seed_bundle(db, bundle: SeedBundle) -> None:
    if bundle.alert_ids:
        await db.execute(delete(AlertLog).where(AlertLog.id.in_(bundle.alert_ids)))
    if bundle.observation_ids:
        await db.execute(
            delete(ExternalObservation).where(ExternalObservation.id.in_(bundle.observation_ids))
        )
    if bundle.price_ids:
        await db.execute(delete(MarketDataPrice).where(MarketDataPrice.id.in_(bundle.price_ids)))
    await db.commit()
    _log(f"  Rolled back scratch rows: {len(bundle.alert_ids)} alerts, "
         f"{len(bundle.observation_ids)} observations, {len(bundle.price_ids)} prices")


async def build_domain_report(
    db,
    domain_id: str,
    *,
    use_generator_job: bool,
) -> tuple[dict, str, dict]:
    """Return (context, markdown, payload)."""
    alert = await resolve_latest_domain_alert(db, domain_id)
    if alert:
        _log(f"  Anchor alert: {alert.id} | {alert.target_label[:80]}")

    context = await build_pro_structural_context(
        db,
        alert_log=alert,
        domain_id=domain_id,
        force_rebuild=True,
    )
    context["brief_title"] = build_dynamic_structural_title(context)
    context = sanitize_unicode_tree(context)

    if use_generator_job:
        # Mirror jobs/pro_report_generator.py without persisting (dry compile path).
        report_md = sanitize_unicode_tree(build_pro_structural_report(context))
        payload = build_pro_structural_report_payload(context)
    else:
        report_md = build_pro_structural_report(context)
        payload = build_pro_structural_report_payload(context)

    return context, report_md, payload


def _verify_markdown(md: str) -> List[str]:
    required = [
        "## 8. Cascading Impacts",
        "## 9. Tail-Risk & Contrarian Scenarios",
        "## 10. Quantitative Evidence Matrix",
    ]
    missing = [h for h in required if h not in md]
    return missing


async def main() -> int:
    parser = argparse.ArgumentParser(description="Generate sample Pro Insight markdown (v3).")
    parser.add_argument(
        "--domains",
        nargs="+",
        default=DEFAULT_DOMAINS,
        help="Domain IDs to include (default: energy + global market).",
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Never inject scratch DB rows (use only existing data).",
    )
    parser.add_argument(
        "--keep-seed",
        action="store_true",
        help="Leave scratch-tagged rows in the DB after generation.",
    )
    parser.add_argument(
        "--use-generator-job",
        action="store_true",
        help="Also exercise jobs.pro_report_generator (inserts a Report row).",
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_PATH,
        help=f"Output markdown path (default: {OUTPUT_PATH}).",
    )
    args = parser.parse_args()

    bundles: List[SeedBundle] = []
    parts: List[str] = []
    generated_at = datetime.now(timezone.utc).isoformat()

    parts.append("# Sample Pro Insight Reports (Structural v3)\n")
    parts.append(f"_Generated at {generated_at} — local DB pipeline, LLM shaping off._\n")

    async with AsyncSessionLocal() as db:
        for domain_id in args.domains:
            config = get_pro_domain_config(domain_id)
            display = (config or {}).get("display_name", domain_id)
            _log(f"\n=== Domain: {domain_id} ({display}) ===")

            context, md, payload = await build_domain_report(
                db, domain_id, use_generator_job=False,
            )
            stats = _section_stats(context)
            _log(f"  Coverage: {stats}")

            seeded = False
            if not args.no_seed and not _is_meaningful(stats):
                _log("  Insufficient coverage — injecting scratch-tagged seed data…")
                bundle = await seed_domain_data(db, domain_id)
                bundles.append(bundle)
                seeded = True
                context, md, payload = await build_domain_report(
                    db, domain_id, use_generator_job=False,
                )
                stats = _section_stats(context)
                _log(f"  Post-seed coverage: {stats}")

            missing = _verify_markdown(md)
            if missing:
                _log(f"  WARNING: missing headings: {missing}")

            if args.use_generator_job:
                _log("  Running jobs.pro_report_generator (DB insert)…")
                report = await run_pro_structural_report_generation(
                    domain_id=domain_id,
                    force_rebuild=True,
                )
                _log(f"  Inserted report id={report.id} title={report.title[:72]}")

            parts.append(f"\n---\n\n## Domain: {display} (`{domain_id}`)\n")
            parts.append(f"- **Schema:** `{payload.get('payload_schema_version', '?')}`\n")
            parts.append(f"- **Brief title:** {context.get('brief_title', 'N/A')}\n")
            parts.append(f"- **Seed data used:** {'yes' if seeded else 'no'}\n")
            parts.append(
                f"- **Sections:** cascading T1/T2/T3 = "
                f"{stats['cascading_t1']}/{stats['cascading_t2']}/{stats['cascading_t3']}, "
                f"tail-risk = {stats['tail_risks']}, QE matrix rows = {stats['qe_rows']}\n"
            )
            parts.append("\n")
            parts.append(md)
            parts.append("\n")

        if bundles and not args.keep_seed:
            _log("\nRolling back scratch seed data…")
            for bundle in bundles:
                await cleanup_seed_bundle(db, bundle)
        elif bundles and args.keep_seed:
            _log("\n--keep-seed: scratch rows left in DB (tag: "
                 f"{SCRATCH_MARKER})")

    out_path = os.path.abspath(args.output)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))

    _log(f"\nWrote sample report → {out_path}")
    _log("Open scratch/sample_pro_report.md to review Cascading Impacts, Tail-Risk, and Quantitative Evidence Matrix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
