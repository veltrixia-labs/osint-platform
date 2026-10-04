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
};
type RGraph = { meta: any; nodes: RNode[]; edges: REdge[] };

const esc = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

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
function search(q: string): RNode[] {
    const needle = q.trim().toLowerCase();
    if (!needle) return [];
    const scored: Array<{ n: RNode; rank: number }> = [];
    for (const n of BY_ID.values()) {
        const id = n.id.toLowerCase();
        let rank = -1;
        if (id === needle) rank = 0;
        else if (id.startsWith(needle)) rank = 1;
        else if (id.includes(needle)) rank = 2;
        if (rank < 0 && n.title && n.title.toLowerCase().includes(needle)) rank = 3;
        if (rank < 0) for (const a of n.aliases || []) {
            if (a.toLowerCase().includes(needle)) { rank = 3; break; }
        }
        if (rank < 0) for (const t of n.listing || []) {
            const low = t.toLowerCase(), sym = low.split(':')[1] || '';
            if (low === needle || sym === needle || low.includes(needle)) { rank = 2; break; }
        }
        if (rank >= 0) scored.push({ n, rank });
    }
    scored.sort((a, b) => a.rank - b.rank || a.n.id.localeCompare(b.n.id));
    return scored.slice(0, 8).map((x) => x.n);
}

function nodeCardHtml(n: RNode): string {
    const chips = (n.listing || []).map((t) => `<span class="rv-chip">${esc(t)}</span>`).join('');
    const dom = (n.domain || []).join(' · ');
    const meta = [n.type, dom, n.country].filter(Boolean).map((x) => esc(String(x))).join(' · ');
    return `<div class="rv-card">
        <div class="rv-card-title">${esc(n.title || n.id)}</div>
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
    if (hasW && e.weight === null) w = `<span class="rv-unmeasured">未測定</span>`;
    else if (hasW && e.weight != null) {
        const unit = e.unit ? ` <span class="pm-co-unit">${esc(e.unit)}</span>` : '';
        w = `${e.weight}${unit}`;
    }
    const role = e.role ? ` · ${esc(e.role)}` : '';
    // Verbatim the pro_interactive_map ternary.
    const ws = e.weight_source == null
        ? (hasW && e.weight != null ? 'unlabelled' : '')
        : String(e.weight_source);
    const wsCls = ws === 'observed' ? 'obs' : ws === 'estimated' ? 'est' : 'unk';
    const prov = ws ? ` <span class="pm-co-src pm-co-src--${wsCls}">${esc(ws)}</span>` : '';
    const vs = e.verify_status
        ? ` <span class="rv-vs rv-vs--${e.verify_status === 'verified' ? 'ok' : 'no'}">${esc(e.verify_status)}</span>`
        : '';
    const src = e.source ? ` <a class="rv-src" href="${esc(e.source)}" target="_blank" rel="noopener" title="${esc(e.source)}">↗</a>` : '';
    const tip = e.basis_short ? ` title="${esc(e.basis_short)}"` : '';
    return `<div class="pm-co-nb"${tip}>
        <span class="pm-co-nb-t"><span class="rv-dir">${dir}</span> <a class="rv-link" data-goto="${esc(other)}">${esc(other)}</a></span>
        <span class="pm-co-nb-rel">${esc(e.type)}${role}${prov}${vs}${src}</span>
        <span class="pm-co-nb-w">${w}</span>
    </div>`;
}

function neighbourHtml(id: string): string {
    const all = neighbours(id);
    if (!all.length) return `<div class="rv-empty">no recorded relationships</div>`;
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
        `<div class="pm-co-nb"><span class="pm-co-nb-t"><a class="rv-link" data-goto="${esc(n)}">${esc(n)}</a></span>
         <span class="pm-co-nb-rel">via ${esc(via)}</span><span class="pm-co-nb-w"></span></div>`).join('');
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
      <div class="rv-root">
        <div class="rv-head">
          <input class="rv-search" type="search" placeholder="Search an entity — name, 別名, or ticker (TSMC / 台湾積体電路製造 / 2330)" autocomplete="off" />
          <div class="rv-meta">${g.nodes.length} entities · ${g.edges.length} relationships · ${IS_PRO ? 'full provenance' : 'structure only'}</div>
          <div class="rv-results"></div>
        </div>
        <div class="rv-body">
          <div class="rv-canvas-host"></div>
          <aside class="rv-panel">
            ${IS_PRO ? '' : '<div class="rv-freeline">FREE — relationships only; upgrade for weights &amp; sources</div>'}
            <div class="rv-detail"></div>
          </aside>
        </div>
        <div class="rv-legend">${legend}<span class="rv-leg rv-leg--ring"><i></i>country = ring</span></div>
      </div>`;
    const input = container.querySelector('.rv-search') as HTMLInputElement;
    const results = container.querySelector('.rv-results') as HTMLElement;
    const detail = container.querySelector('.rv-detail') as HTMLElement;
    const cHost = container.querySelector('.rv-canvas-host') as HTMLElement;

    const idle = () =>
        `<div class="rv-idle">${g.nodes.length} entities · ${g.edges.length} relationships<br>
         <span class="rv-hint">Click a node, or search, to see what the vault records about it.</span></div>`;
    detail.innerHTML = idle();

    let handle: CanvasHandle | null = null;
    const show = (id: string | null, fromCanvas = false) => {
        if (!id) { detail.innerHTML = idle(); if (!fromCanvas) handle?.select(null); return; }
        const n = BY_ID.get(id);
        if (!n) return;
        results.innerHTML = '';
        detail.innerHTML = nodeCardHtml(n) + neighbourHtml(id) + twoHopHtml(id);
        detail.scrollTop = 0;
        if (!fromCanvas) handle?.focus(id); else handle?.select(id);
    };

    // The canvas owns positions; the panel owns provenance. A click in either drives the other.
    // ★ Guarded: a throw inside the canvas used to leave an empty <canvas> of the correct size
    //   with a working panel beside it — indistinguishable from "the layout produced nothing".
    //   Now it says so, and the list still works without the picture.
    try {
        handle = mountGraphCanvas(
            cHost,
            g.nodes.map((n) => ({ id: n.id, type: n.type, country: n.country, title: n.title })),
            g.edges.map((e) => ({ s: e.s, t: e.t, type: e.type, weight: e.weight })),
            (id) => show(id, true),
        );
    } catch (err) {
        // eslint-disable-next-line no-console
        console.error('[relationship_view] graph canvas failed to mount; list still usable', err);
        cHost.innerHTML = `<div class="rv-empty">Graph canvas failed to mount — see console.<br>
            <span class="rv-hint">Search and the relationship list still work.</span></div>`;
    }
    const doSearch = () => {
        const q = input.value;
        detail.innerHTML = '';
        if (!q.trim()) { results.innerHTML = ''; return; }
        const hits = search(q);
        if (!hits.length) { results.innerHTML = `<div class="rv-empty">no match</div>`; return; }
        results.innerHTML = hits.map((n) =>
            `<button class="rv-hit" data-goto="${esc(n.id)}">
                <span class="rv-hit-id">${esc(n.title || n.id)}</span>
                <span class="rv-hit-meta">${esc(n.type || '')}${n.country ? ' · ' + esc(n.country) : ''}</span>
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
