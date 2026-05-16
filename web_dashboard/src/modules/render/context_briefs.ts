/**
 * render/context_briefs.ts (formerly free_feed.ts)
 * Context Briefs renderer — High-detail data without AI scoring.
 * Layout aligns with Pro Insights / Latest Structural Briefs (grid + premium cards).
 */
import { simpleMarkdown } from './utils';
import type { FreeAlertFeedItem } from '../api';
import { getTopicDisplayLabel, getTopicCssVars, normalizeTopicCode } from '../topics';

type CompanyImpactSource = NonNullable<FreeAlertFeedItem['company_impacts']>[number];
type SectorImpactSource = NonNullable<FreeAlertFeedItem['sector_impacts']>[number];
type MarkdownTableRow = Record<string, string>;

/** Related-news row from API or parsed markdown table. */
type ContextNewsRow = {
    title?: string;
    news?: string;
    source?: string;
    category?: string;
    published?: string;
    url?: string | null;
    source_url?: string | null;
};

function formatDate(iso: string): string {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso || '—';
    return d.toLocaleString(undefined, {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });
}

/** Strip trigger-style prefixes (e.g. acceleration:, entity_surge:) for display titles. */
function cleanBriefTitle(raw: string): string {
    if (!raw) return 'Strategic Intelligence Alert';
    let s = raw.replace(/\(🚨\s*INTENSITY\s*SPIKE\)/gi, '').trim();
    s = s.replace(
        /^(acceleration|entity_surge|pattern_risk|sector_surge|event_continuation|sustained_event|risk_pattern|risk_acceleration)\s*:\s*/i,
        ''
    ).trim();
    return s || raw;
}

