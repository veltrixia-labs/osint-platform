/**
 * Pro Interactive Map — two-stage entry.
 *
 *   STAGE 1 (on open)  WHERE is something happening?
 *       One node per FIRING scenario, at its hub. No cascade, no arcs. The
 *       40-node propagation must not descend on the user before they have
 *       understood what they are looking at.
 *
 *   STAGE 2 (on click) WHAT does it affect?
 *       The full cascade — delegated to mountSpatialContagionMap(), which already
 *       owns the fan-out, the arcs and the hollow grey rings for unmeasured exposure.
 *
 * The two stages show DIFFERENT KINDS OF QUANTITY and are deliberately given
 * different visual languages:
 *   • Stage 1 = NEWS SIGNAL      (amber) — how loudly the world is talking.
 *   • Stage 2 = STRUCTURAL IMPACT (cyan→red) — what the vault's graph says propagates.
 * Headline volume never touches the cascade's numbers. Conflating them would be
 * fabrication.
 */
import { apiClient } from '../api';
import { renderSpatialContagionShell, mountSpatialContagionMap, injectMaplibreCss } from './pro_interactive_map';

const LOG = '[TriggerMap]';

// ── Wire types (mirror /pro/domains/scenarios/triggers) ──────────────────────
type MatchedAlert = {
    id: string;
    title: string;
    importance: number | null;      // 0-100; null = unscored, NEVER 0
    severity: string | null;
    triggered_at: string | null;
    matched_alias: string;
    source_url: string | null;
};

type ScenarioTrigger = {
    id: string;
    hub: string;
    label: string | null;
    aliases: string[];
    lat: number | null;
    lon: number | null;
    firing: boolean;
    match_count: number;
    max_importance: number | null;   // null = nothing matched / nothing scored
    latest_match_at: string | null;
    matched_alerts: MatchedAlert[];
};

type TriggerPayload = {
    window_hours: number;
    min_matches_to_fire: number;
    alerts_in_window: number;
    scenarios: ScenarioTrigger[];
};

// ── Display helpers ──────────────────────────────────────────────────────────

function esc(s: string): string {
    return String(s ?? '').replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string
    ));
}

/**
 * Name the HUB, never a premise. The payload asserts that a chokepoint is in the
 * news; it does NOT assert that the strait is closed. The headlines supply the event.
 */
function displayName(s: { aliases?: string[]; label?: string | null; hub?: string; id?: string }): string {
    const cjk = (s.aliases ?? []).find((a) => /[　-鿿＀-￯]/.test(a));
    return cjk || s.label || (s.hub ?? s.id ?? '').replace(/_/g, ' ');
}

/** Unknown is not zero. */
function fmtImportance(v: number | null): string {
    return v == null ? '--' : String(Math.round(v));
}

/** Marker radius encodes MATCH_COUNT only. sqrt so 40 alerts isn't 40x the area of 1. */
function markerRadiusPx(matchCount: number): number {
    return Math.round(Math.min(46, 18 + Math.sqrt(Math.max(0, matchCount)) * 5));
}

/**
 * Marker shade encodes MAX_IMPORTANCE only — a SEPARATE metric from size.
 * The two are never multiplied into one score; any weighting would be invented.
 * null (unscored) → neutral slate, and the badge reads "--".
 */
function markerShade(maxImportance: number | null): { fill: string; ring: string } {
    if (maxImportance == null) return { fill: 'rgba(148,163,184,0.20)', ring: '#94a3b8' };
    const t = Math.max(0, Math.min(1, maxImportance / 100));
    // amber (news signal) — deliberately NOT the cascade's cyan→red impact ramp.
    const light = 62 - 22 * t;   // higher importance → deeper amber
    return { fill: `hsla(38, 95%, ${light}%, 0.28)`, ring: `hsl(38, 95%, ${light}%)` };
}

