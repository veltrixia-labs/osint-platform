import { submitFeedback, updateWatchlist } from './api';
import type { Alert, AnalystProfile, HealthData } from './api';
import { getTopicDef, canAccessTopic, canAccessReport, normalizeReportType, REPORT_TYPE_LABELS, REPORT_TYPE_MIN_TIER } from './topics';

function formatIntensity(val: number | undefined | null): string {
    if (typeof val !== 'number') return '0.0';
    const rounded = val.toFixed(1);
    let label = 'Low';
    if (val >= 4) label = 'High';
    else if (val >= 2) label = 'Medium';
    return `${rounded} (${label})`;
}

export function renderHealth(data: HealthData, container: HTMLElement) {
    container.innerHTML = `
        <div class="health-grid">
            <div class="health-stat">
                <span class="health-val">${(data.review_rate * 100).toFixed(0)}%</span>
                <span class="health-label">Review Rate</span>
            </div>
            <div class="health-stat">
                <span class="health-val">${(data.suppression_ratio * 100).toFixed(0)}%</span>
                <span class="health-label">Suppression</span>
            </div>
        </div>
        <div class="trigger-stats u-m-top-1">
            <h4>Top Triggers</h4>
            <div class="u-flex u-m-top-1" style="flex-wrap: wrap; row-gap: 0.5rem;">
                ${(data.top_performing_triggers || []).map(t => `<div class="watchlist-tag">${t.type} (${t.avg_feedback})</div>`).join('')}
            </div>
        </div>
    `;
}

