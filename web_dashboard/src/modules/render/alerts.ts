import { type Alert } from '../api';
import { getTopicColor, getTopicDisplayLabel, getTopicCssVars, normalizeTopicCode } from '../topics';
import { resolveAlertHeadline } from '../alert_display';

/**
 * [v34] Simplified Evidence Modal for Live Alerts (Non-global)
 */
export function showEvidenceModal(title: string, evidenceList: any[]) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    overlay.innerHTML = `
        <div class="modal-card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem; border-bottom:1px solid var(--border); padding-bottom:1rem;">
                <h3 style="font-size:1.1rem; color:#58a6ff;">Evidence: ${title}</h3>
                <button class="modal-close-btn" style="background:none; border:none; color:#8b949e; cursor:pointer; font-size:1.5rem;">&times;</button>
            </div>
            <div style="display:flex; flex-direction:column; gap:1.5rem;">
                ${evidenceList.map((item, index) => `
                    <div class="evidence-item" style="border-left:2px solid var(--accent); padding-left:1rem;">
        
                        ${index === 0 ? `<div class="primary-badge">PRIMARY</div>` : ''}

                        <div style="font-weight:600; color:#c9d1d9; font-size:0.9rem; margin-bottom:0.5rem;">
                            ${item.title || 'Source Signal'}
                        </div>

                        <div style="display:flex; gap:0.5rem; align-items:center; margin-bottom:0.75rem;">
                            <span class="evidence-domain">${item.domain || item.type || 'OSINT'}</span>
                        </div>

                        ${(item.url || item.link) ? `
                            <a href="${item.url || item.link}" target="_blank"
                            style="color:#58a6ff; text-decoration:none; font-size:0.8rem; font-weight:600;">
                            🔗 View Source &rarr;
                            </a>
                        ` : '<div style="font-size:0.8rem; color:#8b949e;">🔒 Restricted Source</div>'}
                    </div>
                `).join('')}
                ${evidenceList.length === 0 ? '<p style="text-align:center; opacity:0.6;">No supporting sources available.</p>' : ''}
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
    const close = () => document.body.removeChild(overlay);
    overlay.querySelector('.modal-close-btn')?.addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
}

export function renderLiveFeed(alerts: Alert[], container: HTMLElement) {
    // [v16.0] Compact Pulse Bar: Single most critical/recent signal
    const severityMap: Record<string, number> = { critical: 3, elevated: 2, watch: 1 };
    const latest = [...alerts].sort((a, b) => {
        const sevA = severityMap[a.severity?.toLowerCase() || ''] || 0;
        const sevB = severityMap[b.severity?.toLowerCase() || ''] || 0;
        if (sevA !== sevB) return sevB - sevA;
        return new Date(b.triggered_at).getTime() - new Date(a.triggered_at).getTime();
    })[0];

    if (!latest) {
        container.innerHTML = `
            <div class="pulse-content" style="opacity:0.6; font-size: 0.75rem; letter-spacing: 0.5px; display: flex; align-items: center; gap: 8px;">
                <span class="severity-dot" style="background: rgba(88, 166, 255, 0.4); box-shadow: 0 0 8px rgba(88, 166, 255, 0.2);"></span>
                <span style="font-weight: 500;">PULSE: Monitoring global signal backbone...</span>
            </div>
        `;
        return;
    }

    const severityClass = latest.severity.toLowerCase();
    const timeStr = new Date(latest.triggered_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const canonicalTopic = normalizeTopicCode(latest.topic);
    const topicColor = getTopicColor(canonicalTopic);
    const topicLabel = getTopicDisplayLabel(canonicalTopic);
    const pulseHeadline = resolveAlertHeadline(latest);

    // Apply temporary fade class if container already had content (simulating update)
    const isUpdate = container.innerHTML.length > 0;

    const headlineHtml = pulseHeadline.pending
        ? '<span class="alert-headline-skeleton alert-headline-skeleton--inline" aria-hidden="true"></span>'
        : `<span style="flex:1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 0.75rem; font-weight: 600; color: #fff;">${pulseHeadline.text}</span>`;

    container.innerHTML = `
        <div class="pulse-content ${isUpdate ? 'pulse-fade-update' : ''}" style="display: flex; align-items: center; gap: 10px; width: 100%; overflow: hidden;">
            <span class="severity-dot ${severityClass}"></span>
            <span style="font-weight:900; color:${topicColor}; font-size: 0.65rem; text-transform: uppercase; letter-spacing: 1px;">${topicLabel}</span>
            ${headlineHtml}
            <span style="opacity:0.5; font-size: 0.65rem; font-family: monospace;">[${timeStr}]</span>
        </div>
    `;
}

export function renderAlerts(alerts: Alert[], container: HTMLElement, userTier: string = 'free') {
    if (!Array.isArray(alerts)) {
        console.error("renderAlerts expected an array, got:", alerts);
        container.innerHTML = '<div class="u-p-2 u-text-center" style="color:#f85149;">Technical error: invalid alerts data.</div>';
        return;
    }

    const sortedAlerts = [...alerts].sort((a, b) => {
        const sevMap: Record<string, number> = { critical: 3, elevated: 2, watch: 1 };
        const sevA = sevMap[a.severity?.toLowerCase() || ''] || 0;
        const sevB = sevMap[b.severity?.toLowerCase() || ''] || 0;
        if (sevA !== sevB) return sevB - sevA;
        return new Date(b.triggered_at).getTime() - new Date(a.triggered_at).getTime();
    });

    if (sortedAlerts.length === 0) {
        container.innerHTML = `
            <div class="empty-state u-p-2 u-text-center">
                <div class="empty-icon">📡</div>
                <div class="empty-title">No active signals detected.</div>
                <div class="empty-subtitle">The AI backbone is currently scanning for strategic momentum.</div>
            </div>
        `;
        return;
    }

    container.innerHTML = sortedAlerts.map(alert => {
        const canonicalTopic = normalizeTopicCode(alert.topic);
        const topicLabel = getTopicDisplayLabel(canonicalTopic);
        const headline = resolveAlertHeadline(alert);
        const severityClass = alert.severity.toLowerCase();
        const date = new Date(alert.triggered_at);

        const displayDate = isNaN(date.getTime()) ? 'Recent' : date.toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });

        const status = alert.backbone_discovery_status || 'idle';
        const statusMap: Record<string, { label: string, class: string }> = {
            'processing': { label: '', class: 'status-processing' },
            'complete': { label: 'VERIFIED', class: 'status-complete' },
            'failed': { label: 'SIGNAL', class: 'status-failed' },
            'idle': { label: 'PENDING', class: 'status-failed' }
        };
        const statusCfg = statusMap[status] || statusMap['idle'];

        const isPro = userTier === 'pro';
        const isExpert = userTier === 'experts' || userTier === 'enterprise';
        const tierBadge = isExpert
            ? '<span class="alert-tier-corner alert-tier-corner--expert" title="Expert access">EX</span>'
            : isPro
                ? '<span class="alert-tier-corner alert-tier-corner--pro" title="Pro access">PRO</span>'
                : '';

        const count = alert.evidence_list?.length || 0;

        const cardContent = `
            <div class="alert-header u-flex-between">
                <div class="u-flex" style="gap: 8px; align-items: center;">
                    <span class="severity-badge ${severityClass}">${alert.severity.toUpperCase()}</span>
                    <span class="status-badge ${statusCfg.class}">${statusCfg.label}</span>
                    <span class="timestamp">${displayDate}</span>
                </div>
                <div class="alert-header-meta">
                    ${tierBadge}
                    <span class="meta-item-topic meta-item-topic--tag">${topicLabel}</span>
                </div>
            </div>

            <div class="alert-content-terminal">
                <div class="alert-main-row">
                    ${headline.pending
                        ? '<div class="alert-headline-skeleton" aria-busy="true" aria-label="Loading headline"></div>'
                        : `<h3 class="alert-headline-compact">${headline.text}</h3>`
                    }
                </div>
                
                <div class="source-terminal-row">
                    <span class="source-label">SOURCES:</span>
                    <button class="source-modal-trigger" data-alert-id="${alert.id}">
                        View Sources ${count ? `(${count})` : ''}
                    </button>
                </div>
            </div>

        `;

        return `
            <div class="alert-card-compact severity-${severityClass} ${alert.is_locked ? 'locked' : ''}" data-id="${alert.id}" style="${getTopicCssVars(canonicalTopic)}">
                ${cardContent}
            </div>
        `;
    }).join('');

    container.querySelectorAll('.source-modal-trigger').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();

            const alertId = (btn as HTMLElement).dataset.alertId;
            const targetAlert = sortedAlerts.find(a => a.id === alertId);

            if (!targetAlert) return;

            const modalTitle = resolveAlertHeadline(targetAlert).text || targetAlert.target_label;
            showEvidenceModal(
                modalTitle,
                targetAlert.evidence_list || []
            );
        });
    });
}