function stripMarkdownLite(s: string): string {
    return s
        .replace(/\*\*([^*]+)\*\*/g, '$1')
        .replace(/\*([^*]+)\*/g, '$1')
        .replace(/\[(.*?)\]\([^)]*\)/g, '$1')
        .replace(/#{1,6}\s*/g, '')
        .replace(/`/g, '')
        .trim();
}

/** Plain-text teaser for card body (line-clamp applied in CSS). */
function extractTeaserFromMarkdown(markdown: string, maxChars = 240): string {
    if (!markdown) {
        return 'Rule-based context, related news, and matched entities — open the full brief for detail.';
    }
    let t = markdown.replace(/^#\s+[^\n]*\n?/m, '').trim();
    const summaryMatch = t.match(/##\s*Summary[^\n]*\n+([\s\S]*?)(?=\n##|\n*$)/i);
    if (summaryMatch) {
        t = summaryMatch[1].trim();
    } else {
        const blocks = t.split(/\n\n+/);
        t = (blocks[0] || t).replace(/^##[^\n]+\n/m, '').trim();
    }
    t = stripMarkdownLite(t).replace(/\s+/g, ' ');
    if (t.length > maxChars) return t.slice(0, maxChars).trim() + '…';
    return t || 'Open the full brief for structured context and evidence.';
}

function escapeHtml(unsafe: string): string {
    if (!unsafe) return '';
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function escapeAttr(unsafe: string): string {
    if (!unsafe) return '';
    return unsafe
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/**
 * Parses markdown table content into a list of objects for card rendering.
 * Matches: | Col 1 | Col 2 | ...
 */
function parseMarkdownTable(markdown: string): MarkdownTableRow[] {
    const lines = markdown.trim().split('\n').filter(l => l.trim().includes('|'));
    if (lines.length < 3) return [];

    const headers = lines[0].split('|').map((cell: string) => cell.trim()).filter((cell: string) => cell);
    const dataRows = lines.slice(2);

    return dataRows.map(row => {
        const cells = row.split('|').map((cell: string) => cell.trim()).filter((_, i, arr) => i > 0 && i < arr.length - 1);
        const obj: MarkdownTableRow = {};
        headers.forEach((h, i) => {
            const key = h.toLowerCase().replace(/\s+/g, '_');
            obj[key] = cells[i] || '';
        });
        return obj;
    });
}

function isPlaceholderCompanyRow(row: { name?: string }): boolean {
    const n = (row.name || '').toLowerCase();
    return (
        n.includes('no significantly affected') ||
        n.includes('no related companies') ||
        n.includes('no matched')
    );
}

type ExposureRow = {
    name: string;
    ticker?: string | null;
    entity_id?: string | null;
    entity_type?: string | null;
    sector: string;
    country: string;
    match_basis: string;
    registry_entity_type?: string | null;
};

function isGeopoliticalActorRow(r: ExposureRow): boolean {
    return (r.registry_entity_type || '').toLowerCase() === 'country';
}

/** Sector buckets for Structural / Regional exposure tags (keyword match on label). */
type SectorTagKind = 'energy' | 'marine' | 'industry' | 'finance' | 'defense' | 'default';

function classifySectorTagKind(sector: string): SectorTagKind {
    const s = (sector || '').toLowerCase();
    if (/\b(oil|gas|lng|energy|petrol|crude|power)\b/.test(s)) return 'energy';
    if (/\b(marine|maritime|shipping|logistics|port|vessel|tanker|freight|container)\b/.test(s)) return 'marine';
    if (/\b(refin|industrial|manufact|chemic|materials)\b/.test(s)) return 'industry';
    if (/\b(finance|bank|asset\s*manag|crypto|bitcoin|stablecoin|payment|digital\s*asset)\b/.test(s))
        return 'finance';
    if (/\b(defense|military|aerospace|security|nato|weapon)\b/.test(s)) return 'defense';
    return 'default';
}

function isRegionalSectorBucket(sector: string): boolean {
    const s = sector.trim().toLowerCase();
    return s === 'country' || s === 'geography' || s === 'region';
}

type SectorImpactRow = {
    sector: string;
    matched: number;
    entity_id?: string | null;
    entity_type?: string | null;
    label?: string | null;
};

function _normEntityId(v: unknown): string {
    return String(v || '').trim().toLowerCase();
}

function _normLabelKey(v: unknown): string {
    return String(v || '').trim().toLowerCase();
}

function dedupeExposureRowsByEntityId(rows: ExposureRow[]): ExposureRow[] {
    const seen = new Set<string>();
    const out: ExposureRow[] = [];
    rows.forEach(r => {
        const eid = _normEntityId(r.entity_id);
        const fallback = `${_normLabelKey(r.name)}|${_normLabelKey(r.country)}|${_normLabelKey(r.sector)}`;
        const key = eid || fallback;
        if (!key || seen.has(key)) return;
        seen.add(key);
        out.push(r);
    });
    return out;
}

function dedupeSectorRowsByEntityId(rows: SectorImpactRow[]): SectorImpactRow[] {
    const seen = new Set<string>();
    const out: SectorImpactRow[] = [];
    rows.forEach(r => {
        const eid = _normEntityId(r.entity_id);
        const fallback = `${_normLabelKey(r.label || r.sector)}|${_normLabelKey(r.entity_type)}`;
        const key = eid || fallback;
        if (!key || seen.has(key)) return;
        seen.add(key);
        out.push(r);
    });
    return out;
}

function partitionRegionalSectorRows(rows: SectorImpactRow[]): {
    regional: SectorImpactRow[];
    structural: SectorImpactRow[];
} {
    const regional = rows.filter(r => isRegionalSectorBucket(r.sector));
    const structural = rows.filter(r => !isRegionalSectorBucket(r.sector));
    return { regional, structural };
}

function sectorTagIconSvg(kind: SectorTagKind): string {
    const common =
        'width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
    switch (kind) {
        case 'energy':
            return `<svg ${common}><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>`;
        case 'marine':
            return `<svg ${common}><path d="M2 12h20M4 12c2-4 6-6 8-6s6 2 8 6M6 16c1.5 2 4 3 6 3s4.5-1 6-3"/></svg>`;
        case 'industry':
            return `<svg ${common}><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>`;
        case 'finance':
            return `<svg ${common}><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>`;
        case 'defense':
            return `<svg ${common}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`;
        default:
            return `<svg ${common}><circle cx="12" cy="12" r="3"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>`;
    }
}

function renderSectorPillHtml(
    r: SectorImpactRow,
    variant: 'structural' | 'regional'
): string {
    const kind = classifySectorTagKind(r.sector);
    const icon = sectorTagIconSvg(kind);
    const base =
        variant === 'regional'
            ? 'cb-sector-pill cb-sector-pill--regional'
            : `cb-sector-pill cb-sector-pill--structural cb-sector-pill--${kind}`;
    return `
        <div class="${base}" role="listitem">
            <span class="cb-sector-pill-icon">${icon}</span>
            <span class="cb-sector-pill-label">${escapeHtml(r.sector)}</span>
            <span class="cb-sector-pill-count">${r.matched}</span>
        </div>`;
}

function renderProGateCard(additionalCount: number): string {
    const n = Math.max(0, Math.floor(additionalCount));
    const line = `+ ${n} more specific entities monitored in Pro...`;
    return `
    <button type="button" class="cb-pro-gate-card" data-cb-pro-gate="1"
      aria-label="Open Subscription Plans to upgrade to Pro for deeper entity coverage."
      title="Pro unlocks the full matched entity list, dependency-level monitoring, and Structural Briefs. Click to open Subscription Plans.">
      <div class="cb-pro-gate-logos-wrap" aria-hidden="true">
        <span class="cb-pro-gate-lock">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        </span>
        <div class="cb-pro-gate-logos">
          <span class="cb-pro-gate-logo cb-pro-gate-logo--a"></span>
          <span class="cb-pro-gate-logo cb-pro-gate-logo--b"></span>
          <span class="cb-pro-gate-logo cb-pro-gate-logo--c"></span>
        </div>
      </div>
      <p class="cb-pro-gate-text">${escapeHtml(line)}</p>
    </button>`;
}

function renderIndustryExpandableList(rows: ExposureRow[]): string {
    const initialCount = 3;
    const visible = rows.slice(0, initialCount);
    const hidden = rows.slice(initialCount);
    const hiddenCount = hidden.length;

    let html = `<div class="cb-compact-list">`;
    visible.forEach((row: ExposureRow) => {
        html += renderExposureRowHtml(row, 'industry');
    });
    html += `</div>`;

    if (hiddenCount > 0) {
        html += `
        <div class="cb-expand-wrap" data-cb-expand-wrap>
            <div class="cb-expand-hidden" data-cb-expand-hidden aria-hidden="true">
                <div class="cb-compact-list">`;
        hidden.forEach((row: ExposureRow) => {
            html += renderExposureRowHtml(row, 'industry');
        });
        html += `</div>
            </div>
            <button type="button" class="cb-expand-btn" data-cb-expand-btn="0" aria-expanded="false">
                + ${hiddenCount} more items ↓
            </button>
        </div>`;
    }
    return html;
}

function isPaidContextTier(tier?: string | null): boolean {
    const t = (tier || 'free').toLowerCase();
    return t === 'pro' || t === 'enterprise' || t === 'experts';
}

/** Prefer API sector_impacts; else parse legacy markdown table (2- or 3-column). */
function normalizeSectorImpacts(
    apiRows: FreeAlertFeedItem['sector_impacts'] | undefined,
    body: string
): SectorImpactRow[] {
    if (apiRows && apiRows.length > 0) {
        return [...apiRows]
            .map((r: SectorImpactSource) => ({
                sector: String(r.sector || '').trim(),
                matched: typeof r.matched_entities === 'number' ? r.matched_entities : 0,
                entity_id: _normEntityId(r.entity_id) || null,
                entity_type: String(r.entity_type || '').trim().toLowerCase() || null,
                label: String(r.label ?? r.name ?? r.sector ?? '').trim() || null,
            }))
            .filter((r: SectorImpactRow) => r.sector && !r.sector.toLowerCase().includes('no sector coverage'))
            .sort((a: SectorImpactRow, b: SectorImpactRow) => b.matched - a.matched);
    }
    const raw = parseMarkdownTable(body);
    return raw
        .map((obj: MarkdownTableRow) => {
            const sector = obj.sector || obj.name || '';
            const rawN = obj.matched_entities ?? obj.entities ?? '0';
            const matched = parseInt(String(rawN).replace(/[^\d-]/g, ''), 10) || 0;
            return {
                sector: String(sector).trim(),
                matched,
                entity_id: _normEntityId(obj.entity_id) || null,
                entity_type: String(obj.entity_type || '').trim().toLowerCase() || null,
                label: String(obj.name || obj.label || sector || '').trim() || null,
            };
        })
        .filter((r: SectorImpactRow) => r.sector && !r.sector.toLowerCase().includes('no sector coverage'))
        .sort((a: SectorImpactRow, b: SectorImpactRow) => b.matched - a.matched);
}

function renderExposureRowHtml(row: ExposureRow, mode: 'geo' | 'industry'): string {
    const meta =
        mode === 'geo'
            ? 'Geopolitical Actor'
            : (row.sector && row.sector !== '—' ? row.sector : 'Industry & assets');
    const basis = row.match_basis ? ` · ${escapeHtml(row.match_basis)}` : '';
    const tk = (row.ticker || '').trim();
    const tickerLine =
        mode === 'industry' && tk
            ? `<div class="cb-compact-item-ticker" aria-label="Ticker">${escapeHtml(tk)}</div>`
            : '';
    return `
        <div class="cb-compact-item cb-compact-item--exposure">
            <div class="cb-compact-item-title">${escapeHtml(row.name)}</div>
            ${tickerLine}
            <div class="cb-compact-item-meta cb-compact-item-meta--exposure">
                <span class="cb-exposure-role">(${escapeHtml(meta)})</span>${basis}
            </div>
        </div>`;
}

function parseSummaryRows(body: string): { label: string; value: string }[] {
    const rows: { label: string; value: string }[] = [];
    body.split('\n').forEach(line => {
        const m = line.match(/^[\-\*]\s+\*\*(.*?):\*\*\s*(.*)$/);
        if (m) rows.push({ label: m[1].trim(), value: m[2].trim() });
    });
    const order = ['alert type', 'triggered at', 'topic', 'target label'];
    rows.sort((a, b) => {
        const ia = order.indexOf(a.label.toLowerCase());
        const ib = order.indexOf(b.label.toLowerCase());
        return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
    });
    return rows;
}

function summaryValueClass(label: string): string {
    const n = label.toLowerCase();
    let cls = 'cb-summary-value';
    if (n === 'topic' || n.includes('target label')) {
        cls += ' cb-summary-value--clamp cb-summary-value--clamp-3';
    } else if (n.includes('alert type')) {
        cls += ' cb-summary-value--clamp cb-summary-value--clamp-2';
    }
    return cls;
}

/**
 * Renders the content markdown as structured cards where possible.
 */
function renderStructuredContent(
    markdown: string,
    structuredNews?: FreeAlertFeedItem['related_news'],
    structuredCompanyImpacts?: FreeAlertFeedItem['company_impacts'],
    topic?: string,
    structuredSectorImpacts?: FreeAlertFeedItem['sector_impacts'],
    additionalProCount = 0,
    viewerTier?: string | null
): string {
    // 1. Suppress redundant title
    const cleanMarkdown = markdown.replace(/^# .*\n?/, '').trim();
    
    const sections = cleanMarkdown.split('## ').filter(s => s.trim());
    let html = '';
    
    sections.forEach(section => {
        const lines = section.split('\n');
        const title = lines[0].trim();
        const body = lines.slice(1).join('\n').trim();
        
        if (!title) return;
        
        // Normalize title (remove numbers like "1. ")
        const displayTitle = title.replace(/^\d+\.\s*/, '');
        
        // Section specific rendering
        const lowerTitle = displayTitle.toLowerCase();
        if (lowerTitle.includes('summary')) {
            const summaryRows = parseSummaryRows(body);
            html += `<div class="cb-section cb-section--summary">`;
            html += `<div class="cb-summary-head">`;
            html += `<span class="cb-summary-head-num">01</span>`;
            html += `<h4 class="cb-summary-head-title">${escapeHtml(displayTitle)}</h4>`;
            html += `</div>`;
            html += `<div class="cb-summary-grid" role="group" aria-label="Alert summary">`;
            summaryRows.forEach(row => {
                const slug = escapeAttr(row.label.toLowerCase().replace(/\s+/g, '-'));
                html += `
                        <div class="cb-summary-cell" data-field="${slug}">
                            <span class="cb-summary-label">${escapeHtml(row.label)}</span>
                            <span class="${summaryValueClass(row.label)}">${escapeHtml(row.value)}</span>
                        </div>`;
            });
            if (summaryRows.length === 0) {
                html += `<div class="cb-summary-fallback" style="grid-column: 1 / -1;">${simpleMarkdown(body)}</div>`;
            }
            html += `</div>`;
        }
        else if (lowerTitle.includes('related news')) {
            html += `<div class="cb-section">`;
            html += `<h4 class="cb-section-title">${displayTitle}</h4>`;

            const newsList: ContextNewsRow[] =
                structuredNews && structuredNews.length > 0
                    ? structuredNews
                    : (parseMarkdownTable(body) as ContextNewsRow[]);
            
            if (newsList.length > 0 && !newsList[0].title?.toLowerCase().includes('no related news') && !newsList[0].news?.toLowerCase().includes('no related news')) {
                html += `<div class="cb-compact-list">`;
                newsList.forEach((n: ContextNewsRow) => {
                    const title = n.title || n.news || 'Untitled Signal';
                    const url = n.url || n.source_url || null;
                    
                    const titleHtml = url 
                        ? `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer" class="cb-compact-item-link">${escapeHtml(title)} ↗</a>`
                        : escapeHtml(title);

                    html += `
                        <div class="cb-compact-item">
                            <div class="cb-compact-item-title">${titleHtml}</div>
                            <div class="cb-compact-item-meta">
                                ${escapeHtml(n.source || 'Unknown')} · ${escapeHtml(n.category || 'General')} · ${escapeHtml(n.published || '—')}
                            </div>
                        </div>`;
                });
                html += `</div>`;
            } else {
                html += `<div class="cb-muted-text">No related news matched this alert.</div>`;
            }
        } 
        else if (lowerTitle.includes('companies') || lowerTitle.includes('infrastructure')) {
            html += `<div class="cb-section cb-section--related-exposure">`;
            html += `<h4 class="cb-section-title">Related Companies &amp; Infrastructure</h4>`;
            let comps: ExposureRow[] = [];
            if (structuredCompanyImpacts && structuredCompanyImpacts.length > 0) {
                comps = structuredCompanyImpacts.map((impact: CompanyImpactSource) => ({
                    name: (impact.company_name || '').trim() || 'Unknown Entity',
                    ticker: impact.ticker ?? null,
                    entity_id: String(impact.entity_id || '').trim() || null,
                    entity_type: String(impact.entity_type || '').trim().toLowerCase() || null,
                    sector: (impact.sector || 'Various').trim(),
                    country: (impact.country || 'Global').trim(),
                    match_basis: Array.isArray(impact.match_basis)
                        ? impact.match_basis.join(', ')
                        : String(impact.match_basis || ''),
                    registry_entity_type: impact.registry_entity_type ?? null,
                }));
            } else {
                const raw = parseMarkdownTable(body);
                comps = raw.map((row: MarkdownTableRow) => ({
                    name: (row.name || row.company_name || '').trim() || 'Unknown Entity',
                    ticker: row.ticker || null,
                    entity_id: String(row.entity_id || '').trim() || null,
                    entity_type: String(row.entity_type || '').trim().toLowerCase() || null,
                    sector: (row.sector || 'Various').trim(),
                    country: (row.country || 'Global').trim(),
                    match_basis: typeof row.match_basis === 'string' ? row.match_basis : '',
                    registry_entity_type: null,
                }));
            }
            const usable = dedupeExposureRowsByEntityId(comps).filter(
                (row: ExposureRow) => row.name && !isPlaceholderCompanyRow(row)
            );
            const industryRows = usable.filter((row: ExposureRow) => !isGeopoliticalActorRow(row));
            const paid = isPaidContextTier(viewerTier);
            const showProGate = !paid && additionalProCount > 0;

            if (usable.length > 0) {
                html += `<div class="cb-exposure-single">`;
                html += `<p class="cb-exposure-kicker">Affected segments</p>`;
                html += `<h5 class="cb-exposure-subtitle">Industry &amp; Assets</h5>`;
                if (industryRows.length > 0) {
                    if (paid) {
                        html += renderIndustryExpandableList(industryRows);
                    } else {
                        const freeVisible = industryRows.slice(0, 1);
                        html += `<div class="cb-compact-list">`;
                        freeVisible.forEach((row: ExposureRow) => {
                            html += renderExposureRowHtml(row, 'industry');
                        });
                        if (showProGate) {
                            html += `<div class="cb-inline-pro-gate">${renderProGateCard(additionalProCount)}</div>`;
                        }
                        html += `</div>`;
                    }
                } else {
                    html += `<div class="cb-muted-text cb-exposure-empty">No industry or asset matches.</div>`;
                }
                html += `</div>`;
                if (showProGate && industryRows.length === 0) {
                    html += renderProGateCard(additionalProCount);
                }
            } else {
                html += `<div class="cb-muted-text">No related companies or infrastructure matched this alert.</div>`;
            }
        }
        else if (lowerTitle.includes('coverage')) {
            const canonicalTopic = normalizeTopicCode(topic);
            const topicVars = getTopicCssVars(canonicalTopic);
            const sectorRows = dedupeSectorRowsByEntityId(normalizeSectorImpacts(structuredSectorImpacts, body));
            const { regional, structural } = partitionRegionalSectorRows(sectorRows);
            html += `<div class="cb-section cb-section--structural-exposure" style="${topicVars}">`;
            html += `<h4 class="cb-section-title">Structural Exposure</h4>`;
            if (regional.length > 0) {
                html += `<div class="cb-regional-impact">`;
                html += `<p class="cb-exposure-kicker cb-exposure-kicker--regional">Regional impact</p>`;
                html += `<div class="cb-regional-tags" role="list">`;
                regional.forEach(r => {
                    html += renderSectorPillHtml(r, 'regional');
                });
                html += `</div></div>`;
            }
            if (structural.length > 0) {
                html += `<p class="cb-exposure-kicker">Impacted segments</p>`;
                html += `<div class="cb-structural-tags" role="list">`;
                structural.forEach(r => {
                    html += renderSectorPillHtml(r, 'structural');
                });
                html += `</div>`;
            } else if (sectorRows.length === 0) {
                html += `<div class="cb-muted-text">No structural exposure identified.</div>`;
            } else if (structural.length === 0 && regional.length > 0) {
                html += `<p class="cb-exposure-kicker">Impacted segments</p>`;
                html += `<div class="cb-muted-text">No additional industry segments aggregated for this alert.</div>`;
            }
        }
        else if (lowerTitle.includes('notes')) {
            html += `<div class="cb-section cb-section--notes">`;
            html += `<details class="cb-details">
                        <summary class="cb-details-summary">${displayTitle}</summary>
                        <div class="cb-section-body u-m-top-1">${simpleMarkdown(body)}</div>
                     </details>`;
        }
        else {
            html += `<div class="cb-section">`;
            html += `<h4 class="cb-section-title">${displayTitle}</h4>`;
            html += `<div class="cb-section-body">${simpleMarkdown(body)}</div>`;
        }
        
        html += `</div>`;
    });
    
    return html;
}

