/**
 * Shared Pro dashboard UI primitives (Market Pulse + Pro Insights + Expert).
 */

import { getTopicDef } from '../topics';

export const SECTOR_DISTRIBUTION_GUIDE_HTML = `
<p class="intel-guide-title"><strong>Sector Distribution Guide</strong></p>
<ul class="intel-guide-list">
<li><strong>Intelligence Volume Index:</strong> Represents the total cumulative data points, active alerts, and structured contextual inputs currently ingested within each specific domain.</li>
<li><strong>Operational Utility:</strong> This bar ratio visualizes VELTRIXIA&rsquo;s cognitive focus. A sudden spike or extension in a specific sector&rsquo;s bar reflects a heavy influx of real-time signals, indicating an escalating operational friction or high-density risk event in that market vertical.</li>
</ul>`;

export const HISTORICAL_RISK_TREND_GUIDE_HTML = `
<p class="intel-guide-title"><strong>Historical Risk Trend</strong></p>
<p class="intel-guide-body">A chronological visualization of normalized domain pressure indexes across key sectors over the past 24 hours, 7 days, or 30 days. This chart allows for comparative analysis of relative risk volatility and trend waveforms.</p>`;

export const ACTIVE_MARKET_PRESSURES_GUIDE_HTML = `
<p class="intel-guide-title"><strong>Active Market Pressures</strong></p>
<p class="intel-guide-body">A real-time dashboard aggregating and quantifying sudden volatility, anomaly detection, and incoming signal intensity for each targeted sector.</p>`;

function effectiveRiskIntensity(stat: Record<string, unknown>): number {
    const ui = Number(stat.intensity);
    if (Number.isFinite(ui) && ui > 0) return ui;
    const score = Number(stat.intelligence_score);
    if (Number.isFinite(score) && score > 0) return score * 10;
    return 0;
}

function formatPressureIndex(stat: Record<string, unknown>): string {
    const v = effectiveRiskIntensity(stat);
    return v >= 9.5 ? v.toFixed(2) : v.toFixed(1);
}

function renderPressureBadge(stat: Record<string, unknown>): string {
    const variant = String(stat.pressure_badge_variant || '');
    const label = String(stat.pressure_badge_label || '');
    if (variant && label) {
        const cls =
            variant === 'sustained'
                ? 'pressure-badge pressure-badge--sustained'
                : 'pressure-badge pressure-badge--anomaly';
        const prefix = variant === 'anomaly' ? '⚠️ ' : '';
        return `<div class="${cls}" role="status">${prefix}${escHtml(label)}</div>`;
    }
    if (stat.anomaly_detected) {
        return `<div class="pressure-badge pressure-badge--anomaly" role="status">⚠️ ANOMALY DETECTED</div>`;
    }
    return '';
}

export function escHtml(s: string): string {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

export function escAttr(s: string): string {
    return escHtml(s).replace(/'/g, '&#39;');
}

/** ℹ️ guide control — shared glassmorphism popover (inline next to panel titles). */
export function renderPanelGuide(ariaLabel: string, guideInnerHtml: string): string {
    return `<span class="intel-section-guide-wrap intel-section-guide-wrap--inline">
            <button type="button" class="intel-section-guide" aria-label="About ${escAttr(ariaLabel)}">
                <span class="intel-section-guide-icon" aria-hidden="true">ℹ</span>
            </button>
            <span class="intel-section-guide-popover intel-section-guide-popover--rich" role="tooltip">${guideInnerHtml}</span>
           </span>`;
}

/** Panel guides use pure CSS hover on `.intel-section-guide-wrap` (no JS required). */
export function wirePanelGuideTooltips(_root: HTMLElement): void {
    /* intentionally empty — hover tooltips are CSS-driven */
}

/** Glass panel wrapper (Sector Distribution chrome). */
export function renderProPanel(
    title: string,
    content: string,
    footer?: string,
    accentColor = '#58a6ff',
    guideHtml?: string,
): string {
    const headerClass = guideHtml
        ? 'insight-card-header insight-card-header--with-guide'
        : 'insight-card-header';
    return `
    <div class="insight-card pro-insight-panel" style="--accent: ${accentColor}">
        <div class="${headerClass}">
            <h3 class="insight-card-title">${title}</h3>
            ${guideHtml || ''}
        </div>
        <div class="insight-card-body">
            ${content}
        </div>
        ${footer ? `<div class="insight-card-footer">${footer}</div>` : ''}
    </div>`;
}

export function renderIntensityBar(value: number, label: string, color = '#58a6ff'): string {
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

export function buildRiskSummaryCardsHtml(riskSummary: Record<string, unknown> | undefined): string {
    if (!riskSummary || Object.keys(riskSummary).length === 0) {
        return `<div class="u-p-2 u-text-center" style="grid-column: 1/-1; opacity:0.6; font-size: 0.9rem;">Intelligence gathering in progress...</div>`;
    }
    return Object.entries(riskSummary)
        .map(([topic, stat]: [string, any]) => {
            const def = getTopicDef(topic === 'null' ? null : topic);
            return `
                <div class="bluf-stat-card bluf-stat-card--compact" style="--accent: ${def.color}">
                    <div class="bluf-header u-flex-between">
                        <div class="bluf-topic">${def.icon} ${def.label}</div>
                        <div class="bluf-trend bluf-trend--${stat.trend}">${stat.trend === 'rising' ? '▲' : '■'}</div>
                    </div>
                    <div class="u-flex u-flex-baseline">
                        <div class="bluf-value">${formatPressureIndex(stat)}</div>
                        ${stat.intensity_delta !== undefined ? `
                            <div class="bluf-delta ${stat.intensity_delta > 0.5 ? 'rising' : stat.intensity_delta < -0.5 ? 'falling' : ''}" style="margin-left: 8px; font-size: 0.75rem; font-weight: 800;">
                                ${stat.intensity_delta > 0 ? '↑' : stat.intensity_delta < 0 ? '↓' : ''} ${Math.abs(stat.intensity_delta).toFixed(1)} <span style="font-weight:400; opacity:0.6;">(24h)</span>
                            </div>
                        ` : ''}
                        ${stat.spike_detected ? `<div class="spike-badge" title="UNUSUAL MOMENTUM DETECTED">SPIKE</div>` : ''}
                    </div>
                    <div class="bluf-label">${stat.why_it_matters || ''}</div>
                    ${renderPressureBadge(stat)}
                    <div class="bluf-latest-wrap">
                        <span class="bluf-latest-label">TOP SIGNAL</span>
                        <div class="bluf-latest">${stat.top_signal || 'None'}</div>
                    </div>
                </div>`;
        })
        .join('');
}
