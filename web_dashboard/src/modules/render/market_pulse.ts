/**
 * Market Pulse — quantitative indicators, sector index, historical risk trends.
 */

import type { MacroRegime, ProInsights, UserMe } from '../api';
import { fetchMacroRegime, fetchProInsights } from '../api';
import { isAuthSessionPending } from '../auth_session';
import { renderLockedFeature } from '../subscription';
import { DEV_MODE_AUDIT } from '../dev_mode';
import {
    LEAD_LAG_GUIDE_HTML,
    renderPanelGuide,
    renderProPanel,
} from './pro_dashboard_primitives';
import { RadialNetworkEngine } from './radial_network';

const REGIME_BANNER_STYLE_ID = 'market-pulse-regime-styles';
function injectRegimeBannerStyles(): void {
    if (typeof document === 'undefined' || document.getElementById(REGIME_BANNER_STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = REGIME_BANNER_STYLE_ID;
    style.textContent = `
        .market-regime-banner {
            position: relative;
            display: flex;
            align-items: center;
            gap: 14px;
            padding: 12px 18px;
            margin-bottom: 14px;
            border-radius: 14px;
            background: linear-gradient(135deg,
                color-mix(in srgb, var(--regime-accent, #38bdf8) 16%, rgba(15,23,42,0.55)),
                color-mix(in srgb, var(--regime-accent, #38bdf8) 6%, rgba(15,23,42,0.30)));
            border: 1px solid color-mix(in srgb, var(--regime-accent, #38bdf8) 55%, rgba(125,211,252,0.25));
            backdrop-filter: blur(18px) saturate(140%);
            -webkit-backdrop-filter: blur(18px) saturate(140%);
            box-shadow:
                0 8px 28px rgba(2,6,23,0.45),
                inset 0 0 0 1px rgba(255,255,255,0.04),
                0 0 24px var(--regime-glow, rgba(56,189,248,0.30));
            color: #e2e8f0;
            transition: border-color 0.30s ease, box-shadow 0.30s ease, background 0.30s ease;
            cursor: default;
        }
        .market-regime-banner .regime-emoji {
            font-size: 1.8rem;
            line-height: 1;
            filter: drop-shadow(0 0 8px var(--regime-glow, transparent));
        }
        .market-regime-banner .regime-text {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .market-regime-banner .regime-label {
            font-size: 0.82rem;
            font-weight: 800;
            color: var(--regime-accent, #e2e8f0);
            letter-spacing: 0.10em;
            text-transform: uppercase;
            text-shadow: 0 0 12px var(--regime-glow, transparent);
        }
        .market-regime-banner .regime-rationale {
            font-size: 0.74rem;
            color: #cbd5e1;
            line-height: 1.45;
        }
        .market-regime-banner .regime-components {
            margin-left: auto;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            font-size: 0.68rem;
            color: #94a3b8;
            font-variant-numeric: tabular-nums;
        }
        .market-regime-banner .regime-comp {
            padding: 4px 8px;
            border-radius: 6px;
            background: rgba(2,6,23,0.42);
            border: 1px solid rgba(148,163,184,0.18);
        }
        .market-regime-banner .regime-comp .k { color: #64748b; }
        .market-regime-banner .regime-comp .v.pos { color: #6ee7b7; }
        .market-regime-banner .regime-comp .v.neg { color: #fca5a5; }
        .market-regime-banner .regime-comp .v.flat { color: #cbd5e1; }
        .market-regime-banner.loading .regime-label { color: #94a3b8; }

        @media (max-width: 720px) {
            .market-regime-banner .regime-components { display: none; }
        }
    `;
    document.head.appendChild(style);
}

function renderRegimeBannerHtml(): string {
    return `
        <section class="pro-insight-regime" aria-label="Market Regime Indicator">
            <div id="market-regime-banner" class="market-regime-banner loading">
                <span class="regime-emoji">⏳</span>
                <div class="regime-text">
                    <span class="regime-label">Detecting regime…</span>
                    <span class="regime-rationale">Computing 30-day RoC across DGS10, DCOILWTICO, VIXCLS.</span>
                </div>
            </div>
        </section>
    `;
}

function fmtRoc(v: number | null | undefined): { txt: string; cls: string } {
    if (v == null || !Number.isFinite(v)) return { txt: 'n/a', cls: 'flat' };
    const sign = v > 0 ? '+' : '';
    const cls = v > 0.5 ? 'pos' : v < -0.5 ? 'neg' : 'flat';
    return { txt: `${sign}${v.toFixed(2)}%`, cls };
}

function applyRegimeToBanner(banner: HTMLElement, regime: MacroRegime | null): void {
    if (!regime) {
        banner.classList.add('loading');
        return;
    }
    banner.classList.remove('loading');
    banner.style.setProperty('--regime-accent', regime.accent_color);
    banner.style.setProperty('--regime-glow', regime.glow_color);
    const c = regime.components || {} as MacroRegime['components'];
    const rates = fmtRoc(c.rates_roc_pct);
    const oil = fmtRoc(c.oil_roc_pct);
    const vix = fmtRoc(c.vix_roc_pct);
    banner.innerHTML = `
        <span class="regime-emoji" aria-hidden="true">${regime.emoji}</span>
        <div class="regime-text">
            <span class="regime-label">${regime.label}</span>
            <span class="regime-rationale" title="${regime.rationale.replace(/"/g, '&quot;')}">
                ${regime.rationale}
            </span>
        </div>
        <div class="regime-components" aria-label="Component rates of change">
            <span class="regime-comp"><span class="k">Rates 30d</span> <span class="v ${rates.cls}">${rates.txt}</span></span>
            <span class="regime-comp"><span class="k">Oil 30d</span> <span class="v ${oil.cls}">${oil.txt}</span></span>
            <span class="regime-comp"><span class="k">VIX 30d</span> <span class="v ${vix.cls}">${vix.txt}</span></span>
        </div>
    `;
}

async function refreshRegimeBanner(container: HTMLElement): Promise<void> {
    const banner = container.querySelector<HTMLElement>('#market-regime-banner');
    if (!banner) return;
    const regime = await fetchMacroRegime();
    applyRegimeToBanner(banner, regime);
}

const MARKET_PULSE_REFRESH_MS = 60_000;

let marketPulseSession = 0;
let marketPulsePollTimer: ReturnType<typeof setInterval> | null = null;

/** Stop background refresh so other tabs are not overwritten. */
export function disposeMarketPulseView(): void {
    marketPulseSession += 1;
    if (marketPulsePollTimer !== null) {
        clearInterval(marketPulsePollTimer);
        marketPulsePollTimer = null;
    }
}


export async function renderMarketPulse(container: HTMLElement, user: UserMe, onNavigatePlans: () => void): Promise<void> {
    disposeMarketPulseView();
    const sessionId = marketPulseSession;

    if (isAuthSessionPending()) {
        container.innerHTML = `<div class="intelligence-loader">Validating session…</div>`;
        return;
    }

    // Dev Mode / Audit Build: bypass the locked-feature overlay so reviewers
    // see the full Market Pulse hub regardless of subscription tier.
    if (user.tier === 'free' && !DEV_MODE_AUDIT) {
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

    let shellRendered = false;

    const paint = () => {
        if (sessionId !== marketPulseSession) return;
        if (container.dataset.dashboardView !== 'market-pulse') return;
        const riskSummary = (data?.risk_summary || {}) as Record<string, unknown>;

        if (!shellRendered) {
            injectRegimeBannerStyles();
            container.innerHTML = `
        <div class="pro-hub-page market-pulse-hub">
            <div class="insights-dashboard pro-dashboard market-pulse-page">

                ${renderRegimeBannerHtml()}

                <!-- System Entropy Gauge (statistical mechanics) -->
                <section class="pro-insight-entropy pro-insight-section" aria-label="Market Entropy Gauge">
                    ${renderProPanel(
                        'Market Entropy Gauge',
                        '<div id="market-entropy-container" class="w-full"></div>',
                        undefined,
                        '#22d3ee',
                        renderPanelGuide('Market Entropy Gauge', '<p>Shannon entropy <code>S = -Σ pᵢ ln pᵢ</code> over the last 24h of alerts, combining topic dispersion (60%) and intensity dispersion (40%). Values above the engine threshold trigger a Breakout Warning state.</p>')
                    )}
                </section>

                <!-- Choke-Point Fluid-Dynamics Map -->
                <section class="pro-insight-chokepoints pro-insight-section" aria-label="Fluid-Dynamics Choke-Point Analyzer">
                    ${renderProPanel(
                        'Fluid-Dynamics Choke-Point Analyzer',
                        '<div id="choke-point-container" class="w-full"></div>',
                        undefined,
                        '#f59e0b',
                        renderPanelGuide('Fluid-Dynamics Choke-Point Analyzer', '<p>Models global logistics as a fluid network. Each maritime node&#39;s halo encodes the restriction factor <code>sigmoid(OSINT_viscosity / physical_Q − baseline)</code>; click to inspect downstream sector drag.</p>')
                    )}
                </section>

                <!-- Module A: Risk Contagion & Lead-Lag Tracker (Radial Grid) -->
                <section class="pro-insight-leadlag pro-insight-section" aria-label="Risk Contagion Lead-Lag Tracker">
                    ${renderProPanel(
                        'Risk Contagion &amp; Lead-Lag Tracker',
                        `<div id="radial-network-container"></div>`,
                        undefined,
                        '#58a6ff',
                        renderPanelGuide('Risk Contagion &amp; Lead-Lag Tracker', LEAD_LAG_GUIDE_HTML),
                    )}
                </section>

                <!-- Macro Transmission Channel -->
                <section class="pro-insight-transmission pro-insight-section" aria-label="Macro Transmission Channel">
                    ${renderProPanel(
                        'Macro Transmission Channel',
                        '<div id="macro-transmission-chart" class="w-full min-h-[350px]"></div>',
                        undefined,
                        '#58a6ff',
                        renderPanelGuide('Macro Transmission Channel', '<p>Visualizes the quantitative lag and correlation between any tradeable macro indicator (WTI, US 10Y, VIX, Copper, USD) and any strategic sector. Click a heatmap cell to load it here instantly.</p>')
                    )}
                </section>

                <!-- Macro Influence Heatmap (cross-sectional screener) -->
                <section class="pro-insight-matrix pro-insight-section" aria-label="Macro Influence Heatmap">
                    ${renderProPanel(
                        'Macro Influence Heatmap',
                        '<div id="macro-matrix-container" class="w-full"></div>',
                        undefined,
                        '#22d3ee',
                        renderPanelGuide('Macro Influence Heatmap', '<p>Cross-sectional correlation of every tradeable macro indicator against every strategic sector. Color encodes correlation strength (deep red = strong inverse, cyan/emerald = strong positive). Click any cell to load that pair into the Macro Transmission chart.</p>')
                    )}
                </section>

                <!-- Hidden Accumulation Screener (Price-OSINT divergence + CFTC overlay) -->
                <section class="pro-insight-accumulation pro-insight-section" aria-label="Hidden Accumulation Screener">
                    ${renderProPanel(
                        'Hidden Accumulation Screener',
                        '<div id="hidden-accumulation-container" class="w-full"></div>',
                        undefined,
                        '#10b981',
                        renderPanelGuide('Hidden Accumulation Screener', '<p>Detects 24h clusters where OSINT intensity surged ≥1.5x but the macro asset price stayed flat or rose. CFTC commercial net positioning overlays each row to confirm or refute institutional accumulation. Strict guardrails: <code>cluster_window=24h, reignite_factor=1.5x</code>.</p>')
                    )}
                </section>

            </div>
        </div>`;
            shellRendered = true;

            // Render every embedded analytical surface once. Each module
            // owns its own selector / drill-down state and survives the
            // 60s Market Pulse refresh.
            import('./macro_chart').then(m => m.renderMacroTransmissionChart('macro-transmission-chart'));
            import('./macro_matrix').then(m => m.renderMacroInfluenceMatrix('macro-matrix-container'));
            import('./market_entropy_gauge').then(m => m.renderMarketEntropyGauge('market-entropy-container'));
            import('./choke_point_map').then(m => m.renderChokePointMap('choke-point-container'));
            import('./hidden_accumulation').then(m => m.renderHiddenAccumulation('hidden-accumulation-container'));
            void refreshRegimeBanner(container);
        }

        // Store live riskSummary for poll cycle
        (container as any).__mpRiskSummary = riskSummary;

        // Render Radial Network Grid
        const radialContainer = container.querySelector('#radial-network-container') as HTMLElement;
        if (radialContainer) {
            new RadialNetworkEngine(radialContainer, data?.lead_lag_matrix || [], riskSummary as any);
        }
    };

    paint();

    marketPulsePollTimer = setInterval(async () => {
        if (sessionId !== marketPulseSession) return;
        if (container.dataset.dashboardView !== 'market-pulse') return;
        await loadInsights();
        paint();
        void import('./macro_chart').then(m => (m as any).refreshMacroTransmissionChart?.());
        void import('./macro_matrix').then(m => (m as any).refreshMacroInfluenceMatrix?.());
        void import('./market_entropy_gauge').then(m => (m as any).refreshMarketEntropyGauge?.());
        void import('./choke_point_map').then(m => (m as any).refreshChokePointMap?.());
        void import('./hidden_accumulation').then(m => (m as any).refreshHiddenAccumulation?.());
        void refreshRegimeBanner(container);
    }, MARKET_PULSE_REFRESH_MS);
}
