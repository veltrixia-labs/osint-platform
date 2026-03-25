import { submitFeedback, updateWatchlist } from './api';
import type { Alert, AnalystProfile, HealthData } from './api';

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
            <div class="u-flex u-m-top-1" style="flex-wrap: wrap;">
                ${(data.top_performing_triggers || []).map(t => `<div class="watchlist-tag">${t.type} (${t.avg_feedback})</div>`).join('')}
            </div>
        </div>
    `;
}

export function renderAlerts(alerts: Alert[], container: HTMLElement) {
    if (!Array.isArray(alerts)) {
        console.error("renderAlerts expected an array, got:", alerts);
        container.innerHTML = '<div class="u-p-2 u-text-center" style="color:#f85149;">Technical error: invalid alerts data.</div>';
        return;
    }
    container.innerHTML = alerts.map(alert => {
        const severityClass = alert.severity.toLowerCase();
        const date = new Date(alert.triggered_at);
        const displayDate = isNaN(date.getTime()) ? 'Recent' : date.toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });
        
        const triggerLabel = (alert.trigger_type || 'Pattern').replace(/_/g, ' ').toUpperCase();
        const hasReport = !!alert.related_report_id;

        return `
            <div class="alert-card ${severityClass}" data-id="${alert.id}">
                <div class="alert-header u-flex-between">
                    <div class="u-flex" style="flex-wrap: wrap;">
                        <span class="severity-badge">${alert.severity}</span>
                        <span class="watchlist-tag" style="background:rgba(255,255,255,0.05);">
                            ${triggerLabel}
                        </span>
                        <span style="color: #8b949e; font-size: var(--font-xs);">${displayDate}</span>
                    </div>
                    <div class="u-text-right">
                        <div style="font-size: var(--font-xs); color:#8b949e;">Intelligence Priority</div>
                        <div class="intel-score">${alert.intelligence_score.toFixed(2)}</div>
                    </div>
                </div>
                
                <h3 style="color: #58a6ff;">${alert.target_label || 'Unknown Signal'}</h3>
                
                <div class="u-grid-2 u-p-1 u-m-top-1" style="background:rgba(0,0,0,0.2); border-radius: 6px; border:1px solid rgba(255,255,255,0.05);">
                    <div>
                        <h4>Risk Momentum</h4>
                        <div style="font-size:var(--font-m); color:#c9d1d9; font-weight:600;">${alert.intensity?.toFixed(2) || '0.00'}/10.0</div>
                    </div>
                    <div>
                        <h4>Evidence</h4>
                        <div class="evidence-trigger-btn u-m-top-1" style="color:#58a6ff; background:rgba(88,166,255,0.05); padding:2px 8px; border-radius:4px; display:inline-block; border:1px solid rgba(88,166,255,0.1); font-size: var(--font-s); cursor: pointer;">
                            🔍 ${alert.domain_count || 0} Domains
                        </div>
                    </div>
                    <div>
                        <h4>Change</h4>
                        <div style="font-size:var(--font-m); color:${(alert.spike_delta || 0) > 0 ? '#3fb950' : '#8b949e'}; font-weight:600;">
                            ${(alert.spike_delta || 0) > 0 ? '↑' : ''}${(alert.spike_delta || 0).toFixed(2)}
                        </div>
                    </div>
                    ${hasReport ? `
                    <div style="display:flex; align-items:flex-end;">
                        <button class="btn-fb active view-report-btn u-w-full">View Report</button>
                    </div>
                    ` : `
                    <div style="font-size:var(--font-xs); color:#8b949e; display:flex; align-items:flex-end; opacity:0.6; font-style: italic;">
                        Analysis Pending...
                    </div>
                    `}
                </div>

                <div class="u-flex-between u-m-top-1">
                    <div style="font-size: var(--font-xs); color: #8b949e;">
                        ${alert.delivery ? `Targeted Alert` : 'Broadcast Alert'}
                    </div>
                    <div class="feedback-controls" style="margin-top:0;">
                        ${[1, 2, 3, 4, 5].map(s => `
                            <button class="btn-fb ${alert.feedback_score === s ? 'active' : ''}" data-score="${s}">${s}</button>
                        `).join('')}
                    </div>
                </div>
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
            if (reportId) {
                const event = new CustomEvent('view-report', { detail: { reportId } });
                window.dispatchEvent(event);
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
        <h2>Intelligence Watchlist</h2>
        <div class="watchlist-group">
            <h4 class="u-m-top-1">Entity Watchlist</h4>
            <p style="margin-bottom: 1rem;">Add specific companies, assets, or executives to prioritize them in your intelligence stream.</p>
            <div class="watchlist-tags" id="keyword-tags">
                ${(a.watch_keywords || []).map(k => `
                    <span class="watchlist-tag keyword-tag" data-keyword="${k}">
                        ${k}
                        <button class="remove-kw" data-keyword="${k}">&times;</button>
                    </span>
                `).join('')}
            </div>
            
            <div class="watchlist-add-row u-m-top-1">
                <input type="text" id="new-keyword" placeholder="Add entity..." ${limitReached ? 'disabled' : ''} />
                <button id="add-keyword-btn" class="btn-primary" ${limitReached ? 'disabled' : ''}>Add</button>
            </div>
            ${limitReached ? `
                <div class="limit-warning u-m-top-1" style="color:#d29922; font-size:var(--font-xs);">
                    Keyword limit reached (${usage.keywords.limit}/${usage.keywords.limit}). 
                    <a href="#" id="watchlist-upgrade-link" style="color:#58a6ff; text-decoration:none;">Upgrade to Pro</a>
                </div>
            ` : ''}
        </div>
        <div style="margin-top: auto; font-size: var(--font-xs); color: #8b949e; padding-top: 1rem; border-top: 1px solid #30363d;">
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

export function renderReportDetail(report: any, container: HTMLElement, onBack?: () => void, onActionRequested?: (actionType: string) => void) {
    const isPreview = report.is_preview === true || report.locked === true;
    const dateStr = report.created_at || "";
    const cleanDate = dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T');
    const date = new Date(cleanDate).toLocaleDateString();
    
    const TOPICS_INTERNAL = [
        { code: 'energy_resource_risk', label: '⚡ Energy Risk' },
        { code: 'global_market_intelligence', label: '💰 Financial Intel' },
        { code: 'ai_semiconductor_intelligence', label: '🤖 AI/Semi Intel' },
        { code: 'crypto_geopolitics', label: '₿ Crypto Risk' },
        { code: 'defense_technology', label: '🛡️ Defense Tech' },
        { code: 'supply_chain_intelligence', label: '📦 Supply Chain' },
    ];
    const topicObj = TOPICS_INTERNAL.find(t => t.code === report.topic_code);
    const topicLabel = topicObj ? topicObj.label : (report.topic_code ? report.topic_code.toUpperCase() : 'GLOBAL INTEL');

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

    container.innerHTML = `
        <div class="report-detail">
            <div class="u-flex-between u-m-top-1" style="margin-bottom: var(--space-m); flex-wrap: wrap; gap: 1rem;">
                <div class="u-flex" style="flex-wrap: wrap;">
                    <button class="btn-fb active" id="back-to-feed-btn">← Back</button>
                    <div style="color: #8b949e; font-size: var(--font-s); display: flex; align-items: center; gap: var(--space-xs); flex-wrap: wrap;">
                        <span style="font-weight: 600; color: #c9d1d9;">${topicLabel}</span>
                        <span style="opacity: 0.5;">|</span>
                        <span>${(report.report_type || "daily").toUpperCase()}</span>
                        <span style="opacity: 0.5;">|</span>
                        <span style="color: #d29922; font-weight: 500;">${(report.plan_required || "free").toUpperCase()} Plan</span>
                        <span style="opacity: 0.5;">|</span>
                        <span>${date}</span>
                    </div>
                </div>
                ${isPreview ? '<span class="tier-badge" style="background: rgba(210,153,34,0.1); color: #d29922; border: 1px solid rgba(210,153,34,0.3);">PREVIEW</span>' : ''}
            </div>
            
            <div class="report-content-card u-m-top-1">
                <h1>${report.title}</h1>
                <div class="u-m-top-1 u-text-center" style="text-align: left;">
                    <div class="confidence-trigger u-flex" style="display: inline-flex; background: rgba(88,166,255,0.1); color: #58a6ff; padding: 6px 14px; border-radius: 20px; font-size: var(--font-s); border: 1px solid rgba(88,166,255,0.3); transition: all 0.2s; cursor: pointer; user-select: none;">
                        <span style="font-size: 1.1rem;">📊</span> 
                        <span style="font-weight: 600;">Confidence: ${report.confidence_level || 'High'}</span>
                        <span style="opacity: 0.8;">(${report.source_count || 0} sources)</span>
                        <span class="chevron-icon" style="transition: transform 0.3s;">▾</span>
                    </div>

                    <div class="evidence-panel u-m-top-1" style="display: none; background: rgba(13, 17, 23, 0.9); border: 1px solid rgba(88,166,255,0.2); border-radius: 12px; padding: 1.5rem; box-shadow: 0 10px 30px rgba(0,0,0,0.5); backdrop-filter: blur(10px); max-width: 650px;">
                        <div class="u-flex-between" style="font-size: var(--font-xs); color: #8b949e; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 1.5rem; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 0.5rem;">
                            <span>Source Transparency & Evidence Log</span>
                            <span style="color: #58a6ff;">Verified</span>
                        </div>
                        
                        ${evidenceData.length > 0 ? `
                            <div class="u-flex" style="flex-direction: column; gap: 1.5rem;">
                                ${evidenceData.map(e => `
                                    <div style="border-left: 2px solid rgba(88,166,255,0.3); padding-left: 1rem;">
                                        <div class="u-flex-between" style="margin-bottom: 0.5rem; align-items: flex-start;">
                                            <div style="font-weight: 600; color: #c9d1d9; font-size: var(--font-s);">${e.title}</div>
                                            <span style="font-size: var(--font-xs); background: rgba(88,166,255,0.15); color: #58a6ff; padding: 2px 8px; border-radius: 10px; border: 1px solid rgba(88,166,255,0.2); white-space: nowrap;">${e.type}</span>
                                        </div>
                                        <div style="font-size: var(--font-s); color: #8b949e; line-height: 1.6; margin-bottom: 0.8rem;">${e.explanation}</div>
                                        ${e.link && e.link !== '#' ? `
                                            <a href="${e.link}" target="_blank" class="btn-fb u-flex" style="text-decoration: none; font-size: var(--font-xs); display: inline-flex;">🔗 View Source</a>
                                        ` : '<div style="font-size: var(--font-xs); color: #8b949e; opacity: 0.6;">🔒 Private Source</div>'}
                                    </div>
                                `).join('')}
                            </div>
                        ` : '<div class="u-p-2 u-text-center">ℹ️ Detailed evidence list pending...</div>'}
                    </div>
                </div>

                <div class="markdown-body u-m-top-1" style="${isPreview ? 'mask-image: linear-gradient(to bottom, black 50%, transparent 100%); -webkit-mask-image: linear-gradient(to bottom, black 50%, transparent 100%);' : ''}">
                    ${simpleMarkdown(md)}
                </div>

                ${isPreview ? `
                    <div class="paywall-v2 u-m-top-1 u-p-2" style="background: rgba(88, 166, 255, 0.03); border: 1px solid rgba(88, 166, 255, 0.2); border-radius: 12px; text-align: center; backdrop-filter: blur(4px);">
                        <h2 style="color: #c9d1d9; margin-top: 0;">Verified Intelligence</h2>
                        <div style="color: #8b949e; margin-bottom: 2rem; max-width: 500px; margin-inline: auto;">
                            <ul style="list-style: none; padding: 0; margin-bottom: 1rem; color: #c9d1d9; text-align: center;">
                                <li>• Targeted Entity Risk Profiles</li>
                                <li>• Supply Chain Vulnerability Nodes</li>
                            </ul>
                            <button id="cta-main-btn" class="plan-cta-btn u-w-full u-m-top-1">Access Detailed Intelligence (Pro)</button>
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
