/**
 * topics.ts — Canonical mapping layer
 *
 * What actually reaches a caller: getTopicDef() resolves a topic_code to a label
 * and a colour, and every one of its 11 call sites reads only those two. It takes
 * both from STRATEGIC_TOPIC_LABELS and getTopicColor at the return (:361-362),
 * overwriting whatever the matched ACCESS_MAP entry carried — so ACCESS_MAP's own
 * `label` and `color` fields never reach a caller, and neither do `icon`,
 * `description` or `valueProposition`.
 *
 * `minTier` is NOT enforced here or anywhere else. Its only two readers are in
 * renderLockedTopicOverlay (subscription.ts), which has no callers, and no backend
 * path consults it — is_topic_allowed (gating.py:182) requires PRO for every topic
 * alike. It is kept as the record of which topics are meant to be gated when Expert
 * ships; the union type on it is enforced by tsc, so it costs nothing to hold.
 *
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
        color: '#58a6ff',
        description: 'Cross-asset correlation and macroeconomic risk detection.',
        valueProposition: 'Data-driven insights into central bank shifts and market inflections.',
    },
    {
        code: 'crypto_geopolitics',
        key: 'crypto_geopolitics',
        label: 'Crypto & Geopolitics',
        icon: '₿',
        minTier: 'pro',
        color: '#db6d28',
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
        color: '#f85149',
        description: 'Intelligence on emerging weapons systems and dual-use tech.',
        valueProposition: 'Strategic forecasting of disruptive military innovation.',
    },
    {
        code: 'supply_chain_intelligence',
        key: 'supply_chain_intelligence',
        label: 'Supply Chain Intel',
        icon: '📦',
        minTier: 'experts',
        color: '#3fb950',
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
 * ENTITLEMENT_MATRIX — a DISPLAY table, not a gate.
 *
 * It has one importer, subscription.ts, which reads it only to compute the ✓/✗
 * glyphs in the plan comparison table. No gate derives from it: the frontend's two
 * gate functions below are short-circuited, and the backend never sees it. Treat a
 * change here as a change to what the pricing page claims, and verify the claim
 * against api/gating.py separately.
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
 * Returns true. Both parameters are ignored — the underscores are the signature
 * saying so. It does NOT use TIER_ORDER, and has not since 2026-04-09.
 *
 * ba0d77c de-gated this and canAccessReport below, calling it "temporary de-gating
 * for development phase" in a subject-only commit message that states no duration
 * and no condition for restoring it. dabe19d, 24 minutes later, renamed the now-dead
 * parameters to silence noUnusedParameters — answering the one check that noticed,
 * rather than restoring the reads.
 *
 * Restoring the pre-ba0d77c body is NOT a drop-in: getTopicDef(null) resolves to
 * global_market_intelligence (minTier 'pro'), not the global entry, so a free user
 * would lose the daily global briefing — their whole declared entitlement. Fix
 * getTopicDef's null path first.
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

/** Strategic sectors — single UI vocabulary (6 fields). */
export const STRATEGIC_TOPIC_CODES = [
    'ENERGY',
    'MARKET',
    'AI_TECH',
    'CRYPTO',
    'DEFENSE',
    'SUPPLY_CHAIN',
] as const;

export type StrategicTopicCode = (typeof STRATEGIC_TOPIC_CODES)[number];

/**
 * Fixed UI colors per strategic sector.
 * Alert Stream, Context Briefs, Global Map — all use getTopicColor().
 */
export const TOPIC_COLORS: Record<StrategicTopicCode, string> = {
    ENERGY: '#d29922',
    MARKET: '#58a6ff',
    AI_TECH: '#bc8cff',
    CRYPTO: '#db6d28',
    DEFENSE: '#f85149',
    SUPPLY_CHAIN: '#3fb950',
};

export const STRATEGIC_TOPIC_LABELS: Record<StrategicTopicCode, string> = {
    ENERGY: 'Energy & Resources',
    MARKET: 'Global Market Intel',
    AI_TECH: 'AI & Semiconductors',
    CRYPTO: 'Crypto & Geopolitics',
    DEFENSE: 'Defense Technology',
    SUPPLY_CHAIN: 'Supply Chain Intelligence',
};

/** Alert Stream / map filter chips — all 6 strategic sectors (CRYPTO is top-level, not under MARKET). */
export const STRATEGIC_TOPIC_FILTERS: ReadonlyArray<{
    code: StrategicTopicCode;
    label: string;
    color: string;
}> = STRATEGIC_TOPIC_CODES.map(code => ({
    code,
    label: STRATEGIC_TOPIC_LABELS[code],
    color: TOPIC_COLORS[code],
}));

/** Backbone API path segment per strategic code (internal fetch only). */
export const BACKBONE_API_BY_STRATEGIC: Record<StrategicTopicCode, string> = {
    ENERGY: 'energy',
    MARKET: 'market',
    AI_TECH: 'ai',
    CRYPTO: 'crypto',
    DEFENSE: 'defense',
    SUPPLY_CHAIN: 'trade',
};

