import { type Alert, type DomainItem, fetchMarketEntropy } from '../api';
import {
    STRATEGIC_TOPIC_FILTERS,
    getTopicColor,
    getTopicDisplayLabel,
    getTopicCssVars,
    normalizeTopicCode,
    type StrategicTopicCode,
} from '../topics';
import { resolveAlertHeadline } from '../alert_display';
import { formatIntelDate, formatIntelFeedTimestamp, formatIntelRelativeTimestamp, formatIntelTime } from './utils';
import { DEV_MODE_AUDIT } from '../dev_mode';
import { renderPanelGuide, wirePanelGuideTooltips } from './pro_dashboard_primitives';

type ThreatLevelTier = 'critical' | 'elevated' | 'watch';

function normalizeThreatLevel(severity: string | undefined): ThreatLevelTier {
    const key = (severity || '').toLowerCase();
    if (key === 'critical') return 'critical';
    if (key === 'elevated') return 'elevated';
    return 'watch';
}

// The displayed tier is derived from IMPORTANCE (the Stream headline axis), NOT the
// anomaly intensity_pct and NOT the raw stored severity. Bands mirror the scoring
// prompt: >=80 => CRITICAL, >=50 => ELEVATED, else STANDARD (the 'watch' tier key,
// relabeled in the UI). Anomaly is kept only as a secondary gauge on the detail ring.
// Falls back to the stored severity string only when importance_score is absent
// (rare legacy/unscored rows). Anomaly intensity_pct is no longer used for tiering;
// it survives only as a secondary gauge on the detail ring (read directly there).
const IMPORTANCE_CRITICAL = 80;
const IMPORTANCE_ELEVATED = 50;
function alertThreatTier(alert: { importance_score?: number | null; intensity_pct?: number | null; severity?: string }): ThreatLevelTier {
    const imp = typeof alert.importance_score === 'number' ? alert.importance_score : null;
    if (imp !== null) {
        if (imp >= IMPORTANCE_CRITICAL) return 'critical';
        if (imp >= IMPORTANCE_ELEVATED) return 'elevated';
        return 'watch';
    }
    return normalizeThreatLevel(alert.severity);
}

// Human-facing tier label. The internal tier key stays 'watch' (so every
// `severity-watch` / `chud-sev--watch` CSS rule keeps working) but the bottom
// tier now READS as "STANDARD" in the feed per the recalibration.
const TIER_LABEL: Record<ThreatLevelTier, string> = {
    critical: 'CRITICAL',
    elevated: 'ELEVATED',
    watch: 'STANDARD',
};

/**
 * [v34] Simplified Evidence Modal for Live Alerts (Non-global)
 */
