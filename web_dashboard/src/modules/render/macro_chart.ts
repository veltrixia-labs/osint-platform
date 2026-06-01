import ApexCharts from 'apexcharts';
import {
    fetchMacroTransmission,
    fetchMacroTransmissionOptions,
    type MacroTransmissionData,
    type MacroTransmissionMacroOption,
    type MacroTransmissionTopicOption,
    type MacroTransmissionOptions,
} from '../api';

/**
 * Macro Transmission Card — Dynamic Macro Selector (Hypothesis Testing Engine)
 * ---------------------------------------------------------------------------
 * Two glassmorphic <select> dropdowns let the analyst pair any tradeable macro
 * series (WTI, DGS10, VIX, Copper, USD Index) with any strategic topic. The
 * card re-fetches and re-renders dual-axis chart + metrics + evidence modal on
 * every selection change. Colours track the selected topic's domain accent.
 */

const STYLE_ID = 'macro-tx-card-styles';

interface MacroPreset {
    id: string;
    label: string;
    macro: string;
    topic: string;
    includeInverse?: boolean;
}

const MACRO_PRESETS: MacroPreset[] = [
    { id: 'rates_x_tech',     label: 'Rates × Tech',     macro: 'DGS10',      topic: 'ai_semiconductor_intelligence' },
    { id: 'oil_x_logistics',  label: 'Oil × Logistics',  macro: 'DCOILWTICO', topic: 'supply_chain_intelligence' },
    { id: 'fear_x_crypto',    label: 'Fear × Crypto',    macro: 'VIXCLS',     topic: 'crypto_geopolitics' },
];

/** Custom event dispatched by macro_matrix.ts when a cell is clicked. */
export const MACRO_TX_SELECT_EVENT = 'macro-tx-select';

interface LagDescription {
    headline: string;
    detail: string;
    direction: 'lead' | 'follow' | 'sync';
}

interface ChartState {
    includeInverse: boolean;
    source: string;
    targetTopic: string;
    chartInstance: ApexCharts | null;
    lastData: MacroTransmissionData | null;
    options: MacroTransmissionOptions | null;
}

type PersistedChartSelection = Pick<ChartState, 'includeInverse' | 'source' | 'targetTopic'>;

let persistedSelection: PersistedChartSelection | null = null;
let activeCard: HTMLElement | null = null;
let activeState: ChartState | null = null;

function optionExists(
    options: MacroTransmissionOptions,
    kind: 'macro' | 'topic',
    id: string,
): boolean {
    const rows = kind === 'macro' ? options.macro_series : options.target_topics;
    return rows.some((row) => row.id === id);
}

function resolveInitialSelection(options: MacroTransmissionOptions): PersistedChartSelection {
    const saved = persistedSelection;
    return {
        includeInverse: saved?.includeInverse ?? false,
        source:
            saved?.source && optionExists(options, 'macro', saved.source)
                ? saved.source
                : options.defaults.macro_ticker,
        targetTopic:
            saved?.targetTopic && optionExists(options, 'topic', saved.targetTopic)
                ? saved.targetTopic
                : options.defaults.target_topic,
    };
}

function persistSelection(state: ChartState): void {
    persistedSelection = {
        includeInverse: state.includeInverse,
        source: state.source,
        targetTopic: state.targetTopic,
    };
}

function findMacro(opts: MacroTransmissionOptions | null, id: string): MacroTransmissionMacroOption | undefined {
    return opts?.macro_series.find((m) => m.id === id);
}

function findTopic(opts: MacroTransmissionOptions | null, id: string): MacroTransmissionTopicOption | undefined {
    return opts?.target_topics.find((t) => t.id === id);
}

function describeLag(data: MacroTransmissionData, opts: MacroTransmissionOptions | null): LagDescription {
    const sourceLabel = findMacro(opts, data.source)?.label ?? data.source;
    const targetLabel = findTopic(opts, data.target)?.label ?? data.target;
    const lag = data.lag_days;
    if (lag > 0) {
        return {
            headline: `${sourceLabel} leads ${targetLabel}`,
            detail: `Macro signal precedes the topic by ${lag} day${lag === 1 ? '' : 's'}.`,
            direction: 'lead',
        };
    }
    if (lag < 0) {
        const n = Math.abs(lag);
        return {
            headline: `${targetLabel} leads ${sourceLabel}`,
            detail: `Topic intensity precedes the macro asset by ${n} day${n === 1 ? '' : 's'} (inverse transmission).`,
            direction: 'follow',
        };
    }
    return {
        headline: 'Simultaneous transmission',
        detail: 'Peak correlation occurs at lag = 0 — no detectable lead/lag relationship.',
        direction: 'sync',
    };
}