export function renderAlerts(alerts: Alert[], container: HTMLElement, userTier: string = 'free') {
    if (!Array.isArray(alerts)) {
        console.error("renderAlerts expected an array, got:", alerts);
        container.innerHTML = '<div class="u-p-2 u-text-center" style="color:#f85149;">Technical error: invalid alerts data.</div>';
        return;
    }
    container.innerHTML = alerts.map(alert => {
        const topicDef = getTopicDef(alert.topic);
        const accessible = canAccessTopic(userTier, topicDef);
        const severityClass = alert.severity.toLowerCase();
        const date = new Date(alert.triggered_at);
        const displayDate = isNaN(date.getTime()) ? 'Recent' : date.toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });
        
        const triggerLabel = (alert.trigger_type || 'Pattern').replace(/_/g, ' ').toUpperCase();
        const hasReport = !!alert.related_report_id;

        // Note: Alert card access is topic-based. 
        // Report access within the card will be validated upon clicking/loading.
        const cardContent = `
            <div class="alert-header u-flex-between">
                <div class="u-flex" style="flex-wrap: wrap; row-gap: 0.5rem;">
                    <span class="severity-badge">${alert.severity}</span>
                    <span class="watchlist-tag">
                        ${triggerLabel}
                    </span>
                    <span style="color: #8b949e; font-size: var(--font-xs);">${displayDate}</span>
                </div>
                <div class="u-text-right">
                    <div style="font-size: var(--font-xs); color:#8b949e;">Intelligence Priority</div>
                    <div class="intel-score">${accessible ? alert.intelligence_score.toFixed(2) : '•.••'}</div>
                </div>
            </div>
            
            <h3 style="color: #58a6ff; line-height: 1.4; margin-bottom: 0.25rem;">${alert.target_label || 'Unknown Signal'}</h3>
            ${!accessible ? `
                <div style="font-size: var(--font-xs); color: ${topicDef.color}; opacity: 0.9; margin-bottom: 0.75rem; font-weight: 500;">
                    ${topicDef.valueProposition}
                    ${alert.intensity >= 8.0 ? `<span style="display: block; color: #ff7b72; margin-top: 2px;">🔥 High momentum signal detected</span>` : ''}
                </div>
            ` : ''}
            
            <div class="u-grid-2 u-p-1 u-m-top-1" style="background:rgba(255,255,255,0.03); border-radius: 8px; border:1px solid var(--border);">
                <div>
                    <h4>Intensity</h4>
                    <div style="font-size:var(--font-m); color:#c9d1d9; font-weight:600;">${accessible ? formatIntensity(alert.intensity) : '•.••'}/10.0</div>
                </div>
                <div>
                    <h4>Evidence</h4>
                    <div class="evidence-trigger-btn u-tier-1 u-m-top-1" style="color:#58a6ff; background:var(--accent-soft); padding:4px 12px; border-radius:6px; display:inline-block; border:1px solid var(--border-active); font-size: var(--font-s); cursor: ${accessible ? 'pointer' : 'not-allowed'};">
                        🔍 ${accessible ? (alert.domain_count || 0) : '•'} Domains
                    </div>
                </div>
                <div>
                    <h4>Change</h4>
                    <div style="font-size:var(--font-m); color:${accessible && (alert.spike_delta || 0) > 0 ? '#3fb950' : '#8b949e'}; font-weight:600;">
                        ${accessible ? ((alert.spike_delta || 0) > 0 ? '↑' : '') + (alert.spike_delta || 0).toFixed(1) : '•.••'}
                    </div>
                </div>
                ${hasReport ? `
                <div style="display:flex; align-items:flex-end;">
                    <button class="btn-fb active view-report-btn u-w-full u-tier-1 ${!accessible ? 'btn--locked' : ''}">
                        ${accessible ? 'View Analysis' : `Upgrade to ${topicDef.minTier === 'pro' ? 'Pro' : 'Expert'} to access Intelligence`}
                    </button>
                </div>
                ` : `
                <div style="font-size:var(--font-xs); color:#8b949e; display:flex; align-items:flex-end; opacity:0.6; font-style: italic;">
                    ${accessible ? 'Report not available yet' : 'Upgrade Required'}
                </div>
                `}
            </div>

            <div class="u-flex-between u-m-top-1">
                <div style="font-size: var(--font-xs); color: #8b949e;">
                    ${accessible ? (alert.delivery ? `Targeted Alert` : 'Broadcast Alert') : `Locked Sector: ${topicDef.label}`}
                </div>
                <div class="feedback-controls" style="margin-top:0; ${accessible ? '' : 'pointer-events:none; opacity:0.3;'}">
                    ${[1, 2, 3, 4, 5].map(s => `
                        <button class="btn-fb u-tier-1 ${alert.feedback_score === s ? 'active' : ''}" data-score="${s}">${s}</button>
                    `).join('')}
                </div>
            </div>
            ${!accessible ? `<div class="alert-lock-overlay">🔒 Content restricted to ${topicDef.minTier === 'pro' ? 'Pro' : 'Expert'} Analyst tier</div>` : ''}
        `;

        return `
            <div class="alert-card ${severityClass} ${!accessible ? 'alert-card--locked' : ''}" data-id="${alert.id}" data-topic="${alert.topic || ''}">
                ${cardContent}
            </div>
        `;
    }).join('');

    // Attach feedback events
    container.querySelectorAll('.btn-fb[data-score]').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const target = e.currentTarget as HTMLButtonElement;
            const card = target.closest('.alert-card') as HTMLElement;
            const alertId = card.dataset.id!;
            const score = parseInt(target.dataset.score!);

            await submitFeedback(alertId, score);

            // Optimistic UI update
            card.querySelectorAll('.btn-fb[data-score]').forEach(b => b.classList.remove('active'));
            target.classList.add('active');
        });
    });

    // Attach View Report events
    container.querySelectorAll('.view-report-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const target = e.currentTarget as HTMLButtonElement;
            const card = target.closest('.alert-card') as HTMLElement;
            const alertId = card.dataset.id!;
            const alert = alerts.find(a => a.id === alertId);
            const reportId = alert?.related_report_id;
            const topicDef = getTopicDef(alert?.topic || null);
            const accessible = canAccessTopic(userTier, topicDef);

            if (reportId) {
                if (!accessible) {
                    // Trigger upgrade overlay via custom event
                    const event = new CustomEvent('show-locked-topic', { detail: { topicKey: topicDef.key } });
                    window.dispatchEvent(event);
                } else {
                    const event = new CustomEvent('view-report', { detail: { reportId } });
                    window.dispatchEvent(event);
                }
            }
        });
    });

    // Attach Evidence Modal events
    container.querySelectorAll('.evidence-trigger-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const card = (e.currentTarget as HTMLElement).closest('.alert-card') as HTMLElement;
            const alertId = card.dataset.id;
            const alert = alerts.find(a => a.id === alertId);
            if (alert && alert.evidence_list && alert.evidence_list.length > 0) {
                showEvidenceModal(alert.target_label, alert.evidence_list);
            }
        });
    });
}

