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
// Pure math, no imports of its own. greatCircleAt is the legacy particle-position function;
// easeOutCubic drives the opacity fade and the pulse.
import { greatCircleAt, easeOutCubic } from './relationship_arcs';
// ★ deck.gl is a LIBRARY, not the legacy module. These are the same packages the legacy map
//   loads (pro_interactive_map.ts:970-972, :987) and they carry none of its code: no scenario
//   payload and none of the derived per-node fields the contract block above names. The legacy
//   MODULES stay forbidden, and the isolation check now rejects dynamic import() too, so this
//   allowlist cannot be walked around with `await import(...)` the way the legacy map loads deck.
//   (Written without those field names on purpose — the check scans this file for them, and it
//   caught this very comment when it did name one. The exemption covers the contract block only,
//   which is the right size for it.)
import { ArcLayer, ScatterplotLayer } from '@deck.gl/layers';
import { MapboxOverlay } from '@deck.gl/mapbox';

export type GlobeNode = { id: string; type?: string | null; country?: string | null };
export type GlobeEdge = { s: string; t: string; type: string; weight?: number | null };
type Coord = { lat: number; lng: number; type?: string; city?: string };

/** Same basemap as the Pro map — CARTO dark-matter, no token. */
export const BASEMAP = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

const DEFAULT_COLOR = '#64748b';

