/**
 * Spatial Contagion Network — Interactive Map Component
 *
 * Integration architecture (deck.gl v9.3.2 + MapLibre GL JS v4):
 *
 *   • @deck.gl/mapbox v9 does NOT export `MapboxLayer` (removed in v9).
 *     The production-grade equivalent is `MapboxOverlay({ interleaved: true })`.
 *   • interleaved:true → deck.gl's _onAddInterleaved() extracts MapLibre's native
 *     WebGL2 context via `map.painter.context.gl`, creates a shared-context Deck
 *     instance, and registers each layer as a MapLibre custom layer internally via
 *     `map.addLayer()`. No separate canvas, no manual view-state sync.
 *   • The overlay is added via `map.addControl(overlay)` INSIDE the `load` event
 *     callback so that `map.painter` is guaranteed to be initialised.
 *   • Edge coordinates are pre-computed (source_lon/lat, target_lon/lat) because
 *     deck.gl cannot perform ID lookups automatically.
 */

import { apiClient } from '../api';

const LOG = '[SpatialContagion]';
const GLOBAL_DOMAIN_ID = 'global';

/**
 * Phase 4 — Dynamic Domain Routing registry.
 *
 * The sidebar renders one row per entry; the controller uses `id` to call
 * `apiClient.get('/pro/domains/{id}/fragility-history')` (except for
 * `global`, which is an in-memory aggregation of all cached domain payloads).
 *
 * The order of this array is the display order. `global` MUST stay first
 * because the sidebar treats index 0 as the aggregate root.
 */
type DomainRegistryEntry = {
    id: string;
    label: string;
    icon: string;       // emoji OR the literal "SYNC" sentinel for the Global SVG glyph
    accent: string;
    isAggregate?: boolean;
};
/**
 * A vault scenario cascade, from GET /pro/domains/scenarios.
 *
 * These are NOT domains: they are standalone structural graphs and must be
 * selected EXCLUSIVELY. Merging Hormuz with Malacca would produce a graph that
 * describes no event that has ever happened.
 */
export type ScenarioMeta = {
    id: string;            // the domain_id, e.g. 'strait_of_hormuz'
    hub: string;           // 'Strait_of_Hormuz'
    hub_type?: string;
    label?: string;        // derived: 'Strait of Hormuz'
    aliases?: string[];    // e.g. ['ホルムズ海峡', 'Strait of Hormuz', 'Hormuz']
    domain?: string[];
    node_count?: number;
    edge_count?: number;
};


const DOMAIN_REGISTRY: DomainRegistryEntry[] = [
    { id: 'global',                          label: 'Global',   icon: 'SYNC', accent: '#22d3ee', isAggregate: true },
    { id: 'energy_resource_risk',            label: 'Energy',   icon: '⛽',   accent: '#eab308' },
    { id: 'global_market_intelligence',      label: 'Markets',  icon: '📈',   accent: '#58a6ff' },
    { id: 'ai_semiconductor_intelligence',   label: 'AI-Semi',  icon: '🤖',   accent: '#bc8cff' },
    { id: 'supply_chain_intelligence',       label: 'Shipping', icon: '🚢',   accent: '#10b981' },
    { id: 'defense_technology',              label: 'Defense',  icon: '🛡',   accent: '#f87171' },
    { id: 'crypto_geopolitics',              label: 'Crypto',   icon: '⚡',   accent: '#f59e0b' },
];
const SPECIALIZED_DOMAIN_IDS = DOMAIN_REGISTRY
    .filter((d) => !d.isAggregate)
    .map((d) => d.id);

/**
 * Phase 7.2 — Map the frontend's long domain ids onto the short ids the
 * Spatial Engine (`spatial_nodes.domain_id`) was seeded with. The cache /
 * sidebar continue using the long form so the Pro Report system stays
 * unaffected; only the live-spatial network call swaps in the short alias.
 *
 * Domains absent from this table are queried as-is. The map is also used
 * by /spatial-contagion + /fragility-history on the wire.
 */
const SPATIAL_DOMAIN_ALIAS: Record<string, string> = {
    energy_resource_risk: 'energy',
    supply_chain_intelligence: 'shipping',
};
function toSpatialDomainId(domainId: string): string {
    return SPATIAL_DOMAIN_ALIAS[domainId] ?? domainId;
}

// credit_gaps[].kind -> customer-facing copy. The payload's `reason` is the PD slice's own
// text and is NOT rendered: it is pipeline vocabulary ("EXCLUDE:", "BY-DESIGN", "PD~0 FLAG",
// and an internal filename) written for the vault's own filter, not for a reader. `kind` is
// the stable key — a closed set of five, enforced at the emitter, which exits rather than
// invent a sixth (export_scenarios.py:304-329). Wording follows credit.basis: state the
// condition, pass no verdict.
// ★ kind is COARSER than reason: three slice reasons (market_cap null / equity_volatility
//   null / no total_liabilities) collapse onto honest_null_unsourced. Today only the first
//   occurs, so the copy below is accurate; if the others ever reach a panel the split belongs
//   at the emitter, not here — this file must not become the arbiter of provenance.
const CREDIT_GAP_COPY: Record<string, string> = {
    severed_no_traded_equity: 'No traded equity — Merton not applicable',
    private_valuation:        'Unlisted — no traded market capitalisation',
    net_cash_no_debt:         'Net cash — Merton premise does not hold',
    honest_null_unsourced:    'Market capitalisation not sourced',
    absent_from_slice:        'No financial data on file',
};
const CREDIT_GAP_COPY_FALLBACK = 'No credit figure available';
function creditGapCopy(kind?: string): string {
    return (kind ? CREDIT_GAP_COPY[kind] : undefined) ?? CREDIT_GAP_COPY_FALLBACK;
}


// ── Types ─────────────────────────────────────────────────────────────────────
/** Network-theoretic depth of a contagion node (1 = epicenter, 3 = 2-hop downstream). */
export type ContagionOrder = 1 | 2 | 3;

export type SpatialNode = {
    id: string;
    name: string;
    raw_input?: string;
    lat: number;
    lon: number;
    country?: string;
    impact_score: number;
    /**
     * 'exposed_unquantified' — structurally exposed to the hub, but the magnitude
     * is UNKNOWN (payload carries impact_score: null). It is NOT a low-impact node.
     * Never let it reach the affected colour ramp: 0 would read as "benign".
     */
    type: 'epicenter' | 'affected' | 'exposed_unquantified';
    /** True when the payload's impact_score was null. Survives the `?? 0` coercion below. */
    unquantified?: boolean;
    /** Payload-supplied rationale, e.g. "structurally exposed via X; magnitude unknown". */
    why?: string;
    /** True position, preserved when applyColocationOffsets() fans a co-located
     *  group onto a display ring. lat/lon may be the DISPLAY position; these are
     *  the real ones and are what the tooltip must report. */
    trueLat?: number;
    trueLon?: number;
    /** Phase 2 — N-th Order Impact. Optional on payloads older than spatial_contagion_v2. */
    order?: ContagionOrder;
    /**
     * 0.0–1.0. DATA, not presentation — the producer emits a number and the badge
     * formats it. (Was typed `string`, which forced producers to pre-render "100%"
     * and made a real 0.0 indistinguishable from "absent" under a truthiness check.)
     */
    confidence?: number;
    geonameid?: number;
    /** Per-company detail merged onto the node by the API from the scenario JSON (whitelist-only:
     *  the DB has no column for these). Present ONLY on affected company nodes; absent on the
     *  epicenter, exposed nodes, and company-less affected nodes (countries/routes). */
    title?: string;
    role_blurb?: string;
    financials?: Record<string, { value: number; unit: string; source: string; as_of: string }>;
    neighbourhood?: Array<{ target: string; type: string; role: string | null; weight: number | null; unit: string | null }>;
};

export type SpatialEdge = {
    source_id: string;
    target_id: string;
    intensity: number;
    /** True when the payload's intensity was null (unknown magnitude, not zero). */
    unquantified?: boolean;
    /** Mirrors the target node's order so the frontend can split layers without re-joining. */
    target_order?: ContagionOrder;
    /** Omni-aggregate — originating Pro domain (Energy, Shipping, …). */
    domain_id?: string;
};

/** Placeless payload fields — coordinate-less nodes the map cannot show. Passed through
 *  verbatim by the API from the scenario JSON; raw_impact/weight may be null (never 0). */
export type Conduit = { commodity: string; weight: number | null; unit: string };
export type OffMapNode = { id: string; type?: string; raw_impact: number | null; reason?: string };
export type HonestGaps = {
    exposed_null?: Array<{ id: string; role?: string }>;
    node_gaps?: Array<{ id: string; impact?: number | null; reason?: string }>;
};

export type SpatialContagion = {
    nodes: SpatialNode[];
    edges: SpatialEdge[];
    epicenter_impact_score: number;
    edge_intensity: number;
    node_count?: number;
    edge_count?: number;
    schema_version?: string;
    warning?: string;
    /** Coordinate-less nodes / conduits / model gaps — present only for scenario domains. */
    conduits?: Conduit[];
    no_map?: OffMapNode[];
    honest_gaps?: HonestGaps;
    /** v2 payload — counts per order (1/2/3). Drives sidebar mini-text. */
    order_counts?: {
        order_1?: number;
        order_2?: number;
        order_3?: number;
    };
    /** Payload-embedded fragility scalars — seed the animation when no
     *  /fragility-history polling is available (e.g. Global aggregate). */
    entropy_index?: number | null;
    viscosity_coefficient?: number | null;
};

// Edge with pre-resolved lat/lon (required by ArcLayer — IDs are not auto-joined)
type ResolvedEdge = {
    source_lon: number;
    source_lat: number;
    target_lon: number;
    target_lat: number;
    intensity: number;
    /** True when the payload's intensity was null — rendered grey/dashed, never as a weak arc. */
    unquantified?: boolean;
    /** target node order (1/2/3) — drives per-layer visual scaling. */
    target_order: ContagionOrder;
    /** Omni-aggregate — Pro domain that owns this arc. */
    domain_id?: string;
    /** Per-domain lane lift + micro positional offset for overlapping routes. */
    lane_offset?: number;
};

/** Phase 7.11 — additive arc compositing for multi-domain Global view. */
const GL_SRC_ALPHA = 0x0302;
const GL_ONE = 0x0001;
const GL_FUNC_ADD = 0x8006;
const ARC_AGGREGATE_OPACITY = 0.6;
const ARC_AGGREGATE_BLEND = {
    blend: true,
    blendFunc: [GL_SRC_ALPHA, GL_ONE] as [number, number],
    blendEquation: GL_FUNC_ADD,
    depthTest: false,
};

