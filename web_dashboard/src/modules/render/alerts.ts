import type { Alert } from '../api';
import { getTopicDef, canAccessTopic } from '../topics';
import { formatIntensity } from './utils';

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
                ${evidenceList.map(item => `
                    <div class="evidence-item" style="border-left:2px solid var(--accent); padding-left:1rem;">
                        <div style="font-weight:600; color:#c9d1d9; font-size:0.9rem; margin-bottom:0.5rem;">${item.title || 'Source Signal'}</div>
                        <div style="display:flex; gap:0.5rem; align-items:center; margin-bottom:0.75rem;">
                            <span class="evidence-domain">${item.domain || item.type || 'OSINT'}</span>
                        </div>
                        ${(item.url || item.link) ? `
                            <a href="${item.url || item.link}" target="_blank" style="color:#58a6ff; text-decoration:none; font-size:0.8rem; font-weight:600;">🔗 View Source &rarr;</a>
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
    // Show top 8 most recent alerts in a compact way
    const recent = [...alerts].sort((a,b) => new Date(b.triggered_at).getTime() - new Date(a.triggered_at).getTime()).slice(0, 8);
    
    container.innerHTML = recent.map(alert => {
        const severityClass = alert.severity.toLowerCase();
        return `
            <div class="live-feed-item ${severityClass}" style="padding: 0.5rem; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 0.8rem; display: flex; align-items: center; gap: 0.5rem;">
                <span class="severity-dot ${severityClass}"></span>
                <span style="font-weight:600; color:var(--accent); min-width: 60px;">${alert.topic?.toUpperCase() || 'GLBL'}</span>
                <span style="flex:1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #c9d1d9;">${alert.target_label}</span>
                <span style="opacity:0.4; font-size: 0.7rem;">${new Date(alert.triggered_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
            </div>
        `;
    }).join('') || '<div class="u-p-1 u-text-center" style="opacity:0.5;">No active signals detected.</div>';
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
        const isLocked = alert.is_locked === true;

        const displayDate = isNaN(date.getTime()) ? 'Recent' : date.toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });
        
        const triggerLabel = (alert.trigger_type || 'Pattern').replace(/_/g, ' ').toUpperCase();
        const hasReport = !!alert.related_report_id;

        // [v50] Unified Mosaic Gating UI
        const cardContent = `
            ${isLocked ? `
                <div class="vlt-mosaic-mask">
                    <div class="vlt-lock-icon">🔒</div>
                    <div class="vlt-gating-title">Forensic Intelligence Restricted</div>
                    <div class="vlt-gating-text">
                        Detailed analysis and <span style="color:#58a6ff; font-weight:600;">Real-time Email Notifications</span> for this domain require an active Analyst Account.
                    </div>
                    <button class="vlt-mosaic-cta trigger-login-btn">
                        <span>Sign Up for Email Alerts</span>
                    </button>
                    <div style="font-size: 0.7rem; color: #8b949e; margin-top: 1rem; opacity: 0.6;">
                        Topic: ${topicDef.label} | Tier: ${topicDef.minTier.toUpperCase()}
                    </div>
                </div>
            ` : ''}
            <div class="alert-header u-flex-between" style="${isLocked ? 'filter: blur(8px); pointer-events:none; opacity: 0.3;' : ''}">
                <div class="u-flex" style="flex-wrap: wrap; row-gap: 0.5rem;">
                    <span class="severity-badge">${alert.severity}</span>
                    <span class="watchlist-tag">
                        ${triggerLabel}
                    </span>
                    <span style="color: #8b949e; font-size: var(--font-xs);">${displayDate}</span>
                </div>
                <div class="u-text-right">
                    <div style="font-size: var(--font-xs); color:#8b949e;">Intelligence Priority</div>
                    <div class="intel-score">${!isLocked ? (alert.intelligence_score || 0).toFixed(2) : '•.••'}</div>
                </div>
            </div>
            
            <div class="alert-body" style="${isLocked ? 'filter: blur(8px); pointer-events:none; opacity: 0.3;' : ''}">
                <h3 style="color: #58a6ff; line-height: 1.4; margin-bottom: 0.25rem;">${alert.target_label || 'Unknown Signal'}</h3>
                ${!accessible ? `
                    <div style="font-size: var(--font-xs); color: ${topicDef.color}; opacity: 0.9; margin-bottom: 0.75rem; font-weight: 500;">
                        ${topicDef.valueProposition}
                        ${alert.intensity >= 8.0 ? `<span style="display: block; color: #ff7b72; margin-top: 2px;">🔥 High momentum signal detected</span>` : ''}
                    </div>
                ` : ''}
                
                <div class="u-grid-2 u-p-1 u-m-top-1" style="background:rgba(255,255,255,0.03); border-radius: 8px; border:1px solid var(--border);">
                    <div>
                        <h4>Risk Momentum</h4>
                        <div style="font-size:var(--font-m); color:#c9d1d9; font-weight:600;">${!isLocked ? (formatIntensity(alert.intensity) || '•.••') : '•.••'}</div>
                    </div>
                    <div>
                        <h4>Evidence</h4>
                        <div class="evidence-trigger-btn u-m-top-1" style="color:#58a6ff; background:var(--accent-soft); padding:4px 12px; border-radius:6px; display:inline-block; border:1px solid var(--border-active); font-size: var(--font-s); cursor: ${!isLocked ? 'pointer' : 'not-allowed'};">
                            🔍 ${!isLocked ? (alert.domain_count || 0) : '•'} Domains
                        </div>
                    </div>
                    <div>
                        <h4>Confidence</h4>
                        <div style="font-size:var(--font-m); color:${!isLocked && (alert.spike_delta || 0) > 0 ? '#3fb950' : '#8b949e'}; font-weight:600;">
                            ${!isLocked ? ((alert.spike_delta || 0) > 0 ? '↑' : '') + (alert.spike_delta || 0).toFixed(1) : '•.••'}
                        </div>
                    </div>
                    ${hasReport ? `
                    <div style="display:flex; align-items:flex-end;">
                        <button class="btn-fb active view-report-btn u-w-full ${isLocked ? 'btn--locked' : ''}">
                            ${!isLocked ? 'View Analysis' : 'Report Locked'}
                        </button>
                    </div>
                    ` : `
                    <div style="font-size:var(--font-xs); color:#8b949e; display:flex; align-items:flex-end; opacity:0.6; font-style: italic;">
                        ${!isLocked ? 'Report not available yet' : 'Upgrade Required'}
                    </div>
                    `}
                </div>
                
                ${accessible ? `
                <div class="impact-chain-system u-m-top-1" style="background: rgba(88,166,255,0.02); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem;">
                    <div style="font-weight: 800; font-size: 0.65rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.75rem; display: flex; align-items: center; gap: 8px;">
                        <span>⛓️</span> Cascading Impact Analysis (3rd-Order)
                    </div>
                    
                    <!-- Primary Signal -->
                    <div class="impact-node" style="position: relative; padding-left: 1.2rem; margin-bottom: 0.5rem;">
                        <div style="position: absolute; left: 0; top: 0; bottom: 0; width: 2px; background: var(--accent); opacity: 0.5;"></div>
                        <div style="font-weight: 700; color: var(--accent); font-size: 0.75rem;">PRIMARY SIGNAL</div>
                        <div style="font-size: 0.75rem; opacity: 0.9;">Detected anomaly in ${alert.topic || 'Sector'}</div>
                    </div>

                    <!-- Secondary Impact -->
                    <div class="impact-node" style="position: relative; padding-left: 1.2rem; margin-left: 0.6rem; margin-bottom: 0.5rem;">
                        <div style="position: absolute; left: 0; top: -0.5rem; bottom: 0; width: 2px; background: #8b949e; opacity: 0.3;"></div>
                        <div style="position: absolute; left: -0.6rem; top: 0.4rem; width: 0.6rem; height: 2px; background: #8b949e; opacity: 0.3;"></div>
                        <div style="font-weight: 700; color: #c9d1d9; font-size: 0.75rem;">↳ 2ND WAVE (RIPPLE)</div>
                        <div style="font-size: 0.75rem; opacity: 0.8;">Network-level volatility & cross-domain correlation</div>
                    </div>

                    <!-- Tertiary (Enterprise) Impact -->
                    <div class="impact-node" style="position: relative; padding-left: 1.2rem; margin-left: 1.2rem;">
                        <div style="position: absolute; left: 0; top: -0.5rem; bottom: 0.6rem; width: 2px; background: #8b949e; opacity: 0.3;"></div>
                        <div style="position: absolute; left: -0.6rem; top: 0.4rem; width: 0.6rem; height: 2px; background: #8b949e; opacity: 0.3;"></div>
                        <div style="font-weight: 700; color: #3fb950; font-size: 0.75rem;">↳ 3RD WAVE (ENTERPRISE ASSET)</div>
                        <div style="font-size: 0.75rem; opacity: 0.8; font-style: italic;">Detailed impact on Strategic Portfolio Assets</div>
                    </div>
                </div>
                ` : ''}

                <div class="u-flex-between u-m-top-1">
                    <div style="font-size: var(--font-xs); color: #8b949e; opacity: 0.8;">
                        ${accessible ? (alert.delivery ? `DIRECT INTELLIGENCE SIGNAL` : 'BROADCAST ALERT') : `Locked Sector: ${topicDef.label}`}
                    </div>
                    <div class="validation-badge" style="font-size: 0.65rem; color: #3fb950; display: flex; align-items: center; gap: 4px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">
                        ${accessible ? '<span>✓</span> Validated' : ''}
                    </div>
                </div>
                
                <div class="u-m-top-1" style="border-top: 1px solid var(--border); padding-top: 0.75rem;">
                    <a class="map-viz-link ${!accessible ? 'btn--locked' : ''}" data-id="${alert.id}" style="font-size: 0.8rem; color: var(--accent); cursor: pointer; text-decoration: none; font-weight: 600; display: inline-flex; align-items: center; gap: 4px;">
                        Visualize & Track on Global Map &rarr;
                    </a>
                </div>
            </div>
        `;

        return `
            <div class="alert-card ${severityClass} ${!accessible ? 'alert-card--locked' : ''}" data-id="${alert.id}" data-topic="${alert.topic || ''}">
                ${cardContent}
            </div>
        `;
    }).join('');

    // Attach Visualize & Track events
    container.querySelectorAll('.map-viz-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.stopPropagation();
            const target = e.currentTarget as HTMLElement;
            const alertId = target.dataset.id;
            console.log(`[Antigravity] Map Tracking Initiated for Alert: ${alertId}`);
            window.dispatchEvent(new CustomEvent('map-track-alert', { detail: { id: alertId } }));
        });
    });

    // Attach View Report events
    container.querySelectorAll('.view-report-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation(); // prevent triggering focus-map
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
            e.stopPropagation(); // prevent triggering focus-map
            const card = (e.currentTarget as HTMLElement).closest('.alert-card') as HTMLElement;
            const alertId = card.dataset.id;
            const alert = alerts.find(a => a.id === alertId);
            if (alert && alert.evidence_list && alert.evidence_list.length > 0) {
                // [v34] Restore simplified inline-safe modal for alerts
                showEvidenceModal(alert.target_label || 'Signal', alert.evidence_list || []);
            }
        });
    });

    // Attach Map Focus events (Exclusive to the visualize link)
    container.querySelectorAll('.map-viz-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.stopPropagation();
            const el = e.currentTarget as HTMLElement;
            const alertId = el.dataset.id;
            console.log(`[Antigravity] Visualize Link Clicked: ID = ${alertId}`);
            if (alertId) {
                (window as any)._mapTriggerTimestamp = Date.now();
                window.dispatchEvent(new CustomEvent('focus-map', { detail: { alertId } }));
            }
        });
    });

    // Attach login triggers
    container.querySelectorAll('.trigger-login-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            window.dispatchEvent(new CustomEvent('trigger-login'));
        });
    });

    // Attach Plans Trigger events
    container.querySelectorAll('.trigger-plans-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelector<HTMLElement>('#nav-plans')?.click();
            // Optional: Slight delay to ensure tab is rendered before scrolling/highlighting
            setTimeout(() => {
                const pricing = document.querySelector('.pricing-container') || document.querySelector('.subscription-grid');
                if (pricing) {
                    pricing.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    pricing.classList.add('pulse-highlight');
                    setTimeout(() => pricing.classList.remove('pulse-highlight'), 3000);
                }
            }, 100);
        });
    });

    // Add persistent footer to the container base
    const footer = document.createElement('div');
    footer.className = 'content-footer u-m-top-2 u-p-2 u-text-center';
    footer.style.opacity = '0.4';
    footer.style.fontSize = '0.7rem';
    footer.style.borderTop = '1px solid var(--border)';
    footer.innerHTML = `
        <div style="display: flex; justify-content: center; gap: 1rem; margin-bottom: 0.5rem;">
            <a href="disclosure.html" target="_blank" style="color: inherit; text-decoration: none;">Commercial Disclosure</a>
            <a href="terms.html" target="_blank" style="color: inherit; text-decoration: none;">Terms</a>
            <a href="privacy.html" target="_blank" style="color: inherit; text-decoration: none;">Privacy</a>
        </div>
        <div>&copy; 2026 VELTRIXIA LABS | Global Risk Intelligence Platform</div>
    `;
    container.appendChild(footer);
}
