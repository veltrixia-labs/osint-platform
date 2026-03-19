import { submitFeedback, updateWatchlist } from './api';
import { renderLockedFeature } from './subscription';

export function renderHealth(data, container) {
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

export function renderAlerts(alerts, container) {
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
            const card = e.target.closest('.alert-card');
            const alertId = card.dataset.id;
            const score = parseInt(e.target.dataset.score);
            
            await submitFeedback(alertId, score);
            
            // Optimistic UI update
            card.querySelectorAll('.btn-fb').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
        });
    });
}

export function renderSidebar(analysts, container) {
    if (!analysts || analysts.length === 0) {
        container.innerHTML = '<h2>Analysts</h2><p>No active profiles.</p>';
        return;
    }
    
    // For simplicity in v1, show the first analyst's watchlist
    const a = analysts[0];
    const usage = (window as any).getCurrentUsage();
    const canAdd = usage ? usage.keywords.used < usage.keywords.limit : true;
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
    const addBtn = container.querySelector('#add-keyword-btn');
    const input = container.querySelector<HTMLInputElement>('#new-keyword');
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
                // Refresh usage and trigger local state update if possible
                // For simplicity, we trigger a global refresh via any polling state
                if ((window as any).refreshUsage) (window as any).refreshUsage();
                // Note: The parent renderSidebar will be re-called by polling loop
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
            const kw = (e.target as HTMLElement).dataset.keyword;
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
