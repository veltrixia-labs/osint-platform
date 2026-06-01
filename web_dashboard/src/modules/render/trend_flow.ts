/**
 * Monthly Trend Flow — pure data analytics cockpit (no map).
 *
 *   • Left  — wide 30-day trajectory chart (per-domain colored spike series +
 *             faint total-volatility bars; click a day → Daily Digest card) +
 *             scrollable spiked-news list
 *   • Right — interactive 6-node Cyber-Orbit sector selector + system physics
 *             (ALWAYS visible — never replaced)
 *
 * Selecting a signal (from the list or a Daily Digest) opens a floating
 * Glassmorphism "Trend Signal Inspector" card overlaying the dashboard, with a
 * frosted backdrop, X / backdrop / Esc close. Each domain has a fixed, distinct
 * color applied to the orbit, the chart series, and the cards. Fully open.
 */
import {
    fetchAlert,
    fetchMonthlyTrendIndex,
    fetchLatestMonthlyTrend,
    fetchMonthlyTrend,
    type Alert,
    type MonthlyTrendIndexItem,
    type MonthlyTrendSnapshot,
} from '../api';

const MAX_NEWS_FETCH = 60; // cap source-alert enrichment per snapshot
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
let tfActiveDay: number | null = null;    // chart day highlight while a Digest is open
let tfPeriodStartMs = 0;            // current period start (UTC ms) for day math
let tfRenderToken = 0;             // bumped each showFlow → guards stale hydration

// Floating-card overlay (Inspector / Daily Digest) — body-level, single at a time.
let tfFloat: HTMLElement | null = null;
let tfFloatKey: ((e: KeyboardEvent) => void) | null = null;

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
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

/** Remove any open floating card + its key handler. */
function _floatClose(): void {
    if (tfFloatKey) { document.removeEventListener('keydown', tfFloatKey); tfFloatKey = null; }
    const ov = tfFloat || document.getElementById('tf-float');
    if (ov) {
        ov.classList.remove('tf-float--in');
        window.setTimeout(() => { try { ov.remove(); } catch { /* gone */ } }, 220);
    }
    tfFloat = null;
}

/**
 * Clear transient state on tab exit. No map/WebGL context to tear down anymore;
 * we bump the render token so any in-flight hydration is discarded.
 */
export function disposeTrendFlow(): void {
    tfRenderToken++;
    _floatClose();
    tfAlertDomain = new Map();
    tfSortedAlerts = [];
    tfNewsOverflow = 0;
    tfActiveDomain = null;
    tfActiveDay = null;
    tfPeriodStartMs = 0;
}

// ── Top statbar (global month summary) ───────────────────────────────────────
function _renderSummary(statsEl: HTMLElement, snapshot: MonthlyTrendSnapshot): void {
    const s = snapshot.summary || {};
    const top = Array.isArray(s.top_sectors) ? s.top_sectors : [];
    const entropy = typeof s.entropy_index === 'number' ? s.entropy_index.toFixed(3) : (s.entropy_index ?? '—');
    statsEl.innerHTML =
        `<span class="tf-stat"><b>${s.alerts_spiked ?? 0}</b> SPIKED</span>` +
        `<span class="tf-stat tf-stat--dim"><b>${s.alerts_total ?? 0}</b> TOTAL</span>` +
        `<span class="tf-stat"><b>${entropy}</b> H</span>` +
        `<span class="tf-stat"><b>${s.node_count ?? 0}</b> NODES</span>` +
        `<span class="tf-stat"><b>${s.edge_count ?? 0}</b> EDGES</span>` +
        (top.length ? `<span class="tf-stat tf-stat--sectors">${top.map((d: string) => _esc(_domainLabel(d))).join(' · ')}</span>` : '');
}

