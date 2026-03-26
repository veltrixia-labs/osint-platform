import './style.css'
import { DashboardState } from './modules/poll'
import { renderAlerts, renderHealth, renderSidebar, renderReportDetail } from './modules/render'
import { login, fetchMe, logout, fetchUsage, fetchReports, fetchReport } from './modules/api'
import type { UserMe, AnalystProfile, Report } from './modules/api'
import {
    renderTierBadge,
    renderGracePeriodBanner,
    renderSubscriptionTab,
} from './modules/subscription'
import {
    ACCESS_MAP,
    canAccessTopic,
    getTopicDef,
    normalizeReportType,
    REPORT_TYPE_LABELS,
    REPORT_TYPE_MIN_TIER,
} from './modules/topics'


const app = document.querySelector<HTMLDivElement>('#app')!

export async function renderLogin() {
    // Stop any active polling
    (window as any).stopPolling?.();
    
    app.className = 'login-page'
    app.innerHTML = `
    <div class="login-container">
        <div class="login-card">
            <h1>OSINT Intelligence</h1>
            <p>Enter your analyst credentials</p>
            <input type="text" id="chat-id" placeholder="Telegram Chat ID" required />
            <input type="password" id="password" placeholder="Password" required />
            <button id="login-btn">Login</button>
            <div id="login-error" style="color: #ff7b72; margin-top: 1rem; font-size: 0.9rem;"></div>
        </div>
    </div>
    `
    
    const btn = document.querySelector('#login-btn')!
    btn.addEventListener('click', async () => {
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



type TabId = 'feed' | 'plans' | 'reports'

async function initDashboard() {
    const urlParams = new URLSearchParams(window.location.search);
    const reportId = urlParams.get('report_id');
    
    let user: UserMe | null = await fetchMe();
    
    if (!user && !reportId) {
        renderLogin();
        return;
    }
    app.classList.remove('login-page');

    // Handle Payment Status Notifications
    const paymentStatus = urlParams.get('payment');
    const sessionId = urlParams.get('session_id');

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
          <span style="font-weight:700; color:var(--accent);">OSINT</span>
          <span style="opacity:0.5;">|</span>
          <span style="font-size:0.8rem; color:var(--text-secondary);">Analyst Platform</span>
        </div>
        <button class="hamburger" id="mobile-menu-btn">☰</button>
      </div>

      <div class="mobile-overlay" id="mobile-overlay"></div>

      <aside class="sidebar" id="sidebar">
        <div class="sidebar-header u-flex u-m-bottom-1">
          <div style="width:32px; height:32px; background:var(--accent); border-radius:8px; display:flex; align-items:center; justify-content:center; color:white; font-weight:bold;">O</div>
          <h2>OSINT Analytics</h2>
        </div>
        
        <nav class="u-m-top-1">
          <div class="sidebar-nav-link sidebar-nav-link--active" id="nav-feed">Intelligence Feed</div>
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
        <div class="main-feed" id="alerts-container">
          <div class="u-p-2 u-text-center">Initializing intelligence feed...</div>
        </div>
      </main>
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

    const handleTabSwitch = (tab: TabId) => {
        currentTab = tab;
        updateNavUI(tab);
        if (tab === 'feed') renderIntelligenceFeed();
        else if (tab === 'plans') renderPlans();
        else if (tab === 'reports') renderReports();
    };

    document.querySelector('#nav-feed')?.addEventListener('click', () => handleTabSwitch('feed'));
    document.querySelector('#nav-plans')?.addEventListener('click', () => handleTabSwitch('plans'));
    document.querySelector('#nav-reports')?.addEventListener('click', () => handleTabSwitch('reports'));

    window.addEventListener('view-report', (e: any) => {
        // Track the tab we're leaving
        const originTab = currentTab;
        renderSingleReport(e.detail.reportId, originTab);
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
            if (!feedContainer) return;

            // Only rebuild static structure on first render (avoid wiping active overlay)
            if (!feedContainer.querySelector('#topic-tabs-container')) {
                feedContainer.innerHTML = `
                    <div id="topic-tabs-container"></div>
                    <h3 class="u-m-top-1" style="margin-bottom: 1.5rem; color: #c9d1d9; border-bottom: 2px solid #30363d; padding-bottom: 0.5rem;">Live Alert Stream</h3>
                    <div id="feed-alerts-inner"><div class="u-p-2 u-text-center">Fetching Intelligence Feed...</div></div>
                `;
            }

            const healthDiv = document.querySelector<HTMLElement>('#health-container');
            if (data.health && healthDiv) renderHealth(data.health, healthDiv);

            const tabsContainer = document.querySelector<HTMLElement>('#topic-tabs-container');
            if (tabsContainer) renderTopicTabs(tabsContainer, state);

            const feedInner = document.querySelector<HTMLElement>('#feed-alerts-inner');
            // Only update alert list if no locked overlay is showing
            if (feedInner && !feedInner.querySelector('.locked-topic-view')) {
                renderAlerts(data.alerts || [], feedInner);
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
                    return `<button
                        class="topic-tab ${isActive ? 'topic-tab--active' : ''} ${!accessible ? 'topic-tab--locked' : ''}"
                        data-key="${topic.key}"
                        data-accessible="${accessible}"
                        style="--topic-color: ${topic.color}"
                        title="${accessible ? topic.label : topic.label + ' — Requires Pro'}"
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
                } else {
                    renderLockedTopicOverlay(key);
                }
            });
        });
    };

    const renderLockedTopicOverlay = (key: string) => {
        const topic = ACCESS_MAP.find(t => t.key === key)!;
        const minTierDisplay = topic.minTier.charAt(0).toUpperCase() + topic.minTier.slice(1);
        const feedInner = document.querySelector<HTMLElement>('#feed-alerts-inner');
        if (!feedInner) return;
        feedInner.innerHTML = `
            <div class="locked-topic-view">
                <div class="locked-topic-skeletons">
                    <div class="skeleton-card"></div>
                    <div class="skeleton-card"></div>
                    <div class="skeleton-card"></div>
                </div>
                <div class="locked-topic-overlay">
                    <div class="locked-topic-inner">
                        <div class="locked-topic-icon">${topic.icon}</div>
                        <h3 style="color: ${topic.color}">${topic.label}</h3>
                        <p>This intelligence domain requires a <strong>${minTierDisplay}</strong> subscription or higher.</p>
                        <button class="btn-primary locked-upgrade-btn" style="background: ${topic.color}22; color: ${topic.color}; border: 1px solid ${topic.color}55;">
                            Upgrade to ${minTierDisplay} →
                        </button>
                    </div>
                </div>
            </div>
        `;
        feedInner.querySelector('.locked-upgrade-btn')?.addEventListener('click', () => {
            handleTabSwitch('plans');
        });
    }

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
                <div class="reports-grid u-m-top-1">
                    ${reports.map(r => {
                        const topicDef = getTopicDef(r.topic_code ?? null);
                        const rtNorm = normalizeReportType(r.report_type);
                        const rtLabel = REPORT_TYPE_LABELS[rtNorm] ?? rtNorm.toUpperCase();
                        const planReq = r.plan_required || REPORT_TYPE_MIN_TIER[rtNorm] || 'free';
                        const isPremium = planReq !== 'free';
                        return `
                        <div class="alert-card u-tier-3" style="cursor:pointer;" onclick="window.dispatchEvent(new CustomEvent('view-report', {detail:{reportId:'${r.id}'}}))">
                            <div class="u-flex-between">
                                <div class="u-flex" style="gap:0.5rem; flex-wrap:wrap;">
                                    <span class="severity-badge" style="background:${topicDef.color}22; color:${topicDef.color}; border:1px solid ${topicDef.color}55;">${topicDef.icon} ${topicDef.label}</span>
                                    <span class="severity-badge" style="background:var(--accent-soft); color:var(--accent); border:1px solid var(--border-active);">${rtLabel}</span>
                                    ${isPremium ? `<span class="severity-badge" style="background:rgba(210,153,34,0.1); color:#d29922; border:1px solid rgba(210,153,34,0.3);">${planReq.toUpperCase()}</span>` : ''}
                                </div>
                                <span style="font-size:var(--font-xs); color:#8b949e;">${new Date(r.created_at).toLocaleDateString()}</span>
                            </div>
                            <h3 style="margin-top:0.75rem;">${r.title}</h3>
                            <div class="u-flex-between u-m-top-1">
                                <span style="font-size:var(--font-xs); color:#8b949e;">${r.source_count || 0} sources · ${r.confidence_level || 'Medium'} confidence</span>
                                <button class="btn-fb active u-tier-1">Read Analysis</button>
                            </div>
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
        try {
            const report = await fetchReport(id);
            renderReportDetail(report, alertsContainer, () => handleTabSwitch(origin), (action) => {
                if (action === 'upgrade') handleTabSwitch('plans');
            });
        } catch (e) { alertsContainer.innerHTML = '<div class="u-p-2 u-text-center">Decryption failed.</div>'; }
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

initDashboard();
