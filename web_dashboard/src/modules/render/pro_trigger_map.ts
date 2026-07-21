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
import { renderStaticCascadeShell, renderDrawer, mountSpatialContagionMap, injectMaplibreCss } from './pro_interactive_map';

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
 *
 * English display: prefer a Latin/ASCII alias ("Strait of Hormuz"), then the
 * explicit label, then the hub id with underscores stripped. The Japanese aliases
 * stay in the payload for MATCHING (the trigger scans all of them) — they are just
 * not shown as the name.
 */
function displayName(s: { aliases?: string[]; label?: string | null; hub?: string; id?: string }): string {
    const latin = (s.aliases ?? []).find((a) => /^[\x00-\x7F]+$/.test(a));
    return latin || s.label || (s.hub ?? s.id ?? '').replace(/_/g, ' ');
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

/**
 * Real coordinate, formatted DD.DDN DDD.DDE from the payload's own lat/lon. Two decimals
 * is the hub centroid's real precision, zero-padded for column alignment only — nothing is
 * padded to fake exactness we do not have.
 */
function fmtCoord(lat: number, lon: number): string {
    const fmt = (v: number, intDigits: number, pos: string, neg: string): string => {
        const [w, f] = Math.abs(v).toFixed(2).split('.');
        return `${w.padStart(intDigits, '0')}.${f}${v >= 0 ? pos : neg}`;
    };
    return `${fmt(lat, 2, 'N', 'S')} ${fmt(lon, 3, 'E', 'W')}`;
}

/** UTC timestamp, ISO 8601 Zulu, whole seconds (e.g. 2026-07-20T14:03:07Z). */
function utcStamp(): string {
    return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
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
        // Full-bleed: the receipts live in the map's own drawer (open by default — they justify
        // the firing state, so hiding them would leave the map unexplained). The fixed 380px
        // sidebar stays retired in Stage 1 too.
        this.panelEl.style.display = 'none';

        const p = this.payload;
        const firing = p.scenarios.filter((s) => s.firing && s.lat != null && s.lon != null);
        const dormant = p.scenarios.filter((s) => !s.firing);

        this.stageEl.innerHTML = `
            <div class="tm2-map" id="tm2-map"></div>
            <div class="tm2-frame" aria-hidden="true">
                <i class="tm2-corner tm2-corner--tl"></i><i class="tm2-corner tm2-corner--tr"></i>
                <i class="tm2-corner tm2-corner--bl"></i><i class="tm2-corner tm2-corner--br"></i>
            </div>
            <div class="tm2-hud">
                <span class="tm2-hud-title">Spatial Contagion</span>
                <span class="tm2-hud-src">OSINT // Open Source</span>
                <span class="tm2-hud-clock" id="tm2-clock"></span>
            </div>
            ${renderDrawer('Receipts', 'triggers', true)}`;

        const drawerBody = this.stageEl.querySelector<HTMLElement>('.sc-drawer-body');
        if (drawerBody) this.renderPanel(firing, dormant, p, drawerBody);
        this.wireDrawer();

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

        const BoundsCtor = maplibregl?.LngLatBounds ?? maplibregl?.default?.LngLatBounds;

        this.map = new MapCtor({
            container: mapEl,
            style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
            center: [20, 25],
            zoom: 1.4,
            attributionControl: false,
        });
        this.addCleanup(() => this.disposeStage1Map());

        // Auto-fit to the firing set on open — never a hardcoded camera. The fit key is
        // stamped on the map instance, so a future in-place poll that keeps the SAME map
        // (unchanged firing set) will not yank a camera the user has since panned. A changed
        // firing set, or a freshly rebuilt map, fits again.
        this.fitToFiring(firing, BoundsCtor);

        // Reticles. Firing = amber, pulsing, sized by match_count. Dormant (watched, not
        // firing) = small desaturated slate, clearly subordinate — the map shows what is
        // being watched, not only what is loud.
        //
        // Label de-collision (§ never move the reticle): the reticle stays on its true
        // coordinate; only the TAG is offset, with a leader line. Placement alternates
        // below/above by descending match_count rank (largest below, next above, …), so two
        // nearby scenarios of different volume — Hormuz vs Bab el-Mandeb — always land on
        // opposite sides of their reticles instead of stacking.
        const tagUpFor = new Map<string, boolean>();
        [...firing]
            .sort((a, b) => b.match_count - a.match_count)
            .forEach((s, i) => tagUpFor.set(s.id, i % 2 === 1));

        for (const s of firing) {
            const el = this.buildMarkerEl(s, { dormant: false, tagUp: tagUpFor.get(s.id) ?? false });
            const marker = new MarkerCtor({ element: el }).setLngLat([s.lon, s.lat]).addTo(this.map);
            this.markers.push(marker);
        }
        for (const s of dormant) {
            if (s.lat == null || s.lon == null) continue;
            const el = this.buildMarkerEl(s, { dormant: true, tagUp: false });
            const marker = new MarkerCtor({ element: el }).setLngLat([s.lon, s.lat]).addTo(this.map);
            this.markers.push(marker);
        }

        // UTC clock in the map HUD (ISO 8601, Zulu). Ticks once a second; cleaned up on stop().
        const clockEl = this.stageEl.querySelector<HTMLElement>('#tm2-clock');
        if (clockEl) {
            const tick = (): void => {
                if (this.aborted) return;
                clockEl.textContent = utcStamp();
            };
            tick();
            const id = window.setInterval(tick, 1000);
            this.addCleanup(() => window.clearInterval(id));
        }
    }

    /**
     * Fit the camera to the firing set. World view when nothing fires; clamp maxZoom so a
     * single firing scenario does not zoom to street level. The fit key lives on the map
     * instance, so this is idempotent for a given (map, firing set): the initial open fits,
     * and after that the user's pan/zoom is left alone unless the firing set changes.
     */
    private fitToFiring(firing: ScenarioTrigger[], BoundsCtor: any): void {
        if (!this.map) return;
        const key = firing.map((s) => s.id).sort().join(',');
        if (this.map.__tmFitKey === key) return;   // same map + same set → keep the user's camera
        this.map.__tmFitKey = key;

        if (!firing.length || !BoundsCtor) {
            this.map.jumpTo({ center: [20, 25], zoom: 1.4 });   // zero firing → stable world view
            return;
        }
        const bounds = new BoundsCtor();
        for (const s of firing) bounds.extend([s.lon as number, s.lat as number]);
        this.map.fitBounds(bounds, {
            padding: { top: 110, bottom: 72, left: 72, right: 72 },
            maxZoom: firing.length === 1 ? 4.5 : 5,
            duration: 0,
        });
    }

    /**
     * One reticle per scenario. Firing: size = match_count, amber shade = max_importance —
     * two SEPARATE encodings, both NEWS SIGNAL, never impact. Dormant: fixed small slate,
     * subordinate. The reticle is anchored on the true coordinate; only the tag is offset.
     */
    private buildMarkerEl(s: ScenarioTrigger, opts: { dormant: boolean; tagUp: boolean }): HTMLElement {
        const dormant = opts.dormant;
        const r = dormant ? 9 : markerRadiusPx(s.match_count);
        const ring = dormant ? '#64748b' : markerShade(s.max_importance).ring;
        const name = displayName(s);
        const coord = (s.lat != null && s.lon != null) ? fmtCoord(s.lat, s.lon) : '';

        const el = document.createElement('button');
        el.type = 'button';
        el.className = `tm2-marker${dormant ? ' tm2-marker--dormant' : ''}${opts.tagUp ? ' tm2-marker--tagup' : ''}`;
        el.setAttribute(
            'aria-label',
            `${name} — ${s.match_count} alert${s.match_count === 1 ? '' : 's'}${dormant ? ' (watched, not firing)' : ''}`,
        );
        el.style.width = `${r * 2}px`;
        el.style.height = `${r * 2}px`;
        el.style.setProperty('--ring', ring);

        const tag = dormant
            ? `<span class="tm2-tag"><span class="tm2-tag-name">${esc(name)}</span></span>`
            : `<span class="tm2-tag">
                   <span class="tm2-tag-name">${esc(name)}</span>
                   ${coord ? `<span class="tm2-tag-coord">${esc(coord)}</span>` : ''}
               </span>`;

        el.innerHTML = `
            <span class="tm2-ret">
                <span class="tm2-ret-ring tm2-ret-ring--outer"></span>
                <span class="tm2-ret-ring tm2-ret-ring--inner"></span>
                <i class="tm2-ret-tick tm2-ret-tick--n"></i>
                <i class="tm2-ret-tick tm2-ret-tick--s"></i>
                <i class="tm2-ret-tick tm2-ret-tick--e"></i>
                <i class="tm2-ret-tick tm2-ret-tick--w"></i>
                <span class="tm2-ret-count">${s.match_count}</span>
            </span>
            ${tag}`;
        const onClick = (): void => {
            // Firing → surface its receipts in the drawer (the card's "View cascade →" goes deeper).
            // Dormant has no receipt card, so it jumps straight into its cascade.
            if (opts.dormant) void this.enterStage2(s);
            else this.highlightScenarioCard(s.id);
        };
        el.addEventListener('click', onClick);
        this.addCleanup(() => el.removeEventListener('click', onClick));
        return el;
    }

    // ── The receipts panel — WHY it is firing ────────────────────────────────

    private renderPanel(firing: ScenarioTrigger[], dormant: ScenarioTrigger[], p: TriggerPayload, target: HTMLElement): void {
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
                <div class="tm2-card" data-scenario="${esc(s.id)}">
                    <div class="tm2-card-head">
                        <span class="tm2-card-name">${esc(displayName(s))}</span>
                        <button type="button" class="tm2-view" data-scenario="${esc(s.id)}">View cascade →</button>
                    </div>
                    <div class="tm2-readouts">
                        <span class="tm2-ro"><span class="tm2-ro-k">Match</span><span class="tm2-ro-v">${s.match_count}</span></span>
                        <span class="tm2-ro"><span class="tm2-ro-k">Peak</span><span class="tm2-ro-v">${fmtImportance(s.max_importance)}</span></span>
                        <span class="tm2-ro"><span class="tm2-ro-k">Window</span><span class="tm2-ro-v">${p.window_hours}h</span></span>
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

        target.innerHTML = header + (zero ? zeroState : cards) + manual;

        target.querySelectorAll<HTMLButtonElement>('button[data-scenario]').forEach((btn) => {
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

    /**
     * The cascade's own node inventory, for the Stage-2 side panel. Ordered by MEASURED
     * impact desc; exposed_unquantified entries are grouped SEPARATELY and show "--", never
     * 0 — an unmeasured node is not a zero-impact node, and sorting it as 0 would bury the
     * real ones. (Bidirectional row↔node highlight/zoom lands with the node-vocabulary pass.)
     */
    private buildCascadeListHtml(sc: any): string {
        const nodes: any[] = Array.isArray(sc?.nodes) ? sc.nodes : [];
        const isExposed = (n: any): boolean => n.type === 'exposed_unquantified' || n.unquantified === true;
        const nameOf = (n: any): string => esc(String(n.name ?? n.id ?? '—'));
        const scoreOf = (n: any): string =>
            isExposed(n) || n.impact_score == null ? '--' : String(Math.round(n.impact_score));
        const ordOf = (n: any): string => (n.order ? `O${n.order}` : '');

        const epi = nodes.filter((n) => n.type === 'epicenter');
        const affected = nodes
            .filter((n) => n.type === 'affected' && !isExposed(n))
            .sort((a, b) => (b.impact_score ?? 0) - (a.impact_score ?? 0));
        const exposed = nodes.filter(isExposed);

        const row = (n: any, cls: string): string => `
            <button type="button" class="tm2-node ${cls}" data-node-id="${esc(String(n.id ?? ''))}">
                <span class="tm2-node-sw"></span>
                <span class="tm2-node-name" title="${nameOf(n)}">${nameOf(n)}</span>
                <span class="tm2-node-ord">${ordOf(n)}</span>
                <span class="tm2-node-score">${scoreOf(n)}</span>
            </button>`;

        const group = (label: string, items: any[], cls: string): string =>
            items.length ? `<div class="tm2-node-group">${esc(label)}</div>${items.map((n) => row(n, cls)).join('')}` : '';

        return `<div class="tm2-cascade">
            ${group('Epicenter', epi, 'tm2-node--epi')}
            ${group(`Affected · measured (${affected.length})`, affected, 'tm2-node--aff')}
            ${group(`Exposed · magnitude unknown (${exposed.length})`, exposed, 'tm2-node--unq')}
        </div>`;
    }

    /** Wire the "← Triggers" affordance (new shell's .sc-static-back, or the empty-state #tm2-back). */
    private wireBack(): void {
        const back = this.stageEl.querySelector<HTMLButtonElement>('.sc-static-back, #tm2-back');
        if (!back) return;
        const onBack = (): void => { void this.renderStage1(); };
        back.addEventListener('click', onBack);
        this.addCleanup(() => back.removeEventListener('click', onBack));
    }

    /** Wire the drawer's slide toggle. Shared by Stage 1 (Receipts) and Stage 2 (Roster). */
    private wireDrawer(): void {
        const drawer = this.stageEl.querySelector<HTMLElement>('.sc-drawer');
        const handle = this.stageEl.querySelector<HTMLButtonElement>('.sc-drawer-handle');
        if (!drawer || !handle) return;
        const onToggle = (): void => {
            const open = drawer.classList.toggle('sc-drawer--open');
            handle.setAttribute('aria-expanded', String(open));
            drawer.setAttribute('aria-hidden', String(!open));
        };
        handle.addEventListener('click', onToggle);
        this.addCleanup(() => handle.removeEventListener('click', onToggle));
    }

    /** Map→panel link: open the drawer and flash+scroll a firing scenario's receipt card. */
    private highlightScenarioCard(id: string): void {
        const drawer = this.stageEl.querySelector<HTMLElement>('.sc-drawer');
        const handle = this.stageEl.querySelector<HTMLButtonElement>('.sc-drawer-handle');
        if (drawer && !drawer.classList.contains('sc-drawer--open')) {
            drawer.classList.add('sc-drawer--open');
            drawer.setAttribute('aria-hidden', 'false');
            handle?.setAttribute('aria-expanded', 'true');
        }
        const card = this.stageEl.querySelector<HTMLElement>(`.tm2-card[data-scenario="${id}"]`);
        if (!card) return;
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        card.classList.add('tm2-card--flash');
        window.setTimeout(() => card.classList.remove('tm2-card--flash'), 1600);
    }

    private async enterStage2(s: ScenarioTrigger): Promise<void> {
        if (this.aborted) return;
        this.disposeStage1Map();     // Stage 1's map must die before Stage 2 builds its own.

        // Full-bleed: the roster moves into the map's own drawer, so the fixed 380px sidebar is
        // retired for Stage 2 and the map goes edge-to-edge. renderStage1() restores it on Back.
        this.panelEl.style.display = 'none';
        this.panelEl.innerHTML = '';

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
                    <button type="button" class="tm2-back" id="tm2-back">← Back to triggers</button>
                    <div class="tm2-empty-title">No cascade data for ${esc(displayName(s))}.</div>
                    <div class="tm2-empty-sub">The scenario is triggered, but its graph has not been loaded.</div>
                </div>`;
            this.wireBack();
            return;
        }

        // Full-bleed drawer shell; the roster lives in the drawer, not a sidebar.
        this.stageEl.innerHTML = renderStaticCascadeShell(sc, s.id);

        const titleEl = this.stageEl.querySelector<HTMLElement>('.sc-static-title');
        if (titleEl) titleEl.textContent = displayName(s);
        this.wireBack();

        const body = this.stageEl.querySelector<HTMLElement>('.sc-drawer-body');
        if (body) body.innerHTML = this.buildCascadeListHtml(sc);

        this.wireDrawer();

        // Delegate to the existing cascade renderer: fan-out, arcs, hollow rings, reticles.
        // start() also installs wrapEl.__scFocusNode() for the drawer→card wiring below.
        await mountSpatialContagionMap(this.stageEl, sc, s.id, { staticScenario: true });
        if (this.aborted) return;

        // Drawer row → open that node's card on the map (read at click time, so the mount race
        // is harmless — __scFocusNode is present well before any click).
        const wrap = this.stageEl.querySelector<HTMLElement>('.sc-map-wrap');
        if (body && wrap) {
            const onRow = (e: Event): void => {
                const btn = (e.target as HTMLElement).closest<HTMLElement>('[data-node-id]');
                const id = btn?.getAttribute('data-node-id');
                if (id) (wrap as any).__scFocusNode?.(id);
            };
            body.addEventListener('click', onRow);
            this.addCleanup(() => body.removeEventListener('click', onRow));
        }
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
                background:#020617; color:#e2e8f0;
                font-family:ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace;
                font-variant-numeric:tabular-nums; }
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
    .tm2-head-title { font-size:15px; font-weight:800; letter-spacing:0.08em; text-transform:uppercase; }
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
    .tm2-card--flash { animation:tm2-card-flash 1.6s ease; }
    @keyframes tm2-card-flash {
        0%,100% { box-shadow:0 0 0 0 rgba(251,191,36,0); border-color:rgba(148,163,184,0.18); }
        18%     { box-shadow:0 0 0 2px rgba(251,191,36,0.85); border-color:#fbbf24; }
    }
    .tm2-card-head { display:flex; align-items:center; justify-content:space-between; gap:8px; }
    .tm2-card-name { font-size:13px; font-weight:800; letter-spacing:0.08em; text-transform:uppercase; }

    /* Readout strip — KEY over value, tabular. The honesty prose below it is unchanged. */
    .tm2-readouts { display:flex; gap:18px; margin:11px 0 3px; }
    .tm2-ro { display:flex; flex-direction:column; gap:2px; }
    .tm2-ro-k { font-size:9px; font-weight:800; letter-spacing:0.14em; text-transform:uppercase; color:#64748b; }
    .tm2-ro-v { font-size:16px; font-weight:800; color:#e2e8f0; line-height:1; }
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

    /* Stage-2 cascade node inventory (side panel). Mono is inherited from .tm2-host. */
    .tm2-cascade { margin-top:16px; }
    .tm2-node-group { font-size:9.5px; font-weight:800; letter-spacing:0.13em; text-transform:uppercase;
                      color:#64748b; margin:14px 0 6px; }
    .tm2-node { display:grid; grid-template-columns:auto 1fr auto auto; align-items:center; gap:8px;
                width:100%; padding:6px 4px; border:0; border-top:1px solid rgba(148,163,184,0.08);
                background:transparent; color:inherit; font:inherit; font-size:11.5px;
                text-align:left; cursor:pointer; border-radius:4px; }
    .tm2-node:hover { background:rgba(148,163,184,0.08); }
    .tm2-node-sw { width:9px; height:9px; border-radius:50%; flex:0 0 auto; }
    .tm2-node--epi .tm2-node-sw { background:#ef4444; }
    .tm2-node--aff .tm2-node-sw { background:#22d3ee; }
    .tm2-node--unq .tm2-node-sw { background:transparent; border:1.5px solid #94a3b8; }
    .tm2-node-name { text-transform:uppercase; letter-spacing:0.04em; color:#cbd5e1;
                     white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .tm2-node-ord { font-size:9.5px; color:#64748b; }
    .tm2-node-score { font-weight:800; color:#e2e8f0; font-variant-numeric:tabular-nums;
                      min-width:2ch; text-align:right; }
    .tm2-node--unq .tm2-node-score { color:#64748b; }

    .tm2-legend { display:flex; flex-direction:column; gap:6px; margin-top:14px;
                  font-size:11.5px; color:#94a3b8; }
    .tm2-legend > div { display:flex; align-items:center; gap:8px; }
    .tm2-sw { width:11px; height:11px; border-radius:50%; display:inline-block; }
    .tm2-sw--epi { background:#ef4444; }
    .tm2-sw--aff { background:#22d3ee; }
    .tm2-sw--unq { background:transparent; border:1.5px solid #94a3b8; }

    /* ── Map chrome: command-post HUD + corner brackets. pointer-events:none so the
       basemap stays draggable underneath. Open-source data — no classification marks. */
    .tm2-hud { position:absolute; top:0; left:0; right:0; z-index:5; pointer-events:none;
               display:flex; align-items:center; gap:14px; padding:9px 14px;
               font-size:10px; letter-spacing:0.14em; text-transform:uppercase;
               background:linear-gradient(180deg, rgba(2,6,23,0.78), rgba(2,6,23,0)); }
    .tm2-hud-title { color:#cbd5e1; font-weight:800; }
    .tm2-hud-src   { color:#64748b; }
    .tm2-hud-clock { margin-left:auto; color:#94a3b8; letter-spacing:0.08em; }

    .tm2-frame { position:absolute; inset:10px; z-index:4; pointer-events:none; }
    .tm2-corner { position:absolute; width:15px; height:15px; border:1px solid rgba(148,163,184,0.5); }
    .tm2-corner--tl { top:0; left:0;    border-right:0; border-bottom:0; }
    .tm2-corner--tr { top:0; right:0;   border-left:0;  border-bottom:0; }
    .tm2-corner--bl { bottom:0; left:0;  border-right:0; border-top:0; }
    .tm2-corner--br { bottom:0; right:0; border-left:0;  border-top:0; }

    /* ── Stage-1 reticle. AMBER = news signal, deliberately NOT the cascade's impact ramp.
       --ring carries the amber shade (or slate, for dormant). The reticle sits ON the true
       coordinate; only the tag is offset for legibility (see the de-collision rule above). */
    .tm2-marker { position:relative; display:flex; align-items:center; justify-content:center;
                  background:transparent; border:0; padding:0; cursor:pointer; --ring:#f59e0b; }
    .tm2-ret { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; }
    .tm2-ret-ring { position:absolute; border-radius:50%; border:1px solid var(--ring); }
    .tm2-ret-ring--outer { inset:0; opacity:0.5; animation:tm2-pulse 2.4s ease-in-out infinite; }
    .tm2-ret-ring--inner { inset:34%; opacity:0.9; }
    .tm2-ret-tick { position:absolute; background:var(--ring); opacity:0.7; }
    .tm2-ret-tick--n, .tm2-ret-tick--s { left:50%; width:1px; height:16%; transform:translateX(-0.5px); }
    .tm2-ret-tick--e, .tm2-ret-tick--w { top:50%; height:1px; width:16%; transform:translateY(-0.5px); }
    .tm2-ret-tick--n { top:0; } .tm2-ret-tick--s { bottom:0; }
    .tm2-ret-tick--w { left:0; } .tm2-ret-tick--e { right:0; }
    .tm2-ret-count { position:relative; font-size:12px; font-weight:800; color:var(--ring);
                     text-shadow:0 1px 3px #000; pointer-events:none; }

    /* Tag = scenario name + real coordinates, offset from the reticle by a thin leader line.
       The reticle never moves; only this tag does. */
    .tm2-tag { position:absolute; left:50%; top:100%; transform:translate(-50%, 12px);
               display:flex; flex-direction:column; align-items:center; gap:1px;
               white-space:nowrap; text-align:center; pointer-events:none; }
    .tm2-tag::before { content:''; position:absolute; left:50%; bottom:100%; width:1px; height:12px;
                       background:rgba(148,163,184,0.55); transform:translateX(-0.5px); }
    .tm2-marker--tagup .tm2-tag { top:auto; bottom:100%; transform:translate(-50%, -12px); }
    .tm2-marker--tagup .tm2-tag::before { bottom:auto; top:100%; }
    .tm2-tag-name { font-size:10.5px; font-weight:800; letter-spacing:0.1em; text-transform:uppercase;
                    color:#e2e8f0; text-shadow:0 1px 4px #000; }
    .tm2-tag-coord { font-size:9.5px; letter-spacing:0.06em; color:#94a3b8; text-shadow:0 1px 3px #000; }

    /* Dormant: watched but not firing — small, slate, no pulse, clearly subordinate. */
    .tm2-marker--dormant { --ring:#64748b; opacity:0.7; }
    .tm2-marker--dormant .tm2-ret-ring--outer { animation:none; opacity:0.3; }
    .tm2-marker--dormant .tm2-ret-count { font-size:10px; }
    .tm2-marker--dormant .tm2-tag-name { font-size:9px; font-weight:700; color:#94a3b8; }
    .tm2-marker--dormant:hover { opacity:1; }

    @keyframes tm2-pulse {
        0%,100% { box-shadow:0 0 0 0 rgba(245,158,11,0.28); }
        50%     { box-shadow:0 0 0 9px rgba(245,158,11,0); }
    }
    @media (max-width: 900px) {
        .tm2-host { flex-direction:column; height:auto; }
        .tm2-stage { height:52vh; }
        .tm2-panel { flex:1 1 auto; max-width:none; border-left:0;
                     border-top:1px solid rgba(148,163,184,0.18); }
    }`;
    document.head.appendChild(st);
}
