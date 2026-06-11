/**
 * Monthly Trend Flow — 4-quadrant master-detail cockpit (no map, no modals).
 *
 * 2x2 grid mirroring the Alert Stream's master-detail pattern:
 *   ┌────────────────────────────┬──────────────────────────┐
 *   │ TL  30-Day Spike Trajectory │ TR  Sector Pressure orbit│
 *   ├────────────────────────────┼──────────────────────────┤
 *   │ BL  Spiked Signals list     │ BR  Signal Detail pane   │
 *   └────────────────────────────┴──────────────────────────┘
 *
 * Wiring:
 *   • Click a chart day  → filters the Bottom-Left list to that day.
 *   • Click an orbit sector → filters the list to that domain.
 *   • Click a list item  → renders its detail PERMANENTLY in the Bottom-Right
 *     pane, reusing the Alert Stream's `chudDetailHtml` so the look/feel is
 *     identical. No overlay modal. Fully open (no tier gating).
 */
import {
    fetchMonthlyTrendIndex,
    fetchLatestMonthlyTrend,
    fetchMonthlyTrend,
    type Alert,
    type MonthlyTrendIndexItem,
    type MonthlyTrendSnapshot,
} from '../api';
import { chudDetailHtml } from './alerts';
import { wirePanelGuideTooltips } from './pro_dashboard_primitives';

const DAY_MS = 86_400_000;

/**
 * The 6 canonical strategic domains (mirrors analysis/pro_domain_config
 * STRATEGIC_DOMAINS). Order = orbit position (clockwise from top). Each carries
 * one distinct, high-contrast color token applied everywhere it appears.
 */
interface TfDomain { id: string; label: string; color: string; }
const TF_DOMAINS: TfDomain[] = [
    { id: 'global_market_intelligence', label: 'Markets', color: '#00f0ff' },
    { id: 'energy_resource_risk', label: 'Energy', color: '#ffb020' },
    { id: 'defense_technology', label: 'Defense', color: '#ff3b5c' },
    { id: 'supply_chain_intelligence', label: 'Supply Chain', color: '#3ddc97' },
    { id: 'ai_semiconductor_intelligence', label: 'AI / Semi', color: '#7c5cff' },
    { id: 'crypto_geopolitics', label: 'Crypto', color: '#f472b6' },
];
const TF_DOMAIN_BY_ID: Record<string, TfDomain> = Object.fromEntries(TF_DOMAINS.map((d) => [d.id, d]));
const _domainColor = (id: string): string => TF_DOMAIN_BY_ID[id]?.color || '#6f8aa6';
const _domainLabel = (id: string): string => TF_DOMAIN_BY_ID[id]?.label || id;

// ── Module-level render state ────────────────────────────────────────────────
let tfAlertDomain: Map<string, string> = new Map(); // alert id → strategic domain id
let tfSortedAlerts: Alert[] = [];   // current month's spiked alerts (desc by time)
let tfNewsOverflow = 0;             // spiked sources beyond the fetch cap
let tfActiveDomain: string | null = null; // orbit sector filter (null = all)
let tfActiveDay: number | null = null;     // chart day filter (null = all days)
let tfSelectedId: string | null = null;    // master-detail selection (persists across list re-renders)
let tfPeriodStartMs = 0;            // current period start (UTC ms) for day math

