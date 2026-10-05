/**
 * Relationship view — search an entity, see what the vault records about its relations.
 *
 * LIST-FIRST BY DESIGN. There is no canvas. The vault's graph is not geographic and a force
 * layout would assert adjacency the data does not carry; the panel the Pro map already had
 * (buildNeighbourhoodHtml) was always the part that answered the question. This promotes it
 * from a drawer to the primary view and puts a search box in front of it.
 *
 * REUSED VERBATIM from pro_interactive_map.ts's neighbourhood panel, so the styling comes for
 * free (style.css scopes these to #pro-map-container, which is where this mounts):
 *   .pm-co-sec / .pm-co-sec-h / .pm-co-count / .pm-co-nb-list / .pm-co-nb
 *   .pm-co-nb-t / .pm-co-nb-rel / .pm-co-nb-w / .pm-co-unit
 *   .pm-co-src / .pm-co-src--obs / .pm-co-src--est / .pm-co-src--unk
 * and the provenance ternary itself: a null weight_source on a WEIGHTED edge reads 'unlabelled'
 * (a gap in the record); on an unweighted edge it reads nothing at all (provenance was never
 * applicable, which is a different fact from a missing one).
 *
 * TIER. The free payload OMITS the provenance fields. This view renders what is present and
 * nothing else — on free the provenance columns are simply absent, never greyed placeholders,
 * because a greyed cell says "this edge has no source" and the truth is "your tier is not served
 * that field".
 */
import { apiClient } from '../api';
import { mountGraphCanvas, PALETTE, type CanvasHandle } from './relationship_graph_canvas';
import { mountGlobe, type GlobeHandle } from './relationship_globe';

type RNode = {
    id: string; type?: string | null; domain?: string[]; country?: string | null;
    title?: string | null; role?: string | null; aliases?: string[]; listing?: string[];
    layer?: string | null;
};
type REdge = {
    s: string; t: string; type: string; flow?: string | null; role?: string | null;
    weight?: number | null; unit?: string | null; weight_source?: string | null;
    verify_status?: string | null; materiality?: string | null; as_of?: string | null;
    retrieved?: string | null; source?: string | null; desc?: string | null;
    basis_short?: string | null;
    // Derived in the vault export, not authored: see export_relationships.py weight_kind().
    weight_kind?: string | null; weight_kind_label?: string | null; weight_scope?: string | null;
};
type RGraph = { meta: any; nodes: RNode[]; edges: REdge[] };

const esc = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/** Display label from the node id. Underscores to spaces, nothing else — the id IS the vault's
 *  identifier and an acronym must survive unchanged (TSMC, SMIC, OPEC, CATL, SOMO, PIF, DRC).
 *  No title-casing: that would turn TSMC into Tsmc. The server drops any CJK `title`, so this is
 *  the label for those nodes, and it asserts nothing the id does not already say. */
const humanize = (id: string): string => id.replace(/_/g, ' ');

let GRAPH: RGraph | null = null;
let BY_ID = new Map<string, RNode>();
let OUT = new Map<string, REdge[]>();
let IN = new Map<string, REdge[]>();
let IS_PRO = false;

/** Edges where the node is EITHER endpoint. The vault authors `competitor` single-sided and
 *  alphabetically (00_SCHEMA.md:46), so an out-edge-only view makes the alphabetically-later
 *  company look unconnected — BYD out 23 / in 2 against Volkswagen out 7 / in 18. Bidirectional
 *  is not a nicety here; one-directional is simply wrong. */
function neighbours(id: string): Array<{ e: REdge; other: string; dir: '→' | '←' }> {
    const out = (OUT.get(id) || []).map((e) => ({ e, other: e.t, dir: '→' as const }));
    const inc = (IN.get(id) || []).map((e) => ({ e, other: e.s, dir: '←' as const }));
    return [...out, ...inc];
}

/**
 * ★ A node with ZERO recorded relationships. Keyed on DEGREE, deliberately not on id and not on
 *   `layer`. Not on id because 00_SCHEMA.md now names PURE CONVERGENCE RECEIVER as a sanctioned
 *   convention that may gain members, so a SIPRI special case would silently rot. Not on `layer`
 *   because measurement kills it: 9 nodes carry `layer: index` and 8 of them have edges.
 *   Measured on the served payload: exactly one node qualifies today (SIPRI); the next most
 *   fragile is Memory_Price at degree 1, which is NOT a dead end because it has a neighbour.
 */
