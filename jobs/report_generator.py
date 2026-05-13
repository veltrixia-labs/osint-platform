import asyncio
import logging
import os
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Any, Dict, Set

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from db.database import AsyncSessionLocal
from db.models import SignalRanking, Item, Report, EventCluster, TrendSignal, ExternalPost, ItemTopic, Stakeholder, Dependency
from db.enums import PlanTier, ReportType
from llm.prompts import SYSTEM_PROMPT, NEUTRAL_ANALYSIS_PROMPT, LLM_POLISH_PROMPT
from llm.client import generate_analysis, get_metrics_summary

TREND_LOOKBACK_DAYS = 7
from processor.location_resolver import LocationResolver

resolver = LocationResolver()
from integrations.threads_client import create_threads_posting_client, threads_mock_force_enabled
logger = logging.getLogger(__name__)

from render.markdown_builder import build_publish_markdown, build_teaser_markdown, build_degraded_markdown
from render.safety_checker import check_safety
from analysis.free_company_matcher import match_news_to_companies

# ──────────────────────────────────────────────────────────────────────────────
# Tiered Analysis Prompts
# ──────────────────────────────────────────────────────────────────────────────

WEEKLY_ANALYSIS_PROMPT = """
Analyze the following OSINT findings for a WEEKLY summary.
Focus on identifying major themes and shifts over the past 7 days.
Provide a lightweight analysis that connects major developments without deep forecasting.
Maintain a professional, intelligence-grade tone.
"""

MONTHLY_EXPERTS_PROMPT = """
You are a Senior Intelligence Analyst performing a MONTHLY decision-support analysis.
Analyze the trends and developments provided to generate a comprehensive strategic report.

REQUIRED STRUCTURE:
# Monthly Intelligence Report

## 1. Macro Overview
(Summary of the overall landscape and major trends)

## 2. Key Structural Shifts
(Deep dive into major changes in the status quo)

## 3. Scenario Analysis
- **Best Case**: [Optimistic projection]
- **Base Case**: [Most likely projection]
- **Worst Case**: [Pessimistic projection]

## 4. Risk Forecast
(Quantitative and qualitative risk assessment)

## 5. Cross-Domain Impact
(How developments in this field affect other sectors like geopolitics, economy, or technology)

## 6. Forward Outlook (30–60 days)
(Concrete expectations for the next 2 months)

TONE: Objective, analytical, and forward-looking.
"""

# Visualization is optional in production to avoid heavy matplotlib dependency issues
try:
    from analysis.visual_engine import generate_intensity_chart, generate_diversity_chart
    HAS_VISUAL_ENGINE = True
except ImportError:
    logger.warning("Visual engine (matplotlib) not found. Skipping chart generation.")
    HAS_VISUAL_ENGINE = False
    generate_intensity_chart = None
    generate_diversity_chart = None

# ──────────────────────────────────────────────────────────────────────────────
# Analysis Context Helpers
# ──────────────────────────────────────────────────────────────────────────────

DOMAIN_KEYWORDS = {
    "energy_resource_risk": ["oil", "energy", "refinery", "pipeline", "opec", "gas", "crude", "shipping", "lng"],
    "global_market_intelligence": ["inflation", "fed", "equity", "volatility", "market", "pricing", "liquidity", "yields", "economic"],
    "ai_semiconductor_intelligence": ["ai", "chip", "semiconductor", "gpu", "nvidia", "fab", "compute", "model", "export control"],
    "defense_technology": ["procurement", "weapons", "missile", "drone", "defense industry", "military technology"],
    "supply_chain_intelligence": ["logistics", "shipping", "port", "congestion", "raw materials", "shortage", "inventory"],
    "crypto_geopolitics": ["crypto", "bitcoin", "ethereum", "web3", "digital asset", "regulation", "cbdc", "stablecoin"]
}

EXCLUDED_NICHES = {"sports", "gaming", "celebrity", "wildlife", "local weather", "human interest"}