// ── Right column top: interactive 6-node Cyber-Orbit sector selector ─────────
function _buildOrbit(snapshot: MonthlyTrendSnapshot): string {
    const domains: Record<string, any> = snapshot.summary?.domains || {};
    const R = 37;                      // node ring radius (% of orbit box)
    const SVG = 200, C = SVG / 2, RR = R * 2;
    const N = TF_DOMAINS.length;       // always 6
    const sectorCount = String(N).padStart(2, '0');

    let spokes = '';
    const nodes = TF_DOMAINS.map((d, i) => {
        const spiked = domains[d.id]?.spiked || 0;
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
        `<span class="tf-orbit-core-val">${sectorCount}</span>` +
        `<span class="tf-orbit-core-lbl" data-tf-core-state>ALL ${N} SECTORS</span>` +
        `</button>` +
        nodes +
        `</div>`
    );
}

// ── Right column bottom: system physics statistics ───────────────────────────
function _renderAnalytics(el: HTMLElement, snapshot: MonthlyTrendSnapshot): void {
    const s = snapshot.summary || {};
    const entropy = typeof s.entropy_index === 'number' ? s.entropy_index.toFixed(3) : '—';
    const visc = typeof s.viscosity_coefficient === 'number' ? s.viscosity_coefficient.toFixed(1) : '—';
    const ratio = typeof s.spike_ratio === 'number' ? `${s.spike_ratio.toFixed(1)}×` : '—';

    el.innerHTML =
        `<div class="tf-panel tf-panel--orbit">` +
        `<div class="tf-panel-head"><span class="tf-panel-title">SECTOR PRESSURE</span>` +
        `<span class="tf-panel-tag">6 domains · tap to filter</span></div>` +
        `<div class="tf-panel-body tf-orbit-body">${_buildOrbit(snapshot)}</div>` +
        `</div>` +
        `<div class="tf-panel tf-panel--metrics">` +
        `<div class="tf-panel-head"><span class="tf-panel-title">SYSTEM PHYSICS</span><span class="tf-panel-tag">${_esc(snapshot.schema_version || '')}</span></div>` +
        `<div class="tf-panel-body tf-metric-grid">` +
        `<div class="tf-metric"><span class="tf-metric-val">${entropy}</span><span class="tf-metric-lbl">Entropy H</span></div>` +
        `<div class="tf-metric"><span class="tf-metric-val">${visc}</span><span class="tf-metric-lbl">Viscosity</span></div>` +
        `<div class="tf-metric"><span class="tf-metric-val tf-metric-val--ok">${ratio}</span><span class="tf-metric-lbl">Per-Domain Gate ✓</span></div>` +
        `<div class="tf-metric"><span class="tf-metric-val">${s.alerts_spiked ?? 0}<i>/${s.alerts_total ?? 0}</i></span><span class="tf-metric-lbl">Spiked / Total</span></div>` +
        `<div class="tf-metric"><span class="tf-metric-val">${s.node_count ?? 0}</span><span class="tf-metric-lbl">Active Nodes</span></div>` +
        `<div class="tf-metric"><span class="tf-metric-val">${s.edge_count ?? 0}</span><span class="tf-metric-lbl">Ripple Edges</span></div>` +
        `</div></div>`;
}

// ── Left column top: 30-day trajectory — per-domain colored spike series ─────
// Returns the chart markup (stretched SVG for the plot + a crisp HTML axis row).
// No cursor-following tooltip (it clipped at the panel edge) — days are clickable.
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
        total[idx] += 1;
        const dom = tfAlertDomain.get(a.id);
        if (dom && perDomain[dom]) perDomain[dom][idx] += 1;
    }

    const W = 600, H = 220, padX = 10, padTop = 12, padBot = 14;
    const maxTotal = Math.max(1, ...total);
    const plotW = W - padX * 2;
    const plotH = H - padTop - padBot;
    const barW = plotW / days;

    const grid = [0.25, 0.5, 0.75, 1].map((f) => {
        const y = padTop + plotH - f * plotH;
        return `<line x1="${padX}" y1="${y.toFixed(1)}" x2="${W - padX}" y2="${y.toFixed(1)}" stroke="rgba(120,160,210,0.10)" stroke-width="0.6"></line>`;
    }).join('');

    const dayHl = (activeDay != null && activeDay >= 0 && activeDay < days)
        ? `<rect class="tf-spark-dayhl" x="${(padX + activeDay * barW).toFixed(1)}" y="${padTop}" width="${barW.toFixed(2)}" height="${plotH}"></rect>`
        : '';

    const bars = total.map((c, i) => {
        if (!c) return '';
        const h = (c / maxTotal) * plotH;
        const x = padX + i * barW;
        const y = padTop + (plotH - h);
        const w = Math.max(barW - 1.5, 1);
        return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="1" fill="rgba(120,160,210,0.16)"></rect>`;
    }).join('');

    const series = TF_DOMAINS.map((d) => {
        const counts = perDomain[d.id];
        const domTotal = counts.reduce((s, v) => s + v, 0);
        if (!domTotal) return '';
        const pts = counts.map((v, i) => {
            const x = padX + i * barW + barW / 2;
            const y = padTop + (plotH - (v / maxTotal) * plotH);
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        }).join(' ');
        const dim = activeDomain && activeDomain !== d.id;
        const w = activeDomain === d.id ? 2.6 : 1.6;
        const op = dim ? 0.12 : 0.95;
        return `<polyline points="${pts}" fill="none" stroke="${d.color}" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round" opacity="${op}"></polyline>`;
    }).join('');

    // Transparent per-day hit columns → click opens the Daily Digest card.
    const hits = total.map((_c, i) => {
        const x = padX + i * barW;
        const sel = activeDay === i ? ' tf-spark-hit--on' : '';
        return `<rect class="tf-spark-hit${sel}" data-tf-day="${i}" x="${x.toFixed(1)}" y="${padTop}" width="${barW.toFixed(2)}" height="${plotH}"><title>${_esc(_dayLabel(i))}</title></rect>`;
    }).join('');

    const axisLine = `<line x1="${padX}" y1="${padTop + plotH}" x2="${W - padX}" y2="${padTop + plotH}" stroke="rgba(120,160,210,0.28)" stroke-width="0.8"></line>`;
    const midDay = Math.round(days / 2);

    return (
        `<svg class="tf-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Daily per-domain spike trajectory">` +
        grid + dayHl + axisLine + bars + series + hits +
        `</svg>` +
        `<div class="tf-spark-axis"><span>DAY 1</span><span>${midDay}</span><span>${days}</span></div>`
    );
}

