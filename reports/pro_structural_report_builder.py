"""
Pro Structural Report Builder.

Converts structured context (macro statistics and market data) into a 
human-readable Markdown report for Pro users.
"""

from datetime import datetime, timezone
from typing import Any, List, Optional, Dict
import math

MIN_EVENT_TIMELINE_ITEMS = 3
TARGET_EVENT_TIMELINE_ITEMS = 5

from reports.text_encoding import sanitize_unicode_tree
from analysis.pro_global_series import (
    MAX_MACRO_DISPLAY_CARDS,
    MIN_MACRO_DISPLAY_CARDS,
    energy_supply_driven_market_status,
    merge_relevance_maps,
    pad_macro_display_cards,
    relevance_display_name,
    select_quantitative_context_cards,
    trend_meaning_for_observation,
)

def build_pro_structural_report(context: dict) -> str:
    """
    Generates a full Markdown report based on the provided context.
    """
    context = _apply_macro_and_market_priorities(context)
    brief_title = sanitize_unicode_tree(context.get("brief_title") or "Structural Impact Brief")
    sections = [
        f"# {brief_title}",
        _build_executive_snapshot(context),
        _build_signal_brief(context),
        _build_market_relevance(context),
        _build_transmission_channels(context),
        _build_quantitative_context(context),
        _build_market_confirmation_section(context),
        _build_asset_sector_exposure(context),
        _build_watch_indicators(context),
        _build_balanced_interpretations(context),
        _build_cascading_impacts_section(context),
        _build_tail_risk_section(context),
        _build_quantitative_evidence_matrix_section(context),
        _build_data_notes(context)
    ]

    report = "\n\n".join(sections)
    report = _apply_compliance_guardrails(report)
    return _apply_institutional_tone_to_report(report)

def _build_executive_snapshot(ctx: dict) -> str:
    domain = ctx.get("domain", {})
    sig = ctx.get("signal") or {}
    s_ctx = ctx.get("structural_context", {})
    m_ctx = ctx.get("market_confirmation", {})
    watch_inds = ctx.get("watch_indicators", [])
    data_notes = ctx.get("data_notes", [])
    
    domain_name = domain.get("display_name", "N/A")
    sig_title = sig.get("title", "N/A")
    
    macro_obs = s_ctx.get("macro_observations", [])
    struct_pts = [f"{o['series_id']} ({format_percent(o.get('change_pct'))})" for o in macro_obs[:3]]
    struct_str = ", ".join(struct_pts) if struct_pts else "N/A"
    
    prices = m_ctx.get("latest_prices", [])
    market_pts = [f"{p['symbol']} ({format_percent(p.get('percent_change'))})" for p in prices[:3]]
    market_str = ", ".join(market_pts) if market_pts else "N/A"
    
    limitation = data_notes[0] if data_notes else "None detected"
    
    lines = [
        "## Executive Snapshot",
        "<div class=\"snapshot-grid\">",
        f"  <div class=\"snapshot-card\"><span class=\"snapshot-card-label\">Domain</span><span class=\"snapshot-card-value\">{domain_name}</span></div>",
        f"  <div class=\"snapshot-card\"><span class=\"snapshot-card-label\">Primary Signal</span><span class=\"snapshot-card-value\">{sig_title}</span></div>",
        f"  <div class=\"snapshot-card\"><span class=\"snapshot-card-label\">Structural Data</span><span class=\"snapshot-card-value\">{struct_str}</span></div>",
        f"  <div class=\"snapshot-card\"><span class=\"snapshot-card-label\">Market Pricing</span><span class=\"snapshot-card-value\">{market_str}</span></div>",
        f"  <div class=\"snapshot-card\"><span class=\"snapshot-card-label\">Watch Indicators</span><span class=\"snapshot-card-value\">{len(watch_inds)} Active</span></div>",
        f"  <div class=\"snapshot-card\"><span class=\"snapshot-card-label\">Primary Limitation</span><span class=\"snapshot-card-value\">{limitation}</span></div>",
        "</div>"
    ]
    return "\n".join(lines)

def _build_signal_brief(ctx: dict) -> str:
    sig = ctx.get("signal")
    domain = ctx.get("domain", {})
    
    lines = ["## 1. Signal & Market Relevance"]
    lines.append("<div class=\"signal-relevance-grid\">")
    
    # Left Column: Context
    lines.append("  <div class=\"signal-context\">")
    lines.append("    <h3>Signal Context</h3>")
    if sig:
        lines.append(f"    <p><strong>Alert:</strong> {sig.get('title', 'N/A')}<br>")
        lines.append(f"    <strong>Triggered At:</strong> {sig.get('triggered_at', 'N/A')}<br>")
        lines.append(f"    <strong>Analytical Question:</strong> {domain.get('primary_user_question', 'N/A')}</p>")
        
        news = sig.get("related_news", [])
        if news:
            lines.append("    <p><strong>Related Events:</strong><br>")
            for n in news[:3]:
                title = n.get("title", n.get("text", "Related Event"))
                url = n.get("url")
                lines.append(f"    <a href=\"{url}\" target=\"_blank\">{title}</a><br>" if url else f"    {title}<br>")
            lines.append("    </p>")
    lines.append("  </div>")
    
    # Right Column: Relevance
    lines.append("  <div class=\"market-relevance\">")
    lines.append("    <h3>Decision-Relevant Questions</h3>")
    lines.append("    <ul>")
    for q in domain.get("decision_relevant_questions", []):
        lines.append(f"      <li>{q}</li>")
    lines.append("    </ul>")
    lines.append("  </div>")
    
    lines.append("</div>")
    return "\n".join(lines)

def _build_market_relevance(ctx: dict) -> str:
    # Merged into _build_signal_brief
    return ""

def _build_transmission_channels(ctx: dict) -> str:
    channels = ctx.get("transmission_channels", [])
    lines = ["## 2. Transmission Channels"]
    if channels:
        lines.append("<div class=\"transmission-flow\">")
        for i, c in enumerate(channels):
            lines.append(f"  <div class=\"transmission-step\">{c}</div>")
            if i < len(channels) - 1:
                lines.append("  <div class=\"transmission-arrow\">→</div>")
        lines.append("</div>")
    else:
        lines.append("<p>No specific transmission channels defined for this domain.</p>")
    return "\n".join(lines)

