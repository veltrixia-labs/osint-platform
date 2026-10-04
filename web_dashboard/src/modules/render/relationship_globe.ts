/**
 * Globe mode for the relationship view — the same graph, placed geographically.
 *
 * ★★ ISOLATION CONTRACT — read before adding an import.
 *
 *   This module may import ONLY: maplibre-gl, and types from relationship_graph_canvas.
 *   It must NEVER import from, or read, any of the chokepoint-scenario apparatus:
 *     • the five scenario payloads (strait_of_hormuz.json &c.) or /pro/domains/* routes
 *     • the impact roster (impact_roster_rows / impact_roster_loads, /pro/impact-roster)
 *     • the spatial_nodes / spatial_edges / contagion_history tables
 *     • pro_interactive_map.ts, pro_trigger_map.ts
 *     • any node field named impact_score, raw_impact, order, confidence, intensity,
 *       viscosity_coefficient, entropy_index, is_epicenter
 *
 *   The reason is the vault's CLAUDE.md §5. order-3 in export_scenarios.py is a country×domain
 *   cross-product with NO edge predicate: it assigns a firm impact = country × DECAY(0.7)
 *   whether or not that firm has any edge to the hub — INPEX sits at −0.63 with no Hormuz edge
 *   at all — and the coordinate gate is the only thing that keeps such a node off a map. A globe
 *   is exactly the surface where a coordinate turns a derived number into a published one. This
 *   view therefore carries coordinates and NOTHING else from that side: position is presentation,
 *   and every edge drawn here is one the vault authored.
 *
 *   node_coordinates.json's own header says the same thing: "Presentation layer only.
 *   Coordinates are NOT graph structure and never enter canonical .md."
 */
import maplibregl from 'maplibre-gl';
// ★ MapLibre's OWN stylesheet. Without it .maplibregl-map / -canvas-container / -canvas carry no
//   position or size rules, so the GL canvas does not fill its container — the globe rendered
//   ~1030px wide inside a ~1900px host. The existing maps get this from injectMaplibreCss()
//   (pro_interactive_map.ts:568), a <link> to unpkg; that module is off-limits here under the
//   isolation contract, and bundling from the package is better anyway: no CDN, no version skew.
import 'maplibre-gl/dist/maplibre-gl.css';
import { PALETTE } from './relationship_graph_canvas';
// Pure geometry + easing, no imports of its own. See its header for exactly what was ported
// from the legacy deck.gl arcs and what had to be re-derived.
import { arc, arcProgress, easeOutCubic, ARC_POINTS } from './relationship_arcs';

export type GlobeNode = { id: string; type?: string | null; country?: string | null };
export type GlobeEdge = { s: string; t: string; type: string; weight?: number | null };
type Coord = { lat: number; lng: number; type?: string; city?: string };

/** Same basemap as the Pro map — CARTO dark-matter, no token. */
export const BASEMAP = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

const DEFAULT_COLOR = '#64748b';

/** Spread animation. The arcs draw outward from the selected node over ARC_MS, ease-out. */
const ARC_MS = 600;
const PULSE_MS = 420;
/** Hard cap on arcs per selection. China has ~190 edges; drawing them all is unreadable as well
 *  as slow, so the cap is a legibility decision first. Which 60 survive is decided by
 *  arcPriority() below, never by array order. */
const MAX_ARCS = 60;
/** Competitor is the second-largest edge type in the graph (299 of 1535) and is symmetric
 *  rather than directional, so it is drawn dimmer and ranked last under the cap. */
const DIM_TYPES = new Set(['competitor']);
const humanize = (id: string) => id.replace(/_/g, ' ');

export type GlobeHandle = {
    select: (id: string | null) => void;
    focus: (id: string) => void;
    resize: () => void;
    refit: () => void;
    destroy: () => void;
};

