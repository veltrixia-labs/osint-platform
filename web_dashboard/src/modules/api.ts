/**
 * api.ts
 * OSINT Risk Intelligence API Client
 */

/** Default page size for Alert Stream list endpoints. */
export const ALERT_STREAM_DISPLAY_LIMIT = 30;

/** Default page size for Context Briefs list endpoints. */
export const CONTEXT_BRIEFS_DISPLAY_LIMIT = 40;

/**
 * Resolve API prefix for fetch():
 * 1. VITE_API_BASE_URL when set at build time (Render / CI).
 * 2. Same-origin `/api` when the dashboard is served from a non-local host (production).
 * 3. `/api` for local dev (Vite proxy to the backend).
 */
function resolveApiBase(): string {
    const fromEnv = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
    if (fromEnv) {
        let raw = fromEnv;
        if (raw.startsWith('http') && !raw.endsWith('/api')) {
            raw = raw.replace(/\/$/, '') + '/api';
        }
        return raw;
    }
    if (typeof globalThis !== 'undefined' && 'location' in globalThis) {
        const loc = (globalThis as unknown as Window).location;
        if (loc?.hostname && loc.hostname !== 'localhost' && loc.hostname !== '127.0.0.1') {
            const port = loc.port ? `:${loc.port}` : '';
            return `${loc.protocol}//${loc.hostname}${port}/api`;
        }
    }
    return '/api';
}

const API_BASE = resolveApiBase();

/** Exposed for startup logging / debugging (no secrets). */
export function getResolvedApiBase(): string {
    return API_BASE;
}

// --- Types & Interfaces ---

export interface UserMe {
    id: string;
    email: string;
    chat_id: string | null;
    role: string;
    tier: string;
    expires_at: string | null;
    features: {
        pro_insights: boolean;
        expert_intelligence: boolean;
        team_admin: boolean;
        custom_topics: boolean;
        onboarding: boolean;
        support: boolean;
    };
    limits: {
        impact_depth: number;
        topics: string[];
        reports: string[];
    };
}

export interface Alert {
    id: string;
    title?: string;
    target_label: string;
    topic: string;
    severity: string;
    triggered_at: string;
    fidelity_score: number;
    intensity: number;
    intensity_label: string;
    intensity_display: string;
    status: string;
    country?: string;
    description?: string;
    source_url?: string;
    evidence_list?: any[];
    cascading_impacts?: any[];
    location_lat?: number;
    location_lng?: number;
    related_report_id?: string;
    intelligence_score?: number;
    is_high_fidelity?: boolean;
    backbone_discovery_status?: string;
    is_locked: boolean;
    metadata_json?: any;
}

export interface Report {
    id: string;
    title: string;
    summary: string;
    content_markdown: string;
    report_type: string;
    topic_code: string;
    created_at: string;
}

export interface AnalystProfile {
    id: string;
    email: string;
    chat_id: string | null;
    user_role: string;
    subscription_tier: string;
    watch_keywords: string[];
}

export interface HealthData {
    review_rate: number;
    suppression_ratio: number;
    total_alerts: number;
    high_fidelity_count: number;
    status_summary: string;
    last_week_total: number;
}

export interface ProInsights {
    time_pressure: string;
    causal_logic: string;
    action_priority: string;
    strategic_context: string;
    risk_summary?: Record<string, any>;
    sector_distribution?: Record<string, number>;
    top_entities?: any[];
    momentum_alerts?: Alert[];
}

export interface ExpertIntelligence {
    counterfactuals: any[];
    tail_risks: any[];
    adversarial_take: string;
    confidence_score: number;
    scenario_outlook?: any[];
    full_impact_chains?: any[];
    cross_domain_risks?: any[];
}

export interface FreeAlertFeedItem {
    alert_id: string;
    title: string;
    topic: string;
    target_label: string;
    triggered_at: string;
    related_news_count: number;
    related_news_source: string;
    related_entities_count: number;
    related_news?: {
        title: string;
        source: string;
        category: string;
        published: string;
        url: string | null;
    }[];
    content_markdown: string;
    generated_at?: string;
    /** Registry / fallback context for location-linked rows (Context Briefs). */
    location_context?: Record<string, unknown>;
    /** Structured rows for Related Companies (preferred over markdown table parse). */
    company_impacts?: {
        company_name?: string | null;
        ticker?: string | null;
        entity_id?: string | null;
        entity_type?: string | null;
        sector?: string | null;
        country?: string | null;
        match_basis?: string[];
        /** Location registry entity type: `country` → geopolitical bucket in UI */
        registry_entity_type?: string | null;
    }[];
    /** Sector aggregates for Structural Exposure badges (sorted server-side). */
    sector_impacts?: {
        sector?: string | null;
        matched_entities: number;
        entity_id?: string | null;
        entity_type?: string | null;
        label?: string | null;
        name?: string | null;
    }[];
    /** Entity rows not included in `company_impacts` on Free (Pro gate); 0 when paid tier. */
    additional_pro_count?: number;
}

