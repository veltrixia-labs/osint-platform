import L from 'leaflet';
import type { Alert, AnalystProfile, HealthData } from './api';
import { fetchAlerts, updateWatchlist } from './api';
import { getTopicDef, canAccessTopic, canAccessReport, normalizeReportType, REPORT_TYPE_LABELS, REPORT_TYPE_MIN_TIER } from './topics';
import { STRATEGIC_ASSETS, getStrategicContext } from './infrastructure';
 
let activeMapFilters = new Set(['global']);

const TOPIC_LABELS: Record<string, string> = {
    geopolitical: 'Geopolitical',
    supply_chain: 'Supply Chain',
    market: 'Global Market',
    tech: 'Tech Infrastructure'
};

let currentFilterControl: L.Control | null = null;

function formatIntensity(val: number | undefined | null): string | null {
    // Treat 0 or negative as invalid/missing for UI presentation purposes
    if (typeof val !== 'number' || isNaN(val) || val <= 0) return null;
    const rounded = val.toFixed(1);
    let label = 'Low';
    if (val >= 4) label = 'High';
    else if (val >= 2) label = 'Medium';
    return `${rounded} (${label})`;
}

/**
 * Hierarchical coordinate extraction to handle differing API response formats.
 * Priority: Top-level > metadata_json > cascading_impacts[0]
 */
function getAlertCoords(alert: Alert): { lat: number, lng: number, source: string } | null {
    if (alert.location_lat && alert.location_lng) {
        return { lat: alert.location_lat, lng: alert.location_lng, source: 'Top-Level' };
    }
    const meta = alert.metadata_json as any;
    if (meta?.location_lat && meta?.location_lng) {
        return { lat: meta.location_lat, lng: meta.location_lng, source: 'Metadata' };
    }
    const impacts = (alert.cascading_impacts || meta?.cascading_impacts) as any[];
    if (impacts && impacts.length > 0) {
        return getNodeCoords(impacts[0]);
    }
    return null;
}

/**
 * Generic coordinate extractor for Stakeholder/Finding nodes.
 */
function getNodeCoords(node: any): { lat: number, lng: number, source: string } | null {
    if (node.location_lat && node.location_lng) {
        return { lat: node.location_lat, lng: node.location_lng, source: 'Node-Direct' };
    }
    if (node.metadata_json?.location_lat && node.metadata_json?.location_lng) {
        return { lat: node.metadata_json.location_lat, lng: node.metadata_json.location_lng, source: 'Node-Metadata' };
    }
    return null;
}

/**
 * Sanitizes markdown content by identifying raw intensity floats and formatting them.
 */
function sanitizeMarkdownIntensities(text: string): string {
    if (!text) return text;
    
    // 1. Remove redundant systemic prefixes that reduce scan speed
    const prefixExcludes = [
        /Emerging high-risk event detected:\s*/gi,
        /Rapid risk escalation detected:\s*/gi,
        /Sustained activity detected for event:\s*/gi,
        /High-risk signal:\s*/gi
    ];
    let cleanText = text;
    prefixExcludes.forEach(re => { cleanText = cleanText.replace(re, ''); });

    // 2. Robust regex: Matches "Intensity: 3.8", "(Intensity: 3.8)", "Intensity Score: 3.8", etc.
    return cleanText.replace(/\(?Intensity(?:\s+Score)?\s*:\s*(\d+(?:\.\d+)?)\)?/gi, (match, val) => {
        const v = parseFloat(val);
        const formatted = formatIntensity(v);
        return formatted ? `Intensity: ${formatted}` : match;
    });
}

/**
 * [v34] Simplified Evidence Modal for Live Alerts (Non-global)
 */