/** Arcs fade in over ARC_MS. The GEOMETRY is deck.gl's (greatCircle in a shader); only the
 *  layer opacity is tweened, so nothing is ever drawn half-built. */
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
    /**
     * The dock's own headline for the current selection. NO line is ever drawn to these
     * counterparts — they have no coordinate by design, and a line to an invented point is the
     * fabrication the isolation contract exists to stop. The chip IS the edge.
     *
     * ★ "N relationships" is EDGES, and edges do not match chips. Measured on the committed
     *   graph: 29 ordered pairs are joined by more than one edge, and for 16 nodes the
     *   non-geographic edge count differs from the number of distinct counterparts — Kuwait has
     *   2 non-geographic relationships but only 1 chip to light, TSMC 10 across 8. Printing the
     *   edge count alone next to a smaller number of lit chips would look like a bug, so when the
     *   two differ the text says both.
     */
    const dockNote = (): string => {
        const n = dockEdgeCount, k = dockHits.length;
        if (!n) return '';
        if (n === k) return `${n} non-geographic relationship${n === 1 ? '' : 's'} — highlighted below`;
        return `${n} non-geographic relationships across ${k} entit${k === 1 ? 'y' : 'ies'}`
            + ' — highlighted below';
    };

    const renderDock = () => {
        const expanded = dock.dataset.expanded === '1';
        const shown = expanded ? ranked : ranked.slice(0, CHIPS_COLLAPSED);
        const rest = ranked.length - shown.length;
        const head = dockNote();
        dock.innerHTML = (head ? `<span class="rv-dock-note">${head}</span>` : '')
            + `<span class="rv-dock-l">Non-geographic</span>`
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
        attributionControl: false,
        // ★ `dragRotate: false` used to sit here, and it was the whole reason right-drag and
        //   ctrl-drag did nothing: DragRotateHandler owns rotate, and pitchWithRotate rides on
        //   the same handler, so one false killed BOTH rotate and pitch.
        //
        //   The legacy map sets NONE of these options — grep finds no dragPan, dragRotate,
        //   pitchWithRotate, touchZoomRotate, keyboard or maxPitch in pro_interactive_map.ts. It
        //   takes MapLibre's defaults, so "match the legacy maxPitch" means 60, the 4.7.1 default
        //   (one `maxPitch:60` literal in the dist bundle). Everything here except dragRotate was
        //   therefore already on by default; they are written out explicitly so the next person
        //   does not have to prove that by grepping a minified bundle.
        dragPan: true,
        dragRotate: true,
        pitchWithRotate: true,
        touchZoomRotate: true,
        touchPitch: true,
        keyboard: true,
        scrollZoom: true,
        doubleClickZoom: true,
        maxPitch: 60,
        // ★ Required for deck.gl's interleaved mode — it fixes the WebGL2 context attributes the
        //   overlay needs. The legacy map sets it for the same reason (:1034).
        antialias: true,
    });
    const dead = () => !map || (map as any)._removed === true;
    const safeResize = () => { if (!dead()) map.resize(); };
    // showCompass is on now that rotation works: without it there is no way back to north
    // after a ctrl-drag, and pitch makes a lost bearing easy to acquire.
    map.addControl(new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }), 'top-right');

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
    // Arcs — deck.gl ArcLayer on this MapLibre map, via MapboxOverlay(interleaved:true)
    //
    // Replaces a hand-rolled GeoJSON polyline + progressive point-count draw. That version had
    // to re-derive a bow (deck.gl's getHeight is a 3-D lift with no 2-D equivalent) and to
    // unwrap longitudes by hand across the antimeridian. Both problems belong to the shader, and
    // handing them back to it deletes the code that solved them.
    // ──────────────────────────────────────────────────────────────────────────────────────────
    type ArcEdge = {
        slon: number; slat: number; tlon: number; tlat: number;
        src: [number, number, number, number];
        tgt: [number, number, number, number];
        width: number;
        other: string;
    };
    const EMPTY = { type: 'FeatureCollection' as const, features: [] as any[] };

    /** '#38bdf8' -> [56,189,248,a]. deck.gl wants RGBA arrays; PALETTE holds CSS hex. */
    const rgba = (hex: string, a: number): [number, number, number, number] => {
        const h = hex.replace('#', '');
        const v = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
        const i = parseInt(v, 16);
        return Number.isFinite(i) ? [(i >> 16) & 255, (i >> 8) & 255, i & 255, a] : [100, 116, 139, a];
    };

    /** Which arcs survive MAX_ARCS. Lower sorts first, i.e. is kept.
     *  ★ A weighted non-competitor edge outranks an unweighted one, but the WEIGHT ITSELF is not
     *    a ranking key beyond present/absent. Ranking by magnitude would quietly make the cap a
     *    statement about which dependencies matter most, and this view's weights are
     *    within-hub-relative and 425-of-546 estimated (vault CLAUDE.md sections 3 and 4) — not a
     *    cross-hub ordering. Ties fall back to the counterpart id so the kept set is stable
     *    across renders instead of following array order. */
    const arcPriority = (e: GlobeEdge, other: string): [number, number, string] =>
        [DIM_TYPES.has(e.type) ? 1 : 0, e.weight == null ? 1 : 0, other];

    let arcEdges: ArcEdge[] = [];
    /** Non-geographic counterparts of the current selection. NO line is drawn to these — see
     *  renderDock(). They have no coordinate by design and inventing one is the fabrication the
     *  isolation contract exists to stop. */
    let dockHits: string[] = [];
    let dockEdgeCount = 0;
    let totalEdges = 0;

    const buildArcs = () => {
        arcEdges = []; dockHits = []; dockEdgeCount = 0; totalEdges = 0;
        if (!selected) return;
        const a = coords[selected];
        const selColor = PALETTE[byId.get(selected)?.type || ''] || DEFAULT_COLOR;

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

        const seenDock = new Set<string>();
        for (const { e, other } of cand) {
            const b = coords[other];
            if (!b || !a) {
                // Non-geographic (or an endpoint we cannot place): chip only, never a line.
                if (byId.has(other)) {
                    dockEdgeCount++;
                    if (!seenDock.has(other)) { seenDock.add(other); dockHits.push(other); }
                }
                continue;
            }
            if (arcEdges.length >= MAX_ARCS) continue;
            const dim = DIM_TYPES.has(e.type);
            arcEdges.push({
                slon: a.lng, slat: a.lat, tlon: b.lng, tlat: b.lat,
                src: rgba(selColor, dim ? 70 : 200),
                tgt: rgba(PALETTE[byId.get(other)?.type || ''] || DEFAULT_COLOR, dim ? 70 : 160),
                width: e.weight == null ? 1.5 : 3,
                other,
            });
        }
    };

    // ── deck.gl overlay ────────────────────────────────────────────────────────────────────
    // ★ interleaved:true makes deck.gl share MapLibre's WebGL2 context: _onAddInterleaved()
    //   reads map.painter.context.gl and registers each deck layer as a MapLibre CustomLayer.
    //   That requires map.painter to exist, so the overlay is added in 'load' — and it requires
    //   `antialias: true` on the Map constructor for the right context attributes, which is why
    //   the legacy map sets it at :1034 and why this one now does too.
    const overlay: any = new MapboxOverlay({ interleaved: true, layers: [] });
    let overlayAdded = false;

    let arcOpacity = 0;      // 0..1, tweened over ARC_MS
    let cometPhase = 0;      // 0..1, one lap every 4s — the legacy's animationPhase
    let raf: number | null = null;
    let lastFrame = 0;
    let fadeStart = 0;

    /**
     * ★ COMET PARTICLES — ported, and the port has a known flaw that the legacy shares.
     *
     *   The arithmetic is copied from pro_interactive_map.ts:3068-3087 (pushStaticTracers):
     *   per-edge phase offset (i*0.17)%1 from :1638, TAIL=7, TAIL_SPAN=0.16, alpha 235*f*f,
     *   radius 1200+2800*f, and an arrival bloom over the last BLOOM_W=0.14 of the loop at
     *   radius 16000+30000*p, alpha 200*(1-p). Positions come from greatCircleAt, which is
     *   itself the legacy function. Nothing is imported from the legacy module: every value here
     *   is a literal and the only call is to our own pure copy.
     *
     *   ★ THE FLAW: greatCircleAt returns GROUND-LEVEL lng/lat, while the ArcLayer above draws
     *   with getHeight 0.45 — a 3-D lift. The comets therefore ride the ground TRACK, not the
     *   lifted arc, and at the pitch:50 this view now fits to, they visibly run below their own
     *   arc. This is not a porting mistake: the legacy map has exactly the same offset, because
     *   its ScatterplotLayer particles are unelevated too and its own comment ("ride exactly on
     *   top of the rendered arc geometry") is only true in plan view. Closing it needs an
     *   elevation model deck.gl does not expose from ArcLayer, so it is left as-is and recorded
     *   here rather than silently inherited.
     */
    const TAIL = 7;
    const TAIL_SPAN = 0.16;
    const BLOOM_W = 0.14;
    const comets = () => {
        const dots: Array<{ p: [number, number]; head: number; alpha: number; size: number }> = [];
        const blooms: Array<{ p: [number, number]; radius: number; alpha: number }> = [];
        for (let i = 0; i < arcEdges.length; i++) {
            const e = arcEdges[i];
            const head = (cometPhase + ((i * 0.17) % 1)) % 1;
            for (let k = 0; k < TAIL; k++) {
                const t = head - (k / (TAIL - 1)) * TAIL_SPAN;
                if (t < 0) continue;
                const f = 1 - k / TAIL;
                dots.push({
                    p: greatCircleAt(e.slon, e.slat, e.tlon, e.tlat, t),
                    head: k === 0 ? 1 : 0,
                    alpha: Math.round(235 * f * f),
                    size: 1_200 + 2_800 * f,
                });
            }
            if (head >= 1 - BLOOM_W) {
                const q = (head - (1 - BLOOM_W)) / BLOOM_W;
                blooms.push({ p: [e.tlon, e.tlat], radius: 16_000 + 30_000 * q, alpha: Math.round(200 * (1 - q)) });
            }
        }
        return { dots, blooms };
    };

    const deckLayers = (): any[] => {
        if (!arcEdges.length || arcOpacity <= 0) return [];
        const { dots, blooms } = comets();
        return [
            new ArcLayer({
                id: 'rv-arc',
                data: arcEdges,
                pickable: false,
                getSourcePosition: (d: ArcEdge) => [d.slon, d.slat],
                getTargetPosition: (d: ArcEdge) => [d.tlon, d.tlat],
                getSourceColor: (d: ArcEdge) => d.src,
                getTargetColor: (d: ArcEdge) => d.tgt,
                getWidth: (d: ArcEdge) => d.width,
                widthMinPixels: 1,
                widthMaxPixels: 6,
                greatCircle: true,
                getHeight: 0.45,
                numSegments: 64,
                opacity: arcOpacity,
            }),
            new ScatterplotLayer({
                id: 'rv-arc-comet',
                data: dots,
                pickable: false, stroked: false, filled: true,
                radiusUnits: 'meters', radiusMinPixels: 0.8, radiusMaxPixels: 2.5,
                getPosition: (d: any) => d.p,
                getRadius: (d: any) => d.size,
                getFillColor: (d: any) => (d.head ? [190, 250, 255, 255] : [0, 210, 255, d.alpha]),
                parameters: { depthTest: false },
                opacity: arcOpacity,
                updateTriggers: { getPosition: cometPhase, getFillColor: cometPhase, getRadius: cometPhase },
            }),
            new ScatterplotLayer({
                id: 'rv-arc-bloom',
                data: blooms,
                pickable: false, stroked: true, filled: false,
                radiusUnits: 'meters',
                getPosition: (d: any) => d.p,
                getRadius: (d: any) => d.radius,
                getLineColor: (d: any) => [190, 250, 255, d.alpha],
                lineWidthMinPixels: 1,
                parameters: { depthTest: false },
                opacity: arcOpacity,
                updateTriggers: { getRadius: cometPhase, getLineColor: cometPhase },
            }),
        ];
    };

    const pushDeck = () => { if (!dead() && overlayAdded) overlay.setProps({ layers: deckLayers() }); };
    const stopAnim = () => { if (raf !== null) cancelAnimationFrame(raf); raf = null; };

    /** Ego-node pulse: one expanding ring, PULSE_MS, fired when the fade-in completes. */
    const pulseFC = () => ({
        type: 'FeatureCollection' as const,
        features: !selected ? [] : [selected, ...arcEdges.map((a) => a.other)]
            .filter((id, i, xs) => coords[id] && xs.indexOf(id) === i)
            .map((id) => ({
                type: 'Feature' as const,
                geometry: { type: 'Point' as const, coordinates: [coords[id].lng, coords[id].lat] },
                properties: { id },
            })),
    });

    /**
     * One rAF loop for both animations. The opacity tween runs once over ARC_MS; the comet phase
     * keeps advancing at the legacy's rate (dt*0.25, i.e. one lap every 4s) for as long as a
     * selection has arcs. With nothing selected the loop stops entirely — the legacy's runs
     * unconditionally, which is wasted work on a view where arcs only exist during a selection.
     */
    const frame = () => {
        if (dead()) { raf = null; return; }
        const now = performance.now();
        const dt = lastFrame ? Math.max(0, now - lastFrame) / 1000 : 0;
        lastFrame = now;
        cometPhase = (cometPhase + dt * 0.25) % 1;

        if (arcOpacity < 1) {
            const q = Math.min(1, (now - fadeStart) / ARC_MS);
            arcOpacity = easeOutCubic(q);
            if (q >= 1) { arcOpacity = 1; runPulse(); }
        }
        pushDeck();
        raf = arcEdges.length ? requestAnimationFrame(frame) : null;
    };

    /** Arrival pulse — a MapLibre circle layer, deliberately not a deck layer: it is tied to the
     *  node positions the basemap already carries, and keeping it off the overlay means it
     *  survives any deck failure. */
    const runPulse = () => {
        if (dead()) return;
        (map.getSource('rv-pulse') as any)?.setData(pulseFC());
        const t0p = performance.now();
        const step = () => {
            if (dead()) return;
            const q = Math.min(1, (performance.now() - t0p) / PULSE_MS);
            const e = easeOutCubic(q);
            try {
                map.setPaintProperty('rv-pulse', 'circle-radius', 3 + 22 * e);
                map.setPaintProperty('rv-pulse', 'circle-stroke-opacity', 0.6 * (1 - e));
            } catch { /* layer gone — nothing to pulse */ }
            if (q < 1) { requestAnimationFrame(step); return; }
            (map.getSource('rv-pulse') as any)?.setData(EMPTY);   // one pulse, then gone
        };
        requestAnimationFrame(step);
    };

    /** Build this selection's arcs and fade them in. fitEgo() has already moved the camera. */
    const spread = () => {
        stopAnim();
        if (dead()) return;
        (map.getSource('rv-pulse') as any)?.setData(EMPTY);
        buildArcs();
        const drawn = arcEdges.length;
        if (selected && totalEdges > drawn + dockEdgeCount) {
            note.textContent = `${drawn} of ${totalEdges - dockEdgeCount} geographic connections drawn`
                + ' — see the list for all of them';
            note.hidden = false;
        } else {
            note.hidden = true;
        }
        arcOpacity = 0;
        if (!drawn) { pushDeck(); return; }
        fadeStart = performance.now();
        lastFrame = 0;
        raf = requestAnimationFrame(frame);
    };

    /** Deselect clears immediately — no reverse animation. */
    const clearArcs = () => {
        stopAnim();
        arcEdges = []; dockHits = []; dockEdgeCount = 0; totalEdges = 0; arcOpacity = 0;
        note.hidden = true;
        if (dead()) return;
        pushDeck();
        (map.getSource('rv-pulse') as any)?.setData(EMPTY);
    };

    /** Points + chips only. Arcs are animated separately and must NOT be reset from here. */
    const refresh = () => {
        if (dead()) return;
        (map.getSource('rv-nodes') as any)?.setData(pointFC());
        const drawn = new Set(dockHits);
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
        if (!id) { clearArcs(); renderDock(); return; }
        if (fit) fitEgo(id);
        spread();
        // renderDock(), not refresh(): the dock's headline is part of the selection now, and
        // renderDock() calls refresh() itself to re-apply data-lit / data-arc to the new chips.
        renderDock();
    };

    map.on('load', () => {
        // ── deck.gl overlay ──────────────────────────────────────────────────────────────
        // addControl -> overlay.onAdd(map) -> _onAddInterleaved(map), which needs map.painter,
        // hence 'load' and not the constructor. Guarded: a deck failure must cost the arcs, not
        // the whole globe — the nodes, labels, dock and pulse are all plain MapLibre below.
        try {
            map.addControl(overlay);
            overlayAdded = true;
        } catch (err) {
            // eslint-disable-next-line no-console
            console.error('[relationship_globe] deck.gl overlay failed; nodes still render', err);
        }

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
        // ★ The legacy static-cascade fit, verbatim from pro_interactive_map.ts:1181-1183:
        //   pitch 50, bearing 0, duration 900. Its comment explains the tilt — "the static
        //   cascade opens tilted so the raised arcs read as curves over the surface" — which is
        //   exactly why it matters here: ArcLayer's getHeight 0.45 lift is INVISIBLE in plan
        //   view, so a flat camera would render these arcs as straight chords and throw away the
        //   whole point of using it.
        //
        //   duration 900 overlaps the 600 ms arc fade on purpose. The previous version snapped
        //   (duration 0) because a geometric draw-outward would have been half off-screen under a
        //   moving camera; an OPACITY fade has no such problem — nothing is drawn in the wrong
        //   place, it is only drawn faintly — so the camera ease and the fade can run together
        //   and read as one event.
        map.fitBounds(b, {
            padding: { top: 60, bottom: 90, left: 60, right: 420 },
            maxZoom: 5, pitch: 50, bearing: 0, duration: 900,
        });
    };

    // ★ MapLibre sizes itself from the container at construction. The host is a grid cell that
    //   may not have resolved yet, and the overlay drawer changes the visible area without
    //   changing the container, so resize() is called after mount, from a ResizeObserver, and by
    //   the view whenever the drawer opens or closes.
    const ro = new ResizeObserver(() => safeResize());
    ro.observe(host);
    requestAnimationFrame(() => safeResize());

    // ★ The 'move' handler that used to live here is gone with the dock arcs. It recomputed a
    //   screen-derived endpoint and called setData on EVERY move event, i.e. once per frame of a
    //   pan — real jank on a gesture that is now supposed to feel free. Geographic arcs need
    //   nothing of the kind: deck.gl re-projects them from lng/lat itself.

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
            stopAnim(); note.remove();
            // The overlay holds a GL context reference; map.remove() tears it down, but dropping
            // the layers first stops any in-flight deck render from touching a dying context.
            try { if (overlayAdded) overlay.setProps({ layers: [] }); } catch { /* already gone */ }        // a live rAF outliving the map would call setPaintProperty on a
                               // removed layer every frame; dead() guards it, but not leaking the
                               // frame loop at all is the actual fix.
            ro.disconnect(); if (!dead()) map.remove(); mapEl.remove(); dock.remove();
        },
    };
}
