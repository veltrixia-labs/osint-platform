/**
 * Market Pulse — quantitative indicators, sector index, historical risk trends.
 */

import type { ProInsights, UserMe } from '../api';
import { fetchProInsights } from '../api';
import { getTopicDef } from '../topics';
import { isAuthSessionPending } from '../auth_session';
import { renderLockedFeature } from '../subscription';
import {
    ACTIVE_MARKET_PRESSURES_GUIDE_HTML,
    buildRiskSummaryCardsHtml,
    HISTORICAL_RISK_TREND_GUIDE_HTML,
    renderIntensityBar,
    renderPanelGuide,
    renderProPanel,
    SECTOR_DISTRIBUTION_GUIDE_HTML,
} from './pro_dashboard_primitives';

const MARKET_PULSE_REFRESH_MS = 60_000;

let marketPulseSession = 0;
let marketPulsePollTimer: ReturnType<typeof setInterval> | null = null;
let marketPulseActiveRange: TrendRange = '24h';
let marketPulseRepaint: ((range: TrendRange) => void) | null = null;

/** Stop background refresh so other tabs are not overwritten. */
export function disposeMarketPulseView(): void {
    marketPulseSession += 1;
    marketPulseRepaint = null;
    if (marketPulsePollTimer !== null) {
        clearInterval(marketPulsePollTimer);
        marketPulsePollTimer = null;
    }
}

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

/** Normalized domain pressure index scale (0.0–1.0). */
const TREND_Y_MIN = 0;
const TREND_Y_MAX = 1;
const TREND_Y_TICKS = [0, 0.25, 0.5, 0.75, 1];

function renderTrendChartSvg(series: TrendSeries[], range: TrendRange): string {
    const width = 880;
    const height = 220;
    const padLeft = 44;
    const padRight = 28;
    const padY = 28;
    const plotX = padLeft;
    const innerW = width - padLeft - padRight;
    const innerH = height - padY * 2;

    if (!series.length) {
        return `<div class="mp-trend-empty">Awaiting domain pressure telemetry...</div>`;
    }

    const toX = (i: number, len: number) => plotX + (i / Math.max(1, len - 1)) * innerW;
    const toY = (v: number) => {
        const clamped = Math.min(TREND_Y_MAX, Math.max(TREND_Y_MIN, v));
        return padY + innerH - ((clamped - TREND_Y_MIN) / (TREND_Y_MAX - TREND_Y_MIN)) * innerH;
    };

    const yAxis = TREND_Y_TICKS.map((tick) => {
        const y = toY(tick);
        const label = tick.toFixed(1);
        return `
            <line x1="${padLeft - 5}" y1="${y.toFixed(1)}" x2="${padLeft}" y2="${y.toFixed(1)}" class="mp-trend-axis-tick"/>
            <text x="${padLeft - 8}" y="${(y + 3.5).toFixed(1)}" text-anchor="end" class="mp-trend-y-label">${label}</text>
            <line x1="${padLeft}" y1="${y.toFixed(1)}" x2="${width - padRight}" y2="${y.toFixed(1)}" class="mp-trend-grid-line"/>
        `;
    }).join('');

    const paths = series
        .map((s) => {
            const coords = s.points.map((v, i) => `${toX(i, s.points.length).toFixed(1)},${toY(v).toFixed(1)}`);
            const line = coords.join(' ');
            const area = `${coords.join(' ')} L ${toX(s.points.length - 1, s.points.length).toFixed(1)},${(padY + innerH).toFixed(1)} L ${plotX},${(padY + innerH).toFixed(1)} Z`;
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
                <line x1="${padLeft}" y1="${padY}" x2="${padLeft}" y2="${padY + innerH}" class="mp-trend-y-axis"/>
                ${yAxis}
                ${paths}
            </svg>
            <div class="mp-trend-legend">${legend}</div>
            <div class="mp-trend-axis-label">${rangeLabel} · Y-axis: normalized index (0.0–1.0)</div>
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
    disposeMarketPulseView();
    const sessionId = marketPulseSession;

    if (isAuthSessionPending()) {
        container.innerHTML = `<div class="intelligence-loader">Validating session…</div>`;
        return;
    }

    if (user.tier === 'free') {
        container.innerHTML = renderLockedFeature('Market Pulse', 'pro');
        container.querySelector('#locked-goto-plans')?.addEventListener('click', () => onNavigatePlans());
        return;
    }

    container.dataset.dashboardView = 'market-pulse';
    container.innerHTML = `<div class="intelligence-loader">Synchronizing market pulse telemetry...</div>`;

    let data: ProInsights | null = null;

    const loadInsights = async (): Promise<void> => {
        if (sessionId !== marketPulseSession) return;
        try {
            data = await fetchProInsights();
        } catch (err) {
            console.error('Failed to load Market Pulse data:', err);
        }
    };

    await loadInsights();
    if (sessionId !== marketPulseSession) return;

    let activeRange: TrendRange = '24h';

    const paint = (range: TrendRange) => {
        if (sessionId !== marketPulseSession) return;
        if (container.dataset.dashboardView !== 'market-pulse') return;
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
                        `<div class="dashboard-row bluf-row pro-bluf-row pro-bluf-row--mp-six" role="list">${riskHtml}</div>`,
                        undefined,
                        '#58a6ff',
                        renderPanelGuide(
                            'Active Market Pressures',
                            ACTIVE_MARKET_PRESSURES_GUIDE_HTML,
                            'above',
                        ),
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

    marketPulseActiveRange = activeRange;
    marketPulseRepaint = paint;

    if (container.dataset.mpTrendClickBound !== '1') {
        container.dataset.mpTrendClickBound = '1';
        container.addEventListener('click', (e) => {
            if (container.dataset.dashboardView !== 'market-pulse') return;
            const btn = (e.target as HTMLElement).closest('.mp-trend-range-btn') as HTMLElement | null;
            if (!btn) return;
            const next = btn.dataset.range as TrendRange;
            if (next && marketPulseRepaint && next !== marketPulseActiveRange) {
                marketPulseActiveRange = next;
                marketPulseRepaint(next);
            }
        });
    }

    paint(activeRange);

    marketPulsePollTimer = setInterval(async () => {
        if (sessionId !== marketPulseSession) return;
        if (container.dataset.dashboardView !== 'market-pulse') return;
        await loadInsights();
        paint(activeRange);
    }, MARKET_PULSE_REFRESH_MS);
}
