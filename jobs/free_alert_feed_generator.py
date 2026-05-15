import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import select, or_

from db.models import Item, Stakeholder, Dependency
from analysis.free_company_matcher import match_news_to_companies, sector_impacts_from_companies
from reports.free_alert_builder import build_company_impact_alert
from processor.location_resolver import LocationResolver
from processor.location_context import build_location_company_supplement

logger = logging.getLogger(__name__)

_location_resolver_singleton: Optional[LocationResolver] = None


async def _load_stakeholders_and_dependencies(db):
    """
    Load stakeholder graph for company matching. On missing table / SQL error,
    returns empty structures so Context Briefs generation can continue.
    """
    try:
        stmt_stk = select(Stakeholder).where(Stakeholder.is_auto_provisioned == False)
        stk_records = (await db.execute(stmt_stk)).scalars().all()
        if not stk_records:
            stk_records = (await db.execute(select(Stakeholder))).scalars().all()

        stk_ids = [s.id for s in stk_records]
        deps_records = []
        target_name_map = {}
        if stk_ids:
            stmt_dep = select(Dependency).where(Dependency.source_id.in_(stk_ids))
            deps_records = (await db.execute(stmt_dep)).scalars().all()
            all_target_ids = list({d.target_id for d in deps_records})
            if all_target_ids:
                stmt_targets = select(Stakeholder.id, Stakeholder.name).where(
                    Stakeholder.id.in_(all_target_ids)
                )
                targets_result = (await db.execute(stmt_targets)).all()
                target_name_map = {t[0]: t[1] for t in targets_result}
        return stk_records, deps_records, target_name_map
    except Exception as e:
        logger.error(
            "Stakeholder/dependency lookup skipped (table missing or DB error): %s",
            e,
        )
        return [], [], {}


def _get_location_resolver() -> LocationResolver:
    global _location_resolver_singleton
    if _location_resolver_singleton is None:
        _location_resolver_singleton = LocationResolver()
    return _location_resolver_singleton

async def build_free_alert_feed_item(db, alert_log) -> dict:
    """
    Generates the UI-ready JSON and Markdown for a Company Impact Alert.
    Fetches required news and stakeholder data dynamically.
    Does not write to the DB.
    """
    metadata = alert_log.metadata_json or {}
    related_item_ids = metadata.get("related_item_ids", [])
    
    items = []
    
    # --- 1. Fetch Related News ---
    related_news_source = "none"
    
    if related_item_ids:
        import uuid
        # Fetch by explicitly saved IDs
        related_uuids = [uuid.UUID(uid) for uid in related_item_ids]
        stmt_items = select(Item).where(Item.id.in_(related_uuids))
        items = (await db.execute(stmt_items)).scalars().all()
        if items:
            related_news_source = "related_item_ids"
    
    if not items:
        # Fallback 1: Target label match
        one_day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        target_label = (alert_log.target_label or "").strip()
        
        if len(target_label) >= 3:
            stmt_fallback_label = select(Item).where(
                Item.created_at >= one_day_ago,
                or_(
                    Item.title.ilike(f"%{target_label}%"),
                    Item.summary.ilike(f"%{target_label}%")
                )
            ).order_by(Item.created_at.desc()).limit(10)
            items = (await db.execute(stmt_fallback_label)).scalars().all()
            if items:
                related_news_source = "target_label_fallback"
                
    if not items:
        # Fallback 2: Topic match (category from keyword normalize — no LLM required)
        topic = (alert_log.topic or "").strip()
        if topic:
            stmt_fallback_topic = select(Item).where(
                Item.created_at >= one_day_ago,
                or_(
                    Item.category == topic,
                    Item.rough_category == topic,
                ),
            ).order_by(Item.created_at.desc()).limit(5)
            items = (await db.execute(stmt_fallback_topic)).scalars().all()
            if items:
                related_news_source = "topic_fallback"

    if not items:
        # Fallback 3: Recent items (physical pipeline — show latest context without AI category)
        stmt_recent = (
            select(Item)
            .where(Item.created_at >= one_day_ago)
            .order_by(Item.created_at.desc())
            .limit(5)
        )
        items = (await db.execute(stmt_recent)).scalars().all()
        if items:
            related_news_source = "recent_items_fallback"

    # --- 2. Fetch Stakeholders (optional; Briefs still generate if table missing) ---
    stk_records, deps_records, target_name_map = await _load_stakeholders_and_dependencies(db)
            
    # Assembly
    stk_map = {}
    for s in stk_records:
        stk_map[s.id] = {
            "id": str(s.id),
            "name": s.name,
            "ticker": s.ticker,
            "sector": s.sector,
            "country": s.country,
            "description": s.description,
            "top_dependencies": []
        }
        
    for d in deps_records:
        if d.source_id in stk_map:
            t_name = target_name_map.get(d.target_id, "Unknown")
            stk_map[d.source_id]["top_dependencies"].append({
                "target": t_name,
                "type": d.dependency_type,
                "weight": d.exposure_weight
            })
            
    stakeholders_list = list(stk_map.values())
    
    # --- 4. Run Matcher ---
    company_impacts, _sector_unused = match_news_to_companies(items, [], stakeholders_list)

    resolver = _get_location_resolver()
    sup_rows, loc_ctx = build_location_company_supplement(alert_log, resolver)
    seen_names = {str(c.get("company_name", "")).strip().lower() for c in company_impacts if c.get("company_name")}
    for srow in sup_rows:
        k = str(srow.get("company_name", "")).strip().lower()
        if not k or k in seen_names:
            continue
        seen_names.add(k)
        company_impacts.append(srow)

    def _concrete_entity_rank(c: dict) -> int:
        if str(c.get("registry_entity_type") or "").lower() == "company":
            return 1
        t = (c.get("ticker") or "").strip()
        return 1 if len(t) >= 2 else 0

    company_impacts.sort(
        key=lambda x: (
            -float(x.get("_internal_score", 0.0) or 0.0),
            -_concrete_entity_rank(x),
            str(x.get("company_name") or "").lower(),
        )
    )
    sector_impacts = sector_impacts_from_companies(company_impacts)

    # Free-tier display cap vs full merged list (Pro-gate "additional" count)
    display_cap = int(os.getenv("FREE_ALERT_COMPANY_IMPACT_DISPLAY_CAP", "1"))
    store_max = int(os.getenv("FREE_ALERT_COMPANY_IMPACT_STORE_MAX", "50"))
    total_impacts = len(company_impacts)
    additional_pro_count = min(99, max(0, total_impacts - 1))

    # --- 5. Generate Markdown ---
    content_markdown = build_company_impact_alert(
        alert_log=alert_log,
        items=items,
        company_impacts=company_impacts,
        sector_impacts=sector_impacts
    )
    
    # --- 6. Assemble UI JSON ---
    t_time = alert_log.triggered_at
    triggered_at_str = t_time.isoformat() if hasattr(t_time, 'isoformat') else str(t_time) if t_time else ""
    
    related_news = []
    for item in items:
        pub = getattr(item, "published_at", None) or getattr(item, "created_at", None)
        pub_str = pub.strftime("%Y-%m-%d %H:%M") if hasattr(pub, "strftime") else str(pub) if pub else ""
        related_news.append({
            "title": getattr(item, "title", "") or "",
            "source": getattr(item, "source_name", None) or getattr(item, "source_group", None) or "Unknown",
            "category": getattr(item, "category", None) or getattr(item, "rough_category", None) or "uncategorized",
            "published": pub_str,
            "url": getattr(item, "source_url", None),
        })
        
    company_impacts_public = [
        {
            "company_name": c.get("company_name"),
            "ticker": c.get("ticker"),
            "sector": c.get("sector"),
            "country": c.get("country"),
            "match_basis": c.get("match_basis") or [],
            "registry_entity_type": c.get("registry_entity_type"),
        }
        for c in company_impacts[:store_max]
    ]

    sector_impacts_public = [
        {
            "sector": s.get("sector"),
            "matched_entities": int(s.get("matched_entities") or 0),
        }
        for s in (sector_impacts or [])
        if int(s.get("matched_entities") or 0) > 0
    ]

    ui_feed_item = {
        "alert_id": str(alert_log.id) if alert_log.id else "",
        "title": f"{alert_log.trigger_type or 'Alert'}: {alert_log.target_label or 'Unknown'}",
        "topic": alert_log.topic or "Unknown",
        "target_label": alert_log.target_label or "Unknown",
        "triggered_at": triggered_at_str,
        "related_news_count": len(items),
        "related_news_source": related_news_source,
        "related_entities_count": len(company_impacts),
        "related_news": related_news,
        "content_markdown": content_markdown,
        "location_context": loc_ctx,
        "company_impacts": company_impacts_public,
        "sector_impacts": sector_impacts_public,
        "additional_pro_count": additional_pro_count,
        "free_company_impact_display_cap": display_cap,
    }
    
    return ui_feed_item

