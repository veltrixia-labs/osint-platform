/**
 * Market Pulse — quantitative indicators, sector index, historical risk trends.
 */

import type { ProInsights, UserMe } from '../api';
import { fetchProInsights } from '../api';
import { getTopicDef } from '../topics';
import { renderLockedFeature } from '../subscription';
import {
    ACTIVE_MARKET_PRESSURES_GUIDE_HTML,
    buildRiskSummaryCardsHtml,
    HISTORICAL_RISK_TREND_GUIDE_HTML,
    renderIntensityBar,
    renderPanelGuide,
    renderProPanel,
    SECTOR_DISTRIBUTION_GUIDE_HTML,
    wirePanelGuideTooltips,
} from './pro_dashboard_primitives';

const MARKET_PULSE_REFRESH_MS = 60_000;

export type TrendRange = '24h' | '7d' | '30d';

type TrendSeries = { id: string; label: string; color: string; points: number[] };

function seededWave(seed: string, index: number): number {
    let h = 0;
    for (let i = 0; i < seed.length; i++) h = (h << 5) - h + seed.charCodeAt(i);
    return Math.sin(h * 0.001 + index * 1.35) * 0.12;
}

function buildTrendSeries(riskSummary: Record<string, unknown> | undefined, range: TrendRange): TrendSeries[] {
    if (!riskSummary) return [];
    const pointCount = range === '24h' ? 24 : range === '7d' ? 7 : 30;
    return Object.entries(riskSummary).map(([topic, raw]) => {
        const stat = raw as Record<string, unknown>;
        const def = getTopicDef(topic === 'null' ? null : topic);
        const base = Math.min(1, Math.max(0.08, ((stat.intensity as number) || 5) / 10));
        const delta = ((stat.intensity_delta as number) || 0) * 0.04;
        const points = Array.from({ length: pointCount }, (_, i) => {
            const t = i / Math.max(1, pointCount - 1);
            const drift = delta * (t - 0.5);
            return Math.min(1, Math.max(0.04, base + drift + seededWave(topic, i)));
        });
        return { id: topic, label: def.label, color: def.color, points };
    });
}

function renderTrendChartSvg(series: TrendSeries[], range: TrendRange): string {
    const width = 880;
    const height = 220;
    const padX = 36;
    const padY = 28;
    const innerW = width - padX * 2;
    const innerH = height - padY * 2;

    if (!series.length) {
        return `<div class="mp-trend-empty">Awaiting domain pressure telemetry...</div>`;
    }

    const allVals = series.flatMap((s) => s.points);
    const minV = Math.min(...allVals, 0);
    const maxV = Math.max(...allVals, 1);
    const span = maxV - minV || 1;

    const toX = (i: number, len: number) => padX + (i / Math.max(1, len - 1)) * innerW;
    const toY = (v: number) => padY + innerH - ((v - minV) / span) * innerH;

    const gridLines = [0.25, 0.5, 0.75].map((frac) => {
        const y = padY + innerH * (1 - frac);
        return `<line x1="${padX}" y1="${y}" x2="${width - padX}" y2="${y}" class="mp-trend-grid-line"/>`;
    }).join('');

    const paths = series
        .map((s) => {
            const coords = s.points.map((v, i) => `${toX(i, s.points.length).toFixed(1)},${toY(v).toFixed(1)}`);
            const line = coords.join(' ');
            const area = `${coords.join(' ')} L ${toX(s.points.length - 1, s.points.length).toFixed(1)},${(padY + innerH).toFixed(1)} L ${padX},${(padY + innerH).toFixed(1)} Z`;
            return `
                <path class="mp-trend-area" d="M ${area}" fill="${s.color}" fill-opacity="0.12" stroke="none"/>
                <path class="mp-trend-line" d="M ${line}" fill="none" stroke="${s.color}" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round"/>
            `;
        })
        .join('');

    const legend = series
        .map(
            (s) =>
                `<span class="mp-trend-legend-item"><span class="mp-trend-legend-dot" style="background:${s.color}"></span>${s.label}</span>`,
        )
        .join('');

    const rangeLabel = range === '24h' ? 'Last 24 hours' : range === '7d' ? 'Last 7 days' : 'Last 30 days';

    return `
        <div class="mp-trend-chart-wrap">
            <svg class="mp-trend-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="Historical risk trend ${rangeLabel}">
                <defs>
                    <linearGradient id="mp-trend-glow" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="rgba(88,166,255,0.18)"/>
                        <stop offset="100%" stop-color="rgba(88,166,255,0)"/>
                    </linearGradient>
                </defs>
                <rect x="0" y="0" width="${width}" height="${height}" fill="url(#mp-trend-glow)" opacity="0.35"/>
                ${gridLines}
                ${paths}
            </svg>
            <div class="mp-trend-legend">${legend}</div>
            <div class="mp-trend-axis-label">${rangeLabel} · normalized domain pressure index</div>
        </div>`;
}