function renderFeedCard(item: FreeAlertFeedItem, index: number): string {
    const cardId = `cb-card-${index}`;
    const triggeredStr = formatDate(item.triggered_at);
    const canonicalTopic = normalizeTopicCode(item.topic);
    const topicStr = getTopicDisplayLabel(canonicalTopic);
    const topicVars = getTopicCssVars(canonicalTopic);
    const newsCount = item.related_news_count ?? 0;
    const entitiesCount = item.related_entities_count ?? 0;
    const displayTitle = cleanBriefTitle(item.title || item.target_label || 'Strategic Intelligence Alert');
    const teaser = escapeHtml(extractTeaserFromMarkdown(item.content_markdown || ''));

    return `
    <div class="pro-brief-card cb-brief-card" id="${cardId}" data-domain-card="1" style="${topicVars}">
      <div class="cb-brief-card-head u-flex-between">
        <span class="domain-chip meta-item-topic--tag">${topicStr}</span>
        <div class="cb-brief-card-head-meta">
          <span class="cb-brief-kind">Context Brief</span>
          <span class="cb-brief-ts">${escapeHtml(triggeredStr)}</span>
        </div>
      </div>
      <h3 class="cb-brief-card-title">${escapeHtml(displayTitle)}</h3>
      <p class="cb-brief-card-teaser">${teaser}</p>
      <div class="cb-brief-card-stats" aria-label="Evidence counts">
        <span class="cb-brief-stat-chip">📰 ${newsCount} news</span>
        <span class="cb-brief-stat-chip">🏢 ${entitiesCount} entities</span>
      </div>
      <div class="cb-brief-card-actions">
        <button type="button" class="btn-fb pro-brief-btn cb-open-context-btn" data-detail-index="${index}">
          View Full Context →
        </button>
      </div>
    </div>`;
}