// ── Left column bottom: spiked news list (whole row opens the Inspector) ─────
function _newsItemHtml(a: Alert, domainId: string | undefined): string {
    // No severity badge — everything here is, by definition, a high-impact spike.
    // A slim domain-colored rail (--dom) carries the only color cue needed.
    const color = domainId ? _domainColor(domainId) : '#6f8aa6';
    const dt = new Date(a.triggered_at);
    const when = Number.isNaN(dt.getTime())
        ? ''
        : dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' · ' +
          dt.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    const domChip = domainId
        ? `<span class="tf-news-dom" style="--dom:${color}">${_esc(_domainLabel(domainId))}</span>`
        : '';
    return (
        `<div class="tf-news-item" role="button" tabindex="0" data-tf-alert="${_esc(a.id)}"${domainId ? ` data-tf-domain="${_esc(domainId)}"` : ''} style="--dom:${color}" aria-label="Inspect signal: ${_esc(a.title || a.target_label || 'Signal')}">` +
        `<span class="tf-news-main">` +
        `<span class="tf-news-title">${_esc(a.title || a.target_label || 'Signal')}</span>` +
        `<span class="tf-news-meta">${domChip}<span class="tf-news-time">${when}</span></span>` +
        `</span>` +
        `<span class="tf-news-go" aria-hidden="true">›</span>` +
        `</div>`
    );
}

