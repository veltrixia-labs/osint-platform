import { apiClient, ALERT_STREAM_DISPLAY_LIMIT, SYNTHETIC_NETWORK_STATUS, type Alert } from './api';

export class DashboardState {
    alerts: Alert[] = [];
    health: any = null;
    analysts: any[] = [];
    isPolling = false;
    isPaused = false;
    error: string | null = null;
    lastStatus = 200;
    consecutiveFailures = 0;
    userTier: string = 'free';
    currentTopic: string | null = null;

    private static readonly OFFLINE_FAILURE_THRESHOLD = 3;

    private subscribers: ((state: DashboardState) => void)[] = [];

    constructor(tier: string = 'free') {
        this.userTier = tier;
    }

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
        this.currentTopic = topic;
        this.updateOnce();
    }

    async updateOnce() {
        if (!this.isPolling || this.isPaused) return;

        try {
            const params: any = { limit: ALERT_STREAM_DISPLAY_LIMIT };
            if (this.currentTopic) params.topic = this.currentTopic;
            const query = new URLSearchParams(params).toString();

            const [alertsResp, healthResp] = await Promise.all([
                apiClient.get(`/alerts?${query}`),
                this.userTier === 'free' ? Promise.resolve(null) : apiClient.get('/system/health')
            ]);

            if (alertsResp) {
                this.lastStatus = alertsResp.status;

                if (alertsResp.ok) {
                    this.consecutiveFailures = 0;
                    this.error = null;
                    const data = await alertsResp.json();
                    this.alerts = Array.isArray(data) ? data : [];
                    this.health = (healthResp && healthResp.ok) ? await healthResp.json() : null;
                } else if (alertsResp.status === 429) {
                    this.error = null;
                    this.consecutiveFailures = 0;
                } else if (alertsResp.status === 401 || alertsResp.status === 403) {
                    this.consecutiveFailures += 1;
                    this.error = `HTTP ${alertsResp.status}`;
                } else {
                    this.consecutiveFailures += 1;
                    const isNetworkSynthetic = alertsResp.status === SYNTHETIC_NETWORK_STATUS;
                    const terminal =
                        isNetworkSynthetic ||
                        this.consecutiveFailures >= DashboardState.OFFLINE_FAILURE_THRESHOLD;
                    this.error = terminal
                        ? isNetworkSynthetic
                            ? 'Offline'
                            : `HTTP ${alertsResp.status}`
                        : null;
                }
            }

            this.notify();
        } catch (err) {
            console.error("Dashboard polling error:", err);
            this.consecutiveFailures += 1;
            this.lastStatus = SYNTHETIC_NETWORK_STATUS;
            this.error =
                this.consecutiveFailures >= DashboardState.OFFLINE_FAILURE_THRESHOLD
                    ? 'Sync Failure'
                    : null;
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