/**
 * Renders the Context Briefs feed list.
 */
export function renderFreeAlertFeed(
    items: FreeAlertFeedItem[],
    container: HTMLElement,
    viewerTier: string = 'free'
): void {
    if (!items || items.length === 0) {
        container.innerHTML = `
            <div class="empty-state u-p-2 u-text-center">
                <div class="empty-icon">📡</div>
                <div class="empty-title">No alerts found</div>
                <div class="empty-subtitle">There are no Context Briefs yet, or none match your filters. New briefs appear after alerts are processed and the free-feed job runs.</div>
            </div>`;
        return;
    }

    const detailBodies = items.map(item =>
        renderStructuredContent(
            item.content_markdown || '',
            item.related_news,
            item.company_impacts,
            item.topic,
            item.sector_impacts,
            item.additional_pro_count ?? 0,
            viewerTier
        )
    );
    const modalTitles = items.map(item =>
        cleanBriefTitle(item.title || item.target_label || 'Strategic Intelligence Alert')
    );

    container.innerHTML = `
        <div class="cb-briefs-page">
            <div class="cb-feed-header">
                <h2 class="cb-feed-title">🛰 Context Briefs</h2>
                <p class="cb-feed-subtitle">
                    Rule-based context for recent alerts — same card language as Pro Structural Briefs.
                </p>
            </div>
            <div class="cb-briefs-grid cb-briefs-grid--context">
                ${items.map((item, i) => renderFeedCard(item, i)).join('')}
            </div>
            <div id="cb-context-modal-root" class="cb-modal-root" aria-hidden="true">
                <div class="cb-modal-backdrop" tabindex="-1"></div>
                <div class="cb-modal-panel" role="dialog" aria-modal="true" aria-labelledby="cb-modal-title">
                    <button type="button" class="cb-modal-close" aria-label="Close">×</button>
                    <h2 id="cb-modal-title" class="cb-modal-title"></h2>
                    <div class="cb-modal-body"></div>
                </div>
            </div>
        </div>`;

    container.dataset.cbViewerTier = viewerTier;

    const modalRoot = container.querySelector('#cb-context-modal-root') as HTMLElement;
    const modalBody = modalRoot.querySelector('.cb-modal-body') as HTMLElement;
    const modalTitleEl = modalRoot.querySelector('#cb-modal-title') as HTMLElement;
    const backdrop = modalRoot.querySelector('.cb-modal-backdrop') as HTMLElement;
    const closeBtn = modalRoot.querySelector('.cb-modal-close') as HTMLButtonElement;
    const panel = modalRoot.querySelector('.cb-modal-panel') as HTMLElement;

    const closeModal = () => {
        if (!modalRoot.classList.contains('cb-modal-root--open')) return;
        modalRoot.classList.remove('cb-modal-root--open');
        modalRoot.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('cb-modal-scroll-lock');
        modalBody.innerHTML = '';
        document.removeEventListener('keydown', onDocKey);
    };

    function onDocKey(ev: KeyboardEvent) {
        if (ev.key !== 'Escape' || !modalRoot.classList.contains('cb-modal-root--open')) return;
        ev.preventDefault();
        closeModal();
    }

    const openModal = (index: number) => {
        if (index < 0 || index >= detailBodies.length) return;
        modalTitleEl.textContent = modalTitles[index] || 'Context Brief';
        modalBody.innerHTML = detailBodies[index] || '';
        modalRoot.classList.add('cb-modal-root--open');
        modalRoot.setAttribute('aria-hidden', 'false');
        document.body.classList.add('cb-modal-scroll-lock');
        document.removeEventListener('keydown', onDocKey);
        document.addEventListener('keydown', onDocKey);
        closeBtn.focus();
    };

    container.querySelectorAll<HTMLButtonElement>('.cb-open-context-btn').forEach(btn => {
        btn.addEventListener('click', e => {
            e.stopPropagation();
            const idx = parseInt(btn.getAttribute('data-detail-index') || '-1', 10);
            openModal(idx);
        });
    });

    backdrop.addEventListener('click', closeModal);
    closeBtn.addEventListener('click', closeModal);

    modalBody.addEventListener('click', (e: MouseEvent) => {
        const expBtn = (e.target as HTMLElement).closest('[data-cb-expand-btn]') as HTMLButtonElement | null;
        if (expBtn) {
            e.preventDefault();
            const wrap = expBtn.closest('[data-cb-expand-wrap]');
            const hidden = wrap?.querySelector('[data-cb-expand-hidden]') as HTMLElement | null;
            if (wrap && hidden) {
                const expanded = expBtn.getAttribute('data-cb-expand-btn') === '1';
                if (expanded) {
                    wrap.classList.remove('cb-expand-wrap--open');
                    hidden.setAttribute('aria-hidden', 'true');
                    expBtn.setAttribute('data-cb-expand-btn', '0');
                    expBtn.setAttribute('aria-expanded', 'false');
                    const n = hidden.querySelectorAll('.cb-compact-item').length;
                    expBtn.textContent = n > 0 ? `+ ${n} more items ↓` : '';
                    expBtn.style.display = n > 0 ? '' : 'none';
                } else {
                    wrap.classList.add('cb-expand-wrap--open');
                    hidden.setAttribute('aria-hidden', 'false');
                    expBtn.setAttribute('data-cb-expand-btn', '1');
                    expBtn.setAttribute('aria-expanded', 'true');
                    expBtn.style.display = '';
                    expBtn.textContent = 'Show less ↑';
                }
            }
            return;
        }
        const gate = (e.target as HTMLElement).closest('[data-cb-pro-gate]');
        if (!gate) return;
        e.preventDefault();
        const tier = (container.dataset.cbViewerTier || 'free').toLowerCase();
        if (tier === 'pro' || tier === 'enterprise' || tier === 'experts') {
            window.dispatchEvent(new CustomEvent('trigger-tab', { detail: { tab: 'pro-insights' } }));
        } else {
            sessionStorage.setItem(
                'plansContextBriefUpsell',
                JSON.stringify({
                    message:
                        'On Pro, every matched company and infrastructure link from our registry is visible — with dependency-aligned Structural Briefs, not just this preview.',
                    ts: Date.now(),
                })
            );
            window.dispatchEvent(new CustomEvent('trigger-tab', { detail: { tab: 'plans' } }));
        }
        closeModal();
    });
    modalBody.addEventListener('keydown', (e: KeyboardEvent) => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const gate = (e.target as HTMLElement).closest('[data-cb-pro-gate]');
        if (!gate || !modalBody.contains(gate)) return;
        e.preventDefault();
        const tier = (container.dataset.cbViewerTier || 'free').toLowerCase();
        if (tier === 'pro' || tier === 'enterprise' || tier === 'experts') {
            window.dispatchEvent(new CustomEvent('trigger-tab', { detail: { tab: 'pro-insights' } }));
        } else {
            sessionStorage.setItem(
                'plansContextBriefUpsell',
                JSON.stringify({
                    message:
                        'On Pro, every matched company and infrastructure link from our registry is visible — with dependency-aligned Structural Briefs, not just this preview.',
                    ts: Date.now(),
                })
            );
            window.dispatchEvent(new CustomEvent('trigger-tab', { detail: { tab: 'plans' } }));
        }
        closeModal();
    });

    panel.addEventListener('click', e => e.stopPropagation());
}
