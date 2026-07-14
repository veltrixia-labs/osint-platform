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

/**
 * Display name for a scenario.
 *
 * Prefers a CJK alias when the payload carries one (ホルムズ海峡), else the derived
 * label. Deliberately states only the HUB — never a premise. The payload asserts a
 * chokepoint, a type and aliases; it does NOT assert that the strait is closed, so
 * the UI must not say "封鎖"/"closure". Naming an event we have no evidence for is
 * the same class of quiet falsehood as rendering an unmeasured impact as zero.
 */
function scenarioDisplayName(s: ScenarioMeta): string {
    const cjk = (s.aliases ?? []).find((a) => /[　-鿿＀-￯]/.test(a));
    return cjk || s.label || (s.hub ?? s.id).replace(/_/g, ' ');
}

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

/**
 * Phase 6.5 — Ambient global graticules.
 *
 * Adds two MapLibre layers on top of the dark-matter basemap:
 *   • `vt-graticule-major` — 30° lat/lon lines at opacity 0.06
 *   • `vt-graticule-minor` — 10° lat/lon lines at opacity 0.04 (dotted)
 *
 * Both are pure GeoJSON LineStrings — no external tileset required.
 * Idempotent: re-running won't duplicate sources/layers.
 */
function _injectAmbientGraticules(map: any): void {
    if (!map || typeof map.getSource !== 'function') return;
    if (!map.isStyleLoaded?.()) return;

    const buildLines = (stepDeg: number): GeoJSON.FeatureCollection => {
        const features: GeoJSON.Feature[] = [];
        // Latitude lines (parallels): east-west, sample longitudes every 5°
        for (let lat = -80; lat <= 80; lat += stepDeg) {
            const coords: [number, number][] = [];
            for (let lon = -180; lon <= 180; lon += 5) coords.push([lon, lat]);
            features.push({
                type: 'Feature', properties: { kind: 'lat' },
                geometry: { type: 'LineString', coordinates: coords },
            });
        }
        // Longitude lines (meridians): north-south
        for (let lon = -180; lon < 180; lon += stepDeg) {
            const coords: [number, number][] = [];
            for (let lat = -85; lat <= 85; lat += 5) coords.push([lon, lat]);
            features.push({
                type: 'Feature', properties: { kind: 'lon' },
                geometry: { type: 'LineString', coordinates: coords },
            });
        }
        return { type: 'FeatureCollection', features };
    };

    const addGraticuleLayer = (
        layerId: string,
        sourceId: string,
        data: GeoJSON.FeatureCollection,
        paint: Record<string, unknown>,
    ): void => {
        if (map.getLayer(layerId)) return;
        if (!map.getSource(sourceId)) {
            map.addSource(sourceId, { type: 'geojson', data });
        }
        map.addLayer({
            id: layerId,
            type: 'line',
            source: sourceId,
            paint,
        });
        // Keep both grid layers at the absolute top of the style stack so
        // dark land/ocean fills never occlude the matrix scan lines.
        map.moveLayer(layerId);
    };

    // Minor grid — every 10°, faint dotted scan lines.
    addGraticuleLayer(
        'vt-graticule-minor',
        'vt-graticule-minor-src',
        buildLines(10),
        {
            'line-color': 'rgba(0, 242, 254, 1)',
            'line-opacity': 0.08,
            'line-width': 0.6,
            'line-dasharray': [1, 3],
        },
    );

    // Major grid — every 30°, slightly heavier solid baseline.
    addGraticuleLayer(
        'vt-graticule-major',
        'vt-graticule-major-src',
        buildLines(30),
        {
            'line-color': 'rgba(125, 211, 252, 1)',
            'line-opacity': 0.12,
            'line-width': 0.8,
        },
    );
}

/**
 * Phase 7.2 — Normalise a payload from the live Spatial Engine into the
 * frontend's SpatialContagion shape.
 *
 *  • Backend nodes carry an explicit `type` ('epicenter' | 'affected')
 *    AND a numeric impact_score; we trust those.
 *  • Backend edges name endpoints by lat/lon. The renderer also needs
 *    `source_id` / `target_id` so the per-order ArcLayer split can join
 *    edges back to nodes — synthesise those from the coords.
 *  • `target_order` is mirrored from `order_level`.
 */
function _normalizeSpatialPayload(raw: any): SpatialContagion {
    const nodes: SpatialNode[] = Array.isArray(raw?.nodes)
        ? raw.nodes.map((n: any): SpatialNode => ({
            id: String(n.id ?? `${n.lat}_${n.lon}`),
            name: String(n.name ?? 'Unknown'),
            lat: Number(n.lat),
            lon: Number(n.lon),
            country: n.country,
            // `?? 0` is kept — downstream radius/colour math needs a number. But it
            // DESTROYS the null, so capture the distinction first: unknown ≠ zero.
            unquantified: n.impact_score == null,
            impact_score: Number(n.impact_score ?? 0),
            type: (
                n.type === 'epicenter' ? 'epicenter'
                : n.type === 'exposed_unquantified' ? 'exposed_unquantified'
                : 'affected'
            ),
            why: n.why,
            order: (n.order as ContagionOrder | undefined),
            confidence: n.confidence,
        }))
        : [];
    // Coord-keyed lookup so edges (which name endpoints by lat/lon) can
    // re-bind to a stable node id.
    const byCoord = new Map<string, string>();
    for (const n of nodes) byCoord.set(`${n.lat.toFixed(4)}|${n.lon.toFixed(4)}`, n.id);

    const edges: SpatialEdge[] = Array.isArray(raw?.edges)
        ? raw.edges.map((e: any): SpatialEdge | null => {
            const srcKey = `${Number(e.source_lat).toFixed(4)}|${Number(e.source_lon).toFixed(4)}`;
            const tgtKey = `${Number(e.target_lat).toFixed(4)}|${Number(e.target_lon).toFixed(4)}`;
            const source_id = byCoord.get(srcKey);
            const target_id = byCoord.get(tgtKey);
            if (!source_id || !target_id) return null;
            const order = Number(e.target_order ?? e.order_level ?? 2) as ContagionOrder;
            return {
                source_id,
                target_id,
                // Same rule as nodes: keep the numeric coercion, but remember it was null.
                unquantified: (e.intensity ?? e.edge_intensity) == null,
                intensity: Number(e.intensity ?? e.edge_intensity ?? 0),
                target_order: order,
            };
        }).filter((e: SpatialEdge | null): e is SpatialEdge => e !== null)
        : [];

    // Mirror node.order from the edge target_order if missing — the
    // criticality filter and order-style table both consult node.order.
    const orderByNodeId = new Map<string, ContagionOrder>();
    for (const e of edges) orderByNodeId.set(e.target_id, (e.target_order ?? 2) as ContagionOrder);
    for (const n of nodes) {
        if (n.type === 'epicenter') n.order = 1;
        else if (n.order === undefined) n.order = orderByNodeId.get(n.id) ?? 2;
    }

    return {
        nodes,
        edges,
        epicenter_impact_score: Number(raw?.epicenter_impact_score ?? 0),
        edge_intensity: Number(raw?.edge_intensity ?? 0),
        node_count: nodes.length,
        edge_count: edges.length,
        schema_version: String(raw?.schema_version ?? 'spatial_engine_v1'),
        order_counts: raw?.order_counts,
    };
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

export type SpatialContagion = {
    nodes: SpatialNode[];
    edges: SpatialEdge[];
    epicenter_impact_score: number;
    edge_intensity: number;
    node_count?: number;
    edge_count?: number;
    schema_version?: string;
    warning?: string;
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

async function fetchGlobalSpatialContagion(): Promise<SpatialContagion | null> {
    const candidatePaths = [
        '/spatial/global',
        '/pro/spatial/global',
        '/pro/domains/global/spatial-contagion',
    ];

    for (const path of candidatePaths) {
        try {
            const resp = await apiClient.get(path, { cache: 'no-store' }, true);
            if (!resp.ok) continue;
            const body = await resp.json();
            const sc = body?.spatial_contagion ?? body;
            if (Array.isArray(sc?.nodes) && sc.nodes.length > 0) {
                return sc as SpatialContagion;
            }
        } catch (err) {
            console.warn(`${LOG} global endpoint failed (${path})`, err);
        }
    }

    return null;
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
        : 'Sovereign geo-engine resolves entity coordinates from signal intelligence and plots contagion propagation arcs. Arc width reflects entropy-derived edge intensity; node radius scales with impact score. Hover nodes for details.';

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
 * Phase 5 — Immersive HUD Refactor
 *
 * Reshapes the dashboard's spatial pane into a Palantir/Pentagon-style
 * monitor: the WebGL map fills the entire route viewport as the absolute
 * background (z:0), while all controls float above it as glassmorphic HUD
 * widgets (z:10).
 *
 * Strict invariants:
 *   • DashboardSpatialController internals are NOT touched — this is pure
 *     DOM/CSS refactor + an external MutationObserver for stats sync.
 *   • Phase 4's <50ms WebGL layer-swap path is preserved as-is.
 *   • No placeholders / "Coming Soon" / mosaic — empty payload → empty
 *     overlay, but the basemap and HUDs remain visible.
 */
export function renderGlobalSurveillanceMap(container: HTMLElement): void {
    injectImmersiveStyles();
    const fallback = getGlobalFallbackSpatialContagion();

    // Tag the container so styles target the immersive layout (full viewport,
    // padding removed). Preserve the .pro-map-global-container class so the
    // existing controller can find the sidebar via stageEl.closest(...).
    container.classList.add('pro-map-global-container', 'pro-map-immersive-host');
    container.innerHTML = `
        <!-- z:0 — Fullscreen WebGL stage. MapLibre canvas + Deck.gl overlay
             live INSIDE here. Bootstrap queries #sc-map-* / #sc-wrap-* here. -->
        <div class="pro-map-immersive-stage">
            ${renderImmersiveSpatialShell(fallback, GLOBAL_DOMAIN_ID)}
        </div>

        <!-- z:10 — Top HUD: epicenter / impact / nodes / edge intensity -->
        <div class="pro-map-hud pro-map-hud--top pro-map-hud-crisp" data-role="stats-hud"
             aria-label="Spatial contagion summary">
            ${renderStatsHudBody(fallback)}
        </div>

        <!-- z:10 — Left HUD: domain selector. Controller._buildSidebar()
             writes its content; we just provide the host element + class. -->
        <aside class="pro-map-sidebar pro-map-hud pro-map-hud--left"
               aria-label="Active surveillance domain"></aside>
    `;

    const stage = container.querySelector<HTMLElement>('.pro-map-immersive-stage');
    if (!stage) {
        console.error(`${LOG} renderGlobalSurveillanceMap: stage element missing`);
        return;
    }

    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            void bootstrapSpatialMap(stage, fallback, GLOBAL_DOMAIN_ID).then(() => {
                wireStatsHudObserver(container);
            }).catch((err) => {
                console.error(`${LOG} renderGlobalSurveillanceMap: bootstrap failed`, err);
            });
        });
    });
}