export interface ProStructuralReportItem {
    id: string;
    title: string;
    report_type: string;
    topic: string;
    plan_required: string;
    is_premium: boolean;
    created_at: string;
    content_markdown?: string;
    teaser_md?: string;
    structured_payload?: any;
}

/** Alias for Context Briefs feed responses (`fetchFreeAlerts`). */
export type FreeAlertFeedList = FreeAlertFeedItem[];

/** Alias for Pro structural brief collections (`fetchProStructuralReports`). */
export type ProStructuralReportList = ProStructuralReportItem[];

export type SyncStatus = 'stable' | 'retrying' | 'offline';

// --- State Management ---

const getLoggingOut = () => sessionStorage.getItem("isLoggingOut") === "true";
const setLoggingOut = (val: boolean) => {
    if (val) sessionStorage.setItem("isLoggingOut", "true");
    else sessionStorage.removeItem("isLoggingOut");
};

function dispatchSyncEvent(status: SyncStatus) {
    window.dispatchEvent(new CustomEvent('api-sync-status', {
        detail: { status, timestamp: new Date() }
    }));
}

// --- Core Fetch with Auth ---

async function fetchWithAuth(url: string, options: RequestInit = {}, skipSyncEvent = false): Promise<Response> {
    if (getLoggingOut()) return new Response(null, { status: 401 });

    const headers = new Headers(options.headers || {});
    const token = localStorage.getItem('access_token');
    if (token) headers.set('Authorization', `Bearer ${token}`);

    try {
        const resp = await fetch(url, { ...options, headers });
        if (!skipSyncEvent) {
            if (resp.ok) dispatchSyncEvent('stable');
            else if (resp.status >= 500) dispatchSyncEvent('retrying');
        }
        return resp;
    } catch (e) {
        console.error(`[API Connectivity Error] URL: ${url}`, e);
        if (!skipSyncEvent) dispatchSyncEvent('offline');
        return new Response(JSON.stringify({ error: 'network_error' }), { status: 0 });
    }
}

// --- API Client ---

export const apiClient = {
    async get(path: string, options: RequestInit = {}, skipSyncEvent = false) {
        const separator = path.includes('?') ? '&' : '?';
        const url = `${API_BASE}${path}${separator}_t=${Date.now()}`;
        return fetchWithAuth(url, { ...options, method: 'GET' }, skipSyncEvent);
    },
    async post(path: string, body?: any, options: RequestInit = {}, skipSyncEvent = false) {
        const url = `${API_BASE}${path}`;
        return fetchWithAuth(url, {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options.headers },
            body: body ? JSON.stringify(body) : undefined
        }, skipSyncEvent);
    }
};

// --- Exported API Functions ---

export async function login(email: any, password?: string) {
    const data = typeof email === 'object' ? email : { email, password };
    const resp = await apiClient.post('/auth/token', data);
    if (resp.ok) {
        const body = await resp.json();
        if (body.access_token) localStorage.setItem('access_token', body.access_token);
    }
    return resp;
}

export async function signup(email: any, password?: string, chat_id?: string) {
    const data = typeof email === 'object' ? email : { email, password, chat_id };
    return await apiClient.post('/auth/signup', data);
}

export async function logout() {
    setLoggingOut(true);
    const resp = await apiClient.post('/auth/logout');
    localStorage.removeItem('access_token');
    return resp;
}

export async function fetchMe(_cache?: any): Promise<UserMe | null> {
    try {
        const resp = await apiClient.get('/auth/me', {}, true);
        if (!resp.ok) return null;
        return await resp.json();
    } catch { return null; }
}

export async function fetchAlerts(params: Record<string, string> = {}): Promise<Alert[]> {
    const query = new URLSearchParams(params).toString();
    const resp = await apiClient.get(`/alerts?${query}`);
    return resp.ok ? await resp.json() : [];
}

