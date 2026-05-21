/**
 * api.ts
 * OSINT Risk Intelligence API Client
 */

/** Default page size for Alert Stream list endpoints. */
export const ALERT_STREAM_DISPLAY_LIMIT = 30;

/** Default page size for Context Briefs list endpoints. */
export const CONTEXT_BRIEFS_DISPLAY_LIMIT = 40;

/** Dashboard hosts that serve static files only (API is on Render). */
const STATIC_DASHBOARD_HOSTS = new Set(['veltrixia.net', 'www.veltrixia.net']);
const DEFAULT_REMOTE_API_ORIGIN = 'https://osint-platform.onrender.com';

const FETCH_RETRY_ATTEMPTS = 3;
const FETCH_RETRY_BASE_MS = 400;

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Read `<meta name="veltrixia-api-base" content="https://…">` (origin only, no `/api`). */
function readMetaApiOrigin(): string | null {
    if (typeof document === 'undefined') return null;
    const content = document.querySelector('meta[name="veltrixia-api-base"]')?.getAttribute('content')?.trim();
    if (!content) return null;
    let origin = content.replace(/\/+$/, '');
    if (origin.toLowerCase().endsWith('/api')) {
        origin = origin.slice(0, -4);
    }
    return origin;
}

/** Normalize any origin or `/api` URL to exactly one `…/api` suffix. */
function normalizeApiBase(originOrBase: string): string {
    let raw = originOrBase.trim().replace(/\/+$/, '');
    if (!raw) return '/api';
    if (raw.toLowerCase().endsWith('/api')) {
        raw = raw.slice(0, -4);
    }
    if (!raw.startsWith('http')) {
        return `${raw}/api`;
    }
    return `${raw}/api`;
}

/**
 * Resolve API prefix for all dashboard fetches (single source of truth).
 * 1. `<meta name="veltrixia-api-base">` (production split: static site → Render API).
 * 2. `VITE_API_BASE_URL` at build time when set to an absolute URL.
 * 3. Known static dashboard hosts → DEFAULT_REMOTE_API_ORIGIN.
 * 4. Same-origin `/api` when API and UI share a host.
 * 5. `/api` on localhost (Vite proxy).
 */
function resolveApiBase(): string {
    if (typeof globalThis !== 'undefined' && 'location' in globalThis) {
        const loc = (globalThis as unknown as Window).location;
        const host = loc?.hostname ?? '';
        if (host === 'localhost' || host === '127.0.0.1') {
            return '/api';
        }
        if (STATIC_DASHBOARD_HOSTS.has(host)) {
            const port = loc.port ? `:${loc.port}` : '';
            return `${loc.protocol}//${host}${port}/api`;
        }
    }

    const fromMeta = readMetaApiOrigin();
    if (fromMeta) {
        return normalizeApiBase(fromMeta);
    }

    const fromEnv = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
    if (fromEnv) {
        return normalizeApiBase(fromEnv);
    }

    if (typeof globalThis !== 'undefined' && 'location' in globalThis) {
        const loc = (globalThis as unknown as Window).location;
        const host = loc?.hostname ?? '';
        if (host) {
            const port = loc.port ? `:${loc.port}` : '';
            return `${loc.protocol}//${host}${port}/api`;
        }
    }
    return '/api';
}

const API_PROBE_CACHE_KEY = 'veltrixia_resolved_api_base';

let cachedApiBase: string | null = null;
let apiBaseInitPromise: Promise<string> | null = null;

/** Origins to probe for a live `/api/status` (order matters). */
function getApiOriginCandidates(): string[] {
    const seen = new Set<string>();
    const add = (origin: string | null | undefined) => {
        if (!origin) return;
        const o = origin.replace(/\/+$/, '');
        if (o && !seen.has(o)) seen.add(o);
    };

    if (typeof globalThis !== 'undefined' && 'location' in globalThis) {
        const loc = (globalThis as unknown as Window).location;
        const host = loc?.hostname ?? '';
        if (host && host !== 'localhost' && host !== '127.0.0.1') {
            add(loc.origin);
        }
    }

    add(readMetaApiOrigin());

    const fromEnv = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
    if (fromEnv) {
        let raw = fromEnv;
        if (raw.toLowerCase().endsWith('/api')) raw = raw.slice(0, -4);
        add(raw);
    }

    add(DEFAULT_REMOTE_API_ORIGIN);
    return [...seen];
}

