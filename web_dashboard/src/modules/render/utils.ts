import type { Alert } from '../api';

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
    return md
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') // Escape HTML
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
