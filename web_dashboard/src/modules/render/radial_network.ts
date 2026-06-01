import { fetchSectorDrilldown, type DrilldownData } from '../api';
import { getTopicColor, getTopicDef } from '../topics';

type MatrixRow = { source: string; target: string; lag_hours: number; correlation: number };
type RiskSummary = Record<string, { intensity?: number; intensity_delta?: number; top_signal?: string }>;

const DOMAINS = [
    'energy_resource_risk',
    'global_market_intelligence',
    'crypto_geopolitics',
    'ai_semiconductor_intelligence',
    'defense_technology',
    'supply_chain_intelligence',
];

const DOMAIN_SHORT: Record<string, string> = {
    energy_resource_risk:          'Energy',
    global_market_intelligence:    'Market',
    crypto_geopolitics:            'Crypto',
    ai_semiconductor_intelligence: 'AI/Semi',
    defense_technology:            'Defense',
    supply_chain_intelligence:     'Supply Chain',
};

const SEVERITY_COLOR: Record<string, string> = {
    critical: '#ef4444',
    elevated: '#f97316',
    watch:    '#eab308',
};
const SEVERITY_ICON: Record<string, string> = {
    critical: '🔴',
    elevated: '🟠',
    watch:    '🟡',
};
const TRIGGER_LABEL: Record<string, string> = {
    spike:        'SPIKE',
    acceleration: 'ACCEL',
    new_pattern:  'PATTERN',
    multi_source: 'MULTI-SRC',
    signal:       'SIGNAL',
};

