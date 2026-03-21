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
        <div class="trigger-stats">
            <h4>Top Triggers</h4>
            ${(data.top_performing_triggers || []).map(t => `<div class="watchlist-tag">${t.type} (${t.avg_feedback})</div>`).join('')}
        </div>
    `;
}

export function renderAlerts(alerts: Alert[], container: HTMLElement) {
    if (!Array.isArray(alerts)) {
        console.error("renderAlerts expected an array, got:", alerts);
        container.innerHTML = '<div style="padding:2rem;text-align:center;color:#f85149;">Technical error: invalid alerts data.</div>';
        return;
    }
    container.innerHTML = alerts.map(alert => {
        const severityClass = alert.severity.toLowerCase();
        return `
            <div class="alert-card ${severityClass}" data-id="${alert.id}">
                <div class="alert-header">
                    <div>
                        <span class="severity-badge">${alert.severity}</span>
                        <span style="margin-left: 10px; color: #8b949e; font-size: 0.8rem;">
                            ${new Date(alert.triggered_at).toLocaleTimeString()}
                        </span>
                    </div>
                    <div class="intel-score">${alert.intelligence_score.toFixed(2)}</div>
                </div>
                <h3 style="margin: 0 0 0.5rem 0;">${alert.target_label}</h3>
                <div style="font-size: 0.9rem; color: #c9d1d9; opacity: 0.8;">
                    ${alert.delivery ? `Matched Analyst: ${alert.delivery.analyst_id.slice(0,8)}... (P-Score: ${alert.delivery.relevance_score.toFixed(2)})` : 'Master System Alert'}
                </div>
                
                <div class="feedback-controls">
                    ${[1,2,3,4,5].map(s => `
                        <button class="btn-fb ${alert.feedback_score === s ? 'active' : ''}" data-score="${s}">${s}</button>
                    `).join('')}
                </div>
            </div>
        `;
    }).join('');

    // Attach feedback events
    container.querySelectorAll('.btn-fb').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const target = e.currentTarget as HTMLButtonElement;
            const card = target.closest('.alert-card') as HTMLElement;
            const alertId = card.dataset.id!;
            const score = parseInt(target.dataset.score!);
            
            await submitFeedback(alertId, score);
            
            // Optimistic UI update
            card.querySelectorAll('.btn-fb').forEach(b => b.classList.remove('active'));
            target.classList.add('active');
        });
    });
}

export function renderSidebar(analysts: AnalystProfile[], container: HTMLElement) {
    if (!analysts || analysts.length === 0) {
        container.innerHTML = '<h2>Analysts</h2><p>No active profiles.</p>';
        return;
    }
    
    // For simplicity in v1, show the first analyst's watchlist
    const a = analysts[0];
    const usage = (window as any).getCurrentUsage();
    const limitReached = usage && usage.keywords.used >= usage.keywords.limit;

    container.innerHTML = `
        <h2>Intelligence Watchlist</h2>
        <div class="watchlist-group">
            <h4>Entity Watchlist</h4>
            <p style="font-size: 0.8rem; color: #8b949e; margin-top: -0.5rem; margin-bottom: 1rem;">Add specific companies, assets, or executives to prioritize them in your intelligence stream. Matches receive boosted relevance scores.</p>
            <div class="watchlist-tags" id="keyword-tags">
                ${(a.watch_keywords || []).map(k => `
                    <span class="watchlist-tag keyword-tag" data-keyword="${k}">
                        ${k}
                        <button class="remove-kw" data-keyword="${k}">&times;</button>
                    </span>
                `).join('')}
            </div>
            
            <div class="watchlist-add-row" style="margin-top: 1rem;">
                <input type="text" id="new-keyword" placeholder="Add entity/topic..." ${limitReached ? 'disabled' : ''} />
                <button id="add-keyword-btn" class="btn-primary" ${limitReached ? 'disabled' : ''}>Add</button>
            </div>
            ${limitReached ? `
                <div class="limit-warning" style="margin-top:0.5rem; color:#d29922; font-size:0.8rem;">
                    Keyword limit reached (${usage.keywords.limit}/${usage.keywords.limit}). 
                    <a href="#" id="watchlist-upgrade-link" style="color:#58a6ff; text-decoration:none;">Upgrade to Pro</a>
                </div>
            ` : ''}
        </div>
        <div style="margin-top: auto; font-size: 0.75rem; color: #8b949e; padding-top: 1rem; border-top: 1px solid #30363d;">
            Analyst ID: ${a.id.slice(0,8)}...
        </div>
    `;

    // Event handlers for keyword management
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

export function renderReportDetail(report: any, container: HTMLElement, onActionRequested?: (actionType: string) => void) {
    const isPreview = report.is_preview === true || report.locked === true;
    const dateStr = report.created_at || "";
    const cleanDate = dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T');
    const date = new Date(cleanDate).toLocaleDateString();
    const typeLabel = (report.report_type || "").replace(/_/g, ' ').toUpperCase();
    const topicLabel = report.topic_code ? report.topic_code.toUpperCase() : 'GLOBAL';

    
    let md = isPreview ? (report.content_preview || "") : (report.content_markdown || "");
    
    let evidenceData: any[] = [];
    const evidenceMatch = md.match(/<!--\s*EVIDENCE_JSON:\s*([\s\S]*?)\s*-->/);
    if (evidenceMatch) {
        try {
            evidenceData = JSON.parse(evidenceMatch[1]);
            md = md.replace(evidenceMatch[0], ''); // Hide the raw JSON comment
        } catch(e) { console.error("Evidence parse error", e); }
    }
    
    // Fallback: Try to extract from # Sources if EVIDENCE_JSON is missing
    if (evidenceData.length === 0 && md.includes('# Sources')) {
        const sourcesSection = md.split('# Sources')[1] || "";
        const links = sourcesSection.match(/\[(.*?)\]\((.*?)\)/g);
        if (links) {
            evidenceData = links.map(l => {
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
    

    container.innerHTML = `
        <div class="report-detail">
            <div style="margin-bottom: 2rem; display: flex; align-items: center; gap: 1rem;">
                <button class="btn-fb active" id="back-to-feed-btn">← Back to Feed</button>
                <div style="color: #8b949e; font-size: 0.9rem;">
                    ${topicLabel} Intelligence Briefing | ${date}
                    ${isPreview ? ' | <span style="color:#d29922;">PREVIEW</span>' : ''}
                </div>
            </div>
            
            <div class="report-content-card" style="background: rgba(255,255,255,0.03); padding: 2rem; border-radius: 12px; border: 1px solid var(--border); line-height: 1.6; position: relative;">
                <h1 style="margin-top: 0; color: #58a6ff;">${typeLabel}: ${topicLabel}</h1>
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
                                        <div style="font-size: 0.85rem; color: #8b949e; line-height: 1.6; margin-bottom: 0.8rem;">${e.explanation}</div>
                                        ${e.link && e.link !== '#' ? `
                                            <a href="${e.link}" target="_blank" style="font-size: 0.8rem; color: #58a6ff; text-decoration: none; display: inline-flex; align-items: center; gap: 4px; padding: 6px 12px; background: rgba(88,166,255,0.05); border-radius: 4px; border: 1px solid rgba(88,166,255,0.1); transition: background 0.2s;">
                                                🔗 View Original Source
                                            </a>
                                        ` : `
                                            <div style="font-size: 0.8rem; color: #8b949e; display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; background: rgba(255,255,255,0.03); border-radius: 4px; border: 1px solid rgba(255,255,255,0.05); cursor: default;">
                                                🔒 Source Content Restricted
                                            </div>
                                        `}
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

                <div class="markdown-body" style="color: #c9d1d9; ${isPreview ? 'mask-image: linear-gradient(to bottom, black 50%, transparent 100%); -webkit-mask-image: linear-gradient(to bottom, black 50%, transparent 100%);' : ''}">
                    ${simpleMarkdown(md)}
                </div>

                ${isPreview ? `
                    <div class="paywall-v2" style="margin-top: 2rem; padding: 2.5rem; background: rgba(88, 166, 255, 0.03); border: 1px solid rgba(88, 166, 255, 0.2); border-radius: 12px; text-align: center; backdrop-filter: blur(4px);">
                        
                        
                        <h2 style="color: #c9d1d9; margin-top: 0; font-size: 1.4rem;">Verified Intelligence</h2>
                        <div style="color: #8b949e; margin-bottom: 2rem; max-width: 500px; margin-inline: auto; font-size: 0.95rem;">
                            <ul style="list-style: none; padding: 0; margin-bottom: 1rem; color: #c9d1d9; text-align: center;">
                                <li>• 3 supply chain nodes identified</li>
                                <li>• 14-day disruption window</li>
                            </ul>
                            <div style="margin-bottom: 1rem; text-align: center; background: rgba(0,0,0,0.2); padding: 1rem; border-radius: 8px;">
                                <div style="color: #c9d1d9; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem;">Who this impacts:</div>
                                <div style="font-size: 0.9rem; color: #8b949e;">Semiconductor Investors • Hardware OEMs • Logistics Operators</div>
                            </div>
                            <p style="font-weight: 500; color: #58a6ff; margin: 0;">See which suppliers and positions are exposed before the market re-prices.</p>
                        </div>
                        
                        <div class="cta-hierarchy" style="display: flex; flex-direction: column; gap: 0.75rem; max-width: 360px; margin: 0 auto;">
                            <button id="cta-main-btn" class="plan-cta-btn" style="width: 100%; padding: 0.8rem; font-size: 1rem; font-weight: 600;">
                                Access Detailed Entity Risk List
                            </button>
                            <button class="plan-cta-btn minimal" style="width: 100%; padding: 0.5rem; font-size: 0.8rem; background: transparent; border: none; color: #58a6ff; cursor: pointer;" onclick="document.querySelector('#cta-main-btn').click()">
                                Secure Founding Member Access ($19/mo)
                            </button>
                        </div>
                    </div>
                ` : ''}
            </div>

            ${!isPreview && report.substack_url ? `
                <div style="margin-top: 2rem; text-align: center;">
                    <a href="${report.substack_url}" target="_blank" class="plan-cta-btn" style="text-decoration: none; display: inline-block;">
                        Read original on Substack
                    </a>
                </div>
            ` : ''}
        </div>
    `;

    document.querySelector('#back-to-feed-btn')?.addEventListener('click', () => {
        const feedNav = document.querySelector<HTMLElement>('#nav-feed');
        if (feedNav) feedNav.click();
    });

    
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

        container.querySelector('#cta-main-btn')?.addEventListener('click', () => {
            if (onActionRequested) onActionRequested('upgrade');
            else window.location.reload();
        });
    }
}
