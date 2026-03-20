import { submitFeedback, updateWatchlist, logAnalyticsEvent } from './api';
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
            <h4>Sectors</h4>
            <div class="watchlist-tags">
                ${(a.watch_sectors || []).map(s => `<span class="watchlist-tag">${s}</span>`).join('')}
            </div>
        </div>
        <div class="watchlist-group">
            <h4>Keywords</h4>
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

export function renderReportDetail(report: any, container: HTMLElement, onLoginRequested?: () => void) {
    const isPreview = report.is_preview === true;
    const date = new Date(report.created_at).toLocaleDateString();
    const typeLabel = (report.report_type || "").replace(/_/g, ' ').toUpperCase();
    const topicLabel = report.topic_code ? report.topic_code.toUpperCase() : 'GLOBAL';

    const content = isPreview ? report.content_preview : report.content_markdown;

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
                <div class="markdown-body" style="color: #c9d1d9; ${isPreview ? 'mask-image: linear-gradient(to bottom, black 50%, transparent 100%); -webkit-mask-image: linear-gradient(to bottom, black 50%, transparent 100%);' : ''}">
                    ${simpleMarkdown(content || "")}
                </div>

                ${isPreview ? `
                    <div class="preview-cta" style="margin-top: 2rem; padding: 2.5rem; background: rgba(88, 166, 255, 0.05); border: 1px dashed #58a6ff; border-radius: 8px; text-align: center;">
                        <h2 style="color: #58a6ff; margin-top: 0;">Ready to see the full analysis?</h2>
                        <p style="color: #8b949e; margin-bottom: 2rem; max-width: 500px; margin-inline: auto;">
                            Join our community of elite analysts to unlock the complete report, real-time alerts, and deep-dive technical intelligence.
                        </p>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; max-width: 400px; margin: 0 auto 2rem auto; text-align: left; font-size: 0.9rem; color: #c9d1d9;">
                            <div>✅ Full Intelligence Reports</div>
                            <div>✅ Real-Time Signal Alerts</div>
                            <div>✅ Deep-Dive Technical Detail</div>
                            <div>✅ Ongoing Market Intelligence</div>
                        </div>
                        <button id="cta-login-btn" class="plan-cta-btn" style="padding: 1rem 2.5rem; font-size: 1.1rem;">Sign Up / Log In to Read More</button>
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

    if (isPreview) {
        document.querySelector('#cta-login-btn')?.addEventListener('click', () => {
            logAnalyticsEvent('cta_click', report.id);
            if (onLoginRequested) onLoginRequested();
            else window.location.reload();
        });
    }
}
