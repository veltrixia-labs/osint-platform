import type { ProStructuralReportItem } from '../api';
import { fetchProStructuralReports, fetchProStructuralReport } from '../api';
import { simpleMarkdown, getDomainSlugClass, formatIntelDateTime, formatIntelPreciseTimestamp } from './utils';
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
) {
    container.innerHTML = `
        <div class="pro-briefs-container">
            <h2 style="font-size: 1.3rem; color: #c9d1d9; margin: 0 0 1rem 0; padding-bottom: 0.5rem; border-bottom: 1px solid var(--border);">Latest Structural Briefs</h2>
            <div id="briefs-list" class="pro-briefs-grid pro-briefs-grid--loading">
                <div class="u-p-2 u-text-center">Synchronizing intelligence assets...</div>
            </div>
        </div>
    `;
    try {
        const reports: ProStructuralReportItem[] = await fetchProStructuralReports();
        const listContainer = container.querySelector('#briefs-list') as HTMLElement;
        if (!listContainer) return;

        const filtered = topicFilter
            ? reports.filter((r) => normalizeTopicCode(r.topic) === topicFilter)
            : reports;

        const paintGrid = (html: string) => {
            listContainer.classList.remove('pro-briefs-grid--loading', 'pro-briefs-grid--settled');
            listContainer.classList.add('pro-briefs-grid--transition');
            listContainer.style.opacity = '0';
            listContainer.innerHTML = html;
            requestAnimationFrame(() => {
                listContainer.style.opacity = '1';
                listContainer.classList.add('pro-briefs-grid--settled');
                window.setTimeout(() => {
                    listContainer.classList.remove('pro-briefs-grid--transition');
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
                    const createdStr = formatIntelPreciseTimestamp(r.created_at);
                    return `<div class="pro-brief-card ${dc}" data-id="${r.id}" style="${topicVars}"><div class="u-flex-between" style="margin-bottom:1rem;"><span class="domain-chip meta-item-topic--tag">${topicLabel}</span><div style="display:flex;flex-direction:column;align-items:flex-end;gap:2px;"><span style="font-size:0.65rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.05em;">${(r.report_type || 'PRO_STRUCTURAL').replace(/_/g, ' ')}</span><span class="pro-brief-ts" style="font-size:0.75rem;color:var(--text-secondary);font-family:ui-monospace,monospace;">${createdStr}</span></div></div><h3 style="margin:0 0 1rem;font-size:1.2rem;line-height:1.4;color:var(--text-primary);">${r.title}</h3><div style="font-size:0.9rem;color:var(--text-secondary);line-height:1.6;margin-bottom:1.5rem;flex-grow:1;">${r.teaser_md || 'Detailed structural analysis of transmission channels, macro-economic dependencies, and market confirmation signals.'}</div><button class="btn-fb pro-brief-btn" style="width:100%;pointer-events:none;">View Full Brief →</button></div>`;
                })
                .join(''),
        );
        listContainer.querySelectorAll('.pro-brief-card').forEach(card => {
            (card as HTMLElement).addEventListener('click', () => { const id = card.getAttribute('data-id'); if (id) onSelect(id); });
        });
    } catch (e) {
        console.error("Failed to fetch Pro briefs", e);
        const lc = container.querySelector('#briefs-list') as HTMLElement;
        if (lc) { lc.style.display='block'; lc.innerHTML=`<div class="u-p-2 u-text-center u-error" style="background:rgba(248,81,73,0.1);border:1px solid rgba(248,81,73,0.2);border-radius:12px;color:#f85149;">Failed to synchronize intelligence assets.</div>`; }
    }
}

/* --- Helpers --- */
function sh(num: string, title: string): string {
    return `<div class="intel-section-head"><span class="intel-section-num">${num}</span><h3 class="intel-section-title">${title}</h3></div>`;
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
// overallCoverage is now computed in the payload (divergence_check.overall_coverage)

function renderStructuredProBrief(report: ProStructuralReportItem, contentContainer: HTMLElement, domainClass: string) {
    const p = report.structured_payload;
    if (!p) return;
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

    // 01 Executive Summary + Key Findings
    const keyFindings: string[] = p.key_findings || [];
    html += `<div class="intel-panel">${sh('01','Executive Summary')}<p class="intel-body-text">${execSummary}</p>${keyFindings.length ? `<div style="margin-top:1rem;"><span class="intel-sig-label">Key Findings</span><ul style="margin:0.4rem 0 0;padding-left:1.2rem;">${keyFindings.map((f:string)=>`<li style="font-size:0.85rem;color:var(--text-primary);padding:0.15rem 0;">${f}</li>`).join('')}</ul></div>`:''}</div>`;

    // 02 Signal Classification
    if (sigClass.primary_type) {
        html += `<div class="intel-panel">${sh('02','Signal Classification')}
            <div class="intel-sig-class"><div class="intel-sig-primary"><span class="intel-sig-label">Primary</span><span class="intel-sig-chip intel-sig-chip--primary">${sigClass.primary_type.replace(/_/g,' ')}</span></div>${(sigClass.secondary_types||[]).length?`<div class="intel-sig-secondary"><span class="intel-sig-label">Secondary</span><div class="intel-chip-row">${sigClass.secondary_types.map((t:string)=>`<span class="intel-sig-chip">${t.replace(/_/g,' ')}</span>`).join('')}</div></div>`:''}</div>
            <p class="intel-rationale">${sigClass.rationale||''}</p></div>`;
    }

    // 03 Geo Context
    html += `<div class="intel-panel">${sh('03','Geographic Context')}`;
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

    // 04 Event Timeline — always render (backend guarantees minimum entries)
    const tlItems = timeline.length > 0
        ? timeline
        : [{ type: 'context', title: 'Timeline synchronizing — check back after the next intelligence cycle.', timestamp: null }];
    html += `<div class="intel-panel">${sh('04','Event Timeline')}<div class="intel-timeline">${tlItems.map((ev: any) => {
        const tsLabel = ev.timestamp ? formatIntelPreciseTimestamp(ev.timestamp) : '';
        return `<div class="intel-tl-item"><div class="intel-tl-dot"></div><div class="intel-tl-content"><div class="intel-tl-head">${roleBadge(ev.type || ev.role)}${tsLabel ? `<span class="intel-tl-time">${tsLabel}</span>` : ''}${ev.location_label ? `<span class="intel-tl-loc">📍 ${ev.location_label}</span>` : ''}</div><div class="intel-tl-title">${ev.source_url ? `<a href="${ev.source_url}" target="_blank" rel="noopener">${ev.title}</a>` : ev.title}</div></div></div>`;
    }).join('')}</div></div>`;

    // 05 Structural Impact & Transmission
    html += `<div class="intel-panel">${sh('05','Structural Impact & Transmission')}${flows.length?`<div class="intel-transmission-flow">${flows.map((f:string,i:number)=>`<div class="flow-step">${f}</div>${i<flows.length-1?'<div class="flow-arrow">→</div>':''}`).join('')}</div>`:'<p class="intel-body-text">No specific transmission channels defined.</p>'}</div>`;

    // 06 Quantitative Context
    if (macro.length > 0) {
        html += `<div class="intel-panel">${sh('06','Quantitative Context')}<div class="intel-metric-grid">${macro.slice(0,12).map((m:any)=>`<div class="intel-metric-card"><div class="metric-label">${m.display_name || m.series_id}</div>${m.display_name ? `<div style="font-size:0.65rem;color:var(--text-secondary);font-family:monospace;margin-bottom:0.25rem;">${m.series_id}</div>` : ''}<div class="metric-value">${m.latest_value??'N/A'}</div><div class="metric-change" style="color:${(m.change_pct||0)>0?'var(--success)':'var(--danger)'}">${(m.change_pct||0)>0?'+':''}${m.change_pct?m.change_pct.toFixed(2):'0.00'}%</div>${m.trend_meaning ? `<div style="font-size:0.7rem;color:var(--text-secondary);margin-top:0.35rem;line-height:1.3;">${m.trend_meaning}</div>` : ''}</div>`).join('')}</div></div>`;
    }

    // 07 Market Confirmation Breakdown
    html += `<div class="intel-panel">${sh('07','Market Confirmation')}
        <div class="intel-market-summary">
            <div class="intel-score-card"><div class="score-label">Status</div><div class="score-value" style="color:${sc(market.status)}">${market.status||'N/A'}</div></div>
            <div class="intel-score-card"><div class="score-label">Positive</div><div class="score-value" style="color:var(--success)">${market.positive_movers||0}</div></div>
            <div class="intel-score-card"><div class="score-label">Negative</div><div class="score-value" style="color:var(--danger)">${market.negative_movers||0}</div></div>
        </div>
        ${breakdown.length?`<div class="intel-breakdown-grid">${breakdown.map((g:any)=>`<div class="intel-breakdown-card"><div class="intel-bd-head"><span class="intel-bd-group">${g.group}</span><span class="intel-bd-status" style="color:${sc(g.status)}">${(g.status||'').replace('_',' ')}</span></div>${g.description?`<div style="font-size:0.7rem;color:var(--text-secondary);margin-bottom:0.4rem;">${g.description}</div>`:''}<div class="intel-chip-row">${(g.instrument_details||[]).map((d:any)=>pctChip(d.symbol,d.percent_change)).join('')}</div></div>`).join('')}</div>`:''}</div>`;

    // 08 Divergence Check
    if (divCheck.interpretation) {
        html += `<div class="intel-panel intel-divergence-banner">${sh('08','Divergence Check')}
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
        html += `<div class="intel-panel">${sh('09','Escalation / De-escalation Watch')}<div class="intel-watch-split"><div class="intel-watch-col intel-watch-col--esc"><h4 class="intel-watch-col-title" style="color:var(--danger);">↑ Escalation Triggers</h4><ul class="intel-watch-list">${esc.map((e:any)=>`<li><span>${e.condition}</span><span class="intel-watch-data">${(e.monitored_data||[]).join(', ')}</span></li>`).join('')}</ul></div><div class="intel-watch-col intel-watch-col--deesc"><h4 class="intel-watch-col-title" style="color:var(--success);">↓ De-escalation Signals</h4><ul class="intel-watch-list">${deesc.map((d:any)=>`<li><span>${d.condition}</span><span class="intel-watch-data">${(d.monitored_data||[]).join(', ')}</span></li>`).join('')}</ul></div></div></div>`;
    }

    // 10 Watch Indicators
    if (watch.length) {
        html += `<div class="intel-panel">${sh('10','Watch Indicators')}<div class="intel-watch-grid">${watch.map((w:any)=>`<div class="intel-metric-card"><strong>${w.indicator}</strong><div style="margin:0.5rem 0;color:var(--text-primary);font-size:1.1rem;">Latest: ${w.latest_value??'N/A'}</div><div style="font-size:0.85rem;border-left:2px solid var(--success);padding-left:0.5rem;margin-bottom:0.25rem;">↑ ${w.upward_interpretation}</div><div style="font-size:0.85rem;border-left:2px solid var(--danger);padding-left:0.5rem;">↓ ${w.downward_interpretation}</div></div>`).join('')}</div></div>`;
    }

    // 11 Balanced Assessment
    html += `<div class="intel-panel">${sh('11','Balanced Assessment')}<div class="intel-balanced-grid"><div class="intel-balanced-card intel-balanced-card--stability"><h4>Stability View</h4><p>${interpretations.stability_view||'N/A'}</p></div><div class="intel-balanced-card intel-balanced-card--volatility"><h4>Volatility View</h4><p>${interpretations.volatility_view||'N/A'}</p></div></div></div>`;

    // 12 Exposure Matrix
    if (expMatrix.length) {
        html += `<div class="intel-panel">${sh('12','Exposure Matrix')}<table class="intel-exposure-table"><thead><tr><th>Target</th><th>Transmission</th><th>Sensitivity</th><th>Rationale</th></tr></thead><tbody>${expMatrix.map((e:any)=>`<tr><td><strong>${e.target}</strong></td><td>${e.transmission}</td><td><span class="intel-sens-badge" style="color:${sc(e.sensitivity)}">${(e.sensitivity||'').toUpperCase()}</span></td><td class="intel-reason-cell">${e.reason}</td></tr>`).join('')}</tbody></table></div>`;
    }

    // 13 Coverage Matrix
    if (covMatrix.macro_data) {
        html += `<div class="intel-panel">${sh('13','Source Coverage Matrix')}<div class="intel-coverage-grid"><div class="intel-cov-item"><span class="intel-cov-label">Macro</span><span class="intel-cov-val">${covDot(covMatrix.macro_data)}</span></div><div class="intel-cov-item"><span class="intel-cov-label">Market</span><span class="intel-cov-val">${covDot(covMatrix.market_data)}</span></div><div class="intel-cov-item"><span class="intel-cov-label">Trade</span><span class="intel-cov-val">${covDot(covMatrix.trade_data)}</span></div><div class="intel-cov-item"><span class="intel-cov-label">Geo</span><span class="intel-cov-val">${covDot(covMatrix.geo_data)}</span></div><div class="intel-cov-item"><span class="intel-cov-label">News</span><span class="intel-cov-val">${covDot(covMatrix.news_evidence)}</span></div></div>${covMatrix.notes?`<p class="intel-body-text" style="margin-top:0.75rem;font-size:0.8rem;">${covMatrix.notes}</p>`:''}</div>`;
    }

    // Data Notes (collapsible)
    const limList = notes.coverage_limitations || [];
    html += `<details class="intel-data-details"><summary class="intel-data-summary">Data Notes & Coverage Limitations</summary><div class="intel-data-details-body"><div><strong>Data Freshness:</strong> ${notes.freshness||'Unknown'}</div>${limList.length?`<div style="margin-top:0.5rem;"><strong>Limitations:</strong></div><ul style="padding-left:1.2rem;margin-top:0.25rem;">${limList.map((l:string)=>`<li>${l}</li>`).join('')}</ul>`:''}</div></details>`;

    html += `</div>`;
    contentContainer.innerHTML = html;

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
