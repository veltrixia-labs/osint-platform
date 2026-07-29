/**
 * Impact Roster — a standalone Pro surface over /api/pro/impact-roster/.
 *
 * A scenario picker drives two tables for the selected supply-shock scenario:
 *   - firms, ranked by impact x credit-fragility (Merton PD)
 *   - hubs (countries / choke-points), which carry impact only and NO credit measure
 *
 * Three PD facts are kept visually distinct and never merged:
 *   pd > 0    -> the number
 *   pd === 0  -> "Negligible" (the PD was computed and underflowed below double precision)
 *   pd null   -> em dash + the reason (the PD could not be computed at all)
 *
 * We deliberately branch on resp.status rather than the house `resp.ok ? … : []`
 * idiom: a 503 (roster not loaded) must read differently from an empty roster, and
 * the backend built that distinction on purpose.
 */
import { apiClient } from '../api';

// ── Types: match the endpoint keys exactly ──────────────────────────────────
interface RosterLoad {
    load_id: string;
    finished_at: string;
    rows_written: number;
}
interface ScenarioCount {
    scenario: string;
    firm_row_count: number;
    hub_row_count: number;
}
interface ScenariosResponse {
    load: RosterLoad;
    scenarios: ScenarioCount[];
}
interface FirmRow {
    entity: string;
    impact: number;
    pd: number | null;
    pd_category: string | null;
    pd_reason: string | null;
    bucket: string | null;
    combined: number | null;
}
interface HubRow {
    entity: string;
    impact: number;
}
interface ScenarioResponse {
    scenario: string;
    ingested_at: string;
    firms: FirmRow[];
    hubs: HubRow[];
}

const CONTAINER_ID = 'impact-roster-container';
const STYLE_ID = 'impact-roster-style';
const DEFAULT_SCENARIO = 'lithium';

// ── Small local helpers ─────────────────────────────────────────────────────
function esc(s: unknown): string {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function fmtDate(iso: string | null | undefined): string {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleString(undefined, {
            year: 'numeric', month: 'short', day: '2-digit',
            hour: '2-digit', minute: '2-digit',
        });
    } catch {
        return iso;
    }
}

function injectStyles(): void {
    if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    // Scoped under #impact-roster-container. Table language copied verbatim from
    // .intel-quant-table (pro_reports.ts) so the surface looks native.
    style.textContent = `
    #${CONTAINER_ID} { padding: 1rem 1.2rem 2rem; overflow-y: auto; color: #cbd5e1; }
    #${CONTAINER_ID} .ir-header {
        display: flex; align-items: center; justify-content: space-between;
        gap: 1rem; flex-wrap: wrap; margin: 0.2rem 0 1rem;
    }
    #${CONTAINER_ID} .ir-title { font-size: 0.95rem; font-weight: 700; color: #f0f6fc; }
    #${CONTAINER_ID} .ir-selector { position: relative; display: inline-flex; align-items: center; }
    #${CONTAINER_ID} .ir-selector select {
        appearance: none; -webkit-appearance: none;
        background: rgba(22,27,34,0.72); color: #e2e8f0;
        border: 1px solid rgba(148,163,184,0.28); border-radius: 8px;
        padding: 7px 30px 7px 12px; font-size: 0.8rem; cursor: pointer;
        font-variant-numeric: tabular-nums;
    }
    #${CONTAINER_ID} .ir-selector select:hover { border-color: rgba(148,163,184,0.5); }
    #${CONTAINER_ID} .ir-selector select:focus-visible { outline: 2px solid #58a6ff; outline-offset: 1px; }
    #${CONTAINER_ID} .ir-selector::after {
        content: '▾'; position: absolute; right: 10px; top: 50%;
        transform: translateY(-50%); color: #64748b; pointer-events: none; font-size: 0.7rem;
    }
    #${CONTAINER_ID} .ir-ingest { font-size: 0.66rem; color: #64748b; letter-spacing: 0.04em; }

    #${CONTAINER_ID} .intel-quant-subtable-title {
        margin: 16px 0 6px; font-size: 0.72rem; font-weight: 700; color: #94a3b8;
        text-transform: uppercase; letter-spacing: 0.08em;
    }
    #${CONTAINER_ID} .intel-quant-subtable-note { font-size: 0.66rem; color: #64748b; font-weight: 400; text-transform: none; letter-spacing: 0; margin-left: 6px; }
    #${CONTAINER_ID} .intel-quant-table { width: 100%; border-collapse: collapse; font-size: 0.80rem; }
    #${CONTAINER_ID} .intel-quant-table th {
        text-align: left; font-size: 0.64rem; color: #64748b; text-transform: uppercase;
        letter-spacing: 0.08em; padding: 6px 8px; border-bottom: 1px solid rgba(148,163,184,0.14);
    }
    #${CONTAINER_ID} .intel-quant-table td {
        padding: 7px 8px; color: #cbd5e1; border-bottom: 1px solid rgba(148,163,184,0.08);
        font-variant-numeric: tabular-nums; vertical-align: top;
    }
    #${CONTAINER_ID} .intel-quant-table td.num { font-weight: 700; text-align: right; }
    #${CONTAINER_ID} .intel-quant-table td code { color: #7dd3fc; font-size: 0.74rem; }
    #${CONTAINER_ID} .intel-quant-table tr:last-child td { border-bottom: none; }

    /* the three PD states — each visually distinct */
    #${CONTAINER_ID} .ir-pd-num { font-weight: 700; }
    #${CONTAINER_ID} .ir-pd-negligible { color: #64748b; font-style: italic; }
    #${CONTAINER_ID} .ir-pd-null { color: #8b949e; }
    #${CONTAINER_ID} .ir-pd-reason { display: block; font-size: 0.62rem; color: #64748b; margin-top: 2px; line-height: 1.3; max-width: 340px; }

    #${CONTAINER_ID} .ir-country-note { font-size: 0.78rem; color: #94a3b8; font-style: italic; margin: 0.7rem 0 0.2rem; }

    #${CONTAINER_ID} .empty-state { padding: 2.2rem 1rem; text-align: center; }
    #${CONTAINER_ID} .empty-title { font-size: 0.98rem; color: #c9d1d9; margin-bottom: 0.4rem; }
    #${CONTAINER_ID} .empty-subtitle { font-size: 0.82rem; color: #8b949e; max-width: 460px; margin: 0 auto; line-height: 1.5; }
    `;
    document.head.appendChild(style);
}