function escHtml(s: string): string {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function formatTime(iso: string | null): string {
    if (!iso) return '';
    const d = new Date(iso);
    const diff = Date.now() - d.getTime();
    const h = Math.floor(diff / 3_600_000);
    if (h < 1) return `${Math.floor(diff / 60_000)}m ago`;
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
}

// ─── Master Contagion Nexus — geometry helpers ────────────────────────────
//
// Single large radial graph: one centre + 5 spokes, designed for the new
// glassmorphic dashboard panel.  Geometry uses transform="translate(x,y)" on
// each node <g> so the orbit-swap animation is a CSS transition (no manual
// tween / rAF loop required).

const NEXUS_W = 650;          // viewBox width
const NEXUS_H = 610;          // viewBox height
const NEXUS_CX = NEXUS_W / 2;
const NEXUS_CY = NEXUS_H / 2;
const NEXUS_MIN_R = 165;      // 0h lag: clear centre glow + node padding
const NEXUS_MAX_R = 235;      // 24h lag: far but still connected
const NEXUS_OORT_R = 260;     // uncorrelated sectors: ghosted outer rim
const NEXUS_SIGNIFICANT_R = 0.15;
const NEXUS_LAG_MAX_HOURS = 24;
const NEXUS_CENTER_R = 64;    // centre node circle radius
const NEXUS_OUTER_R = 44;     // orbit node circle radius
const NEXUS_SWAP_MS = 420;    // transform transition duration

let manualFocusEntityId: string | null = null;

function isKnownDomain(domain: string | null): domain is string {
    return !!domain && DOMAINS.includes(domain);
}


function findPair(matrix: MatrixRow[], a: string, b: string): MatrixRow | undefined {
    return matrix.find(m =>
        (m.source === a && m.target === b) ||
        (m.source === b && m.target === a)
    );
}

function isSignificantPair(pair: MatrixRow | undefined): pair is MatrixRow {
    return !!pair && Number.isFinite(pair.correlation) && Math.abs(pair.correlation) >= NEXUS_SIGNIFICANT_R;
}

function radiusForPair(pair: MatrixRow | undefined): number {
    if (!isSignificantPair(pair)) return NEXUS_OORT_R;
    const lag = Math.min(Math.abs(pair.lag_hours || 0), NEXUS_LAG_MAX_HOURS);
    const t = lag / NEXUS_LAG_MAX_HOURS;
    return NEXUS_MIN_R + (NEXUS_MAX_R - NEXUS_MIN_R) * t;
}

function formatLagHours(hours: number): string {
    const sign = hours >= 0 ? '+' : '';
    return `${sign}${hours.toFixed(1)}h`;
}

function incidentPairs(centerDomain: string, matrix: MatrixRow[]): MatrixRow[] {
    return DOMAINS
        .filter((d) => d !== centerDomain)
        .map((d) => findPair(matrix, centerDomain, d))
        .filter((p): p is MatrixRow => isSignificantPair(p))
        .sort((a, b) => Math.abs(a.lag_hours) - Math.abs(b.lag_hours));
}

function otherSide(pair: MatrixRow, centerDomain: string): string {
    return pair.source === centerDomain ? pair.target : pair.source;
}

function computeNexusPositions(
    centerDomain: string,
    matrix: MatrixRow[],
): Record<string, { x: number; y: number }> {
    const outer = DOMAINS.filter(d => d !== centerDomain);
    const pos: Record<string, { x: number; y: number }> = {};
    pos[centerDomain] = { x: NEXUS_CX, y: NEXUS_CY };
    const step = (2 * Math.PI) / outer.length;
    outer.forEach((d, i) => {
        const angle = i * step - Math.PI / 2;
        const r = radiusForPair(findPair(matrix, centerDomain, d));
        pos[d] = {
            x: NEXUS_CX + r * Math.cos(angle),
            y: NEXUS_CY + r * Math.sin(angle),
        };
    });
    return pos;
}

/**
 * Build the full Master Nexus SVG. Each domain gets one `<g class="mcn-node"
 * data-domain="...">` positioned via `transform="translate(x,y)"`; the
 * orbit-swap animation simply mutates that transform and CSS handles the tween.
 */
function buildMasterGraph(
    centerDomain: string,
    matrix: MatrixRow[],
    riskSummary: RiskSummary,
    positions: Record<string, { x: number; y: number }>,
    handlers: {
        onOrbitClick: (domain: string) => void;
    },
): SVGSVGElement {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg') as SVGSVGElement;
    svg.setAttribute('class', 'mcn-svg');
    svg.setAttribute('viewBox', `0 0 ${NEXUS_W} ${NEXUS_H}`);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');

    const centerColor = getTopicColor(centerDomain);

    // ── Defs (gradients + filters) ───────────────────────────────────────
    const defs = document.createElementNS(NS, 'defs');
    defs.innerHTML = `
        <radialGradient id="mcn-bg" cx="50%" cy="50%" r="50%">
            <stop offset="0%"  stop-color="${centerColor}" stop-opacity="0.16"/>
            <stop offset="55%" stop-color="${centerColor}" stop-opacity="0.04"/>
            <stop offset="100%" stop-color="${centerColor}" stop-opacity="0"/>
        </radialGradient>
        <filter id="mcn-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="5" result="blur"/>
            <feMerge>
                <feMergeNode in="blur"/>
                <feMergeNode in="SourceGraphic"/>
            </feMerge>
        </filter>
        <filter id="mcn-soft-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="2.5" result="blur"/>
            <feMerge>
                <feMergeNode in="blur"/>
                <feMergeNode in="SourceGraphic"/>
            </feMerge>
        </filter>
    `;
    svg.appendChild(defs);

    // ── Background halo behind the centre ─────────────────────────────────
    const bgHalo = document.createElementNS(NS, 'circle');
    bgHalo.setAttribute('cx', String(NEXUS_CX));
    bgHalo.setAttribute('cy', String(NEXUS_CY));
    bgHalo.setAttribute('r', String(NEXUS_MAX_R + 90));
    bgHalo.setAttribute('fill', 'url(#mcn-bg)');
    bgHalo.setAttribute('pointer-events', 'none');
    svg.appendChild(bgHalo);

    // Orbit guide ring
    const orbitRing = document.createElementNS(NS, 'circle');
    orbitRing.setAttribute('cx', String(NEXUS_CX));
    orbitRing.setAttribute('cy', String(NEXUS_CY));
    orbitRing.setAttribute('r', String(NEXUS_MAX_R));
    orbitRing.setAttribute('fill', 'none');
    orbitRing.setAttribute('stroke', `${centerColor}55`);
    orbitRing.setAttribute('stroke-width', '0.6');
    orbitRing.setAttribute('stroke-dasharray', '3 6');
    orbitRing.setAttribute('pointer-events', 'none');
    svg.appendChild(orbitRing);

    // ── Edges ─────────────────────────────────────────────────────────────
    const edgesG = document.createElementNS(NS, 'g') as SVGGElement;
    edgesG.setAttribute('class', 'mcn-edges');
    const outerDomains = DOMAINS.filter(d => d !== centerDomain);

    for (const outer of outerDomains) {
        const pair = findPair(matrix, centerDomain, outer);
        if (!isSignificantPair(pair)) continue;
        const absR = Math.abs(pair.correlation);

        const p1 = positions[centerDomain];
        const p2 = positions[outer];
        const strokeColor = pair.correlation > 0 ? '#10b981' : '#f43f5e';

        const line = document.createElementNS(NS, 'line');
        line.setAttribute('x1', p1.x.toFixed(2));
        line.setAttribute('y1', p1.y.toFixed(2));
        line.setAttribute('x2', p2.x.toFixed(2));
        line.setAttribute('y2', p2.y.toFixed(2));
        line.setAttribute('stroke', strokeColor);
        line.setAttribute('stroke-width', Math.max(1.4, absR * 5).toFixed(1));
        line.setAttribute('opacity', (0.20 + absR * 0.55).toFixed(2));
        line.setAttribute('stroke-linecap', 'round');
        line.setAttribute('pointer-events', 'none');
        line.setAttribute('filter', 'url(#mcn-soft-glow)');

        if (absR > 0.45) {
            line.setAttribute('stroke-dasharray', '6 4');
            const anim = document.createElementNS(NS, 'animate');
            anim.setAttribute('attributeName', 'stroke-dashoffset');
            anim.setAttribute('from', pair.correlation > 0 ? '10' : '0');
            anim.setAttribute('to',   pair.correlation > 0 ? '0' : '10');
            anim.setAttribute('dur', `${(1.4 - absR * 0.5).toFixed(1)}s`);
            anim.setAttribute('repeatCount', 'indefinite');
            line.appendChild(anim);
        }
        edgesG.appendChild(line);
    }
    svg.appendChild(edgesG);

    // ── Nodes ─────────────────────────────────────────────────────────────
    const nodesG = document.createElementNS(NS, 'g') as SVGGElement;
    nodesG.setAttribute('class', 'mcn-nodes');

    // Helper that constructs one <g class="mcn-node" transform="translate(...)">
    const makeNodeGroup = (domain: string, isCenter: boolean): SVGGElement => {
        const col = getTopicColor(domain);
        const def = getTopicDef(domain);
        const intensity = Number(riskSummary[domain]?.intensity) || 0;
        const delta = Number(riskSummary[domain]?.intensity_delta) || 0;
        const p = positions[domain];

        const pair = isCenter ? undefined : findPair(matrix, centerDomain, domain);
        const isGhost = !isCenter && !isSignificantPair(pair);

        const g = document.createElementNS(NS, 'g') as SVGGElement;
        g.setAttribute('class', `mcn-node ${isCenter ? 'mcn-node--center' : 'mcn-node--orbit'}${isGhost ? ' mcn-node--ghost' : ''}`);
        g.setAttribute('data-domain', domain);
        g.setAttribute('transform', `translate(${p.x.toFixed(2)},${p.y.toFixed(2)})`);
        g.style.cursor = 'pointer';

        const R = isCenter ? NEXUS_CENTER_R : NEXUS_OUTER_R;

        // Outer glow ring (centre only)
        if (isCenter) {
            const glow = document.createElementNS(NS, 'circle');
            glow.setAttribute('r', (R + 9).toString());
            glow.setAttribute('fill', 'none');
            glow.setAttribute('stroke', col);
            glow.setAttribute('stroke-width', '2');
            glow.setAttribute('opacity', '0.45');
            glow.setAttribute('filter', 'url(#mcn-glow)');
            glow.setAttribute('pointer-events', 'none');
            g.appendChild(glow);
        }

        // Core circle
        const core = document.createElementNS(NS, 'circle');
        core.setAttribute('r', R.toString());
        core.setAttribute('fill', `${col}${isCenter ? '28' : '18'}`);
        core.setAttribute('stroke', col);
        core.setAttribute('stroke-width', isCenter ? '2.8' : '1.8');
        g.appendChild(core);

        // Icon
        const icon = document.createElementNS(NS, 'text');
        icon.setAttribute('x', '0');
        icon.setAttribute('y', isCenter ? '-13' : '-11');
        icon.setAttribute('text-anchor', 'middle');
        icon.setAttribute('font-size', isCenter ? '18px' : '13px');
        icon.setAttribute('pointer-events', 'none');
        icon.textContent = def.icon;
        g.appendChild(icon);

        // Label
        const lbl = document.createElementNS(NS, 'text');
        lbl.setAttribute('x', '0');
        lbl.setAttribute('y', isCenter ? '5' : '2');
        lbl.setAttribute('fill', '#f1f5f9');
        lbl.setAttribute('font-size', isCenter ? '12px' : '9.5px');
        lbl.setAttribute('font-weight', '800');
        lbl.setAttribute('text-anchor', 'middle');
        lbl.setAttribute('pointer-events', 'none');
        lbl.textContent = DOMAIN_SHORT[domain] || domain;
        g.appendChild(lbl);

        // Intensity score
        const score = document.createElementNS(NS, 'text');
        score.setAttribute('x', '0');
        score.setAttribute('y', isCenter ? '22' : '16');
        score.setAttribute('fill', col);
        score.setAttribute('font-size', isCenter ? '13px' : '10px');
        score.setAttribute('font-weight', '800');
        score.setAttribute('text-anchor', 'middle');
        score.setAttribute('pointer-events', 'none');
        score.setAttribute('font-family', 'ui-monospace, monospace');
        score.textContent = intensity > 0 ? intensity.toFixed(1) : '—';
        g.appendChild(score);

        // Orbit metrics live inside the node to keep spokes clean at short lags.
        if (!isCenter) {
            const metricText = isSignificantPair(pair)
                ? `Δ ${formatLagHours(pair.lag_hours)} | R=${pair.correlation.toFixed(2)}`
                : 'Outer Rim';
            const metricW = Math.min(96, metricText.length * 4.5 + 12);

            const metricBg = document.createElementNS(NS, 'rect');
            metricBg.setAttribute('x', (-metricW / 2).toFixed(1));
            metricBg.setAttribute('y', '23');
            metricBg.setAttribute('width', metricW.toFixed(1));
            metricBg.setAttribute('height', '13');
            metricBg.setAttribute('rx', '6.5');
            metricBg.setAttribute('fill', isSignificantPair(pair) ? 'rgba(2,6,23,0.68)' : 'rgba(15,23,42,0.58)');
            metricBg.setAttribute('stroke', `${col}55`);
            metricBg.setAttribute('stroke-width', '0.5');
            metricBg.setAttribute('pointer-events', 'none');
            g.appendChild(metricBg);

            const metric = document.createElementNS(NS, 'text');
            metric.setAttribute('x', '0');
            metric.setAttribute('y', '32.3');
            metric.setAttribute('fill', isSignificantPair(pair) ? '#dbeafe' : 'rgba(203,213,225,0.70)');
            metric.setAttribute('font-size', '7.4px');
            metric.setAttribute('font-weight', '800');
            metric.setAttribute('text-anchor', 'middle');
            metric.setAttribute('pointer-events', 'none');
            metric.setAttribute('font-family', 'ui-monospace, monospace');
            metric.textContent = metricText;
            g.appendChild(metric);
        }

        // Delta arrow on centre
        if (isCenter && Math.abs(delta) >= 0.3) {
            const dt = document.createElementNS(NS, 'text');
            dt.setAttribute('x', '0');
            dt.setAttribute('y', '36');
            dt.setAttribute('fill', delta > 0 ? '#f97316' : '#6ee7b7');
            dt.setAttribute('font-size', '10px');
            dt.setAttribute('font-weight', '700');
            dt.setAttribute('text-anchor', 'middle');
            dt.setAttribute('pointer-events', 'none');
            dt.textContent = `${delta > 0 ? '▲' : '▼'} ${Math.abs(delta).toFixed(1)}`;
            g.appendChild(dt);
        }

        // Click handler
        g.addEventListener('click', (e) => {
            e.stopPropagation();
            if (!isCenter) handlers.onOrbitClick(domain);
        });
        return g;
    };

    // Orbit nodes first (so centre paints on top)
    for (const outer of outerDomains) {
        nodesG.appendChild(makeNodeGroup(outer, false));
    }
    nodesG.appendChild(makeNodeGroup(centerDomain, true));
    svg.appendChild(nodesG);

    return svg;
}

// ─── Main export ────────────────────────────────────────────────────────────

export class RadialNetworkEngine {
    private container: HTMLElement;
    private matrix: MatrixRow[];
    private riskSummary: RiskSummary;
    private currentCenter: string;
    private autoFocused: string;          // remembered so the Reset button can restore
    private svgHost: HTMLElement | null = null;
    private animating = false;            // guards against rapid double-clicks
    private investigationToken = 0;

    constructor(container: HTMLElement, matrix: MatrixRow[], riskSummary: RiskSummary) {
        this.container = container;
        this.matrix    = matrix;
        this.riskSummary = riskSummary || {};
        this.autoFocused = this.pickInitialCenter();
        this.currentCenter = isKnownDomain(manualFocusEntityId)
            ? manualFocusEntityId
            : this.autoFocused;
        this.render();
    }

    /**
     * Heuristic auto-focus: the domain that most warrants the analyst's
     * attention right now.
     *   score = intensity * 10 + Σ |R| of incident lead-lag edges
     * Ties broken by the static DOMAINS order.  We never crash on empty
     * data — we just fall back to the first domain.
     */
    private pickInitialCenter(): string {
        let best = DOMAINS[0];
        let bestScore = -Infinity;
        for (const d of DOMAINS) {
            const intensity = Number(this.riskSummary[d]?.intensity) || 0;
            const incident = this.matrix
                .filter(m => m.source === d || m.target === d)
                .reduce((s, m) => s + Math.abs(m.correlation || 0), 0);
            const score = intensity * 10 + incident;
            if (score > bestScore) {
                bestScore = score;
                best = d;
            }
        }
        return best;
    }

    private ensureStyles(): void {
        if (document.getElementById('mcn-styles')) return;
        const st = document.createElement('style');
        st.id = 'mcn-styles';
        st.textContent = `
            .mcn-card {
                position: relative;
                display: flex;
                flex-direction: column;
                gap: 12px;
                padding: 18px 20px 18px;
                border-radius: 14px;
                background: linear-gradient(160deg, rgba(15,23,42,0.55), rgba(15,23,42,0.25));
                border: 1px solid var(--mcn-accent-border, rgba(125,211,252,0.18));
                backdrop-filter: blur(18px) saturate(140%);
                -webkit-backdrop-filter: blur(18px) saturate(140%);
                box-shadow:
                    0 10px 32px rgba(2,6,23,0.45),
                    inset 0 0 0 1px rgba(255,255,255,0.03),
                    0 0 28px var(--mcn-accent-glow, transparent);
                color: #cbd5e1;
                transition: border-color 0.35s ease, box-shadow 0.35s ease;
            }
            .mcn-header {
                display: flex;
                justify-content: space-between;
                align-items: baseline;
                gap: 10px;
                flex-wrap: wrap;
            }
            .mcn-header h3 {
                margin: 0;
                font-size: 0.95rem;
                font-weight: 700;
                color: #e2e8f0;
            }
            .mcn-subtitle {
                font-size: 0.74rem;
                color: #94a3b8;
                margin-top: 4px;
            }
            .mcn-focus-pill {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 4px 12px;
                border-radius: 999px;
                font-size: 0.66rem;
                font-weight: 800;
                letter-spacing: 0.10em;
                text-transform: uppercase;
                color: #ffffff;
                background: linear-gradient(135deg,
                    color-mix(in srgb, var(--mcn-accent-primary, #38bdf8) 38%, rgba(2,6,23,0.55)),
                    color-mix(in srgb, var(--mcn-accent-primary, #38bdf8) 22%, rgba(15,23,42,0.45)));
                border: 1px solid var(--mcn-accent-primary, #38bdf8);
            }
            .mcn-reset {
                background: rgba(148,163,184,0.12);
                color: #cbd5e1;
                border: 1px solid rgba(148,163,184,0.30);
                padding: 4px 10px;
                font-size: 0.66rem;
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                border-radius: 999px;
                cursor: pointer;
                transition: border-color 0.18s ease, color 0.18s ease;
            }
            .mcn-reset:hover {
                border-color: var(--mcn-accent-primary, #38bdf8);
                color: #e2e8f0;
            }
            .mcn-reset:disabled {
                opacity: 0.40;
                cursor: not-allowed;
            }
            .mcn-body {
                display: grid;
                grid-template-columns: minmax(0, 3fr) minmax(320px, 2fr);
                gap: 16px;
                align-items: stretch;
            }
            .mcn-svg-wrap {
                width: 100%;
                aspect-ratio: ${NEXUS_W} / ${NEXUS_H};
                min-height: 560px;
                max-height: 760px;
                border-radius: 12px;
                background: radial-gradient(circle at 50% 50%, rgba(2,6,23,0.30), rgba(2,6,23,0.55));
                border: 1px solid rgba(148,163,184,0.10);
                overflow: hidden;
            }
            .mcn-svg {
                width: 100%;
                height: 100%;
                display: block;
            }
            /* Orbit-swap animation: changing the transform attribute on a node
               <g> tweens smoothly thanks to this CSS rule. */
            .mcn-node {
                transition: transform ${NEXUS_SWAP_MS}ms cubic-bezier(0.4, 0, 0.2, 1);
                transform-box: fill-box;
            }
            .mcn-node--ghost {
                opacity: 0.30;
                filter: grayscale(100%);
            }
            .mcn-node circle {
                transition: r 0.30s ease, fill 0.30s ease, stroke-width 0.30s ease;
            }
            .mcn-edges {
                transition: opacity 0.18s ease;
            }
            .mcn-edges.fading { opacity: 0; }
            .mcn-node--orbit:hover circle:last-of-type,
            .mcn-node--orbit:hover circle:not([fill="none"]) {
                stroke-width: 2.6;
            }
            .mcn-investigation {
                display: flex;
                flex-direction: column;
                gap: 14px;
                min-height: 520px;
                padding: 16px;
                border-radius: 12px;
                background:
                    radial-gradient(circle at 20% 10%, var(--mcn-accent-glow, transparent), transparent 38%),
                    rgba(2,6,23,0.48);
                border: 1px solid rgba(148,163,184,0.16);
                box-shadow: inset 0 0 0 1px rgba(255,255,255,0.025);
            }
            .mcn-analysis-kicker {
                font-size: 0.62rem;
                color: var(--mcn-accent-primary, #38bdf8);
                font-weight: 800;
                letter-spacing: 0.12em;
                text-transform: uppercase;
            }
            .mcn-analysis-title {
                margin: 2px 0 0;
                color: #f1f5f9;
                font-size: 1.05rem;
                font-weight: 800;
            }
            .mcn-summary {
                margin: 0;
                color: #cbd5e1;
                font-size: 0.86rem;
                line-height: 1.65;
            }
            .mcn-summary strong {
                color: #f8fafc;
            }
            .mcn-impact-list {
                display: flex;
                flex-direction: column;
                gap: 8px;
            }
            .mcn-impact-row {
                display: grid;
                grid-template-columns: auto 1fr auto;
                gap: 10px;
                align-items: center;
                padding: 9px 10px;
                border-radius: 9px;
                background: rgba(15,23,42,0.54);
                border: 1px solid rgba(148,163,184,0.13);
                border-left: 3px solid var(--impact-color, #94a3b8);
            }
            .mcn-impact-rank {
                width: 22px;
                height: 22px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border-radius: 999px;
                font-size: 0.66rem;
                font-weight: 800;
                color: #020617;
                background: var(--impact-color, #94a3b8);
            }
            .mcn-impact-name {
                color: #e2e8f0;
                font-size: 0.82rem;
                font-weight: 700;
            }
            .mcn-impact-meta {
                margin-top: 2px;
                color: #94a3b8;
                font-size: 0.68rem;
                font-family: ui-monospace, monospace;
            }
            .mcn-impact-urgency {
                color: var(--impact-color, #94a3b8);
                font-size: 0.66rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.08em;
            }
            .mcn-evidence-toggle {
                margin-top: auto;
                align-self: flex-start;
                padding: 7px 11px;
                border-radius: 999px;
                border: 1px solid color-mix(in srgb, var(--mcn-accent-primary, #38bdf8) 55%, rgba(148,163,184,0.35));
                background: color-mix(in srgb, var(--mcn-accent-primary, #38bdf8) 14%, rgba(2,6,23,0.64));
                color: #e2e8f0;
                cursor: pointer;
                font-size: 0.70rem;
                font-weight: 800;
                letter-spacing: 0.07em;
                text-transform: uppercase;
            }
            .mcn-evidence-list {
                display: none;
                max-height: 220px;
                overflow: auto;
                padding-top: 4px;
            }
            .mcn-evidence-list.is-open {
                display: flex;
                flex-direction: column;
                gap: 8px;
            }
            .mcn-evidence-item {
                padding: 9px 10px;
                border-radius: 9px;
                background: rgba(2,6,23,0.50);
                border: 1px solid rgba(148,163,184,0.14);
                color: #cbd5e1;
                font-size: 0.74rem;
                line-height: 1.45;
            }
            .mcn-evidence-item a {
                color: var(--mcn-accent-primary, #38bdf8);
                text-decoration: none;
                font-weight: 700;
            }
            .mcn-footer {
                display: flex;
                gap: 16px;
                font-size: 0.66rem;
                color: #64748b;
                flex-wrap: wrap;
            }
            .mcn-footer .mcn-leg {
                display: inline-flex;
                align-items: center;
                gap: 6px;
            }
            .mcn-footer .mcn-swatch {
                width: 18px;
                height: 3px;
                border-radius: 2px;
            }
            @media (max-width: 540px) {
                .mcn-body { grid-template-columns: 1fr; }
                .mcn-svg-wrap { aspect-ratio: 1 / 0.95; min-height: 420px; }
                .mcn-investigation { min-height: auto; }
                .mcn-header h3 { font-size: 0.85rem; }
            }
            @media (max-width: 980px) {
                .mcn-body { grid-template-columns: 1fr; }
            }
        `;
        document.head.appendChild(st);
    }

    private applyAccent(card: HTMLElement): void {
        const color = getTopicColor(this.currentCenter);
        card.style.setProperty('--mcn-accent-primary', color);
        card.style.setProperty('--mcn-accent-glow', `${color}55`);
        card.style.setProperty('--mcn-accent-border',
            `color-mix(in srgb, ${color} 38%, rgba(125,211,252,0.18))`);
    }

    private render() {
        this.container.innerHTML = '';
        this.ensureStyles();

        const card = document.createElement('div');
        card.className = 'mcn-card';
        this.applyAccent(card);
        this.container.appendChild(card);

        const def = getTopicDef(this.currentCenter);
        const intensity = Number(this.riskSummary[this.currentCenter]?.intensity) || 0;
        const isManualFocus = isKnownDomain(manualFocusEntityId);
        const subtitle = !isManualFocus
            ? `Auto-focused on highest-priority sector: <strong style="color:#e2e8f0;">${def.label}</strong> (intensity ${intensity.toFixed(1)})`
            : `Manually focused on <strong style="color:#e2e8f0;">${def.label}</strong> — orbit nodes reveal lag &amp; correlation against this centre`;

        card.innerHTML = `
            <div class="mcn-header">
                <div>
                    <h3>Master Contagion Nexus</h3>
                    <div class="mcn-subtitle">${subtitle}</div>
                </div>
                <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                    <span class="mcn-focus-pill">${def.icon} ${def.label}</span>
                    <button class="mcn-reset" id="mcn-reset" ${!isManualFocus ? 'disabled' : ''}
                        title="Restore auto-focus to the highest-priority sector">
                        ↺ Auto-Focus
                    </button>
                </div>
            </div>
            <div class="mcn-body">
                <div class="mcn-svg-wrap" id="mcn-svg-host"></div>
                <aside class="mcn-investigation" id="mcn-investigation-panel"></aside>
            </div>
            <div class="mcn-footer">
                <span class="mcn-leg"><span class="mcn-swatch" style="background:#10b981;"></span>positive correlation (synchronised lead-lag)</span>
                <span class="mcn-leg"><span class="mcn-swatch" style="background:#f43f5e;"></span>negative correlation (counter-trend)</span>
                <span style="margin-left:auto; color:#94a3b8;">Click an orbiting node to swap focus · shortest lag ranks highest urgency</span>
            </div>
        `;

        this.svgHost = card.querySelector<HTMLElement>('#mcn-svg-host');
        if (this.svgHost) {
            const positions = computeNexusPositions(this.currentCenter, this.matrix);
            const svg = buildMasterGraph(
                this.currentCenter,
                this.matrix,
                this.riskSummary,
                positions,
                {
                    onOrbitClick: (d) => this.swapToCenter(d),
                },
            );
            this.svgHost.appendChild(svg);
        }

        this.renderInvestigationPanel(card);

        card.querySelector<HTMLButtonElement>('#mcn-reset')?.addEventListener('click', () => {
            this.autoFocusTopTrend();
        });
    }

    private renderInvestigationPanel(card: HTMLElement): void {
        const panel = card.querySelector<HTMLElement>('#mcn-investigation-panel');
        if (!panel) return;

        const token = ++this.investigationToken;
        const def = getTopicDef(this.currentCenter);
        const intensity = Number(this.riskSummary[this.currentCenter]?.intensity) || 0;
        const delta = Number(this.riskSummary[this.currentCenter]?.intensity_delta) || 0;
        const impacts = incidentPairs(this.currentCenter, this.matrix);
        const strongest = [...impacts].sort((a, b) => Math.abs(b.correlation) - Math.abs(a.correlation))[0];
        const strongestDomain = strongest ? otherSide(strongest, this.currentCenter) : null;
        const strongestDef = strongestDomain ? getTopicDef(strongestDomain) : null;

        const summary = strongest && strongestDef
            ? `Primary shock detected in <strong>${escHtml(def.label)}</strong> (Intensity: <strong>${intensity.toFixed(1)}</strong>${Math.abs(delta) >= 0.1 ? `, Δ ${delta > 0 ? '+' : ''}${delta.toFixed(1)}` : ''}). The strongest contagion path currently leads to <strong>${escHtml(strongestDef.label)}</strong> with a lag of <strong>${formatLagHours(strongest.lag_hours)}</strong> (R=<strong>${strongest.correlation.toFixed(2)}</strong>).`
            : `Primary monitoring focus is <strong>${escHtml(def.label)}</strong> (Intensity: <strong>${intensity.toFixed(1)}</strong>). No statistically meaningful contagion path is active above the correlation threshold; adjacent sectors are parked in the outer rim until stronger coupling emerges.`;

        const impactRows = impacts.length
            ? impacts.map((pair, index) => {
                const domain = otherSide(pair, this.currentCenter);
                const target = getTopicDef(domain);
                const lagAbs = Math.abs(pair.lag_hours);
                const urgency = lagAbs <= 4 ? 'Immediate' : lagAbs <= 12 ? 'Near-Term' : 'Watch';
                const color = getTopicColor(domain);
                return `
                    <div class="mcn-impact-row" style="--impact-color:${color};">
                        <span class="mcn-impact-rank">${index + 1}</span>
                        <div>
                            <div class="mcn-impact-name">${target.icon} ${escHtml(target.label)}</div>
                            <div class="mcn-impact-meta">${formatLagHours(pair.lag_hours)} · R=${pair.correlation.toFixed(2)} · radius=${Math.round(radiusForPair(pair))}px</div>
                        </div>
                        <span class="mcn-impact-urgency">${urgency}</span>
                    </div>
                `;
            }).join('')
            : `<div class="mcn-evidence-item">No impending cross-sector impacts are above the current correlation threshold. Ghosted outer-rim sectors remain visible for context.</div>`;

        panel.innerHTML = `
            <div>
                <div class="mcn-analysis-kicker">Automated Quantitative Analysis</div>
                <h4 class="mcn-analysis-title">${def.icon} ${escHtml(def.label)}</h4>
            </div>
            <p class="mcn-summary">${summary}</p>
            <div>
                <div class="mcn-analysis-kicker" style="margin-bottom:8px;">Impending Impacts · Ranked by Lag</div>
                <div class="mcn-impact-list">${impactRows}</div>
            </div>
            <button type="button" class="mcn-evidence-toggle" id="mcn-evidence-toggle">
                🔍 View Source Evidence
            </button>
            <div class="mcn-evidence-list" id="mcn-evidence-list">
                <div class="mcn-evidence-item">Loading source evidence…</div>
            </div>
        `;

        const toggle = panel.querySelector<HTMLButtonElement>('#mcn-evidence-toggle');
        const evidenceList = panel.querySelector<HTMLElement>('#mcn-evidence-list');
        toggle?.addEventListener('click', () => {
            const open = evidenceList?.classList.toggle('is-open') ?? false;
            toggle.textContent = open ? '▴ Hide Source Evidence' : '🔍 View Source Evidence';
        });

        void fetchSectorDrilldown(this.currentCenter).then((data) => {
            if (token !== this.investigationToken || !evidenceList) return;
            evidenceList.innerHTML = this.renderEvidenceItems(data);
        }).catch(() => {
            if (token !== this.investigationToken || !evidenceList) return;
            evidenceList.innerHTML = `<div class="mcn-evidence-item" style="color:#fca5a5;">Source evidence unavailable.</div>`;
        });
    }

    private renderEvidenceItems(data: DrilldownData | null): string {
        const seenUrls = new Set<string>();
        const seenTitles = new Set<string>();
        const rows = (data?.trigger_news || []).filter((n) => {
            const urlKey = (n.url || '').trim().toLowerCase();
            const titleKey = (n.headline || n.display_title || '').trim().toLowerCase().replace(/\s+/g, ' ');
            if (!urlKey && !titleKey) return false;
            if ((urlKey && seenUrls.has(urlKey)) || (titleKey && seenTitles.has(titleKey))) return false;
            if (urlKey) seenUrls.add(urlKey);
            if (titleKey) seenTitles.add(titleKey);
            return true;
        });
        if (!rows.length) {
            return `<div class="mcn-evidence-item">No raw trigger signals are available for this sector in the current window.</div>`;
        }
        return rows.slice(0, 8).map((n) => {
            const timeAgo = formatTime(n.timestamp);
            const title = n.url
                ? `<a href="${escHtml(n.url)}" target="_blank" rel="noopener noreferrer">${escHtml(n.headline)}</a>`
                : escHtml(n.headline);
            return `
                <div class="mcn-evidence-item">
                    <div style="display:flex;gap:8px;align-items:center;margin-bottom:5px;flex-wrap:wrap;">
                        <span style="color:${SEVERITY_COLOR[n.severity] || '#eab308'};font-weight:800;font-size:0.62rem;letter-spacing:0.08em;text-transform:uppercase;">
                            ${SEVERITY_ICON[n.severity] || '🟡'} ${TRIGGER_LABEL[n.trigger_type] || n.trigger_type}
                        </span>
                        <span style="color:#64748b;font-size:0.64rem;margin-left:auto;">${timeAgo}</span>
                    </div>
                    <div style="font-weight:700;color:#e2e8f0;">${title}</div>
                    <div style="margin-top:6px;color:#94a3b8;font-size:0.66rem;">
                        I=${n.intensity.toFixed(1)} · CF=${Math.round(n.fidelity_score * 100)}% · ${n.supporting_sources_count} src
                    </div>
                </div>
            `;
        }).join('');
    }

    private autoFocusTopTrend(): void {
        manualFocusEntityId = null;
        const nextCenter = this.pickInitialCenter();
        this.autoFocused = nextCenter;
        if (this.currentCenter === nextCenter) {
            this.render();
            return;
        }
        this.swapToCenter(nextCenter, { manual: false });
    }

    /**
     * Interactive orbit swap.
     *   1. Mutate `transform` on every node <g> to its new (lat/lng-free) target
     *      position — CSS transition handles the tween (0.42s).
     *   2. Fade the old edge layer to 0 in parallel.
     *   3. After the transition settles, do a clean redraw so the new centre's
     *      gradient, halo, edge labels, and analysis panel all reflect reality.
     */
    private swapToCenter(newCenter: string, options: { manual?: boolean } = { manual: true }): void {
        if (newCenter === this.currentCenter || this.animating) return;
        if (options.manual !== false) {
            manualFocusEntityId = newCenter;
        }
        this.animating = true;

        const svg = this.svgHost?.querySelector<SVGSVGElement>('svg.mcn-svg');
        if (!svg) {
            this.currentCenter = newCenter;
            this.render();
            this.animating = false;
            return;
        }

        const targetPositions = computeNexusPositions(newCenter, this.matrix);
        svg.querySelectorAll<SVGGElement>('g.mcn-node').forEach((g) => {
            const domain = g.getAttribute('data-domain');
            if (!domain) return;
            const p = targetPositions[domain];
            if (!p) return;
            g.setAttribute('transform', `translate(${p.x.toFixed(2)},${p.y.toFixed(2)})`);
        });

        // Hide edges during the transit — they will be rebuilt accurately by
        // the post-animation redraw.
        const edges = svg.querySelector<SVGGElement>('g.mcn-edges');
        edges?.classList.add('fading');

        // Subtle accent transition on the card border / glow during the swap.
        const card = this.container.querySelector<HTMLElement>('.mcn-card');
        if (card) {
            const nextColor = getTopicColor(newCenter);
            card.style.setProperty('--mcn-accent-primary', nextColor);
            card.style.setProperty('--mcn-accent-glow', `${nextColor}55`);
            card.style.setProperty('--mcn-accent-border',
                `color-mix(in srgb, ${nextColor} 38%, rgba(125,211,252,0.18))`);
        }

        window.setTimeout(() => {
            this.currentCenter = newCenter;
            this.render();
            this.animating = false;
        }, NEXUS_SWAP_MS + 40);
    }
}
