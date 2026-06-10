import { type Alert } from '../api';
import {
    STRATEGIC_TOPIC_FILTERS,
    getTopicColor,
    getTopicDisplayLabel,
    getTopicCssVars,
    normalizeTopicCode,
    type StrategicTopicCode,
} from '../topics';
import { resolveAlertHeadline } from '../alert_display';
import { formatIntelFeedTimestamp, formatIntelTime } from './utils';
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
                <h3 style="font-size:1.1rem; color:#58a6ff;">Evidence: ${title}</h3>
                <button class="modal-close-btn" style="background:none; border:none; color:#8b949e; cursor:pointer; font-size:1.5rem;">&times;</button>
            </div>
            <div style="display:flex; flex-direction:column; gap:1.5rem;">
                ${evidenceList.map((item, index) => `
                    <div class="evidence-item" style="border-left:2px solid var(--accent); padding-left:1rem;">
        
                        ${index === 0 ? `<div class="primary-badge">PRIMARY</div>` : ''}

                        <div style="font-weight:600; color:#c9d1d9; font-size:0.9rem; margin-bottom:0.5rem;">
                            ${item.title || 'Source Signal'}
                        </div>

                        <div style="display:flex; gap:0.5rem; align-items:center; margin-bottom:0.75rem;">
                            <span class="evidence-domain">${item.domain || item.type || 'OSINT'}</span>
                        </div>

                        ${(item.url || item.link) ? `
                            <a href="${item.url || item.link}" target="_blank"
                            style="color:#58a6ff; text-decoration:none; font-size:0.8rem; font-weight:600;">
                            🔗 View Source &rarr;
                            </a>
                        ` : '<div style="font-size:0.8rem; color:#8b949e;">🔒 Restricted Source</div>'}
                    </div>
                `).join('')}
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

