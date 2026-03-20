const API_BASE = import.meta.env.VITE_API_BASE_URL || "https://osint-platform-xs7p.onrender.com/api";

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
    target_label: string;
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
export async function fetchCheckoutSession(tier: string): Promise<CheckoutResponse> {
    const resp = await fetchWithAuth(`${API_BASE}/payments/checkout-session?tier=${tier}`);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Failed to start checkout (HTTP ${resp.status})`);
    }
    return await resp.json();
}

/**
 * Placeholder for the cancel/manage subscription action.
 * In production this will call a Stripe portal-session endpoint.
 * Currently surfaces the Plans & Billing tab for user awareness.
 */
export async function cancelSubscription(): Promise<{ message: string }> {
    // When backend portal-session endpoint is ready, swap this for:
    // const resp = await fetchWithAuth(`${API_BASE}/payments/portal-session`, { method: 'POST' });
    // if (resp.ok) { window.location.href = (await resp.json()).url; return; }
    return { message: 'cancel_pending' };
}
