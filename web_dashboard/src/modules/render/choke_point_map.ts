/**
 * Choke-Point Fluid-Dynamics Map
 * ==============================
 *
 * Pure-SVG world map. Projects any number of nodes (maritime choke points,
 * flash-points, emerging flashpoints, etc.) via equirectangular projection.
 * Labels are placed using an in-memory force-directed simulation (AABB
 * repulsion + spring attraction) so there are ZERO hardcoded [dx,dy] offsets.
 * The simulation runs entirely in memory and the final settled positions are
 * committed to the DOM in one pass — no visual jitter.
 */
import { fetchChokePointFlow, type ChokePointNode, type ChokePointEdge } from '../api';

const STYLE_ID = 'choke-point-map-styles';
let activeContainerId: string | null = null;

// ─── Constants ───────────────────────────────────────────────────────────────

const SECTOR_LABELS: Record<string, string> = {
    energy_resource_risk:          'Energy',
    global_market_intelligence:    'Market',
    crypto_geopolitics:            'Crypto',
    ai_semiconductor_intelligence: 'AI/Semi',
    defense_technology:            'Defense',
    supply_chain_intelligence:     'Supply Chain',
};

const SECTOR_COLORS: Record<string, string> = {
    energy_resource_risk:          '#eab308',
    global_market_intelligence:    '#58a6ff',
    crypto_geopolitics:            '#f59e0b',
    ai_semiconductor_intelligence: '#bc8cff',
    defense_technology:            '#f87171',
    supply_chain_intelligence:     '#10b981',
};

// Map canvas dimensions
const MAP_W = 600;
const MAP_H = 300;

// Force simulation parameters
const SIM_ITERS      = 180;   // iterations to run before DOM commit
const LABEL_W        = 70;    // estimated label bounding-box width (px)
const LABEL_H        = 12;    // estimated label bounding-box height (px)
const REPULSE_DIST   = LABEL_W * 1.25; // repulsion between label centres
const NODE_REPULSE_R = 18;    // labels repel from node dots within this radius
const SPRING_REST    = 38;    // preferred distance label–node (px)
const SPRING_K       = 0.018; // spring stiffness
const REPULSE_K      = 320;   // repulsion coefficient
const DAMPING        = 0.82;  // velocity damping per step

// ─── Helpers ─────────────────────────────────────────────────────────────────

