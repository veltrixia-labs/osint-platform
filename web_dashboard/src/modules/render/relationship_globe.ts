/**
 * Globe mode for the relationship view — the same graph, placed geographically.
 *
 * ★★ ISOLATION CONTRACT — read before adding an import.
 *
 *   This module may import ONLY: maplibre-gl, and types from relationship_graph_canvas.
 *   It must NEVER import from, or read, any of the chokepoint-scenario apparatus:
 *     • the five scenario payloads (strait_of_hormuz.json &c.) or /pro/domains/* routes
 *     • the impact_roster_rows / impact_roster_loads tables (the Impact Roster feature and its
 *       /pro/impact-roster routes were removed 2026-10-06, fd7aaf3; the tables remain, orphaned)
 *     • the spatial_nodes / spatial_edges / contagion_history tables
 *     • pro_interactive_map.ts, pro_trigger_map.ts
 *     • any node field named impact_score, raw_impact, order, confidence, intensity,
 *       viscosity_coefficient, entropy_index, is_epicenter
 *
 *   The reason is the vault's CLAUDE.md §5. A globe is exactly the surface where a coordinate
 *   turns a derived number into a published one. This view therefore carries coordinates and
 *   NOTHING else from the scenario side: position is presentation, and every edge drawn here is
 *   one the vault authored.
 *   (Comment corrected 2026-10-06.) This paragraph used to justify the contract with order-3 as
 *   live, an edge-less country×domain impact (country × DECAY 0.7) that put INPEX at −0.63 with
 *   no Hormuz edge. Both are stale. order-3 was removed from the payloads on 2026-10-05 (vault
 *   f2795b0), and INPEX was never promoted into the graph (it is HELD). The contract still stands:
 *   the scenario surface still carries derived, hub-relative numbers that must not reach a globe,
 *   and scripts/check-globe-isolation.mjs enforces it.
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

/**
 * ★ MARKER SIZE = DEGREE x ZOOM. Before this, `circle-radius` was
 *   `['*', ['get','radius'], 1.1]` over a per-feature `radius = 3 + log1p(degree) * 1.9` —
 *   degree-driven and completely ZOOM-INDEPENDENT, so a node was the same number of screen
 *   pixels at world view and street view. Europe, the US east coast and East Asia fused into
 *   blobs zoomed out, and markers stayed tiny relative to the map zoomed in.
 *
 *   MULTIPLIED, not added, so the degree ordering holds at EVERY zoom: a degree-132 node is
 *   12.29/3.00 = 4.1x a degree-0 node at world view and still 4.1x at street view. An additive
 *   zoom term would compress that ratio away as zoom rose.
 *
 * ★ ZOOM MUST BE THE TOP-LEVEL INPUT. Writing
 *     ['*', ['get','radius'], ['interpolate', ['linear'], ['zoom'], ...]]
 *   makes MapLibre REJECT THE WHOLE LAYER — 'circle-radius: "zoom" expression may only be used
 *   as input to a top-level "step" or "interpolate" expression' — addLayer throws and the rest
 *   of the load handler never runs. A zoom-and-property expression puts `interpolate` on `zoom`
 *   on the OUTSIDE and does the per-feature arithmetic INSIDE each stop, which is what this
 *   builder emits. Declarative so MapLibre evaluates it per frame on the GPU: no JS on move.
 */
const byZoom = (base: any, stops: Array<[number, number]>): any =>
    ['interpolate', ['linear'], ['zoom'],
        ...stops.flatMap(([z, f]) => [z, ['*', base, f]])];

const RADIUS_STOPS: Array<[number, number]> = [
    [0, 0.40],   // world view — a degree-0 node is 1.2px, dense clusters stay separable
    [2, 0.70],
    [4, 1.10],   // ~ the old fixed 1.1, so regional view is unchanged from before
    [6, 1.70],
    [9, 2.60],   // a degree-132 node is a 32px-radius click target
];
const STROKE_STOPS: Array<[number, number]> = [[0, 0.7], [4, 1.0], [9, 1.8]];

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
    /** Width (side drawer) or height (bottom sheet) the overlay drawer currently occupies, so
     *  fitEgo can keep the ego set clear of it. The VIEW owns the number and the breakpoint;
     *  this module only reads which edge it applies to. */
    setPanelOffset: (px: number) => void;
    select: (id: string | null) => void;
    focus: (id: string) => void;
    resize: () => void;
    refit: () => void;
    destroy: () => void;
};

