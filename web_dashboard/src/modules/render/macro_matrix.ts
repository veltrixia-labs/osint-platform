/**
 * Macro Influence Heatmap (Bloomberg-style screener)
 * ==================================================
 *
 * Dense CSS-Grid matrix showing peak correlation for every
 * (tradeable_macro × strategic_topic) pair. Click a cell to load that combo
 * into the Macro Transmission chart via the `macro-tx-select` CustomEvent.
 *
 * Pure vanilla TS + CSS Grid. No charting library, no D3, no <canvas>.
 */

import {
    fetchMacroMatrix,
    fetchMacroTransmissionOptions,
    type MacroMatrix,
    type MacroMatrixCell,
    type MacroTransmissionMacroOption,
    type MacroTransmissionOptions,
    type MacroTransmissionTopicOption,
} from '../api';
import { MACRO_TX_SELECT_EVENT } from './macro_chart';

const STYLE_ID = 'macro-matrix-styles';

let activeContainerId: string | null = null;
let cachedOptions: MacroTransmissionOptions | null = null;

function injectStyles(): void {
    if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
        .macro-matrix-card {
            position: relative;
            display: flex;
            flex-direction: column;
            gap: 14px;
            padding: 18px 20px 16px;
            border-radius: 14px;
            background: linear-gradient(160deg, rgba(15, 23, 42, 0.55), rgba(15, 23, 42, 0.25));
            border: 1px solid rgba(125, 211, 252, 0.18);
            backdrop-filter: blur(18px) saturate(140%);
            -webkit-backdrop-filter: blur(18px) saturate(140%);
            box-shadow:
                0 8px 28px rgba(2, 6, 23, 0.45),
                inset 0 0 0 1px rgba(255, 255, 255, 0.03);
            color: #cbd5e1;
        }
        .macro-matrix-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 12px;
            flex-wrap: wrap;
        }
        .macro-matrix-header h3 {
            margin: 0;
            font-size: 0.95rem;
            font-weight: 700;
            color: #e2e8f0;
        }
        .macro-matrix-subtitle {
            font-size: 0.72rem;
            color: #94a3b8;
        }
        .macro-matrix-meta {
            font-size: 0.66rem;
            color: #64748b;
            font-variant-numeric: tabular-nums;
        }

        .macro-matrix-grid {
            display: grid;
            /* 1 macro-label column + N topic columns */
            gap: 4px;
        }
        .macro-matrix-cell {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 10px 6px;
            border-radius: 8px;
            font-size: 0.78rem;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            color: #f8fafc;
            background: var(--cell-bg, rgba(71,85,105,0.30));
            border: 1px solid var(--cell-border, rgba(148,163,184,0.18));
            cursor: pointer;
            transition: transform 0.12s ease, box-shadow 0.12s ease, border-color 0.18s ease;
            text-shadow: 0 1px 2px rgba(0,0,0,0.45);
            min-height: 42px;
            position: relative;
        }
        .macro-matrix-cell:hover {
            transform: translateY(-1px) scale(1.02);
            border-color: rgba(125,211,252,0.55);
            box-shadow: 0 4px 16px rgba(2,6,23,0.55), 0 0 0 1px rgba(125,211,252,0.45);
            z-index: 2;
        }
        .macro-matrix-cell:focus-visible {
            outline: none;
            box-shadow: 0 0 0 3px rgba(125,211,252,0.45);
        }
        .macro-matrix-cell.null {
            color: #64748b;
            cursor: not-allowed;
            background: rgba(15,23,42,0.55);
            border-style: dashed;
        }
        .macro-matrix-cell .lag-sub {
            display: block;
            font-size: 0.58rem;
            font-weight: 600;
            opacity: 0.78;
            margin-top: 2px;
            letter-spacing: 0.04em;
        }

        .macro-matrix-rowhdr,
        .macro-matrix-colhdr {
            font-size: 0.68rem;
            font-weight: 700;
            color: #cbd5e1;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            display: flex;
            align-items: center;
            padding: 6px 8px;
        }
        .macro-matrix-rowhdr {
            justify-content: flex-start;
            background: rgba(2,6,23,0.45);
            border-radius: 6px;
            border-left: 3px solid var(--row-accent, #94a3b8);
        }
        .macro-matrix-colhdr {
            justify-content: center;
            color: #94a3b8;
            font-size: 0.66rem;
        }
        .macro-matrix-colhdr.corner {
            background: transparent;
            border: none;
        }

        .macro-matrix-legend {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 0.68rem;
            color: #94a3b8;
            flex-wrap: wrap;
        }
        .macro-matrix-legend-bar {
            display: inline-flex;
            height: 10px;
            width: 220px;
            border-radius: 999px;
            background: linear-gradient(90deg,
                #dc2626 0%,
                #f87171 16%,
                #475569 50%,
                #0d9488 70%,
                #22d3ee 86%,
                #10b981 100%);
            border: 1px solid rgba(148,163,184,0.30);
        }

        .macro-matrix-status {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100px;
            font-size: 0.85rem;
            color: #94a3b8;
        }
        .macro-matrix-status.error { color: #fca5a5; }
    `;
    document.head.appendChild(style);
}

/**
 * Map a correlation in [-1, 1] (or null) to a glassmorphism-compatible
 * background + border colour. Strong negative → deep red, neutral → slate,
 * strong positive → cyan/emerald. Opacity scales with |R|.
 */
function correlationColors(corr: number | null): { bg: string; border: string } {
    if (corr === null || !Number.isFinite(corr)) {
        return { bg: 'rgba(71,85,105,0.20)', border: 'rgba(148,163,184,0.18)' };
    }
    const r = Math.max(-1, Math.min(1, corr));
    const mag = Math.abs(r);
    // Opacity floor + magnitude scaling (so even weak signals are visible)
    const alpha = 0.18 + mag * 0.62;

    // Three-zone palette
    let rgb: [number, number, number];
    if (r <= -0.7)        rgb = [220, 38, 38];   // deep red
    else if (r <= -0.4)   rgb = [248, 113, 113]; // soft red
    else if (r <= -0.2)   rgb = [146, 128, 106]; // brownish
    else if (r <  0.2)    rgb = [71, 85, 105];   // neutral slate
    else if (r <  0.4)    rgb = [13, 148, 136];  // teal
    else if (r <  0.7)    rgb = [34, 211, 238];  // cyan
    else                  rgb = [16, 185, 129];  // emerald

    const [rd, gd, bd] = rgb;
    return {
        bg: `rgba(${rd},${gd},${bd},${alpha.toFixed(3)})`,
        border: `rgba(${rd},${gd},${bd},${Math.min(1, alpha + 0.18).toFixed(3)})`,
    };
}

function findMacro(options: MacroTransmissionOptions | null, id: string): MacroTransmissionMacroOption | undefined {
    return options?.macro_series.find((m) => m.id === id);
}
function findTopic(options: MacroTransmissionOptions | null, id: string): MacroTransmissionTopicOption | undefined {
    return options?.target_topics.find((t) => t.id === id);
}

function escAttr(s: string): string {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function cellHtml(cell: MacroMatrixCell, options: MacroTransmissionOptions | null): string {
    const macroLabel = findMacro(options, cell.macro_id)?.label ?? cell.macro_id;
    const topicLabel = findTopic(options, cell.topic_id)?.label ?? cell.topic_id;
    if (cell.correlation === null || !Number.isFinite(cell.correlation)) {
        return `<button
            type="button"
            class="macro-matrix-cell null"
            data-role="cell"
            data-macro="${escAttr(cell.macro_id)}"
            data-topic="${escAttr(cell.topic_id)}"
            disabled
            title="${escAttr(macroLabel)} → ${escAttr(topicLabel)} · ${escAttr(cell.status)}"
        >—</button>`;
    }
    const r = cell.correlation;
    const colors = correlationColors(r);
    const lag = cell.lag_days;
    const lagLabel = lag == null ? '' : lag === 0 ? 'sync' : `+${lag}d`;
    const sign = r > 0 ? '+' : '';
    const value = `${sign}${r.toFixed(2)}`;
    const tooltip = `${macroLabel} → ${topicLabel}\n` +
        `Correlation: ${value}\n` +
        (lag != null ? `Lag: ${lagLabel}\n` : '') +
        `Sample: ${cell.sample_size} pts\n` +
        `Click to load into chart`;
    return `<button
        type="button"
        class="macro-matrix-cell"
        data-role="cell"
        data-macro="${escAttr(cell.macro_id)}"
        data-topic="${escAttr(cell.topic_id)}"
        title="${escAttr(tooltip)}"
        style="--cell-bg:${colors.bg}; --cell-border:${colors.border};"
    >${value}${lagLabel ? `<span class="lag-sub">${lagLabel}</span>` : ''}</button>`;
}

function setStatus(host: HTMLElement, html: string, isError = false): void {
    host.innerHTML = `<div class="macro-matrix-status ${isError ? 'error' : ''}">${html}</div>`;
}

async function paintMatrix(host: HTMLElement, matrix: MacroMatrix, options: MacroTransmissionOptions | null): Promise<void> {
    const nTopics = matrix.topics.length;
    // 1 label column + N topic columns
    const colTemplate = `minmax(110px, 0.9fr) repeat(${nTopics}, minmax(72px, 1fr))`;

    // Corner cell + topic headers
    const headerCells: string[] = [`<div class="macro-matrix-colhdr corner"></div>`];
    for (const topicId of matrix.topics) {
        const t = findTopic(options, topicId);
        const label = t?.label ?? topicId;
        const accent = t?.accent_color ?? '#94a3b8';
        headerCells.push(
            `<div class="macro-matrix-colhdr" title="${escAttr(label)}" style="color:${escAttr(accent)};">${escAttr(label)}</div>`
        );
    }

    // Body rows
    const bodyCells: string[] = [];
    matrix.macros.forEach((macroId, i) => {
        const m = findMacro(options, macroId);
        const macroLabel = m?.label ?? macroId;
        const accent = m?.accent_color ?? '#94a3b8';
        bodyCells.push(
            `<div class="macro-matrix-rowhdr" style="--row-accent:${escAttr(accent)}" title="${escAttr(macroLabel)}">${escAttr(macroLabel)}</div>`
        );
        const row = matrix.cells[i] || [];
        for (const cell of row) {
            bodyCells.push(cellHtml(cell, options));
        }
    });

    const generatedAt = new Date(matrix.generated_at);
    const tsLabel = isNaN(generatedAt.getTime())
        ? matrix.generated_at
        : generatedAt.toLocaleTimeString();

    host.innerHTML = `
        <div class="macro-matrix-header">
            <div>
                <h3>Macro Influence Heatmap</h3>
                <div class="macro-matrix-subtitle">
                    Peak correlation (R) for every macro × sector pair · Click any cell to load the chart
                </div>
            </div>
            <div class="macro-matrix-meta">
                Lookback ${matrix.lookback_days}d · RoC ${matrix.roc_window_days}d · ${tsLabel}
            </div>
        </div>
        <div class="macro-matrix-grid" style="grid-template-columns:${colTemplate};">
            ${headerCells.join('')}
            ${bodyCells.join('')}
        </div>
        <div class="macro-matrix-legend">
            <span>Strong inverse (-1)</span>
            <span class="macro-matrix-legend-bar" role="presentation"></span>
            <span>Strong positive (+1)</span>
        </div>
    `;

    host.querySelectorAll<HTMLButtonElement>('button[data-role="cell"]').forEach((btn) => {
        if (btn.classList.contains('null')) return;
        btn.addEventListener('click', () => {
            const macro = btn.dataset.macro || '';
            const topic = btn.dataset.topic || '';
            if (!macro || !topic) return;
            window.dispatchEvent(new CustomEvent(MACRO_TX_SELECT_EVENT, {
                detail: { macro, topic },
            }));
        });
    });
}

async function loadAndPaint(host: HTMLElement): Promise<void> {
    setStatus(host, '<span class="animate-pulse">Loading macro influence matrix…</span>');
    const [matrix, options] = await Promise.all([
        fetchMacroMatrix(),
        cachedOptions ? Promise.resolve(cachedOptions) : fetchMacroTransmissionOptions(),
    ]);
    cachedOptions = options;
    if (!matrix) {
        setStatus(host, 'Macro matrix endpoint unavailable.', true);
        return;
    }
    if (!matrix.cells.length || !matrix.cells[0]?.length) {
        setStatus(host, 'No matrix data available.');
        return;
    }
    await paintMatrix(host, matrix, options);
}

export async function renderMacroInfluenceMatrix(containerId: string): Promise<void> {
    const container = document.getElementById(containerId);
    if (!container) return;
    injectStyles();
    container.innerHTML = `<div class="macro-matrix-card" id="${containerId}-card"></div>`;
    const card = container.querySelector<HTMLElement>(`#${CSS.escape(containerId)}-card`);
    if (!card) return;
    activeContainerId = containerId;
    await loadAndPaint(card);
}

/** Re-fetch and repaint the active heatmap (called on the 60-second poll). */
export async function refreshMacroInfluenceMatrix(): Promise<void> {
    if (!activeContainerId) return;
    const container = document.getElementById(activeContainerId);
    if (!container) return;
    const card = container.querySelector<HTMLElement>(`#${CSS.escape(activeContainerId)}-card`);
    if (!card || !document.body.contains(card)) return;
    await loadAndPaint(card);
}
