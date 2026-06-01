/**
 * Hidden Accumulation List
 * ========================
 *
 * Renders findings from `analysis/price_osint_divergence.py` — situations
 * where OSINT intensity surged ≥1.5x in a 24h cluster while the macro asset
 * price stayed flat or rose. When CFTC commercial positioning confirms
 * accumulation, the row is highlighted as "🔒 Confirmed Accumulation".
 *
 * Always shows the engine's enforced guardrails (24h cluster, 1.5x reignite)
 * in the header so analysts know the result is institutional-grade.
 */
import { fetchHiddenAccumulation, type HiddenAccumulation, type HiddenAccumulationFinding } from '../api';

const STYLE_ID = 'hidden-accumulation-styles';
let activeContainerId: string | null = null;

const MACRO_LABELS: Record<string, string> = {
    DCOILWTICO: 'WTI Crude Oil',
    DGS10:      'US 10Y Yield',
    VIXCLS:     'VIX',
    PCOPPUSDM:  'Copper',
    DTWEXBGS:   'USD Index',
};
const TOPIC_LABELS: Record<string, string> = {
    energy_resource_risk:          'Energy & Resource',
    global_market_intelligence:    'Global Market',
    crypto_geopolitics:            'Crypto Geopolitics',
    ai_semiconductor_intelligence: 'AI / Semiconductor',
    defense_technology:            'Defense Technology',
    supply_chain_intelligence:     'Supply Chain',
};

