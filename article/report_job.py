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
from db.models import SignalRanking, Item, Report, EventCluster, TrendSignal, ExternalPost, ItemTopic
from db.enums import PlanTier, ReportType
from llm.prompts import SYSTEM_PROMPT, NEUTRAL_ANALYSIS_PROMPT, LLM_POLISH_PROMPT
from llm.client import generate_analysis, get_metrics_summary

TREND_LOOKBACK_DAYS = 7
logger = logging.getLogger(__name__)

from render.markdown_builder import build_publish_markdown, build_teaser_markdown, build_degraded_markdown
from render.safety_checker import check_safety

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
    if dry_run:
        logger.info(f"[DRY RUN] Would post to Threads: {normalized_text[:50]}...")
        return

    logger.info(f"Attempting Threads auto-post for report {report_id}...")
    
    app_id = os.getenv("THREADS_APP_ID")
    app_secret = os.getenv("THREADS_APP_SECRET")
    client = ThreadsClient(access_token, user_id, app_id, app_secret)
    
    try:
        # 7.1 Token Refresh (Safety first)
        if app_secret:
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
    """Determine if a report should be generated based on active user subscription tiers."""
    if report_type not in ["monthly", "specialized"]:
        return True # Default reports are generated for everyone
    
    stmt = select(AnalystProfile).where(AnalystProfile.is_active == True)
    analysts = (await db.execute(stmt)).scalars().all()
    
    for a in analysts:
        tier = await get_effective_tier(a)
        if report_type == "monthly" and tier in [TIER_PRO, TIER_ENTERPRISE]:
            return True
        if report_type == "specialized" and tier == TIER_ENTERPRISE:
            return True
            
    return False