export function showEvidenceModal(title: string, evidenceList: any[]) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    overlay.innerHTML = `
        <div class="modal-card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem; border-bottom:1px solid var(--border); padding-bottom:1rem;">
                <h3 style="font-size:1.1rem; color:#58a6ff;">Evidence: ${chudEscape(String(title || ''))}</h3>
                <button class="modal-close-btn" style="background:none; border:none; color:#8b949e; cursor:pointer; font-size:1.5rem;">&times;</button>
            </div>
            <div style="display:flex; flex-direction:column; gap:1.5rem;">
                ${evidenceList.map((item, index) => {
                    // Every value below is external: titles and urls originate in the RSS
                    // items behind alert_logs.metadata_json.evidence_list, and `domain` is
                    // urlparse(...).netloc of an external url. Escape all three, and gate
                    // the href on scheme — chudEscape blocks attribute breakout but leaves
                    // `javascript:` intact, which is live on click.
                    const safeUrl = chudSafeUrl(item.url || item.link);
                    return `
                    <div class="evidence-item" style="border-left:2px solid var(--accent); padding-left:1rem;">

                        ${index === 0 ? `<div class="primary-badge">PRIMARY</div>` : ''}

                        <div style="font-weight:600; color:#c9d1d9; font-size:0.9rem; margin-bottom:0.5rem;">
                            ${chudEscape(String(item.title || 'Source Signal'))}
                        </div>

                        <div style="display:flex; gap:0.5rem; align-items:center; margin-bottom:0.75rem;">
                            <span class="evidence-domain">${chudEscape(String(item.domain || item.type || 'OSINT'))}</span>
                        </div>

                        ${safeUrl ? `
                            <a href="${chudEscape(safeUrl)}" target="_blank" rel="noopener noreferrer"
                            style="color:#58a6ff; text-decoration:none; font-size:0.8rem; font-weight:600;">
                            🔗 View Source &rarr;
                            </a>
                        ` : '<div style="font-size:0.8rem; color:#8b949e;">🔒 Restricted Source</div>'}
                    </div>
                `;
                }).join('')}
                ${evidenceList.length === 0 ? '<p style="text-align:center; opacity:0.6;">No supporting sources available.</p>' : ''}
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
    const close = () => document.body.removeChild(overlay);
    overlay.querySelector('.modal-close-btn')?.addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
}

export function renderTopicFilterBar(
    container: HTMLElement,
    activeTopic: StrategicTopicCode | null,
    onSelect: (topic: StrategicTopicCode | null) => void,
): void {
    const allActive = activeTopic === null;
    const activeLabel = allActive
        ? 'All'
        : (STRATEGIC_TOPIC_FILTERS.find(f => f.code === activeTopic)?.label ?? 'All');
    // Re-render always starts the (mobile) dropdown collapsed.
    container.classList.remove('is-open');
    container.innerHTML = `
        <button type="button" class="topic-mobile-toggle" data-topic-mobile-toggle aria-expanded="false">
            <span class="topic-mobile-current">${activeLabel}</span>
            <span class="topic-mobile-caret" aria-hidden="true">▾</span>
        </button>
        <div class="topic-pills">
            <button type="button" class="topic-btn ${allActive ? 'topic-btn--active' : ''}" data-topic="">
                All
            </button>
            ${STRATEGIC_TOPIC_FILTERS.map(({ code, label, color }) => `
                <button
                    type="button"
                    class="topic-btn ${activeTopic === code ? 'topic-btn--active' : ''}"
                    data-topic="${code}"
                    style="--topic-color:${color}; border-color: color-mix(in srgb, ${color} 45%, var(--border));"
                >
                    ${label}
                </button>
            `).join('')}
        </div>
    `;

    // Mobile: the toggle expands/collapses the category dropdown. On desktop the
    // toggle is display:none and all pills show inline (CSS-driven).
    const mobileToggle = container.querySelector<HTMLButtonElement>('[data-topic-mobile-toggle]');
    mobileToggle?.addEventListener('click', () => {
        const open = container.classList.toggle('is-open');
        mobileToggle.setAttribute('aria-expanded', String(open));
    });

    container.querySelectorAll<HTMLButtonElement>('.topic-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            container.classList.remove('is-open'); // selecting a category closes the dropdown
            const raw = btn.dataset.topic ?? '';
            onSelect(raw ? (raw as StrategicTopicCode) : null);
        });
    });
}

// ════════════════════════════════════════════════════════════════════════
// Phase 8.4 — "Cyber-HUD Terminal" Master-Detail intelligence console.
//
// renderAlerts() is the entry point and is invoked on every ~10s poll. All
// heavy/continuous state below lives at module scope so the scrolling raw-log
// stream and the currently-selected detail survive each re-render without
// flicker, scroll-jump, or duplicated intervals. The first render builds the
// full HUD shell + starts the log engine; subsequent renders take a cheap
// incremental path that only swaps the stream rows.
// ════════════════════════════════════════════════════════════════════════

let chudSelectedId: string | null = null;
// Secondary-sources accordion open-state. Lives at module scope so the ~10s poll
// (which rebuilds the detail panel's innerHTML) can RE-EMIT the expanded markup
// instead of silently collapsing it. Reset to false whenever the selection
// changes (a freshly-opened signal always starts collapsed).
let chudSrcExpanded = false;
let chudAlerts: Alert[] = [];       // current (filtered+sorted) set, by render
let chudFilterGuardian: MutationObserver | null = null; // re-homes the shared filter bar on tab exit
let chudFilterBarEl: HTMLElement | null = null;          // direct ref so a DETACHED bar can still be re-homed

/** Strategic code → terminal token prefix (e.g. ENR-8D59). */
const CHUD_TOPIC_PREFIX: Record<string, string> = {
    ENERGY: 'ENR',
    MARKET: 'MKT',
    AI_TECH: 'SEM',
    CRYPTO: 'CRY',
    DEFENSE: 'DEF',
    SUPPLY_CHAIN: 'SHP',
};

/** Strict 3-letter category abbreviation for the compact mobile row tag.
 *  Crypto / Digital-Assets must read as CRY (never the legacy "DGA"). */
function chudTopicAbbr(canonicalTopic: string): string {
    const t = (canonicalTopic || '').toUpperCase();
    if (t.includes('CRYPTO') || t.includes('DIGITAL')) return 'CRY';
    return CHUD_TOPIC_PREFIX[canonicalTopic] || 'SIG';
}

/** Threat-ring SVG circumference = 2π·r with r=45 in the 100×100 viewBox. */
const THREAT_CIRCUMFERENCE = 2 * Math.PI * 45; // ≈ 282.74

function chudEscape(unsafe: string): string {
    if (!unsafe) return '';
    return unsafe
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

/** http/https only. chudEscape stops attribute breakout but not `javascript:` as a
 *  whole value, so a scheme allowlist is required in addition to escaping. Returns ''
 *  for anything else, which the caller renders as "Restricted Source". */
function chudSafeUrl(raw: unknown): string {
    const s = String(raw || '').trim();
    if (!s) return '';
    try {
        const proto = new URL(s, window.location.origin).protocol.toLowerCase();
        return proto === 'http:' || proto === 'https:' ? s : '';
    } catch {
        return '';
    }
}

/** Deterministic terminal token for an alert — stable across re-renders. */
function chudToken(alert: Alert): string {
    const prefix = CHUD_TOPIC_PREFIX[normalizeTopicCode(alert.topic)] || 'SIG';
    const hex = (alert.id || '')
        .replace(/[^a-z0-9]/gi, '')
        .slice(-4)
        .toUpperCase()
        .padStart(4, '0');
    return `${prefix}-${hex}`;
}

// ─── Stream rows (left pane) ─────────────────────────────────────────────

function chudRowHtml(alert: Alert): string {
    const canonicalTopic = normalizeTopicCode(alert.topic);
    const topicLabel = getTopicDisplayLabel(canonicalTopic);
    const topicColor = getTopicColor(canonicalTopic);
    const headline = resolveAlertHeadline(alert);
    const sev = alertThreatTier(alert);
    const time = alert.triggered_at ? formatIntelRelativeTimestamp(alert.triggered_at) : '—';
    const token = chudToken(alert);
    const locked = alert.is_locked && !DEV_MODE_AUDIT;
    const active = alert.id === chudSelectedId ? ' is-active' : '';

    const headlineHtml = headline.pending
        ? '<span class="alert-headline-skeleton alert-headline-skeleton--inline" aria-hidden="true"></span>'
        : chudEscape(headline.text);

    // Source density: EVERY row carries the SAME bright-cyan glassmorphism badge
    // (uniform high-tech layout). Floor at 1 (every signal has its trigger source).
    const sourceCount = Math.max(1, Array.isArray(alert.evidence_list) ? alert.evidence_list.length : 0);
    const sourceBadge =
        `<span class="chud-source-badge"`
        + ` title="${sourceCount} corroborating source${sourceCount > 1 ? 's clustered into this signal' : ''}">`
        + `${sourceCount} SRC</span>`;

    return `
        <button type="button" class="chud-row severity-${sev}${active}${locked ? ' chud-row--locked' : ''}"
            data-id="${chudEscape(alert.id)}" style="${getTopicCssVars(canonicalTopic)}"
            aria-label="${chudEscape(headline.text || alert.target_label || 'signal')}">
            <span class="chud-row-rail" aria-hidden="true"></span>
            <span class="chud-row-ts">${chudEscape(time)}</span>
            <span class="chud-row-token">${token}</span>
            <span class="chud-row-abbr" style="color:${topicColor}">${chudTopicAbbr(canonicalTopic)}</span>
            <span class="chud-row-sev chud-sev--${sev}">${TIER_LABEL[sev].slice(0, 4)}</span>
            <span class="chud-row-topic" style="color:${topicColor}">${topicLabel}</span>
            <span class="chud-row-headline">
                <span class="chud-row-headline-text">${locked ? '🔒 ' : ''}${headlineHtml}</span>
            </span>
            ${sourceBadge}
            <span class="chud-row-caret" aria-hidden="true">▸</span>
        </button>`;
}

function chudStreamRowsHtml(alerts: Alert[]): string {
    if (alerts.length === 0) {
        return `
            <div class="chud-stream-empty">
                <div class="chud-stream-empty-glyph" aria-hidden="true">⊘</div>
                <div class="chud-stream-empty-title">NO ACTIVE SIGNALS</div>
                <div class="chud-stream-empty-sub">Backbone scanning for strategic momentum…</div>
            </div>`;
    }
    return alerts.map(chudRowHtml).join('');
}

// ─── Detail panel (right pane) ───────────────────────────────────────────

// Plain-language explainer for the two orthogonal axes shown in the detail
// pane (anomaly ring + importance bar). Wired as a click ⓘ popover.
const AXES_GUIDE_HTML = `
    <strong>Two independent axes</strong><br>
    <b>ANOMALY</b> — how sharply this story's source-domain deviated from its own recent baseline (a self-normalizing "unusualness" ratio, not importance).<br>
    <b>IMPORTANCE</b> — how widely the event affects the world (energy, markets, shipping, defense, AI/semiconductors, crypto), scored 0–100 by an LLM from the headline.<br>
    They're independent: a globally important story can show low anomaly, and a high-anomaly blip can be globally trivial.`;

/** Comparison form for duplicate detection: trimmed, internal whitespace runs
 *  collapsed to one space, case-folded. Two strings that differ only in spacing
 *  or capitalisation are the same sentence to a reader. */
function chudNormaliseText(s: string): string {
    return s.trim().replace(/\s+/g, ' ').toLowerCase();
}