function showEvidenceModal(title: string, evidenceList: any[]) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.id = 'modal-overlay';
    
    overlay.innerHTML = `
        <div class="modal-card">
            <div class="modal-header">
                <h2>Evidence: ${title}</h2>
                <button class="modal-close" style="font-size:1.5rem; cursor:pointer; background:none; border:none; color:var(--text-secondary);">&times;</button>
            </div>
            <div class="modal-body">
                ${evidenceList.map(item => `
                    <div class="evidence-item">
                        <h4>${item.title}</h4>
                        <div class="evidence-meta u-m-top-1">
                            <span class="evidence-domain">${item.domain}</span>
                        </div>
                        <a href="${item.url}" target="_blank" class="evidence-link u-m-top-1">
                            🔗 View Original Source
                        </a>
                    </div>
                `).join('')}
                ${evidenceList.length === 0 ? '<p class="u-p-2 u-text-center">No supporting sources available.</p>' : ''}
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
    document.body.classList.add('no-scroll');

    const close = () => {
        document.body.removeChild(overlay);
        document.body.classList.remove('no-scroll');
        window.removeEventListener('keydown', onEsc);
    };

    overlay.querySelector('.modal-close')?.addEventListener('click', close);
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) close();
    });

    const onEsc = (e: KeyboardEvent) => {
        if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', onEsc);
}

export function renderSidebar(analysts: AnalystProfile[], container: HTMLElement) {
    if (!analysts || analysts.length === 0) {
        container.innerHTML = '<h2>Analysts</h2><p>No active profiles.</p>';
        return;
    }

    const a = analysts[0];
    const usage = (window as any).getCurrentUsage();
    const limitReached = usage && usage.keywords.used >= usage.keywords.limit;

    container.innerHTML = `
        <h2>Watchlist</h2>
        <div class="watchlist-group">
            <h4 class="u-m-top-1">Key Entities</h4>
            <p style="margin-bottom: 1.5rem;">Add specific companies, assets, or executives to prioritize them in your intelligence stream.</p>
            <div class="watchlist-tags" id="keyword-tags">
                ${(a.watch_keywords || []).map(k => `
                    <span class="watchlist-tag keyword-tag" data-keyword="${k}">
                        ${k}
                        <button class="remove-kw u-tier-1" data-keyword="${k}">&times;</button>
                    </span>
                `).join('')}
            </div>
            
            <div class="watchlist-add-row u-m-top-1">
                <input type="text" id="new-keyword" placeholder="Add entity..." ${limitReached ? 'disabled' : ''} />
                <button id="add-keyword-btn" class="btn-primary u-tier-1" ${limitReached ? 'disabled' : ''}>Add</button>
            </div>
            ${limitReached ? `
                <div class="limit-warning u-m-top-1" style="color:#d29922; font-size:var(--font-xs);">
                    Keyword limit reached (${usage.keywords.limit}/${usage.keywords.limit}). 
                    <a href="#" id="watchlist-upgrade-link" style="color:#58a6ff; text-decoration:none;">Upgrade to Pro</a>
                </div>
            ` : ''}
        </div>
        <div class="sidebar-analyst-id">
            Analyst ID: ${a.id.slice(0, 8)}...
        </div>
    `;

    const addBtn = container.querySelector('#add-keyword-btn') as HTMLButtonElement | null;
    const input = container.querySelector('#new-keyword') as HTMLInputElement | null;
    const upgradeLink = container.querySelector('#watchlist-upgrade-link');

    if (addBtn && input) {
        addBtn.addEventListener('click', async () => {
            const val = input.value.trim();
            if (!val) return;
            const currentKws = a.watch_keywords || [];
            if (currentKws.includes(val)) return;
            try {
                addBtn.textContent = "...";
                await updateWatchlist(a.id, [...currentKws, val]);
                if ((window as any).refreshUsage) (window as any).refreshUsage();
            } catch (err: any) {
                alert(err.message);
            } finally {
                addBtn.textContent = "Add";
            }
        });
    }

    if (upgradeLink) {
        upgradeLink.addEventListener('click', (e) => {
            e.preventDefault();
            document.querySelector<HTMLElement>('#nav-plans')?.click();
        });
    }

    container.querySelectorAll('.remove-kw').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const target = e.currentTarget as HTMLElement;
            const kw = target.dataset.keyword;
            const currentKws = a.watch_keywords || [];
            try {
                await updateWatchlist(a.id, currentKws.filter(k => k !== kw));
                if ((window as any).refreshUsage) (window as any).refreshUsage();
            } catch (err: any) {
                alert(err.message);
            }
        });
    });
}

function simpleMarkdown(md: string): string {
    if (!md) return "";
    return md
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') // Escape HTML
        .replace(/^### (.*$)/gm, '<h4>$1</h4>')
        .replace(/^## (.*$)/gm, '<h3>$1</h3>')
        .replace(/^# (.*$)/gm, '<h2>$1</h2>')
        .replace(/^\* (.*$)/gm, '<li>$1</li>')
        .replace(/^\- (.*$)/gm, '<li>$1</li>')
        .replace(/\*\*(.*)\*\*/g, '<b>$1</b>')
        .replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank" style="color:var(--tier-grace);">$1</a>')
        .replace(/\n/g, '<br>');
}

export function renderReportDetail(report: any, userTier: string, container: HTMLElement, onBack?: () => void, onActionRequested?: (actionType: string) => void) {
    const dateStr = report.created_at || "";
    const cleanDate = dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T');
    const date = new Date(cleanDate).toLocaleDateString();

    // Use canonical mapping layer
    const topicDef = getTopicDef(report.topic_code ?? null);
    const topicLabel = `${topicDef.icon} ${topicDef.label}`;
    const rtNorm = normalizeReportType(report.report_type);
    const rtLabel = REPORT_TYPE_LABELS[rtNorm] ?? rtNorm.toUpperCase();
    
    // Check access using CENTRALIZED ENTITLEMENTS
    const hasAccess = canAccessReport(userTier, report.report_type, report.topic_code ?? null);
    const isPreview = !hasAccess || report.is_preview === true || report.locked === true;
    
    // Determine required plan for display
    const planReq = report.plan_required || REPORT_TYPE_MIN_TIER[rtNorm] || 'free';
    const planDisplay = planReq.charAt(0).toUpperCase() + planReq.slice(1);

    let md = isPreview ? (report.content_preview || "") : (report.content_markdown || "");
    let evidenceData: any[] = [];
    const evidenceMatch = md.match(/<!--\s*EVIDENCE_JSON:\s*([\s\S]*?)\s*-->/);
    if (evidenceMatch) {
        try {
            evidenceData = JSON.parse(evidenceMatch[1]);
            md = md.replace(evidenceMatch[0], '');
        } catch (e) { console.error("Evidence parse error", e); }
    }

    if (evidenceData.length === 0 && md.includes('# Sources')) {
        const sourcesSection = md.split('# Sources')[1] || "";
        const links = sourcesSection.match(/\[(.*?)\]\((.*?)\)/g);
        if (links) {
            evidenceData = links.map((l: string) => {
                const parts = l.match(/\[(.*?)\]\((.*?)\)/);
                return {
                    title: parts ? parts[1] : "Verified Source",
                    type: "External Doc",
                    explanation: "Supporting data node captured during ingestion window.",
                    link: parts ? parts[2] : "#"
                };
            });
        }
    }

    if (md.includes('# Sources')) {
        md = md.split('# Sources')[0].trim();
    }

    // Terminology Normalization (Depth-based Differentiation)
    const isExpertPlus = planReq === 'experts' || planReq === 'enterprise';
    if (isExpertPlus) {
        md = md.replace(/# Scenarios/g, '# Strategic Scenarios');
        md = md.replace(/# Monitoring Points/g, '# 30–60 Day Outlook');
    } else {
        md = md.replace(/# Scenarios/g, '# Potential Developments');
        // Monitoring Points remains as is for Free/Pro
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
                    <div class="confidence-trigger u-flex u-tier-2" style="display: inline-flex; background: var(--accent-soft); color: #58a6ff; padding: 8px 20px; border-radius: 20px; font-size: var(--font-m); border: 1px solid var(--border-active); cursor: pointer; user-select: none; gap: 1rem; align-items: center;">
                        <div style="display: flex; gap: 0.75rem; align-items: center;">
                            <span style="font-size: 1.1rem;">📊</span> 
                            <span style="font-weight: 600;">Confidence: ${report.confidence_level || 'High'}</span>
                        </div>
                        <span style="opacity: 0.3; width: 1px; height: 16px; background: #58a6ff;"></span>
                        <div style="display: flex; gap: 0.75rem; align-items: center;">
                            <span style="font-size: 1.1rem;">🔥</span> 
                            <span style="font-weight: 600;">Intensity: ${formatIntensity(report.intensity)}</span>
                        </div>
                        <span class="chevron-icon" style="transition: transform 0.3s;">▾</span>
                    </div>

                    <div class="evidence-panel u-m-top-1" style="display: none; background: rgba(13, 17, 23, 0.95); border: 1px solid var(--border-active); border-radius: 16px; padding: 2rem; box-shadow: 0 12px 48px rgba(0,0,0,0.6); backdrop-filter: blur(12px); max-width: 700px; margin-top: 1rem;">
                        <div class="u-flex-between" style="font-size: var(--font-xs); color: #8b949e; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 2rem; border-bottom: 1px solid var(--border); padding-bottom: 0.75rem;">
                            <span>Source Transparency & Evidence Log</span>
                            <span style="color: #58a6ff;">Verified Signal</span>
                        </div>
                        
                        ${evidenceData.length > 0 ? `
                            <div class="u-flex" style="flex-direction: column; gap: 2rem;">
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
                            const h = l.match(/^(#{1,3})\s+(.*)$/);
                            if (h) {
                                if (currentSec.title || currentSec.content.trim()) sections.push({ ...currentSec });
                                currentSec = { title: h[2].trim(), content: '' };
                            } else {
                                currentSec.content += l + '\n';
                            }
                        });
                        if (currentSec.title || currentSec.content.trim()) sections.push(currentSec);

                        const findSec = (names: string[]) => {
                            const idx = sections.findIndex(s => names.some(n => s.title.toLowerCase().includes(n.toLowerCase())));
                            if (idx === -1) return null;
                            return sections.splice(idx, 1)[0];
                        };

                        // Extract Summary & Actions
                        const executive = findSec(['Executive Signal', 'Summary', 'Key Insights']);
                        const actions = findSec(['Key Actions', 'Recommendations', 'Next Steps']);
                        const developments = findSec(['Key Developments', 'Key Findings', 'Analysis']);
                        const trend = findSec(['Trend Analysis', 'Market Context']);
                        const scenarios = findSec(['Strategic Scenarios', 'Potential Developments', 'Outlook', 'Monitoring']);

                        let html = '';
                        
                        // Render Summary Box
                        if (executive || actions) {
                            html += `<div class="report-summary-box">
                                ${executive ? `<div class="summary-section">
                                    <div class="summary-label">EXECUTIVE SIGNAL</div>
                                    <div class="summary-content">${simpleMarkdown(executive.content.trim())}</div>
                                </div>` : ''}
                                ${actions ? `<div class="summary-section">
                                    <div class="summary-label">KEY ACTIONS</div>
                                    <div class="summary-content">${simpleMarkdown(actions.content.trim())}</div>
                                </div>` : ''}
                            </div>`;
                        }

                        // Render remaining in order
                        const renderSec = (s: any, priority: 'medium' | 'low' = 'medium') => 
                            s ? `<div class="report-section--${priority}"><h3>${s.title}</h3>${simpleMarkdown(s.content)}</div>` : '';

                        html += renderSec(developments, 'medium');
                        html += renderSec(trend, 'medium');
                        html += renderSec(scenarios, 'low');
                        
                        // Remaining bits
                        sections.forEach(s => {
                            html += renderSec(s, 'low');
                        });

                        return html || simpleMarkdown(md);
                    })()}
                </div>

                ${isPreview ? `
                    <div class="paywall-v2 u-m-top-1 u-p-2" style="background: var(--accent-soft); border: 1px solid var(--border-active); border-radius: 16px; text-align: center; backdrop-filter: blur(8px); margin-top: 3rem;">
                        <h2 style="color: #c9d1d9; margin-top: 0;">Verified Intelligence Access</h2>
                        <div style="color: #8b949e; margin-bottom: 2rem; max-width: 500px; margin-inline: auto;">
                            <ul style="list-style: none; padding: 0; margin-bottom: 1.5rem; color: #c9d1d9; text-align: center; display: flex; flex-direction: column; gap: 0.5rem;">
                                <li>• Comprehensive Risk Exposure Analysis</li>
                                <li>• Direct Entity & Asset Targeting Logs</li>
                            </ul>
                            <button id="cta-main-btn" class="btn-primary u-w-full u-tier-1">Upgrade to ${planDisplay} for Full Intelligence</button>
                        </div>
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
    const panel = container.querySelector('.evidence-panel') as HTMLElement;
    const chevron = container.querySelector('.chevron-icon') as HTMLElement;

    if (trigger && panel) {
        trigger.addEventListener('click', () => {
            const isHidden = panel.style.display === 'none';
            panel.style.display = isHidden ? 'block' : 'none';
            if (chevron) chevron.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
        });
    }

    if (isPreview) {
        container.querySelector('#cta-main-btn')?.addEventListener('click', () => {
            if (onActionRequested) onActionRequested('upgrade');
            else window.location.reload();
        });
    }
}
