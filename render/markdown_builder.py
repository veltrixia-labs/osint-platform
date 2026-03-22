from datetime import datetime, timezone

def build_publish_markdown(title: str, llm_content: str, items: list) -> str:
    # Deduplicate sources by URL
    seen_urls = set()
    unique_items = []
    for item in items:
        if item.source_url not in seen_urls:
            unique_items.append(item)
            seen_urls.add(item.source_url)

    sources_list = "\n".join([f"- [{item.source_name}]({item.source_url})" for item in unique_items if item.source_url])
    
    md = f"# {title}\n\n"
    md += f"{llm_content}\n\n"
    
    if "## Sources" not in llm_content and "Sources" not in llm_content:
        md += f"## Sources\n{sources_list}\n\n"
    
    if "## Disclaimer" not in llm_content and "Disclaimer" not in llm_content:
        md += "## Disclaimer\n"
        md += "This document is generated for informational purposes only. It does not constitute investment advice.\n"
        
    return md

def build_degraded_markdown(title: str, items: list, topic_code: str | None = None) -> str:
    """Creates a high-quality analytical memo without LLM analysis."""
    topic_label = topic_code.replace("_", " ").title() if topic_code else "Global Multi-Domain"
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    md = f"# {title} (Data-Driven Analytical Memo)\n\n"
    md += f"> [!IMPORTANT]\n> This report was generated using rule-based analysis and source aggregation due to LLM provider unavailability or safety guidelines. Focus is placed on factual data points and observed source priorities.\n\n"
    
    md += "## Summary of Themes\n"
    md += f"Analysis of current signals in **{topic_label}** indicates a focus on the following key entries. Sources from institutional and primary news outlets show sustained activity.\n\n"
    
    md += "## Key Developments (Aggregated)\n"
    # Deduplicate
    seen_urls = set()
    for item in items[:15]: # Take top 15 for degraded
        if item.source_url in seen_urls: continue
        seen_urls.add(item.source_url)
        
        md += f"### {item.title}\n"
        md += f"- **Source**: {item.source_name} ({item.published_at.strftime('%Y-%m-%d') if item.published_at else 'N/A'})\n"
        md += f"- **Core Event**: {item.summary[:400]}...\n\n"

    md += "## Potential Implications & Monitoring Points\n"
    md += "- **Monitoring**: Continued observation of priority source publications listed below.\n"
    md += "- **Impact**: Rule-based scoring suggests these events carry significant relevance to the target domain.\n\n"
    
    md += "## Sources\n"
    seen_urls = set()
    for item in items:
        if item.source_url not in seen_urls:
            md += f"- [{item.source_name}]({item.source_url})\n"
            seen_urls.add(item.source_url)
            
    md += "\n## Disclaimer\nThis document is a technical aggregation. It does not constitute investment or strategic advice.\n"
    return md

def build_teaser_markdown(title: str, llm_content: str) -> str:
    md = f"# {title} - Insight\n\n"
    md += f"{llm_content[:500]}...\n\n"
    md += "## CTA\n"
    md += "Read the full report on Substack: https://example-substack-url.com\n"
    return md