function formatCorrelation(r: number): string {
    const sign = r > 0 ? '+' : '';
    return `${sign}${r.toFixed(3)}`;
}

function correlationStrengthLabel(r: number): string {
    const a = Math.abs(r);
    if (a >= 0.7) return 'Strong';
    if (a >= 0.4) return 'Moderate';
    if (a >= 0.2) return 'Weak';
    return 'Negligible';
}

function escAttr(s: string): string {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function injectStyles(): void {
    if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
        .macro-tx-card {
            position: relative;
            display: flex;
            flex-direction: column;
            gap: 16px;
            padding: 18px 20px 16px;
            border-radius: 14px;
            background: linear-gradient(160deg, rgba(15, 23, 42, 0.55), rgba(15, 23, 42, 0.25));
            border: 1px solid var(--macro-tx-accent-border, rgba(125, 211, 252, 0.18));
            backdrop-filter: blur(18px) saturate(140%);
            -webkit-backdrop-filter: blur(18px) saturate(140%);
            box-shadow:
                0 8px 28px rgba(2, 6, 23, 0.45),
                inset 0 0 0 1px rgba(255, 255, 255, 0.03),
                0 0 24px var(--macro-tx-accent-glow, rgba(56,189,248,0.0));
            color: #cbd5e1;
            transition: border-color 0.30s ease, box-shadow 0.30s ease;
        }
        .macro-tx-header {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            align-items: flex-start;
            justify-content: space-between;
        }
        .macro-tx-title h3 {
            margin: 0;
            font-size: 0.95rem;
            font-weight: 700;
            color: #e2e8f0;
            letter-spacing: 0.01em;
        }
        .macro-tx-subtitle {
            margin-top: 6px;
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        .macro-tx-selector {
            position: relative;
            display: inline-flex;
            align-items: center;
        }
        .macro-tx-selector::after {
            /* custom chevron */
            content: '▾';
            position: absolute;
            right: 10px;
            top: 50%;
            transform: translateY(-50%);
            pointer-events: none;
            color: #94a3b8;
            font-size: 0.70rem;
        }
        .macro-tx-selector select {
            appearance: none;
            -webkit-appearance: none;
            -moz-appearance: none;
            background: linear-gradient(135deg, rgba(2,6,23,0.65), rgba(15,23,42,0.55));
            border: 1px solid rgba(125,211,252,0.28);
            border-radius: 10px;
            color: #e2e8f0;
            font-size: 0.82rem;
            font-weight: 600;
            padding: 7px 28px 7px 12px;
            cursor: pointer;
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            transition: border-color 0.18s ease, box-shadow 0.18s ease;
        }
        .macro-tx-selector select:hover {
            border-color: rgba(125,211,252,0.55);
            box-shadow: 0 0 0 3px rgba(125,211,252,0.08);
        }
        .macro-tx-selector select:focus-visible {
            outline: none;
            border-color: var(--macro-tx-accent-primary, #38bdf8);
            box-shadow: 0 0 0 3px color-mix(in srgb, var(--macro-tx-accent-primary, #38bdf8) 22%, transparent);
        }
        .macro-tx-selector select option {
            background: #0b1220;
            color: #e2e8f0;
        }
        .macro-tx-arrow {
            color: #64748b;
            font-size: 0.9rem;
            font-weight: 700;
            text-shadow: 0 0 8px var(--macro-tx-accent-glow, transparent);
        }

        /* === Preset pills (quick-select row) ============================= */
        .macro-tx-presets {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 8px;
            align-items: center;
        }
        .macro-tx-presets-label {
            font-size: 0.62rem;
            font-weight: 700;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.10em;
            margin-right: 4px;
        }
        .macro-tx-preset {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 4px 11px;
            border-radius: 999px;
            font-size: 0.74rem;
            font-weight: 600;
            color: #cbd5e1;
            background: linear-gradient(135deg, rgba(2,6,23,0.55), rgba(15,23,42,0.45));
            border: 1px solid rgba(148,163,184,0.20);
            cursor: pointer;
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            transition: transform 0.12s ease, border-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
            user-select: none;
        }
        .macro-tx-preset:hover {
            transform: translateY(-1px);
            color: #e2e8f0;
            border-color: rgba(125,211,252,0.55);
            box-shadow: 0 4px 14px rgba(56,189,248,0.18);
        }
        .macro-tx-preset.active {
            color: #ffffff;
            background: linear-gradient(135deg,
                color-mix(in srgb, var(--macro-tx-accent-primary, #38bdf8) 38%, rgba(2,6,23,0.55)),
                color-mix(in srgb, var(--macro-tx-accent-primary, #38bdf8) 22%, rgba(15,23,42,0.45)));
            border-color: var(--macro-tx-accent-primary, #38bdf8);
            box-shadow: 0 0 0 1px var(--macro-tx-accent-primary, #38bdf8),
                        0 0 14px var(--macro-tx-accent-glow, rgba(56,189,248,0.30));
        }
        .macro-tx-preset:focus-visible {
            outline: none;
            box-shadow: 0 0 0 3px color-mix(in srgb, var(--macro-tx-accent-primary, #38bdf8) 28%, transparent);
        }

        .macro-tx-controls {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .macro-tx-toggle {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-size: 0.78rem;
            color: #cbd5e1;
            cursor: pointer;
            user-select: none;
            padding: 6px 10px;
            border-radius: 8px;
            background: rgba(15, 23, 42, 0.45);
            border: 1px solid rgba(148, 163, 184, 0.18);
        }
        .macro-tx-toggle input { accent-color: var(--macro-tx-accent-primary, #38bdf8); cursor: pointer; }
        .macro-tx-btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            border-radius: 8px;
            font-size: 0.78rem;
            font-weight: 600;
            color: #e0f2fe;
            background: linear-gradient(135deg, rgba(56, 189, 248, 0.20), rgba(99, 102, 241, 0.18));
            border: 1px solid rgba(125, 211, 252, 0.45);
            cursor: pointer;
            transition: transform 0.12s ease, box-shadow 0.12s ease;
        }
        .macro-tx-btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 14px var(--macro-tx-accent-glow, rgba(56,189,248,0.22));
        }
        .macro-tx-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 10px;
        }
        .macro-tx-metric {
            display: flex;
            flex-direction: column;
            gap: 4px;
            padding: 10px 12px;
            border-radius: 10px;
            background: rgba(2, 6, 23, 0.45);
            border: 1px solid rgba(148, 163, 184, 0.12);
        }
        .macro-tx-metric .label {
            font-size: 0.66rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.10em;
        }
        .macro-tx-metric .value {
            font-size: 0.98rem;
            font-weight: 700;
            color: #e2e8f0;
            font-variant-numeric: tabular-nums;
        }
        .macro-tx-metric .hint {
            font-size: 0.70rem;
            color: #94a3b8;
        }
        .macro-tx-direction-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 3px 8px;
            border-radius: 999px;
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }
        .macro-tx-direction-badge.lead   { background: rgba(234, 179, 8, 0.16);  color: #fde68a; border: 1px solid rgba(234, 179, 8, 0.45); }
        .macro-tx-direction-badge.follow { background: rgba(16, 185, 129, 0.16); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.45); }
        .macro-tx-direction-badge.sync   { background: rgba(148, 163, 184, 0.16); color: #e2e8f0; border: 1px solid rgba(148, 163, 184, 0.45); }
        .macro-tx-chart {
            width: 100%;
            min-height: 350px;
        }
        .macro-tx-status {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 200px;
            font-size: 0.85rem;
            color: #94a3b8;
        }
        .macro-tx-status.error { color: #fca5a5; }

        /* === Evidence modal === */
        .macro-tx-modal-overlay {
            position: fixed;
            inset: 0;
            z-index: 9999;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(2, 6, 23, 0.62);
            backdrop-filter: blur(6px);
            -webkit-backdrop-filter: blur(6px);
            opacity: 0;
            transition: opacity 0.18s ease;
        }
        .macro-tx-modal-overlay.visible { opacity: 1; }
        .macro-tx-modal {
            max-width: 640px;
            width: calc(100% - 32px);
            max-height: 80vh;
            overflow-y: auto;
            padding: 22px 24px;
            border-radius: 16px;
            background: linear-gradient(160deg, rgba(15, 23, 42, 0.96), rgba(2, 6, 23, 0.96));
            border: 1px solid rgba(125, 211, 252, 0.35);
            backdrop-filter: blur(24px) saturate(160%);
            -webkit-backdrop-filter: blur(24px) saturate(160%);
            box-shadow:
                0 20px 60px rgba(2, 6, 23, 0.65),
                inset 0 0 0 1px rgba(255, 255, 255, 0.04);
            color: #cbd5e1;
            transform: translateY(8px);
            transition: transform 0.18s ease;
        }
        .macro-tx-modal-overlay.visible .macro-tx-modal { transform: translateY(0); }
        .macro-tx-modal header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid rgba(148, 163, 184, 0.18);
        }
        .macro-tx-modal h2 {
            margin: 0;
            font-size: 1.0rem;
            color: #e0f2fe;
            font-weight: 700;
        }
        .macro-tx-modal-close {
            background: none;
            border: none;
            color: #94a3b8;
            cursor: pointer;
            font-size: 1.4rem;
            line-height: 1;
            padding: 4px 8px;
        }
        .macro-tx-modal-close:hover { color: #e2e8f0; }
        .macro-tx-modal section { margin-bottom: 16px; }
        .macro-tx-modal section h3 {
            margin: 0 0 6px;
            font-size: 0.78rem;
            color: #7dd3fc;
            text-transform: uppercase;
            letter-spacing: 0.10em;
        }
        .macro-tx-modal section p,
        .macro-tx-modal section li {
            margin: 4px 0;
            font-size: 0.84rem;
            color: #cbd5e1;
            line-height: 1.55;
        }
        .macro-tx-modal .kv {
            display: grid;
            grid-template-columns: 140px 1fr;
            gap: 6px 12px;
            font-size: 0.82rem;
        }
        .macro-tx-modal .kv .k { color: #94a3b8; }
        .macro-tx-modal .kv .v { color: #e2e8f0; font-variant-numeric: tabular-nums; }
    `;
    document.head.appendChild(style);
}

function applyTopicAccent(card: HTMLElement, topic: MacroTransmissionTopicOption | undefined): void {
    const primary = topic?.accent_color || '#38bdf8';
    const glow = topic?.glow_color || 'rgba(56,189,248,0.30)';
    card.style.setProperty('--macro-tx-accent-primary', primary);
    card.style.setProperty('--macro-tx-accent-glow', glow);
    card.style.setProperty('--macro-tx-accent-border', `color-mix(in srgb, ${primary} 38%, rgba(125,211,252,0.18))`);
}

function setStatus(host: HTMLElement, html: string, isError = false): void {
    host.innerHTML = `<div class="macro-tx-status ${isError ? 'error' : ''}">${html}</div>`;
}

function renderEvidenceModal(state: ChartState): void {
    const data = state.lastData;
    const macroOpt = findMacro(state.options, state.source);
    const topicOpt = findTopic(state.options, state.targetTopic);
    const macroDesc = macroOpt?.name || macroOpt?.label || state.source;
    const topicDesc = topicOpt?.description || topicOpt?.label || state.targetTopic;
    const series = data?.series ?? [];
    const dateRange = series.length
        ? `${series[0].date} → ${series[series.length - 1].date}`
        : '—';

    const overlay = document.createElement('div');
    overlay.className = 'macro-tx-modal-overlay';
    overlay.innerHTML = `
        <div class="macro-tx-modal" role="dialog" aria-modal="true" aria-label="Source Evidence">
            <header>
                <h2>Source Evidence & Methodology</h2>
                <button class="macro-tx-modal-close" aria-label="Close">&times;</button>
            </header>

            <section>
                <h3>Macro Series</h3>
                <div class="kv">
                    <span class="k">Series ID</span><span class="v">${escAttr(state.source)}</span>
                    <span class="k">Label</span><span class="v">${escAttr(macroOpt?.label || state.source)}</span>
                    <span class="k">Provider</span><span class="v">${escAttr(macroOpt?.provider || 'FRED')}</span>
                    <span class="k">Unit</span><span class="v">${escAttr(macroOpt?.unit_label || '—')}</span>
                    <span class="k">Frequency</span><span class="v">${escAttr(macroOpt?.frequency || '—')}</span>
                </div>
                <p>${escAttr(macroDesc)}</p>
            </section>

            <section>
                <h3>Target Topic</h3>
                <div class="kv">
                    <span class="k">Topic ID</span><span class="v">${escAttr(state.targetTopic)}</span>
                    <span class="k">Label</span><span class="v">${escAttr(topicOpt?.label || state.targetTopic)}</span>
                </div>
                <p>${escAttr(topicDesc)}</p>
                <p style="color:#94a3b8;">
                    Alert intensity is aggregated as the <em>daily maximum</em> across all
                    AlertLog rows matching this topic, then converted to an N-day rate of
                    change using a floored denominator to avoid 0→k explosion.
                </p>
            </section>

            <section>
                <h3>Methodology</h3>
                <ul>
                    <li><strong>Macro RoC</strong>: log-return over the rolling window (stable for price series).</li>
                    <li><strong>Intensity RoC</strong>: floored ratio with denominator ≥ 1.0 to bound 0-base swings.</li>
                    <li><strong>CCF</strong>: Pearson cross-correlation of z-scored signals, scanned across ±14 day lags.</li>
                    <li><strong>Beta</strong>: covariance / variance at the aligned peak lag.</li>
                    <li>Correlation is clipped to [-1, 1] to guarantee the Pearson bound.</li>
                    <li>Monthly series (e.g. Copper) auto-expand the RoC window to ~30 days and the lookback to ~365 days.</li>
                </ul>
            </section>

            <section>
                <h3>This Result</h3>
                <div class="kv">
                    <span class="k">Lag (days)</span><span class="v">${data?.lag_days ?? '—'}</span>
                    <span class="k">Correlation</span><span class="v">${data ? formatCorrelation(data.correlation) : '—'} (${data ? correlationStrengthLabel(data.correlation) : '—'})</span>
                    <span class="k">Beta</span><span class="v">${data ? data.beta.toFixed(4) : '—'}</span>
                    <span class="k">Sample size</span><span class="v">${series.length} ${data?.resolution === 'monthly' ? 'monthly' : 'daily'} points</span>
                    <span class="k">Resolution</span><span class="v">${escAttr(data?.resolution || 'daily')}</span>
                    <span class="k">RoC window</span><span class="v">${data?.roc_window_days ?? '—'} days</span>
                    <span class="k">Lookback</span><span class="v">${data?.days_lookback ?? '—'} days</span>
                    <span class="k">Date range</span><span class="v">${escAttr(dateRange)}</span>
                    <span class="k">Inverse scan</span><span class="v">${state.includeInverse ? 'enabled (±lag)' : 'forward only (+lag)'}</span>
                </div>
            </section>

            <section>
                <h3>Interpretation Notes</h3>
                <p>
                    A positive lag means the macro asset's move precedes the topic's alert
                    intensity shift; a negative lag (inverse scan only) indicates topic
                    activity leading the macro response. Correlation magnitude under 0.2
                    should be treated as noise.
                </p>
            </section>
        </div>
    `;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('visible'));

    const close = () => {
        overlay.classList.remove('visible');
        setTimeout(() => overlay.remove(), 200);
    };
    overlay.querySelector('.macro-tx-modal-close')?.addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', function onKey(e) {
        if (e.key === 'Escape') {
            close();
            document.removeEventListener('keydown', onKey);
        }
    });
}

function renderMetrics(host: HTMLElement, data: MacroTransmissionData, opts: MacroTransmissionOptions | null): void {
    const lag = describeLag(data, opts);
    const directionClass = lag.direction;
    const directionLabel =
        directionClass === 'lead'   ? 'Macro Leads'
      : directionClass === 'follow' ? 'Target Leads'
      :                                'Simultaneous';

    host.innerHTML = `
        <div class="macro-tx-metric">
            <span class="label">Transmission</span>
            <span class="value">
                <span class="macro-tx-direction-badge ${directionClass}">${directionLabel}</span>
            </span>
            <span class="hint">${escAttr(lag.detail)}</span>
        </div>
        <div class="macro-tx-metric">
            <span class="label">Lag (days)</span>
            <span class="value">${data.lag_days > 0 ? '+' : ''}${data.lag_days}</span>
            <span class="hint">${escAttr(lag.headline)}</span>
        </div>
        <div class="macro-tx-metric">
            <span class="label">Correlation</span>
            <span class="value">${formatCorrelation(data.correlation)}</span>
            <span class="hint">${correlationStrengthLabel(data.correlation)} signal</span>
        </div>
        <div class="macro-tx-metric">
            <span class="label">Beta</span>
            <span class="value">${data.beta.toFixed(3)}</span>
            <span class="hint">Sensitivity at peak lag</span>
        </div>
        <div class="macro-tx-metric">
            <span class="label">Sample</span>
            <span class="value">${data.series.length}</span>
            <span class="hint">${data.resolution === 'monthly' ? 'Monthly obs.' : 'Daily obs.'}</span>
        </div>
    `;
}

function renderChart(host: HTMLElement, data: MacroTransmissionData, state: ChartState): void {
    const macroOpt = findMacro(state.options, data.source);
    const topicOpt = findTopic(state.options, data.target);
    const sourceLabel = macroOpt?.label ?? data.source;
    const targetLabel = topicOpt?.label ?? data.target;
    const lag = describeLag(data, state.options);

    const macroColor = macroOpt?.accent_color || '#eab308';
    const topicColor = topicOpt?.accent_color || '#10b981';

    const dates = data.series.map((s) => s.date);
    const macroValues = data.series.map((s) => s.macro_value);
    const intensityValues = data.series.map((s) => s.intensity);

    const titleText = data.beta !== 0 || data.correlation !== 0
        ? `${lag.headline} — corr ${formatCorrelation(data.correlation)} · β ${data.beta.toFixed(2)}`
        : `${sourceLabel} — awaiting sufficient ${targetLabel} alerts for CCF`;

    const options = {
        series: [
            { name: `${sourceLabel}${lag.direction === 'lead' ? ' (Lead)' : lag.direction === 'follow' ? ' (Lag)' : ''}`, type: 'line', data: macroValues },
            { name: `${targetLabel} Intensity${lag.direction === 'follow' ? ' (Lead)' : lag.direction === 'lead' ? ' (Lag)' : ''}`, type: 'area', data: intensityValues },
        ],
        chart: {
            height: 350,
            type: 'line' as const,
            background: 'transparent',
            toolbar: { show: false },
            zoom: { enabled: false },
            animations: { enabled: true, easing: 'easeinout' as const, speed: 300 },
        },
        theme: { mode: 'dark' as const },
        colors: [macroColor, topicColor],
        stroke: { width: [3, 0], curve: 'smooth' as const },
        fill: {
            type: ['solid', 'gradient'],
            gradient: { shadeIntensity: 1, inverseColors: false, opacityFrom: 0.50, opacityTo: 0.05, stops: [20, 100] },
        },
        title: {
            text: titleText,
            align: 'left' as const,
            style: { fontSize: '13px', fontWeight: 600, color: '#94a3b8' },
        },
        xaxis: {
            categories: dates,
            type: 'datetime' as const,
            labels: { style: { colors: '#64748b' } },
            axisBorder: { show: false },
            axisTicks: { show: false },
        },
        yaxis: [
            { title: { text: macroOpt?.unit_label ?? sourceLabel, style: { color: macroColor } }, labels: { style: { colors: macroColor }, formatter: (v: number) => v.toFixed(2) } },
            { opposite: true, title: { text: 'Risk Intensity', style: { color: topicColor } }, labels: { style: { colors: topicColor }, formatter: (v: number) => v.toFixed(1) } },
        ],
        grid: { borderColor: 'rgba(255,255,255,0.05)', strokeDashArray: 4, xaxis: { lines: { show: true } }, yaxis: { lines: { show: true } } },
        tooltip: { shared: true, intersect: false, theme: 'dark' as const },
        legend: { position: 'top' as const, horizontalAlign: 'right' as const, offsetY: -10 },
    };

    if (state.chartInstance) {
        state.chartInstance.destroy();
    }
    state.chartInstance = new ApexCharts(host, options);
    state.chartInstance.render();
}

async function loadAndRender(card: HTMLElement, state: ChartState): Promise<void> {
    const chartHost = card.querySelector<HTMLElement>('.macro-tx-chart');
    const metricsHost = card.querySelector<HTMLElement>('.macro-tx-metrics');
    if (!chartHost || !metricsHost) return;

    // Apply the topic accent immediately so the card glow tracks the selector
    // even while the data is still loading.
    applyTopicAccent(card, findTopic(state.options, state.targetTopic));

    setStatus(chartHost, '<span class="animate-pulse">Loading transmission data…</span>');
    metricsHost.innerHTML = '';

    try {
        const data = await fetchMacroTransmission(state.source, state.targetTopic, state.includeInverse);
        if (!data || data.series.length === 0) {
            setStatus(chartHost, 'Insufficient data for transmission analysis.');
            return;
        }
        state.lastData = data;
        chartHost.innerHTML = '';
        renderMetrics(metricsHost, data, state.options);
        renderChart(chartHost, data, state);
    } catch (err) {
        console.error('Failed to render macro transmission chart:', err);
        setStatus(chartHost, 'Error loading transmission data.', true);
    }
}

export async function refreshMacroTransmissionChart(): Promise<void> {
    if (!activeCard || !activeState) return;
    if (!document.body.contains(activeCard)) return;
    await loadAndRender(activeCard, activeState);
}

function renderPresetPills(state: ChartState): string {
    const pills = MACRO_PRESETS.map((p) => {
        const active = p.macro === state.source && p.topic === state.targetTopic;
        return `<button
            type="button"
            class="macro-tx-preset${active ? ' active' : ''}"
            data-role="preset"
            data-preset-id="${escAttr(p.id)}"
            data-macro="${escAttr(p.macro)}"
            data-topic="${escAttr(p.topic)}"
            title="Load ${escAttr(p.label)} preset"
            aria-pressed="${active ? 'true' : 'false'}"
        >${escAttr(p.label)}</button>`;
    }).join('');
    return `
        <div class="macro-tx-presets" role="group" aria-label="Macro transmission presets">
            <span class="macro-tx-presets-label">Templates</span>
            ${pills}
        </div>
    `;
}

function syncPresetActiveStates(card: HTMLElement, state: ChartState): void {
    card.querySelectorAll<HTMLElement>('.macro-tx-preset').forEach((el) => {
        const m = el.dataset.macro || '';
        const t = el.dataset.topic || '';
        const isActive = m === state.source && t === state.targetTopic;
        el.classList.toggle('active', isActive);
        el.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
}

function syncSelectorsToState(card: HTMLElement, state: ChartState): void {
    const macroSelect = card.querySelector<HTMLSelectElement>('select[data-role="macro-select"]');
    if (macroSelect && macroSelect.value !== state.source) macroSelect.value = state.source;
    const topicSelect = card.querySelector<HTMLSelectElement>('select[data-role="topic-select"]');
    if (topicSelect && topicSelect.value !== state.targetTopic) topicSelect.value = state.targetTopic;
}

function renderSelectors(state: ChartState): string {
    const opts = state.options!;
    const macroOptionsHtml = opts.macro_series
        .map((m) => `<option value="${escAttr(m.id)}"${m.id === state.source ? ' selected' : ''}>${escAttr(m.label)}${m.frequency === 'monthly' ? ' · monthly' : ''}</option>`)
        .join('');
    const topicOptionsHtml = opts.target_topics
        .map((t) => `<option value="${escAttr(t.id)}"${t.id === state.targetTopic ? ' selected' : ''}>${escAttr(t.label)}</option>`)
        .join('');
    return `
        <span class="macro-tx-selector" title="Macro lead series">
            <select data-role="macro-select" aria-label="Macro lead series">${macroOptionsHtml}</select>
        </span>
        <span class="macro-tx-arrow">→</span>
        <span class="macro-tx-selector" title="Sector lag topic">
            <select data-role="topic-select" aria-label="Sector lag topic">${topicOptionsHtml}</select>
        </span>
    `;
}

export async function renderMacroTransmissionChart(containerId: string): Promise<void> {
    const container = document.getElementById(containerId);
    if (!container) return;

    injectStyles();

    container.innerHTML = `
        <div class="macro-tx-card" data-component="macro-transmission">
            <div class="macro-tx-status">Loading macro selector options…</div>
        </div>
    `;
    const card = container.querySelector<HTMLElement>('.macro-tx-card');
    if (!card) return;

    // Resolve options (with cached/hardcoded fallback) before painting the shell.
    const options = await fetchMacroTransmissionOptions();
    const initialSelection = resolveInitialSelection(options);
    const state: ChartState = {
        ...initialSelection,
        chartInstance: null,
        lastData: null,
        options,
    };
    persistSelection(state);

    card.innerHTML = `
        <div class="macro-tx-header">
            <div class="macro-tx-title">
                <h3>Dynamic Macro Transmission</h3>
                <div class="macro-tx-subtitle">${renderSelectors(state)}</div>
                ${renderPresetPills(state)}
            </div>
            <div class="macro-tx-controls">
                <label class="macro-tx-toggle" title="Also scan negative lags (target leads macro)">
                    <input type="checkbox" data-role="include-inverse" />
                    <span>Scan inverse lags</span>
                </label>
                <button class="macro-tx-btn" data-role="evidence" type="button">
                    <span>🔍</span> Source Evidence
                </button>
            </div>
        </div>
        <div class="macro-tx-metrics"></div>
        <div class="macro-tx-chart"></div>
    `;

    const macroSelect = card.querySelector<HTMLSelectElement>('select[data-role="macro-select"]');
    macroSelect?.addEventListener('change', () => {
        if (!macroSelect.value) return;
        state.source = macroSelect.value;
        persistSelection(state);
        syncPresetActiveStates(card, state);
        void loadAndRender(card, state);
    });

    const topicSelect = card.querySelector<HTMLSelectElement>('select[data-role="topic-select"]');
    topicSelect?.addEventListener('change', () => {
        if (!topicSelect.value) return;
        state.targetTopic = topicSelect.value;
        persistSelection(state);
        syncPresetActiveStates(card, state);
        void loadAndRender(card, state);
    });

    const inverseToggle = card.querySelector<HTMLInputElement>('input[data-role="include-inverse"]');
    if (inverseToggle) inverseToggle.checked = state.includeInverse;
    inverseToggle?.addEventListener('change', () => {
        state.includeInverse = !!inverseToggle.checked;
        persistSelection(state);
        void loadAndRender(card, state);
    });

    const evidenceBtn = card.querySelector<HTMLButtonElement>('button[data-role="evidence"]');
    evidenceBtn?.addEventListener('click', () => renderEvidenceModal(state));

    // Preset pills — instant macro/topic swap.
    card.querySelectorAll<HTMLButtonElement>('button[data-role="preset"]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const macro = btn.dataset.macro || '';
            const topic = btn.dataset.topic || '';
            if (!macro || !topic) return;
            applySelection(card, state, macro, topic);
        });
    });

    // External selection (e.g. from the Macro Influence Heatmap) routed
    // through a global CustomEvent so the components stay decoupled.
    const externalSelectHandler = (ev: Event) => {
        const detail = (ev as CustomEvent<{ macro?: string; topic?: string }>).detail || {};
        if (!detail.macro && !detail.topic) return;
        const nextMacro = detail.macro && state.options && optionExists(state.options, 'macro', detail.macro)
            ? detail.macro : state.source;
        const nextTopic = detail.topic && state.options && optionExists(state.options, 'topic', detail.topic)
            ? detail.topic : state.targetTopic;
        applySelection(card, state, nextMacro, nextTopic);
    };
    window.addEventListener(MACRO_TX_SELECT_EVENT, externalSelectHandler);
    // Clean up the listener when the card is removed from the DOM.
    const cleanupObserver = new MutationObserver(() => {
        if (!document.body.contains(card)) {
            window.removeEventListener(MACRO_TX_SELECT_EVENT, externalSelectHandler);
            cleanupObserver.disconnect();
        }
    });
    cleanupObserver.observe(document.body, { childList: true, subtree: true });

    activeCard = card;
    activeState = state;
    await loadAndRender(card, state);
}

function applySelection(card: HTMLElement, state: ChartState, macro: string, topic: string): void {
    if (macro === state.source && topic === state.targetTopic) {
        return; // no-op
    }
    state.source = macro;
    state.targetTopic = topic;
    persistSelection(state);
    syncSelectorsToState(card, state);
    syncPresetActiveStates(card, state);
    void loadAndRender(card, state);
}
