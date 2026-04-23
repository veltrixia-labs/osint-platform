import './style.css'
declare const __APP_BUILD_INFO__: string;
console.log(`[Antigravity] API Base URL configured: ${import.meta.env.VITE_API_BASE_URL || '/api'}`);
console.log(`[Antigravity] Mode: ${import.meta.env.MODE}`);
console.log(`[Antigravity] Build Version: v11.1.2-AURORA-SYNC`);
console.log(`[Antigravity] Deploy Signature: AURORA-SYNC-${Date.now()}`);
console.log(`[Antigravity] Build Timestamp: ${new Date().toLocaleString()}`);
import { DashboardState } from './modules/poll'
import { renderAlerts, renderReportDetail, renderLiveFeed, renderMap, renderNavigation, updateNavActiveState, renderProInsights as renderPro, renderExpertIntel as renderExpert } from './modules/render/index'
import { login, signup, fetchMe, logout, fetchReports, fetchReport } from './modules/api'
import type { UserMe } from './modules/api'
import {
    renderGracePeriodBanner,
    renderSubscriptionTab,
} from './modules/subscription'



const app = document.querySelector<HTMLDivElement>('#app')!

export async function renderLogin(message?: string, initialEmail?: string) {
    (window as any).stopPolling?.();
    app.className = 'login-page'
    app.innerHTML = `
    <div class="login-container">
        <div class="login-card">
            <h1>VELTRIXIA LABS</h1>
            <p>Enter your analyst credentials</p>
            ${message ? `<div id="login-message" style="color: #3fb950; margin-bottom: 1rem; font-size: 0.9rem;">${message}</div>` : ''}
            <input type="email" id="login-email" placeholder="Email Address" required value="${initialEmail || ''}" />
            <input type="password" id="password" placeholder="Password" required />
            <button id="login-btn">Login</button>
            <div id="login-error" style="color: #ff7b72; margin-top: 1rem; font-size: 0.9rem;"></div>
            <div style="margin-top: 1.5rem; font-size: 0.85rem; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 1rem;">
                <span style="opacity: 0.6;">New analyst?</span>
                <a href="#" id="go-signup" style="color: var(--accent); text-decoration: none; margin-left: 0.5rem; font-weight: 600;">Create Account</a>
            </div>
        </div>
    </div>
    `
    const loginBtn = document.querySelector('#login-btn')!
    const signupLink = document.querySelector('#go-signup')!
    signupLink.addEventListener('click', (e) => { e.preventDefault(); renderSignup(); });
    loginBtn.addEventListener('click', async () => {
        const email = (document.querySelector('#login-email') as HTMLInputElement).value
        const pwd = (document.querySelector('#password') as HTMLInputElement).value
        const errorDiv = document.querySelector('#login-error')!
        try { await login(email, pwd); initDashboard(); } catch (e) { errorDiv.textContent = "Authentication failed."; }
    })
}

export async function renderSignup() {
    app.className = 'login-page'
    app.innerHTML = `
    <div class="login-container">
        <div class="login-card">
            <h1>Create Account</h1>
            <input type="email" id="signup-email" placeholder="Email Address" required />
            <input type="text" id="signup-chat-id" placeholder="Telegram Chat ID (Optional)" />
            <input type="password" id="signup-password" placeholder="Create Password" required />
            <button id="signup-btn" class="u-tier-1">Sign Up</button>
            <div id="signup-error" style="color: #ff7b72; margin-top: 1rem; font-size: 0.9rem;"></div>
            <div style="margin-top: 1.5rem; font-size: 0.85rem; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 1rem;">
                <a href="#" id="go-login" style="color: var(--accent); text-decoration: none; font-weight: 600;">Back to Login</a>
            </div>
        </div>
    </div>
    `
    const signupBtn = document.querySelector('#signup-btn')!
    const loginLink = document.querySelector('#go-login')!
    loginLink.addEventListener('click', (e) => { e.preventDefault(); renderLogin(); });
    signupBtn.addEventListener('click', async () => {
        const email = (document.querySelector('#signup-email') as HTMLInputElement).value
        const chatId = (document.querySelector('#signup-chat-id') as HTMLInputElement).value
        const pwd = (document.querySelector('#signup-password') as HTMLInputElement).value
        try { await signup({ email, password: pwd, chat_id: chatId }); renderLogin("Account created!", email); } catch (e: any) { (document.querySelector('#signup-error') as HTMLElement).textContent = "Registration failed."; }
    })
}

type TabId = 'feed' | 'plans' | 'reports' | 'map' | 'legal' | 'pro-insights' | 'expert-intel'

