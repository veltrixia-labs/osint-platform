"""
Optional LLM text-shaping pass for Pro Structural Briefs (titles + timeline copy).
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
    title = sanitize_unicode_text(shaped.get("brief_title") or "")
    if title:
        ctx["brief_title"] = title

    summary = shaped.get("executive_summary")
    if isinstance(summary, str) and summary.strip():
        ctx.setdefault("executive_summary_override", sanitize_unicode_text(summary))

    timeline = list(ctx.get("event_timeline") or [])
    for patch in shaped.get("event_timeline") or []:
        if not isinstance(patch, dict):
            continue
        idx = patch.get("index")
        new_title = sanitize_unicode_text(patch.get("title") or "")
        if isinstance(idx, int) and 0 <= idx < len(timeline) and new_title:
            timeline[idx] = {**timeline[idx], "title": new_title}
    ctx["event_timeline"] = timeline

    sig = ctx.get("signal")
    if isinstance(sig, dict) and title:
        sig = {**sig, "title": title}
        ctx["signal"] = sig
    return sanitize_unicode_tree(ctx)


async def shape_pro_structural_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rule-based title synthesis always runs; optional LLM pass refines copy when enabled.
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

    payload = {
        "domain_id": (ctx.get("domain") or {}).get("domain_id"),
        "brief_title": ctx.get("brief_title"),
        "executive_summary": (ctx.get("predictive_forecast") or {}).get("headline"),
        "event_timeline": [
            {"index": i, "title": ev.get("title", "")}
            for i, ev in enumerate(ctx.get("event_timeline") or [])
            if isinstance(ev, dict)
        ],
    }
    user_prompt = json.dumps(payload, ensure_ascii=False)

    try:
        shaped = await generate_analysis(PRO_STRUCTURAL_TEXT_SHAPE_PROMPT, user_prompt, is_batch=True)
        if isinstance(shaped, dict) and shaped.get("brief_title"):
            logger.info("Pro structural LLM text shaping applied for %s", payload.get("domain_id"))
            return _apply_shaped_copy(ctx, shaped)
    except Exception as exc:
        logger.warning("Pro structural LLM shaping failed: %s", exc)

    return ctx