function timeAgo(iso: string | null): string {
    if (!iso) return '';
    const ms = Date.now() - new Date(iso).getTime();
    if (!Number.isFinite(ms) || ms < 0) return '';
    const m = Math.floor(ms / 60000);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    return h < 24 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`;
}

// ── Controller ───────────────────────────────────────────────────────────────

/**
 * INVARIANT (same contract as SurveillanceMapController, 849c188): every DOM/map
 * write is `aborted`-guarded, and teardown removes listeners, timers AND observers.
 * A stopped controller can reach nothing. New subscriptions MUST register via
 * addCleanup() — no exceptions, or the invariant is not an invariant.
 */
class TriggerMapController {
    private aborted = false;
    private cleanups: Array<() => void> = [];
    private map: any = null;
    private markers: any[] = [];
    private payload: TriggerPayload | null = null;
    private readonly stageEl: HTMLElement;
    private readonly panelEl: HTMLElement;

    constructor(stageEl: HTMLElement, panelEl: HTMLElement) {
        this.stageEl = stageEl;
        this.panelEl = panelEl;
    }

    addCleanup(fn: () => void): void {
        if (this.aborted) { try { fn(); } catch { /* ignore */ } return; }
        this.cleanups.push(fn);
    }

    stop = (): void => {
        if (this.aborted) return;
        this.aborted = true;
        for (const fn of this.cleanups) {
            try { fn(); } catch { /* teardown must never throw */ }
        }
        this.cleanups.length = 0;
        this.disposeStage1Map();
    };

    /** Remove markers + the MapLibre instance. Idempotent. */
    private disposeStage1Map(): void {
        for (const m of this.markers) {
            try { m.remove(); } catch { /* ignore */ }
        }
        this.markers = [];
        try { this.map?.remove(); } catch { /* ignore */ }
        this.map = null;
    }

    async start(): Promise<void> {
        if (this.aborted) return;
        this.panelEl.innerHTML = `<div class="tm2-loading">Reading the alert stream…</div>`;
        try {
            const resp = await apiClient.get('/pro/domains/scenarios/triggers', { cache: 'no-store' }, true);
            if (this.aborted) return;                       // landed after stop()
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            this.payload = (await resp.json()) as TriggerPayload;
        } catch (err) {
            if (this.aborted) return;
            console.warn(`${LOG} trigger fetch failed`, err);
            this.panelEl.innerHTML = `
                <div class="tm2-empty">
                    <div class="tm2-empty-title">Trigger feed unavailable</div>
                    <div class="tm2-empty-sub">Could not read the alert stream. The map cannot say what is firing, so it says nothing.</div>
                </div>`;
            return;
        }
        if (this.aborted) return;
        await this.renderStage1();
    }

    // ── STAGE 1 — WHERE ──────────────────────────────────────────────────────

    private async renderStage1(): Promise<void> {
        if (this.aborted || !this.payload) return;
        this.disposeStage1Map();

        const p = this.payload;
        const firing = p.scenarios.filter((s) => s.firing && s.lat != null && s.lon != null);
        const dormant = p.scenarios.filter((s) => !s.firing);

        this.stageEl.innerHTML = `<div class="tm2-map" id="tm2-map"></div>`;
        this.renderPanel(firing, dormant, p);

        const mapEl = this.stageEl.querySelector<HTMLElement>('#tm2-map');
        if (!mapEl) return;

        // MapLibre's own stylesheet is REQUIRED: `.maplibregl-marker { position:absolute }`
        // is what lifts markers onto the map. Without it they fall into normal document
        // flow and land below the viewport — present in the DOM, invisible on screen.
        injectMaplibreCss();
        const maplibregl: any = await import('maplibre-gl');
        if (this.aborted) return;                            // import landed after stop()
        const MapCtor = maplibregl?.Map ?? maplibregl?.default?.Map;
        const MarkerCtor = maplibregl?.Marker ?? maplibregl?.default?.Marker;
        if (!MapCtor || !MarkerCtor) {
            console.error(`${LOG} maplibre exports missing`);
            return;
        }

        // Centre on the firing set; a stable world view when nothing fires.
        const lons = firing.map((s) => s.lon as number);
        const lats = firing.map((s) => s.lat as number);
        const center: [number, number] = firing.length
            ? [(Math.min(...lons) + Math.max(...lons)) / 2, (Math.min(...lats) + Math.max(...lats)) / 2]
            : [20, 25];

        this.map = new MapCtor({
            container: mapEl,
            style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
            center,
            zoom: firing.length === 1 ? 3.4 : 1.9,
            attributionControl: false,
        });
        this.addCleanup(() => this.disposeStage1Map());

        for (const s of firing) {
            const el = this.buildMarkerEl(s);
            const marker = new MarkerCtor({ element: el }).setLngLat([s.lon, s.lat]).addTo(this.map);
            this.markers.push(marker);
        }
    }

    /** One node per firing scenario. Size = match_count. Shade = max_importance. */
    private buildMarkerEl(s: ScenarioTrigger): HTMLElement {
        const r = markerRadiusPx(s.match_count);
        const { fill, ring } = markerShade(s.max_importance);
        const el = document.createElement('button');
        el.type = 'button';
        el.className = 'tm2-marker';
        el.setAttribute('aria-label', `${displayName(s)} — ${s.match_count} alerts`);
        el.style.width = `${r * 2}px`;
        el.style.height = `${r * 2}px`;
        el.innerHTML = `
            <span class="tm2-marker-dot" style="border-color:${ring}; background:${fill};"></span>
            <span class="tm2-marker-count" style="color:${ring};">${s.match_count}</span>
            <span class="tm2-marker-label">${esc(displayName(s))}</span>`;
        const onClick = (): void => { void this.enterStage2(s); };
        el.addEventListener('click', onClick);
        this.addCleanup(() => el.removeEventListener('click', onClick));
        return el;
    }

    // ── The receipts panel — WHY it is firing ────────────────────────────────

    private renderPanel(firing: ScenarioTrigger[], dormant: ScenarioTrigger[], p: TriggerPayload): void {
        if (this.aborted) return;

        const zero = firing.length === 0;
        const header = `
            <div class="tm2-head">
                <div class="tm2-head-title">Triggered by the news</div>
                <div class="tm2-head-sub">
                    ${p.alerts_in_window} alerts in the last ${p.window_hours} hours ·
                    ${p.min_matches_to_fire}+ matching headlines to fire
                </div>
            </div>`;

        const zeroState = `
            <div class="tm2-empty">
                <div class="tm2-empty-title">No scenario is currently triggered by the news.</div>
                <div class="tm2-empty-sub">
                    Nothing in the last ${p.window_hours} hours matched a scenario hub.
                    The map shows nothing rather than assert an event that is not happening.
                </div>
            </div>`;

        const cards = firing.map((s) => {
            const aliasList = Array.from(new Set(s.matched_alerts.map((m) => m.matched_alias)));
            const receipts = s.matched_alerts.map((m) => `
                <li class="tm2-receipt">
                    <div class="tm2-receipt-line">
                        ${m.source_url
                            ? `<a href="${esc(m.source_url)}" target="_blank" rel="noopener noreferrer">${esc(m.title)}</a>`
                            : esc(m.title)}
                    </div>
                    <div class="tm2-receipt-meta">
                        <span class="tm2-imp" title="Importance: an LLM-assigned score (0-100) for breadth of impact. Not a measured quantity.">imp ${fmtImportance(m.importance)}</span>
                        <span>·</span><span>${esc(m.severity ?? '')}</span>
                        <span>·</span><span>${esc(timeAgo(m.triggered_at))}</span>
                        <span>·</span><span class="tm2-alias">matched “${esc(m.matched_alias)}”</span>
                    </div>
                </li>`).join('');

            return `
                <div class="tm2-card">
                    <div class="tm2-card-head">
                        <span class="tm2-card-name">${esc(displayName(s))}</span>
                        <button type="button" class="tm2-view" data-scenario="${esc(s.id)}">View cascade →</button>
                    </div>
                    <div class="tm2-card-why">
                        Firing on <b>${s.match_count} alerts</b> in the last ${p.window_hours} hours —
                        matched on ${aliasList.map((a) => `“<b>${esc(a)}</b>”`).join(' / ')} in the headline.
                        Peak importance <b>${fmtImportance(s.max_importance)}</b> —
                        <span class="tm2-prov">LLM-scored breadth of impact, not a measured quantity</span>.
                    </div>
                    <div class="tm2-card-note">
                        Size and shade above are <b>news signal</b> — how loudly this is being reported.
                        They are not impact. The cascade’s numbers come from the structural graph.
                    </div>
                    <ul class="tm2-receipts">${receipts}</ul>
                    ${s.match_count > s.matched_alerts.length
                        ? `<div class="tm2-more">+ ${s.match_count - s.matched_alerts.length} more matching alerts</div>`
                        : ''}
                    <div class="tm2-foot">
                        <b>imp</b> = importance: an LLM-assigned score (0-100) for breadth of impact.
                        It is a judgement, not a measurement.
                    </div>
                </div>`;
        }).join('');

        const manual = dormant.length ? `
            <div class="tm2-manual">
                <div class="tm2-manual-head">Not in the news — explore manually</div>
                ${dormant.map((s) => `
                    <button type="button" class="tm2-manual-row" data-scenario="${esc(s.id)}">
                        <span>${esc(displayName(s))}</span>
                        <span class="tm2-manual-count">${s.match_count} alerts</span>
                    </button>`).join('')}
            </div>` : '';

        this.panelEl.innerHTML = header + (zero ? zeroState : cards) + manual;

        this.panelEl.querySelectorAll<HTMLButtonElement>('button[data-scenario]').forEach((btn) => {
            const id = btn.dataset.scenario;
            if (!id) return;
            const target = (this.payload?.scenarios ?? []).find((s) => s.id === id);
            if (!target) return;
            const onClick = (): void => { void this.enterStage2(target); };
            btn.addEventListener('click', onClick);
            this.addCleanup(() => btn.removeEventListener('click', onClick));
        });
    }

    // ── STAGE 2 — WHAT IT AFFECTS ────────────────────────────────────────────

    private async enterStage2(s: ScenarioTrigger): Promise<void> {
        if (this.aborted) return;
        this.disposeStage1Map();     // Stage 1's map must die before Stage 2 builds its own.

        this.panelEl.innerHTML = `
            <div class="tm2-head">
                <button type="button" class="tm2-back" id="tm2-back">← Back to triggers</button>
                <div class="tm2-head-title">${esc(displayName(s))}</div>
                <div class="tm2-head-sub">
                    Structural cascade from the vault graph.
                    <b>Not</b> derived from headline volume.
                </div>
            </div>
            <div class="tm2-legend">
                <div><span class="tm2-sw tm2-sw--epi"></span> epicenter</div>
                <div><span class="tm2-sw tm2-sw--aff"></span> affected (measured)</div>
                <div><span class="tm2-sw tm2-sw--unq"></span> exposed · magnitude unknown</div>
            </div>`;

        const back = this.panelEl.querySelector<HTMLButtonElement>('#tm2-back');
        if (back) {
            const onBack = (): void => { void this.renderStage1(); };
            back.addEventListener('click', onBack);
            this.addCleanup(() => back.removeEventListener('click', onBack));
        }

        this.stageEl.innerHTML = `<div class="tm2-loading">Loading cascade…</div>`;
        let sc: any = null;
        try {
            const resp = await apiClient.get(
                `/pro/domains/${encodeURIComponent(s.id)}/spatial-contagion`,
                { cache: 'no-store' },
                true,
            );
            if (this.aborted) return;
            if (resp.ok) sc = await resp.json();
        } catch (err) {
            console.warn(`${LOG} cascade fetch failed`, err);
        }
        if (this.aborted) return;

        if (!sc || !Array.isArray(sc.nodes) || sc.nodes.length === 0) {
            this.stageEl.innerHTML = `
                <div class="tm2-empty tm2-empty--stage">
                    <div class="tm2-empty-title">No cascade data for ${esc(displayName(s))}.</div>
                    <div class="tm2-empty-sub">The scenario is triggered, but its graph has not been loaded.</div>
                </div>`;
            return;
        }

        // Delegate to the existing cascade renderer: fan-out, arcs, and the hollow
        // grey rings for exposed_unquantified all come along unchanged.
        this.stageEl.innerHTML = renderSpatialContagionShell(sc, '01', s.id);
        await mountSpatialContagionMap(this.stageEl, sc, s.id, { staticScenario: true });
        if (this.aborted) return;
        // mountSpatialContagionMap installs its own teardown handle on the wrap element
        // (__scTeardown) and self-stops when that element leaves the DOM — which is exactly
        // what happens when renderStage1() replaces stageEl.innerHTML. No orphan.
    }
}

// ── Entry ────────────────────────────────────────────────────────────────────

let active: TriggerMapController | null = null;

/** Mount the two-stage Pro map into `container`. Idempotent per container. */
export function renderTriggerMap(container: HTMLElement): void {
    active?.stop();                 // never leave a previous controller running
    active = null;

    injectTriggerMapStyles();
    container.classList.add('tm2-host');
    // The host's own stylesheet may carry `#pro-map-container { display:none }` (an ID
    // selector outranks our class). The app normally overrides that inline on tab switch,
    // but the module must not depend on someone else's cooperation to be visible.
    container.style.display = 'flex';
    container.innerHTML = `
        <div class="tm2-stage" id="tm2-stage"></div>
        <aside class="tm2-panel" id="tm2-panel"></aside>`;

    const stageEl = container.querySelector<HTMLElement>('#tm2-stage');
    const panelEl = container.querySelector<HTMLElement>('#tm2-panel');
    if (!stageEl || !panelEl) return;

    const ctrl = new TriggerMapController(stageEl, panelEl);
    active = ctrl;
    void ctrl.start();
}