// ── Cell renderers — the central display rule lives here ────────────────────
function fragilityCell(f: FirmRow): string {
    if (f.pd === null) {
        const reason = f.pd_reason
            ? `<span class="ir-pd-reason">${esc(f.pd_reason)}</span>`
            : '';
        return `<span class="ir-pd-null">—</span>${reason}`;
    }
    if (f.pd === 0) {
        return `<span class="ir-pd-negligible">Negligible</span>`;
    }
    return `<span class="ir-pd-num">${f.pd.toFixed(4)}</span>`;
}

function combinedCell(f: FirmRow): string {
    if (f.combined === null) return '';       // unmeasured — stays blank, never 0
    if (f.combined === 0) return '0';         // computed zero — shown as 0, never blank
    return f.combined.toFixed(4);
}

function firmsTable(firms: FirmRow[]): string {
    const rows = firms.map((f) => `
        <tr>
            <td><code>${esc(f.entity)}</code></td>
            <td class="num">${f.impact.toFixed(3)}</td>
            <td class="num">${fragilityCell(f)}</td>
            <td class="num">${combinedCell(f)}</td>
            <td>${f.bucket ? esc(f.bucket) : '<span class="ir-pd-null">—</span>'}</td>
        </tr>`).join('');
    return `
        <h5 class="intel-quant-subtable-title">Exposed firms <span class="intel-quant-subtable-note">ranked by impact × credit fragility</span></h5>
        <table class="intel-quant-table">
            <thead><tr><th>Entity</th><th>Impact</th><th>Credit fragility</th><th>Combined</th><th>Bucket</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

function hubsTable(hubs: HubRow[]): string {
    if (!hubs.length) return '';
    const rows = hubs.map((h) => `
        <tr>
            <td><code>${esc(h.entity)}</code></td>
            <td class="num">${h.impact.toFixed(3)}</td>
        </tr>`).join('');
    return `
        <h5 class="intel-quant-subtable-title">Countries &amp; hubs <span class="intel-quant-subtable-note">impact only — no firm-level credit measure applies</span></h5>
        <table class="intel-quant-table">
            <thead><tr><th>Entity</th><th>Impact</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

function stateBlock(title: string, subtitle: string): string {
    return `
        <div class="empty-state">
            <div class="empty-title">${esc(title)}</div>
            <div class="empty-subtitle">${esc(subtitle)}</div>
        </div>`;
}

function loadingBlock(): string {
    return `<div class="intelligence-loader">Decrypting Impact Roster...</div>`;
}

// ── Scenario body render ─────────────────────────────────────────────────────
function renderScenarioBody(bodyEl: HTMLElement, data: ScenarioResponse): void {
    if (!data.firms.length && !data.hubs.length) {
        // Every picker scenario has >= 1 row, so this is defensive; distinct copy.
        bodyEl.innerHTML = stateBlock(
            'No rows for this scenario',
            'The current load contains this scenario but no impacted entities.',
        );
        return;
    }
    if (!data.firms.length) {
        // Hub-only scenario (e.g. grain): country-level model, no firm table.
        bodyEl.innerHTML = `
            <p class="ir-country-note">This scenario is modelled at country level — no firm-level roster applies. Impacted countries and hubs:</p>
            ${hubsTable(data.hubs)}`;
        return;
    }
    bodyEl.innerHTML = firmsTable(data.firms) + hubsTable(data.hubs);
}

async function loadScenario(scenario: string, bodyEl: HTMLElement): Promise<void> {
    bodyEl.innerHTML = loadingBlock();
    let resp: Response;
    try {
        resp = await apiClient.get(`/pro/impact-roster/scenarios/${encodeURIComponent(scenario)}`);
    } catch {
        bodyEl.innerHTML = stateBlock('Could not reach the roster', 'A network error occurred. Confirm connectivity and try again.');
        return;
    }
    if (resp.status === 503) {
        bodyEl.innerHTML = stateBlock('The roster has not been loaded yet', 'No successful load exists on the server. This is different from a scenario with no impacted entities.');
        return;
    }
    if (resp.status === 404) {
        bodyEl.innerHTML = stateBlock('Scenario not found', 'That scenario is not in the current load.');
        return;
    }
    if (!resp.ok) {
        bodyEl.innerHTML = stateBlock('Could not load the scenario', `The server returned an unexpected status (${resp.status}).`);
        return;
    }
    try {
        const data = (await resp.json()) as ScenarioResponse;
        renderScenarioBody(bodyEl, data);
    } catch {
        bodyEl.innerHTML = stateBlock('Could not read the response', 'The roster response could not be parsed.');
    }
}

function buildShell(container: HTMLElement, data: ScenariosResponse): void {
    const names = data.scenarios.map((s) => s.scenario);
    const selected = names.includes(DEFAULT_SCENARIO) ? DEFAULT_SCENARIO : names[0];
    const options = data.scenarios
        .map((s) => `<option value="${esc(s.scenario)}"${s.scenario === selected ? ' selected' : ''}>${esc(s.scenario)}</option>`)
        .join('');

    container.innerHTML = `
        <div class="ir-header">
            <div style="display:flex; align-items:center; gap:0.8rem; flex-wrap:wrap;">
                <span class="ir-title">Impact Roster</span>
                <span class="ir-selector">
                    <select data-role="ir-scenario" aria-label="Scenario">${options}</select>
                </span>
            </div>
            <span class="ir-ingest">Ingested: ${esc(fmtDate(data.load.finished_at))}</span>
        </div>
        <div data-role="ir-body"></div>`;

    const bodyEl = container.querySelector<HTMLElement>('[data-role="ir-body"]')!;
    const select = container.querySelector<HTMLSelectElement>('[data-role="ir-scenario"]')!;
    select.addEventListener('change', () => void loadScenario(select.value, bodyEl));
    void loadScenario(selected, bodyEl);
}

async function loadScenarios(container: HTMLElement): Promise<void> {
    container.innerHTML = loadingBlock();
    let resp: Response;
    try {
        resp = await apiClient.get('/pro/impact-roster/scenarios');
    } catch {
        container.innerHTML = stateBlock('Could not reach the roster', 'A network error occurred. Confirm connectivity and try again.');
        return;
    }
    if (resp.status === 503) {
        container.innerHTML = stateBlock('The roster has not been loaded yet', 'No successful load exists on the server. This is different from a scenario with no impacted entities.');
        return;
    }
    if (!resp.ok) {
        container.innerHTML = stateBlock('Could not load the roster', `The server returned an unexpected status (${resp.status}).`);
        return;
    }
    let data: ScenariosResponse;
    try {
        data = (await resp.json()) as ScenariosResponse;
    } catch {
        container.innerHTML = stateBlock('Could not read the response', 'The roster response could not be parsed.');
        return;
    }
    if (!data.scenarios.length) {
        container.innerHTML = stateBlock('No scenarios available', 'The current load contains no scenarios with rows.');
        return;
    }
    buildShell(container, data);
}

/**
 * Impact Roster route entry. No args — self-fetches its container, mirroring
 * pro_map.ts's signature and re-mount guard.
 */
export function renderImpactRoster(): void {
    const container = document.getElementById(CONTAINER_ID);
    if (!container) return;

    if (container.dataset.impactRosterMounted === '1') {
        return; // already mounted — keep existing state on tab re-entry
    }
    container.dataset.impactRosterMounted = '1';
    injectStyles();
    void loadScenarios(container);
}