/** Render the news list from cached alerts, optionally filtered to one domain. */
function _renderNewsList(newsEl: HTMLElement, countEl: HTMLElement | null, filterDomain: string | null): void {
    if (!tfSortedAlerts.length) {
        newsEl.innerHTML = `<div class="tf-news-empty">No spiked signals this month.</div>`;
        if (countEl) countEl.textContent = '0';
        return;
    }
    const items = filterDomain
        ? tfSortedAlerts.filter((a) => tfAlertDomain.get(a.id) === filterDomain)
        : tfSortedAlerts;

    if (!items.length) {
        newsEl.innerHTML = `<div class="tf-news-empty">No ${_esc(_domainLabel(filterDomain || ''))} spikes this month.</div>`;
        if (countEl) countEl.textContent = '0';
        return;
    }
    const overflowNote = (!filterDomain && tfNewsOverflow > 0)
        ? `<div class="tf-news-more">+${tfNewsOverflow} more spiked source${tfNewsOverflow === 1 ? '' : 's'} this month</div>`
        : '';
    newsEl.innerHTML = items.map((a) => _newsItemHtml(a, tfAlertDomain.get(a.id))).join('') + overflowNote;
    if (countEl) countEl.textContent = String(items.length);

    newsEl.classList.remove('tf-news-anim');
    void newsEl.offsetWidth;
    newsEl.classList.add('tf-news-anim');
}

/** Bounded-concurrency map (avoid hammering the API with 60 parallel requests). */
async function _pool<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
    const out: R[] = new Array(items.length);
    let cursor = 0;
    const workers = new Array(Math.min(limit, items.length)).fill(0).map(async () => {
        while (cursor < items.length) {
            const i = cursor++;
            out[i] = await fn(items[i]);
        }
    });
    await Promise.all(workers);
    return out;
}

async function _hydrateLeftPanels(
    snapshot: MonthlyTrendSnapshot,
    chartEl: HTMLElement,
    newsEl: HTMLElement,
    countEl: HTMLElement | null,
    token: number,
): Promise<void> {
    const domains: Record<string, any> = snapshot.summary?.domains || {};

    const alertDomain = new Map<string, string>();
    const order: string[] = [];
    for (const d of TF_DOMAINS) {
        const ids: string[] = domains[d.id]?.source_alert_ids || [];
        for (const id of ids) {
            if (!alertDomain.has(id)) { alertDomain.set(id, d.id); order.push(id); }
        }
    }
    tfAlertDomain = alertDomain;
    tfPeriodStartMs = new Date(snapshot.period.start).getTime();

    if (!order.length) {
        tfSortedAlerts = [];
        tfNewsOverflow = 0;
        chartEl.innerHTML = `<div class="tf-chart-empty">No spike trajectory</div>`;
        newsEl.innerHTML = `<div class="tf-news-empty">No spiked signals in ${_esc(snapshot.period?.label ?? 'this period')}.</div>`;
        if (countEl) countEl.textContent = '0';
        return;
    }

    const ids = order.slice(0, MAX_NEWS_FETCH);
    tfNewsOverflow = order.length - ids.length;

    chartEl.innerHTML = `<div class="tf-chart-load">Resolving trajectory…</div>`;
    newsEl.innerHTML = `<div class="tf-news-load">Resolving ${ids.length} spiked source${ids.length === 1 ? '' : 's'}…</div>`;

    const results = await _pool(ids, 8, async (id) => {
        try { return await fetchAlert(id); } catch { return null; }
    });
    if (token !== tfRenderToken) return; // a newer month took over

    const alerts = results.filter((a): a is Alert => !!a);
    alerts.sort((a, b) => new Date(b.triggered_at).getTime() - new Date(a.triggered_at).getTime());
    tfSortedAlerts = alerts;

    chartEl.innerHTML = `<div class="tf-spark-wrap">${_sparklineSvg(snapshot.period, alerts, tfActiveDomain, tfActiveDay)}</div>`;
    _renderNewsList(newsEl, countEl, tfActiveDomain);
}

// ── Floating card content builders ───────────────────────────────────────────
function _host(url: string): string {
    try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
}