function statusProbeUrl(origin: string): string {
    return `${normalizeApiBase(origin)}/status`;
}

async function probeApiOrigin(origin: string): Promise<boolean> {
    const url = statusProbeUrl(origin);
    try {
        const resp = await fetch(url, {
            method: 'GET',
            mode: 'cors',
            credentials: 'omit',
            cache: 'no-store',
            headers: { Accept: 'application/json' },
        });
        if (!resp.ok) return false;
        const body = (await resp.json()) as { status?: string; message?: string };
        return body?.status === 'ok' || Boolean(body?.message?.toLowerCase().includes('running'));
    } catch {
        return false;
    }
}

/**
 * Probe candidate API hosts and cache the first healthy `/api/status`.
 * Call once before dashboard data loads (initDashboard).
 */
export async function initApiBase(): Promise<string> {
    if (apiBaseInitPromise) return apiBaseInitPromise;

    apiBaseInitPromise = (async () => {
        const cached = sessionStorage.getItem(API_PROBE_CACHE_KEY);
        if (cached) {
            cachedApiBase = cached;
            const origin = cached.replace(/\/api$/i, '');
            if (await probeApiOrigin(origin)) {
                console.log(`[API] Using cached base: ${cached}`);
                return cached;
            }
            sessionStorage.removeItem(API_PROBE_CACHE_KEY);
            cachedApiBase = null;
        }

        for (const origin of getApiOriginCandidates()) {
            if (await probeApiOrigin(origin)) {
                cachedApiBase = normalizeApiBase(origin);
                sessionStorage.setItem(API_PROBE_CACHE_KEY, cachedApiBase);
                console.log(`[API] Discovered live API base: ${cachedApiBase}`);
                return cachedApiBase;
            }
            console.warn(`[API] Probe failed for origin: ${origin}`);
        }

        cachedApiBase = resolveApiBase();
        console.error(
            `[API] No live API found. Probes failed for: ${getApiOriginCandidates().join(', ')}. ` +
                'Ensure the Render osint-platform service is running (uvicorn api.main:app).',
        );
        return cachedApiBase;
    })();

    return apiBaseInitPromise;
}

/** Exposed for startup logging / debugging (no secrets). */
export function getResolvedApiBase(): string {
    if (!cachedApiBase) {
        const cached = typeof sessionStorage !== 'undefined'
            ? sessionStorage.getItem(API_PROBE_CACHE_KEY)
            : null;
        cachedApiBase = cached || resolveApiBase();
    }
    return cachedApiBase;
}

export function isCrossOriginApiRequest(url: string): boolean {
    if (!url.startsWith('http') || typeof window === 'undefined') return false;
    try {
        return new URL(url).origin !== window.location.origin;
    } catch {
        return false;
    }
}

export async function isSyntheticNetworkResponse(resp: Response): Promise<boolean> {
    if (resp.status !== SYNTHETIC_NETWORK_STATUS) return false;
    try {
        const body = (await resp.clone().json()) as { synthetic?: boolean };
        return body?.synthetic === true;
    } catch {
        return resp.status === SYNTHETIC_NETWORK_STATUS;
    }
}

/**
 * Route paths are `/alerts`, `/free/alerts`, … (no `/api` prefix).
 * Base already ends with `/api` — strip duplicate `/api` to avoid `/api/api/...`.
 */
function normalizeApiPath(path: string): string {
    let p = (path || '').trim();
    if (!p.startsWith('/')) p = `/${p}`;
    if (p.startsWith('/api/')) return p.slice(4);
    if (p === '/api') return '/';
    return p;
}

/** Build absolute URL for an API path (`/alerts`, `/free/alerts`, …). */
export function buildApiUrl(path: string): string {
    const base = getResolvedApiBase().replace(/\/$/, '');
    return `${base}${normalizeApiPath(path)}`;
}