const isUnlinked = (id: string): boolean => neighbours(id).length === 0;

function index(g: RGraph) {
    GRAPH = g; BY_ID = new Map(); OUT = new Map(); IN = new Map();
    for (const n of g.nodes) BY_ID.set(n.id, n);
    for (const e of g.edges) {
        if (!OUT.has(e.s)) OUT.set(e.s, []);
        OUT.get(e.s)!.push(e);
        if (!IN.has(e.t)) IN.set(e.t, []);
        IN.get(e.t)!.push(e);
    }
    IS_PRO = (g.meta && g.meta.tier) === 'pro';
}

/** Search id ∪ aliases ∪ title ∪ listing. Case-insensitive substring; CJK needs no folding
 *  (toLowerCase is a no-op on it and substring works directly). A ticker matches on the bare
 *  symbol or the full EXCHANGE:SYMBOL. */
function search(q: string): Array<{ n: RNode; rank: number; tickerHit?: string | null }> {
    const needle = q.trim().toLowerCase();
    if (!needle) return [];
    const scored: Array<{ n: RNode; rank: number; tickerHit?: string | null }> = [];
    for (const n of BY_ID.values()) {
        const id = n.id.toLowerCase();
        let rank = -1;
        if (id === needle) rank = 0;
        else if (id.startsWith(needle)) rank = 1;
        else if (id.includes(needle)) rank = 2;
        // Index = id ∪ aliases ∪ listing. `title` is deliberately NOT indexed: the server drops
        // every CJK title, so indexing it would make search behave differently for the 15 nodes
        // whose title was Japanese than for the rest — a silent asymmetry.
        let tickerHit: string | null = null;
        if (rank < 0) for (const a of n.aliases || []) {
            if (a.toLowerCase().includes(needle)) { rank = 3; break; }
        }
        if (rank < 0) for (const t of n.listing || []) {
            const low = t.toLowerCase(), sym = low.split(':')[1] || '';
            if (low === needle || sym === needle || low.includes(needle)) { rank = 2; tickerHit = t; break; }
        }
        if (rank >= 0) scored.push({ n, rank, tickerHit });
    }
    scored.sort((a, b) => a.rank - b.rank || a.n.id.localeCompare(b.n.id));
    return scored.slice(0, 8);
}

function nodeCardHtml(n: RNode): string {
    const chips = (n.listing || []).map((t) => `<span class="rv-chip">${esc(t)}</span>`).join('');
    const dom = (n.domain || []).join(' · ');
    const meta = [n.type, dom, n.country].filter(Boolean).map((x) => esc(String(x))).join(' · ');
    return `<div class="rv-card">
        <div class="rv-card-title">${esc(humanize(n.id))}</div>
        <div class="rv-card-meta">${meta}</div>
        ${n.role ? `<div class="rv-card-role">${esc(n.role)}</div>` : ''}
        ${chips ? `<div class="rv-chips">${chips}</div>` : ''}
    </div>`;
}