export function chudDetailHtml(alert: Alert | null): string {
    if (!alert) {
        return `
            <div class="chud-detail-idle">
                <div class="chud-detail-idle-ring" aria-hidden="true"></div>
                <div class="chud-detail-idle-text">SELECT A SIGNAL</div>
                <div class="chud-detail-idle-sub">Tactical breakdown will project here.</div>
            </div>`;
    }

    const canonicalTopic = normalizeTopicCode(alert.topic);
    const topicLabel = getTopicDisplayLabel(canonicalTopic);
    const topicColor = getTopicColor(canonicalTopic);
    const sev = alertThreatTier(alert);
    // The ring is driven STRICTLY by the backend's calibrated intensity_pct
    // (distributed ratio-%: 1.5x gate = 50%, >=3.0x = 100%). No client-side tanh
    // math — text and arc both read the same server-supplied value.
    //
    // An ABSENT intensity_pct is NOT a zero. It renders the same em dash the
    // IMPORTANCE readout below uses and draws no arc at all, while a measured
    // 0.0 still reads "0%" with a fully unwound arc — the two are different
    // claims and must stay distinguishable on screen.
    const pctRaw = typeof alert.intensity_pct === 'number' ? alert.intensity_pct : null;
    const pctVal = pctRaw === null ? null : Math.max(0, Math.min(100, pctRaw));
    const threatOffset = pctVal === null ? null : Math.round(THREAT_CIRCUMFERENCE * (1 - pctVal / 100));
    const displayPercentage = pctVal === null ? '—' : Math.round(pctVal) + '%';
    const headline = resolveAlertHeadline(alert);
    const token = chudToken(alert);
    const time = alert.triggered_at ? formatIntelFeedTimestamp(alert.triggered_at) : '—';
    const locked = alert.is_locked && !DEV_MODE_AUDIT;

    const status = alert.backbone_discovery_status || 'idle';
    // ANALYZING badge purged — the 'processing' state renders no status chip.
    const statusLabel =
        status === 'complete' ? 'VERIFIED'
        : status === 'failed' ? 'RAW SIGNAL'
        : status === 'processing' ? ''
        : 'PENDING';

    const sources = Array.isArray(alert.evidence_list) ? alert.evidence_list : [];
    const sourceCount = sources.length;
    const PRIMARY_SOURCE_N = 3;
    const renderSrcRow = (s: any, primary: boolean): string => {
        const title = chudEscape(String(s.title || s.source || 'Source signal'));
        const dom = chudEscape(String(s.domain || s.type || 'OSINT'));
        const url = s.url || s.link || '';
        const titleHtml = url
            ? `<a href="${chudEscape(String(url))}" target="_blank" rel="noopener noreferrer" class="chud-src-link">${title} ↗</a>`
            : title;
        return `
            <div class="chud-src-row${primary ? ' chud-src-row--primary' : ''}">
                <span class="chud-src-dom">${dom}</span>
                <span class="chud-src-title">${titleHtml}</span>
            </div>`;
    };
    // Strict cap: at most PRIMARY_SOURCE_N primaries; EVERYTHING else is secondary.
    const primarySources = sources.slice(0, PRIMARY_SOURCE_N);
    const secondarySources = sources.slice(PRIMARY_SOURCE_N);
    const primaryCount = primarySources.length;   // header badge (<=3) — NOT the total
    const primaryRows = primarySources.map((s: any) => renderSrcRow(s, true)).join('');

    // Media clustering: group secondary sources by their base publisher domain.
    // `domain` is urlparse(...).netloc from the backend (may carry www./sub-domain);
    // normalize (lowercase, strip leading www.) and fall back to the URL host.
    const baseDomain = (s: any): string => {
        let d = String(s.domain || s.type || '').trim().toLowerCase();
        if (!d || d === 'osint') {
            try { d = new URL(String(s.url || s.link || '')).hostname.toLowerCase(); }
            catch { /* keep d */ }
        }
        return d.replace(/^www\./, '') || 'other';
    };
    const secondaryGroups = new Map<string, any[]>();
    for (const s of secondarySources) {
        const key = baseDomain(s);
        const arr = secondaryGroups.get(key);
        if (arr) arr.push(s);
        else secondaryGroups.set(key, [s]);
    }
    const secondaryRows = [...secondaryGroups.entries()].map(([dom, items]) =>
        `<div class="chud-src-domain-header">${chudEscape(dom.toUpperCase())}`
        + ` <span class="chud-src-domain-count">(${items.length})</span></div>`
        + items.map((s: any) => renderSrcRow(s, false)).join('')
    ).join('');

    // The h2 below already shows the headline, so a description that only repeats
    // it renders the same sentence twice. Measured over alert_logs: of the 36
    // non-empty descriptions, 34 are byte-identical to the label. The other 2 are
    // the SOURCE's own headline sitting under a COMPOSED one (alert_manager's
    // _resolve_display_label rewrites a generic label via compose_headline) — a
    // second, different sentence, which still renders.
    //
    // Compared against the whole fallback chain, not headline.text alone: when
    // resolveAlertHeadline returns pending ('' text) the headline falls back to
    // target_label, and that is the case where the duplicate is most likely.
    // The h2 below renders this same variable, so there is one writer: whatever
    // the heading shows is exactly what the description is tested against.
    const renderedHeadline = headline.text || alert.target_label || 'Signal';
    const description = alert.description
        && chudNormaliseText(alert.description) !== chudNormaliseText(renderedHeadline)
        ? `<p class="chud-detail-desc">${chudEscape(alert.description)}</p>`
        : '';

    // IMPORTANCE (headline axis). Additive display only — server already
    // serializes importance_score/_rationale; the anomaly arc above is unchanged.
    const impRaw = typeof alert.importance_score === 'number' ? alert.importance_score : null;
    const impVal = impRaw === null ? null : Math.max(0, Math.min(100, Math.round(impRaw)));
    const impPct = impVal === null ? 0 : impVal;
    const impText = impVal === null ? '—' : String(impVal);
    const impRationale = typeof alert.importance_rationale === 'string' ? alert.importance_rationale : '';
    const importanceBlockHtml = `
        <div class="chud-imp chud-imp--${sev}" title="${chudEscape(impRationale)}">
            <div class="chud-imp-head">
                <span class="chud-imp-cap">IMPORTANCE</span>
                <span class="chud-imp-val">${impText}</span>
            </div>
            <div class="chud-imp-track">
                <div class="chud-imp-fill" style="width:${impPct}%"></div>
            </div>
        </div>`;

    return `
        <div class="chud-detail-inner${locked ? ' chud-detail-inner--locked' : ''}" style="${getTopicCssVars(canonicalTopic)}">
            <button type="button" class="chud-detail-back" data-chud-back aria-label="Close detail">✕ Close</button>
            <header class="chud-detail-head">
                <div class="chud-detail-head-row">
                    <span class="chud-detail-token">${token}</span>
                    <span class="chud-detail-topic" style="color:${topicColor}">${topicLabel}</span>
                </div>
                <div class="chud-detail-time">${chudEscape(time)}</div>
            </header>

            <div class="chud-threat">
                <div class="chud-threat-ring chud-threat-ring--${sev}">
                    <svg class="chud-threat-svg" viewBox="0 0 100 100" aria-hidden="true">
                        <circle class="chud-threat-track" cx="50" cy="50" r="45"></circle>
                        ${threatOffset === null ? '' : `<circle class="chud-threat-meter" cx="50" cy="50" r="45"
                            style="stroke-dasharray:${THREAT_CIRCUMFERENCE.toFixed(2)};stroke-dashoffset:${threatOffset}"></circle>`}
                    </svg>
                    <div class="chud-threat-core">
                        <span class="chud-threat-val">${displayPercentage}</span>
                        <span class="chud-threat-cap">ANOMALY</span>
                    </div>
                </div>
                <div class="chud-threat-meta">
                    <div class="chud-threat-axes-guide">${renderPanelGuide('Anomaly and Importance', AXES_GUIDE_HTML)}</div>
                    <div class="chud-threat-sev chud-sev--${sev}">${TIER_LABEL[sev]}</div>
                    ${statusLabel ? `<div class="chud-threat-status chud-status--${status}">${statusLabel}</div>` : ''}
                    ${importanceBlockHtml}
                </div>
            </div>

            <h2 class="chud-detail-headline">${locked ? '🔒 ' : ''}${chudEscape(renderedHeadline)}</h2>
            ${description}

            <section class="chud-block">
                <div class="chud-block-label">PRIMARY SOURCES <span class="chud-block-count">${primaryCount}</span></div>
                ${sourceCount
                    ? `<div class="chud-src-list">${primaryRows}</div>
                       ${secondarySources.length
                          ? `<div class="chud-src-secondary${chudSrcExpanded ? ' expanded' : ''}">
                                 <div class="chud-src-list chud-src-list--secondary">${secondaryRows}</div>
                             </div>
                             <button type="button" class="chud-src-more" data-chud-src-toggle="1" aria-expanded="${chudSrcExpanded}">
                                 ${chudSrcExpanded ? 'Hide' : `View all ${secondarySources.length}`} secondary sources <span class="chud-src-more-caret">${chudSrcExpanded ? '▴' : '▾'}</span>
                             </button>`
                          : ''}`
                    : '<div class="chud-muted">No supporting sources resolved.</div>'}
            </section>
        </div>`;
}