/**
 * Trend Signal Inspector card body (full detail + all raw source links).
 * When opened from a Daily Digest, `backDay` is that digest's day index → a
 * "‹ Back" control is injected that returns to the digest (modal stacking).
 */
function _inspectorHtml(a: Alert, backDay: number | null = null): string {
    const domainId = tfAlertDomain.get(a.id);
    const accent = domainId ? _domainColor(domainId) : '#00f0ff';
    // Driven STRICTLY by the backend's calibrated intensity_pct (1.5x gate = 50%,
    // >=3.0x = 100%) — no client-side tanh. Absent (cold-start) → 0%.
    const pctVal = Math.max(0, Math.min(100, typeof a.intensity_pct === 'number' ? a.intensity_pct : 0));
    const frac = Math.max(0.04, Math.min(1, pctVal / 100));
    const pct = Math.round(pctVal) + '%'; // integer % — fits cleanly inside the ring
    const dt = new Date(a.triggered_at);
    const when = Number.isNaN(dt.getTime()) ? '—' : dt.toLocaleString(undefined, {
        weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });

    const R = 26, CIRC = 2 * Math.PI * R, offset = CIRC * (1 - frac);
    const gauge =
        `<svg class="tf-insp-gauge" viewBox="0 0 64 64" aria-hidden="true">` +
        `<circle cx="32" cy="32" r="${R}" fill="none" stroke="rgba(120,160,210,0.16)" stroke-width="5"></circle>` +
        `<circle cx="32" cy="32" r="${R}" fill="none" stroke="${accent}" stroke-width="5" stroke-linecap="round"` +
        ` stroke-dasharray="${CIRC.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}" transform="rotate(-90 32 32)"></circle>` +
        `</svg>`;

    const seen = new Set<string>();
    const sources: { url: string; title: string; host: string }[] = [];
    const pushSrc = (url?: string, title?: string) => {
        if (!url || seen.has(url)) return;
        seen.add(url);
        sources.push({ url, title: title || url, host: _host(url) });
    };
    pushSrc(a.source_url, a.title || a.target_label);
    if (Array.isArray(a.evidence_list)) {
        for (const e of a.evidence_list) {
            if (typeof e === 'string') pushSrc(e);
            else if (e && typeof e === 'object') pushSrc(e.url, e.title);
        }
    }
    const sourcesHtml = sources.length
        ? sources.map((s) =>
            `<a class="tf-insp-src" href="${_esc(s.url)}" target="_blank" rel="noopener noreferrer">` +
            `<span class="tf-insp-src-host">${_esc(s.host || 'source')}</span>` +
            `<span class="tf-insp-src-title">${_esc(s.title)}</span>` +
            `<span class="tf-insp-src-go" aria-hidden="true">↗</span>` +
            `</a>`).join('')
        : `<p class="tf-muted">No raw source URLs recorded for this signal.</p>`;

    // Single, cleanly-styled colored domain chip only — no redundant plain topic token.
    const domTag = domainId
        ? `<span class="tf-insp-tag tf-insp-tag--dom" style="--dom:${_domainColor(domainId)}">${_esc(_domainLabel(domainId))}</span>`
        : '';

    const backBtn = backDay != null
        ? `<button type="button" class="tf-insp-back" data-tf-insp-back="${backDay}" aria-label="Back to daily digest">‹ Back</button>`
        : '';
    return (
        `<div class="tf-card-inner" style="--insp:${accent}">` +
        `<header class="tf-insp-head${backDay != null ? ' tf-insp-head--back' : ''}">` +
        backBtn +
        `<span class="tf-insp-kicker">TREND SIGNAL INSPECTOR</span>` +
        `<button type="button" class="tf-float-close" data-tf-float-close aria-label="Close inspector">×</button>` +
        `</header>` +
        `<div class="tf-insp-body">` +
        `<div class="tf-insp-severity">` +
        `<div class="tf-insp-gauge-wrap">${gauge}<span class="tf-insp-gauge-val">${pct}</span></div>` +
        `<div class="tf-insp-sevmeta">` +
        `<span class="tf-insp-sev-label">SIGNAL INTENSITY</span>` +
        `<span class="tf-insp-sev-sub">Normalized strength vs domain baseline</span>` +
        `</div></div>` +
        `<div class="tf-insp-title">${_esc(a.title || a.target_label || 'Signal')}</div>` +
        `<div class="tf-insp-time">🕑 ${_esc(when)}</div>` +
        `<div class="tf-insp-tags">${domTag}</div>` +
        `<div class="tf-insp-srchead">RAW SOURCES <b>${sources.length}</b></div>` +
        `<div class="tf-insp-srclist">${sourcesHtml}</div>` +
        `</div></div>`
    );
}