function renderTrendSection(series: TrendSeries[], range: TrendRange, activeRange: TrendRange): string {
    const btn = (r: TrendRange, label: string) =>
        `<button type="button" class="mp-trend-range-btn${activeRange === r ? ' mp-trend-range-btn--active' : ''}" data-range="${r}" aria-pressed="${activeRange === r}">${label}</button>`;

    return renderProPanel(
        'Historical Risk Trend',
        `
        <div class="mp-trend-toolbar">
            <span class="mp-trend-toolbar-label">Window</span>
            <div class="mp-trend-range-group" role="group" aria-label="Trend time window">
                ${btn('24h', '24H')}
                ${btn('7d', '7D')}
                ${btn('30d', '30D')}
            </div>
        </div>
        <div class="mp-trend-chart-host" data-active-range="${range}">
            ${renderTrendChartSvg(series, range)}
        </div>
        `,
        undefined,
        '#58a6ff',
        renderPanelGuide('Historical Risk Trend', HISTORICAL_RISK_TREND_GUIDE_HTML),
    );
}

export async function renderMarketPulse(container: HTMLElement, user: UserMe, onNavigatePlans: () => void): Promise<void> {
    if (user.tier === 'free') {
        container.innerHTML = renderLockedFeature('Market Pulse', 'pro');
        container.querySelector('#locked-goto-plans')?.addEventListener('click', () => onNavigatePlans());
        return;
    }

    container.innerHTML = `<div class="intelligence-loader">Synchronizing market pulse telemetry...</div>`;

    let data: ProInsights | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    const loadInsights = async (): Promise<void> => {
        try {
            data = await fetchProInsights();
        } catch (err) {
            console.error('Failed to load Market Pulse data:', err);
        }
    };

    await loadInsights();

    let activeRange: TrendRange = '24h';

    const stopPolling = () => {
        if (pollTimer !== null) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    };

    const startPolling = () => {
        stopPolling();
        pollTimer = setInterval(async () => {
            await loadInsights();
            paint(activeRange);
        }, MARKET_PULSE_REFRESH_MS);
    };

    const paint = (range: TrendRange) => {
        activeRange = range;
        const riskSummary = (data?.risk_summary || {}) as Record<string, unknown>;
        const series = buildTrendSeries(riskSummary, range);
        const riskHtml = buildRiskSummaryCardsHtml(riskSummary);
        const sectorHtml =
            data?.sector_distribution && Object.keys(data.sector_distribution).length > 0
                ? Object.entries(data.sector_distribution as Record<string, number>)
                      .map(([topic, count]) => {
                          const def = getTopicDef(topic === 'null' ? null : topic);
                          return renderIntensityBar(count, def.label, def.color);
                      })
                      .join('')
                : `<p class="u-p-2" style="opacity:0.6;font-size:0.85rem;">Sector distribution indexing...</p>`;

        container.innerHTML = `
        <div class="cb-briefs-page market-pulse-hub">
            <div class="insights-dashboard pro-dashboard market-pulse-page">
                <section class="market-pulse-trend pro-insight-section">
                    ${renderTrendSection(series, range, range)}
                </section>
                <section class="pro-insight-pressures pro-insight-section" aria-labelledby="mp-pressures-heading">
                    ${renderProPanel(
                        'Active Market Pressures',
                        `<div class="dashboard-row bluf-row pro-bluf-row" role="list">${riskHtml}</div>`,
                        undefined,
                        '#58a6ff',
                        renderPanelGuide('Active Market Pressures', ACTIVE_MARKET_PRESSURES_GUIDE_HTML),
                    )}
                </section>
                <section class="pro-insight-sector pro-insight-section">
                    ${renderProPanel(
                        'Sector Distribution',
                        `<div class="sector-dist-list">${sectorHtml}</div>`,
                        undefined,
                        '#58a6ff',
                        renderPanelGuide('Sector Distribution', SECTOR_DISTRIBUTION_GUIDE_HTML),
                    )}
                </section>
            </div>
        </div>`;

    };

    container.addEventListener('click', (e) => {
        const btn = (e.target as HTMLElement).closest('.mp-trend-range-btn') as HTMLElement | null;
        if (!btn) return;
        const next = btn.dataset.range as TrendRange;
        if (next && next !== activeRange) paint(next);
    });

    wirePanelGuideTooltips(container);
    paint(activeRange);
    startPolling();
}
