import type { ProStructuralReportItem } from '../api';
import { fetchProStructuralReports, fetchProStructuralReport, fetchAlert, fetchFragilityHistory } from '../api';
import { renderSpatialContagionShell, mountSpatialContagionMap } from './pro_interactive_map';
import {
    simpleMarkdown,
    getDomainSlugClass,
    formatIntelDateTime,
    formatIntelPreciseTimestamp,
    formatIntelRelativeTimestamp,
    dedupeProStructuralBriefs,
} from './utils';
import { showEvidenceModal } from './alerts';
import { resolveAlertHeadline } from '../alert_display';
import {
    getTopicCssVars,
    getTopicDisplayLabel,
    normalizeTopicCode,
    type StrategicTopicCode,
} from '../topics';
import L from 'leaflet';

/**
 * Renders the list of Pro Structural Briefs.
 */
export async function renderProStructuralBriefs(
    container: HTMLElement,
    onSelect: (id: string) => void,
    topicFilter: StrategicTopicCode | null = null,
    options?: { refreshOnly?: boolean },
) {
    const refreshOnly = options?.refreshOnly === true;
    let listContainer = container.querySelector('#briefs-list') as HTMLElement | null;

    if (!listContainer) {
        container.innerHTML = `
        <div class="pro-briefs-container">
            <div class="insight-card pro-insight-panel">
                <div class="insight-card-header">
                    <h3 class="insight-card-title">Latest Structural Briefs</h3>
                </div>
                <div class="insight-card-body">
                    <div id="briefs-list" class="pro-briefs-grid pro-briefs-grid--loading">
                        <div class="u-p-2 u-text-center">Synchronizing intelligence assets...</div>
                    </div>
                </div>
            </div>
        </div>
    `;
        listContainer = container.querySelector('#briefs-list') as HTMLElement;
    }

    try {
        const reports: ProStructuralReportItem[] = dedupeProStructuralBriefs(
            await fetchProStructuralReports(),
        );
        if (!listContainer) return;

        const filtered = topicFilter
            ? reports.filter((r) => normalizeTopicCode(r.topic) === topicFilter)
            : reports;

        const bindCards = () => {
            listContainer!.querySelectorAll('.pro-brief-card').forEach((card) => {
                (card as HTMLElement).addEventListener('click', () => {
                    const id = card.getAttribute('data-id');
                    if (id) onSelect(id);
                });
            });
        };

        const paintGrid = (html: string) => {
            if (refreshOnly) {
                listContainer!.replaceChildren();
                listContainer!.insertAdjacentHTML('beforeend', html);
                bindCards();
                return;
            }
            listContainer!.classList.remove('pro-briefs-grid--loading', 'pro-briefs-grid--settled');
            listContainer!.classList.add('pro-briefs-grid--transition');
            listContainer!.style.opacity = '0';
            listContainer!.innerHTML = html;
            requestAnimationFrame(() => {
                listContainer!.style.opacity = '1';
                listContainer!.classList.add('pro-briefs-grid--settled');
                window.setTimeout(() => {
                    listContainer!.classList.remove('pro-briefs-grid--transition');
                }, 320);
            });
        };

        if (reports.length === 0) {
            paintGrid(
                `<div class="pro-briefs-empty u-p-2 u-text-center"><div style="font-size: 2.5rem; margin-bottom: 1rem;">📡</div><div style="font-weight: 600; color: #c9d1d9; margin-bottom: 0.5rem;">No Structural Briefs Detected</div><div style="color: #8b949e; font-size: 0.9rem;">Intelligence pipelines are active.</div></div>`,
            );
            return;
        }

        if (!filtered.length) {
            const filterLabel = topicFilter ? getTopicDisplayLabel(topicFilter) : null;
            paintGrid(
                `<div class="pro-briefs-empty u-p-2 u-text-center"><div class="empty-title" style="color: #c9d1d9; font-weight: 600; margin-bottom: 0.5rem;">No Structural Briefs for ${filterLabel}</div><div style="color: #8b949e; font-size: 0.9rem;">Select another domain or clear the filter to view all briefs.</div></div>`,
            );
            return;
        }

        paintGrid(
            filtered
                .map((r) => {
                    const dc = getDomainSlugClass(r.topic);
                    const topicVars = getTopicCssVars(r.topic);
                    const topicLabel = getTopicDisplayLabel(r.topic);
                    const createdRel = formatIntelRelativeTimestamp(r.created_at);
                    const createdUtc = formatIntelPreciseTimestamp(r.created_at);
                    return `<div class="pro-brief-card ${dc}" data-id="${r.id}" style="${topicVars}"><div class="u-flex-between" style="margin-bottom:1rem;"><span class="domain-chip meta-item-topic--tag">${topicLabel}</span><div style="display:flex;flex-direction:column;align-items:flex-end;gap:2px;"><span style="font-size:0.65rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.05em;">${(r.report_type || 'PRO_STRUCTURAL').replace(/_/g, ' ')}</span><span class="pro-brief-ts" title="${createdUtc}" style="font-size:0.75rem;color:var(--text-secondary);">${createdRel}</span></div></div><h3 style="margin:0 0 1rem;font-size:1.2rem;line-height:1.4;color:var(--text-primary);">${r.title}</h3><div style="font-size:0.9rem;color:var(--text-secondary);line-height:1.6;margin-bottom:1.5rem;flex-grow:1;">${r.teaser_md || 'Detailed structural analysis of transmission channels, macro-economic dependencies, and market confirmation signals.'}</div><button class="btn-fb pro-brief-btn" style="width:100%;pointer-events:none;">View Full Brief →</button></div>`;
                })
                .join(''),
        );
        bindCards();
    } catch (e) {
        console.error("Failed to fetch Pro briefs", e);
        const lc = container.querySelector('#briefs-list') as HTMLElement;
        if (lc) { lc.style.display='block'; lc.innerHTML=`<div class="u-p-2 u-text-center u-error" style="background:rgba(248,81,73,0.1);border:1px solid rgba(248,81,73,0.2);border-radius:12px;color:#f85149;">Failed to synchronize intelligence assets.</div>`; }
    }
}

/* --- Helpers --- */
const PRO_SECTION_GUIDES: Record<string, string> = {
    '01': 'Summary of the detected anomaly, primary risk dimensions, and data verification status.',
    '02': 'Categorizes the core event type and secondary structural dependencies triggering the shift.',
    '03': 'Identifies the spatial nexus and geographical point of origin for the systemic risk.',
    '04': 'Chronological tracking of factual real-world incidents acting as the structural catalyst.',
    '05': 'Visualizes the cascading domino effect from political decisions down to material availability.',
    '06': 'Hard macroeconomic statistics and live asset prices reinforcing the analytical core.',
    '07': 'Audits whether the financial markets have already priced in the geopolitical shock.',
    '08': 'Measures the valuation gap between sentiment and quantitative market tracking.',
    '09': 'Defines actionable thresholds that will either amplify or defuse this structural risk.',
    '10': 'Core security ETFs and sector spending metrics mapped for real-time monitoring.',
    '11': 'Dual-perspective modeling weighing long-term revenue visibility against sudden policy shifts.',
    '12': 'Direct tactical mapping showing how specific business tiers and suppliers are impacted.',
    '13': 'Evaluates data fidelity and limitation notes to calibrate your decision-making confidence.',
    '14': 'Three-tier systemic propagation: direct exposure (1st-order), downstream channels (2nd-order), and cross-domain spillover (3rd-order).',
    '15': 'Low-probability, high-impact contrarian paths sourced from invalidating conditions, extreme macro moves, and short-lag transmission acceleration.',
    '16': 'Exact numeric foundation of the brief: CCF lag, [-1, 1]-clipped correlation, log-return beta, and the largest macro / market moves driving the analysis.',
};

const PRO_V3_STYLE_ID = 'pro-v3-section-styles';

/**
 * One-time injection of glassmorphism styles for the v3 sections.
 * Kept inline so the change is atomic and the build pipeline is not affected.
 */