/**
 * Daily Digest card body — spiked signals on one clicked day. Respects the
 * active orbit sector filter so a "Markets"-filtered chart never leaks other
 * domains' alerts into the digest.
 */
function _digestHtml(day: number): string {
    const items = tfSortedAlerts.filter((a) =>
        _alertDayIndex(a) === day && (!tfActiveDomain || tfAlertDomain.get(a.id) === tfActiveDomain));
    const rows = items.length
        ? items.map((a) => {
            const dom = tfAlertDomain.get(a.id);
            const color = dom ? _domainColor(dom) : '#6f8aa6';
            const dt = new Date(a.triggered_at);
            const when = Number.isNaN(dt.getTime()) ? '' : dt.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
            const domChip = dom ? `<span class="tf-news-dom" style="--dom:${color}">${_esc(_domainLabel(dom))}</span>` : '';
            return (
                `<button type="button" class="tf-digest-item" data-tf-digest-alert="${_esc(a.id)}" style="--dom:${color}">` +
                `<span class="tf-digest-main">` +
                `<span class="tf-digest-title">${_esc(a.title || a.target_label || 'Signal')}</span>` +
                `<span class="tf-digest-meta">${domChip}<span>${when}</span></span>` +
                `</span>` +
                `<span class="tf-digest-go" aria-hidden="true">›</span>` +
                `</button>`
            );
        }).join('')
        : `<p class="tf-muted">No spiked signals on this day.</p>`;

    const accent = tfActiveDomain ? _domainColor(tfActiveDomain) : '#00f0ff';
    const scope = tfActiveDomain ? ` · ${_domainLabel(tfActiveDomain).toUpperCase()}` : '';
    return (
        `<div class="tf-card-inner" style="--insp:${accent}">` +
        `<header class="tf-insp-head">` +
        `<span class="tf-insp-kicker">DAILY DIGEST · ${_esc(_dayLabel(day))}${_esc(scope)}</span>` +
        `<button type="button" class="tf-float-close" data-tf-float-close aria-label="Close digest">×</button>` +
        `</header>` +
        `<div class="tf-insp-body">` +
        `<div class="tf-insp-srchead">SPIKED SIGNALS <b>${items.length}</b></div>` +
        `<div class="tf-digest-list">${rows}</div>` +
        `</div></div>`
    );
}

