import { apiClient, type Alert } from '../api';
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
    // [v16.0] Compact Pulse Bar: Single most critical/recent signal
    const severityMap: Record<string, number> = { critical: 3, elevated: 2, watch: 1 };
    const latest = [...alerts].sort((a,b) => {
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
    const timeStr = new Date(latest.triggered_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    
    // Apply temporary fade class if container already had content (simulating update)
    const isUpdate = container.innerHTML.length > 0;
    
    container.innerHTML = `
        <div class="pulse-content ${isUpdate ? 'pulse-fade-update' : ''}" style="display: flex; align-items: center; gap: 10px; width: 100%; overflow: hidden;">
            <span class="severity-dot ${severityClass}"></span>
            <span style="font-weight:900; color:var(--accent); font-size: 0.65rem; text-transform: uppercase; letter-spacing: 1px;">${latest.topic?.toUpperCase() || 'CORE'}</span>
            <span style="flex:1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 0.75rem; font-weight: 600; color: #fff;">${latest.target_label}</span>
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
    const sortedAlerts = [...alerts].sort((a,b) => {
        const sevMap: Record<string, number> = { critical: 3, elevated: 2, watch: 1 };
        const sevA = sevMap[a.severity?.toLowerCase() || ''] || 0;
        const sevB = sevMap[b.severity?.toLowerCase() || ''] || 0;
        if (sevA !== sevB) return sevB - sevA;
        return new Date(b.triggered_at).getTime() - new Date(a.triggered_at).getTime();
    });

    if (sortedAlerts.length === 0) {
        container.innerHTML = `
            <div class="u-p-2 u-text-center" style="opacity:0.5; border: 1px dashed var(--border); border-radius: 8px; margin-top: 2rem;">
                <div style="font-size: 1.5rem; margin-bottom: 0.5rem;">📡</div>
                <div style="font-size: var(--font-m); font-weight: 500;">No active signals detected in this sector.</div>
                <div style="font-size: var(--font-xs); margin-top: 0.25rem;">The AI backbone is currently scanning for strategic momentum.</div>
            </div>
        `;
        return;
    }

    container.innerHTML = sortedAlerts.map(alert => {
        const topicDef = getTopicDef(alert.topic);
        const accessible = canAccessTopic(userTier, topicDef);
        const severityClass = alert.severity.toLowerCase();
        const date = new Date(alert.triggered_at);

        const displayDate = isNaN(date.getTime()) ? 'Recent' : date.toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });
        
        const triggerLabel = (alert.trigger_type || 'Pattern').replace(/_/g, ' ').toUpperCase();

        // [v50] Unified Mosaic Gating UI - DISABLED for Dev Release
        const status = alert.backbone_discovery_status || 'idle';
        const statusMap: Record<string, {label: string, class: string}> = {
            'processing': { label: 'AI REFINING', class: 'status-processing' },
            'complete': { label: 'ANALYSIS VERIFIED', class: 'status-complete' },
            'failed': { label: 'STATISTICAL ONLY', class: 'status-failed' },
            'idle': { label: 'DISCOVERY PENDING', class: 'status-failed' }
        };
        const statusCfg = statusMap[status] || statusMap['idle'];

        const cardContent = `
            <div class="alert-header u-flex-between">
                <div class="u-flex" style="flex-wrap: wrap; row-gap: 0.5rem; align-items: center;">
                    <span class="severity-badge">${alert.severity}</span>
                    <span class="discovery-status-badge ${statusCfg.class}" style="margin-right: 0.5rem;">
                        ${status === 'complete' ? '<span>✓</span>' : ''} ${statusCfg.label}
                    </span>
                    <span class="watchlist-tag">
                        ${triggerLabel}
                    </span>
                    <span style="color: #8b949e; font-size: var(--font-xs);">${displayDate}</span>
                    ${alert.is_partial ? `<span class="partial-view-badge" style="background: rgba(210, 153, 34, 0.05); color: rgba(210, 153, 34, 0.75); border: 1px solid rgba(210, 153, 34, 0.15); font-size: 0.55rem; font-weight: 800; padding: 1px 6px; border-radius: 4px; margin-left: auto;">LIMITED VIEW</span>` : ''}
                </div>
                <div class="u-text-right">
                    <div style="font-size: var(--font-xs); color:#8b949e;">Intelligence Priority</div>
                    <div class="intel-score">${(alert.intelligence_score || 0).toFixed(2)}</div>
                </div>
            </div>
            
            <div class="alert-body">
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
                        <div style="font-size:var(--font-m); color:#c9d1d9; font-weight:600;">
                            ${alert.is_partial ? `
                                <span style="color:rgba(88, 166, 255, 0.6); font-weight: 700;" title="Upgrade to Pro for precise intensity forensics">
                                    ${alert.intensity_label}
                                    ${alert.intensity_label === 'High' ? '<span style="font-size:0.6rem; opacity:0.6; margin-left:4px;">(Pro for details)</span>' : ''}
                                </span>
                                <span style="font-size: var(--font-xs); opacity: 0.4; margin-left: 4px;">(${alert.intensity_display})</span>
                            ` : (formatIntensity(alert.intensity) || '•.••')}
                        </div>
                    </div>
                    <div>
                        <h4>Evidence</h4>
                        <div class="evidence-trigger-btn u-m-top-1" style="color:#58a6ff; background:var(--accent-soft); padding:4px 12px; border-radius:6px; display:inline-block; border:1px solid var(--border-active); font-size: var(--font-s); cursor: pointer;">
                            🔍 ${alert.domain_count || 0} Domains
                        </div>
                    </div>
                    <div>
                        <h4>Confidence</h4>
                        <div style="font-size:var(--font-m); color:${(alert.spike_delta || 0) > 0 ? '#3fb950' : '#8b949e'}; font-weight:600;">
                            ${((alert.spike_delta || 0) > 0 ? '↑' : '') + (alert.spike_delta || 0).toFixed(1)}
                        </div>
                    </div>
                    <div style="display:flex; align-items:flex-end;">
                        ${status === 'processing' ? `
                        <span style="color: #8b949e; font-size: var(--font-s); font-weight: 600; cursor: not-allowed;">
                            ⏳ Incoming Strategic Signal...
                        </span>
                        ` : `
                        <a href="#" class="map-track-link" data-id="${alert.id}" style="color: var(--accent); font-size: var(--font-s); text-decoration: none; font-weight: 600; border-bottom: 1px solid transparent; transition: all 0.2s;" onmouseover="this.style.borderBottom='1px solid var(--accent)'" onmouseout="this.style.borderBottom='1px solid transparent'">
                            Visualize & Track on Global Map —
                        </a>
                        `}
                    </div>
                </div>
                
                ${(alert.cascading_impacts && alert.cascading_impacts.length > 0) ? `
                    <div class="impact-chain-system u-m-top-1" style="background: rgba(88,166,255,0.02); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem;">
                        <div style="font-weight: 800; font-size: 0.65rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.75rem; display: flex; align-items: center; gap: 8px;">
                            <span>⛓️</span> Active Impact Discovery (${alert.cascading_impacts[0].source === 'ai_reasoning' ? 'AI Analyzed' : 'Statistical Model'})
                        </div>
                        ${alert.cascading_impacts.slice(0, 3).map((imp, idx) => `
                            <div class="impact-node" style="position: relative; padding-left: 1.2rem; margin-bottom: 0.4rem; margin-left: ${idx * 0.6}rem;">
                                <div style="position: absolute; left: 0; top: 0; bottom: 0; width: 2px; background: ${idx === 0 ? 'var(--accent)' : '#8b949e'}; opacity: 0.5;"></div>
                                ${idx > 0 ? `<div style="position: absolute; left: -0.6rem; top: 0.4rem; width: 0.6rem; height: 2px; background: #8b949e; opacity: 0.3;"></div>` : ''}
                                <div style="font-weight: 700; color: ${idx === 0 ? 'var(--accent)' : (idx === 2 ? '#3fb950' : '#c9d1d9')}; font-size: 0.75rem;">
                                    ${idx === 0 ? 'PRIMARY RIPPLE' : (idx === 1 ? '↳ SECONDARY' : '↳ TERTIARY')} • ${imp.entity_name}
                                </div>
                                <div style="font-size: 0.7rem; opacity: 0.8;">${imp.reasoning || 'Cascading dependency detected.'}</div>
                            </div>
                        `).join('')}
                    </div>
                ` : (status === 'processing' ? `
                    <div class="impact-chain-system u-m-top-1" style="background: rgba(255,255,255,0.02); border: 1px dashed var(--border); border-radius: 8px; padding: 0.75rem; opacity: 0.7;">
                        <div style="font-weight: 800; font-size: 0.65rem; color: var(--accent); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.4rem; display: flex; align-items: center; gap: 8px;">
                            ⚙️ AI Refining Active
                        </div>
                        <div style="font-size: 0.7rem; color: #8b949e;">
                            High-fidelity impact analysis is currently running in the background. Actionable intelligence will appear automatically when complete.
                        </div>
                    </div>
                ` : `
                    <div class="impact-chain-system u-m-top-1" style="background: rgba(255,255,255,0.02); border: 1px dashed var(--border); border-radius: 8px; padding: 0.75rem; opacity: 0.7;">
                        <div style="font-weight: 800; font-size: 0.65rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.4rem;">
                            🔎 Analysis Missing for Past Signal
                        </div>
                        <div style="font-size: 0.7rem; color: #8b949e;">
                            This alert was generated before the Geopolitical Engine upgrade. 
                            <span style="color: var(--accent); font-weight: 600;">Visualize on map</span> to trigger real-time AI discovery.
                        </div>
                    </div>
                `)}

                <div class="u-flex-between u-m-top-1">
                    <div style="font-size: var(--font-xs); color: #8b949e; opacity: 0.8;">
                        ${accessible ? (alert.delivery ? `DIRECT INTELLIGENCE SIGNAL` : 'BROADCAST ALERT') : `Locked Sector: ${topicDef.label}`}
                    </div>
                    <div class="validation-badge" style="font-size: 0.65rem; color: #3fb950; display: flex; align-items: center; gap: 4px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">
                        ${accessible ? '<span>✓</span> Validated' : ''}
                    </div>
                </div>
                
                <div class="u-m-top-1" style="border-top: 1px solid var(--border); padding-top: 0.75rem;">
                    ${status === 'processing' ? `
                    <span style="font-size: 0.8rem; color: #8b949e; font-weight: 600; display: inline-flex; align-items: center; gap: 4px; cursor: not-allowed; opacity: 0.7;">
                        Incoming Strategic Signal... [AI Refining]
                    </span>
                    ` : `
                    <a class="map-viz-link ${!accessible ? 'btn--locked' : ''}" data-id="${alert.id}" style="font-size: 0.8rem; color: var(--accent); cursor: pointer; text-decoration: none; font-weight: 600; display: inline-flex; align-items: center; gap: 4px;">
                        Visualize & Track on Global Map &rarr;
                    </a>
                    `}
                </div>
            </div>
        `;

        return `
            <div class="alert-card ${severityClass} ${!accessible ? 'alert-card--locked' : ''}" data-id="${alert.id}" data-topic="${alert.topic || ''}" style="cursor: pointer;">
                ${cardContent}
            </div>
        `;
    }).join('');
    
    // [v11.3] Background Pre-Warming: Automate AI analysis for high-priority signals
    alerts.forEach(alert => {
        if (alert.intensity >= 6.5 && (alert.backbone_discovery_status === 'idle' || !alert.backbone_discovery_status)) {
            const topicDef = getTopicDef(alert.topic);
            const accessible = canAccessTopic(userTier, topicDef);
            if (accessible) {
                console.log(`[Antigravity] Auto-Promoting high-intensity alert to AI analysis: ${alert.id}`);
                apiClient.post(`/alerts/${alert.id}/analyze`).catch(err => {
                    console.warn(`[Antigravity] Background analysis trigger failed for ${alert.id}:`, err);
                });
            }
        }
    });

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

    // [v4.0] Card-level Map Interconnectivity (No page jump)
    container.querySelectorAll('.alert-card').forEach(card => {
        card.addEventListener('click', (e) => {
            if (e.target instanceof HTMLAnchorElement || e.target instanceof HTMLButtonElement || (e.target as HTMLElement).closest('a, button')) return;
            const alertId = (card as HTMLElement).dataset.id;
            console.log(`[Antigravity] Passive Map Sync Requested: Alert ${alertId}`);
            window.dispatchEvent(new CustomEvent('map-track-alert', { detail: { id: alertId, silent: true } }));
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

    // [v10.1] Tactical Map Optimization: Visualize & Track
    container.querySelectorAll('.map-track-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const el = e.currentTarget as HTMLElement;
            const id = el.dataset.id;
            console.log(`[Antigravity] Visualize Link Clicked: ID = ${id}`);
            if (id) {
                // [v10.9] Explicit Timestamp: Ensure map logic recognizes this as a fresh user action
                (window as any)._mapTriggerTimestamp = Date.now();
                
                // [v10.1] main.ts listens for map-track-alert to switch tabs and focus
                window.dispatchEvent(new CustomEvent('map-track-alert', { detail: { id } }));
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
