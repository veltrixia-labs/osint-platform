/**
 * Shared Pro dashboard UI primitives (Market Pulse + Pro Insights + Expert).
 */

import { getTopicDef, getTopicColor, normalizeTopicCode } from '../topics';

export const SECTOR_DISTRIBUTION_GUIDE_HTML = `
<p class="intel-guide-title"><strong>Sector Distribution Guide</strong></p>
<ul class="intel-guide-list">
<li><strong>Intelligence Volume Index:</strong> Represents the total cumulative data points, active alerts, and structured contextual inputs currently ingested within each specific domain.</li>
<li><strong>Operational Utility:</strong> This bar ratio visualizes VELTRIXIA&rsquo;s cognitive focus. A sudden spike or extension in a specific sector&rsquo;s bar reflects a heavy influx of real-time signals, indicating an escalating operational friction or high-density risk event in that market vertical.</li>
</ul>`;

/** Module A — Risk Contagion & Lead-Lag Tracker */
export const LEAD_LAG_GUIDE_HTML = `
<div class="pro-guide-content">
  <strong>Risk Contagion & Lead-Lag Tracker</strong>
  <p>Quantifies the directional propagation of risk across sectors by calculating the real-time Cross-Correlation Function (CCF).</p>
  <ul style="margin-top: 8px; padding-left: 16px; opacity: 0.9; line-height: 1.4;">
    <li style="margin-bottom: 4px;"><strong>Lag (e.g., +6.0h):</strong> The time delay before the source sector's risk impacts the target sector.</li>
    <li><strong>R (Correlation):</strong> Measures relationship strength (-1.0 to 1.0).
      <ul style="margin-top: 4px; padding-left: 16px; list-style-type: circle;">
        <li><strong>R &gt; 0:</strong> Positive correlation (moves in the same direction).</li>
        <li><strong>R &lt; 0:</strong> Inverse correlation (moves in the opposite direction). <em>*A negative R is a strong predictive signal, not a lack of correlation.</em></li>
      </ul>
    </li>
  </ul>
</div>`;

/** Module B — Momentum & Acceleration Gauge */
export const MOMENTUM_GAUGE_GUIDE_HTML = `
<p class="intel-guide-title"><strong>Momentum &amp; Acceleration Gauge</strong></p>
<p class="intel-guide-body">Applies fluid-dynamic derivatives to quantify risk velocity (dI/dt) and acceleration (d²I/dt²). This reveals whether a threat is expanding exponentially (burst potential) or stabilizing, serving as an early-warning metric before scores peak.</p>`;

/** Module C — Verified Source Evidence Stream */
export const EVIDENCE_STREAM_GUIDE_HTML = `
<p class="intel-guide-title"><strong>Verified Source Evidence Stream</strong></p>
<p class="intel-guide-body">A live, horizontal timeline of the raw OSINT signals, news feeds, and intelligence nodes causing current domain spikes. Provides strict end-to-end transparency and auditability for automated platform risk triggers.</p>`;

export const HISTORICAL_RISK_TREND_GUIDE_HTML = `
<p class="intel-guide-title"><strong>Historical Risk Trend</strong></p>
<p class="intel-guide-body">A chronological visualization of normalized domain pressure indexes across key sectors over the past 24 hours, 7 days, or 30 days. This chart allows for comparative analysis of relative risk volatility and trend waveforms.</p>`;

export const ACTIVE_MARKET_PRESSURES_GUIDE_HTML = `
<div class="intel-guide-content intel-guide-content--pressures">
<p class="intel-guide-title"><strong>Active Market Pressures</strong></p>
<p class="intel-guide-body">A real-time dashboard tracking sudden volatility and incoming signal intensity for targeted sectors.</p>
<p class="intel-guide-subhead"><strong>How to read:</strong></p>
<ul class="intel-guide-list intel-guide-list--compact">
<li><strong>Score (e.g., 8.5):</strong> The current normalized domain pressure index.</li>
<li><strong>Delta (e.g., &uarr; 0.7):</strong> The net change in the score over the last 24 hours.</li>
<li><strong>SPIKE / ANOMALY Badge:</strong> This alert specifically triggers when the underlying raw signal intensity increases by <strong>1.5x or more within a 24-hour clustering window</strong>, highlighting sudden, accelerating threats regardless of the baseline score.</li>
</ul>
</div>`;