function escAttr(s: string): string {
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function injectStyles(): void {
    if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
        .hac-card {
            display: flex;
            flex-direction: column;
            gap: 14px;
            padding: 18px 20px 16px;
            border-radius: 14px;
            background: linear-gradient(160deg, rgba(15,23,42,0.55), rgba(15,23,42,0.25));
            border: 1px solid rgba(125,211,252,0.18);
            backdrop-filter: blur(18px) saturate(140%);
            -webkit-backdrop-filter: blur(18px) saturate(140%);
            box-shadow:
                0 8px 28px rgba(2,6,23,0.45),
                inset 0 0 0 1px rgba(255,255,255,0.03);
            color: #cbd5e1;
        }
        .hac-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 12px;
            flex-wrap: wrap;
        }
        .hac-header h3 {
            margin: 0;
            font-size: 0.95rem;
            font-weight: 700;
            color: #e2e8f0;
        }
        .hac-subtitle {
            font-size: 0.72rem;
            color: #94a3b8;
        }
        .hac-guardrails {
            display: inline-flex;
            gap: 8px;
            font-size: 0.62rem;
            color: #cbd5e1;
        }
        .hac-pill {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 3px 8px;
            background: rgba(2,6,23,0.55);
            border: 1px solid rgba(125,211,252,0.45);
            border-radius: 999px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 700;
            color: #bae6fd;
            font-variant-numeric: tabular-nums;
        }

        .hac-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .hac-row {
            display: grid;
            grid-template-columns: 200px 1fr auto;
            gap: 12px;
            padding: 12px 14px;
            border-radius: 12px;
            background: rgba(2,6,23,0.50);
            border: 1px solid rgba(148,163,184,0.16);
            position: relative;
            overflow: hidden;
        }
        .hac-row::before {
            content: '';
            position: absolute;
            left: 0; top: 0; bottom: 0;
            width: 3px;
            background: var(--hac-accent, #38bdf8);
        }
        @media (max-width: 880px) {
            .hac-row { grid-template-columns: 1fr; }
        }

        .hac-row-pair {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .hac-row-pair .macro {
            font-size: 0.78rem;
            font-weight: 700;
            color: #e2e8f0;
        }
        .hac-row-pair .arrow {
            color: #64748b;
        }
        .hac-row-pair .topic {
            font-size: 0.72rem;
            color: #94a3b8;
        }
        .hac-row-pair .window {
            font-size: 0.62rem;
            color: #64748b;
            margin-top: 2px;
            font-variant-numeric: tabular-nums;
        }

        .hac-row-rationale {
            font-size: 0.78rem;
            color: #cbd5e1;
            line-height: 1.55;
        }
        .hac-row-metrics {
            display: flex;
            gap: 6px;
            margin-top: 8px;
            flex-wrap: wrap;
        }
        .hac-metric {
            padding: 4px 10px;
            border-radius: 6px;
            background: rgba(148,163,184,0.10);
            border: 1px solid rgba(148,163,184,0.18);
            font-size: 0.68rem;
            color: #cbd5e1;
            font-variant-numeric: tabular-nums;
        }
        .hac-metric .k { color: #64748b; margin-right: 4px; }
        .hac-metric.up   { background: rgba(16,185,129,0.10); border-color: rgba(16,185,129,0.40); color: #6ee7b7; }
        .hac-metric.down { background: rgba(248,113,113,0.10); border-color: rgba(248,113,113,0.40); color: #fca5a5; }

        .hac-verdict {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            justify-content: center;
            gap: 4px;
            min-width: 160px;
        }
        .hac-verdict-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 0.66rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #ffffff;
            background: var(--hac-verdict-bg, rgba(148,163,184,0.30));
            border: 1px solid var(--hac-verdict-border, rgba(148,163,184,0.55));
        }
        .hac-verdict-cot {
            font-size: 0.68rem;
            color: #94a3b8;
            text-align: right;
            font-variant-numeric: tabular-nums;
        }
        .hac-verdict-cot .delta.up   { color: #6ee7b7; font-weight: 700; }
        .hac-verdict-cot .delta.down { color: #fca5a5; font-weight: 700; }
        .hac-verdict-cot .delta.flat { color: #cbd5e1; font-weight: 700; }

        .hac-empty {
            padding: 16px;
            border-radius: 10px;
            background: rgba(2,6,23,0.45);
            border: 1px dashed rgba(148,163,184,0.25);
            color: #94a3b8;
            font-size: 0.82rem;
            line-height: 1.55;
            text-align: center;
        }

        .hac-inspected {
            margin-top: 8px;
            padding: 10px 12px;
            border-radius: 10px;
            background: rgba(2,6,23,0.42);
            border: 1px solid rgba(148,163,184,0.14);
        }
        .hac-inspected-title {
            font-size: 0.62rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 6px;
        }
        .hac-inspected-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 6px;
            font-size: 0.68rem;
            color: #94a3b8;
            font-variant-numeric: tabular-nums;
        }
        .hac-inspected-cell {
            display: flex;
            justify-content: space-between;
            padding: 4px 6px;
            background: rgba(15,23,42,0.45);
            border-radius: 4px;
            border: 1px solid rgba(148,163,184,0.10);
        }
        .hac-inspected-cell .name { color: #cbd5e1; font-weight: 600; }

        .hac-status {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100px;
            font-size: 0.85rem;
            color: #94a3b8;
        }
        .hac-status.error { color: #fca5a5; }
    `;
    document.head.appendChild(style);
}

function verdictStyle(accent: string): string {
    return `--hac-verdict-bg: color-mix(in srgb, ${accent} 28%, rgba(2,6,23,0.55));
            --hac-verdict-border: color-mix(in srgb, ${accent} 65%, rgba(148,163,184,0.40));`;
}

function renderRow(finding: HiddenAccumulationFinding): string {
    const macroLabel = MACRO_LABELS[finding.macro_ticker] ?? finding.macro_ticker;
    const topicLabel = TOPIC_LABELS[finding.topic] ?? finding.topic;
    const accent = finding.verdict.accent_color;
    const winStart = new Date(finding.window_start);
    const winEnd = new Date(finding.window_end);
    const winLabel = isNaN(winStart.getTime())
        ? finding.window_start
        : `${winStart.toLocaleString()} → ${winEnd.toLocaleTimeString()}`;
    const priceUp = finding.price_change_pct_24h >= 0;

    const cotBlock = finding.cot_overlay
        ? (() => {
              const c = finding.cot_overlay!;
              const dir = c.accumulation_direction;
              const delta = c.comm_net_delta_contracts;
              const sign = delta > 0 ? '+' : '';
              const reportDate = c.latest_report_date ? new Date(c.latest_report_date).toLocaleDateString() : 'n/a';
              return `<div class="hac-verdict-cot">
                  <div>Comm net Δ <span class="delta ${dir === 'buying' ? 'up' : dir === 'selling' ? 'down' : 'flat'}">${sign}${delta.toLocaleString()}</span> contracts</div>
                  <div>CFTC ${escAttr(reportDate)}</div>
              </div>`;
          })()
        : `<div class="hac-verdict-cot" style="font-style:italic;">No CFTC overlay</div>`;

    return `<div class="hac-row" style="--hac-accent:${escAttr(accent)};">
        <div class="hac-row-pair">
            <div class="macro">${escAttr(macroLabel)} <span class="arrow">→</span></div>
            <div class="topic">${escAttr(topicLabel)}</div>
            <div class="window">${escAttr(winLabel)}</div>
        </div>
        <div>
            <div class="hac-row-rationale">${escAttr(finding.verdict.rationale)}</div>
            <div class="hac-row-metrics">
                <span class="hac-metric"><span class="k">Intensity Δ</span>×${finding.intensity_ratio.toFixed(2)}</span>
                <span class="hac-metric"><span class="k">Peak I</span>${finding.current_peak_intensity.toFixed(1)}</span>
                <span class="hac-metric"><span class="k">Baseline I</span>${finding.baseline_peak_intensity.toFixed(1)}</span>
                <span class="hac-metric ${priceUp ? 'up' : 'down'}"><span class="k">Price 24h</span>${finding.price_change_pct_24h >= 0 ? '+' : ''}${finding.price_change_pct_24h.toFixed(2)}%</span>
            </div>
        </div>
        <div class="hac-verdict">
            <span class="hac-verdict-badge" style="${verdictStyle(accent)}">
                ${escAttr(finding.verdict.emoji)} ${escAttr(finding.verdict.label)}
            </span>
            ${cotBlock}
        </div>
    </div>`;
}

function renderInspected(data: HiddenAccumulation): string {
    if (!data.inspected_pairs.length) return '';
    const cells = data.inspected_pairs.map((p) => {
        const macroLabel = MACRO_LABELS[p.macro_ticker] ?? p.macro_ticker;
        const ratio = p.baseline_peak_intensity > 0
            ? (p.current_peak_intensity / p.baseline_peak_intensity)
            : 0;
        const ratioStr = isFinite(ratio) ? `×${ratio.toFixed(2)}` : '—';
        const priceStr = p.price_change_pct_24h == null
            ? 'no price'
            : `${p.price_change_pct_24h >= 0 ? '+' : ''}${p.price_change_pct_24h.toFixed(2)}%`;
        return `<div class="hac-inspected-cell">
            <span class="name">${escAttr(macroLabel)}</span>
            <span>${ratioStr} · ${priceStr}</span>
        </div>`;
    }).join('');
    return `<div class="hac-inspected">
        <div class="hac-inspected-title">Inspected pairs (no divergence triggered)</div>
        <div class="hac-inspected-grid">${cells}</div>
    </div>`;
}

function setStatus(card: HTMLElement, html: string, isError = false): void {
    card.innerHTML = `<div class="hac-status ${isError ? 'error' : ''}">${html}</div>`;
}

async function loadAndPaint(card: HTMLElement): Promise<void> {
    setStatus(card, '<span class="animate-pulse">Detecting price-OSINT divergences…</span>');
    const data = await fetchHiddenAccumulation();
    if (!data) {
        setStatus(card, 'Hidden accumulation endpoint unavailable.', true);
        return;
    }

    const ts = new Date(data.generated_at);
    const tsLabel = isNaN(ts.getTime()) ? data.generated_at : ts.toLocaleTimeString();

    const findingsHtml = data.findings.length
        ? `<div class="hac-list">${data.findings.map(renderRow).join('')}</div>`
        : `<div class="hac-empty">
            No active divergences in the current ${data.cluster_window_hours}h window.
            Engine requires intensity ≥ ${data.reignite_factor}× of the prior cluster's peak
            (baseline floor ${data.min_baseline_intensity}) AND price flat or up.
          </div>`;

    card.innerHTML = `
        <div class="hac-header">
            <div>
                <h3>Hidden Accumulation Screener</h3>
                <div class="hac-subtitle">Price-OSINT divergence with live CFTC Commitments-of-Traders overlay.</div>
            </div>
            <div style="display:flex; flex-direction:column; gap:4px; align-items:flex-end;">
                <div class="hac-guardrails">
                    <span class="hac-pill">⏱ ${data.cluster_window_hours}h cluster</span>
                    <span class="hac-pill">📈 ≥ ${data.reignite_factor}× reignite</span>
                    <span class="hac-pill">⚓ baseline ≥ ${data.min_baseline_intensity}</span>
                </div>
                <div style="font-size:0.62rem; color:#64748b; font-variant-numeric:tabular-nums;">
                    ${data.findings.length} finding${data.findings.length === 1 ? '' : 's'} · ${data.inspected_pairs.length} pairs inspected · ${tsLabel}
                </div>
            </div>
        </div>
        ${findingsHtml}
        ${renderInspected(data)}
    `;
}

export async function renderHiddenAccumulation(containerId: string): Promise<void> {
    const container = document.getElementById(containerId);
    if (!container) return;
    injectStyles();
    container.innerHTML = `<div class="hac-card" id="${containerId}-card"></div>`;
    const card = container.querySelector<HTMLElement>(`#${CSS.escape(containerId)}-card`);
    if (!card) return;
    activeContainerId = containerId;
    await loadAndPaint(card);
}

export async function refreshHiddenAccumulation(): Promise<void> {
    if (!activeContainerId) return;
    const container = document.getElementById(activeContainerId);
    if (!container) return;
    const card = container.querySelector<HTMLElement>(`#${CSS.escape(activeContainerId)}-card`);
    if (!card || !document.body.contains(card)) return;
    await loadAndPaint(card);
}
