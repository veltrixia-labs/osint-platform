"""
Daily external macro-data sync pipeline (Phase 0–2.5).

Runs ExternalDataFetcher steps sequentially with configurable inter-step delay
so API rate limits are respected and the OSINT pipeline stays unblocked.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List

from data_sources.base_client import redact_credentials
from db.database import AsyncSessionLocal
from jobs.external_data_fetcher import ExternalDataFetcher

logger = logging.getLogger(__name__)

# Pro backfill priority: BEA/BLS/FRED/EIA + trade/energy strategy (no 20min delay)
PRO_MACRO_SYNC_STEPS: List[tuple[str, str, str]] = [
    ("fred", "FRED", "sync_fred"),
    ("bls", "BLS", "sync_bls"),
    ("bea", "BEA GDPbyIndustry", "sync_bea_industry_stats"),
    ("eia", "Energy Stats (EIA)", "sync_eia_energy_stats"),
    ("opec", "Energy Strategy (OPEC)", "sync_opec_energy_stats"),
    ("comtrade", "UN Comtrade", "sync_comtrade"),
    ("worldbank", "World Bank", "sync_worldbank"),
    # census removed here too — see the note at EXTERNAL_SYNC_STEPS below.
]

# (step_id, log label, fetcher method name)
EXTERNAL_SYNC_STEPS: List[tuple[str, str, str]] = [
    ("fred", "FRED", "sync_fred"),
    ("bls", "BLS", "sync_bls"),
    ("worldbank", "World Bank", "sync_worldbank"),
    ("comtrade", "UN Comtrade", "sync_comtrade"),
    ("bea", "BEA GDPbyIndustry", "sync_bea_industry_stats"),
    # census is DELIBERATELY NOT REGISTERED, in this list or in PRO_MACRO_SYNC_STEPS
    # above. It is not missing. The reason does not depend on the trigger, so removing
    # it from only one list would recreate the config divergence this change exists to
    # remove.
    #
    # It has no reader. The sole consumer of external_industry_stats
    # (analysis/pro_structural_context.py:1171-1178) orders by year DESC, value DESC
    # and takes 20 rows; that window is 20 BEA 2023 rows, and the census rows are 2022.
    # The consumer also never projects raw_json, so nothing it writes is reachable.
    #
    # It fails every day and records success. The response fails JSON parse
    # ("Expecting value: line 1 column 1 (char 0)"), census_client.py:39 turns the
    # exception into [["error"], [str(e)]], format_as_dicts turns that into one
    # synthetic row, and sync_census_cbp writes it three times into
    # external_industry_stats with value NULL and the exception string in raw_json —
    # then calls finish_fetch_log(status="success"). 95 of 95 logged runs say success.
    #
    # The only data that ever landed is 2022 US state-level totals (industry_id NULL,
    # industry_name "Total") — no industry breakdown, which is what the domain configs
    # ask of this source. Measured cost while failing: 4 HTTP attempts per day, because
    # JSONDecodeError carries no .response so base_client.py:98 cannot take the 4xx
    # early-raise and the full max_retries+1 loop runs.
    #
    # data_sources/census_client.py, sync_census_cbp in jobs/external_data_fetcher.py
    # and every import are retained. Re-registering is one line in each list.
    #
    # The three NULL-valued census rows already in external_industry_stats are
    # deliberately NOT deleted here.
    ("estat", "Japan Stats (e-Stat)", "sync_estat_japan_stats"),
    ("eia", "Energy Stats (EIA)", "sync_eia_energy_stats"),
    ("ecb", "Europe Stats (ECB)", "sync_ecb_market_stats"),
    ("bcb", "South America (BCB)", "sync_south_america_stats"),
    ("opec", "Energy Strategy (OPEC)", "sync_opec_energy_stats"),
    ("asean", "Southeast Asia (ASEAN)", "sync_asean_supply_chain_stats"),
]


def _inter_step_delay_seconds() -> float:
    """Pause between sync steps (default 20 minutes)."""
    raw = os.getenv("EXTERNAL_SYNC_INTER_STEP_SECONDS", "1200")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 1200.0


def _is_sync_disabled() -> bool:
    return os.getenv("EXTERNAL_DATA_SYNC_DISABLED", "").lower() in (
        "true",
        "1",
        "yes",
    )


async def _run_one_step(step_id: str, label: str, method_name: str) -> Dict[str, Any]:
    """Execute a single fetcher sync inside its own DB session."""
    started = datetime.now(timezone.utc)
    logger.info("[ExternalDataSync] Step start: %s (%s)", step_id, label)
    try:
        async with AsyncSessionLocal() as session:
            fetcher = ExternalDataFetcher(session)
            sync_fn: Callable[..., Awaitable[Dict[str, Any]]] = getattr(fetcher, method_name)
            result = await sync_fn()
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        logger.info(
            "[ExternalDataSync] Step success: %s (%s) in %.1fs — %s",
            step_id,
            label,
            elapsed,
            result,
        )
        return {
            "step": step_id,
            "label": label,
            "status": "success",
            "elapsed_sec": elapsed,
            "result": result,
        }
    except Exception as exc:
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        logger.error(
            "[ExternalDataSync] Step failed: %s (%s) after %.1fs — %s",
            step_id,
            label,
            elapsed,
            exc,
            exc_info=True,
        )
        return {
            "step": step_id,
            "label": label,
            "status": "failed",
            "elapsed_sec": elapsed,
            # This dict is returned to the caller and becomes the HTTP response body
            # of POST /api/dev/sync-external-data and /api/dev/sync-pro-macro-data,
            # so an exception carrying a credential-bearing URL would be served to
            # whoever holds the ops secret. Redact before it leaves the function.
            "error": redact_credentials(exc),
        }


async def _run_steps(
    steps: List[tuple[str, str, str]],
    *,
    inter_step_delay: float,
) -> Dict[str, Any]:
    pipeline_started = datetime.now(timezone.utc)
    step_results: List[Dict[str, Any]] = []

    for index, (step_id, label, method_name) in enumerate(steps):
        step_results.append(await _run_one_step(step_id, label, method_name))
        if index < len(steps) - 1 and inter_step_delay > 0:
            logger.info(
                "[ExternalDataSync] Inter-step delay %.0fs before next source…",
                inter_step_delay,
            )
            await asyncio.sleep(inter_step_delay)

    success_count = sum(1 for r in step_results if r.get("status") == "success")
    failed = [r["step"] for r in step_results if r.get("status") == "failed"]
    finished = datetime.now(timezone.utc)
    return {
        "status": "completed",
        "started_at": pipeline_started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_sec": (finished - pipeline_started).total_seconds(),
        "steps_total": len(steps),
        "steps_success": success_count,
        "steps_failed": failed,
        "steps": step_results,
    }


async def run_pro_macro_data_sync(
    *,
    full_pipeline: bool = False,
    skip_inter_step_delay: bool = True,
    sync_market_data: bool = True,
) -> Dict[str, Any]:
    """
    One-shot Pro coverage sync: priority macro sources + optional market prices.

    Targets Hormuz/energy series (WTI, GPR*, EIA inventories, OPEC/Comtrade flows).
    """
    if _is_sync_disabled():
        return {"status": "skipped", "reason": "EXTERNAL_DATA_SYNC_DISABLED"}

    from analysis.pro_global_series import ENERGY_GEOPOLITICAL_SERIES_IDS
    from data_sources.bls_series_catalog import get_bls_series_ids
    from data_sources.fred_series_catalog import get_fred_series_ids
    from jobs.market_data_fetcher import MarketDataFetcher

    core_pro_domains = [
        "energy_resource_risk",
        "global_market_intelligence",
        "ai_semiconductor_intelligence",
        "supply_chain_intelligence",
        "crypto_geopolitics",
        "defense_technology",
    ]

    pipeline_started = datetime.now(timezone.utc)
    logger.info("[ProMacroSync] === Pro macro backfill started ===")

    steps = EXTERNAL_SYNC_STEPS if full_pipeline else PRO_MACRO_SYNC_STEPS
    delay = 0.0 if skip_inter_step_delay else _inter_step_delay_seconds()
    macro_summary = await _run_steps(steps, inter_step_delay=delay)

    # Extra-targeted FRED pull (crude + GPR) even if catalog sync partially failed
    fred_extra: Dict[str, Any] = {"status": "skipped"}
    try:
        async with AsyncSessionLocal() as session:
            from jobs.external_data_fetcher import ExternalDataFetcher

            fetcher = ExternalDataFetcher(session)
            priority_fred = list(
                dict.fromkeys(
                    get_fred_series_ids() + list(ENERGY_GEOPOLITICAL_SERIES_IDS)
                )
            )
            fred_extra = await fetcher.sync_fred(series_ids=priority_fred)
            bls_extra = await fetcher.sync_bls(series_ids=get_bls_series_ids())
        fred_extra = {"fred": fred_extra, "bls": bls_extra, "status": "ok"}
    except Exception as exc:
        logger.error("[ProMacroSync] Targeted FRED/BLS refresh failed: %s", exc)
        fred_extra = {"status": "failed", "error": str(exc)}

    market_summary: Dict[str, Any] = {"status": "skipped"}
    if sync_market_data:
        market_results: List[Dict[str, Any]] = []
        try:
            async with AsyncSessionLocal() as session:
                mf = MarketDataFetcher(session)
                for domain_id in core_pro_domains:
                    # Per-domain isolation: one domain's failure must not abort the
                    # remaining domains, nor the keyless Frankfurter call below.
                    try:
                        res = await mf.sync_alpha_vantage_sample(domain_id=domain_id)
                    except Exception as exc:
                        logger.error("[ProMacroSync] Market sync failed for %s: %s", domain_id, exc)
                        res = {"provider": "alpha_vantage", "status": "failed", "error": str(exc)}
                    market_results.append({"domain_id": domain_id, "result": res})
                    await asyncio.sleep(2)
                # Frankfurter requires no API key and is the one path that works when
                # ALPHA_VANTAGE_API_KEY is absent. Keep it reachable regardless.
                try:
                    fx_res = await mf.sync_frankfurter_fx_history(days=31)
                except Exception as exc:
                    logger.error("[ProMacroSync] Frankfurter FX sync failed: %s", exc)
                    fx_res = {"provider": "frankfurter", "status": "failed", "error": str(exc)}
                market_results.append({"domain_id": "_fx", "result": fx_res})

                # Derive the top-level status from what actually happened rather than
                # asserting success. Every entry carries its own "status"; ok/success/
                # completed are the success-equivalent values already used across this
                # codebase (_STATUS_SEVERITY, jobs/pro_brief_regenerator.py:39-48).
                # Not worst_status(): that is worst-wins and would call 5-of-6 "failed".
                outcomes = [(r.get("result") or {}).get("status") for r in market_results]
                ok_count = sum(1 for s in outcomes if s in ("ok", "success", "completed"))
                failed_count = sum(1 for s in outcomes if s == "failed")
                if not outcomes:
                    market_status = "failed"
                elif ok_count == len(outcomes):
                    market_status = "ok"
                elif failed_count == len(outcomes):
                    market_status = "failed"
                else:
                    market_status = "partial"
            market_summary = {"status": market_status, "domains": market_results}
        except Exception as exc:
            logger.error("[ProMacroSync] Market data sync failed: %s", exc)
            # Preserve whatever completed before the session-level failure; discarding
            # it reported one aggregate failure over up to six independent outcomes.
            market_summary = {"status": "failed", "error": str(exc), "domains": market_results}

    finished = datetime.now(timezone.utc)
    return {
        "status": "completed",
        "mode": "full" if full_pipeline else "pro_priority",
        "started_at": pipeline_started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_sec": (finished - pipeline_started).total_seconds(),
        "macro_pipeline": macro_summary,
        "fred_bls_targeted": fred_extra,
        "market_data": market_summary,
    }


async def run_daily_external_data_sync_pipeline() -> Dict[str, Any]:
    """
    Run all ExternalDataFetcher sync methods once, sequentially, with jitter between steps.
    Individual step failures are logged; later steps still run (retry next day).
    """
    if _is_sync_disabled():
        logger.info("[ExternalDataSync] Skipped — EXTERNAL_DATA_SYNC_DISABLED is set.")
        return {"status": "skipped", "reason": "disabled"}

    pipeline_started = datetime.now(timezone.utc)
    logger.info("[ExternalDataSync] === Daily macro sync pipeline started (UTC %s) ===", pipeline_started.isoformat())

    delay = _inter_step_delay_seconds()
    summary = await _run_steps(EXTERNAL_SYNC_STEPS, inter_step_delay=delay)
    summary["started_at"] = pipeline_started.isoformat()
    success_count = summary["steps_success"]
    failed = summary["steps_failed"]
    finished = datetime.fromisoformat(summary["finished_at"])

    if failed:
        logger.error(
            "[ExternalDataSync] Pipeline finished with failures: %s (%d/%d ok)",
            failed,
            success_count,
            len(EXTERNAL_SYNC_STEPS),
        )
    else:
        logger.info(
            "[ExternalDataSync] Pipeline finished successfully (%d/%d steps).",
            success_count,
            len(EXTERNAL_SYNC_STEPS),
        )

    try:
        from jobs.cleanup_job import update_system_metric

        async with AsyncSessionLocal() as session:
            await update_system_metric(
                session,
                "external_data_sync_last_run",
                finished.isoformat(),
            )
            await update_system_metric(
                session,
                "external_data_sync_last_summary",
                str({"success": success_count, "failed": failed}),
            )
    except Exception as metric_exc:
        logger.warning("[ExternalDataSync] Could not persist system metrics: %s", metric_exc)

    try:
        from jobs.pro_generation_policy import pro_regen_after_external_sync
        from jobs.pro_realtime_stream import run_continuous_pro_intelligence_stream
        # Lazy import (main_scheduler imports this module at top → a module-level
        # import here would be circular). By runtime main_scheduler is fully
        # loaded, so this returns the same singleton lock pro_automation_wrapper
        # uses. This was the last unlocked 6-domain pro compile path: without the
        # guard it stacked on heavy_work jobs and could blow the 512MB ceiling.
        # NOTE: _heavy_work_lock / _heavy_db_lock / _external_data_sync_lock are
        #       intentionally SEPARATE locks. Wrapping this external-sync tail in
        #       _heavy_work_lock is safe under the EDS→HW lock order (this fn runs
        #       inside _external_data_sync_lock). But if the three are ever merged
        #       into one lock, this becomes re-acquisition of a held lock (EDS
        #       already held) → self-deadlock. If you merge the locks, REMOVE this
        #       wrap. (Mirror of the NOTE at the lock definitions in main_scheduler.)
        from jobs.main_scheduler import _heavy_work_lock

        if pro_regen_after_external_sync():
            logger.info("[ExternalDataSync] Triggering Pro realtime intelligence stream (force INSERT).")
            async with _heavy_work_lock:
                summary["pro_intelligence_stream"] = await run_continuous_pro_intelligence_stream()
    except Exception as pro_exc:
        logger.error("[ExternalDataSync] Pro realtime stream hook failed: %s", pro_exc)
        summary["pro_intelligence_stream"] = {"status": "error", "error": str(pro_exc)}

    return summary


async def run_all_sync_steps() -> Dict[str, Any]:
    """Alias for manual / one-shot full pipeline runs (same as daily sync)."""
    return await run_daily_external_data_sync_pipeline()