function escAttr(s: string): string {
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function project(lat: number, lng: number): { x: number; y: number } {
    return {
        x: ((lng + 180) / 360) * MAP_W,
        y: ((90 - lat) / 180) * MAP_H,
    };
}

function restrictionColor(r: number): string {
    if (r >= 0.75) return '#dc2626';
    if (r >= 0.50) return '#f59e0b';
    if (r >= 0.25) return '#22d3ee';
    return '#10b981';
}

function restrictionBadgeStyle(label: string): string {
    const map: Record<string, string> = {
        Severe:   'background:rgba(220,38,38,0.18); color:#fca5a5; border:1px solid rgba(220,38,38,0.55);',
        Elevated: 'background:rgba(245,158,11,0.18); color:#fde68a; border:1px solid rgba(245,158,11,0.50);',
        Moderate: 'background:rgba(56,189,248,0.18); color:#bae6fd; border:1px solid rgba(56,189,248,0.50);',
        Nominal:  'background:rgba(16,185,129,0.18); color:#6ee7b7; border:1px solid rgba(16,185,129,0.50);',
    };
    return map[label] || 'background:rgba(148,163,184,0.18); color:#cbd5e1; border:1px solid rgba(148,163,184,0.35);';
}

// ─── Force-Directed Label Placement ──────────────────────────────────────────
//
// Each label is treated as a point-mass living on the 2D map plane.
// We run a mini physics loop:
//   1. Repulsion between every pair of labels (inverse-square if close).
//   2. Repulsion away from every node DOT centre (so lines don't occlude dots).
//   3. Spring attraction back toward the label's own node anchor.
//   4. Velocity damping + boundary clamping.
//
// The loop runs SIM_ITERS times in memory.  Only the final (x,y) are used.

interface LabelState {
    // Anchor (fixed) — the projected node position
    ax: number;
    ay: number;
    // Current label centre position (evolves during sim)
    x: number;
    y: number;
    // Velocity
    vx: number;
    vy: number;
}

function initLabelStates(
    nodes: ChokePointNode[],
    projFn: (n: ChokePointNode) => { x: number; y: number },
): LabelState[] {
    return nodes.map((node, i) => {
        const { x: ax, y: ay } = projFn(node);
        // Deterministic initial offset — spiral out from the anchor so we
        // avoid all labels starting at the exact same point (which causes
        // degenerate zero-length repulsion vectors).
        const angle = (i / Math.max(nodes.length, 1)) * 2 * Math.PI - Math.PI / 2;
        const r = SPRING_REST;
        return {
            ax, ay,
            x: ax + r * Math.cos(angle),
            y: ay + r * Math.sin(angle),
            vx: 0, vy: 0,
        };
    });
}

function runSimulation(
    states: LabelState[],
    allNodePts: { x: number; y: number }[],
): void {
    for (let iter = 0; iter < SIM_ITERS; iter++) {
        // Adaptive cooling: reduce forces as we converge
        const cool = 1 - iter / (SIM_ITERS * 1.5);

        for (let i = 0; i < states.length; i++) {
            const s = states[i]!;
            let fx = 0;
            let fy = 0;

            // 1. Label–label repulsion (AABB-aware)
            for (let j = 0; j < states.length; j++) {
                if (i === j) continue;
                const t = states[j]!;
                const dx = s.x - t.x;
                const dy = s.y - t.y;
                const dist = Math.sqrt(dx * dx + dy * dy) || 0.001;
                if (dist < REPULSE_DIST) {
                    const strength = (REPULSE_K * cool) / (dist * dist);
                    fx += (dx / dist) * strength;
                    fy += (dy / dist) * strength;
                }
            }

            // 2. Node-dot repulsion (labels shouldn't sit on top of dots)
            for (const pt of allNodePts) {
                const dx = s.x - pt.x;
                const dy = s.y - pt.y;
                const dist = Math.sqrt(dx * dx + dy * dy) || 0.001;
                if (dist < NODE_REPULSE_R) {
                    const strength = (REPULSE_K * 0.6 * cool) / (dist * dist);
                    fx += (dx / dist) * strength;
                    fy += (dy / dist) * strength;
                }
            }

            // 3. Spring attraction toward own anchor
            const adx = s.ax - s.x;
            const ady = s.ay - s.y;
            const adist = Math.sqrt(adx * adx + ady * ady) || 0.001;
            const stretch = adist - SPRING_REST;
            fx += (adx / adist) * stretch * SPRING_K * (1 / cool + 0.2);
            fy += (ady / adist) * stretch * SPRING_K * (1 / cool + 0.2);

            // 4. Integrate
            s.vx = (s.vx + fx) * DAMPING;
            s.vy = (s.vy + fy) * DAMPING;
            s.x += s.vx;
            s.y += s.vy;

            // 5. Boundary clamping (keep labels inside map + margins)
            const margin = LABEL_H;
            s.x = Math.max(margin, Math.min(MAP_W - margin, s.x));
            s.y = Math.max(margin, Math.min(MAP_H - margin, s.y));
        }
    }
}

// ─── Styles ──────────────────────────────────────────────────────────────────

function injectStyles(): void {
    if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
        .cpm-card {
            display: flex;
            flex-direction: column;
            gap: 14px;
            padding: 18px 20px 16px;
            border-radius: 14px;
            background: linear-gradient(160deg, rgba(15,23,42,0.55), rgba(15,23,42,0.25));
            border: 1px solid var(--cpm-accent-border, rgba(125,211,252,0.18));
            backdrop-filter: blur(18px) saturate(140%);
            -webkit-backdrop-filter: blur(18px) saturate(140%);
            box-shadow:
                0 8px 28px rgba(2,6,23,0.45),
                inset 0 0 0 1px rgba(255,255,255,0.03);
            color: #cbd5e1;
        }
        .cpm-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 12px;
            flex-wrap: wrap;
        }
        .cpm-header h3 {
            margin: 0;
            font-size: 0.95rem;
            font-weight: 700;
            color: #e2e8f0;
        }
        .cpm-header .cpm-subtitle {
            font-size: 0.72rem;
            color: #94a3b8;
        }
        .cpm-meta {
            font-size: 0.66rem;
            color: #64748b;
            font-variant-numeric: tabular-nums;
        }
        .cpm-global-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 0.66rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #e2e8f0;
        }
        .cpm-global-badge[data-label="Severe"]   { background: rgba(220,38,38,0.20); color: #fca5a5; border:1px solid rgba(220,38,38,0.55); }
        .cpm-global-badge[data-label="Elevated"] { background: rgba(245,158,11,0.18); color: #fde68a; border:1px solid rgba(245,158,11,0.50); }
        .cpm-global-badge[data-label="Moderate"] { background: rgba(56,189,248,0.18); color: #bae6fd; border:1px solid rgba(56,189,248,0.50); }
        .cpm-global-badge[data-label="Nominal"]  { background: rgba(16,185,129,0.18); color: #6ee7b7; border:1px solid rgba(16,185,129,0.50); }

        .cpm-body {
            display: grid;
            grid-template-columns: 1.4fr 1fr;
            gap: 14px;
        }
        @media (max-width: 880px) {
            .cpm-body { grid-template-columns: 1fr; }
        }

        .cpm-svg-wrap {
            position: relative;
            border-radius: 12px;
            overflow: hidden;
            background:
                radial-gradient(circle at 30% 40%, rgba(56,189,248,0.10), transparent 50%),
                linear-gradient(160deg, rgba(2,6,23,0.85), rgba(15,23,42,0.55));
            border: 1px solid rgba(148,163,184,0.18);
            min-height: 280px;
        }
        .cpm-svg {
            width: 100%;
            height: 100%;
            display: block;
            overflow: visible;
        }
        .cpm-node {
            pointer-events: none;
            opacity: 1;
            transition: opacity 0.22s ease;
        }
        .cpm-node-layer.is-focusing .cpm-node:not(.is-hovered) {
            opacity: 0.25;
        }
        .cpm-node-layer.is-focusing .cpm-node.is-hovered {
            opacity: 1;
        }
        .cpm-map-bg,
        .cpm-node-halo,
        .cpm-node-ring,
        .cpm-node-callout,
        .cpm-node-label {
            pointer-events: none;
        }
        .cpm-node-callout {
            fill: none;
            stroke: rgba(226,232,240,0.42);
            stroke-width: 0.85;
            stroke-linecap: round;
            stroke-linejoin: round;
            filter: drop-shadow(0 0 4px rgba(125,211,252,0.28));
        }
        .cpm-node-dot {
            pointer-events: all;
            cursor: pointer;
            transition: stroke-width 0.16s ease, filter 0.16s ease, opacity 0.16s ease;
        }
        .cpm-node-dot:hover,
        .cpm-node.focused .cpm-node-dot {
            stroke: #e2e8f0;
            stroke-width: 1.8;
            opacity: 0.96;
        }
        .cpm-node-label {
            font-family: Inter, system-ui, sans-serif;
            font-size: 8px;
            fill: #e2e8f0;
            font-weight: 700;
            text-shadow: 0 1px 4px rgba(0,0,0,0.6);
            paint-order: stroke fill;
            stroke: rgba(2,6,23,0.85);
            stroke-width: 2px;
            stroke-linejoin: round;
            dominant-baseline: central;
        }

        /* Detail panel */
        .cpm-detail {
            display: flex;
            flex-direction: column;
            gap: 10px;
            padding: 12px 14px;
            border-radius: 10px;
            background: rgba(2,6,23,0.45);
            border: 1px solid rgba(148,163,184,0.18);
            min-height: 240px;
        }
        .cpm-detail.empty {
            align-items: center;
            justify-content: center;
            color: #64748b;
            text-align: center;
            font-size: 0.78rem;
            min-height: 240px;
        }
        .cpm-detail-head {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 8px;
        }
        .cpm-detail-name {
            font-size: 0.92rem;
            font-weight: 700;
            color: #e2e8f0;
        }
        .cpm-detail-restriction {
            font-size: 0.66rem;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 999px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .cpm-detail-desc {
            font-size: 0.74rem;
            color: #94a3b8;
            line-height: 1.5;
        }
        .cpm-detail-stats {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 6px;
        }
        .cpm-detail-stat {
            padding: 6px 8px;
            background: rgba(15,23,42,0.55);
            border: 1px solid rgba(148,163,184,0.16);
            border-radius: 6px;
        }
        .cpm-detail-stat .k {
            font-size: 0.60rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .cpm-detail-stat .v {
            font-size: 0.86rem;
            font-weight: 700;
            color: #e2e8f0;
            font-variant-numeric: tabular-nums;
        }
        .cpm-detail-sectors {
            display: flex;
            flex-direction: column;
            gap: 4px;
            margin-top: 4px;
        }
        .cpm-detail-sector {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 6px 8px;
            border-radius: 6px;
            background: var(--sector-bg, rgba(148,163,184,0.10));
            border-left: 3px solid var(--sector-color, #94a3b8);
            font-size: 0.72rem;
        }
        .cpm-detail-sector .sector-name { color: #e2e8f0; font-weight: 600; }
        .cpm-detail-sector .sector-drag {
            color: var(--sector-color, #94a3b8);
            font-weight: 700;
            font-variant-numeric: tabular-nums;
        }

        .cpm-status {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 220px;
            font-size: 0.85rem;
            color: #94a3b8;
        }
        .cpm-status.error { color: #fca5a5; }
    `;
    document.head.appendChild(style);
}

// ─── SVG Builder ─────────────────────────────────────────────────────────────

function buildSvg(
    nodes: ChokePointNode[],
    onSelect: (n: ChokePointNode) => void,
    root: HTMLElement,
): void {
    const NS = 'http://www.w3.org/2000/svg';

    // ── 1. Pre-compute projected node positions ───────────────────────────
    const nodePts = nodes.map((n) => project(n.lat, n.lng));

    // ── 2. Run force-directed label simulation (100% in memory) ──────────
    const labelStates = initLabelStates(nodes, (n) => project(n.lat, n.lng));
    runSimulation(labelStates, nodePts);

    // ── 3. Build SVG (one DOM pass, no jitter) ────────────────────────────
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'cpm-svg');
    svg.setAttribute('viewBox', `0 0 ${MAP_W} ${MAP_H}`);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');

    // Defs
    const defs = document.createElementNS(NS, 'defs');
    defs.innerHTML = `
        <radialGradient id="cpm-node-glow" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0%" stop-color="currentColor" stop-opacity="0.55"/>
            <stop offset="100%" stop-color="currentColor" stop-opacity="0"/>
        </radialGradient>
        <filter id="cpm-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.5" result="blur"/>
            <feMerge>
                <feMergeNode in="blur"/>
                <feMergeNode in="SourceGraphic"/>
            </feMerge>
        </filter>
    `;
    svg.appendChild(defs);

    // Geographic grid
    const grid = document.createElementNS(NS, 'g');
    grid.setAttribute('class', 'cpm-map-bg');
    grid.setAttribute('stroke', 'rgba(148,163,184,0.10)');
    grid.setAttribute('stroke-width', '0.5');
    grid.setAttribute('fill', 'none');
    for (let lng = -180; lng <= 180; lng += 30) {
        const { x } = project(0, lng);
        grid.innerHTML += `<line x1="${x.toFixed(1)}" y1="0" x2="${x.toFixed(1)}" y2="${MAP_H}"/>`;
    }
    for (let lat = -60; lat <= 60; lat += 30) {
        const { y } = project(lat, 0);
        grid.innerHTML += `<line x1="0" y1="${y.toFixed(1)}" x2="${MAP_W}" y2="${y.toFixed(1)}"/>`;
    }
    const { y: eqY } = project(0, 0);
    grid.innerHTML += `<line x1="0" y1="${eqY.toFixed(1)}" x2="${MAP_W}" y2="${eqY.toFixed(1)}" stroke="rgba(125,211,252,0.18)" stroke-width="1"/>`;
    svg.appendChild(grid);

    // Continent silhouettes
    const landHints = document.createElementNS(NS, 'g');
    landHints.setAttribute('class', 'cpm-map-bg');
    landHints.setAttribute('fill', 'rgba(148,163,184,0.07)');
    landHints.innerHTML = `
        <!-- North America -->
        <path d="M 80 70 L 180 55 L 200 110 L 140 145 L 70 130 Z"/>
        <!-- South America -->
        <path d="M 160 160 L 200 180 L 195 240 L 155 250 L 145 200 Z"/>
        <!-- Europe + Africa -->
        <path d="M 280 70 L 330 60 L 360 90 L 360 165 L 320 240 L 295 230 L 290 160 Z"/>
        <!-- Asia -->
        <path d="M 340 55 L 480 50 L 510 100 L 470 145 L 420 130 L 380 105 Z"/>
        <!-- Australia -->
        <path d="M 470 195 L 525 195 L 525 225 L 475 230 Z"/>
    `;
    svg.appendChild(landHints);

    // ── 4. Node layer ─────────────────────────────────────────────────────
    const nodeLayer = document.createElementNS(NS, 'g');
    nodeLayer.setAttribute('class', 'cpm-node-layer');

    for (let i = 0; i < nodes.length; i++) {
        const node      = nodes[i]!;
        const { x, y }  = nodePts[i]!;
        const ls        = labelStates[i]!;
        const color     = restrictionColor(node.restriction);
        const haloR     = 9 + node.restriction * 28;
        const dotR      = 3.4 + node.restriction * 3.1;

        const g = document.createElementNS(NS, 'g');
        g.setAttribute('class', 'cpm-node');
        // NOTE: node group lives at map origin; we use absolute coords for
        // the callout because label positions come from the sim (map space).
        g.setAttribute('data-node-id', node.id);
        g.style.color = color;

        // Water-ripple pulse ring (restriction >= Moderate)
        if (node.restriction >= 0.25) {
            const pulseStartR = dotR + 1.6;
            const ring = document.createElementNS(NS, 'circle');
            ring.setAttribute('class', 'cpm-node-ring');
            ring.setAttribute('cx', x.toFixed(2));
            ring.setAttribute('cy', y.toFixed(2));
            ring.setAttribute('r', pulseStartR.toFixed(2));
            ring.setAttribute('opacity', '0');
            ring.setAttribute('pointer-events', 'none');
            ring.setAttribute('fill', 'none');
            ring.setAttribute('stroke', color);
            ring.setAttribute('stroke-opacity', '0');
            ring.setAttribute('stroke-width', '1');
            ring.setAttribute('filter', 'url(#cpm-glow)');

            const rAnim = document.createElementNS(NS, 'animate');
            rAnim.setAttribute('attributeName', 'r');
            rAnim.setAttribute('from', pulseStartR.toFixed(2));
            rAnim.setAttribute('to', haloR.toFixed(2));
            rAnim.setAttribute('dur', '2.8s');
            rAnim.setAttribute('repeatCount', 'indefinite');
            rAnim.setAttribute('calcMode', 'spline');
            rAnim.setAttribute('keyTimes', '0;1');
            rAnim.setAttribute('keySplines', '0.22 1 0.36 1');
            ring.appendChild(rAnim);

            const oAnim = document.createElementNS(NS, 'animate');
            oAnim.setAttribute('attributeName', 'opacity');
            oAnim.setAttribute('values', '0.72;0');
            oAnim.setAttribute('dur', '2.8s');
            oAnim.setAttribute('repeatCount', 'indefinite');
            oAnim.setAttribute('calcMode', 'spline');
            oAnim.setAttribute('keyTimes', '0;1');
            oAnim.setAttribute('keySplines', '0.22 1 0.36 1');
            ring.appendChild(oAnim);

            const soAnim = document.createElementNS(NS, 'animate');
            soAnim.setAttribute('attributeName', 'stroke-opacity');
            soAnim.setAttribute('values', '0.62;0');
            soAnim.setAttribute('dur', '2.8s');
            soAnim.setAttribute('repeatCount', 'indefinite');
            soAnim.setAttribute('calcMode', 'spline');
            soAnim.setAttribute('keyTimes', '0;1');
            soAnim.setAttribute('keySplines', '0.22 1 0.36 1');
            ring.appendChild(soAnim);

            g.appendChild(ring);
        }

        // Core dot (absolute map coords — no group transform needed)
        const dot = document.createElementNS(NS, 'circle');
        dot.setAttribute('class', 'cpm-node-dot');
        dot.setAttribute('cx', x.toFixed(2));
        dot.setAttribute('cy', y.toFixed(2));
        dot.setAttribute('r', dotR.toFixed(2));
        dot.setAttribute('fill', color);
        dot.setAttribute('filter', 'url(#cpm-glow)');
        dot.setAttribute('tabindex', '0');
        dot.setAttribute('role', 'button');
        dot.setAttribute('aria-label', node.label);
        g.appendChild(dot);

        // ── Dynamic HUD callout (force-settled position) ──────────────────
        // The callout is a two-segment polyline: node → elbow → label end.
        // The elbow is at the midpoint between the node and the settled label
        // centre, offset vertically for a "stepped" HUD aesthetic.
        const lx = ls.x;  // settled label centre x (map space)
        const ly = ls.y;  // settled label centre y (map space)

        // Elbow: halfway horizontally, at label's y-level
        const elbowX = (x + lx) / 2;
        const elbowY = ly;

        const calloutLine = document.createElementNS(NS, 'polyline');
        calloutLine.setAttribute('class', 'cpm-node-callout');
        calloutLine.setAttribute(
            'points',
            `${x.toFixed(1)},${y.toFixed(1)} ${elbowX.toFixed(1)},${elbowY.toFixed(1)} ${lx.toFixed(1)},${ly.toFixed(1)}`,
        );
        g.appendChild(calloutLine);

        // Determine label anchor: if label is to the right of elbow, start;
        // if to the left, end — so text never overlaps the line terminus.
        const labelAnchor = lx >= elbowX ? 'start' : 'end';
        const labelOffX   = lx >= elbowX ? lx + 3 : lx - 3;

        const text = document.createElementNS(NS, 'text');
        text.setAttribute('class', 'cpm-node-label');
        text.setAttribute('x', labelOffX.toFixed(1));
        text.setAttribute('y', (ly - 4).toFixed(1));
        text.setAttribute('text-anchor', labelAnchor);
        text.textContent = node.label;
        g.appendChild(text);

        // ── Interaction ───────────────────────────────────────────────────
        const setHoverFocus = (active: boolean) => {
            nodeLayer.classList.toggle('is-focusing', active);
            g.classList.toggle('is-hovered', active);
        };

        dot.addEventListener('click', () => {
            root.querySelectorAll('.cpm-node.focused').forEach((el) => el.classList.remove('focused'));
            g.classList.add('focused');
            onSelect(node);
        });
        dot.addEventListener('mouseenter', () => { setHoverFocus(true); onSelect(node); });
        dot.addEventListener('mouseleave', () => setHoverFocus(false));
        dot.addEventListener('focus',      () => { setHoverFocus(true); onSelect(node); });
        dot.addEventListener('blur',       () => setHoverFocus(false));
        dot.addEventListener('keydown', (event) => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            root.querySelectorAll('.cpm-node.focused').forEach((el) => el.classList.remove('focused'));
            g.classList.add('focused');
            onSelect(node);
        });

        nodeLayer.appendChild(g);
    }

    svg.appendChild(nodeLayer);
    root.innerHTML = '';
    root.appendChild(svg);
}

// ─── Detail Panel ─────────────────────────────────────────────────────────────

function renderDetailEmpty(detail: HTMLElement): void {
    detail.classList.add('empty');
    detail.innerHTML = 'Hover or click any node to inspect its physical flow, viscosity, and downstream sector drag.';
}

function renderDetail(detail: HTMLElement, node: ChokePointNode, edges: ChokePointEdge[]): void {
    detail.classList.remove('empty');
    const badgeStyle   = restrictionBadgeStyle(node.restriction_label);
    const matchingEdges = edges.filter((e) => e.from_node === node.id);

    const sectorRows = matchingEdges.length
        ? matchingEdges.map((e) => {
              const color   = SECTOR_COLORS[e.sector] || '#94a3b8';
              const label   = SECTOR_LABELS[e.sector] || e.sector;
              const bg      = `color-mix(in srgb, ${color} 14%, rgba(2,6,23,0.55))`;
              const dragPct = `${Math.round(e.drag * 100)}%`;
              return `<div class="cpm-detail-sector"
                  style="--sector-color:${color}; --sector-bg:${bg};"
                  title="${escAttr(e.explanation)}">
                  <span class="sector-name">${escAttr(label)}</span>
                  <span class="sector-drag">${dragPct} drag</span>
              </div>`;
          }).join('')
        : '<div style="font-size:0.72rem; color:#64748b;">No downstream sectors mapped.</div>';

    const alertRows = node.matched_alerts.length
        ? node.matched_alerts.slice(0, 4).map((a) => {
              const label = a.target_label || a.topic || 'Signal';
              return `<li style="font-size:0.70rem; color:#cbd5e1;">${escAttr(label)} <span style="color:#64748b;">(I=${a.intensity.toFixed(1)})</span></li>`;
          }).join('')
        : '';

    detail.innerHTML = `
        <div class="cpm-detail-head">
            <span class="cpm-detail-name">${escAttr(node.label)}</span>
            <span class="cpm-detail-restriction" style="${badgeStyle}">
                ${escAttr(node.restriction_label)} · ${Math.round(node.restriction * 100)}%
            </span>
        </div>
        <div class="cpm-detail-desc">${escAttr(node.description || '')}</div>
        <div class="cpm-detail-stats">
            <div class="cpm-detail-stat">
                <div class="k">Throughput</div>
                <div class="v">${node.daily_volume_mbpd.toFixed(1)} mbpd</div>
            </div>
            <div class="cpm-detail-stat">
                <div class="k">Viscosity</div>
                <div class="v">${node.viscosity.toFixed(2)}</div>
            </div>
            <div class="cpm-detail-stat">
                <div class="k">Alerts (24h)</div>
                <div class="v">${node.matched_alert_count}</div>
            </div>
        </div>
        <div>
            <div style="font-size:0.62rem; color:#64748b; text-transform:uppercase; letter-spacing:0.08em; margin:6px 0 4px;">Downstream Sector Drag</div>
            <div class="cpm-detail-sectors">${sectorRows}</div>
        </div>
        ${alertRows
            ? `<div>
                <div style="font-size:0.62rem; color:#64748b; text-transform:uppercase; letter-spacing:0.08em; margin:6px 0 4px;">Recent Matched Alerts</div>
                <ul style="margin:0; padding-left:18px;">${alertRows}</ul>
            </div>` : ''}
    `;
}

// ─── Load & Paint ─────────────────────────────────────────────────────────────

async function loadAndPaint(card: HTMLElement): Promise<void> {
    setStatus(card, '<span class="animate-pulse">Loading choke-point fluid model…</span>');
    const data = await fetchChokePointFlow();
    if (!data) {
        setStatus(card, 'Choke-point endpoint unavailable.', true);
        return;
    }
    const ts      = new Date(data.generated_at);
    const tsLabel = isNaN(ts.getTime()) ? data.generated_at : ts.toLocaleTimeString();
    card.innerHTML = `
        <div class="cpm-header">
            <div>
                <h3>Fluid-Dynamics Choke-Point Analyzer</h3>
                <div class="cpm-subtitle">
                    Viscosity (OSINT intensity) ÷ Physical Q → restriction factor. Click a node to inspect downstream drag.
                    <span style="color:#64748b;"> · ${data.nodes.length} node${data.nodes.length !== 1 ? 's' : ''} active</span>
                </div>
            </div>
            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                <span class="cpm-global-badge" data-label="${escAttr(data.global_restriction_label)}">
                    Global: ${escAttr(data.global_restriction_label)} · ${Math.round(data.global_restriction * 100)}%
                </span>
                <span class="cpm-meta">Window ${data.window_hours}h · baseline V=${data.baseline_viscosity} · ${tsLabel}</span>
            </div>
        </div>
        <div class="cpm-body">
            <div class="cpm-svg-wrap" id="cpm-svg-host"></div>
            <div class="cpm-detail" id="cpm-detail"></div>
        </div>
    `;

    const svgHost = card.querySelector<HTMLElement>('#cpm-svg-host')!;
    const detail  = card.querySelector<HTMLElement>('#cpm-detail')!;
    renderDetailEmpty(detail);

    buildSvg(data.nodes, (n) => renderDetail(detail, n, data.edges), svgHost);

    // Auto-focus the most-restricted node so the detail panel is informative on load.
    const top = [...data.nodes].sort((a, b) => b.restriction - a.restriction)[0];
    if (top) {
        renderDetail(detail, top, data.edges);
        svgHost.querySelector(`.cpm-node[data-node-id="${CSS.escape(top.id)}"]`)?.classList.add('focused');
    }
}

function setStatus(card: HTMLElement, html: string, isError = false): void {
    card.innerHTML = `<div class="cpm-status ${isError ? 'error' : ''}">${html}</div>`;
}

// ─── Public API ───────────────────────────────────────────────────────────────

export async function renderChokePointMap(containerId: string): Promise<void> {
    const container = document.getElementById(containerId);
    if (!container) return;
    injectStyles();
    container.innerHTML = `<div class="cpm-card" id="${containerId}-card"></div>`;
    const card = container.querySelector<HTMLElement>(`#${CSS.escape(containerId)}-card`);
    if (!card) return;
    activeContainerId = containerId;
    await loadAndPaint(card);
}

export async function refreshChokePointMap(): Promise<void> {
    if (!activeContainerId) return;
    const container = document.getElementById(activeContainerId);
    if (!container) return;
    const card = container.querySelector<HTMLElement>(`#${CSS.escape(activeContainerId)}-card`);
    if (!card || !document.body.contains(card)) return;
    await loadAndPaint(card);
}