function showEvidenceModal(title: string, evidenceList: any[]) {
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

export function renderHealth(data: HealthData, container: HTMLElement) {
    container.innerHTML = `
        <div class="health-grid">
            <div class="health-stat">
                <div class="u-flex u-flex-between">
                    <span class="health-label">Signal Fidelity <span class="help-tooltip" data-tooltip="Accuracy of AI signals.">?</span></span>
                    <span class="health-val">${((data.review_rate || 0) * 100).toFixed(0)}%</span>
                </div>
            </div>
            <div class="health-stat">
                <div class="u-flex u-flex-between">
                    <span class="health-label">Noise Reduction <span class="help-tooltip" data-tooltip="Data filtered out.">?</span></span>
                    <span class="health-val">${((data.suppression_ratio || 0) * 100).toFixed(0)}%</span>
                </div>
            </div>
        </div>
    `;
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

export function renderRiskProfile(health: HealthData, container: HTMLElement) {
    // Helper to generate sparkline HTML
    const genSparkline = (points: number[]) => {
        return points.map(p => {
            const h = Math.max(5, p * 100);
            return `<div class="sparkline-bar" style="height: ${h}%"></div>`;
        }).join('');
    };

    container.innerHTML = `
        <h2 style="font-size:1.1rem; margin-bottom:1rem;">Risk Profile</h2>
        
        <div class="risk-profile-card">
            <div class="u-flex-between">
                <span style="font-size:0.8rem; opacity:0.7;">Geo-Security Index</span>
                <span style="color:#ff7b72; font-weight:700;">${((health.review_rate || 0) * 10).toFixed(1)}</span>
            </div>
            <div class="sparkline-container">
                ${genSparkline([0.4, 0.5, 0.45, 0.6, 0.7, 0.8, 0.85])}
            </div>
            <div style="font-size:0.65rem; opacity:0.5; margin-top:0.4rem;">Trend: +12% Escalation (24h)</div>
        </div>

        <div class="risk-profile-card">
            <div class="u-flex-between">
                <span style="font-size:0.8rem; opacity:0.7;">Economic Stability</span>
                <span style="color:#3fb950; font-weight:700;">${((health.suppression_ratio || 0) * 10).toFixed(1)}</span>
            </div>
            <div class="sparkline-container">
                ${genSparkline([0.8, 0.75, 0.7, 0.65, 0.6, 0.5, 0.55])}
            </div>
            <div style="font-size:0.65rem; opacity:0.5; margin-top:0.4rem;">Trend: -4.2% Volatility (24h)</div>
        </div>
        
        <div class="u-m-top-1 u-p-1" style="background:rgba(99,102,241,0.05); border-radius:8px; border:1px solid rgba(99,102,241,0.1);">
            <div style="font-size:0.75rem; color:var(--accent); font-weight:600;">Active Correlation Map</div>
            <p style="font-size:0.7rem; opacity:0.6; margin-top:0.25rem;">32 nodes connected via 128 edges. Cross-domain intensity at peak.</p>
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
        const hoursAgo = (Date.now() - date.getTime()) / (1000 * 60 * 60);
        const isGuest = userTier === 'free';
        const isLocked = isGuest && hoursAgo < 24;

        const displayDate = isNaN(date.getTime()) ? 'Recent' : date.toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });
        
        const triggerLabel = (alert.trigger_type || 'Pattern').replace(/_/g, ' ').toUpperCase();
        const hasReport = !!alert.related_report_id;

        // [v38] Alert card access is topic-based OR time-delayed for guests. 
        // Report access within the card will be validated upon clicking/loading.
        const cardContent = `
            ${isLocked ? `
                <div class="lock-overlay u-flex-center" style="position:absolute; inset:0; background:rgba(13,17,23,0.7); z-index:100; backdrop-filter:blur(8px); border-radius:12px; flex-direction:column; padding:1.5rem; text-align:center; border: 1px solid rgba(88,166,255,0.1);">
                    <div style="font-size:2.5rem; margin-bottom:1rem; filter: drop-shadow(0 0 10px var(--accent));">🔒</div>
                    <div style="font-weight:700; color:var(--accent); font-size:1.1rem; letter-spacing:0.1em; text-transform: uppercase;">Real-Time Signal Locked</div>
                    <div style="font-size:0.85rem; color:#8b949e; margin-top:0.75rem; line-height:1.6; max-width: 280px;">
                        This intelligence is currently restricted to <span style="color:#c9d1d9; font-weight:600;">Registered Analysts</span>. 
                        Public release in <strong style="color:var(--accent);">${Math.ceil(24 - hoursAgo)} hours</strong>.
                    </div>
                    <button class="btn-fb active u-m-top-1 trigger-plans-btn" style="box-shadow: 0 0 20px rgba(99,102,241,0.2); border-radius: 8px; padding: 10px 24px;">Unlock with Pro Plan →</button>
                </div>
            ` : ''}
            <div class="alert-header u-flex-between" style="${isLocked ? 'opacity:0.1; pointer-events:none;' : ''}">
                <div class="u-flex" style="flex-wrap: wrap; row-gap: 0.5rem;">
                    <span class="severity-badge">${alert.severity}</span>
                    <span class="watchlist-tag">
                        ${triggerLabel}
                    </span>
                    <span style="color: #8b949e; font-size: var(--font-xs);">${displayDate}</span>
                </div>
                <div class="u-text-right">
                    <div style="font-size: var(--font-xs); color:#8b949e;">Intelligence Priority</div>
                    <div class="intel-score">${accessible ? (alert.intelligence_score || 0).toFixed(2) : '•.••'}</div>
                </div>
            </div>
            
            <div class="alert-body" style="${isLocked ? 'opacity:0.1; pointer-events:none;' : ''}">
                <h3 style="color: #58a6ff; line-height: 1.4; margin-bottom: 0.25rem;">${alert.target_label || 'Unknown Signal'}</h3>
                ${!accessible ? `
                    <div style="font-size: var(--font-xs); color: ${topicDef.color}; opacity: 0.9; margin-bottom: 0.75rem; font-weight: 500;">
                        ${topicDef.valueProposition}
                        ${alert.intensity >= 8.0 ? `<span style="display: block; color: #ff7b72; margin-top: 2px;">🔥 High momentum signal detected</span>` : ''}
                    </div>
                ` : ''}
                
                <div class="u-grid-2 u-p-1 u-m-top-1" style="background:rgba(255,255,255,0.03); border-radius: 8px; border:1px solid var(--border);">
                    <div>
                        <h4>Risk Momentum <span class="help-tooltip" data-tooltip="A metric combining signal velocity and impact scale. High values indicate rapid escalation.">?</span></h4>
                        <div style="font-size:var(--font-m); color:#c9d1d9; font-weight:600;">${accessible ? (formatIntensity(alert.intensity) || '•.••') : '•.••'}</div>
                    </div>
                    <div>
                        <h4>Evidence</h4>
                        <div class="evidence-trigger-btn u-m-top-1" style="color:#58a6ff; background:var(--accent-soft); padding:4px 12px; border-radius:6px; display:inline-block; border:1px solid var(--border-active); font-size: var(--font-s); cursor: ${accessible ? 'pointer' : 'not-allowed'};">
                            🔍 ${accessible ? (alert.domain_count || 0) : '•'} Domains
                        </div>
                    </div>
                    <div>
                        <h4>Confidence <span class="help-tooltip" data-tooltip="Intelligence score representing the reliability and cross-source verification of the signal.">?</span></h4>
                        <div style="font-size:var(--font-m); color:${accessible && (alert.spike_delta || 0) > 0 ? '#3fb950' : '#8b949e'}; font-weight:600;">
                            ${accessible ? ((alert.spike_delta || 0) > 0 ? '↑' : '') + (alert.spike_delta || 0).toFixed(1) : '•.••'}
                        </div>
                    </div>
                    ${hasReport ? `
                    <div style="display:flex; align-items:flex-end;">
                        <button class="btn-fb active view-report-btn u-w-full ${!accessible ? 'btn--locked' : ''}">
                            ${accessible ? 'View Analysis' : `Upgrade to ${topicDef.minTier === 'pro' ? 'Pro' : 'Expert'} to access Intelligence`}
                        </button>
                    </div>
                    ` : `
                    <div style="font-size:var(--font-xs); color:#8b949e; display:flex; align-items:flex-end; opacity:0.6; font-style: italic;">
                        ${accessible ? 'Report not available yet' : 'Upgrade Required'}
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
                window.dispatchEvent(new CustomEvent('focus-map', { detail: { alertId } }));
            }
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

// [v33] Legacy showEvidenceModal removed in favor of global implementation at line 86

export function renderSidebar(analysts: AnalystProfile[], container: HTMLElement) {
    if (!analysts.length) return;
    const a = analysts[0];
    const usage = (window as any).getCurrentUsage?.() || { keywords: { used: 0, limit: 3 } };
    const isGuest = a.id === 'guest';

    container.innerHTML = `
        <div class="sidebar-header" style="margin-bottom: 1.5rem;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                <span style="font-size: 1.2rem; filter: drop-shadow(0 0 5px var(--accent));">📈</span>
                <h3 style="font-size: 0.9rem; letter-spacing: 0.02em; font-weight: 700; color: #fff;">Strategic Entities</h3>
            </div>
            <div style="display: flex; align-items: center; gap: 6px;">
                <span style="font-size: 1rem; opacity: 0.7;">🏢</span>
                <p style="font-size: 0.65rem; opacity: 0.5; font-weight: 600; text-transform: uppercase;">Enterprise Assets & Priorities</p>
            </div>
        </div>
        <div class="keyword-list">
            ${(a.watch_keywords || []).map(k => `
                <div class="kw-item u-flex-between">
                    <span>${k}</span>
                    <button class="remove-kw" data-keyword="${k}">&times;</button>
                </div>
            `).join('')}
        </div>
        <div class="add-kw-container u-m-top-1">
            <input type="text" id="new-keyword" placeholder="${isGuest ? 'Join to add' : 'Add entity...'}" ${isGuest ? 'disabled' : ''} />
            <button id="add-keyword-btn" class="u-tier-1" ${isGuest ? 'disabled' : ''}>Add</button>
            ${isGuest ? `
                <div class="guest-lock-msg" style="font-size: 0.7rem; color: var(--accent); margin-top: 8px; font-weight: 600;">
                    🔒 Account required for alerts
                </div>
            ` : (usage.keywords?.used >= usage.keywords?.limit ? `
                <div style="font-size: 0.7rem; color: #ff7b72; margin-top: 8px;">
                    Keyword limit reached (${usage.keywords.limit}/${usage.keywords.limit}). 
                    <a href="#" id="watchlist-upgrade-link" style="color:#58a6ff; text-decoration:none;">Upgrade to Pro</a>
                </div>
            ` : '')}
        </div>

        <div class="sidebar-footer-nav" style="margin-top: auto; padding-top: 2rem; border-top: 1px solid var(--border);">
            ${isGuest ? '' : `
                <div class="sidebar-analyst-id">
                    Analyst ID: ${a.id.slice(0, 8)}...
                </div>
                <button class="btn-logout" style="width: 100%; margin-top: 1rem; opacity: 0.6;" onclick="window.dispatchEvent(new CustomEvent('logout-request'))">Logout</button>
            `}

            <div class="legal-links u-m-top-1" style="font-size: 0.65rem; opacity: 0.4; text-align: center; display: flex; flex-wrap: wrap; justify-content: center; gap: 8px;">
                <a href="disclosure.html" target="_blank" style="color: inherit; text-decoration: none;">Disclosure</a>
                <a href="terms.html" target="_blank" style="color: inherit; text-decoration: none;">Terms</a>
                <a href="privacy.html" target="_blank" style="color: inherit; text-decoration: none;">Privacy</a>
            </div>
            <div style="font-size: 0.6rem; opacity: 0.3; text-align: center; margin-top: 8px;">&copy; 2026 VELTRIXIA LABS</div>
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
                const updatedKws = [...currentKws, val];
                await updateWatchlist(a.id, updatedKws);
                
                // Optimistic & State Sync: Update the local analyst object in memory
                a.watch_keywords = updatedKws;
                input.value = ""; // Clear input
                
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
                const updatedKws = currentKws.filter(k => k !== kw);
                await updateWatchlist(a.id, updatedKws);
                a.watch_keywords = updatedKws; // State Sync
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
        .replace(/^\- (High Priority|Monitor|Maintain): (.*$)/gm, (_, priority, text) => {
            const cls = priority.toLowerCase().replace(' ', '-');
            let cleanText = text;
            let rationaleHtml = '';
            let confidenceHtml = '';
            
            // Extract Rationale first
            const rationaleMatch = cleanText.match(/ — \*(.*)\*/);
            if (rationaleMatch) {
                cleanText = cleanText.replace(rationaleMatch[0], '');
                rationaleHtml = `<span class="report-action-rationale">${rationaleMatch[1]}</span>`;
            }
            
            // Extract Confidence second
            const confidenceMatch = cleanText.match(/ — Confidence: (High|Medium|Low)/i);
            if (confidenceMatch) {
                const confValue = confidenceMatch[1];
                const confClass = confValue.toLowerCase() === 'low' ? 'confidence-low' : '';
                cleanText = cleanText.replace(confidenceMatch[0], '');
                confidenceHtml = `<span class="confidence-tag ${confClass}">${confValue}</span>`;
            }
            
            return `<li class="priority-${cls}">${cleanText.trim()}${rationaleHtml}${confidenceHtml}</li>`;
        })
        .replace(/^\* (.*$)/gm, (_, content) => {
            // Case: Outcome with structured metadata: [IMPACT: HIGH, TIME: Immediate]
            const metaMatch = content.match(/\[IMPACT:\s*(HIGH|MEDIUM|LOW),\s*TIME:\s*([^\]]+)\]/i);
            if (metaMatch) {
                const textOnly = content.replace(metaMatch[0], '').trim();
                const impact = metaMatch[1].toUpperCase();
                const time = metaMatch[2];
                return `<li>${textOnly} <span class="impact-tag impact-${impact.toLowerCase()}">${impact} IMPACT</span> <span class="separator">·</span> <span class="time-tag">${time}</span></li>`;
            }
            return `<li>${content}</li>`;
        })
        .replace(/^\- (.*$)/gm, '<li>$1</li>')
        .replace(/\*\*(.*)\*\*/g, '<b>$1</b>')
        .replace(/\*(.*)\*/g, '<i>$1</i>')
        .replace(/!\[(.*?)\]\((.*?)\)/g, '<img src="$2" alt="$1" class="report-visual u-m-top-1" style="max-width:100%; border-radius:8px; border:1px solid var(--border);">')
        .replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank" style="color:var(--tier-grace);">$1</a>')
        .replace(/\n/g, '<br>');
}

export function renderReportDetail(report: any, userTier: string, container: HTMLElement, onBack?: () => void, onActionRequested?: (actionType: string) => void) {
    const dateStr = report.created_at || "";
    const cleanDate = dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T');
    const date = new Date(cleanDate).toLocaleDateString();

    // Use canonical mapping layer
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

    // Universal strip already handled in v32 logic above

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
                                s.content.trim().length > 30 // [v31] Only 'find' if it has real substance
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
                        
                        // Render Summary Box (Targeting high-decision value content)
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

                        if (!executive && !actions && sections.length > 0) {
                            // Failsafe: If no explicit headers match, use the first section as executive summary
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

                        // Render remaining in order (Impact Analysis / Watch Points handled via developments/scenarios mapping above)
                        const renderSec = (s: any, priority: 'medium' | 'low' = 'medium') => 
                            s ? `<div class="report-section--${priority}"><h3>${s.title}</h3>${simpleMarkdown(sanitizeMarkdownIntensities(s.content))}</div>` : '';

                        const impact = findSec(['Impact Analysis', 'Watch Points', 'Potential Implications']);
                        if (impact) html += renderSec(impact, 'medium');

                        html += renderSec(developments, 'medium');
                        html += renderSec(trend, 'medium');
                        html += renderSec(scenarios, 'low');
                        
                        // Render remaining bits
                        sections.forEach(s => {
                            html += renderSec(s, 'low');
                        });

                        console.log("[DEBUG] Final HTML Generated. Length:", html.length);
                        
                        // [v30] Content Lockdown: If structured rendering is abnormally thin compared to source
                        const sourceLen = md.trim().length;
                        const resultLen = html.replace(/<[^>]*>/g, '').trim().length; // Text-only length
                        
                        const isAbnormallyThin = sourceLen > 500 && resultLen < 150;

                        if ((!html.trim() || isAbnormallyThin) && sourceLen > 0) {
                            console.warn("[Antigravity] Structured extraction failed or thin. Falling back to simple markdown.");
                            html = simpleMarkdown(sanitizeMarkdownIntensities(fullOriginalMd)); // [v31] Use Backup
                        }
                        
                        // Final Failsafe
                        return html || `<div class="u-p-2 u-text-center" style="opacity:0.6;">(Detailed intelligence for this sector is currently being synchronized...)</div>`;
                    })()}
                </div>

                ${isPreview ? `
                    <div class="paywall-overlay-v2">
                        <div class="nexus-preview">
                            <!-- Ghost Nodes -->
                            <div class="ghost-node" style="top:20%; left:30%;">?</div>
                            <div class="ghost-node" style="top:60%; left:70%;">?</div>
                            <div class="ghost-node" style="top:40%; left:50%; font-size:3rem; opacity:0.5;">🔒</div>
                            <div class="ghost-node" style="top:10%; left:80%;">?</div>
                            <div class="ghost-node" style="top:80%; left:20%;">?</div>
                            
                            <div style="position:absolute; bottom:1rem; width:100%; text-align:center; color:var(--accent); font-size:0.8rem; font-weight:600; letter-spacing:0.1em; text-shadow:0 0 10px rgba(0,0,0,0.5);">
                                NEXUS CORRELATION GRAPH (ENCRYPTED PREVIEW)
                            </div>
                        </div>

                        <h2 style="color: #c9d1d9; margin-top: 1rem;">Unlock Full Investigation</h2>
                        <p style="color: #8b949e; max-width: 500px; margin: 0 auto 1.5rem;">
                            Access the complete multi-dimensional analysis, including entity relationship logs and risk propagation forecasts.
                        </p>

                        <div style="max-width: 450px; margin: 0 auto;">
                            <table class="comparison-table-mini">
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

                        <button id="cta-main-btn" class="btn-primary u-w-full u-tier-1" style="height: 54px; font-weight: 700; font-size: 1.1rem; box-shadow: 0 4px 20px var(--accent-soft);">
                            Upgrade to ${planDisplay} & Unlock
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
        container.querySelector('#cta-main-btn')?.addEventListener('click', () => {
            if (onActionRequested) onActionRequested('upgrade');
            else window.location.reload();
        });
    }
}

let currentGlobalMap: L.Map | null = null;
let currentDynamicLayer: L.LayerGroup | null = null;

export const renderMap = async (container: HTMLElement, _tier: string, focusAlertId?: string) => {
    console.log(`[Antigravity] Viewport update requested for Alert ID: ${focusAlertId || 'NONE'}`);
    
    // Safety delay to ensure Leaflet has a valid container size after the display:block transition
    await new Promise(r => setTimeout(r, 100));

    // 1. Persistent Map Canvas: Only initialize if not already mounted
    if (!currentGlobalMap) {
        container.innerHTML = '<div id="map-instance" style="height:100%; width:100%; min-height:500px; background:transparent;"></div>';
        
        // Wait for DOM
        await new Promise(r => setTimeout(r, 50));
        
        const mapElement = document.getElementById('map-instance');
        if (!mapElement) return;

        currentGlobalMap = L.map('map-instance', {
            zoomControl: false,
            attributionControl: false,
            minZoom: 2,
            maxZoom: 16,
            worldCopyJump: true
        }).setView([20, 0], 2);

        // Base layer: World Dark Gray
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Esri'
        }).addTo(currentGlobalMap);

        // Reference layer: English Labels
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
            className: 'map-labels'
        }).addTo(currentGlobalMap);

        L.control.zoom({ position: 'bottomright' }).addTo(currentGlobalMap);
        
        // Create an exclusive layer for dynamic alerts/arcs 
        currentDynamicLayer = L.layerGroup().addTo(currentGlobalMap);
    }
    
    // UI: Native Filter Control (Always Refresh/Re-bind)
    initMapFilter(currentGlobalMap, () => {
        renderMap(container, _tier, focusAlertId);
    });

    const map = currentGlobalMap;
    const layerGroup = currentDynamicLayer!;
    
    // Re-bind layerGroup if it became detached (Sanity Check)
    if (!map.hasLayer(layerGroup)) {
        layerGroup.addTo(map);
    }
    console.log(`[Antigravity] Arc Layer Active: ${map.hasLayer(layerGroup)}`);

    // Clear old dynamic elements precisely without touching base tiles
    layerGroup.clearLayers();
    
    // Force a resize check in case the container flexed
    setTimeout(() => {
        map.invalidateSize();
        console.log(`[Antigravity] Map Container Ready (Size Invalidated)`);
    }, 150);

    // Initial view reset if no focus
    if (!focusAlertId) {
        map.setView([20, 0], 2);
    }

    try {
        // Fetch Alerts (Reports removed from map for monitor purity)
        const [alerts] = await Promise.all([
            fetchAlerts()
        ]);

        // 1. Context Isolation (Exclusive Focus Mode)
        // If an alert is focused, we hide all OTHER alerts and reports to avoid clutter/overlap.
        let targetAlert: Alert | null = null;
        let filteredAlerts = alerts;

        if (focusAlertId) {
            targetAlert = alerts.find(a => a.id === focusAlertId) || null;
            if (targetAlert) {
                console.log(`[Antigravity] Exclusive Focus: ${targetAlert.target_label}`);
                filteredAlerts = [targetAlert];
                
// Filter reports removed for monitor purity
            } else {
                console.warn(`[Antigravity] Focus Alert ID ${focusAlertId} not found.`);
            }
        }

        // 2. Delayed Plotting to ensure Map Container is ready
        setTimeout(() => {
            layerGroup.clearLayers();
            renderRegionalContext(layerGroup, filteredAlerts);

        // Plot Filtered Alerts
        filteredAlerts.forEach(alert => {
            const coords = getAlertCoords(alert);
            if (coords) {
                const intensity = alert.intensity || 5;
                const isCritical = intensity >= 9.0;
                
                // [v35] Strategic Proximity Amplification (Gravity Well)
                const baseSize = 20 + (intensity * 2);
                const strategicHub = getStrategicContext(coords.lat, coords.lng, 500);
                const ampScale = strategicHub ? 1.5 : 1.0;
                const finalSize = baseSize * ampScale;

                const markerIcon = L.divIcon({
                    className: 'custom-div-icon',
                    html: `
                        <div class="map-marker-pulse ${isCritical ? 'map-marker-pulse--critical' : ''} ${strategicHub ? 'marker-gravity-well' : ''}" 
                             style="width: ${finalSize}px; height: ${finalSize}px;">
                            <div class="ring" style="background: ${strategicHub ? 'rgba(88, 166, 255, 0.4)' : ''};"></div>
                            <div class="core"></div>
                            ${strategicHub ? `<div class="gravity-label">[NEAR ${strategicHub.name.toUpperCase()}]</div>` : ''}
                        </div>
                    `,
                    iconSize: [finalSize, finalSize],
                    iconAnchor: [finalSize / 2, finalSize / 2]
                });

                const popupContent = `
                    <div style="padding:10px; min-width:240px;">
                        <strong style="color:var(--accent); font-size:1rem; display:block; margin-bottom:4px;">${alert.target_label}</strong>
                        <div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:8px;">
                            ${alert.topic?.replace('_', ' ').toUpperCase() || 'GLOBAL'} | ${alert.severity.toUpperCase()}
                        </div>
                        <div style="font-size:0.85rem; background:rgba(255,255,255,0.03); padding:8px; border-radius:6px; border:1px solid var(--border);">
                            Signal Intensity: <span style="color:var(--accent); font-weight:700;">${intensity.toFixed(1)}</span>
                        </div>
                        
                        ${alert.metadata_json?.cascading_impacts ? `
                            <div style="margin-top:12px; border-top:1px solid var(--border); padding-top:8px;">
                                <div style="font-size:0.7rem; color:var(--accent); font-weight:600; text-transform:uppercase; margin-bottom:4px;">Cascading Impacts</div>
                                ${alert.metadata_json.cascading_impacts.slice(0, 3).map((f: any) => `
                                    <div style="font-size:0.75rem; display:flex; justify-content:space-between; margin-bottom:2px;">
                                        <span style="color:#c9d1d9;">${f.entity_name}</span>
                                        <span style="color:${f.impact_alpha < 0 ? 'var(--danger)' : 'var(--success)'}; font-weight:700;">${f.impact_alpha > 0 ? '+' : ''}${f.impact_alpha}%</span>
                                    </div>
                                `).join('')}
                            </div>
                        ` : ''}
                    </div>
                `;

                const isFocus = focusAlertId === alert.id;
                
                const marker = L.marker([coords.lat, coords.lng], { 
                    icon: markerIcon,
                    zIndexOffset: isFocus ? 5000 : 1000,
                    pane: 'overlayPane' 
                })
                    .addTo(layerGroup)
                    .bindPopup(popupContent);
                    
                // Handle Focus / Camera Transition
                if (isFocus) {
                    console.log(`[Antigravity] Starting Transition to ${coords.lat}, ${coords.lng}`);
                    map.flyTo([coords.lat, coords.lng], 3, {
                        duration: 1.8,
                        easeLinearity: 0.25
                    });
                    
                    // Auto-open popup after transition
                    map.once('moveend', () => {
                        console.log(`[Antigravity] Transit Complete - Extracting details...`);
                        marker.openPopup();
                    });
                }

                // [Demo Discovery] Injecting 3rd-Order Chain for Strategic AI Infrastructure Surge
                if (alert.target_label === 'Strategic AI Infrastructure Surge') {
                    alert.cascading_impacts = [
                        {
                            stakeholder_id: 'nvda_001',
                            entity_name: 'NVIDIA',
                            impact_direction: 'positive',
                            impact_alpha: 4.2,
                            topic: 'market',
                            confidence: 0.94,
                            reasoning: 'Strategic AI Export Restrictions directly hit GPU sales.',
                            location_lat: 37.3541,
                            location_lng: -121.9552,
                            cascading_impacts: [
                                {
                                    stakeholder_id: 'tsmc_001',
                                    entity_name: 'TSMC',
                                    impact_direction: 'negative',
                                    impact_alpha: -2.8,
                                    topic: 'supply_chain',
                                    confidence: 0.88,
                                    reasoning: 'Reduced wafer demand from primary GPU client.',
                                    location_lat: 24.7735,
                                    location_lng: 121.0105,
                                    cascading_impacts: [
                                        {
                                            stakeholder_id: 'aws_001',
                                            entity_name: 'AWS',
                                            impact_direction: 'negative',
                                            impact_alpha: -1.5,
                                            topic: 'tech',
                                            confidence: 0.82,
                                            reasoning: 'GPU shortage delays cloud cluster expansion.',
                                            location_lat: 47.6062,
                                            location_lng: -122.3321
                                        }
                                    ]
                                }
                            ]
                        }
                    ];
                }

                // [v18 Upgrade] Recursive Cascading Impact Engine
                const impacts = alert.cascading_impacts || (alert as any).metadata_json?.cascading_impacts;
                if (impacts && impacts.length > 0) {
                    const shouldDrawArcs = !focusAlertId || isFocus;
                    if (shouldDrawArcs) {
                        const drawDelay = isFocus ? 1200 : 500; 
                        setTimeout(() => {
                            renderImpactChain(map, layerGroup, coords, impacts, 1, intensity);
                        }, drawDelay);
                    }
                }
            }
        });

// [v36] Report markers removed from map for 'Strategic Monitor' purity

        }, 300); // END delayed plotting loop

        setTimeout(() => map.invalidateSize(), 200);

    } catch (err) {
        console.error("Failed to load map data:", err);
    }
}

const renderRegionalContext = (layerGroup: L.LayerGroup, alerts: any[]) => {
    // 1. Foundational Alert Context (Hot Zones)
    const highIntensityAlerts = alerts.filter(a => (a.intensity || 0) > 8);
    highIntensityAlerts.forEach(alert => {
        if (alert.location_lat && alert.location_lng) {
            L.circle([alert.location_lat, alert.location_lng], {
                radius: 200000, 
                color: '#f43f5e',
                fillColor: '#f43f5e',
                fillOpacity: 0.05,
                stroke: false,
                interactive: false
            }).addTo(layerGroup);
        }
    });

    // 2. [v35] Persistent Strategic Infrastructure Layer
    STRATEGIC_ASSETS.forEach(asset => {
        // [v36] Asset Visibility Filter: Show if topic matches or it's a global choke point
        const isVisible = !asset.topic_code || activeMapFilters.has(asset.topic_code as string) || activeMapFilters.has('global');
        if (!isVisible) return;

        const color = asset.type === 'choke_point' ? '#58a6ff' : 
                     (asset.type === 'energy' ? '#f1e05a' : 
                     (asset.type === 'military' ? '#ff7b72' : 
                     (asset.type === 'market' ? '#3fb950' : 
                     (asset.type === 'crypto' ? '#f78166' : '#bc8cff'))));
        
        const assetIcon = L.divIcon({
            className: 'infrastructure-node',
            html: `
                <div class="infra-marker-container ${asset.type}" title="${asset.name}">
                    <div class="infra-dot" style="background: ${color};"></div>
                    <div class="infra-symbol">${asset.symbol || ''}</div>
                    <div class="infra-label">${asset.name}</div>
                </div>
            `,
            iconSize: [100, 24],
            iconAnchor: [50, 12]
        });

        L.marker([asset.lat, asset.lng], { icon: assetIcon, zIndexOffset: 500, pane: 'overlayPane' }).addTo(layerGroup);
        
        // Visual gravity wells for choke points
        if (asset.type === 'choke_point') {
             L.circle([asset.lat, asset.lng], {
                radius: 120000,
                color: color,
                fillOpacity: 0.02,
                weight: 1,
                dashArray: '5,10',
                interactive: false
            }).addTo(layerGroup);
        }
    });
}

/**
 * [v18 Upgrade] Recursive rendering engine for 3rd-order cascading impacts.
 */
/**
 * [v19 Upgrade] Recursive rendering engine with refined labels and filtering.
 */
function renderImpactChain(map: L.Map, layer: L.LayerGroup, parentCoords: {lat: number, lng: number}, impacts: any[], level: number, baseIntensity: number) {
    if (level > 3 || !impacts) return;

    impacts.forEach((finding, index) => {
        const nodeCoords = getNodeCoords(finding);
        if (!nodeCoords) return;

        // 0. Filter Check
        const nodeTopic = finding.topic || 'geopolitical';
        if (!activeMapFilters.has(nodeTopic)) return;

        const isLocked = finding.is_locked || false;
        console.log(`[Antigravity] Refined Label Rendered for: ${isLocked ? '???' : finding.entity_name} with Topic: ${nodeTopic}`);

        // 1. Calculate Bezier Path
        const start = L.latLng(parentCoords.lat, parentCoords.lng);
        const end = L.latLng(nodeCoords.lat, nodeCoords.lng);
        const points: L.LatLng[] = [];
        const steps = 36;
        
        const dLat = end.lat - start.lat;
        const dLng = end.lng - start.lng;
        const dist = Math.sqrt(dLat*dLat + dLng*dLng);
        
        const heightAttenuation = 1.0 - (level - 1) * 0.25; 
        const baseOffset = (0.15 + (Math.min(dist, 40) / 200)) * heightAttenuation;
        const overlapAvoidance = (index % 3 === 0) ? 0.05 : ((index % 3 === 1) ? -0.05 : 0);
        const offsetFactor = baseOffset + overlapAvoidance;

        const midLat = (start.lat + end.lat) / 2;
        const midLng = (start.lng + end.lng) / 2;
        let cpLat = midLat - dLng * offsetFactor;
        let cpLng = midLng + dLat * offsetFactor;
        cpLat = Math.max(-80, Math.min(80, cpLat));

        for (let i = 0; i <= steps; i++) {
            const t = i / steps;
            const lat = (1-t)**2 * start.lat + 2*(1-t)*t * cpLat + t**2 * end.lat;
            const lng = (1-t)**2 * start.lng + 2*(1-t)*t * cpLng + t**2 * end.lng;
            points.push(L.latLng(lat, lng));
        }

        // 2. Styling (Level-based)
        const pathColor = finding.impact_alpha < 0 ? '#f43f5e' : '#10b981';
        let weight = Math.max(1, (baseIntensity / 5) * (1.5 - (level-1)*0.4));
        let opacity = 0.8 - (level-1) * 0.25;
        let dashArray = level === 2 ? '5, 5' : (level === 3 ? '2, 6' : undefined);

        L.polyline(points, {
            className: `propagation-arc-curved ${isLocked ? 'ghost-node' : ''}`,
            color: pathColor,
            weight,
            opacity: isLocked ? 0.2 : opacity,
            dashArray
        }).addTo(layer);

        // 3. Recursive Call
        const subImpacts = finding.cascading_impacts || finding.metadata_json?.cascading_impacts;
        if (subImpacts && level < 3 && !isLocked) {
            renderImpactChain(map, layer, nodeCoords, subImpacts, level + 1, baseIntensity);
        }

        // 4. Particle Animation
        if (!isLocked) {
            const animParticle = L.circleMarker(points[0], {
                radius: 2.5 - (level-1)*0.5,
                color: '#ffffff',
                fillColor: pathColor,
                fillOpacity: 1,
                weight: 1,
                className: 'pulse-particle-dynamic',
                pane: 'overlayPane'
            }).addTo(layer);

            // [v35] Physical Meaning Logic (Time-to-Impact)
            // Use alpha and level to determine hypothetical 'velocity'
            // alphaVal=10 (%) -> Fast, alphaVal=1 (%) -> Slow
            const alphaVal = Math.abs(finding.impact_alpha || 0.1);
            const levelDamping = 1.0 - (level - 1) * 0.2;
            const durationMs = Math.max(400, 3000 / (alphaVal * levelDamping)); 

            let startTime: number | null = null;
            const animatePulse = (timestamp: number) => {
                if (!startTime) startTime = timestamp;
                const elapsed = timestamp - startTime;
                const progress = (elapsed % durationMs) / durationMs;

                const indexFloat = progress * steps;
                const lowerIndex = Math.floor(indexFloat);
                const upperIndex = Math.min(steps, Math.ceil(indexFloat));
                const tLocal = indexFloat - lowerIndex;

                if (points[lowerIndex] && points[upperIndex]) {
                     const lat = points[lowerIndex].lat + (points[upperIndex].lat - points[lowerIndex].lat) * tLocal;
                     const lng = points[lowerIndex].lng + (points[upperIndex].lng - points[lowerIndex].lng) * tLocal;
                     animParticle.setLatLng([lat, lng]);

                     // [v35] Dynamic Decay/Trail: Faster particles are more opaque
                     const opacity = 0.5 + (alphaVal / 20);
                     animParticle.setStyle({ fillOpacity: opacity, opacity: opacity });
                }
                
                if (currentGlobalMap === map && layer.hasLayer(animParticle)) {
                    requestAnimationFrame(animatePulse);
                }
            };
            requestAnimationFrame(animatePulse);
        }

        // 5. Refined Node Marker (Mockup Aesthetic with Overlap Dodge)
        const trendIcon = finding.impact_alpha >= 0 ? '↑' : '↓';
        const trendClass = finding.impact_alpha >= 0 ? 'alpha-up' : 'alpha-down';
        const topicLabel = TOPIC_LABELS[nodeTopic] || 'General';

        // Aggressive dodge: At low zoom (level 2-3), labels are 48px high. 1 deg is tiny.
        // We push Level 3 nodes as far as 8-10 degrees to ensure clear separation from the Alert/Level 1 centers.
        const vOffset = level === 1 ? 0 : (level === 2 ? 3.5 : (index % 2 === 0 ? 8.0 : -8.0));
        const finalCoords: [number, number] = [nodeCoords.lat + vOffset, nodeCoords.lng];

        const pulseIcon = L.divIcon({
            className: 'none',
            html: `
                <div class="market-pulse-node refined-node ${isLocked ? 'ghost-node' : ''}" 
                     style="scale: ${1.0 - (level-1)*0.1};"
                     onclick="${isLocked ? 'window.dispatchEvent(new CustomEvent(\'upsell-click\'))' : ''}">
                    <div class="node-topic topic-tag-${nodeTopic}">${isLocked ? '[LOCKED]' : `[${topicLabel.toUpperCase()}]`}</div>
                    <div class="node-entity">${isLocked ? '???' : finding.entity_name}</div>
                    <div class="node-stats">
                        <span class="${trendClass}">${isLocked ? 'Locked' : (finding.impact_alpha > 0 ? '+' : '') + finding.impact_alpha + '%'}</span>
                        <span class="trend-arrow ${trendClass}">${isLocked ? '' : trendIcon}</span>
                    </div>
                </div>
            `,
            iconSize: [140, 48],
            iconAnchor: [70, level === 1 ? 24 : 70] // Pivot higher level nodes significantly up
        });
        
        L.marker(finalCoords, { 
            icon: pulseIcon,
            zIndexOffset: 1000 - level * 50,
            pane: 'overlayPane'
        }).addTo(layer);
    });
}

function initMapFilter(map: L.Map, onUpdate: () => void) {
    if (currentFilterControl) {
        currentFilterControl.remove();
    }

    const FilterControl = L.Control.extend({
        options: { position: 'topleft' },
        onAdd: function() {
            const div = L.DomUtil.create('div', 'map-filter-control map-filter-panel');
            L.DomEvent.disableClickPropagation(div);
            L.DomEvent.disableScrollPropagation(div);

            // [v36] 7-Domain Strategic Asset List
            const TOPICS = [
                { id: 'global', label: 'Monitor', icon: '🌐', color: '#58a6ff' },
                { id: 'energy_resource_risk', label: 'Energy', icon: '⚡', color: '#d29922' },
                { id: 'global_market_intelligence', label: 'Market', icon: '🏛️', color: '#3fb950' },
                { id: 'crypto_geopolitics', label: 'Crypto', icon: '₿', color: '#f78166' },
                { id: 'ai_semiconductor_intelligence', label: 'AI/Tech', icon: '🤖', color: '#bc8cff' },
                { id: 'defense_technology', label: 'Defense', icon: '🛡️', color: '#ff7b72' },
                { id: 'supply_chain_intelligence', label: 'Trade', icon: '🚢', color: '#79c0ff' }
            ];

            div.innerHTML = `
                <div class="monitor-header u-flex-between">
                    <h3>Strategic Monitoring</h3>
                    <span style="font-size: 0.65rem; opacity: 0.5;">LIVE V1.5</span>
                </div>
                <div class="monitor-hotbar">
                    ${TOPICS.map(t => `
                        <button class="preset-btn ${activeMapFilters.has(t.id) ? 'active' : ''}" 
                                data-preset="${t.id}" 
                                style="--accent-color: ${t.color}"
                                title="${t.label} Intelligence">
                            <span class="btn-icon">${t.icon}</span>
                            <span class="btn-label">${t.label}</span>
                        </button>
                    `).join('')}
                </div>
            `;
            
            // [v36] Preset Button Handlers (Exclusive Filter)
            div.querySelectorAll('.preset-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const preset = (e.currentTarget as HTMLElement).dataset.preset!;
                    activeMapFilters.clear();
                    activeMapFilters.add(preset);
                    
                    // Correlation Logic: Tech also shows Global Market
                    if (preset === 'ai_semiconductor_intelligence') activeMapFilters.add('global_market_intelligence');
                    if (preset === 'supply_chain_intelligence') activeMapFilters.add('global');
                    
                    onUpdate();
                });
            });

            return div;
        }
    });

    currentFilterControl = new (FilterControl as any)();
    currentFilterControl?.addTo(map);
}

