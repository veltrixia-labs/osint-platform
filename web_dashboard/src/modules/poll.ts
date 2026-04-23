import { apiClient } from './api';

export interface Alert {
    id: string;
    target_label: string;
    topic: string;
    severity: string;
    triggered_at: string;
    fidelity_score: number;
    intensity: number;
    is_locked: boolean;
    description?: string;
    intensity_display?: string;
    country?: string;
}

export class DashboardState {
    alerts: Alert[] = [];
    health: any = null;
    analysts: any[] = [];
    isPolling = false;
    isPaused = false;
    error: string | null = null;
    lastStatus = 200;
    userTier: string = 'guest';

    private subscribers: ((state: DashboardState) => void)[] = [];

    subscribe(fn: (state: DashboardState) => void) {
        this.subscribers.push(fn);
        fn(this);
        return () => {
            this.subscribers = this.subscribers.filter(s => s !== fn);
        };
    }

    notify() {
        this.subscribers.forEach(s => s(this));
    }

    setTier(tier: string) {
        this.userTier = tier;
    }

    setTopic(topic: string | null) {
        // Topic switching handled via re-fetch in main.ts
    }

    async updateOnce(topic: string | null = null) {
        if (!this.isPolling || this.isPaused) return;

        try {
            const params: any = { limit: 15 };
            if (topic) params.topic = topic;
            const query = new URLSearchParams(params).toString();

            // Simple parallel fetch
            const [alertsResp, healthResp] = await Promise.all([
                apiClient.get(`/alerts?${query}`),
                this.userTier === 'guest' ? Promise.resolve(null) : apiClient.get('/system/health')
            ]);

            this.lastStatus = alertsResp.status;
            
            if (!alertsResp.ok && alertsResp.status !== 0) {
                this.error = `HTTP ${alertsResp.status}`;
            } else if (alertsResp.status === 0) {
                this.error = "Offline";
            } else {
                this.error = null;
                const data = await alertsResp.json();
                this.alerts = Array.isArray(data) ? data : [];
                this.health = (healthResp && healthResp.ok) ? await healthResp.json() : null;
            }

            this.notify();
        } catch (err) {
            console.error("Dashboard polling error:", err);
            this.error = "Sync Failure";
            this.notify();
        }
    }

    startPolling(interval = 10000) {
        if (this.isPolling) return;
        this.isPolling = true;
        
        const tick = async () => {
            if (!this.isPolling) return;
            await this.updateOnce();
            setTimeout(tick, interval);
        };
        tick();
    }

    stopPolling() {
        this.isPolling = false;
    }
}

export const dashboardState = new DashboardState();