function effectiveRiskIntensity(stat: Record<string, unknown>): number {
    const ui = Number(stat.intensity);
    if (Number.isFinite(ui) && ui > 0) return ui;
    const score = Number(stat.intelligence_score);
    if (Number.isFinite(score) && score > 0) return score * 10;
    return 0;
}

function formatPressureIndex(stat: Record<string, unknown>): string {
    const v = effectiveRiskIntensity(stat);
    return v >= 9.5 ? v.toFixed(2) : v.toFixed(1);
}

function renderPressureBadge(stat: Record<string, unknown>): string {
    const variant = String(stat.pressure_badge_variant || '');
    const label = String(stat.pressure_badge_label || '');
    if (variant && label) {
        const cls =
            variant === 'sustained'
                ? 'pressure-badge pressure-badge--sustained'
                : 'pressure-badge pressure-badge--anomaly';
        const prefix = variant === 'anomaly' ? '⚠️ ' : '';
        return `<div class="${cls}" role="status">${prefix}${escHtml(label)}</div>`;
    }
    if (stat.anomaly_detected) {
        return `<div class="pressure-badge pressure-badge--anomaly" role="status">⚠️ ANOMALY DETECTED</div>`;
    }
    return '';
}

export function escHtml(s: string): string {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

export function escAttr(s: string): string {
    return escHtml(s).replace(/'/g, '&#39;');
}

export type PanelGuidePlacement = 'below' | 'above';

/** ℹ️ guide control — shared glassmorphism popover (inline next to panel titles). */
export function renderPanelGuide(
    ariaLabel: string,
    guideInnerHtml: string,
    placement: PanelGuidePlacement = 'below',
): string {
    const placementClass =
        placement === 'above' ? ' intel-section-guide-wrap--popover-above' : '';
    return `<span class="intel-section-guide-wrap intel-section-guide-wrap--inline${placementClass}">
            <button type="button" class="intel-section-guide" aria-label="About ${escAttr(ariaLabel)}" aria-expanded="false">
                <span class="intel-section-guide-icon" aria-hidden="true">ℹ</span>
            </button>
            <span class="intel-section-guide-popover intel-section-guide-popover--rich" role="tooltip">
                <button type="button" class="intel-section-guide-close" aria-label="Close guide" tabindex="0">×</button>
                ${guideInnerHtml}
            </span>
           </span>`;
}

/** Wire up all guide ℹ️ buttons in root: click to open, × or outside-click to close. */
export function wirePanelGuideTooltips(root: HTMLElement): void {
    root.querySelectorAll<HTMLElement>('.intel-section-guide').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const wrap = btn.closest('.intel-section-guide-wrap');
            const pop = wrap?.querySelector('.intel-section-guide-popover');
            if (!pop) return;
            const wasOpen = pop.classList.contains('is-open');
            // Close all open popovers in this root first
            root.querySelectorAll('.intel-section-guide-popover.is-open').forEach((el) => {
                el.classList.remove('is-open');
                el.closest('.intel-section-guide-wrap')?.querySelector('.intel-section-guide')?.setAttribute('aria-expanded', 'false');
            });
            if (!wasOpen) {
                pop.classList.add('is-open');
                btn.setAttribute('aria-expanded', 'true');
            }
        });
    });

    root.querySelectorAll<HTMLElement>('.intel-section-guide-close').forEach((closeBtn) => {
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const pop = closeBtn.closest('.intel-section-guide-popover');
            if (!pop) return;
            pop.classList.remove('is-open');
            pop.closest('.intel-section-guide-wrap')?.querySelector('.intel-section-guide')?.setAttribute('aria-expanded', 'false');
        });
    });
}

