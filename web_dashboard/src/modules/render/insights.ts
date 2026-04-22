/**
 * insights.ts
 * Premium Intelligence Dashboards
 * 
 * Responsibilities:
 * - renderProInsights: Decision-grade briefing grid
 * - renderExpertIntel: Strategic-grade causal mapping & scenarios
 * - Pure CSS/SVG components for "Speed of Judgment"
 */

import type { 
    ProInsights, ExpertIntelligence, UserMe 
} from '../api';
import { fetchProInsights, fetchExpertIntelligence } from '../api';
import { getTopicDef } from '../topics';
import { renderLockedFeature } from '../subscription';

// ──────────────────────────────────────────────────────────────────────────────
// Component Primitives (Pure CSS / SVG)
// ──────────────────────────────────────────────────────────────────────────────

/** Renders a "Dashboard Card" wrapper */
function renderCard(title: string, content: string, footer?: string, accentColor = '#58a6ff'): string {
    return `
    <div class="insight-card" style="--accent: ${accentColor}">
        <div class="insight-card-header">
            <h3 class="insight-card-title">${title}</h3>
        </div>
        <div class="insight-card-body">
            ${content}
        </div>
        ${footer ? `<div class="insight-card-footer">${footer}</div>` : ''}
    </div>`;
}

/** Renders a horizontal "Intensity Bar" */
function renderIntensityBar(value: number, label: string, color = '#58a6ff'): string {
    const percent = Math.min(Math.max(value * 10, 0), 100);
    return `
    <div class="intensity-bar-wrap">
        <div class="intensity-bar-label">
            <span>${label}</span>
            <span style="color: ${color}">${value.toFixed(1)}</span>
        </div>
        <div class="intensity-bar-bg">
            <div class="intensity-bar-fill" style="width: ${percent}%; background: ${color}; box-shadow: 0 0 10px ${color}44;"></div>
        </div>
    </div>`;
}

/** Renders a small priority badge */
function renderPriorityBadge(priority: string, minimal = false): string {
    const colors: Record<string, string> = {
        'Critical': '#ff7b72',
        'Watch': '#d29922',
        'Low': '#3fb950'
    };
    const color = colors[priority] || '#adbac7';
    
    if (minimal) {
        return `<span class="priority-dot" title="${priority}" style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${color}; margin-left:6px;"></span>`;
    }
    
    return `
    <div class="priority-badge" style="background: ${color}22; border: 1px solid ${color}; color: ${color}; font-size: 0.6rem; font-weight: 800; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; letter-spacing: 0.5px;">
        ${priority}
    </div>`;
}

/** Renders a category-specific action badge */
function renderCategoryBadge(category: string): string {
    const colors: Record<string, string> = {
        'Immediate': '#ff7b72', // Red
        'Monitor': '#d29922',   // Orange
        'No Action': '#3fb950'  // Green
    };
    const color = colors[category] || '#8b949e';
    return `<span class="category-badge" style="color: ${color}; border-left: 2px solid ${color}; padding-left: 6px; font-size: 0.65rem; font-weight: 800; margin-left: 8px;">${category.toUpperCase()}</span>`;
}

// ──────────────────────────────────────────────────────────────────────────────
// Pro Insights Dashboard
// ──────────────────────────────────────────────────────────────────────────────