/** Project an alert into the sticky detail panel + sync row highlight. */
function chudSelect(container: HTMLElement, id: string | null): void {
    // A genuine selection change starts collapsed; a poll re-selecting the SAME
    // signal preserves whatever the user expanded.
    if (id !== chudSelectedId) chudSrcExpanded = false;
    chudSelectedId = id;
    const detail = container.querySelector<HTMLElement>('.chud-detail');
    const alert = id ? chudAlerts.find(a => a.id === id) ?? null : null;
    if (detail) { detail.innerHTML = chudDetailHtml(alert); wirePanelGuideTooltips(detail); }

    container.querySelectorAll<HTMLElement>('.chud-row').forEach(row => {
        row.classList.toggle('is-active', !!id && row.dataset.id === id);
    });
}

function chudCurrentAlert(): Alert | null {
    return chudSelectedId ? chudAlerts.find(a => a.id === chudSelectedId) ?? null : null;
}

// ─── Mobile Alert Detail modal — body-level portal (mirrors openSystemLogic) ──
// On phones the in-place .chud-detail is trapped by an ancestor containing block
// (`#alerts-container.main-feed { contain: layout }`), so a position:fixed panel
// anchors to the feed box, not the viewport. We sidestep that exactly like the
// System Logic overlay: build a fresh overlay and append it to <body>.
let chudDetailModalEl: HTMLElement | null = null;
let chudDetailModalKeyHandler: ((e: KeyboardEvent) => void) | null = null;

function closeChudDetailModal(): void {
    if (chudDetailModalKeyHandler) {
        document.removeEventListener('keydown', chudDetailModalKeyHandler);
        chudDetailModalKeyHandler = null;
    }
    document.body.classList.remove('chud-detail-modal-open');
    if (chudDetailModalEl) {
        chudDetailModalEl.classList.remove('chud-detail-modal--in');
        const el = chudDetailModalEl;
        chudDetailModalEl = null;
        // Brief exit transition, then detach.
        window.setTimeout(() => { try { el.remove(); } catch { /* already gone */ } }, 240);
    }
}

function openChudDetailModal(alert: Alert | null): void {
    // Idempotent: if already open, just swap content for the freshly-tapped signal.
    if (chudDetailModalEl) {
        const room = chudDetailModalEl.querySelector<HTMLElement>('.chud-detail-modal-room');
        if (room) { room.innerHTML = chudDetailHtml(alert); wirePanelGuideTooltips(room); }
        return;
    }

    const overlay = document.createElement('div');
    overlay.className = 'chud-detail-modal';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Signal detail');
    // The room carries the `chud-root` context class so the portaled detail
    // inherits the same parent scope as the desktop feed: the --chud-* CSS
    // variables (cyan, edges) and the ::before grid wash all live on .chud-root,
    // so without it the modal renders devoid of its theme. Identical to desktop.
    overlay.innerHTML = `
        <div class="chud-detail-modal-backdrop"></div>
        <div class="chud-detail-modal-room chud-root" role="document">${chudDetailHtml(alert)}</div>`;

    document.body.appendChild(overlay);
    document.body.classList.add('chud-detail-modal-open');
    chudDetailModalEl = overlay;
    const _modalRoom = overlay.querySelector<HTMLElement>('.chud-detail-modal-room');
    if (_modalRoom) wirePanelGuideTooltips(_modalRoom);

    // Delegated interactions inside the portaled detail — mirrors the in-place
    // .chud-detail handler: ✕ Close / backdrop, evidence-sources modal, and the
    // secondary-sources accordion toggle.
    overlay.addEventListener('click', (e) => {
        const t = e.target as HTMLElement;
        if (t.closest('.chud-detail-modal-backdrop') || t.closest('[data-chud-back]')) {
            closeChudDetailModal();
            return;
        }
        if (t.closest('[data-chud-sources]')) {
            const a = chudCurrentAlert();
            if (a) showEvidenceModal(resolveAlertHeadline(a).text || a.target_label, a.evidence_list || []);
            return;
        }
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
            return;
        }
    });

    // Escape closes (matches System Logic).
    chudDetailModalKeyHandler = (e: KeyboardEvent) => {
        if (e.key === 'Escape') { e.preventDefault(); closeChudDetailModal(); }
    };
    document.addEventListener('keydown', chudDetailModalKeyHandler);

    // Entrance transition.
    requestAnimationFrame(() => overlay.classList.add('chud-detail-modal--in'));
}

/**
 * Phase 8.26 — the System Logic action is a page-level control, so it lives in
 * the primary page-title row (`.header-row`), far-right, balanced against the
 * title. Mounted on feed render, removed when the feed is torn down so it never
 * lingers on other tabs.
 */
function chudMountSystemLogicButton(): void {
    const headerRow = document.querySelector<HTMLElement>('.header-row');
    if (!headerRow || headerRow.querySelector('#chud-syslogic-header')) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'chud-syslogic-header';
    btn.className = 'syslogic-toggle syslogic-toggle--header';
    btn.title = 'Inspect the live computational pipeline';
    btn.innerHTML = '<span class="syslogic-toggle-gear" aria-hidden="true">⚙</span> System Logic';
    btn.addEventListener('click', () => openSystemLogic());
    headerRow.appendChild(btn);
}

function chudUnmountSystemLogicButton(): void {
    document.getElementById('chud-syslogic-header')?.remove();
}

/** Default category labels — last-resort fallback so the pad is NEVER blank. */
/** Kept in sync by hand with STRATEGIC_TOPIC_LABELS (topics.ts) — change both. */
const CHUD_FALLBACK_FILTERS = [
    'All', 'Energy', 'Markets', 'AI / Semi',
    'Crypto', 'Defense', 'Supply Chain',
];

/**
 * Phase 8.38 — if a DOM/async race ever leaves the filter bar with no pills,
 * inject a static fallback set so the control pad is never blank. Under normal
 * flow main.ts's renderTopicFilterBar keeps the live (interactive) pills in
 * place and this no-ops.
 */