async function initDashboard() {
    let user: UserMe | null = null;
    try { user = await fetchMe(); if (user && !user.email) { logout(); return; } } catch (e) {}
    
    if (!user) {
        user = { 
            id: 'guest', 
            email: 'Guest', 
            chat_id: 'Guest', 
            role: 'anonymous', 
            tier: 'guest', 
            expires_at: null,
            features: {
                pro_insights: false,
                expert_intelligence: false,
                team_admin: false,
                custom_topics: false,
                onboarding: false,
                support: false
            },
            limits: {
                impact_depth: 0,
                topics: [],
                reports: []
            }
        };
    }

    if (user) app.classList.remove('login-page');

    app.addEventListener('click', (e) => {
        const target = e.target as HTMLElement;
        if (target.id === 'sidebar-login-btn') { renderLogin(); }
        if (target.id === 'sidebar-logout-btn') { if (confirm("Sign out?")) logout(); }
    });

    let currentTab: TabId = 'feed';
    
    const renderBaseUI = () => {
      const graceBanner = user ? renderGracePeriodBanner(user) : '';
      app.innerHTML = `
      <div class="mobile-header">
        <div class="u-flex"><span style="font-weight:700; color:var(--accent);">VELTRIXIA</span></div>
        <button class="hamburger" id="mobile-menu-btn">☰</button>
      </div>
      <div class="mobile-overlay" id="mobile-overlay"></div>
      <div class="app-container">
        <aside class="sidebar" id="sidebar">
          <div class="sidebar-header u-flex"><h2>VELTRIXIA LABS</h2></div>
          <div id="sidebar-nav-container" style="display:flex; flex-direction:column; flex:1;"></div>
        </aside>
        <main class="main-content">
          ${graceBanner ? `<div id="grace-header">${graceBanner}</div>` : ''}
          <div class="header-row"><h1 id="main-title">Analyst Intelligence</h1></div>
          <div class="main-feed" id="alerts-container">
            <div id="pulse-bar" class="pulse-bar"></div>
            <div id="alerts-list"></div>
          </div>
          <div id="map-page-container" style="display:none;"></div>
        </main>
      </div>
      `;
      document.querySelector('#mobile-menu-btn')?.addEventListener('click', () => {
        document.querySelector('#sidebar')?.classList.toggle('active');
        document.querySelector('#mobile-overlay')?.classList.toggle('active');
      });
    };

    renderBaseUI();
    const alertsContainer = document.querySelector<HTMLElement>('#alerts-list')!
    const pulseBar = document.querySelector<HTMLElement>('#pulse-bar')!

    // [v42] Connectivity Sync Listener: Restores real-time HUD status updates
    window.addEventListener('api-sync-status' as any, (e: CustomEvent) => {
        const { status } = e.detail;
        const hud = document.getElementById('sync-hud');
        if (!hud) return;
        
        const dot = hud.querySelector('.sync-dot');
        const label = hud.querySelector('.sync-label');
        const time = hud.querySelector('.sync-time');
        
        if (dot) {
            // Remove all possible status classes
            dot.classList.remove('sync-dot--init', 'sync-dot--stable', 'sync-dot--retrying', 'sync-dot--offline');
            dot.classList.add(`sync-dot--${status}`);
        }
        if (label) {
            label.textContent = `SYNC: ${status.toUpperCase()}`;
        }
        if (time) {
            time.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        }
    });

    renderNavigation(user, document.querySelector('#sidebar-nav-container')!, (tabId) => handleTabSwitch(tabId as TabId));

    const handleTabSwitch = (tab: TabId, focusAlertId?: string, skipPushState = false) => {
        currentTab = tab;
        updateNavActiveState('sidebar-nav-container', tab);
        if (!skipPushState) {
            const newHash = `#${tab}${focusAlertId ? `?alert=${focusAlertId}` : ''}`;
            if (window.location.hash !== newHash) history.pushState({ tab, focusAlertId }, '', newHash);
        }

        const mainContent = document.querySelector<HTMLElement>('.main-content');
        const feedContainer = document.querySelector<HTMLElement>('#alerts-container');
        const mapContainer = document.querySelector<HTMLElement>('#map-page-container');

        if (mainContent) mainContent.style.opacity = '0';
        setTimeout(() => {
            const isFeedLike = ['feed', 'plans', 'reports', 'legal', 'pro-insights', 'expert-intel'].includes(tab);
            if (feedContainer) feedContainer.style.display = isFeedLike ? 'block' : 'none';
            if (mapContainer) mapContainer.style.display = (tab === 'map') ? 'block' : 'none';
            
            if (tab === 'feed') renderIntelligenceFeed();
            else if (tab === 'plans') renderSubscriptionTab(user!, alertsContainer, () => handleTabSwitch('plans'));
            else if (tab === 'reports') renderReports();
            else if (tab === 'map') renderMap(mapContainer!, user!.tier, focusAlertId);
            else if (tab === 'pro-insights') renderPro(alertsContainer, user!, () => handleTabSwitch('plans'));
            else if (tab === 'expert-intel') renderExpert(alertsContainer, user!, () => handleTabSwitch('plans'));
            
            if (mainContent) mainContent.style.opacity = '1';
        }, 50);
    };

    window.addEventListener('hashchange', () => {
        const hash = window.location.hash.slice(1);
        if (!hash) return;
        const [base, query] = hash.split('?');
        const params = new URLSearchParams(query || '');
        if (['feed', 'map', 'plans', 'reports', 'legal', 'pro-insights', 'expert-intel'].includes(base)) {
            handleTabSwitch(base as TabId, params.get('alert') || undefined, true);
        }
    });

    window.addEventListener('view-report', (e: any) => {
        renderSingleReport(e.detail.reportId, currentTab);
    });

    const renderIntelligenceFeed = async () => {
        const state = new DashboardState(user!.tier);
        state.subscribe((data) => {
            if (currentTab !== 'feed') return;
            
            // [v12.0] Feed Error Separation Logic
            if (data.error || data.lastStatus >= 400) {
                alertsContainer.innerHTML = `
                    <div class="u-p-2 u-text-center" style="border: 1px solid rgba(255,123,114,0.2); border-radius: 8px; background: rgba(255,123,114,0.05); margin-top: 2rem;">
                        <div style="font-size: 1.5rem; margin-bottom: 0.5rem;">⚠️</div>
                        <div style="color: #ff7b72; font-weight: 600;">${data.lastStatus === 401 ? 'Intelligence Access Restricted' : 'Strategic Pipeline Offline'}</div>
                        <div style="font-size: var(--font-xs); color: #8b949e; margin-top: 0.5rem;">
                            ${data.lastStatus === 401 ? 'Your current tier does not have clearance for this signal stream.' : 'The analysis engine is currently unreachable. Reconnecting...'}
                        </div>
                        ${data.lastStatus === 401 ? `<button class="btn-fb u-m-top-1" onclick="window.dispatchEvent(new CustomEvent('trigger-tab', {detail:{tab:'plans'}}))">Upgrade Clearance</button>` : ''}
                    </div>
                `;
                return;
            }

            if (data.alerts) {
                renderAlerts(data.alerts, alertsContainer, user!.tier);
                renderLiveFeed(data.alerts, pulseBar);
            }
        });
        (window as any).stopPolling = () => state.stopPolling();
        state.startPolling();
    };

    const renderReports = async () => {
        alertsContainer.innerHTML = '<div class="u-p-2 u-text-center" style="opacity:0.5;">Loading reports...</div>';
        try {
            const reports = await fetchReports();
            if (reports.length === 0) {
                alertsContainer.innerHTML = `
                    <div class="u-p-2 u-text-center" style="opacity:0.5; border: 1px dashed var(--border); border-radius: 8px; margin-top: 2rem;">
                        <div style="font-size: 1.5rem; margin-bottom: 0.5rem;">📑</div>
                        <div style="font-size: var(--font-m); font-weight: 500;">No intelligence reports published yet.</div>
                        <div style="font-size: var(--font-xs); margin-top: 0.25rem;">Reports are generated following significant strategic pivots.</div>
                    </div>
                `;
                return;
            }
            alertsContainer.innerHTML = `<div class="reports-list">${reports.map(r => `<div class="report-row" onclick="window.dispatchEvent(new CustomEvent('view-report', {detail:{reportId:'${r.id}'}}))">${r.title}</div>`).join('')}</div>`;
        } catch (err: any) {
             alertsContainer.innerHTML = `
                <div class="u-p-2 u-text-center" style="border: 1px solid rgba(255,123,114,0.2); border-radius: 8px; margin-top: 2rem;">
                    <div style="color: #ff7b72; font-weight: 600;">Intelligence Retrieval Failed</div>
                    <div style="font-size: var(--font-xs); color: #8b949e; margin-top: 0.5rem;">${err.message || 'Failed to sync with report repository.'}</div>
                </div>
            `;
        }
    };

    const renderSingleReport = async (id: string, origin: TabId = 'feed') => {
        const report = await fetchReport(id);
        renderReportDetail(report, user!.tier, alertsContainer, () => handleTabSwitch(origin));
    };

    // [v8.4] Strategic Tracking Integration (Revised for Silent Sync)
    window.addEventListener('map-track-alert' as any, (e: CustomEvent) => {
        const id = e.detail.id;
        const silent = e.detail.silent || false;
        if (silent) {
            const mapContainer = document.querySelector<HTMLElement>('#map-page-container');
            if (mapContainer && mapContainer.style.display !== 'none') {
                window.dispatchEvent(new CustomEvent('focus-map', { detail: { alertId: id } }));
            }
        } else {
            handleTabSwitch('map', id);
        }
    });

    window.addEventListener('trigger-tab' as any, (e: CustomEvent) => {
        if (e.detail.tab) handleTabSwitch(e.detail.tab);
    });
}

// Global Core
const startHeartbeat = () => {
    setInterval(async () => { try { await fetchMe(); } catch (e) {} }, 5 * 60 * 1000);
};

initDashboard().then(() => { startHeartbeat(); });

window.addEventListener('trigger-login', () => renderLogin());