/** Explicit teardown, for route changes. */
export function disposeTriggerMap(): void {
    active?.stop();
    active = null;
}

function injectTriggerMapStyles(): void {
    if (document.getElementById('tm2-styles')) return;
    const st = document.createElement('style');
    st.id = 'tm2-styles';
    st.textContent = `
    .tm2-host { display:flex; gap:0 !important; padding:0 !important;
                height:calc(100vh - 80px); min-height:640px;
                background:#020617; color:#e2e8f0; }
    .tm2-stage { position:relative; flex:1 1 auto; min-width:0; }
    /* Specificity 0,2,0 on purpose. MapLibre stamps .maplibregl-map (position:relative)
       onto this same element, and its stylesheet loads AFTER ours -- a single class would
       lose the cascade on document order and the div would collapse to height 0. */
    .tm2-stage .tm2-map { position:absolute; inset:0; width:100%; height:100%; }
    .tm2-panel { flex:0 0 380px; max-width:380px; overflow-y:auto; padding:18px;
                 border-left:1px solid rgba(148,163,184,0.18); background:rgba(2,6,23,0.92); }

    .tm2-loading { display:flex; align-items:center; justify-content:center; height:100%;
                   color:#64748b; font-size:13px; }

    .tm2-head { margin-bottom:16px; }
    .tm2-head-title { font-size:17px; font-weight:800; letter-spacing:-0.01em; }
    .tm2-head-sub { margin-top:4px; font-size:11.5px; color:#64748b; line-height:1.5; }
    .tm2-back { background:transparent; border:1px solid rgba(148,163,184,0.35); color:#94a3b8;
                border-radius:6px; padding:5px 10px; font-size:11px; font-weight:700;
                cursor:pointer; margin-bottom:10px; }
    .tm2-back:hover { color:#e2e8f0; border-color:#94a3b8; }

    .tm2-empty { padding:22px 4px; }
    .tm2-empty--stage { display:flex; flex-direction:column; align-items:center;
                        justify-content:center; height:100%; text-align:center; }
    .tm2-empty-title { font-size:14px; font-weight:700; color:#cbd5e1; }
    .tm2-empty-sub { margin-top:8px; font-size:12px; color:#64748b; line-height:1.6; max-width:44ch; }

    .tm2-card { border:1px solid rgba(148,163,184,0.18); border-radius:10px;
                padding:14px; margin-bottom:14px; background:rgba(8,13,28,0.6); }
    .tm2-card-head { display:flex; align-items:center; justify-content:space-between; gap:8px; }
    .tm2-card-name { font-size:15px; font-weight:800; }
    .tm2-view { background:rgba(245,158,11,0.12); border:1px solid rgba(245,158,11,0.45);
                color:#fbbf24; border-radius:6px; padding:5px 9px; font-size:11px;
                font-weight:800; cursor:pointer; white-space:nowrap; }
    .tm2-view:hover { background:rgba(245,158,11,0.22); }
    .tm2-card-why { margin-top:8px; font-size:12px; color:#cbd5e1; line-height:1.6; }
    .tm2-card-note { margin-top:8px; padding-top:8px; border-top:1px solid rgba(148,163,184,0.14);
                     font-size:11px; color:#64748b; line-height:1.5; font-style:italic; }

    .tm2-receipts { list-style:none; margin:12px 0 0; padding:0; }
    .tm2-receipt { padding:8px 0; border-top:1px solid rgba(148,163,184,0.10); }
    .tm2-receipt-line a { color:#93c5fd; text-decoration:none; font-size:12px; line-height:1.45; }
    .tm2-receipt-line a:hover { text-decoration:underline; }
    .tm2-receipt-line { font-size:12px; line-height:1.45; color:#e2e8f0; }
    .tm2-receipt-meta { margin-top:3px; display:flex; gap:5px; flex-wrap:wrap;
                        font-size:10.5px; color:#64748b;
                        font-family:ui-monospace, Menlo, monospace; }
    .tm2-imp { color:#fbbf24; font-weight:700; }
    .tm2-alias { color:#94a3b8; }
    .tm2-more { margin-top:8px; font-size:11px; color:#64748b; }
    .tm2-prov { color:#94a3b8; font-style:italic; }
    .tm2-foot { margin-top:10px; padding-top:8px;
                border-top:1px solid rgba(148,163,184,0.14);
                font-size:10.5px; color:#64748b; line-height:1.5; }
    .tm2-foot b { color:#fbbf24; font-weight:700; }

    .tm2-manual { margin-top:18px; padding-top:14px; border-top:1px solid rgba(148,163,184,0.18); }
    .tm2-manual-head { font-size:10px; font-weight:800; letter-spacing:0.12em;
                       text-transform:uppercase; color:#64748b; margin-bottom:8px; }
    .tm2-manual-row { display:flex; width:100%; align-items:center; justify-content:space-between;
                      background:transparent; border:1px solid rgba(148,163,184,0.18);
                      color:#94a3b8; border-radius:8px; padding:9px 11px; margin-bottom:6px;
                      font-size:12px; cursor:pointer; }
    .tm2-manual-row:hover { color:#e2e8f0; border-color:#475569; }
    .tm2-manual-count { font-size:10.5px; color:#475569;
                        font-family:ui-monospace, Menlo, monospace; }

    .tm2-legend { display:flex; flex-direction:column; gap:6px; margin-top:14px;
                  font-size:11.5px; color:#94a3b8; }
    .tm2-legend > div { display:flex; align-items:center; gap:8px; }
    .tm2-sw { width:11px; height:11px; border-radius:50%; display:inline-block; }
    .tm2-sw--epi { background:#ef4444; }
    .tm2-sw--aff { background:#22d3ee; }
    .tm2-sw--unq { background:transparent; border:1.5px solid #94a3b8; }

    /* Stage-1 marker: AMBER = news signal. Deliberately NOT the cascade's impact ramp. */
    .tm2-marker { position:relative; display:flex; align-items:center; justify-content:center;
                  background:transparent; border:0; padding:0; cursor:pointer; }
    .tm2-marker-dot { position:absolute; inset:0; border-radius:50%; border-width:2px;
                      border-style:solid; animation:tm2-pulse 2.4s ease-in-out infinite; }
    .tm2-marker-count { position:relative; font-size:13px; font-weight:800;
                        font-family:ui-monospace, Menlo, monospace; pointer-events:none; }
    .tm2-marker-label { position:absolute; top:100%; left:50%; transform:translateX(-50%);
                        margin-top:5px; white-space:nowrap; font-size:11px; font-weight:700;
                        color:#e2e8f0; text-shadow:0 1px 4px #000; pointer-events:none; }
    @keyframes tm2-pulse {
        0%,100% { box-shadow:0 0 0 0 rgba(245,158,11,0.28); }
        50%     { box-shadow:0 0 0 10px rgba(245,158,11,0); }
    }
    @media (max-width: 900px) {
        .tm2-host { flex-direction:column; height:auto; }
        .tm2-stage { height:52vh; }
        .tm2-panel { flex:1 1 auto; max-width:none; border-left:0;
                     border-top:1px solid rgba(148,163,184,0.18); }
    }`;
    document.head.appendChild(st);
}