function chudEnsureFilterPills(bar: HTMLElement): void {
    if (bar.querySelector('.topic-btn')) return; // already populated — leave the live pills alone
    bar.innerHTML = CHUD_FALLBACK_FILTERS
        .map((label, i) =>
            `<button type="button" class="topic-btn${i === 0 ? ' topic-btn--active' : ''}" disabled>${label}</button>`)
        .join('');
}

/**
 * Phase 8.25/8.38 — relocate the shared `#topic-filter-bar` into the header's
 * left "control pad" column, and keep it robust against the per-tab innerHTML
 * wipes of #alerts-list.
 *
 * The bar physically lives inside #alerts-list (the control pad), so any
 * innerHTML replacement of #alerts-list (offline banner, Briefs loading, tab
 * swap) DETACHES it. We therefore hold a DIRECT element reference
 * (`chudFilterBarEl`) — `getElementById` returns null for detached nodes, which
 * is exactly what previously orphaned the bar until a hard reload. With the
 * direct ref the guardian can always re-attach it (children/pills survive the
 * detach intact), so the filter row is guaranteed present under every state.
 */
function chudRelocateFilterBar(root: HTMLElement): void {
    // Prefer a live attached element (guards against a stale ref after a base-UI
    // rebuild); fall back to the stored ref when the bar is currently detached.
    const fresh = document.getElementById('topic-filter-bar');
    if (fresh) chudFilterBarEl = fresh;
    const bar = chudFilterBarEl;
    const list = document.getElementById('alerts-list');
    const pad = root.querySelector<HTMLElement>('.chud-control-pad');
    if (!bar || !list || !pad) return;

    if (bar.parentElement !== pad) {
        bar.classList.add('chud-filter-inline');
        pad.appendChild(bar);   // re-attaches even a detached bar; preserves its pills
    }
    chudEnsureFilterPills(bar); // never leave the pad blank

    if (!chudFilterGuardian) {
        chudFilterGuardian = new MutationObserver(() => {
            const container = document.getElementById('alerts-container');
            const liveList = document.getElementById('alerts-list');
            const liveBar = chudFilterBarEl; // direct ref — works even when detached
            if (!container || !liveList || !liveBar) return;
            // Feed torn down (its .chud-root is gone) → re-home the filter bar to
            // its original slot (for the Briefs tab) and drop the page-level button.
            if (!liveList.querySelector('.chud-root')) {
                if (liveBar.parentElement !== container) {
                    liveBar.classList.remove('chud-filter-inline');
                    container.insertBefore(liveBar, liveList);
                }
                chudUnmountSystemLogicButton();
            }
        });
        // Observe direct children only — fires on tab-render swaps, not on the
        // deep mutations of an ordinary in-place re-render.
        chudFilterGuardian.observe(list, { childList: true });
    }
}

// ─── Entry point ─────────────────────────────────────────────────────────

export function renderAlerts(
    alerts: Alert[],
    container: HTMLElement,
    userTier: string = 'free',
    topicFilter: StrategicTopicCode | null = null,
) {
    if (!Array.isArray(alerts)) {
        console.error('renderAlerts expected an array, got:', alerts);
        container.innerHTML = '<div class="u-p-2 u-text-center" style="color:#f85149;">Technical error: invalid alerts data.</div>';
        return;
    }

    const sortedAlerts = [...alerts]
        .filter(a => !topicFilter || normalizeTopicCode(a.topic) === topicFilter)
        .sort((a, b) => {
            // Headline axis = importance, fine-grained (mirrors the server order_by:
            // importance DESC NULLS LAST → triggered_at DESC). A higher importance is
            // always above a lower one; triggered_at only breaks ties within equal
            // scores. Unscored rows (null) sort last.
            const impA = typeof a.importance_score === 'number' ? a.importance_score : -1;
            const impB = typeof b.importance_score === 'number' ? b.importance_score : -1;
            if (impA !== impB) return impB - impA;
            return new Date(b.triggered_at).getTime() - new Date(a.triggered_at).getTime();
        });

    // Refresh module state consumed by the row/detail helpers.
    chudAlerts = sortedAlerts;

    const SPARSE_MAX = 2;  // 0–2 alerts = sparse → shrink panel so the
                           // off-screen domain-items hint chip is reachable
    const isAllTab = topicFilter === null;  // "All" tab keeps the old fixed-height filled panel

    // CRIT counter mirrors the displayed CRITICAL tier (importance_score >= 80),
    // so the header matches the row badges produced by alertThreatTier.
    const critical = sortedAlerts.filter(a => typeof a.importance_score === 'number' && a.importance_score >= IMPORTANCE_CRITICAL).length;
    const existing = container.querySelector<HTMLElement>('.chud-root');

    // ── Incremental path (≈ every 10s poll) — swap rows only, keep log + detail.
    if (existing) {
        existing.classList.toggle('chud-root--sparse', sortedAlerts.length <= SPARSE_MAX);
        existing.classList.toggle('chud-root--filled', isAllTab);
        const list = existing.querySelector<HTMLElement>('.chud-stream-list');
        if (list) list.innerHTML = chudStreamRowsHtml(sortedAlerts);
        const countEl = existing.querySelector<HTMLElement>('[data-chud-count]');
        if (countEl) countEl.textContent = String(sortedAlerts.length);
        const critEl = existing.querySelector<HTMLElement>('[data-chud-crit]');
        if (critEl) critEl.textContent = String(critical);

        // Keep selection if it survived; otherwise fall back to the top signal.
        const stillThere = chudSelectedId && sortedAlerts.some(a => a.id === chudSelectedId);
        chudSelect(existing, stillThere ? chudSelectedId : (sortedAlerts[0]?.id ?? null));
        return;
    }

    // ── Full build (first paint / after a tab switch wiped the container).
    const tierTag = (userTier === 'experts' || userTier === 'enterprise')
        ? 'EXPERT' : userTier === 'pro' ? 'PRO' : 'STANDARD';

    container.innerHTML = `
        <div class="chud-root">
            <div class="chud-console" aria-label="Filters">
                <div class="chud-console-grid">
                    <div class="chud-control-pad" data-role="control-pad"></div>
                </div>
            </div>

            <div class="chud-split">
                <section class="chud-stream" aria-label="Signal stream">
                    <div class="chud-stream-head">
                        <span class="chud-stream-title">SIGNAL STREAM</span>
                        <span class="chud-stream-stats">
                            <span class="chud-stat"><b data-chud-count>${sortedAlerts.length}</b> TRACKED</span>
                            <span class="chud-stat chud-stat--crit"><b data-chud-crit>${critical}</b> CRIT</span>
                            <span class="chud-stat chud-stat--tier">${tierTag}</span>
                        </span>
                    </div>
                    <div class="chud-stream-list">${chudStreamRowsHtml(sortedAlerts)}</div>
                </section>

                <aside class="chud-detail" aria-label="Tactical detail"></aside>
            </div>
        </div>`;

    const root = container.querySelector<HTMLElement>('.chud-root')!;
    root.classList.toggle('chud-root--sparse', sortedAlerts.length <= SPARSE_MAX);
    root.classList.toggle('chud-root--filled', isAllTab);

    // Phase 8.25 — dock the Domain Filter Bar into the header's control pad.
    chudRelocateFilterBar(root);
    // Phase 8.26 — lock the System Logic action to the page-title row.
    chudMountSystemLogicButton();

    // Event delegation (attached once to stable parents; survives row swaps).
    const list = root.querySelector<HTMLElement>('.chud-stream-list');
    list?.addEventListener('click', (e) => {
        const row = (e.target as HTMLElement).closest<HTMLElement>('.chud-row');
        if (!row || !list.contains(row)) return;
        const id = row.dataset.id;
        if (!id) return;
        chudSelect(root, id);
        // Mobile: open the detail as a body-level PORTAL modal (mirrors System
        // Logic) so it fills the viewport instead of being trapped by the feed's
        // `contain: layout` ancestor. Desktop keeps the side-by-side split pane.
        if (window.matchMedia('(max-width: 768px)').matches) {
            openChudDetailModal(chudAlerts.find(a => a.id === id) ?? null);
        }
    });

    const detail = root.querySelector<HTMLElement>('.chud-detail');
    detail?.addEventListener('click', (e) => {
        const t = e.target as HTMLElement;
        // Mobile "← Back to Stream": return to the master list view.
        if (t.closest('[data-chud-back]')) {
            root.querySelector<HTMLElement>('.chud-split')?.classList.remove('chud-split--detail-open');
            return;
        }
        if (t.closest('[data-chud-sources]')) {
            const a = chudCurrentAlert();
            if (a) showEvidenceModal(resolveAlertHeadline(a).text || a.target_label, a.evidence_list || []);
            return;
        }
        // Secondary-sources accordion toggle (inline, no modal).
        const srcToggle = t.closest<HTMLElement>('[data-chud-src-toggle]');
        if (srcToggle) {
            const sec = srcToggle.previousElementSibling as HTMLElement | null;
            if (sec && sec.classList.contains('chud-src-secondary')) {
                // Toggle the .expanded class (CSS hides the container by default).
                // Persist to module state so the next poll's re-render re-emits it.
                chudSrcExpanded = !sec.classList.contains('expanded');
                sec.classList.toggle('expanded', chudSrcExpanded);
                srcToggle.setAttribute('aria-expanded', String(chudSrcExpanded));
                const secCount = sec.querySelectorAll('.chud-src-row').length;
                const caret = chudSrcExpanded ? '▴' : '▾';
                srcToggle.innerHTML =
                    `${chudSrcExpanded ? 'Hide' : `View all ${secCount}`} secondary sources `
                    + `<span class="chud-src-more-caret">${caret}</span>`;
            }
            return;
        }
    });

    // Project an initial selection.
    const initial = (chudSelectedId && sortedAlerts.some(a => a.id === chudSelectedId))
        ? chudSelectedId
        : (sortedAlerts[0]?.id ?? null);
    chudSelect(root, initial);
}