export function mountGlobe(
    host: HTMLElement,
    nodes: GlobeNode[],
    edges: GlobeEdge[],
    coords: Record<string, Coord>,
    onSelect: (id: string | null) => void,
): GlobeHandle {
    const t0 = performance.now();
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const deg = new Map<string, number>();
    for (const e of edges) {
        deg.set(e.s, (deg.get(e.s) || 0) + 1);
        deg.set(e.t, (deg.get(e.t) || 0) + 1);
    }
    const adj = new Map<string, Set<string>>();
    for (const e of edges) {
        if (!adj.has(e.s)) adj.set(e.s, new Set());
        if (!adj.has(e.t)) adj.set(e.t, new Set());
        adj.get(e.s)!.add(e.t); adj.get(e.t)!.add(e.s);
    }
    const geo = nodes.filter((n) => coords[n.id]);
    const nongeo = nodes.filter((n) => !coords[n.id]);

    const mapEl = document.createElement('div');
    mapEl.className = 'rv-globe';
    host.appendChild(mapEl);

    // Non-geographic dock: concepts, markets, funds, blocs and orgs have no coordinate BY DESIGN
    // (node_coordinates.json's no_coords_by_design list). They are not missing data and must not
    // be dropped from the view — they are where most of the vault's hub structure lives.
    const dock = document.createElement('div');
    dock.className = 'rv-dock'; dock.dataset.expanded = '0';
    const ranked = nongeo.slice().sort((a, b) => (deg.get(b.id) || 0) - (deg.get(a.id) || 0));
    const CHIPS_COLLAPSED = 24;        // ~3 rows at the dock's width; the rest behind "+N more"
    const chip = (n: GlobeNode) =>
        `<button class="rv-chip-n" data-goto="${n.id}" style="--c:${PALETTE[n.type || ''] || DEFAULT_COLOR}">${humanize(n.id)}</button>`;
    const renderDock = () => {
        const expanded = dock.dataset.expanded === '1';
        const shown = expanded ? ranked : ranked.slice(0, CHIPS_COLLAPSED);
        const rest = ranked.length - shown.length;
        dock.innerHTML = `<span class="rv-dock-l">Non-geographic</span>`
            + shown.map(chip).join('')
            + (rest > 0 ? `<button class="rv-dock-more" data-more="1">+${rest} more</button>` : '')
            + (expanded ? `<button class="rv-dock-more" data-more="0">show less</button>` : '');
        refresh();
    };
    host.appendChild(dock);

    // ★ MAX_ARCS truncation is announced, never silent. Measured on the committed graph, the cap
    //   bites on exactly 2 of 248 placeable nodes — but on one of them it is severe:
    //   United_States has 132 edges, so 72 arcs are not drawn. A map that shows 60 of 132
    //   relationships and says nothing is a map that reads as complete. The list view beside it
    //   still carries every neighbour; this note is what tells the reader to go look.
    const note = document.createElement('div');
    note.className = 'rv-arcnote';
    note.hidden = true;
    host.appendChild(note);

    /** Finite, in-range coordinates only. One bad entry would otherwise poison the whole bounds. */
    const finiteCoords = (ids: string[]) => ids.filter((id) => {
        const c = coords[id];
        return c && Number.isFinite(c.lat) && Number.isFinite(c.lng)
            && c.lat >= -90 && c.lat <= 90 && c.lng >= -180 && c.lng <= 180;
    });
    const placeable = finiteCoords(geo.map((n) => n.id));
    const geoBounds = () => {
        const b = new maplibregl.LngLatBounds();
        for (const id of placeable) b.extend([coords[id].lng, coords[id].lat]);
        return b;
    };

    // ★ The constructor gets a PLAIN center/zoom and no `bounds`. The previous version passed
    //   `bounds: …, center: undefined, zoom: undefined`, and an explicitly-present `undefined`
    //   is not the same as an absent key: option-merging copies it over the default. The initial
    //   framing now happens in `once('load')` via fitBounds, where the map definitely exists and
    //   a failure is recoverable instead of fatal to the mount.
    const map = new maplibregl.Map({
        container: mapEl, style: BASEMAP, center: [20, 25], zoom: 1.2,
        attributionControl: false, dragRotate: false,
    });
    const dead = () => !map || (map as any)._removed === true;
    const safeResize = () => { if (!dead()) map.resize(); };
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

    let selected: string | null = null;
    let mountedMs = 0;

    const pointFC = () => ({
        type: 'FeatureCollection' as const,
        features: geo.map((n) => {
            const c = coords[n.id];
            const inEgo = !selected || n.id === selected || (adj.get(selected)?.has(n.id) ?? false);
            return {
                type: 'Feature' as const,
                geometry: { type: 'Point' as const, coordinates: [c.lng, c.lat] },
                properties: {
                    id: n.id, label: humanize(n.id), ntype: n.type || '',
                    color: PALETTE[n.type || ''] || DEFAULT_COLOR,
                    radius: 3 + Math.log1p(deg.get(n.id) || 0) * 1.9,
                    ring: n.type === 'country' ? 1 : 0,
                    alpha: inEgo ? 1 : 0.15,
                    sel: n.id === selected ? 1 : 0,
                },
            };
        }),
    });

    // ──────────────────────────────────────────────────────────────────────────────────────────
    // Arc spread
    // ──────────────────────────────────────────────────────────────────────────────────────────
    type Arc = {
        pts: [number, number][];
        etype: string;
        color: string;
        dim: 0 | 1;      // competitor — drawn thinner and fainter
        w: 0 | 1;        // 0 = the vault authored no weight for this edge
        other: string;
    };
    const EMPTY = { type: 'FeatureCollection' as const, features: [] as any[] };

    /** Which arcs survive MAX_ARCS. Lower sorts first, i.e. is kept.
     *  ★ A weighted non-competitor edge outranks an unweighted one, but the WEIGHT ITSELF is not
     *    a ranking key beyond present/absent. Ranking by magnitude would quietly make the cap a
     *    statement about which dependencies matter most, and this view's weights are
     *    within-hub-relative and 425-of-546 estimated (vault CLAUDE.md sections 3 and 4) — not a
     *    cross-hub ordering. Ties fall back to the counterpart id so the kept set is stable
     *    across renders instead of following array order. */
    const arcPriority = (e: GlobeEdge, other: string): [number, number, string] =>
        [DIM_TYPES.has(e.type) ? 1 : 0, e.weight == null ? 1 : 0, other];

    /** Every edge of `selected`, split into arcs that land on a coordinate and arcs that land in
     *  the non-geographic dock. Geometry is built ONCE per selection, never per frame. */
    /** Every edge touching `selected`, drawn or not — the denominator for the truncation note.
     *  Counted from `edges`, not from `adj`, because adj is a SET of neighbours and would
     *  under-count a pair joined by more than one edge type. */
    let totalEdges = 0;

    const buildArcs = (): { geo: Arc[]; dockArcs: Arc[] } => {
        if (!selected) return { geo: [], dockArcs: [] };
        const a = coords[selected];
        const cand: Array<{ e: GlobeEdge; other: string; key: [number, number, string] }> = [];
        for (const e of edges) {
            // Annotated, not inferred: without it tsc reports TS7022 (circular inference)
            // because `other` is handed straight to arcPriority, whose own parameter is `other`.
            const other: string | null = e.s === selected ? e.t : e.t === selected ? e.s : null;
            if (!other || other === selected) continue;
            cand.push({ e, other, key: arcPriority(e, other) });
        }
        totalEdges = cand.length;
        cand.sort((x, y) =>
            x.key[0] - y.key[0] || x.key[1] - y.key[1] || (x.key[2] < y.key[2] ? -1 : x.key[2] > y.key[2] ? 1 : 0));

        const geo: Arc[] = [];
        const dockArcs: Arc[] = [];
        for (const { e, other } of cand) {
            if (geo.length + dockArcs.length >= MAX_ARCS) break;
            const base: Omit<Arc, 'pts'> = {
                etype: e.type,
                color: PALETTE[byId.get(other)?.type || ''] || DEFAULT_COLOR,
                dim: DIM_TYPES.has(e.type) ? 1 : 0,
                w: e.weight == null ? 0 : 1,
                other,
            };
            const b = coords[other];
            if (a && b) {
                const pts = arc([a.lng, a.lat], [b.lng, b.lat]);
                if (pts.length) geo.push({ ...base, pts });
            } else if (a && !b && nongeo.some((n) => n.id === other)) {
                const pts = dockArcPts(a.lng, a.lat, other);
                if (pts.length) dockArcs.push({ ...base, pts });
            }
        }
        return { geo, dockArcs };
    };

    /**
     * ★ A dock counterpart has NO coordinate, by design — OPEC, US_Treasuries and the rest are
     *   not places. An arc cannot reach the chip, because the chip is DOM and the arc is drawn in
     *   the GL canvas, and inventing a lng/lat for it is exactly the fabrication the isolation
     *   contract exists to prevent.
     *
     *   What is drawn instead: the chip's own screen x is read from the live DOM, a point on the
     *   canvas's BOTTOM EDGE at that x is turned back into a lng/lat with map.unproject(), and the
     *   arc runs to there and fades out (line-gradient, see the rv-arcs-dock layer). So the arc
     *   points AT the chip and stops at the map's edge instead of pretending to land somewhere.
     *   The chip is lit at the same time, which is what actually identifies the counterpart.
     *
     *   Because this endpoint is screen-derived it is INVALID the moment the camera moves, so it
     *   is recomputed on 'move' (cheap — only dock arcs, and only while something is selected).
     *   A chip hidden behind "+N more" has no box; the dock's horizontal centre is used instead.
     */
    const dockArcPts = (lng: number, lat: number, other: string): [number, number][] => {
        if (dead()) return [];
        const cv = map.getCanvas();
        const cb = cv.getBoundingClientRect();
        if (!cb.width || !cb.height) return [];
        const el = dock.querySelector(`[data-goto="${CSS.escape(other)}"]`) as HTMLElement | null;
        const r = el?.getBoundingClientRect();
        const x = r && r.width
            ? Math.max(2, Math.min(cb.width - 2, r.left + r.width / 2 - cb.left))
            : cb.width / 2;
        let end: [number, number];
        try {
            const ll = map.unproject([x, cb.height - 2]);
            if (!Number.isFinite(ll.lng) || !Number.isFinite(ll.lat)) return [];
            end = [ll.lng, ll.lat];
        } catch { return []; }
        // Gentler bow than a geographic arc: this one is a pointer, not a route.
        return arc([lng, lat], end, 0.05, Math.round(ARC_POINTS / 2));
    };

    const arcFC = (list: Arc[], frac: number) => ({
        type: 'FeatureCollection' as const,
        features: list.flatMap((a) => {
            const pts = arcProgress(a.pts, frac);
            if (pts.length < 2) return [];
            return [{
                type: 'Feature' as const,
                geometry: { type: 'LineString' as const, coordinates: pts },
                properties: { etype: a.etype, color: a.color, dim: a.dim, w: a.w },
            }];
        }),
    });

    let arcs: { geo: Arc[]; dockArcs: Arc[] } = { geo: [], dockArcs: [] };
    let raf: number | null = null;

    const setArcData = (frac: number) => {
        (map.getSource('rv-arcs') as any)?.setData(arcFC(arcs.geo, frac));
        (map.getSource('rv-arcs-dock') as any)?.setData(arcFC(arcs.dockArcs, frac));
    };

    const stopAnim = () => { if (raf !== null) cancelAnimationFrame(raf); raf = null; };

    /** Ego-node pulse: one expanding ring, PULSE_MS, fired when the arcs land. */
    const pulseFC = () => ({
        type: 'FeatureCollection' as const,
        features: !selected ? [] : [selected, ...arcs.geo.map((a) => a.other)]
            .filter((id, i, xs) => coords[id] && xs.indexOf(id) === i)
            .map((id) => ({
                type: 'Feature' as const,
                geometry: { type: 'Point' as const, coordinates: [coords[id].lng, coords[id].lat] },
                properties: { id },
            })),
    });

    const runPulse = () => {
        if (dead()) return;
        (map.getSource('rv-pulse') as any)?.setData(pulseFC());
        const t0p = performance.now();
        const step = () => {
            if (dead()) { raf = null; return; }
            const q = Math.min(1, (performance.now() - t0p) / PULSE_MS);
            const e = easeOutCubic(q);
            try {
                map.setPaintProperty('rv-pulse', 'circle-radius', 3 + 22 * e);
                map.setPaintProperty('rv-pulse', 'circle-stroke-opacity', 0.6 * (1 - e));
            } catch { /* layer gone — nothing to pulse */ }
            if (q < 1) { raf = requestAnimationFrame(step); return; }
            raf = null;
            (map.getSource('rv-pulse') as any)?.setData(EMPTY);   // one pulse, then gone
        };
        raf = requestAnimationFrame(step);
    };

    /** Draw the selection's arcs outward over ARC_MS. fitEgo() has already run, so the spread
     *  happens inside the final viewport rather than under a camera that is still moving. */
    const spread = () => {
        stopAnim();
        if (dead()) return;
        (map.getSource('rv-pulse') as any)?.setData(EMPTY);
        arcs = buildArcs();
        const drawn = arcs.geo.length + arcs.dockArcs.length;
        if (selected && totalEdges > drawn) {
            note.textContent = `${drawn} of ${totalEdges} connections drawn — see the list for all of them`;
            note.hidden = false;
        } else {
            note.hidden = true;
        }
        if (!drawn) { setArcData(1); return; }
        const t0a = performance.now();
        const step = () => {
            if (dead()) { raf = null; return; }
            const q = Math.min(1, (performance.now() - t0a) / ARC_MS);
            setArcData(easeOutCubic(q));
            if (q < 1) { raf = requestAnimationFrame(step); return; }
            raf = null;
            runPulse();
        };
        raf = requestAnimationFrame(step);
    };

    /** Deselect clears immediately — no reverse animation. */
    const clearArcs = () => {
        stopAnim();
        arcs = { geo: [], dockArcs: [] };
        totalEdges = 0;
        note.hidden = true;
        if (dead()) return;
        (map.getSource('rv-arcs') as any)?.setData(EMPTY);
        (map.getSource('rv-arcs-dock') as any)?.setData(EMPTY);
        (map.getSource('rv-pulse') as any)?.setData(EMPTY);
    };

    /** Points + chips only. Arcs are animated separately and must NOT be reset from here. */
    const refresh = () => {
        if (dead()) return;
        (map.getSource('rv-nodes') as any)?.setData(pointFC());
        const drawn = new Set(arcs.dockArcs.map((a) => a.other));
        for (const el of Array.from(dock.querySelectorAll('.rv-chip-n'))) {
            const id = (el as HTMLElement).dataset.goto!;
            const lit = !selected || id === selected || (adj.get(selected)?.has(id) ?? false);
            (el as HTMLElement).dataset.lit = lit ? '1' : '0';
            // data-arc marks the chips an arc actually points at, which is a strictly smaller set
            // than data-lit: a counterpart is lit whenever it is adjacent, but only gets an arc if
            // it survived MAX_ARCS.
            (el as HTMLElement).dataset.arc = drawn.has(id) ? '1' : '0';
        }
    };

    /**
     * The one place selection changes. Order matters and is the point of the function:
     * fit FIRST (step 4 — otherwise the arcs animate under a camera that is still moving and the
     * spread is half off-screen), then build + draw. `fit` is false for a click on the map itself,
     * where the node is already in view and re-framing would yank it away under the cursor.
     */
    const applySelection = (id: string | null, fit: boolean) => {
        selected = id;
        if (!id) { clearArcs(); refresh(); return; }
        if (fit) fitEgo(id);
        spread();
        refresh();          // after spread(), so data-arc reflects the arcs just built
    };

    map.on('load', () => {
        // ── Arcs: ONE source, TWO layers (glow under core) ────────────────────────────────
        // Colour is the COUNTERPART's type colour, so a fan of arcs reads as "what kinds of thing
        // is this connected to" at a glance. `dim` thins and fades competitor edges. `w` is the
        // vault's three-weight-state distinction collapsed to present/absent: an edge the vault
        // left unweighted is drawn hairline, never as a weak-but-measured one — the same refusal
        // the legacy map makes with its separate grey unquantified arc layer
        // (pro_interactive_map.ts:497-519).
        map.addSource('rv-arcs', { type: 'geojson', data: EMPTY });
        map.addLayer({
            id: 'rv-arcs-glow', type: 'line', source: 'rv-arcs',
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: {
                'line-color': ['get', 'color'],
                'line-width': ['case', ['==', ['get', 'dim'], 1], 4.0, 6.5],
                'line-opacity': ['case', ['==', ['get', 'dim'], 1], 0.07, 0.16],
                'line-blur': 3.5,
            },
        });

        // ── Dock arcs: their own source, because a fade NEEDS line-gradient ───────────────
        // ★ line-gradient is the only paint property that can read ['line-progress'], and it is
        //   NOT data-driven — no ['get','color'] inside it — so it has to be one colour for the
        //   whole layer, hence a separate source and a neutral slate. The counterpart's colour is
        //   carried by the lit chip instead. lineMetrics:true is what makes line-progress exist;
        //   without it the gradient is silently ignored and the arc draws at flat opacity.
        map.addSource('rv-arcs-dock', { type: 'geojson', data: EMPTY, lineMetrics: true });
        map.addLayer({
            id: 'rv-arcs-dock', type: 'line', source: 'rv-arcs-dock',
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: {
                'line-width': 1.4,
                'line-gradient': [
                    'interpolate', ['linear'], ['line-progress'],
                    0, 'rgba(148,163,184,0.75)',
                    0.55, 'rgba(148,163,184,0.38)',
                    1, 'rgba(148,163,184,0)',
                ],
            },
        });

        map.addLayer({
            id: 'rv-arcs-core', type: 'line', source: 'rv-arcs',
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: {
                'line-color': ['get', 'color'],
                'line-width': [
                    'case',
                    ['==', ['get', 'w'], 0], 0.8,
                    ['==', ['get', 'dim'], 1], 1.1,
                    1.5,
                ],
                'line-opacity': ['case', ['==', ['get', 'dim'], 1], 0.34, 0.85],
            },
        });

        // Arrival pulse. Radius and stroke opacity are driven per frame by setPaintProperty from
        // runPulse(); the values here are only the resting state before the first pulse.
        map.addSource('rv-pulse', { type: 'geojson', data: EMPTY });
        map.addLayer({
            id: 'rv-pulse', type: 'circle', source: 'rv-pulse',
            paint: {
                'circle-radius': 3, 'circle-color': 'rgba(0,0,0,0)',
                'circle-stroke-width': 1.4, 'circle-stroke-color': '#e2e8f0',
                'circle-stroke-opacity': 0,
            },
        });
        map.addSource('rv-nodes', { type: 'geojson', data: pointFC() });
        map.addLayer({
            id: 'rv-nodes', type: 'circle', source: 'rv-nodes',
            paint: {
                'circle-radius': ['*', ['get', 'radius'], 1.1],
                // countries render as rings: a different kind of thing, not a bigger one
                'circle-color': ['case', ['==', ['get', 'ring'], 1], 'rgba(0,0,0,0)', ['get', 'color']],
                'circle-opacity': ['get', 'alpha'],
                'circle-stroke-width': ['case', ['==', ['get', 'sel'], 1], 2.4, ['==', ['get', 'ring'], 1], 1.6, 0],
                'circle-stroke-color': ['case', ['==', ['get', 'sel'], 1], '#f1f5f9', ['get', 'color']],
                'circle-stroke-opacity': ['get', 'alpha'],
            },
        });
        map.addLayer({
            id: 'rv-labels', type: 'symbol', source: 'rv-nodes',
            layout: {
                'text-field': ['get', 'label'], 'text-size': 10, 'text-offset': [0, 1.1],
                'text-anchor': 'top', 'text-allow-overlap': false,
            },
            paint: { 'text-color': '#cbd5e1', 'text-opacity': ['get', 'alpha'], 'text-halo-color': '#020610', 'text-halo-width': 1.2 },
        });

        const pop = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: 'rv-globe-pop' });
        map.on('mousemove', 'rv-nodes', (ev) => {
            map.getCanvas().style.cursor = 'pointer';
            const f = ev.features?.[0]; if (!f) return;
            const p: any = f.properties;
            pop.setLngLat(ev.lngLat).setHTML(`<b>${p.label}</b><br>${[p.ntype, byId.get(p.id)?.country].filter(Boolean).join(' · ')}`).addTo(map);
        });
        map.on('mouseleave', 'rv-nodes', () => { map.getCanvas().style.cursor = ''; pop.remove(); });
        map.on('click', 'rv-nodes', (ev) => {
            const id = (ev.features?.[0]?.properties as any)?.id as string | undefined;
            if (!id) return;
            applySelection(id, false); onSelect(id);
        });
        map.on('click', (ev) => {
            const hit = map.queryRenderedFeatures(ev.point, { layers: ['rv-nodes'] });
            if (!hit.length && selected) { applySelection(null, false); onSelect(null); }
        });
        renderDock();
        // ★ Initial framing here, not in the constructor. Fewer than two placeable nodes gives a
        //   degenerate bounds, so keep the fixed view in that case rather than fitting to a point.
        if (placeable.length >= 2 && !dead()) {
            try {
                map.fitBounds(geoBounds(), {
                    padding: { top: 48, bottom: 110, left: 48, right: 48 }, maxZoom: 4, duration: 0,
                });
            } catch (err) {
                // eslint-disable-next-line no-console
                console.warn('[relationship_globe] initial fitBounds failed; keeping the default view', err);
            }
        }
        mountedMs = performance.now() - t0;
        /* eslint-disable no-console */
        console.log(`[relationship_globe] ${geo.length} geo nodes (${placeable.length} placeable) · ${nongeo.length} dock chips · ${edges.length} edges · mount ${mountedMs.toFixed(0)}ms`);
        /* eslint-enable no-console */
        refresh();
        // ★ A selection can arrive BEFORE 'load' — the view calls focus()/select() as soon as
        //   mountGlobe returns, and until the style is loaded there are no sources to write, so
        //   spread()'s setData calls no-op through `?.` and the arcs are simply lost. Replay here.
        if (selected) spread();
    });

    dock.addEventListener('click', (ev) => {
        const more = (ev.target as HTMLElement).closest('[data-more]') as HTMLElement | null;
        if (more) { dock.dataset.expanded = more.dataset.more!; renderDock(); return; }
        const el = (ev.target as HTMLElement).closest('[data-goto]') as HTMLElement | null;
        if (!el) return;
        applySelection(el.dataset.goto!, true); onSelect(selected);
    });

    const fitEgo = (id: string) => {
        if (dead()) return;
        const ids = finiteCoords([id, ...(adj.get(id) || [])]);
        if (ids.length < 1) return;                  // dock-only entity: nothing geographic to fit
        const b = new maplibregl.LngLatBounds();
        for (const x of ids) b.extend([coords[x].lng, coords[x].lat]);
        // ★ duration 0, not 500. Step 4 requires the ego set to be FRAMED BEFORE the arcs
        //   animate; a 500ms camera ease overlapping a 600ms spread draws most of the fan
        //   off-screen and then slides it in, which looks like a bug. The alternative —
        //   keep the ease and start the spread on 'moveend' — needs a timeout fallback because
        //   moveend does not fire if the camera was already at the target. A snap to the
        //   neighbourhood followed by the spread is both simpler and clearer about cause.
        map.fitBounds(b, { padding: { top: 60, bottom: 90, left: 60, right: 420 }, maxZoom: 5, duration: 0 });
    };

    // ★ MapLibre sizes itself from the container at construction. The host is a grid cell that
    //   may not have resolved yet, and the overlay drawer changes the visible area without
    //   changing the container, so resize() is called after mount, from a ResizeObserver, and by
    //   the view whenever the drawer opens or closes.
    const ro = new ResizeObserver(() => safeResize());
    ro.observe(host);
    requestAnimationFrame(() => safeResize());

    /** A dock arc's far end is a SCREEN position turned into a lng/lat, so panning or zooming
     *  invalidates it — left alone it drifts away from the chip it is supposed to point at.
     *  Recomputed on every camera move, but skipped while the spread is mid-flight so the two
     *  do not write the same source in the same frame. Geographic arcs need none of this. */
    map.on('move', () => {
        if (dead() || raf !== null || !selected || !arcs.dockArcs.length) return;
        const a = coords[selected];
        if (!a) return;
        arcs.dockArcs = arcs.dockArcs
            .map((d) => ({ ...d, pts: dockArcPts(a.lng, a.lat, d.other) }))
            .filter((d) => d.pts.length >= 2);
        (map.getSource('rv-arcs-dock') as any)?.setData(arcFC(arcs.dockArcs, 1));
    });

    const refit = () => {
        if (dead() || placeable.length < 2) return;
        try {
            map.fitBounds(geoBounds(), {
                padding: { top: 48, bottom: 110, left: 48, right: 48 }, maxZoom: 4, duration: 0,
            });
        } catch { /* keep the current view */ }
    };

    return {
        select(id) { applySelection(id, false); },
        focus(id) { applySelection(id, true); },
        resize() { safeResize(); },
        /** Re-frame after the host has actually been laid out at its final width. */
        refit() { safeResize(); refit(); },
        destroy() {
            stopAnim(); note.remove();        // a live rAF outliving the map would call setPaintProperty on a
                               // removed layer every frame; dead() guards it, but not leaking the
                               // frame loop at all is the actual fix.
            ro.disconnect(); if (!dead()) map.remove(); mapEl.remove(); dock.remove();
        },
    };
}
