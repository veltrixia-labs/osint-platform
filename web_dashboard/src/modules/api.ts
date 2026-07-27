/**
 * api.ts
 * OSINT Risk Intelligence API Client
 */

import { parseApiJson } from './text_encoding';

/** Payload safety ceiling for Alert Stream list endpoints — NOT the real limiter.
 *  The stream is now bounded by the backend rolling 1h window + 20% intensity
 *  floor; this cap only guards against an unexpectedly large payload. */
export const ALERT_STREAM_DISPLAY_LIMIT = 100;

/** Dashboard hosts that serve static files only (API is on Render). */
const STATIC_DASHBOARD_HOSTS = new Set(['veltrixia.net', 'www.veltrixia.net']);
const DEFAULT_REMOTE_API_ORIGIN = 'https://osint-platform-xs7p.onrender.com';

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
        if (loc?.origin) {
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
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000);
    try {
        const resp = await fetch(url, {
            method: 'GET',
            mode: 'cors',
            credentials: 'omit',
            cache: 'no-store',
            headers: { Accept: 'application/json' },
            signal: controller.signal,
        });
        clearTimeout(timeoutId);
        if (!resp.ok) return false;
        const body = (await resp.json()) as { status?: string; message?: string };
        return body?.status === 'ok' || Boolean(body?.message?.toLowerCase().includes('running'));
    } catch {
        clearTimeout(timeoutId);
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
        // ── DEV DIRECT PASSTHROUGH ───────────────────────────────────────────
        // Under `vite` dev (`npm run dev`), bypass ALL probe/cache magic and pin
        // the base straight at the local backend port — CORS already allows
        // localhost:5173 → :8000, so the alerts fetch fires cleanly with zero
        // ambient configuration. Any stale/mismatched cached base is purged first.
        // (A production `vite build` sets DEV=false and uses the probe path below.)
        if (
            import.meta.env.DEV
            && typeof window !== 'undefined'
            && ['localhost', '127.0.0.1'].includes(window.location.hostname)
        ) {
            try { sessionStorage.removeItem(API_PROBE_CACHE_KEY); } catch { /* noop */ }
            const devBase = `${window.location.protocol}//${window.location.hostname}:8000/api`;
            cachedApiBase = devBase;
            console.log(`[API] DEV direct passthrough base (forced): ${devBase}`);
            return devBase;
        }

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
 * Route paths are `/alerts`, `/reports`, … (no `/api` prefix).
 * Base already ends with `/api` — strip duplicate `/api` to avoid `/api/api/...`.
 */
function normalizeApiPath(path: string): string {
    let p = (path || '').trim();
    if (!p.startsWith('/')) p = `/${p}`;
    if (p.startsWith('/api/')) return p.slice(4);
    if (p === '/api') return '/';
    return p;
}

/** Build absolute URL for an API path (`/alerts`, `/reports`, …). */
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
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
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
    intensity_pct?: number | null;
    importance_score?: number | null;
    importance_rationale?: string | null;
    importance_scored_at?: string | null;
    importance_model?: string | null;
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
    /** Module A — Risk Contagion Lead-Lag Tracker */
    lead_lag_matrix?: {
        source: string;
        target: string;
        lag_hours: number;
        correlation: number;
    }[];
    /** Module C — Verified Source Evidence Stream */
    evidence_stream?: {
        alert_id: string;
        topic: string;
        source_name: string;
        title: string;
        confidence_score: number;
        url?: string | null;
        triggered_at?: string | null;
        evidence_list?: any[];
    }[];
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

/**
 * Mirror the LOCAL DEV TIER toggle to the backend via the `X-Dev-Tier` header so
 * data payloads match the toggled UI tier. Gated to MODE=development + localhost
 * (same condition main.ts uses to apply the dev override) and honored only in
 * non-prod by the API. Absent / FREE → no header (backend resolves real free/guest).
 */
function getDevTierHeader(): string | null {
    try {
        if (import.meta.env.MODE !== 'development' || typeof window === 'undefined') return null;
        const host = window.location.hostname;
        if (host !== 'localhost' && host !== '127.0.0.1') return null;
        const tier = (sessionStorage.getItem('vel_dev_tier_override') || '').trim().toLowerCase();
        return tier && tier !== 'free' ? tier : null;
    } catch {
        return null;
    }
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
    const devTier = getDevTierHeader();
    if (devTier) headers.set('X-Dev-Tier', devTier);

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

export type FetchMeResult =
    | { status: 'ok'; user: UserMe }
    | { status: 'unauthorized' }
    | { status: 'error' };

export async function fetchMeDetailed(): Promise<FetchMeResult> {
    try {
        const resp = await apiClient.get('/auth/me', {}, true);
        if (resp.ok) {
            return { status: 'ok', user: await resp.json() };
        }
        if (resp.status === 401 || resp.status === 403) {
            return { status: 'unauthorized' };
        }
        return { status: 'error' };
    } catch {
        return { status: 'error' };
    }
}

export async function fetchMe(_cache?: any): Promise<UserMe | null> {
    const result = await fetchMeDetailed();
    return result.status === 'ok' ? result.user : null;
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

/** One row of the per-domain comprehensive feed (GET /items). Raw, time-ordered,
 *  LLM-free — deliberately carries no importance/anomaly (that's the Alert Stream). */
export interface DomainItem {
    id: string;
    title: string | null;
    title_original: string | null;
    lang: string | null;
    source_name: string | null;
    source_url: string | null;
    published_at: string | null;
    created_at: string | null;
    reliability_weight: number | null;
    category: string | null;
}

/** Comprehensive per-domain item list (newest-first). `topic` is the long-code
 *  category (e.g. 'ai_semiconductor_intelligence'), exactly what the topic tab
 *  carries. Empty topic / failure -> []. */
export async function fetchItems(topic: string, limit = 100): Promise<DomainItem[]> {
    if (!topic) return [];
    const query = new URLSearchParams({ topic, limit: String(limit) }).toString();
    const resp = await apiClient.get(`/items?${query}`);
    return resp.ok ? await resp.json() : [];
}

export async function fetchAlert(id: string): Promise<Alert> {
    const resp = await apiClient.get(`/alerts/${id}`);
    if (!resp.ok) throw new Error("Alert not found");
    return await resp.json();
}

// ── Monthly Trend Flow ──────────────────────────────────────────────────────

export interface MonthlyTrendIndexItem {
    year: number;
    month: number;
    label: string;
    generated_at: string | null;
    alerts_total: number;
    alerts_spiked: number;
}

export interface MonthlyTrendNode {
    id: string;
    domain_id: string;
    site_key: string;
    name: string;
    lat: number;
    lon: number;
    impact_score: number;
    entropy_index: number;
    viscosity_coefficient: number;
    type: 'epicenter' | 'affected';
    event_count: number;
    source_alert_ids: string[];
}

export interface MonthlyTrendEdge {
    domain_id: string;
    source_id: string | null;
    target_id: string | null;
    source_lon: number;
    source_lat: number;
    target_lon: number;
    target_lat: number;
    intensity: number;
    edge_intensity: number;
    viscosity_coefficient: number;
    order_level: number;
    target_order: number;
    source_alert_ids: string[];
}

export interface MonthlyTrendSnapshot {
    period: { year: number; month: number; label: string; start: string; end: string };
    generated_at: string | null;
    schema_version: string;
    summary: Record<string, any>;
    nodes: MonthlyTrendNode[];
    edges: MonthlyTrendEdge[];
}

export async function fetchMonthlyTrendIndex(): Promise<MonthlyTrendIndexItem[]> {
    const resp = await apiClient.get('/monthly-trends');
    if (!resp.ok) throw new Error(`Could not load trend archive (HTTP ${resp.status}).`);
    const data = await parseApiJson<MonthlyTrendIndexItem[]>(resp);
    return Array.isArray(data) ? data : [];
}

/** Newest archived month, or null when none have been generated yet (404). */
export async function fetchLatestMonthlyTrend(): Promise<MonthlyTrendSnapshot | null> {
    const resp = await apiClient.get('/monthly-trends/latest');
    if (resp.status === 404) return null;
    if (!resp.ok) throw new Error(`Could not load latest trend (HTTP ${resp.status}).`);
    return await parseApiJson<MonthlyTrendSnapshot>(resp);
}

export async function fetchMonthlyTrend(year: number, month: number): Promise<MonthlyTrendSnapshot | null> {
    const resp = await apiClient.get(`/monthly-trends/${year}/${month}`);
    if (resp.status === 404) return null;
    if (!resp.ok) throw new Error(`Could not load ${year}-${month} trend (HTTP ${resp.status}).`);
    return await parseApiJson<MonthlyTrendSnapshot>(resp);
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
    const resp = await apiClient.get('/pro/reports', {
        cache: 'no-store',
        headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
    });
    return resp.ok ? await parseApiJson<ProStructuralReportList>(resp) : [];
}

export type FragilityHistoryPoint = {
    timestamp: string;
    entropy_index: number;
    viscosity_coefficient: number;
    label?: string;
    phase_transition_warning?: boolean;
};

export type FragilityHistory = {
    domain_id: string;
    days: number;
    series: FragilityHistoryPoint[];
};

export async function fetchFragilityHistory(domainId: string, days = 7): Promise<FragilityHistory | null> {
    try {
        const resp = await apiClient.get(
            `/pro/domains/${encodeURIComponent(domainId)}/fragility-history?days=${days}`,
            { cache: 'no-store' },
        );
        if (!resp.ok) return null;
        return await resp.json() as FragilityHistory;
    } catch {
        return null;
    }
}
export async function fetchProStructuralReport(id: string): Promise<ProStructuralReportItem> {
    const resp = await apiClient.get(`/pro/reports/${id}`, {
        cache: 'no-store',
        headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
    });
    if (!resp.ok) throw new Error("Pro report not found");
    return await parseApiJson<ProStructuralReportItem>(resp);
}

export type MacroTransmissionData = {
    source: string;
    target: string;
    // null when the metric was NOT measured (no macro / no alerts / insufficient overlap);
    // `status` says which. Never 0 in that case — 0 would read as a measured zero.
    lag_days: number | null;
    correlation: number | null;
    beta: number | null;
    series: Array<{
        date: string;
        macro_value: number;
        intensity: number;
    }>;
    /** Present when the metrics are absent: "no_macro_data" | "no_alerts" | "insufficient_overlap" (else "ok"/omitted). */
    status?: string;
    sample_size?: number;
    /** "daily" or "monthly" — engine-reported sampling resolution */
    resolution?: 'daily' | 'monthly';
    roc_window_days?: number;
    days_lookback?: number;
};

export type MacroTransmissionMacroOption = {
    id: string;
    label: string;
    name?: string;
    category?: string;
    frequency?: string;
    unit_label?: string;
    accent_color?: string;
    provider?: string;
};

export type MacroTransmissionTopicOption = {
    id: string;
    label: string;
    description?: string;
    accent_color?: string;
    glow_color?: string;
};

export type MacroTransmissionOptions = {
    macro_series: MacroTransmissionMacroOption[];
    target_topics: MacroTransmissionTopicOption[];
    defaults: { macro_ticker: string; target_topic: string };
};

/** Hardcoded fallback used when the /options endpoint is unreachable. */
const MACRO_OPTIONS_FALLBACK: MacroTransmissionOptions = {
    macro_series: [
        { id: 'DCOILWTICO', label: 'WTI Crude Oil (Spot)',     category: 'energy',           frequency: 'daily',   unit_label: 'USD / barrel',         accent_color: '#eab308', provider: 'FRED' },
        { id: 'DGS10',      label: 'US 10-Year Treasury Yield', category: 'monetary_policy', frequency: 'daily',   unit_label: '% (annualised)',       accent_color: '#58a6ff', provider: 'FRED' },
        { id: 'VIXCLS',     label: 'VIX (Volatility Index)',    category: 'volatility',      frequency: 'daily',   unit_label: 'Index (annualised %)', accent_color: '#f87171', provider: 'FRED' },
        { id: 'PCOPPUSDM',  label: 'Global Copper Price',       category: 'commodities',     frequency: 'monthly', unit_label: 'USD / metric ton',     accent_color: '#f97316', provider: 'FRED' },
        { id: 'DTWEXBGS',   label: 'Broad USD Index',           category: 'currency',        frequency: 'daily',   unit_label: 'Index (Jan-2006 = 100)', accent_color: '#22d3ee', provider: 'FRED' },
    ],
    target_topics: [
        { id: 'energy_resource_risk',          label: 'Energy & Resource Risk',     accent_color: '#eab308', glow_color: 'rgba(234,179,8,0.45)' },
        { id: 'global_market_intelligence',    label: 'Global Market Intelligence', accent_color: '#58a6ff', glow_color: 'rgba(88,166,255,0.45)' },
        { id: 'ai_semiconductor_intelligence', label: 'AI & Semiconductor',         accent_color: '#bc8cff', glow_color: 'rgba(188,140,255,0.45)' },
        { id: 'supply_chain_intelligence',     label: 'Supply Chain Intelligence',  accent_color: '#10b981', glow_color: 'rgba(16,185,129,0.45)' },
        { id: 'defense_technology',            label: 'Defense Technology',         accent_color: '#f87171', glow_color: 'rgba(248,113,113,0.40)' },
        { id: 'crypto_geopolitics',            label: 'Crypto Geopolitics',         accent_color: '#f59e0b', glow_color: 'rgba(245,158,11,0.45)' },
    ],
    defaults: { macro_ticker: 'DCOILWTICO', target_topic: 'supply_chain_intelligence' },
};

let macroOptionsCache: MacroTransmissionOptions | null = null;

/**
 * Fetch the Dynamic Macro Selector option catalog from the API.
 * Cached for the lifetime of the session. Falls back to a hardcoded list when
 * the endpoint is unreachable so the selector UI is never empty.
 */
export async function fetchMacroTransmissionOptions(): Promise<MacroTransmissionOptions> {
    if (macroOptionsCache) return macroOptionsCache;
    try {
        const resp = await apiClient.get('/insights/macro-transmission/options');
        if (resp.ok) {
            const data = (await resp.json()) as MacroTransmissionOptions;
            if (data?.macro_series?.length && data?.target_topics?.length) {
                macroOptionsCache = data;
                return data;
            }
        }
    } catch (e) {
        console.warn('[Macro Selector] /options endpoint unreachable, using fallback', e);
    }
    macroOptionsCache = MACRO_OPTIONS_FALLBACK;
    return MACRO_OPTIONS_FALLBACK;
}

export type MacroRegime = {
    regime: string;
    label: string;
    emoji: string;
    accent_color: string;
    glow_color: string;
    rationale: string;
    components: {
        rates_roc_pct: number | null;
        oil_roc_pct: number | null;
        vix_roc_pct: number | null;
        series_ids: { rates: string; oil: string; vix: string };
        trigger_thresholds_pct: { rates: number; oil: number; vix: number };
    };
    observation_window_days: number;
    generated_at: string;
};

export async function fetchMacroRegime(): Promise<MacroRegime | null> {
    try {
        const resp = await apiClient.get('/insights/macro-regime');
        return resp.ok ? ((await resp.json()) as MacroRegime) : null;
    } catch (e) {
        console.warn('[Macro Regime] fetch failed', e);
        return null;
    }
}

// ── Market Entropy ───────────────────────────────────────────────────────
export type MarketEntropy = {
    entropy_normalised: number;
    topic_entropy_normalised: number;
    intensity_entropy_normalised: number;
    topic_entropy_nats: number;
    intensity_entropy_nats: number;
    n_alerts: number;
    topic_distribution: Record<string, number>;
    intensity_distribution: { low: number; medium: number; high: number };
    window_hours: number;
    breakout_threshold: number;
    breakout_warning: boolean;
    regime_label: string;
    regime_emoji: string;
    accent_color: string;
    glow_color: string;
    interpretation: string;
    generated_at: string;
};

export async function fetchMarketEntropy(): Promise<MarketEntropy | null> {
    try {
        const resp = await apiClient.get('/insights/market-entropy');
        return resp.ok ? ((await resp.json()) as MarketEntropy) : null;
    } catch (e) {
        console.warn('[Market Entropy] fetch failed', e);
        return null;
    }
}

// ── Choke-Point Flow ─────────────────────────────────────────────────────
export type ChokePointNode = {
    id: string;
    label: string;
    lat: number;
    lng: number;
    daily_volume_mbpd: number;
    primary_commodity?: string | null;
    description?: string | null;
    viscosity: number;
    peak_intensity: number;
    matched_alert_count: number;
    matched_alerts: Array<{
        alert_id: string;
        topic?: string | null;
        domain?: string | null;
        intensity: number;
        target_label?: string | null;
        triggered_at?: string | null;
    }>;
    restriction: number;
    restriction_label: string;
    downstream_sectors: string[];
};
export type ChokePointEdge = {
    from_node: string;
    from_label: string;
    sector: string;
    drag: number;
    explanation: string;
};
export type ChokePointFlow = {
    nodes: ChokePointNode[];
    edges: ChokePointEdge[];
    global_restriction: number;
    global_restriction_label: string;
    window_hours: number;
    baseline_viscosity: number;
    generated_at: string;
};

export async function fetchChokePointFlow(): Promise<ChokePointFlow | null> {
    try {
        const resp = await apiClient.get('/insights/choke-points');
        return resp.ok ? ((await resp.json()) as ChokePointFlow) : null;
    } catch (e) {
        console.warn('[Choke-Point Flow] fetch failed', e);
        return null;
    }
}

// ── Hidden Accumulation ──────────────────────────────────────────────────
export type COTOverlay = {
    market: string;
    latest_report_date: string | null;
    comm_net_position_latest: number;
    comm_net_position_prior: number;
    comm_net_delta_contracts: number;
    accumulation_direction: 'buying' | 'selling' | 'flat';
};
export type HiddenAccumulationFinding = {
    macro_ticker: string;
    topic: string;
    intensity_ratio: number;
    current_peak_intensity: number;
    baseline_peak_intensity: number;
    price_change_pct_24h: number;
    cot_overlay: COTOverlay | null;
    verdict: {
        label: string;
        emoji: string;
        accent_color: string;
        rationale: string;
    };
    window_start: string;
    window_end: string;
};
export type HiddenAccumulation = {
    findings: HiddenAccumulationFinding[];
    inspected_pairs: Array<{
        macro_ticker: string;
        topic: string;
        current_peak_intensity: number;
        baseline_peak_intensity: number;
        price_change_pct_24h: number | null;
    }>;
    cluster_window_hours: number;
    reignite_factor: number;
    min_baseline_intensity: number;
    generated_at: string;
};

export async function fetchHiddenAccumulation(): Promise<HiddenAccumulation | null> {
    try {
        const resp = await apiClient.get('/insights/hidden-accumulation');
        return resp.ok ? ((await resp.json()) as HiddenAccumulation) : null;
    } catch (e) {
        console.warn('[Hidden Accumulation] fetch failed', e);
        return null;
    }
}

// ── Sanctions Network ────────────────────────────────────────────────────
export type SanctionsNode = {
    id: string;
    name: string;
    country: string | null;
    sector: string | null;
    domain: string | null;
    ticker: string | null;
    sanctioned_status: boolean;
    sanction_program: string | null;
    pep_score: number | null;
    network_score: number;
    tier: 'primary' | 'direct_collateral' | 'indirect_collateral' | 'background';
    accent_color: string;
};
export type SanctionsEdge = {
    source_id: string;
    target_id: string;
    type: string | null;
    exposure_weight: number;
    beta_correlation: number;
};
export type SanctionsNetwork = {
    nodes: SanctionsNode[];
    edges: SanctionsEdge[];
    root_entity_id: string | null;
    stats: {
        primary_count: number;
        direct_collateral_count: number;
        indirect_collateral_count: number;
        total_nodes: number;
        total_edges: number;
        reason?: string;
    };
};

export async function fetchSanctionsNetwork(rootEntityId?: string, maxNodes = 60): Promise<SanctionsNetwork | null> {
    try {
        const qs = new URLSearchParams({ max_nodes: String(maxNodes) });
        if (rootEntityId) qs.set('root_entity_id', rootEntityId);
        const resp = await apiClient.get(`/insights/sanctions-network?${qs.toString()}`);
        return resp.ok ? ((await resp.json()) as SanctionsNetwork) : null;
    } catch (e) {
        console.warn('[Sanctions Network] fetch failed', e);
        return null;
    }
}

export type MacroMatrixCell = {
    macro_id: string;
    topic_id: string;
    correlation: number | null;
    lag_days: number | null;
    sample_size: number;
    status: string;
};

export type MacroMatrix = {
    macros: string[];
    topics: string[];
    cells: MacroMatrixCell[][];
    generated_at: string;
    lookback_days: number;
    roc_window_days: number;
};

export async function fetchMacroMatrix(): Promise<MacroMatrix | null> {
    try {
        const resp = await apiClient.get('/insights/macro-matrix');
        return resp.ok ? ((await resp.json()) as MacroMatrix) : null;
    } catch (e) {
        console.warn('[Macro Matrix] fetch failed', e);
        return null;
    }
}

export async function fetchMacroTransmission(
    macroTicker: string = 'DCOILWTICO',
    targetTopic: string = 'supply_chain_intelligence',
    includeInverse: boolean = false,
): Promise<MacroTransmissionData | null> {
    const params = new URLSearchParams({
        macro_ticker: macroTicker,
        // include the legacy `source` alias too so older API deployments
        // that haven't picked up the macro_ticker rename still work.
        source: macroTicker,
        target_topic: targetTopic,
        include_inverse: includeInverse ? 'true' : 'false',
    });
    const resp = await apiClient.get(`/insights/macro-transmission?${params.toString()}`);
    return resp.ok ? await resp.json() : null;
}

export type DrilldownData = {
    topic: string;
    top_entities: Array<{
        name: string;
        count: number;
        max_intensity: number;
        severity: string;
    }>;
    trigger_news: Array<{
        id: string;
        headline: string;
        display_title: string;
        intensity: number;
        severity: string;
        fidelity_score: number;
        timestamp: string | null;
        source: string;
        url: string | null;
        trigger_type: string;
        supporting_sources_count: number;
    }>;
    sector_stats: {
        total_alerts: number;
        avg_intensity: number;
        peak_intensity: number;
        window_hours: number;
    };
};

export async function fetchSectorDrilldown(topic: string): Promise<DrilldownData | null> {
    const params = new URLSearchParams({ topic });
    const resp = await apiClient.get(`/insights/pro/drilldown?${params.toString()}`);
    return resp.ok ? await resp.json() : null;
}