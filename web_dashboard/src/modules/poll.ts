import { apiClient } from './api';
import type { Alert, HealthData, AnalystProfile } from './api';

export class DashboardState {
    alerts: Alert[];
    health: HealthData | null;
    analysts: AnalystProfile[];
    isPolling: boolean;
    isPaused: boolean;
    subscribers: ((state: DashboardState) => void)[];
    topic: string | null;
    lastStatus: number;
    error: string | null;
    userTier: string;

    constructor(tier: string = 'guest') {
        this.alerts = [];
        this.health = null;
        this.analysts = [];
        this.isPolling = false;
        this.isPaused = false;
        this.subscribers = [];
        this.topic = null;
        this.lastStatus = 200;
        this.error = null;
        this.userTier = tier;
    }

    subscribe(callback: (state: DashboardState) => void) {
        this.subscribers.push(callback);
    }

    notify() {
        this.subscribers.forEach(cb => cb(this));
    }

    setTopic(topic: string | null) {
        this.topic = topic;
        this.updateOnce();
    }

    async updateOnce() {
        if (!this.isPolling || this.isPaused) return;
        try {
            const params: any = { limit: 15 };
            if (this.topic) params.topic = this.topic;

            const query = new URLSearchParams(params).toString();
            
            // [v11.5] Guest Isolation: Skip protected endpoints for Guests
            const isGuest = this.userTier === 'guest';
            
            const promises: Promise<Response | null>[] = [
                apiClient.get(`/alerts?${query}`)
            ];

            if (!isGuest) {
                promises.push(apiClient.get(`/system/health`));
                promises.push(apiClient.get(`/analysts`));
            } else {
                promises.push(Promise.resolve(null));
                promises.push(Promise.resolve(null));
            }

            const [alertsResp, healthResp, analystsResp] = await Promise.all(promises);

            // status 0 = synthetic network error from fetchWithAuth (not thrown anymore)
            const alertStatus = alertsResp?.status ?? 0;
            this.lastStatus = alertStatus;

            if (alertStatus === 0 || (alertStatus >= 400 && alertStatus !== 429)) {
                this.error = alertStatus === 0 ? 'Connection lost' : `API Error: ${alertStatus}`;
                this.notify();
                return;
            }

            const [alertsRes, healthRes, analystsRes] = await Promise.all([
                alertsResp ? alertsResp.json() : Promise.resolve([]),
                healthResp && healthResp.ok ? healthResp.json() : Promise.resolve(null),
                analystsResp && analystsResp.ok ? analystsResp.json() : Promise.resolve([])
            ]);

            this.error = null;
            const alerts = Array.isArray(alertsRes) ? alertsRes : [];
            const analysts = Array.isArray(analystsRes) ? analystsRes : [];

            const unique = new Map();
            alerts.forEach((a: Alert) => {
                if (!unique.has(a.id)) unique.set(a.id, a);
            });
            this.alerts = Array.from(unique.values());
            this.health = healthRes && healthRes.status ? healthRes : null;
            this.analysts = analysts;
            this.notify();
        } catch (err: any) {
            // fetchWithAuth no longer throws - this is a fallback for unexpected errors only
            console.error("Unexpected polling error:", err);
            this.error = "Unexpected error";
            this.lastStatus = 0;
            this.notify();
        }
    }

    startPolling(interval = 5000) {
        if (this.isPolling) return;
        this.isPolling = true;
        this.isPaused = false;
        
        const poll = async () => {
            if (!this.isPolling) return;
            if (!this.isPaused) {
                await this.updateOnce();
            }
            setTimeout(poll, interval);
        };
        
        poll();
    }

    stopPolling() {
        this.isPolling = false;
    }

    pause() {
        this.isPaused = true;
    }

    resume() {
        if (!this.isPaused) return;
        this.isPaused = false;
        // Immediate refresh on tab focus
        if (this.isPolling) {
            this.updateOnce();
        }
    }
}
