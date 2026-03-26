/**
 * topics.ts — Canonical mapping layer
 *
 * Single source of truth for topic_code → label, icon, and min tier.
 * All UI modules must import from here. No inline label strings allowed.
 */

export interface TopicDef {
    /** Matches `topic_code` in the DB. null = global. */
    code: string | null;
    /** URL-safe key used in API query params */
    key: string;
    label: string;
    icon: string;
    /** Minimum plan tier required to access this topic */
    minTier: 'free' | 'pro' | 'experts';
    /** Display color accent */
    color: string;
}

/**
 * ACCESS_MAP — ordered list of all 7 report domains.
 * topic_code `null` in the DB maps to key `'global'`.
 */
export const ACCESS_MAP: TopicDef[] = [
    {
        code: null,
        key: 'global',
        label: 'Global Briefing',
        icon: '🌐',
        minTier: 'free',
        color: '#58a6ff',
    },
    {
        code: 'energy_resource_risk',
        key: 'energy_resource_risk',
        label: 'Energy & Resource Risk',
        icon: '⚡',
        minTier: 'pro',
        color: '#d29922',
    },
    {
        code: 'global_market_intelligence',
        key: 'global_market_intelligence',
        label: 'Global Market Intel',
        icon: '💰',
        minTier: 'pro',
        color: '#3fb950',
    },
    {
        code: 'crypto_geopolitics',
        key: 'crypto_geopolitics',
        label: 'Crypto & Geopolitics',
        icon: '₿',
        minTier: 'pro',
        color: '#f78166',
    },
    {
        code: 'ai_semiconductor_intelligence',
        key: 'ai_semiconductor_intelligence',
        label: 'AI & Semiconductors',
        icon: '🤖',
        minTier: 'pro',
        color: '#bc8cff',
    },
    {
        code: 'defense_technology',
        key: 'defense_technology',
        label: 'Defense Technology',
        icon: '🛡️',
        minTier: 'pro',
        color: '#ff7b72',
    },
    {
        code: 'supply_chain_intelligence',
        key: 'supply_chain_intelligence',
        label: 'Supply Chain Intel',
        icon: '📦',
        minTier: 'pro',
        color: '#79c0ff',
    },
];

/** Tier hierarchy for comparison */
const TIER_ORDER: Record<string, number> = {
    free: 0,
    pro: 1,
    experts: 2,
    enterprise: 3,
};

/**
 * Returns true if `userTier` meets or exceeds the topic's `minTier`.
 */
export function canAccessTopic(userTier: string, topic: TopicDef): boolean {
    return (TIER_ORDER[userTier] ?? 0) >= (TIER_ORDER[topic.minTier] ?? 0);
}

/**
 * Look up a TopicDef by its DB topic_code (including null → global).
 */
export function getTopicDef(code: string | null): TopicDef {
    const found = ACCESS_MAP.find(t => t.code === code || (code === null && t.key === 'global'));
    return found ?? ACCESS_MAP[0]; // fallback to global
}

/**
 * Normalise raw DB/API report_type strings to canonical short form.
 * Handles both 'daily_global' (legacy) and 'daily' (current) formats.
 */
export function normalizeReportType(raw: string | null | undefined): 'daily' | 'weekly' | 'monthly' {
    if (!raw) return 'daily';
    const s = raw.toLowerCase();
    if (s.startsWith('monthly')) return 'monthly';
    if (s.startsWith('weekly')) return 'weekly';
    return 'daily';
}

/** Human-readable label for a normalised report type */
export const REPORT_TYPE_LABELS: Record<string, string> = {
    daily: 'Daily Briefing',
    weekly: 'Weekly Analysis',
    monthly: 'Monthly Deep-Dive',
};

/**
 * Minimum plan tier required to view a report_type.
 */
export const REPORT_TYPE_MIN_TIER: Record<string, string> = {
    daily: 'free',
    weekly: 'pro',
    monthly: 'experts',
};