function rowHtml(e: REdge, other: string, dir: '→' | '←'): string {
    const hasW = Object.prototype.hasOwnProperty.call(e, 'weight');
    // Three weight states, kept apart exactly as the export keeps them: key absent = the edge
    // type carries no weight by design; explicit null = magnitude never measured; number = a value.
    let w = '';
    if (hasW && e.weight === null) w = `<span class="rv-unmeasured">not measured</span>`;
    else if (hasW && e.weight != null) {
        // ★ THE NUMBER IS PRINTED VERBATIM, never reformatted. A share of 0.527
        //   (Germany→Nord_Stream) is a different authored value from 0.55 (Germany→Russia), and
        //   the vault holds those two in separate fields precisely because they are not the same
        //   quantity. Rounding to a fixed 2dp on the way to a product surface would silently
        //   merge them, so the illustrative "0.50" in the brief is NOT implemented as toFixed(2).
        const kind = e.weight_kind || '';
        const label = kind && kind !== 'unclassified'
            ? e.weight_kind_label || ''
            // An unclassified kind means the vault has not tagged this edge's basis yet. Say
            // that, rather than borrowing a neighbouring edge's meaning for it.
            : `${e.unit || 'share'} · basis not tagged`;
        const lab = label ? ` <span class="rv-wkind">· ${esc(label)}</span>` : '';
        w = `${e.weight}${lab}`;
    }
    const role = e.role ? ` · ${esc(e.role)}` : '';
    // Verbatim the pro_interactive_map ternary.
    // ★ 'unlabelled' read as a judgement about the edge. It is a judgement about the RECORD:
    //   36 numeric-weight edges carry no weight_source field at all, and they include
    //   load-bearing pins (Germany→Russia 0.55, the Tether bridge). "source not recorded" says
    //   what is actually true — nobody wrote it down — without implying the weight is suspect.
    const ws = e.weight_source == null
        ? (hasW && e.weight != null ? 'source not recorded' : '')
        : String(e.weight_source);
    const wsCls = ws === 'observed' ? 'obs' : ws === 'estimated' ? 'est' : 'unk';
    const wsExtra = ws === 'source not recorded' ? ' rv-src-none' : '';
    const prov = ws ? ` <span class="pm-co-src pm-co-src--${wsCls}${wsExtra}">${esc(ws)}</span>` : '';
    const vs = e.verify_status
        ? ` <span class="rv-vs rv-vs--${e.verify_status === 'verified' ? 'ok' : 'no'}">${esc(e.verify_status)}</span>`
        : '';
    const src = e.source ? ` <a class="rv-src" href="${esc(e.source)}" target="_blank" rel="noopener" title="${esc(e.source)}">↗</a>` : '';
    const tip = e.basis_short ? ` title="${esc(e.basis_short)}"` : '';
    return `<div class="pm-co-nb"${tip}>
        <span class="pm-co-nb-t"><span class="rv-dir">${dir}</span> <a class="rv-link" data-goto="${esc(other)}">${esc(humanize(other))}</a></span>
        <span class="pm-co-nb-rel">${esc(e.type)}${role}${prov}${vs}${src}</span>
        <span class="pm-co-nb-w">${w}</span>
    </div>`;
}

function neighbourHtml(id: string): string {
    const all = neighbours(id);
    if (!all.length) {
        // ★ THE BUG THIS REPLACES: three words under an empty canvas, on a surface whose whole
        //   job is "if this moves, what else moves". It stated a fact and explained nothing.
        //   What this says instead is only what the payload actually supports — 0 of N
        //   relationships — and it does NOT claim the node is a citation source, because the
        //   served payload carries no field saying so. The vault knows; this surface does not.
        //   See the commit message for the vault-side proposal that would let it say more.
        const total = GRAPH?.edges.length ?? 0;
        return `<div class="rv-unlinked">
            <div class="rv-unlinked-h">No relationships recorded</div>
            <p>This entity is held in the vault in its own right, but it takes part in
               <strong>0 of ${total.toLocaleString()}</strong> recorded relationships. The explorer draws
               relationships, so there is nothing to draw for it — its own attributes are above.</p>
        </div>`;
    }
    const groups = new Map<string, typeof all>();
    for (const x of all) {
        if (!groups.has(x.e.type)) groups.set(x.e.type, []);
        groups.get(x.e.type)!.push(x);
    }
    const order = [...groups.keys()].sort((a, b) => groups.get(b)!.length - groups.get(a)!.length || a.localeCompare(b));
    const secs = order.map((t) => {
        const rows = groups.get(t)!.slice().sort((a, b) => {
            const aw = a.e.weight != null ? 0 : 1, bw = b.e.weight != null ? 0 : 1;   // weighted first
            return aw - bw || a.other.localeCompare(b.other);
        });
        return `<section class="pm-co-sec">
            <div class="pm-co-sec-h">${esc(t)} <span class="pm-co-count">${rows.length}</span></div>
            <div class="pm-co-nb-list">${rows.map((x) => rowHtml(x.e, x.other, x.dir)).join('')}</div>
        </section>`;
    }).join('');
    return `<div class="rv-nb-total">${all.length} relationships</div>${secs}`;
}

