import type { Alert } from './api';

const KNOWN_SOURCE_SLUGS = new Set([
    'reddit', 'technip', 'twitter', 'x', 'facebook', 'linkedin',
    'youtube', 'telegram', 'rss', 'newsapi', 'google', 'bing',
    'yahoo', 'bloomberg', 'reuters', 'apnews', 'osint',
]);

/**
 * True when text looks like a source slug / label, not a news headline.
 */
export function isPlaceholderAlertLabel(text: string | null | undefined): boolean {
    if (!text) return true;
    const s = text.trim();
    if (s.length < 4) return true;
    const lower = s.toLowerCase();
    if (KNOWN_SOURCE_SLUGS.has(lower)) return true;
    if (!/\s/.test(s) && s.length <= 28 && /^[a-z0-9._-]+$/i.test(s) && s === lower) {
        return true;
    }
    if (!/\s/.test(s) && s.includes('.') && s.length <= 48) return true;
    return false;
}

export type AlertHeadlineState = { text: string; pending: boolean };

/**
 * Resolve card headline: API title → evidence → target_label; skeleton while backbone loads.
 */
export function resolveAlertHeadline(alert: Alert): AlertHeadlineState {
    const status = (alert.backbone_discovery_status || 'idle').toLowerCase();
    const candidates = [
        alert.title,
        alert.evidence_list?.[0]?.title,
        alert.target_label,
    ];

    for (const raw of candidates) {
        const t = (raw || '').trim();
        if (t && !isPlaceholderAlertLabel(t)) {
            return { text: t, pending: false };
        }
    }

    if (status === 'processing' || status === 'idle') {
        return { text: '', pending: true };
    }

    const fallback = (alert.target_label || alert.title || '').trim();
    return { text: fallback || 'Strategic signal', pending: false };
}