function ensureProV3Styles(): void {
    if (typeof document === 'undefined' || document.getElementById(PRO_V3_STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = PRO_V3_STYLE_ID;
    style.textContent = `
        /* === Shared glass surface ============================================ */
        .intel-panel.intel-quant-narrative,
        .intel-panel.intel-audit-appendix,
        .intel-panel.intel-cascading,
        .intel-panel.intel-tail-risk,
        .intel-panel.intel-quant-matrix,
        .intel-panel.intel-wargaming-panel,
        .intel-panel.intel-psyops-panel,
        .intel-panel.intel-sf-panel {
            background: linear-gradient(165deg, rgba(15,23,42,0.62), rgba(15,23,42,0.30));
            border: 1px solid rgba(125,211,252,0.18);
            backdrop-filter: blur(18px) saturate(140%);
            -webkit-backdrop-filter: blur(18px) saturate(140%);
            box-shadow: 0 10px 32px rgba(2,6,23,0.45), inset 0 0 0 1px rgba(255,255,255,0.03);
        }

        .intel-panel-intro {
            color: #94a3b8;
            font-size: 0.85rem;
            line-height: 1.55;
            margin: 0.25rem 0 1rem;
        }

        /* === Senior Quant Analyst narrative ================================= */
        .intel-narrative-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 12px;
            margin-top: 0.85rem;
        }
        .intel-narrative-card {
            position: relative;
            overflow: hidden;
            padding: 14px 15px;
            border-radius: 13px;
            background: linear-gradient(150deg, rgba(15,23,42,0.76), rgba(15,23,42,0.42));
            border: 1px solid rgba(125,211,252,0.16);
            box-shadow: inset 0 0 0 1px rgba(255,255,255,0.025);
        }
        .intel-narrative-card::before {
            content: "";
            position: absolute;
            inset: 0 auto 0 0;
            width: 3px;
            background: var(--topic-accent, #38bdf8);
            opacity: 0.75;
        }
        .intel-narrative-kicker {
            display: flex;
            align-items: center;
            gap: 7px;
            margin-bottom: 8px;
            color: var(--topic-accent, #38bdf8);
            font-size: 0.68rem;
            font-weight: 800;
            letter-spacing: 0.10em;
            text-transform: uppercase;
        }
        .intel-narrative-body {
            margin: 0;
            color: #dbeafe;
            font-size: 0.88rem;
            line-height: 1.62;
        }
        .intel-audit-appendix {
            margin-top: 1.2rem;
            opacity: 0.88;
            background: linear-gradient(165deg, rgba(15,23,42,0.42), rgba(15,23,42,0.20));
            border-style: dashed;
        }
        .intel-audit-appendix .intel-section-title,
        .intel-audit-appendix .intel-tl-title {
            color: #cbd5e1;
        }

        /* === Systemic Fragility Engine ====================================== */
        @keyframes sf-bar-pulse {
            0%,100% { opacity:1; }
            50%      { opacity:0.55; }
        }
        @keyframes sf-critical-pulse {
            0%,100% { border-color:rgba(239,68,68,0.45); box-shadow:0 0 0 1px rgba(239,68,68,0.18), inset 0 0 40px rgba(239,68,68,0.05); }
            50%      { border-color:rgba(239,68,68,0.85); box-shadow:0 0 22px rgba(239,68,68,0.4), inset 0 0 40px rgba(239,68,68,0.10); }
        }
        @keyframes sf-dot-outer-pulse {
            0%,100% { r:14; opacity:0.12; }
            50%      { r:22; opacity:0.06; }
        }
        .intel-sf-panel--critical {
            border-color: rgba(239,68,68,0.45) !important;
            animation: sf-critical-pulse 2.5s ease-in-out infinite;
        }
        .intel-sf-panel--warning {
            border-color: rgba(245,158,11,0.38) !important;
        }
        .sf-dot-pulse-outer {
            animation: sf-dot-outer-pulse 2s ease-in-out infinite;
        }
        .sf-status-row {
            display: flex;
            align-items: center;
            gap: 14px;
            margin: 0.5rem 0 1rem;
            flex-wrap: wrap;
        }
        .sf-label-badge {
            display: inline-block;
            padding: 4px 14px;
            border-radius: 20px;
            border: 1px solid;
            font-size: 0.72rem;
            font-weight: 900;
            letter-spacing: 0.10em;
            text-transform: uppercase;
        }
        .sf-conjunction-label {
            font-size: 0.75rem;
            font-weight: 600;
        }
        .sf-main-layout {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 20px;
            align-items: start;
            margin-top: 0.25rem;
        }
        @media (max-width: 700px) {
            .sf-main-layout { grid-template-columns: 1fr; }
        }
        .sf-gauges-col {
            display: flex;
            flex-direction: column;
            gap: 0;
        }
        .sf-dual-gauge {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }
        .sf-gauge {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .sf-gauge-header {
            display: flex;
            align-items: baseline;
            gap: 8px;
        }
        .sf-gauge-symbol {
            font-size: 1.1rem;
            font-style: italic;
            font-weight: 700;
            color: #94a3b8;
            min-width: 20px;
        }
        .sf-gauge-label {
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #64748b;
            flex: 1;
        }
        .sf-gauge-value {
            font-size: 1.5rem;
            font-weight: 900;
            font-variant-numeric: tabular-nums;
            line-height: 1;
        }
        .sf-gauge-unit {
            font-size: 0.75rem;
            font-weight: 500;
            opacity: 0.6;
            margin-left: 2px;
        }
        .sf-bar-track {
            position: relative;
            height: 10px;
            border-radius: 99px;
            background: rgba(255,255,255,0.07);
            overflow: visible;
        }
        .sf-bar-fill {
            height: 100%;
            border-radius: 99px;
            transition: width 0.8s cubic-bezier(0.22,1,0.36,1);
            position: relative;
            z-index: 1;
        }
        .sf-bar-threshold {
            position: absolute;
            top: -5px;
            width: 2px;
            height: 20px;
            background: #ef4444;
            border-radius: 2px;
            z-index: 2;
            transform: translateX(-50%);
        }
        .sf-thr-label {
            position: absolute;
            top: -16px;
            left: 50%;
            transform: translateX(-50%);
            font-size: 0.55rem;
            font-weight: 800;
            letter-spacing: 0.06em;
            color: #ef4444;
            white-space: nowrap;
        }
        .sf-gauge-sublabel {
            font-size: 0.68rem;
            font-weight: 600;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }
        /* Phase-space SVG */
        .sf-phase-col {
            flex-shrink: 0;
        }
        .sf-phase-space {
            width: 280px;
            height: 200px;
            display: block;
            border-radius: 8px;
            background: rgba(10,15,30,0.7);
            border: 1px solid rgba(148,163,184,0.12);
        }
        /* Rationale terminal */
        .sf-terminal {
            margin-top: 14px;
            border-radius: 8px;
            background: #070c18;
            border: 1px solid rgba(148,163,184,0.12);
            overflow: hidden;
            font-family: "Courier New", Courier, monospace;
        }
        .sf-terminal-header {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            background: rgba(15,23,42,0.9);
            border-bottom: 1px solid rgba(148,163,184,0.10);
        }
        .sf-terminal-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: rgba(255,255,255,0.12);
        }
        .sf-terminal-title {
            margin-left: 6px;
            font-size: 0.60rem;
            color: #475569;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }
        .sf-terminal-body {
            padding: 11px 15px;
            font-size: 0.82rem;
            line-height: 1.65;
            color: #94a3b8;
        }
        .sf-terminal-prompt {
            color: var(--sf-accent, #22d3ee);
            font-weight: 700;
            user-select: none;
        }
        .sf-terminal-out {
            color: #cbd5e1;
        }
        /* === Information Integrity & PsyOps Assessment ====================== */
        @keyframes scanlines {
            0%   { background-position: 0 0; }
            100% { background-position: 0 8px; }
        }
        @keyframes psyops-glitch {
            0%,100% { text-shadow: 0 0 8px #e879f9, 0 0 20px rgba(232,121,249,0.5); clip-path: none; transform: none; }
            7%       { clip-path: inset(15% 0 70% 0); transform: translate(-3px, 1px) skewX(-3deg); text-shadow: -2px 0 #f0abfc, 2px 0 #a855f7, 0 0 20px #e879f9; }
            14%      { clip-path: none; transform: none; text-shadow: 0 0 8px #e879f9; }
            21%      { clip-path: inset(60% 0 20% 0); transform: translate(2px, -1px) skewX(2deg); text-shadow: 2px 0 #f0abfc, -2px 0 #a855f7; }
            28%      { clip-path: none; transform: none; }
        }
        @keyframes psyops-pulse-border {
            0%,100% { border-color: rgba(232,121,249,0.35); box-shadow: 0 0 0 1px rgba(232,121,249,0.15), inset 0 0 40px rgba(232,121,249,0.04); }
            50%      { border-color: rgba(232,121,249,0.75); box-shadow: 0 0 18px rgba(232,121,249,0.35), inset 0 0 40px rgba(232,121,249,0.08); }
        }
        .intel-psyops-panel--alert {
            border-color: rgba(232,121,249,0.45) !important;
            animation: psyops-pulse-border 3s ease-in-out infinite;
            position: relative;
            overflow: hidden;
        }
        .intel-psyops-panel--alert::after {
            content: "";
            position: absolute;
            inset: 0;
            pointer-events: none;
            background: repeating-linear-gradient(
                0deg,
                transparent,
                transparent 3px,
                rgba(232,121,249,0.025) 3px,
                rgba(232,121,249,0.025) 4px
            );
            animation: scanlines 0.4s linear infinite;
        }
        .psyops-warning-badge {
            margin: 0.6rem 0 1rem;
            padding: 10px 14px;
            border-radius: 6px;
            background: linear-gradient(90deg, rgba(232,121,249,0.18), rgba(168,85,247,0.12));
            border: 1px solid rgba(232,121,249,0.5);
            box-shadow: 0 0 18px rgba(232,121,249,0.25), inset 0 0 12px rgba(232,121,249,0.07);
            text-align: center;
        }
        .psyops-glitch {
            display: inline-block;
            font-size: 0.8rem;
            font-weight: 900;
            letter-spacing: 0.09em;
            text-transform: uppercase;
            color: #f0abfc;
            text-shadow: 0 0 8px #e879f9, 0 0 20px rgba(232,121,249,0.5);
            animation: psyops-glitch 5s steps(1) infinite;
            position: relative;
        }
        .psyops-body {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .psyops-risk-row {
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }
        .psyops-risk-label {
            font-size: 0.65rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: #64748b;
        }
        .psyops-risk-badge {
            display: inline-flex;
            align-items: center;
            gap: 7px;
            padding: 3px 12px;
            border-radius: 20px;
            border: 1px solid;
            font-size: 0.7rem;
            font-weight: 800;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }
        .psyops-dot {
            display: inline-block;
            width: 7px;
            height: 7px;
            border-radius: 50%;
            flex-shrink: 0;
        }
        .psyops-dot--low    { background: #22d3ee; box-shadow: 0 0 5px #22d3ee; }
        .psyops-dot--medium { background: #f59e0b; box-shadow: 0 0 5px #f59e0b; }
        .psyops-dot--high   { background: #e879f9; box-shadow: 0 0 7px #e879f9; animation: psyops-pulse-border 1.8s ease-in-out infinite; }
        .psyops-divergence-indicator {
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.07em;
            text-transform: uppercase;
            margin-left: auto;
        }
        .psyops-terminal {
            border-radius: 8px;
            background: #0a0f1e;
            border: 1px solid rgba(148,163,184,0.15);
            overflow: hidden;
            font-family: "Courier New", Courier, monospace;
        }
        .psyops-terminal-header {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 7px 12px;
            background: rgba(15,23,42,0.9);
            border-bottom: 1px solid rgba(148,163,184,0.12);
        }
        .psyops-terminal-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: rgba(255,255,255,0.15);
        }
        .psyops-terminal-title {
            margin-left: 6px;
            font-size: 0.62rem;
            color: #475569;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }
        .psyops-terminal-body {
            padding: 12px 15px;
            font-size: 0.83rem;
            line-height: 1.65;
            color: #94a3b8;
        }
        .psyops-prompt {
            color: #e879f9;
            font-weight: 700;
            margin-right: 2px;
            user-select: none;
        }
        .psyops-output {
            color: #cbd5e1;
        }
        /* === Wargaming & Probability Matrix ================================= */
        .intel-wargaming-panel {
            margin-top: 0;
        }
        .wargame-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 14px;
            margin-top: 1rem;
        }
        .wargame-card {
            position: relative;
            border-radius: 14px;
            padding: 16px 18px;
            background: linear-gradient(145deg, rgba(15,23,42,0.78), rgba(15,23,42,0.44));
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: 0 0 0 1px var(--wg-glow, rgba(34,211,238,0.18)),
                        inset 0 0 24px var(--wg-glow, rgba(34,211,238,0.06));
            transition: box-shadow 0.25s ease;
            overflow: hidden;
        }
        .wargame-card::before {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 2px;
            background: var(--wg-accent, #22d3ee);
            opacity: 0.8;
        }
        .wargame-card-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 12px;
        }
        .wargame-badge {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.68rem;
            font-weight: 800;
            letter-spacing: 0.09em;
            text-transform: uppercase;
            white-space: nowrap;
        }
        .wargame-badge--cyan  { background: rgba(34,211,238,0.15); color: #22d3ee; border: 1px solid rgba(34,211,238,0.35); }
        .wargame-badge--amber { background: rgba(245,158,11,0.15); color: #f59e0b; border: 1px solid rgba(245,158,11,0.35); }
        .wargame-badge--crimson { background: rgba(239,68,68,0.15); color: #ef4444; border: 1px solid rgba(239,68,68,0.35); }
        .wargame-prob-wrap {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 5px;
            min-width: 88px;
        }
        .wargame-prob-num {
            font-size: 1.75rem;
            font-weight: 900;
            line-height: 1;
            color: var(--wg-accent, #22d3ee);
            text-shadow: 0 0 12px var(--wg-glow, rgba(34,211,238,0.5));
            font-variant-numeric: tabular-nums;
        }
        .wargame-prob-sym {
            font-size: 1rem;
            font-weight: 600;
            vertical-align: top;
            margin-top: 0.15rem;
            opacity: 0.7;
        }
        .wargame-bar-track {
            width: 88px;
            height: 5px;
            border-radius: 99px;
            background: rgba(255,255,255,0.08);
            overflow: hidden;
        }
        .wargame-bar-fill {
            height: 100%;
            border-radius: 99px;
            transition: width 0.6s cubic-bezier(0.22,1,0.36,1);
        }
        .wargame-desc {
            margin: 0 0 10px;
            color: #e2e8f0;
            font-size: 0.875rem;
            line-height: 1.6;
        }
        .wargame-timeline-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            padding-top: 8px;
            border-top: 1px solid rgba(255,255,255,0.07);
        }
        .wargame-timeline-label {
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #64748b;
        }
        .wargame-timeline-val {
            font-size: 0.78rem;
            font-weight: 600;
            color: #94a3b8;
            text-align: right;
        }
        /* === Spatial Contagion Network Map ==================================== */
        .intel-spatial-panel {
            padding-bottom: 0;
            overflow: hidden;
        }
        .sc-stats-bar {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            margin: 0.6rem 0 1rem;
            padding: 0.65rem 1rem;
            background: rgba(15,23,42,0.55);
            border: 1px solid rgba(148,163,184,0.1);
            border-radius: 10px;
        }
        .sc-stat {
            display: flex;
            flex-direction: column;
            gap: 3px;
            min-width: 80px;
        }
        .sc-stat-label {
            font-size: 0.6rem;
            font-weight: 800;
            letter-spacing: 0.10em;
            text-transform: uppercase;
            color: #475569;
        }
        .sc-stat-val {
            font-size: 0.88rem;
            font-weight: 700;
            color: #e2e8f0;
            font-variant-numeric: tabular-nums;
        }
        .sc-stat-val--critical {
            color: #ef4444;
            text-shadow: 0 0 8px rgba(239,68,68,0.4);
        }
        .sc-map-wrap {
            position: relative;
            width: 100%;
            height: 420px;
            border-radius: 0 0 12px 12px;
            overflow: hidden;
            background: #07090f;
            border-top: 1px solid rgba(148,163,184,0.08);
        }
        .sc-map-canvas {
            width: 100%;
            height: 100%;
        }
        .sc-map-overlay {
            position: absolute;
            inset: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: rgba(7,9,15,0.82);
            backdrop-filter: blur(6px);
            z-index: 20;
            gap: 12px;
            transition: opacity 0.4s ease;
        }
        .sc-map-overlay-content {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 10px;
            text-align: center;
            padding: 2rem;
        }
        .sc-map-overlay-icon {
            font-size: 2.2rem;
            opacity: 0.4;
        }
        .sc-map-overlay-text {
            font-size: 0.88rem;
            font-weight: 600;
            color: #94a3b8;
            letter-spacing: 0.04em;
        }
        .sc-map-overlay-sub {
            font-size: 0.76rem;
            color: #475569;
            max-width: 300px;
            line-height: 1.55;
        }
        .sc-map-overlay--loading {
            background: rgba(7,9,15,0.72);
            gap: 10px;
        }
        .sc-loading-pulse {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            border: 2px solid rgba(34,211,238,0.25);
            border-top-color: #22d3ee;
            animation: sc-spin 1s linear infinite;
        }
        @keyframes sc-spin {
            to { transform: rotate(360deg); }
        }
        .sc-loading-text {
            font-size: 0.75rem;
            color: #64748b;
            font-family: "Courier New", Courier, monospace;
            letter-spacing: 0.04em;
        }
        /* === Cascading impacts: three vertical tier cards ==================== */
        .intel-cascading-tiers {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 14px;
            margin-top: 0.5rem;
        }
        .intel-tier-card {
            border-radius: 12px;
            padding: 14px 14px 12px;
            background: rgba(2,6,23,0.50);
            border: 1px solid rgba(148,163,184,0.14);
            position: relative;
            overflow: hidden;
        }
        .intel-tier-card::before {
            content: '';
            position: absolute;
            inset: 0;
            border-top: 3px solid var(--tier-accent, #38bdf8);
            border-radius: 12px 12px 0 0;
            pointer-events: none;
        }
        .intel-tier-card.tier-1 { --tier-accent: #f87171; }
        .intel-tier-card.tier-2 { --tier-accent: #fbbf24; }
        .intel-tier-card.tier-3 { --tier-accent: #38bdf8; }

        .intel-tier-header {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            margin-bottom: 10px;
        }
        .intel-tier-title {
            margin: 0;
            font-size: 0.78rem;
            font-weight: 700;
            color: #e2e8f0;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }
        .intel-tier-count {
            font-size: 0.68rem;
            color: #94a3b8;
            font-variant-numeric: tabular-nums;
        }

        .intel-tier-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.78rem;
        }
        .intel-tier-table th {
            text-align: left;
            color: #64748b;
            font-size: 0.65rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            padding: 6px 8px;
            border-bottom: 1px solid rgba(148,163,184,0.14);
        }
        .intel-tier-table td {
            padding: 8px;
            color: #cbd5e1;
            border-bottom: 1px solid rgba(148,163,184,0.08);
            vertical-align: top;
            line-height: 1.45;
        }
        .intel-tier-table td strong { color: #e2e8f0; }
        .intel-tier-table tr:last-child td { border-bottom: none; }

        .intel-sens-pill {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 0.65rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }
        .intel-sens-pill.high   { background: rgba(248,113,113,0.15); color: #fca5a5; border: 1px solid rgba(248,113,113,0.40); }
        .intel-sens-pill.medium { background: rgba(251,191,36,0.15); color: #fcd34d; border: 1px solid rgba(251,191,36,0.40); }
        .intel-sens-pill.low    { background: rgba(56,189,248,0.15); color: #7dd3fc; border: 1px solid rgba(56,189,248,0.40); }
        .intel-sens-pill.unspecified { background: rgba(148,163,184,0.15); color: #cbd5e1; border: 1px solid rgba(148,163,184,0.30); }

        .intel-tier-channels {
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px dashed rgba(148,163,184,0.18);
        }
        .intel-tier-channels h5 {
            font-size: 0.68rem;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin: 0 0 6px;
        }
        .intel-tier-channels ul {
            list-style: none;
            padding: 0;
            margin: 0;
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }
        .intel-tier-channels li {
            font-size: 0.72rem;
            padding: 4px 9px;
            background: rgba(148,163,184,0.10);
            border: 1px solid rgba(148,163,184,0.20);
            border-radius: 6px;
            color: #cbd5e1;
        }

        .intel-spillover-list {
            margin: 0;
            padding: 0;
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .intel-spillover-list li {
            padding: 8px 10px;
            background: rgba(56,189,248,0.08);
            border-left: 3px solid #38bdf8;
            border-radius: 6px;
            font-size: 0.80rem;
            line-height: 1.45;
            color: #cbd5e1;
        }
        .intel-spillover-list code {
            color: #7dd3fc;
            font-size: 0.74rem;
            font-weight: 700;
        }

        .intel-active-pressure {
            margin-top: 14px;
            padding: 12px 14px;
            border-radius: 10px;
            background: rgba(248,113,113,0.06);
            border: 1px solid rgba(248,113,113,0.25);
        }
        .intel-active-pressure h5 {
            margin: 0 0 8px;
            font-size: 0.70rem;
            color: #fca5a5;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .intel-active-pressure-table {
            width: 100%;
            font-size: 0.78rem;
            border-collapse: collapse;
        }
        .intel-active-pressure-table th,
        .intel-active-pressure-table td {
            text-align: left;
            padding: 4px 6px;
            color: #cbd5e1;
        }
        .intel-active-pressure-table th { color: #64748b; font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.08em; }
        .intel-pressure-delta { font-weight: 700; font-variant-numeric: tabular-nums; }
        .intel-pressure-delta.up   { color: #fca5a5; }
        .intel-pressure-delta.down { color: #6ee7b7; }

        /* === Tail-Risk scenario cards ======================================== */
        .intel-tail-risk-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 12px;
        }
        .intel-risk-scenario {
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 12px 14px 10px;
            border-radius: 12px;
            background: rgba(2,6,23,0.50);
            border: 1px solid rgba(148,163,184,0.14);
            position: relative;
            overflow: hidden;
        }
        .intel-risk-scenario::before {
            content: '';
            position: absolute;
            left: 0; top: 0; bottom: 0;
            width: 3px;
            background: var(--risk-accent, #38bdf8);
        }
        .intel-risk-scenario.type-thesis_invalidator      { --risk-accent: #818cf8; }
        .intel-risk-scenario.type-stress_case             { --risk-accent: #fbbf24; }
        .intel-risk-scenario.type-regime_break            { --risk-accent: #f87171; }
        .intel-risk-scenario.type-transmission_acceleration { --risk-accent: #38bdf8; }

        .intel-risk-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
        }
        .intel-risk-type {
            font-size: 0.62rem;
            font-weight: 800;
            letter-spacing: 0.10em;
            text-transform: uppercase;
            padding: 3px 8px;
            border-radius: 999px;
            background: color-mix(in srgb, var(--risk-accent) 18%, transparent);
            color: var(--risk-accent, #38bdf8);
            border: 1px solid color-mix(in srgb, var(--risk-accent) 45%, transparent);
        }
        .intel-risk-pi {
            display: flex;
            gap: 6px;
            font-size: 0.68rem;
        }
        .intel-risk-pi span {
            font-variant-numeric: tabular-nums;
            color: #cbd5e1;
        }
        .intel-risk-pi .k { color: #64748b; }
        .intel-risk-body {
            font-size: 0.83rem;
            line-height: 1.55;
            color: #e2e8f0;
            margin: 0;
        }
        .intel-risk-footer {
            font-size: 0.66rem;
            color: #64748b;
            border-top: 1px dashed rgba(148,163,184,0.16);
            padding-top: 6px;
        }
        .intel-risk-footer code {
            color: #7dd3fc;
            font-size: 0.66rem;
        }

        /* === Quantitative Evidence Matrix =================================== */
        .intel-quant-hero {
            display: flex;
            flex-direction: column;
            gap: 10px;
            padding: 14px 16px 12px;
            border-radius: 14px;
            background: linear-gradient(140deg, rgba(56,189,248,0.10), rgba(99,102,241,0.10));
            border: 1px solid rgba(125,211,252,0.30);
            margin-bottom: 14px;
        }
        .intel-quant-hero-head {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 8px;
        }
        .intel-quant-hero-title {
            margin: 0;
            font-size: 0.78rem;
            font-weight: 800;
            color: #e0f2fe;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .intel-quant-hero-pair code {
            font-size: 0.72rem;
            color: #7dd3fc;
        }
        .intel-quant-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 10px;
        }
        .intel-quant-metric {
            padding: 10px 12px;
            background: rgba(2,6,23,0.55);
            border-radius: 10px;
            border: 1px solid rgba(148,163,184,0.16);
        }
        .intel-quant-metric .k {
            display: block;
            font-size: 0.62rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.10em;
            margin-bottom: 4px;
        }
        .intel-quant-metric .v {
            font-size: 1.04rem;
            font-weight: 800;
            color: #e2e8f0;
            font-variant-numeric: tabular-nums;
        }
        .intel-quant-metric .s {
            display: block;
            font-size: 0.66rem;
            color: #94a3b8;
            margin-top: 2px;
        }
        .intel-quant-meta {
            font-size: 0.70rem;
            color: #94a3b8;
            font-style: italic;
        }
        .intel-quant-meta code { color: #7dd3fc; font-style: normal; }

        .intel-quant-subtable-title {
            margin: 12px 0 6px;
            font-size: 0.72rem;
            font-weight: 700;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .intel-quant-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.80rem;
        }
        .intel-quant-table th {
            text-align: left;
            font-size: 0.64rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            padding: 6px 8px;
            border-bottom: 1px solid rgba(148,163,184,0.14);
        }
        .intel-quant-table td {
            padding: 7px 8px;
            color: #cbd5e1;
            border-bottom: 1px solid rgba(148,163,184,0.08);
            font-variant-numeric: tabular-nums;
        }
        .intel-quant-table td.num { font-weight: 700; text-align: right; }
        .intel-quant-table td.num.up   { color: #6ee7b7; }
        .intel-quant-table td.num.down { color: #fca5a5; }
        .intel-quant-table td code { color: #7dd3fc; font-size: 0.74rem; }
        .intel-quant-table tr:last-child td { border-bottom: none; }

        .intel-quant-stats {
            display: flex;
            gap: 12px;
            margin-top: 8px;
            flex-wrap: wrap;
        }
        .intel-quant-stat {
            padding: 8px 12px;
            border-radius: 8px;
            background: rgba(148,163,184,0.08);
            border: 1px solid rgba(148,163,184,0.18);
            min-width: 110px;
        }
        .intel-quant-stat .k { font-size: 0.62rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.08em; }
        .intel-quant-stat .v { font-size: 0.95rem; font-weight: 700; color: #e2e8f0; font-variant-numeric: tabular-nums; }
    `;
    document.head.appendChild(style);
}

function escHtml(s: string): string {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function escAttr(s: string): string {
    return escHtml(s).replace(/'/g, '&#39;');
}

function sh(num: string, title: string, guideKey: string = num): string {
    const guide = PRO_SECTION_GUIDES[guideKey];
    const guideHtml = guide
        ? `<span class="intel-section-guide-wrap">
            <button type="button" class="intel-section-guide" aria-label="About ${escAttr(title)}" aria-expanded="false">
                <span class="intel-section-guide-icon" aria-hidden="true">ℹ</span>
            </button>
            <span class="intel-section-guide-popover" role="tooltip">
                <button type="button" class="intel-section-guide-close" aria-label="Close guide" tabindex="0">×</button>
                ${escHtml(guide)}
            </span>
           </span>`
        : '';
    return `<div class="intel-section-head"><span class="intel-section-num">${num}</span><h3 class="intel-section-title">${title}</h3>${guideHtml}</div>`;
}

type TimelineEvidenceItem = { title?: string; url?: string; link?: string; domain?: string; type?: string };

function parseTimelineEvidencePayload(raw: string): TimelineEvidenceItem[] {
    if (!raw) return [];
    try {
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function normalizeTimelineEvidenceList(items: TimelineEvidenceItem[]): TimelineEvidenceItem[] {
    return items
        .map((item) => {
            const url = item.url || item.link;
            const title = item.title || 'Source Signal';
            const domain = item.domain || item.type || 'OSINT';
            return url ? { title, url, domain } : { title, domain };
        })
        .filter((item) => item.title || item.url);
}

function mergeTimelineEvidence(
    primary: TimelineEvidenceItem[],
    fallback: TimelineEvidenceItem[],
): TimelineEvidenceItem[] {
    const merged = normalizeTimelineEvidenceList(primary);
    if (merged.length > 0) return merged;
    return normalizeTimelineEvidenceList(fallback);
}

async function openTimelineEvidence(
    alertId: string,
    embeddedSourcesJson: string,
    sourceUrl: string,
    title: string,
): Promise<void> {
    const embedded = normalizeTimelineEvidenceList(parseTimelineEvidencePayload(embeddedSourcesJson));
    const urlFallback: TimelineEvidenceItem[] = sourceUrl
        ? [{ title: title || 'Timeline source', url: sourceUrl, domain: 'OSINT' }]
        : title
          ? [{ title, domain: 'OSINT' }]
          : [];

    if (alertId) {
        try {
            const alert = await fetchAlert(alertId);
            const modalTitle = resolveAlertHeadline(alert).text || alert.target_label || title;
            const fromAlert = (alert.evidence_list || []) as TimelineEvidenceItem[];
            const alertUrlFallback: TimelineEvidenceItem[] = alert.source_url
                ? [{ title: modalTitle, url: alert.source_url, domain: 'OSINT' }]
                : [];
            const evidence = mergeTimelineEvidence(
                fromAlert,
                mergeTimelineEvidence(embedded, mergeTimelineEvidence(urlFallback, alertUrlFallback)),
            );
            showEvidenceModal(modalTitle, evidence);
            return;
        } catch (err) {
            console.warn('Timeline alert fetch failed, using embedded timeline sources', err);
        }
    }

    const evidence = mergeTimelineEvidence(embedded, urlFallback);
    if (evidence.length > 0) {
        showEvidenceModal(title || 'Timeline event', evidence);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Systemic Fragility: async comet-tail painter
// ─────────────────────────────────────────────────────────────────────────────
function paintSFCometTail(
    svgEl: SVGSVGElement,
    series: Array<{ timestamp: string; entropy_index: number; viscosity_coefficient: number; label?: string }>,
): void {
    const layerSelector = svgEl.querySelector('.sf-comet-layer');
    if (!layerSelector) return;

    const NS = 'http://www.w3.org/2000/svg';
    const pts = series
        .filter(p => typeof p.entropy_index === 'number' && typeof p.viscosity_coefficient === 'number')
        .map(p => ({
            x: sfToX(p.entropy_index),
            y: sfToY(p.viscosity_coefficient),
            ts: p.timestamp,
            e: p.entropy_index,
            v: p.viscosity_coefficient,
            label: p.label || '',
        }));

    if (pts.length === 0) return;

    const n = pts.length;
    const frag = document.createDocumentFragment();

    // ── Line segments: oldest→newest, opacity ramps from 0.08 → 0.75 ──────
    for (let i = 0; i < n - 1; i++) {
        const t1 = n === 1 ? 1 : (i + 1) / (n - 1);
        const opacity = 0.08 + t1 * 0.67;           // trailing opacity of the segment end
        // Width also ramps: 0.8px → 2px
        const strokeW = (0.8 + t1 * 1.2).toFixed(2);

        const line = document.createElementNS(NS, 'line');
        line.setAttribute('x1', pts[i].x.toFixed(2));
        line.setAttribute('y1', pts[i].y.toFixed(2));
        line.setAttribute('x2', pts[i + 1].x.toFixed(2));
        line.setAttribute('y2', pts[i + 1].y.toFixed(2));
        line.setAttribute('stroke', '#7dd3fc');
        line.setAttribute('stroke-width', strokeW);
        line.setAttribute('stroke-opacity', opacity.toFixed(3));
        line.setAttribute('stroke-linecap', 'round');
        frag.appendChild(line);
    }

    // ── Historical point dots with SVG title tooltips ─────────────────────
    for (let i = 0; i < n; i++) {
        const t = n === 1 ? 0.5 : i / (n - 1);
        const dotOpacity = (0.06 + t * 0.44).toFixed(3);
        const r = (1.5 + t * 1.5).toFixed(2);
        const p = pts[i];

        const circle = document.createElementNS(NS, 'circle');
        circle.setAttribute('cx', p.x.toFixed(2));
        circle.setAttribute('cy', p.y.toFixed(2));
        circle.setAttribute('r', r);
        circle.setAttribute('fill', '#7dd3fc');
        circle.setAttribute('fill-opacity', dotOpacity);
        circle.setAttribute('stroke', '#7dd3fc');
        circle.setAttribute('stroke-width', '0.5');
        circle.setAttribute('stroke-opacity', (parseFloat(dotOpacity) * 1.5).toFixed(3));

        // Native SVG tooltip — auditable by hovering
        const title = document.createElementNS(NS, 'title');
        const tsLabel = (() => {
            try {
                return new Date(p.ts).toLocaleString(undefined, {
                    month: 'short', day: 'numeric',
                    hour: '2-digit', minute: '2-digit',
                });
            } catch { return p.ts; }
        })();
        title.textContent = `${tsLabel}\nH=${p.e.toFixed(4)}  ν=${p.v.toFixed(4)}${p.label ? '\n' + p.label : ''}`;
        circle.appendChild(title);

        frag.appendChild(circle);
    }

    layerSelector.appendChild(frag);
}

function injectFragilityHistory(
    container: HTMLElement,
    domainId: string,
): void {
    const safeId = domainId.replace(/[^a-z0-9]/gi, '_');
    const svgEl = container.querySelector(`#sf-phase-svg-${safeId}`) as SVGSVGElement | null;
    if (!svgEl) return;

    fetchFragilityHistory(domainId, 7).then(history => {
        if (!history || !Array.isArray(history.series) || history.series.length === 0) return;

        // Save history to state/variable for the Time Machine later
        (window as any).__fragilityHistory = history;

        // Sort chronologically (oldest first) so the tail builds left-to-right
        const sorted = [...history.series].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
        paintSFCometTail(svgEl, sorted);
    }).catch(err => console.error("[SpatialContagion] History fetch failed:", err));
}
function wireProBriefInteractions(root: HTMLElement): void {
    root.querySelectorAll('.intel-section-guide').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const wrap = btn.closest('.intel-section-guide-wrap');
            const pop = wrap?.querySelector('.intel-section-guide-popover');
            if (!pop) return;
            const wasOpen = pop.classList.contains('is-open');
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

    root.querySelectorAll('.intel-section-guide-close').forEach((closeBtn) => {
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const pop = closeBtn.closest('.intel-section-guide-popover');
            if (!pop) return;
            pop.classList.remove('is-open');
            pop.closest('.intel-section-guide-wrap')?.querySelector('.intel-section-guide')?.setAttribute('aria-expanded', 'false');
        });
    });

    root.querySelectorAll('.intel-tl-item--actionable').forEach((row) => {
        const el = row as HTMLElement;
        const handler = () => {
            void openTimelineEvidence(
                el.dataset.alertId || '',
                el.dataset.evidenceSources || '',
                el.dataset.sourceUrl || '',
                el.dataset.timelineTitle || '',
            );
        };
        el.addEventListener('click', (e) => {
            e.stopPropagation();
            handler();
        });
        el.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                handler();
            }
        });
    });
}
function sc(s: string): string {
    const m: Record<string,string> = {confirming:'var(--success)',stress:'var(--danger)',mixed:'#d29922',divergent:'var(--danger)',limited:'var(--text-secondary)',elevated:'var(--danger)',medium:'#d29922',low:'var(--text-secondary)',high:'var(--success)',neutral:'var(--accent)',unavailable:'var(--text-secondary)',easing:'#58a6ff',resilient:'var(--success)',risk_on:'var(--success)',flight_to_safety:'#d29922',inflationary:'var(--danger)',deflationary:'#58a6ff',usd_strength:'#d29922',usd_weakness:'#58a6ff',strong:'var(--success)',moderate:'#d29922'};
    return m[s?.toLowerCase()]||'var(--text-secondary)';
}
function covDot(level: string): string {
    const c = level==='high'?'var(--success)':level==='medium'?'#d29922':'var(--danger)';
    return `<span class="intel-cov-dot" style="background:${c};"></span>${level.toUpperCase()}`;
}
function roleBadge(role: string): string {
    const c: Record<string,string> = {
        trigger:'#f85149',
        escalation:'#d29922',
        confirmation:'#3fb950',
        context:'#8b949e',
        market_reaction:'#58a6ff',
        background:'#6e7681',
    };
    const key = (role || 'context').toLowerCase();
    return `<span class="intel-role-badge" style="border-color:${c[key]||'#8b949e'};color:${c[key]||'#8b949e'};">${key.replace(/_/g,' ')}</span>`;
}
function pctChip(symbol: string, pct: number|null): string {
    if (pct == null) return `<span class="intel-mover-chip intel-mover--na">${symbol} N/A</span>`;
    const cls = pct > 0.1 ? 'intel-mover--pos' : pct < -0.1 ? 'intel-mover--neg' : 'intel-mover--flat';
    return `<span class="intel-mover-chip ${cls}">${symbol} ${pct>0?'+':''}${pct.toFixed(2)}%</span>`;
}

type QuantNarrativePayload = Partial<Record<
    'executive_thesis' | 'ground_zero_drag' | 'smart_money_flow' | 'contagion_timeline' | 'market_translation',
    string
>>;

function normalizeQuantNarrative(raw: any): QuantNarrativePayload {
    if (!raw) return {};
    if (typeof raw === 'string') {
        try {
            return normalizeQuantNarrative(JSON.parse(raw));
        } catch {
            return {};
        }
    }
    if (typeof raw !== 'object') return {};
    const out: QuantNarrativePayload = {};
    (['executive_thesis', 'ground_zero_drag', 'smart_money_flow', 'contagion_timeline', 'market_translation'] as const).forEach((key) => {
        const val = raw[key];
        if (typeof val === 'string' && val.trim()) out[key] = val.trim();
    });
    return out;
}

function renderQuantNarrativeSection(raw: any, fallbackSummary: string, keyFindings: string[], sectionNum: string): string {
    const narrative = normalizeQuantNarrative(raw);
    const cards = [
        ['executive_thesis', 'Executive Thesis', 'TL;DR'] as const,
        ['ground_zero_drag', 'Ground-Zero Drag', 'Choke Point'] as const,
        ['smart_money_flow', 'Smart-Money Flow', 'Divergence'] as const,
        ['contagion_timeline', 'Contagion Timeline', 'Lead-Lag'] as const,
        ['market_translation', 'Market Translation', 'Strategy'] as const,
    ].filter(([key]) => narrative[key]);

    if (!cards.length) {
        return `<div class="intel-panel">${sh(sectionNum,'Executive Summary', '01')}<p class="intel-body-text">${escHtml(fallbackSummary)}</p>${keyFindings.length ? `<div style="margin-top:1rem;"><span class="intel-sig-label">Key Findings</span><ul style="margin:0.4rem 0 0;padding-left:1.2rem;">${keyFindings.map((f:string)=>`<li style="font-size:0.85rem;color:var(--text-primary);padding:0.15rem 0;">${escHtml(f)}</li>`).join('')}</ul></div>`:''}</div>`;
    }

    return `<div class="intel-panel intel-quant-narrative">${sh(sectionNum, 'Senior Quant Analyst Narrative', '01')}
        <p class="intel-panel-intro">LLM-generated 5-part narrative grounded in computed divergence, cascade, lead-lag, market, and signal-intensity data. The chronological source trail remains preserved in the appendix.</p>
        <div class="intel-narrative-grid">
            ${cards.map(([key, title, kicker]) => `<article class="intel-narrative-card">
                <div class="intel-narrative-kicker"><span>${escHtml(kicker)}</span></div>
                <h4 style="margin:0 0 0.45rem;color:#f8fafc;font-size:0.95rem;">${escHtml(title)}</h4>
                <p class="intel-narrative-body">${escHtml(narrative[key] || '')}</p>
            </article>`).join('')}
        </div>
    </div>`;
}

// ── Systemic Fragility SVG layout constants (shared between render + async tail painter)
const SF_SVG_W = 280;
const SF_SVG_H = 200;
const SF_SVG_PAD = { t: 18, r: 18, b: 38, l: 48 };
function sfPlotW() { return SF_SVG_W - SF_SVG_PAD.l - SF_SVG_PAD.r; }
function sfPlotH() { return SF_SVG_H - SF_SVG_PAD.t - SF_SVG_PAD.b; }
function sfToX(e: number): number { return SF_SVG_PAD.l + (Math.min(Math.max(e, 0), 1)) * sfPlotW(); }
function sfToY(v: number): number { return SF_SVG_PAD.t + sfPlotH() - (Math.min(v, SF_VISCOSITY_MAX) / SF_VISCOSITY_MAX) * sfPlotH(); }
// ----------------------------------------------------------------
// Systemic Fragility Gauge / Phase Space
// ----------------------------------------------------------------
type SystemicFragilityPayload = {
    entropy_index: number;
    viscosity_coefficient: number;
    entropy_critical?: boolean;
    viscosity_critical?: boolean;
    phase_transition_warning: boolean;
    entropy_threshold?: number;
    viscosity_threshold?: number;
    label: string;
    rationale?: string;
};

const SF_ENTROPY_THRESHOLD = 0.85;
const SF_VISCOSITY_THRESHOLD = 0.10;
const SF_VISCOSITY_MAX = 0.50; // display ceiling for the gauge

function normalizeSystemicFragility(raw: any): SystemicFragilityPayload | null {
    if (!raw || typeof raw !== 'object') return null;
    if (raw.label === 'INSUFFICIENT DATA') return null;
    const e = typeof raw.entropy_index === 'number' ? raw.entropy_index : null;
    const v = typeof raw.viscosity_coefficient === 'number' ? raw.viscosity_coefficient : null;
    if (e === null || v === null) return null;
    return {
        entropy_index: e,
        viscosity_coefficient: v,
        entropy_critical: !!raw.entropy_critical,
        viscosity_critical: !!raw.viscosity_critical,
        phase_transition_warning: !!raw.phase_transition_warning,
        entropy_threshold: typeof raw.entropy_threshold === 'number' ? raw.entropy_threshold : SF_ENTROPY_THRESHOLD,
        viscosity_threshold: typeof raw.viscosity_threshold === 'number' ? raw.viscosity_threshold : SF_VISCOSITY_THRESHOLD,
        label: typeof raw.label === 'string' ? raw.label : 'STABLE',
        rationale: typeof raw.rationale === 'string' ? raw.rationale : '',
    };
}

function renderSystemicFragilitySection(raw: any, sectionNum: string, domainId = 'unknown'): string {
    const sf = normalizeSystemicFragility(raw);
    if (!sf) return '';

    const label = sf.label.toUpperCase();
    const isPhaseTransition = sf.phase_transition_warning || label.includes('PHASE TRANSITION');
    const isWarning = label.includes('CHOKING') || label.includes('ELEVATED');

    // Accent palette
    const accent = isPhaseTransition ? '#ef4444'
        : isWarning            ? '#f59e0b'
        : '#22d3ee';
    const accentGlow = isPhaseTransition ? 'rgba(239,68,68,0.35)'
        : isWarning            ? 'rgba(245,158,11,0.28)'
        : 'rgba(34,211,238,0.22)';
    const accentBg = isPhaseTransition ? 'rgba(239,68,68,0.12)'
        : isWarning            ? 'rgba(245,158,11,0.10)'
        : 'rgba(34,211,238,0.08)';

    const panelClass = isPhaseTransition
        ? 'intel-panel intel-sf-panel intel-sf-panel--critical'
        : isWarning
            ? 'intel-panel intel-sf-panel intel-sf-panel--warning'
            : 'intel-panel intel-sf-panel';

    // Label badge
    const labelBadge = `<span class="sf-label-badge" style="color:${accent};background:${accentBg};border-color:${accent};box-shadow:0 0 10px ${accentGlow};">${isPhaseTransition ? '&#x26A0;&#xFE0F; ' : ''}${escHtml(label)}</span>`;

    // ── Dual Gauge ──────────────────────────────────────────────────
    // Entropy gauge: 0→1, threshold at SF_ENTROPY_THRESHOLD
    const eThr = sf.entropy_threshold ?? SF_ENTROPY_THRESHOLD;
    const vThr = sf.viscosity_threshold ?? SF_VISCOSITY_THRESHOLD;
    const ePct = Math.min(sf.entropy_index * 100, 100);
    const eThrPct = eThr * 100;
    const vRaw = sf.viscosity_coefficient;
    const vPct = Math.min(vRaw / SF_VISCOSITY_MAX * 100, 100);
    const vThrPct = vThr / SF_VISCOSITY_MAX * 100;

    const eColor = sf.entropy_critical ? '#ef4444' : sf.entropy_index > eThr * 0.7 ? '#f59e0b' : '#22d3ee';
    const vColor = sf.viscosity_critical ? '#ef4444' : sf.viscosity_coefficient > vThr * 0.7 ? '#f59e0b' : '#22d3ee';

    const gauge = (label: string, symbol: string, value: number, pct: number, thrPct: number, color: string, isCritical: boolean, unit: string) =>
        `<div class="sf-gauge">
            <div class="sf-gauge-header">
                <span class="sf-gauge-symbol">${symbol}</span>
                <span class="sf-gauge-label">${escHtml(label)}</span>
                <span class="sf-gauge-value" style="color:${color};${isCritical ? `text-shadow:0 0 10px ${color};` : ''}">${value.toFixed(3)}<span class="sf-gauge-unit">${unit}</span></span>
            </div>
            <div class="sf-bar-track">
                <div class="sf-bar-fill" style="width:${pct}%;background:${color};box-shadow:0 0 8px ${color}40;${isCritical ? `animation:sf-bar-pulse 1.8s ease-in-out infinite;` : ''}"></div>
                <div class="sf-bar-threshold" style="left:${thrPct}%;" title="Critical threshold: ${thrPct.toFixed(0)}%">
                    <span class="sf-thr-label">CRIT</span>
                </div>
            </div>
            <div class="sf-gauge-sublabel">${isCritical ? '<span style="color:#ef4444;font-weight:700;">&#x25CF; CRITICAL</span>' : '<span style="color:#475569;">Within bounds</span>'}</div>
        </div>`;

    const dualGauge = `<div class="sf-dual-gauge">
        ${gauge('Network Entropy', 'H', sf.entropy_index, ePct, eThrPct, eColor, !!sf.entropy_critical, '')}
        ${gauge('Kinematic Viscosity', '\u03BD', vRaw, vPct, vThrPct, vColor, !!sf.viscosity_critical, '')}
    </div>`;

    // ── 2-D Phase Space SVG ─────────────────────────────────────────
    // X = entropy (0→1), Y = viscosity (0→SF_VISCOSITY_MAX, inverted so high = top)
    const svgW = 280; const svgH = 200;
    const pad = { t: 18, r: 18, b: 38, l: 48 };
    const plotW = svgW - pad.l - pad.r;
    const plotH = svgH - pad.t - pad.b;

    const toX = (e: number) => pad.l + (e / 1) * plotW;
    const toY = (v: number) => pad.t + plotH - (Math.min(v, SF_VISCOSITY_MAX) / SF_VISCOSITY_MAX) * plotH;

    const dotX = toX(sf.entropy_index);
    const dotY = toY(sf.viscosity_coefficient);
    const thrX = toX(eThr);
    const thrY = toY(vThr);

    // Critical zone (top-right quadrant above both thresholds)
    const czX = thrX; const czY = pad.t;
    const czW = pad.l + plotW - czX; const czH = thrY - czY;

    // Axis labels: entropy X (0, 0.5, 1.0), viscosity Y (0, 0.1, 0.25, 0.5)
    const xTicks = [0, 0.25, 0.5, 0.75, 1.0];
    const yTicks = [0, 0.10, 0.25, 0.50];

    const sfSvgId = `sf-phase-svg-${domainId.replace(/[^a-z0-9]/gi, '_')}`;
    const svg = `<svg id="${sfSvgId}" class="sf-phase-space" viewBox="0 0 ${svgW} ${svgH}" xmlns="http://www.w3.org/2000/svg" aria-label="Phase Space: Entropy vs Viscosity">
        <defs>
            <radialGradient id="sfDotGrad" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stop-color="${accent}" stop-opacity="1"/>
                <stop offset="100%" stop-color="${accent}" stop-opacity="0.2"/>
            </radialGradient>
        </defs>
        <!-- Grid -->
        <rect x="${pad.l}" y="${pad.t}" width="${plotW}" height="${plotH}" fill="rgba(15,23,42,0.6)" rx="4"/>
        <!-- Critical zone highlight -->
        ${czW > 0 && czH > 0 ? `<rect x="${czX}" y="${czY}" width="${czW}" height="${czH}" fill="rgba(239,68,68,0.08)" stroke="rgba(239,68,68,0.25)" stroke-width="0.5"/>` : ''}
        <!-- Grid lines -->
        ${xTicks.slice(1,-1).map(t => `<line x1="${toX(t)}" y1="${pad.t}" x2="${toX(t)}" y2="${pad.t+plotH}" stroke="rgba(255,255,255,0.05)" stroke-width="1"/>`).join('')}
        ${yTicks.slice(1).map(t => `<line x1="${pad.l}" y1="${toY(t)}" x2="${pad.l+plotW}" y2="${toY(t)}" stroke="rgba(255,255,255,0.05)" stroke-width="1"/>`).join('')}
        <!-- Threshold lines -->
        <line x1="${thrX}" y1="${pad.t}" x2="${thrX}" y2="${pad.t+plotH}" stroke="#ef4444" stroke-width="1" stroke-dasharray="4 3" opacity="0.6"/>
        <line x1="${pad.l}" y1="${thrY}" x2="${pad.l+plotW}" y2="${thrY}" stroke="#ef4444" stroke-width="1" stroke-dasharray="4 3" opacity="0.6"/>
        <!-- Threshold labels -->
        <text x="${thrX+3}" y="${pad.t+10}" fill="#ef4444" font-size="7" opacity="0.8">H=${eThr}</text>
        <text x="${pad.l+3}" y="${thrY-3}" fill="#ef4444" font-size="7" opacity="0.8">\u03BD=${vThr}</text>
        <!-- Axes -->
        <line x1="${pad.l}" y1="${pad.t+plotH}" x2="${pad.l+plotW}" y2="${pad.t+plotH}" stroke="rgba(148,163,184,0.3)" stroke-width="1"/>
        <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${pad.t+plotH}" stroke="rgba(148,163,184,0.3)" stroke-width="1"/>
        <!-- X axis ticks & labels -->
        ${xTicks.map(t => `<text x="${toX(t)}" y="${pad.t+plotH+12}" fill="#64748b" font-size="8" text-anchor="middle">${t}</text>`).join('')}
        <!-- Y axis ticks & labels -->
        ${yTicks.map(t => `<text x="${pad.l-5}" y="${toY(t)+3}" fill="#64748b" font-size="8" text-anchor="end">${t}</text>`).join('')}
        <!-- Axis titles -->
        <text x="${pad.l+plotW/2}" y="${svgH-2}" fill="#94a3b8" font-size="9" text-anchor="middle">Entropy H</text>
        <text x="10" y="${pad.t+plotH/2}" fill="#94a3b8" font-size="9" text-anchor="middle" transform="rotate(-90,10,${pad.t+plotH/2})">\u03BD</text>
        <!-- Comet tail layer (populated asynchronously) -->
        <g id="sf-comet-${sfSvgId}" class="sf-comet-layer"></g>
        <!-- Current state dot glow -->
        ${isPhaseTransition ? `<circle cx="${dotX}" cy="${dotY}" r="14" fill="${accent}" opacity="0.12" class="sf-dot-pulse-outer"/>` : ''}
        <circle cx="${dotX}" cy="${dotY}" r="8" fill="${accent}" opacity="0.22"/>
        <circle cx="${dotX}" cy="${dotY}" r="5" fill="url(#sfDotGrad)"/>
        <circle cx="${dotX}" cy="${dotY}" r="5" fill="none" stroke="${accent}" stroke-width="1.2" opacity="0.9"/>
    </svg>`;

    // ── Rationale terminal ───────────────────────────────────────────
    const rationale = sf.rationale
        ? `<div class="sf-terminal">
            <div class="sf-terminal-header">
                <span class="sf-terminal-dot"></span><span class="sf-terminal-dot"></span><span class="sf-terminal-dot"></span>
                <span class="sf-terminal-title">FRAGILITY_ENGINE // PHYSICS RATIONALE</span>
            </div>
            <div class="sf-terminal-body">
                <span class="sf-terminal-prompt">&#x276F;&#x276F; </span><span class="sf-terminal-out">${escHtml(sf.rationale)}</span>
            </div>
          </div>`
        : '';

    return `<div class="${panelClass}" style="--sf-accent:${accent};--sf-glow:${accentGlow};">
        ${sh(sectionNum, 'Systemic Fragility Engine')}
        <p class="intel-panel-intro">Real-time Shannon network entropy (H) and kinematic viscosity (\u03BD) computed over cross-asset volatility distribution. Phase-transition warning fires when both components simultaneously breach critical thresholds.</p>
        <div class="sf-status-row">${labelBadge}<span class="sf-conjunction-label">${sf.entropy_critical && sf.viscosity_critical ? '<span style="color:#ef4444;font-weight:700;">&#x26A0; BOTH COMPONENTS CRITICAL</span>' : sf.entropy_critical ? '<span style="color:#f59e0b;">H Critical</span>' : sf.viscosity_critical ? '<span style="color:#f59e0b;">\u03BD Critical</span>' : '<span style="color:#22d3ee;">System Nominal</span>'}</span></div>
        <div class="sf-main-layout">
            <div class="sf-gauges-col">${dualGauge}</div>
            <div class="sf-phase-col">${svg}</div>
        </div>
        ${rationale}
    </div>`;
}
// ----------------------------------------------------------------
// Wargaming & Probability Matrix
// ----------------------------------------------------------------
type WargamingScenario = {
    title: string;
    probability_pct: number;
    description: string;
    projected_timeline: string;
};

function normalizeWargaming(raw: any): WargamingScenario[] {
    if (!Array.isArray(raw)) return [];
    const out: WargamingScenario[] = [];
    for (const item of raw) {
        if (!item || typeof item !== 'object') continue;
        const title = typeof item.title === 'string' ? item.title.trim() : '';
        if (!title) continue;
        const pct = typeof item.probability_pct === 'number'
            ? Math.round(item.probability_pct)
            : parseInt(String(item.probability_pct ?? 0), 10) || 0;
        out.push({
            title,
            probability_pct: pct,
            description: typeof item.description === 'string' ? item.description.trim() : '',
            projected_timeline: typeof item.projected_timeline === 'string' ? item.projected_timeline.trim() : '',
        });
    }
    return out.slice(0, 3);
}

function renderWargamingSection(raw: any, sectionNum: string): string {
    const scenarios = normalizeWargaming(raw);
    if (!scenarios.length) return '';

    const scenarioPalette = (title: string): { accent: string; glow: string; barColor: string; badge: string } => {
        const t = title.toLowerCase();
        if (t.includes('black swan') || t.includes('tail')) {
            return { accent: '#ef4444', glow: 'rgba(239,68,68,0.25)', barColor: '#ef4444', badge: 'wargame-badge--crimson' };
        }
        if (t.includes('escalat') || t.includes('risk')) {
            return { accent: '#f59e0b', glow: 'rgba(245,158,11,0.22)', barColor: '#f59e0b', badge: 'wargame-badge--amber' };
        }
        return { accent: '#22d3ee', glow: 'rgba(34,211,238,0.18)', barColor: '#22d3ee', badge: 'wargame-badge--cyan' };
    };

    const cards = scenarios.map((s) => {
        const pal = scenarioPalette(s.title);
        const pct = Math.max(0, Math.min(100, s.probability_pct));
        return `<div class="wargame-card" style="--wg-accent:${pal.accent};--wg-glow:${pal.glow};">
            <div class="wargame-card-header">
                <span class="wargame-badge ${pal.badge}">${escHtml(s.title)}</span>
                <div class="wargame-prob-wrap">
                    <span class="wargame-prob-num">${pct}<span class="wargame-prob-sym">%</span></span>
                    <div class="wargame-bar-track">
                        <div class="wargame-bar-fill" style="width:${pct}%;background:${pal.barColor};box-shadow:0 0 8px ${pal.glow};"></div>
                    </div>
                </div>
            </div>
            <p class="wargame-desc">${escHtml(s.description)}</p>
            <div class="wargame-timeline-row">
                <span class="wargame-timeline-label">Projected Horizon</span>
                <span class="wargame-timeline-val">${escHtml(s.projected_timeline)}</span>
            </div>
        </div>`;
    }).join('');

    return `<div class="intel-panel intel-wargaming-panel">${sh(sectionNum, 'Wargaming & Probability Matrix')}
        <p class="intel-panel-intro">Probabilistic scenario analysis derived from current structural signals, cascading impact tiers, and divergence conditions. Three mutually exclusive scenarios covering the full probability space.</p>
        <div class="wargame-grid">${cards}</div>
    </div>`;
}
// ----------------------------------------------------------------
// Information Integrity & PsyOps Assessment
// ----------------------------------------------------------------
type InformationIntegrity = {
    psyops_risk_level: 'LOW' | 'MEDIUM' | 'HIGH';
    rhetoric_vs_reality_divergence: boolean;
    assessment_text: string;
};

function normalizeInfoIntegrity(raw: any): InformationIntegrity | null {
    if (!raw || typeof raw !== 'object') return null;
    const levels = ['LOW', 'MEDIUM', 'HIGH'] as const;
    const lvlRaw = typeof raw.psyops_risk_level === 'string'
        ? raw.psyops_risk_level.toUpperCase().trim()
        : 'LOW';
    const level = (levels.includes(lvlRaw as any) ? lvlRaw : 'LOW') as 'LOW' | 'MEDIUM' | 'HIGH';
    const div = typeof raw.rhetoric_vs_reality_divergence === 'boolean'
        ? raw.rhetoric_vs_reality_divergence
        : String(raw.rhetoric_vs_reality_divergence || '').toLowerCase() === 'true';
    const text = typeof raw.assessment_text === 'string' ? raw.assessment_text.trim() : '';
    if (!text) return null;
    return { psyops_risk_level: level, rhetoric_vs_reality_divergence: div, assessment_text: text };
}

function renderInformationIntegrity(raw: any, sectionNum: string): string {
    const ii = normalizeInfoIntegrity(raw);
    if (!ii) return '';

    const lvlPalette: Record<string, { color: string; bg: string; border: string; glow: string }> = {
        LOW:    { color: '#22d3ee', bg: 'rgba(34,211,238,0.08)',  border: 'rgba(34,211,238,0.25)',  glow: 'rgba(34,211,238,0.3)' },
        MEDIUM: { color: '#f59e0b', bg: 'rgba(245,158,11,0.10)', border: 'rgba(245,158,11,0.30)',  glow: 'rgba(245,158,11,0.3)' },
        HIGH:   { color: '#e879f9', bg: 'rgba(232,121,249,0.10)', border: 'rgba(232,121,249,0.35)', glow: 'rgba(232,121,249,0.4)' },
    };
    const pal = lvlPalette[ii.psyops_risk_level] || lvlPalette.LOW;
    const isDivergent = ii.rhetoric_vs_reality_divergence;
    const panelClass = isDivergent
        ? 'intel-panel intel-psyops-panel intel-psyops-panel--alert'
        : 'intel-panel intel-psyops-panel';

    const warningBadge = isDivergent
        ? `<div class="psyops-warning-badge" role="alert">
               <span class="psyops-glitch" data-text="&#x1F3AD; PSYOPS WARNING: RHETORIC/REALITY DIVERGENCE DETECTED">&#x1F3AD; PSYOPS WARNING: RHETORIC/REALITY DIVERGENCE DETECTED</span>
           </div>`
        : '';

    const lvlDotClass = `psyops-dot psyops-dot--${ii.psyops_risk_level.toLowerCase()}`;

    return `<div class="${panelClass}">${sh(sectionNum, 'Information Integrity & PsyOps Assessment')}
        <p class="intel-panel-intro">Measures divergence between official/state-media rhetoric and independent physical evidence streams. Flags coordinated information operations that may be designed to manufacture market-moving panic.</p>
        ${warningBadge}
        <div class="psyops-body">
            <div class="psyops-risk-row">
                <span class="psyops-risk-label">INFO-OPS RISK</span>
                <span class="psyops-risk-badge" style="color:${pal.color};background:${pal.bg};border-color:${pal.border};box-shadow:0 0 10px ${pal.glow};">
                    <span class="${lvlDotClass}"></span>${ii.psyops_risk_level}
                </span>
                <span class="psyops-divergence-indicator" style="color:${isDivergent ? '#e879f9' : '#22d3ee'};">
                    ${isDivergent ? '&#x26A0; DIVERGENCE: TRUE' : '&#x2713; DIVERGENCE: FALSE'}
                </span>
            </div>
            <div class="psyops-terminal">
                <div class="psyops-terminal-header">
                    <span class="psyops-terminal-dot"></span>
                    <span class="psyops-terminal-dot"></span>
                    <span class="psyops-terminal-dot"></span>
                    <span class="psyops-terminal-title">OSINT_INTEGRITY_ENGINE v2 // ASSESSMENT OUTPUT</span>
                </div>
                <div class="psyops-terminal-body">
                    <span class="psyops-prompt">&#x276F;&#x276F; </span><span class="psyops-output">${escHtml(ii.assessment_text)}</span>
                </div>
            </div>
        </div>
    </div>`;
}
function renderEventTimelineAppendix(timeline: any[]): string {
    const tlItems = timeline.length > 0
        ? timeline
        : [{ type: 'context', title: 'Timeline synchronizing - check back after the next intelligence cycle.', timestamp: null }];

    return `<div class="intel-panel intel-audit-appendix">${sh('APP', 'Appendix: Chronological Audit Trail')}
        <p class="intel-panel-intro">Immutable source sequence for auditability. Click any supported row to inspect the underlying evidence.</p>
        <div class="intel-timeline">${tlItems.map((ev: any) => {
            const tsLabel = ev.timestamp ? formatIntelPreciseTimestamp(ev.timestamp) : '';
            const alertId = ev.alert_id ? String(ev.alert_id) : '';
            const sourceUrl = ev.source_url ? String(ev.source_url) : '';
            const supporting = Array.isArray(ev.supporting_sources) && ev.supporting_sources.length
                ? ev.supporting_sources
                : sourceUrl || ev.title
                  ? [{
                      title: ev.title || 'Timeline event',
                      url: sourceUrl || undefined,
                      domain: ev.source_name || ev.source || 'OSINT',
                  }]
                  : [];
            const actionable = !!(alertId || sourceUrl || supporting.length);
            const itemCls = actionable ? 'intel-tl-item intel-tl-item--actionable' : 'intel-tl-item';
            const evidenceJson = escAttr(JSON.stringify(supporting));
            const attrs = actionable
                ? ` role="button" tabindex="0" data-alert-id="${escAttr(alertId)}" data-source-url="${escAttr(sourceUrl)}" data-evidence-sources="${evidenceJson}" data-timeline-title="${escAttr(ev.title || '')}"`
                : '';
            return `<div class="${itemCls}"${attrs}><div class="intel-tl-dot"></div><div class="intel-tl-content"><div class="intel-tl-head">${roleBadge(ev.type || ev.role)}${tsLabel ? `<span class="intel-tl-time">${tsLabel}</span>` : ''}${ev.location_label ? `<span class="intel-tl-loc">Loc: ${escHtml(ev.location_label)}</span>` : ''}</div><div class="intel-tl-title">${escHtml(ev.title || '')}</div></div></div>`;
        }).join('')}</div>
    </div>`;
}

// overallCoverage is now computed in the payload (divergence_check.overall_coverage)

/**
 * Phase 7.4 — Composite Risk HUD.
 *
 * Renders a single Luminous Cryo-Glass plate directly under Section 01 that
 * exposes the four metrics the rest of the brief was previously hiding:
 *   • Composite Multiplier (Phase 7.4 cross-domain amplification)
 *   • Systemic Entropy (Shannon, 0..1)
 *   • Viscosity Coefficient (kinematic, 0..0.5 typical)
 *   • Phase Transition Warning (flashing when true)
 *
 * Below the metric grid we also show the tier-by-tier spillover path
 * sourced from `spatial_contagion.edges[].order_level`. If no live spatial
 * graph is present we fall back to the propagation_path string returned
 * by `compute_composite_multiplier`.
 *
 * Returns `''` if the payload has neither composite_risk_profile nor
 * systemic_fragility — so old briefs don't render an empty plate.
 */
function renderCompositeRiskHud(p: any): string {
    const composite = p?.composite_risk_profile;
    const fragility = p?.systemic_fragility;
    const spatial = p?.spatial_contagion;
    if (!composite && !fragility && !spatial) return '';

    const mult = Number(composite?.composite_multiplier ?? 1.0);
    const multCritical = mult >= 1.5;
    const path: string = composite?.primary_propagation_path
        || 'Stable (no cross-domain spillover)';

    const entropy = Number(fragility?.entropy_index ?? 0);
    const viscosity = Number(fragility?.viscosity_coefficient ?? 0);
    const phaseWarn = Boolean(fragility?.phase_transition_warning);

    // Tier breakdown from spatial edges by order_level.
    const edges: any[] = Array.isArray(spatial?.edges) ? spatial.edges : [];
    const tierCounts = { 1: 0, 2: 0, 3: 0 } as Record<number, number>;
    for (const e of edges) {
        const o = Number(e?.order_level ?? e?.target_order ?? 0);
        if (o === 1 || o === 2 || o === 3) tierCounts[o] += 1;
    }
    const hasTiers = (tierCounts[1] + tierCounts[2] + tierCounts[3]) > 0;

    const multColor = multCritical ? '#fca5a5' : '#7dd3fc';
    const multGlow = multCritical ? 'rgba(248,113,113,0.55)' : 'rgba(125,211,252,0.40)';
    const warnColor = phaseWarn ? '#fca5a5' : '#94a3b8';
    const warnGlow = phaseWarn ? 'rgba(248,113,113,0.55)' : 'transparent';

    // Tier propagation chip row — count of edges per order so the reader
    // can scan T1/T2/T3 distribution without opening the Omni-Monitor.
    const tierChips = hasTiers
        ? `<div class="crh-tiers">
            <span class="crh-tier crh-tier--t1">T1·Direct <b>${tierCounts[1]}</b></span>
            <span class="crh-tier-arrow">→</span>
            <span class="crh-tier crh-tier--t2">T2·Channels <b>${tierCounts[2]}</b></span>
            <span class="crh-tier-arrow">→</span>
            <span class="crh-tier crh-tier--t3">T3·Systemic <b>${tierCounts[3]}</b></span>
        </div>`
        : `<div class="crh-tiers crh-tiers--empty">No live cross-domain edges — Spatial Engine seeded with epicenter only.</div>`;

    return `
    <style>
        /* Scoped Cryo-Glass for the Pro Brief Composite Risk HUD. */
        .composite-risk-hud {
            position: relative;
            margin: 1.0rem 0 1.4rem;
            padding: 14px 18px 16px;
            border-radius: 14px;
            background: rgba(8, 13, 28, 0.82);
            backdrop-filter: blur(20px) saturate(180%);
            -webkit-backdrop-filter: blur(20px) saturate(180%);
            border: 1px solid transparent;
            box-shadow:
                0 20px 50px rgba(0, 0, 0, 0.65),
                inset 0 0 20px rgba(0, 242, 254, 0.05),
                inset 0 1px 0 rgba(255, 255, 255, 0.10);
            color: #e2e8f0;
            font-family: 'Inter', system-ui, sans-serif;
            font-variant-numeric: tabular-nums;
        }
        .composite-risk-hud::before {
            content: "";
            position: absolute; inset: 0;
            border-radius: inherit;
            padding: 1px;
            background: linear-gradient(135deg,
                rgba(255,255,255,0.28) 0%,
                rgba(125,211,252,0.12) 35%,
                rgba(0,242,254,0.32) 70%,
                rgba(255,255,255,0.10) 100%);
            -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
            -webkit-mask-composite: xor;
                    mask-composite: exclude;
            pointer-events: none;
        }
        .composite-risk-hud > * { position: relative; }
        .crh-head {
            display: flex; align-items: baseline; justify-content: space-between;
            font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
            color: #7dd3fc; font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
            margin-bottom: 10px;
        }
        .crh-head .crh-path {
            color: #cbd5e1; letter-spacing: 0.08em; font-weight: 700;
            text-shadow: 0 0 8px rgba(125,211,252,0.25);
        }
        .crh-grid {
            display: grid;
            grid-template-columns: 1.4fr 1fr 1fr 1.1fr;
            gap: 14px 22px;
            padding-bottom: 12px;
            border-bottom: 1px solid rgba(125,211,252,0.10);
        }
        .crh-cell { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
        .crh-k {
            font-size: 0.58rem; color: #64748b;
            text-transform: uppercase; letter-spacing: 0.11em; font-weight: 700;
            font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
        }
        .crh-v {
            font-size: 1.5rem; font-weight: 800; line-height: 1.05;
            font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
            font-variant-numeric: tabular-nums;
            letter-spacing: 0.01em;
        }
        .crh-v--sub {
            font-size: 1.05rem;
        }
        @keyframes crh-warn-flash {
            0%,100% { box-shadow: 0 0 14px rgba(248,113,113,0.45); }
            50%     { box-shadow: 0 0 28px rgba(248,113,113,0.85); }
        }
        .crh-v--phase-on {
            display: inline-block;
            padding: 2px 10px;
            border-radius: 999px;
            background: rgba(220,38,38,0.18);
            border: 1px solid rgba(248,113,113,0.55);
            font-size: 0.78rem;
            animation: crh-warn-flash 1.4s ease-in-out infinite;
        }
        .crh-tiers {
            display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
            margin-top: 12px;
            font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
            font-size: 0.70rem; letter-spacing: 0.06em;
        }
        .crh-tier {
            padding: 4px 10px; border-radius: 999px;
            background: rgba(15,23,42,0.55);
            border: 1px solid rgba(125,211,252,0.25);
            color: #cbd5e1;
        }
        .crh-tier b {
            color: #f1f5f9;
            font-variant-numeric: tabular-nums;
            margin-left: 4px;
            text-shadow: 0 0 6px rgba(125,211,252,0.35);
        }
        .crh-tier--t1 { border-color: rgba(248,113,113,0.55); color: #fecaca; }
        .crh-tier--t2 { border-color: rgba(251,191,36,0.55); color: #fde68a; }
        .crh-tier--t3 { border-color: rgba(125,211,252,0.55); color: #bae6fd; }
        .crh-tier-arrow { color: #64748b; font-weight: 800; }
        .crh-tiers--empty {
            color: #64748b; font-size: 0.66rem;
            font-style: italic; letter-spacing: 0.04em;
        }
    </style>
    <section class="composite-risk-hud" aria-label="Composite Risk Profile">
        <div class="crh-head">
            <span>◷ Composite Risk Profile · Phase 7.4</span>
            <span class="crh-path">${escHtml(path)}</span>
        </div>
        <div class="crh-grid">
            <div class="crh-cell">
                <span class="crh-k">Composite Multiplier</span>
                <span class="crh-v"
                      style="color:${multColor}; text-shadow: 0 0 12px ${multGlow};">
                    ${mult.toFixed(2)}x
                </span>
            </div>
            <div class="crh-cell">
                <span class="crh-k">Systemic Entropy</span>
                <span class="crh-v crh-v--sub" style="color:#e2e8f0;">
                    ${entropy.toFixed(3)}
                </span>
            </div>
            <div class="crh-cell">
                <span class="crh-k">Viscosity ν</span>
                <span class="crh-v crh-v--sub" style="color:#e2e8f0;">
                    ${viscosity.toFixed(3)}
                </span>
            </div>
            <div class="crh-cell">
                <span class="crh-k">Phase Transition</span>
                ${phaseWarn
                    ? `<span class="crh-v crh-v--sub crh-v--phase-on"
                            style="color:${warnColor}; text-shadow: 0 0 10px ${warnGlow};">⚡ WARNING</span>`
                    : `<span class="crh-v crh-v--sub" style="color:${warnColor};">STABLE</span>`
                }
            </div>
        </div>
        ${tierChips}
    </section>
    `;
}

function renderStructuredProBrief(report: ProStructuralReportItem, contentContainer: HTMLElement, domainClass: string) {
    const p = report.structured_payload;
    if (!p) return;
    ensureProV3Styles();
    const domainName = p.domain?.display_name || report.topic;
    const signal = p.signal || {};
    const execSummary = p.executive_summary || '';
    const sigClass = p.signal_classification || {};
    const timeline = p.event_timeline || [];
    const macro = p.structural_context?.macro_display_cards || p.structural_context?.macro_observations || [];
    const market = p.market_confirmation || {};
    const breakdown = market.breakdown || [];
    const divCheck = p.divergence_check || {};
    const unresolved: string[] = p.unresolved_signals || [];
    const watch = p.watch_indicators || [];
    const watchCond = p.watch_conditions || {};
    const flows = p.transmission_flow || [];
    const expMatrix = p.exposure_matrix || [];
    const interpretations = p.balanced_interpretations || {};
    const covMatrix = p.coverage_matrix || {};
    const geoCtx = p.geo_context || {};
    const notes = p.data_notes || {};
    const hasLocation = signal.location_lat != null && signal.location_lng != null;

    let html = `<div class="intel-report ${domainClass}">`;
    let sectionIndex = 1;
    const nextSectionNum = () => String(sectionIndex++).padStart(2, '0');

    // Hero
    html += `<div class="intel-hero">
        <div class="intel-hero-domain">${domainName}</div>
        <h1 class="intel-hero-title">${report.title}</h1>
        <div class="intel-hero-meta"><span>Generated: ${formatIntelDateTime(report.created_at)}</span>${signal.triggered_at?`<span>Triggered: ${formatIntelDateTime(signal.triggered_at)}</span>`:''}</div>
    </div>`;

    // Status Metric Cards (hero sub-bar) �?�Euses payload values
    const covLabel = (divCheck.overall_coverage || 'limited');
    html += `<div class="intel-status-bar">
        <div class="intel-status-card"><div class="intel-status-label">Structural Risk</div><div class="intel-status-val" style="color:${sc(divCheck.structural_risk)}">${(divCheck.structural_risk||'N/A').toUpperCase()}</div></div>
        <div class="intel-status-card"><div class="intel-status-label">Market Status</div><div class="intel-status-val" style="color:${sc(market.status)}">${(market.status||'N/A').toUpperCase()}</div></div>
        <div class="intel-status-card"><div class="intel-status-label">Data Coverage</div><div class="intel-status-val" style="color:${sc(covLabel)}">${covLabel.toUpperCase()}</div></div>
        <div class="intel-status-card"><div class="intel-status-label">Data Lag</div><div class="intel-status-val" style="color:${sc(divCheck.data_lag==='low'?'high':divCheck.data_lag==='high'?'low':'medium')}">${(divCheck.data_lag||'N/A').toUpperCase()}</div></div>
    </div>`;

    // 01 Senior Quant Analyst Narrative (LLM), with legacy summary fallback
    const keyFindings: string[] = p.key_findings || [];
    html += renderQuantNarrativeSection(p.llm_narrative, execSummary, keyFindings, nextSectionNum());

    // 01b Composite Risk HUD (Phase 7.4) — closes the Information Reflection
    // Gap by surfacing the cross-domain multiplier, systemic fragility, and
    // tier-by-tier spillover path immediately under the Hero/Narrative.
    html += renderCompositeRiskHud(p);

    // 02 Signal Classification
    if (sigClass.primary_type) {
        html += `<div class="intel-panel">${sh(nextSectionNum(),'Signal Classification', '02')}
            <div class="intel-sig-class"><div class="intel-sig-primary"><span class="intel-sig-label">Primary</span><span class="intel-sig-chip intel-sig-chip--primary">${sigClass.primary_type.replace(/_/g,' ')}</span></div>${(sigClass.secondary_types||[]).length?`<div class="intel-sig-secondary"><span class="intel-sig-label">Secondary</span><div class="intel-chip-row">${sigClass.secondary_types.map((t:string)=>`<span class="intel-sig-chip">${t.replace(/_/g,' ')}</span>`).join('')}</div></div>`:''}</div>
            <p class="intel-rationale">${sigClass.rationale||''}</p></div>`;
    }

    // 03 Geo Context
    html += `<div class="intel-panel">${sh(nextSectionNum(),'Geographic Context', '03')}`;
    if (hasLocation) {
        html += `<div class="intel-map-panel"><div id="pro-brief-minimap" class="pro-brief-mini-map"></div></div>`;
    }
    if (geoCtx.mentioned_regions && geoCtx.mentioned_regions.length > 0) {
        html += `<div style="margin-top:${hasLocation?'1rem':'0'};"><span class="intel-sig-label">Mentioned Regions</span><div class="intel-chip-row" style="margin-top:0.4rem;">${geoCtx.mentioned_regions.map((r:string)=>`<span class="intel-sig-chip">📍 ${r}</span>`).join('')}</div></div>`;
    }
    if (!hasLocation && (!geoCtx.mentioned_regions || geoCtx.mentioned_regions.length===0)) {
        html += `<p class="intel-body-text">Coordinates unavailable. No geographic regions could be inferred from available evidence.</p>`;
    }
    html += `<div style="margin-top:0.75rem;"><span class="intel-sig-label">Geo Confidence</span> <span class="intel-div-val" style="font-size:0.8rem;color:${sc(geoCtx.confidence==='coordinates'?'high':geoCtx.confidence==='inferred'?'medium':'low')}">${(geoCtx.confidence||'unavailable').toUpperCase()}</span></div></div>`;

    const timelineAppendixHtml = renderEventTimelineAppendix(timeline);

    // 04 Wargaming & Probability Matrix
    const wargamingRaw = (p.llm_narrative as any)?.scenario_wargaming;
    if (wargamingRaw && Array.isArray(wargamingRaw) && wargamingRaw.length > 0) {
        html += renderWargamingSection(wargamingRaw, nextSectionNum());
    }

    // 05 Information Integrity & PsyOps Assessment
    const infoIntegrityRaw = (p.llm_narrative as any)?.information_integrity;
    if (infoIntegrityRaw && typeof infoIntegrityRaw === 'object') {
        html += renderInformationIntegrity(infoIntegrityRaw, nextSectionNum());
    }

    // 06 Structural Impact & Transmission
    html += `<div class="intel-panel">${sh(nextSectionNum(),'Structural Impact & Transmission', '05')}${flows.length?`<div class="intel-transmission-flow">${flows.map((f:string,i:number)=>`<div class="flow-step">${f}</div>${i<flows.length-1?'<div class="flow-arrow">→</div>':''}`).join('')}</div>`:'<p class="intel-body-text">No specific transmission channels defined.</p>'}</div>`;

    // 06 Quantitative Context
    if (macro.length > 0) {
        html += `<div class="intel-panel">${sh(nextSectionNum(),'Quantitative Context', '06')}<div class="intel-metric-grid">${macro.slice(0,12).map((m:any)=>`<div class="intel-metric-card"><div class="metric-label">${m.display_name || m.series_id}</div>${m.display_name ? `<div style="font-size:0.65rem;color:var(--text-secondary);font-family:monospace;margin-bottom:0.25rem;">${m.series_id}</div>` : ''}<div class="metric-value">${m.latest_value??'N/A'}</div><div class="metric-change" style="color:${(m.change_pct||0)>0?'var(--success)':'var(--danger)'}">${(m.change_pct||0)>0?'+':''}${m.change_pct?m.change_pct.toFixed(2):'0.00'}%</div>${m.trend_meaning ? `<div style="font-size:0.7rem;color:var(--text-secondary);margin-top:0.35rem;line-height:1.3;">${m.trend_meaning}</div>` : ''}</div>`).join('')}</div></div>`;
    }

    // 07 Market Confirmation Breakdown + Real-Time Market Pulse
    // Derive movers directly from latest_prices for maximum fidelity.
    const latestPrices: any[] = market.latest_prices || [];
    const sigPosMvrs = latestPrices.filter((p: any) => (p.percent_change ?? 0) > 0.5)
        .sort((a: any, b: any) => (b.percent_change ?? 0) - (a.percent_change ?? 0));
    const sigNegMvrs = latestPrices.filter((p: any) => (p.percent_change ?? 0) < -0.5)
        .sort((a: any, b: any) => (a.percent_change ?? 0) - (b.percent_change ?? 0));
    const hasPulseMvrs = sigPosMvrs.length > 0 || sigNegMvrs.length > 0;
    const limitedInstr = typeof market.limited_instruments === 'number' ? market.limited_instruments : 0;

    // Supply-driven badge (energy domain only; bool from backend)
    const supplyDrivenBadge = market.supply_driven
        ? `<span class="intel-pulse-supply-badge">⚡ Supply-Driven Confirmation</span>`
        : '';

    // Render a single mover row: arrow glyph + symbol + asset class + price + pct
    const moverRow = (p: any, dir: 'pos'|'neg'): string => {
        const arrow   = dir === 'pos' ? '▲' : '▼';
        const cls     = dir === 'pos' ? 'intel-pulse-row--pos' : 'intel-pulse-row--neg';
        const pct     = p.percent_change != null ? `${p.percent_change > 0 ? '+' : ''}${p.percent_change.toFixed(2)}%` : 'N/A';
        const price   = p.latest_close  != null ? p.latest_close.toFixed(p.latest_close > 100 ? 2 : 4) : '—';
        const assetCl = (p.asset_class || 'instrument').replace(/_/g, ' ');
        const dateStr = p.latest_date ? `<span class="intel-pulse-date">${p.latest_date}</span>` : '';
        return `<div class="intel-pulse-row ${cls}">
            <span class="intel-pulse-arrow">${arrow}</span>
            <span class="intel-pulse-symbol">${escHtml(p.symbol)}</span>
            <span class="intel-pulse-asset">${escHtml(assetCl)}</span>
            <span class="intel-pulse-price">${price}</span>
            <span class="intel-pulse-pct">${pct}</span>
            ${dateStr}
        </div>`;
    };

    const pulseSection = hasPulseMvrs ? `
        <div class="intel-pulse-section">
            <div class="intel-pulse-header">
                <span class="intel-pulse-dot"></span>
                Real-Time Market Pulse
                ${supplyDrivenBadge}
                ${limitedInstr > 0 ? `<span class="intel-pulse-limited">${limitedInstr} instruments awaiting price data</span>` : ''}
            </div>
            ${sigPosMvrs.length > 0 ? `
                <div class="intel-pulse-group">
                    <div class="intel-pulse-group-label pos">Positive Movers — ${sigPosMvrs.length} instrument${sigPosMvrs.length > 1 ? 's' : ''} confirmed bid</div>
                    ${sigPosMvrs.map((p: any) => moverRow(p, 'pos')).join('')}
                </div>` : ''}
            ${sigNegMvrs.length > 0 ? `
                <div class="intel-pulse-group">
                    <div class="intel-pulse-group-label neg">Negative Movers — ${sigNegMvrs.length} instrument${sigNegMvrs.length > 1 ? 's' : ''} under pressure</div>
                    ${sigNegMvrs.map((p: any) => moverRow(p, 'neg')).join('')}
                </div>` : ''}
        </div>` : (latestPrices.length > 0
            ? `<div class="intel-pulse-section intel-pulse-section--flat">
                <span class="intel-pulse-dot intel-pulse-dot--flat"></span>
                <span>Market Pulse: All tracked instruments within ±0.5% threshold — no significant price reaction detected.</span>
                ${supplyDrivenBadge}
               </div>`
            : '');

    html += `<div class="intel-panel">${sh(nextSectionNum(),'Market Confirmation', '07')}
        <div class="intel-market-summary">
            <div class="intel-score-card"><div class="score-label">Status</div><div class="score-value" style="color:${sc(market.status)}">${market.status||'N/A'}</div></div>
            <div class="intel-score-card"><div class="score-label">↑ Positive</div><div class="score-value" style="color:var(--success)">${sigPosMvrs.length}</div></div>
            <div class="intel-score-card"><div class="score-label">↓ Negative</div><div class="score-value" style="color:var(--danger)">${sigNegMvrs.length}</div></div>
            <div class="intel-score-card"><div class="score-label">Tracking</div><div class="score-value" style="color:var(--text-secondary)">${latestPrices.length}</div></div>
        </div>
        ${pulseSection}
        ${breakdown.length?`<div class="intel-breakdown-grid">${breakdown.map((g:any)=>`<div class="intel-breakdown-card"><div class="intel-bd-head"><span class="intel-bd-group">${g.group}</span><span class="intel-bd-status" style="color:${sc(g.status)}">${(g.status||'').replace('_',' ')}</span></div>${g.description?`<div style="font-size:0.7rem;color:var(--text-secondary);margin-bottom:0.4rem;">${g.description}</div>`:''}<div class="intel-chip-row">${(g.instrument_details||[]).map((d:any)=>pctChip(d.symbol,d.percent_change)).join('')}</div></div>`).join('')}</div>`:''}</div>`;

    // 08 Systemic Fragility Engine
    if (p.systemic_fragility) {
        html += renderSystemicFragilitySection(p.systemic_fragility, nextSectionNum(), p.domain?.domain_id || 'unknown');
    }

    // 09 Divergence Check
    if (divCheck.interpretation) {
        html += `<div class="intel-panel intel-divergence-banner">${sh(nextSectionNum(),'Divergence Check', '08')}
            <div class="intel-div-grid">
                <div class="intel-div-item"><span class="intel-div-label">Structural Risk</span><span class="intel-div-val" style="color:${sc(divCheck.structural_risk)}">${(divCheck.structural_risk||'N/A').toUpperCase()}</span></div>
                <div class="intel-div-item"><span class="intel-div-label">Market Confirmation</span><span class="intel-div-val" style="color:${sc(divCheck.market_confirmation)}">${(divCheck.market_confirmation||'N/A').toUpperCase()}</span></div>
                <div class="intel-div-item"><span class="intel-div-label">Data Lag</span><span class="intel-div-val" style="color:${sc(divCheck.data_lag==='low'?'high':divCheck.data_lag==='high'?'low':'medium')}">${(divCheck.data_lag||'N/A').toUpperCase()}</span></div>
            </div>
            <p class="intel-body-text" style="margin-top:1rem;">${divCheck.interpretation}</p></div>`;
    }

    // Unresolved Signals
    if (unresolved.length > 0) {
        html += `<div class="intel-panel intel-unresolved-box"><div class="intel-section-head"><span class="intel-section-num" style="background:rgba(248,81,73,0.12);color:var(--danger);">⚠</span><h3 class="intel-section-title">Contradictory / Unresolved Signals</h3></div><ul class="intel-unresolved-list">${unresolved.map((u:string)=>`<li>${u}</li>`).join('')}</ul></div>`;
    }

    // 09 Escalation / De-escalation Watch
    const esc = watchCond.escalation||[]; const deesc = watchCond.deescalation||[];
    if (esc.length||deesc.length) {
        html += `<div class="intel-panel">${sh(nextSectionNum(),'Escalation / De-escalation Watch', '09')}<div class="intel-watch-split"><div class="intel-watch-col intel-watch-col--esc"><h4 class="intel-watch-col-title" style="color:var(--danger);">↑ Escalation Triggers</h4><ul class="intel-watch-list">${esc.map((e:any)=>`<li><span>${e.condition}</span><span class="intel-watch-data">${(e.monitored_data||[]).join(', ')}</span></li>`).join('')}</ul></div><div class="intel-watch-col intel-watch-col--deesc"><h4 class="intel-watch-col-title" style="color:var(--success);">↓ De-escalation Signals</h4><ul class="intel-watch-list">${deesc.map((d:any)=>`<li><span>${d.condition}</span><span class="intel-watch-data">${(d.monitored_data||[]).join(', ')}</span></li>`).join('')}</ul></div></div></div>`;
    }

    // 10 Watch Indicators
    if (watch.length) {
        html += `<div class="intel-panel">${sh(nextSectionNum(),'Watch Indicators', '10')}<div class="intel-watch-grid">${watch.map((w:any)=>`<div class="intel-metric-card"><strong>${w.indicator}</strong><div style="margin:0.5rem 0;color:var(--text-primary);font-size:1.1rem;">Latest: ${w.latest_value??'N/A'}</div><div style="font-size:0.85rem;border-left:2px solid var(--success);padding-left:0.5rem;margin-bottom:0.25rem;">↑ ${w.upward_interpretation}</div><div style="font-size:0.85rem;border-left:2px solid var(--danger);padding-left:0.5rem;">↓ ${w.downward_interpretation}</div></div>`).join('')}</div></div>`;
    }

    // 11 Balanced Assessment
    html += `<div class="intel-panel">${sh(nextSectionNum(),'Balanced Assessment', '11')}<div class="intel-balanced-grid"><div class="intel-balanced-card intel-balanced-card--stability"><h4>Stability View</h4><p>${interpretations.stability_view||'N/A'}</p></div><div class="intel-balanced-card intel-balanced-card--volatility"><h4>Volatility View</h4><p>${interpretations.volatility_view||'N/A'}</p></div></div></div>`;

    // 12 Exposure Matrix
    if (expMatrix.length) {
        html += `<div class="intel-panel">${sh(nextSectionNum(),'Exposure Matrix', '12')}<table class="intel-exposure-table"><thead><tr><th>Target</th><th>Transmission</th><th>Sensitivity</th><th>Rationale</th></tr></thead><tbody>${expMatrix.map((e:any)=>`<tr><td><strong>${e.target}</strong></td><td>${e.transmission}</td><td><span class="intel-sens-badge" style="color:${sc(e.sensitivity)}">${(e.sensitivity||'').toUpperCase()}</span></td><td class="intel-reason-cell">${e.reason}</td></tr>`).join('')}</tbody></table></div>`;
    }

    // 13 Coverage Matrix
    if (covMatrix.macro_data) {
        html += `<div class="intel-panel">${sh(nextSectionNum(),'Source Coverage Matrix', '13')}<div class="intel-coverage-grid"><div class="intel-cov-item"><span class="intel-cov-label">Macro</span><span class="intel-cov-val">${covDot(covMatrix.macro_data)}</span></div><div class="intel-cov-item"><span class="intel-cov-label">Market</span><span class="intel-cov-val">${covDot(covMatrix.market_data)}</span></div><div class="intel-cov-item"><span class="intel-cov-label">Trade</span><span class="intel-cov-val">${covDot(covMatrix.trade_data)}</span></div><div class="intel-cov-item"><span class="intel-cov-label">Geo</span><span class="intel-cov-val">${covDot(covMatrix.geo_data)}</span></div><div class="intel-cov-item"><span class="intel-cov-label">News</span><span class="intel-cov-val">${covDot(covMatrix.news_evidence)}</span></div></div>${covMatrix.notes?`<p class="intel-body-text" style="margin-top:0.75rem;font-size:0.8rem;">${covMatrix.notes}</p>`:''}</div>`;
    }

    // 14 Cascading Impacts (v3)
    if (p.cascading_impacts) {
        html += renderCascadingImpactsSection(p.cascading_impacts, nextSectionNum());
    }

    // Spatial Contagion Network Map
    if (p.spatial_contagion) {
        const domainIdSc = p.domain?.domain_id || 'unknown';
        html += renderSpatialContagionShell(p.spatial_contagion, nextSectionNum(), domainIdSc);
    }

    // 15 Tail-Risk & Contrarian Scenarios (v3)
    if (p.tail_risk_scenarios?.length) {
        html += renderTailRiskSection(p.tail_risk_scenarios, nextSectionNum());
    }

    // 16 Quantitative Evidence Matrix (v3)
    if (p.quantitative_evidence_matrix) {
        html += renderQuantitativeEvidenceMatrixSection(p.quantitative_evidence_matrix, nextSectionNum());
    }

    // Data Notes (collapsible)
    const limList = notes.coverage_limitations || [];
    html += `<details class="intel-data-details"><summary class="intel-data-summary">Data Notes & Coverage Limitations</summary><div class="intel-data-details-body"><div><strong>Data Freshness:</strong> ${notes.freshness||'Unknown'}</div>${limList.length?`<div style="margin-top:0.5rem;"><strong>Limitations:</strong></div><ul style="padding-left:1.2rem;margin-top:0.25rem;">${limList.map((l:string)=>`<li>${escHtml(l)}</li>`).join('')}</ul>`:''}</div></details>`;

    html += timelineAppendixHtml;

    html += `</div>`;
    contentContainer.innerHTML = html;
    wireProBriefInteractions(contentContainer);

    // Systemic Fragility comet tail (async, non-blocking)
    if (p.systemic_fragility && p.domain?.domain_id) {
        injectFragilityHistory(contentContainer, p.domain.domain_id);
    }

    // Spatial Contagion interactive map (async, non-blocking)
    if (p.spatial_contagion && p.domain?.domain_id) {
        mountSpatialContagionMap(contentContainer, p.spatial_contagion, p.domain.domain_id);
    }

    // Leaflet
    if (hasLocation) {
        setTimeout(() => {
            const el = document.getElementById('pro-brief-minimap');
            if (el) {
                const m = L.map('pro-brief-minimap', {zoomControl:false,dragging:false,scrollWheelZoom:false,doubleClickZoom:false,attributionControl:false}).setView([signal.location_lat,signal.location_lng],4);
                L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{subdomains:'abcd',maxZoom:20}).addTo(m);
                const icon = L.divIcon({className:'backbone-node',html:`<div class="backbone-marker backbone-marker--selected" style="--node-color:#ff4d6d;"><div class="backbone-marker-dot"></div><span class="backbone-marker-label">${signal.target_label||'Event'}</span></div>`,iconSize:undefined,iconAnchor:[0,12]});
                L.marker([signal.location_lat,signal.location_lng],{icon}).addTo(m);
            }
        }, 100);
    }
}

/* ============================================================
 * v3 section renderers — Cascading Impacts, Tail-Risk, QE Matrix
 * ============================================================ */

type CascadingTierEntry = {
    target?: string;
    transmission?: string;
    rationale?: string;
    sensitivity?: string;
};
type CascadingChannel = { channel?: string; note?: string };
type CascadingSpillover = { spillover_domain?: string; mechanism?: string };
type CascadingMacroPressure = { series_id?: string; display_name?: string; change_pct?: number };
interface CascadingImpactsPayload {
    tier_1_direct?: CascadingTierEntry[];
    tier_2_downstream?: CascadingTierEntry[];
    tier_2_channels?: CascadingChannel[];
    tier_3_systemic?: CascadingSpillover[];
    active_macro_pressure?: CascadingMacroPressure[];
}

type TailRiskScenario = {
    type?: string;
    scenario?: string;
    probability?: string;
    impact?: string;
    source?: string;
};

type QuantTransmission = {
    source_series?: string;
    target_topic?: string;
    lag_days?: number;
    correlation?: number;
    correlation_strength?: string;
    beta_log_return?: number;
    sample_size?: number;
    include_inverse?: boolean;
    methodology?: string;
};
type QuantMacroMove = {
    series_id?: string;
    display_name?: string;
    latest_value?: number | string | null;
    change_pct?: number;
};
type QuantMarketMove = {
    symbol?: string;
    asset_class?: string;
    latest_close?: number | string | null;
    percent_change?: number;
};
type QuantIntensityStats = { count?: number; max?: number; mean?: number };
interface QuantitativeEvidenceMatrixPayload {
    transmission?: QuantTransmission | null;
    top_macro_moves?: QuantMacroMove[];
    top_market_moves?: QuantMarketMove[];
    alert_intensity_stats?: QuantIntensityStats | null;
    schema_version?: string;
}

function fmtPct(v: number | null | undefined, decimals = 2): string {
    if (v == null || !Number.isFinite(v)) return '—';
    const sign = v > 0 ? '+' : '';
    return `${sign}${v.toFixed(decimals)}%`;
}

function fmtSigned(v: number | null | undefined, decimals = 3): string {
    if (v == null || !Number.isFinite(v)) return '—';
    const sign = v > 0 ? '+' : '';
    return `${sign}${v.toFixed(decimals)}`;
}

function fmtNum(v: number | string | null | undefined): string {
    if (v == null) return '—';
    const n = typeof v === 'number' ? v : Number(v);
    if (!Number.isFinite(n)) return String(v);
    if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return n.toFixed(2);
}

function renderCascadingImpactsSection(ci: CascadingImpactsPayload | null | undefined, sectionNum: string): string {
    if (!ci) return '';
    const tier1 = ci.tier_1_direct || [];
    const tier2 = ci.tier_2_downstream || [];
    const channels = ci.tier_2_channels || [];
    const tier3 = ci.tier_3_systemic || [];
    const pressure = ci.active_macro_pressure || [];
    if (!tier1.length && !tier2.length && !tier3.length) return '';

    const tierRows = (rows: CascadingTierEntry[]): string => rows.map((r) => {
        const sens = (r.sensitivity || 'unspecified').toLowerCase();
        return `<tr>
            <td><strong>${escHtml(r.target || '—')}</strong></td>
            <td>${escHtml(r.transmission || '—')}</td>
            <td><span class="intel-sens-pill ${escAttr(sens)}">${escHtml(sens)}</span></td>
            <td>${escHtml(r.rationale || '—')}</td>
        </tr>`;
    }).join('');

    let tier1Html = '';
    if (tier1.length) {
        tier1Html = `
            <div class="intel-tier-card tier-1">
                <div class="intel-tier-header">
                    <h4 class="intel-tier-title">1st-Order — Direct Exposure</h4>
                    <span class="intel-tier-count">${tier1.length} target${tier1.length === 1 ? '' : 's'}</span>
                </div>
                <table class="intel-tier-table">
                    <thead><tr><th>Target</th><th>Transmission</th><th>Sensitivity</th><th>Rationale</th></tr></thead>
                    <tbody>${tierRows(tier1)}</tbody>
                </table>
            </div>`;
    }

    let tier2Html = '';
    if (tier2.length || channels.length) {
        const tableHtml = tier2.length
            ? `<table class="intel-tier-table">
                    <thead><tr><th>Target</th><th>Transmission</th><th>Sensitivity</th><th>Rationale</th></tr></thead>
                    <tbody>${tierRows(tier2)}</tbody>
                </table>`
            : '';
        const channelsHtml = channels.length
            ? `<div class="intel-tier-channels">
                    <h5>Indirect Channels</h5>
                    <ul>${channels.map((c) => `<li>${escHtml(c.channel || '')}</li>`).join('')}</ul>
                </div>`
            : '';
        tier2Html = `
            <div class="intel-tier-card tier-2">
                <div class="intel-tier-header">
                    <h4 class="intel-tier-title">2nd-Order — Downstream</h4>
                    <span class="intel-tier-count">${tier2.length} target${tier2.length === 1 ? '' : 's'}</span>
                </div>
                ${tableHtml}
                ${channelsHtml}
            </div>`;
    }

    let tier3Html = '';
    if (tier3.length) {
        tier3Html = `
            <div class="intel-tier-card tier-3">
                <div class="intel-tier-header">
                    <h4 class="intel-tier-title">3rd-Order — Systemic Spillover</h4>
                    <span class="intel-tier-count">${tier3.length} domain${tier3.length === 1 ? '' : 's'}</span>
                </div>
                <ul class="intel-spillover-list">
                    ${tier3.map((s) => `<li><code>${escHtml(s.spillover_domain || '—')}</code><br>${escHtml(s.mechanism || '')}</li>`).join('')}
                </ul>
            </div>`;
    }

    let pressureHtml = '';
    if (pressure.length) {
        const rows = pressure.map((m) => {
            const chg = typeof m.change_pct === 'number' ? m.change_pct : null;
            const dir = chg != null && chg > 0 ? 'up' : 'down';
            return `<tr>
                <td><code>${escHtml(m.series_id || '—')}</code></td>
                <td>${escHtml(m.display_name || m.series_id || '—')}</td>
                <td class="intel-pressure-delta ${dir}">${fmtPct(chg)}</td>
            </tr>`;
        }).join('');
        pressureHtml = `
            <div class="intel-active-pressure">
                <h5>Active Macro Pressure (≥3% lookback)</h5>
                <table class="intel-active-pressure-table">
                    <thead><tr><th>Series</th><th>Label</th><th>Change</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>`;
    }

    return `<div class="intel-panel intel-cascading">${sh(sectionNum, 'Cascading Impacts', '14')}
        <p class="intel-panel-intro">Second- and third-order systemic effects mapped from <code>exposure_matrix_details</code> plus observed structural moves. Each tier is rule-derived — no narrative speculation.</p>
        <div class="intel-cascading-tiers">
            ${tier1Html}
            ${tier2Html}
            ${tier3Html}
        </div>
        ${pressureHtml}
    </div>`;
}

function renderTailRiskSection(scenarios: TailRiskScenario[] | null | undefined, sectionNum: string): string {
    if (!scenarios || !scenarios.length) return '';
    const cards = scenarios.map((s) => {
        const t = (s.type || 'context').toLowerCase();
        const typeLabel = t.replace(/_/g, ' ');
        return `<article class="intel-risk-scenario type-${escAttr(t)}">
            <header class="intel-risk-header">
                <span class="intel-risk-type">${escHtml(typeLabel)}</span>
                <span class="intel-risk-pi">
                    <span><span class="k">P:</span> ${escHtml(s.probability || '—')}</span>
                    <span><span class="k">I:</span> ${escHtml(s.impact || '—')}</span>
                </span>
            </header>
            <p class="intel-risk-body">${escHtml(s.scenario || '')}</p>
            <footer class="intel-risk-footer">Source: <code>${escHtml(s.source || '—')}</code></footer>
        </article>`;
    }).join('');
    return `<div class="intel-panel intel-tail-risk">${sh(sectionNum, 'Tail-Risk & Contrarian Scenarios', '15')}
        <p class="intel-panel-intro">Low-probability, high-impact paths that would invalidate or accelerate the base case. Each entry is sourced from invalidating conditions, extreme macro moves, the volatility view, or short-lag transmission detected by the quantitative engine.</p>
        <div class="intel-tail-risk-grid">${cards}</div>
    </div>`;
}

function renderQuantitativeEvidenceMatrixSection(matrix: QuantitativeEvidenceMatrixPayload | null | undefined, sectionNum: string): string {
    if (!matrix) return '';
    const tx = matrix.transmission;
    const macroRows = matrix.top_macro_moves || [];
    const marketRows = matrix.top_market_moves || [];
    const stats = matrix.alert_intensity_stats;
    const hasAny = tx || macroRows.length || marketRows.length || stats;
    if (!hasAny) return '';

    let txHtml = '';
    if (tx) {
        const lag = typeof tx.lag_days === 'number' ? tx.lag_days : null;
        const corr = typeof tx.correlation === 'number' ? Math.max(-1, Math.min(1, tx.correlation)) : null;
        const beta = typeof tx.beta_log_return === 'number' ? tx.beta_log_return : null;
        const lagText = lag == null ? '—' : `${lag > 0 ? '+' : ''}${lag} day${Math.abs(lag) === 1 ? '' : 's'}`;
        const lagSub = lag == null
            ? '—'
            : lag > 0 ? 'Macro leads' : lag < 0 ? 'Topic leads' : 'Simultaneous';
        txHtml = `
            <div class="intel-quant-hero">
                <div class="intel-quant-hero-head">
                    <h4 class="intel-quant-hero-title">Macro → Topic Transmission</h4>
                    <span class="intel-quant-hero-pair">
                        <code>${escHtml(tx.source_series || '—')}</code> → <code>${escHtml(tx.target_topic || '—')}</code>
                    </span>
                </div>
                <div class="intel-quant-metrics">
                    <div class="intel-quant-metric">
                        <span class="k">Lag</span>
                        <span class="v">${escHtml(lagText)}</span>
                        <span class="s">${escHtml(lagSub)}</span>
                    </div>
                    <div class="intel-quant-metric">
                        <span class="k">Correlation</span>
                        <span class="v">${fmtSigned(corr, 3)}</span>
                        <span class="s">${escHtml(tx.correlation_strength || '—')}</span>
                    </div>
                    <div class="intel-quant-metric">
                        <span class="k">β (log-return)</span>
                        <span class="v">${fmtSigned(beta, 4)}</span>
                        <span class="s">Sensitivity at peak lag</span>
                    </div>
                    <div class="intel-quant-metric">
                        <span class="k">Sample</span>
                        <span class="v">${tx.sample_size ?? '—'}</span>
                        <span class="s">Daily observations</span>
                    </div>
                    <div class="intel-quant-metric">
                        <span class="k">Inverse scan</span>
                        <span class="v">${tx.include_inverse ? '±lag' : '+lag only'}</span>
                        <span class="s">${tx.include_inverse ? 'Both directions' : 'Forward only'}</span>
                    </div>
                </div>
                <div class="intel-quant-meta">${escHtml(tx.methodology || '')}</div>
            </div>`;
    }

    let macroHtml = '';
    if (macroRows.length) {
        const rows = macroRows.map((m) => {
            const chg = typeof m.change_pct === 'number' ? m.change_pct : null;
            const dir = chg != null && chg > 0 ? 'up' : 'down';
            return `<tr>
                <td><code>${escHtml(m.series_id || '—')}</code></td>
                <td>${escHtml(m.display_name || m.series_id || '—')}</td>
                <td class="num">${fmtNum(m.latest_value)}</td>
                <td class="num ${dir}">${fmtPct(chg)}</td>
            </tr>`;
        }).join('');
        macroHtml = `
            <h5 class="intel-quant-subtable-title">Top Structural Moves (by |Δ%|)</h5>
            <table class="intel-quant-table">
                <thead><tr><th>Series</th><th>Label</th><th>Latest</th><th>Δ Lookback</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>`;
    }

    let marketHtml = '';
    if (marketRows.length) {
        const rows = marketRows.map((p) => {
            const chg = typeof p.percent_change === 'number' ? p.percent_change : null;
            const dir = chg != null && chg > 0 ? 'up' : 'down';
            return `<tr>
                <td><code>${escHtml(p.symbol || '—')}</code></td>
                <td>${escHtml(p.asset_class || '—')}</td>
                <td class="num">${fmtNum(p.latest_close)}</td>
                <td class="num ${dir}">${fmtPct(chg)}</td>
            </tr>`;
        }).join('');
        marketHtml = `
            <h5 class="intel-quant-subtable-title">Top Market Moves (by |Δ%|)</h5>
            <table class="intel-quant-table">
                <thead><tr><th>Symbol</th><th>Class</th><th>Latest Close</th><th>Δ</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>`;
    }

    let statsHtml = '';
    if (stats && stats.count != null) {
        statsHtml = `
            <h5 class="intel-quant-subtable-title">Alert Intensity (Related Events)</h5>
            <div class="intel-quant-stats">
                <div class="intel-quant-stat"><div class="k">Sample</div><div class="v">${stats.count}</div></div>
                <div class="intel-quant-stat"><div class="k">Peak</div><div class="v">${stats.max ?? '—'}</div></div>
                <div class="intel-quant-stat"><div class="k">Mean</div><div class="v">${stats.mean ?? '—'}</div></div>
            </div>`;
    }

    return `<div class="intel-panel intel-quant-matrix">${sh(sectionNum, 'Quantitative Evidence Matrix', '16')}
        <p class="intel-panel-intro">Exact numeric inputs supporting the narrative. All correlations are clipped to <code>[-1, 1]</code>; betas are computed on log-return residuals at the aligned peak lag.</p>
        ${txHtml}
        ${macroHtml}
        ${marketHtml}
        ${statsHtml}
    </div>`;
}


/**
 * Renders the full detail of a Pro Structural Brief.
 */
export async function renderProStructuralBriefDetail(id: string, container: HTMLElement, onBack: () => void) {
    container.innerHTML = `<div class="vx-scan-loading u-p-2 u-text-center" data-vx-loading="true"><div class="loading-spinner u-m-bottom-1"></div><div class="vx-mono" style="color:var(--text-secondary);font-size:0.85rem;">Decrypting structural impact matrix...</div></div>`;
    try {
        const report = await fetchProStructuralReport(id);
        const domainClass = getDomainSlugClass(report.topic);
        const topicVars = getTopicCssVars(report.topic);
        container.innerHTML = `
            <div class="pro-brief-detail ${domainClass}" style="${topicVars}">
                <div class="u-flex u-m-bottom-2"><button class="btn-fb" id="pro-brief-back-btn" style="padding:8px 16px;">← Back to Index</button></div>
                <div id="pro-brief-content-container" class="pro-brief-content-card" style="background:var(--card-bg);border:1px solid var(--border);border-radius:16px;padding:2.5rem;box-shadow:0 12px 32px rgba(0,0,0,0.4);"></div>
                <div class="u-m-top-2 u-text-center" style="color:#8b949e;font-size:0.75rem;padding-bottom:3rem;letter-spacing:0.1em;">
                    END OF STRUCTURAL BRIEF | REF: ${report.id.slice(0,8).toUpperCase()} | NOT INVESTMENT ADVICE
                </div>
            </div>`;
        container.querySelector('#pro-brief-back-btn')?.addEventListener('click', onBack);
        const cc = container.querySelector('#pro-brief-content-container') as HTMLElement;
        if (report.structured_payload && Object.keys(report.structured_payload).length > 0) {
            renderStructuredProBrief(report, cc, domainClass);
        } else {
            cc.innerHTML = `<div class="markdown-body">${simpleMarkdown(report.content_markdown || '# Content Missing\\nData for this structural brief is currently being re-indexed.')}</div>`;
        }
        window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) {
        console.error("Failed to fetch Pro report detail", e);
        container.innerHTML = `<div class="u-p-2 u-text-center" style="margin-top:4rem;"><div class="u-error u-m-bottom-2" style="font-size:1.1rem;">Failed to retrieve document content.</div><button class="btn-fb" id="pro-brief-error-back">← Return to Index</button></div>`;
        container.querySelector('#pro-brief-error-back')?.addEventListener('click', onBack);
    }
}
