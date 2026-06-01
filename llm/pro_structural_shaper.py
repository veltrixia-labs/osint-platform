"""
Optional LLM analytical narrative pass for Pro Structural Briefs.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from analysis.pro_structural_compiler import build_dynamic_structural_title, synthesize_structural_title
from llm.client import generate_analysis
from llm.prompts import PRO_STRUCTURAL_TEXT_SHAPE_PROMPT
from reports.text_encoding import sanitize_unicode_text, sanitize_unicode_tree

logger = logging.getLogger(__name__)


def pro_structural_llm_shaping_enabled() -> bool:
    return os.getenv("ENABLE_PRO_STRUCTURAL_LLM_SHAPING", "true").lower() in ("true", "1", "yes")


def _apply_shaped_copy(context: Dict[str, Any], shaped: Dict[str, Any]) -> Dict[str, Any]:
    ctx = dict(context)
    narrative = _normalize_quant_narrative(shaped)
    if narrative:
        ctx["llm_narrative"] = narrative
        thesis = narrative.get("executive_thesis")
        if thesis:
            ctx.setdefault("executive_summary_override", thesis)
    return sanitize_unicode_tree(ctx)


def _normalize_information_integrity(raw: Any) -> Dict[str, Any]:
    """Validate and sanitize the information_integrity object from LLM output."""
    if not isinstance(raw, dict):
        return {}
    valid_levels = {"LOW", "MEDIUM", "HIGH"}
    level = str(raw.get("psyops_risk_level") or "").strip().upper()
    if level not in valid_levels:
        level = "LOW"
    divergence = raw.get("rhetoric_vs_reality_divergence")
    if isinstance(divergence, str):
        divergence = divergence.lower() in ("true", "1", "yes")
    divergence = bool(divergence)
    assessment = sanitize_unicode_text(str(raw.get("assessment_text") or "").strip())
    if not assessment:
        return {}
    return {
        "psyops_risk_level": level,
        "rhetoric_vs_reality_divergence": divergence,
        "assessment_text": assessment,
    }


def _normalize_wargaming(raw: Any) -> List[Dict[str, Any]]:
    """Validate and sanitize the scenario_wargaming array from LLM output."""
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        prob = item.get("probability_pct")
        desc = item.get("description")
        timeline = item.get("projected_timeline")
        if not (isinstance(title, str) and title.strip()):
            continue
        if not isinstance(prob, (int, float)):
            try:
                prob = int(prob)
            except (TypeError, ValueError):
                prob = 0
        out.append({
            "title": sanitize_unicode_text(str(title).strip()),
            "probability_pct": int(prob),
            "description": sanitize_unicode_text(str(desc or "").strip()),
            "projected_timeline": sanitize_unicode_text(str(timeline or "").strip()),
        })
    return out[:3]


def _normalize_quant_narrative(shaped: Dict[str, Any]) -> Dict[str, Any]:
    fields = (
        "executive_thesis",
        "ground_zero_drag",
        "smart_money_flow",
        "contagion_timeline",
        "market_translation",
    )
    out: Dict[str, Any] = {}
    for field in fields:
        value = shaped.get(field)
        if isinstance(value, str) and value.strip():
            out[field] = sanitize_unicode_text(value.strip())
    if len(out) != len(fields):
        return {}
    wargaming = _normalize_wargaming(shaped.get("scenario_wargaming"))
    if wargaming:
        out["scenario_wargaming"] = wargaming
    info_integrity = _normalize_information_integrity(shaped.get("information_integrity"))
    if info_integrity:
        out["information_integrity"] = info_integrity
    return out


def _top_items(items: Any, limit: int = 5) -> List[Any]:
    return list(items or [])[:limit] if isinstance(items, list) else []


def _build_llm_prompt_payload(ctx: Dict[str, Any], structured_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = structured_payload or {}
    matrix = payload.get("quantitative_evidence_matrix") or ctx.get("quantitative_evidence_matrix") or {}
    cascading = payload.get("cascading_impacts") or ctx.get("cascading_impacts") or {}
    market = payload.get("market_confirmation") or ctx.get("market_confirmation") or {}
    divergence = payload.get("divergence_check") or {}
    signal = payload.get("signal") or ctx.get("signal") or {}
    transmission = matrix.get("transmission") or ctx.get("quantitative_evidence")

    return sanitize_unicode_tree({
        "domain": payload.get("domain") or ctx.get("domain"),
        "brief_title": ctx.get("brief_title"),
        "signal": {
            "title": signal.get("title") or signal.get("target_label"),
            "topic": signal.get("topic"),
            "severity": signal.get("severity"),
            "trigger_type": signal.get("trigger_type"),
            "triggered_at": signal.get("triggered_at"),
            "intensity": signal.get("intensity"),
            "intelligence_score": signal.get("intelligence_score"),
            "fidelity_score": signal.get("fidelity_score"),
        },
        "choke_point": {
            "intensity": signal.get("intensity"),
            "fidelity_score": signal.get("fidelity_score"),
            "viscosity_proxy": signal.get("viscosity")
            or signal.get("viscosity_proxy")
            or matrix.get("viscosity_proxy"),
            "alert_intensity_stats": matrix.get("alert_intensity_stats"),
            "active_macro_pressure": _top_items(cascading.get("active_macro_pressure"), 5),
        },
        "primary_divergence_check": divergence,
        "market_confirmation": {
            "status": market.get("status"),
            "supply_driven": market.get("supply_driven"),
            "positive_movers": market.get("positive_movers"),
            "negative_movers": market.get("negative_movers"),
            "breakdown": _top_items(market.get("breakdown"), 4),
            "top_market_moves": _top_items(matrix.get("top_market_moves"), 5),
        },
        "cascading_impacts": {
            "tier_1_direct": _top_items(cascading.get("tier_1_direct"), 4),
            "tier_2_downstream": _top_items(cascading.get("tier_2_downstream"), 4),
            "tier_2_channels": _top_items(cascading.get("tier_2_channels"), 4),
            "tier_3_systemic": _top_items(cascading.get("tier_3_systemic"), 4),
        },
        "top_cascading_impact_lags": [
            {
                "source": transmission.get("source_series") or transmission.get("source"),
                "target": transmission.get("target_topic") or transmission.get("target"),
                "lag_days": transmission.get("lag_days"),
                "correlation": transmission.get("correlation"),
                "beta_log_return": transmission.get("beta_log_return") or transmission.get("beta"),
            }
        ] if isinstance(transmission, dict) and transmission.get("lag_days") is not None else [],
        "lead_lag_transmission": transmission,
        "top_macro_moves": _top_items(matrix.get("top_macro_moves"), 5),
        "watch_conditions": payload.get("watch_conditions") or ctx.get("watch_conditions_template"),
        "event_timeline_audit_sample": [
            {
                "timestamp": ev.get("timestamp"),
                "type": ev.get("type") or ev.get("role"),
                "title": ev.get("title"),
                "structural_correlation": ev.get("structural_correlation"),
            }
            for ev in _top_items(payload.get("event_timeline") or ctx.get("event_timeline"), 6)
            if isinstance(ev, dict)
        ],
    })


async def shape_pro_structural_context(
    context: Dict[str, Any],
    structured_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Rule-based title synthesis always runs; optional LLM pass writes a 5-part
    quantitative narrative when enabled.
    """
    draft_title = build_dynamic_structural_title(context)
    ctx = dict(context)
    ctx["brief_title"] = draft_title

    sig = ctx.get("signal") or {}
    if isinstance(sig, dict) and sig.get("title"):
        sig = {**sig, "title": synthesize_structural_title(sig.get("title", ""), ctx)}
        ctx["signal"] = sig

    timeline: List[dict] = []
    for ev in ctx.get("event_timeline") or []:
        if isinstance(ev, dict) and ev.get("title"):
            timeline.append({**ev, "title": sanitize_unicode_text(ev.get("title"))})
        else:
            timeline.append(ev)
    ctx["event_timeline"] = timeline
    ctx = sanitize_unicode_tree(ctx)

    if not pro_structural_llm_shaping_enabled():
        return ctx

    payload = _build_llm_prompt_payload(ctx, structured_payload)
    user_prompt = json.dumps(payload, ensure_ascii=False)

    try:
        shaped = await generate_analysis(PRO_STRUCTURAL_TEXT_SHAPE_PROMPT, user_prompt, is_batch=True)
        if isinstance(shaped, dict) and _normalize_quant_narrative(shaped):
            domain_id = ((ctx.get("domain") or {}).get("domain_id") or "unknown")
            logger.info("Pro structural LLM quant narrative applied for %s", domain_id)
            return _apply_shaped_copy(ctx, shaped)
    except Exception as exc:
        logger.warning("Pro structural LLM shaping failed: %s", exc)

    return ctx
