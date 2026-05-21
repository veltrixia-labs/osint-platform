/**
 * insights.ts
 * Premium Intelligence Dashboards
 * 
 * Responsibilities:
 * - renderProInsights: Decision-grade briefing grid
 * - renderExpertIntel: Strategic-grade causal mapping & scenarios
 * - Pure CSS/SVG components for "Speed of Judgment"
 */

import type { ProInsights, UserMe } from '../api';
import type { ExpertIntelligence } from '../api';
import { fetchProInsights, fetchExpertIntelligence } from '../api';
import {
    getTopicDef,
    getTopicCssVars,
    getTopicDisplayLabel,
    normalizeTopicCode,
    UI_TOPIC_PREVIEW_CODES,
    type StrategicTopicCode,
} from '../topics';
import { renderLockedFeature } from '../subscription';
import { renderProStructuralBriefs, renderProStructuralBriefDetail } from './pro_reports';
// ──────────────────────────────────────────────────────────────────────────────
// Component Primitives (Pure CSS / SVG)
// ──────────────────────────────────────────────────────────────────────────────

/** Renders a "Dashboard Card" wrapper */
function renderCard(title: string, content: string, footer?: string, accentColor = '#58a6ff'): string {
    return `
    <div class="insight-card pro-insight-panel" style="--accent: ${accentColor}">
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
    if (user.tier === 'free') {
        container.innerHTML = renderLockedFeature('Pro Insights Dashboard', 'pro');
        const btn = container.querySelector('#locked-goto-plans');
        btn?.addEventListener('click', () => onNavigatePlans());
        return;
    }

    container.innerHTML = `<div class="intelligence-loader">Initializing Pro Suite...</div>`;

    let selectedDomain: StrategicTopicCode | null = null;

    const renderDomainFilterButtons = (): string => {
        const allActive = selectedDomain === null;
        const allBtn = `<button type="button" class="domain-chip pro-domain-filter-btn pro-domain-filter-btn--all${allActive ? ' pro-domain-filter-btn--active' : ''}" data-domain="" aria-pressed="${allActive ? 'true' : 'false'}">All</button>`;
        const domainBtns = UI_TOPIC_PREVIEW_CODES.map((code) => {
            const norm = normalizeTopicCode(code);
            const active = selectedDomain === norm;
            return `<button type="button" class="domain-chip pro-domain-filter-btn meta-item-topic--tag${active ? ' pro-domain-filter-btn--active' : ''}" data-domain="${code}" style="${getTopicCssVars(code)}" aria-pressed="${active ? 'true' : 'false'}">${getTopicDisplayLabel(code)}</button>`;
        }).join('');
        return allBtn + domainBtns;
    };

    const updateDomainFilterUi = (root: HTMLElement) => {
        const bar = root.querySelector('.pro-domain-filter-bar');
        if (bar) {
            bar.innerHTML = renderDomainFilterButtons();
        }
    };

    let domainFilterDelegationBound = false;
    const ensureDomainFilterDelegation = (root: HTMLElement, onSelectBrief: (id: string) => void) => {
        if (domainFilterDelegationBound) return;
        domainFilterDelegationBound = true;
        root.addEventListener('click', async (e) => {
            const btn = (e.target as HTMLElement).closest<HTMLButtonElement>('.pro-domain-filter-btn');
            if (!btn || !root.contains(btn)) return;
            const code = btn.dataset.domain ?? '';
            if (code === '') {
                selectedDomain = null;
            } else {
                selectedDomain = normalizeTopicCode(code);
            }
            updateDomainFilterUi(root);
            const briefsContainer = root.querySelector(
                '#pro-hub-structural-briefs-container',
            ) as HTMLElement | null;
            if (briefsContainer) {
                await renderProStructuralBriefs(briefsContainer, onSelectBrief, selectedDomain);
            }
        });
    };

    // Internal navigation handler for switching between Hub and Detail view
    const showHub = async () => {
        let data: ProInsights | null = null;
        try {
            data = await fetchProInsights();
        } catch (err) {
            console.error("Failed to load Pro Insights data:", err);
        }

        // Log automation state for devs only
        console.debug('[ProInsights] Automation state: dry_run=true');

        const riskSummaryHtml = data && data.risk_summary && Object.keys(data.risk_summary).length > 0
            ? Object.entries((data.risk_summary || {}) as any).map(([topic, stat]: [string, any]) => {
                const def = getTopicDef(topic === 'null' ? null : topic);
                return `
                <div class="bluf-stat-card bluf-stat-card--compact" style="--accent: ${def.color}">
                    <div class="bluf-header u-flex-between">
                        <div class="bluf-topic">${def.icon} ${def.label}</div>
                        <div class="bluf-trend bluf-trend--${stat.trend}">${stat.trend === 'rising' ? '▲' : '■'}</div>
                    </div>
                    <div class="u-flex u-flex-baseline">
                        <div class="bluf-value">${(stat.intensity || 0).toFixed(1)}</div>
                        ${stat.intensity_delta !== undefined ? `
                            <div class="bluf-delta ${stat.intensity_delta > 0.5 ? 'rising' : stat.intensity_delta < -0.5 ? 'falling' : ''}" style="margin-left: 8px; font-size: 0.75rem; font-weight: 800;">
                                ${stat.intensity_delta > 0 ? '↑' : stat.intensity_delta < 0 ? '↓' : ''} ${Math.abs(stat.intensity_delta).toFixed(1)} <span style="font-weight:400; opacity:0.6;">(24h)</span>
                            </div>
                        ` : ''}
                        ${stat.spike_detected ? `<div class="spike-badge" title="UNUSUAL MOMENTUM DETECTED">SPIKE</div>` : ''}
                    </div>
                    <div class="bluf-label">${stat.why_it_matters || ''}</div>
                    ${stat.anomaly_detected ? `<div class="anomaly-warning-pill">⚠️ ANOMALY DETECTED</div>` : ''}
                    <div class="bluf-latest-wrap">
                        <span class="bluf-latest-label">TOP SIGNAL</span>
                        <div class="bluf-latest">${stat.top_signal || 'None'}</div>
                    </div>
                </div>`;
            }).join('')
            : `<div class="u-p-2 u-text-center" style="grid-column: 1/-1; opacity:0.6; font-size: 0.9rem;">Intelligence gathering in progress...</div>`;

        const sectorDistributionHtml =
            data && data.sector_distribution
                ? `
            <section class="pro-insight-sector pro-insight-section">
                ${renderCard(
                    'Sector Distribution',
                    `
                    <div class="sector-dist-list">
                        ${Object.entries((data.sector_distribution || {}) as any)
                            .map(([topic, count]: [string, any]) => {
                                const def = getTopicDef(topic === 'null' ? null : topic);
                                return renderIntensityBar(count, def.label, def.color);
                            })
                            .join('')}
                    </div>
                `,
                )}
            </section>`
                : '';

        const pressuresPanel = renderCard(
            'Active Market Pressures',
            `<div class="dashboard-row bluf-row pro-bluf-row" role="list">${riskSummaryHtml}</div>`,
        );

        const monitoredDomainsPanel = renderCard(
            'Monitored Domains',
            `<div class="domain-chips-container pro-domain-filter-bar" role="group" aria-label="Filter structural briefs by domain">${renderDomainFilterButtons()}</div>`,
        );

        container.innerHTML = `
        <div class="cb-briefs-page pro-insight-hub">
        <div class="insights-dashboard pro-dashboard pro-insight-page">
            <section class="pro-insight-pressures pro-insight-section" aria-labelledby="pro-pressures-heading">
                ${pressuresPanel}
            </section>

            ${sectorDistributionHtml}

            <section class="pro-insight-filters pro-insight-section" aria-label="Monitored Domains">
                ${monitoredDomainsPanel}
            </section>

            <section id="pro-hub-structural-briefs-container" class="pro-insight-briefs pro-insight-section" aria-label="Latest Structural Briefs">
                <!-- Injected via renderProStructuralBriefs -->
            </section>
        </div>
        </div>`;

        const onSelectBrief = (id: string) => {
            renderProStructuralBriefDetail(id, container, () => {
                showHub();
            });
        };

        ensureDomainFilterDelegation(container, onSelectBrief);

        const briefsContainer = container.querySelector(
            '#pro-hub-structural-briefs-container',
        ) as HTMLElement;
        if (briefsContainer) {
            await renderProStructuralBriefs(briefsContainer, onSelectBrief, selectedDomain);
        }
    };

    // Initialize hub
    await showHub();
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
        const data: ExpertIntelligence | null = await fetchExpertIntelligence();
        if (!data) {
            container.innerHTML = `
                <div class="empty-state u-p-2 u-text-center">
                    <div class="empty-title">Expert intelligence unavailable</div>
                    <div class="empty-subtitle">Could not load strategic outlook. Confirm API access and tier.</div>
                </div>`;
            return;
        }

        const scenarios = (data.scenario_outlook as any[]) ?? [];
        const impactChains = (data.full_impact_chains as any[]) ?? [];
        const crossRisks = (data.cross_domain_risks as any[]) ?? [];

        // 2. Build Expert-grade Layout
        container.innerHTML = `
        <div class="insights-dashboard expert-dashboard">
            <!-- BLUF: Scenario Outlooks -->
            <div class="expert-main-grid">
                <!-- Column 1: Scenarios & Actions (Decision Center) -->
                <div class="decision-center">
                    <h2 class="section-title">Strategic Outlook</h2>
                    ${scenarios.length ? scenarios.map((s: any) => `
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
                                ${(s.recommended_actions as any[]).map((a: any) => `
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
                `).join('') : '<p class="u-p-2" style="opacity:0.6;">No scenario outlook in the current window.</p>'}
            </div>

            <div class="dashboard-grid">
                <!-- Causal Impact Chains -->
                ${renderCard('Active Causal Chains', `
                    <div class="impact-chain-preview-list">
                        ${impactChains.length ? impactChains.map((chain: any) => `
                            <div class="impact-chain-item" data-alert-id="${chain.alert_id}">
                                <div class="impact-chain-header">
                                    <span class="chain-title">${chain.title}</span>
                                    <span class="chain-count">${chain.impacts.length} nodes</span>
                                </div>
                                <div class="impact-chain-visual">
                                    ${(chain.impacts as any[]).slice(0, 5).map((i: any) => `
                                        <div class="impact-node-dot" title="${i.entity_name}" style="background: ${getTopicDef(i.topic || null).color}"></div>
                                    `).join('')}
                                    ${chain.impacts.length > 5 ? '<span class="chain-more">+</span>' : ''}
                                </div>
                            </div>
                        `).join('') : '<p style="opacity:0.6;font-size:0.85rem;">No impact chains with gated metadata yet.</p>'}
                    </div>
                `, 'Full recursive analysis of ripples across domains')}

                <!-- Cross-Domain Risks -->
                ${renderCard('Strategic Correlation', `
                    <div class="cross-domain-list">
                        ${crossRisks.length ? crossRisks.map((r: any) => `
                            <div class="cross-domain-item">
                                <div class="domain-pair">
                                    <span>${getTopicDef(r.origin).label}</span>
                                    <span class="domain-arrow">→</span>
                                    <span>${r.target}</span>
                                </div>
                                ${renderIntensityBar(r.intensity, 'Interaction Strength', '#bc8cff')}
                            </div>
                        `).join('') : '<p style="opacity:0.6;font-size:0.85rem;">No cross-domain correlations in the current window.</p>'}
                    </div>
                `, 'Systemic risks bridging primary and tertiary sectors')}
            </div>
        </div>`;

    } catch (err) {
        container.innerHTML = `<div class="error-slate">Failed to load Expert Intelligence: ${err}</div>`;
    }
}