// ── Entry point ──────────────────────────────────────────────────────────────
export async function renderTrendFlow(container: HTMLElement, _userTier: string = 'free'): Promise<void> {
    disposeTrendFlow();

    container.innerHTML =
        `<div class="tf-root tf-root--analytics">` +
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
        `<div class="tf-grid tf-grid--analytics">` +
        `<div class="tf-col tf-col--main">` +
        `<div class="tf-panel tf-panel--chart">` +
        `<div class="tf-panel-head"><span class="tf-panel-title">30-DAY SPIKE TRAJECTORY</span>` +
        `<span class="tf-legend"><i class="tf-legend-bar"></i>volatility <i class="tf-legend-line"></i>per-domain · click a day</span></div>` +
        `<div class="tf-panel-body tf-chart tf-chart--wide" data-tf-chart><div class="tf-chart-load">Loading…</div></div>` +
        `</div>` +
        `<div class="tf-panel tf-panel--news">` +
        `<div class="tf-panel-head"><div class="tf-panel-headcol">` +
        `<span class="tf-panel-title">SPIKED SIGNALS</span>` +
        `<span class="tf-panel-subnote">Exclusively high-impact signals — already filtered to 1.5×+ per-domain spikes</span>` +
        `</div>` +
        `<span class="tf-panel-tag"><b data-tf-newscount>0</b> stories<span class="tf-news-filtertag" data-tf-filtertag hidden></span></span></div>` +
        `<div class="tf-panel-body tf-newsfeed" data-tf-news><div class="tf-news-load">Loading…</div></div>` +
        `</div>` +
        `</div>` +
        `<div class="tf-col tf-col--side" data-tf-analytics></div>` +
        `</div>` +
        `</div>`;

    const archive = container.querySelector<HTMLSelectElement>('[data-tf-archive]')!;
    const statsEl = container.querySelector<HTMLElement>('[data-tf-stats]')!;
    const subEl = container.querySelector<HTMLElement>('[data-tf-sub]')!;
    const chartEl = container.querySelector<HTMLElement>('[data-tf-chart]')!;
    const newsEl = container.querySelector<HTMLElement>('[data-tf-news]')!;
    const newsCountEl = container.querySelector<HTMLElement>('[data-tf-newscount]');
    const filterTagEl = container.querySelector<HTMLElement>('[data-tf-filtertag]');
    const analyticsEl = container.querySelector<HTMLElement>('[data-tf-analytics]')!;

    let lastSnap: MonthlyTrendSnapshot | null = null;

    const renderChart = () => {
        if (!lastSnap) return;
        const wrap = chartEl.querySelector<HTMLElement>('.tf-spark-wrap');
        if (wrap) wrap.innerHTML = _sparklineSvg(lastSnap.period, tfSortedAlerts, tfActiveDomain, tfActiveDay);
    };

    // ── Floating card (Inspector / Daily Digest) — overlays the whole HUD ────
    const closeCard = () => {
        _floatClose();
        if (tfActiveDay != null) { tfActiveDay = null; renderChart(); } // clear day highlight
    };
    const openCard = (html: string) => {
        _floatClose();
        const ov = document.createElement('div');
        ov.className = 'tf-float';
        ov.id = 'tf-float';
        ov.innerHTML = `<div class="tf-float-backdrop" data-tf-float-close></div><div class="tf-float-card" role="dialog" aria-modal="true">${html}</div>`;
        document.body.appendChild(ov);
        tfFloat = ov;
        requestAnimationFrame(() => ov.classList.add('tf-float--in'));
        ov.addEventListener('click', (e) => {
            const t = e.target as HTMLElement;
            if (t.closest('[data-tf-float-close]')) { closeCard(); return; }
            if (t.closest('a.tf-insp-src')) return; // raw-source links navigate freely
            const card = ov.querySelector<HTMLElement>('.tf-float-card');
            // ‹ Back: return from the Inspector to the Daily Digest it came from.
            const back = t.closest<HTMLElement>('[data-tf-insp-back]');
            if (back) {
                const day = parseInt(back.getAttribute('data-tf-insp-back') || '-1', 10);
                if (day >= 0 && card) card.innerHTML = _digestHtml(day);
                return;
            }
            // Unified navigation: a Daily Digest row opens the same Inspector card
            // (carrying the digest's day so the Inspector shows a ‹ Back control).
            const drow = t.closest<HTMLElement>('[data-tf-digest-alert]');
            if (drow) {
                const a = tfSortedAlerts.find((x) => x.id === drow.getAttribute('data-tf-digest-alert'));
                if (a && card) card.innerHTML = _inspectorHtml(a, tfActiveDay);
            }
        });
        tfFloatKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); closeCard(); } };
        document.addEventListener('keydown', tfFloatKey);
    };
    const openInspector = (alertId: string) => {
        const a = tfSortedAlerts.find((x) => x.id === alertId);
        if (a) openCard(_inspectorHtml(a));
    };
    const openDigest = (day: number) => {
        tfActiveDay = day;
        renderChart();              // highlight the selected day column
        openCard(_digestHtml(day));
    };

    // Re-sync orbit visuals, filter tag, chart, and news to the active domain.
    const refresh = () => {
        analyticsEl.querySelectorAll<HTMLElement>('.tf-orbit-node').forEach((n) => {
            const active = n.getAttribute('data-tf-domain') === tfActiveDomain;
            n.classList.toggle('tf-orbit-node--active', active);
            n.setAttribute('aria-pressed', String(active));
        });
        analyticsEl.querySelector('.tf-orbit')?.classList.toggle('tf-orbit--filtered', !!tfActiveDomain);
        const stateEl = analyticsEl.querySelector<HTMLElement>('[data-tf-core-state]');
        if (stateEl) stateEl.textContent = tfActiveDomain ? `${_domainLabel(tfActiveDomain).toUpperCase()} ONLY` : `ALL ${TF_DOMAINS.length} SECTORS`;
        if (filterTagEl) {
            if (tfActiveDomain) { filterTagEl.textContent = ` · ${_domainLabel(tfActiveDomain).toUpperCase()}`; filterTagEl.hidden = false; }
            else filterTagEl.hidden = true;
        }
        renderChart();
        _renderNewsList(newsEl, newsCountEl, tfActiveDomain);
    };

    // Orbit interactions (delegated; analyticsEl persists across re-renders).
    analyticsEl.addEventListener('click', (e) => {
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

    // Chart: click a day → Daily Digest card (no clipping hover tooltip).
    chartEl.addEventListener('click', (e) => {
        const hit = (e.target as HTMLElement).closest('[data-tf-day]');
        if (!hit) return;
        const day = parseInt(hit.getAttribute('data-tf-day') || '-1', 10);
        if (day >= 0) openDigest(day);
    });

    // News item → open the Trend Signal Inspector (whole row is the trigger).
    newsEl.addEventListener('click', (e) => {
        const btn = (e.target as HTMLElement).closest<HTMLElement>('.tf-news-item');
        if (btn) openInspector(btn.getAttribute('data-tf-alert') || '');
    });
    newsEl.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const btn = (e.target as HTMLElement).closest<HTMLElement>('.tf-news-item');
        if (btn) { e.preventDefault(); openInspector(btn.getAttribute('data-tf-alert') || ''); }
    });

    const showFlow = (snap: MonthlyTrendSnapshot | null) => {
        const token = ++tfRenderToken;
        tfActiveDomain = null; // reset filters on month change
        tfActiveDay = null;
        _floatClose();         // close any open card
        lastSnap = snap;
        if (filterTagEl) filterTagEl.hidden = true;
        if (!snap) {
            statsEl.innerHTML = '';
            chartEl.innerHTML = `<div class="tf-chart-empty">No data</div>`;
            newsEl.innerHTML =
                `<div class="tf-empty"><div class="tf-empty-glyph" aria-hidden="true">📡</div>` +
                `<div class="tf-empty-title">NO ARCHIVES YET</div>` +
                `<div class="tf-empty-sub">Monthly snapshots are generated at the start of each month.</div></div>`;
            if (newsCountEl) newsCountEl.textContent = '0';
            analyticsEl.innerHTML =
                `<div class="tf-panel"><div class="tf-panel-head"><span class="tf-panel-title">SECTOR PRESSURE</span></div>` +
                `<div class="tf-panel-body"><p class="tf-muted">Awaiting first archived month.</p></div></div>`;
            tfAlertDomain = new Map();
            tfSortedAlerts = [];
            return;
        }
        subEl.textContent = `${snap.period.label} · per-domain pressure spikes across the 6 strategic sectors`;
        _renderSummary(statsEl, snap);
        _renderAnalytics(analyticsEl, snap);
        void _hydrateLeftPanels(snap, chartEl, newsEl, newsCountEl, token);
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
