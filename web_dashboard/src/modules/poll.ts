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

    constructor() {
        this.alerts = [];
        this.health = null;
        this.analysts = [];
        this.isPolling = false;
        this.isPaused = false;
        this.subscribers = [];
        this.topic = null; // null means 'all' or default
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
            const [alertsResp, healthResp, analystsResp] = await Promise.all([
                apiClient.get(`/alerts?${query}`),
                apiClient.get(`/system/health`),
                apiClient.get(`/analysts`)
            ]);

            const [alerts, health, analysts] = await Promise.all([
                alertsResp.json(),
                healthResp.json(),
                analystsResp.json()
            ]);

            const unique = new Map();
            (alerts || []).forEach((a: Alert) => {
                if (!unique.has(a.id)) unique.set(a.id, a);
            });
            this.alerts = Array.from(unique.values());
            this.health = health;
            this.analysts = analysts;
            this.notify();
        } catch (err) {
            console.error("Polling failed:", err);
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