async def run_report_generation(
    db: AsyncSession,
    report_type: str = "daily",
    period_days: int = 1,
    topic: str | None = None,
    auto_post_threads: bool = False
) -> Tuple[str, str, str]: # returns (teaser_md, status, reason)
    """
    Generates report using Data-Driven Intelligence + Optional LLM Polish.
    """
    logger.info(f"Generating report: {report_type} | topic={topic}")
    
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
    # Using aware now for comparison with DateTime(timezone=True)
    stmt = select(SignalRanking).where(
        SignalRanking.signal_type == signal_type,
        SignalRanking.created_at >= now - timedelta(hours=24)
    ).order_by(SignalRanking.rank.asc()).limit(20)

    rankings = (await db.execute(stmt)).scalars().all()
    items = []
    seen_urls = set()
    for r in rankings:
        item = (await db.execute(select(Item).where(Item.id == r.item_id))).scalar_one_or_none()
        if item and item.source_url not in seen_urls:
            items.append(item)
            seen_urls.add(item.source_url)
    
    if not items:
        # Fallback to latest items (Ideally topic-specific)
        if topic:
            # Try to get items matching this topic from ItemTopic
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
        
        items = (await db.execute(stmt_fallback)).scalars().all()
        items = list(items)

    # 1.1 Noise Filter for Global Report (Phase 19.3)
    topic_str = topic if topic else "global"
    logger.info(f"Candidates fetched: {len(items)} items found.")
    
    if topic_str == "global":
        RISK_STOPWORDS = {"f1", "grandprix", "entertainment", "sports", "celebrity", "lifestyle", "fashion", "hollywood"}
        filtered_items = []
        for it in items:
            content_lower = (it.title + " " + (it.summary or "")).lower()
            if not any(stop in content_lower for stop in RISK_STOPWORDS):
                filtered_items.append(it)
        items = filtered_items[:10] # Keep top 10 after filtering
        logger.info(f"After global noise filter: {len(items)} items remaining.")
    
    if not items:
        return "", "failed", "No items found for report window."

    # 2. Rule-Based Intelligence Construction
    # A. Clustering & Context Extraction
    clustering_metrics = await cluster_items(db, items)
    
    # Fetch enriched clusters for context
    cluster_ids = list(set(it.cluster_id for it in items if it.cluster_id))
    clusters_stmt = select(EventCluster).where(EventCluster.id.in_(cluster_ids))
    clusters = (await db.execute(clusters_stmt)).scalars().all()
    
    # Format Cluster Context for LLM
    cluster_context_list = []
    for c in clusters:
        m = c.metrics_json or {}
        s = c.summary_data or {}
        context = (
            f"EVENT: {c.representative_title}\n"
            f"- Scale: {c.article_count} reports from {c.source_count} unique sources\n"
            f"- Diversity: {m.get('source_diversity', 0) * 100}% agreement across sources\n"
            f"- Timeline: Seen over {m.get('time_span_hours', 0)} hours\n"
            f"- Key Entities: {', '.join(s.get('top_geos', []) + s.get('top_orgs', []))}"
        )
        cluster_context_list.append(context)
    
    cluster_context_str = "\n\n".join(cluster_context_list)
    
    # B. Signal & Themes
    themes = extract_themes(items)
    avg_score = sum(it.lightweight_score for it in items) / len(items) if items else 0.0
    
    # C. Developments (Theme Alignment & Context Slot - Phase 19.4)
    # 1. Calculate Alignment Score for each cluster against themes
    # 2. Pick top 4 highly-aligned (Core) + 1 relevant-but-broad (Context)
    
    scored_clusters = []
    theme_str = " ".join(themes).lower()
    
    for c in clusters:
        m = c.metrics_json or {}
        s = c.summary_data or {}
        # Calculate Overlap
        cluster_entities = set([e.lower() for e in s.get("top_geos", []) + s.get("top_orgs", [])])
        cluster_text = (c.representative_title + " " + (c.summary_data.get("summary", ""))).lower()
        
        alignment = 0
        if any(ent in theme_str for ent in cluster_entities):
            alignment += 2
        if any(theme.lower() in cluster_text for theme in themes):
            alignment += 3
            
        # Context Rule: Same Geo/Sector check
        has_context_link = False
        if any(geo.lower() in theme_str for geo in s.get("top_geos", [])):
            has_context_link = True
        if any(sector.lower() in theme_str for sector in s.get("top_sectors", [])):
            has_context_link = True
            
        scored_clusters.append({
            "cluster": c,
            "alignment": alignment,
            "has_context_link": has_context_link,
            "score": c.article_count + (alignment * 5)
        })
        
    # Sort by score
    scored_clusters.sort(key=lambda x: x["score"], reverse=True)
    
    # Core Slots (Top 4 Highly Aligned)
    core_clusters = [x for x in scored_clusters if x["alignment"] >= 2][:4]
    remaining = [x for x in scored_clusters if x not in core_clusters]
    
    # Context Slot (top 1 from remaining that has context link)
    context_cluster = next((x for x in remaining if x["has_context_link"]), (remaining[0] if remaining else None))
    
    final_selection = core_clusters
    if context_cluster:
        final_selection.append(context_cluster)
        
    enriched_developments = []
    for x in final_selection:
        c = x["cluster"]
        support_label = ""
        if c.source_count > 3:
            support_label = "[High Support] "
        elif c.source_count > 1:
            support_label = "[Multi-Source] "
        
        entry = f"{support_label}{c.representative_title} (Sources: {c.source_count})"
        enriched_developments.append(entry)
    
    # D. Forecasts & Scenarios
    forecasts = generate_forecasts([topic] if topic else ["global"], " ".join([c.representative_title for c in clusters]), avg_score)
    scenarios = generate_scenarios(avg_score, forecasts)

    # E. Trend Analysis (Phase 19 & 19.1)
    # Fetch trends for the target period
    trend_stmt = select(TrendSignal).where(TrendSignal.created_at >= now - timedelta(hours=24))
    all_trends = (await db.execute(trend_stmt)).scalars().all()
    
    # Prioritize Risk Patterns, then Sustained Events
    BANNED_PHRASES = ["escalating regional risks", "general escalation", "regional risk", "mixed signals"]
    patterns = [
        t for t in all_trends 
        if t.trend_type == "risk_pattern" 
        and t.intensity_score <= 10.0 
        and not any(p in t.target_label.lower() for p in BANNED_PHRASES)
    ]
    if topic:
        # Filter patterns that mentioned topic entities or sector
        patterns = [p for p in patterns if topic.lower() in p.target_label.lower()]
    
    # Sort and Hard Cap to Top 3 (Phase 19.3)
    patterns.sort(key=lambda x: x.intensity_score, reverse=True)
    patterns = patterns[:3]
        
    trends_pool = patterns if patterns else [t for t in all_trends if t.intensity_score <= 10.0][:10]

    # Explained Trend Context for LLM
    trend_context_list = []
    skeleton_trends = {"patterns": [], "persistent": [], "surges": [], "changes": []}
    
    for t in trends_pool:
        m = t.metrics_json or {}
        # 1. Explained context for LLM
        if t.trend_type == "risk_pattern":
            explained = (
                f"RISK PATTERN: {t.target_label}\n"
                f"- Evolution: {t.description}\n"
                f"- Supporting Events: {', '.join(m.get('supporting_events', []))}\n"
                f"- Key Metrics: {m.get('recent', 0)} vs baseline {m.get('baseline', 0)} (Δ {m.get('delta', 0)})"
            )
        else:
            explained = (
                f"TREND: {t.target_label} ({t.trend_type})\n"
                f"- Change: {m.get('delta', 0) * 100}% shift from baseline ({m.get('baseline', 0)} -> {m.get('recent', 0)})\n"
                f"- Evidence: Supported by {m.get('supporting_cluster_count', 0)} clusters"
            )
        trend_context_list.append(explained)
        
        # 2. Skeleton entries based on type
        if t.trend_type == "risk_pattern":
            entry = {
                "label": t.target_label,
                "description": t.description,
                "intensity": round(t.intensity_score, 2),
                "supporting": m.get("supporting_events", [])
            }
            skeleton_trends["patterns"].append(entry)
        else:
            # Deduplicate target_label vs description
            desc = t.description
            label = t.target_label
            
            # If description already starts with the label or contains it significantly, just use description
            if desc.lower().startswith(label.lower()) or label.lower() in desc.lower()[:len(label)+5]:
                clean_item = desc
            else:
                clean_item = f"{label}: {desc}"
            
            # Strip redundant systemic prefixes if they linger from legacy signals
            for prefix in ["Emerging high-risk event detected: ", "Rapid risk escalation detected: ", "Sustained activity detected for event: "]:
                if clean_item.startswith(prefix):
                    clean_item = clean_item[len(prefix):]
            
            # Ensure proper punctuation before intensity
            if not clean_item.endswith("."):
                clean_item += "."
            
            entry_str = f"{clean_item} Intensity: {t.intensity_score}"
            
            if t.trend_type == "sustained_event":
                skeleton_trends["persistent"].append(entry_str)
            elif t.trend_type in ["sector_surge", "risk_acceleration"]:
                skeleton_trends["surges"].append(entry_str)
            else: # entity_heat
                skeleton_trends["changes"].append(entry_str)

    trend_context_str = "\n\n".join(trend_context_list)
    
    # F. Visual Analytics Generation (Phase 20)
    visual_files = []
    date_str = now.strftime('%Y%m%d')
    topic_str = topic if topic else "global"
    
    if HAS_VISUAL_ENGINE:
        try:
            # Visual 1: Intensity Chart for MAX Intensity Risk Pattern
            if patterns:
                max_p = max(patterns, key=lambda x: x.intensity_score)
                v1 = await generate_intensity_chart(db, max_p.target_label, topic_str, date_str)
                if v1: visual_files.append(v1)
                
            # Visual 2: Source Diversity Chart for MAX Supported Cluster
            if clusters and len(visual_files) < 2:
                max_c = max(clusters, key=lambda x: x.article_count)
                v2 = await generate_diversity_chart(db, max_c.id, topic_str, date_str)
                if v2: visual_files.append(v2)
        except Exception as ve:
            logger.error(f"Error during visual generation: {ve}")

    # 3. Build Skeleton Report
    skeleton_content = build_substack_skeleton(
        themes, 
        enriched_developments, 
        forecasts, 
        scenarios, 
        [it.source_url for it in items],
        trends=skeleton_trends,
        visuals=visual_files
    )
    
    # 4. Skeleton Validation
    if not validate_skeleton(skeleton_content):
        return "", "failed", "Skeleton structure validation failed."

    # 5. Tiered Content Generation (Phase 36 Redesign)
    plan_required = PlanTier.FREE.value
    status = "rule_based"
    final_content = skeleton_content
    llm_attempts = 0
    llm_successVal = 0
    
    # Standardize report type for generation logic
    current_type = (report_type or "daily").lower()
    if "event_driven" in current_type: # Legacy compatibility
        current_type = ReportType.DAILY.value

    if current_type == ReportType.DAILY.value:
        # ABSOLUTE LLM ISOLATION: No generate_analysis call
        logger.info(f"Generating DAILY report: 100% Rule-based (LLM bypassed).")
        plan_required = PlanTier.FREE.value
        status = "success" # Rule-based is considered success for Daily
        
    elif current_type == ReportType.WEEKLY.value:
        logger.info(f"Generating WEEKLY report: Lightweight LLM analysis (Pro+).")
        plan_required = PlanTier.PRO.value
        analysis_input = f"SKELETON DATA:\n{skeleton_content}\n\nCONTEXT:\n{cluster_context_str}"
        polished = await generate_analysis(WEEKLY_ANALYSIS_PROMPT, analysis_input)
        if polished and polished != "__DEGRADED_MODE__":
            final_content = polished
            status = "success"
        else:
            logger.warning("Weekly LLM analysis failed. Falling back to rule-based.")

    elif current_type == ReportType.MONTHLY.value:
        logger.info(f"Generating MONTHLY report: Full Expert Analysis (Experts only).")
        plan_required = PlanTier.EXPERTS.value
        analysis_input = f"MONTHLY RAW DATA & TRENDS:\n{skeleton_content}\n\nBROADER CONTEXT:\n{trend_context_str}"
        expert_analysis = await generate_analysis(MONTHLY_EXPERTS_PROMPT, analysis_input)
        
        if expert_analysis and expert_analysis != "__DEGRADED_MODE__" and "Scenario Analysis" in expert_analysis:
            final_content = expert_analysis
            status = "success"
        else:
            logger.warning("Monthly Expert LLM failed. Using Degraded Monthly Skeleton.")
            # Mandatory Fallback structure for Monthly
            final_content = (
                "# Monthly Intelligence Report (Degraded Mode)\n\n"
                "## 1. Macro Overview\nRule-based summary of developments is available below.\n\n"
                "## 2. Key Structural Shifts\nStructural automated detection active.\n\n"
                "## 3. Scenario Analysis\n[LLM UNAVAILABLE: Strategic scenarios suspended]\n\n"
                "## 4. Risk Forecast\nRisk metrics derived from rule-based thresholds.\n\n"
                "## 5. Cross-Domain Impact\nCross-domain synthesis requires LLM assistance.\n\n"
                "## 6. Forward Outlook (30–60 days)\nMaintain monitoring based on current rule-based signals.\n\n"
                "---\n"
                + skeleton_content
            )
            status = "rule_based_fallback"
    
    if current_type != ReportType.DAILY.value:
        llm_attempts = 1
        llm_successVal = 1 if status == "success" else 0


    # --- ADD EVIDENCE JSON ---
    import json
    evidence_payload = []
    
    # URL Validation Patterns
    BANNED_DOMAINS = ["example.com", "localhost", "127.0.0.1", "test.com", "dummy.org", "maritime-intel-example.org"]
    
    for it in items:
        url = (it.source_url or "").lower()
        
        # 1. Strict Validation: Must be http(s) and not a common placeholder
        is_valid_url = (
            url.startswith("http") and 
            not any(d in url for d in BANNED_DOMAINS) and
            len(url) > 12 # Minimum length for a real URL (e.g. http://a.com)
        )
        
        # 2. Data Integrity Safeguard: Skip records with mock/test keywords in title or summary
        is_mock_data = any(kw in (it.title or "").lower() or kw in (it.summary or "").lower() for kw in ["mock item", "test report", "dummy article"])
        
        if not is_valid_url or is_mock_data:
            # Still allow the entry but mark it as restricted for the UI to handle
            final_url = "#" if not is_valid_url else url
        else:
            final_url = url
            
        expl = (it.summary or "Observed data node matching cluster parameters.")
        if len(expl) > 150: expl = expl[:147] + "..."
        
        evidence_payload.append({
            "title": (it.title or "Unknown Source")[:100],
            "type": it.source_name or "Intelligence Node",
            "explanation": expl,
            "link": final_url
        })
        if len(evidence_payload) >= 10: break

    try:
        evi_str = json.dumps(evidence_payload)
        final_content += f"\n\n<!-- EVIDENCE_JSON: {evi_str} -->\n"
    except Exception as e:
        logger.error(f"Failed to serialize evidence JSON: {e}")
    # -------------------------
    # -------------------------

    # 6. Title and Metadata Generation (Phase 36 Redesign)
    
    # --- Title Generation ---
    # Major Theme Logic: Use themes[0] (Top confidence/sorted)
    major_theme = "Unknown"
    if themes and len(themes) > 0:
        major_theme = themes[0].source_label if hasattr(themes[0], 'source_label') else str(themes[0])
        if ":" in major_theme: major_theme = major_theme.split(":")[0].strip()
    
    topic_label = TOPIC_CONFIG.get(topic, {}).get("label") if topic else "Global"
    
    # Standardized Format: Themes: [Major Theme] | [Topic Label] Intelligence
    derived_title = f"Themes: {major_theme} | {topic_label} Intelligence"
    
    # --- Teaser Generation ---
    lines = final_content.split('\n')

    # --- Teaser Generation ---
    # Extract 2-3 meaningful lines starting from the first non-header, non-empty line
    teaser_lines = []
    for line in lines:
        clean = line.strip()
        if clean and not clean.startswith('#') and not clean.startswith('!') and not clean.startswith('[') and not clean.startswith('<!--'):
            teaser_lines.append(clean)
            if len(teaser_lines) >= 3:
                break
    
    teaser_md = " ".join(teaser_lines)
    if len(teaser_md) > 280:
        teaser_md = teaser_md[:277] + "..."

    # 7. Output Persistence & Idempotency Flow
    topic_str = topic if topic else "global"
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(base_dir, "outputs")
    os.makedirs(out_dir, exist_ok=True)
    
    date_str = now.strftime('%Y%m%d')
    base_name = f"{topic_str}_{report_type}_{date_str}_en"
    
    md_path = os.path.join(out_dir, f"analysis_{base_name}.md")
    with open(md_path, "w", encoding='utf-8') as f:
        f.write(final_content)

    # 8. Calculate Metrics & Better Metadata
    count = len(items)
    
    # Confirmed Title
    if not derived_title or "Summary of Themes" in derived_title:
        derived_title = f"Themes: {major_theme} | {topic_label} Intelligence"
    
    # Refined teaser (avoid null, ensure meaningful start)
    if not teaser_md:
        # Re-derive teaser from content if missing
        teaser_lines = []
        for line in final_content.split('\n'):
            clean = line.strip()
            if clean and not any(clean.startswith(x) for x in ['#', '!', '[', '<!--', 'Date:']):
                teaser_lines.append(clean)
                if len(teaser_lines) >= 3: break
        teaser_md = " ".join(teaser_lines)[:277] + "..." if teaser_lines else "Latest OSINT analysis and risk intelligence briefing."

    # Scoring Logic
    if count >= 8 and llm_successVal:
        conf = "High"
    elif count >= 3 or llm_successVal:
        conf = "Medium"
    else:
        conf = "Low"

    logger.info(f"Persisting report with metrics -> source_count: {count}, confidence: {conf}, title: {derived_title[:30]}")

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if topic is None:
        stmt = select(Report).where(
            Report.topic_code.is_(None),
            Report.report_type == report_type,
            Report.created_at >= today_start
        )
    else:
        stmt = select(Report).where(
            Report.topic_code == topic,
            Report.report_type == report_type,
            Report.created_at >= today_start
        )
    repo = (await db.execute(stmt)).scalars().first()

    is_premium = (current_type != ReportType.DAILY.value)
    
    # Tier mapping for reports (Gating logic alignment)
    plan_required = "free"
    if current_type == ReportType.WEEKLY.value:
        plan_required = "pro"
    elif current_type == ReportType.MONTHLY.value:
        plan_required = "experts"

    if not repo:
        repo = Report(
            report_type=current_type,
            topic_code=topic,
            period_start=now - timedelta(days=period_days),
            period_end=now,
            title=derived_title,
            teaser_md=teaser_md,
            content_markdown=final_content,
            is_premium=is_premium,
            plan_required=plan_required,
            source_count=count,
            confidence_level=conf
        )
        db.add(repo)
    else:
        logger.info(f"Report already exists for {topic_str} today. Updating content and metadata.")
        repo.report_type = current_type
        repo.title = derived_title
        repo.teaser_md = teaser_md
        repo.content_markdown = final_content
        repo.is_premium = is_premium
        repo.plan_required = plan_required
        repo.source_count = count
        repo.confidence_level = conf

    await db.flush()
    report_id = repo.id
    await db.commit()

    # 7. Build Teaser (Internal Platform Focus)
    top_cluster_event = items[0].title if items else "No significant developments identified."
    top_theme = themes[0] if themes else (topic.capitalize() if topic else "Global")
    
    platform_base = os.getenv("PLATFORM_BASE_URL", "https://osint-web-1oev.onrender.com")
    platform_url = f"{platform_base}/?report_id={report_id}"
    
    teaser_md = build_threads_teaser(top_cluster_event, top_theme, topic_str, platform_url)

    with open(os.path.join(out_dir, f"teaser_{base_name}.md"), "w", encoding='utf-8') as f:
        f.write(teaser_md)
    
    # 8. Queue Threads Auto-Post
    # (Off-loaded to the polling job - now independent of Substack status)
    if auto_post_threads:
        stmt_pending = select(ExternalPost).where(
            ExternalPost.report_id == report_id,
            ExternalPost.platform == "threads"
        )
        existing_post = (await db.execute(stmt_pending)).scalars().first()
        if not existing_post:
            logger.info("Queuing Threads post into 'pending' sequence...")
            db.add(ExternalPost(platform="threads", report_id=report_id, status="pending"))
            await db.commit()
        else:
            logger.info("Threads post is already queued/processed.")

    # Record Metrics
    logger.info(f"Phase 11 Metrics [{topic_str}]: " + json.dumps({
        "cluster_count": clustering_metrics["clusters_created"],
        "theme_count": len(themes),
        "signal_scores": avg_score,
        "forecast_rules_triggered": len(forecasts),
        "scenario_count": 3,
        "llm_polish_attempts": llm_attempts,
        "llm_polish_success": llm_successVal,
        "threads_posts_generated": 1,
        "substack_articles_generated": 1
    }))

    logger.info(f"Report process complete for {topic_str}.")
    return teaser_md, status, "OK"