def calculate_trend_relevance(trend: TrendSignal, report_themes: List[str], report_category: str) -> float:
    """
    Calculates a relevance score for a trend signal based on report context.
    - Theme overlap (keywords)
    - Domain alignment (category)
    - Sector-specific bonuses
    - Hard exclusions (noise suppression)
    """
    score = 0.0
    label_lower = (trend.target_label or "").lower()
    desc_lower = (trend.description or "").lower()
    
    # 1. Hard Exclusions (Noise)
    if any(niche in label_lower or niche in desc_lower for niche in EXCLUDED_NICHES):
        return -100.0  # Immediate rejection
        
    # 2. Theme Keyword Match
    for theme in report_themes:
        tw = theme.lower().strip()
        if len(tw) < 3: continue
        if tw in label_lower: score += 5.0
        if tw in desc_lower: score += 2.0
        
    # 3. Domain Alignment Match
    if trend.topic == report_category:
        score += 10.0
        
    # 4. Sector-specific Bonus (Even if domain tag differs)
    keywords = DOMAIN_KEYWORDS.get(report_category, [])
    for kw in keywords:
        if kw in label_lower: score += 5.0
        if kw in desc_lower: score += 2.0
        
    return score

def infer_domain_from_content(themes: List[str], requested_topic: str | None) -> str | None:
    """
    Infers the correct intelligence domain from theme keywords.
    Uses the module-level DOMAIN_KEYWORDS (all 6 topics) to prevent misassignment
    (e.g. 'Energy' themes assigned to 'AI' reports).
    Returns the inferred topic_code if confidence is high, else requested_topic.
    """
    # Guard: empty themes or placeholder string → keep requested topic as-is
    if not themes or themes == ["Strategic Monitoring"]:
        return requested_topic

    theme_text = " ".join(themes).lower()
    scores = {domain: 0 for domain in DOMAIN_KEYWORDS.keys()}

    for domain, keywords in DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in theme_text:
                scores[domain] += 1

    if not any(scores.values()):
        return requested_topic

    # Find top-scoring domain
    inferred = max(scores, key=scores.get)
    max_score = scores[inferred]

    # Confidence Threshold: At least 2 signal matches
    # OR if the requested topic has 0 matches and another domain has 1+
    requested_score = scores.get(requested_topic, 0)
    if max_score >= 2 or (requested_score == 0 and max_score >= 1):
        if inferred != requested_topic:
            matched_kws = [k for k in DOMAIN_KEYWORDS[inferred] if k in theme_text]
            logger.info(
                f"Domain Mismatch Detected: Requested={requested_topic}, "
                f"Inferred={inferred}, Score={max_score}, "
                f"Reason: {', '.join(matched_kws)}"
            )
        return inferred

    return requested_topic

# ──────────────────────────────────────────────────────────────────────────────
# Pipeline Orchestration
# ──────────────────────────────────────────────────────────────────────────────

# Config
NUM_WORKERS = 3
REPORT_TASK_DEADLINE = 240.0 
EXPECTED_CATEGORIES = 7 # 6 topics + 1 global

