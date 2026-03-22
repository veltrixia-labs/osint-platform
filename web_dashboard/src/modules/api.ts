const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api";

let accessToken: string | null = localStorage.getItem('access_token');

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

export interface Alert {
    id: string;
    severity: string;
    triggered_at: string;
    intelligence_score: number;
    intensity: number;
    trigger_type: string;
    target_label: string;
    domain_count: number;
    evidence_list?: {
        title: string;
        domain: string;
        url: string;
    }[];
    spike_delta: number;
    related_report_id?: string;
    feedback_score?: number;
    delivery?: {
        analyst_id: string;
        relevance_score: number;
    };
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
    return data;
}

export async function logout() {
    try {
        await fetchWithAuth(`${API_BASE}/auth/logout`, { method: 'POST' });
    } catch (e) {
        console.warn("Logout request failed, clearing local state anyway.");
    }
    accessToken = null;
    localStorage.removeItem('access_token');
    window.location.reload();
}

async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
    const headers = new Headers(options.headers || {});
    if (accessToken) {
        headers.set('Authorization', `Bearer ${accessToken}`);
    }
    
    const authOptions: RequestInit = {
        ...options,
        headers,
        credentials: 'include'
    };

    let resp = await fetch(url, authOptions);

    // 401? Try Refresh
    if (resp.status === 401 && !url.includes('/auth/refresh')) {
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
            accessToken = null;
            localStorage.removeItem('access_token');
            throw new Error("Session expired");
        }
    }

    return resp;
}

export async function fetchAlerts(params: Record<string, string> = {}): Promise<Alert[]> {
    const query = new URLSearchParams(params).toString();
    const resp = await fetchWithAuth(`${API_BASE}/alerts?${query}`);
    return await resp.json();
}

export async function submitFeedback(alertId: string, score: number) {
    const resp = await fetchWithAuth(`${API_BASE}/alerts/${alertId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ score })
    });
    return await resp.json();
}

export async function fetchAnalysts(): Promise<AnalystProfile[]> {
    const resp = await fetchWithAuth(`${API_BASE}/analysts`);
    return await resp.json();
}

export async function updateWatchlist(analystId: string, watchlist: string[]): Promise<any> {
    const resp = await fetchWithAuth(`${API_BASE}/analysts/${analystId}/watchlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(watchlist)
    });
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
    const resp = await fetchWithAuth(`${API_BASE}/system/usage`);
    return await resp.json();
}

export async function fetchHealth(): Promise<HealthData> {
    const resp = await fetchWithAuth(`${API_BASE}/system/health`);
    return await resp.json();
}

export async function fetchMe(): Promise<UserMe | null> {
    try {
        const resp = await fetchWithAuth(`${API_BASE}/auth/me`);
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
    let url = `${API_BASE}/payments/checkout-session?tier=${tier}&return_url=${returnUrl}`;
    if (reportId) url += `&report_id=${reportId}`;
    
    const resp = await fetchWithAuth(url);
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
    const resp = await fetchWithAuth(`${API_BASE}/payments/confirm-session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId })
    });
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
    const resp = await fetchWithAuth(`${API_BASE}/payments/portal-session`, {
        method: 'POST'
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to open management portal');
    }
    return await resp.json();
}

export async function fetchReports(limit: number = 10, topic?: string): Promise<any[]> {
    let url = `${API_BASE}/reports?limit=${limit}`;
    if (topic) url += `&topic=${topic}`;
    const resp = await fetchWithAuth(url);
    if (!resp.ok) throw new Error(`Failed to fetch reports (HTTP ${resp.status})`);
    return await resp.json();
}

export async function fetchReport(reportId: string): Promise<any> {
    const resp = await fetchWithAuth(`${API_BASE}/reports/${reportId}`);
    if (resp.status === 404) throw new Error("Report not found");
    if (!resp.ok) throw new Error(`Failed to fetch report (HTTP ${resp.status})`);
    
    const data = await resp.json();
    // Return the full data (which may include 'locked: true')
    return data;
}

export async function fetchPublicReport(reportId: string): Promise<any> {
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

        await fetchWithAuth(`${API_BASE}/analytics/event`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                event_type: type,
                report_id: reportId,
                metadata_json: enrichedMetadata
            })
        });
    } catch (err) {
        console.warn('Analytics logging failed:', err);
    }
}
