/**
 * Force-directed canvas for the relationship graph.
 *
 * HTML canvas, not SVG: 1535 edges as DOM nodes would make every hover a layout pass. One 2D
 * context, redrawn on transform/selection change, is the cheap and boring choice.
 *
 * ★ DETERMINISTIC LAYOUT. Node start positions are seeded from a hash of the node id, so the
 *   same graph lands in the same arrangement on every reload. A force layout seeded from
 *   Math.random() rearranges itself each time, which would make the picture look like it carries
 *   information that changes — it does not. The layout is a reading aid, not a measurement.
 *
 * ★ WHAT THE PICTURE MUST NOT IMPLY. Distance between two unconnected nodes means nothing, and
 *   edge length is a function of edge TYPE, not of weight — weights in this vault are
 *   within-hub relative and not comparable across hubs (CLAUDE.md §3), so mapping them to
 *   geometry would invent a cross-hub comparison the data forbids. Weight shows as a small
 *   thickness step and, exactly, as a number in the panel.
 */
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from 'd3-force';
import type { Simulation } from 'd3-force';
import { select } from 'd3-selection';
import { zoom, zoomIdentity, type D3ZoomEvent, type ZoomTransform } from 'd3-zoom';
import { drag } from 'd3-drag';

export type GNode = {
    id: string; type?: string | null; country?: string | null; title?: string | null;
    x?: number; y?: number; vx?: number; vy?: number; fx?: number | null; fy?: number | null;
    deg?: number; r?: number;
};
export type GEdge = { s: string; t: string; type: string; weight?: number | null;
                      source?: any; target?: any; weighted?: boolean };

/** One palette, by node type. Countries are drawn as rings rather than discs so a country never
 *  reads as "a bigger company" — they are a different kind of thing, not a larger one. */
export const PALETTE: Record<string, string> = {
    company: '#38bdf8',   // sky
    country: '#f59e0b',   // amber   (ring)
    market:  '#a78bfa',   // violet
    concept: '#34d399',   // emerald
    route:   '#fb7185',   // rose
    fund:    '#facc15',   // yellow
    port:    '#2dd4bf',   // teal
    bloc:    '#c084fc',   // purple
    org:     '#94a3b8',   // slate
};
const DEFAULT_COLOR = '#64748b';

/** Link distance by EDGE TYPE. Containment is tight, rivalry is middling, exposure is loose. */
function linkDistance(t: string): number {
    // ★ x1.6 over the first pass (26/62/110/80): at the original distances the 1535 edges pulled
    //   the graph into a hairball in which nothing could be read.
    if (t === 'located_in' || t === 'hosts' || t === 'owns' || t === 'subsidizes') return 42;
    if (t === 'competitor' || t === 'complementary' || t === 'joint_venture') return 99;
    if (t === 'context_link') return 176;
    return 128;
}

/** FNV-1a over the id -> a stable start position. Same graph, same picture, every reload. */
function seedPos(id: string, w: number, h: number): { x: number; y: number } {
    let a = 2166136261;
    for (let i = 0; i < id.length; i++) { a ^= id.charCodeAt(i); a = Math.imul(a, 16777619); }
    const u = ((a >>> 0) % 100000) / 100000;
    let b = 2166136261;
    for (let i = id.length - 1; i >= 0; i--) { b ^= id.charCodeAt(i); b = Math.imul(b, 16777619); }
    const v = ((b >>> 0) % 100000) / 100000;
    const ang = u * Math.PI * 2, rad = Math.sqrt(v) * Math.min(w, h) * 0.42;
    return { x: w / 2 + Math.cos(ang) * rad, y: h / 2 + Math.sin(ang) * rad };
}

