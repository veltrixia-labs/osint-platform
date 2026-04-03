const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

let accessToken: string | null = localStorage.getItem('access_token');

/**
 * Global Logout Flag
 * Uses sessionStorage to persist across reloads while logging out.
 */
const getLoggingOut = () => sessionStorage.getItem("isLoggingOut") === "true";
const setLoggingOut = (val: boolean) => {
    if (val) sessionStorage.setItem("isLoggingOut", "true");
    else sessionStorage.removeItem("isLoggingOut");
};

export interface AuthResponse {
    access_token: string;
    token_type: string;
}

export interface UserMe {
    id: string;
    chat_id: string;
    role: string;
    tier: string;
    expires_at: string | null;
}

export interface CheckoutResponse {
    url?: string;
    success?: boolean;
    plan?: string;
}

export interface StakeholderImpact {
    stakeholder_id: string;
    entity_name: string;
    impact_direction: string;
    impact_alpha: number;
    confidence: number;
    reasoning: string;
    location_lat?: number;
    location_lng?: number;
    is_locked?: boolean;
    topic?: string;
    cascading_impacts?: StakeholderImpact[];
}

export interface Alert {
    id: string;
    severity: string;
    triggered_at: string;
    intelligence_score: number;
    intensity: number;
    trigger_type: string;
    topic: string | null;
    target_label: string;
    domain_count: number;
    evidence_list?: {
        title: string;
        domain: string;
        url: string;
    }[];
    spike_delta: number;
    fidelity_score?: number;
    is_high_fidelity?: boolean;
    related_report_id?: string;
    metadata_json?: {
        spike_delta?: number;
        domain_count?: number;
        evidence_list?: any[];
        cascading_impacts?: StakeholderImpact[];
    };
    location_lat?: number;
    location_lng?: number;
    cascading_impacts?: StakeholderImpact[];
    delivery?: {
        analyst_id: string;
        relevance_score: number;
    };
}

export interface Report {
    id: string;
    report_type: string;
    topic_code: string;
    title: string;
    teaser_md: string;
    summary_bluf?: string; // Phase 19.5 canonical field
    content_markdown: string;
    content_preview?: string;
    intensity?: number;
    intensity_score?: number;
    is_premium: boolean;
    plan_required: string;
    source_count: number;
    confidence_level: string;
    created_at: string;
    location_lat?: number;
    location_lng?: number;
    locked?: boolean;
}

export interface AnalystProfile {
    id: string;
    telegram_chat_id: string;
    user_role: string;
    subscription_tier: string;
    watch_keywords: string[];
    watch_sectors: string[];
}

export interface TriggerStat {
    type: string;
    avg_feedback: number;
}

export interface HealthData {
    review_rate: number;
    suppression_ratio: number;
    top_performing_triggers: TriggerStat[];
}

