import './style.css'
declare const __APP_BUILD_INFO__: string;
console.log(`[Antigravity] API Base URL configured: ${import.meta.env.VITE_API_BASE_URL || '/api'}`);
console.log(`[Antigravity] Mode: ${import.meta.env.MODE}`);
console.log(`[Antigravity] Build Version: v11.0.0-LUMINA-SYNC`);
console.log(`[Antigravity] Build Timestamp: ${new Date().toLocaleString()}`);
import { DashboardState } from './modules/poll'
import { renderAlerts, renderHealth, renderSidebar, renderReportDetail, renderLiveFeed, renderMap, renderLegal } from './modules/render/index'
import { login, signup, fetchMe, logout, fetchUsage, fetchReports, fetchReport, apiClient } from './modules/api'
import type { UserMe, AnalystProfile, Report } from './modules/api'
import {
    renderTierBadge,
    renderGracePeriodBanner,
    renderSubscriptionTab,
} from './modules/subscription'
import {
    ACCESS_MAP,
    canAccessTopic,
    canAccessReport,
    getTopicDef,
    normalizeReportType,
    REPORT_TYPE_LABELS,
    REPORT_TYPE_MIN_TIER,
} from './modules/topics'


const app = document.querySelector<HTMLDivElement>('#app')!

export async function renderLogin(message?: string, initialEmail?: string) {
    // Stop any active polling
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
            <div style="margin-top: 1rem; font-size: 0.75rem; opacity: 0.4; text-align: center;">
                <a href="#legal" style="color: inherit; text-decoration: none; margin: 0 5px;">Disclosure</a> |
                <a href="#legal" style="color: inherit; text-decoration: none; margin: 0 5px;">Terms</a> |
                <a href="#legal" style="color: inherit; text-decoration: none; margin: 0 5px;">Privacy</a>
            </div>
        </div>
    </div>
    `
    
    const loginBtn = document.querySelector('#login-btn')!
    const signupLink = document.querySelector('#go-signup')!

    signupLink.addEventListener('click', (e) => {
        e.preventDefault();
        renderSignup();
    });

    loginBtn.addEventListener('click', async () => {
        const email = (document.querySelector('#login-email') as HTMLInputElement).value
        const pwd = (document.querySelector('#password') as HTMLInputElement).value
        const errorDiv = document.querySelector('#login-error')!
        
        try {
            await login(email, pwd)
            initDashboard()
        } catch (e) {
            errorDiv.textContent = "Authentication failed. Please check credentials."
        }
    })
}

export async function renderSignup() {
    app.className = 'login-page'
    app.innerHTML = `
    <div class="login-container">
        <div class="login-card">
            <h1>Create Account</h1>
            <p>Join the VELTRIXIA LABS network</p>
            <input type="email" id="signup-email" placeholder="Email Address" required />
            <input type="text" id="signup-chat-id" placeholder="Telegram Chat ID (Optional)" />
            <input type="password" id="signup-password" placeholder="Create Password" required />
            <button id="signup-btn" class="u-tier-1">Sign Up</button>
            <div id="signup-error" style="color: #ff7b72; margin-top: 1rem; font-size: 0.9rem;"></div>
            <div style="margin-top: 1.5rem; font-size: 0.85rem; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 1rem;">
                <span style="opacity: 0.6;">Already have an account?</span>
                <a href="#" id="go-login" style="color: var(--accent); text-decoration: none; margin-left: 0.5rem; font-weight: 600;">Back to Login</a>
            </div>
            <div style="margin-top: 1rem; font-size: 0.75rem; opacity: 0.4; text-align: center;">
                <a href="#legal" style="color: inherit; text-decoration: none; margin: 0 5px;">Disclosure</a> |
                <a href="#legal" style="color: inherit; text-decoration: none; margin: 0 5px;">Terms</a> |
                <a href="#legal" style="color: inherit; text-decoration: none; margin: 0 5px;">Privacy</a>
            </div>
        </div>
    </div>
    `
    
    const signupBtn = document.querySelector('#signup-btn')!
    const loginLink = document.querySelector('#go-login')!

    loginLink.addEventListener('click', (e) => {
        e.preventDefault();
        renderLogin();
    });

    signupBtn.addEventListener('click', async () => {
        const email = (document.querySelector('#signup-email') as HTMLInputElement).value
        const chatId = (document.querySelector('#signup-chat-id') as HTMLInputElement).value
        const pwd = (document.querySelector('#signup-password') as HTMLInputElement).value
        const errorDiv = document.querySelector('#signup-error')!
        
        if (!email || !pwd) {
            errorDiv.textContent = "Please fill in required fields."
            return;
        }

        try {
            signupBtn.textContent = 'Creating Account...';
            (signupBtn as HTMLButtonElement).disabled = true;
            
            await signup(email, pwd, chatId)
            renderLogin("Account created successfully! Please log in.", email);
        } catch (e: any) {
            errorDiv.textContent = e.message || "Registration failed. Try a different email.";
            signupBtn.textContent = 'Sign Up';
            (signupBtn as HTMLButtonElement).disabled = false;
        }
    })
}



type TabId = 'feed' | 'plans' | 'reports' | 'map' | 'legal'

async function initDashboard() {
    const urlParams = new URLSearchParams(window.location.search);
    const reportId = urlParams.get('report_id');
    const paymentStatus = urlParams.get('payment');
    const sessionId = urlParams.get('session_id');

    let user: UserMe | null = null;
    try {
        user = await fetchMe();
        
        // [v40] Session Integrity: Clear legacy chat_id sessions if email is missing
        if (user && !user.email) {
            console.warn("[Antigravity] Legacy session detected. Performing hard-reset.");
            logout();
            return;
        }
    } catch (e) {
        // Silently suppress 401s for guest mode
        console.log("[Antigravity] Session check: Guest access initialized.");
    }
    
    // [v38] Guest Mode Implementation: Define a clear 'guest' tier
    if (!user) {
        user = {
            id: 'guest',
            email: 'Guest',
            chat_id: 'Guest',
            role: 'anonymous',
            tier: 'guest',
            expires_at: null
        };
        
        // Security: If Guest tries to access restricted reports via hash, we ALLOW it
        // and let renderReportDetail handle the preview/paywall state.
        // This optimizes the Threads/SNS conversion funnel.
        const currentHash = window.location.hash;
        if (currentHash.startsWith('#report/')) {
            console.log("[Antigravity] Social Referral Landing: Initializing Guest Preview.");
        }
    }

    if (user) app.classList.remove('login-page');

    // [v40] Event Delegation for Sidebar Actions
    app.addEventListener('click', (e) => {
        const target = e.target as HTMLElement;
        
        // 1. Sidebar Login (Guest -> Login Page)
        if (target.id === 'sidebar-login-btn' || target.classList.contains('trigger-login-btn')) {
            e.preventDefault();
            renderLogin();
            return;
        }

        // 2. Sidebar Logout (Member -> Guest Mode)
        if (target.id === 'sidebar-logout-btn') {
            e.preventDefault();
            if (confirm("Sign out of analyst account?")) {
                logout();
            }
            return;
        }
    });

    if (paymentStatus === 'success' && sessionId && !user) {
        app.innerHTML = `
            <div style="padding: 4rem; text-align: center; max-width: 600px; margin: 0 auto;">
                <h2 style="color:#3fb950;">✨ Payment Received</h2>
                <p>Please log in to unlock your intelligence report.</p>
                <button class="btn-primary u-tier-1" id="relogin-btn" style="width: 100%;">Log In Now</button>
            </div>
        `;
        document.querySelector('#relogin-btn')?.addEventListener('click', () => renderLogin());
        return;
    }

    // Default Tab
    let currentTab: TabId = 'feed';
    
    const renderBaseUI = () => {
      const graceBanner = user ? renderGracePeriodBanner(user) : '';
      app.innerHTML = `
      <div class="mobile-header">
        <div class="u-flex">
          <span style="font-weight:700; color:var(--accent);">VELTRIXIA</span>
          <span style="opacity:0.5;">|</span>
          <span style="font-size:0.8rem; color:var(--text-secondary);">LABS</span>
        </div>
        <div class="dev-mode-badge" style="margin-left:auto; margin-right:1rem; position:static;">Dev Mode: Unlocked</div>
        <button class="hamburger" id="mobile-menu-btn">☰</button>
      </div>

      <div class="mobile-overlay" id="mobile-overlay"></div>

      <div class="app-container">
        <aside class="sidebar" id="sidebar">
          <div class="sidebar-header u-flex u-m-bottom-1">
            <div style="width:32px; height:32px; background:var(--accent); border-radius:8px; display:flex; align-items:center; justify-content:center; color:white; font-weight:bold;">V</div>
            <h2>VELTRIXIA LABS</h2>
          </div>
          
          <nav class="u-m-top-1">
            <div class="sidebar-nav-link sidebar-nav-link--active" id="nav-feed">Intelligence Feed</div>
            <div class="sidebar-nav-link" id="nav-map">Global Map</div>
            <div class="sidebar-nav-link" id="nav-reports">Expert Reports</div>
            <div class="sidebar-nav-link" id="nav-plans">Subscription Plans</div>
          </nav>

          <div id="sidebar-watchlist" class="u-m-top-1" style="flex:1; overflow-y:auto; overflow-x:hidden; margin-bottom:1rem;"></div>

          <div class="sidebar-footer u-m-top-1">
            <div id="sync-hud" style="font-size: 0.65rem; color: #8b949e; margin-bottom: 0.75rem; letter-spacing: 0.05rem; font-family: monospace;">● SYNC: INITIALIZING...</div>
            <div class="u-flex u-m-bottom-1">
              <div id="user-tier-badge"></div>
            </div>
            <button id="logout-btn" style="width:100%; padding:0.6rem; background:rgba(248,81,73,0.1); color:#f85149; border:1px solid rgba(248,81,73,0.2); border-radius:6px; cursor:pointer;">Logout</button>
          </div>
        </aside>

        <main class="main-content">
          ${graceBanner ? `<div id="grace-header">${graceBanner}</div>` : ''}
          <div class="header-row">
            <h1 id="main-title">Analyst Intelligence</h1>
            <div id="health-container"></div>
          </div>
          
          <div id="live-feed-container" class="live-feed-container" style="display:none;">
            <div class="live-feed-header">
                <div class="pulse-dot"></div>
                <span style="font-weight:700; letter-spacing:0.05em; font-size:0.9rem;">LIVE INTELLIGENCE FEED</span>
            </div>
            <div id="live-feed-ticker" class="live-feed-ticker">
                <div class="u-p-1 u-text-center" style="opacity:0.5;">Scanning global signals...</div>
            </div>
          </div>

          <div class="main-feed" id="alerts-container">
            <div class="u-p-2 u-text-center">Initializing intelligence feed...</div>
          </div>
          <div id="map-page-container" style="display:none;"></div>
        </main>
      </div>
      `;

      const hamburger = document.querySelector('#mobile-menu-btn');
      const sidebar = document.querySelector('#sidebar');
      const overlay = document.querySelector('#mobile-overlay');
      const toggleMenu = () => {
        sidebar?.classList.toggle('active');
        overlay?.classList.toggle('active');
        document.body.classList.toggle('no-scroll');
      };
      hamburger?.addEventListener('click', toggleMenu);
      overlay?.addEventListener('click', toggleMenu);
    };

    renderBaseUI();

    const alertsContainer = document.querySelector<HTMLElement>('#alerts-container')!
    const healthContainer = document.querySelector<HTMLElement>('#health-container')!
    const sidebarWatchlist = document.querySelector<HTMLElement>('#sidebar-watchlist')!
    const mainTitle = document.querySelector<HTMLElement>('#main-title')!
    const logoutBtn = document.querySelector<HTMLElement>('#logout-btn')!

    logoutBtn.addEventListener('click', () => {
        (window as any).stopPolling?.();
        logout();
        renderLogin();
    });

    const updateNavUI = (tab: TabId) => {
      document.querySelectorAll('.sidebar-nav-link').forEach(el => el.classList.remove('sidebar-nav-link--active'));
      document.querySelector(`#nav-${tab}`)?.classList.add('sidebar-nav-link--active');
      document.querySelector('#sidebar')?.classList.remove('active');
      document.querySelector('#mobile-overlay')?.classList.remove('active');
      document.body.classList.remove('no-scroll');
    };

    const handleTabSwitch = (tab: TabId, focusAlertId?: string, skipPushState = false) => {
        currentTab = tab;
        updateNavUI(tab);
        console.log(`[Antigravity] Viewport State: ${tab}${focusAlertId ? ` | Focus: ${focusAlertId}` : ''}`);
        
        // Sync URL Hash (Phase 4)
        if (!skipPushState) {
            const newHash = `#${tab}${focusAlertId ? `?alert=${focusAlertId}` : ''}`;
            if (window.location.hash !== newHash) {
                history.pushState({ tab, focusAlertId }, '', newHash);
            }
        }

        const mainContent = document.querySelector<HTMLElement>('.main-content');
        const feedContainer = document.querySelector<HTMLElement>('#alerts-container');
        const mapContainer = document.querySelector<HTMLElement>('#map-page-container');
        const liveFeed = document.querySelector<HTMLElement>('#live-feed-container');
        
        // Start fade-out
        if (mainContent) mainContent.style.opacity = '0';

        setTimeout(() => {
            // Strict Toggle
            if (feedContainer) feedContainer.style.display = (tab === 'feed' || tab === 'plans' || tab === 'reports' || tab === 'legal') ? 'block' : 'none';
            if (mapContainer) mapContainer.style.display = (tab === 'map') ? 'block' : 'none';
            if (liveFeed) liveFeed.style.display = (tab === 'feed') ? 'block' : 'none';

            if (tab === 'feed') renderIntelligenceFeed();
            else if (tab === 'plans') renderPlans();
            else if (tab === 'reports') renderReports();
            else if (tab === 'map') renderMapPage(focusAlertId);
            else if (tab === 'legal' && feedContainer) {
                mainTitle.textContent = 'Legal & Compliance';
                renderLegal(feedContainer);
            }

            // Fade-in
            if (mainContent) mainContent.style.opacity = '1';
        }, 50);
    };

    // [v38] Hash Router Watcher
    window.addEventListener('hashchange', () => {
        const hash = window.location.hash.slice(1);
        if (!hash) return;
        
        const [base, query] = hash.split('?');
        const params = new URLSearchParams(query || '');
        
        if (base === 'feed' || base === 'map' || base === 'plans' || base === 'reports' || base === 'legal') {
            if (currentTab !== base) {
                handleTabSwitch(base as TabId, params.get('alert') || undefined, true);
            }
        } else if (base.startsWith('report/')) {
            const reportId = base.split('/')[1];
            if (reportId) {
                window.dispatchEvent(new CustomEvent('view-report', { detail: { reportId, skipPushState: true } }));
            }
        }
    });

    // History API Listener
    window.addEventListener('popstate', (e) => {
        if (e.state && e.state.tab) {
            handleTabSwitch(e.state.tab, e.state.focusAlertId, true);
        }
    });

    document.querySelector('#nav-feed')?.addEventListener('click', () => handleTabSwitch('feed'));
    document.querySelector('#nav-map')?.addEventListener('click', () => handleTabSwitch('map'));
    document.querySelector('#nav-plans')?.addEventListener('click', () => handleTabSwitch('plans'));
    document.querySelector('#nav-reports')?.addEventListener('click', () => handleTabSwitch('reports'));
    document.querySelector('#quick-map-trigger')?.addEventListener('click', () => handleTabSwitch('map'));

    // New Event Listener: Switch to Map tab and focus on alert
    window.addEventListener('focus-map', (e: any) => {
        handleTabSwitch('map', e.detail.alertId);
    });

    window.addEventListener('view-report', (e: any) => {
        const reportId = e.detail.reportId;
        const skipPushState = e.detail.skipPushState;

        // Sync URL Hash
        if (!skipPushState) {
            history.pushState({ tab: 'reports', reportId }, '', `#report/${reportId}`);
        }

        // Track the tab we're leaving
        const originTab = currentTab;
        
        // Ensure map and ticker are hidden
        const mapContainer = document.querySelector<HTMLElement>('#map-page-container');
        const liveFeed = document.querySelector<HTMLElement>('#live-feed-container');
        const feedContainer = document.querySelector<HTMLElement>('#alerts-container');
        if (mapContainer) mapContainer.style.display = 'none';
        if (liveFeed) liveFeed.style.display = 'none';
        if (feedContainer) feedContainer.style.display = 'block';

        renderSingleReport(reportId, originTab);
    });

    window.addEventListener('show-locked-topic', (e: any) => {
        renderLockedTopicOverlay(e.detail.topicKey);
    });

    window.addEventListener('upsell-click', () => {
        // Create Upsell Modal for Expert Tier
        const modal = document.createElement('div');
        modal.className = 'upsell-modal';
        modal.innerHTML = `
            <div style="font-size: 2.5rem; margin-bottom: 1rem;">💎</div>
            <h2 style="color: #bc8cff; margin-bottom: 0.5rem;">Expert-Tier Intelligence</h2>
            <p style="color: #c9d1d9; line-height: 1.6; margin-bottom: 1.5rem;">
                You've discovered a <strong>Strategic Ghost Node</strong>. <br/>
                Expert analysts can see the full cascading impact chain, including hidden stakeholders and deep reasoning.
            </p>
            <div style="text-align: left; background: rgba(0,0,0,0.2); padding: 1rem; border-radius: 8px; margin-bottom: 1.5rem; font-size: 0.9rem;">
                <div style="color: #3fb950; margin-bottom: 0.5rem;">✓ Full Cascading Logic (No Limits)</div>
                <div style="color: #3fb950; margin-bottom: 0.5rem;">✓ Second-Order Risk Curves</div>
                <div style="color: #3fb950;">✓ Self-Learning Weight Audits</div>
            </div>
            <button class="upsell-btn" id="modal-upgrade-btn">Upgrade to Expert</button>
            <button style="background:transparent; border:none; color:var(--text-secondary); margin-top:1rem; cursor:pointer;" onclick="this.parentElement.remove()">Maybe Later</button>
        `;
        document.body.appendChild(modal);
        
        document.querySelector('#modal-upgrade-btn')?.addEventListener('click', () => {
            modal.remove();
            handleTabSwitch('plans');
        });
    });

    const renderIntelligenceFeed = async () => {
        if (!user) { renderLogin(); return; }
        (window as any).stopPolling?.();
        const alertsContainer = document.querySelector<HTMLElement>('#alerts-container');
        if (alertsContainer) alertsContainer.innerHTML = '<div class="u-p-2 u-text-center">Initializing dashboard...</div>';

        const proBadge = user.tier === 'pro' ? '<span class="tier-badge u-m-top-1" style="background:var(--accent-soft); border:1px solid var(--accent); color:var(--accent);">💎 PRO Active</span>' : '';
        mainTitle.innerHTML = `Dashboard ${proBadge}`;
        
        const state = new DashboardState();
        state.subscribe((data) => {
            if (currentTab !== 'feed') return;
            const feedContainer = document.querySelector<HTMLElement>('#alerts-container');
            const healthDiv = document.querySelector<HTMLElement>('#health-container');
            if (!feedContainer) return;

            // Only rebuild static structure on first render (avoid wiping active overlay)
            if (!feedContainer.querySelector('#topic-tabs-container')) {
                feedContainer.innerHTML = `
                    <div id="topic-tabs-container"></div>
                    <h3 class="u-m-top-1" style="margin-bottom: 1.5rem; color: #c9d1d9; border-bottom: 2px solid #30363d; padding-bottom: 0.5rem;">Live Alert Stream</h3>
                    <div id="feed-alerts-inner"><div class="u-p-2 u-text-center">Fetching Intelligence Feed...</div></div>
                `;
            }

            if (data.health && healthDiv) renderHealth(data.health, healthDiv);

            // Phase 2: Live Feed
            const liveFeedContainer = document.querySelector<HTMLElement>('#live-feed-container');
            const liveFeedTicker = document.querySelector<HTMLElement>('#live-feed-ticker');

            if (liveFeedContainer) liveFeedContainer.style.display = 'block';
            if (liveFeedTicker && data.alerts) {
                // For Live Feed, we show 100% of global signals in a compact way
                renderLiveFeed(data.alerts, liveFeedTicker);
            }

            const tabsContainer = document.querySelector<HTMLElement>('#topic-tabs-container');
            if (tabsContainer) renderTopicTabs(tabsContainer, state);

            const feedInner = document.querySelector<HTMLElement>('#feed-alerts-inner');
            // Only update alert list if no locked overlay is showing
            if (feedInner && !feedInner.querySelector('.locked-topic-view')) {
                renderAlerts(data.alerts || [], feedInner, user!.tier);
            }
        });
        
        (window as any).stopPolling = () => state.stopPolling();
        (window as any).pausePolling = () => state.pause();
        (window as any).resumePolling = () => state.resume();
        state.startPolling();
    };

    const renderTopicTabs = (container: HTMLElement, state: DashboardState) => {
        if (!container || !user) return;
        const currentKey = state.topic ?? 'global';

        container.innerHTML = `
            <div class="topic-tab-bar">
                ${ACCESS_MAP.map(topic => {
                    const accessible = canAccessTopic(user!.tier, topic);
                    const isActive = currentKey === topic.key;
                    const lockIcon = accessible ? '' : '<span class="topic-lock-icon">🔒</span>';
                    const minTierDisplay = topic.minTier === 'experts' ? 'Expert' : topic.minTier.charAt(0).toUpperCase() + topic.minTier.slice(1);
                    return `<button
                        class="topic-tab ${isActive ? 'topic-tab--active' : ''} ${!accessible ? 'topic-tab--locked' : ''}"
                        data-key="${topic.key}"
                        data-accessible="${accessible}"
                        style="--topic-color: ${topic.color}"
                        title="${accessible ? topic.label : 'Upgrade to ' + minTierDisplay + ' to access'}"
                    >${topic.icon} ${topic.label}${lockIcon}</button>`;
                }).join('')}
            </div>
        `;

        container.querySelectorAll('.topic-tab').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const target = e.currentTarget as HTMLButtonElement;
                const accessible = target.dataset.accessible === 'true';
                const key = target.dataset.key!;
                if (accessible) {
                    // null = global in API
                    const topicDef = ACCESS_MAP.find(t => t.key === key)!;
                    state.setTopic(topicDef.code);
                    
                    // Clear locked view if present to allow feed to re-render
                    const feedInner = document.querySelector<HTMLElement>('#feed-alerts-inner');
                    if (feedInner && feedInner.querySelector('.locked-topic-view')) {
                        feedInner.innerHTML = '<div class="u-p-2 u-text-center">Loading Intelligence Feed...</div>';
                    }
                } else {
                    renderLockedTopicOverlay(key);
                }
            });
        });
    };

    const renderLockedTopicOverlay = (key: string, targetContainer?: HTMLElement) => {
        const topic = ACCESS_MAP.find(t => t.key === key)!;
        const minTierDisplay = topic.minTier === 'experts' ? 'Expert' : topic.minTier.charAt(0).toUpperCase() + topic.minTier.slice(1);
        const container = targetContainer || document.querySelector<HTMLElement>('#feed-alerts-inner');
        if (!container) return;
        
        container.innerHTML = `
            <div class="locked-topic-view" style="${targetContainer ? 'min-height: 500px;' : ''}">
                <div class="locked-topic-skeletons">
                    <div class="skeleton-card"></div>
                    <div class="skeleton-card"></div>
                    <div class="skeleton-card"></div>
                </div>
                <div class="locked-topic-overlay">
                    <div class="locked-topic-inner" style="max-width: 600px; padding: 2.5rem;">
                        <div class="locked-topic-icon" style="font-size: 3rem; margin-bottom: 1rem;">${topic.icon}</div>
                        <h2 style="color: ${topic.color}; margin-bottom: 0.5rem; font-size: 1.8rem;">${topic.label}</h2>
                        <p style="font-size: 1.1rem; color: #c9d1d9; font-weight: 500; margin-bottom: 1.5rem;">
                            ${topic.valueProposition}
                        </p>
                        
                        <div class="tier-comparison-mini u-m-bottom-2" style="background: rgba(0,0,0,0.2); border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); overflow: hidden; width: 100%;">
                            <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 0.9rem;">
                                <thead style="background: rgba(255,255,255,0.03);">
                                    <tr>
                                        <th style="padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.1);">Feature</th>
                                        <th style="padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); text-align: center; opacity: 0.6;">Free</th>
                                        <th style="padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); text-align: center; color: #d29922;">Pro</th>
                                        <th style="padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); text-align: center; color: #bc8cff;">Expert</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr>
                                        <td style="padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.05);">Global Briefing</td>
                                        <td style="padding: 10px 12px; text-align: center; color: #3fb950;">✓</td>
                                        <td style="padding: 10px 12px; text-align: center; color: #3fb950;">✓</td>
                                        <td style="padding: 10px 12px; text-align: center; color: #3fb950;">✓</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.05);">Specialized (Energy/Market)</td>
                                        <td style="padding: 10px 12px; text-align: center; opacity: 0.3;">🔒</td>
                                        <td style="padding: 10px 12px; text-align: center; color: #3fb950;">✓</td>
                                        <td style="padding: 10px 12px; text-align: center; color: #3fb950;">✓</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 12px;">Expert Portfolio (AI/Defense)</td>
                                        <td style="padding: 10px 12px; text-align: center; opacity: 0.3;">🔒</td>
                                        <td style="padding: 10px 12px; text-align: center; opacity: 0.3;">🔒</td>
                                        <td style="padding: 10px 12px; text-align: center; color: #3fb950;">✓</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>

                        <p style="font-size: 0.95rem; color: #8b949e; margin-bottom: 2rem;">
                            Accessing this intelligence domain requires an <strong>${minTierDisplay}</strong> analyst subscription.
                        </p>
                        
                        <button class="btn-primary locked-upgrade-btn" style="background: ${topic.color}; color: #0d1117; border: none; padding: 14px 32px; font-weight: 700; font-size: 1.1rem; cursor: pointer; border-radius: 8px; box-shadow: 0 4px 12px ${topic.color}44;">
                            Unlock ${topic.label} Intelligence →
                        </button>
                    </div>
                </div>
            </div>
        `;
        container.querySelector('.locked-upgrade-btn')?.addEventListener('click', () => {
            handleTabSwitch('plans');
        });
    };

    const renderPlans = async () => {
        (window as any).stopPolling?.();
        mainTitle.textContent = 'Account & Subscription';
        healthContainer.innerHTML = '';
        if (user) renderSubscriptionTab(user, alertsContainer, () => handleTabSwitch('plans'));
    };

    const renderReports = async () => {
        (window as any).stopPolling?.();
        mainTitle.textContent = 'Expert Intelligence Reports';
        healthContainer.innerHTML = '';
        alertsContainer.innerHTML = '<div class="u-p-2 u-text-center">Loading intelligence catalog...</div>';
        try {
            const reports: Report[] = await fetchReports();
            if (!reports.length) {
                alertsContainer.innerHTML = '<div class="u-p-2 u-text-center">No reports available for your plan yet.</div>';
                return;
            }
            
            alertsContainer.innerHTML = `
                <div class="reports-list u-m-top-1">
                    ${reports.map(r => {
                        const topicDef = getTopicDef(r.topic_code ?? null);
                        const rtNorm = normalizeReportType(r.report_type);
                        const rtLabel = REPORT_TYPE_LABELS[rtNorm] ?? rtNorm.toUpperCase();
                        
                        const accessible = canAccessReport(user!.tier, r.report_type, r.topic_code ?? null);
                        const planReq = r.plan_required || REPORT_TYPE_MIN_TIER[rtNorm] || 'free';
                        
                        // Extract BLUF (Bottom Line Up Front) from API field or fall back safely
                        const bluf = (r.summary_bluf || r.teaser_md || "")
                            .substring(0, 120) + ( (r.summary_bluf || r.teaser_md || "").length > 120 ? '...' : '');

                        return `
                        <div class="report-row ${!accessible ? 'report-row--locked' : ''}" 
                             onclick="window.dispatchEvent(new CustomEvent('view-report', {detail:{reportId:'${r.id}'}}))">
                            <!-- Col 1: Metrics & Badges -->
                            <div class="report-col-meta">
                                <div class="topic-icon-ring" style="--color: ${topicDef.color}">${topicDef.icon}</div>
                                <div class="badge-stack">
                                    <span class="report-badge">${rtLabel}</span>
                                    <span class="report-date">${new Date(r.created_at).toLocaleDateString()}</span>
                                </div>
                            </div>
                            
                            <!-- Col 2: Title & BLUF -->
                            <div class="report-col-main">
                                <h3 class="report-title">${r.title.split(' | ')[0]}</h3>
                                <p class="report-bluf">${accessible ? bluf : 'Detailed strategic analysis is restricted to ' + planReq.toUpperCase() + ' tier.'}</p>
                            </div>
                            
                            <!-- Col 3: Actions & Score -->
                            <div class="report-col-action">
                                <div class="score-display">
                                    <span class="score-val">${r.confidence_level || 'Medium'}</span>
                                    <span class="score-label">Confidence</span>
                                </div>
                                <button class="btn-fb active">${accessible ? 'Read' : 'Unlock'}</button>
                            </div>
                            
                            ${!accessible ? `<div class="alert-lock-overlay">🔒 Upgrade to ${planReq.toUpperCase()}</div>` : ''}
                        </div>`;
                    }).join('')}
                </div>
            `;
        } catch (e) { alertsContainer.innerHTML = '<div class="u-p-2 u-text-center">Unable to load reports.</div>'; }
    };

    const renderSingleReport = async (id: string, origin: TabId = 'feed') => {
        (window as any).stopPolling?.();
        mainTitle.textContent = 'Situation Report';
        healthContainer.innerHTML = '';
        alertsContainer.innerHTML = '<div class="u-p-2 u-text-center">Loading Report...</div>';
        try {
            const report = await fetchReport(id);

            // [v50] Detail module handles paywall masking and auth-triggers internally.
            renderReportDetail(report, user!.tier, alertsContainer, () => handleTabSwitch(origin));
        } catch (e) { 
            console.error("Report load failed:", e);
            alertsContainer.innerHTML = '<div class="u-p-2 u-text-center">Decryption failed or unauthorized access.</div>'; 
        }
    };

    const renderMapPage = async (focusAlertId?: string) => {
        if (!user) { renderLogin(); return; }
        (window as any).stopPolling?.();
        mainTitle.textContent = 'Global Intelligence Map';
        healthContainer.innerHTML = '';
        
        const mapContainer = document.querySelector<HTMLElement>('#map-page-container')!;
        renderMap(mapContainer, user.tier, focusAlertId);
    };

    const refreshWatchlist = async () => {
        if (!user) return;
        const usage = await fetchUsage();
        (window as any).getCurrentUsage = () => usage;
        const analysts = [user as unknown as AnalystProfile];
        renderSidebar(analysts, sidebarWatchlist);
    };
    (window as any).refreshUsage = refreshWatchlist;

    if (user) {
        const badgeContainer = document.querySelector<HTMLElement>('#user-tier-badge')!;
        badgeContainer.innerHTML = renderTierBadge(user);
    }

    // Initial Route Handling (Phase 4)
    const initialHash = window.location.hash.slice(1);
    if (initialHash) {
        const [base, query] = initialHash.split('?');
        const params = new URLSearchParams(query || '');
        if (base === 'feed' || base === 'map' || base === 'plans' || base === 'reports') {
            handleTabSwitch(base as TabId, params.get('alert') || undefined, true);
        } else if (base.startsWith('report/')) {
            const rId = base.split('/')[1];
            window.dispatchEvent(new CustomEvent('view-report', { detail: { reportId: rId, skipPushState: true } }));
        } else {
            handleTabSwitch('feed', undefined, true);
        }
    } else if (reportId) {
        renderSingleReport(reportId);
    } else {
        handleTabSwitch('feed', undefined, true);
    }
    // [v42] Strategic Heartbeat & Sync Monitor
    const updateSyncHUD = (status: string, timestamp: Date) => {
        const hud = document.querySelector('#sync-hud');
        if (!hud) return;
        
        const timeStr = timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const colorMap: Record<string, string> = {
            'stable': '#3fb950',
            'retrying': '#d29922',
            'offline': '#f85149'
        };
        
        const color = colorMap[status] || '#8b949e';
        const label = status.toUpperCase();
        
        hud.innerHTML = `<span style="color: ${color}; margin-right: 4px;">●</span> SYNC: ${timeStr} (${label})`;
    };

    window.addEventListener('api-sync-status' as any, (e: CustomEvent) => {
        updateSyncHUD(e.detail.status, e.detail.timestamp);
    });

    // Start Silent Heartbeat (10 minutes)
    const startHeartbeat = () => {
        console.log("[Antigravity] Initializing background tactical synchronization...");
        setInterval(async () => {
            console.log("[Antigravity] Background Sync Triggered...");
            await fetchMe(); // Triggers silent refresh check in api.ts
        }, 10 * 60 * 1000);
    };
    startHeartbeat();

    // [v10.9] Tactical AI Upgrade Trigger (On-Demand Intelligence)
    window.addEventListener('map-upgrade-ai' as any, async (e: CustomEvent) => {
        const alertId = e.detail.alertId;
        console.log(`[Antigravity] Tactical Upgrade Initiated: Alert ${alertId}`);
        
        try {
            // 1. Trigger Status HUD Update (via event)
            window.dispatchEvent(new CustomEvent('map-status-update', { detail: { message: 'ENHANCING SIGNAL...' } }));
            
            // 2. Call Backend Analyze Endpoint

            const response = await apiClient.post(`/alerts/${alertId}/analyze`);

            
            const result = await response.json();
            
            // [Fix] Treat 'processing' as a normal state for asynchronous AI jobs
            if (result.status === 'success' || result.status === 'skipped' || result.status === 'processing') {
                console.log(`[Antigravity] AI Analysis state: ${result.status}. Delegating to map engine...`);
                // 3. Force Re-render of focused alert on map
                const msg = result.status === 'processing' ? 'AI REFINING...' : 'INTELLIGENCE SYNCED';
                window.dispatchEvent(new CustomEvent('map-status-update', { detail: { message: msg } }));
                
                // We re-trigger focus-map with the same ID to force a fresh fetch/render
                window.dispatchEvent(new CustomEvent('focus-map', { detail: { alertId } }));
            } else {
                window.dispatchEvent(new CustomEvent('map-status-update', { detail: { message: 'SYNC ERROR' } }));
            }
        } catch (err) {
            console.error("AI Upgrade failed:", err);
            window.dispatchEvent(new CustomEvent('map-status-update', { detail: { message: 'NETWORK TIMEOUT' } }));
        }
    });

    refreshWatchlist();

    // [v8.4] Strategic Tracking Integration
    window.addEventListener('map-track-alert' as any, (e: CustomEvent) => {
        console.log(`[Antigravity] Strategic Monitor Tracking: Alert ID ${e.detail.id}`);
        handleTabSwitch('map', e.detail.id);
    });

    // [v8.1] Tactical Map -> Report Integration
    window.addEventListener('map-view-report' as any, (e: CustomEvent) => {
        console.log(`[Antigravity] Map Navigation Triggered: Asset ID ${e.detail.id}`);
        renderSingleReport(e.detail.id, 'map');
    });
}