// ════════════════════════════════════════════════════════════════════════
// Phase 8.5 — "System Logic" Mathematical Blueprint simulation overlay.
//
// A body-level fullscreen overlay (independent of the alerts container, so the
// underlying Cyber-HUD is never disturbed). It animates the 4-stage backend
// pipeline with a glowing SVG flow + live LaTeX-style math + cascading number
// tickers. Toggling out simply removes the overlay → the stream is intact.
// ════════════════════════════════════════════════════════════════════════

let sysLogicEl: HTMLElement | null = null;
let sysLogicTimer: number | null = null;
let sysLogicKeyHandler: ((e: KeyboardEvent) => void) | null = null;
let sysLogicIter = 0;

const SYS_LOGIC_STAGES: ReadonlyArray<{
    idx: string; glyph: string; title: string; tag: string; desc: string; tick: string;
}> = [
    {
        idx: '01', glyph: '📡', title: 'Ingestion & Normalization', tag: '[Alert Window]',
        desc: 'Fetches the most recent alerts from the API on each poll and replaces the working set.',
        tick: 'window <b data-sl="win">—</b>h · <b data-sl="nalerts">—</b> alerts in window',
    },
    {
        idx: '02', glyph: '🛰', title: 'Map Placement', tag: '[Row Coordinates]',
        desc: 'Places signals on the map when the alert row already carries coordinates.',
        tick: 'coordinates when present on the row',
    },
    {
        idx: '03', glyph: '🧮', title: 'Multi-Domain Classification', tag: '[Domain Matrix]',
        desc: 'Sorts filtered signals into AI-Semi, Energy, Shipping, Defense & Crypto lattices without human bias.',
        tick: '6 strategic domains · keyword + LLM fallback',
    },
    {
        idx: '04', glyph: '🖥', title: 'UI State Engine & Repaint', tag: '[UI Repaint]',
        desc: 'Rewrites the stream rows from the new set, keeping the selected signal open if it is still present.',
        tick: 'rows rewritten · selection preserved',
    },
];

function sysLogicStageHtml(): string {
    return SYS_LOGIC_STAGES.map((s, i) => `
        <article class="sl-card" style="--sl-i:${i}">
            <div class="sl-card-rail" aria-hidden="true"></div>
            <header class="sl-card-head">
                <span class="sl-card-idx">${s.idx}</span>
                <span class="sl-card-glyph" aria-hidden="true">${s.glyph}</span>
            </header>
            <div class="sl-card-tag">${chudEscape(s.tag)}</div>
            <h3 class="sl-card-title">${chudEscape(s.title)}</h3>
            <p class="sl-card-desc">${chudEscape(s.desc)}</p>
            <div class="sl-card-tick">${s.tick}</div>
        </article>`).join('<div class="sl-arrow" aria-hidden="true">▶</div>');
}

/** Glowing SVG spine with declarative (SMIL) particle flow across all stages.
 *  Exported: the MTF System Logic overlay reuses the same 4-node spine. */
export function sysLogicFlowSvg(): string {
    const nodes = [125, 375, 625, 875];
    const nodeCircles = nodes.map((x, i) => `
        <circle class="sl-node" cx="${x}" cy="60" r="11" style="--sl-n:${i}"/>
        <circle class="sl-node-core" cx="${x}" cy="60" r="4.5"/>`).join('');
    const particles = [0, 0.55, 1.1, 1.65, 2.2, 2.75].map((begin, i) => `
        <circle r="3.4" class="sl-particle" style="--sl-p:${i}">
            <animateMotion dur="3.3s" begin="-${begin}s" repeatCount="indefinite" rotate="auto">
                <mpath href="#sl-spine"/>
            </animateMotion>
        </circle>`).join('');
    return `
        <svg class="sl-flow" viewBox="0 0 1000 120" preserveAspectRatio="xMidYMid meet" role="img"
            aria-label="Animated data pipeline flow">
            <defs>
                <linearGradient id="sl-spine-grad" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stop-color="#2b6cff"/>
                    <stop offset="55%" stop-color="#00f0ff"/>
                    <stop offset="100%" stop-color="#57f5a3"/>
                </linearGradient>
            </defs>
            <path id="sl-spine" d="M125 60 H875" fill="none" stroke="url(#sl-spine-grad)"
                stroke-width="2.5" class="sl-spine-glow"/>
            <path d="M125 60 H875" fill="none" stroke="#00f0ff" stroke-width="1"
                stroke-dasharray="6 10" class="sl-spine-dash"/>
            ${nodeCircles}
            ${particles}
        </svg>`;
}

/**
 * Phase 8.9 — two honest panels for the Alert Stream's real client pipeline:
 *   • Left  — authentic Shannon entropy (a genuine backbone calculation run on
 *             alert payloads to score cross-domain volatility), with the same
 *             sharp cyan-railed typography as the rest of the blueprint.
 *   • Right — the incremental delta-state hydration loop that powers the
 *             Cyber-HUD. (Markov / fluid-dynamics graph math stays exclusive
 *             to the Pro Interactive Map.)
 */
