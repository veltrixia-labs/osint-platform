const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

let accessToken: string | null = localStorage.getItem('access_token');

/**
 * Global Logout Flag
 */
const getLoggingOut = () => sessionStorage.getItem("isLoggingOut") === "true";
const setLoggingOut = (val: boolean) => {
    if (val) sessionStorage.setItem("isLoggingOut", "true");
    else sessionStorage.removeItem("isLoggingOut");
};

/**
 * Notifies the UI about API connectivity and auth health.
 */
export type SyncStatus = 'stable' | 'retrying' | 'offline';

function dispatchSyncEvent(status: SyncStatus) {
    window.dispatchEvent(new CustomEvent('api-sync-status', { 
        detail: { status, timestamp: new Date() } 
    }));
}

/**
 * [v11.9] Production Diagnostics: Standardized API Client
 * Stripped of redundant patch logic to isolate the root cause of connectivity failures.
 */
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

export async function fetchMe(): Promise<any | null> {
    try {
        const resp = await apiClient.get('/auth/me', {}, true);
        if (!resp.ok) return null;
        return await resp.json();
    } catch { return null; }
}

export async function fetchAlerts(params: Record<string, string> = {}): Promise<any[]> {
    const query = new URLSearchParams(params).toString();
    const resp = await apiClient.get(`/alerts?${query}`);
    return resp.ok ? await resp.json() : [];
}

export async function fetchLiveAlerts(limit: number = 10): Promise<any[]> {
    const resp = await apiClient.get(`/alerts/live?limit=${limit}`);
    return resp.ok ? await resp.json() : [];
}
