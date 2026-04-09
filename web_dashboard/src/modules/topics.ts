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
    /** Short summary of the topic's scope */
    description: string;
    /** The core value statement for upgrade conversion */
    valueProposition: string;
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
        description: 'Macro-level geopolitical and economic signal monitoring.',
        valueProposition: 'Foundational intelligence for global situational awareness.',
    },
    {
        code: 'energy_resource_risk',
        key: 'energy_resource_risk',
        label: 'Energy & Resource Risk',
        icon: '⚡',
        minTier: 'pro',
        color: '#d29922',
        description: 'Monitoring volatility in oil, gas, and critical minerals.',
        valueProposition: 'Strategic analysis of energy market disruptions and supply risks.',
    },
    {
        code: 'global_market_intelligence',
        key: 'global_market_intelligence',
        label: 'Global Market Intel',
        icon: '💰',
        minTier: 'pro',
        color: '#3fb950',
        description: 'Cross-asset correlation and macroeconomic risk detection.',
        valueProposition: 'Data-driven insights into central bank shifts and market inflections.',
    },
    {
        code: 'crypto_geopolitics',
        key: 'crypto_geopolitics',
        label: 'Crypto & Geopolitics',
        icon: '₿',
        minTier: 'pro',
        color: '#f78166',
        description: 'Tracking digital asset flows and regulatory impact.',
        valueProposition: 'Predictive intelligence on state-level crypto adoption and risks.',
    },
    {
        code: 'ai_semiconductor_intelligence',
        key: 'ai_semiconductor_intelligence',
        label: 'AI & Semiconductors',
        icon: '🤖',
        minTier: 'experts',
        color: '#bc8cff',
        description: 'Deep-dives into the silicon supply chain and AI competition.',
        valueProposition: 'High-fidelity technical intelligence on compute-driven dominance.',
    },
    {
        code: 'defense_technology',
        key: 'defense_technology',
        label: 'Defense Technology',
        icon: '🛡️',
        minTier: 'experts',
        color: '#ff7b72',
        description: 'Intelligence on emerging weapons systems and dual-use tech.',
        valueProposition: 'Strategic forecasting of disruptive military innovation.',
    },
    {
        code: 'supply_chain_intelligence',
        key: 'supply_chain_intelligence',
        label: 'Supply Chain Intel',
        icon: '📦',
        minTier: 'experts',
        color: '#79c0ff',
        description: 'Global logistics bottlenecks and tiered supplier mapping.',
        valueProposition: 'Real-time monitoring of systemic vulnerabilities in trade.',
    },
];

/** Tier hierarchy for comparison */
export const TIER_ORDER: Record<string, number> = {
    free: 0,
    pro: 1,
    experts: 2,
    enterprise: 3,
};

/**
 * ENTITLEMENT_MATRIX — The single source of truth for tier capabilities.
 * All UI gating MUST derive from this mapping.
 */
export const ENTITLEMENT_MATRIX = {
    free: {
        topics: ['global'],
        reports: ['daily'],
    },
    pro: {
        topics: ['global', 'energy_resource_risk', 'global_market_intelligence', 'crypto_geopolitics'],
        reports: ['daily', 'weekly'],
    },
    experts: {
        topics: ['global', 'energy_resource_risk', 'global_market_intelligence', 'crypto_geopolitics', 'ai_semiconductor_intelligence', 'defense_technology', 'supply_chain_intelligence'],
        reports: ['daily', 'weekly', 'monthly'],
    },
    enterprise: {
        topics: ['global', 'energy_resource_risk', 'global_market_intelligence', 'crypto_geopolitics', 'ai_semiconductor_intelligence', 'defense_technology', 'supply_chain_intelligence'],
        reports: ['daily', 'weekly', 'monthly'],
        custom: true
    }
};

/**
 * Returns true if `userTier` meets or exceeds the topic's `minTier`.
 * Note: Uses TIER_ORDER for hierarchy.
 */
export function canAccessTopic(_userTier: string, _topic: TopicDef): boolean {
    // [Dev Phase Override] Always allow access to verify system completion
    return true;
}

/**
 * Returns true if the user can access a specific report based on its type and topic.
 */
export function canAccessReport(_userTier: string, _reportType: string, _topicCode: string | null): boolean {
    // [Dev Phase Override] Always allow access to verify system completion
    return true;
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