/** Glass panel wrapper (Sector Distribution chrome). */
export function renderProPanel(
    title: string,
    content: string,
    footer?: string,
    accentColor = '#58a6ff',
    guideHtml?: string,
): string {
    const headerClass = guideHtml
        ? 'insight-card-header insight-card-header--with-guide'
        : 'insight-card-header';
    return `
    <div class="insight-card pro-insight-panel" style="--accent: ${accentColor}">
        <div class="${headerClass}">
            <h3 class="insight-card-title">${title}</h3>
            ${guideHtml || ''}
        </div>
        <div class="insight-card-body">
            ${content}
        </div>
        ${footer ? `<div class="insight-card-footer">${footer}</div>` : ''}
    </div>`;
}

export function renderIntensityBar(value: number, label: string, color = '#58a6ff'): string {
    const percent = Math.min(Math.max(value * 10, 0), 100);
    return `
    <div class="intensity-bar-wrap">
        <div class="intensity-bar-label">
            <span>${label}</span>
            <span style="color: ${color}">${value.toFixed(1)}</span>
        </div>
        <div class="intensity-bar-bg">
            <div class="intensity-bar-fill" style="width: ${percent}%; background: ${color}; box-shadow: 0 0 10px ${color}44;"></div>
        </div>
    </div>`;
}

export function buildRiskSummaryCardsHtml(riskSummary: Record<string, unknown> | undefined): string {
    if (!riskSummary || Object.keys(riskSummary).length === 0) {
        return `<div class="u-p-2 u-text-center" style="grid-column: 1/-1; opacity:0.6; font-size: 0.9rem;">Intelligence gathering in progress...</div>`;
    }
    return Object.entries(riskSummary)
        .map(([topic, stat]: [string, any]) => {
            const def = getTopicDef(topic === 'null' ? null : topic);
            return `
                <div class="bluf-stat-card bluf-stat-card--compact" style="--accent: ${def.color}">
                    <div class="bluf-header u-flex-between">
                        <div class="bluf-topic">${def.icon} ${def.label}</div>
                        <div class="bluf-trend bluf-trend--${stat.trend}">${stat.trend === 'rising' ? '▲' : '■'}</div>
                    </div>
                    <div class="u-flex u-flex-baseline">
                        <div class="bluf-value">${formatPressureIndex(stat)}</div>
                        ${stat.intensity_delta !== undefined ? `
                            <div class="bluf-delta ${stat.intensity_delta > 0.5 ? 'rising' : stat.intensity_delta < -0.5 ? 'falling' : ''}" style="margin-left: 8px; font-size: 0.75rem; font-weight: 800;">
                                ${stat.intensity_delta > 0 ? '↑' : stat.intensity_delta < 0 ? '↓' : ''} ${Math.abs(stat.intensity_delta).toFixed(1)} <span style="font-weight:400; opacity:0.6;">(24h)</span>
                            </div>
                        ` : ''}
                        ${stat.spike_detected ? `<div class="spike-badge" title="UNUSUAL MOMENTUM DETECTED">SPIKE</div>` : ''}
                    </div>
                    <div class="bluf-label">${stat.why_it_matters || ''}</div>
                    ${renderPressureBadge(stat)}
                    <div class="bluf-latest-wrap">
                        <span class="bluf-latest-label">TOP SIGNAL</span>
                        <div class="bluf-latest">${stat.top_signal || 'None'}</div>
                    </div>
                </div>`;
        })
        .join('');
}

// ── Module A: Risk Contagion & Lead-Lag Tracker ────────────────────────────────

const DOMAIN_SHORT: Record<string, string> = {
    energy_resource_risk:       'Energy',
    global_market_intelligence: 'Market',
    crypto_geopolitics:         'Crypto',
    ai_semiconductor_intelligence: 'AI/Semi',
    defense_technology:         'Defense',
    supply_chain_intelligence:  'Supply Chain',
};