export function renderLiveFeed(alerts: Alert[], container: HTMLElement) {
    // [v16.0] Compact Pulse Bar: Single most critical/recent signal
    const latest = [...alerts].sort((a, b) => {
        const impA = typeof a.importance_score === 'number' ? a.importance_score : -1;
        const impB = typeof b.importance_score === 'number' ? b.importance_score : -1;
        if (impA !== impB) return impB - impA;
        return new Date(b.triggered_at).getTime() - new Date(a.triggered_at).getTime();
    })[0];

    if (!latest) {
        container.innerHTML = `
            <div class="pulse-content" style="opacity:0.6; font-size: 0.75rem; letter-spacing: 0.5px; display: flex; align-items: center; gap: 8px;">
                <span class="severity-dot" style="background: rgba(88, 166, 255, 0.4); box-shadow: 0 0 8px rgba(88, 166, 255, 0.2);"></span>
                <span style="font-weight: 500;">PULSE: Monitoring global signal backbone...</span>
            </div>
        `;
        return;
    }

    const severityClass = latest.severity.toLowerCase();
    const timeStr = formatIntelTime(latest.triggered_at);
    const canonicalTopic = normalizeTopicCode(latest.topic);
    const topicColor = getTopicColor(canonicalTopic);
    const topicLabel = getTopicDisplayLabel(canonicalTopic);
    const pulseHeadline = resolveAlertHeadline(latest);

    // Apply temporary fade class if container already had content (simulating update)
    const isUpdate = container.innerHTML.length > 0;

    const headlineHtml = pulseHeadline.pending
        ? '<span class="alert-headline-skeleton alert-headline-skeleton--inline" aria-hidden="true"></span>'
        : `<span style="flex:1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 0.75rem; font-weight: 600; color: #fff;">${pulseHeadline.text}</span>`;

    container.innerHTML = `
        <div class="pulse-content ${isUpdate ? 'pulse-fade-update' : ''}" style="display: flex; align-items: center; gap: 10px; width: 100%; overflow: hidden;">
            <span class="severity-dot ${severityClass}"></span>
            <span style="font-weight:900; color:${topicColor}; font-size: 0.65rem; text-transform: uppercase; letter-spacing: 1px;">${topicLabel}</span>
            ${headlineHtml}
            <span style="opacity:0.5; font-size: 0.65rem; font-family: monospace;">[${timeStr}]</span>
        </div>
    `;
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

const CHUD_LOG_MAX = 64;          // raw-log lines retained in the DOM
const CHUD_LOG_TICK_MS = 820;     // base cadence of the synthetic process log

let chudLogBuffer: string[] = []; // persists across re-renders → seamless stream
let chudLogTimer: number | null = null;
let chudSelectedId: string | null = null;
// Secondary-sources accordion open-state. Lives at module scope so the ~10s poll
// (which rebuilds the detail panel's innerHTML) can RE-EMIT the expanded markup
// instead of silently collapsing it. Reset to false whenever the selection
// changes (a freshly-opened signal always starts collapsed).
let chudSrcExpanded = false;
let chudAlerts: Alert[] = [];       // current (filtered+sorted) set, by render
let chudLatestAlerts: Alert[] = []; // pool the log generator samples from
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

function chudPick<T>(arr: T[]): T {
    return arr[Math.floor(Math.random() * arr.length)];
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

function chudClock(): string {
    const d = new Date();
    const p = (n: number) => String(n).padStart(2, '0');
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

// ─── Raw process-log engine ──────────────────────────────────────────────

/** Synthesise one plausible system-process line, biased toward live alerts. */
function chudGenerateLogLine(pool: Alert[]): string {
    const a = pool.length ? chudPick(pool) : null;
    const topic = a ? getTopicDisplayLabel(normalizeTopicCode(a.topic)) : 'GLOBAL';
    const tok = a ? chudToken(a) : `SYS-${chudPick(['00A1', '7F2C', '4E90', 'BB13'])}`;
    const country = (a?.country || chudPick(['US', 'CN', 'RU', 'IR', 'UA', 'SA', 'TW', 'EU', 'IL'])).toUpperCase();
    const sev = (a?.severity || 'watch').toUpperCase();
    const n = 8 + Math.floor(Math.random() * 240);
    const entropy = (Math.random() * 0.6 + 0.05).toFixed(3);
    const visc = (Math.random() * 1.2 + 0.1).toFixed(3);
    const lat = (Math.random() * 40 + 1).toFixed(2);
    const conf = (Math.random() * 0.28 + 0.7).toFixed(2);

    const templates = [
        `[RSS] parsed ${n} nodes :: stream=${topic}`,
        `[GEO-RESOLVER] mapping coordinates for ${tok} → ${country}`,
        `[PHYSICS] entropy stable at ${entropy} · ν=${visc}`,
        `[NLP] entity match ${tok} :: confidence ${conf}`,
        `[BACKBONE] discovery ${tok} status=${a?.backbone_discovery_status || 'idle'}`,
        `[SIGNAL] ${sev} intensity=${a?.intensity_display ?? '—'} topic=${topic}`,
        `[INGEST] flush buffer ${n} items · lat=${lat}ms`,
        `[VECTOR] recompute affinity matrix dim=${n}×${n}`,
        `[CACHE] hit-ratio ${(Math.random() * 18 + 80).toFixed(1)}% · evict=${Math.floor(Math.random() * 9)}`,
        `[ENTROPY] phase-transition guard nominal :: Δ${(Math.random() * 0.04).toFixed(4)}`,
        `[XFEED] cross-domain link ${tok} ⇄ ${country} weight=${Math.random().toFixed(2)}`,
    ];
    return chudPick(templates);
}

function chudLogLineHtml(line: string): string {
    const m = line.match(/^\[([A-Z-]+)\]/);
    const tag = m ? m[1] : 'SYS';
    const body = line.replace(/^\[[A-Z-]+\]\s*/, '');
    return (
        `<div class="chud-log-line">` +
        `<span class="chud-log-ts">${chudClock()}</span>` +
        `<span class="chud-log-tag chud-tag--${tag}">[${tag}]</span>` +
        `<span class="chud-log-body">${chudEscape(body)}</span>` +
        `</div>`
    );
}

/** Lightly fluctuate the pipeline telemetry cluster (hyper-real, not jumpy). */
function chudUpdateTelemetry(): void {
    const set = (key: string, val: string) => {
        const el = document.querySelector<HTMLElement>(`[data-ptl="${key}"]`);
        if (el) el.textContent = val;
    };
    set('rate', (Math.random() * 6 + 9.5).toFixed(1));        // 9.5–15.5 sig/s
    set('lat', String(28 + Math.floor(Math.random() * 32)));  // 28–60 ms
    set('load', String(31 + Math.floor(Math.random() * 22))); // 31–53 %
    set('up', (Math.random() < 0.5 ? 99.9 : 100.0).toFixed(1));
}

/** Start (or restart) the single self-cleaning raw-log interval. */
function chudStartLogStream(container: HTMLElement): void {
    const track = container.querySelector<HTMLElement>('.chud-log-track');
    if (!track) return;

    if (chudLogBuffer.length === 0) {
        for (let i = 0; i < 14; i++) chudLogBuffer.push(chudGenerateLogLine(chudLatestAlerts));
    }
    track.innerHTML = chudLogBuffer.map(chudLogLineHtml).join('');
    track.scrollTop = track.scrollHeight;
    chudUpdateTelemetry();

    if (chudLogTimer !== null) {
        clearInterval(chudLogTimer);
        chudLogTimer = null;
    }

    chudLogTimer = window.setInterval(() => {
        const liveTrack = document.querySelector<HTMLElement>('.chud-log-track');
        // Self-clean: if the console left the DOM (tab switch / re-render race)
        // kill the interval so we never write to a detached node.
        if (!liveTrack || !document.body.contains(liveTrack)) {
            if (chudLogTimer !== null) clearInterval(chudLogTimer);
            chudLogTimer = null;
            return;
        }
        const burst = 1 + (Math.random() < 0.32 ? 1 : 0);
        for (let i = 0; i < burst; i++) {
            const line = chudGenerateLogLine(chudLatestAlerts);
            chudLogBuffer.push(line);
            if (chudLogBuffer.length > CHUD_LOG_MAX) chudLogBuffer.shift();
            const holder = document.createElement('div');
            holder.innerHTML = chudLogLineHtml(line);
            const node = holder.firstElementChild as HTMLElement | null;
            if (node) {
                node.classList.add('chud-log-line--new');
                liveTrack.appendChild(node);
            }
        }
        while (liveTrack.childElementCount > CHUD_LOG_MAX && liveTrack.firstElementChild) {
            liveTrack.removeChild(liveTrack.firstElementChild);
        }
        liveTrack.scrollTop = liveTrack.scrollHeight;
        chudUpdateTelemetry();
    }, CHUD_LOG_TICK_MS);
}

// ─── Stream rows (left pane) ─────────────────────────────────────────────

function chudRowHtml(alert: Alert): string {
    const canonicalTopic = normalizeTopicCode(alert.topic);
    const topicLabel = getTopicDisplayLabel(canonicalTopic);
    const topicColor = getTopicColor(canonicalTopic);
    const headline = resolveAlertHeadline(alert);
    const sev = alertThreatTier(alert);
    const time = alert.triggered_at ? formatIntelTime(alert.triggered_at) : 'LIVE';
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

function chudTagChip(label: string, kind: string): string {
    return `<span class="chud-chip chud-chip--${kind}">${chudEscape(label)}</span>`;
}

// Plain-language explainer for the two orthogonal axes shown in the detail
// pane (anomaly ring + importance bar). Wired as a click ⓘ popover.
const AXES_GUIDE_HTML = `
    <strong>Two independent axes</strong><br>
    <b>ANOMALY</b> — how sharply this story's source-domain deviated from its own recent baseline (a self-normalizing "unusualness" ratio, not importance; usually 20–60%).<br>
    <b>IMPORTANCE</b> — how widely the event affects the world (energy, markets, shipping, defense, AI/semiconductors, crypto), scored 0–100 by an LLM from the headline.<br>
    They're independent: a globally important story can show low anomaly, and a high-anomaly blip can be globally trivial.`;

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
    // math — text and arc both read the same server-supplied value. When the
    // field is absent (rare cold-start rows) the gauge reads 0%.
    const pctVal = Math.max(0, Math.min(100, typeof alert.intensity_pct === 'number' ? alert.intensity_pct : 0));
    const threatOffset = Math.round(THREAT_CIRCUMFERENCE * (1 - pctVal / 100));
    const displayPercentage = Math.round(pctVal) + '%';
    const headline = resolveAlertHeadline(alert);
    const token = chudToken(alert);
    const time = alert.triggered_at ? formatIntelFeedTimestamp(alert.triggered_at) : 'Live';
    const locked = alert.is_locked && !DEV_MODE_AUDIT;

    const status = alert.backbone_discovery_status || 'idle';
    // ANALYZING badge purged — the 'processing' state renders no status chip.
    const statusLabel =
        status === 'complete' ? 'VERIFIED'
        : status === 'failed' ? 'RAW SIGNAL'
        : status === 'processing' ? ''
        : 'PENDING';

    // Signal tags — all from real alert fields (no fabricated entities).
    const tags: string[] = [chudTagChip(topicLabel, 'topic')];
    if (alert.country) tags.push(chudTagChip(alert.country, 'geo'));
    tags.push(chudTagChip(TIER_LABEL[sev], `sev-${sev}`));
    if (statusLabel) tags.push(chudTagChip(statusLabel, 'status'));
    // Raw float coordinates intentionally omitted — they are debug noise, not a signal tag.

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

    const description = alert.description
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
                        <circle class="chud-threat-meter" cx="50" cy="50" r="45"
                            style="stroke-dasharray:${THREAT_CIRCUMFERENCE.toFixed(2)};stroke-dashoffset:${threatOffset}"></circle>
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

            <h2 class="chud-detail-headline">${locked ? '🔒 ' : ''}${chudEscape(headline.text || alert.target_label || 'Signal')}</h2>
            ${description}

            <section class="chud-block">
                <div class="chud-block-label">SIGNAL TAGS</div>
                <div class="chud-chips">${tags.join('')}</div>
            </section>

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
const CHUD_FALLBACK_FILTERS = [
    'All', 'Energy & Resources', 'Global Market Intel', 'AI & Semiconductors',
    'Crypto & Geopolitics', 'Defense Technology', 'Supply Chain Intelligence',
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
        // Observe direct children only — fires on tab-render swaps, NOT on the
        // per-second log appends (those mutate deep inside .chud-log-track).
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

    // Refresh module state consumed by the row/detail/log helpers.
    chudAlerts = sortedAlerts;
    chudLatestAlerts = sortedAlerts;

    // CRIT counter mirrors the displayed CRITICAL tier (importance_score >= 80),
    // so the header matches the row badges produced by alertThreatTier.
    const critical = sortedAlerts.filter(a => typeof a.importance_score === 'number' && a.importance_score >= IMPORTANCE_CRITICAL).length;
    const existing = container.querySelector<HTMLElement>('.chud-root');

    // ── Incremental path (≈ every 10s poll) — swap rows only, keep log + detail.
    if (existing) {
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
            <div class="chud-console" role="log" aria-label="Live ingestion process log">
                <div class="chud-console-grid">
                    <div class="chud-control-pad" data-role="control-pad"></div>
                    <div class="chud-monitor">
                        <div class="chud-console-head">
                            <span class="chud-console-dot" aria-hidden="true"></span>
                            <span class="chud-console-title">RAW INGESTION STREAM</span>
                            <span class="chud-console-meta">PID//OSINT-CORE · <span class="chud-console-live">LIVE</span></span>
                        </div>
                        <div class="chud-console-body">
                            <div class="chud-log-track"></div>
                            <div class="pipeline-telemetry" aria-label="Pipeline telemetry">
                                <div class="ptl-item">
                                    <span class="ptl-k">INGEST RATE</span>
                                    <span class="ptl-v"><b data-ptl="rate">12.4</b> <span class="ptl-u">sig/s</span></span>
                                </div>
                                <div class="ptl-item">
                                    <span class="ptl-k">LATENCY</span>
                                    <span class="ptl-v"><b data-ptl="lat">42</b> <span class="ptl-u">ms</span></span>
                                </div>
                                <div class="ptl-item">
                                    <span class="ptl-k">CORE LOAD</span>
                                    <span class="ptl-v"><b data-ptl="load">37</b> <span class="ptl-u">%</span></span>
                                </div>
                                <div class="ptl-item ptl-item--ok">
                                    <span class="ptl-k">UPTIME</span>
                                    <span class="ptl-v"><b data-ptl="up">99.9</b> <span class="ptl-u">%</span></span>
                                </div>
                            </div>
                        </div>
                    </div>
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

    // Boot the perpetual raw-log engine + project an initial selection.
    chudStartLogStream(root);
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
        idx: '01', glyph: '📡', title: 'Ingestion & Normalization', tag: '[Delta Polling / Cache]',
        desc: 'Fetches the active data window using the since cursor, matching server-side Redis constraints.',
        tick: 'src=<b data-sl="sources">1208</b> · dedup <b data-sl="dedup">99.2%</b>',
    },
    {
        idx: '02', glyph: '🛰', title: 'NLP Entity Tracking & Geocoding', tag: '[Geospatial Resolver]',
        desc: 'Identifies company contexts and assigns physical coordinates (lat, lon).',
        tick: 'vec(φ,λ) ok <b data-sl="ner">96.4%</b> · ents <b data-sl="ents">37</b>',
    },
    {
        idx: '03', glyph: '🧮', title: 'Multi-Domain Classification', tag: '[Domain Matrix]',
        desc: 'Sorts filtered signals into AI-Semi, Energy, Shipping, Defense & Crypto lattices without human bias.',
        tick: 'matched <b data-sl="domains">6</b>/6 domains · conf <b data-sl="dconf">0.91</b>',
    },
    {
        idx: '04', glyph: '🖥', title: 'UI State Engine & Repaint', tag: '[Stateful Hydration]',
        desc: 'Pipes the fresh delta payloads into the modular rendering queue to drive the Cyber-HUD layout.',
        tick: 'upsert <b data-sl="upsert">3</b> rows · repaint <b data-sl="repaint">6</b>ms',
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

/** Glowing SVG spine with declarative (SMIL) particle flow across all stages. */
function sysLogicFlowSvg(): string {
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

    // Left (bottom) — concrete fact interception + dedupe loop, paired with the
    // entropy math above to form one complete intelligence ledger.
    const interceptor = `
        <pre class="sl-code"><span class="sl-code-head">[Fact Interception]</span>
<span class="sl-kw">const</span> seen = <span class="sl-kw">new</span> <span class="sl-fn">Set</span>()
<span class="sl-kw">for</span> (sig <span class="sl-kw">of</span> Δ_payload) {
  <span class="sl-kw">if</span> (seen.<span class="sl-fn">has</span>(sig.id)) <span class="sl-kw">continue</span> <span class="sl-cmt">// dedupe</span>
  rank = SEV_RANK[sig.severity] <span class="sl-cmt">// crit &gt; elev &gt; watch</span>
}
sorted = <span class="sl-fn">stableSort</span>(rank, recency)</pre>`;

    // Right — the actual incremental UI rendering / state-hydration loop.
    const hydration = `
        <pre class="sl-code"><span class="sl-code-head">[State Validation Loop]</span>
Δ_payload = <span class="sl-fn">fetch</span>(<span class="sl-str">'/api/alerts?since='</span> + last_tick)
<span class="sl-kw">if</span> (Δ_payload.length &gt; 0) {
  <span class="sl-fn">DOM_Upsert</span>(stream_container, Δ_payload)
  <span class="sl-fn">Maintain_Active_Selection</span>(module_state.selected_id)
}</pre>`;

    const telemetry = `
        <div class="sl-telemetry">
            <div class="sl-telem-row"><span class="sl-telem-k">Polling Interval</span><span class="sl-telem-v">10,000 ms</span></div>
            <div class="sl-telem-row"><span class="sl-telem-k">State Persistence</span><span class="sl-telem-v sl-telem-v--ok">Active</span></div>
            <div class="sl-telem-row"><span class="sl-telem-k">Event Delegation</span><span class="sl-telem-v sl-telem-v--ok">Enabled · Stable Parents</span></div>
        </div>`;

    return `
        <div class="sl-math">
            <section class="sl-math-block">
                <div class="sl-math-label">NETWORK ENTROPY · information-theoretic volatility</div>
                ${entropy}
                <div class="sl-math-live">Iterating: ΔH = <b data-sl="dH">0.281</b> · Current Entropy: <b data-sl="entropy">2.317</b> bits</div>
                <div class="sl-divider" aria-hidden="true"></div>
                ${interceptor}
                <div class="sl-math-live">intercepted <b data-sl="intercepted">128</b> · deduped <b data-sl="deduped">12</b> · sorted ok</div>
            </section>
            <section class="sl-math-block">
                <div class="sl-math-label">INCREMENTAL TICKER ENGINE · delta state hydration</div>
                ${hydration}
                ${telemetry}
                <div class="sl-math-live">Spatial Worker Handoff (downstream) <b data-sl="adj">62.6%</b> · cyc <b data-sl="iter">0</b></div>
            </section>
        </div>`;
}

function sysLogicRandom(min: number, max: number, dp: number): string {
    return (Math.random() * (max - min) + min).toFixed(dp);
}

/** Cascade fresh values into every [data-sl] readout for the "deep compute" feel. */
function sysLogicTick(root: HTMLElement): void {
    sysLogicIter += 1;
    const set = (key: string, val: string) => {
        const el = root.querySelector<HTMLElement>(`[data-sl="${key}"]`);
        if (el) el.textContent = val;
    };
    // Stage telemetry — ingestion / NER / classification / UI repaint.
    set('sources', String(1200 + Math.floor(Math.random() * 96)));
    set('dedup', sysLogicRandom(98.4, 99.9, 1) + '%');
    set('ner', sysLogicRandom(94.5, 98.9, 1) + '%');
    set('ents', String(24 + Math.floor(Math.random() * 40)));
    set('domains', String(4 + Math.floor(Math.random() * 3)));
    set('dconf', sysLogicRandom(0.86, 0.98, 2));
    set('upsert', String(Math.floor(Math.random() * 12)));
    set('repaint', String(2 + Math.floor(Math.random() * 14)));
    // State-panel readouts — Shannon entropy + interception (left), hydration (right).
    set('dH', sysLogicRandom(0.18, 0.42, 3));
    set('entropy', sysLogicRandom(2.0, 2.9, 3));
    set('intercepted', String(40 + Math.floor(Math.random() * 200)));
    set('deduped', String(1 + Math.floor(Math.random() * 40)));
    set('adj', sysLogicRandom(40, 88, 1) + '%');
    set('iter', String(sysLogicIter));
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

function openSystemLogic(): void {
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
                    <div class="syslogic-sub">REAL-TIME COMPUTATIONAL SCHEMATIC · OSINT-CORE</div>
                </div>
                <button type="button" class="syslogic-close" aria-label="Close System Logic">×</button>
            </header>

            <div class="syslogic-body">
                ${sysLogicFlowSvg()}
                <div class="sl-stages">${sysLogicStageHtml()}</div>
                ${sysLogicStatePanelsHtml()}
            </div>

            <footer class="syslogic-foot">
                <span class="syslogic-foot-dot" aria-hidden="true"></span>
                ENGINE NOMINAL · pipeline executing · press <kbd>ESC</kbd> to return to stream
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
    sysLogicTimer = window.setInterval(() => {
        if (!sysLogicEl || !document.body.contains(overlay)) {
            if (sysLogicTimer !== null) clearInterval(sysLogicTimer);
            sysLogicTimer = null;
            return;
        }
        sysLogicTick(overlay);
    }, 720);
}