/** HTTP status safe for `new Response()` (200–599 only). */
export function safeHttpStatus(code: unknown, fallback = 503): number {
    const n = typeof code === 'number' ? code : Number(code);
    if (Number.isFinite(n) && n >= 200 && n < 600) return Math.trunc(n);
    return fallback;
}

/** Synthetic response when fetch fails after retries (must not use status 0). */
export const SYNTHETIC_NETWORK_STATUS = 503;

function createNetworkErrorResponse(): Response {
    return new Response(JSON.stringify({ error: 'network_error', synthetic: true }), {
        status: SYNTHETIC_NETWORK_STATUS,
        statusText: 'Network Unavailable',
        headers: { 'Content-Type': 'application/json' },
    });
}

// --- Types & Interfaces ---

export interface UserMe {
    id: string;
    email: string;
    chat_id: string | null;
    role: string;
    is_admin?: boolean;
    manual_tier?: string | null;
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
    time_pressure?: string;
    causal_logic?: string;
    action_priority?: string;
    strategic_context?: string;
    risk_summary?: Record<string, any>;
    sector_distribution?: Record<string, number>;
    top_entities?: { name: string; count: number; entity_comment?: string }[];
    momentum_alerts?: Alert[];
    early_warnings?: { id: string; title: string; severity: string; timestamp: string }[];
    coverage_domains?: number;
    active_domains?: number;
    focus_alert_id?: string | null;
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

function isRetryableStatus(status: number): boolean {
    return status === 429 || status >= 500;
}

function updateSyncStatusFromResponse(resp: Response, skipSyncEvent: boolean, attempt: number, maxAttempts: number): void {
    if (skipSyncEvent) return;
    if (resp.ok) {
        dispatchSyncEvent('stable');
        return;
    }
    if (resp.status === 429 || (resp.status >= 500 && attempt < maxAttempts - 1)) {
        dispatchSyncEvent('retrying');
        return;
    }
    if (resp.status >= 500) {
        dispatchSyncEvent(attempt >= maxAttempts - 1 ? 'offline' : 'retrying');
        return;
    }
    // 4xx (except terminal cases): stay stable so feed does not flash offline for auth/config
    dispatchSyncEvent('stable');
}

async function fetchWithAuth(
    url: string,
    options: RequestInit = {},
    skipSyncEvent = false,
    attempt = 0,
): Promise<Response> {
    if (getLoggingOut()) return new Response(null, { status: 401 });

    const headers = new Headers(options.headers || {});
    if (!headers.has('Accept')) headers.set('Accept', 'application/json');
    const token = localStorage.getItem('access_token');
    if (token) headers.set('Authorization', `Bearer ${token}`);

    const crossOrigin = isCrossOriginApiRequest(url);
    const fetchOptions: RequestInit = {
        ...options,
        headers,
        mode: 'cors',
        credentials: crossOrigin ? 'omit' : 'include',
        cache: options.cache ?? 'no-store',
    };

    try {
        const resp = await fetch(url, fetchOptions);
        if (isRetryableStatus(resp.status) && attempt < FETCH_RETRY_ATTEMPTS - 1) {
            if (!skipSyncEvent) dispatchSyncEvent('retrying');
            await sleep(FETCH_RETRY_BASE_MS * (attempt + 1));
            return fetchWithAuth(url, options, skipSyncEvent, attempt + 1);
        }
        updateSyncStatusFromResponse(resp, skipSyncEvent, attempt, FETCH_RETRY_ATTEMPTS);
        return resp;
    } catch (e) {
        console.error(`[API Connectivity Error] URL: ${url} (attempt ${attempt + 1})`, e);
        if (attempt < FETCH_RETRY_ATTEMPTS - 1) {
            if (!skipSyncEvent) dispatchSyncEvent('retrying');
            await sleep(FETCH_RETRY_BASE_MS * (attempt + 1));
            return fetchWithAuth(url, options, skipSyncEvent, attempt + 1);
        }
        if (!skipSyncEvent) dispatchSyncEvent('offline');
        return createNetworkErrorResponse();
    }
}

// --- API Client ---

export const apiClient = {
    async get(path: string, options: RequestInit = {}, skipSyncEvent = false) {
        const separator = path.includes('?') ? '&' : '?';
        const url = `${buildApiUrl(path)}${separator}_t=${Date.now()}`;
        return fetchWithAuth(url, { ...options, method: 'GET' }, skipSyncEvent);
    },
    async post(path: string, body?: any, options: RequestInit = {}, skipSyncEvent = false) {
        const url = buildApiUrl(path);
        return fetchWithAuth(url, {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options.headers },
            body: body ? JSON.stringify(body) : undefined
        }, skipSyncEvent);
    }
};