/**
 * Reset-view button, as a MapLibre IControl so it joins the existing control group rather than
 * floating somewhere new — same surface, same border, same hit target as the zoom buttons.
 *
 * ★ WHAT "RESET" MEANS HERE: IT RE-FRAMES, IT NEVER CLEARS. With a node selected it re-runs
 *   fitEgo for that same node; with nothing selected it returns to the default world view. The
 *   selection, the drawer and the collapse state all survive untouched.
 *
 *   The alternative — reset also drops the selection and goes back to the world — was rejected
 *   as the more surprising of the two. A camera control that silently discards your selection
 *   makes you redo a search to get back, and the drawer already has an explicit × for exactly
 *   that. Keeping it to the camera also makes the label honest: "Reset view" is true of both
 *   branches, whereas anything implying "clear" would be a lie in the selected case.
 *
 * ★ ALWAYS ENABLED, deliberately. Disabling it at the reset state would mean comparing live
 *   centre/zoom/pitch/bearing against a target that is itself recomputed from the current
 *   coordinates every time, with tolerances on four axes. A stale disabled state is a dead
 *   control the user cannot diagnose; a reset that is momentarily a no-op costs nothing.
 */
class ResetViewControl {
    private _c!: HTMLDivElement;
    onAdd(_m: any) {
        this._c = document.createElement('div');
        this._c.className = 'maplibregl-ctrl maplibregl-ctrl-group';
        const b = document.createElement('button');
        b.type = 'button';
        // ★ NOT maplibregl-ctrl-icon. That class carries our `filter: invert(1)`, which exists
        //   to flip MapLibre's black SVGs light on a dark surface — and it inverted this icon's
        //   cyan --accent into red. Computed style said rgb(0,209,255) while the pixels said
        //   orange, which is the same class of trap as the emoji glyph this icon replaced.
        //   Our own icon needs none of MapLibre's icon styling; the group button rule already
        //   gives it size, border and hover.
        b.className = 'rv-ctrl-reset';
        b.title = 'Reset view';
        b.setAttribute('aria-label', 'Reset view');
        b.addEventListener('click', () => this.onReset?.());
        this._c.appendChild(b);
        return this._c;
    }
    onRemove() { this._c.parentNode?.removeChild(this._c); }
    /** Assigned by mountGlobe once resetView exists. */
    onReset?: () => void;
}