function hexToRgb(hex: string): [number, number, number] {
    const normalized = hex.replace('#', '').trim();
    const full = normalized.length === 3
        ? normalized.split('').map((c) => c + c).join('')
        : normalized;
    const n = parseInt(full, 16);
    if (!Number.isFinite(n)) return [239, 68, 68];
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function domainAccentRgb(domainId?: string): [number, number, number] {
    const entry = DOMAIN_REGISTRY.find((d) => d.id === domainId);
    return entry ? hexToRgb(entry.accent) : [239, 68, 68];
}

function domainIdFromPrefixedId(prefixedId: string): string | undefined {
    const sep = prefixedId.indexOf('__');
    if (sep <= 0) return undefined;
    const prefix = prefixedId.slice(0, sep);
    return SPECIALIZED_DOMAIN_IDS.find((d) => safeId(d) === prefix);
}

/** Lane separation in degrees — visible as parallel tracks at world zoom. */
function domainLaneOffset(domainId: string | undefined): number {
    if (!domainId) return 0;
    const idx = SPECIALIZED_DOMAIN_IDS.indexOf(domainId);
    if (idx < 0) return 0;
    const center = (SPECIALIZED_DOMAIN_IDS.length - 1) / 2;
    const span = Math.max(1, SPECIALIZED_DOMAIN_IDS.length - 1);
    return ((idx - center) / span) * 2.2;
}

/** Shift arc endpoints perpendicular to the chord — multi-lane highway effect. */
function applyArcLaneOffset(
    srcLon: number,
    srcLat: number,
    tgtLon: number,
    tgtLat: number,
    laneDeg: number,
): { source_lon: number; source_lat: number; target_lon: number; target_lat: number } {
    if (!laneDeg) {
        return { source_lon: srcLon, source_lat: srcLat, target_lon: tgtLon, target_lat: tgtLat };
    }
    const dLon = tgtLon - srcLon;
    const dLat = tgtLat - srcLat;
    const len = Math.hypot(dLon, dLat) || 1;
    const perpLon = (-dLat / len) * laneDeg;
    const perpLat = (dLon / len) * laneDeg;
    return {
        source_lon: srcLon + perpLon,
        source_lat: srcLat + perpLat,
        target_lon: tgtLon + perpLon,
        target_lat: tgtLat + perpLat,
    };
}

function resolveDomainForEdge(edge: SpatialEdge, sourceId: string, targetId: string): string | undefined {
    return edge.domain_id ?? domainIdFromPrefixedId(sourceId) ?? domainIdFromPrefixedId(targetId);
}

function buildResolvedEdge(
    edge: SpatialEdge,
    src: SpatialNode,
    tgt: SpatialNode,
    isAggregate: boolean,
): ResolvedEdge {
    const targetOrder = (edge.target_order ?? tgt.order ?? 2) as ContagionOrder;
    const domain_id = resolveDomainForEdge(edge, edge.source_id, edge.target_id);
    const lane_offset = isAggregate ? domainLaneOffset(domain_id) : 0;
    const shifted = isAggregate
        ? applyArcLaneOffset(src.lon, src.lat, tgt.lon, tgt.lat, lane_offset)
        : { source_lon: src.lon, source_lat: src.lat, target_lon: tgt.lon, target_lat: tgt.lat };
    return {
        ...shifted,
        intensity: edge.intensity,
        unquantified: edge.unquantified === true,
        target_order: targetOrder,
        domain_id,
        lane_offset,
    };
}

// ── Unquantified ("structurally exposed, magnitude unknown") styling ──────────
//
// These nodes/edges arrive with impact_score / intensity === null. After the
// `?? 0` coercion they would otherwise render as small cyan dots and hairline
// arcs — i.e. visually IDENTICAL to a genuinely negligible impact. That is a
// lie, so they get their own grey, hollow, pseudo-dashed treatment and are
// excluded from the affected colour ramp and the epicenter styling entirely.
const UNQ_NODE_STROKE: [number, number, number, number] = [148, 163, 184, 220]; // slate — hollow ring
const UNQ_ARC_RGBA: [number, number, number, number] = [148, 163, 184, 120];    // slate — faint arc
const UNQ_NODE_RADIUS_M = 16_000;   // FIXED: never scale a meaningless 0
const UNQ_ARC_WIDTH = 1.2;          // FIXED: never scale a meaningless 0

// ── Co-located node fan-out (display-time only) ───────────────────────────────
//
// Real payloads put many entities on ONE point: 7 companies share Tokyo's
// (35.7, 139.7), 6 share Beijing's (39.9, 116.4). Drawn at their true coords
// they collapse into a single blob — unreadable and unclickable.
//
// The SOURCE DATA IS NEVER MUTATED. We fan the members of a co-located group
// onto a small circle around the true point at DISPLAY time and stash the real
// position on `trueLat`/`trueLon` so the tooltip still reports the truth.
// Arc endpoints follow automatically: resolveEdgesFlat() reads the node objects,
// so offsetting a node offsets every arc touching it (otherwise arcs would point
// at empty space).
//
// The ring radius is ZOOM-AWARE — it is sized in METRES from the current
// metres-per-pixel so the on-screen separation stays ~constant as you zoom.
// The epicenter is NEVER displaced: it anchors its own point.
const COLOCATION_PIXEL_GAP = 30;      // target on-screen separation, px
const COLOCATION_MIN_M = 6_000;
const COLOCATION_MAX_M = 220_000;

/** Web-Mercator ground resolution at a given latitude/zoom. */
function metresPerPixel(lat: number, zoom: number): number {
    return (156543.03392 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, zoom);
}

/**
 * Returns a NEW node array in which co-located nodes are fanned onto a ring.
 * Never mutates the input. Pure function of (nodes, zoom) → deterministic.
 */
function applyColocationOffsets(nodes: SpatialNode[], zoom: number): SpatialNode[] {
    const groups = new Map<string, SpatialNode[]>();
    for (const n of nodes) {
        // ~2dp ≈ 1.1 km — anything closer is "the same point" for display purposes.
        const key = `${n.lat.toFixed(2)}|${n.lon.toFixed(2)}`;
        const bucket = groups.get(key);
        if (bucket) bucket.push(n);
        else groups.set(key, [n]);
    }

    const out: SpatialNode[] = [];
    for (const members of groups.values()) {
        const anchored = members.filter((n) => n.type === 'epicenter');
        const movable = members.filter((n) => n.type !== 'epicenter');

        // The epicenter keeps its true position, always.
        for (const n of anchored) out.push({ ...n, trueLat: n.lat, trueLon: n.lon });

        // A lone node (or a lone non-epicenter beside the epicenter) needs no fan-out.
        if (movable.length <= 1 && anchored.length === 0) {
            for (const n of movable) out.push({ ...n, trueLat: n.lat, trueLon: n.lon });
            continue;
        }
        if (movable.length === 0) continue;

        const radius = Math.min(
            COLOCATION_MAX_M,
            Math.max(COLOCATION_MIN_M, COLOCATION_PIXEL_GAP * metresPerPixel(members[0].lat, zoom)),
        );
        const count = movable.length;
        movable.forEach((n, i) => {
            // Deterministic: index i of n always lands on the same spoke.
            const angle = (2 * Math.PI * i) / count - Math.PI / 2;
            const dLat = (radius * Math.sin(angle)) / 111_320;
            const cosLat = Math.max(0.2, Math.cos((n.lat * Math.PI) / 180));
            const dLon = (radius * Math.cos(angle)) / (111_320 * cosLat);
            out.push({
                ...n,
                trueLat: n.lat,
                trueLon: n.lon,
                lat: n.lat + dLat,
                lon: n.lon + dLon,
            });
        });
    }
    return out;
}

/** Hollow grey ring for structurally-exposed-but-unquantified nodes. */
function buildExposedLayer(Ctor: any, sid: string, nodes: SpatialNode[]): any {
    return new Ctor({
        id: `sc-exposed-${sid}`,
        data: nodes.filter((n: SpatialNode) => n.type === 'exposed_unquantified'),
        pickable: true,
        stroked: true,
        filled: false,                      // hollow — the "we don't know" signal
        radiusUnits: 'meters',
        radiusMinPixels: 5,
        radiusMaxPixels: 24,
        lineWidthMinPixels: 1.5,
        getPosition: (d: any) => [d.lon, d.lat],
        getRadius: () => UNQ_NODE_RADIUS_M,  // fixed — impact_score is meaningless here
        getLineColor: UNQ_NODE_STROKE,
    });
}

// ── Stage-2 reticle glyphs (STATIC cascade only) ────────────────────────────
// Canvas-generated icons for a deck.gl IconLayer, so Stage 2's nodes speak the
// same reticle language as Stage 1. One glyph per (role, detail); the controller
// caches each so it is drawn exactly once. Detail degrades with size — ticks
// collapse into noise on small nodes, so they are dropped. That is a rendering
// choice, NOT a data claim: size still encodes impact_score, which is real.
const RETICLE_PX = 128;
type ReticleKind = 'epi' | 'aff' | 'exp';
type ReticleDetail = 'full' | 'ticks' | 'ring' | 'dashed';

function makeReticleIcon(kind: ReticleKind, detail: ReticleDetail): string {
    const S = RETICLE_PX;
    const canvas = document.createElement('canvas');
    canvas.width = S;
    canvas.height = S;
    const ctx = canvas.getContext('2d');
    if (!ctx) return '';
    const cx = S / 2;
    const cy = S / 2;
    const color = kind === 'epi' ? '#ef4444' : kind === 'aff' ? '#00ff5a' : '#94a3b8';
    const outer = S * 0.42;
    const inner = S * 0.24;
    ctx.strokeStyle = color;
    ctx.lineCap = 'round';

    if (detail === 'dashed') {
        // Exposed · magnitude unknown — coarse dashes + no fill, so it reads as broken
        // even at the smallest render size and never as a measured ring.
        ctx.lineWidth = S * 0.05;
        ctx.setLineDash([S * 0.11, S * 0.08]);
        ctx.beginPath();
        ctx.arc(cx, cy, outer, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
        return canvas.toDataURL('image/png');
    }

    // Outer ring — every non-dashed variant.
    ctx.lineWidth = S * 0.045;
    ctx.beginPath();
    ctx.arc(cx, cy, outer, 0, Math.PI * 2);
    ctx.stroke();

    // Inner ring — only the 'full' glyph is double-ringed (epicenter, or large affected).
    if (detail === 'full') {
        ctx.lineWidth = S * 0.038;
        ctx.beginPath();
        ctx.arc(cx, cy, inner, 0, Math.PI * 2);
        ctx.stroke();
    }

    // N/S/E/W ticks — dropped for the small 'ring'-only variant.
    if (detail === 'full' || detail === 'ticks') {
        ctx.lineWidth = S * 0.045;
        const t0 = outer - S * 0.10;
        const t1 = outer + S * 0.055;
        const ticks: Array<[number, number, number, number]> = [
            [cx, cy - t0, cx, cy - t1],
            [cx, cy + t0, cx, cy + t1],
            [cx + t0, cy, cx + t1, cy],
            [cx - t0, cy, cx - t1, cy],
        ];
        for (const [x0, y0, x1, y1] of ticks) {
            ctx.beginPath();
            ctx.moveTo(x0, y0);
            ctx.lineTo(x1, y1);
            ctx.stroke();
        }
    }

    // Epicenter carries a small solid centre so the origin reads at a glance.
    if (kind === 'epi') {
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(cx, cy, S * 0.05, 0, Math.PI * 2);
        ctx.fill();
    }

    return canvas.toDataURL('image/png');
}

/**
 * Faint grey arc for unquantified edges. Deck.gl's ArcLayer has no native dash
 * support, so we reuse the established order-3 pseudo-dash recipe already used
 * in TM_ORDER_STYLE (very thin + low alpha) to read as a broken/uncertain line.
 */
function buildUnquantifiedArcLayer(Ctor: any, sid: string, edges: ResolvedEdge[]): any {
    return new Ctor({
        id: `sc-arcs-unq-${sid}`,
        data: edges.filter((e: ResolvedEdge) => e.unquantified === true),
        pickable: false,
        getSourcePosition: (d: ResolvedEdge) => [d.source_lon, d.source_lat],
        getTargetPosition: (d: ResolvedEdge) => [d.target_lon, d.target_lat],
        getSourceColor: UNQ_ARC_RGBA,
        getTargetColor: UNQ_ARC_RGBA,
        getWidth: () => UNQ_ARC_WIDTH,       // fixed — intensity is meaningless here
        widthMinPixels: 1,
        widthMaxPixels: 2,
        greatCircle: true,
        getHeight: 0.45,
        numSegments: 64,
    });
}

function resolveEdgesFlat(
    nodes: SpatialNode[],
    edges: SpatialEdge[],
    isAggregate: boolean,
): ResolvedEdge[] {
    const nodeMap = new Map<string, SpatialNode>(nodes.map((n) => [n.id, n]));
    return edges
        .map((e): ResolvedEdge | null => {
            const src = nodeMap.get(e.source_id);
            const tgt = nodeMap.get(e.target_id);
            if (!src || !tgt) return null;
            return buildResolvedEdge(e, src, tgt, isAggregate);
        })
        .filter((e): e is ResolvedEdge => e !== null);
}

function arcDomainRgba(
    domainId: string | undefined,
    alpha: number,
    end: 'source' | 'target',
    isAggregate: boolean,
): [number, number, number, number] {
    const rgb = domainAccentRgb(domainId);
    const scale = isAggregate ? ARC_AGGREGATE_OPACITY : 1;
    const a = Math.max(0, Math.min(255, Math.round(alpha * scale)));
    if (end === 'target') {
        const mix = isAggregate ? 0.22 : 0.45;
        return [
            Math.round(rgb[0] + (34 - rgb[0]) * mix),
            Math.round(rgb[1] + (211 - rgb[1]) * mix),
            Math.round(rgb[2] + (238 - rgb[2]) * mix),
            Math.max(0, Math.min(255, Math.round(a * 0.82))),
        ];
    }
    return [rgb[0], rgb[1], rgb[2], a];
}

function arcLayerBlendProps(isAggregate: boolean): Record<string, unknown> {
    if (!isAggregate) return { parameters: { depthTest: false } };
    return { opacity: ARC_AGGREGATE_OPACITY, parameters: ARC_AGGREGATE_BLEND };
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function esc(s: string): string {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function safeId(s: string | null | undefined): string {
    return String(s || GLOBAL_DOMAIN_ID).replace(/[^a-z0-9]/gi, '_');
}
export function injectMaplibreCss(): void {
    if (document.querySelector('#maplibre-gl-css')) return;
    const link = document.createElement('link');
    link.id = 'maplibre-gl-css';
    link.rel = 'stylesheet';
    link.href = 'https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.css';
    document.head.appendChild(link);
}

function forceMapElementDimensions(el: HTMLElement): void {
    Object.assign(el.style, {
        width: '100%',
        height: '100%',
        minHeight: '520px',
        position: 'relative',
        display: 'block',
    });
}

async function waitForVisibleMapElement(el: HTMLElement): Promise<void> {
    forceMapElementDimensions(el);

    for (let i = 0; i < 12; i += 1) {
        const rect = el.getBoundingClientRect();
        const styles = window.getComputedStyle(el);
        const isVisible =
            rect.width > 0 &&
            rect.height > 0 &&
            styles.display !== 'none' &&
            styles.visibility !== 'hidden';

        console.log(`${LOG} map DOM check ${i + 1}/12`, {
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            display: styles.display,
            visibility: styles.visibility,
        });

        if (isVisible) return;
        await new Promise<void>((resolve) => setTimeout(resolve, 50));
    }

    console.warn(`${LOG} map container still has weak dimensions after waiting; forcing fallback height`);
    el.style.height = '600px';
    el.style.minHeight = '600px';
}

function resolveMapLibreExports(maplibreglMod: any): {
    MapCtor: any;
    AttributionControl: any;
    LngLatBounds: any;
} {
    const defaultExport = maplibreglMod?.default;
    return {
        MapCtor: maplibreglMod?.Map ?? defaultExport?.Map ?? (typeof defaultExport === 'function' ? defaultExport : undefined),
        AttributionControl: maplibreglMod?.AttributionControl ?? defaultExport?.AttributionControl,
        LngLatBounds: maplibreglMod?.LngLatBounds ?? defaultExport?.LngLatBounds,
    };
}

export function getGlobalFallbackSpatialContagion(): SpatialContagion {
    const nodes: SpatialNode[] = [
        {
            id: 'middle-east-energy-corridor',
            name: 'Middle East Energy Corridor',
            raw_input: 'Hormuz / Gulf energy transit complex',
            lat: 26.6,
            lon: 56.2,
            country: 'Gulf',
            impact_score: 96,
            type: 'epicenter',
        },
        {
            id: 'south-china-sea',
            name: 'South China Sea',
            raw_input: 'Trade lane militarization and shipping exposure',
            lat: 13.5,
            lon: 114.5,
            country: 'Indo-Pacific',
            impact_score: 88,
            type: 'affected',
        },
        {
            id: 'eastern-europe-frontier',
            name: 'Eastern Europe Frontier',
            raw_input: 'Forward logistics and energy infrastructure stress',
            lat: 49.0,
            lon: 31.3,
            country: 'Eastern Europe',
            impact_score: 84,
            type: 'affected',
        },
        {
            id: 'red-sea-chokepoint',
            name: 'Red Sea / Bab el-Mandeb',
            raw_input: 'Maritime chokepoint disruption risk',
            lat: 12.6,
            lon: 43.3,
            country: 'Red Sea',
            impact_score: 82,
            type: 'affected',
        },
        {
            id: 'taiwan-strait',
            name: 'Taiwan Strait',
            raw_input: 'Semiconductor and naval escalation exposure',
            lat: 24.1,
            lon: 121.0,
            country: 'Taiwan Strait',
            impact_score: 79,
            type: 'affected',
        },
    ];

    const edges: SpatialEdge[] = [
        { source_id: 'middle-east-energy-corridor', target_id: 'south-china-sea', intensity: 0.91 },
        { source_id: 'middle-east-energy-corridor', target_id: 'eastern-europe-frontier', intensity: 0.77 },
        { source_id: 'middle-east-energy-corridor', target_id: 'red-sea-chokepoint', intensity: 0.86 },
        { source_id: 'middle-east-energy-corridor', target_id: 'taiwan-strait', intensity: 0.69 },
    ];

    return {
        nodes,
        edges,
        epicenter_impact_score: 96,
        edge_intensity: 0.81,
        node_count: nodes.length,
        edge_count: edges.length,
        schema_version: 'global-fallback-v1',
        warning: 'fallback_global_surveillance_demo',
    };
}

// ── Section header ────────────────────────────────────────────────────────────
function sectionHead(num: string, title: string): string {
    return `<div class="intel-section-head">
        <span class="intel-section-num">${esc(num)}</span>
        <h3 class="intel-section-title">${esc(title)}</h3>
    </div>`;
}

// ── HTML shell (synchronous, never blocks report render) ──────────────────────
export function renderSpatialContagionShell(sc: any, sectionNum: string, domainId = GLOBAL_DOMAIN_ID): string {
    const normalizedDomainId = domainId || GLOBAL_DOMAIN_ID;
    const effectiveSc = sc ?? (normalizedDomainId === GLOBAL_DOMAIN_ID ? getGlobalFallbackSpatialContagion() : null);
    const nodes: SpatialNode[] = effectiveSc?.nodes ?? [];
    const epicenter = nodes.find((n: SpatialNode) => n.type === 'epicenter');
    const hasData = nodes.length > 0 && !String(effectiveSc?.warning ?? '').includes('no_resolved');
    const sid = safeId(normalizedDomainId);

    console.log(`${LOG} shell — domainId=${normalizedDomainId} nodes=${nodes.length} hasData=${hasData} warning=${effectiveSc?.warning ?? 'none'}`);

    const statsBar = epicenter
        ? `<div class="sc-stats-bar">
            <div class="sc-stat"><span class="sc-stat-label">Epicenter</span><span class="sc-stat-val">${esc(epicenter.name)}</span></div>
            <div class="sc-stat"><span class="sc-stat-label">Impact Score</span><span class="sc-stat-val sc-stat-val--critical">${(effectiveSc.epicenter_impact_score ?? 0).toFixed(1)}</span></div>
            <div class="sc-stat"><span class="sc-stat-label">Affected Nodes</span><span class="sc-stat-val">${Math.max(0, (effectiveSc.node_count ?? nodes.length) - 1)}</span></div>
            <div class="sc-stat"><span class="sc-stat-label">Edge Intensity</span><span class="sc-stat-val">${(effectiveSc.edge_intensity ?? 0).toFixed(3)}</span></div>
           </div>`
        : '';

    const overlay = hasData
        ? `<div class="sc-map-overlay sc-map-overlay--loading" id="sc-loading-${sid}">
               <div class="sc-loading-pulse"></div>
               <span class="sc-loading-text">Initializing spatial intelligence layer...</span>
           </div>`
        : `<div class="sc-map-overlay">
               <div class="sc-map-overlay-content">
                   <span class="sc-map-overlay-icon">&#x1F310;</span>
                   <span class="sc-map-overlay-text">Awaiting Spatial Data...</span>
                   <span class="sc-map-overlay-sub">Geographic entities could not be resolved for this event. Check back after the next intelligence cycle.</span>
               </div>
           </div>`;

    const title = normalizedDomainId === GLOBAL_DOMAIN_ID ? 'Global Surveillance Monitor' : 'Spatial Contagion Network';
    const intro = normalizedDomainId === GLOBAL_DOMAIN_ID
        ? 'Pentagon-style situational awareness layer for high-impact physical computations and critical alerts. Global fallback sectors remain visible while backend aggregation routes come online.'
        : 'Propagation computed from the vault dependency graph. Arc width is the measured edge weight; node radius scales with impact score. Dashed = structurally exposed, magnitude never measured.';

    return `<div class="intel-panel intel-spatial-panel" data-sc-domain="${esc(normalizedDomainId)}">
        ${sectionHead(sectionNum, title)}
        <p class="intel-panel-intro">${esc(intro)}</p>
        ${statsBar}
        <div class="sc-map-wrap" id="sc-wrap-${sid}">
            <div id="sc-map-${sid}" class="sc-map-canvas"></div>
            ${overlay}
        </div>
    </div>`;
}

/**
 * The shared map skeleton — the ONE place the `#sc-wrap-${sid}` / `#sc-map-${sid}` id
 * contract lives. mountSpatialContagionMap() looks these up by id. (renderSpatialContagionShell
 * predates this and inlines its own identical copy; it is left byte-for-byte unchanged so the
 * Pro Brief is provably untouched — only the new static shell routes through here.)
 */
function renderMapWrap(sid: string, hasData: boolean): string {
    const overlay = hasData
        ? `<div class="sc-map-overlay sc-map-overlay--loading" id="sc-loading-${sid}">
               <div class="sc-loading-pulse"></div>
               <span class="sc-loading-text">Initializing spatial intelligence layer...</span>
           </div>`
        : `<div class="sc-map-overlay">
               <div class="sc-map-overlay-content">
                   <span class="sc-map-overlay-icon">&#x1F310;</span>
                   <span class="sc-map-overlay-text">Awaiting Spatial Data...</span>
                   <span class="sc-map-overlay-sub">Geographic entities could not be resolved for this event. Check back after the next intelligence cycle.</span>
               </div>
           </div>`;
    return `<div class="sc-map-wrap" id="sc-wrap-${sid}">
            <div id="sc-map-${sid}" class="sc-map-canvas"></div>
            ${overlay}
        </div>`;
}

/**
 * The map drawer — a right-edge slide-out with a vertical handle. Shared by the static cascade
 * (roster, collapsed by default) and Stage 1 of the trigger map (receipts, expanded by default:
 * the receipts ARE the justification for the firing state, so hiding them would leave the map
 * unexplained). The caller fills `#sc-drawer-body-${sid}` and wires the handle toggle.
 */
export function renderDrawer(label: string, sid: string, open: boolean): string {
    return `<aside class="sc-drawer${open ? ' sc-drawer--open' : ''}" id="sc-drawer-${sid}" aria-hidden="${open ? 'false' : 'true'}">
        <button type="button" class="sc-drawer-handle" aria-expanded="${open ? 'true' : 'false'}">${esc(label)}</button>
        <div class="sc-drawer-body" id="sc-drawer-body-${sid}"></div>
    </aside>`;
}

/**
 * Full-bleed, drawer-based shell for the STATIC cascade (Stage 2 of the trigger map). Distinct
 * from renderSpatialContagionShell (the Pro Brief's inline report card) on purpose: no section
 * head, no intro paragraph, map fills the whole area, and the node roster lives in a right-edge
 * drawer instead of a fixed sidebar. Shares only the map skeleton (renderMapWrap) + the stats
 * strip markup. The .pm-c2 chrome (corners/legend/static readout) is injected by the controller
 * onto #sc-wrap-${sid}, so it carries over here unchanged.
 */
export function renderStaticCascadeShell(sc: any, domainId: string): string {
    const normalizedDomainId = domainId || GLOBAL_DOMAIN_ID;
    const nodes: SpatialNode[] = sc?.nodes ?? [];
    const epicenter = nodes.find((n: SpatialNode) => n.type === 'epicenter');
    const hasData = nodes.length > 0 && !String(sc?.warning ?? '').includes('no_resolved');
    const sid = safeId(normalizedDomainId);

    const statsBar = epicenter
        ? `<div class="sc-stats-bar">
            <div class="sc-stat"><span class="sc-stat-label">Epicenter</span><span class="sc-stat-val">${esc(epicenter.name)}</span></div>
            <div class="sc-stat"><span class="sc-stat-label">Impact Score</span><span class="sc-stat-val sc-stat-val--critical">${(sc.epicenter_impact_score ?? 0).toFixed(1)}</span></div>
            <div class="sc-stat"><span class="sc-stat-label">Affected Nodes</span><span class="sc-stat-val">${Math.max(0, (sc.node_count ?? nodes.length) - 1)}</span></div>
            <div class="sc-stat"><span class="sc-stat-label">Edge Intensity</span><span class="sc-stat-val">${(sc.edge_intensity ?? 0).toFixed(3)}</span></div>
           </div>`
        : '';

    return `<div class="sc-static-shell" data-sc-domain="${esc(normalizedDomainId)}">
        ${renderMapWrap(sid, hasData)}
        <div class="sc-static-topbar">
            <button type="button" class="sc-static-back" id="sc-back-${sid}">&larr; Triggers</button>
            <span class="sc-static-title" id="sc-title-${sid}"></span>
        </div>
        ${statsBar}
        ${renderDrawer('Roster', sid, false)}
    </div>`;
}

/**
 * Stats HUD body — the same four cards Phase 4 had, but stripped of any
 * panel chrome. The wireStatsHudObserver() refreshes these on domain swap.
 */
function renderStatsHudBody(sc: SpatialContagion | null | undefined): string {
    const nodes = sc?.nodes ?? [];
    const epicenter =
        nodes.find((n) => n.type === 'epicenter') ??
        [...nodes].sort((a, b) => (b.impact_score ?? 0) - (a.impact_score ?? 0))[0];
    const epiName = epicenter?.name ?? (nodes.length > 0 ? 'Live cluster' : '—');
    // UNKNOWN IS NOT ZERO. The old `?? 0` chain printed "0.0" whether the value was a
    // genuine zero or simply absent — the same lie we removed from the map itself.
    // A real 0 still renders as 0.0; only a null/undefined becomes "--".
    const impactRaw: number | null | undefined =
        (sc?.epicenter_impact_score as number | null | undefined) ?? epicenter?.impact_score;
    const impact = impactRaw == null ? '--' : impactRaw.toFixed(1);
    const affectedN = Math.max(0, (sc?.node_count ?? nodes.length) - 1);
    const edgeRaw = sc?.edge_intensity as number | null | undefined;
    const edgeI = edgeRaw == null ? '--' : edgeRaw.toFixed(3);
    return `
        <div class="sc-hud-stat">
            <span class="sc-hud-stat-label">Epicenter</span>
            <span class="sc-hud-stat-val" title="${esc(epiName)}">${esc(epiName)}</span>
        </div>
        <div class="sc-hud-stat">
            <span class="sc-hud-stat-label">Impact</span>
            <span class="sc-hud-stat-val sc-hud-stat-val--critical">${impact}</span>
        </div>
        <div class="sc-hud-stat">
            <span class="sc-hud-stat-label">Affected</span>
            <span class="sc-hud-stat-val">${affectedN}</span>
        </div>
        <div class="sc-hud-stat">
            <span class="sc-hud-stat-label">Edge ν</span>
            <span class="sc-hud-stat-val">${edgeI}</span>
        </div>
    `;
}

// ── Entity Badge Tooltip (Phase 5 — Palantir-style HUD glow) ─────────────────
//
// Match the Global Map's rich-glow aesthetic. Each badge gets:
//   • Tier chip (EPICENTER / ORDER 2 / ORDER 3) with accent colour
//   • Confidence label in the top-right
//   • Bold entity name as headline
//   • Country + entity classification line
//   • Impact + great-circle coordinates
//   • Drop-shadow glow keyed to the tier accent
function buildTooltipHtml(node: SpatialNode): string {
    const isEpi = node.type === 'epicenter';
    const isUnq = node.type === 'exposed_unquantified' || node.unquantified === true;
    const order: 1 | 2 | 3 = (isEpi ? 1 : (node.order ?? 2)) as 1 | 2 | 3;
    // Unquantified nodes must NEVER take the order-based amber/red accent — a
    // coloured tier chip would imply a magnitude we do not have.
    const accent = isUnq ? '#94a3b8' :
        order === 1 ? '#ef4444' :
        order === 2 ? '#f59e0b' :
                      '#fbbf24';
    const tierLabel = isUnq ? 'EXPOSED · UNQUANTIFIED' : (isEpi ? 'EPICENTER' : `ORDER ${order}`);
    // confidence is a NUMBER (0..1); formatting is presentation, done here.
    // NB: a `node.confidence ? …` truthiness check would render a genuine 0.0
    // as "UNVERIFIED" — an explicit typeof test is required.
    const confidence = isUnq
        ? 'MAGNITUDE UNKNOWN'
        : (typeof node.confidence === 'number'
            ? `${Math.round(node.confidence * 100)}% CONF`
            : 'UNVERIFIED');
    const country = node.country ? esc(node.country) : 'Global';
    // Decorative classification chip: chokepoints (negative geonameid) get
    // a MARITIME tag, real cities get TACTICAL.
    const classification = (node.geonameid ?? 0) < 0 ? 'MARITIME' : 'TACTICAL';
    return `<div class="sc-entity-badge" style="--badge-accent:${accent};">
        <div class="sc-badge-header">
            <span class="sc-badge-tier">${tierLabel}</span>
            <span class="sc-badge-conf">${confidence}</span>
        </div>
        <div class="sc-badge-name">${esc(node.name)}</div>
        <div class="sc-badge-meta">
            <span class="sc-badge-meta-cls">${classification}</span>
            <span class="sc-badge-meta-sep">·</span>
            <span class="sc-badge-meta-country">${country}</span>
        </div>
        <div class="sc-badge-metrics">
            <div class="sc-badge-metric">
                <span class="k">Impact</span>
                <span class="v">${isUnq ? 'unknown' : node.impact_score.toFixed(1)}</span>
            </div>
            <div class="sc-badge-metric">
                <span class="k">Coords</span>
                <span class="v">${(node.trueLat ?? node.lat).toFixed(2)}&deg; · ${(node.trueLon ?? node.lon).toFixed(2)}&deg;</span>
            </div>
        </div>
        ${isUnq && node.why ? `<div class="sc-badge-why">${esc(node.why)}</div>` : ''}
    </div>`;
}

// ── Async map mount ───────────────────────────────────────────────────────────
export async function mountSpatialContagionMap(
    container: HTMLElement,
    sc?: any,
    domainId = GLOBAL_DOMAIN_ID,
    /** A vault scenario cascade: one snapshot, no time axis. Disables the scrubber and
     *  relabels the panel, instead of leaving a dead control that looks broken. */
    opts?: { staticScenario?: boolean },
): Promise<void> {
    const normalizedDomainId = domainId || GLOBAL_DOMAIN_ID;
    let payload: SpatialContagion | any = sc;

    if (!Array.isArray(payload?.nodes) || payload.nodes.length === 0) {
        if (normalizedDomainId === GLOBAL_DOMAIN_ID) {
            // Unconditional fallback — not a last resort. The three global endpoints this used
            // to probe first (/spatial/global, /pro/spatial/global,
            // /pro/domains/global/spatial-contagion) were removed in d8a696d, so the fetch 404'd
            // through all of them on every call and always landed here anyway.
            console.warn(`${LOG} no global payload supplied — using client-side fallback`);
            payload = getGlobalFallbackSpatialContagion();
        } else {
            console.warn(`${LOG} no nodes in payload — skipping map init`);
            return;
        }
    }

    console.log(`${LOG} mount called — domainId="${normalizedDomainId}"`, {
        schema: payload?.schema_version,
        nodeCount: payload?.node_count ?? payload?.nodes?.length,
        edgeCount: payload?.edge_count ?? payload?.edges?.length,
        warning: payload?.warning,
    });

    const nodes: SpatialNode[] = payload?.nodes ?? [];
    const edges: SpatialEdge[] = payload?.edges ?? [];

    if (nodes.length === 0) {
        console.warn(`${LOG} no nodes in payload — skipping map init`);
        return;
    }

    console.log(`${LOG} nodes[0]:`, JSON.stringify(nodes[0]));
    if (edges.length > 0) console.log(`${LOG} edges[0]:`, JSON.stringify(edges[0]));

    const sid = safeId(normalizedDomainId);
    const mapEl = container.querySelector(`#sc-map-${sid}`) as HTMLElement | null;
    if (!mapEl) {
        console.error(`${LOG} map container #sc-map-${sid} not found in DOM`);
        return;
    }
    await waitForVisibleMapElement(mapEl);
    console.log(`${LOG} map container ready — offsetWidth=${mapEl.offsetWidth} offsetHeight=${mapEl.offsetHeight}`);

    injectMaplibreCss();

    try {
        // ── Dynamic imports (separate Vite chunks, loaded only when needed) ──
        console.log(`${LOG} loading maplibre-gl + deck.gl modules…`);
        const [maplibreglMod, layersMod, mapboxMod] = await Promise.all([
            import('maplibre-gl'),
            import('@deck.gl/layers'),
            import('@deck.gl/mapbox'),
        ]);

        const { MapCtor, AttributionControl, LngLatBounds } = resolveMapLibreExports(maplibreglMod as any);

        // @deck.gl/layers: named exports (ScatterplotLayer, ArcLayer)
        const ScatterplotLayer: any = (layersMod as any).ScatterplotLayer;
        const ArcLayer: any        = (layersMod as any).ArcLayer;
        const IconLayer: any       = (layersMod as any).IconLayer;   // static-cascade reticles
        // ScatterplotLayer doubles as the particle layer — each particle is
        // a small filled circle whose position is parametrically interpolated
        // along the arc's great-circle path each animation frame.

        // @deck.gl/mapbox v9: named export `MapboxOverlay`
        // (MapboxLayer was removed in v9 — MapboxOverlay with interleaved:true is the equivalent)
        const MapboxOverlay: any = (mapboxMod as any).MapboxOverlay;

        console.log(`${LOG} modules OK — Map:${!!MapCtor} ScatterplotLayer:${!!ScatterplotLayer} ArcLayer:${!!ArcLayer} MapboxOverlay:${!!MapboxOverlay}`);

        if (!MapCtor || !ScatterplotLayer || !ArcLayer || !MapboxOverlay) {
            throw new Error(`Module export resolution failed: ${JSON.stringify({
                Map: !!MapCtor, ScatterplotLayer: !!ScatterplotLayer,
                ArcLayer: !!ArcLayer, MapboxOverlay: !!MapboxOverlay,
            })}`);
        }

        // ── Pre-compute edge coordinates (CRITICAL — ArcLayer cannot auto-join IDs) ──
        const nodeMap = new Map<string, SpatialNode>(nodes.map(n => [n.id, n]));
        const unresolved = edges.filter((e) => !nodeMap.has(e.source_id) || !nodeMap.has(e.target_id));
        if (unresolved.length > 0) {
            console.warn(`${LOG} ${unresolved.length} edge(s) could not be resolved`);
        }

        // Fan co-located nodes onto a ring BEFORE resolving edges, so arc endpoints
        // land on the displayed dots rather than on the shared true point.
        const initialZoomForFan = nodes.length === 1 ? 5 : 2;
        let displayNodes = applyColocationOffsets(nodes, initialZoomForFan);
        const edgesFlat = resolveEdgesFlat(displayNodes, edges, false);

        console.log(`${LOG} edges resolved: ${edgesFlat.length}/${edges.length}`);

        // ── Compute map centre and bounds ─────────────────────────────────────
        const lons = nodes.map(n => n.lon);
        const lats = nodes.map(n => n.lat);
        const centerLon = (Math.min(...lons) + Math.max(...lons)) / 2;
        const centerLat = (Math.min(...lats) + Math.max(...lats)) / 2;
        const initialZoom = nodes.length === 1 ? 5 : 2;

        console.log(`${LOG} center=(${centerLon.toFixed(3)}, ${centerLat.toFixed(3)}) zoom=${initialZoom}`);

        // ── MapLibre GL dark-mode basemap ─────────────────────────────────────
        const map = new MapCtor({
            container: mapEl,
            style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
            center: [centerLon, centerLat],
            zoom: initialZoom,
            // Static cascade opens tilted so the raised arcs read as curves over the surface;
            // the Pro Brief (no staticScenario) stays flat (0 = MapLibre default). Set only once
            // here — never re-applied on refresh, so the user's later pitch/bearing/zoom stick.
            pitch: opts?.staticScenario ? 50 : 0,
            attributionControl: false,
            antialias: true,   // Required: ensures WebGL2 context attributes for deck.gl interleaved mode
        });
        if (AttributionControl) {
            map.addControl(new AttributionControl({ compact: true }), 'bottom-right');
        }
        requestAnimationFrame(() => map.resize());
        console.log(`${LOG} MapLibre Map created`);

        // ── Build deck.gl layers ──────────────────────────────────────────────
        const epicenterScore = (payload.epicenter_impact_score as number) || 100;

        // Epicenter nodes — crimson
        const epicenterLayer = new ScatterplotLayer({
            id: `sc-epicenter-${sid}`,
            data: displayNodes.filter((n: SpatialNode) => n.type === 'epicenter'),
            pickable: true,
            stroked: true,
            filled: true,
            radiusUnits: 'meters',
            radiusMinPixels: 10,
            radiusMaxPixels: 60,
            lineWidthMinPixels: 2,
            getPosition: (d: any) => [d.lon, d.lat],
            getRadius:   (d: any) => Math.max(25_000 + d.impact_score * 1_200, 35_000),
            getFillColor: [239, 68, 68, 210],
            getLineColor: [255, 100, 100, 255],
        });

        // Affected nodes — amber ↔ cyan based on impact rank
        const affectedLayer = new ScatterplotLayer({
            id: `sc-affected-${sid}`,
            data: displayNodes.filter((n: SpatialNode) => n.type === 'affected'),
            pickable: true,
            stroked: true,
            filled: true,
            radiusUnits: 'meters',
            radiusMinPixels: 5,
            radiusMaxPixels: 36,
            lineWidthMinPixels: 1,
            getPosition: (d: any) => [d.lon, d.lat],
            getRadius:   (d: any) => Math.max(12_000 + d.impact_score * 800, 16_000),
            // Lerp: low-impact → cyan [34,211,238], high-impact → amber [245,158,11]
            getFillColor: (d: any) => {
                const t = Math.min(d.impact_score / epicenterScore, 1);
                return [
                    Math.round(34  + (245 - 34)  * t),
                    Math.round(211 + (158 - 211) * t),
                    Math.round(238 + (11  - 238) * t),
                    190,
                ];
            },
            getLineColor: [148, 163, 184, 140],
        });

        // Structurally exposed, magnitude unknown — hollow grey ring, fixed radius.
        const exposedLayer = buildExposedLayer(ScatterplotLayer, sid, displayNodes);

        // Contagion arcs — red source → cyan target, slight 3-D tilt.
        // Unquantified edges are excluded here and drawn by their own grey layer;
        // an intensity of 0 would otherwise render them as a "negligible" hairline.
        const arcLayer = new ArcLayer({
            id: `sc-arcs-${sid}`,
            data: edgesFlat.filter((e: ResolvedEdge) => !e.unquantified),
            pickable: false,
            getSourcePosition: (d: ResolvedEdge) => [d.source_lon, d.source_lat],
            getTargetPosition: (d: ResolvedEdge) => [d.target_lon, d.target_lat],
            getSourceColor: [239, 68, 68, 200],
            getTargetColor: [34, 211, 238, 160],
            getWidth:  (d: ResolvedEdge) => Math.max(d.intensity * 5, 1.5),
            widthMinPixels: 1,
            widthMaxPixels: 8,
            greatCircle: true,
            getHeight: 0.45,    // subtle 3-D arc elevation
            numSegments: 64,
        });

        const unquantifiedArcLayer = buildUnquantifiedArcLayer(ArcLayer, sid, edgesFlat);

        // ── MapboxOverlay with interleaved:true ───────────────────────────────
        // interleaved:true → deck.gl shares MapLibre's WebGL2 context.
        // Internally, _onAddInterleaved() accesses map.painter.context.gl and
        // registers each deck layer as a MapLibre CustomLayer via map.addLayer().
        // This requires map.painter to be initialised, hence we add inside 'load'.
        const overlay = new MapboxOverlay({
            interleaved: true,
            layers: [unquantifiedArcLayer, arcLayer, exposedLayer, affectedLayer, epicenterLayer],
            getTooltip: ({ object }: { object: any }) => {
                if (!object || typeof object.impact_score !== 'number') return null;
                return {
                    html: buildTooltipHtml(object as SpatialNode),
                    style: { background: 'transparent', padding: '0', border: 'none' },
                };
            },
        });

        console.log(`${LOG} MapboxOverlay instance created (interleaved:true)`);

        // ── Race-condition-safe initialisation ────────────────────────────────
        // Dynamic imports + style fetch can resolve AFTER the map's 'load' event
        // has already fired. Registering map.on('load') at that point means the
        // callback never runs. Guard with map.loaded() to handle both orderings:
        //   Fast map  : load fired before we got here → call initDeckGlLayers() now
        //   Slow map  : load fires after   we got here → callback handles it
        const initDeckGlLayers = () => {
            console.log(`${LOG} initDeckGlLayers — map.loaded()=${map.loaded()}`);

            try {
                // addControl → overlay.onAdd(map) → _onAddInterleaved(map)
                // which extracts map.painter.context.gl and registers each
                // deck.gl layer as a MapLibre custom layer via map.addLayer().
                map.addControl(overlay);
                console.log(`${LOG} overlay added successfully`);

                // Force hide the loading text / Update sync status
                window.dispatchEvent(new CustomEvent('api-sync-status', {
                    detail: { status: 'stable', timestamp: new Date() }
                }));

                // Explicit DOM override as fallback per request
                document.querySelectorAll('.sync-label').forEach((el) => {
                    const label = el as HTMLElement;
                    if (label.innerText.includes('INITIALIZING')) {
                        label.innerText = 'SYNC: STABLE';
                        label.style.color = '#22d3ee'; // Cyan
                    }
                });
                document.querySelectorAll('.sync-dot').forEach((el) => {
                    el.classList.remove('sync-dot--init', 'sync-dot--retrying', 'sync-dot--offline');
                    el.classList.add('sync-dot--stable');
                });
            } catch (overlayErr) {
                console.error(`${LOG} overlay.addControl failed:`, overlayErr);
            }

            // Fit bounds to show all nodes
            map.resize();
            if (nodes.length > 1 && LngLatBounds) {
                const bounds = new LngLatBounds(
                    [Math.min(...lons), Math.min(...lats)],
                    [Math.max(...lons), Math.max(...lats)],
                );
                if (opts?.staticScenario) {
                    // MapLibre's cameraForBounds computes the fit zoom TOP-DOWN — it does not
                    // account for pitch. A pitched frustum reveals MORE ground than top-down at the
                    // same zoom, so nothing is cut off, but the framing is looser and the cluster
                    // sits low. Extra top padding pushes it down off the compressed horizon; keep
                    // the tilt (pitch/bearing forwarded to the eased camera). Applied once — not on refresh.
                    map.fitBounds(bounds, {
                        padding: { top: 130, bottom: 60, left: 70, right: 70 },
                        maxZoom: 7, pitch: 50, bearing: 0, duration: 900,
                    });
                } else {
                    map.fitBounds(bounds, { padding: 70, maxZoom: 7, duration: 900 });
                }
            }

            // ─────────────────────────────────────────────────────────────
            // Phase 1 (Animation) + Phase 3 (Time Machine) — class-based
            // ─────────────────────────────────────────────────────────────
            //
            // Local state managers replace the old `window.__fragilityHistory`
            // global. The animator runs at ~30Hz, the history poller at 3s,
            // and the slider scrubs through a strict 24-hour rolling window.
            // Cleanup is wired to the wrap element via __scTeardown so a
            // subsequent renderGlobalSurveillanceMap() never leaks RAF or
            // intervals from a previous mount.

            const surveillance = new SurveillanceMapController({
                container,
                wrapEl: container.querySelector(`#sc-wrap-${sid}`) as HTMLElement,
                mapEl,
                overlay,
                arcLayer,
                affectedLayer,
                epicenterLayer,
                exposedLayer,
                unquantifiedArcLayer,
                ScatterplotLayer,
                IconLayer,
                nodes: displayNodes,
                edgesFlat,
                domainId: normalizedDomainId,
                epicenterScore,
                // A static cascade has no time axis — don't poll, and say so on the panel.
                enableHistoryPolling: opts?.staticScenario !== true,
                staticScenario: opts?.staticScenario === true,
                // Placeless fields for the OFF-MAP panel — verbatim, no coercion.
                // credit_gaps rides here too: it is top-level like the other three, and the company
                // panel needs it to explain a node that has no credit figure.
                offMap: {
                    conduits: payload?.conduits,
                    no_map: payload?.no_map,
                    honest_gaps: payload?.honest_gaps,
                    credit_gaps: payload?.credit_gaps,
                },
                graphEdges: payload?.edges,   // raw edges (source_id/target_id) for the GRAPH view
                mapRef: map,   // ← triggerRepaint() keeps interleaved animation alive
            });
            surveillance.start();

            // Keep the co-location ring at a constant ON-SCREEN separation: re-fan from
            // the new metres-per-pixel whenever the zoom changes materially. Named (not
            // inline) so stop() can map.off() it — see addCleanup below.
            let lastFanZoom = initialZoomForFan;
            const onZoomEnd = (): void => {
                const z = map.getZoom();
                if (Math.abs(z - lastFanZoom) < 0.4) return;
                lastFanZoom = z;
                displayNodes = applyColocationOffsets(nodes, z);
                surveillance.updateGeometry(displayNodes, resolveEdgesFlat(displayNodes, edges, false));
            };
            map.on('zoomend', onZoomEnd);
            surveillance.addCleanup(() => map.off('zoomend', onZoomEnd));
            // ─────────────────────────────────────────────────────────────

            // Dismiss loading overlay
            const loadingEl = container.querySelector(`#sc-loading-${sid}`) as HTMLElement | null;
            if (loadingEl) {
                loadingEl.style.transition = 'opacity 0.4s ease';
                loadingEl.style.opacity = '0';
                setTimeout(() => loadingEl.remove(), 420);
            }
        };

        if (map.loaded()) {
            // Map style already rendered — invoke directly (race condition path)
            console.log(`${LOG} map already loaded — calling initDeckGlLayers() directly`);
            initDeckGlLayers();
        } else {
            // Normal path — wait for the style tiles to finish loading
            map.once('load', () => {
                console.log(`${LOG} 'load' event fired`);
                initDeckGlLayers();
            });
        }

        // Handle style-load failure gracefully
        map.on('error', (e: any) => {
            console.error(`${LOG} MapLibre error:`, e?.error?.message ?? e);
        });

    } catch (err) {
        console.error(`${LOG} fatal error:`, err);
        showMapError(container, sid, String(err instanceof Error ? err.message : err));
    }
}

function showMapError(container: HTMLElement, sid: string, msg: string): void {
    const wrapEl = container.querySelector(`#sc-wrap-${sid}`);
    if (!wrapEl) return;
    // Remove loading overlay first
    wrapEl.querySelector(`#sc-loading-${sid}`)?.remove();
    const errDiv = document.createElement('div');
    errDiv.className = 'sc-map-overlay';
    errDiv.innerHTML = `<div class="sc-map-overlay-content">
        <span class="sc-map-overlay-icon">&#x26A0;</span>
        <span class="sc-map-overlay-text">Spatial layer unavailable</span>
        <span class="sc-map-overlay-sub">${esc(msg)}</span>
    </div>`;
    wrapEl.appendChild(errDiv);
}


// ─────────────────────────────────────────────────────────────────────────
//   Phase 1 + Phase 3 — Real-Time Surveillance + Time Machine
// ─────────────────────────────────────────────────────────────────────────

const TM_HISTORY_HOURS = 24;                   // sliding window length
const TM_POLL_INTERVAL_MS = 3_000;             // 3s incremental poll (Polling, see ADR)
const TM_ANIMATION_FPS = 60;                    // particle / pulse refresh rate
const TM_TRIGGER_IMPACT_THRESHOLD = 75;        // viscosity-derived score that counts as a >1.5x trigger
const TM_PLAYBACK_STEP_MS = 800;               // time between auto-advance ticks

/**
 * Per-order visual scaling — drives the N-th Order Impact Graph (Phase 2).
 *   widthScale     : multiplier for arc width + particle size
 *   velocityScale  : multiplier on the global animation phase
 *                    (1.0 = standard pace, higher = faster)
 *   arcAlphaBase   : base alpha (0-255) before the pulse adds variance
 *   particleAlpha  : flat alpha for the dot particles (no pulse needed)
 *   particles      : how many dots flow along each arc in this tier
 *
 * Tier 3 explicitly looks "fading into the noise" — slow, thin, faint —
 * which is the correct visual analogue of energy dissipation across hops.
 */
type OrderStyle = {
    widthScale: number;
    velocityScale: number;
    arcAlphaBase: number;
    particleAlpha: number;
    particles: number;
};
const TM_ORDER_STYLE: Record<ContagionOrder, OrderStyle> = {
    // Phase 6 — sharpened hierarchy:
    //   1: Thick, bright, flowing fast  (Epicenter → 1st hop)
    //   2: Medium, opaque                (1st → 2nd hop)
    //   3: VERY thin, low-alpha, 6 dots  → reads as a dashed/dotted line,
    //      no native dash support needed on Deck.gl ArcLayer.
    1: { widthScale: 1.30, velocityScale: 1.40, arcAlphaBase: 200, particleAlpha: 240, particles: 3 },
    2: { widthScale: 0.85, velocityScale: 1.00, arcAlphaBase: 150, particleAlpha: 180, particles: 2 },
    3: { widthScale: 0.22, velocityScale: 0.55, arcAlphaBase: 55,  particleAlpha: 235, particles: 6 },
};

type HistoryPoint = {
    timestamp: string;
    epoch_ms: number;
    entropy: number;        // 0..1 normalised Shannon entropy
    viscosity: number;       // unbounded; expect ~0..0.5
    label: string;
    phase_transition_warning: boolean;
};

/**
 * Project a point at parametric `t` (0..1) along the great-circle arc
 * between two lng/lat positions. Uses spherical linear interpolation —
 * matches Deck.gl's ArcLayer { greatCircle: true } so particles ride
 * exactly on top of the rendered arc geometry.
 */
function greatCircleAt(
    srcLon: number, srcLat: number,
    tgtLon: number, tgtLat: number,
    t: number,
): [number, number] {
    const lat1 = (srcLat * Math.PI) / 180;
    const lon1 = (srcLon * Math.PI) / 180;
    const lat2 = (tgtLat * Math.PI) / 180;
    const lon2 = (tgtLon * Math.PI) / 180;
    const d = 2 * Math.asin(Math.sqrt(
        Math.sin((lat2 - lat1) / 2) ** 2 +
        Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2,
    ));
    if (!isFinite(d) || d === 0) return [srcLon, srcLat];
    const A = Math.sin((1 - t) * d) / Math.sin(d);
    const B = Math.sin(t * d) / Math.sin(d);
    const x = A * Math.cos(lat1) * Math.cos(lon1) + B * Math.cos(lat2) * Math.cos(lon2);
    const y = A * Math.cos(lat1) * Math.sin(lon1) + B * Math.cos(lat2) * Math.sin(lon2);
    const z = A * Math.sin(lat1) + B * Math.sin(lat2);
    const lat = (Math.atan2(z, Math.sqrt(x * x + y * y)) * 180) / Math.PI;
    const lon = (Math.atan2(y, x) * 180) / Math.PI;
    return [lon, lat];
}

/**
 * Local time-machine state. Append-only with hard 24h trim. The history is
 * scrubable; `currentIndex == series.length - 1` is "live mode" and the
 * panel auto-advances when new points arrive.
 */
class TimeMachineState {
    series: HistoryPoint[] = [];
    currentIndex: number = -1;

    isLive(): boolean {
        return this.currentIndex < 0 || this.currentIndex >= this.series.length - 1;
    }

    point(): HistoryPoint | null {
        if (this.series.length === 0) return null;
        const idx = this.currentIndex < 0 ? this.series.length - 1 : this.currentIndex;
        return this.series[Math.max(0, Math.min(idx, this.series.length - 1))];
    }

    /** Merge new points into the history. Caller passes the full series the
     *  API returned; we dedupe by timestamp and re-trim to 24h. */
    ingest(rawSeries: any[]): { newPoints: number } {
        let added = 0;
        let updated = 0;
        const seeds = this.series.filter((p) => p.label === 'SEED');
        const history = this.series.filter((p) => p.label !== 'SEED');
        const byTs = new Map(history.map((p) => [p.timestamp, p]));

        for (const raw of rawSeries || []) {
            const point = normalizeHistoryRawPoint(raw);
            if (!point) continue;
            if (byTs.has(point.timestamp)) {
                byTs.set(point.timestamp, point);
                updated++;
            } else {
                byTs.set(point.timestamp, point);
                added++;
            }
        }

        this.series = [...seeds, ...[...byTs.values()].sort((a, b) => a.epoch_ms - b.epoch_ms)];

        // Trim to last TM_HISTORY_HOURS window (never drop SEED).
        const cutoff = Date.now() - TM_HISTORY_HOURS * 3600_000;
        const trimmedSeeds = this.series.filter((p) => p.label === 'SEED');
        const trimmedHistory = this.series
            .filter((p) => p.label !== 'SEED' && p.epoch_ms >= cutoff);
        this.series = [...trimmedSeeds, ...trimmedHistory];

        if (this.series.length === 0) {
            this.currentIndex = -1;
        } else if (this.currentIndex < 0 || this.currentIndex >= this.series.length) {
            this.currentIndex = this.series.length - 1;
        }
        return { newPoints: added + updated };
    }

    seek(idx: number): void {
        if (this.series.length === 0) return;
        this.currentIndex = Math.max(0, Math.min(idx, this.series.length - 1));
    }
}

function clamp01(x: number): number {
    if (!isFinite(x)) return 0;
    return Math.max(0, Math.min(1, x));
}

/** Normalise one fragility-history row from the API (flat schema, no wrappers). */
function normalizeHistoryRawPoint(raw: any): HistoryPoint | null {
    if (!raw || typeof raw !== 'object') return null;
    const tsRaw = raw.timestamp ?? raw.snapshot_timestamp;
    let timestamp = '';
    if (typeof tsRaw === 'string') {
        timestamp = tsRaw;
    } else if (typeof tsRaw === 'number' && isFinite(tsRaw)) {
        timestamp = new Date(tsRaw).toISOString();
    } else {
        return null;
    }
    const epoch = Date.parse(timestamp);
    if (!isFinite(epoch)) return null;
    return {
        timestamp,
        epoch_ms: epoch,
        entropy: clamp01(Number(raw.entropy_index ?? raw.entropy ?? 0)),
        viscosity: Math.max(0, Number(raw.viscosity_coefficient ?? raw.viscosity ?? 0)),
        label: String(raw.label ?? ''),
        phase_transition_warning: Boolean(raw.phase_transition_warning),
    };
}

/**
 * Build headline HUD metrics from live map nodes, with optional timeline point
 * overlay when the user is scrubbing history.
 */
function buildStatsHudPayload(
    nodes: SpatialNode[],
    pt: HistoryPoint | null,
    fallbackImpact: number,
    // null = "no measured edges to average" → the HUD prints "--", not a fake 0.000.
    fallbackEdgeIntensity: number | null = null,
): SpatialContagion {
    // The epicenter is the node the payload DECLARES as such. Only fall back to
    // "highest score" when no epicenter is declared — and rank unmeasured nodes
    // last (-1) rather than treating a null as 0, which would let an unmeasured
    // node tie with a genuinely zero-impact one.
    const epicenter =
        nodes.find((n) => n.type === 'epicenter') ??
        [...nodes].sort(
            (a, b) => (b.impact_score ?? -1) - (a.impact_score ?? -1),
        )[0];
    const impactVal = pt
        ? pt.entropy * 100
        : (epicenter?.impact_score ?? fallbackImpact);
    const edgeVal = pt ? pt.viscosity : fallbackEdgeIntensity;
    return {
        nodes,
        edges: [],
        // Cast: these are `number` on SpatialContagion, but the HUD renderer reads
        // them as nullable so it can print "--" for genuinely-unknown stats.
        epicenter_impact_score: impactVal as number,
        edge_intensity: edgeVal as number,
        node_count: nodes.length,
        edge_count: 0,
    };
}


type SurveillanceMapCtorArgs = {
    container: HTMLElement;
    wrapEl: HTMLElement;
    mapEl: HTMLElement;
    overlay: any;                  // deck.gl MapboxOverlay
    arcLayer: any;
    affectedLayer: any;
    epicenterLayer: any;
    /** Hollow grey ring layer for exposed_unquantified nodes. Optional so the
     *  legacy renderGlobalSurveillanceMap() path can omit it. */
    exposedLayer?: any;
    /** Faint grey arc layer for unquantified edges. */
    unquantifiedArcLayer?: any;
    ScatterplotLayer: any;
    /** @deck.gl/layers IconLayer constructor — static-cascade reticle glyphs. Optional:
     *  absent → the static path falls back to the standard dot layers. */
    IconLayer?: any;
    /** @deck.gl/layers ArcLayer constructor — required for forecast ghost arcs.
     *  Optional only because the legacy renderGlobalSurveillanceMap() path
     *  predates Phase 6 forecast mode and doesn't supply it. */
    ArcLayerCtor?: any;
    /** @deck.gl/layers TextLayer constructor — used for critical entity labels. */
    TextLayer?: any;
    nodes: SpatialNode[];
    edgesFlat: ResolvedEdge[];
    domainId: string;
    epicenterScore: number;
    /**
     * When false, the controller does NOT poll
     * `/pro/domains/{domainId}/fragility-history`. Used by the Global
     * aggregate view (no per-domain endpoint exists for it), so the
     * animation still runs from payload-embedded entropy/viscosity but
     * the time-machine slider stays disabled.
     */
    enableHistoryPolling?: boolean;
    /** A vault scenario cascade: one snapshot, no time axis. Disables the scrubber
     *  and relabels the panel instead of leaving a dead control that looks broken. */
    staticScenario?: boolean;
    /** Placeless payload fields (conduits / no_map / honest_gaps / credit_gaps) — for the static
     *  OFF-MAP panel and the company panel's Credit section.
     *  Verbatim from the payload; absent for non-scenario domains.
     *  credit_gaps is inlined rather than given an exported type: Conduit/OffMapNode/HonestGaps are
     *  exported because they appear in the exported SpatialContagion; this one is read only here. */
    offMap?: {
        conduits?: Conduit[];
        no_map?: OffMapNode[];
        honest_gaps?: HonestGaps;
        credit_gaps?: Array<{ id: string; kind?: string; reason?: string; slice?: string }>;
    };
    /** RAW payload edges (with source_id/target_id) — the adjacency the map-free GRAPH view needs.
     *  edgesFlat is coordinate-only, so it cannot supply the id join. */
    graphEdges?: SpatialEdge[];
    /** Fallback entropy when polling is disabled. */
    seedEntropy?: number;
    /** Fallback viscosity when polling is disabled. */
    seedViscosity?: number;
    /**
     * MapLibre Map instance. When supplied, `map.triggerRepaint()` is called
     * at the end of every repaintLayers() so the animation loop never freezes
     * when the map is idle (interleaved mode: MapLibre owns the render loop).
     */
    mapRef?: any;
};

class SurveillanceMapController {
    private readonly args: SurveillanceMapCtorArgs;
    private readonly state = new TimeMachineState();

    // UI handles
    private panel!: HTMLElement;
    private playBtn!: HTMLButtonElement;
    private slider!: HTMLInputElement;
    private dateLabel!: HTMLElement;
    private metricsLabel!: HTMLElement;
    private liveDot!: HTMLElement;
    private warningChip!: HTMLElement;
    // Phase 6 — glassmorphic event ticker (sits directly above the slider).
    // Events are derived from nodes + history spikes and re-evaluated every
    // refreshPanel(); the strip auto-scrolls so the chip nearest the scrub
    // cursor sits at the centre.
    private tickerPanel!: HTMLElement;
    private tickerStrip!: HTMLElement;
    private tickerCursor!: HTMLElement;
    private tickerEvents: { epoch_ms: number; severity: 'crit' | 'warn' | 'info'; text: string }[] = [];
    // Phase 6 — Forecast Mode: ghosted +48h predicted ripples overlaid on top
    // of the current state. Entropy + viscosity are linearly extrapolated
    // from the last ~6 history points.
    private forecastMode = false;
    private forecastBtn!: HTMLButtonElement;

    // Animation + polling timers
    private rafId: number | null = null;
    private lastFrameAt = 0;
    private animationPhase = 0;       // 0..1 — particle position along each arc
    private playTimer: number | null = null;
    private pollTimer: number | null = null;
    private aborted = false;
    /** Unsubscribe fns drained by stop() — see addCleanup(). */
    private cleanups: Array<() => void> = [];
    private offsets: number[] = [];    // per-arc phase offsets so particles are staggered
    // Phase 6.5.9 — has at least one history poll attempt completed (success
    // OR failure)? Lets refreshPanel() distinguish the cold "Awaiting history…"
    // boot state from the steady "polled, but the backend has no history for
    // this domain" state (→ "LIVE ONLY · NO HISTORY", slider parked). Without
    // this the global panel sticks on "AWAITING HISTORY…" forever whenever the
    // aggregate timeline is empty.
    private historyPolled = false;

    constructor(args: SurveillanceMapCtorArgs) {
        this.args = args;
        // Stagger each arc's particles so the visual doesn't pulse in lockstep
        for (let i = 0; i < this.args.edgesFlat.length; i++) {
            this.offsets.push((i * 0.17) % 1);
        }
    }

    start(): void {
        this.buildPanel();
        this.installTeardownHandle();
        // A static cascade has no time axis. Stamp .pm-c2 on the wrap and swap the live
        // Time Machine / Event Stream for a command-post readout + legend. Gated on
        // staticScenario, so the Pro Brief (which mounts without it) is never affected.
        if (this.args.staticScenario) { this.injectStaticChrome(); this.installNodeCard(); }
        // Seed the state with the payload's static entropy/viscosity so the
        // animation has sensible scaling values even before any polling.
        if (
            (this.args.seedEntropy ?? null) !== null ||
            (this.args.seedViscosity ?? null) !== null
        ) {
            this.state.ingest([{
                timestamp: new Date().toISOString(),
                entropy_index: this.args.seedEntropy ?? 0,
                viscosity_coefficient: this.args.seedViscosity ?? 0,
                label: 'SEED',
                phase_transition_warning: false,
            }]);
        }
        // History polling is opt-in: the Global aggregate view passes
        // enableHistoryPolling=false because /pro/domains/global/... has no
        // per-domain endpoint. The animation still runs from the seed.
        if (this.args.enableHistoryPolling !== false) {
            void this.pollHistoryOnce();
            this.pollTimer = window.setInterval(() => {
                if (!this.aborted) void this.pollHistoryOnce();
            }, TM_POLL_INTERVAL_MS);
        } else {
            // Mark the panel so the user understands why scrubbing is locked
            // — single neutral line, NOT a "Coming Soon" placeholder.
            this.refreshPanel();
        }
        // Start the animation loop
        this.lastFrameAt = performance.now();
        this.rafId = requestAnimationFrame(this.frame);
    }

    /**
     * Idempotent teardown. INVARIANT: every setProps/DOM write is `aborted`-guarded, and
     * teardown removes LISTENERS as well as timers. A stopped controller can reach nothing.
     */
    stop = (): void => {
        if (this.aborted) return;
        this.aborted = true;
        if (this.rafId !== null) cancelAnimationFrame(this.rafId);
        if (this.playTimer !== null) window.clearInterval(this.playTimer);
        if (this.pollTimer !== null) window.clearInterval(this.pollTimer);
        this.rafId = this.playTimer = this.pollTimer = null;
        // Unsubscribe anything registered via addCleanup() (e.g. map 'zoomend').
        // A listener outliving its controller is worse than a dead write: a zoom event
        // would drive a DEAD controller's repaintLayers() into the LIVE overlay.
        for (const fn of this.cleanups) {
            try { fn(); } catch { /* teardown must never throw */ }
        }
        this.cleanups.length = 0;
        this.panel?.remove();
        this.tickerPanel?.remove();
    };

    /** Register an unsubscribe fn to run on stop(). Fires immediately if already stopped. */
    public addCleanup(fn: () => void): void {
        if (this.aborted) { try { fn(); } catch { /* ignore */ } return; }
        this.cleanups.push(fn);
    }

    private installTeardownHandle(): void {
        // Persist the teardown so future mounts (e.g. domain swap) can clean
        // up the previous instance. Also auto-stop if the wrap is removed.
        (this.args.wrapEl as any).__scTeardown = this.stop;
        const observer = new MutationObserver(() => {
            if (!document.body.contains(this.args.wrapEl)) {
                observer.disconnect();
                this.stop();
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
        // No exceptions to the invariant: stop() unsubscribes this too. On a domain/scenario
        // switch the wrapEl SURVIVES, so the self-disconnect above never fires and a
        // document-wide subtree observer would leak (holding a dead controller) per switch.
        this.addCleanup(() => observer.disconnect());
    }

    /**
     * Static-cascade chrome (.pm-c2 idiom). The CSS hides the live Time Machine + Event
     * Stream and this adds three overlays in the Stage-1 command-post register: corner
     * brackets, a bottom-left legend, and a bottom-right "STATIC CASCADE · NO TIME SERIES"
     * readout. Deliberately no entropy/viscosity number: for a scenario domain both are
     * stored as 0.0 sentinels ("not applicable"), so printing 0.000 would assert a
     * measurement that was never made — the same lie removed everywhere else.
     */
    private injectStaticChrome(): void {
        const wrap = this.args.wrapEl;
        wrap.classList.add('pm-c2');
        const chrome = document.createElement('div');
        chrome.className = 'pm-c2-chrome';
        chrome.innerHTML = `
            <div class="pm-c2-frame" aria-hidden="true">
                <i class="pm-c2-corner pm-c2-corner--tl"></i><i class="pm-c2-corner pm-c2-corner--tr"></i>
                <i class="pm-c2-corner pm-c2-corner--bl"></i><i class="pm-c2-corner pm-c2-corner--br"></i>
            </div>
            <div class="pm-c2-legend">
                <div class="pm-c2-leg-row"><span class="pm-c2-sw pm-c2-sw--epi"></span>Epicenter</div>
                <div class="pm-c2-leg-row"><span class="pm-c2-sw pm-c2-sw--aff"></span>Affected · measured</div>
                <div class="pm-c2-leg-row"><span class="pm-c2-sw pm-c2-sw--unq"></span>Exposed · magnitude unknown</div>
            </div>
            <div class="pm-c2-static">Static cascade · no time series</div>
            <button type="button" class="pm-c2-graphbtn" aria-label="Open the relationship graph">◈ Graph</button>`;
        wrap.appendChild(chrome);
        this.addCleanup(() => { chrome.remove(); wrap.classList.remove('pm-c2'); });

        // GRAPH view — a full-panel overlay that COVERS the map (the map is NOT unmounted). It
        // carries the off-map nodes as first-class diamonds, replacing the old OFF-MAP text panel.
        const graphBtn = chrome.querySelector<HTMLButtonElement>('.pm-c2-graphbtn');
        if (graphBtn) {
            const onGraph = (): void => this.openGraph();
            graphBtn.addEventListener('click', onGraph);
            this.addCleanup(() => graphBtn.removeEventListener('click', onGraph));
        }
    }

    // ─── Map-free GRAPH view (static cascade only) ───────────────────────
    private graphEl: HTMLElement | null = null;
    private graphCardEl: HTMLElement | null = null;

    /** Open the relationship graph as a full-panel overlay OVER the map. The map is NOT unmounted —
     *  it stays live underneath; closing just hides this overlay. Built once (deterministic radial
     *  layout, no force sim), so it looks identical every open. */
    private openGraph(): void {
        if (this.graphEl) { this.graphEl.style.display = 'flex'; return; }
        const host = this.args.wrapEl.parentElement ?? this.args.wrapEl;
        const el = document.createElement('div');
        el.className = 'pm-graph';
        const epiName = this.args.nodes.find((n) => n.type === 'epicenter')?.name ?? this.args.domainId;
        el.innerHTML = `
            <div class="pm-graph-head">
                <span class="pm-graph-title">Cascade graph · ${esc(String(epiName))}</span>
                <button type="button" class="pm-graph-close">&times; Map</button>
            </div>
            ${this.buildGraphSvg()}
            <div class="pm-graph-legend">
                <span><i class="pm-gl pm-gl--epi"></i>Epicenter</span>
                <span><i class="pm-gl pm-gl--aff"></i>Affected · size = impact</span>
                <span><i class="pm-gl pm-gl--unq"></i>Exposed · dashed, magnitude unknown</span>
                <span><i class="pm-gl pm-gl--om"></i>Off-map · market/org, no coordinates</span>
                <span><i class="pm-gl pm-gl--der"></i>Dotted edge = derived from weight, not a payload edge</span>
            </div>`;
        host.appendChild(el);
        this.graphEl = el;

        const onClick = (ev: Event): void => {
            const target = ev.target as HTMLElement;
            if (target.closest('.pm-graph-close')) { this.closeGraph(); return; }
            const g = target.closest<HTMLElement>('.pm-g-node');
            if (!g) { this.hideGraphCard(); return; }
            const rect = el.getBoundingClientRect();
            const x = (ev as MouseEvent).clientX - rect.left;
            const y = (ev as MouseEvent).clientY - rect.top;
            const nid = g.getAttribute('data-nid');
            const omid = g.getAttribute('data-omid');
            if (nid) {
                const node = this.args.nodes.find((n) => String(n.id) === nid);
                if (node) {
                    if (this.isCompany(node)) { this.openCompanyPanel(node); return; }
                    const role = node.type === 'epicenter' ? 'epi' : node.type === 'affected' ? 'aff' : 'unq';
                    this.graphShowCard(this.buildNodeCardHtml(node), role, x, y);
                }
            } else if (omid) {
                const om = (this.args.offMap?.no_map ?? []).find((o) => String(o.id) === omid);
                if (om) this.graphShowCard(this.buildOffMapCardHtml(om), 'unq', x, y);
            }
        };
        el.addEventListener('click', onClick);
        this.addCleanup(() => { el.removeEventListener('click', onClick); el.remove(); this.graphEl = null; });
    }

    private closeGraph(): void {
        if (this.graphEl) this.graphEl.style.display = 'none';
        this.hideGraphCard();
    }

    private hideGraphCard(): void {
        if (this.graphCardEl) this.graphCardEl.style.display = 'none';
    }

    private graphShowCard(html: string, roleCls: string, x: number, y: number): void {
        if (!this.graphEl) return;
        let card = this.graphCardEl;
        if (!card) { card = document.createElement('div'); this.graphEl.appendChild(card); this.graphCardEl = card; }
        card.className = `sc-node-card sc-node-card--${roleCls} pm-graph-card`;
        card.innerHTML = html;
        card.style.display = 'block';
        const gr = this.graphEl.getBoundingClientRect();
        const cw = card.offsetWidth || 220;
        const ch = card.offsetHeight || 160;
        let cx = x + 14;
        if (cx + cw > gr.width) cx = x - cw - 14;
        cx = Math.max(8, Math.min(cx, gr.width - cw - 8));
        let cy = y - ch / 2;
        cy = Math.max(8, Math.min(cy, gr.height - ch - 8));
        card.style.left = `${Math.round(cx)}px`;
        card.style.top = `${Math.round(cy)}px`;
    }

    /** Card for an off-map node — it has no cascade role/coords, so a small variant (id · type ·
     *  weight; "--" for null, never 0). */
    private buildOffMapCardHtml(om: OffMapNode): string {
        const weight = om.raw_impact == null ? '--' : String(om.raw_impact);
        return `<button type="button" class="sc-node-card-close" aria-label="Close">&times;</button>
            <div class="sc-card-name">${esc(String(om.id ?? '—'))}</div>
            <div class="sc-card-role">Off-map · ${esc(String(om.type ?? ''))} — no coordinates</div>
            <div class="sc-card-rows"><div class="sc-card-row"><span class="sc-card-k">Weight</span><span class="sc-card-v">${weight}</span></div></div>
            ${om.reason ? `<div class="sc-card-why">${esc(String(om.reason))}</div>` : ''}`;
    }

    /**
     * Deterministic radial layout of ONE cascade — no force sim, so it's identical every open.
     * Rings by order: centre=epicenter, R1=order-2, R2=order-3 (placed within their parent's angular
     * sector so the tree reads), ROFF=off-map (a synthesised hub→node edge from no_map.raw_impact,
     * drawn DOTTED to mark it derived-from-weight, not a payload edge). It is a DAG: every payload
     * edge is drawn, so a node with two parents keeps both (Malacca's Mitsui/NYK: measured via Japan
     * + an unquantified dashed direct edge from the strait).
     */
    private buildGraphSvg(): string {
        const CX = 500, CY = 500, TAU = Math.PI * 2, TOP = -Math.PI / 2;
        const R1 = 185, R2 = 350, ROFF = 470;
        const nodes = this.args.nodes;
        const edges = this.args.graphEdges ?? [];
        const noMap = Array.isArray(this.args.offMap?.no_map) ? (this.args.offMap!.no_map as OffMapNode[]) : [];
        const idOf = (n: any): string => String(n.id ?? '');

        const epi = nodes.find((n) => n.type === 'epicenter');
        const hubId = epi ? idOf(epi) : '';
        const order2 = nodes.filter((n) => n.order === 2);
        const order3 = nodes.filter((n) => n.order === 3);
        const o2ids = new Set(order2.map(idOf));

        const parentsOf = new Map<string, string[]>();
        const addTo = (m: Map<string, string[]>, k: string, v: string): void => { const a = m.get(k); if (a) a.push(v); else m.set(k, [v]); };
        for (const e of edges) {
            if (!e.source_id || !e.target_id) continue;
            addTo(parentsOf, e.target_id, e.source_id);
        }

        // Group order-3 under their PRIMARY order-2 parent; hub-only order-3 are "orphans".
        const o3ByParent = new Map<string, SpatialNode[]>();
        const orphans: SpatialNode[] = [];
        for (const c of order3) {
            const o2p = (parentsOf.get(idOf(c)) ?? []).find((p) => o2ids.has(p));
            if (o2p) addToNode(o3ByParent, o2p, c);
            else orphans.push(c);
        }
        function addToNode(m: Map<string, SpatialNode[]>, k: string, v: SpatialNode): void { const a = m.get(k); if (a) a.push(v); else m.set(k, [v]); }

        const o2sorted = [...order2].sort((a, b) => (idOf(a) < idOf(b) ? -1 : 1));
        const N2 = o2sorted.length || 1;
        const childCounts = o2sorted.map((o) => o3ByParent.get(idOf(o))?.length ?? 0);
        const totalChildren = childCounts.reduce((s, c) => s + c, 0);
        // Every order-2 node gets a GUARANTEED minimum sector (60% of the equal share) so childless
        // high-impact nodes (Iraq/Iran/India) are not crushed. The rest is a child-proportional BONUS,
        // then re-weighted by |cos(angle)| (two-pass: lay out once to get each fan's angle, then give
        // HORIZONTAL fans — 3/9 o'clock, where horizontal labels run into each other — more width than
        // vertical ones, where labels stack). The min stays fixed. Deterministic: order is by id.
        const MIN_SECTOR = (TAU / N2) * 0.6;
        const ORPH_SECTOR = orphans.length ? (TAU / N2) * 0.5 : 0;
        const bonusTotal = Math.max(0, TAU - N2 * MIN_SECTOR - ORPH_SECTOR);
        const evenBonus = childCounts.map((c) => (totalChildren > 0 ? bonusTotal * (c / totalChildren) : bonusTotal / N2));
        let paAcc = 0; const provAng: number[] = [];
        for (let i = 0; i < N2; i++) { const wi = MIN_SECTOR + evenBonus[i]; provAng.push(paAcc + wi / 2 + TOP); paAcc += wi; }
        const wBonus = evenBonus.map((b, i) => b * (1 + 0.9 * Math.abs(Math.cos(provAng[i]))));
        const wSum = wBonus.reduce((s, b) => s + b, 0) || 1;
        const sectorW = wBonus.map((b) => MIN_SECTOR + bonusTotal * (b / wSum));

        // id → {x, y, ang}; ang drives the OUTWARD label anchoring below.
        const pos = new Map<string, { x: number; y: number; ang: number }>();
        const place = (id: string, r: number, a: number): void => { pos.set(id, { x: CX + r * Math.cos(a), y: CY + r * Math.sin(a), ang: a }); };
        if (epi) pos.set(hubId, { x: CX, y: CY, ang: 0 });

        const SUBRINGS = 5, RSTEP = 32;
        // 5 sub-rings + push horizontal children (|cos| large) further out, where the arc is longer,
        // so same-ring siblings separate. Names stay full — never truncated, never rotated.
        const childR = (j: number, a: number): number => R2 + (j % SUBRINGS) * RSTEP + Math.abs(Math.cos(a)) * 42;
        let ang = 0;
        for (let i = 0; i < o2sorted.length; i++) {
            const w = sectorW[i];
            const start = ang; ang += w;
            place(idOf(o2sorted[i]), R1, (start + ang) / 2 + TOP);
            const kids = o3ByParent.get(idOf(o2sorted[i])) ?? [];
            for (let j = 0; j < kids.length; j++) {
                const f = kids.length === 1 ? 0.5 : 0.1 + (0.8 * j) / (kids.length - 1);
                const a = start + w * f + TOP;
                place(idOf(kids[j]), childR(j, a), a);
            }
        }
        for (let j = 0; j < orphans.length; j++) {
            const f = orphans.length === 1 ? 0.5 : j / (orphans.length - 1);
            const a = ang + ORPH_SECTOR * f + TOP;
            place(idOf(orphans[j]), childR(j, a), a);
        }
        noMap.forEach((n, k) => place(`om:${n.id}`, ROFF, (k / Math.max(1, noMap.length)) * TAU + TOP));

        const parts: string[] = [];
        // Edges first (so nodes sit on top). Payload edges: solid, width = intensity; unquantified dashed.
        for (const e of edges) {
            const s = pos.get(e.source_id); const t = pos.get(e.target_id);
            if (!s || !t) continue;
            const w = e.unquantified ? 1 : Math.max(0.6, (e.intensity ?? 0) * 2.4);
            parts.push(`<line class="pm-g-edge${e.unquantified ? ' pm-g-edge--unq' : ''}" x1="${s.x.toFixed(1)}" y1="${s.y.toFixed(1)}" x2="${t.x.toFixed(1)}" y2="${t.y.toFixed(1)}" stroke-width="${w.toFixed(2)}"/>`);
        }
        // Derived off-map edges (hub → off-map): dotted, distinct — NOT in edges[].
        const hub = pos.get(hubId);
        if (hub) noMap.forEach((n) => {
            const p = pos.get(`om:${n.id}`); if (!p) return;
            parts.push(`<line class="pm-g-edge pm-g-edge--derived" x1="${hub.x.toFixed(1)}" y1="${hub.y.toFixed(1)}" x2="${p.x.toFixed(1)}" y2="${p.y.toFixed(1)}"/>`);
        });

        const num = (v: number | null | undefined): string => (v == null ? '--' : String(Math.round(v)));
        const geoR = (n: any): number =>
            (n.type === 'exposed_unquantified' || n.impact_score == null)
                ? 9                                                              // fixed small — never zero-sized
                : 9 + (Math.min(100, Math.max(0, n.impact_score)) / 100) * 15;  // 9..24 by impact
        // OUTWARD label placement: text grows AWAY from the centre — right-half start-anchored,
        // left-half end-anchored — so long names (KAWASAKI HEAVY INDUSTRIES) extend outward instead
        // of across their neighbours toward the centre. Epicenter label sits centred above the hub.
        const labelAttrs = (a: number, r: number, isEpi: boolean): { anchor: string; x: string; y: string } => {
            if (isEpi) return { anchor: 'middle', x: '0', y: (-(r + 8)).toFixed(1) };
            const c = Math.cos(a), s = Math.sin(a);
            return { anchor: c >= 0 ? 'start' : 'end', x: (c >= 0 ? r + 6 : -(r + 6)).toFixed(1), y: (5 + s * 5).toFixed(1) };
        };
        for (const n of nodes) {
            const p = pos.get(idOf(n)); if (!p) continue;
            const r = geoR(n);
            const role = n.type === 'epicenter' ? 'epi' : n.type === 'affected' ? 'aff' : 'unq';
            const la = labelAttrs(p.ang, r, n.type === 'epicenter');
            parts.push(`<g class="pm-g-node pm-g-node--${role}" data-nid="${esc(idOf(n))}" transform="translate(${p.x.toFixed(1)},${p.y.toFixed(1)})">`
                + `<circle r="${r.toFixed(1)}"/>`
                + `<text class="pm-g-label" text-anchor="${la.anchor}" x="${la.x}" y="${la.y}">${esc(String(n.name ?? n.id ?? ''))} ${num(n.impact_score)}</text></g>`);
        }
        // Off-map nodes: DIAMONDS (different shape) in a distinct hue — a different kind of thing.
        noMap.forEach((n) => {
            const p = pos.get(`om:${n.id}`); if (!p) return;
            const r = n.raw_impact == null ? 8 : 8 + Math.min(1, Math.max(0, n.raw_impact)) * 7;   // small, own (0..1) scale
            const la = labelAttrs(p.ang, r, false);
            parts.push(`<g class="pm-g-node pm-g-node--om" data-omid="${esc(String(n.id))}" transform="translate(${p.x.toFixed(1)},${p.y.toFixed(1)})">`
                + `<path d="M 0 ${-r} L ${r} 0 L 0 ${r} L ${-r} 0 Z"/>`
                + `<text class="pm-g-label pm-g-label--om" text-anchor="${la.anchor}" x="${la.x}" y="${la.y}">${esc(String(n.id))} ${n.raw_impact == null ? '--' : String(n.raw_impact)}</text></g>`);
        });

        return `<svg class="pm-graph-svg" viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid meet">${parts.join('')}</svg>`;
    }

    // ─── Node detail card (static cascade only) ──────────────────────────
    private cardEl: HTMLElement | null = null;
    private activeNodeId: string | null = null;
    private cardMoveHandler: (() => void) | null = null;

    /** Immersive company detail panels, keyed by node id — MULTIPLE may be open at once (unlike the
     *  single node card). Each is torn down on its own close and all of them on stop(). */
    private companyPanels = new Map<string, HTMLElement>();
    /** Monotonic spawn counter so a second panel cascades off the first instead of landing on it. */
    private panelSpawns = 0;
    /** Top of the panel z-stack; bumped on bring-to-front. Above the card (8) and graph (20). */
    private panelTopZ = 40;

    /** Wire click→card: a reticle click opens a detail card; empty-map click closes it. Also
     *  exposes wrapEl.__scFocusNode(id) so drawer rows can open the same card. */
    private installNodeCard(): void {
        const card = document.createElement('div');
        card.className = 'sc-node-card';
        card.style.display = 'none';
        this.args.wrapEl.appendChild(card);
        this.cardEl = card;
        this.addCleanup(() => { card.remove(); this.cardEl = null; });

        // onClick merges into the overlay's existing props (getTooltip/layers survive; the
        // per-frame setProps({layers}) does not clobber it).
        this.args.overlay.setProps({
            onClick: (info: any): void => {
                const obj = info?.object;
                if (obj && (obj.type === 'epicenter' || obj.type === 'affected' || obj.type === 'exposed_unquantified')) {
                    this.showCardForNode(obj);
                } else {
                    this.hideCard();
                }
            },
        });

        const onCardClick = (e: Event): void => {
            if ((e.target as HTMLElement).closest('.sc-node-card-close')) this.hideCard();
        };
        card.addEventListener('click', onCardClick);
        this.addCleanup(() => card.removeEventListener('click', onCardClick));

        (this.args.wrapEl as any).__scFocusNode = (id: string): void => this.focusNodeById(id);
        this.addCleanup(() => { try { delete (this.args.wrapEl as any).__scFocusNode; } catch { /* ignore */ } });
    }

    private focusNodeById(id: string): void {
        const node = this.args.nodes.find((n) => String(n.id) === String(id));
        if (node) this.showCardForNode(node);
    }

    private showCardForNode(node: any): void {
        // Company nodes get the immersive detail panel, not the small card. Everything else
        // (epicenter / exposed / company-less affected) keeps the card path byte-for-byte.
        if (this.isCompany(node)) { this.openCompanyPanel(node); return; }
        if (!this.cardEl) return;
        const roleCls = node.type === 'epicenter' ? 'epi' : node.type === 'affected' ? 'aff' : 'unq';
        this.activeNodeId = String(node.id);
        this.cardEl.className = `sc-node-card sc-node-card--${roleCls}`;
        this.cardEl.innerHTML = this.buildNodeCardHtml(node);
        this.cardEl.style.display = 'block';
        this.positionCard(node);
        // Re-anchor on pan/zoom (registered once).
        if (!this.cardMoveHandler) {
            this.cardMoveHandler = (): void => {
                const n = this.args.nodes.find((x) => String(x.id) === this.activeNodeId);
                if (n && this.cardEl && this.cardEl.style.display !== 'none') this.positionCard(n);
            };
            this.args.mapRef?.on('move', this.cardMoveHandler);
            this.addCleanup(() => { if (this.cardMoveHandler) this.args.mapRef?.off('move', this.cardMoveHandler); });
        }
    }

    /** Anchor beside the node; flip to the other side on horizontal overflow, clamp to the wrap. */
    private positionCard(node: any): void {
        const card = this.cardEl;
        const map = this.args.mapRef;
        if (!card || !map || node.lon == null || node.lat == null) return;
        const p = map.project([node.lon, node.lat]);
        const w = this.args.wrapEl.getBoundingClientRect();
        const cw = card.offsetWidth || 240;
        const ch = card.offsetHeight || 160;
        const gap = 16;
        let x = p.x + gap;
        if (x + cw > w.width) x = p.x - cw - gap;           // flip left
        x = Math.max(8, Math.min(x, w.width - cw - 8));      // clamp X
        let y = p.y - ch / 2;
        y = Math.max(8, Math.min(y, w.height - ch - 8));     // clamp Y
        card.style.left = `${Math.round(x)}px`;
        card.style.top = `${Math.round(y)}px`;
    }

    private hideCard(): void {
        this.activeNodeId = null;
        if (this.cardEl) this.cardEl.style.display = 'none';
    }

    /** Only fields the node object actually carries. impact → "--" for exposed/null (never 0).
     *  `why` is the payload's own provenance string (it carries the upstream/weight text — there
     *  is no structured VIA field on the node). */
    private buildNodeCardHtml(node: any): string {
        const isExposed = node.type === 'exposed_unquantified' || node.impact_score == null;
        const roleLabel = node.type === 'epicenter' ? 'Epicenter'
            : node.type === 'affected' ? 'Affected · measured'
            : 'Exposed · magnitude unknown';
        const impact = isExposed || node.impact_score == null ? '--' : Number(node.impact_score).toFixed(1);
        const rows: string[] = [
            `<div class="sc-card-row"><span class="sc-card-k">Impact</span><span class="sc-card-v">${impact}</span></div>`,
        ];
        if (node.order != null) rows.push(`<div class="sc-card-row"><span class="sc-card-k">Order</span><span class="sc-card-v">O${esc(String(node.order))}</span></div>`);
        if (node.country) rows.push(`<div class="sc-card-row"><span class="sc-card-k">Country</span><span class="sc-card-v">${esc(String(node.country))}</span></div>`);
        if (node.lat != null && node.lon != null) {
            const coord = `${Math.abs(node.lat).toFixed(2)}${node.lat >= 0 ? 'N' : 'S'} ${Math.abs(node.lon).toFixed(2)}${node.lon >= 0 ? 'E' : 'W'}`;
            rows.push(`<div class="sc-card-row"><span class="sc-card-k">Coord</span><span class="sc-card-v">${coord}</span></div>`);
        }
        const why = node.why ? `<div class="sc-card-why">${esc(String(node.why))}</div>` : '';
        return `<button type="button" class="sc-node-card-close" aria-label="Close">&times;</button>
            <div class="sc-card-name">${esc(String(node.name ?? node.id ?? '—'))}</div>
            <div class="sc-card-role">${esc(roleLabel)}</div>
            <div class="sc-card-rows">${rows.join('')}</div>
            ${why}`;
    }

    // ─── Immersive company detail panel (static path only) ───────────────────

    /** A company node carries JSON-merged detail the DB has no column for. Only `affected` nodes
     *  are ever enriched, and `title` is the reliable marker the panel needs. Countries/routes and
     *  the epicenter/exposed nodes fail this and keep the small card. */
    private isCompany(node: any): boolean {
        return node?.type === 'affected' && node?.title != null;
    }

    /** Open (or re-focus) the floating detail panel for a company node. Panels are keyed by id so a
     *  second click on the same company brings its existing panel forward rather than duplicating it;
     *  distinct companies stack, cascading their spawn so they never land exactly on each other. */
    private openCompanyPanel(node: any): void {
        const id = String(node.id);
        const existing = this.companyPanels.get(id);
        if (existing) { this.bringPanelToFront(existing); return; }

        // Float above BOTH the map card and the graph overlay — same host the graph mounts on.
        const host = (this.args.wrapEl.parentElement ?? this.args.wrapEl) as HTMLElement;
        const panel = document.createElement('div');
        panel.className = 'pm-co-panel';
        panel.innerHTML = this.buildCompanyPanelHtml(node);
        // Cascade: base inset + step per already-spawned panel, wrapped so it stays on-screen.
        const step = (this.panelSpawns++ % 6) * 26;
        panel.style.left = `${28 + step}px`;
        panel.style.top = `${28 + step}px`;
        panel.style.zIndex = String(++this.panelTopZ);
        host.appendChild(panel);
        this.companyPanels.set(id, panel);

        const head = panel.querySelector<HTMLElement>('.pm-co-head');

        // Bring-to-front on any interaction with the panel.
        const onFront = (): void => this.bringPanelToFront(panel);
        panel.addEventListener('pointerdown', onFront);

        // Controls: close / maximise (via delegation so innerHTML stays simple).
        const onClick = (e: Event): void => {
            const t = e.target as HTMLElement;
            if (t.closest('.pm-co-close')) { this.closeCompanyPanel(id); return; }
            if (t.closest('.pm-co-max')) { panel.classList.toggle('pm-co-panel--max'); this.bringPanelToFront(panel); }
        };
        panel.addEventListener('click', onClick);

        // Drag by the header (never while maximised; never when the pointer is on a control button).
        let dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
        const onMove = (e: PointerEvent): void => {
            if (!dragging) return;
            const wrap = host.getBoundingClientRect();
            const nx = Math.max(0, Math.min(ox + (e.clientX - sx), wrap.width - panel.offsetWidth));
            const ny = Math.max(0, Math.min(oy + (e.clientY - sy), wrap.height - panel.offsetHeight));
            panel.style.left = `${Math.round(nx)}px`;
            panel.style.top = `${Math.round(ny)}px`;
        };
        const onUp = (): void => {
            dragging = false;
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
        };
        const onDown = (e: PointerEvent): void => {
            if ((e.target as HTMLElement).closest('button')) return;
            if (panel.classList.contains('pm-co-panel--max')) return;
            dragging = true;
            sx = e.clientX; sy = e.clientY;
            ox = panel.offsetLeft; oy = panel.offsetTop;
            window.addEventListener('pointermove', onMove);
            window.addEventListener('pointerup', onUp);
            e.preventDefault();
        };
        head?.addEventListener('pointerdown', onDown);

        // Teardown: remove the DOM + all listeners, both on per-panel close and on stop().
        this.addCleanup(() => {
            panel.removeEventListener('pointerdown', onFront);
            panel.removeEventListener('click', onClick);
            head?.removeEventListener('pointerdown', onDown);
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
            panel.remove();
            this.companyPanels.delete(id);
        });
    }

    private bringPanelToFront(panel: HTMLElement): void {
        panel.style.zIndex = String(++this.panelTopZ);
    }

    private closeCompanyPanel(id: string): void {
        const panel = this.companyPanels.get(id);
        if (panel) panel.remove();
        this.companyPanels.delete(id);
    }

    /** Build the panel body — only what the payload actually carries. DB-derived fields (impact_score,
     *  why, country) and JSON-merged detail (role_blurb, financials, neighbourhood) both render here. */
    private buildCompanyPanelHtml(node: any): string {
        const name = String(node.title ?? node.name ?? node.id ?? '—');
        const order = node.order != null ? `ORDER 0${esc(String(node.order))}` : 'ORDER —';
        const impact = node.impact_score == null ? '--' : Number(node.impact_score).toFixed(1);

        // Blurb — verbatim (EN for some, JP for COSCO/Saudi_Aramco). Never truncated or hidden.
        const blurb = node.role_blurb
            ? `<div class="pm-co-blurb" lang="und">${esc(String(node.role_blurb))}</div>`
            : '';

        const impactSec = `
            <section class="pm-co-sec">
                <div class="pm-co-sec-h">Impact</div>
                <div class="pm-co-kv"><span class="pm-co-k">Score</span><span class="pm-co-v">${impact}</span></div>
                ${node.why ? `<div class="pm-co-why">${esc(String(node.why))}</div>` : ''}
            </section>`;

        // Identity — country always if present; listing/tickers only when the payload carries them.
        const idRows: string[] = [];
        if (node.country) idRows.push(this.coKv('Country', String(node.country)));
        if (node.listing) idRows.push(this.coKv('Listing', String(node.listing)));
        if (Array.isArray(node.tickers) && node.tickers.length) idRows.push(this.coKv('Tickers', node.tickers.join(' · ')));
        const idSec = idRows.length
            ? `<section class="pm-co-sec"><div class="pm-co-sec-h">Identity</div>${idRows.join('')}</section>`
            : '';

        const finSec = this.buildFinancialsHtml(node.financials);
        const creditSec = this.buildCreditHtml(node);
        const nbSec = this.buildNeighbourhoodHtml(node.neighbourhood);

        return `
            <div class="pm-co-head">
                <div class="pm-co-titles">
                    <div class="pm-co-title">${esc(name)}</div>
                    <div class="pm-co-role">Company · ${order}</div>
                </div>
                <div class="pm-co-ctl">
                    <button type="button" class="pm-co-btn pm-co-max" aria-label="Maximise / restore">▢</button>
                    <button type="button" class="pm-co-btn pm-co-close" aria-label="Close">&times;</button>
                </div>
            </div>
            <div class="pm-co-body">
                ${blurb}
                ${impactSec}
                ${idSec}
                ${finSec}
                ${creditSec}
                ${nbSec}
            </div>`;
    }

    private coKv(k: string, v: string): string {
        return `<div class="pm-co-kv"><span class="pm-co-k">${esc(k)}</span><span class="pm-co-v">${esc(v)}</span></div>`;
    }

    /** Financials — each metric shows value+unit AND provenance (source + as_of). The provenance is
     *  the point: an estimated 18 usd_bn is a different claim from an observed 268. A metric that
     *  isn't in the payload is OMITTED — never rendered as 0. */
    private buildFinancialsHtml(fin: any): string {
        if (!fin || typeof fin !== 'object') return '';
        const ORDER: Array<[string, string]> = [
            ['market_cap', 'Market cap'],
            ['total_debt', 'Total debt'],
            ['equity_volatility', 'Equity volatility'],
        ];
        const known = new Set(ORDER.map(([k]) => k));
        const keys = [...ORDER.map(([k]) => k), ...Object.keys(fin).filter((k) => !known.has(k))];
        const rows: string[] = [];
        for (const key of keys) {
            const m = fin[key];
            if (!m || m.value == null) continue;                 // absent metric → omitted, never 0
            const label = (ORDER.find(([k]) => k === key)?.[1]) ?? key.replace(/_/g, ' ');
            const unit = m.unit ? `<span class="pm-co-unit">${esc(String(m.unit))}</span>` : '';
            const src = m.source ? String(m.source) : '';
            const srcCls = src === 'observed' ? 'obs' : src === 'estimated' ? 'est' : 'unk';
            const prov = [
                src ? `<span class="pm-co-src pm-co-src--${srcCls}">${esc(src)}</span>` : '',
                m.as_of ? `<span class="pm-co-asof">as of ${esc(String(m.as_of))}</span>` : '',
            ].filter(Boolean).join('');
            rows.push(`
                <div class="pm-co-fin">
                    <div class="pm-co-fin-top">
                        <span class="pm-co-fin-label">${esc(label)}</span>
                        <span class="pm-co-fin-val">${esc(String(m.value))} ${unit}</span>
                    </div>
                    ${prov ? `<div class="pm-co-prov">${prov}</div>` : ''}
                </div>`);
        }
        if (!rows.length) return '';
        return `<section class="pm-co-sec"><div class="pm-co-sec-h">Financials</div>${rows.join('')}</section>`;
    }

    /** Credit — the vault's Merton distance-to-default, and nothing derived from it.
     *
     *  d2, NOT pd. pd = Phi(-d2) underflows to exactly 0.0 in float64 once d2 clears ~8.3, so
     *  Saudi_Aramco (20.38) and NVIDIA (16.69) would emit an identical 0.0 — an arithmetic limit,
     *  not a claim about either firm. No tier word ships either: the tiers are thresholds over that
     *  same withheld pd. Shading without a verdict, as impact_score already does.
     *
     *  `bucket` rides as a .pm-co-unit ON the number rather than as its own row. It answers "which
     *  scale is this 2.9 on", which is what basis's "per-bucket only" is about — banks use
     *  D = total_liabilities and sit at 0.08-0.94, industrials use D = total_debt and run
     *  0.45-20.4. A Bucket row would read 'industrial' on every panel that can open today, and a
     *  value that cannot vary is a constant wearing the shape of a measurement.
     *
     *  sigma and provenance are deliberately NOT repeated: sigma IS
     *  financials.equity_volatility.value (43/43) and provenance is a copy of the three
     *  financials[*].source values, both already on screen above with unit, badge and per-field
     *  as_of. Repeating them stripped is a worse presentation of numbers already presented well.
     *
     *  oldest_as_of goes through VERBATIM — it is the min across the three inputs, computed in the
     *  vault, and nothing else in the payload carries it. Tokens are 2025 / 2025-FY / 2026-Q1 /
     *  2026-Q2; it is never parsed or reformatted into a date. It sits in .pm-co-prov, the same
     *  block wrapper .pm-co-asof already has in Financials — a bare span would rely on anonymous
     *  block-box generation and carry no margin.
     *
     *  A company with no credit figure but an entry in credit_gaps shows that entry's `reason`
     *  instead — the human-readable half; `kind` is the machine token and the two are 1:1. The two
     *  states partition the openable panels exactly (40 + 21 = 61), so this section is never empty
     *  and never absent. */
    private buildCreditHtml(node: any): string {
        const c = node.credit;
        if (c && c.distance_to_default != null) {
            const d2 = Number(c.distance_to_default).toFixed(1);
            const bucket = c.bucket ? ` <span class="pm-co-unit">${esc(String(c.bucket))}</span>` : '';
            const asOf = c.oldest_as_of
                ? `<div class="pm-co-prov"><span class="pm-co-asof">as of ${esc(String(c.oldest_as_of))}</span></div>`
                : '';
            return `
            <section class="pm-co-sec">
                <div class="pm-co-sec-h">Credit</div>
                <div class="pm-co-kv"><span class="pm-co-k">Distance to default</span><span class="pm-co-v">${esc(d2)}${bucket}</span></div>
                ${asOf}
                ${c.basis ? `<div class="pm-co-why">${esc(String(c.basis))}</div>` : ''}
            </section>`;
        }
        const gap = (this.args.offMap?.credit_gaps ?? []).find((g) => String(g.id) === String(node.id));
        if (!gap) return '';
        return `
            <section class="pm-co-sec">
                <div class="pm-co-sec-h">Credit</div>
                <div class="pm-co-why">${esc(creditGapCopy(gap.kind))}</div>
            </section>`;
    }

    /** Neighbourhood — the company's own edges. Weighted relations sort first (desc) so 19 rows stay
     *  scannable; unweighted structural rows (located_in, weight null) follow, rendered "--" — never
     *  0 or blank, which would read as a real zero-weight relation. */
    private buildNeighbourhoodHtml(nb: any): string {
        if (!Array.isArray(nb) || !nb.length) return '';
        const weighted = nb.filter((e) => e && e.weight != null).sort((a, b) => Number(b.weight) - Number(a.weight));
        const unweighted = nb.filter((e) => e && e.weight == null);
        const ordered = [...weighted, ...unweighted];
        const rows = ordered.map((e) => {
            const target = esc(String(e.target ?? '—'));
            const rel = esc(String(e.type ?? ''));
            const role = e.role ? ` · ${esc(String(e.role))}` : '';
            const w = e.weight == null ? '--' : String(e.weight);
            const unit = (e.weight != null && e.unit) ? ` <span class="pm-co-unit">${esc(String(e.unit))}</span>` : '';
            // Edge-weight provenance — the Financials vocabulary (.pm-co-src), same token verbatim,
            // uppercased by CSS. NOT gated on weight: HMN_Tech -> Subsea_Cables carries weight null
            // with source 'estimated', and dropping its badge would hide a stated provenance. A
            // weighted edge whose source is null is 'unlabelled' — a gap in the record. A structural
            // edge (located_in/owns/competitor) has neither, and gets no badge: provenance was never
            // applicable there, which is a different fact from a missing one.
            const ws = e.weight_source == null
                ? (e.weight != null ? 'unlabelled' : '')
                : String(e.weight_source);
            const wsCls = ws === 'observed' ? 'obs' : ws === 'estimated' ? 'est' : 'unk';
            const prov = ws ? ` <span class="pm-co-src pm-co-src--${wsCls}">${esc(ws)}</span>` : '';
            return `
                <div class="pm-co-nb">
                    <span class="pm-co-nb-t">${target}</span>
                    <span class="pm-co-nb-rel">${rel}${role}${prov}</span>
                    <span class="pm-co-nb-w">${w}${unit}</span>
                </div>`;
        }).join('');
        return `<section class="pm-co-sec">
            <div class="pm-co-sec-h">Neighbourhood <span class="pm-co-count">${ordered.length}</span></div>
            <div class="pm-co-nb-list">${rows}</div>
        </section>`;
    }

    // ─── UI ──────────────────────────────────────────────────────────────

    private buildPanel(): void {
        const panel = document.createElement('div');
        // Phase 6.5 — Luminous Cryo-Glass. Mirrors .pro-map-hud's recipe
        // (rgba(8,13,28,0.82) + blur(20px)/saturate(180%) + inner cyan
        // glow), but kept inline so the time-machine carries the same
        // weight as the other HUD plates without depending on injected CSS.
        panel.className = 'time-machine-panel cryo-glass';
        Object.assign(panel.style, {
            // Anchored bottom-LEFT, not centred. Dead-centre placement sat directly
            // on top of the epicenter (worst on Malacca, whose hub is mid-frame) —
            // the HUD was hiding the single most important node on the map.
            position: 'absolute', bottom: '32px', left: '24px', transform: 'none',
            width: 'min(440px, calc(100% - 48px))', padding: '12px 16px',
            borderRadius: '14px',
            display: 'flex', flexDirection: 'column', gap: '8px', zIndex: '9999',
            pointerEvents: 'auto',
            background: 'rgba(8, 13, 28, 0.85)',
            backdropFilter: 'blur(25px) saturate(190%)',
            WebkitBackdropFilter: 'blur(25px) saturate(190%)',
            border: '1px solid transparent',
            boxShadow: [
                '0 20px 50px rgba(0, 0, 0, 0.75)',
                'inset 0 0 25px rgba(0, 242, 254, 0.08)',
                'inset 0 1px 0 rgba(255, 255, 255, 0.15)',
            ].join(', '),
            color: '#e2e8f0', fontFamily: 'Inter, system-ui, sans-serif',
        });
        panel.innerHTML = `
            <div class="tm-panel-crisp tm-panel-head">
                <span style="display:inline-flex; align-items:center; gap:6px;">
                    <span class="tm-live-dot" style="width:8px;height:8px;border-radius:50%;
                          background:#22d3ee;box-shadow:0 0 8px #22d3ee;animation:tm-pulse 1.4s ease-in-out infinite;"></span>
                    <span id="tm-date-label">Awaiting history…</span>
                </span>
                <span id="tm-metrics-label">H: -- · ν: --</span>
            </div>
            <div class="tm-panel-crisp" style="display:flex; gap:10px; align-items:center;">
                <button id="tm-play-btn"
                    title="Play 24h history"
                    style="background:rgba(56,189,248,0.10); border:1px solid rgba(56,189,248,0.35);
                           color:#7dd3fc; cursor:pointer; padding:0; width:30px; height:30px;
                           border-radius:7px; display:flex; align-items:center; justify-content:center;
                           transition:transform 0.12s ease, box-shadow 0.18s ease;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                </button>
                <input type="range" id="tm-slider" min="0" max="0" value="0"
                    style="flex:1; cursor:pointer; accent-color:#38bdf8;" disabled>
                <button id="tm-forecast-btn"
                    title="Toggle +48h forecast overlay"
                    style="background:transparent; border:1px solid rgba(217, 70, 239, 0.45);
                           color:#f0abfc; cursor:pointer; padding:4px 10px; height:28px;
                           border-radius:6px; font-weight:800;
                           letter-spacing:0.10em;
                           text-transform:uppercase; transition:all 0.18s ease;">
                    +48H
                </button>
                <span id="tm-warning-chip"
                    style="font-weight:800; padding:3px 8px; border-radius:999px;
                           background:transparent; color:transparent; border:1px solid transparent;
                           text-transform:uppercase; letter-spacing:0.08em; transition:all 0.25s ease;">
                </span>
            </div>
            <style>
                @keyframes tm-pulse {
                    0%,100% { transform: scale(1);   opacity: 1;   }
                    50%     { transform: scale(1.4); opacity: 0.4; }
                }
                #tm-play-btn:hover {
                    transform: translateY(-1px);
                    box-shadow: 0 4px 14px rgba(56,189,248,0.30);
                }
            </style>
        `;
        this.args.mapEl.parentElement?.appendChild(panel);

        this.panel = panel;
        this.playBtn = panel.querySelector('#tm-play-btn') as HTMLButtonElement;
        this.slider = panel.querySelector('#tm-slider') as HTMLInputElement;
        this.dateLabel = panel.querySelector('#tm-date-label') as HTMLElement;
        this.metricsLabel = panel.querySelector('#tm-metrics-label') as HTMLElement;
        this.liveDot = panel.querySelector('.tm-live-dot') as HTMLElement;
        this.warningChip = panel.querySelector('#tm-warning-chip') as HTMLElement;
        this.forecastBtn = panel.querySelector('#tm-forecast-btn') as HTMLButtonElement;

        // Phase 6 — Forecast toggle. Active state is highlighted via the
        // dataset attribute; repaintLayers reads `this.forecastMode` directly.
        this.forecastBtn.addEventListener('click', () => {
            this.forecastMode = !this.forecastMode;
            this.applyForecastBtnState();
            this.repaintLayers();
        });
        this.applyForecastBtnState();

        // — Phase 6: Glassmorphic Event Ticker —
        // Lives directly above the time-machine panel; the centred cursor
        // line marks the current scrub position so events to the left are
        // "past" and events to the right are "future-relative-to-cursor".
        this.buildEventTicker(panel);

        // Scrub
        this.slider.addEventListener('input', () => {
            // User dragging the slider switches off "live" mode.
            const idx = parseInt(this.slider.value, 10) || 0;
            this.state.seek(idx);
            this.refreshPanel();
            this.repaintLayers();
        });
        this.slider.addEventListener('change', () => {
            const idx = parseInt(this.slider.value, 10) || 0;
            this.state.seek(idx);
            this.refreshPanel();
            this.repaintLayers();
        });

        // Playback
        this.playBtn.addEventListener('click', () => this.togglePlayback());
    }

    /**
     * Update FORECAST button visuals to reflect active/inactive state.
     * Mirrors the state into `.is-active` so CSS / future tests can read
     * the active flag declaratively (in addition to the inline magenta glow).
     */
    private applyForecastBtnState(): void {
        if (this.forecastMode) {
            this.forecastBtn.classList.add('is-active');
            this.forecastBtn.setAttribute('aria-pressed', 'true');
            this.forecastBtn.style.background = 'rgba(217, 70, 239, 0.22)';
            this.forecastBtn.style.color = '#fdf4ff';
            this.forecastBtn.style.borderColor = 'rgba(217, 70, 239, 0.85)';
            this.forecastBtn.style.boxShadow = '0 0 12px rgba(217, 70, 239, 0.45)';
            this.forecastBtn.textContent = 'FORECAST';
        } else {
            this.forecastBtn.classList.remove('is-active');
            this.forecastBtn.setAttribute('aria-pressed', 'false');
            this.forecastBtn.style.background = 'transparent';
            this.forecastBtn.style.color = '#f0abfc';
            this.forecastBtn.style.borderColor = 'rgba(217, 70, 239, 0.45)';
            this.forecastBtn.style.boxShadow = 'none';
            this.forecastBtn.textContent = '+48H';
        }
    }

    /**
     * Linearly extrapolate entropy + viscosity 48h forward from the current
     * scrub point, using the slope of the last `lookback` samples. Returns
     * { entropy, viscosity } clamped to plausible ranges. If not enough
     * history is available, falls back to the current point.
     */
    private projectForecast(): { entropy: number; viscosity: number; confidence: number } {
        const series = this.state.series;
        const cur = this.state.point();
        if (!cur) return { entropy: 0, viscosity: 0, confidence: 0 };

        const lookback = 6;
        const sample = series.slice(Math.max(0, series.length - lookback));
        if (sample.length < 2) {
            return { entropy: cur.entropy, viscosity: cur.viscosity, confidence: 0.25 };
        }

        // Slope per ms over the lookback window — same for entropy/viscosity.
        const first = sample[0];
        const last = sample[sample.length - 1];
        const dt = Math.max(1, last.epoch_ms - first.epoch_ms);
        const dEnt = (last.entropy - first.entropy) / dt;
        const dVis = (last.viscosity - first.viscosity) / dt;

        const horizonMs = 48 * 3600_000;
        const projEnt = clamp01(cur.entropy + dEnt * horizonMs);
        const projVis = Math.max(0, cur.viscosity + dVis * horizonMs);
        // Confidence shrinks with how volatile the lookback window is.
        const variance = sample.reduce(
            (acc, p) => acc + Math.abs(p.entropy - cur.entropy), 0,
        ) / sample.length;
        const confidence = clamp01(1 - variance * 1.5);
        return { entropy: projEnt, viscosity: projVis, confidence };
    }

    /**
     * Build the glassmorphic event ticker that sits ~14px above the
     * time-machine panel. Visual contract:
     *   • One row of chips, each chip = one synthesised event.
     *   • A vertical accent line marks the current scrub cursor; the chip
     *     nearest the cursor brightens (the "now" event).
     *   • Chips are positioned absolutely along a 24h timeline (0% = oldest,
     *     100% = newest) so scrubbing the slider aligns 1:1 with the strip.
     * The strip is anchored to mapEl.parentElement (same as the panel itself).
     */
    private buildEventTicker(timeMachinePanel: HTMLElement): void {
        const ticker = document.createElement('div');
        ticker.className = 'tm-event-ticker cryo-glass';
        Object.assign(ticker.style, {
            position: 'absolute',
            bottom: '136px',                       // 12px gap above time-machine panel
            left: '24px', transform: 'none',       // bottom-LEFT — see the panel above
            width: 'min(440px, calc(100% - 48px))',
            height: '44px',
            padding: '6px 14px',
            borderRadius: '12px',
            background: 'rgba(8, 13, 28, 0.85)',
            backdropFilter: 'blur(25px) saturate(190%)',
            WebkitBackdropFilter: 'blur(25px) saturate(190%)',
            border: '1px solid transparent',
            boxShadow: [
                '0 20px 50px rgba(0, 0, 0, 0.75)',
                'inset 0 0 25px rgba(0, 242, 254, 0.08)',
                'inset 0 1px 0 rgba(255, 255, 255, 0.15)',
            ].join(', '),
            color: '#e2e8f0', fontFamily: 'Inter, system-ui, sans-serif',
            display: 'flex', flexDirection: 'column', gap: '4px',
            zIndex: '9999', overflow: 'hidden',
            pointerEvents: 'auto',
        });
        ticker.innerHTML = `
            <div class="tm-ticker-crisp tm-ticker-head">
                <span>◷ Event Stream · 24h</span>
                <span id="tm-ticker-count">0 events</span>
            </div>
            <div id="tm-ticker-strip"
                 style="position:relative; flex:1; min-height:18px; overflow:hidden;">
                <div id="tm-ticker-cursor"
                     style="position:absolute; top:-4px; bottom:-4px; left:50%;
                            width:1px; background:linear-gradient(180deg,
                                rgba(248,113,113,0) 0%,
                                rgba(248,113,113,0.85) 50%,
                                rgba(248,113,113,0) 100%);
                            transform:translateX(-0.5px);
                            box-shadow:0 0 6px rgba(248,113,113,0.55);
                            pointer-events:none;"></div>
            </div>
        `;
        // Insert right above the time-machine panel (shares the same parent).
        timeMachinePanel.parentElement?.appendChild(ticker);
        this.tickerPanel = ticker;
        this.tickerStrip = ticker.querySelector('#tm-ticker-strip') as HTMLElement;
        this.tickerCursor = ticker.querySelector('#tm-ticker-cursor') as HTMLElement;
    }

    /**
     * Synthesise the 24h event list from the current spatial payload + history.
     * Cheap and deterministic — purely a function of nodes/edges/series.
     * Sources, in priority order:
     *   1. Every history point with phase_transition_warning → "PHASE TRANSITION"
     *   2. Critical nodes (impact >= 75) → "{name} · IMPACT {score}"
     *   3. Each domain's epicenter → "EPICENTER · {name}"
     * Distributed across the 24h window so the strip is never empty.
     */
    private rebuildTickerEvents(): void {
        const out: { epoch_ms: number; severity: 'crit' | 'warn' | 'info'; text: string }[] = [];
        const nowMs = Date.now();
        const windowMs = TM_HISTORY_HOURS * 3600_000;
        const startMs = nowMs - windowMs;

        // 1. Phase-transition warnings from history
        for (const p of this.state.series) {
            if (p.phase_transition_warning && p.epoch_ms >= startMs) {
                out.push({
                    epoch_ms: p.epoch_ms,
                    severity: 'crit',
                    text: 'PHASE TRANSITION · ' + (p.label || 'critical state'),
                });
            }
        }

        // 2. Critical nodes — distribute them along the window so they aren't
        // all stacked at the same x-position. Spread them deterministically.
        const criticals = this.args.nodes.filter(
            (n) => n.impact_score >= TM_TRIGGER_IMPACT_THRESHOLD && n.type !== 'epicenter',
        );
        criticals.forEach((n, i) => {
            // Distribute critical nodes evenly across the back half of the
            // window — these are "recently flagged" events.
            const t = 0.55 + (i / Math.max(1, criticals.length)) * 0.40;
            out.push({
                epoch_ms: startMs + t * windowMs,
                severity: 'warn',
                text: `${n.name} · IMPACT ${Math.round(n.impact_score)}`,
            });
        });

        // 3. Epicenters
        const epicenters = this.args.nodes.filter((n) => n.type === 'epicenter');
        epicenters.forEach((n, i) => {
            // Anchor epicenter activation near the start (oldest) so the
            // ripple narrative reads: "epicenter activated → ripples spread".
            const t = 0.15 + (i / Math.max(1, epicenters.length)) * 0.20;
            out.push({
                epoch_ms: startMs + t * windowMs,
                severity: 'crit',
                text: `EPICENTER · ${n.name}`,
            });
        });

        // Sort chronologically, cap count to avoid visual clutter.
        out.sort((a, b) => a.epoch_ms - b.epoch_ms);
        this.tickerEvents = out.slice(0, 18);
    }

    /**
     * Re-render the ticker strip from `this.tickerEvents`. Cheap — just
     * builds chip DOM. Called from refreshPanel() so the strip stays in
     * sync with the scrub cursor.
     */
    private refreshTicker(): void {
        if (!this.tickerStrip) return;
        // Cheap rebuild gate: events change only when nodes or series change;
        // both already trigger a full repaintLayers + refreshPanel chain.
        if (this.tickerEvents.length === 0) this.rebuildTickerEvents();

        const nowMs = Date.now();
        const windowMs = TM_HISTORY_HOURS * 3600_000;
        const startMs = nowMs - windowMs;

        const pt = this.state.point();
        const cursorEpoch = pt ? pt.epoch_ms : nowMs;
        const cursorT = clamp01((cursorEpoch - startMs) / windowMs);

        // Clear out old chips (keep the cursor element).
        Array.from(this.tickerStrip.children).forEach((c) => {
            if ((c as HTMLElement).id !== 'tm-ticker-cursor') c.remove();
        });

        const countEl = this.tickerPanel.querySelector('#tm-ticker-count') as HTMLElement | null;
        if (countEl) countEl.textContent = `${this.tickerEvents.length} events`;

        let nearestIdx = -1;
        let nearestDt = Infinity;
        for (let i = 0; i < this.tickerEvents.length; i++) {
            const dt = Math.abs(this.tickerEvents[i].epoch_ms - cursorEpoch);
            if (dt < nearestDt) { nearestDt = dt; nearestIdx = i; }
        }

        this.tickerEvents.forEach((ev, i) => {
            const isActive = i === nearestIdx && nearestDt < windowMs * 0.04; // ~58min
            const chip = document.createElement('div');
            chip.className = `tm-ticker-chip${isActive ? ' is-active' : ''}`;
            const palette = ev.severity === 'crit'
                ? { bg: 'rgba(220, 38, 38, 0.22)', fg: '#fecaca', border: 'rgba(248,113,113,0.55)' }
                : ev.severity === 'warn'
                ? { bg: 'rgba(245, 158, 11, 0.18)', fg: '#fde68a', border: 'rgba(251,191,36,0.55)' }
                : { bg: 'rgba(56, 189, 248, 0.16)', fg: '#bae6fd', border: 'rgba(56,189,248,0.45)' };
            Object.assign(chip.style, {
                padding: '4px 10px',
                borderRadius: '999px',
                fontSize: '12px',
                fontFamily: 'ui-monospace, Consolas, monospace',
                fontWeight: '700',
                fontVariantNumeric: 'tabular-nums',
                letterSpacing: '0.04em',
                background: palette.bg,
                color: palette.fg,
                border: `1px solid ${palette.border}`,
                whiteSpace: 'nowrap',
                opacity: isActive ? '1' : '0.72',
                boxShadow: isActive ? `0 0 10px ${palette.border}` : 'none',
                pointerEvents: 'none',
                transition: 'opacity 0.18s ease, transform 0.18s ease, box-shadow 0.18s ease',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
            });
            chip.textContent = ev.text;
            chip.title = ev.text;
            this.tickerStrip.appendChild(chip);
        });

        if (this.tickerCursor) {
            this.tickerCursor.style.left = `${(cursorT * 100).toFixed(2)}%`;
        }
    }

    // ─── Playback (Task 1 bug-fix: split into start/stop/advance, atomic sync) ──
    //
    // Behaviour contract:
    //   • Clicking ▶ while at the last frame → seek to 0 *immediately* so the
    //     user sees motion within the first ~16ms instead of waiting 800ms.
    //   • Every advance tick goes through advancePlayback() which delegates to
    //     syncToCurrent() so slider, panel, AND deck.gl layers move in lock-step.
    //   • Loop-back from end to start is handled gracefully — index wraps to
    //     0 once we step past series.length-1; no jump-mid-tick.
    //   • If polling shrinks the series (24h cutoff drops an old point), the
    //     clamp inside state.seek protects against out-of-bounds reads.

    private static readonly PLAY_SVG  = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
    private static readonly PAUSE_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>';

    private togglePlayback(): void {
        if (this.playTimer !== null) {
            this.stopPlayback();
        } else {
            this.startPlayback();
        }
    }

    private startPlayback(): void {
        const maxIdx = Math.max(0, this.state.series.length - 1);
        if (maxIdx < 1) return;
        // If we're parked at the live end, restart at 0 immediately for snappy UX.
        if (this.state.currentIndex >= maxIdx) {
            this.state.seek(0);
            this.syncToCurrent();
        }
        this.playBtn.innerHTML = SurveillanceMapController.PAUSE_SVG;
        this.playTimer = window.setInterval(this.advancePlayback, TM_PLAYBACK_STEP_MS);
    }

    private stopPlayback(): void {
        if (this.playTimer !== null) {
            window.clearInterval(this.playTimer);
            this.playTimer = null;
        }
        this.playBtn.innerHTML = SurveillanceMapController.PLAY_SVG;
    }

    /** Advance one tick. Bound as an arrow property so setInterval doesn't lose `this`. */
    private advancePlayback = (): void => {
        const len = this.state.series.length;
        const maxIdx = Math.max(0, len - 1);
        if (maxIdx < 1) {
            this.stopPlayback();
            return;
        }
        const cur = this.state.currentIndex < 0 ? 0 : this.state.currentIndex;
        let nextIdx = cur + 1;
        if (nextIdx > maxIdx) nextIdx = 0;
        this.state.seek(nextIdx);
        this.syncToCurrent();
    };

    /**
     * Single atomic update: slider value + panel text + deck.gl layer props
     * all reflect `state.currentIndex` in the same tick. The slider check
     * skips when the user is actively dragging.
     */
    private syncToCurrent(): void {
        this.refreshPanel();
        this.repaintLayers();
    }

    // ─── Polling ─────────────────────────────────────────────────────────

    private async pollHistoryOnce(): Promise<void> {
        if (document.hidden) return; // tab-visibility back-off
        try {
            const wireDomain = toSpatialDomainId(this.args.domainId);
            const resp = await apiClient.get(
                `/pro/domains/${encodeURIComponent(wireDomain)}/fragility-history?days=1`,
                { cache: 'no-store' },
                true,
            );
            // Phase 6.5.9 — a failed poll must NEVER wipe a valid live render.
            // We only *append* history points via state.ingest(); nodes/edges
            // (the live map vectors) are owned by the controller's args and are
            // left untouched here. So the worst a failed/empty poll can do is
            // leave the slider parked — which is exactly the graceful behaviour
            // we want. Mark the attempt done so the panel can drop the cold
            // "Awaiting history…" copy regardless of outcome.
            this.historyPolled = true;
            if (!resp.ok) {
                this.refreshPanel();
                return;
            }
            const body: any = await resp.json();
            if (this.aborted) return;   // fetch may have landed after stop()
            const incoming = Array.isArray(body?.series) ? body.series : [];
            const { newPoints } = this.state.ingest(incoming);
            // New history points can flip phase_transition_warning flags
            // → ticker events need to be re-synthesised.
            if (newPoints > 0) this.rebuildTickerEvents();
            this.refreshPanel();
            // If live, repaint with new latest; if scrubbed, leave the user's
            // current frame alone — only the slider bounds update.
            if (newPoints > 0 && this.state.isLive()) this.repaintLayers();
        } catch (err) {
            // Polling failures are non-fatal — try again on the next tick.
            // Crucially, we do NOT touch the live render on failure.
            this.historyPolled = true;
            console.warn(`${LOG} time-machine poll failed`, err);
            this.refreshPanel();
        }
    }

    // ─── Animation ───────────────────────────────────────────────────────

    private frame = (now: number): void => {
        if (this.aborted) return;
        const dt = Math.max(0, now - this.lastFrameAt) / 1000;
        // Phase advances at a constant velocity (one full lap every 4s).
        this.animationPhase = (this.animationPhase + dt * 0.25) % 1;
        const targetInterval = 1000 / TM_ANIMATION_FPS;
        if (now - this.lastFrameAt >= targetInterval) {
            this.lastFrameAt = now;
            this.repaintLayers();
        }
        this.rafId = requestAnimationFrame(this.frame);
    };

    /**
     * Single source of truth for what the overlay shows.
     *
     * Phase 2 — N-th Order Impact Graph:
     *   Arcs and particles are SPLIT by `target_order` (1 / 2 / 3). Each
     *   tier gets its own width multiplier, opacity, and particle velocity
     *   so the visual encodes energy dissipation across hops.
     *
     * Visual scaling table (TM_ORDER_STYLE):
     *   order 1 → thick, bright, fast    (highest entropy / shortest hop)
     *   order 2 → standard               (direct affected — backbone)
     *   order 3 → thin, dim, slow        (2-hop downstream ripple)
     */
    /**
     * Swap in re-fanned geometry (co-location ring resized for a new zoom).
     *
     * The per-frame rebuild in repaintLayers() CLONES the base layers, and a
     * clone inherits its parent's `data` reference — so mutating the arrays in
     * place would never reach the GPU (deck.gl only re-uploads attributes when
     * the data REFERENCE changes). Hence we rebuild the base layers with the new
     * arrays; the next repaint picks them up automatically.
     */
    public updateGeometry(nodes: SpatialNode[], edgesFlat: ResolvedEdge[]): void {
        if (this.aborted) return;   // INVARIANT (see stop())
        this.args.nodes = nodes;
        this.args.edgesFlat = edgesFlat;
        this.args.epicenterLayer = this.args.epicenterLayer.clone({
            data: nodes.filter((n) => n.type === 'epicenter'),
        });
        this.args.affectedLayer = this.args.affectedLayer.clone({
            data: nodes.filter((n) => n.type === 'affected'),
        });
        if (this.args.exposedLayer) {
            this.args.exposedLayer = this.args.exposedLayer.clone({
                data: nodes.filter((n) => n.type === 'exposed_unquantified'),
            });
        }
        this.args.arcLayer = this.args.arcLayer.clone({
            data: edgesFlat.filter((e) => !e.unquantified),
        });
        if (this.args.unquantifiedArcLayer) {
            this.args.unquantifiedArcLayer = this.args.unquantifiedArcLayer.clone({
                data: edgesFlat.filter((e) => e.unquantified),
            });
        }
        this.repaintLayers();
    }

    /** (role, detail) → cached IconLayer icon descriptor. Generated once per glyph. */
    private reticleIconCache = new Map<string, any>();

    private reticleIcon(kind: ReticleKind, detail: ReticleDetail): any {
        const key = `${kind}:${detail}`;
        let icon = this.reticleIconCache.get(key);
        if (!icon) {
            icon = {
                url: makeReticleIcon(kind, detail),
                width: RETICLE_PX,
                height: RETICLE_PX,
                anchorX: RETICLE_PX / 2,
                anchorY: RETICLE_PX / 2,
                mask: false,   // the glyph carries its own colour; do NOT tint by getColor
            };
            this.reticleIconCache.set(key, icon);
        }
        return icon;
    }

    /**
     * Static-cascade node vocabulary: reticles instead of glowing dots, so Stage 2 speaks
     * the same language as Stage 1. Split by cascade ROLE only (type) — no entity taxonomy
     * exists in the data, so none is invented. Radius mirrors the dot formulas (size still
     * encodes impact_score); ticks degrade out on small nodes as a legibility choice.
     */
    private pushStaticNodeReticles(builtLayers: any[], sid: string, triggerPulse: number): void {
        const IconLayer = this.args.IconLayer;
        const nodes = this.args.nodes;

        // Exposed · magnitude unknown — dashed slate hollow ring, fixed size, drawn behind
        // the measured nodes. Must never read as a measured ring.
        const exposed = nodes.filter((n) => n.type === 'exposed_unquantified');
        if (exposed.length) {
            builtLayers.push(new IconLayer({
                id: `sc-reticle-exposed-${sid}`,
                data: exposed,
                pickable: true,
                billboard: true,   // face the camera + hold constant px size when the map is pitched
                // Pick the whole icon quad, not just opaque pixels. IconLayer's default
                // alphaCutoff (0.05) discards the transparent interior AND the dash gaps from
                // picking, so the sparse dashed exposed ring was almost unclickable.
                alphaCutoff: 0,
                sizeUnits: 'pixels',   // constant screen size across zoom (was metres → ballooned when zoomed in)
                sizeMinPixels: 16,
                sizeMaxPixels: 22,
                getPosition: (d: any) => [d.lon, d.lat],
                getIcon: () => this.reticleIcon('exp', 'dashed'),
                getSize: () => 18,     // fixed — impact is meaningless for exposed; large enough to stay visibly dashed
            }));
        }

        // Measured — epicenter (red double ring + ticks) + affected (green; ticks degrade by
        // impact). One layer, role/impact picked per node.
        const measured = nodes.filter((n) => n.type === 'epicenter' || n.type === 'affected');
        if (measured.length) {
            const affDetail = (impact: number): ReticleDetail =>
                impact >= 75 ? 'full' : impact >= 40 ? 'ticks' : 'ring';
            builtLayers.push(new IconLayer({
                id: `sc-reticle-measured-${sid}`,
                data: measured,
                pickable: true,
                billboard: true,   // face the camera + hold constant px size when the map is pitched
                alphaCutoff: 0,   // full-quad picking (see exposed layer) — click the ring's interior too
                sizeUnits: 'pixels',   // CONSTANT screen size across zoom (was 'meters' → reticles ballooned when zoomed in)
                sizeMinPixels: 6,
                sizeMaxPixels: 40,
                getPosition: (d: any) => [d.lon, d.lat],
                getIcon: (d: any) =>
                    d.type === 'epicenter'
                        ? this.reticleIcon('epi', 'full')
                        : this.reticleIcon('aff', affDetail(d.impact_score ?? 0)),
                // impact_score → screen pixels: 10px @ impact 0 → 26px @ impact 100 (epicenter +2).
                // The epicenter pulse still multiplies the size; the high-impact affected pulse is
                // unchanged. nodeScale (viscosity-derived, 0 for scenarios) is dropped — it was for
                // the metre-based dynamic and has no role in a constant pixel size.
                getSize: (d: any) => {
                    const px = 10 + clamp01((d.impact_score ?? (d.type === 'epicenter' ? 100 : 0)) / 100) * 16;
                    if (d.type === 'epicenter') return (px + 2) * triggerPulse;
                    return (d.impact_score ?? 0) >= TM_TRIGGER_IMPACT_THRESHOLD ? px * triggerPulse : px;
                },
                updateTriggers: { getSize: this.animationPhase },
            }));
        }
    }

    /**
     * Command-room tracer treatment (static cascade only). Three layers per repaint:
     *   1. a persistent dark TRACK for every quantified edge — width = the measured weight,
     *      no pulse, always visible so the structure reads when nothing is travelling;
     *   2. a bright COMET running the track source→target — a short bright-headed segment
     *      fading behind, at UNIFORM speed (speed encodes nothing; width already carries the
     *      weight, and a speed difference would assert a quantity we never measured);
     *   3. an arrival BLOOM ring that expands + fades when the comet reaches its target.
     * Per-edge phase offset staggers them so they don't fire in lockstep. Unquantified edges are
     * excluded entirely — they keep their dashed track and get no tracer, because nothing should
     * appear to flow along an edge whose magnitude was never measured.
     */
    private pushStaticTracers(builtLayers: any[], sid: string): void {
        const ScatterCtor = this.args.ScatterplotLayer;
        const edges = this.args.edgesFlat.filter((e) => !e.unquantified);
        if (!edges.length || !ScatterCtor) return;

        // 1) Track — a single thin, pale-blue line, normal alpha blend. No halo: the neon
        //    core+halo glow washed the map out at convergence. Width carries the measured edge
        //    weight; the pale blue encodes nothing and stays clear of the green/red/slate nodes.
        const arcHeight = (d: ResolvedEdge) => 0.40 + Math.abs(d.lane_offset ?? 0) * 0.22;
        builtLayers.push(this.args.arcLayer.clone({
            id: `sc-track-${sid}`,
            data: edges,
            getWidth: (d: ResolvedEdge) => Math.max(d.intensity * 1.6, 0.8),
            getSourceColor: [0, 210, 255, 190],
            getTargetColor: [0, 210, 255, 190],
            getHeight: arcHeight,
            ...arcLayerBlendProps(false),
        }));

        // 2) comet (bright head + fading tail) + 3) arrival bloom — keyed to a uniform head phase.
        const TAIL = 7;
        const TAIL_SPAN = 0.16;   // fraction of the arc the comet covers
        const BLOOM_W = 0.14;     // arrival window as a fraction of the loop
        const comet: Array<{ lon: number; lat: number; head: number; alpha: number; size: number }> = [];
        const blooms: Array<{ lon: number; lat: number; radius: number; alpha: number }> = [];

        for (let i = 0; i < edges.length; i++) {
            const e = edges[i];
            const offset = this.offsets[i % this.offsets.length] ?? 0;
            const head = (this.animationPhase + offset) % 1;   // uniform speed; offset = the stagger
            for (let k = 0; k < TAIL; k++) {
                const t = head - (k / (TAIL - 1)) * TAIL_SPAN;
                if (t < 0) continue;                            // tail not yet clear of the source
                const [lon, lat] = greatCircleAt(e.source_lon, e.source_lat, e.target_lon, e.target_lat, t);
                const f = 1 - k / TAIL;                         // 1 at the head → ~0 at the tail
                comet.push({ lon, lat, head: k === 0 ? 1 : 0, alpha: Math.round(235 * f * f), size: 1_200 + 2_800 * f });
            }
            if (head >= 1 - BLOOM_W) {
                const p = (head - (1 - BLOOM_W)) / BLOOM_W;     // 0 at arrival → 1 fully expanded
                blooms.push({ lon: e.target_lon, lat: e.target_lat, radius: 16_000 + 30_000 * p, alpha: Math.round(200 * (1 - p)) });
            }
        }

        builtLayers.push(new ScatterCtor({
            id: `sc-tracer-${sid}`,
            data: comet,
            pickable: false, stroked: false, filled: true,
            // Sits ON the thin track; a comet fatter than its own track reads wrong.
            radiusUnits: 'meters', radiusMinPixels: 0.8, radiusMaxPixels: 2.5,
            getPosition: (d: any) => [d.lon, d.lat],
            getRadius: (d: any) => d.size,
            getFillColor: (d: any) => (d.head ? [190, 250, 255, 255] : [0, 210, 255, d.alpha]),
            parameters: { depthTest: false },
            updateTriggers: { getPosition: this.animationPhase, getFillColor: this.animationPhase, getRadius: this.animationPhase },
        }));

        if (blooms.length) {
            builtLayers.push(new ScatterCtor({
                id: `sc-bloom-${sid}`,
                data: blooms,
                pickable: false, stroked: true, filled: false,
                radiusUnits: 'meters', lineWidthMinPixels: 1.5, lineWidthMaxPixels: 3,
                getPosition: (d: any) => [d.lon, d.lat],
                getRadius: (d: any) => d.radius,
                getLineColor: (d: any) => [0, 255, 90, d.alpha],   // phosphor green — blooms from the (green) target node
                getLineWidth: 2.5,
                parameters: { depthTest: false },
                updateTriggers: { getRadius: this.animationPhase, getLineColor: this.animationPhase },
            }));
        }
    }

    private repaintLayers(): void {
        if (this.aborted) return;   // INVARIANT (see stop())
        const pt = this.state.point();
        const entropy = pt ? pt.entropy : 0;
        const viscosity = pt ? pt.viscosity : 0;
        const warning = pt ? pt.phase_transition_warning : false;

        const sid = safeId(this.args.domainId);
        const isAggregate = this.args.domainId === GLOBAL_DOMAIN_ID;

        // Global pulse on the same phase keeps the visual coherent across orders.
        const arcPulse = 0.7 + 0.5 * Math.sin(this.animationPhase * Math.PI * 2);
        const triggerPulse = 0.85 + 0.40 * Math.sin(this.animationPhase * Math.PI * 2);
        const arcScale = 0.8 + clamp01(entropy) * 0.6;
        const nodeScale = 0.8 + Math.min(viscosity, 1) * 0.4;

        // Group edges by their target node's order so each tier produces a
        // dedicated ArcLayer + particle layer. Empty tiers create no layers
        // (Dev Mode philosophy — no empty placeholder layers).
        // Unquantified edges are EXCLUDED from the per-order tiers: they own a
        // dedicated grey layer. Leaving them in would re-draw them in red/cyan
        // (and give them flow particles), implying a direction and magnitude the
        // payload explicitly says is unknown.
        const edgesByOrder = new Map<ContagionOrder, ResolvedEdge[]>();
        for (const e of this.args.edgesFlat) {
            if (e.unquantified) continue;
            const o = (e.target_order ?? 2) as ContagionOrder;
            const bucket = edgesByOrder.get(o);
            if (bucket) bucket.push(e);
            else        edgesByOrder.set(o, [e]);
        }

        // Build the layer list in z-order (back → front): arcs first, then
        // particles, then nodes — so node halos always sit on top.
        const builtLayers: any[] = [];

        // Static cascade → command-room tracer treatment (persistent dark track + a bright comet
        // running source→target + an arrival bloom) instead of the per-order pulsing arcs and
        // crawling particles. Empty tier list ⇒ the loop below is a no-op in static mode; the
        // non-static path (the Pro Brief) is byte-identical.
        const useReticles = this.args.staticScenario === true && !!this.args.IconLayer;
        if (useReticles) this.pushStaticTracers(builtLayers, sid);

        const orderedTiers: ContagionOrder[] = useReticles ? [] : [3, 2, 1];   // back to front
        for (const order of orderedTiers) {
            const tierEdges = edgesByOrder.get(order);
            if (!tierEdges || tierEdges.length === 0) continue;
            const style = TM_ORDER_STYLE[order];

            // — Arcs ─────────────────────────────────────────────────
            const pushArcLayer = (layerEdges: ResolvedEdge[], layerKey: string): void => {
                const arcLayerForTier = this.args.arcLayer.clone({
                    id: `sc-arcs-${sid}-o${order}-${layerKey}`,
                    data: layerEdges,
                    getWidth: (d: ResolvedEdge) =>
                        Math.max(d.intensity * 5 * arcScale * arcPulse * style.widthScale, 1.0),
                    getSourceColor: (d: ResolvedEdge) =>
                        isAggregate
                            ? arcDomainRgba(
                                d.domain_id,
                                style.arcAlphaBase + 60 * arcPulse * arcScale,
                                'source',
                                true,
                            )
                            : [239, 68, 68, Math.round(style.arcAlphaBase + 60 * arcPulse * arcScale)],
                    getTargetColor: (d: ResolvedEdge) =>
                        isAggregate
                            ? arcDomainRgba(
                                d.domain_id,
                                style.arcAlphaBase * 0.75 + 40 * arcPulse * arcScale,
                                'target',
                                true,
                            )
                            : [34, 211, 238, Math.round(style.arcAlphaBase * 0.75 + 40 * arcPulse * arcScale)],
                    getHeight: (d: ResolvedEdge) =>
                        0.40 + Math.abs(d.lane_offset ?? 0) * 0.22,
                    ...arcLayerBlendProps(isAggregate),
                    updateTriggers: {
                        getWidth: this.animationPhase,
                        getSourceColor: this.animationPhase,
                        getTargetColor: this.animationPhase,
                        getHeight: this.animationPhase,
                    },
                });
                builtLayers.push(arcLayerForTier);
            };

            if (isAggregate) {
                const byDomain = new Map<string, ResolvedEdge[]>();
                for (const e of tierEdges) {
                    const dom = e.domain_id ?? 'unknown';
                    const bucket = byDomain.get(dom);
                    if (bucket) bucket.push(e);
                    else byDomain.set(dom, [e]);
                }
                for (const [dom, domEdges] of byDomain) {
                    pushArcLayer(domEdges, safeId(dom));
                }
            } else {
                pushArcLayer(tierEdges, 'all');
            }

            // — Particles ────────────────────────────────────────────
            // Per-tier phase: outer orders run slower to communicate dissipation.
            const tierPhase = (this.animationPhase * style.velocityScale) % 1;
            const tierParticles: Array<{ lon: number; lat: number; intensity: number; size: number; alpha: number }> = [];
            for (let i = 0; i < tierEdges.length; i++) {
                const e = tierEdges[i];
                const base = this.offsets[i % this.offsets.length] ?? 0;
                for (let p = 0; p < style.particles; p++) {
                    const t = (tierPhase + base + p / style.particles) % 1;
                    const [lon, lat] = greatCircleAt(
                        e.source_lon, e.source_lat,
                        e.target_lon, e.target_lat,
                        t,
                    );
                    const headDist = Math.min(1 - p / style.particles, 1);
                    tierParticles.push({
                        lon, lat,
                        intensity: e.intensity,
                        size: (4_500 + e.intensity * 5_500 * headDist) * style.widthScale,
                        alpha: style.particleAlpha,
                    });
                }
            }
            const particleLayerForTier = new this.args.ScatterplotLayer({
                id: `sc-particles-${sid}-o${order}`,
                data: tierParticles,
                pickable: false,
                stroked: false,
                filled: true,
                radiusUnits: 'meters',
                radiusMinPixels: 1.2,
                radiusMaxPixels: 6 * style.widthScale,
                getPosition: (d: any) => [d.lon, d.lat],
                getRadius: (d: any) => d.size,
                getFillColor: (d: any) => [
                    255,
                    Math.round(220 - 60 * d.intensity),
                    64,
                    d.alpha,
                ],
                updateTriggers: { getPosition: this.animationPhase },
            });
            builtLayers.push(particleLayerForTier);
        }

        // — Unquantified: static grey. Deliberately NOT pulsed and NOT scaled —
        //   any animation keyed to impact_score/intensity (both 0 here) would
        //   fabricate a magnitude we do not have. Pushed first so it sits behind
        //   the quantified layers. Omitting these would let setProps() wipe the
        //   exposed nodes/arcs off the map on the first animation frame.
        // The exposed reticle replaces the grey hollow ring, so skip that push when reticling
        // (useReticles is defined above, at the tracer/tier branch).
        if (this.args.unquantifiedArcLayer) builtLayers.push(this.args.unquantifiedArcLayer);
        if (this.args.exposedLayer && !useReticles) builtLayers.push(this.args.exposedLayer);

        if (useReticles) {
            this.pushStaticNodeReticles(builtLayers, sid, triggerPulse);
        } else {
            // — Affected nodes: pulse only when impact_score crosses the trigger
            //   threshold (the >1.5x intensity surrogate).
            const animatedAffected = this.args.affectedLayer.clone({
                getRadius: (d: any) => {
                    const base = Math.max(12_000 + d.impact_score * 800, 16_000) * nodeScale;
                    return d.impact_score >= TM_TRIGGER_IMPACT_THRESHOLD
                        ? base * triggerPulse
                        : base;
                },
                updateTriggers: { getRadius: this.animationPhase },
            });
            builtLayers.push(animatedAffected);

            // — Epicenter: always-on heavy pulse (it IS the trigger by definition)
            const animatedEpicenter = this.args.epicenterLayer.clone({
                getRadius: (d: any) =>
                    Math.max(25_000 + d.impact_score * 1_200, 35_000) * nodeScale * triggerPulse,
                getLineColor: warning
                    ? [255, 80, 80, Math.round(200 + 55 * arcPulse)]
                    : [255, 100, 100, 240],
                updateTriggers: { getRadius: this.animationPhase, getLineColor: warning ? this.animationPhase : 0 },
            });
            builtLayers.push(animatedEpicenter);
        }

        // — Phase 6.5: Three concentric ripple rings for critical nodes —
        // Each ring expands outward, fades, then resets — three offset
        // phases create a staggered "sonar" effect rather than a single
        // pulsating dot. Uses the same ScatterplotLayer ctor so no extra
        // module import is needed.
        //
        // Dropped in static-cascade (reticle) mode: the expanding cyan rings sit on top of
        // every impact>=75 node and drown the reticle glyphs, so epicenter/affected/exposed
        // stop being distinguishable. The reticle IS the vocabulary now, and radius already
        // encodes impact continuously — the >=75 sonar was the old dot design's flourish.
        const ScatterplotCtor = this.args.ScatterplotLayer;
        if (ScatterplotCtor && !useReticles) {
            const criticalForRings = this.args.nodes.filter(
                (n) => n.type === 'epicenter' || n.impact_score >= TM_TRIGGER_IMPACT_THRESHOLD,
            );
            if (criticalForRings.length > 0) {
                const baseRadius = (d: any) =>
                    Math.max(22_000 + d.impact_score * 900, 28_000) * nodeScale;
                // Three async phases — 0, 0.33, 0.66 along the 0..1 loop.
                for (let i = 0; i < 3; i++) {
                    const ringT = (this.animationPhase + i / 3) % 1;     // 0..1 expansion
                    // Radius grows linearly from base→6.0x over the cycle.
                    const radiusScale = 1 + ringT * 5.0;
                    // Alpha fades out as the ring expands (full at t=0, 0 at t=1).
                    const ringAlpha = Math.round(Math.max(0, 200 * (1 - ringT)));
                    const ringColor = warning
                        ? [220, 38, 38, ringAlpha]           // deep crimson — phase transition
                        : [0, 242, 254, ringAlpha];          // neon-cyan sonar — standard critical
                    builtLayers.push(new ScatterplotCtor({
                        id: `sc-ripple-ring-${sid}-${i}`,
                        data: criticalForRings,
                        pickable: false,
                        stroked: true,
                        filled: false,
                        getPosition: (d: any) => [d.lon, d.lat],
                        getRadius: (d: any) => baseRadius(d) * radiusScale,
                        getLineColor: ringColor,
                        getLineWidth: 3,
                        lineWidthMinPixels: 2,
                        lineWidthMaxPixels: 4,
                        radiusUnits: 'meters',
                        parameters: { depthTest: false },
                        updateTriggers: {
                            getRadius: this.animationPhase,
                            getLineColor: this.animationPhase,
                        },
                    }));
                }
            }
        }

        // — Phase 6: Critical entity labels —
        // Persistently render the name of every node that crossed the 1.5x
        // trigger threshold (impact_score >= 75) directly on the map. Uses
        // Deck.gl TextLayer; falls back silently if TextLayer isn't loaded.
        const TextLayerCtor = this.args.TextLayer;
        if (TextLayerCtor) {
            const criticalNodes = this.args.nodes.filter(
                (n) => n.type === 'epicenter' || n.impact_score >= TM_TRIGGER_IMPACT_THRESHOLD,
            );
            if (criticalNodes.length > 0) {
                const labelPulse = 200 + Math.round(55 * Math.sin(this.animationPhase * Math.PI * 2));
                const labelLayer = new TextLayerCtor({
                    id: `sc-critical-labels-${sid}`,
                    data: criticalNodes,
                    pickable: false,
                    getPosition: (d: any) => [d.lon, d.lat],
                    getText: (d: any) => {
                        const raw = String(d.name ?? '');
                        return raw.length > 28 ? raw.slice(0, 26) + '…' : raw;
                    },
                    getSize: 14,
                    sizeUnits: 'pixels',
                    sizeMinPixels: 11,
                    sizeMaxPixels: 18,
                    getColor: (d: any) =>
                        d.type === 'epicenter'
                            ? [255, 180, 180, labelPulse]
                            : [253, 230, 138, 230],
                    getPixelOffset: (d: any) =>
                        d.type === 'epicenter' ? [0, -42] : [0, -28],
                    getTextAnchor: 'middle',
                    getAlignmentBaseline: 'bottom',
                    fontFamily: '"Inter", "Segoe UI", system-ui, sans-serif',
                    fontWeight: 800,
                    outlineColor: [2, 6, 23, 235],
                    outlineWidth: 3,
                    fontSettings: { sdf: true },
                    background: true,
                    backgroundPadding: [6, 3, 6, 3],
                    getBackgroundColor: (d: any) =>
                        d.type === 'epicenter'
                            ? [60, 0, 0, 200]
                            : [40, 24, 0, 200],
                    getBorderColor: (d: any) =>
                        d.type === 'epicenter' ? [248, 113, 113, 255] : [251, 191, 36, 255],
                    getBorderWidth: 1.2,
                    updateTriggers: { getColor: this.animationPhase },
                });
                builtLayers.push(labelLayer);
            }
        }

        // — Phase 6: Forecast Mode overlay (+48h predicted ripples) —
        // Ghosted amber→magenta gradient arcs reusing the same topology.
        // Width/alpha scale with PREDICTED entropy/viscosity so the user
        // can see whether the system is trending toward calmer or hotter.
        if (this.forecastMode && this.args.edgesFlat.length > 0 && this.args.ArcLayerCtor) {
            const ArcLayerCtor = this.args.ArcLayerCtor;
            const ScatterplotLayerCtor = this.args.ScatterplotLayer;
            const proj = this.projectForecast();
            const projEntropy = proj.entropy;
            const projViscosity = proj.viscosity;
            const projConfidence = proj.confidence;
            // Slow second-order pulse so the forecast layer "shimmers"
            // distinctly from the live arcs (different frequency, π/2 offset).
            const ghostPulse = 0.55 + 0.30 * Math.sin(this.animationPhase * Math.PI * 2 + Math.PI / 2);
            const forecastWidth = (0.8 + projEntropy * 1.2) * (0.8 + projConfidence * 0.4);
            // Forecast arcs are rendered per-order so the hierarchy is
            // preserved, but with a minimum alpha floor so even order-3
            // dotted lines stay visible against the dark basemap.
            for (const [order, bucket] of edgesByOrder) {
                const tier = TM_ORDER_STYLE[order];
                // Visible alpha floor: never let the ghost arc drop below
                // ~110 alpha or it disappears into the basemap.
                const alpha = Math.max(110, Math.round(220 * ghostPulse * (tier.arcAlphaBase / 200)));
                const ghostArcs = new ArcLayerCtor({
                    id: `sc-forecast-arcs-${sid}-o${order}`,
                    data: bucket,
                    getSourcePosition: (e: any) => [e.source_lon, e.source_lat],
                    getTargetPosition: (e: any) => [e.target_lon, e.target_lat],
                    // amber-magenta gradient: from amber (251,191,36) at src
                    // to fuchsia (217,70,239) at tgt — the "future" colour.
                    getSourceColor: () => [251, 191, 36, alpha],
                    getTargetColor: () => [217, 70, 239, alpha],
                    getWidth: 2.5 + forecastWidth * tier.widthScale * 2.5,
                    widthMinPixels: 1.5,
                    widthMaxPixels: 7,
                    greatCircle: true,
                    parameters: { depthTest: false },
                    updateTriggers: {
                        getSourceColor: this.animationPhase,
                        getTargetColor: this.animationPhase,
                    },
                });
                builtLayers.push(ghostArcs);
            }
            // Predicted viscosity inflates node radii — visually broadcasts
            // "where the energy will accumulate by t+48h".
            const projNodeScale = 0.9 + Math.min(projViscosity, 1) * 0.8;
            const forecastNodes = new ScatterplotLayerCtor({
                id: `sc-forecast-nodes-${sid}`,
                data: this.args.nodes.filter((n) => n.impact_score >= TM_TRIGGER_IMPACT_THRESHOLD),
                pickable: false,
                stroked: true,
                filled: false,
                getPosition: (d: any) => [d.lon, d.lat],
                getRadius: (d: any) =>
                    Math.max(20_000 + d.impact_score * 800, 28_000) * projNodeScale,
                getLineColor: [217, 70, 239, Math.max(170, Math.round(220 * ghostPulse))],
                getLineWidth: 2,
                lineWidthMinPixels: 1.5,
                lineWidthMaxPixels: 4,
                updateTriggers: {
                    getRadius: this.animationPhase,
                    getLineColor: this.animationPhase,
                },
            });
            builtLayers.push(forecastNodes);
        }

        // CRITICAL: setProps preserves the WebGL context — no flicker.
        this.args.overlay.setProps({ layers: builtLayers });

        // CRITICAL: In interleaved mode, MapLibre GL owns the WebGL render loop
        // and only redraws when its own state changes (pan / zoom / style).
        // Once the map is idle, deck.gl layers are frozen unless we explicitly
        // ask MapLibre to schedule a new frame. Without this call the concentric
        // ripple rings animate a few times (while the map settles) then freeze.
        this.args.mapRef?.triggerRepaint();
    }


    // ─── Panel sync ──────────────────────────────────────────────────────

    private refreshPanel(): void {
        if (this.aborted) return;   // INVARIANT (see stop())
        const series = this.state.series;
        const pt = this.state.point();

        // A scenario cascade is STATIC — it has exactly one snapshot, because it is
        // a structural graph, not a rolling observation. Rather than leave a dead
        // scrubber that looks broken, say so plainly. We do NOT fake a trajectory:
        // there is no time dimension here to scrub, and inventing one would be a lie.
        if (this.args.staticScenario) {
            this.slider.disabled = true;
            this.playBtn.disabled = true;
            this.forecastBtn.disabled = true;
            this.playBtn.style.opacity = '0.35';
            this.forecastBtn.style.opacity = '0.35';
            this.forecastBtn.style.cursor = 'not-allowed';
            this.playBtn.style.cursor = 'not-allowed';
            const dot = this.args.wrapEl.querySelector<HTMLElement>('.tm-live-dot');
            if (dot) {
                // Not "live" — kill the pulsing cyan dot that implies a feed.
                dot.style.animation = 'none';
                dot.style.background = '#94a3b8';
                dot.style.boxShadow = 'none';
            }
            this.dateLabel.textContent = 'STATIC SCENARIO · no time series';
            this.metricsLabel.textContent = 'structural cascade';
            // MUST still refresh the ticker + top HUD. An early return here skipped
            // refreshStatsHud() below, which is why the HUD kept showing the previous
            // (domain-aggregate) stats while the map correctly drew the scenario.
            this.refreshTicker();
            this.refreshStatsHud(null);
            return;
        }

        const pollingDisabled = this.args.enableHistoryPolling === false;
        const maxIdx = Math.max(0, series.length - 1);
        const hasHistory = maxIdx > 0;
        this.slider.max = String(maxIdx);
        this.slider.min = '0';
        this.slider.disabled = pollingDisabled || !hasHistory;
        if (!this.slider.disabled) {
            this.slider.removeAttribute('disabled');
        }
        const sliderIdx = this.state.currentIndex < 0
            ? maxIdx
            : Math.min(Math.max(0, this.state.currentIndex), maxIdx);
        if (document.activeElement !== this.slider) {
            this.slider.value = String(sliderIdx);
        }
        // Date label
        if (pollingDisabled) {
            this.dateLabel.textContent = 'Live aggregate · per-domain scrub';
            this.metricsLabel.textContent = pt
                ? `H: ${pt.entropy.toFixed(3)} · ν: ${pt.viscosity.toFixed(3)}`
                : 'H: -- · ν: --';
        } else if (!hasHistory) {
            // Phase 6.5.9 — graceful degradation. Once at least one poll has
            // returned without populating a scrubbable timeline, stop showing
            // the cold "Awaiting history…" spinner-copy and tell the user the
            // map is simply live-only. The live render itself is left intact.
            this.dateLabel.textContent = this.historyPolled
                ? 'LIVE ONLY · NO HISTORY'
                : 'Awaiting history…';
            this.metricsLabel.textContent = pt
                ? `H: ${pt.entropy.toFixed(3)} · ν: ${pt.viscosity.toFixed(3)}`
                : 'H: -- · ν: --';
        } else if (pt) {
            try {
                this.dateLabel.textContent = new Date(pt.epoch_ms).toLocaleString(undefined, {
                    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                });
            } catch {
                this.dateLabel.textContent = pt.timestamp;
            }
            this.metricsLabel.textContent =
                `H: ${pt.entropy.toFixed(3)} · ν: ${pt.viscosity.toFixed(3)}`;
        }
        // Live indicator
        const isLive = this.state.isLive();
        this.liveDot.style.background = isLive ? '#22d3ee' : '#fbbf24';
        this.liveDot.style.boxShadow = isLive ? '0 0 8px #22d3ee' : '0 0 8px #fbbf24';
        this.liveDot.style.animationPlayState = isLive ? 'running' : 'paused';

        // Warning chip
        if (pt?.phase_transition_warning) {
            this.warningChip.textContent = '⚡ ' + (pt.label || 'WARNING');
            this.warningChip.style.background = 'rgba(220,38,38,0.18)';
            this.warningChip.style.color = '#fca5a5';
            this.warningChip.style.borderColor = 'rgba(220,38,38,0.55)';
        } else {
            this.warningChip.textContent = '';
            this.warningChip.style.background = 'transparent';
            this.warningChip.style.color = 'transparent';
            this.warningChip.style.borderColor = 'transparent';
        }

        // Phase 6 — keep the event ticker in lock-step with the scrub cursor.
        this.refreshTicker();
        this.refreshStatsHud(pt);
    }

    /** Phase 7.10 — top metric strip tracks live nodes + timeline frame. */
    private refreshStatsHud(pt: HistoryPoint | null): void {
        if (this.aborted) return;   // INVARIANT (see stop())
        const host =
            this.args.container.closest('.pro-map-global-container') ??
            this.args.container.parentElement;
        const hud = host?.querySelector<HTMLElement>('[data-role="stats-hud"]')
            ?? host?.querySelector<HTMLElement>('.pro-map-hud--top');
        if (!hud) return;
        const livePt = pt ?? (this.state.series.length > 0 ? this.state.point() : null);
        // The 4th arg was omitted, so fallbackEdgeIntensity silently defaulted to 0 —
        // EDGE N rendered "0.000" for every payload, always. Compute the real mean,
        // over MEASURED edges only (an unquantified edge must not dilute the divisor),
        // and pass null when there is nothing to average so the HUD prints "--", not 0.
        const measured = this.args.edgesFlat.filter(
            (e) => !e.unquantified && typeof e.intensity === 'number',
        );
        const meanIntensity = measured.length
            ? measured.reduce((s, e) => s + e.intensity, 0) / measured.length
            : null;
        hud.innerHTML = renderStatsHudBody(
            buildStatsHudPayload(
                this.args.nodes,
                livePt,
                this.args.epicenterScore,
                meanIntensity,
            ),
        );
    }
}