function sysLogicStatePanelsHtml(): string {
    // Left (top) — Shannon entropy: H = −∑ᵢ P(xᵢ) log P(xᵢ)
    const entropy = `
        <div class="sl-eq">
            <span class="sl-var">H</span>
            <span class="sl-op">=</span>
            <span class="sl-neg">−</span>
            <span class="sl-sum">∑<span class="sl-sub">i</span></span>
            <span class="sl-term">P(x<span class="sl-sub">i</span>)</span>
            <span class="sl-op">log</span>
            <span class="sl-term">P(x<span class="sl-sub">i</span>)</span>
        </div>`;

    // Left (bottom) — the ordering step, paired with the entropy math above.
    // No dedupe stage is shown because none exists: renderAlerts filters and
    // sorts, and the poll replaces the array wholesale rather than merging.
    const interceptor = `
        <pre class="sl-code"><span class="sl-code-head">[Fact Interception]</span>
<span class="sl-kw">for</span> (sig <span class="sl-kw">of</span> payload) {
  key = sig.importance_score ?? -1 <span class="sl-cmt">// unscored last</span>
}
sorted = <span class="sl-fn">stableSort</span>(key ↓, recency ↓)</pre>`;

    // Right — the actual incremental UI rendering / state-hydration loop.
    const hydration = `
        <pre class="sl-code"><span class="sl-code-head">[State Validation Loop]</span>
params = { limit }; <span class="sl-kw">if</span> (topic) params.topic = topic
payload = <span class="sl-fn">fetch</span>(<span class="sl-str">'/api/alerts?'</span> + <span class="sl-fn">qs</span>(params))
stream_container.innerHTML = <span class="sl-fn">rows</span>(payload)   <span class="sl-cmt">// empty &rArr; "no active signals"</span>
<span class="sl-fn">Maintain_Active_Selection</span>(module_state.selected_id)</pre>`;

    const telemetry = `
        <div class="sl-telemetry">
            <div class="sl-telem-row"><span class="sl-telem-k">Polling Interval</span><span class="sl-telem-v">10,000 ms</span></div>
        </div>`;

    return `
        <div class="sl-math">
            <section class="sl-math-block">
                <div class="sl-math-label">NETWORK ENTROPY · information-theoretic volatility</div>
                ${entropy}
                <div class="sl-math-live">Normalised entropy <b data-sl="entropy">—</b> · regime <b data-sl="regime">—</b> · <b data-sl="nalerts2">—</b> alerts (<b data-sl="win2">—</b>h)</div>
                <div class="sl-divider" aria-hidden="true"></div>
                ${interceptor}
                <div class="sl-math-live">stable sort by importance, then recency</div>
            </section>
            <section class="sl-math-block">
                <div class="sl-math-label">POLL LOOP · state refresh</div>
                ${hydration}
                ${telemetry}
                <div class="sl-math-live">downstream: monthly trend flow · cyc <b data-sl="iter">0</b></div>
            </section>
        </div>`;
}

/** Advances the System Logic modal's cycle counter (the only live readout). */
function sysLogicTick(root: HTMLElement): void {
    // Only the cycle counter ticks — everything else is real, fetched once on open.
    sysLogicIter += 1;
    const el = root.querySelector<HTMLElement>('[data-sl="iter"]');
    if (el) el.textContent = String(sysLogicIter);
}

// One-shot: fetch the REAL market entropy and fill the honest readouts. No randomness.
async function sysLogicLoadReal(root: HTMLElement): Promise<void> {
    const set = (key: string, val: string) => {
        const el = root.querySelector<HTMLElement>(`[data-sl="${key}"]`);
        if (el) el.textContent = val;
    };
    try {
        const e = await fetchMarketEntropy();
        if (!e) {
            ['entropy', 'regime', 'nalerts', 'nalerts2', 'win', 'win2'].forEach(k => set(k, 'n/a'));
            return;
        }
        set('entropy', e.entropy_normalised.toFixed(3));
        set('regime', e.regime_label || '—');
        set('nalerts', String(e.n_alerts));
        set('nalerts2', String(e.n_alerts));
        set('win', String(e.window_hours));
        set('win2', String(e.window_hours));
    } catch {
        ['entropy', 'regime', 'nalerts', 'nalerts2', 'win', 'win2'].forEach(k => set(k, 'n/a'));
    }
}

function closeSystemLogic(): void {
    if (sysLogicTimer !== null) { clearInterval(sysLogicTimer); sysLogicTimer = null; }
    if (sysLogicKeyHandler) { document.removeEventListener('keydown', sysLogicKeyHandler); sysLogicKeyHandler = null; }
    document.body.classList.remove('syslogic-open');
    if (sysLogicEl) {
        sysLogicEl.classList.remove('syslogic-overlay--in');
        const el = sysLogicEl;
        sysLogicEl = null;
        // Brief exit transition, then detach.
        window.setTimeout(() => { try { el.remove(); } catch { /* already gone */ } }, 220);
    }
}

/**
 * Generic System Logic overlay opener — shared chrome (backdrop, head, close
 * wiring, Escape, entrance, 720ms cycle ticker). The subtitle, body, footer, and
 * an optional one-shot live loader (onOpen) are injected by the caller. The Alert
 * Stream wrapper below (openSystemLogic) emits byte-identical DOM. Singleton state
 * (sysLogicEl / sysLogicTimer / sysLogicKeyHandler) is shared on purpose — the
 * Alert Stream and MTF System Logic tabs are mutually exclusive, never open together.
 */
export function openSysLogicOverlay(opts: { subtitle: string; bodyHtml: string; footNote: string; onOpen?: (root: HTMLElement) => void; }): void {
    if (sysLogicEl) return; // already open — idempotent

    const overlay = document.createElement('div');
    overlay.className = 'syslogic-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'System Logic — pipeline blueprint');
    overlay.innerHTML = `
        <div class="syslogic-backdrop"></div>
        <div class="syslogic-room" role="document">
            <div class="syslogic-grid" aria-hidden="true"></div>
            <header class="syslogic-head">
                <div class="syslogic-head-titles">
                    <div class="syslogic-title"><span class="syslogic-gear" aria-hidden="true">⚙</span> SYSTEM LOGIC // PIPELINE BLUEPRINT</div>
                    <div class="syslogic-sub">${opts.subtitle}</div>
                </div>
                <button type="button" class="syslogic-close" aria-label="Close System Logic">×</button>
            </header>

            <div class="syslogic-body">
                ${opts.bodyHtml}
            </div>

            <footer class="syslogic-foot">
                <span class="syslogic-foot-dot" aria-hidden="true"></span>
                ${opts.footNote}
            </footer>
        </div>`;

    document.body.appendChild(overlay);
    document.body.classList.add('syslogic-open');
    sysLogicEl = overlay;
    sysLogicIter = 0;

    // Wire dismissal — close button, backdrop, Escape.
    overlay.querySelector('.syslogic-close')?.addEventListener('click', closeSystemLogic);
    overlay.querySelector('.syslogic-backdrop')?.addEventListener('click', closeSystemLogic);
    sysLogicKeyHandler = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); closeSystemLogic(); } };
    document.addEventListener('keydown', sysLogicKeyHandler);

    // Entrance + live computation cascade.
    requestAnimationFrame(() => overlay.classList.add('syslogic-overlay--in'));
    sysLogicTick(overlay);
    opts.onOpen?.(overlay);
    sysLogicTimer = window.setInterval(() => {
        if (!sysLogicEl || !document.body.contains(overlay)) {
            if (sysLogicTimer !== null) clearInterval(sysLogicTimer);
            sysLogicTimer = null;
            return;
        }
        sysLogicTick(overlay);
    }, 720);
}