export async function signup(telegram_chat_id: string, password: string): Promise<void> {
    const resp = await fetch(`${API_BASE}/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ telegram_chat_id, password })
    });
    
    if (resp.status === 400) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || "Username already taken");
    }
    if (!resp.ok) throw new Error("Registration failed");
}

export async function login(telegram_chat_id: string, password: string): Promise<AuthResponse> {
    const resp = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ telegram_chat_id, password })
    });
    
    if (resp.status === 401) throw new Error("Invalid credentials");
    
    const data: AuthResponse = await resp.json();
    accessToken = data.access_token;
    localStorage.setItem('access_token', accessToken);
    
    // Clear logout flag on successful login
    setLoggingOut(false);
    
    return data;
}

export async function logout() {
    // 1. Set global logout flag
    setLoggingOut(true);

    // 2. Stop any active polling in the window
    (window as any).stopPolling?.();

    // 3. Clear local tokens immediately (Before network call)
    accessToken = null;
    localStorage.removeItem('access_token');

    try {
        // 4. Call /auth/logout using RAW fetch (bypass fetchWithAuth noise)
        await fetch(`${API_BASE}/auth/logout`, { 
            method: 'POST',
            credentials: 'include'
        });
    } catch (e) {
        // Ignore failures during logout
    }

    // 5. Small delay for stability
    await new Promise(r => setTimeout(r, 100));

    // 6. Reload 
    window.location.reload();
}

/**
 * apiClient - Unified authenticated request wrapper
 */
export const apiClient = {
    async get(path: string, options: RequestInit = {}) {
        return fetchWithAuth(`${API_BASE}${path}`, { ...options, method: 'GET' });
    },
    async post(path: string, body?: any, options: RequestInit = {}) {
        return fetchWithAuth(`${API_BASE}${path}`, {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options.headers },
            body: body ? JSON.stringify(body) : undefined
        });
    }
};

async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
    // A. Early Exit if logging out
    if (getLoggingOut()) {
        return new Response(null, { status: 401 });
    }

    const headers = new Headers(options.headers || {});
    const currentToken = localStorage.getItem('access_token');
    
    if (currentToken) {
        headers.set('Authorization', `Bearer ${currentToken}`);
    }
    
    const authOptions: RequestInit = {
        ...options,
        headers,
        credentials: 'include'
    };

    let resp = await fetch(url, authOptions);

    // B. Refresh Logic (401 Handling)
    if (resp.status === 401 && !url.includes('/auth/refresh') && !url.includes('/auth/login')) {
        // If logging out, ignore any 401 errors
        if (getLoggingOut()) {
            return resp;
        }

        try {
            const refreshResp = await fetch(`${API_BASE}/auth/refresh`, {
                method: 'POST',
                credentials: 'include'
            });

            if (refreshResp.ok) {
                const data: AuthResponse = await refreshResp.json();
                accessToken = data.access_token;
                localStorage.setItem('access_token', accessToken!);
                
                // Retry original request
                headers.set('Authorization', `Bearer ${accessToken}`);
                resp = await fetch(url, { ...authOptions, headers });
            } else {
                // [v37] DEFINITIVE SESSION EXPIRY
                // If refresh fails, the session is truly dead. Notify UI and clear local tokens.
                if (!getLoggingOut()) {
                    accessToken = null;
                    localStorage.removeItem('access_token');
                    
                    // Dispatch global event for main.ts to handle redirect
                    window.dispatchEvent(new CustomEvent('session-expired'));
                }
                return resp;
            }
        } catch (err) {
            console.error("Auth refresh failed:", err);
            return resp;
        }
    }

    return resp;
}

export async function fetchAlerts(params: Record<string, string> = {}): Promise<Alert[]> {
    const query = new URLSearchParams(params).toString();
    const resp = await apiClient.get(`/alerts?${query}`);
    return await resp.json();
}

export async function fetchLiveAlerts(limit: number = 10): Promise<Alert[]> {
    const resp = await apiClient.get(`/alerts/live?limit=${limit}`);
    return await resp.json();
}

export async function submitFeedback(alertId: string, score: number) {
    const resp = await apiClient.post(`/alerts/${alertId}/feedback`, { score });
    return await resp.json();
}

export async function fetchAnalysts(): Promise<AnalystProfile[]> {
    const resp = await apiClient.get(`/analysts`);
    return await resp.json();
}

export async function updateWatchlist(analystId: string, watchlist: string[]): Promise<any> {
    const resp = await apiClient.post(`/analysts/${analystId}/watchlist`, watchlist);
    if (resp.status === 403) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || 'Plan limit reached');
    }
    return await resp.json();
}

export interface UsageResponse {
    tier: string;
    alerts: { used: number; limit: number };
    keywords: { used: number; limit: number };
    topics: { allowed: string[]; restricted: string[] };
    reports: { daily: boolean; monthly: boolean };
}

export async function fetchUsage(): Promise<UsageResponse> {
    const resp = await apiClient.get(`/system/usage`);
    return await resp.json();
}

export async function fetchHealth(): Promise<HealthData> {
    const resp = await apiClient.get(`/system/health`);
    return await resp.json();
}

export async function fetchMe(): Promise<UserMe | null> {
    try {
        const resp = await apiClient.get(`/auth/me`);
        if (!resp.ok) return null;
        return await resp.json();
    } catch {
        return null;
    }
}

/**
 * Fetches a Stripe checkout URL for the given tier and redirects the browser.
 * Falls back gracefully if the API is unreachable.
 */
export async function fetchCheckoutSession(tier: string, reportId?: string): Promise<CheckoutResponse> {
    const returnUrl = encodeURIComponent(window.location.origin);
    let path = `/payments/checkout-session?tier=${tier}&return_url=${returnUrl}`;
    if (reportId) path += `&report_id=${reportId}`;
    
    const resp = await apiClient.get(path);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Failed to start checkout (HTTP ${resp.status})`);
    }
    return await resp.json();
}

/**
 * Validates a Stripe session on the backend to trigger immediate fulfillment.
 */
export async function confirmCheckoutSession(sessionId: string): Promise<any> {
    const resp = await apiClient.post(`/payments/confirm-session`, { session_id: sessionId });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || 'Fulfillment failed');
    }
    return await resp.json();
}

/**
 * Creates a Stripe portal session for the user to manage their subscription.
 */
export async function cancelSubscription(): Promise<{ url: string }> {
    const resp = await apiClient.post(`/payments/portal-session`, {});
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to open management portal');
    }
    return await resp.json();
}


export async function fetchReports(limit: number = 10, topic?: string): Promise<Report[]> {
    let path = `/reports?limit=${limit}`;
    if (topic) path += `&topic=${topic}`;
    
    const resp = await apiClient.get(path);
    if (!resp.ok) throw new Error("Failed to fetch reports");
    return await resp.json();
}

export async function fetchReport(reportId: string): Promise<Report> {
    const resp = await apiClient.get(`/reports/${reportId}`);
    if (resp.status === 404) throw new Error("Report not found");
    if (!resp.ok) throw new Error(`Failed to fetch report (HTTP ${resp.status})`);
    
    const data = await resp.json();
    return data;
}

export async function fetchPublicReport(reportId: string): Promise<Report> {
    const resp = await fetch(`${API_BASE}/public/reports/${reportId}`);
    if (resp.status === 404) throw new Error("Report not found");
    if (!resp.ok) throw new Error(`Failed to fetch public report (HTTP ${resp.status})`);
    return await resp.json();
}

export async function logAnalyticsEvent(type: string, reportId?: string, metadata: any = {}): Promise<void> {
    try {
        const vid = localStorage.getItem('osint_visitor_id');
        const enrichedMetadata = {
            ...metadata,
            visitor_id: vid || 'unknown',
            url: window.location.href
        };

        await apiClient.post(`/analytics/event`, {
            event_type: type,
            report_id: reportId,
            metadata_json: enrichedMetadata
        });
    } catch (err) {
        console.warn('Analytics logging failed:', err);
    }
}