export function mountGlobe(
    host: HTMLElement,
    /** The dock's own strip BELOW the map — not inside it. See renderDock(). */
    dockHost: HTMLElement,
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
    //
    // ★ It lives in its OWN STRIP BELOW THE MAP, not as an overlay on it. As an overlay it was
    //   absolutely positioned across the full width of the bottom edge — 76px collapsed, 42vh
    //   expanded — which cost two things at once: it hid the southern hemisphere behind a
    //   gradient, and its wrapper box swallowed any mousedown landing between chips, so drags
    //   begun low on the globe went nowhere. Out of the map, both problems are structural
    //   non-issues rather than things held off by a pointer-events rule.
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
        // ★ The strip is now INSIDE the flex column that also holds the map, so anything that
        //   changes the dock's height — "+N more", "show less", the selection headline
        //   appearing or disappearing — takes that height straight out of the map's. rAF so the
        //   new layout has resolved before MapLibre re-reads the container.
        //   The ResizeObserver on `host` should also catch this, since host IS the box that
        //   shrinks; this is the explicit call, not a replacement for it, because the RO fires
        //   asynchronously and a visibly stretched canvas for a frame is the failure it leaves.
        requestAnimationFrame(() => safeResize());
    };
    dockHost.hidden = false;
    dockHost.appendChild(dock);

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
        //   takes MapLibre's defaults, which for maxPitch is 60 (one `maxPitch:60` literal in the
        //   4.7.1 dist bundle). This view now deliberately EXCEEDS that — see the maxPitch note
        //   below — so it is the one navigation option that no longer matches the legacy map.
        //   Everything here except dragRotate and maxPitch was
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
        // ★ 60 (MapLibre's default) -> 75, CHOSEN BY READING SCREENSHOTS AT 50/60/70/75/80/85
        //   with an ego selected and the zoom held constant so pitch was the only variable:
        //     70  excellent — arcs strongly three-dimensional, every label legible, markers
        //         distinct across the whole plane including the Europe and East Asia clusters
        //     75  the limit that still holds — the far band (Russia/Kazakhstan/Mongolia)
        //         compresses but labels stay individually readable and markers stay separable
        //     80  markers in the far band MERGE into a smear, which breaks the one thing the
        //         zoom-scaled radius was added to fix, and ~25% of the viewport is empty
        //         foreground
        //     85  the northern hemisphere is crushed into a strip a few pixels deep,
        //         GREENLAND/ICELAND/UNITED KINGDOM/NORWAY collide on one line, and ~40% of the
        //         viewport is empty foreground
        //   75 is therefore the highest angle that is still readable, NOT the maximum available.
        maxPitch: 75,
        // ★ true AGAIN FROM 2026-10-06, and correctness is the reason. It was set false at 1e8d223
        //   as a visual preference ("zooming out stops at one world"), not to fix any fault.
        //   But with ONE world, deck.gl's ArcLayer (greatCircle: true) has no second copy to
        //   continue into. It cuts every arc that crosses the antimeridian into two mid-air
        //   stubs, one at +180 and one at -180 (arc-layer-vertex.glsl: segments that jump >180 are
        //   discarded). @deck.gl/mapbox renders one pass per world copy only when
        //   getRenderWorldCopies() is true.
        //   That is not an edge case here. 133 of the 932 drawable edges span >180 deg of
        //   longitude (TSMC 18, Samsung 16, United_States 13, Micron 13). The semiconductor
        //   supply chain crosses the Pacific.
        //   The alternative of drawing them the long way round inside one world would draw all
        //   133 geographically false (NVIDIA->TSMC across the Atlantic and Eurasia). That would
        //   make the display assert a route the data does not contain. The one-world floor is
        //   kept by the minZoom below; only the hard edge goes.
        renderWorldCopies: true,
        // ★ Required for deck.gl's interleaved mode — it fixes the WebGL2 context attributes the
        //   overlay needs. The legacy map sets it for the same reason (:1034).
        antialias: true,
    });
    const dead = () => !map || (map as any)._removed === true;
    /**
     * ★ THE ZOOM FLOOR IS DERIVED FROM THE CONTAINER, NOT HARD-CODED. The world is
     *   512·2^z CSS px wide (MapLibre's tile size is 512), so the zoom at which it exactly
     *   covers the viewport depends on the viewport. A literal that is right at 2400px leaves
     *   grey gutters at 1400px and blocks legitimate zoom-out in fullscreen.
     *
     *   max(w, h), not w: the floor has to stop grey appearing on EITHER axis. For a landscape
     *   container the two agree because w > h; they differ only in portrait, where w alone
     *   would leave grey above and below.
     *
     *   ★ Re-checked 2026-10-06 when renderWorldCopies went back to true. With world copies,
     *   horizontal grey can no longer appear (the copies fill it), so the WIDTH term no longer
     *   guards against grey. It still does the other job it was introduced for in 1e8d223:
     *   zoomed fully out, exactly one world's width is visible, so the default view shows
     *   no repetition. The copies appear only when the user pans across the antimeridian,
     *   which is where they are needed. The HEIGHT term still prevents vertical grey.
     *   Formula unchanged.
     *
     *   Recomputed on mount, on every ResizeObserver callback, and after the view's resize()
     *   (which is what fullscreen enter/exit calls), so entering fullscreen raises the floor and
     *   leaving lowers it again. MapLibre clamps the current zoom itself when the floor rises.
     */
    const TILE_PX = 512;
    const applyMinZoom = () => {
        if (dead()) return;
        const b = mapEl.getBoundingClientRect();
        const side = Math.max(b.width || 0, b.height || 0);
        if (!(side > 0)) return;                        // not laid out yet; the RO will retry
        const z = Math.log2(side / TILE_PX);
        if (!Number.isFinite(z)) return;
        try { map.setMinZoom(Math.max(-2, z)); } catch { /* style not ready */ }
    };
    const safeResize = () => { if (!dead()) { map.resize(); applyMinZoom(); } };
    // showCompass is on now that rotation works: without it there is no way back to north
    // after a ctrl-drag, and pitch makes a lost bearing easy to acquire.
    // ★ TOP-LEFT, NOT TOP-RIGHT, AND THAT IS A FIX NOT A PREFERENCE. The drawer is 320px of
    //   absolutely-positioned overlay pinned top:0/bottom:0 on the RIGHT, so at >=1200px it
    //   covers the entire right edge of the map. The zoom buttons sat under it whenever a node
    //   was selected — I hit that myself during an earlier verification run, where repeated
    //   clicks on .maplibregl-ctrl-zoom-out silently did nothing because they were landing on
    //   the drawer. The left edge is the only region the drawer never reaches.
    map.addControl(new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }), 'top-left');
    const resetCtl = new ResetViewControl();
    map.addControl(resetCtl, 'top-left');
    // ★ ATTRIBUTION WAS MISSING ENTIRELY. The constructor sets attributionControl:false and
    //   nothing added one back, so this view shipped a CARTO dark-matter basemap with no
    //   credit — while style.css:9109 in this same repo calls it "the required CARTO/OSM
    //   attribution" and pro_interactive_map.ts:1037 adds AttributionControl({compact:true}).
    //   Restored on that existing convention. Bottom-LEFT rather than the legacy bottom-right
    //   for the same reason as above: the drawer owns the right edge, and attribution that is
    //   hidden behind a panel is not attribution.
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-left');

    let selected: string | null = null;
    let mountedMs = 0;
    let panelPx = 0;
    /** Below this the drawer is a BOTTOM SHEET, so it eats height, not width. Must match the
     *  media query in style.css (#pro-map-container .rv-panel). */
    const SHEET_BP = 1200;
    const egoPadding = () => (window.innerWidth < SHEET_BP
        ? { top: 60, bottom: 48 + panelPx, left: 60, right: 60 }
        : { top: 60, bottom: 48, left: 60, right: 60 + panelPx });

    const pointFC = () => ({
        type: 'FeatureCollection' as const,
        features: geo.map((n) => {
            const c = coords[n.id];
            // ★ Same guard as the graph canvas: a selection with no neighbours would dim every
            //   geo node to alpha 0.15 and leave a basemap with nothing on it. An ego of one
            //   disables the filter instead. (The node itself may not even be on the map — a
            //   zero-degree node with no coordinate lives in the dock.)
            const nbrs = selected === null ? undefined : adj.get(selected);
            const egoActive = (nbrs?.size ?? 0) > 0;
            const inEgo = !egoActive || n.id === selected || (nbrs?.has(n.id) ?? false);
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
                'circle-radius': byZoom(['get', 'radius'], RADIUS_STOPS),
                // countries render as rings: a different kind of thing, not a bigger one
                'circle-color': ['case', ['==', ['get', 'ring'], 1], 'rgba(0,0,0,0)', ['get', 'color']],
                'circle-opacity': ['get', 'alpha'],
                // The ring IS the country marker, so its stroke grows with the circle or a
                // country reads as a hairline at high zoom. Capped below the radius scale so it
                // never closes into a disc.
                'circle-stroke-width': byZoom(
                    ['case', ['==', ['get', 'sel'], 1], 2.4, ['==', ['get', 'ring'], 1], 1.6, 0],
                    STROKE_STOPS),
                'circle-stroke-color': ['case', ['==', ['get', 'sel'], 1], '#f1f5f9', ['get', 'color']],
                'circle-stroke-opacity': ['get', 'alpha'],
            },
        });
        map.addLayer({
            id: 'rv-labels', type: 'symbol', source: 'rv-nodes',
            layout: {
                'text-field': ['get', 'label'],
                // ★ SIZE deliberately NOT scaled: 10px is readable at every zoom and growing it
                //   crowds the map exactly where zooming in is meant to make room. The OFFSET
                //   must move though — it is in ems of the text size, so a fixed 1.1em stays
                //   ~11px while the circle under it grows 6.5x and the label ends up inside its
                //   own marker. Symbol collision is between symbols, not against the circle
                //   layer, so decluttering is unaffected by either.
                'text-size': 10,
                'text-offset': ['interpolate', ['linear'], ['zoom'], 0, ['literal', [0, 1.1]],
                                4, ['literal', [0, 1.8]], 9, ['literal', [0, 3.6]]],
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
        // The floor must exist before the first fitBounds, or the initial frame can land below
        // it and be clamped a moment later, which reads as the map jumping on load.
        applyMinZoom();
        // ★ NO setMaxBounds, AND THAT IS A MEASURED DECISION, NOT AN OMISSION.
        //   Traced getMinZoom()/getZoom() around each call at 2400px (container 1972x596):
        //     after setMinZoom(1.945)   minZoom 1.945   zoom 1.945
        //     after setMaxBounds        minZoom 1.945   zoom 22      <- slammed to the maximum
        //     setZoom(-5) afterwards    minZoom 1.945   zoom 22      <- stuck, unrecoverable
        //   So maxBounds does NOT overwrite the floor, which was the obvious guess and was
        //   wrong. It makes the camera unsatisfiable: full-Mercator bounds demand "show all
        //   latitude +/-85" AND "show no more than +/-180 longitude" at once, which cannot hold
        //   in a 3.3:1 viewport, and MapLibre resolves the contradiction by pinning zoom to its
        //   maximum. That is what rendered as an untiled grey slab.
        //
        //   Tightening latitude (say +/-60) would make the bounds satisfiable, but this graph
        //   contains Nord Stream, Power of Siberia and Arctic shipping context — cropping the
        //   subject to buy a panning nicety is the wrong trade. The explicit floor already
        //   delivers the thing that was asked for: you cannot zoom out past one world. What is
        //   given up is that the single world can be panned partly off-screen, showing grey at
        //   the edge. That is cosmetic, and strictly smaller than a map that cannot zoom at all.
        // ★ Initial framing here, not in the constructor. Fewer than two placeable nodes gives a
        //   degenerate bounds, so keep the fixed view in that case rather than fitting to a point.
        if (placeable.length >= 2 && !dead()) {
            try {
                map.fitBounds(geoBounds(), {
                    padding: { top: 48, bottom: 48, left: 48, right: 48 }, maxZoom: 4, duration: 0,
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
        // ★ CONTINUOUS LONGITUDES, RELATIVE TO THE EGO (2026-10-06). LngLatBounds.extend is a
        //   plain min/max of longitude. For an ego whose arcs cross the antimeridian
        //   (NVIDIA->TSMC, TSMC->Apple, ...) that framed the long Atlantic-centred span, so the
        //   Pacific arcs ran off both sides and joined off-screen. Each counterpart is therefore
        //   shifted by whole turns to lie within 180 deg of the ego: the same side the great-circle
        //   arc actually goes (|dlng| > 180 <=> the shortest path crosses +/-180). The bounds may
        //   extend past +/-180, which renderWorldCopies: true renders as the adjacent copy.
        //   The ego's own longitude is never moved, so the frame stays on the copy the user is in.
        const egoLng = coords[id] && Number.isFinite(coords[id].lng) ? coords[id].lng : null;
        const near = (lng: number) => {
            if (egoLng === null) return lng;
            let x = lng;
            while (x - egoLng > 180) x -= 360;
            while (x - egoLng < -180) x += 360;
            return x;
        };
        const b = new maplibregl.LngLatBounds();
        for (const x of ids) b.extend([near(coords[x].lng), coords[x].lat]);
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
            // ★ 50 -> 65. More oblique, so the ArcLayer getHeight 0.45 lift actually reads as
            //   lift, while leaving 10 degrees of headroom under the 75 ceiling for the user to
            //   tilt further by drag. Padding is UNCHANGED and was re-verified at the new angle:
            //   a pitched camera sees MORE ground than a flat one at the same zoom, and
            //   fitBounds computes its fit top-down, so it errs toward showing too much rather
            //   than too little. The ego and its counterparts stay on screen.
            padding: egoPadding(), maxZoom: 5, pitch: 65, bearing: 0, duration: 900,
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

    /**
     * Re-frame to whatever framing this view would have produced on its own: the current ego if
     * one is selected, otherwise the default world fit. Animated at 900ms to match the fitBounds
     * the selection path already uses, so reset feels like the same gesture rather than a jump.
     * Selection, drawer and collapse state are untouched by design — see ResetViewControl.
     */
    const resetView = () => {
        if (dead()) return;
        if (selected && coords[selected]) { fitEgo(selected); return; }
        if (placeable.length < 2) return;
        try {
            map.fitBounds(geoBounds(), {
                padding: { top: 48, bottom: 48, left: 48, right: 48 },
                maxZoom: 4, pitch: 0, bearing: 0, duration: 900,
            });
        } catch { /* keep the current view */ }
    };
    resetCtl.onReset = resetView;

    const refit = () => {
        if (dead() || placeable.length < 2) return;
        try {
            map.fitBounds(geoBounds(), {
                padding: { top: 48, bottom: 48, left: 48, right: 48 }, maxZoom: 4, duration: 0,
            });
        } catch { /* keep the current view */ }
    };

    return {
        setPanelOffset(px) { panelPx = Math.max(0, px | 0); },
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
            ro.disconnect(); if (!dead()) map.remove(); mapEl.remove();
            dock.remove(); dockHost.hidden = true;
        },
    };
}
