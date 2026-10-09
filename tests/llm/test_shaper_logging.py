"""Every exit of the Pro brief narrative shaper must log why it has no narrative, and record the reason as
llm_narrative_status in the stored payload (vault audit §12.76(c)/(d), §12.82).

generate_analysis never raises; it returns None on any LLM failure. Before 2026-10-09 the None, non-dict and
incomplete cases fell through silently, and the brief was saved with a null narrative and no trace.
"""
import logging

import pytest

import llm.pro_structural_shaper as shp

FULL = {f: f"text for {f}" for f in shp._QUANT_FIELDS}
CTX = {"domain": {"domain_id": "energy_resource_risk"}}


@pytest.fixture
def shaper(monkeypatch):
    monkeypatch.setenv("ENABLE_PRO_STRUCTURAL_LLM_SHAPING", "true")
    monkeypatch.setattr(shp, "build_dynamic_structural_title", lambda ctx: "T")
    monkeypatch.setattr(shp, "_build_llm_prompt_payload", lambda ctx, sp: {})

    def returning(value=None, exc=None):
        async def fake_generate_analysis(*args, **kwargs):
            if exc is not None:
                raise exc
            return value
        monkeypatch.setattr(shp, "generate_analysis", fake_generate_analysis)
    return returning


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records
            if r.name == shp.logger.name and r.levelno == logging.WARNING]


async def test_none_result_is_logged(shaper, caplog):
    shaper(None)
    with caplog.at_level(logging.INFO, logger=shp.logger.name):
        ctx = await shp.shape_pro_structural_context(dict(CTX))
    assert "llm_narrative" not in ctx
    msgs = _warnings(caplog)
    assert len(msgs) == 1 and "no result for energy_resource_risk" in msgs[0]
    assert ctx["llm_narrative_status"] == "no_result"


async def test_non_dict_result_is_logged(shaper, caplog):
    shaper([FULL])
    with caplog.at_level(logging.INFO, logger=shp.logger.name):
        ctx = await shp.shape_pro_structural_context(dict(CTX))
    assert "llm_narrative" not in ctx
    msgs = _warnings(caplog)
    assert len(msgs) == 1 and "expected an object for energy_resource_risk, got list" in msgs[0]
    assert ctx["llm_narrative_status"] == "not_object"


async def test_incomplete_result_names_missing_fields(shaper, caplog):
    partial = dict(FULL, smart_money_flow="", market_translation=None)
    shaper(partial)
    with caplog.at_level(logging.INFO, logger=shp.logger.name):
        ctx = await shp.shape_pro_structural_context(dict(CTX))
    assert "llm_narrative" not in ctx
    msgs = _warnings(caplog)
    assert len(msgs) == 1 and "incomplete for energy_resource_risk" in msgs[0]
    assert "smart_money_flow" in msgs[0] and "market_translation" in msgs[0]
    assert "executive_thesis" not in msgs[0]
    assert ctx["llm_narrative_status"] == "incomplete"
    assert ctx["llm_narrative_missing"] == ["smart_money_flow", "market_translation"]


async def test_exception_is_logged_with_domain(shaper, caplog):
    shaper(exc=RuntimeError("boom"))
    with caplog.at_level(logging.INFO, logger=shp.logger.name):
        ctx = await shp.shape_pro_structural_context(dict(CTX))
    assert "llm_narrative" not in ctx
    msgs = _warnings(caplog)
    assert len(msgs) == 1 and "failed for energy_resource_risk: boom" in msgs[0]
    assert ctx["llm_narrative_status"] == "error"


async def test_complete_result_is_applied_without_warning(shaper, caplog):
    shaper(FULL)
    with caplog.at_level(logging.INFO, logger=shp.logger.name):
        ctx = await shp.shape_pro_structural_context(dict(CTX))
    assert ctx["llm_narrative"]["executive_thesis"] == "text for executive_thesis"
    assert ctx["llm_narrative_status"] == "applied"
    assert _warnings(caplog) == []


async def test_disabled_makes_no_call_and_no_warning(shaper, monkeypatch, caplog):
    shaper(None)
    monkeypatch.setenv("ENABLE_PRO_STRUCTURAL_LLM_SHAPING", "false")
    with caplog.at_level(logging.INFO, logger=shp.logger.name):
        ctx = await shp.shape_pro_structural_context(dict(CTX))
    assert "llm_narrative" not in ctx
    assert _warnings(caplog) == []
    # The path production runs since 2026-10-09: a deliberate null must say so.
    assert ctx["llm_narrative_status"] == "disabled"


def test_payload_carries_the_status():
    from reports.pro_structural_report_builder import build_pro_structural_report_payload
    p = build_pro_structural_report_payload(
        {"llm_narrative_status": "incomplete", "llm_narrative_missing": ["smart_money_flow"]})
    assert p["llm_narrative_status"] == "incomplete"
    assert p["llm_narrative_missing"] == ["smart_money_flow"]
    # A context that never passed through the shaper says so with None, not with a guess.
    assert build_pro_structural_report_payload({})["llm_narrative_status"] is None