def _build_quantitative_context(ctx: dict) -> str:
    s_ctx = ctx.get("structural_context", {})
    lines = ["## 3. Quantitative Context"]
    
    display_cards = s_ctx.get("macro_display_cards") or s_ctx.get("macro_observations", [])
    all_macro = s_ctx.get("macro_observations", [])

    if display_cards:
        lines.append("<div class=\"metric-card-grid\">")
        for o in display_cards[:MAX_MACRO_DISPLAY_CARDS]:
            val = format_value(o.get("latest_value"))
            change = format_percent(o.get("change_pct"))
            label = o.get("display_name") or o.get("series_id", "")
            lines.append("  <div class=\"metric-card\">")
            lines.append(f"    <div class=\"metric-label\">{label}</div>")
            lines.append(f"    <div class=\"metric-value\">{val}</div>")
            lines.append(f"    <div class=\"metric-label\">{change} (Lookback)</div>")
            meaning = o.get("trend_meaning")
            if meaning:
                lines.append(f"    <blockquote class=\"highlight-box\">{meaning}</blockquote>")
            lines.append("  </div>")
        lines.append("</div>")
    else:
        lines.append(
            "<p class=\"intel-body-text\">Quantitative cards are populated from domain structural "
            "matrices while external macro series sync completes.</p>"
        )

    # Raw Tables hidden in details
    lines.append("<details>")
    lines.append("<summary>Show raw macroeconomic tables</summary>")
    lines.append("<div class=\"u-m-top-1\">")
    
    # Macro Table
    lines.append("### Macro / Structural Observations")
    if all_macro:
        lines.append("| Series ID | Source | Latest Value | Date | % Change (Lookback) |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for o in all_macro:
            val = format_value(o.get("latest_value"))
            change = format_percent(o.get("change_pct"))
            lines.append(f"| {o['series_id']} | {o['source']} | {val} | {o['latest_date']} | {change} |")
    else:
        lines.append("No macro observations available.")

    # Trade Flows Table
    lines.append("\n### Trade Flows")
    flows = s_ctx.get("trade_flows", [])
    if flows:
        lines.append("| Reporter | Partner | Flow | Commodity | Value (USD) | Year |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for f in flows[:10]:
            val = compact_number(f.get("trade_value"))
            lines.append(f"| {f['reporter_name']} | {f['partner_name']} | {f['flow_type']} | {f['commodity_id']} | {val} | {f['year']} |")
    else:
        lines.append("No recent trade flow data found.")

    # Industry Stats Table
    lines.append("\n### Industry / Regional Stats")
    stats = s_ctx.get("industry_stats", [])
    if stats:
        lines.append("| Source | Dataset | Geo | Industry | Metric | Value | Year |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for s in stats[:10]:
            val = format_value(s.get("value"))
            lines.append(f"| {s['source']} | {s['dataset']} | {s['geo_name']} | {s['industry_name']} | {s['metric_name']} | {val} | {s['year']} |")
    else:
        lines.append("No industry statistics found.")
        
    lines.append("</div>")
    lines.append("</details>")
        
    return "\n".join(lines)

def _build_market_confirmation_section(ctx: dict) -> str:
    m_ctx = ctx.get("market_confirmation", {})
    lines = ["## 4. Market Confirmation"]
    
    prices = m_ctx.get("latest_prices", [])
    pos_movers = [p for p in prices if (p.get("percent_change") or 0) > 0.5]
    neg_movers = [p for p in prices if (p.get("percent_change") or 0) < -0.5]
    na_movers = [p for p in prices if p.get("percent_change") is None]
    
    status = m_ctx.get("status") or _compute_market_status(prices)
            
    # Market Summary Grid
    lines.append("<div class=\"market-summary-grid\">")
    lines.append(f"  <div class=\"market-status-card\"><div>Status</div><div class=\"metric-value\">{status}</div></div>")
    lines.append(f"  <div class=\"market-status-card\"><div>Positive Movers</div><div class=\"metric-value\">{len(pos_movers)}</div></div>")
    lines.append(f"  <div class=\"market-status-card\"><div>Negative Movers</div><div class=\"metric-value\">{len(neg_movers)}</div></div>")
    lines.append(f"  <div class=\"market-status-card\"><div>N/A</div><div class=\"metric-value\">{len(na_movers)}</div></div>")
    lines.append("</div>")
    
    lines.append("<details open>")
    lines.append("<summary>Market pricing table</summary>")
    lines.append("<div class=\"u-m-top-1\">")
    
    if prices:
        lines.append("| Symbol | Provider | Latest Close | Date | 30D Change | Class |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for p in prices:
            close = format_value(p.get("latest_close"))
            change = format_percent(p.get("percent_change"))
            lines.append(f"| **{p['symbol']}** | {p['provider']} | {close} | {p['latest_date']} | {change} | {p['asset_class']} |")
    else:
        lines.append("\n*Market confirmation data is not yet available for the instruments defined in this domain configuration.*")
        
    lines.append("</div>")
    lines.append("</details>")
        
    # Interpretation section
    lines.append("\n**Interpretation**:")
    if not prices:
        lines.append("Market confirmation remains incomplete due to missing price data for domain-specific instruments.")
    else:
        interp = []
        if na_movers:
            interp.append(f"Analysis is partially limited by {len(na_movers)} instruments showing N/A for 30D change (reference prices only).")
        
        if len(pos_movers) > len(prices) * 0.6:
            interp.append("Current market price action shows broad upward momentum, which may confirm positive structural adjustments.")
        elif len(neg_movers) > len(prices) * 0.6:
            interp.append("Market pricing indicates broad downward pressure, aligning with identified structural risks.")
        elif len(pos_movers) > 0 and len(neg_movers) > 0:
            interp.append("Market confirmation is mixed; structural signals have not yet consolidated into a singular directional trend.")
        else:
            interp.append("Market has not confirmed severe stress; price action remains within historical range for most tracked instruments.")
            
        lines.append("<blockquote class=\"highlight-box\">" + " ".join(interp) + "</blockquote>")

    return "\n".join(lines)

def _build_asset_sector_exposure(ctx: dict) -> str:
    domain = ctx.get("domain", {})
    lines = ["## 5. Asset / Sector Exposure"]
    
    exposure = ctx.get("exposure_targets", [])
    assets = domain.get("primary_asset_classes", [])
    
    all_chips = exposure + assets
    
    if all_chips:
        lines.append("<div class=\"exposure-chip-grid\">")
        for chip in all_chips:
            lines.append(f"  <span class=\"exposure-chip\">{chip}</span>")
        lines.append("</div>")
    else:
        lines.append("<p>No exposure targets defined.</p>")
            
    lines.append("<p style=\"font-size: 0.8rem; color: var(--text-secondary);\">Note: This list identifies potential correlation points and sensitivity targets. It does not constitute a recommendation to trade.</p>")
    return "\n".join(lines)

def _build_watch_indicators(ctx: dict) -> str:
    indicators = ctx.get("watch_indicators", [])
    lines = ["## 6. Watch Indicators"]
    if indicators:
        lines.append("<div class=\"watch-indicator-grid\">")
        for ind in indicators:
            val = format_value(ind.get("latest_value"))
            lines.append("  <div class=\"watch-indicator-card\">")
            lines.append(f"    <div class=\"wi-header\">{ind['indicator']}</div>")
            lines.append(f"    <div class=\"wi-source\">{ind['source']} | Latest: <strong>{val}</strong></div>")
            lines.append(f"    <div style=\"font-size:0.9rem; margin:0.5rem 0;\"><strong>Why it matters:</strong> {ind['why_it_matters']}</div>")
            lines.append("    <div style=\"font-size:0.85rem; border-left:2px solid var(--success); padding-left:0.5rem;\">⬆ {ind['upward_interpretation']}</div>".replace("{ind['upward_interpretation']}", ind['upward_interpretation']))
            lines.append("    <div style=\"font-size:0.85rem; border-left:2px solid var(--danger); padding-left:0.5rem;\">⬇ {ind['downward_interpretation']}</div>".replace("{ind['downward_interpretation']}", ind['downward_interpretation']))
            if ind.get("limitation"):
                lines.append(f"    <div style=\"font-size:0.75rem; color:var(--text-secondary); margin-top:0.25rem;\"><em>Limitation: {ind['limitation']}</em></div>")
            lines.append("  </div>")
        lines.append("</div>")
    else:
        lines.append("<p>No watch indicators defined.</p>")
    return "\n".join(lines)

def _build_balanced_interpretations(ctx: dict) -> str:
    interp = ctx.get("balanced_interpretations", {})
    lines = ["## 7. Balanced Interpretations"]
    
    if interp:
        lines.append("<div class=\"balanced-view-grid\">")
        lines.append("  <div class=\"balanced-view-card\">")
        lines.append("    <h3 style=\"color: var(--success);\">Stability / Resilience View</h3>")
        lines.append(f"    <p>{interp.get('stability_view', 'N/A')}</p>")
        lines.append("  </div>")
        lines.append("  <div class=\"balanced-view-card\">")
        lines.append("    <h3 style=\"color: var(--danger);\">Volatility / Stress View</h3>")
        lines.append(f"    <p>{interp.get('volatility_view', 'N/A')}</p>")
        lines.append("  </div>")
        lines.append("</div>")
        
        lines.append(f"\n**Market Confirmation View**: {interp.get('market_confirmation_view', 'N/A')}")
        
        cond = interp.get("invalidating_conditions", [])
        if cond:
            lines.append("\n**Invalidating Conditions (Watch for these to reverse the thesis)**:")
            for c in cond:
                lines.append(f"- {c}")
    else:
        lines.append("<p>Interpretations not available.</p>")
    return "\n".join(lines)

def _build_data_notes(ctx: dict) -> str:
    lines = []
    lines.append("<details style=\"margin-top: 2rem;\">")
    lines.append("<summary>Data Notes & Coverage Limitations</summary>")
    lines.append("<div class=\"u-m-top-1\">")
    
    lines.append("### Methodology & Legal Disclaimers")
    lines.append("<ul>")
    lines.append("<li>This report uses public structural data and delayed or reference market data.</li>")
    lines.append("<li>No LLM forecast, scenario generation, or deterministic prediction is included.</li>")
    lines.append("<li><strong>This is not investment advice and does not provide buy/sell recommendations.</strong></li>")
    lines.append("<li>Market data may be delayed and subject to provider licensing limitations.</li>")
    lines.append("</ul>")
    
    notes = ctx.get("data_notes", [])
    if notes:
        lines.append("### Coverage Limitations")
        lines.append("<ul>")
        for n in notes:
            lines.append(f"<li>{n}</li>")
        lines.append("</ul>")
        
    lines.append("</div>")
    lines.append("</details>")
            
    freshness = ctx.get("data_freshness", {})
    if freshness.get("last_update"):
        lines.append(f"\n<div class=\"data-freshness-meta\">Data Freshness Index: {freshness['last_update']}</div>")
        
    return "\n".join(lines)

def _apply_compliance_guardrails(text: str) -> str:
    """Ensures no prohibited promotional language is used."""
    replacements = {
        "we recommend buying": "exposure targets include",
        "we recommend selling": "potential sensitivity in",
        "price target": "current reference level",
        "will definitely": "historically correlates with",
        "guaranteed return": "performance profile"
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
        text = text.replace(old.capitalize(), new.capitalize())
    return text


def _apply_institutional_tone_to_report(text: str) -> str:
    """Strip dramatic adjectives across the whole rendered markdown."""
    from analysis.pro_structural_compiler import enforce_institutional_tone
    return enforce_institutional_tone(text)


def _build_cascading_impacts_section(ctx: dict) -> str:
    """
    Section 8 — three-tier cascading impact analysis.
    1st-order: direct exposure (sensitivity == high)
    2nd-order: downstream channels + medium-sensitivity targets
    3rd-order: systemic spillover to adjacent domains
    """
    ci = ctx.get("cascading_impacts") or {}
    lines = ["## 8. Cascading Impacts"]

    tier1 = ci.get("tier_1_direct") or []
    tier2 = ci.get("tier_2_downstream") or []
    tier2_ch = ci.get("tier_2_channels") or []
    tier3 = ci.get("tier_3_systemic") or []
    macro_pressure = ci.get("active_macro_pressure") or []

    if not (tier1 or tier2 or tier3):
        lines.append("<p class=\"intel-body-text\">No cascading impacts derivable from current domain configuration.</p>")
        return "\n".join(lines)

    lines.append("<p class=\"intel-body-text\">Second- and third-order systemic effects mapped from domain exposure data and active macro pressure. Each tier is grounded in `exposure_matrix_details` and observed structural moves; no narrative speculation is included.</p>")

    # Tier 1
    lines.append("\n### 1st-Order — Direct Exposure")
    if tier1:
        lines.append("| Target | Transmission Mechanism | Rationale |")
        lines.append("| :--- | :--- | :--- |")
        for row in tier1:
            target = row.get("target") or "—"
            mech = row.get("transmission") or "—"
            rationale = row.get("rationale") or "—"
            lines.append(f"| {target} | {mech} | {rationale} |")
    else:
        lines.append("_No high-sensitivity direct targets recorded for this domain._")

    # Tier 2
    lines.append("\n### 2nd-Order — Downstream Propagation")
    if tier2:
        lines.append("| Target | Transmission Mechanism | Sensitivity |")
        lines.append("| :--- | :--- | :--- |")
        for row in tier2:
            lines.append(
                f"| {row.get('target') or '—'} | {row.get('transmission') or '—'} "
                f"| {row.get('sensitivity') or '—'} |"
            )
    if tier2_ch:
        lines.append("\n**Indirect channels:**")
        for ch in tier2_ch:
            lines.append(f"- {ch.get('channel')} — {ch.get('note')}")

    # Tier 3
    lines.append("\n### 3rd-Order — Systemic Spillover")
    if tier3:
        for row in tier3:
            spillover = row.get("spillover_domain") or "—"
            mech = row.get("mechanism") or "—"
            lines.append(f"- **{spillover}** — {mech}")
    else:
        lines.append("_No cross-domain spillover map registered._")

    # Active macro pressure reinforcing the cascade
    if macro_pressure:
        lines.append("\n### Active Macro Pressure (≥3% lookback)")
        lines.append("| Series | Label | Change |")
        lines.append("| :--- | :--- | :--- |")
        for m in macro_pressure:
            chg = m.get("change_pct")
            chg_s = f"{chg:+.2f}%" if isinstance(chg, (int, float)) else "—"
            lines.append(f"| {m.get('series_id') or '—'} | {m.get('display_name') or '—'} | {chg_s} |")

    return "\n".join(lines)


def _build_tail_risk_section(ctx: dict) -> str:
    """Section 9 — Tail-Risk & Contrarian Scenarios."""
    scenarios = ctx.get("tail_risk_scenarios") or []
    lines = ["## 9. Tail-Risk & Contrarian Scenarios"]
    if not scenarios:
        lines.append("<p class=\"intel-body-text\">No contrarian scenarios derivable from current configuration and observed data.</p>")
        return "\n".join(lines)

    lines.append("<p class=\"intel-body-text\">Low-probability, high-impact paths that would invalidate or accelerate the base case. Each entry is sourced either from domain `balanced_interpretations.invalidating_conditions`, extreme macro moves (≥5% lookback), or short-lag high-correlation transmission detected by the quantitative engine.</p>")

    lines.append("\n| Scenario | Probability | Impact | Type | Source |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")
    for sc in scenarios:
        scenario_txt = sc.get("scenario") or "—"
        prob = sc.get("probability") or "—"
        impact = sc.get("impact") or "—"
        s_type = (sc.get("type") or "—").replace("_", " ")
        source = sc.get("source") or "—"
        lines.append(f"| {scenario_txt} | {prob} | {impact} | {s_type} | `{source}` |")

    return "\n".join(lines)


def _build_quantitative_evidence_matrix_section(ctx: dict) -> str:
    """Section 10 — Quantitative Evidence Matrix (the exact numbers behind the brief)."""
    matrix = ctx.get("quantitative_evidence_matrix") or {}
    lines = ["## 10. Quantitative Evidence Matrix"]
    if not matrix:
        lines.append("<p class=\"intel-body-text\">No quantitative evidence available for this period.</p>")
        return "\n".join(lines)

    lines.append("<p class=\"intel-body-text\">Exact numeric inputs supporting the narrative. All correlations are clipped to [-1, 1]; betas are computed on log-return residuals at the aligned peak lag.</p>")

    # Transmission block
    tx = matrix.get("transmission")
    if tx:
        lag = tx.get("lag_days")
        lag_s = f"{lag:+d}" if isinstance(lag, int) else "—"
        corr = tx.get("correlation")
        corr_s = f"{corr:+.3f}" if isinstance(corr, (int, float)) else "—"
        beta = tx.get("beta_log_return")
        beta_s = f"{beta:+.4f}" if isinstance(beta, (int, float)) else "—"
        lines.append("\n### Macro → Topic Transmission")
        lines.append("| Metric | Value |")
        lines.append("| :--- | :--- |")
        lines.append(f"| Source series | `{tx.get('source_series') or '—'}` |")
        lines.append(f"| Target topic | `{tx.get('target_topic') or '—'}` |")
        lines.append(f"| Lag (days) | **{lag_s}** |")
        lines.append(f"| Correlation (clipped) | **{corr_s}** ({tx.get('correlation_strength')}) |")
        lines.append(f"| β (log-return) | **{beta_s}** |")
        lines.append(f"| Sample size | {tx.get('sample_size') or '—'} daily points |")
        lines.append(f"| Inverse scan | {'enabled (±lag)' if tx.get('include_inverse') else 'forward only (+lag)'} |")
        lines.append(f"| Methodology | {tx.get('methodology') or '—'} |")

    # Top macro moves
    macro_rows = matrix.get("top_macro_moves") or []
    if macro_rows:
        lines.append("\n### Top Structural Moves (by |Δ%|)")
        lines.append("| Series | Label | Latest | Lookback Δ |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for m in macro_rows:
            chg = m.get("change_pct")
            chg_s = f"{chg:+.2f}%" if isinstance(chg, (int, float)) else "—"
            lines.append(
                f"| `{m.get('series_id') or '—'}` | {m.get('display_name') or '—'} "
                f"| {format_value(m.get('latest_value'))} | **{chg_s}** |"
            )

    # Top market moves
    market_rows = matrix.get("top_market_moves") or []
    if market_rows:
        lines.append("\n### Top Market Moves (by |Δ%|)")
        lines.append("| Symbol | Class | Latest Close | Δ |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for p in market_rows:
            chg = p.get("percent_change")
            chg_s = f"{chg:+.2f}%" if isinstance(chg, (int, float)) else "—"
            lines.append(
                f"| `{p.get('symbol') or '—'}` | {p.get('asset_class') or '—'} "
                f"| {format_value(p.get('latest_close'))} | **{chg_s}** |"
            )

    # Alert intensity stats
    stats = matrix.get("alert_intensity_stats")
    if stats:
        lines.append("\n### Alert Intensity (Related Events)")
        lines.append("| Metric | Value |")
        lines.append("| :--- | :--- |")
        lines.append(f"| Sample count | {stats.get('count')} |")
        lines.append(f"| Peak intensity | {stats.get('max')} |")
        lines.append(f"| Mean intensity | {stats.get('mean')} |")

    return "\n".join(lines)

# --- Format Helpers ---

def format_value(val: Any) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, (int, float)):
        # If very small, use more decimals
        if 0 < abs(val) < 0.01:
            return f"{val:.6f}"
        return f"{val:,.2f}"
    return str(val)

def format_percent(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    prefix = "+" if val > 0 else ""
    return f"{prefix}{val:.2f}%"

def compact_number(val: Any) -> str:
    if val is None or not isinstance(val, (int, float)):
        return "N/A"
    if val >= 1_000_000_000:
        return f"{val / 1_000_000_000:.2f}B"
    if val >= 1_000_000:
        return f"{val / 1_000_000:.2f}M"
    if val >= 1_000:
        return f"{val / 1_000:.2f}K"
    return f"{val:.2f}"


def _timeline_supporting_sources(entry: dict) -> List[dict]:
    """Normalize evidence rows for the Source Evidence modal (url/link aliases)."""
    existing = entry.get("supporting_sources")
    if isinstance(existing, list) and existing:
        normalized: List[dict] = []
        for row in existing:
            if not isinstance(row, dict):
                continue
            url = row.get("url") or row.get("link") or row.get("source_url")
            title = (
                row.get("title")
                or row.get("headline")
                or entry.get("title")
                or "Source Signal"
            )
            domain = row.get("domain") or row.get("type") or entry.get("source") or "OSINT"
            item = {"title": str(title), "domain": str(domain)}
            if url:
                item["url"] = str(url).strip()
            normalized.append(item)
        if normalized:
            return normalized

    title = (entry.get("title") or "Timeline event").strip()
    source_name = entry.get("source_name") or entry.get("source") or "OSINT"
    url = entry.get("source_url") or entry.get("url") or entry.get("link")
    if url:
        url_s = str(url).strip()
        if url_s:
            return [{"title": title, "url": url_s, "domain": str(source_name)}]
    if title:
        return [{"title": title, "domain": str(source_name)}]
    return []


def _normalize_timeline_entry(item: dict) -> dict:
    """Fixed schema for UI: alert_id, source_url, type/role, supporting_sources."""
    out = dict(item)
    aid = out.get("alert_id")
    if aid is not None:
        s = str(aid).strip()
        out["alert_id"] = s or None
    else:
        out["alert_id"] = None
    url = out.get("source_url") or out.get("url") or out.get("link")
    if url is not None:
        s = str(url).strip()
        out["source_url"] = s or None
    else:
        out["source_url"] = None
    role = out.get("role") or out.get("type") or "context"
    out["role"] = role
    out["type"] = out.get("type") or role
    out.setdefault("title", "")
    snippet = out.get("evidence_text") or out.get("summary") or out.get("raw_text")
    if snippet and not out.get("evidence_text"):
        out["evidence_text"] = str(snippet).strip()
    out["source_name"] = out.get("source_name") or out.get("source") or "OSINT"
    out["supporting_sources"] = _timeline_supporting_sources(out)
    out["evidence_actionable"] = bool(
        out["alert_id"] or out["source_url"] or out["supporting_sources"]
    )
    return out


def _normalize_event_timeline(timeline: List[dict]) -> List[dict]:
    return [_normalize_timeline_entry(item) for item in timeline]


def _finalize_event_timeline_for_payload(
    event_timeline: List[dict],
    related_events: List[dict],
    signal: Optional[dict],
) -> List[dict]:
    """
    Merge correlated timeline rows only (no blind append of unrelated alert logs).
    """
    from analysis.pro_structural_context import _assign_timeline_types
    from analysis.pro_structural_compiler import filter_correlated_timeline_events

    timeline = [dict(item) for item in event_timeline]
    seen = {(e.get("alert_id"), e.get("title")) for e in timeline}
    for ev in related_events or []:
        if ev.get("structural_correlation") is not None and float(ev["structural_correlation"]) < 0.22:
            continue
        key = (ev.get("alert_id"), ev.get("title"))
        if key not in seen:
            timeline.append(dict(ev))
            seen.add(key)

    trigger_alert_id = (signal or {}).get("alert_id")
    typed = _assign_timeline_types(timeline, trigger_alert_id)
    return _normalize_event_timeline(filter_correlated_timeline_events(typed))


def _ensure_event_timeline_floor(
    timeline: List[dict],
    *,
    sig: dict,
    s_ctx: dict,
    m_ctx: dict,
    domain: dict,
    related_events: List[dict],
    relevance_map: Optional[dict] = None,
) -> List[dict]:
    """
    Enrich timeline with correlated macro/market shifts only (no synthetic filler rows).
    """
    from analysis.pro_structural_context import _assign_timeline_types

    out: List[dict] = [dict(item) for item in timeline]
    seen_titles: set[str] = {(e.get("title") or "").strip().lower() for e in out if e.get("title")}

    def _append(entry: dict) -> None:
        title = (entry.get("title") or "").strip()
        if not title:
            return
        key = title.lower()
        if key in seen_titles:
            return
        out.append(entry)
        seen_titles.add(key)

    for ev in related_events or []:
        if len(out) >= TARGET_EVENT_TIMELINE_ITEMS:
            break
        _append(
            {
                **ev,
                "type": ev.get("type") or "context",
                "role": ev.get("role") or "context",
            }
        )

    from analysis.pro_structural_compiler import structural_correlation_score

    relevance = relevance_map or {}
    macro_vocab = {"phrases": set(), "series_ids": set(relevance.keys()) if relevance else set()}
    for obs in (s_ctx.get("macro_observations") or s_ctx.get("macro_display_cards") or [])[:10]:
        if len(out) >= TARGET_EVENT_TIMELINE_ITEMS:
            break
        chg = obs.get("change_pct")
        if chg is None:
            continue
        label = obs.get("display_name") or obs.get("series_id") or "Macro series"
        sid = obs.get("series_id", "")
        title = f"Structural data shift: {label} ({chg:+.2f}% lookback)"
        coeff = structural_correlation_score(title, macro_vocab)
        if coeff < 0.18 and sid not in (relevance or {}):
            continue
        _append(
            {
                "timestamp": obs.get("latest_date"),
                "title": title,
                "source": "macro_data",
                "source_url": None,
                "location_label": None,
                "type": "context",
                "role": "context",
                "series_id": sid,
                "structural_correlation": round(max(coeff, 0.35), 3),
            }
        )

    for price in (m_ctx.get("latest_prices") or [])[:8]:
        if len(out) >= TARGET_EVENT_TIMELINE_ITEMS:
            break
        pct = price.get("percent_change")
        sym = price.get("symbol") or "Instrument"
        if pct is None:
            continue
        if relevance and sym not in relevance:
            continue
        _append(
            {
                "timestamp": None,
                "title": f"Market confirmation: {sym} {pct:+.2f}% session move",
                "source": "market_data",
                "source_url": None,
                "location_label": None,
                "type": "market_reaction",
                "role": "market_reaction",
            }
        )

    if sig.get("title"):
        _append(
            {
                "timestamp": sig.get("triggered_at"),
                "title": sig.get("title"),
                "alert_id": sig.get("alert_id"),
                "source": "primary_signal",
                "source_url": sig.get("source_url"),
                "location_label": None,
                "type": "trigger",
                "role": "trigger",
            }
        )

    def _sort_key(item: dict) -> tuple:
        ts = item.get("timestamp")
        if ts:
            return (0, str(ts))
        return (1, item.get("title") or "")

    out.sort(key=_sort_key)
    trigger_alert_id = sig.get("alert_id")
    from analysis.pro_structural_compiler import filter_correlated_timeline_events

    typed = _assign_timeline_types(out, trigger_alert_id)
    filtered = filter_correlated_timeline_events(typed)
    return _normalize_event_timeline(filtered[:TARGET_EVENT_TIMELINE_ITEMS])


def _compute_market_status(prices: List[dict]) -> str:
    # Only current prices carry a market signal. Records predating the is_stale
    # field (stored payloads) lack the key and default to fresh, preserving old
    # behaviour.
    fresh = [p for p in prices if not p.get("is_stale")]
    if not fresh:
        return "Limited"
    pos_movers = [p for p in fresh if (p.get("percent_change") or 0) > 0.5]
    neg_movers = [p for p in fresh if (p.get("percent_change") or 0) < -0.5]
    if len(pos_movers) > len(fresh) * 0.6 or len(neg_movers) > len(fresh) * 0.6:
        return "Confirming"
    if len(pos_movers) > 0 and len(neg_movers) > 0:
        return "Mixed"
    return "Divergent"


def _apply_macro_and_market_priorities(context: dict) -> dict:
    """Reorder macro cards and apply energy supply-driven market status override."""
    from analysis.pro_domain_config import get_pro_domain_config

    ctx = dict(context)
    domain_id = ctx.get("domain", {}).get("domain_id", "")
    relevance_raw = ctx.get("relevance_map", {})
    if relevance_raw and not isinstance(next(iter(relevance_raw.values()), None), dict):
        relevance_map = merge_relevance_maps(relevance_raw)
    else:
        relevance_map = relevance_raw or merge_relevance_maps({})

    s_ctx = dict(ctx.get("structural_context", {}))
    m_ctx = dict(ctx.get("market_confirmation", {}))

    enriched: List[dict] = []
    for obs in s_ctx.get("macro_observations", []):
        entry = dict(obs)
        sid = entry.get("series_id", "")
        entry["display_name"] = relevance_display_name(relevance_map, sid)
        entry["trend_meaning"] = trend_meaning_for_observation(
            relevance_map, sid, entry.get("change_pct")
        )
        enriched.append(entry)

    config = get_pro_domain_config(domain_id) or {}
    structural_data = config.get("structural_data", {})
    display_cards = select_quantitative_context_cards(
        enriched, domain_id, structural_data, limit=MAX_MACRO_DISPLAY_CARDS
    )
    picked = {c["series_id"] for c in display_cards}
    s_ctx["macro_display_cards"] = display_cards
    s_ctx["macro_observations"] = display_cards + [
        o for o in enriched if o.get("series_id") not in picked
    ]

    prices = m_ctx.get("latest_prices", [])
    status = _compute_market_status(prices)
    supply_status = energy_supply_driven_market_status(domain_id, enriched)
    if supply_status:
        status = supply_status
        m_ctx["supply_driven"] = True
    else:
        m_ctx["supply_driven"] = False
    m_ctx["status"] = status

    ctx["structural_context"] = s_ctx
    ctx["market_confirmation"] = m_ctx
    ctx["relevance_map"] = relevance_map
    return ctx


def build_pro_structural_report_payload(context: dict) -> dict:
    """
    Extracts structured payload for the Intelligence Report UI.
    Includes signal classification, event timeline, market breakdown,
    divergence check, watch conditions, exposure matrix, and coverage matrix.
    All analysis is rule-based / heuristic — no LLM dependency.
    """
    context = _apply_macro_and_market_priorities(context)
    domain = context.get("domain", {})
    sig = context.get("signal") or {}
    s_ctx = context.get("structural_context", {})
    m_ctx = context.get("market_confirmation", {})
    prices = m_ctx.get("latest_prices", [])
    
    pos_movers = [p for p in prices if (p.get("percent_change") or 0) > 0.5]
    neg_movers = [p for p in prices if (p.get("percent_change") or 0) < -0.5]
    na_movers = [p for p in prices if p.get("percent_change") is None]
    
    status = m_ctx.get("status") or _compute_market_status(prices)
    freshness = context.get("data_freshness", {})

    # --- 1. Signal Classification (from domain template) ---
    sig_class = context.get("signal_classification_template", {})

    # --- 2. Event Timeline (alerts + news, with UI types) ---
    event_timeline = _finalize_event_timeline_for_payload(
        context.get("event_timeline", []),
        context.get("related_events", []),
        sig,
    )
    event_timeline = _ensure_event_timeline_floor(
        event_timeline,
        sig=sig,
        s_ctx=s_ctx,
        m_ctx=m_ctx,
        domain=domain,
        related_events=context.get("related_events", []),
        relevance_map=context.get("relevance_map"),
    )

    # --- 3. Relevance Map (from domain config) ---
    relevance_map = context.get("relevance_map", {})

    # --- 4. Market Confirmation Breakdown by group ---
    market_group_map = context.get("market_group_map", {})
    market_group_interp = context.get("market_group_interpretation", {})
    breakdown = _build_market_breakdown(prices, market_group_map, market_group_interp)

    # --- 4.5. Coverage Matrix (heuristic based on data counts) ---
    coverage_matrix = _build_coverage_matrix(s_ctx, m_ctx, event_timeline, sig)

    # --- 5. Divergence Check (heuristic) ---
    divergence_check = _build_divergence_check(s_ctx, status, freshness, prices, coverage_matrix)

    # --- 6. Watch Conditions (from domain template) ---
    watch_cond = context.get("watch_conditions_template", {})

    # --- 7. Exposure Matrix (from domain config) ---
    exposure_matrix = context.get("exposure_matrix_details", [])

    # Coverage matrix already computed above

    # --- 9. Geo Context ---
    geo_context = _build_geo_context(sig, event_timeline)

    # --- 10. Unresolved Signals ---
    unresolved = _build_unresolved_signals(status, coverage_matrix, divergence_check)

    # --- 11. Executive Summary + Key Findings (auto-generated) ---
    exec_summary, key_findings = _build_executive_summary(
        domain, sig, sig_class, status, coverage_matrix, divergence_check, breakdown, geo_context
    )
    predictive = context.get("predictive_forecast") or {}
    title_override = context.get("executive_summary_override")
    if isinstance(title_override, str) and title_override.strip():
        exec_summary = title_override
    elif predictive.get("alert_cluster_depleted") and predictive.get("headline"):
        exec_summary = f"{predictive['headline']} {exec_summary}"
        for vec in (predictive.get("risk_vectors") or [])[:3]:
            if vec not in key_findings:
                key_findings.append(vec)
    if m_ctx.get("supply_driven"):
        key_findings = [
            "Physical crude up with US inventory draw — supply-driven confirmation",
            *key_findings,
        ]

    # Systemic Fragility: surface a phase-transition warning at the top of
    # key findings when both criticality components fire.
    sf = context.get("systemic_fragility") or {}
    if sf.get("phase_transition_warning"):
        e_idx = sf.get("entropy_index", 0)
        v_coef = sf.get("viscosity_coefficient", 0)
        key_findings = [
            (f"PHASE TRANSITION WARNING: entropy={e_idx:.3f} & "
             f"viscosity={v_coef:.3f} both critical — regime break risk elevated."),
            *key_findings,
        ]

    # Strip dramatic adjectives from the institutional-grade narrative outputs.
    from analysis.pro_structural_compiler import enforce_institutional_tone as _tone
    exec_summary = _tone(exec_summary)
    key_findings = [_tone(f) for f in key_findings]

    enriched_macro = s_ctx.get("macro_observations", [])
    macro_display_cards = s_ctx.get("macro_display_cards", enriched_macro[:6])
    relevance_map_payload = {
        sid: relevance_display_name(relevance_map, sid) for sid in relevance_map
    }

    analysis_generated_at = (
        context.get("analysis_generated_at")
        or datetime.now(timezone.utc).isoformat()
    )

    payload = {
        "payload_schema_version": "pro_structural_v3",
        "generator": "reports.pro_structural_report_builder",
        "brief_title": sanitize_unicode_tree(context.get("brief_title") or ""),
        "analysis_generated_at": analysis_generated_at,
        "force_rebuild": context.get("force_rebuild", True),
        "realtime_mode": context.get("realtime_mode", True),
        "alert_cluster_window_hours": context.get("alert_cluster_window_hours", 24),
        "alert_reignite_factor": context.get("alert_reignite_factor", 1.5),
        "predictive_forecast": context.get("predictive_forecast"),
        # Pro-grade institutional sections.
        "cascading_impacts": context.get("cascading_impacts"),
        "tail_risk_scenarios": context.get("tail_risk_scenarios"),
        "quantitative_evidence_matrix": context.get("quantitative_evidence_matrix"),
        "quantitative_evidence": context.get("quantitative_evidence"),
        # Systemic Fragility Engine (Shannon entropy + kinematic viscosity).
        # Surfaces entropy_index / viscosity_coefficient / phase_transition_warning
        # for both the LLM shaper and the frontend gauge.
        "systemic_fragility": context.get("systemic_fragility"),
        # Spatial Contagion (Sovereign Geo-Engine).
        # nodes[] (epicenter + affected) with lat/lon/impact_score, edges[]
        # linking the epicenter to each affected location with entropy-derived
        # intensity. Powers the Interactive Map in the Pro dashboard.
        "spatial_contagion": context.get("spatial_contagion"),
        "domain": {
            "domain_id": domain.get("domain_id"),
            "display_name": domain.get("display_name"),
            "primary_user_question": domain.get("primary_user_question")
        },
        "signal": {
            "title": sig.get("title"),
            "triggered_at": sig.get("triggered_at"),
            "severity": sig.get("severity"),
            "trigger_type": sig.get("trigger_type"),
            "target_label": sig.get("target_label"),
            "intensity": sig.get("intensity"),
            "intelligence_score": sig.get("intelligence_score"),
            "fidelity_score": sig.get("fidelity_score"),
            "location_lat": sig.get("location_lat"),
            "location_lng": sig.get("location_lng"),
            "related_news": sig.get("related_news", [])
        },
        "executive_summary": exec_summary,
        "key_findings": key_findings,
        "llm_narrative": context.get("llm_narrative"),
        "signal_classification": sig_class,
        "event_timeline": event_timeline,
        "structural_context": {
            "macro_observations": enriched_macro,
            "macro_display_cards": macro_display_cards,
            "trade_flows": s_ctx.get("trade_flows", []),
            "industry_stats": s_ctx.get("industry_stats", [])
        },
        "relevance_map": relevance_map_payload,
        "relevance_map_detail": relevance_map,
        "market_confirmation": {
            "latest_prices": prices,
            "status": status,
            "supply_driven": m_ctx.get("supply_driven", False),
            "positive_movers": len(pos_movers),
            "negative_movers": len(neg_movers),
            "limited_instruments": len(na_movers),
            "breakdown": breakdown
        },
        "divergence_check": divergence_check,
        "unresolved_signals": unresolved,
        "watch_indicators": context.get("watch_indicators", []),
        "watch_conditions": watch_cond,
        "transmission_flow": context.get("transmission_channels", []),
        "exposure_targets": context.get("exposure_targets", []),
        "exposure_matrix": exposure_matrix,
        "balanced_interpretations": context.get("balanced_interpretations", {}),
        "coverage_matrix": coverage_matrix,
        "geo_context": geo_context,
        "data_notes": {
            "freshness": freshness.get("last_update"),
            "coverage_limitations": context.get("data_notes", []),
        }
    }
    return sanitize_unicode_tree(payload)


def _build_market_breakdown(prices: list, group_map: dict, interp_map: dict) -> list:
    """
    Group market instruments by asset group and determine per-group status
    using domain-specific interpretation from market_group_interpretation config.
    """
    groups: dict = {}
    for p in prices:
        symbol = p.get("symbol", "")
        mapping = group_map.get(symbol)
        if not mapping:
            continue
        group_name = mapping["group"]
        order = mapping.get("order", 99)
        if group_name not in groups:
            groups[group_name] = {"group": group_name, "order": order, "instrument_details": [], "changes": []}
        pct = p.get("percent_change")
        groups[group_name]["instrument_details"].append({"symbol": symbol, "percent_change": pct})
        if pct is not None:
            groups[group_name]["changes"].append(pct)

    result = []
    for g in sorted(groups.values(), key=lambda x: x["order"]):
        changes = g["changes"]
        total_instr = len(g["instrument_details"])
        na_count = total_instr - len(changes)
        group_name = g["group"]
        interp = interp_map.get(group_name, {})
        pos_label = interp.get("positive_means", "confirming")
        neg_label = interp.get("negative_means", "stress")
        description = interp.get("description", "")

        if not changes and total_instr > 0:
            grp_status = "unavailable"
        elif na_count > total_instr * 0.5:
            grp_status = "limited"
        elif all(c > 0.2 for c in changes):
            grp_status = pos_label
        elif all(c < -0.2 for c in changes):
            grp_status = neg_label
        elif any(c > 0.2 for c in changes) and any(c < -0.2 for c in changes):
            grp_status = "mixed"
        elif changes:
            grp_status = "neutral"
        else:
            grp_status = "limited"

        result.append({
            "group": group_name,
            "instruments": [d["symbol"] for d in g["instrument_details"]],
            "instrument_details": g["instrument_details"],
            "status": grp_status,
            "description": description
        })

    return result


def _build_divergence_check(s_ctx: dict, market_status: str, freshness: dict, prices: list, coverage: dict) -> dict:
    """
    Heuristic divergence assessment. Uses coverage_matrix to avoid
    saying 'coverage is limited' when data is actually strong.
    """
    significant_changes = 0
    for obs in s_ctx.get("macro_observations", []):
        change = obs.get("change_pct")
        if change is not None and abs(change) > 3:
            significant_changes += 1

    if significant_changes >= 3:
        structural_risk = "elevated"
    elif significant_changes >= 1:
        structural_risk = "medium"
    else:
        structural_risk = "low"

    # Data lag
    last_update = freshness.get("last_update")
    if last_update:
        try:
            from datetime import datetime
            last_dt = datetime.fromisoformat(last_update)
            days_ago = (datetime.now() - last_dt).days
            data_lag = "low" if days_ago <= 3 else ("medium" if days_ago <= 14 else "high")
        except Exception:
            data_lag = "medium"
    else:
        data_lag = "high"

    mc_map = {"Confirming": "confirming", "Mixed": "mixed", "Divergent": "divergent", "Limited": "limited"}
    mc_val = mc_map.get(market_status, "limited")

    # Overall coverage level
    cov_levels = [coverage.get(k, "low") for k in ["macro_data", "market_data", "trade_data", "news_evidence"]]
    high_count = sum(1 for c in cov_levels if c == "high")
    cov_label = "strong" if high_count >= 3 else ("moderate" if high_count >= 1 else "limited")

    # Build interpretation using actual coverage level
    interp_parts = []
    if structural_risk == "elevated" and mc_val == "confirming":
        interp_parts.append("Both structural data and market prices point in the same direction.")
        interp_parts.append("The signal appears well-reflected across available data sources.")
    elif structural_risk == "elevated" and mc_val in ("mixed", "limited"):
        interp_parts.append("Structural risk indicators are elevated while market confirmation remains incomplete.")
        interp_parts.append("This suggests the signal has not yet consolidated into a single market narrative.")
    elif structural_risk == "low" and mc_val == "confirming":
        interp_parts.append("Market prices are moving but structural data shows limited disruption.")
        interp_parts.append("This may reflect sentiment-driven repricing rather than fundamental change.")
    elif structural_risk == "medium" and mc_val == "mixed":
        interp_parts.append("Moderate structural signals with mixed market response.")
        interp_parts.append("The situation is evolving; directional clarity has not yet emerged.")
    elif cov_label == "limited":
        interp_parts.append("Data coverage across source categories is limited.")
        interp_parts.append("The signal requires additional observation before drawing conclusions.")
    else:
        interp_parts.append(f"Data coverage is {cov_label} across available source categories.")
        interp_parts.append("Structural and market signals are within normal ranges for this assessment period.")

    if data_lag == "high":
        interp_parts.append("Note: structural data has significant lag; current assessment may not reflect very recent developments.")

    return {
        "structural_risk": structural_risk,
        "market_confirmation": mc_val,
        "data_lag": data_lag,
        "overall_coverage": cov_label,
        "interpretation": " ".join(interp_parts)
    }


def _build_coverage_matrix(s_ctx: dict, m_ctx: dict, timeline: list, sig: dict) -> dict:
    """
    Heuristic coverage assessment based on data point counts.
    Thresholds: high >= 3, medium >= 1, low = 0
    """
    def _level(count: int) -> str:
        if count >= 3:
            return "high"
        elif count >= 1:
            return "medium"
        return "low"

    macro_count = len(s_ctx.get("macro_observations", []))
    market_count = len(m_ctx.get("latest_prices", []))
    trade_count = len(s_ctx.get("trade_flows", []))
    news_count = len(sig.get("related_news", []))
    geo_count = 1 if sig.get("location_lat") else 0

    notes_parts = []
    if macro_count == 0:
        notes_parts.append("No macro observations available for this domain.")
    if trade_count == 0:
        notes_parts.append("Trade flow data not yet synced or not applicable.")
    if geo_count == 0:
        notes_parts.append("No geographic coordinates associated with this signal.")

    return {
        "macro_data": _level(macro_count),
        "market_data": _level(market_count),
        "trade_data": _level(trade_count),
        "geo_data": _level(geo_count),
        "news_evidence": _level(news_count),
        "notes": " ".join(notes_parts) if notes_parts else (
            f"Records counted: {macro_count} macro, {market_count} market, "
            f"{trade_count} trade, {geo_count} geo, {news_count} news."
        )
    }


# --- Region keyword dictionary for geo extraction ---
_GEO_KEYWORDS = [
    "United States", "China", "Russia", "Japan", "South Korea", "Taiwan",
    "Iran", "Saudi Arabia", "UAE", "Iraq", "Israel", "Turkey",
    "Ukraine", "Europe", "Germany", "France", "United Kingdom", "UK",
    "India", "Brazil", "Mexico", "Canada", "Australia", "Indonesia",
    "Gulf of Oman", "Strait of Hormuz", "South China Sea", "Taiwan Strait",
    "Suez Canal", "Panama Canal", "Red Sea", "Baltic Sea", "Arctic",
    "Middle East", "Southeast Asia", "Central Asia", "Africa", "Latin America",
    "North Korea", "Pakistan", "Nigeria", "Venezuela", "Norway", "Singapore"
]


def _build_geo_context(sig: dict, timeline: list) -> dict:
    """Extract geographic context from signal and timeline text."""
    has_coords = sig.get("location_lat") is not None and sig.get("location_lng") is not None

    # Collect text to scan for region mentions
    texts = []
    if sig.get("title"):
        texts.append(sig["title"])
    for ev in timeline:
        if ev.get("title"):
            texts.append(ev["title"])
        if ev.get("location_label"):
            texts.append(ev["location_label"])
    for n in sig.get("related_news", []):
        t = n.get("title") or n.get("headline") or n.get("text", "")
        if t:
            texts.append(t)

    combined = " ".join(texts)
    mentioned = []
    for kw in _GEO_KEYWORDS:
        if kw.lower() in combined.lower() and kw not in mentioned:
            mentioned.append(kw)

    confidence = "coordinates" if has_coords else ("inferred" if mentioned else "unavailable")

    return {
        "has_coordinates": has_coords,
        "mentioned_regions": mentioned[:8],
        "confidence": confidence
    }


def _build_unresolved_signals(market_status: str, coverage: dict, divergence: dict) -> list:
    """Identify contradictory or incomplete data points worth highlighting."""
    items = []
    if market_status == "Mixed":
        items.append("Market instruments are sending mixed signals — some asset groups confirm while others diverge.")
    if coverage.get("geo_data") == "low":
        items.append("Geographic attribution is limited; the signal's regional scope may be broader than displayed.")
    if coverage.get("trade_data") == "low":
        items.append("Trade flow data is sparse; structural transmission assessment relies primarily on macro and market data.")
    if divergence.get("structural_risk") == "elevated" and divergence.get("market_confirmation") in ("limited", "mixed"):
        items.append("Structural risk appears elevated but market prices have not fully reflected this assessment.")
    if divergence.get("data_lag") == "high":
        items.append("Significant data lag detected; the most recent structural observations may be stale.")
    return items


def _build_executive_summary(
    domain: dict, sig: dict, sig_class: dict,
    market_status: str, coverage: dict, divergence: dict,
    breakdown: list, geo_context: dict
) -> tuple:
    """
    Auto-generate executive summary + key findings from structured payload.
    Returns (summary_text, key_findings_list).
    """
    parts = []
    findings = []

    domain_name = domain.get("display_name", "Unknown Domain")
    signal_title = sig.get("title") or sig.get("target_label") or "an unspecified event"
    primary_type = (sig_class.get("primary_type") or "unclassified").replace("_", " ")
    parts.append(
        f"This brief tracks a {domain_name} signal related to {signal_title}, "
        f"classified as {primary_type}."
    )

    secondary = sig_class.get("secondary_types", [])
    if secondary:
        readable = [s.replace("_", " ") for s in secondary[:3]]
        parts.append(f"Secondary signal dimensions include {', '.join(readable)}.")

    # Market + breakdown
    if breakdown:
        groups_desc = []
        for g in breakdown[:4]:
            groups_desc.append(f"{g['group'].lower()} ({g['status']})")
        parts.append(f"Market confirmation is {market_status.lower()} across {', '.join(groups_desc)}.")
        # Key findings from breakdown
        for g in breakdown:
            if g["status"] in ("confirming", "stress", "easing", "risk_on", "flight_to_safety", "inflationary", "deflationary", "usd_strength", "usd_weakness", "resilient"):
                findings.append(f"{g['group']}: {g['status'].replace('_', ' ')}")
    else:
        parts.append(f"Market confirmation status is {market_status.lower()}.")

    # Coverage
    cov_levels = [coverage.get(k, "low") for k in ["macro_data", "market_data", "trade_data", "news_evidence"]]
    high_count = sum(1 for c in cov_levels if c == "high")
    parts.append(f"{high_count} of 4 source categories (macro, market, trade, news) hold 3 or more records.")

    # Geo
    regions = geo_context.get("mentioned_regions", [])
    geo_conf = geo_context.get("confidence", "unavailable")
    if regions:
        parts.append(f"Geographic scope includes {', '.join(regions[:4])} ({geo_conf} attribution).")
        findings.append(f"Geo scope: {', '.join(regions[:4])}")
    elif geo_conf == "unavailable":
        parts.append("Geographic attribution remains unavailable.")

    # Divergence
    sr = divergence.get("structural_risk", "low")
    mc = divergence.get("market_confirmation", "limited")
    if sr == "elevated":
        findings.append(f"Structural risk: {sr}")
        if mc in ("mixed", "limited"):
            parts.append("Structural risk indicators are elevated while market confirmation remains incomplete.")
    elif sr == "medium" and mc == "mixed":
        findings.append("Evolving situation with mixed market signals")

    return " ".join(parts), findings

