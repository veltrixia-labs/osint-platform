import type { Alert } from '../api';
import { normalizeTopicCode } from '../topics';

const INTEL_DATE_LOCALE = 'en-US';

/**
 * English-only date for intelligence terminals (ignores browser locale).
 */
export function formatIntelDate(
    dateInput: string | Date | number | null | undefined,
    options: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', year: 'numeric' },
): string {
    if (dateInput == null || dateInput === '') return '';
    const d = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleDateString(INTEL_DATE_LOCALE, options);
}

/**
 * English-only date/time for intelligence terminals (ignores browser locale).
 */
export function formatIntelDateTime(
    dateInput: string | Date | number | null | undefined,
    options: Intl.DateTimeFormatOptions = {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    },
): string {
    if (dateInput == null || dateInput === '') return '';
    const d = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleString(INTEL_DATE_LOCALE, options);
}

/** English-only time (e.g. pulse bar). */
export function formatIntelTime(
    dateInput: string | Date | number | null | undefined,
    options: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' },
): string {
    if (dateInput == null || dateInput === '') return '';
    const d = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleTimeString(INTEL_DATE_LOCALE, options);
}

/**
 * Precise UTC timestamp for Pro cards (YYYY-MM-DD HH:mm:ss), aligned with feed density.
 */
export function formatIntelPreciseTimestamp(
    dateInput: string | Date | number | null | undefined,
): string {
    if (dateInput == null || dateInput === '') return '';
    const d = dateInput instanceof Date ? dateInput : new Date(dateInput);
    if (Number.isNaN(d.getTime())) return '';
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}