export function renderLeadLagNetwork(
    matrix: { source: string; target: string; lag_hours: number; correlation: number }[],
    _riskSummary: Record<string, unknown> | undefined,
): string {
    if (!matrix || matrix.length === 0) {
        return `<p class="mp-module-empty">Awaiting cross-sector correlation data — insufficient active domain signals.</p>`;
    }

    const rows = matrix.map(pair => {
        const srcColor = getTopicColor(pair.source);
        const tgtColor = getTopicColor(pair.target);
        const srcShort = DOMAIN_SHORT[pair.source] || pair.source;
        const tgtShort = DOMAIN_SHORT[pair.target] || pair.target;
        const r = pair.correlation;
        const absR = Math.abs(r);
        const lagSign = r >= 0 ? '+' : '';
        // Line opacity scales with |R|
        const lineOpacity = (0.3 + absR * 0.55).toFixed(2);
        const lineWidth = absR >= 0.65 ? 2.5 : 1.5;
        const rClass = absR >= 0.7 ? 'leadlag-r--high' : absR >= 0.5 ? 'leadlag-r--mid' : 'leadlag-r--low';

        return `
        <div class="leadlag-pair">
            <span class="leadlag-badge" style="--badge-color:${srcColor}">${srcShort}</span>
            <span class="leadlag-connector" style="opacity:${lineOpacity};">
                <span class="leadlag-line" style="border-width:${lineWidth}px;"></span>
                <span class="leadlag-annotation">
                    <span class="leadlag-lag">${lagSign}${pair.lag_hours.toFixed(1)}h</span>
                    <span class="leadlag-sep">/</span>
                    <span class="leadlag-corr ${rClass}">R=${r.toFixed(2)}</span>
                </span>
                <span class="leadlag-arrow">&#8250;</span>
            </span>
            <span class="leadlag-badge" style="--badge-color:${tgtColor}">${tgtShort}</span>
        </div>`;
    }).join('');

    return `<div class="leadlag-network">${rows}</div>`;
}

// ── Module B: Momentum & Acceleration Gauge ────────────────────────────────────

export function renderMomentumGauges(
    riskSummary: Record<string, unknown> | undefined,
): string {
    if (!riskSummary || Object.keys(riskSummary).length === 0) {
        return `<p class="mp-module-empty">Awaiting sector telemetry for derivative computation...</p>`;
    }

    const DOMAIN_ORDER = [
        'energy_resource_risk',
        'global_market_intelligence',
        'crypto_geopolitics',
        'ai_semiconductor_intelligence',
        'defense_technology',
        'supply_chain_intelligence',
    ];

    const cols = DOMAIN_ORDER.map(topic => {
        const stat = (riskSummary as any)[topic] || {};
        const def = getTopicDef(topic);
        const color = def.color;
        const shortLabel = DOMAIN_SHORT[topic] || def.label;

        const v: number = stat.velocity ?? 0;
        const a: number = stat.acceleration ?? 0;
        const vLabel: string = stat.v_label ?? 'stable';
        const aLabel: string = stat.a_label ?? 'stable';

        // Velocity arrow
        const vIcon =
            vLabel === 'rising'
                ? '<span class="momentum-arrow momentum-arrow--up" aria-label="Rising velocity">↑</span>'
                : vLabel === 'falling'
                ? '<span class="momentum-arrow momentum-arrow--down" aria-label="Falling velocity">↓</span>'
                : '<span class="momentum-arrow momentum-arrow--stable" aria-label="Stable">—</span>';

        // Acceleration: double-up arrow for high accel
        const isHighAccel = aLabel === 'accelerating' && Math.abs(a) > 0.3;
        const aIcon = isHighAccel
            ? '<span class="momentum-arrow momentum-arrow--burst" aria-label="High acceleration">⇈</span>'
            : aLabel === 'accelerating'
            ? '<span class="momentum-arrow momentum-arrow--accel" aria-label="Accelerating">↑</span>'
            : aLabel === 'decelerating'
            ? '<span class="momentum-arrow momentum-arrow--decel" aria-label="Decelerating">↓</span>'
            : '<span class="momentum-arrow momentum-arrow--stable" aria-label="Stable acceleration">·</span>';

        // Gauge fill: map velocity magnitude to 0-100%
        const vMag = Math.min(1, Math.abs(v) / 1.2);
        const fillColor = vLabel === 'falling' ? '#f85149' : color;

        return `
        <div class="momentum-col" style="--col-color:${color}">
            <div class="momentum-label">${shortLabel}</div>
            <div class="momentum-gauge-wrap">
                <div class="momentum-gauge-bg">
                    <div class="momentum-gauge-fill" style="height:${(vMag*100).toFixed(1)}%; background:${fillColor}; box-shadow:0 0 8px ${fillColor}55;"></div>
                </div>
                <div class="momentum-arrows">
                    <div class="momentum-v">${vIcon}</div>
                    <div class="momentum-a">${aIcon}</div>
                </div>
            </div>
            <div class="momentum-values">
                <span class="momentum-v-val" title="Velocity (dI/dt)">V: ${v >= 0 ? '+' : ''}${v.toFixed(2)}</span>
                <span class="momentum-a-val" title="Acceleration (d²I/dt²)">A: ${a >= 0 ? '+' : ''}${a.toFixed(3)}</span>
            </div>
        </div>`;
    }).join('');

    return `<div class="momentum-grid">${cols}</div>`;
}