export type CanvasHandle = {
    select: (id: string | null) => void;
    focus: (id: string) => void;
    setTwoHop: (on: boolean) => void;
    /** Width of the overlay drawer, so focus() can keep the selected node clear of it. */
    setPanelOffset: (px: number) => void;
    labelStats: () => { kept: number; considered: number; k: number };
    /** Force an immediate re-size + redraw. The ResizeObserver already catches host changes, but
     *  it fires asynchronously, so a fullscreen transition shows one stretched frame without
     *  this. Belt to the observer's braces, not a replacement for it. */
    resize: () => void;
    destroy: () => void;
};

export function mountGraphCanvas(
    host: HTMLElement,
    nodes: GNode[],
    edges: GEdge[],
    onSelect: (id: string | null) => void,
): CanvasHandle {
    const canvas = document.createElement('canvas');
    canvas.className = 'rv-canvas';
    host.appendChild(canvas);
    const ctx = canvas.getContext('2d')!;

    let W = host.clientWidth || 800, H = host.clientHeight || 600;
    let dpr = Math.min(window.devicePixelRatio || 1, 2);
    const sizeCanvas = () => {
        W = host.clientWidth || 800; H = host.clientHeight || 600;
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
        canvas.style.width = `${W}px`; canvas.style.height = `${H}px`;
    };
    sizeCanvas();

    const byId = new Map(nodes.map((n) => [n.id, n]));
    const deg = new Map<string, number>();
    for (const e of edges) {
        deg.set(e.s, (deg.get(e.s) || 0) + 1);
        deg.set(e.t, (deg.get(e.t) || 0) + 1);
    }
    for (const n of nodes) {
        n.deg = deg.get(n.id) || 0;
        n.r = 3 + Math.log1p(n.deg) * 1.9;
        const p = seedPos(n.id, W, H); n.x = p.x; n.y = p.y;
    }
    const adj = new Map<string, Set<string>>();
    for (const e of edges) {
        if (!adj.has(e.s)) adj.set(e.s, new Set());
        if (!adj.has(e.t)) adj.set(e.t, new Set());
        adj.get(e.s)!.add(e.t); adj.get(e.t)!.add(e.s);
        e.weighted = e.weight != null;
        // ★ forceLink reads link.source / link.target, NOT our s / t. Without these it calls
        //   id(undefined) and throws `node not found: undefined` during force setup — after the
        //   canvas element is appended and before any draw, which presents as an empty canvas of
        //   the correct size with the panel beside it working fine.
        e.source = e.s; e.target = e.t;
    }
    // One unresolvable endpoint must not cost the whole canvas: forceLink throws on the first.
    const known = new Set(nodes.map((n) => n.id));
    const linkable = edges.filter((e) => known.has(e.s) && known.has(e.t));
    const dropped = edges.length - linkable.length;

    const t0 = performance.now();
    let ticks = 0;
    const sim: Simulation<GNode, undefined> = forceSimulation(nodes)
        .force('link', forceLink<GNode, any>(linkable).id((d: any) => d.id)
            .distance((l: any) => linkDistance(l.type)).strength(0.35))
        .force('charge', forceManyBody().strength(-260).distanceMax(560))   // x2 repulsion (was -130)
        .force('center', forceCenter(W / 2, H / 2))
        .force('collide', forceCollide<GNode>().radius((d) => (d.r || 4) + 6))      // +6 (was +2.5)
        .stop();
    for (let i = 0; i < 300; i++) { sim.tick(); ticks++; }
    sim.alphaTarget(0);
    const layoutMs = performance.now() - t0;

    let transform: ZoomTransform = zoomIdentity;
    let selected: string | null = null;
    let hovered: string | null = null;
    let twoHop = false;
    let ego: Set<string> = new Set();
    let egoActive = false;          // false when the selection has no neighbours — see computeEgo
    let tween: number | null = null;
    let panelOffset = 0;
    let labelsKept = 0, labelsConsidered = 0;

    /**
     * ★ egoActive, not `selected`, is what gates the dimming — and that distinction IS the fix.
     *   Selecting a node with no neighbours produced ego = {itself}, so all 302 other nodes and
     *   every edge dimmed out and the canvas rendered ONE DOT in a 1572x748 void. The user was
     *   left with an empty picture and a three-line panel, on a surface that exists to answer
     *   "if this moves, what else moves".
     *   Now an ego of one disables the filter: the full graph stays drawn and the node is simply
     *   highlighted in place, which at least shows WHERE it sits. Keyed on neighbour count, so
     *   it holds for any future node of this shape, not just the one that has it today.
     */
    const computeEgo = () => {
        ego = new Set();
        egoActive = false;
        if (!selected) return;
        ego.add(selected);
        for (const a of adj.get(selected) || []) ego.add(a);
        if (twoHop) for (const a of [...ego]) for (const b of adj.get(a) || []) ego.add(b);
        egoActive = ego.size > 1;
    };

    // English-only surface: the server drops CJK titles, and the canvas label is derived from
    // the id regardless so a node never renders under one name here and another in the panel.
    const label = (n: GNode) => n.id.replace(/_/g, ' ');
    const draw = () => {
        ctx.save();
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, W, H);
        ctx.translate(transform.x, transform.y); ctx.scale(transform.k, transform.k);
        const dim = selected ? 0.15 : 1;

        for (const e of edges) {
            const s = e.source as GNode, t = e.target as GNode;
            if (!s || !t || s.x == null || t.x == null) continue;
            const inEgo = !egoActive || (ego.has(s.id) && ego.has(t.id));
            // competitor is UNWEIGHTED BY DESIGN (00_SCHEMA.md:85) — drawn lighter so the eye
            // does not read a rivalry edge as a measured dependency.
            const base = e.type === 'competitor' ? 0.1 : 0.2;
            ctx.globalAlpha = inEgo ? (selected ? 0.75 : base) : base * dim;
            ctx.strokeStyle = inEgo && selected ? '#7dd3fc' : '#475569';
            ctx.lineWidth = (e.weighted ? 1.4 : 0.8) / transform.k;
            ctx.beginPath(); ctx.moveTo(s.x, s.y!); ctx.lineTo(t.x!, t.y!); ctx.stroke();
        }

        for (const n of nodes) {
            if (n.x == null) continue;
            const inEgo = !egoActive || ego.has(n.id);
            ctx.globalAlpha = inEgo ? 1 : dim;
            const col = PALETTE[n.type || ''] || DEFAULT_COLOR;
            ctx.beginPath(); ctx.arc(n.x, n.y!, n.r!, 0, Math.PI * 2);
            if (n.type === 'country') {           // ring, not disc — a different kind, not a bigger one
                ctx.strokeStyle = col; ctx.lineWidth = 1.6 / transform.k; ctx.stroke();
            } else { ctx.fillStyle = col; ctx.fill(); }
            if (n.id === selected) {
                ctx.strokeStyle = '#f1f5f9'; ctx.lineWidth = 2 / transform.k;
                ctx.beginPath(); ctx.arc(n.x, n.y!, n.r! + 3, 0, Math.PI * 2); ctx.stroke();
            }
        }

        ctx.restore();

        // ─── Labels: a SEPARATE pass in SCREEN space ──────────────────────────────────────
        // Drawn with the identity transform and positions projected by hand, so measureText
        // returns real pixels and the collision test is in the space the eye actually sees.
        // Labels are therefore screen-size constant: zooming in frees space and more appear.
        ctx.save();
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.font = '10px ui-sans-serif, system-ui, sans-serif';
        ctx.textBaseline = 'middle';
        const k = transform.k;
        const sx = (n: GNode) => n.x! * k + transform.x;
        const sy = (n: GNode) => n.y! * k + transform.y;
        const PAD = 2;

        type Cand = { n: GNode; txt: string; x: number; y: number; w: number; h: number; forced: boolean };
        const cands: Cand[] = [];
        for (const n of nodes) {
            if (n.x == null) continue;
            const forced = n.id === hovered || n.id === selected || (egoActive && ego.has(n.id));
            // At k >= 2.5 every node is a candidate regardless of degree — there is room by then.
            const eligible = forced || (selected ? false : (k >= 2.5 || (n.deg || 0) >= 12 || n.type === 'country'));
            if (!eligible) continue;
            const X = sx(n), Y = sy(n);
            if (X < -120 || Y < -20 || X > W + 120 || Y > H + 20) continue;   // offscreen
            const txt = label(n);
            cands.push({ n, txt, x: X + n.r! * k + 3, y: Y, w: ctx.measureText(txt).width, h: 11, forced });
        }
        // Greedy: forced first (selected + 1-hop, so they can never be crowded out), then
        // degree-desc. A candidate is dropped if its rect meets one already kept.
        cands.sort((a, b) => (b.forced ? 1 : 0) - (a.forced ? 1 : 0) || (b.n.deg || 0) - (a.n.deg || 0));
        const kept: Cand[] = [];
        const hits = (a: Cand, b: Cand) =>
            a.x - PAD < b.x + b.w + PAD && a.x + a.w + PAD > b.x - PAD &&
            a.y - a.h / 2 - PAD < b.y + b.h / 2 + PAD && a.y + a.h / 2 + PAD > b.y - b.h / 2 - PAD;
        for (const c of cands) {
            if (kept.some((o) => hits(c, o))) continue;
            kept.push(c);
        }
        labelsKept = kept.length; labelsConsidered = cands.length;
        // non-forced first, forced last = selected + 1-hop end up on top
        for (const c of [...kept.filter((c) => !c.forced), ...kept.filter((c) => c.forced)]) {
            ctx.globalAlpha = (!egoActive || ego.has(c.n.id)) ? 0.94 : dim;
            ctx.fillStyle = c.forced && selected ? '#f1f5f9' : '#cbd5e1';
            ctx.fillText(c.txt, c.x, c.y);
        }
        ctx.restore();
    };

    const at = (ev: MouseEvent): GNode | null => {
        const rect = canvas.getBoundingClientRect();
        const [mx, my] = transform.invert([ev.clientX - rect.left, ev.clientY - rect.top]);
        let best: GNode | null = null, bd = Infinity;
        for (const n of nodes) {
            if (n.x == null) continue;
            const d = (n.x - mx) ** 2 + (n.y! - my) ** 2;
            const rr = (n.r! + 4) ** 2;
            if (d < rr && d < bd) { bd = d; best = n; }
        }
        return best;
    };

    const tip = document.createElement('div');
    tip.className = 'rv-tip'; tip.style.display = 'none';
    host.appendChild(tip);

    canvas.addEventListener('mousemove', (ev) => {
        const n = at(ev);
        const id = n ? n.id : null;
        if (id !== hovered) { hovered = id; draw(); }
        if (n) {
            tip.innerHTML = `<b>${n.id.replace(/_/g, ' ').replace(/</g, '&lt;')}</b><br>${[n.type, n.country].filter(Boolean).join(' · ')}`;
            tip.style.display = 'block';
            tip.style.left = `${ev.offsetX + 14}px`; tip.style.top = `${ev.offsetY + 12}px`;
        } else tip.style.display = 'none';
    });
    canvas.addEventListener('mouseleave', () => { tip.style.display = 'none'; hovered = null; draw(); });

    const api: CanvasHandle = {
        select(id) { selected = id; computeEgo(); draw(); },
        focus(id) {
            const n = byId.get(id); if (!n || n.x == null) return;
            selected = id; computeEgo();
            // ★ A node with no neighbours must NOT be zoomed to. The k=1.8 node-centred frame
            //   below is right for an ego with counterparts, but for an isolated node the force
            //   layout has pushed it far from the cluster (nothing pulls it in), so flying to it
            //   at 1.8x parks the camera on empty space. Disabling the ego DIMMING alone did not
            //   fix this — measured 0.04% of the canvas painted, against 12.57% unselected. The
            //   camera was the second half of the bug. Frame the whole graph instead, so the
            //   highlighted node is shown IN CONTEXT rather than alone.
            const k = 1.8;
            // Centre on the VISIBLE half when the drawer is open, not on the canvas centre.
            const cx = (W - panelOffset) / 2;
            const to = egoActive
                ? zoomIdentity.translate(cx - n.x * k, H / 2 - n.y! * k).scale(k)
                : (wholeGraphTransform() ?? transform);
            // ★ Hand-rolled 400ms tween rather than d3-transition: adding a fifth d3 package for
            //   one eased interpolation is not worth the bundle. cubic ease-in-out over
            //   (x, y, k), pushed through zb.transform so d3-zoom's own state stays authoritative
            //   — otherwise the next user pan would jump back to the pre-tween transform.
            const from = transform, t0t = performance.now(), dur = 400;
            if (tween !== null) cancelAnimationFrame(tween);
            const step = () => {
                const p = Math.min(1, (performance.now() - t0t) / dur);
                const e = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
                const cur = zoomIdentity
                    .translate(from.x + (to.x - from.x) * e, from.y + (to.y - from.y) * e)
                    .scale(from.k + (to.k - from.k) * e);
                select(canvas as any).call(zb.transform as any, cur);
                tween = p < 1 ? requestAnimationFrame(step) : null;
            };
            tween = requestAnimationFrame(step);
        },
        setTwoHop(on) { twoHop = on; computeEgo(); draw(); },
        setPanelOffset(px) { panelOffset = px; },
        labelStats() { return { kept: labelsKept, considered: labelsConsidered, k: transform.k }; },
        resize() { sizeCanvas(); draw(); },
        destroy() {
            if (tween !== null) cancelAnimationFrame(tween);
            window.removeEventListener('keydown', onKeyDown);
            ro.disconnect(); canvas.remove(); tip.remove();
        },
    };

    const zb = zoom<HTMLCanvasElement, unknown>().scaleExtent([0.15, 8])
        .on('zoom', (ev: D3ZoomEvent<HTMLCanvasElement, unknown>) => { transform = ev.transform; draw(); });
    select(canvas as any).call(zb as any);

    let dragging: GNode | null = null;
    select(canvas as any).call(
        drag<HTMLCanvasElement, unknown>()
            .subject((ev: any) => at(ev.sourceEvent) as any)
            .on('start', (ev: any) => { dragging = ev.subject as GNode; })
            .on('drag', (ev: any) => {
                if (!dragging) return;
                const [mx, my] = transform.invert([ev.x, ev.y]);
                dragging.x = mx; dragging.y = my; dragging.fx = mx; dragging.fy = my; draw();
            })
            .on('end', () => { dragging = null; }) as any,
    );

    canvas.addEventListener('click', (ev) => {
        const n = at(ev);
        selected = n ? n.id : null;
        computeEgo(); draw();
        onSelect(selected);
    });
    // ★ This is the ONLY listener in this module that is not on the canvas element, and it used
    //   to leak: destroy() removed the canvas but not this, so after switching to Globe mode a
    //   dead graph kept handling Escape — calling draw() on a detached canvas and, worse,
    //   onSelect(null), clearing the GLOBE's selection from a view that no longer existed.
    //   It does NOT call preventDefault or stopPropagation, so it was never what blocked dragging
    //   on the globe; it is a lifetime bug, not an input-interception one. Named and removed in
    //   destroy() now. Everything else here is bound to `canvas`, including d3-zoom and d3-drag
    //   (via select(canvas).call(...)), and goes with the element.
    const onKeyDown = (ev: KeyboardEvent) => {
        if (ev.key === 'Escape' && selected) { selected = null; computeEgo(); draw(); onSelect(null); }
    };
    window.addEventListener('keydown', onKeyDown);

    /** ★ Fit the whole graph on load. The simulation's extent is wider than the viewport
     *  (measured 303/1535: x [123,1964], y [-83,927] against ~1200x800), so without this the
     *  default state would silently crop the graph the brief asks to show whole. */
    let logged = false;
    const logMount = (k: number, tx: number, ty: number) => {
        if (logged) return; logged = true;
        const firstMs = performance.now() - t0;
        /* eslint-disable no-console */
        console.log(`[relationship_canvas] size host ${W}x${H} · backing ${canvas.width}x${canvas.height} · dpr ${dpr}`);
        console.log(`[relationship_canvas] transform k=${k.toFixed(3)} x=${tx.toFixed(1)} y=${ty.toFixed(1)} · nodes ${nodes.length} · edges ${edges.length} linkable ${linkable.length} dropped ${dropped}`);
        console.log(`[relationship_canvas] layout ${layoutMs.toFixed(0)}ms (${ticks} ticks, ${(ticks / Math.max(1, layoutMs / 1000)).toFixed(0)} ticks/s) · first render ${firstMs.toFixed(0)}ms`);
        /* eslint-enable no-console */
    };

    /** The transform that frames the WHOLE graph. Extracted so focus() can fall back to it. */
    const wholeGraphTransform = () => {
        if (!(W > 0 && H > 0)) return null;
        const xs = nodes.map((n) => n.x!).filter(Number.isFinite);
        const ys = nodes.map((n) => n.y!).filter(Number.isFinite);
        if (!xs.length || !ys.length) return null;
        const x0 = Math.min(...xs), x1 = Math.max(...xs);
        const y0 = Math.min(...ys), y1 = Math.max(...ys);
        const pad = 28;
        let k = Math.min((W - pad * 2) / Math.max(1, x1 - x0), (H - pad * 2) / Math.max(1, y1 - y0));
        if (!Number.isFinite(k)) k = 1;
        k = Math.max(0.05, Math.min(8, k));
        const tx = W / 2 - ((x0 + x1) / 2) * k, ty = H / 2 - ((y0 + y1) / 2) * k;
        return Number.isFinite(tx) && Number.isFinite(ty)
            ? zoomIdentity.translate(tx, ty).scale(k) : null;
    };

    let fitted = false;
    const fit = (): boolean => {
        // ★ NEVER fit at zero size. A hidden or not-yet-laid-out tab container reports
        //   clientWidth/Height 0; the extent division then yields Infinity/NaN and a NaN
        //   transform draws nothing whatever. Defer to the ResizeObserver's first non-zero call.
        if (!(W > 0 && H > 0)) return false;
        const xs = nodes.map((n) => n.x!).filter(Number.isFinite);
        const ys = nodes.map((n) => n.y!).filter(Number.isFinite);
        if (!xs.length || !ys.length) return false;
        const x0 = Math.min(...xs), x1 = Math.max(...xs);
        const y0 = Math.min(...ys), y1 = Math.max(...ys);
        const pad = 28;
        let k = Math.min((W - pad * 2) / Math.max(1, x1 - x0), (H - pad * 2) / Math.max(1, y1 - y0));
        if (!Number.isFinite(k)) k = 1;
        k = Math.max(0.05, Math.min(8, k));
        const tx = W / 2 - ((x0 + x1) / 2) * k, ty = H / 2 - ((y0 + y1) / 2) * k;
        const tr = Number.isFinite(tx) && Number.isFinite(ty)
            ? zoomIdentity.translate(tx, ty).scale(k)
            : zoomIdentity;
        select(canvas as any).call(zb.transform as any, tr);
        logMount(tr.k, tr.x, tr.y);
        return true;
    };

    const ro = new ResizeObserver(() => {
        sizeCanvas();
        if (!fitted) fitted = fit();          // first non-zero size wins
        else draw();
    });
    ro.observe(host);

    draw();                                   // at least one draw after the 300 ticks
    fitted = fit();                           // and one after the fit
    return api;
}