// --- Exported API Functions ---

export async function login(email: string, password: string): Promise<void> {
    const resp = await apiClient.post('/auth/login', {
        email: email.trim().toLowerCase(),
        password,
    });
    if (!resp.ok) {
        throw new Error('auth_failed');
    }
    const body = await resp.json();
    if (body.access_token) {
        localStorage.setItem('access_token', body.access_token);
    }
}

export async function signup(email: string, password: string): Promise<void> {
    const resp = await apiClient.post('/auth/signup', {
        email: email.trim().toLowerCase(),
        password,
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({})) as { detail?: string | { msg?: string }[] };
        const detail = err.detail;
        const message =
            typeof detail === 'string'
                ? detail
                : Array.isArray(detail) && detail[0]?.msg
                  ? String(detail[0].msg)
                  : 'signup_failed';
        throw new Error(message);
    }
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

/** Admin-only: set manual_tier override (null clears → Stripe/subscription applies). */
export async function toggleAdminTier(tier: string | null): Promise<{ ok: boolean; tier?: string }> {
    const resp = await apiClient.post('/admin/toggle-tier', { tier });
    if (!resp.ok) return { ok: false };
    const body = await resp.json();
    return { ok: true, tier: body.tier };
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
        if (await isSyntheticNetworkResponse(resp)) {
            throw new Error(
                `API host unreachable (${getResolvedApiBase()}). ` +
                    'The Render API service may be stopped (check osint-platform deploy / uvicorn).',
            );
        }
        throw new Error(
            resp.status === 429
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
    const path = alertId ? `/alerts/${alertId}/insights/pro` : '/insights/pro';
    const resp = await apiClient.get(path);
    return resp.ok ? await resp.json() : null;
}

export async function fetchExpertIntelligence(alertId?: string): Promise<ExpertIntelligence | null> {
    const path = alertId ? `/alerts/${alertId}/insights/expert` : '/insights/expert';
    const resp = await apiClient.get(path);
    return resp.ok ? await resp.json() : null;
}

export async function fetchCheckoutSession(
    tier: string,
    opts?: { email?: string; reportId?: string; billing?: 'monthly' | 'annual' },
) {
    const body: { tier: string; billing: string; email?: string } = {
        tier,
        billing: opts?.billing || 'monthly',
    };
    if (opts?.email) body.email = opts.email.trim().toLowerCase();
    const resp = await apiClient.post('/stripe/create-checkout', body);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({})) as { detail?: string };
        throw new Error(err.detail || 'Checkout failed');
    }
    return await resp.json() as { url?: string; session_id?: string };
}

export async function confirmCheckoutSession(sessionId: string) {
    const resp = await apiClient.post('/payments/confirm-session', { session_id: sessionId });
    if (!resp.ok) throw new Error('confirm_failed');
    return await resp.json();
}

export async function completeStripeSignup(sessionId: string, password: string) {
    const resp = await apiClient.post('/stripe/complete-signup', {
        session_id: sessionId,
        password,
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({})) as { detail?: string };
        throw new Error(err.detail || 'signup_failed');
    }
    const body = await resp.json() as {
        access_token?: string;
        email?: string;
        tier?: string;
    };
    if (body.access_token) {
        localStorage.setItem('access_token', body.access_token);
    }
    return body;
}

export async function cancelSubscription() {
    const resp = await apiClient.post('/payments/portal-session');
    if (!resp.ok) throw new Error('portal_failed');
    return await resp.json() as { url?: string };
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