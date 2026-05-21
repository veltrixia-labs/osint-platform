/**
 * Shared Pro dashboard UI primitives (Market Pulse + Pro Insights + Expert).
 */

import { getTopicDef } from '../topics';

/** Glass panel wrapper (Sector Distribution chrome). */
export function renderProPanel(title: string, content: string, footer?: string, accentColor = '#58a6ff'): string {
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
        })
        .join('');
}