function _esc(s: unknown): string {
    return String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

/** 0-based day index of an alert within the current period (-1 if out of range). */
function _alertDayIndex(a: Alert): number {
    const t = new Date(a.triggered_at).getTime();
    if (Number.isNaN(t) || !tfPeriodStartMs) return -1;
    return Math.floor((t - tfPeriodStartMs) / DAY_MS);
}

/** Short UTC date label for a day index (e.g. "May 14"), matching the bucketing. */
function _dayLabel(day: number): string {
    const d = new Date(tfPeriodStartMs + day * DAY_MS);
    // Force en-US so the day-filter chip reads "Jun 4", not a browser-locale form.
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

/**
 * Clear transient state on tab exit. No map/WebGL/modal context to tear down;
 * we bump the render token so any in-flight hydration is discarded.
 */
export function disposeTrendFlow(): void {
    tfAlertDomain = new Map();
    tfSortedAlerts = [];
    tfNewsOverflow = 0;
    tfActiveDomain = null;
    tfActiveDay = null;
    tfSelectedId = null;
    tfPeriodStartMs = 0;
}

// ── Top statbar (global month summary) ───────────────────────────────────────
function _renderSummary(statsEl: HTMLElement, snapshot: MonthlyTrendSnapshot): void {
    const s = snapshot.summary || {};
    const top = Array.isArray(s.top_sectors) ? s.top_sectors : [];
    const entropy = typeof s.entropy_index === 'number' ? s.entropy_index.toFixed(3) : (s.entropy_index ?? '—');
    statsEl.innerHTML =
        `<span class="tf-stat"><b data-tf-spiked>${s.alerts_spiked ?? 0}</b> SPIKED</span>` +
        `<span class="tf-stat tf-stat--dim"><b>${s.alerts_total ?? 0}</b> TOTAL</span>` +
        `<span class="tf-stat"><b>${entropy}</b> H</span>` +
        `<span class="tf-stat"><b>${s.node_count ?? 0}</b> NODES</span>` +
        `<span class="tf-stat"><b>${s.edge_count ?? 0}</b> EDGES</span>` +
        (top.length ? `<span class="tf-stat tf-stat--sectors">${top.map((d: string) => _esc(_domainLabel(d))).join(' · ')}</span>` : '');
}

// ── Top-Right quadrant: interactive 6-node Cyber-Orbit sector selector ───────
// `counts` = per-domain spiked totals for the ACTIVE scope (whole month, or the
// selected chart day) so the radar stays in lockstep with the header + list.
function _buildOrbit(counts: Record<string, number>): string {
    const R = 37;                      // node ring radius (% of orbit box)
    const SVG = 200, C = SVG / 2, RR = R * 2;
    const N = TF_DOMAINS.length;       // always 6
    // Center readout = total spiked signals in the active scope (sum of nodes).
    const totalSpiked = TF_DOMAINS.reduce((sum, d) => sum + (counts[d.id] || 0), 0);

    let spokes = '';
    const nodes = TF_DOMAINS.map((d, i) => {
        const spiked = counts[d.id] || 0;
        const ang = (-90 + i * (360 / N)) * Math.PI / 180;
        const leftPct = 50 + R * Math.cos(ang);
        const topPct = 50 + R * Math.sin(ang);
        const ex = C + RR * Math.cos(ang);
        const ey = C + RR * Math.sin(ang);
        spokes += `<line x1="${C}" y1="${C}" x2="${ex.toFixed(1)}" y2="${ey.toFixed(1)}" stroke="${d.color}" stroke-opacity="${spiked ? 0.34 : 0.12}" stroke-width="1"></line>`;
        const quiet = spiked === 0 ? ' tf-orbit-node--quiet' : '';
        return (
            `<button type="button" class="tf-orbit-node${quiet}" data-tf-domain="${_esc(d.id)}"` +
            ` style="left:${leftPct.toFixed(2)}%;top:${topPct.toFixed(2)}%;--node:${d.color}"` +
            ` aria-pressed="false" title="${_esc(d.label)} — ${spiked} spiked">` +
            `<span class="tf-orbit-node-val">${spiked}</span>` +
            `<span class="tf-orbit-node-lbl">${_esc(d.label)}</span>` +
            `</button>`
        );
    }).join('');

    return (
        `<div class="tf-orbit" data-tf-orbit>` +
        `<svg class="tf-orbit-rings" viewBox="0 0 ${SVG} ${SVG}" aria-hidden="true">` +
        `<circle class="tf-orbit-ring-spin" cx="${C}" cy="${C}" r="${RR}" fill="none" stroke="rgba(0,240,255,0.18)" stroke-width="1" stroke-dasharray="3 4"></circle>` +
        `<circle cx="${C}" cy="${C}" r="46" fill="none" stroke="rgba(120,160,210,0.14)" stroke-width="1"></circle>` +
        spokes +
        `</svg>` +
        `<button type="button" class="tf-orbit-core" data-tf-core title="Show all sectors (reset filter)">` +
        `<span class="tf-orbit-core-val">${String(totalSpiked).padStart(2, '0')}</span>` +
        `<span class="tf-orbit-core-lbl" data-tf-core-state>TOTAL SPIKED</span>` +
        `</button>` +
        nodes +
        `</div>`
    );
}

// ── Top-Left quadrant: 30-day trajectory — per-domain colored spike series ───
function _sparklineSvg(
    period: MonthlyTrendSnapshot['period'],
    alerts: Alert[],
    activeDomain: string | null,
    activeDay: number | null,
): string {
    const start = new Date(period.start).getTime();
    const end = new Date(period.end).getTime();
    const days = Math.max(1, Math.round((end - start) / DAY_MS));

    const perDomain: Record<string, number[]> = {};
    for (const d of TF_DOMAINS) perDomain[d.id] = new Array(days).fill(0);
    const total = new Array(days).fill(0);
    for (const a of alerts) {
        const t = new Date(a.triggered_at).getTime();
        if (Number.isNaN(t)) continue;
        const idx = Math.floor((t - start) / DAY_MS);
        if (idx < 0 || idx >= days) continue;
        const dom = tfAlertDomain.get(a.id);
        if (dom && perDomain[dom]) {
            perDomain[dom][idx] += 1;
            // Volatility bar = TOTAL COUNT = the exact SUM of the per-domain line
            // counts (count only domains that render a line, so bar === Σ lines,
            // never an intensity/other metric).
            total[idx] += 1;
        }
    }

    // Truncate to the current real-world day: the in-progress month stops at
    // today so lines/bars don't draw flat across empty future days. Past months
    // (period end <= now) render in full.
    const todayIdx = Math.floor((Date.now() - start) / DAY_MS);
    const lastIdx = todayIdx >= days ? days - 1 : Math.max(0, Math.min(days - 1, todayIdx));

    // Integer Y scale — never stretch a small max to the top of the box. Ceiling
    // = max(5, dataMax+1) rounded up to a "nice" step, so gridlines/labels land on
    // real integers and a count of 2 reads at the labeled "2" line (not the top).
    const dataMax = Math.max(0, ...total);
    const NICE_STEPS = [1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000, 2000, 5000];
    const target = Math.max(5, dataMax + 1);                       // min ceiling of 5
    const step = NICE_STEPS.find((s) => target / s <= 6) ?? Math.ceil(target / 6);
    const yMax = Math.ceil(target / step) * step;                  // top tick == yMax
    const ticks: number[] = [];
    for (let v = 0; v <= yMax + 1e-9; v += step) ticks.push(Math.round(v));

    const W = 600, H = 220, padL = 26, padR = 10, padTop = 12, padBot = 14;
    const plotW = W - padL - padR;
    const plotH = H - padTop - padBot;
    const barW = plotW / days;
    const yOf = (v: number) => padTop + plotH - (v / yMax) * plotH; // value → viewBox y

    // Horizontal gridlines exactly on the integer ticks (v=0 doubles as the axis).
    const grid = ticks.map((v) => {
        const y = yOf(v).toFixed(1);
        return `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="rgba(120,160,210,${v === 0 ? '0.28' : '0.10'})" stroke-width="${v === 0 ? '0.8' : '0.6'}"></line>`;
    }).join('');

    // Active-day highlight = a SUBTLE FULL-HEIGHT band (y=0 → full viewBox height),
    // so it reads as a column selection, not a bottom-anchored data bar.
    const dayHl = (activeDay != null && activeDay >= 0 && activeDay < days)
        ? `<rect class="tf-spark-dayhl" x="${(padL + activeDay * barW).toFixed(1)}" y="0" width="${barW.toFixed(2)}" height="${H}"></rect>`
        : '';

    const bars = total.map((c, i) => {
        if (!c || i > lastIdx) return '';   // no bars on empty/future days
        const h = (c / yMax) * plotH;       // mapped to the labeled integer scale
        const x = padL + i * barW;
        const y = padTop + (plotH - h);
        const w = Math.max(barW - 1.5, 1);
        return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="1" fill="rgba(120,160,210,0.16)"></rect>`;
    }).join('');

    // Per-domain horizontal dodge: domains that spike the SAME day with the SAME
    // count would otherwise render as identical, exactly-overlapping polylines —
    // that is why "Markets" was hidden behind "Energy" on Jun 4 (not a key bug;
    // perDomain is keyed by the same domain_id the signals carry). Shift each
    // domain a few viewBox px sideways; the y value stays exactly on its integer
    // gridline (no value distortion).
    const N_DOM = TF_DOMAINS.length;
    const series = TF_DOMAINS.map((d, di) => {
        const counts = perDomain[d.id];
        const domTotal = counts.reduce((s, v) => s + v, 0);
        if (!domTotal) return '';
        const dodge = (di - (N_DOM - 1) / 2) * (barW * 0.12);
        // Only plot points up to today so the line ends at the current day.
        const pts = counts.slice(0, lastIdx + 1).map((v, i) =>
            `${(padL + i * barW + barW / 2 + dodge).toFixed(1)},${yOf(v).toFixed(1)}`
        ).join(' ');
        const dim = activeDomain && activeDomain !== d.id;
        const w = activeDomain === d.id ? 2.6 : 1.6;
        const op = dim ? 0.12 : 0.95;
        return `<polyline points="${pts}" fill="none" stroke="${d.color}" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round" opacity="${op}"></polyline>`;
    }).join('');

    // Transparent per-day hit columns → click filters the list to that day.
    const hits = total.map((_c, i) => {
        if (i > lastIdx) return '';   // future days aren't clickable
        const x = padL + i * barW;
        const sel = activeDay === i ? ' tf-spark-hit--on' : '';
        return `<rect class="tf-spark-hit${sel}" data-tf-day="${i}" x="${x.toFixed(1)}" y="${padTop}" width="${barW.toFixed(2)}" height="${plotH}"><title>${_esc(_dayLabel(i))}</title></rect>`;
    }).join('');

    const midDay = Math.round(days / 2);
    // Crisp HTML Y-axis integer labels overlaid on the (horizontally-stretched)
    // SVG so the digits keep their aspect ratio. Positioned by the SAME fraction
    // as each gridline (preserveAspectRatio=none maps viewBox-y linearly to box
    // height), so "2" sits exactly on the "2" gridline.
    const yLabels = ticks.map((v) =>
        `<span class="tf-spark-ytick" style="top:${((yOf(v) / H) * 100).toFixed(2)}%">${v}</span>`
    ).join('');

    return (
        `<div class="tf-spark-plot">` +
        `<svg class="tf-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Daily per-domain spike trajectory">` +
        grid + dayHl + bars + series + hits +
        `</svg>` +
        `<div class="tf-spark-yaxis" aria-hidden="true">${yLabels}</div>` +
        `</div>` +
        `<div class="tf-spark-axis"><span>DAY 1</span><span>${midDay}</span><span>${days}</span></div>`
    );
}

// ── Bottom-Left quadrant: spiked news list (whole row selects into detail) ───
function _newsItemHtml(a: Alert, domainId: string | undefined): string {
    // No severity badge — everything here is, by definition, a high-impact spike.
    // A slim domain-colored rail (--dom) carries the only color cue needed.
    const color = domainId ? _domainColor(domainId) : '#6f8aa6';
    const dt = new Date(a.triggered_at);
    const when = Number.isNaN(dt.getTime())
        ? ''
        : dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' · ' +
          dt.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    const domChip = domainId
        ? `<span class="tf-news-dom" style="--dom:${color}">${_esc(_domainLabel(domainId))}</span>`
        : '';
    return (
        `<div class="tf-news-item" role="button" tabindex="0" data-tf-alert="${_esc(a.id)}"${domainId ? ` data-tf-domain="${_esc(domainId)}"` : ''} style="--dom:${color}" aria-label="Show detail: ${_esc(a.title || a.target_label || 'Signal')}">` +
        `<span class="tf-news-main">` +
        `<span class="tf-news-title">${_esc(a.title || a.target_label || 'Signal')}</span>` +
        `<span class="tf-news-meta">${domChip}<span class="tf-news-time">${when}</span></span>` +
        `</span>` +
        `<span class="tf-news-go" aria-hidden="true">›</span>` +
        `</div>`
    );
}

/**
 * Per-domain spiked counts for the ACTIVE scope — the selected chart day when
 * `tfActiveDay` is set, otherwise the whole month. Computed from the same
 * `tfSortedAlerts` that feeds the list, so the radar, the header SPIKED count,
 * and the list can never disagree.
 */
function _scopedSpikedCounts(): Record<string, number> {
    const counts: Record<string, number> = {};
    for (const a of tfSortedAlerts) {
        if (tfActiveDay != null && _alertDayIndex(a) !== tfActiveDay) continue;
        const d = tfAlertDomain.get(a.id);
        if (d) counts[d] = (counts[d] || 0) + 1;
    }
    return counts;
}

/** Render the news list from cached alerts, filtered by the active domain AND day. */
function _renderNewsList(newsEl: HTMLElement, countEl: HTMLElement | null): void {
    if (!tfSortedAlerts.length) {
        newsEl.innerHTML = `<div class="tf-news-empty">No spiked signals this month.</div>`;
        if (countEl) countEl.textContent = '0';
        return;
    }
    let items = tfSortedAlerts;
    if (tfActiveDomain) items = items.filter((a) => tfAlertDomain.get(a.id) === tfActiveDomain);
    if (tfActiveDay != null) items = items.filter((a) => _alertDayIndex(a) === tfActiveDay);

    if (!items.length) {
        const scope = [
            tfActiveDomain ? _domainLabel(tfActiveDomain) : '',
            tfActiveDay != null ? _dayLabel(tfActiveDay) : '',
        ].filter(Boolean).join(' · ');
        newsEl.innerHTML = `<div class="tf-news-empty">No spikes${scope ? ` for ${_esc(scope)}` : ''} this month.</div>`;
        if (countEl) countEl.textContent = '0';
        return;
    }
    const unfiltered = !tfActiveDomain && tfActiveDay == null;
    const overflowNote = (unfiltered && tfNewsOverflow > 0)
        ? `<div class="tf-news-more">+${tfNewsOverflow} more spiked source${tfNewsOverflow === 1 ? '' : 's'} this month</div>`
        : '';
    newsEl.innerHTML = items.map((a) => _newsItemHtml(a, tfAlertDomain.get(a.id))).join('') + overflowNote;
    if (countEl) countEl.textContent = String(items.length);

    // Re-apply the persistent master-detail selection highlight after any re-render.
    if (tfSelectedId) {
        newsEl.querySelectorAll<HTMLElement>('.tf-news-item').forEach((el) =>
            el.classList.toggle('tf-news-item--active', el.getAttribute('data-tf-alert') === tfSelectedId));
    }

    newsEl.classList.remove('tf-news-anim');
    void newsEl.offsetWidth;
    newsEl.classList.add('tf-news-anim');
}

/**
 * Paint the Top-Left chart and Bottom-Left list from the snapshot's SELF-CONTAINED
 * `summary.signals` payload — no live alert resolution. The snapshot is frozen at
 * generation time and survives alert_logs retention purges. Each signal mirrors the
 * /api/alerts/{id} shape, so it feeds the existing Alert renderers (chart, list,
 * chudDetailHtml) directly — synchronous, zero network round-trips.
 */
function _hydrate(
    snapshot: MonthlyTrendSnapshot,
    chartEl: HTMLElement,
    newsEl: HTMLElement,
    countEl: HTMLElement | null,
): void {
    const signals: Alert[] = Array.isArray((snapshot.summary as any)?.signals)
        ? ((snapshot.summary as any).signals as Alert[])
        : [];

    tfPeriodStartMs = new Date(snapshot.period.start).getTime();
    tfNewsOverflow = 0;
    const alertDomain = new Map<string, string>();
    for (const s of signals) {
        const dom = (s as any).domain_id;
        if (dom && !alertDomain.has(s.id)) alertDomain.set(s.id, dom);
    }
    tfAlertDomain = alertDomain;

    if (!signals.length) {
        tfSortedAlerts = [];
        chartEl.innerHTML = `<div class="tf-chart-empty">No spike trajectory</div>`;
        newsEl.innerHTML = `<div class="tf-news-empty">No spiked signals in ${_esc(snapshot.period?.label ?? 'this period')}.</div>`;
        if (countEl) countEl.textContent = '0';
        return;
    }

    const alerts = signals.slice().sort(
        (a, b) => new Date(b.triggered_at).getTime() - new Date(a.triggered_at).getTime(),
    );
    tfSortedAlerts = alerts;

    chartEl.innerHTML = `<div class="tf-spark-wrap">${_sparklineSvg(snapshot.period, alerts, tfActiveDomain, tfActiveDay)}</div>`;
    _renderNewsList(newsEl, countEl);
}

// ── Entry point ──────────────────────────────────────────────────────────────
export async function renderTrendFlow(container: HTMLElement, _userTier: string = 'free'): Promise<void> {
    disposeTrendFlow();

    container.innerHTML =
        `<div class="tf-root tf-root--quad">` +
        `<div class="tf-head">` +
        `<div class="tf-head-left">` +
        `<span class="tf-title">MONTHLY TREND FLOW</span>` +
        `<span class="tf-sub" data-tf-sub>Per-domain pressure spikes across the 6 strategic sectors</span>` +
        `</div>` +
        `<div class="tf-controls">` +
        `<select class="tf-archive" data-tf-archive aria-label="Select archived month"></select>` +
        `</div>` +
        `</div>` +
        `<div class="tf-statbar" data-tf-stats></div>` +
        `<div class="tf-grid tf-grid--quad">` +
        // ── TL: chart ──────────────────────────────────────────────────────
        `<div class="tf-panel tf-quad tf-quad--chart">` +
        `<div class="tf-panel-head"><span class="tf-panel-title">30-DAY SPIKE TRAJECTORY</span>` +
        `<span class="tf-legend"><i class="tf-legend-bar"></i>volatility <i class="tf-legend-line"></i>per-domain · click a day</span></div>` +
        `<div class="tf-panel-body tf-chart tf-chart--wide" data-tf-chart><div class="tf-chart-load">Loading…</div></div>` +
        `</div>` +
        // ── TR: sector pressure orbit ──────────────────────────────────────
        `<div class="tf-panel tf-quad tf-quad--orbit" data-tf-orbit-panel>` +
        `<div class="tf-panel-head"><span class="tf-panel-title">SECTOR PRESSURE</span>` +
        `<span class="tf-panel-tag">6 domains · tap to filter</span></div>` +
        `<div class="tf-panel-body tf-orbit-body" data-tf-orbit-host></div>` +
        `</div>` +
        // ── BL: spiked signals list ────────────────────────────────────────
        `<div class="tf-panel tf-quad tf-quad--news">` +
        `<div class="tf-panel-head"><div class="tf-panel-headcol">` +
        `<span class="tf-panel-title">SPIKED SIGNALS</span>` +
        `<span class="tf-panel-subnote">Exclusively high-impact signals — already filtered to 1.5×+ per-domain spikes</span>` +
        `</div>` +
        `<span class="tf-panel-tag"><b data-tf-newscount>0</b> stories</span>` +
        `<button type="button" class="tf-day-reset" data-tf-day-reset hidden></button></div>` +
        `<div class="tf-panel-body tf-newsfeed" data-tf-news><div class="tf-news-load">Loading…</div></div>` +
        `</div>` +
        // ── BR: signal detail (reuses the Alert Stream detail pane) ─────────
        `<div class="tf-panel tf-quad tf-quad--detail">` +
        `<div class="tf-panel-head"><span class="tf-panel-title">SIGNAL DETAIL</span>` +
        `<span class="tf-panel-tag" data-tf-detail-tag>select a signal</span></div>` +
        `<div class="tf-panel-body tf-detail-body"><div class="chud-detail" data-tf-detail></div></div>` +
        `</div>` +
        `</div>` +
        `</div>`;

    const archive = container.querySelector<HTMLSelectElement>('[data-tf-archive]')!;
    const statsEl = container.querySelector<HTMLElement>('[data-tf-stats]')!;
    const subEl = container.querySelector<HTMLElement>('[data-tf-sub]')!;
    const chartEl = container.querySelector<HTMLElement>('[data-tf-chart]')!;
    const orbitPanel = container.querySelector<HTMLElement>('[data-tf-orbit-panel]')!;
    const orbitHost = container.querySelector<HTMLElement>('[data-tf-orbit-host]')!;
    const newsEl = container.querySelector<HTMLElement>('[data-tf-news]')!;
    const newsCountEl = container.querySelector<HTMLElement>('[data-tf-newscount]');
    const resetChipEl = container.querySelector<HTMLButtonElement>('[data-tf-day-reset]');
    const detailEl = container.querySelector<HTMLElement>('[data-tf-detail]')!;
    const detailTagEl = container.querySelector<HTMLElement>('[data-tf-detail-tag]');

    let lastSnap: MonthlyTrendSnapshot | null = null;

    const renderChart = () => {
        if (!lastSnap) return;
        const wrap = chartEl.querySelector<HTMLElement>('.tf-spark-wrap');
        if (wrap) wrap.innerHTML = _sparklineSvg(lastSnap.period, tfSortedAlerts, tfActiveDomain, tfActiveDay);
    };

    // ── Bottom-Right: render an alert's detail into the persistent pane ──────
    const clearDetail = () => {
        tfSelectedId = null;
        detailEl.innerHTML = chudDetailHtml(null);
        wirePanelGuideTooltips(detailEl);
        if (detailTagEl) detailTagEl.textContent = 'select a signal';
        newsEl.querySelectorAll<HTMLElement>('.tf-news-item--active').forEach((el) => el.classList.remove('tf-news-item--active'));
    };
    const selectAlert = (id: string) => {
        const a = tfSortedAlerts.find((x) => x.id === id);
        if (!a) return;
        tfSelectedId = id;
        detailEl.innerHTML = chudDetailHtml(a);
        wirePanelGuideTooltips(detailEl);
        detailEl.scrollTop = 0;
        if (detailTagEl) {
            const dom = tfAlertDomain.get(id);
            detailTagEl.textContent = dom ? _domainLabel(dom).toUpperCase() : 'signal';
        }
        newsEl.querySelectorAll<HTMLElement>('.tf-news-item').forEach((el) =>
            el.classList.toggle('tf-news-item--active', el.getAttribute('data-tf-alert') === id));
    };

    // Discoverable "Show all month" reset — shown whenever a day/sector narrows
    // the view; clicking it clears BOTH filters and returns the full month.
    const renderResetChip = () => {
        if (!resetChipEl) return;
        const parts: string[] = [];
        if (tfActiveDay != null) parts.push(_dayLabel(tfActiveDay));
        if (tfActiveDomain) parts.push(_domainLabel(tfActiveDomain));
        if (parts.length) {
            resetChipEl.innerHTML = `✕ ${_esc(parts.join(' · '))} · Show all month`;
            resetChipEl.hidden = false;
        } else {
            resetChipEl.hidden = true;
        }
    };

    // Re-sync radar + header + chart + list to the ACTIVE scope. The radar node
    // counts, the header SPIKED total, and the list all derive from the same
    // day-scoped counts, so "03 SPIKED" and the list can no longer disagree.
    const refresh = () => {
        const counts = _scopedSpikedCounts();
        const scopedTotal = Object.values(counts).reduce((sum, v) => sum + v, 0);

        orbitHost.innerHTML = _buildOrbit(counts);   // radar scales to the active day
        orbitHost.querySelectorAll<HTMLElement>('.tf-orbit-node').forEach((n) => {
            const active = n.getAttribute('data-tf-domain') === tfActiveDomain;
            n.classList.toggle('tf-orbit-node--active', active);
            n.setAttribute('aria-pressed', String(active));
        });
        orbitHost.querySelector('.tf-orbit')?.classList.toggle('tf-orbit--filtered', !!tfActiveDomain);
        const stateEl = orbitHost.querySelector<HTMLElement>('[data-tf-core-state]');
        if (stateEl) {
            stateEl.textContent = tfActiveDay != null
                ? _dayLabel(tfActiveDay).toUpperCase()
                : (tfActiveDomain ? `${_domainLabel(tfActiveDomain).toUpperCase()} ONLY` : 'TOTAL SPIKED');
        }
        // Header SPIKED count follows the same scope.
        const spikedEl = statsEl.querySelector<HTMLElement>('[data-tf-spiked]');
        if (spikedEl) spikedEl.textContent = String(scopedTotal);

        renderResetChip();
        renderChart();
        _renderNewsList(newsEl, newsCountEl);
    };

    // Orbit interactions (delegated on the stable panel; the orbit body re-renders per month).
    orbitPanel.addEventListener('click', (e) => {
        const target = e.target as HTMLElement;
        const node = target.closest<HTMLElement>('.tf-orbit-node');
        if (node) {
            const d = node.getAttribute('data-tf-domain') || '';
            tfActiveDomain = tfActiveDomain === d ? null : d; // toggle off if re-clicked
            refresh();
            return;
        }
        if (target.closest('.tf-orbit-core')) { tfActiveDomain = null; refresh(); }
    });

    // Chart: click a day → filter the Bottom-Left list to that day (toggle off if re-clicked).
    chartEl.addEventListener('click', (e) => {
        const hit = (e.target as HTMLElement).closest('[data-tf-day]');
        if (!hit) return;
        const day = parseInt(hit.getAttribute('data-tf-day') || '-1', 10);
        if (day < 0) return;
        tfActiveDay = tfActiveDay === day ? null : day;
        refresh();
    });

    // "Show all month" reset — clears the day AND sector filters in one click.
    resetChipEl?.addEventListener('click', () => {
        tfActiveDay = null;
        tfActiveDomain = null;
        refresh();
    });

    // List item → render its detail into the Bottom-Right pane (master-detail).
    newsEl.addEventListener('click', (e) => {
        const btn = (e.target as HTMLElement).closest<HTMLElement>('.tf-news-item');
        if (btn) selectAlert(btn.getAttribute('data-tf-alert') || '');
    });
    newsEl.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const btn = (e.target as HTMLElement).closest<HTMLElement>('.tf-news-item');
        if (btn) { e.preventDefault(); selectAlert(btn.getAttribute('data-tf-alert') || ''); }
    });

    // Bottom-Right pane interactions — mirrors the Alert Stream detail handler:
    // the secondary-sources accordion (inline) and the mobile ✕ Close button.
    detailEl.addEventListener('click', (e) => {
        const t = e.target as HTMLElement;
        if (t.closest('[data-chud-back]')) { clearDetail(); return; }
        const srcToggle = t.closest<HTMLElement>('[data-chud-src-toggle]');
        if (srcToggle) {
            const sec = srcToggle.previousElementSibling as HTMLElement | null;
            if (sec && sec.classList.contains('chud-src-secondary')) {
                const expanded = !sec.classList.contains('expanded');
                sec.classList.toggle('expanded', expanded);
                srcToggle.setAttribute('aria-expanded', String(expanded));
                const secCount = sec.querySelectorAll('.chud-src-row').length;
                const caret = expanded ? '▴' : '▾';
                srcToggle.innerHTML =
                    `${expanded ? 'Hide' : `View all ${secCount}`} secondary sources `
                    + `<span class="chud-src-more-caret">${caret}</span>`;
            }
        }
    });

    const showFlow = (snap: MonthlyTrendSnapshot | null) => {
        tfActiveDomain = null; // reset filters + selection on month change
        tfActiveDay = null;
        tfSelectedId = null;
        lastSnap = snap;
        if (resetChipEl) resetChipEl.hidden = true;
        clearDetail();
        if (!snap) {
            statsEl.innerHTML = '';
            chartEl.innerHTML = `<div class="tf-chart-empty">No data</div>`;
            newsEl.innerHTML =
                `<div class="tf-empty"><div class="tf-empty-glyph" aria-hidden="true">📡</div>` +
                `<div class="tf-empty-title">NO ARCHIVES YET</div>` +
                `<div class="tf-empty-sub">Monthly snapshots are generated at the start of each month.</div></div>`;
            if (newsCountEl) newsCountEl.textContent = '0';
            orbitHost.innerHTML = `<p class="tf-muted">Awaiting first archived month.</p>`;
            tfAlertDomain = new Map();
            tfSortedAlerts = [];
            return;
        }
        subEl.textContent = `${snap.period.label} · per-domain pressure spikes across the 6 strategic sectors`;
        _renderSummary(statsEl, snap);
        _hydrate(snap, chartEl, newsEl, newsCountEl);   // populates tfSortedAlerts + tfAlertDomain
        // Build the radar from the SAME scoped source as the list (whole month on
        // load, since tfActiveDay is null) so they agree from the first paint.
        orbitHost.innerHTML = _buildOrbit(_scopedSpikedCounts());
        renderResetChip();
        // Auto-select the top signal so the detail pane is populated by default
        // (mirrors the Alert Stream's master-detail initial projection).
        if (tfSortedAlerts.length) selectAlert(tfSortedAlerts[0].id);
    };

    archive.addEventListener('change', async () => {
        const [y, m] = archive.value.split('-').map((x) => parseInt(x, 10));
        if (!y || !m) return;
        chartEl.innerHTML = `<div class="tf-chart-load">Loading…</div>`;
        newsEl.innerHTML = `<div class="tf-news-load">Loading…</div>`;
        try {
            showFlow(await fetchMonthlyTrend(y, m));
        } catch (err: any) {
            newsEl.innerHTML = `<div class="tf-news-empty">${_esc(err?.message || 'Load failed')}</div>`;
        }
    });

    try {
        const [index, latest] = await Promise.all([
            fetchMonthlyTrendIndex().catch(() => [] as MonthlyTrendIndexItem[]),
            fetchLatestMonthlyTrend(),
        ]);

        if (index.length) {
            archive.innerHTML = index
                .map((it) => `<option value="${it.year}-${it.month}">${_esc(it.label)}</option>`)
                .join('');
        } else {
            archive.innerHTML = '<option value="">No months yet</option>';
            archive.disabled = true;
        }
        showFlow(latest);
    } catch (err: any) {
        newsEl.innerHTML =
            `<div class="tf-empty"><div class="tf-empty-title">Could not load Trend Flow</div>` +
            `<div class="tf-empty-sub">${_esc(err?.message || 'Connection error')}</div></div>`;
    }
}
