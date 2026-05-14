def _sanitize_cell(value) -> str:
    """Sanitizes text for safe inclusion in Markdown tables."""
    text = str(value or "")
    text = text.replace("\n", " ").replace("\r", " ")
    text = text.replace("|", "\\|")
    return text.strip()

def build_company_impact_alert(
    alert_log,
    items,
    company_impacts,
    sector_impacts,
) -> str:
    """
    Builds the Company Impact Alert Markdown feed for Free tier users.
    No LLM, DB, or external API calls are made here.
    """
    items = items or []
    company_impacts = company_impacts or []
    sector_impacts = sector_impacts or []
    
    # --- 1. Extract Alert Summary Data ---
    a_type = _sanitize_cell(getattr(alert_log, "trigger_type", "Unknown"))
    a_topic = _sanitize_cell(getattr(alert_log, "topic", "Unknown"))
    a_label = _sanitize_cell(getattr(alert_log, "target_label", "Unknown"))
    
    a_time = getattr(alert_log, "triggered_at", None)
    a_time_str = a_time.strftime("%Y-%m-%d %H:%M:%S UTC") if hasattr(a_time, "strftime") else str(a_time) if a_time else "Unknown"

    md = []
    md.append("# Company Impact Alert")
    md.append("")
    
    # --- 1. Alert Summary ---
    md.append("## 1. Alert Summary")
    md.append(f"- **Alert type:** {a_type}")
    md.append(f"- **Triggered at:** {a_time_str}")
    md.append(f"- **Topic:** {a_topic}")
    md.append(f"- **Target label:** {a_label}")
    md.append("")
    
    # --- 2. Related News ---
    md.append("## 2. Related News")
    md.append("| News | Source | Category | Published |")
    md.append("|---|---|---|---|")
    
    processed_items = []
    for item in items:
        title = getattr(item, 'title', '') or ''
        if len(title) > 120:
            title = title[:117] + "..."
            
        source = getattr(item, "source_name", None) or getattr(item, "source_group", None) or "Unknown"
        category = getattr(item, "category", None) or getattr(item, "rough_category", None) or "uncategorized"
        score = getattr(item, "lightweight_score", 0.0)
        
        pub = getattr(item, 'published_at', None) or getattr(item, 'created_at', None)
        pub_str = pub.strftime("%Y-%m-%d %H:%M") if hasattr(pub, 'strftime') else str(pub) if pub else "Unknown"
        
        processed_items.append({
            "title": _sanitize_cell(title),
            "source": _sanitize_cell(source),
            "category": _sanitize_cell(category),
            "published": _sanitize_cell(pub_str),
            "score": float(score) if score is not None else 0.0
        })
        
    # Sort related news by score descending
    processed_items.sort(key=lambda x: x["score"], reverse=True)
    
    for p_item in processed_items[:10]: # Limit to 10
        md.append(f"| {p_item['title']} | {p_item['source']} | {p_item['category']} | {p_item['published']} |")
        
    if not processed_items:
        md.append("| No related news found | - | - | - |")
    md.append("")
    
    # --- 3. Related Companies & Infrastructure ---
    md.append("## 3. Related Companies & Infrastructure")
    md.append("| Name | Ticker | Sector | Country | Match Basis |")
    md.append("|---|---|---|---|---|")
    
    displayed_companies = 0
    for ci in company_impacts:
        c_basis_list = ci.get("match_basis", [])
        if not c_basis_list:
            continue # Skip if match basis is empty
            
        c_name = ci.get("company_name", "")
        if len(c_name) > 120:
            c_name = c_name[:117] + "..."
            
        c_name = _sanitize_cell(c_name)
        c_ticker = _sanitize_cell(ci.get("ticker") or "—")
        c_sector = _sanitize_cell(ci.get("sector", ""))
        c_country = _sanitize_cell(ci.get("country", ""))
        c_basis = _sanitize_cell(", ".join(c_basis_list))
        
        md.append(f"| {c_name} | {c_ticker} | {c_sector} | {c_country} | {c_basis} |")
        displayed_companies += 1
        
        if displayed_companies >= 10:
            break
            
    if displayed_companies == 0:
        md.append("| No significantly affected entities identified | — | - | - | - |")
    md.append("")
    
    # --- 4. Sector coverage (markdown fallback; UI uses structured sector_impacts) ---
    md.append("## 4. Sector Coverage")
    md.append("| Sector | Matched Entities |")
    md.append("|---|---:|")
    
    displayed_sectors = 0
    for si in sector_impacts:
        s_comps = si.get("matched_entities", 0)
        if s_comps <= 0:
            continue # Only show sectors with impact
            
        s_name = _sanitize_cell(si.get("sector", ""))
        
        md.append(f"| {s_name} | {s_comps} |")
        displayed_sectors += 1
        
    if displayed_sectors == 0:
        md.append("| No sector coverage identified | 0 |")
    md.append("")
    
    # --- 5. Data Notes ---
    md.append("## 5. Data Notes")
    md.append("- This alert is generated using RSS-based signals and the registered company dependency database.")
    md.append("- Listed entities are rule-based matches, not ranked impact assessments.")
    md.append("- No BEA, Census, Trade, PPI, FRED, or macroeconomic datasets are used in the Free alert.")
    md.append("- No LLM interpretation, forecasting, scenario analysis, or investment recommendation is included.")
    md.append("")
    
    return "\n".join(md)