/** Second hop, Pro only, capped at 40. Collapsed by default: it is context, not an assertion —
 *  a 2-hop path is not a relationship the vault authored, it is two that happen to share a node. */
function twoHopHtml(id: string): string {
    if (!IS_PRO) return '';
    const first = new Set(neighbours(id).map((x) => x.other));
    const seen = new Map<string, string>();
    for (const a of first) {
        for (const x of neighbours(a)) {
            if (x.other === id || first.has(x.other) || seen.has(x.other)) continue;
            seen.set(x.other, a);
            if (seen.size >= 40) break;
        }
        if (seen.size >= 40) break;
    }
    if (!seen.size) return '';
    const rows = [...seen.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([n, via]) =>
        `<div class="pm-co-nb"><span class="pm-co-nb-t"><a class="rv-link" data-goto="${esc(n)}">${esc(humanize(n))}</a></span>
         <span class="pm-co-nb-rel">via ${esc(humanize(via))}</span><span class="pm-co-nb-w"></span></div>`).join('');
    return `<details class="rv-2hop"><summary>2 hops <span class="pm-co-count">${seen.size}</span>${seen.size >= 40 ? ' (capped)' : ''}</summary>
        <div class="pm-co-nb-list">${rows}</div></details>`;
}

export function resetRelationshipView() { GRAPH = null; }