TOPIC_CONFIG = {
    "energy_resource_risk": {
        "signal_type": "Top 10 Energy Resource Risk Signals",
        "label": "Energy & Resource Risk"
    },
    "global_market_intelligence": {
        "signal_type": "Top 10 Global Market Intelligence Signals",
        "label": "Global Market Intelligence"
    },
    "crypto_geopolitics": {
        "signal_type": "Top 10 Crypto Geopolitics Signals",
        "label": "Crypto & Geopolitics"
    },
    "ai_semiconductor_intelligence": {
        "signal_type": "Top 10 AI Semiconductor Intelligence Signals",
        "label": "AI & Semiconductor"
    },
    "defense_technology": {
        "signal_type": "Top 10 Defense Technology Signals",
        "label": "Defense Technology"
    },
    "supply_chain_intelligence": {
        "signal_type": "Top 10 Supply Chain Intelligence Signals",
        "label": "Supply Chain Intelligence"
    },
}
from analysis.clustering import cluster_items
from analysis.signal_engine import calculate_cluster_signal
from analysis.theme_extractor import extract_themes, build_narrative_summary
from analysis.forecast_engine import generate_forecasts
from analysis.scenario_engine import generate_scenarios
from analysis.skeleton_builder import build_threads_teaser, build_substack_skeleton, validate_skeleton
from llm.prompts import SYSTEM_PROMPT, NEUTRAL_ANALYSIS_PROMPT, LLM_POLISH_PROMPT
from integrations.substack_client import generate_slug, create_draft, update_draft, get_final_url
from db.models import ExternalPost, AnalystProfile
from api.gating import get_effective_tier, TIER_PRO, TIER_ENTERPRISE

# Threads Posting Controls
THREADS_DAILY_CAP = 5
THREADS_MIN_COOLDOWN_HOURS = 1
THREADS_QUIET_HOURS = (1, 5) # UTC 01:00 - 05:00

async def handle_threads_autopost(db: AsyncSession, report_id: uuid.UUID, teaser_text: str, topic: str):
    """Handles the guarded Threads posting flow."""
    access_token = os.getenv("THREADS_ACCESS_TOKEN")
    user_id = os.getenv("THREADS_USER_ID")
    dry_run = os.getenv("DRY_RUN_THREADS", "true").lower() == "true"
    mock_force = threads_mock_force_enabled()
    
    # 1. Topic Gating (Global only for now)
    if topic != "global":
        logger.info(f"Skipping Threads auto-post for topic '{topic}' (Global-only enabled).")
        return

    # 2. Quiet Hours Check
    now_aware = datetime.now(timezone.utc)
    hour = now_aware.hour
    if THREADS_QUIET_HOURS[0] <= hour < THREADS_QUIET_HOURS[1]:
        logger.info(f"Threads quiet hours active ({hour}:00 UTC). Skipping auto-post.")
        return

    # 3. Daily Cap & Cooldown Check
    day_ago = now_aware - timedelta(hours=24)
    stmt_daily = select(ExternalPost).where(
        ExternalPost.platform == "threads",
        ExternalPost.status == "success",
        ExternalPost.published_at >= day_ago
    )
    daily_posts = (await db.execute(stmt_daily)).scalars().all()
    if len(daily_posts) >= THREADS_DAILY_CAP:
        logger.warning(f"Threads daily cap reached ({len(daily_posts)} posts). Skipping.")
        return

    hour_ago = now_aware - timedelta(hours=THREADS_MIN_COOLDOWN_HOURS)
    for p in daily_posts:
        p_dt = p.published_at
        if p_dt and p_dt.tzinfo is None:
            p_dt = p_dt.replace(tzinfo=timezone.utc)
        if p_dt and p_dt >= hour_ago:
            logger.info("Threads cooldown active (last post < 1h ago). Skipping.")
            return

    # 4. Deduplication Check
    stmt = select(ExternalPost).where(ExternalPost.report_id == report_id, ExternalPost.platform == "threads")
    existing = (await db.execute(stmt)).scalars().first()
    if existing and existing.status == "success":
        logger.info(f"Report {report_id} already posted to Threads. Skipping.")
        return

    # 5. Text Normalization
    normalized_text = teaser_text.replace("\n\n\n", "\n\n").strip()
    
    # 6. Pre-posting Validation
    if len(normalized_text) < 10 or len(normalized_text) > 500:
        logger.error(f"Threads validation failed: Text length {len(normalized_text)} outside [10, 500]")
        return

    # 7. Execution (Guarded)
    if dry_run and not mock_force:
        logger.info(f"[DRY RUN] Would post to Threads: {normalized_text[:50]}...")
        return

    logger.info(f"Attempting Threads auto-post for report {report_id}...")
    
    app_id = os.getenv("THREADS_APP_ID")
    app_secret = os.getenv("THREADS_APP_SECRET")
    client = create_threads_posting_client(
        access_token or "",
        user_id or "",
        app_id,
        app_secret,
    )
    
    try:
        # 7.1 Token Refresh (Safety first)
        if app_secret and not mock_force:
            await client.refresh_access_token()
            # Note: client.access_token is updated internally

        # 7.2 Post (with internal polling and retry)
        result = await client.post_thread(normalized_text)
        
        post_record = ExternalPost(
            platform="threads",
            report_id=report_id,
            external_id=result.get("media_id"),
            container_id=result.get("container_id"),
            status="success" if result["success"] else "failure",
            error_message=result.get("error"),
            published_at=datetime.fromisoformat(result["published_at"]) if result["published_at"] else datetime.now(timezone.utc)
        )
        db.add(post_record)
        await db.commit()
        
        if result["success"]:
            logger.info(f"Successfully posted to Threads: {result['media_id']}")
        else:
            logger.error(f"Threads auto-post failed: {result['error']}")
            
    except Exception as e:
        logger.error(f"Fatal error in Threads auto-post utility: {e}")
        # We don't bubble this up to avoid breaking the analysis job