export async function renderProInsights(container: HTMLElement, user: UserMe, onNavigatePlans: () => void) {
    // 1. Tier Enforcement
    if (user.tier === 'guest' || user.tier === 'free') {
        container.innerHTML = renderLockedFeature('Pro Insights Dashboard', 'pro');
        const btn = container.querySelector('#locked-goto-plans');
        btn?.addEventListener('click', () => onNavigatePlans());
        return;
    }

    container.innerHTML = `<div class="intelligence-loader">Initializing Pro Suite...</div>`;

    try {
        const data: ProInsights = await fetchProInsights();
        
        // 2. Build Dashboard Grid
        container.innerHTML = `
        <div class="insights-dashboard pro-dashboard">
            <!-- Row 1: BLUF Summary -->
            <div class="dashboard-row bluf-row">
                ${Object.entries(data.risk_summary).map(([topic, stat]) => {
                    const def = getTopicDef(topic === 'null' ? null : topic);
                    return `
                    <div class="bluf-stat-card" style="--accent: ${def.color}">
                        <div class="bluf-header u-flex-between">
                            <div class="bluf-topic">${def.icon} ${def.label}</div>
                            <div class="bluf-trend bluf-trend--${stat.trend}">${stat.trend === 'rising' ? '▲' : '■'}</div>
                        </div>
                        <div class="u-flex u-flex-baseline">
                            <div class="bluf-value">${stat.intensity.toFixed(1)}</div>
                            ${stat.intensity_delta !== undefined ? `
                                <div class="bluf-delta ${stat.intensity_delta > 0.5 ? 'rising' : stat.intensity_delta < -0.5 ? 'falling' : ''}" style="margin-left: 8px; font-size: 0.75rem; font-weight: 800;">
                                    ${stat.intensity_delta > 0 ? '↑' : stat.intensity_delta < 0 ? '↓' : ''} ${Math.abs(stat.intensity_delta).toFixed(1)} <span style="font-weight:400; opacity:0.6;">(24h)</span>
                                </div>
                            ` : ''}
                            ${stat.spike_detected ? `<div class="spike-badge" title="UNUSUAL MOMENTUM DETECTED">SPIKE</div>` : ''}
                        </div>
                        <div class="bluf-label">${stat.why_it_matters}</div>
                        ${stat.anomaly_detected ? `<div class="anomaly-warning-pill">⚠️ ANOMALY DETECTED</div>` : ''}
                        <div class="bluf-latest-wrap">
                            <span class="bluf-latest-label">TOP SIGNAL</span>
                            <div class="bluf-latest">${stat.top_signal || 'None'}</div>
                        </div>
                    </div>`;
                }).join('')}
            </div>

            <!-- Row 2: Deep Analysis -->
            <div class="dashboard-grid">
                <!-- Sector Distribution -->
                ${renderCard('Sector Distribution', `
                    <div class="sector-dist-list">
                        ${Object.entries(data.sector_distribution).map(([topic, count]) => {
                            const def = getTopicDef(topic === 'null' ? null : topic);
                            return renderIntensityBar(count, def.label, def.color);
                        }).join('')}
                    </div>
                `)}

                <!-- Top Entities -->
                ${renderCard('Exposed Entities', `
                    <div class="entity-list">
                        ${data.top_entities.map(ent => `
                            <div class="entity-item">
                                <div class="entity-core u-flex-between">
                                    <span class="entity-name">${ent.name}</span>
                                    <span class="entity-badge">${ent.count}</span>
                                </div>
                                <div class="entity-comment">${ent.entity_comment || ''}</div>
                            </div>
                        `).join('')}
                    </div>
                `, 'Entities with highest signal frequency in 24h')}

                <!-- Momentum Alerts -->
                ${renderCard('Momentum Alerts', `
                    <div class="momentum-list">
                        ${data.momentum_alerts.map(alert => `
                            <div class="momentum-alert-item" style="border-left: 3px solid ${getTopicDef(alert.topic).color}">
                                <div class="momentum-alert-title">${alert.title}</div>
                                <div class="momentum-alert-meta">
                                    <span>${getTopicDef(alert.topic).label}</span>
                                    <span class="intensity-tag">${alert.intensity.toFixed(1)}</span>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                `, 'Top 3 signals by immediate volatility')}
            </div>
        </div>`;

    } catch (err) {
        container.innerHTML = `<div class="error-slate">Failed to load Pro Insights: ${err}</div>`;
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// Expert Intelligence Dashboard
// ──────────────────────────────────────────────────────────────────────────────

export async function renderExpertIntel(container: HTMLElement, user: UserMe, onNavigatePlans: () => void) {
    // 1. Tier Enforcement
    if (user.tier !== 'experts' && user.tier !== 'enterprise') {
        container.innerHTML = renderLockedFeature('Expert Strategic Suite', 'experts');
        const btn = container.querySelector('#locked-goto-plans');
        btn?.addEventListener('click', () => onNavigatePlans());
        return;
    }

    container.innerHTML = `<div class="intelligence-loader">Decrypting Strategic Outlook...</div>`;

    try {
        const data: ExpertIntelligence = await fetchExpertIntelligence();

        // 2. Build Expert-grade Layout
        container.innerHTML = `
        <div class="insights-dashboard expert-dashboard">
            <!-- BLUF: Scenario Outlooks -->
            <div class="expert-main-grid">
                <!-- Column 1: Scenarios & Actions (Decision Center) -->
                <div class="decision-center">
                    <h2 class="section-title">Strategic Outlook</h2>
                    ${data.scenario_outlook.map(s => `
                        <div class="scenario-card">
                            <div class="u-flex-between u-m-bottom-s">
                                <h3 class="scenario-title">${s.title}</h3>
                                ${renderPriorityBadge(s.priority)}
                            </div>
                            
                            ${s.why_now ? `
                                <div class="strategic-briefing">
                                    <div class="briefing-label">WHY NOW</div>
                                    <div class="briefing-content">${s.why_now}</div>
                                </div>
                            ` : ''}

                            <div class="scenario-description">${s.scenario_outlook}</div>
                            
                            <div class="action-list">
                                <div class="action-list-header u-flex-between">
                                    <span>Recommended Actions</span>
                                    ${s.time_sensitivity ? `
                                        <div class="sensitivity-pill sensitivity-pill--${s.time_sensitivity.toLowerCase().replace(' ', '-')}">
                                            ${s.time_sensitivity}
                                        </div>
                                    ` : ''}
                                </div>
                                ${s.recommended_actions.map(a => `
                                    <div class="action-item ${a.priority.toLowerCase()}">
                                        <div class="u-flex-between">
                                            <span>${a.action}</span>
                                            <div style="flex-shrink:0; display:flex; align-items:center;">
                                                ${renderPriorityBadge(a.priority, true)}
                                                ${renderCategoryBadge(a.category)}
                                            </div>
                                        </li>
                                    `).join('')}
                                </ul>
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>

            <div class="dashboard-grid">
                <!-- Causal Impact Chains -->
                ${renderCard('Active Causal Chains', `
                    <div class="impact-chain-preview-list">
                        ${data.full_impact_chains.map(chain => `
                            <div class="impact-chain-item" data-alert-id="${chain.alert_id}">
                                <div class="impact-chain-header">
                                    <span class="chain-title">${chain.title}</span>
                                    <span class="chain-count">${chain.impacts.length} nodes</span>
                                </div>
                                <div class="impact-chain-visual">
                                    ${chain.impacts.slice(0, 5).map(i => `
                                        <div class="impact-node-dot" title="${i.entity_name}" style="background: ${getTopicDef(i.topic || null).color}"></div>
                                    `).join('')}
                                    ${chain.impacts.length > 5 ? '<span class="chain-more">+</span>' : ''}
                                </div>
                            </div>
                        `).join('')}
                    </div>
                `, 'Full recursive analysis of ripples across domains')}

                <!-- Cross-Domain Risks -->
                ${renderCard('Strategic Correlation', `
                    <div class="cross-domain-list">
                        ${data.cross_domain_risks.map(r => `
                            <div class="cross-domain-item">
                                <div class="domain-pair">
                                    <span>${getTopicDef(r.origin).label}</span>
                                    <span class="domain-arrow">→</span>
                                    <span>${r.target}</span>
                                </div>
                                ${renderIntensityBar(r.intensity, 'Interaction Strength', '#bc8cff')}
                            </div>
                        `).join('')}
                    </div>
                `, 'Systemic risks bridging primary and tertiary sectors')}
            </div>
        </div>`;

    } catch (err) {
        container.innerHTML = `<div class="error-slate">Failed to load Expert Intelligence: ${err}</div>`;
    }
}