/** Legacy DB / API topic strings → strategic code (name unification). */
const LEGACY_TO_STRATEGIC: Record<string, StrategicTopicCode> = {
    energy: 'ENERGY',
    market: 'MARKET',
    trade: 'SUPPLY_CHAIN',
    TRADE: 'SUPPLY_CHAIN',
    crypto: 'CRYPTO',
    ai: 'AI_TECH',
    tech: 'AI_TECH',
    TECH: 'AI_TECH',
    semiconductor: 'AI_TECH',
    SEMICONDUCTOR: 'AI_TECH',
    defense: 'DEFENSE',
    energy_resource_risk: 'ENERGY',
    global_market_intelligence: 'MARKET',
    market_sentiment: 'MARKET',
    geopolitics: 'MARKET',
    crypto_geopolitics: 'CRYPTO',
    ai_semiconductor_intelligence: 'AI_TECH',
    defense_technology: 'DEFENSE',
    supply_chain_intelligence: 'SUPPLY_CHAIN',
    global: 'MARKET',
    ENERGY_RESOURCE_RISK: 'ENERGY',
    GLOBAL_MARKET_INTELLIGENCE: 'MARKET',
    MARKET_SENTIMENT: 'MARKET',
    GEOPOLITICS: 'MARKET',
    CRYPTO_GEOPOLITICS: 'CRYPTO',
    AI_SEMICONDUCTOR_INTELLIGENCE: 'AI_TECH',
    DEFENSE_TECHNOLOGY: 'DEFENSE',
    SUPPLY_CHAIN_INTELLIGENCE: 'SUPPLY_CHAIN',
};

/**
 * Normalize any topic string to one of the 6 strategic sector codes.
 */
export function normalizeTopicCode(raw: string | null | undefined): StrategicTopicCode {
    if (!raw) return 'MARKET';
    const trimmed = raw.trim();
    if (!trimmed) return 'MARKET';

    const upper = trimmed.toUpperCase().replace(/-/g, '_');
    if (upper in TOPIC_COLORS) return upper as StrategicTopicCode;
    if (upper in LEGACY_TO_STRATEGIC) return LEGACY_TO_STRATEGIC[upper];

    const lower = trimmed.toLowerCase();
    if (lower in LEGACY_TO_STRATEGIC) return LEGACY_TO_STRATEGIC[lower];

    if (upper.includes('ENERGY') || upper.includes('OIL') || upper.includes('GAS')) return 'ENERGY';
    if (upper.includes('SUPPLY') || upper.includes('TRADE') || upper.includes('LOGISTIC')) return 'SUPPLY_CHAIN';
    // CRYPTO before MARKET/GLOBAL — avoid folding crypto_geopolitics into MARKET via "GLOBAL" substring heuristics
    if (
        upper.includes('CRYPTO') ||
        upper.includes('BITCOIN') ||
        upper.includes('STABLECOIN') ||
        upper.includes('BLOCKCHAIN') ||
        upper.includes('ETHEREUM')
    ) {
        return 'CRYPTO';
    }
    if (upper.includes('DEFENSE') || upper.includes('MILITARY')) return 'DEFENSE';
    if (upper.includes('SEMICONDUCTOR') || upper.includes('AI_') || upper === 'AI') return 'AI_TECH';
    if (upper.includes('MARKET') || upper.includes('GEOPOLIT')) return 'MARKET';
    if (upper === 'GLOBAL' || upper.endsWith('_GLOBAL')) return 'MARKET';

    return 'MARKET';
}

/** Accent color for alert borders and topic tags (category, not severity). */
export function getTopicColor(topic: string | null | undefined): string {
    return TOPIC_COLORS[normalizeTopicCode(topic)];
}

/** Topics shown in Pro Hub “Monitored Domains” preview chips (legacy keys → normalize). */
export const UI_TOPIC_PREVIEW_CODES = [
    'energy_resource_risk',
    'global_market_intelligence',
    'ai_semiconductor_intelligence',
    'crypto_geopolitics',
    'defense_technology',
    'supply_chain_intelligence',
] as const;

/** Inline CSS custom properties for cards, chips, and Pro brief chrome. */
export function getTopicCssVars(topic: string | null | undefined): string {
    const color = getTopicColor(topic);
    return `--topic-color:${color};--domain-accent:${color};--domain-bg:color-mix(in srgb, ${color} 12%, transparent);`;
}

/** Human-readable label for any topic input (always one of 6 strategic names). */
export function getTopicDisplayLabel(topic: string | null | undefined): string {
    return STRATEGIC_TOPIC_LABELS[normalizeTopicCode(topic)];
}

/** @deprecated Use getTopicDisplayLabel — map/feed share the same 6 labels. */
export function getTopicMapFilterLabel(topic: string | null | undefined): string {
    return getTopicDisplayLabel(topic);
}

const BACKBONE_API_SECTOR_TO_STRATEGIC: Record<string, StrategicTopicCode> = {
    energy: 'ENERGY',
    market: 'MARKET',
    trade: 'SUPPLY_CHAIN',
    ai: 'AI_TECH',
    crypto: 'CRYPTO',
    defense: 'DEFENSE',
};

/** Resolve backbone API path segment → strategic code (never fold crypto into market). */
export function strategicTopicFromBackboneApi(apiSector: string): StrategicTopicCode {
    const key = (apiSector || '').trim().toLowerCase();
    if (key in BACKBONE_API_SECTOR_TO_STRATEGIC) {
        return BACKBONE_API_SECTOR_TO_STRATEGIC[key];
    }
    return normalizeTopicCode(apiSector);
}

/**
 * Look up a TopicDef by its DB topic_code (including null → global).
 */
export function getTopicDef(code: string | null): TopicDef {
    const strategic = normalizeTopicCode(code);
    const byStrategic = ACCESS_MAP.find(
        t => t.code !== null && normalizeTopicCode(t.code) === strategic
    );
    if (byStrategic) {
        return {
            ...byStrategic,
            label: STRATEGIC_TOPIC_LABELS[strategic],
            color: getTopicColor(strategic),
        };
    }
    const found = ACCESS_MAP.find(t => t.code === code || (code === null && t.key === 'global'));
    if (found) {
        const s = normalizeTopicCode(found.code);
        return { ...found, label: STRATEGIC_TOPIC_LABELS[s], color: getTopicColor(s) };
    }
    return ACCESS_MAP[0];
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