// ── Module C: Verified Source Evidence Stream ──────────────────────────────────

type EvidenceStreamItem = {
    alert_id: string;
    topic: string;
    source_name: string;
    title: string;
    confidence_score: number;
    url?: string | null;
    triggered_at?: string | null;
    evidence_list?: any[];
};

export function renderEvidenceStream(items: EvidenceStreamItem[]): string {
    if (!items || items.length === 0) {
        return `<p class="mp-module-empty">Monitoring OSINT anchor signals — no correlated evidence in current window.</p>`;
    }

    const cards = items.map((item, idx) => {
        const color = getTopicColor(normalizeTopicCode(item.topic));
        const def = getTopicDef(item.topic || null);
        const score = item.confidence_score ?? 0;
        const scoreClass = score >= 0.75 ? 'ev-score--high' : score >= 0.45 ? 'ev-score--mid' : 'ev-score--low';
        const truncTitle = item.title.length > 90 ? item.title.slice(0, 87) + '…' : item.title;
        const sourceDisplay = item.source_name.toUpperCase();

        // Encode evidence_list to a data attribute (JSON, single-quoted safely via base64 is risky;
        // we store the index and let the click delegate look it up from the live items array)
        return `
        <div class="evidence-card"
             data-ev-index="${idx}"
             data-ev-alert-id="${escAttrInline(item.alert_id)}"
             data-ev-title="${escAttrInline(truncTitle)}"
             style="--ev-color:${color}; border-left-color:${color};"
             role="button"
             tabindex="0"
             aria-label="View source evidence: ${escAttrInline(truncTitle)}">
            <div class="ev-source">${escHtmlInline(sourceDisplay)}</div>
            <div class="ev-title">${escHtmlInline(truncTitle)}</div>
            <div class="ev-footer">
                <span class="ev-sector" style="color:${color}">${def.icon} ${def.label}</span>
                <span class="ev-score ${scoreClass}">CF: ${(score * 100).toFixed(0)}%</span>
            </div>
        </div>`;
    }).join('');

    return `
    <div class="evidence-stream-wrap">
        <div class="evidence-ticker" id="mp-evidence-ticker">
            <div class="evidence-track">
                ${cards}
                ${cards}<!-- Duplicate for seamless loop -->
            </div>
        </div>
    </div>`;
}

function escHtmlInline(s: string): string {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function escAttrInline(s: string): string {
    return escHtmlInline(s).replace(/'/g, '&#39;');
}