function openSystemLogic(): void {
    openSysLogicOverlay({
        subtitle: 'COMPUTATIONAL SCHEMATIC · OSINT-CORE',
        bodyHtml:
            sysLogicFlowSvg() +
            `<div class="sl-stages">${sysLogicStageHtml()}</div>` +
            sysLogicStatePanelsHtml(),
        footNote: 'Press <kbd>ESC</kbd> to return to stream',
        onOpen: (root) => { void sysLogicLoadReal(root); },
    });
}

// -- Per-domain comprehensive list ("full sector feed") ----------------------
// Second section under a domain tab: the raw, time-ordered, LLM-free item feed
// for that category. NOT a selection - no importance/anomaly badges (handover
// 15.5). The Alert Stream above stays the curated importance view; this is the
// full net. Local esc helpers (alerts.ts has none of its own).
function diEscHtml(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function diEscAttr(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const DOMAIN_LIST_GUIDE_HTML = `
    <strong>Two views, one domain.</strong>
    <span class="intel-guide-p"><b>Alert Stream</b> (above) is the <em>curated</em> view -
    world events ranked by importance, the same global lens as "All".</span>
    <span class="intel-guide-p"><b>Full sector feed</b> (below) is the <em>comprehensive</em>
    view - up to the 100 most recently collected items for this sector, in the order they
    were collected. No ranking and no impact filter, but it is capped: on a busy sector
    older items fall outside it.</span>
    <span class="intel-guide-p">A story can be important yet appear only in the list, or be
    routine yet still listed. That is expected - the list is breadth, the stream is selection.</span>`;

/** Publisher hostname from the item's own URL: lowercased, "www." stripped.
 *  Falls back to the raw source_name on ANY failure (absent or unparseable
 *  URL) — never an empty string, never a guess. source_name is the internal
 *  feed key (Item.source_system, processor/normalize.py:255), so it reads as a
 *  slug; the hostname is what the detail panel already shows for the same
 *  story, and deriving it here makes the two panes agree. */
function domainItemHost(url: string, sourceName: string): string {
    if (!url) return sourceName;
    try {
        return new URL(url).hostname.toLowerCase().replace(/^www\./, '') || sourceName;
    } catch {
        return sourceName;
    }
}

function domainItemRowHtml(it: DomainItem): string {
    // Display the field the list is ORDERED by. api/routes/items.py:83 sorts on
    // Item.created_at.desc().nullslast(), so showing published_at made the
    // rendered clock non-monotonic (02:57 AM above 03:00 AM, measured).
    const when = it.created_at ?? it.published_at ?? '';
    const ts = when ? formatIntelTime(when) : '';
    const src = domainItemHost(it.source_url ?? '', it.source_name ?? '');
    const title = it.title ?? '(untitled)';
    const href = it.source_url ?? '';
    const titleHtml = href
        ? `<a class="domain-item-title" href="${diEscAttr(href)}" target="_blank" rel="noopener noreferrer">${diEscHtml(title)}</a>`
        : `<span class="domain-item-title">${diEscHtml(title)}</span>`;
    return `<li class="domain-item">
        ${titleHtml}
        <span class="domain-item-meta">${diEscHtml(src)}${src && ts ? ' \u00b7 ' : ''}${diEscHtml(ts)}</span>
    </li>`;
}

/** Render the comprehensive item list into its own host (sibling of #alerts-list).
 *  Owned entirely by this fn - the 10s Alert Stream poll never touches it. */
/** Local calendar-day key for an item, or null when it has no usable date.
 *  Keyed on LOCAL year/month/date, never the raw ISO string: created_at is UTC
 *  and a string comparison would put the day boundary 9 hours off (handover
 *  8-4). The year is in the KEY so two Septembers can never collide, even
 *  though the visible label omits it. */
function domainItemDayKey(it: DomainItem): string | null {
    const raw = it.created_at ?? it.published_at ?? '';
    if (!raw) return null;
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return null;
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

/** Rows with a date separator emitted whenever the local calendar day changes,
 *  including before the first row. Unlike the curated stream — sorted by
 *  importance, where a separator would assert an order that does not exist —
 *  this list IS ordered by time (api/routes/items.py:83, created_at DESC), so
 *  the grouping states something true. An item with no usable date emits NO
 *  separator and stays in whatever group is current; it never opens one. */
function domainItemsWithDayBreaks(items: DomainItem[]): string {
    let currentKey: string | null = null;
    const out: string[] = [];
    for (const it of items) {
        const key = domainItemDayKey(it);
        if (key !== null && key !== currentKey) {
            currentKey = key;
            const label = formatIntelDate(it.created_at ?? it.published_at, {
                month: 'short',
                day: 'numeric',
            });
            // aria-hidden: a visual grouping cue only. Each row already carries
            // its own time in .domain-item-meta, so nothing is lost to a reader.
            out.push(`<li class="domain-day" aria-hidden="true">${diEscHtml(label)}</li>`);
        }
        out.push(domainItemRowHtml(it));
    }
    return out.join('');
}

export function renderDomainItems(
    host: HTMLElement,
    items: DomainItem[],
    label: string,
    color: string,
): void {
    const guide = renderPanelGuide('Curated stream vs comprehensive list', DOMAIN_LIST_GUIDE_HTML);
    const body = items.length
        ? `<ul class="domain-item-list">${domainItemsWithDayBreaks(items)}</ul>`
        : `<div class="domain-empty">No items collected for this sector yet.</div>`;
    host.innerHTML = `
        <section class="domain-items" style="--domain-color:${diEscAttr(color)};" aria-label="${diEscAttr(label)} comprehensive news list">
            <div class="domain-items-head">
                <span class="domain-items-icon" aria-hidden="true">\u{1F4CB}</span>
                <span class="domain-items-title">${diEscHtml(label)} - full sector feed</span>
                <span class="domain-items-count">${items.length}</span>
                ${guide}
            </div>
            ${body}
        </section>`;
    wirePanelGuideTooltips(host);
}

/** Visible, poll-safe discoverability chip mounted above the fold (outside
 *  .chud-root). The curated stream caps to the viewport, so the comprehensive
 *  list sits off-screen; this chip says it exists and scrolls to it on click. */
export function renderDomainItemsHint(
    host: HTMLElement,
    count: number,
    label: string,
    color: string,
    onJump: () => void,
): void {
    if (!count) { host.innerHTML = ''; return; }
    host.innerHTML = `
        <button type="button" class="domain-items-hint" style="--domain-color:${diEscAttr(color)};">
            <span class="domain-items-hint-icon" aria-hidden="true">\u{1F4CB}</span>
            <span class="domain-items-hint-text">${diEscHtml(label)} \u2014 ${count} more in full sector feed</span>
            <span class="domain-items-hint-arrow" aria-hidden="true">\u2193</span>
        </button>`;
    host.querySelector<HTMLButtonElement>('.domain-items-hint')?.addEventListener('click', onJump);
}

/** Clear the comprehensive list (used when "All" is selected or tab changes). */
export function clearDomainItems(host: HTMLElement): void {
    host.innerHTML = '';
}
