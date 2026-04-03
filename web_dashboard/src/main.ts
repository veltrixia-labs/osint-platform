import './style.css'
declare const __APP_BUILD_INFO__: string;
console.log(`[Antigravity] API Base URL configured: ${import.meta.env.VITE_API_BASE_URL || '/api'}`);
console.log(`[Antigravity] Mode: ${import.meta.env.MODE}`);
console.log(`[Antigravity] Build Version: 4.3.1-STABLE-UI`);
console.log(`[Antigravity] Build Timestamp: ${new Date().toISOString()}`);
import { DashboardState } from './modules/poll'
import { renderAlerts, renderHealth, renderSidebar, renderReportDetail, renderLiveFeed, renderRiskProfile, renderMap } from './modules/render'
import { login, signup, fetchMe, logout, fetchUsage, fetchReports, fetchReport } from './modules/api'
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

export async function renderLogin(message?: string, initialChatId?: string) {
    // Stop any active polling
    (window as any).stopPolling?.();
    
    app.className = 'login-page'
    app.innerHTML = `
    <div class="login-container">
        <div class="login-card">
            <h1>VELTRIXIA LABS</h1>
            <p>Enter your analyst credentials</p>
            ${message ? `<div id="login-message" style="color: #3fb950; margin-bottom: 1rem; font-size: 0.9rem;">${message}</div>` : ''}
            <input type="text" id="chat-id" placeholder="Telegram Chat ID" required value="${initialChatId || ''}" />
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

    signupLink.addEventListener('click', (e) => {
        e.preventDefault();
        renderSignup();
    });

    loginBtn.addEventListener('click', async () => {
        const chatId = (document.querySelector('#chat-id') as HTMLInputElement).value
        const pwd = (document.querySelector('#password') as HTMLInputElement).value
        const errorDiv = document.querySelector('#login-error')!
        
        try {
            await login(chatId, pwd)
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
            <input type="text" id="signup-chat-id" placeholder="Choose a Chat ID" required />
            <input type="password" id="signup-password" placeholder="Create Password" required />
            <button id="signup-btn" class="u-tier-1">Sign Up</button>
            <div id="signup-error" style="color: #ff7b72; margin-top: 1rem; font-size: 0.9rem;"></div>
            <div style="margin-top: 1.5rem; font-size: 0.85rem; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 1rem;">
                <span style="opacity: 0.6;">Already have an account?</span>
                <a href="#" id="go-login" style="color: var(--accent); text-decoration: none; margin-left: 0.5rem; font-weight: 600;">Back to Login</a>
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
        const chatId = (document.querySelector('#signup-chat-id') as HTMLInputElement).value
        const pwd = (document.querySelector('#signup-password') as HTMLInputElement).value
        const errorDiv = document.querySelector('#signup-error')!
        
        if (!chatId || !pwd) {
            errorDiv.textContent = "Please fill in all fields."
            return;
        }

        try {
            signupBtn.textContent = 'Creating Account...';
            (signupBtn as HTMLButtonElement).disabled = true;
            
            await signup(chatId, pwd)
            renderLogin("Account created successfully! Please log in.", chatId);
        } catch (e: any) {
            errorDiv.textContent = e.message || "Registration failed. Try a different ID.";
            signupBtn.textContent = 'Sign Up';
            (signupBtn as HTMLButtonElement).disabled = false;
        }
    })
}



type TabId = 'feed' | 'plans' | 'reports' | 'map'

async function initDashboard() {
    const urlParams = new URLSearchParams(window.location.search);
    const reportId = urlParams.get('report_id');
    const paymentStatus = urlParams.get('payment');
    const sessionId = urlParams.get('session_id');

    let user: UserMe | null = null;
    try {
        user = await fetchMe();
    } catch (e) {
        // Silently suppress 401s for guest mode
        console.log("[Antigravity] Session check: Guest access initialized.");
    }
    
    // [v38] Full Open Access Implementation: Default to guest if no user found
    if (!user) {
        user = {
            id: 'guest',
            chat_id: 'Guest',
            role: 'anonymous',
            tier: 'free',
            expires_at: null
        };
    }

    if (user) app.classList.remove('login-page');

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

        <aside class="sidebar-right" id="sidebar-right">
            <div id="risk-profile-container">
                <h2 style="font-size:1.1rem; margin-bottom:1rem;">Risk Profile</h2>
                <div class="u-p-1 u-text-center" style="opacity:0.5; font-size:0.8rem;">Analyzing risk trends...</div>
            </div>
            <div id="quick-map-trigger" class="u-m-top-1" style="cursor:pointer;">
                <div class="premium-card u-p-1" style="border:1px solid var(--accent); background:rgba(0,168,255,0.05); cursor:pointer;">
                    <div style="font-size:0.8rem; font-weight:700; color:var(--accent); margin-bottom:0.5rem;">Global Risk Distribution</div>
                    <div id="map-mini-preview" style="height:80px; background:#0d1117; border-radius:4px; display:flex; align-items:center; justify-content:center; border:1px dashed rgba(255,255,255,0.1);">
                        <span style="font-size:0.65rem; opacity:0.5;">Launch Intelligence Map →</span>
                    </div>
                </div>
            </div>
            <div style="flex:1;"></div>
            <div class="sidebar-footer" style="border-top:1px solid var(--border); padding-top:1rem;">
                <div style="font-size:0.7rem; color:var(--text-secondary); opacity:0.6;">
                    System Status: <span style="color:#3fb950;">Stable</span><br>
                    Last Refined: ${new Date().toLocaleTimeString()}<br>
                    <span style="color:var(--accent); display:block; margin-top:0.3rem;">Build: ${typeof __APP_BUILD_INFO__ !== 'undefined' ? __APP_BUILD_INFO__ : 'Dev'}</span>
                </div>
            </div>
        </aside>
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

    const handleTabSwitch = (tab: TabId, focusAlertId?: string) => {
        currentTab = tab;
        updateNavUI(tab);
        console.log(`[Antigravity] Viewport State: ${tab}${focusAlertId ? ` | Focus: ${focusAlertId}` : ''}`);
        
        const mainContent = document.querySelector<HTMLElement>('.main-content');
        const feedContainer = document.querySelector<HTMLElement>('#alerts-container');
        const mapContainer = document.querySelector<HTMLElement>('#map-page-container');
        const liveFeed = document.querySelector<HTMLElement>('#live-feed-container');
        
        // Start fade-out
        if (mainContent) mainContent.style.opacity = '0';

        setTimeout(() => {
            // Strict Toggle
            if (feedContainer) feedContainer.style.display = (tab === 'feed' || tab === 'plans' || tab === 'reports') ? 'block' : 'none';
            if (mapContainer) mapContainer.style.display = (tab === 'map') ? 'block' : 'none';
            if (liveFeed) liveFeed.style.display = (tab === 'feed') ? 'block' : 'none';

            if (tab === 'feed') renderIntelligenceFeed();
            else if (tab === 'plans') renderPlans();
            else if (tab === 'reports') renderReports();
            else if (tab === 'map') renderMapPage(focusAlertId);

            // Fade-in
            if (mainContent) mainContent.style.opacity = '1';
        }, 50);
    };

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
        // Track the tab we're leaving
        const originTab = currentTab;
        
        // Ensure map and ticker are hidden
        const mapContainer = document.querySelector<HTMLElement>('#map-page-container');
        const liveFeed = document.querySelector<HTMLElement>('#live-feed-container');
        const feedContainer = document.querySelector<HTMLElement>('#alerts-container');
        if (mapContainer) mapContainer.style.display = 'none';
        if (liveFeed) liveFeed.style.display = 'none';
        if (feedContainer) feedContainer.style.display = 'block';

        renderSingleReport(e.detail.reportId, originTab);
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

            // Phase 2: Live Feed & Risk Profile
            const liveFeedContainer = document.querySelector<HTMLElement>('#live-feed-container');
            const liveFeedTicker = document.querySelector<HTMLElement>('#live-feed-ticker');
            const riskProfileContainer = document.querySelector<HTMLElement>('#risk-profile-container');

            if (liveFeedContainer) liveFeedContainer.style.display = 'block';
            if (liveFeedTicker && data.alerts) {
                // For Live Feed, we show 100% of global signals in a compact way
                renderLiveFeed(data.alerts, liveFeedTicker);
            }
            if (riskProfileContainer && data.health) {
                renderRiskProfile(data.health, riskProfileContainer);
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

            // Note: We always render the Detail but the detail module handles the paywall masking internally
            // if 'accessible' or report metadata indicates locking.
            renderReportDetail(report, user!.tier, alertsContainer, () => handleTabSwitch(origin), (action) => {
                if (action === 'upgrade') handleTabSwitch('plans');
            });
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

    if (reportId) renderSingleReport(reportId);
    else handleTabSwitch('feed');
    refreshWatchlist();
}

// [v37] Global Auth Watchdog
window.addEventListener('session-expired', () => {
    console.warn("[Antigravity] Session definitively expired. Redirecting to login...");
    renderLogin("Your session has expired for security. Please log in again.");
});

// [v37] Visibility Watchdog: Re-verify on tab focus
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        fetchMe().then(user => {
            if (!user && (app.className !== 'login-page')) {
                window.dispatchEvent(new CustomEvent('session-expired'));
            }
        });
    }
});

// [v37] Server Heartbeat: Keep Render awake & session alive
const startHeartbeat = () => {
    console.log("[Antigravity] Initializing Session Heartbeat (5m interval)");
    const hb = setInterval(async () => {
        try {
            await fetchMe();
            console.log("[Antigravity] Heartbeat Pulse: Session Active");
        } catch (e) {
            console.warn("[Antigravity] Heartbeat Fail-soft");
        }
    }, 5 * 60 * 1000); // 5 minutes
    
    (window as any).stopHeartbeat = () => clearInterval(hb);
};

initDashboard().then(() => {
    startHeartbeat();
});