async def persist_free_alert_feed_item(db, alert_log, *, commit: bool = True) -> dict:
    """
    Builds the Free Alert Feed item and persists it into the AlertLog's metadata_json.
    Stores a nested object at metadata_json["free_alert"] (not a boolean flag).
    Does not overwrite existing metadata such as related_item_ids or scoring_breakdown.
    """
    ui_feed_item = await build_free_alert_feed_item(db, alert_log)
    ui_feed_item["generated_at"] = datetime.now(timezone.utc).isoformat()

    current_metadata = alert_log.metadata_json or {}
    if not isinstance(current_metadata, dict):
        current_metadata = {}

    updated_metadata = dict(current_metadata)
    updated_metadata["free_alert"] = ui_feed_item
    alert_log.metadata_json = updated_metadata

    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(alert_log, "metadata_json")
    db.add(alert_log)

    if commit:
        await db.commit()
        await db.refresh(alert_log)

    logger.info(
        "Persisted free_alert for alert_id=%s topic=%r news_count=%s",
        alert_log.id,
        alert_log.topic,
        ui_feed_item.get("related_news_count", 0),
    )
    return ui_feed_item


def _alertlog_has_free_alert_payload(meta) -> bool:
    if not isinstance(meta, dict):
        return False
    fa = meta.get("free_alert")
    return isinstance(fa, dict) and bool(fa.get("alert_id") or fa.get("title"))


async def backfill_missing_free_alerts(db, limit: int = 50) -> int:
    """Attach free_alert payloads to recent AlertLogs that lack them (no LLM required)."""
    from db.models import AlertLog

    stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(max(limit * 3, limit))
    rows = (await db.execute(stmt)).scalars().all()
    ok = 0
    for alert in rows:
        if _alertlog_has_free_alert_payload(alert.metadata_json):
            continue
        try:
            await persist_free_alert_feed_item(db, alert, commit=True)
            ok += 1
        except Exception as e:
            logger.exception("backfill free_alert failed for alert %s: %s", alert.id, e)
            await db.rollback()
        if ok >= limit:
            break
    if ok:
        logger.info("backfill_missing_free_alerts: wrote free_alert for %s alert(s)", ok)
    return ok