// [v37] Global Auth Watchdog - REDACTED REDIRECT for v42
window.addEventListener('session-expired', () => {
    console.warn("[Antigravity] Session expired (Silent). Background refresh failed or guest period ended.");
    // renderLogin("Your session has expired for security. Please log in again."); // Disabled to prevent page switches
});

// [v37] Visibility Watchdog: Stop polling/heartbeat when hidden, refresh on tab focus
document.addEventListener('visibilitychange', () => {
    const isVisible = document.visibilityState === 'visible';
    console.log(`[Antigravity] Visibility Change: ${document.visibilityState}`);
    
    if (isVisible) {
        (window as any).resumePolling?.();
        (window as any).resumeHeartbeat?.();
        
        fetchMe().then(user => {
            if (!user && (app.className !== 'login-page')) {
                window.dispatchEvent(new CustomEvent('session-expired'));
            }
        });
    } else {
        (window as any).pausePolling?.();
        (window as any).pauseHeartbeat?.();
    }
});

// [v37] Server Heartbeat: Keep Render awake & session alive
const startHeartbeat = () => {
    console.log("[Antigravity] Initializing Session Heartbeat (5m interval)");
    let isPaused = false;
    
    const hb = setInterval(async () => {
        if (isPaused) return;
        try {
            await fetchMe();
            console.log("[Antigravity] Heartbeat Pulse: Session Active");
        } catch (e) {
            console.warn("[Antigravity] Heartbeat Fail-soft");
        }
    }, 5 * 60 * 1000); // 5 minutes
    
    (window as any).stopHeartbeat = () => clearInterval(hb);
    (window as any).pauseHeartbeat = () => { isPaused = true; };
    (window as any).resumeHeartbeat = () => { isPaused = false; };
};

initDashboard().then(() => {
    startHeartbeat();
});
// [v50] Global Conversion Funnel Listeners
window.addEventListener('trigger-login', () => {
    // Navigate to login view
    renderLogin();
});

window.addEventListener('show-locked-topic', (e: any) => {
    const topicKey = e.detail?.topicKey;
    console.log(`[Antigravity] Locked Topic Intercept: ${topicKey}`);
    renderLogin(); // Fallback to login for now, can be sophisticated Plans page later
});
