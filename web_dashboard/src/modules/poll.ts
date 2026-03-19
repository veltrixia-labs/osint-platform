import { fetchAlerts, fetchHealth, fetchAnalysts } from './api';

export class DashboardState {
    alerts: any[];
    health: any;
    analysts: any[];
    isPolling: boolean;
    subscribers: ((state: DashboardState) => void)[];
    topic: string | null;

    constructor() {
        this.alerts = [];
        this.health = null;
        this.analysts = [];
        this.isPolling = false;
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
        try {
            const params: any = { limit: 15 };
            if (this.topic) params.topic = this.topic;

            const [alerts, health, analysts] = await Promise.all([
                fetchAlerts(params),
                fetchHealth(),
                fetchAnalysts()
            ]);
            this.alerts = alerts;
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
        
        const poll = async () => {
            if (!this.isPolling) return;
            await this.updateOnce();
            setTimeout(poll, interval);
        };
        
        poll();
    }

    stopPolling() {
        this.isPolling = false;
    }
}
