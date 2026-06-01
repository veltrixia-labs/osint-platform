/**
 * Market Entropy Gauge
 * ====================
 *
 * Pure-SVG arc gauge that visualises the Shannon-entropy regime computed by
 * `analysis/market_entropy.py`. No charting library — just an SVG path with
 * an arc-length stroke, plus CSS glow on the surrounding card and the breakout
 * warning state.
 *
 * Renders inside any container with a fixed ID. Re-fetch on the 60s
 * Market Pulse poll cycle via `refreshMarketEntropyGauge()`.
 */
import { fetchMarketEntropy, type MarketEntropy } from '../api';

const STYLE_ID = 'market-entropy-gauge-styles';
let activeContainerId: string | null = null;

const TOPIC_LABELS: Record<string, string> = {
    energy_resource_risk:          'Energy',
    global_market_intelligence:    'Market',
    crypto_geopolitics:            'Crypto',
    ai_semiconductor_intelligence: 'AI/Semi',
    defense_technology:            'Defense',
    supply_chain_intelligence:     'Supply',
};

function escAttr(s: string): string {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function injectStyles(): void {
    if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
        .me-gauge-card {
            display: flex;
            flex-direction: column;
            gap: 14px;
            padding: 18px 20px 16px;
            border-radius: 14px;
            background: linear-gradient(160deg, rgba(15,23,42,0.55), rgba(15,23,42,0.25));
            border: 1px solid var(--me-accent-border, rgba(125,211,252,0.18));
            backdrop-filter: blur(18px) saturate(140%);
            -webkit-backdrop-filter: blur(18px) saturate(140%);
            box-shadow:
                0 8px 28px rgba(2,6,23,0.45),
                inset 0 0 0 1px rgba(255,255,255,0.03),
                0 0 24px var(--me-accent-glow, transparent);
            color: #cbd5e1;
            transition: border-color 0.30s ease, box-shadow 0.30s ease;
        }
        .me-gauge-card.warning {
            animation: me-pulse 2.4s ease-in-out infinite;
        }
        @keyframes me-pulse {
            0%, 100% { box-shadow: 0 8px 28px rgba(2,6,23,0.45),
                                   inset 0 0 0 1px rgba(255,255,255,0.03),
                                   0 0 24px var(--me-accent-glow, rgba(220,38,38,0.55)); }
            50%      { box-shadow: 0 8px 28px rgba(2,6,23,0.45),
                                   inset 0 0 0 1px rgba(255,255,255,0.03),
                                   0 0 40px var(--me-accent-glow, rgba(220,38,38,0.85)); }
        }
        .me-gauge-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 12px;
            flex-wrap: wrap;
        }
        .me-gauge-header h3 {
            margin: 0;
            font-size: 0.95rem;
            font-weight: 700;
            color: #e2e8f0;
        }
        .me-gauge-meta {
            font-size: 0.66rem;
            color: #64748b;
            font-variant-numeric: tabular-nums;
        }
        .me-gauge-body {
            display: grid;
            grid-template-columns: 260px 1fr;
            gap: 20px;
            align-items: center;
        }
        @media (max-width: 720px) {
            .me-gauge-body { grid-template-columns: 1fr; }
        }
        .me-gauge-svg {
            width: 100%;
            max-width: 260px;
            aspect-ratio: 1.6 / 1;
            display: block;
        }
        .me-gauge-readout {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .me-gauge-emoji {
            font-size: 2rem;
            line-height: 1;
            filter: drop-shadow(0 0 10px var(--me-accent-glow, transparent));
        }
        .me-gauge-label {
            font-size: 0.92rem;
            font-weight: 800;
            color: var(--me-accent-primary, #e2e8f0);
            letter-spacing: 0.10em;
            text-transform: uppercase;
            text-shadow: 0 0 14px var(--me-accent-glow, transparent);
        }
        .me-gauge-interpretation {
            font-size: 0.78rem;
            color: #cbd5e1;
            line-height: 1.55;
        }
        .me-gauge-components {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 8px;
            margin-top: 4px;
        }
        .me-gauge-comp {
            padding: 8px 10px;
            border-radius: 8px;
            background: rgba(2,6,23,0.45);
            border: 1px solid rgba(148,163,184,0.16);
        }
        .me-gauge-comp .k {
            font-size: 0.62rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .me-gauge-comp .v {
            font-size: 0.92rem;
            font-weight: 700;
            color: #e2e8f0;
            font-variant-numeric: tabular-nums;
        }

        /* Topic distribution mini-bars */
        .me-topic-bars {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 6px;
            margin-top: 8px;
        }
        .me-topic-bar {
            padding: 6px 8px;
            background: rgba(2,6,23,0.42);
            border: 1px solid rgba(148,163,184,0.14);
            border-radius: 6px;
            font-size: 0.66rem;
            color: #cbd5e1;
        }
        .me-topic-bar-head {
            display: flex;
            justify-content: space-between;
            color: #94a3b8;
            font-variant-numeric: tabular-nums;
        }
        .me-topic-bar-track {
            margin-top: 4px;
            height: 4px;
            border-radius: 999px;
            background: rgba(148,163,184,0.12);
            overflow: hidden;
        }
        .me-topic-bar-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--me-accent-primary, #38bdf8), color-mix(in srgb, var(--me-accent-primary, #38bdf8) 40%, #475569));
            transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .me-gauge-status {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 180px;
            font-size: 0.85rem;
            color: #94a3b8;
        }
        .me-gauge-status.error { color: #fca5a5; }
    `;
    document.head.appendChild(style);
}

/**
 * Build the SVG arc path: a 240° sweep from -210° to +30°. The visible
 * portion is a single stroke whose stroke-dasharray encodes the
 * normalised entropy (0 → no fill, 1 → full sweep).
 */
function buildGaugeSvg(value01: number, accent: string): string {
    const v = Math.max(0, Math.min(1, value01));
    // viewBox 200x130, center 100,110, radius 80
    const cx = 100, cy = 110, r = 80;
    const startDeg = -210;
    const endDeg = 30;
    const totalSweep = endDeg - startDeg; // 240°

    const toXY = (deg: number) => {
        const rad = (deg * Math.PI) / 180;
        return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
    };
    const start = toXY(startDeg);
    const end = toXY(endDeg);
    const sweepArc = `M ${start.x.toFixed(2)} ${start.y.toFixed(2)} A ${r} ${r} 0 1 1 ${end.x.toFixed(2)} ${end.y.toFixed(2)}`;

    // Estimate path length for stroke-dasharray fill.
    const arcLen = (totalSweep / 360) * 2 * Math.PI * r;
    const fillLen = arcLen * v;

    // Needle position
    const needleDeg = startDeg + totalSweep * v;
    const needle = toXY(needleDeg);
    const needleInner = (() => {
        const rIn = r - 22;
        const rad = (needleDeg * Math.PI) / 180;
        return { x: cx + rIn * Math.cos(rad), y: cy + rIn * Math.sin(rad) };
    })();

    // Tick marks at 0, 0.3, 0.55, 0.78 thresholds
    const ticks = [0, 0.30, 0.55, 0.78, 1.0];
    const tickElems = ticks.map((t) => {
        const tDeg = startDeg + totalSweep * t;
        const rad = (tDeg * Math.PI) / 180;
        const x1 = cx + (r + 4) * Math.cos(rad);
        const y1 = cy + (r + 4) * Math.sin(rad);
        const x2 = cx + (r - 6) * Math.cos(rad);
        const y2 = cy + (r - 6) * Math.sin(rad);
        return `<line x1="${x1.toFixed(2)}" y1="${y1.toFixed(2)}" x2="${x2.toFixed(2)}" y2="${y2.toFixed(2)}" stroke="rgba(148,163,184,0.38)" stroke-width="1"/>`;
    }).join('');

    return `
        <svg class="me-gauge-svg" viewBox="0 0 200 130" preserveAspectRatio="xMidYMid meet">
            <defs>
                <filter id="me-glow" x="-30%" y="-30%" width="160%" height="160%">
                    <feGaussianBlur stdDeviation="3" result="blur"/>
                    <feMerge>
                        <feMergeNode in="blur"/>
                        <feMergeNode in="SourceGraphic"/>
                    </feMerge>
                </filter>
                <linearGradient id="me-arc-grad" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%"  stop-color="#22d3ee"/>
                    <stop offset="40%" stop-color="#10b981"/>
                    <stop offset="70%" stop-color="#f59e0b"/>
                    <stop offset="100%" stop-color="${escAttr(accent)}"/>
                </linearGradient>
            </defs>

            <!-- Track -->
            <path d="${sweepArc}" fill="none" stroke="rgba(148,163,184,0.18)" stroke-width="11" stroke-linecap="round"/>

            <!-- Filled portion -->
            <path d="${sweepArc}" fill="none" stroke="url(#me-arc-grad)" stroke-width="11" stroke-linecap="round"
                  stroke-dasharray="${fillLen.toFixed(2)} ${arcLen.toFixed(2)}" filter="url(#me-glow)"/>

            ${tickElems}

            <!-- Needle -->
            <line x1="${cx}" y1="${cy}" x2="${needle.x.toFixed(2)}" y2="${needle.y.toFixed(2)}"
                  stroke="${escAttr(accent)}" stroke-width="2.5" stroke-linecap="round" filter="url(#me-glow)"/>
            <circle cx="${needleInner.x.toFixed(2)}" cy="${needleInner.y.toFixed(2)}" r="3" fill="${escAttr(accent)}"/>
            <circle cx="${cx}" cy="${cy}" r="6" fill="rgba(2,6,23,0.85)" stroke="${escAttr(accent)}" stroke-width="1.5"/>

            <!-- Value text -->
            <text x="${cx}" y="${cy - 18}" text-anchor="middle"
                  font-family="ui-monospace, monospace" font-weight="800" font-size="22"
                  fill="#e2e8f0">${(v).toFixed(2)}</text>
            <text x="${cx}" y="${cy - 4}" text-anchor="middle"
                  font-family="Inter, system-ui, sans-serif" font-weight="600" font-size="9"
                  fill="#64748b" letter-spacing="0.12em">ENTROPY</text>
        </svg>
    `;
}

function applyAccent(card: HTMLElement, data: MarketEntropy): void {
    card.style.setProperty('--me-accent-primary', data.accent_color);
    card.style.setProperty('--me-accent-glow', data.glow_color);
    card.style.setProperty('--me-accent-border',
        `color-mix(in srgb, ${data.accent_color} 38%, rgba(125,211,252,0.18))`);
    card.classList.toggle('warning', !!data.breakout_warning);
}

function renderTopicBars(data: MarketEntropy): string {
    const max = Math.max(1, ...Object.values(data.topic_distribution));
    return Object.entries(data.topic_distribution).map(([key, count]) => {
        const label = TOPIC_LABELS[key] || key;
        const width = Math.round((count / max) * 100);
        return `<div class="me-topic-bar">
            <div class="me-topic-bar-head">
                <span>${escAttr(label)}</span>
                <span>${count}</span>
            </div>
            <div class="me-topic-bar-track">
                <div class="me-topic-bar-fill" style="width:${width}%"></div>
            </div>
        </div>`;
    }).join('');
}

function renderCard(card: HTMLElement, data: MarketEntropy): void {
    applyAccent(card, data);
    const ts = new Date(data.generated_at);
    const tsLabel = isNaN(ts.getTime()) ? data.generated_at : ts.toLocaleTimeString();
    const breakoutBadge = data.breakout_warning
        ? `<span style="margin-left:6px; padding:2px 7px; border-radius:999px; font-size:0.62rem;
            font-weight:800; letter-spacing:0.08em; background:rgba(220,38,38,0.20); color:#fecaca;
            border:1px solid rgba(220,38,38,0.55);">⚠ BREAKOUT</span>`
        : '';
    card.innerHTML = `
        <div class="me-gauge-header">
            <div>
                <h3>System Entropy Gauge${breakoutBadge}</h3>
                <div class="me-gauge-meta">
                    Shannon S = -Σ pᵢ ln pᵢ · Window ${data.window_hours}h · ${data.n_alerts} alerts · ${tsLabel}
                </div>
            </div>
        </div>
        <div class="me-gauge-body">
            ${buildGaugeSvg(data.entropy_normalised, data.accent_color)}
            <div class="me-gauge-readout">
                <div style="display:flex; align-items:center; gap:10px;">
                    <span class="me-gauge-emoji">${escAttr(data.regime_emoji)}</span>
                    <span class="me-gauge-label">${escAttr(data.regime_label)}</span>
                </div>
                <div class="me-gauge-interpretation">${escAttr(data.interpretation)}</div>
                <div class="me-gauge-components">
                    <div class="me-gauge-comp">
                        <div class="k">Topic entropy</div>
                        <div class="v">${data.topic_entropy_normalised.toFixed(3)}</div>
                    </div>
                    <div class="me-gauge-comp">
                        <div class="k">Intensity entropy</div>
                        <div class="v">${data.intensity_entropy_normalised.toFixed(3)}</div>
                    </div>
                    <div class="me-gauge-comp">
                        <div class="k">Threshold</div>
                        <div class="v">≥ ${data.breakout_threshold.toFixed(2)}</div>
                    </div>
                    <div class="me-gauge-comp">
                        <div class="k">Alerts (24h)</div>
                        <div class="v">${data.n_alerts}</div>
                    </div>
                </div>
            </div>
        </div>
        <div class="me-topic-bars">${renderTopicBars(data)}</div>
    `;
}

function setStatus(card: HTMLElement, html: string, isError = false): void {
    card.innerHTML = `<div class="me-gauge-status ${isError ? 'error' : ''}">${html}</div>`;
}

async function loadAndPaint(card: HTMLElement): Promise<void> {
    setStatus(card, '<span class="animate-pulse">Computing entropy…</span>');
    const data = await fetchMarketEntropy();
    if (!data) {
        setStatus(card, 'Market entropy endpoint unavailable.', true);
        return;
    }
    renderCard(card, data);
}

export async function renderMarketEntropyGauge(containerId: string): Promise<void> {
    const container = document.getElementById(containerId);
    if (!container) return;
    injectStyles();
    container.innerHTML = `<div class="me-gauge-card" id="${containerId}-card"></div>`;
    const card = container.querySelector<HTMLElement>(`#${CSS.escape(containerId)}-card`);
    if (!card) return;
    activeContainerId = containerId;
    await loadAndPaint(card);
}

export async function refreshMarketEntropyGauge(): Promise<void> {
    if (!activeContainerId) return;
    const container = document.getElementById(activeContainerId);
    if (!container) return;
    const card = container.querySelector<HTMLElement>(`#${CSS.escape(activeContainerId)}-card`);
    if (!card || !document.body.contains(card)) return;
    await loadAndPaint(card);
}