async def create_startup_debug_report(db: AsyncSession):
    """Generates a dummy 'System Startup' report to verify DB write capability."""
    # HARD-DISABLED for Production Stability
    return

    logger.info("Generating STARTUP DEBUG DUMMY REPORT...")
    try:
        now = datetime.now(timezone.utc)
        title = f"System Startup Diagnostic: {now.strftime('%Y-%m-%d %H:%M:%S')}"
        
        # Check if a startup report already exists for this exact minute (prevent double inserts on fast restart)
        stmt = select(Report).where(Report.report_type == "system_diagnostic").order_by(Report.created_at.desc()).limit(1)
        existing = (await db.execute(stmt)).scalars().first()
        
        if existing and (now - existing.created_at).total_seconds() < 60:
            logger.info("Startup diagnostic report already exists. Skipping.")
            return

        dummy = Report(
            title=title,
            teaser_md="This is a diagnostic report generated automatically at system startup to verify database write capabilities.",
            content_markdown="# Diagnostic Report\n\nDatabase: PostgreSQL (Render)\nStatus: RUNNING",
            report_type="system_diagnostic",
            topic_code="system",
            is_premium=False,
            source_count=0,
            confidence_level="High"
        )
        db.add(dummy)
        await db.commit()
        logger.info("STARTUP DEBUG DUMMY REPORT SAVED SUCCESSFULLY.")
    except Exception as e:
        logger.error(f"FAILED to generate startup debug report: {e}")

