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

export type GlobeNode = { id: string; type?: string | null; country?: string | null };
export type GlobeEdge = { s: string; t: string; type: string; weight?: number | null };
type Coord = { lat: number; lng: number; type?: string; city?: string };

/** Same basemap as the Pro map — CARTO dark-matter, no token. */
export const BASEMAP = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

const DEFAULT_COLOR = '#64748b';
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

    /** Edges of the selected node whose BOTH ends have coordinates. An edge to a dock entity is
     *  not drawn as a fake line to an invented point — it is shown by lighting the chip. */
    const lineFC = () => {
        if (!selected) return { type: 'FeatureCollection' as const, features: [] };
        const feats: any[] = [];
        for (const e of edges) {
            const other = e.s === selected ? e.t : e.t === selected ? e.s : null;
            if (!other) continue;
            const a = coords[selected], b = coords[other];
            if (!a || !b) continue;
            feats.push({
                type: 'Feature', geometry: { type: 'LineString', coordinates: [[a.lng, a.lat], [b.lng, b.lat]] },
                properties: { etype: e.type, w: e.weight == null ? 0 : 1 },
            });
        }
        return { type: 'FeatureCollection' as const, features: feats };
    };

    const refresh = () => {
        if (dead()) return;
        (map.getSource('rv-nodes') as any)?.setData(pointFC());
        (map.getSource('rv-lines') as any)?.setData(lineFC());
        for (const el of Array.from(dock.querySelectorAll('.rv-chip-n'))) {
            const id = (el as HTMLElement).dataset.goto!;
            const lit = !selected || id === selected || (adj.get(selected)?.has(id) ?? false);
            (el as HTMLElement).dataset.lit = lit ? '1' : '0';
        }
    };

    map.on('load', () => {
        map.addSource('rv-lines', { type: 'geojson', data: lineFC() });
        map.addLayer({
            id: 'rv-lines', type: 'line', source: 'rv-lines',
            paint: {
                'line-color': '#7dd3fc', 'line-opacity': 0.5,
                'line-width': ['case', ['==', ['get', 'w'], 1], 1.6, 0.9],
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
            selected = id; refresh(); onSelect(id);
        });
        map.on('click', (ev) => {
            const hit = map.queryRenderedFeatures(ev.point, { layers: ['rv-nodes'] });
            if (!hit.length && selected) { selected = null; refresh(); onSelect(null); }
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
    });

    dock.addEventListener('click', (ev) => {
        const more = (ev.target as HTMLElement).closest('[data-more]') as HTMLElement | null;
        if (more) { dock.dataset.expanded = more.dataset.more!; renderDock(); return; }
        const el = (ev.target as HTMLElement).closest('[data-goto]') as HTMLElement | null;
        if (!el) return;
        selected = el.dataset.goto!; refresh(); onSelect(selected);
    });

    const fitEgo = (id: string) => {
        if (dead()) return;
        const ids = finiteCoords([id, ...(adj.get(id) || [])]);
        if (ids.length < 1) return;                  // dock-only entity: nothing geographic to fit
        const b = new maplibregl.LngLatBounds();
        for (const x of ids) b.extend([coords[x].lng, coords[x].lat]);
        map.fitBounds(b, { padding: { top: 60, bottom: 90, left: 60, right: 420 }, maxZoom: 5, duration: 500 });
    };

    // ★ MapLibre sizes itself from the container at construction. The host is a grid cell that
    //   may not have resolved yet, and the overlay drawer changes the visible area without
    //   changing the container, so resize() is called after mount, from a ResizeObserver, and by
    //   the view whenever the drawer opens or closes.
    const ro = new ResizeObserver(() => safeResize());
    ro.observe(host);
    requestAnimationFrame(() => safeResize());

    const refit = () => {
        if (dead() || placeable.length < 2) return;
        try {
            map.fitBounds(geoBounds(), {
                padding: { top: 48, bottom: 110, left: 48, right: 48 }, maxZoom: 4, duration: 0,
            });
        } catch { /* keep the current view */ }
    };

    return {
        select(id) { selected = id; refresh(); },
        focus(id) { selected = id; refresh(); fitEgo(id); },
        resize() { safeResize(); },
        /** Re-frame after the host has actually been laid out at its final width. */
        refit() { safeResize(); refit(); },
        destroy() { ro.disconnect(); if (!dead()) map.remove(); mapEl.remove(); dock.remove(); },
    };
}