export async function fetchAlert(id: string): Promise<Alert> {
    const resp = await apiClient.get(`/alerts/${id}`);
    if (!resp.ok) throw new Error("Alert not found");
    return await resp.json();
}

export async function fetchLiveAlerts(limit: number = ALERT_STREAM_DISPLAY_LIMIT): Promise<Alert[]> {
    const resp = await apiClient.get(`/alerts/live?limit=${limit}`);
    return resp.ok ? await resp.json() : [];
}

export async function fetchReports(_cache?: any, _force?: boolean): Promise<Report[]> {
    const resp = await apiClient.get('/reports');
    return resp.ok ? await resp.json() : [];
}

export async function fetchReport(id: string): Promise<Report> {
    const resp = await apiClient.get(`/reports/${id}`);
    if (!resp.ok) throw new Error("Report not found");
    return await resp.json();
}

export async function fetchFreeAlerts(
    params: { topic?: string; limit?: number } = {}
): Promise<FreeAlertFeedList> {
    const query = new URLSearchParams();
    if (params.topic) query.set('topic', params.topic);
    query.set('limit', String(params.limit ?? CONTEXT_BRIEFS_DISPLAY_LIMIT));
    const qs = query.toString();
    const resp = await apiClient.get(`/free/alerts${qs ? `?${qs}` : ''}`);
    if (!resp.ok) {
        const detail = await resp.text().catch(() => '');
        console.error('[API] fetchFreeAlerts HTTP', resp.status, detail?.slice(0, 200));
        throw new Error(
            resp.status === 401
                ? 'Sign in required to load Context Briefs.'
                : resp.status === 429
                  ? 'Rate limited. Try again in a minute.'
                  : `Could not load alerts (HTTP ${resp.status}).`
        );
    }
    const data = await resp.json();
    if (!Array.isArray(data)) {
        console.error('[API] fetchFreeAlerts: expected JSON array, got', typeof data);
        throw new Error('Invalid response from server.');
    }
    return data;
}

export async function fetchFreeAlert(id: string): Promise<FreeAlertFeedItem> {
    const resp = await apiClient.get(`/free/alerts/${id}`);
    if (!resp.ok) throw new Error('Free alert not found');
    return await resp.json();
}

export async function fetchAnalysts(): Promise<AnalystProfile[]> {
    const resp = await apiClient.get('/analysts');
    return resp.ok ? await resp.json() : [];
}

export async function updateWatchlist(id: string, kw: string[]) {
    return await apiClient.post(`/analysts/${id}/watchlist`, { watchlist: kw });
}

export async function fetchProInsights(alertId?: string): Promise<ProInsights | null> {
    const path = alertId ? `/alerts/${alertId}/insights/pro` : '/analytics/insights/pro';
    const resp = await apiClient.get(path);
    return resp.ok ? await resp.json() : null;
}

export async function fetchExpertIntelligence(alertId?: string): Promise<ExpertIntelligence | null> {
    const path = alertId ? `/alerts/${alertId}/insights/expert` : '/analytics/insights/expert';
    const resp = await apiClient.get(path);
    return resp.ok ? await resp.json() : null;
}

export async function fetchCheckoutSession(tier: string, email?: string) {
    const resp = await apiClient.post('/payments/create-checkout', { tier, email });
    return await resp.json();
}

export async function cancelSubscription() {
    return await apiClient.post('/payments/cancel');
}

export async function submitFeedback(alertId: string, score: number) {
    return await apiClient.post(`/alerts/${alertId}/feedback`, { score });
}

export type BackboneDependency = {
    target: string;
    type: string;
    weight: number;
};

export type BackboneNode = {
    name: string;
    ticker?: string | null;
    sector: string;
    country: string;
    location: {
        lat: number;
        lng: number;
    };
    description: string;
    top_dependencies: BackboneDependency[];
};

export async function fetchBackbone(sector: string): Promise<BackboneNode[]> {
    const resp = await apiClient.get(`/backbone/${sector}`);

    if (!resp.ok) {
        throw new Error(`Failed to fetch backbone sector: ${sector}`);
    }

    return await resp.json();
}

export async function fetchProStructuralReports(): Promise<ProStructuralReportList> {
    const resp = await apiClient.get('/pro/reports');
    return resp.ok ? await resp.json() : [];
}

export async function fetchProStructuralReport(id: string): Promise<ProStructuralReportItem> {
    const resp = await apiClient.get(`/pro/reports/${id}`);
    if (!resp.ok) throw new Error("Pro report not found");
    return await resp.json();
}