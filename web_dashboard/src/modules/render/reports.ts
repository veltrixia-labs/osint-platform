import { getTopicDef, canAccessReport, normalizeReportType, REPORT_TYPE_LABELS, REPORT_TYPE_MIN_TIER } from '../topics';
import { sanitizeMarkdownIntensities, simpleMarkdown } from './utils';

/**
 * Renders the full Situational Report detail view.
 * Handles section extraction and role-based masking (paywalling).
 */
export function renderReportDetail(report: any, userTier: string, container: HTMLElement, onBack?: () => void) {
    const dateStr = report.created_at || "";
    const cleanDate = dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T');
    const date = new Date(cleanDate).toLocaleDateString();

    // [v30] Dynamic Topic Sync: Infer topic from title suffix if possible
    let effectiveTopic = report.topic_code ?? null;
    const titleMatch = report.title ? report.title.match(/\|\s*([^\|\s].*)$/) : null;
    if (titleMatch) {
        const titleSuffix = titleMatch[1].toLowerCase();
        if (titleSuffix.includes('energy')) effectiveTopic = 'energy_resource_risk';
        else if (titleSuffix.includes('market')) effectiveTopic = 'global_market_intelligence';
        else if (titleSuffix.includes('defense')) effectiveTopic = 'defense_technology';
        else if (titleSuffix.includes('ai') || titleSuffix.includes('semiconductor')) effectiveTopic = 'ai_semiconductor_intelligence';
        else if (titleSuffix.includes('supply')) effectiveTopic = 'supply_chain_intelligence';
        else if (titleSuffix.includes('crypto')) effectiveTopic = 'crypto_geopolitics';
    }

    const topicDef = getTopicDef(effectiveTopic);
    const topicLabel = `${topicDef.icon} ${topicDef.label}`;
    const rtNorm = normalizeReportType(report.report_type);
    const rtLabel = REPORT_TYPE_LABELS[rtNorm] ?? rtNorm.toUpperCase();
    
    // Check access using CENTRALIZED ENTITLEMENTS
    const hasAccess = canAccessReport(userTier, report.report_type, report.topic_code ?? null);
    const isPreview = !hasAccess || report.is_preview === true || report.locked === true;
    
    // Determine required plan for display
    const planReq = report.plan_required || REPORT_TYPE_MIN_TIER[rtNorm] || 'free';

    let md = isPreview ? (report.content_preview || "") : (report.content_markdown || "");
    let evidenceData: any[] = [];
    const evidenceMatch = md.match(/<!--\s*EVIDENCE_JSON:\s*([\s\S]*?)\s*-->/);
    if (evidenceMatch) {
        try {
            evidenceData = JSON.parse(evidenceMatch[1]);
            md = md.replace(evidenceMatch[0], '');
        } catch (e) { console.error("Evidence parse error", e); }
    }

    // [v32] Universal Source Stripping (More aggressive regex, applied BEFORE backup)
    const sourceRegex = /^(#+\s*)?(Sources|Evidence|References|EVIDENCE LOG|Sources used|Key Sources)\b/gim;
    const lines = md.split('\n');
    let sourceStartLine = -1;
    for (let i = 0; i < lines.length; i++) {
        if (lines[i].match(sourceRegex)) {
            sourceStartLine = i;
            break;
        }
    }

    if (sourceStartLine !== -1) {
        md = lines.slice(0, sourceStartLine).join('\n').trim();
    }

    const fullOriginalMd = md; // [v31/v32] Backup for failsafe fallback (now safely stripped)

    // Terminology Normalization (Depth-based Differentiation)
    const isExpertPlus = planReq === 'experts' || planReq === 'enterprise';
    if (isExpertPlus) {
        md = md.replace(/# Scenarios/g, '# Strategic Scenarios');
        md = md.replace(/# Monitoring Points/g, '# 30–60 Day Outlook');
    } else {
        md = md.replace(/# Scenarios/g, '# Potential Developments');
    }

    container.innerHTML = `
        <div class="report-detail">
            <div class="u-flex-between u-m-top-1" style="margin-bottom: var(--space-m); flex-wrap: wrap; gap: 1rem;">
                <div class="u-flex" style="flex-wrap: wrap; row-gap: 0.5rem;">
                    <button class="btn-fb active u-tier-1" id="back-to-feed-btn">← Back</button>
                    <div style="color: #8b949e; font-size: var(--font-s); display: flex; align-items: center; gap: var(--space-xs); flex-wrap: wrap;">
                        <span style="font-weight: 600; color: #c9d1d9;">${topicLabel}</span>
                        <span style="opacity: 0.5;">|</span>
                        <span>${rtLabel.toUpperCase()}</span>
                        <span style="opacity: 0.5;">|</span>
                        <span style="color: #d29922; font-weight: 500;">${(report.plan_required || "free").toUpperCase()} Plan</span>
                        <span style="opacity: 0.5;">|</span>
                        <span>${date}</span>
                    </div>
                </div>
                ${isPreview ? '<span class="tier-badge" style="background: rgba(210,153,34,0.1); color: #d29922; border: 1px solid rgba(210,153,34,0.3);">PREVIEW</span>' : ''}
            </div>
            
            <div class="report-content-card u-m-top-1">
                <h1 style="margin-bottom: 1.5rem;">${report.title}</h1>
                <div class="u-m-top-1" style="text-align: left; margin-bottom: 2rem;">
                    <div class="confidence-trigger u-flex u-tier-2" style="display: inline-flex; background: var(--accent-soft); color: #58a6ff; padding: 8px 18px; border-radius: 12px; font-size: var(--font-m); border: 1px solid var(--border-active); cursor: pointer; user-select: none; gap: 0.75rem; align-items: center; transition: all 0.2s;">
                        <span style="font-size: 1.1rem;">📊</span> 
                        <span style="font-weight: 600;">Confidence: ${report.confidence_level || 'High'}</span>
                        <span class="chevron-icon" style="transition: transform 0.3s;">▾</span>
                    </div>

                    <div id="evidence-panel-inline" style="display: none; background: #0d1117; border: 1px solid var(--border-active); border-radius: 12px; margin-top: 1rem; padding: 1.5rem; box-shadow: 0 8px 24px rgba(0,0,0,0.4);">
                        <div class="u-flex-between" style="font-size: var(--font-xs); color: #8b949e; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 1.5rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem;">
                            <span>Source Transparency & Evidence Hub</span>
                            <button class="close-panel-btn" style="background: none; border: none; color: #8b949e; cursor: pointer; font-size: 1.1rem;">&times;</button>
                        </div>
                        
                        ${evidenceData.length > 0 ? `
                            <div class="u-flex" style="flex-direction: column; gap: 1.5rem;">
                                ${evidenceData.map(e => `
                                    <div style="border-left: 3px solid var(--accent); padding-left: 1.25rem;">
                                        <div class="u-flex-between" style="margin-bottom: 0.75rem; align-items: flex-start;">
                                            <div style="font-weight: 600; color: #c9d1d9; font-size: var(--font-m);">${e.title}</div>
                                            <span style="font-size: var(--font-xs); background: var(--accent-soft); color: #58a6ff; padding: 4px 10px; border-radius: 12px; border: 1px solid var(--border-active); white-space: nowrap;">${e.type}</span>
                                        </div>
                                        <div style="font-size: var(--font-s); color: #8b949e; line-height: 1.7; margin-bottom: 1rem;">${e.explanation}</div>
                                        ${e.link && e.link !== '#' ? `
                                            <a href="${e.link}" target="_blank" class="btn-fb u-flex u-tier-1" style="text-decoration: none; font-size: var(--font-xs); display: inline-flex;">🔗 View Source</a>
                                        ` : '<div style="font-size: var(--font-xs); color: #8b949e; opacity: 0.6; font-style: italic;">🔒 Private Intel Source</div>'}
                                    </div>
                                `).join('')}
                            </div>
                        ` : '<div class="u-p-2 u-text-center">ℹ️ Detailed evidence list pending enrichment...</div>'}
                    </div>
                </div>

                <div class="markdown-body u-m-top-1" style="${isPreview ? 'mask-image: linear-gradient(to bottom, black 50%, transparent 100%); -webkit-mask-image: linear-gradient(to bottom, black 50%, transparent 100%);' : ''}">
                    ${(() => {
                        if (isPreview) return simpleMarkdown(md);

                        // Prioritize sections for better scan efficiency
                        const lines = md.split('\n');
                        const sections: { title: string, content: string }[] = [];
                        let currentSec = { title: '', content: '' };
                        lines.forEach((l: string) => {
                            const h = l.match(/^(#{1,3})\s*(.*)$/);
                            if (h) {
                                if (currentSec.title || currentSec.content.trim()) sections.push({ ...currentSec });
                                currentSec = { title: h[2].trim(), content: '' };
                            } else {
                                currentSec.content += l + '\n';
                            }
                        });
                        if (currentSec.title || currentSec.content.trim()) sections.push(currentSec);

                        const findSec = (names: string[]) => {
                            const idx = sections.findIndex(s => 
                                names.some(n => s.title.toLowerCase().includes(n.toLowerCase())) &&
                                s.content.trim().length > 30 
                            );
                            if (idx === -1) return null;
                            return sections.splice(idx, 1)[0];
                        };

                        // Extract Summary & Actions with robust backward compatibility
                        const executive = findSec(['Executive Summary', 'Executive Signal', 'Summary', 'Key Insights']);
                        const actions = findSec(['Key Actions', 'Recommendations', 'Next Steps']);
                        const developments = findSec(['Key Developments', 'Key Findings', 'Analysis']);
                        const trend = findSec(['Trend Analysis', 'Market Context']);
                        const scenarios = findSec(['Strategic Forecast', 'Strategic Scenarios', 'Potential Developments', 'Scenarios', 'Outlook', 'Monitoring']);

                        let html = '';
                        
                        const renderSec = (s: any, priority: 'medium' | 'low' = 'medium') => 
                            s ? `<div class="report-section--${priority}"><h3>${s.title}</h3>${simpleMarkdown(sanitizeMarkdownIntensities(s.content))}</div>` : '';

                        if (executive) {
                            html += `<div class="report-summary-box">
                                <div class="summary-section">
                                    <div class="summary-label">EXECUTIVE SIGNAL</div>
                                    <div class="summary-content">${simpleMarkdown(sanitizeMarkdownIntensities(executive.content.trim()))}</div>
                                </div>
                            </div>`;
                        }

                        if (actions) {
                            html += `<div class="report-actions-box">
                                <h1>Key Actions</h1>
                                <ul>${simpleMarkdown(sanitizeMarkdownIntensities(actions.content.trim()))}</ul>
                            </div>`;
                        }

                        // Failsafe
                        if (!executive && !actions && sections.length > 0) {
                            const first = sections.shift();
                            if (first) {
                                html += `<div class="report-summary-box">
                                    <div class="summary-section">
                                        <div class="summary-label">EXECUTIVE SIGNAL</div>
                                        <div class="summary-content">${simpleMarkdown(sanitizeMarkdownIntensities(first.content.trim()))}</div>
                                    </div>
                                </div>`;
                            }
                        }

                        const impact = findSec(['Impact Analysis', 'Watch Points', 'Potential Implications']);
                        if (impact) html += renderSec(impact, 'medium');

                        html += renderSec(developments, 'medium');
                        html += renderSec(trend, 'medium');
                        html += renderSec(scenarios, 'low');
                        
                        sections.forEach(s => {
                            html += renderSec(s, 'low');
                        });

                        // [v30] Content Lockdown: Fallback
                        const sourceLen = md.trim().length;
                        const resultLen = html.replace(/<[^>]*>/g, '').trim().length; 
                        const isAbnormallyThin = sourceLen > 500 && resultLen < 150;

                        if ((!html.trim() || isAbnormallyThin) && sourceLen > 0) {
                            html = simpleMarkdown(sanitizeMarkdownIntensities(fullOriginalMd)); 
                        }
                        
                        return html || `<div class="u-p-2 u-text-center" style="opacity:0.6;">(Detailed intelligence for this sector is currently being synchronized...)</div>`;
                    })()}
                </div>

                ${isPreview ? `
                    <div class="vlt-mosaic-mask" style="border-radius: 12px; margin-top: 1rem;">
                        <div class="vlt-lock-icon">🔒</div>
                        <div class="vlt-gating-title">Full Investigation Restricted</div>
                        <div class="vlt-gating-text" style="margin-bottom: 1.5rem;">
                            Access the complete multi-dimensional analysis, entity relationship logs, and <span style="color:#58a6ff; font-weight:600;">Direct Professional Delivery</span>.
                        </div>

                        <div style="max-width: 450px; margin: 0 auto; width: 100%;">
                            <table class="comparison-table-mini" style="margin-bottom: 1.5rem;">
                                <tr>
                                    <td>Thematic Coverage</td>
                                    <td style="opacity:0.6;">Regional</td>
                                    <td class="expert-val">Global Nexus</td>
                                </tr>
                                <tr>
                                    <td>Signal Granularity</td>
                                    <td style="opacity:0.6;">Standard</td>
                                    <td class="expert-val">Entity-Level</td>
                                </tr>
                                <tr>
                                    <td>Prediction Window</td>
                                    <td style="opacity:0.6;">7-day</td>
                                    <td class="expert-val">30-60 day</td>
                                </tr>
                            </table>
                        </div>

                        <button class="vlt-mosaic-cta trigger-login-btn" style="width: 100%; max-width: 320px; justify-content: center; height: 50px;">
                            <span>Sign Up to Unlock Full Intelligence</span>
                        </button>
                    </div>
                ` : ''}
            </div>
        </div>
    `;

    const backBtn = container.querySelector('#back-to-feed-btn');
    if (backBtn) {
        backBtn.addEventListener('click', () => {
             if (onBack) onBack();
             else document.querySelector<HTMLElement>('#nav-feed')?.click();
        });
    }

    const trigger = container.querySelector('.confidence-trigger');
    const panel = container.querySelector('#evidence-panel-inline') as HTMLElement;
    const closeBtn = container.querySelector('.close-panel-btn');
    const chevron = container.querySelector('.chevron-icon') as HTMLElement;

    if (trigger && panel) {
        trigger.addEventListener('click', () => {
            const isHidden = panel.style.display === 'none';
            panel.style.display = isHidden ? 'block' : 'none';
            if (chevron) chevron.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
        });

        if (closeBtn) {
            closeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                panel.style.display = 'none';
                if (chevron) chevron.style.transform = 'rotate(0deg)';
            });
        }
    }

    if (isPreview) {
        container.querySelectorAll('.trigger-login-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                window.dispatchEvent(new CustomEvent('trigger-login'));
            });
        });
    }
}