export async function renderRelationshipView(container: HTMLElement): Promise<void> {
    container.innerHTML = `<div class="rv-loading">Loading relationship graph…</div>`;
    if (!GRAPH) {
        // ★ Report WHAT failed. The first version rendered a bare "unavailable" and swallowed the
        //   status, which cost a diagnosis session: the backend was a process started 69 days
        //   before the route existed and without --reload, so /api/relationships was a
        //   router-level 404 while every older route still answered 200. A 404 here means the
        //   route is not registered in the RUNNING app (stale process, or not deployed); a 503
        //   means the app is up but relationship_graph.json is missing from data/scenarios/.
        const url = '/relationships';
        try {
            const resp = await apiClient.get(url, { cache: 'no-store' });
            if (!resp.ok) {
                let body = '';
                try { body = (await resp.text()).slice(0, 200); } catch { /* body already consumed */ }
                console.error(`[relationship_view] GET ${url} -> ${resp.status} ${resp.statusText}`, body);
                const hint = resp.status === 404
                    ? 'route not registered in the running backend — restart it, or it is not deployed'
                    : resp.status === 503
                        ? 'backend is up but data/scenarios/relationship_graph.json is missing'
                        : 'see console for the response body';
                container.innerHTML = `<div class="rv-empty">Relationship graph unavailable — HTTP ${resp.status}.<br><span class="rv-hint">${esc(hint)}</span></div>`;
                return;
            }
            index((await resp.json()) as RGraph);
        } catch (err) {
            console.error(`[relationship_view] GET ${url} failed before a response`, err);
            container.innerHTML = `<div class="rv-empty">Relationship graph unavailable — no response.<br><span class="rv-hint">network/proxy error; see console</span></div>`;
            return;
        }
    }
    const g = GRAPH!;
    const legend = Object.entries(PALETTE)
        .map(([t, c]) => `<span class="rv-leg"><i style="background:${c}"></i>${esc(t)}</span>`).join('');
    container.innerHTML = `
      <div class="rv-root" tabindex="-1">
        <div class="rv-head">
          <input class="rv-search" type="search" placeholder="Search a company, country, or resource — name or ticker (TSMC / TSM / 2330)" autocomplete="off" />
          <div class="rv-meta">${g.nodes.length} entities · ${g.edges.length} relationships · ${IS_PRO ? 'full provenance' : 'structure only'} — click a node, or search, to see what the vault records about it.</div>
          <div class="rv-results"></div>
          <div class="rv-toolbar">
            <div class="rv-modes" role="tablist">
              <button class="rv-mode" data-mode="graph" aria-selected="true">Graph</button>
              <button class="rv-mode" data-mode="globe" aria-selected="false">Globe</button>
            </div>
            <button class="rv-fs" type="button" aria-pressed="false" title="Full screen (F)">⤢ Expand</button>
          </div>
        </div>
        <!-- ★ .rv-body is a COLUMN FLEX BOX and the dock strip lives INSIDE it, not as a
             sibling. As a sibling of .rv-body the strip was simply never visible: .rv-body
             carried min-height:70vh, a flex item cannot shrink below its own min-height, so
             head + 70vh + strip + legend overflowed #pro-map-container's
             height:calc(100vh - 80px) and .rv-root{overflow:hidden} clipped the strip off the
             bottom — with nothing to scroll, because the clip is on an ancestor. -->
        <div class="rv-body">
          <div class="rv-canvas-host"></div>
          <!-- Globe only. Previously an absolutely-positioned overlay ON the map, covering its
               bottom 76px (42vh expanded) and hiding the southern hemisphere. -->
          <div class="rv-dockstrip" hidden></div>
          <aside class="rv-panel" data-open="0" data-collapsed="0">
            <button class="rv-collapse" type="button" aria-label="Collapse panel" title="Collapse"></button>
            <button class="rv-close" type="button" aria-label="Close">&times;</button>
            ${IS_PRO ? '' : '<div class="rv-freeline">FREE — relationships only; upgrade for weights &amp; sources</div>'}
            <div class="rv-detail"></div>
          </aside>
        </div>
        <div class="rv-legend">${legend}<span class="rv-leg rv-leg--ring"><i></i>country = ring</span>
          <!-- ★ Tilt was reachable by right-drag / ctrl-drag and two-finger drag before this and
               NOTHING in the UI said so. The NavigationControl's compass visualises pitch once
               you are tilted, which tells you where you ARE, not that you can get there. -->
          <span class="rv-leg rv-hint-globe">globe: drag to pan · scroll to zoom · right-drag or ctrl-drag to tilt</span></div>
      </div>`;
    const input = container.querySelector('.rv-search') as HTMLInputElement;
    const results = container.querySelector('.rv-results') as HTMLElement;
    const detail = container.querySelector('.rv-detail') as HTMLElement;
    const cHost = container.querySelector('.rv-canvas-host') as HTMLElement;
    const dockStrip = container.querySelector('.rv-dockstrip') as HTMLElement;

    const panel = container.querySelector('.rv-panel') as HTMLElement;
    const root = container.querySelector('.rv-root') as HTMLElement;
    const fsBtn = container.querySelector('.rv-fs') as HTMLButtonElement;
    const collapseBtn = container.querySelector('.rv-collapse') as HTMLButtonElement;

    /** ★ 380 -> 320. These three MUST move together with the media query and the .rv-panel
     *  width in style.css; nothing links them, so they are named here and cited there. */
    const PANEL_W = 320;
    const PANEL_TAB = 24;          // what stays on screen when collapsed
    const SHEET_BP = 1200;         // below this the drawer is a bottom sheet, not a side panel

    /** In-memory for the session, deliberately NOT localStorage — the brief asked for session
     *  state, and a remembered-collapsed drawer would make the next visit look like the panel
     *  is broken. */
    let panelCollapsed = false;

    /** How much of the viewport the drawer is actually covering right now. Zero when closed or
     *  collapsed to its tab — a collapsed drawer should not push the fit target around. */
    const panelOffset = () =>
        (panel.dataset.open === '1' ? (panelCollapsed ? PANEL_TAB : PANEL_W) : 0);
    const applyOffset = () => {
        // The canvas only ever needs the horizontal offset; as a bottom sheet it covers nothing
        // the canvas pans into, so it reports 0 there.
        handle?.setPanelOffset(window.innerWidth < SHEET_BP ? 0 : panelOffset());
        globe?.setPanelOffset(panelOffset());
    };

    // ★ ALL MUTABLE VIEW STATE IS DECLARED HERE, IN ONE BLOCK, AND THAT IS THE FIX FOR A REAL
    //   CRASH — not a tidy-up. `let globe` used to be declared ~140 lines further down, next to
    //   mountGlobeMode(). applyOffset() above reads BOTH handles, and paintCollapse() calls it
    //   eagerly during setup, which landed in `globe`'s temporal dead zone and threw
    //   "ReferenceError: Cannot access 'globe' before initialization" — killing the rest of
    //   renderRelationshipView(), including the mountGraph() call at the very end. The chrome
    //   still rendered because container.innerHTML had already run, so the view looked laid out
    //   and simply had no graph in it.
    //   A `typeof globe` guard would have silenced the throw and left the drawer offset
    //   silently wrong on first paint. Declaring the state before its readers removes the
    //   window instead of surviving it.
    let handle: CanvasHandle | null = null;
    let globe: GlobeHandle | null = null;
    let mode: 'graph' | 'globe' = 'graph';
    root.dataset.mode = mode;      // initial state; setMode() keeps it in step
    let selectedId: string | null = null;
    // ★ NO globe.resize() HERE ANY MORE, in either direction. The drawer is position:absolute
    //   inside .rv-body, so opening it changes nothing about the map container's box — the
    //   resize was a no-op that cost a full MapLibre re-layout on every selection, and on the
    //   close path it was deferred into a rAF for a transition that never moved the container.
    //   The drawer's effect on framing is carried entirely by setPanelOffset -> fitEgo padding.
    const closePanel = () => { panel.dataset.open = '0'; applyOffset(); };
    // declared before use by show(); assigned once the modes exist
    const show = (id: string | null, fromCanvas = false) => {
        if (!id) { closePanel(); if (!fromCanvas) handle?.select(null); return; }
        const n = BY_ID.get(id);
        if (!n) return;
        results.innerHTML = '';
        detail.innerHTML = nodeCardHtml(n) + neighbourHtml(id) + twoHopHtml(id);
        detail.scrollTop = 0;
        panel.dataset.open = '1';
        // ★ The drawer overlays the canvas rather than reflowing it, so the selected node would
        //   sit under it without this: shift the zoom target clear of the drawer.
        applyOffset();
        if (!fromCanvas) { handle?.focus(id); globe?.focus(id); } else { handle?.select(id); globe?.select(id); }
    };
    panel.querySelector('.rv-close')!.addEventListener('click', () => { show(null); handle?.select(null); });

    // ── collapse / expand ─────────────────────────────────────────────────────────────────
    const paintCollapse = () => {
        panel.dataset.collapsed = panelCollapsed ? '1' : '0';
        collapseBtn.setAttribute('aria-label', panelCollapsed ? 'Expand panel' : 'Collapse panel');
        collapseBtn.title = panelCollapsed ? 'Expand' : 'Collapse';
        applyOffset();
    };
    collapseBtn.addEventListener('click', () => { panelCollapsed = !panelCollapsed; paintCollapse(); });
    paintCollapse();

    // ── full screen ───────────────────────────────────────────────────────────────────────
    //
    // ★ WHAT IS GUARDED, AND WHY EACH ONE IS REAL:
    //   • Safari / older WebKit expose webkitRequestFullscreen / webkitExitFullscreen /
    //     webkitFullscreenElement and fire `webkitfullscreenchange`, not the unprefixed names.
    //   • iOS Safari has NO element fullscreen at all — only <video> — so `requestFullscreen`
    //     is simply absent on HTMLElement there. That is the main reason a fallback exists
    //     rather than a feature-detect-and-disable.
    //   • requestFullscreen() returns a PROMISE THAT CAN REJECT even where it exists: without a
    //     user activation, or when a Permissions-Policy / iframe `allow` omits `fullscreen`.
    //     An unhandled rejection there would leave the button dead with no explanation, so the
    //     catch falls through to the CSS path instead of logging and giving up.
    //   Not guarded: ms-prefixed IE11, which this bundle does not support at all.
    const fsEl = (): Element | null =>
        document.fullscreenElement ?? (document as any).webkitFullscreenElement ?? null;
    const canNativeFs = typeof (root as any).requestFullscreen === 'function'
        || typeof (root as any).webkitRequestFullscreen === 'function';
    let pseudo = false;                       // the CSS fallback is active
    const isFs = () => fsEl() === root || pseudo;

    const paintFs = () => {
        const on = isFs();
        fsBtn.textContent = on ? '⤡ Exit' : '⤢ Expand';
        fsBtn.setAttribute('aria-pressed', String(on));
        fsBtn.title = on ? 'Exit full screen (F or Esc)' : 'Full screen (F)';
        root.classList.toggle('rv-pseudo-fs', pseudo);
    };

    /** ★ Re-measure AFTER the transition settles, not on the same frame. Entering fullscreen
     *  resizes the element asynchronously; measuring immediately gives the OLD box. Double rAF
     *  is the floor, and `fullscreenchange` (which calls this) has already fired by then. The
     *  canvas has a ResizeObserver that would eventually catch up on its own — this exists so
     *  there is no stretched frame in between. */
    const afterResize = () => requestAnimationFrame(() => requestAnimationFrame(() => {
        handle?.resize();
        globe?.resize();
        globe?.refit();
    }));

    const enterFs = async () => {
        if (canNativeFs) {
            try {
                const r: any = (root as any).requestFullscreen
                    ? (root as any).requestFullscreen()
                    : (root as any).webkitRequestFullscreen();
                if (r && typeof r.then === 'function') await r;
                return;                        // fullscreenchange paints and resizes
            } catch {
                /* rejected — fall through to the CSS path below */
            }
        }
        pseudo = true; paintFs(); afterResize();
    };
    const exitFs = async () => {
        if (fsEl() === root) {
            try {
                const r: any = document.exitFullscreen
                    ? document.exitFullscreen()
                    : (document as any).webkitExitFullscreen();
                if (r && typeof r.then === 'function') await r;
                return;
            } catch { /* fall through and clear the CSS path too */ }
        }
        pseudo = false; paintFs(); afterResize();
    };
    const toggleFs = () => { void (isFs() ? exitFs() : enterFs()); };
    fsBtn.addEventListener('click', toggleFs);

    const onFsChange = () => { if (fsEl() !== root) pseudo = false; paintFs(); afterResize(); };
    document.addEventListener('fullscreenchange', onFsChange);
    document.addEventListener('webkitfullscreenchange', onFsChange as EventListener);

    // Clicking anywhere in the view focuses its root, so "F when the view has focus" has a
    // definite meaning instead of depending on whether the last click landed on a button.
    root.addEventListener('mousedown', () => {
        if (!root.contains(document.activeElement)) root.focus({ preventScroll: true });
    });

    const onKey = (ev: KeyboardEvent) => {
        // ★ SELF-REMOVING. renderRelationshipView() replaces container.innerHTML on every mount
        //   and there is no view-level teardown to hook, so a document listener from a previous
        //   mount would otherwise live for the life of the page and drive a detached root.
        if (!document.body.contains(root)) {
            document.removeEventListener('keydown', onKey);
            document.removeEventListener('fullscreenchange', onFsChange);
            document.removeEventListener('webkitfullscreenchange', onFsChange as EventListener);
            return;
        }
        const t = ev.target as HTMLElement | null;
        const typing = !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
        if (typing) return;
        if (ev.key === 'Escape' && pseudo) { ev.preventDefault(); void exitFs(); return; }
        // F only acts when the view actually has focus, OR when it is already fullscreen (so the
        // key that got you in can get you out). Anything looser steals F from the whole app.
        if ((ev.key === 'f' || ev.key === 'F') && !ev.metaKey && !ev.ctrlKey && !ev.altKey
            && (root.contains(document.activeElement) || isFs())) {
            ev.preventDefault(); toggleFs();
        }
    };
    document.addEventListener('keydown', onKey);
    paintFs();

    // The canvas owns positions; the panel owns provenance. A click in either drives the other.
    // ★ Guarded: a throw inside the canvas used to leave an empty <canvas> of the correct size
    //   with a working panel beside it — indistinguishable from "the layout produced nothing".
    //   Now it says so, and the list still works without the picture.

    const mountGraph = () => {
        try {
            handle = mountGraphCanvas(
                cHost,
                g.nodes.map((n) => ({ id: n.id, type: n.type, country: n.country, title: n.title })),
                g.edges.map((e) => ({ s: e.s, t: e.t, type: e.type, weight: e.weight })),
                (id) => { selectedId = id; show(id, true); },
            );
        } catch (err) {
            // eslint-disable-next-line no-console
            console.error('[relationship_view] graph canvas failed to mount; list still usable', err);
            cHost.innerHTML = `<div class="rv-empty">Graph canvas failed to mount — see console.<br>
                <span class="rv-hint">Search and the relationship list still work.</span></div>`;
        }
    };
    const mountGlobeMode = async () => {
        try {
            const r = await apiClient.get('/relationships/coordinates', { cache: 'no-store' });
            if (!r.ok) throw new Error(`coordinates ${r.status}`);
            const coords = ((await r.json()) as any).nodes as Record<string, any>;
            globe = mountGlobe(
                cHost,
                dockStrip,
                g.nodes.map((n) => ({ id: n.id, type: n.type, country: n.country })),
                g.edges.map((e) => ({ s: e.s, t: e.t, type: e.type, weight: e.weight })),
                coords,
                (id) => { selectedId = id; show(id, true); },
            );
        } catch (err) {
            // ★ Show the message. "see console" cost a whole diagnosis sitting: the failure is
            //   readable from a screenshot only if the text is on screen.
            const msg = err instanceof Error ? (err.message || err.name) : String(err);
            // eslint-disable-next-line no-console
            console.error('[relationship_view] globe failed to mount', err);
            cHost.innerHTML = `<div class="rv-empty">Globe unavailable.<br>
                <span class="rv-hint">${esc(msg)}</span></div>`;
        }
    };

    // Both modes share one selection, one search and one drawer. Switching re-mounts the canvas
    // host and re-applies the current selection, so the view never loses its place.
    const setMode = async (m: 'graph' | 'globe') => {
        if (m === mode) return;
        mode = m;
        // Lets CSS target the active mode — the globe-only interaction hint in the legend uses
        // it, so the hint does not advertise tilt while the force-directed canvas is showing.
        root.dataset.mode = m;
        handle?.destroy(); handle = null;
        globe?.destroy(); globe = null;
        cHost.innerHTML = '';
        dockStrip.hidden = true; dockStrip.innerHTML = '';
        for (const b of Array.from(container.querySelectorAll('.rv-mode'))) {
            (b as HTMLElement).setAttribute('aria-selected', String((b as HTMLElement).dataset.mode === m));
        }
        if (m === 'graph') mountGraph();
        else {
            await mountGlobeMode();
            // ★ The map was constructed while the host was still the previous mode's size.
            //   Resize and re-frame once the browser has laid the host out at its final width.
            requestAnimationFrame(() => requestAnimationFrame(() => globe?.refit()));
        }
        // TS narrows `handle`/`globe` to null from the assignments above and does not reset
        // that across the mount calls that reassign them, so read them back explicitly.
        const h = handle as CanvasHandle | null, gl = globe as GlobeHandle | null;
        if (selectedId) { h?.focus(selectedId); gl?.focus(selectedId); }
    };
    container.querySelectorAll('.rv-mode').forEach((b) =>
        b.addEventListener('click', () => void setMode((b as HTMLElement).dataset.mode as any)));

    mountGraph();
    const doSearch = () => {
        const q = input.value;
        detail.innerHTML = '';
        if (!q.trim()) { results.innerHTML = ''; return; }
        const hits = search(q);
        if (!hits.length) { results.innerHTML = `<div class="rv-empty">no match</div>`; return; }
        results.innerHTML = hits.map(({ n, tickerHit }) =>
            `<button class="rv-hit" data-goto="${esc(n.id)}">
                <span class="rv-hit-id">${esc(humanize(n.id))}</span>
                <span class="rv-hit-meta">${esc(n.type || '')}${n.country ? ' · ' + esc(n.country) : ''}${tickerHit ? ' · ' + esc(tickerHit) : ''}${isUnlinked(n.id) ? '<em class="rv-hit-unlinked"> · no relationships</em>' : ''}</span>
             </button>`).join('');
    };
    input.addEventListener('input', doSearch);
    container.addEventListener('click', (ev) => {
        const el = (ev.target as HTMLElement).closest('[data-goto]') as HTMLElement | null;
        if (el) { ev.preventDefault(); show(el.dataset.goto!); return; }
        const det = (ev.target as HTMLElement).closest('.rv-2hop') as HTMLDetailsElement | null;
        if (det) setTimeout(() => handle?.setTwoHop(det.open), 0);   // after <details> flips
    });
}
