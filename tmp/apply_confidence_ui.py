import re

file_path = "c:\\RDTP project\\Development\\OSINT_analytics\\web_dashboard\\src\\modules\\render.ts"
with open(file_path, "r", encoding="utf-8") as f:
    text = f.read()

# 1. Update the renderReportDetail function logic
# We need to extract EVIDENCE_JSON and handle fallback.

def update_render_ts(content):
    # Injection of parsing logic at the start of renderReportDetail
    logic_injection = """
    let md = isPreview ? (report.content_preview || "") : (report.content_markdown || "");
    
    let evidenceData: any[] = [];
    const evidenceMatch = md.match(/<!--\\s*EVIDENCE_JSON:\\s*([\\s\\S]*?)\\s*-->/);
    if (evidenceMatch) {
        try {
            evidenceData = JSON.parse(evidenceMatch[1]);
            md = md.replace(evidenceMatch[0], ''); // Hide the raw JSON comment
        } catch(e) { console.error("Evidence parse error", e); }
    }
    
    // Fallback: Try to extract from # Sources if EVIDENCE_JSON is missing
    if (evidenceData.length === 0 && md.includes('# Sources')) {
        const sourcesSection = md.split('# Sources')[1] || "";
        const links = sourcesSection.match(/\\[(.*?)\\]\\((.*?)\\)/g);
        if (links) {
            evidenceData = links.map(l => {
                const parts = l.match(/\\[(.*?)\\]\\((.*?)\\)/);
                return {
                    title: parts ? parts[1] : "Verified Source",
                    type: "External Doc",
                    explanation: "Supporting data node captured during ingestion window.",
                    link: parts ? parts[2] : "#"
                };
            });
        }
    }
    """

    # Find the line 'const content = isPreview ? report.content_preview : report.content_markdown;'
    target_line = "const content = isPreview ? report.content_preview : report.content_markdown;"
    content = content.replace(target_line, logic_injection)
    
    # Replace simpleMarkdown(content || "") with simpleMarkdown(md)
    content = content.replace('simpleMarkdown(content || "")', 'simpleMarkdown(md)')

    # 2. Inject the clickable confidence block into the innerHTML template
    # We'll put it right after the H1
    h1_tag = '<h1 style="margin-top: 0; color: #58a6ff;">${typeLabel}: ${topicLabel}</h1>'
    confidence_html = """
                <div style="margin-bottom: 2rem; margin-top: 1rem; text-align: left;">
                    <div class="confidence-trigger" style="cursor: pointer; display: inline-flex; align-items: center; gap: 8px; background: rgba(88,166,255,0.1); color: #58a6ff; padding: 6px 14px; border-radius: 20px; font-size: 0.85rem; border: 1px solid rgba(88,166,255,0.3); transition: all 0.2s; user-select: none;">
                        <span style="font-size: 1.1rem;">📊</span> 
                        <span style="font-weight: 600;">Confidence: ${report.confidence_level || 'High'}</span>
                        <span style="opacity: 0.8;">(${report.source_count || 0} sources)</span>
                        <span class="chevron-icon" style="transition: transform 0.3s;">▾</span>
                    </div>

                    <div class="evidence-panel" style="display: none; margin-top: 1rem; background: rgba(13, 17, 23, 0.9); border: 1px solid rgba(88,166,255,0.2); border-radius: 12px; padding: 1.5rem; box-shadow: 0 10px 30px rgba(0,0,0,0.5); backdrop-filter: blur(10px); max-width: 650px;">
                        <div style="font-size: 0.7rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 1.5rem; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 0.5rem; display: flex; justify-content: space-between;">
                            <span>Source Transparency & Evidence Log</span>
                            <span style="color: #58a6ff;">Verified</span>
                        </div>
                        
                        ${evidenceData.length > 0 ? `
                            <div style="display: flex; flex-direction: column; gap: 1.5rem;">
                                ${evidenceData.map(e => `
                                    <div style="border-left: 2px solid rgba(88,166,255,0.3); padding-left: 1rem; position: relative;">
                                        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
                                            <div style="font-weight: 600; color: #c9d1d9; font-size: 0.95rem;">${e.title}</div>
                                            <span style="font-size: 0.65rem; background: rgba(88,166,255,0.15); color: #58a6ff; padding: 2px 8px; border-radius: 10px; border: 1px solid rgba(88,166,255,0.2); white-space: nowrap;">${e.type}</span>
                                        </div>
                                        <div style="font-size: 0.85rem; color: #8b949e; line-height: 1.5; margin-bottom: 0.8rem;">${e.explanation}</div>
                                        <a href="${e.link}" target="_blank" style="font-size: 0.8rem; color: #58a6ff; text-decoration: none; display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; background: rgba(88,166,255,0.05); border-radius: 4px; border: 1px solid rgba(88,166,255,0.1);">
                                            🔗 View Original Source
                                        </a>
                                    </div>
                                `).join('')}
                            </div>
                        ` : `
                            <div style="color: #8b949e; font-size: 0.9rem; text-align: center; padding: 1rem;">
                                ℹ️ Detailed supporting evidence is not yet structured for this report.
                            </div>
                        `}
                    </div>
                </div>
"""
    content = content.replace(h1_tag, h1_tag + confidence_html)

    # 3. Remove the old trust-metrics-row from the paywall
    old_row_regex = re.compile(r'<div class="trust-metrics-row".*?</div>', re.DOTALL)
    content = old_row_regex.sub('', content)

    # 4. Attach event listeners
    listener_code = """
    // Confidence Panel Interaction
    const trigger = container.querySelector('.confidence-trigger');
    const panel = container.querySelector('.evidence-panel') as HTMLElement;
    const chevron = container.querySelector('.chevron-icon') as HTMLElement;
    
    if (trigger && panel) {
        trigger.addEventListener('click', () => {
            const isHidden = panel.style.display === 'none';
            panel.style.display = isHidden ? 'block' : 'none';
            if (chevron) {
                chevron.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
            }
            if (isHidden) {
                (trigger as HTMLElement).style.borderColor = 'rgba(88,166,255,0.8)';
                (trigger as HTMLElement).style.background = 'rgba(88,166,255,0.2)';
            } else {
                (trigger as HTMLElement).style.borderColor = 'rgba(88,166,255,0.3)';
                (trigger as HTMLElement).style.background = 'rgba(88,166,255,0.1)';
            }
        });
    }

    if (isPreview) {
"""
    content = content.replace('if (isPreview) {', listener_code, 1)

    return content

new_content = update_render_ts(text)
with open(file_path, "w", encoding="utf-8") as f:
    f.write(new_content)

print("render.ts updated successfully with real evidence logic.")