async def report_worker(queue: asyncio.Queue, results_collector: Dict[str, str]):
    while True:
        task = await queue.get()
        if task is None:
            queue.task_done()
            break
        
        args = task
        topic_key = args[2] or "global"
        
        try:
            async with AsyncSessionLocal() as session:
                teaser, status, reason = await asyncio.wait_for(
                    run_report_generation(session, *args[:3], auto_post_threads=args[3]),
                    timeout=REPORT_TASK_DEADLINE
                )
                results_collector[topic_key] = status
                logger.info(f"Report finished: {topic_key} | Status: {status}")
        except Exception as e:
            logger.error(f"Worker failed category {topic_key}: {e}")
            results_collector[topic_key] = "failed"
        finally:
            queue.task_done()

async def run_all_reports(db, report_type: str = "daily_global", period_days: int = 1, auto_post_threads: bool = False):
    queue = asyncio.Queue()
    results_collector = {}
    
    # Populate Queue
    # tuple format: (report_type, period_days, topic, auto_post_threads)
    queue.put_nowait((report_type, period_days, None, auto_post_threads))
    for t in TOPIC_CONFIG.keys():
        queue.put_nowait((report_type, period_days, t, auto_post_threads))

    workers = [asyncio.create_task(report_worker(queue, results_collector)) for _ in range(NUM_WORKERS)]
    await queue.join()
    for _ in range(NUM_WORKERS): queue.put_nowait(None)
    await asyncio.gather(*workers)

    # Logging Summary
    success_count = sum(1 for v in results_collector.values() if v == "success")
    degraded_count = sum(1 for v in results_collector.values() if v == "degraded")
    failed_count = sum(1 for v in results_collector.values() if v == "failed")
    
    logger.info("--- Report Generation Summary ---")
    logger.info(f"Categories Processed: {len(results_collector)} / {EXPECTED_CATEGORIES}")
    logger.info(f"Results: {results_collector}")
    logger.info(f"Success: {success_count}, Degraded: {degraded_count}, Failed: {failed_count}")
    
    if len(results_collector) < EXPECTED_CATEGORIES or failed_count > 0:
        logger.warning(f"!!! INCOMPLETE REPORT JOB DETECTED !!! Missing or failed categories.")

    logger.info(get_metrics_summary())

if __name__ == "__main__":
    import uuid
    async def main():
        async with AsyncSessionLocal() as session:
            await run_all_reports(session)
    asyncio.run(main())