/** Compact English date+time for feed cards (Alert Stream, Context Briefs). */
export function formatIntelFeedTimestamp(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso || '—';
    return formatIntelDateTime(d, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}

/**
 * Formats an intensity value for UI display.
 */
export function formatIntensity(val: number | undefined | null): string | null {
    if (typeof val !== 'number' || isNaN(val) || val <= 0) return null;
    const rounded = val.toFixed(1);
    let label = 'STABLE/WATCH';
    if (val >= 8.0) label = 'CRITICAL';
    else if (val >= 4.5) label = 'ELEVATED RISK';
    return `${rounded} (${label})`;
}

/**
 * Hierarchical coordinate extraction to handle differing API response formats.
 * Priority: Top-level > metadata_json > cascading_impacts[0]
 */
export function getAlertCoords(alert: Alert): { lat: number, lng: number, source: string } | null {
    // 1. Direct API Fields (Modern)
    if (typeof alert.location_lat === 'number' && typeof alert.location_lng === 'number') {
        return { lat: alert.location_lat, lng: alert.location_lng, source: 'Top-Level' };
    }
    
    // 2. Metadata Nesting (Legacy)
    const meta = alert.metadata_json as any;
    if (typeof meta?.location_lat === 'number' && typeof meta?.location_lng === 'number') {
        return { lat: meta.location_lat, lng: meta.location_lng, source: 'Metadata' };
    }
    
    // 3. First Impact Fallback
    const impacts = (alert.cascading_impacts || (alert.metadata_json as any)?.cascading_impacts) as any[];
    if (impacts && impacts.length > 0) {
        const coords = getNodeCoords(impacts[0]);
        if (coords) return { ...coords, source: `Impact-0:${coords.source}` };
    }
    
    console.warn(`[Antigravity] Coordinate Resolution Failure for Alert ${alert.id}. No lat/lng found.`);
    return null;
}

/**
 * Generic coordinate extractor for Stakeholder/Finding nodes.
 */
export function getNodeCoords(node: any): { lat: number, lng: number, source: string } | null {
    if (typeof node.location_lat === 'number' && typeof node.location_lng === 'number') {
        return { lat: node.location_lat, lng: node.location_lng, source: 'Node-Direct' };
    }
    if (typeof node.metadata_json?.location_lat === 'number' && typeof node.metadata_json?.location_lng === 'number') {
        return { lat: node.metadata_json.location_lat, lng: node.metadata_json.location_lng, source: 'Node-Metadata' };
    }
    return null;
}

/**
 * Sanitizes markdown content by identifying raw intensity floats and formatting them.
 */
export function sanitizeMarkdownIntensities(text: string): string {
    if (!text) return text;
    
    // 1. Remove redundant systemic prefixes that reduce scan speed
    const prefixExcludes = [
        /Emerging high-risk event detected:\s*/gi,
        /Rapid risk escalation detected:\s*/gi,
        /Sustained activity detected for event:\s*/gi,
        /High-risk signal:\s*/gi
    ];
    let cleanText = text;
    prefixExcludes.forEach(re => { cleanText = cleanText.replace(re, ''); });

    // 2. Robust regex: Matches "Intensity: 3.8", "(Intensity: 3.8)", "Intensity Score: 3.8", etc.
    return cleanText.replace(/\(?Intensity(?:\s+Score)?\s*:\s*(\d+(?:\.\d+)?)\)?/gi, (match, val) => {
        const v = parseFloat(val);
        const formatted = formatIntensity(v);
        return formatted ? `Intensity: ${formatted}` : match;
    });
}

/**
 * Simple Markdown parser for report action lists and outcomes.
 */
export function simpleMarkdown(md: string): string {
    if (!md) return "";

    // ── Pre-pass: extract and convert Markdown tables before line-level processing ──
    // Matches a header row, a separator row (|---|), and one or more data rows.
    const tableRegex = /(\|.+\|\n\|[-| :]+\|\n(?:\|.+\|\n?)+)/g;
    const mdWithTables = md.replace(tableRegex, (tableBlock) => {
        const lines = tableBlock.trim().split('\n').filter(l => l.trim());
        if (lines.length < 3) return tableBlock; // need header + separator + at least 1 row

        const parseRow = (line: string): string[] =>
            line.split('|').map((cell: string) => cell.trim()).filter((_, i, arr) => i > 0 && i < arr.length - 1);

        const headers = parseRow(lines[0]);
        // lines[1] is separator — skip
        const dataRows = lines.slice(2);

        const thHtml = headers.map(h => `<th>${h}</th>`).join('');
        const trHtml = dataRows.map(row => {
            const cells = parseRow(row);
            // Pad missing cells
            while (cells.length < headers.length) cells.push('');
            return `<tr>${cells.map((cell: string) => `<td>${cell}</td>`).join('')}</tr>`;
        }).join('');

        return `<div class="table-responsive"><table class="feed-table"><thead><tr>${thHtml}</tr></thead><tbody>${trHtml}</tbody></table></div>`;
    });

    return mdWithTables
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') // Escape HTML
        // Restore specific HTML that was already built or generated safely
        .replace(/&lt;(\/?(table|thead|tbody|tr|th|td|details|summary|blockquote|div|ul|li|strong|em)[^&]*)&gt;/g, '<$1>')
        .replace(/^### (.*$)/gm, '<h4>$1</h4>')
        .replace(/^## (.*$)/gm, '<h3>$1</h3>')
        .replace(/^# (.*$)/gm, '<h2>$1</h2>')
        .replace(/^\- (High Priority|Monitor|Maintain): (.*$)/gm, (_, priority, text) => {
            const cls = priority.toLowerCase().replace(' ', '-');
            let cleanText = text;
            let rationaleHtml = '';
            let confidenceHtml = '';
            
            // Extract Rationale first
            const rationaleMatch = cleanText.match(/ — \*(.*)\*/);
            if (rationaleMatch) {
                cleanText = cleanText.replace(rationaleMatch[0], '');
                rationaleHtml = `<span class="report-action-rationale">${rationaleMatch[1]}</span>`;
            }
            
            // Extract Confidence second
            const confidenceMatch = cleanText.match(/ — Confidence: (High|Medium|Low)/i);
            if (confidenceMatch) {
                const confValue = confidenceMatch[1];
                const confClass = confValue.toLowerCase() === 'low' ? 'confidence-low' : '';
                cleanText = cleanText.replace(confidenceMatch[0], '');
                confidenceHtml = `<span class="confidence-tag ${confClass}">${confValue}</span>`;
            }
            
            return `<li class="priority-${cls}">${cleanText.trim()}${rationaleHtml}${confidenceHtml}</li>`;
        })
        .replace(/^\* (.*$)/gm, (_, content) => {
            // Case: Outcome with structured metadata: [IMPACT: HIGH, TIME: Immediate]
            const metaMatch = content.match(/\[IMPACT:\s*(HIGH|MEDIUM|LOW),\s*TIME:\s*([^\]]+)\]/i);
            if (metaMatch) {
                const textOnly = content.replace(metaMatch[0], '').trim();
                const impact = metaMatch[1].toUpperCase();
                const time = metaMatch[2];
                return `<li>${textOnly} <span class="impact-tag impact-${impact.toLowerCase()}">${impact} IMPACT</span> <span class="separator">·</span> <span class="time-tag">${time}</span></li>`;
            }
            return `<li>${content}</li>`;
        })
        .replace(/^\- (.*$)/gm, '<li>$1</li>')
        .replace(/\*\*(.*)\*\*/g, '<b>$1</b>')
        .replace(/\*(.*)\*/g, '<i>$1</i>')
        .replace(/!\[(.*?)\]\((.*?)\)/g, '<img src="$2" alt="$1" class="report-visual u-m-top-1" style="max-width:100%; border-radius:8px; border:1px solid var(--border);">')
        .replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank" style="color:var(--tier-grace);">$1</a>')
        .replace(/\n/g, '<br>');
}

/**
 * Stable CSS hook derived from canonical topic code (prefer getTopicCssVars on the element).
 */
export function getDomainSlugClass(topicCode: string | null | undefined): string {
    const code = normalizeTopicCode(topicCode);
    return `topic-${code.toLowerCase().replace(/_/g, '-')}`;
}