async def _should_generate_report_for_system(db: AsyncSession, report_type: str) -> bool:
    """[Dev Phase Override] Always allow generation to verify system functionality."""
    return True

async def run_report_generation(
    db: AsyncSession,
    report_type: str = "weekly",
    period_days: int = 7,
    topic: str | None = None,
    auto_post_threads: bool = False
) -> Tuple[str, str, str]: # returns (teaser_md, status, reason)
    """
    Unified report generation: Fetches items, clusters them, extracts themes, 
    and applies tiered LLM analysis (Pro/Expert).
    """
    logger.info(f"Generating report: {report_type} | topic={topic}")
    
    current_type = (report_type or "weekly").lower()
    if current_type == ReportType.DAILY.value or current_type == "daily_global":
        logger.info("Free daily reports are deprecated. Skipping generation.")
        return "", "skipped", "Free daily reports deprecated. Use Free Alert Feed."
        
    if not await _should_generate_report_for_system(db, report_type):
        logger.info(f"Skipping {report_type} report: No active users meet the tier requirements.")
        return "", "skipped", "Insufficient global tier"
        
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=period_days)

    if topic and topic in TOPIC_CONFIG:
        signal_type = TOPIC_CONFIG[topic]["signal_type"]
    else:
        signal_type = "Top 10 Global Risk Signals"

    # 1. Fetch Candidates (Priority: SignalRanking)
    stmt = select(SignalRanking).where(
        SignalRanking.signal_type == signal_type,
        SignalRanking.created_at >= now - timedelta(hours=24)
    ).order_by(SignalRanking.rank.asc()).limit(20)
    
    rankings = (await db.execute(stmt)).scalars().all()
    items = []
    seen_urls = set()
    for r in rankings:
        item_stmt = select(Item).where(Item.id == r.item_id)
        item = (await db.execute(item_stmt)).scalar_one_or_none()
        if item and item.source_url not in seen_urls:
            items.append(item)
            seen_urls.add(item.source_url)
    
    if not items:
        # Fallback to recent items for topic
        if topic:
            stmt_fallback = (
                select(Item)
                .join(ItemTopic, ItemTopic.item_id == Item.id)
                .where(ItemTopic.topic_code == topic)
                .where(Item.published_at >= start_time)
                .order_by(Item.published_at.desc())
                .limit(10)
            )
        else:
            stmt_fallback = select(Item).where(Item.published_at >= start_time).order_by(Item.published_at.desc()).limit(10)
        items = list((await db.execute(stmt_fallback)).scalars().all())

    if not items:
        return "", "failed", "No items found for analysis."

    # 1.1 Noise Filter for Global (Phase 19.3)
    topic_str = topic if topic else "global"
    if topic_str == "global":
        RISK_STOPWORDS = {"f1", "grandprix", "entertainment", "sports", "celebrity", "lifestyle", "fashion", "hollywood"}
        filtered = []
        for it in items:
            text_lower = (it.title + " " + (it.summary or "")).lower()
            if not any(stop in text_lower for stop in RISK_STOPWORDS):
                filtered.append(it)
        items = filtered[:10]

    # 2. Advanced Analysis (Clustering & Context)
    clustering_metrics = await cluster_items(db, items)
    
    # Extract clusters from the returned metrics (or fetch refined clusters from DB)
    from db.models import EventCluster
    stmt_clusters = select(EventCluster).where(EventCluster.created_at >= now - timedelta(hours=1))
    clusters = (await db.execute(stmt_clusters)).scalars().all()
    avg_score = 0.8 # Default baseline
    
    cluster_context_list = []
    for c in clusters:
        # Use representative title and keywords from summary_data for context (Phase 35)
        keywords = ", ".join(c.summary_data.get("keywords", [])) if c.summary_data else ""
        cluster_context_list.append(f"CLUSTER: {c.representative_title} (Docs: {c.source_count})\n- Focus: {keywords}")
    cluster_context_str = "\n\n".join(cluster_context_list) if cluster_context_list else "No significant clusters identified."

    # 3. Themes & Trends
    themes = extract_themes(items)
    effective_topic = infer_domain_from_content(themes, topic_str)
    
    # Trend Analysis
    trend_stmt = select(TrendSignal).where(TrendSignal.created_at >= now - timedelta(hours=24))
    all_trends = (await db.execute(trend_stmt)).scalars().all()
    
    scored_trends = []
    for t in all_trends:
        rel_score = calculate_trend_relevance(t, themes, topic_str)
        if rel_score >= 5:
            scored_trends.append((t, rel_score))
    
    scored_trends.sort(key=lambda x: (x[1], x[0].intensity_score), reverse=True)
    trends_pool = [x[0] for x in scored_trends[:8]]
    
    skeleton_trends = {"patterns": [], "persistent": [], "surges": [], "changes": []}
    trend_context_list = []
    for t in trends_pool:
        m = t.metrics_json or {}
        explained = f"TREND: {t.target_label} ({t.trend_type}) - Intensity: {t.intensity_score}"
        trend_context_list.append(explained)
        
        if t.trend_type == "risk_pattern":
            skeleton_trends["patterns"].append({
                "label": t.target_label, 
                "intensity": t.intensity_score,
                "description": t.description or "Evolution of observed signals suggests a sustained risk pattern."
            })
        elif t.trend_type == "sustained_event":
            skeleton_trends["persistent"].append(explained)
        else:
            skeleton_trends["surges"].append(explained)

    trend_context_str = "\n\n".join(trend_context_list) if trend_context_list else "No significant trends detected."

    # 4. Content Generation
    current_type = (report_type or "daily").lower()
    plan_required = PlanTier.FREE.value
    status = "success"
    final_content = ""
    skeleton_content = ""

    # Generate Forecasts & Scenarios for Weekly/Monthly/Event-Driven
    if current_type in [ReportType.WEEKLY.value, ReportType.MONTHLY.value] or current_type.startswith("event_driven"):
        forecasts = generate_forecasts(
            [effective_topic] if effective_topic else ["global"],
            " ".join(themes),
            avg_score,
        )
        scenarios = generate_scenarios(
            avg_score,
            forecasts,
            domain=effective_topic,
        )
        skeleton_content = build_substack_skeleton(
            themes,
            [],
            forecasts,
            scenarios,
            [it.source_url for it in items],
            trends=skeleton_trends,
            domain=effective_topic,
        )

    if current_type == ReportType.WEEKLY.value:
        plan_required = PlanTier.PRO.value
        analysis_input = f"SKELETON DATA:\n{skeleton_content}\n\nCONTEXT:\n{cluster_context_str}"
        polished = await generate_analysis(WEEKLY_ANALYSIS_PROMPT, analysis_input)
        final_content = polished if polished and polished != "__DEGRADED_MODE__" else skeleton_content

    elif current_type == ReportType.MONTHLY.value:
        plan_required = PlanTier.EXPERTS.value
        analysis_input = f"MONTHLY DATA:\n{skeleton_content}\n\nBROADER CONTEXT:\n{trend_context_str}"
        expert_analysis = await generate_analysis(MONTHLY_EXPERTS_PROMPT, analysis_input)
        final_content = expert_analysis if expert_analysis and expert_analysis != "__DEGRADED_MODE__" else skeleton_content

    elif current_type.startswith("event_driven"):
        plan_required = PlanTier.PRO.value
        final_content = skeleton_content
        logger.info(f"Event-driven report generated for type: {current_type}")

    else:
        # Daily or unknown
        logger.info(f"Generating standard report for type: {current_type}")
        # Build a basic skeleton if not already built
        if not skeleton_content:
            skeleton_content = build_substack_skeleton(
                themes, [], [], [], [it.source_url for it in items],
                trends=skeleton_trends, domain=effective_topic
            )
        final_content = skeleton_content

    # 5. Metadata & Persistence
    major_theme = themes[0] if themes else (topic_str.capitalize() if topic_str else "Global")
    topic_label = TOPIC_CONFIG.get(effective_topic, {}).get("label") if effective_topic else "Global"
    derived_title = f"Intelligence: {major_theme} | {topic_label} Focused"
    
    # Simple teaser from content
    teaser_lines = []
    for line in final_content.split('\n'):
        if line.strip() and not line.strip().startswith(('#', '!', '[')):
            teaser_lines.append(line.strip())
            if len(teaser_lines) >= 2: break
    teaser_md = " ".join(teaser_lines)[:277] + "..."

    # Create Report Record
    new_report = Report(
        report_type=current_type,
        topic_code=effective_topic or "global",
        title=derived_title,
        teaser_md=teaser_md,
        content_markdown=final_content,
        is_premium=(current_type != ReportType.DAILY.value),
        plan_required=plan_required,
        source_count=len(items),
        confidence_level="Medium",
        created_at=now
    )
    db.add(new_report)
    await db.commit()
    await db.refresh(new_report)

    # 6. Threads Teaser
    platform_base = os.getenv("DOMAIN_URL", os.getenv("PLATFORM_BASE_URL", "https://veltrixia.net"))
    platform_url = f"{platform_base}/?report_id={new_report.id}"
    top_event = items[0].title if items else "No significant developments identified."
    
    gen_teaser_threads = build_threads_teaser(top_event, major_theme, topic_str, platform_url)

    logger.info(f"Report generation complete for {topic_str}. Version: {status}")
    
    # 7. Final Cleanup (Record Metrics)
    logger.info(f"Phase 11 Metrics [{topic_str}]: source_count={len(items)}, clusters={clustering_metrics.get('clusters_created')}")
    
    return gen_teaser_threads, status, "OK"

if __name__ == "__main__":
    import argparse
    from jobs.report_orchestrator import run_all_reports
    from jobs.report_utils import purge_report_history

    parser = argparse.ArgumentParser(description="OSINT Report Generation Job")
    parser.add_argument("--type", type=str, default="weekly", choices=["daily", "weekly", "monthly", "specialized"], help="Report type to generate")
    parser.add_argument("--purge", action="store_true", help="Perform Hard Cleanup (purge all history) before starting")
    parser.add_argument("--threads", action="store_true", help="Enable Threads auto-posting")

    args = parser.parse_args()

    async def main():
        async with AsyncSessionLocal() as session:
            if args.purge:
                await purge_report_history(session)
            await run_all_reports(session, report_type=args.type, auto_post_threads=args.threads)

    asyncio.run(main())