// ─── Immersive helpers (Phase 5) ─────────────────────────────────────────────

/**
 * Lean spatial shell for the immersive view — no `.intel-panel` wrapper,
 * no static section header, no in-panel stats bar. Just the map wrap + the
 * loading overlay, so the canvas can fill the entire stage.
 */
function renderImmersiveSpatialShell(sc: SpatialContagion, domainId: string): string {
    const sid = safeId(domainId);
    const nodes = sc?.nodes ?? [];
    const hasData = nodes.length > 0 && !String(sc?.warning ?? '').includes('no_resolved');
    const loading = hasData
        ? `<div class="sc-map-overlay sc-map-overlay--loading" id="sc-loading-${sid}">
               <div class="sc-loading-pulse"></div>
               <span class="sc-loading-text">Initializing spatial intelligence layer...</span>
           </div>`
        : '';
    return `
        <div class="sc-map-wrap sc-map-wrap--immersive" id="sc-wrap-${sid}">
            <div id="sc-map-${sid}" class="sc-map-canvas sc-map-canvas--immersive"></div>
            ${loading}
        </div>
    `;
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

/**
 * Watches the controller-managed sidebar for `aria-pressed=true` changes
 * (i.e. domain switches). On each change, re-fetches the cached spatial
 * contagion for that domain via the same endpoint the controller uses,
 * then rewrites the top HUD body. NEVER touches the controller itself —
 * uses public DOM signals only.
 */
function wireStatsHudObserver(container: HTMLElement): void {
    const sidebar = container.querySelector<HTMLElement>('.pro-map-sidebar');
    const hud = container.querySelector<HTMLElement>('.pro-map-hud--top');
    if (!sidebar || !hud) return;

    // Track the last domain we rendered to avoid duplicate re-fetches when
    // the controller toggles aria-pressed off→on→off during transitions.
    let lastRendered: string | null = null;

    /** True while a scenario row is selected. */
    const scenarioActive = (): boolean =>
        !!sidebar.querySelector('button[data-scenario][aria-checked="true"]');

    const handleDomainChange = async (domainId: string): Promise<void> => {
        // This observer only understands DOMAINS. In scenario mode the controller owns
        // the HUD, and this writer must not clobber it — its async fetch would otherwise
        // land after the scenario render and repaint the HUD with domain-aggregate stats
        // (which is exactly what showed "Middle East Energy Corridor" over a Hormuz map).
        if (scenarioActive()) return;
        if (domainId === lastRendered) return;
        lastRendered = domainId;
        try {
            if (domainId === GLOBAL_DOMAIN_ID) {
                // Global aggregate — show a synthetic "ALL DOMAINS" summary
                // sourced from the still-cached fallback (Phase 4 fall-back).
                hud.innerHTML = renderStatsHudBody(getGlobalFallbackSpatialContagion());
                return;
            }
            const resp = await apiClient.get(
                `/pro/domains/${encodeURIComponent(domainId)}/fragility-history?days=7`,
                { cache: 'no-store' },
                true,
            );
            if (!resp.ok) return;
            const body: any = await resp.json();
            // Re-check AFTER the await: the user may have selected a scenario while this
            // fetch was in flight. Writing now would silently overwrite the scenario HUD.
            if (scenarioActive()) return;
            const sc = body?.latest_spatial_contagion;
            if (sc && Array.isArray(sc.nodes) && sc.nodes.length > 0) {
                hud.innerHTML = renderStatsHudBody(sc as SpatialContagion);
            } else {
                hud.innerHTML = renderStatsHudBody(null);
            }
        } catch (err) {
            console.warn(`${LOG} stats-HUD refresh failed for ${domainId}`, err);
        }
    };

    const observer = new MutationObserver((mutations) => {
        for (const m of mutations) {
            if (m.attributeName !== 'aria-pressed') continue;
            const target = m.target as HTMLElement;
            if (target.getAttribute('aria-pressed') !== 'true') continue;
            const id = target.getAttribute('data-domain');
            if (id) void handleDomainChange(id);
        }
    });
    observer.observe(sidebar, {
        subtree: true,
        attributes: true,
        attributeFilter: ['aria-pressed'],
    });

    // When the container leaves the DOM, disconnect — leak-free.
    const cleanup = new MutationObserver(() => {
        if (!document.body.contains(container)) {
            observer.disconnect();
            cleanup.disconnect();
        }
    });
    cleanup.observe(document.body, { childList: true, subtree: true });
}


/** Inject Phase-5 immersive layout + HUD widget + entity-badge styles. Idempotent. */
function injectImmersiveStyles(): void {
    if (typeof document === 'undefined' || document.getElementById('pro-map-immersive-styles')) return;
    const style = document.createElement('style');
    style.id = 'pro-map-immersive-styles';
    style.textContent = `
        /* === Immersive container — fullscreen background ============== */
        .pro-map-immersive-host {
            position: relative;
            width: 100%;
            /* Fill the viewport minus the dashboard chrome.
               Falls back to a generous 720px when the CSS variable is unset. */
            height: calc(100vh - var(--dashboard-chrome-height, 96px));
            min-height: 720px;
            padding: 0 !important;
            margin: 0;
            overflow: hidden;
            background: #050a14;
            border-radius: 14px;
            isolation: isolate;
        }
        .pro-map-immersive-stage {
            position: absolute;
            inset: 0;
            /* No z-index → does not form its own stacking context.
               Lets the time-machine (rendered as a descendant) participate
               in the host's stacking order alongside the HUD widgets. */
        }
        .sc-map-wrap--immersive {
            position: absolute;
            inset: 0;
            z-index: 1;
            pointer-events: auto;
        }
        .sc-map-canvas--immersive {
            position: absolute !important;
            inset: 0;
            width: 100% !important;
            height: 100% !important;
            min-height: 0 !important;
            z-index: 1;
            pointer-events: auto;
        }
        .pro-map-immersive-host .sc-map-overlay--loading {
            position: absolute;
            inset: 0;
            z-index: 5;
            display: flex;
            align-items: center;
            justify-content: center;
            background: radial-gradient(circle at center, rgba(2,6,23,0.55), rgba(2,6,23,0.85));
            backdrop-filter: blur(2px);
            pointer-events: none;
        }

        /* === Glassmorphic HUD widgets (z:10) ========================== */
        /* === Phase 6.5 — Luminous Cryo-Glass ============================
           Deep slate base + heavy saturate + interior cyan glow so the
           plate reads as a single-piece of lit glass over the basemap.
           Gradient border is painted via a ::before pseudo-element with
           padding-mask so the rim shifts white→cyan around the perimeter
           rather than being a flat solid colour. */
        /* Cryo-glass — beats #pro-map-container .pro-map-sidebar flat fill in style.css */
        .pro-map-immersive-host .pro-map-hud,
        .pro-map-immersive-host .pro-map-sidebar.pro-map-hud,
        .pro-map-hud,
        .time-machine-panel.cryo-glass,
        .tm-event-ticker.cryo-glass {
            position: absolute;
            z-index: 9999 !important;
            pointer-events: auto !important;
            background: rgba(8, 13, 28, 0.85) !important;
            backdrop-filter: blur(25px) saturate(190%) !important;
            -webkit-backdrop-filter: blur(25px) saturate(190%) !important;
            border: 1px solid transparent !important;
            border-radius: 14px;
            box-shadow:
                0 20px 50px rgba(0, 0, 0, 0.75),
                inset 0 0 25px rgba(0, 242, 254, 0.08),
                inset 0 1px 0 rgba(255, 255, 255, 0.15) !important;
            color: #e2e8f0;
            font-family: 'Inter', system-ui, sans-serif;
        }
        .pro-map-immersive-host .pro-map-hud *,
        .time-machine-panel.cryo-glass *,
        .tm-event-ticker.cryo-glass *,
        .time-machine-panel.cryo-glass button,
        .time-machine-panel.cryo-glass input[type="range"],
        .tm-event-ticker.cryo-glass button,
        .tm-event-ticker.cryo-glass input[type="range"] {
            pointer-events: auto !important;
        }
        .pro-map-immersive-host .pro-map-sidebar.pro-map-hud {
            width: 280px !important;
            padding: 18px 18px 16px !important;
            border-radius: 14px !important;
        }
        .pro-map-hud::before,
        .cryo-glass::before {
            content: "";
            position: absolute;
            inset: 0;
            border-radius: inherit;
            padding: 1px;
            background: linear-gradient(135deg,
                rgba(255, 255, 255, 0.28) 0%,
                rgba(125, 211, 252, 0.12) 35%,
                rgba(0, 242, 254, 0.32) 70%,
                rgba(255, 255, 255, 0.10) 100%);
            -webkit-mask:
                linear-gradient(#000 0 0) content-box,
                linear-gradient(#000 0 0);
            -webkit-mask-composite: xor;
                    mask-composite: exclude;
            pointer-events: none;
            z-index: 0;
        }
        .cryo-glass { position: relative; }
        .cryo-glass > * { position: relative; z-index: 1; }

        /* Phase 7.12 — crisp text over backdrop-filter (no parent blur bleed) */
        .pro-map-hud-crisp,
        .time-machine-panel.cryo-glass .tm-panel-crisp,
        .time-machine-panel.cryo-glass .tm-panel-crisp *,
        .tm-event-ticker.cryo-glass .tm-ticker-crisp,
        .tm-event-ticker.cryo-glass .tm-ticker-crisp *,
        .tm-event-ticker.cryo-glass .tm-ticker-chip,
        .sc-entity-badge,
        .sc-entity-badge * {
            position: relative;
            z-index: 1;
            transform: translateZ(0);
            will-change: transform;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            text-shadow: none;
        }
        .time-machine-panel.cryo-glass .tm-panel-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
            color: #94a3b8;
            font-family: ui-monospace, Consolas, 'SF Mono', Menlo, monospace;
            text-transform: uppercase;
            letter-spacing: 0.10em;
            font-variant-numeric: tabular-nums;
        }
        #tm-metrics-label {
            color: #7dd3fc;
            font-size: 14px;
            font-variant-numeric: tabular-nums;
            font-family: ui-monospace, Consolas, 'SF Mono', Menlo, monospace;
            letter-spacing: 0.02em;
        }
        .tm-event-ticker.cryo-glass .tm-ticker-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
            color: #7dd3fc;
            font-family: ui-monospace, Consolas, 'SF Mono', Menlo, monospace;
            text-transform: uppercase;
            letter-spacing: 0.10em;
            font-variant-numeric: tabular-nums;
        }
        #tm-ticker-count {
            color: #94a3b8;
            font-size: 12px;
        }
        #tm-forecast-btn {
            font-size: 12px !important;
            font-family: ui-monospace, Consolas, 'SF Mono', Menlo, monospace !important;
        }
        #tm-warning-chip {
            font-size: 12px !important;
        }

        /* Phase 7.13 — Event Stream track: flex row prevents chip collision */
        .tm-event-ticker.cryo-glass {
            margin-bottom: 12px !important;
        }
        #tm-ticker-strip {
            display: flex !important;
            flex-direction: row !important;
            gap: 12px !important;
            align-items: center !important;
            overflow-x: auto !important;
            overflow-y: hidden !important;
            white-space: nowrap !important;
            position: relative !important;
            flex: 1;
            min-height: 22px;
            padding: 2px 0;
            scrollbar-width: thin;
            scrollbar-color: rgba(125, 211, 252, 0.35) transparent;
        }
        #tm-ticker-strip .tm-ticker-chip {
            position: relative !important;
            left: auto !important;
            top: auto !important;
            flex-shrink: 0 !important;
            transform: none !important;
            max-width: 200px;
        }
        #tm-ticker-strip .tm-ticker-chip.is-active {
            transform: scale(1.06) !important;
            opacity: 1 !important;
        }
        #tm-ticker-cursor {
            display: none;
        }

        /* Top HUD — centred stats strip */
        .pro-map-hud--top {
            top: 18px;
            left: 50%;
            transform: translateX(-50%);
            padding: 10px 16px;
            display: flex;
            align-items: stretch;
            gap: 22px;
            max-width: calc(100% - 360px);
        }
        .sc-hud-stat {
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            gap: 2px;
            min-width: 0;
        }
        .sc-hud-stat:not(:last-child) {
            padding-right: 22px;
            border-right: 1px solid rgba(148, 163, 184, 0.18);
        }
        .sc-hud-stat-label {
            font-size: 12px;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.11em;
            font-weight: 700;
            font-family: ui-monospace, Consolas, 'SF Mono', Menlo, monospace;
            font-variant-numeric: tabular-nums;
        }
        /* Phase 6.5 — razor-sharp metric values across the entire HUD.
           Monospace stack is the SF-tier ladder, never serif/proportional. */
        .sc-hud-stat-val {
            font-size: 14px;
            font-weight: 700;
            color: #e2e8f0;
            font-variant-numeric: tabular-nums;
            font-family: ui-monospace, Consolas, 'SF Mono', Menlo, monospace;
            letter-spacing: 0.01em;
            text-shadow: 0 0 6px rgba(0, 242, 254, 0.35);
            max-width: 220px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .sc-hud-stat-val--critical {
            color: #fca5a5;
            text-shadow: 0 0 10px rgba(248, 113, 113, 0.55);
        }
        /* Apply the global tabular-nums rule to every numeric label/value
           inside the Top HUD so live metric jitter never reflows. */
        .pro-map-hud--top, .pro-map-hud--top * {
            font-variant-numeric: tabular-nums;
        }

        /* Left HUD — sidebar (filled by controller) */
        .pro-map-hud--left {
            top: 92px;
            left: 18px;
            width: 280px;
            max-height: calc(100% - 180px);
            padding: 18px 18px 16px;
            overflow-y: auto;
            scrollbar-width: thin;
            scrollbar-color: rgba(125, 211, 252, 0.35) transparent;
        }
        .pro-map-hud--left::-webkit-scrollbar { width: 6px; }
        .pro-map-hud--left::-webkit-scrollbar-thumb {
            background: rgba(125, 211, 252, 0.30);
            border-radius: 4px;
        }
        .pro-map-hud--left h2 {
            color: #7dd3fc !important;
        }

        /* === Entity Badge Tooltip (Phase 5 — Palantir-style glow) ====== */
        .sc-entity-badge {
            position: relative;
            background: linear-gradient(160deg, rgba(8, 13, 24, 0.95), rgba(15, 23, 42, 0.92));
            border: 1px solid var(--badge-accent, #22d3ee);
            border-left: 4px solid var(--badge-accent, #22d3ee);
            border-radius: 10px;
            padding: 14px 18px 15px;
            font-family: 'Inter', system-ui, sans-serif;
            color: #e2e8f0;
            min-width: 260px;
            max-width: 360px;
            box-shadow:
                0 12px 36px rgba(2, 6, 23, 0.70),
                0 0 24px color-mix(in srgb, var(--badge-accent, #22d3ee) 32%, transparent),
                inset 0 0 0 1px rgba(255, 255, 255, 0.04);
            backdrop-filter: blur(16px) saturate(160%);
            -webkit-backdrop-filter: blur(16px) saturate(160%);
        }
        .sc-badge-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 8px;
        }
        .sc-badge-tier {
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 0.12em;
            color: var(--badge-accent, #22d3ee);
            background: color-mix(in srgb, var(--badge-accent, #22d3ee) 14%, transparent);
            border: 1px solid color-mix(in srgb, var(--badge-accent, #22d3ee) 45%, transparent);
            padding: 3px 8px;
            border-radius: 999px;
            text-transform: uppercase;
        }
        .sc-badge-conf {
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.10em;
            color: #94a3b8;
            text-transform: uppercase;
        }
        .sc-badge-name {
            font-size: 16px;
            font-weight: 800;
            color: #f1f5f9;
            line-height: 1.25;
            margin-bottom: 4px;
        }
        .sc-badge-meta {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            color: #94a3b8;
            margin-bottom: 10px;
            letter-spacing: 0.04em;
        }
        .sc-badge-meta-cls {
            font-weight: 700;
            color: color-mix(in srgb, var(--badge-accent, #22d3ee) 70%, #cbd5e1);
            text-transform: uppercase;
            letter-spacing: 0.10em;
        }
        .sc-badge-meta-sep { color: #475569; }
        .sc-badge-metrics {
            display: grid;
            grid-template-columns: 1fr 1.4fr;
            gap: 8px 12px;
            padding-top: 8px;
            border-top: 1px solid rgba(148, 163, 184, 0.15);
        }
        .sc-badge-metric {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .sc-badge-metric .k {
            font-size: 11px;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.10em;
            font-weight: 700;
        }
        .sc-badge-metric .v {
            font-size: 14px;
            color: #e2e8f0;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            font-family: ui-monospace, Consolas, 'SF Mono', Menlo, monospace;
        }
        /* Rationale line for structurally-exposed-but-unquantified nodes.
           This is the ONLY thing that explains why the marker is a hollow grey
           ring rather than a scored dot — without it the ring is meaningless. */
        .sc-badge-why {
            margin-top: 10px;
            padding-top: 8px;
            border-top: 1px solid rgba(148, 163, 184, 0.25);
            font-size: 11px;
            line-height: 1.45;
            color: #94a3b8;
            font-style: italic;
            max-width: 260px;
        }

        /* === Responsive collapsing (compact tablets) =================== */
        @media (max-width: 720px) {
            .pro-map-hud--top {
                left: 16px;
                right: 16px;
                transform: none;
                gap: 12px;
                padding: 8px 12px;
                max-width: none;
            }
            .sc-hud-stat:not(:last-child) {
                padding-right: 12px;
            }
            .pro-map-hud--left {
                top: auto;
                bottom: 110px;       /* sit above the time-machine panel */
                left: 12px;
                right: 12px;
                width: auto;
                max-height: 220px;
            }
        }
    `;
    document.head.appendChild(style);
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
            console.warn(`${LOG} no global payload supplied — trying global API endpoints before fallback`);
            payload = await fetchGlobalSpatialContagion() ?? getGlobalFallbackSpatialContagion();
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
                map.fitBounds(bounds, { padding: 70, maxZoom: 7, duration: 900 });
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
                nodes: displayNodes,
                edgesFlat,
                domainId: normalizedDomainId,
                epicenterScore,
                // A static cascade has no time axis — don't poll, and say so on the panel.
                enableHistoryPolling: opts?.staticScenario !== true,
                staticScenario: opts?.staticScenario === true,
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

        const orderedTiers: ContagionOrder[] = [3, 2, 1];   // back to front
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
        if (this.args.unquantifiedArcLayer) builtLayers.push(this.args.unquantifiedArcLayer);
        if (this.args.exposedLayer) builtLayers.push(this.args.exposedLayer);

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

        // — Phase 6.5: Three concentric ripple rings for critical nodes —
        // Each ring expands outward, fades, then resets — three offset
        // phases create a staggered "sonar" effect rather than a single
        // pulsating dot. Uses the same ScatterplotLayer ctor so no extra
        // module import is needed.
        const ScatterplotCtor = this.args.ScatterplotLayer;
        if (ScatterplotCtor) {
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


// ─────────────────────────────────────────────────────────────────────────
//   Phase 4 — Dynamic Domain Routing
// ─────────────────────────────────────────────────────────────────────────

/** Lazy-resolved deck.gl + maplibre module bundle. Cached for the controller's lifetime. */
type DeckModuleBundle = {
    MapCtor: any;
    AttributionControl: any;
    LngLatBounds: any;
    ScatterplotLayer: any;
    ArcLayer: any;
    TextLayer: any;
    MapboxOverlay: any;
};


/**
 * Dashboard-wide spatial controller. Owns the MapLibre `map` + the
 * `MapboxOverlay` for the **entire dashboard session** — they are never
 * destroyed. Only the deck.gl Layer objects + the per-domain
 * `SurveillanceMapController` are swapped when the user changes domain.
 *
 * This is the WebGL-stable design — context, basemap, and overlay survive
 * every switch. Only ~25 KB of JS objects (3 layers + 1 controller) are
 * recreated on swap, which Deck.gl diffs internally → no shader recompile.
 */
class DashboardSpatialController {
    private map: any = null;
    private overlay: any = null;
    private deckModules: DeckModuleBundle | null = null;
    private stageEl: HTMLElement;
    private mapEl: HTMLElement;
    private wrapEl: HTMLElement;
    private sidebarListEl: HTMLElement | null = null;

    /** Per-domain spatial_contagion cache. Populated lazily on first switch + at bootstrap. */
    private domainCache: Map<string, SpatialContagion> = new Map();

    /** Currently-mounted per-domain surveillance instance. */
    private surveillance: SurveillanceMapController | null = null;

    /**
     * Phase 6 — Omni-Domain monitor. The map ALWAYS renders the aggregate
     * over `activeDomains`. The sidebar's six rows are multi-select layer
     * filters (default: all six on); the Global row at the top is a
     * shortcut to "select all".
     *
     * activeDomains is intentionally seeded with all specialized domains
     * so the default view is the full cross-domain network.
     */
    /** Scenario catalogue (GET /pro/domains/scenarios). Empty until fetched. */
    private scenarios: ScenarioMeta[] = [];
    /** Currently-selected scenario, or null when in normal (multi-domain) mode.
     *  Scenario selection is EXCLUSIVE — it bypasses the domain aggregate entirely. */
    private scenarioId: string | null = null;
    private activeDomains: Set<string> = new Set(SPECIALIZED_DOMAIN_IDS);

    /** Guard against re-entrant rebuilds (rapid toggle clicks). */
    private rebuildInFlight: Promise<void> | null = null;
    private pendingRebuild = false;
    private lastInteractionDomainId: string = GLOBAL_DOMAIN_ID;

    /**
     * Phase 6.5.9 — true once a render sourced from real backend data
     * (live `/global/spatial-contagion` or a populated per-domain cache) has
     * been mounted. Used to veto a regression back to the static demo seed:
     * once the user has seen the real cross-domain network, a transient empty
     * prefetch must never wipe it back to the hardcoded "Middle East" demo.
     */
    private lastRenderWasLive = false;

    /** Set when stop() has been called. Subsequent calls become no-ops. */
    private destroyed = false;

    constructor(args: { stageEl: HTMLElement; mapEl: HTMLElement; wrapEl: HTMLElement }) {
        this.stageEl = args.stageEl;
        this.mapEl = args.mapEl;
        this.wrapEl = args.wrapEl;
    }

    /**
     * One-shot init. Creates the MapLibre map + the MapboxOverlay, mounts
     * the initial domain (with the payload the caller already has), and
     * starts pre-fetching the remaining specialized domains in the
     * background so Global aggregation is instantaneous later.
     */
    async bootstrap(initialPayload: SpatialContagion, _initialDomainHint: string): Promise<void> {
        // Phase 6 — initialDomain is treated as a hint only. The view ALWAYS
        // boots into Omni-Domain mode with every specialized domain active.
        await this._loadDeckModules();
        await this._createBaseMap(initialPayload);

        // Seed cache so first paint has *something*; real per-domain payloads
        // are pulled in by _prefetchSpecializedDomains() right after.
        this.domainCache.set(GLOBAL_DOMAIN_ID, initialPayload);

        await this._attachDomain(initialPayload, GLOBAL_DOMAIN_ID, /*animatePan=*/ false);
        // Catalogue BEFORE the sidebar: _buildSidebar() renders the Scenarios
        // section from this.scenarios, so an empty list would omit it entirely.
        // Never throws — an unavailable catalogue just means no scenario section.
        await this._loadScenarioCatalogue();
        this._buildSidebar();
        this._refreshDomainRowStates();

        // First successful render → flip the global SYNC indicator to STABLE.
        // The legacy renderGlobalSurveillanceMap() path used to do this; the
        // bootstrap path was silently inheriting "INITIALIZING" forever.
        this._signalSyncStable();

        // Phase 7.2 — cache live global payload for aggregate fallback only.
        // Do NOT re-attach here: the flat global graph lacks per-domain lane
        // separation and would mask multi-domain arcs (Panama Canal).
        void this._fetchGlobalContagion().then((live) => {
            if (this.destroyed || !live) return;
            this.domainCache.set(GLOBAL_DOMAIN_ID, live);
        });

        // Phase 7.13 — after per-domain prefetch, silently swap to the rich
        // lane-separated aggregate so Global view is correct on first load.
        void this._prefetchSpecializedDomains().then(() => {
            if (this.destroyed) return;
            void this._tryHydrateRichAggregate(/*animatePan=*/ false);
        });
    }

    /**
     * Phase 7.13 — Omni Global monitor uses per-domain cache for arcs.
     * Rebuild once specialized payloads exist so lane offsets apply without
     * requiring a manual filter toggle.
     */
    private _hasPopulatedSpecializedCache(): boolean {
        return SPECIALIZED_DOMAIN_IDS.some((d) => {
            const payload = this.domainCache.get(d);
            return Array.isArray(payload?.nodes) && payload.nodes.length > 0;
        });
    }

    private async _tryHydrateRichAggregate(animatePan: boolean): Promise<void> {
        if (this.destroyed || !this._hasPopulatedSpecializedCache()) return;
        const omniActive = SPECIALIZED_DOMAIN_IDS.some((d) => this.activeDomains.has(d));
        if (!omniActive) return;
        await this._rebuildAggregate(animatePan);
    }

    /**
     * Broadcast that the surveillance layer is live. Two paths:
     *  • dispatch an `api-sync-status` CustomEvent for any subscriber that
     *    listens centrally (Phase 5 stats HUD).
     *  • directly mutate `.sync-label` / `.sync-dot` so the visible chrome
     *    flips even if no event listener exists yet.
     * Idempotent — safe to call repeatedly.
     */
    private _signalSyncStable(): void {
        try {
            window.dispatchEvent(new CustomEvent('api-sync-status', {
                detail: { status: 'stable', timestamp: new Date() },
            }));
        } catch { /* CustomEvent missing in legacy environments — non-fatal */ }
        document.querySelectorAll<HTMLElement>('.sync-label').forEach((label) => {
            if (label.innerText.includes('INITIALIZING')) {
                label.innerText = 'SYNC: STABLE';
                label.style.color = '#22d3ee';
            }
        });
        document.querySelectorAll<HTMLElement>('.sync-dot').forEach((el) => {
            el.classList.remove('sync-dot--init', 'sync-dot--retrying', 'sync-dot--offline');
            el.classList.add('sync-dot--stable');
        });
    }

    /**
     * Phase 6 — Toggle a single specialized domain in/out of the aggregate.
     * Global ("global") is a select-all shortcut.
     *
     * Cancellation rules:
     *   • Rapid toggles coalesce into a single rebuild (pendingRebuild flag).
     *   • A rebuild that finds another rebuild already in flight chains itself
     *     via the rebuildInFlight promise — no overlapping setProps calls.
     */
    // ─── Scenario mode (exclusive) ───────────────────────────────────────
    //
    // A scenario is a standalone structural cascade, not a domain to be summed
    // into the aggregate. Selecting one leaves domain mode entirely; selecting any
    // domain row returns to it.

    /** Fetch the catalogue. Never throws — an unavailable catalogue just hides the section. */
    private async _loadScenarioCatalogue(): Promise<void> {
        try {
            const resp = await apiClient.get('/pro/domains/scenarios', { cache: 'no-store' }, true);
            if (!resp.ok) return;
            const body: any = await resp.json();
            this.scenarios = Array.isArray(body?.scenarios) ? body.scenarios : [];
        } catch {
            this.scenarios = [];
        }
    }

    /** The scenario graph, straight from the generic route (no history wrapper). */
    private async _fetchScenarioPayload(scenarioId: string): Promise<SpatialContagion> {
        const empty: SpatialContagion = {
            nodes: [], edges: [],
            epicenter_impact_score: 0, edge_intensity: 0,
            schema_version: 'empty', warning: 'no_scenario_payload',
        };
        try {
            const resp = await apiClient.get(
                `/pro/domains/${encodeURIComponent(scenarioId)}/spatial-contagion`,
                { cache: 'no-store' },
                true,
            );
            if (!resp.ok) return { ...empty, warning: `fetch_failed_${resp.status}` };
            return _normalizeSpatialPayload(await resp.json());
        } catch {
            return empty;
        }
    }

    /** Select a scenario EXCLUSIVELY — never merged with the domain aggregate. */
    async selectScenario(scenarioId: string): Promise<void> {
        if (this.destroyed) return;
        this.scenarioId = scenarioId;
        this.lastInteractionDomainId = scenarioId;

        const payload = await this._fetchScenarioPayload(scenarioId);
        if (payload.nodes.length === 0) {
            console.warn(`${LOG} scenario '${scenarioId}' returned no nodes — has the loader run?`);
        }
        this.domainCache.set(scenarioId, payload);
        this._updateStatsHud(payload);
        // isAggregate is derived as (domainId === GLOBAL_DOMAIN_ID), so a scenario id
        // correctly renders as a single non-aggregate graph (no domain lane offsets).
        await this._attachDomain(payload, scenarioId, /*animatePan=*/ true);
        this._refreshDomainRowStates();
    }

    async toggleDomain(domainId: string): Promise<void> {
        if (this.destroyed) return;
        // Any domain interaction leaves scenario mode.
        this.scenarioId = null;
        this.lastInteractionDomainId = domainId;

        if (domainId === GLOBAL_DOMAIN_ID) {
            // Select-all shortcut: enable every specialized domain.
            const allActive = SPECIALIZED_DOMAIN_IDS.every((d) => this.activeDomains.has(d));
            if (allActive) {
                // Already all active — no-op, but visually flash the row.
                this._refreshDomainRowStates();
                this._pulseDomainToggle(domainId);
                return;
            }
            for (const d of SPECIALIZED_DOMAIN_IDS) this.activeDomains.add(d);
        } else {
            if (this.activeDomains.has(domainId)) {
                this.activeDomains.delete(domainId);
            } else {
                this.activeDomains.add(domainId);
            }
            // Don't allow the aggregate to go fully empty — auto-reactivate
            // the last toggled-off domain instead of showing a black map.
            if (this.activeDomains.size === 0) {
                this.activeDomains.add(domainId);
            }
        }
        this._refreshDomainRowStates();
        await this._scheduleRebuild();
    }

    /** Coalesce rapid toggles into a single rebuild pass. */
    private async _scheduleRebuild(): Promise<void> {
        if (this.rebuildInFlight) {
            this.pendingRebuild = true;
            return;
        }
        this.rebuildInFlight = this._rebuildAggregate(true);
        try {
            await this.rebuildInFlight;
        } finally {
            this.rebuildInFlight = null;
            if (this.pendingRebuild) {
                this.pendingRebuild = false;
                void this._scheduleRebuild();
            }
        }
    }

    /**
     * Re-aggregate over current activeDomains and re-mount the surveillance
     * layer.
     *
     * Phase 6 wipe-guard: if the aggregate has zero nodes AND we already
     * have a working surveillance render, do NOT tear it down. The empty
     * result almost always means "prefetch hasn't populated the per-domain
     * cache yet" — the previous render (typically the bootstrap fallback)
     * is strictly better than a black map until real data lands.
     */
    private async _rebuildAggregate(animatePan: boolean): Promise<void> {
        try {
            const payload = this._buildAggregateFromCache(this.activeDomains);
            if (payload.nodes.length === 0 && this.surveillance) {
                console.warn(
                    `${LOG} rebuildAggregate produced empty aggregate ` +
                    `(reason=${(payload as any).warning ?? 'unknown'}); ` +
                    `preserving existing render`,
                );
                this._pulseDomainToggle(this.lastInteractionDomainId);
                return;
            }
            // Phase 6.5.9 — static-seed regression guard. If the aggregate
            // collapsed to the hardcoded demo fallback (e.g. a prefetch round
            // came back empty and _buildAggregateFromCache fell through to the
            // seeded GLOBAL_DOMAIN_ID payload) but the user is already looking
            // at a real live render, DO NOT tear it down. Reverting a populated
            // cross-domain network to the "Middle East" demo is the exact
            // self-sabotage we're eliminating.
            if (this._isStaticSeed(payload) && this.surveillance && this.lastRenderWasLive) {
                console.warn(
                    `${LOG} rebuildAggregate resolved to static demo seed; ` +
                    `preserving existing live render`,
                );
                this._pulseDomainToggle(this.lastInteractionDomainId);
                return;
            }
            this._teardownSurveillance();
            await this._attachDomain(payload, GLOBAL_DOMAIN_ID, animatePan);
            // Track render provenance so the guard above can protect it next time.
            this.lastRenderWasLive = !this._isStaticSeed(payload);
            this._pulseDomainToggle(this.lastInteractionDomainId);
        } catch (err) {
            console.warn(`${LOG} rebuildAggregate failed:`, err);
        }
    }

    /**
     * Phase 6.5.9 — does this payload come from the static client-side demo
     * fallback (getGlobalFallbackSpatialContagion) rather than the backend?
     * Identified by the markers that function stamps, so a real backend
     * aggregate that happens to be sparse is never mistaken for the seed.
     */
    private _isStaticSeed(payload: SpatialContagion | null | undefined): boolean {
        if (!payload) return false;
        const sv = (payload as any).schema_version;
        const warning = (payload as any).warning;
        return sv === 'global-fallback-v1' || warning === 'fallback_global_surveillance_demo';
    }

    /** Legacy single-domain swap; routed through the new multi-select model. */
    async switchDomain(newDomainId: string): Promise<void> {
        return this.toggleDomain(newDomainId);
    }

    stop = (): void => {
        if (this.destroyed) return;
        this.destroyed = true;
        this._teardownSurveillance();
        try { this.map?.remove(); } catch { /* swallow */ }
        this.map = null;
        this.overlay = null;
    };

    // ─── Module + map bootstrap ──────────────────────────────────────────

    private async _loadDeckModules(): Promise<void> {
        if (this.deckModules) return;
        const [maplibreglMod, layersMod, mapboxMod] = await Promise.all([
            import('maplibre-gl'),
            import('@deck.gl/layers'),
            import('@deck.gl/mapbox'),
        ]);
        const { MapCtor, AttributionControl, LngLatBounds } =
            resolveMapLibreExports(maplibreglMod as any);
        this.deckModules = {
            MapCtor,
            AttributionControl,
            LngLatBounds,
            ScatterplotLayer: (layersMod as any).ScatterplotLayer,
            ArcLayer: (layersMod as any).ArcLayer,
            TextLayer: (layersMod as any).TextLayer,
            MapboxOverlay: (mapboxMod as any).MapboxOverlay,
        };
        if (
            !this.deckModules.MapCtor || !this.deckModules.ScatterplotLayer ||
            !this.deckModules.ArcLayer || !this.deckModules.MapboxOverlay
        ) {
            throw new Error('Failed to resolve maplibre / deck.gl module exports');
        }
        // TextLayer is desired but not fatal — if it's missing from the
        // bundle, the surveillance controller silently skips critical labels.
    }

    private async _createBaseMap(initialPayload: SpatialContagion): Promise<void> {
        if (!this.deckModules) throw new Error('deckModules not loaded');
        const { MapCtor, AttributionControl, MapboxOverlay } = this.deckModules;

        const { centerLon, centerLat, initialZoom } = this._computeMapView(initialPayload);

        const map = new MapCtor({
            container: this.mapEl,
            style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
            center: [centerLon, centerLat],
            zoom: initialZoom,
            attributionControl: false,
            antialias: true,
        });
        if (AttributionControl) {
            map.addControl(new AttributionControl({ compact: true }), 'bottom-right');
        }
        requestAnimationFrame(() => map.resize());

        const overlay = new MapboxOverlay({
            interleaved: true,
            controller: false,
            layers: [],
            getCursor: ({ isHovering }: { isHovering: boolean }) =>
                isHovering ? 'pointer' : 'default',
            getTooltip: ({ object }: { object: any }) => {
                if (!object || typeof object.impact_score !== 'number') return null;
                return {
                    html: buildTooltipHtml(object as SpatialNode),
                    style: { background: 'transparent', padding: '0', border: 'none' },
                };
            },
        });

        await new Promise<void>((resolve) => {
            if (map.loaded()) { resolve(); return; }
            map.once('load', () => resolve());
        });
        map.addControl(overlay);

        // Absolute click-through fix: deck.gl's canvas can sit above HUD/inputs
        // in some stacking contexts; force it to never intercept browser events.
        const enforceDeckCanvasPassthrough = (): void => {
            const deckCanvas = map.getCanvasContainer?.()
                ?.querySelector?.('.deck-canvas') as HTMLElement | null;
            if (!deckCanvas) return;
            deckCanvas.style.pointerEvents = 'none';
            deckCanvas.style.zIndex = '1';
        };
        enforceDeckCanvasPassthrough();
        map.once('idle', enforceDeckCanvasPassthrough);

        // Phase 6.5 — ambient spatial-density graticules (10° dotted / 30° solid).
        const ensureGraticules = (): void => {
            try { _injectAmbientGraticules(map); }
            catch (gErr) { console.warn(`${LOG} graticule inject failed`, gErr); }
        };
        ensureGraticules();
        map.once('idle', ensureGraticules);

        map.on('error', (e: any) => {
            console.error(`${LOG} MapLibre error:`, e?.error?.message ?? e);
        });

        this.map = map;
        this.overlay = overlay;
    }

    // ─── Per-domain attach ───────────────────────────────────────────────

    private async _attachDomain(
        payload: SpatialContagion,
        domainId: string,
        animatePan: boolean,
    ): Promise<void> {
        if (!this.map || !this.overlay || !this.deckModules) return;
        const { ScatterplotLayer, ArcLayer, TextLayer, LngLatBounds } = this.deckModules;
        const nodes: SpatialNode[] = payload?.nodes ?? [];
        const edges: SpatialEdge[] = payload?.edges ?? [];

        if (nodes.length === 0) {
            this.overlay.setProps({ layers: [] });
            this._teardownSurveillance();
            return;
        }

        const isAggregate = domainId === GLOBAL_DOMAIN_ID;
        // Same co-location fan-out as the mount path (see applyColocationOffsets).
        // Applied BEFORE resolveEdgesFlat so arcs follow the displayed dots.
        const fanZoom = this.map?.getZoom?.() ?? 2;
        const displayNodes = applyColocationOffsets(nodes, fanZoom);
        const edgesFlat = resolveEdgesFlat(displayNodes, edges, isAggregate);

        const sid = safeId(domainId);
        const epicenterScore = (payload.epicenter_impact_score as number) || 100;

        const epicenterLayer = new ScatterplotLayer({
            id: `sc-epicenter-${sid}`,
            data: displayNodes.filter((n) => n.type === 'epicenter'),
            pickable: true, stroked: true, filled: true,
            radiusUnits: 'meters', radiusMinPixels: 10, radiusMaxPixels: 60,
            lineWidthMinPixels: 2,
            getPosition: (d: any) => [d.lon, d.lat],
            getRadius:   (d: any) => Math.max(25_000 + d.impact_score * 1_200, 35_000),
            getFillColor: [239, 68, 68, 210],
            getLineColor: [255, 100, 100, 255],
        });
        const affectedLayer = new ScatterplotLayer({
            id: `sc-affected-${sid}`,
            data: displayNodes.filter((n) => n.type === 'affected'),
            pickable: true, stroked: true, filled: true,
            radiusUnits: 'meters', radiusMinPixels: 5, radiusMaxPixels: 36,
            lineWidthMinPixels: 1,
            getPosition: (d: any) => [d.lon, d.lat],
            getRadius:   (d: any) => Math.max(12_000 + d.impact_score * 800, 16_000),
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
        const exposedLayer = buildExposedLayer(ScatterplotLayer, sid, displayNodes);
        const arcLayer = new ArcLayer({
            id: `sc-arcs-${sid}`,
            data: edgesFlat.filter((e: ResolvedEdge) => !e.unquantified),
            pickable: false,
            getSourcePosition: (d: ResolvedEdge) => [d.source_lon, d.source_lat],
            getTargetPosition: (d: ResolvedEdge) => [d.target_lon, d.target_lat],
            getSourceColor: (d: ResolvedEdge) =>
                isAggregate
                    ? arcDomainRgba(d.domain_id, 200, 'source', true)
                    : [239, 68, 68, 200],
            getTargetColor: (d: ResolvedEdge) =>
                isAggregate
                    ? arcDomainRgba(d.domain_id, 160, 'target', true)
                    : [34, 211, 238, 160],
            getWidth: (d: ResolvedEdge) => Math.max(d.intensity * 5, 1.5),
            widthMinPixels: 1, widthMaxPixels: 8,
            greatCircle: true,
            getHeight: (d: ResolvedEdge) =>
                0.40 + Math.abs(d.lane_offset ?? 0) * 0.22,
            numSegments: 64,
            ...arcLayerBlendProps(isAggregate),
        });
        const unquantifiedArcLayer = buildUnquantifiedArcLayer(ArcLayer, sid, edgesFlat);

        // One synchronous setProps so the user never sees a blank overlay
        // between teardown and the new animation loop's first repaint.
        this.overlay.setProps({
            layers: [unquantifiedArcLayer, arcLayer, exposedLayer, affectedLayer, epicenterLayer],
        });

        // Stop the outgoing controller at the single point of replacement, so no caller
        // can forget it and orphan a live rAF/poll loop. Idempotent.
        this._teardownSurveillance();

        this.surveillance = new SurveillanceMapController({
            container: this.stageEl,
            wrapEl: this.wrapEl,
            mapEl: this.mapEl,
            overlay: this.overlay,
            arcLayer, affectedLayer, epicenterLayer,
            exposedLayer, unquantifiedArcLayer,
            ScatterplotLayer,
            ArcLayerCtor: ArcLayer,
            TextLayer,
            nodes: displayNodes, edgesFlat,
            domainId,
            epicenterScore,
            // Phase 6.5.8: backend now serves global fragility-history, so
            // polling is always enabled (Global slider/play must stay live).
            // A scenario has no time axis — don't poll, and relabel the panel.
            enableHistoryPolling: this.scenarioId === null,
            staticScenario: this.scenarioId !== null,
            seedEntropy: (payload.entropy_index as number) ?? undefined,
            seedViscosity: (payload.viscosity_coefficient as number) ?? undefined,
            mapRef: this.map,   // ← needed for triggerRepaint() in the animation loop
        });
        this.surveillance.start();

        // Phase 6.1 — push the freshly-attached payload directly into the
        // Stats HUD. Decouples HUD updates from the aria-pressed observer,
        // which now (correctly) only fires on user toggles. Without this,
        // the HUD sits frozen at the seed values on initial mount.
        this._updateStatsHud(payload);

        if (animatePan && nodes.length > 1 && LngLatBounds) {
            const lons = nodes.map((n) => n.lon);
            const lats = nodes.map((n) => n.lat);
            const bounds = new LngLatBounds(
                [Math.min(...lons), Math.min(...lats)],
                [Math.max(...lons), Math.max(...lats)],
            );
            this.map.fitBounds(bounds, { padding: 70, maxZoom: 7, duration: 600 });
        }
    }

    private _teardownSurveillance(): void {
        if (this.surveillance) {
            this.surveillance.stop();
            this.surveillance = null;
        }
    }

    /**
     * Phase 6.1 — write the current aggregate's headline metrics into the
     * Stats HUD card (Impact / Affected / Edge ν / Epicenter). Always
     * sourced from the controller's payload, so the HUD is in lock-step
     * with the rendered map and never frozen at zero on cold boot.
     */
    private _updateStatsHud(payload: SpatialContagion): void {
        const host =
            this.stageEl.closest('.pro-map-global-container') ?? this.stageEl.parentElement;
        const hud = host?.querySelector<HTMLElement>('.pro-map-hud--top');
        if (!hud) return;
        // Pass the payload's own stats straight through — no `?? 0`. A null must stay
        // null so the HUD can print "--"; coercing it to 0 asserts a measured zero.
        hud.innerHTML = renderStatsHudBody(
            buildStatsHudPayload(
                payload.nodes ?? [],
                null,
                payload.epicenter_impact_score as number,
                (payload.edge_intensity as number | null | undefined) ?? null,
            ),
        );
    }

    private _computeMapView(payload: SpatialContagion): {
        centerLon: number; centerLat: number; initialZoom: number;
    } {
        const nodes = payload?.nodes ?? [];
        if (nodes.length === 0) return { centerLon: 30, centerLat: 25, initialZoom: 2 };
        const lons = nodes.map((n) => n.lon);
        const lats = nodes.map((n) => n.lat);
        return {
            centerLon: (Math.min(...lons) + Math.max(...lons)) / 2,
            centerLat: (Math.min(...lats) + Math.max(...lats)) / 2,
            initialZoom: nodes.length === 1 ? 5 : 2,
        };
    }

    // ─── Payload resolution + caching ────────────────────────────────────
    //
    // Phase 6 — all rendering paths flow through `_buildAggregateFromCache`,
    // so there is no need for a per-domain resolver. `_fetchDomainPayload`
    // populates `domainCache` and the aggregator reads from it.

    private async _fetchDomainPayload(domainId: string): Promise<SpatialContagion> {
        // Phase 7.2 — the live Spatial Engine indexes domains by the short id
        // ('energy', 'shipping', ...). Apply the alias only on the wire so
        // the rest of the controller keeps using the long DOMAIN_REGISTRY id.
        const wireId = toSpatialDomainId(domainId);
        const resp = await apiClient.get(
            `/pro/domains/${encodeURIComponent(wireId)}/fragility-history?days=1`,
            { cache: 'no-store' },
            true,
        );
        if (!resp.ok) {
            return {
                nodes: [], edges: [],
                epicenter_impact_score: 0, edge_intensity: 0,
                schema_version: 'unavailable',
                warning: `fetch_failed_${resp.status}`,
            };
        }
        const body: any = await resp.json();
        const sc = body?.latest_spatial_contagion;
        if (sc && Array.isArray(sc.nodes) && sc.nodes.length > 0) {
            return _normalizeSpatialPayload(sc);
        }
        return {
            nodes: [], edges: [],
            epicenter_impact_score: 0, edge_intensity: 0,
            schema_version: 'empty',
            warning: 'no_spatial_contagion_for_domain',
        };
    }

    /**
     * Phase 7.2 — live fetch of the cross-domain Omni-Monitor view.
     * Backed by `/api/pro/domains/global/spatial-contagion`. Returns null
     * if the endpoint is unreachable so the caller can fall back to the
     * static seed payload.
     */
    private async _fetchGlobalContagion(): Promise<SpatialContagion | null> {
        try {
            const resp = await apiClient.get(
                `/pro/domains/global/spatial-contagion`,
                { cache: 'no-store' },
                true,
            );
            if (!resp.ok) return null;
            const body: any = await resp.json();
            if (Array.isArray(body?.nodes) && body.nodes.length > 0) {
                return _normalizeSpatialPayload(body);
            }
        } catch (err) {
            console.warn(`${LOG} global spatial-contagion fetch failed`, err);
        }
        return null;
    }

    /**
     * Phase 6.1 — non-blocking prefetch of every specialized domain.
     * Each successful fetch lands in `domainCache` so the next call to
     * `_buildAggregateFromCache` can merge it. Outcomes are logged
     * per-domain (node count + warning, if any) so cold-boot misses are
     * visible without breakpoints.
     */
    private async _prefetchSpecializedDomains(): Promise<{ filled: number; empty: number }> {
        const missing = SPECIALIZED_DOMAIN_IDS.filter((d) => !this.domainCache.has(d));
        if (missing.length === 0) return { filled: 0, empty: 0 };
        let filled = 0;
        let empty = 0;
        await Promise.all(missing.map(async (d) => {
            try {
                const p = await this._fetchDomainPayload(d);
                this.domainCache.set(d, p);
                const nc = Array.isArray(p.nodes) ? p.nodes.length : 0;
                if (nc > 0) {
                    filled += 1;
                    console.log(`${LOG} prefetch ${d}: ${nc} nodes`);
                } else {
                    empty += 1;
                    console.log(`${LOG} prefetch ${d}: empty (${(p as any).warning ?? 'unknown'})`);
                }
            } catch (err) {
                empty += 1;
                console.warn(`${LOG} prefetch ${d} failed`, err);
            }
        }));
        console.log(`${LOG} prefetch summary: ${filled} populated / ${empty} empty of ${missing.length}`);
        // Refresh sidebar order_counts now that data has arrived.
        this._buildSidebar();
        this._refreshDomainRowStates();
        return { filled, empty };
    }

    // ─── Global aggregation (in-memory, no network) ─────────────────────

    /**
     * Phase 6 — Aggregate the cached per-domain payloads filtered by the
     * `restrictTo` set. The Criticality filter ("Signal over Noise" rule)
     * keeps a node iff:
     *   (a) type === 'epicenter', OR
     *   (b) impact_score crosses the 1.5x trigger threshold, OR
     *   (c) it is reachable in ≤2 hops from an active epicenter
     *       (order ∈ {2, 3} — already true by our construction).
     *
     * Currently every affected node satisfies (c), so the practical filter
     * effect is "only include nodes from active domains". The function is
     * structured so we can tighten the filter later without changing call
     * sites.
     */
    private _buildAggregateFromCache(restrictTo: Set<string>): SpatialContagion {
        const aggNodes: SpatialNode[] = [];
        const aggEdges: SpatialEdge[] = [];
        let maxImpact = 0;
        let intensitySum = 0;
        let intensityCount = 0;
        const seenCoordByDomain = new Set<string>();
        const orderCounts: Record<number, number> = { 1: 0, 2: 0, 3: 0 };
        let criticalCount = 0;

        for (const domainId of SPECIALIZED_DOMAIN_IDS) {
            if (!restrictTo.has(domainId)) continue;
            const payload = this.domainCache.get(domainId);
            if (!payload || !Array.isArray(payload.nodes) || payload.nodes.length === 0) {
                continue;
            }
            const prefix = `${safeId(domainId)}__`;

            for (const n of payload.nodes) {
                // Signal-over-noise filter — keep iff epicenter or critical
                // or order ≤ 3 (the 1st/2nd-hop ripple constraint).
                const order = (n.order ?? 2) as ContagionOrder;
                const isCritical = n.impact_score >= TM_TRIGGER_IMPACT_THRESHOLD;
                const isEpi = n.type === 'epicenter';
                const isRipple = order <= 3;
                if (!(isEpi || isCritical || isRipple)) continue;

                // Phase 7.12 — per-domain coord keys only. Never collapse Shipping
                // into Energy when both share Panama Canal coordinates.
                const coordKey = `${domainId}|${n.lat.toFixed(4)}|${n.lon.toFixed(4)}`;
                if (seenCoordByDomain.has(coordKey)) continue;
                seenCoordByDomain.add(coordKey);
                aggNodes.push({ ...n, id: `${prefix}${n.id}` });
                orderCounts[order] = (orderCounts[order] || 0) + 1;
                if (isCritical) criticalCount += 1;
                maxImpact = Math.max(maxImpact, n.impact_score || 0);
            }
            // Every edge from this domain — no cross-domain deduplication.
            for (const e of payload.edges) {
                aggEdges.push({
                    source_id: `${prefix}${e.source_id}`,
                    target_id: `${prefix}${e.target_id}`,
                    intensity: e.intensity,
                    target_order: e.target_order,
                    domain_id: domainId,
                });
            }
            if (typeof payload.edge_intensity === 'number') {
                intensitySum += payload.edge_intensity;
                intensityCount += 1;
            }
        }

        // Backfill endpoint nodes so edges are never dropped when a hop node
        // missed the signal filter but is still referenced by an arc.
        const nodeById = new Map(aggNodes.map((n) => [n.id, n]));
        for (const domainId of SPECIALIZED_DOMAIN_IDS) {
            if (!restrictTo.has(domainId)) continue;
            const payload = this.domainCache.get(domainId);
            if (!payload) continue;
            const prefix = `${safeId(domainId)}__`;
            const rawById = new Map(payload.nodes.map((n) => [n.id, n]));
            for (const e of payload.edges ?? []) {
                for (const end of [e.source_id, e.target_id] as const) {
                    const prefixed = `${prefix}${end}`;
                    if (nodeById.has(prefixed)) continue;
                    const raw = rawById.get(end);
                    if (!raw) continue;
                    const stub = { ...raw, id: prefixed };
                    aggNodes.push(stub);
                    nodeById.set(prefixed, stub);
                }
            }
        }

        const survivedIds = new Set(aggNodes.map((n) => n.id));
        const survivedEdges = aggEdges.filter(
            (e) => survivedIds.has(e.source_id) && survivedIds.has(e.target_id),
        );

        // Phase 6.1 — cold-boot fallback. If no specialized domain has any
        // cached spatial data yet (typical immediately after page load),
        // fall through to the seeded GLOBAL payload so the omni-monitor
        // never renders empty. As soon as real per-domain payloads land,
        // this branch stops triggering on its own.
        if (aggNodes.length === 0) {
            const seed = this.domainCache.get(GLOBAL_DOMAIN_ID);
            if (seed && Array.isArray(seed.nodes) && seed.nodes.length > 0) {
                return seed;
            }
        }

        return {
            nodes: aggNodes,
            edges: survivedEdges,
            epicenter_impact_score: maxImpact,
            edge_intensity: intensityCount > 0 ? intensitySum / intensityCount : 0,
            node_count: aggNodes.length,
            edge_count: survivedEdges.length,
            schema_version: 'omni_aggregate_v2',
            order_counts: {
                order_1: orderCounts[1],
                order_2: orderCounts[2],
                order_3: orderCounts[3],
            },
            warning: aggNodes.length === 0
                ? (restrictTo.size === 0 ? 'no_active_domains' : 'no_cached_domains')
                : undefined,
        };
    }

    // ─── Sidebar UI ──────────────────────────────────────────────────────

    private _buildSidebar(): void {
        const hostContainer =
            this.stageEl.closest('.pro-map-global-container') ?? this.stageEl.parentElement;
        const sidebar = hostContainer?.querySelector<HTMLElement>('.pro-map-sidebar');
        if (!sidebar) return;

        if (!sidebar.dataset.dsrSidebar) {
            sidebar.innerHTML = `
                <h2 style="font-size:1.0rem;margin:0 0 0.4rem;color:#7dd3fc;letter-spacing:0.10em;text-transform:uppercase;">
                    Omni-Domain Filters
                </h2>
                <p style="font-size:0.72rem;color:#94a3b8;line-height:1.5;margin:0 0 0.8rem;">
                    Multi-select layer filters — toggle a domain on/off in the live cross-domain aggregate. <strong style="color:#7dd3fc;">Global</strong> at the top selects all.
                </p>
                <div class="dsr-domain-list" data-role="dsr-list"></div>
            `;
            sidebar.dataset.dsrSidebar = '1';
            this._injectSidebarStyles();
        }
        const listEl = sidebar.querySelector<HTMLElement>('[data-role="dsr-list"]');
        if (!listEl) return;
        this.sidebarListEl = listEl;

        const rowsHtml = DOMAIN_REGISTRY
            .map((d, idx) => {
                const payload = this.domainCache.get(d.id);
                const oc = payload?.order_counts as { order_1?: number; order_2?: number; order_3?: number } | undefined;
                const orderStr = oc
                    ? `${oc.order_1 ?? 0} / ${oc.order_2 ?? 0} / ${oc.order_3 ?? 0}`
                    : '— / — / —';
                const iconHtml = d.icon === 'SYNC'
                    ? `<span class="dsr-icon dsr-icon-sync"><svg viewBox="0 0 24 24" width="16" height="16">
                          <circle cx="12" cy="12" r="4" fill="${d.accent}"></circle>
                          <circle cx="12" cy="12" r="9" fill="none" stroke="${d.accent}" stroke-width="1.4" stroke-dasharray="2.6 2.4"></circle>
                       </svg></span>`
                    : `<span class="dsr-icon" aria-hidden="true">${d.icon}</span>`;
                const separator = idx === 1 ? '<div class="dsr-separator" aria-hidden="true"></div>' : '';
                // Toggle indicator (custom checkbox) — visualises active state
                // without taking the click handler from the row.
                const toggleHtml = d.isAggregate
                    ? `<span class="dsr-shortcut" title="Select all">ALL</span>`
                    : `<span class="dsr-toggle" aria-hidden="true">
                           <span class="dsr-toggle-dot"></span>
                       </span>`;
                return `
                    ${separator}
                    <button type="button" class="dsr-domain-row" data-domain="${d.id}"
                        style="--dsr-accent:${d.accent};"
                        role="${d.isAggregate ? 'button' : 'switch'}"
                        aria-checked="false">
                        ${iconHtml}
                        <span class="dsr-label">${d.label}</span>
                        <span class="dsr-orders" title="Order 1 / 2 / 3 node counts">${orderStr}</span>
                        ${toggleHtml}
                    </button>
                `;
            })
            .join('');
        // ── Scenario section ────────────────────────────────────────────
        // Appended BELOW the domains, behind its own heading, because these are a
        // different kind of thing: exclusive structural cascades, not summable
        // domains. Rendered only when the catalogue returned something, so the
        // section simply doesn't exist if the API is unavailable.
        const scenarioHtml = this.scenarios.length
            ? `
                <div class="dsr-separator" aria-hidden="true"></div>
                <div class="dsr-section-head">Scenarios</div>
                ${this.scenarios.map((s) => `
                    <button type="button" class="dsr-domain-row dsr-scenario-row"
                        data-scenario="${esc(s.id)}"
                        style="--dsr-accent:#94a3b8;"
                        role="radio" aria-checked="false"
                        title="${esc(s.hub ?? s.id)}">
                        <span class="dsr-icon" aria-hidden="true">◎</span>
                        <span class="dsr-label">${esc(scenarioDisplayName(s))}</span>
                        <span class="dsr-orders" title="nodes / edges">${s.node_count ?? '—'}n</span>
                    </button>
                `).join('')}
              `
            : '';

        listEl.innerHTML = rowsHtml + scenarioHtml;
        listEl.querySelectorAll<HTMLButtonElement>('button.dsr-domain-row').forEach((btn) => {
            btn.addEventListener('click', () => {
                const scenario = btn.dataset.scenario;
                if (scenario) {
                    void this.selectScenario(scenario);
                    return;
                }
                const target = btn.dataset.domain;
                if (target) void this.toggleDomain(target);
            });
        });
        this._refreshDomainRowStates();
    }

    /**
     * Phase 6 — sync the sidebar's visual state to `activeDomains`.
     * The "Global" row is considered active when ALL specialized domains
     * are on (it doubles as a select-all toggle indicator).
     */
    private _refreshDomainRowStates(): void {
        const list = this.sidebarListEl;
        if (!list) return;
        const allActive = SPECIALIZED_DOMAIN_IDS.every((d) => this.activeDomains.has(d));
        list.querySelectorAll<HTMLElement>('button.dsr-domain-row').forEach((btn) => {
            // Scenario rows are radio-exclusive and carry data-scenario, not data-domain.
            const scenario = btn.dataset.scenario;
            if (scenario) {
                const on = this.scenarioId === scenario;
                btn.classList.toggle('is-active', on);
                const s = on ? 'true' : 'false';
                if (btn.getAttribute('aria-checked') !== s) btn.setAttribute('aria-checked', s);
                return;
            }
            const id = btn.dataset.domain;
            if (!id) return;
            // While a scenario is showing, NO domain row is active — the aggregate
            // isn't on screen, and lighting one up would misreport what's rendered.
            const active = this.scenarioId
                ? false
                : (id === GLOBAL_DOMAIN_ID ? allActive : this.activeDomains.has(id));
            btn.classList.toggle('is-active', active);
            const nextStr = active ? 'true' : 'false';
            // Guard each setAttribute behind a value-changed check: a
            // re-assigned attribute, even with the same value, fires
            // MutationObserver. Phase 5's stats-HUD observer interprets that
            // as "domain re-activated" and refires a network request — with
            // multi-select, init alone would otherwise burst 7 parallel
            // fragility-history fetches.
            if (btn.getAttribute('aria-checked') !== nextStr) {
                btn.setAttribute('aria-checked', nextStr);
            }
            if (btn.getAttribute('aria-pressed') !== nextStr) {
                btn.setAttribute('aria-pressed', nextStr);
            }
        });
    }

    /** Phase 6.5.8 — tactile ack even when vector output barely changes. */
    private _pulseDomainToggle(domainId: string): void {
        const list = this.sidebarListEl;
        if (!list) return;
        const target = list.querySelector<HTMLElement>(
            `button.dsr-domain-row[data-domain="${domainId}"]`,
        );
        if (!target) return;
        target.classList.remove('dsr-domain-row--pulse');
        // Force reflow so repeated toggles replay the animation.
        void target.offsetWidth;
        target.classList.add('dsr-domain-row--pulse');
        window.setTimeout(() => {
            target.classList.remove('dsr-domain-row--pulse');
        }, 340);
    }

    private _injectSidebarStyles(): void {
        if (document.getElementById('dsr-sidebar-styles')) return;
        const style = document.createElement('style');
        style.id = 'dsr-sidebar-styles';
        style.textContent = `
            .dsr-domain-list {
                display: flex;
                flex-direction: column;
                gap: 6px;
            }
            .dsr-separator {
                height: 1px;
                background: rgba(148,163,184,0.18);
                margin: 4px 6px;
            }
            /* Scenarios are a different KIND of selection (exclusive structural
               cascades, not summable domains) — give the group its own heading. */
            .dsr-section-head {
                padding: 6px 12px 2px;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 0.14em;
                text-transform: uppercase;
                color: #64748b;
            }
            .dsr-scenario-row .dsr-icon { color: #94a3b8; }
            .dsr-scenario-row.is-active .dsr-icon { color: #e2e8f0; }
            .dsr-domain-row {
                display: flex;
                align-items: center;
                gap: 10px;
                padding: 8px 12px;
                border-radius: 10px;
                cursor: pointer;
                background: rgba(8,13,24,0.62);
                border: 1px solid rgba(148,163,184,0.14);
                color: #cbd5e1;
                font-family: 'Inter', system-ui, sans-serif;
                font-size: 0.78rem;
                font-weight: 600;
                letter-spacing: 0.01em;
                transition: transform 0.12s ease, border-color 0.18s ease,
                            background 0.18s ease, color 0.18s ease,
                            box-shadow 0.18s ease;
                text-align: left;
                width: 100%;
            }
            .dsr-domain-row:hover {
                color: #e2e8f0;
                border-color: color-mix(in srgb, var(--dsr-accent) 55%, rgba(148,163,184,0.20));
                background: color-mix(in srgb, var(--dsr-accent) 8%, rgba(8,13,24,0.62));
                transform: translateY(-1px);
            }
            .dsr-domain-row.is-active {
                color: #ffffff;
                border-color: var(--dsr-accent);
                background: color-mix(in srgb, var(--dsr-accent) 16%, rgba(8,13,24,0.62));
                box-shadow:
                    inset 3px 0 0 var(--dsr-accent),
                    0 0 18px color-mix(in srgb, var(--dsr-accent) 35%, transparent);
            }
            .dsr-domain-row .dsr-icon {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 22px;
                height: 22px;
                font-size: 1rem;
                line-height: 1;
                flex-shrink: 0;
            }
            .dsr-domain-row .dsr-icon-sync svg {
                animation: dsr-sync-spin 6s linear infinite;
            }
            @keyframes dsr-sync-spin {
                from { transform: rotate(0deg); }
                to   { transform: rotate(360deg); }
            }
            .dsr-domain-row .dsr-label {
                flex: 1;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .dsr-domain-row .dsr-orders {
                font-family: ui-monospace, monospace;
                font-size: 0.66rem;
                color: #64748b;
                font-variant-numeric: tabular-nums;
                letter-spacing: 0.04em;
            }
            .dsr-domain-row.is-active .dsr-orders {
                color: color-mix(in srgb, var(--dsr-accent) 65%, #cbd5e1);
            }

            /* Phase 6 — Multi-select toggle indicator */
            .dsr-toggle {
                width: 26px;
                height: 14px;
                border-radius: 999px;
                background: rgba(15, 23, 42, 0.85);
                border: 1px solid rgba(148, 163, 184, 0.40);
                position: relative;
                transition: background 0.18s ease, border-color 0.18s ease;
                flex-shrink: 0;
            }
            .dsr-toggle-dot {
                position: absolute;
                top: 1px;
                left: 1px;
                width: 10px;
                height: 10px;
                border-radius: 50%;
                background: #94a3b8;
                transition: transform 0.22s cubic-bezier(0.4, 0, 0.2, 1), background 0.18s ease;
            }
            .dsr-domain-row.is-active .dsr-toggle {
                background: color-mix(in srgb, var(--dsr-accent) 35%, rgba(15, 23, 42, 0.85));
                border-color: var(--dsr-accent);
            }
            .dsr-domain-row.is-active .dsr-toggle-dot {
                transform: translateX(12px);
                background: var(--dsr-accent);
                box-shadow: 0 0 6px var(--dsr-accent);
            }
            .dsr-shortcut {
                font-size: 0.58rem;
                font-weight: 800;
                letter-spacing: 0.12em;
                color: var(--dsr-accent);
                background: color-mix(in srgb, var(--dsr-accent) 14%, transparent);
                border: 1px solid color-mix(in srgb, var(--dsr-accent) 45%, transparent);
                padding: 2px 7px;
                border-radius: 6px;
                flex-shrink: 0;
            }
            .dsr-domain-row.is-active .dsr-shortcut {
                background: color-mix(in srgb, var(--dsr-accent) 32%, transparent);
                color: #ffffff;
            }
            .dsr-domain-row--pulse {
                animation: dsr-toggle-pulse 0.32s ease-out;
            }
            @keyframes dsr-toggle-pulse {
                0% {
                    transform: scale(1);
                    box-shadow: 0 0 0 rgba(34, 211, 238, 0);
                    opacity: 1;
                }
                50% {
                    transform: scale(0.985);
                    box-shadow: 0 0 0 2px color-mix(in srgb, var(--dsr-accent) 42%, transparent);
                    opacity: 0.76;
                }
                100% {
                    transform: scale(1);
                    box-shadow: 0 0 0 rgba(34, 211, 238, 0);
                    opacity: 1;
                }
            }
        `;
        document.head.appendChild(style);
    }
}


/**
 * Public bootstrap for the dashboard's GLOBAL surveillance pane. Returns
 * the controller so the host can keep a handle for teardown / external
 * domain switches.
 */
export async function bootstrapSpatialMap(
    stageEl: HTMLElement,
    initialPayload: SpatialContagion,
    initialDomain: string = GLOBAL_DOMAIN_ID,
): Promise<DashboardSpatialController> {
    const sid = safeId(initialDomain);
    const wrapEl = stageEl.querySelector(`#sc-wrap-${sid}`) as HTMLElement | null;
    const mapEl = stageEl.querySelector(`#sc-map-${sid}`) as HTMLElement | null;
    if (!wrapEl || !mapEl) {
        throw new Error(`${LOG} bootstrap: spatial shell elements not found (#sc-wrap-${sid} / #sc-map-${sid})`);
    }
    await waitForVisibleMapElement(mapEl);
    injectMaplibreCss();
    const ctrl = new DashboardSpatialController({ stageEl, mapEl, wrapEl });
    await ctrl.bootstrap(initialPayload, initialDomain);
    const loadingEl = stageEl.querySelector(`#sc-loading-${sid}`) as HTMLElement | null;
    if (loadingEl) {
        loadingEl.style.transition = 'opacity 0.4s ease';
        loadingEl.style.opacity = '0';
        setTimeout(() => loadingEl.remove(), 420);
    }
    return ctrl;
}
