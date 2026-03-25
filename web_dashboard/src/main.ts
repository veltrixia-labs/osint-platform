import './style.css'
import { DashboardState } from './modules/poll'
import { renderAlerts, renderHealth, renderSidebar, renderReportDetail } from './modules/render'
import { login, fetchMe, logout, fetchUsage, fetchReport, logAnalyticsEvent } from './modules/api'
import type { UserMe, AnalystProfile } from './modules/api'
import {
    renderTierBadge,
    renderGracePeriodBanner,
    renderSubscriptionTab,
} from './modules/subscription'

const TOPICS = [
    { code: 'global', label: '🌍 Global Briefing', restricted: false },
    { code: 'market', label: '📈 Market Pulse', restricted: false },
    { code: 'community', label: '🤝 Network Activity', restricted: false },
    { code: 'energy_resource_risk', label: '⚡ Energy Risk', restricted: true },
    { code: 'global_market_intelligence', label: '💰 Financial Intel', restricted: true },
    { code: 'ai_semiconductor_intelligence', label: '🤖 AI/Semi Intel', restricted: true },
    { code: 'crypto_geopolitics', label: '₿ Crypto Risk', restricted: true },
    { code: 'defense_technology', label: '🛡️ Defense Tech', restricted: true },
    { code: 'supply_chain_intelligence', label: '📦 Supply Chain', restricted: true },
];

function getTopicLabel(code: string | null): string {
    if (!code) return '🌍 Global Briefing';
    const t = TOPICS.find(x => x.code === code);
    return t ? t.label : code.toUpperCase();
}

function getMarkdownPreview(md: string): string {
    if (!md) return "";
    const lines = md.split('\n').filter(l => l.trim().length > 0 && !l.startsWith('#'));
    return lines.slice(0, 2).join(' ') + (lines.length > 2 ? '...' : '');
}

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

function getVisitorId(): string {
    let vid = localStorage.getItem('osint_visitor_id');
    if (!vid) {
        vid = crypto.randomUUID();
        localStorage.setItem('osint_visitor_id', vid);
    }
    return vid || 'unknown';
}

function captureUtms(params: URLSearchParams) {
    return {
        utm_source: params.get('utm_source'),
        utm_medium: params.get('utm_medium'),
        utm_campaign: params.get('utm_campaign'),
        source: params.get('source'),
        visitor_id: getVisitorId()
    };
}

type TabId = 'feed' | 'plans' | 'reports'

async function initDashboard() {
    const urlParams = new URLSearchParams(window.location.search);
    const reportId = urlParams.get('report_id');
    
    let user = await fetchMe();
    
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

        <div id="sidebar-watchlist" class="u-m-top-1" style="flex:1; overflow-y:auto; margin-bottom:1rem;"></div>

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

    window.addEventListener('view-report', (e: any) => renderSingleReport(e.detail.reportId));

    const renderIntelligenceFeed = async () => {
        if (!user) { renderLogin(); return; }
        const proBadge = user.tier === 'pro' ? '<span class="tier-badge u-m-top-1" style="background:var(--accent-soft); border:1px solid var(--accent); color:var(--accent);">💎 PRO Active</span>' : '';
        mainTitle.innerHTML = `Dashboard ${proBadge}`;
        
        const state = new DashboardState();
        state.subscribe((data) => {
            if (currentTab !== 'feed') return;
            alertsContainer.innerHTML = `
                <div id="topic-filters-container"></div>
                <div id="featured-reports-container" class="u-flex" style="margin-bottom:2rem; flex-wrap:wrap; gap:var(--space-m);"></div>
                <h3 class="u-m-top-1" style="margin-bottom: 1.5rem; color: #c9d1d9; border-bottom: 2px solid #30363d; padding-bottom: 0.5rem;">Live Alert Stream</h3>
                <div id="feed-alerts-inner"><div class="u-p-2 u-text-center">Fetching Intelligence Feed...</div></div>
            `;
            if (data.health) renderHealth(data.health, healthContainer);
            renderAlerts(data.alerts, document.querySelector<HTMLElement>('#feed-alerts-inner')!);
            renderTopicFilters(document.querySelector<HTMLElement>('#topic-filters-container')!, state);
        });
        
        (window as any).stopPolling = () => state.stopPolling();
        state.startPolling();
    };

    const renderTopicFilters = (container: HTMLElement, state: DashboardState) => {
        if (!container) return;
        const currentTopic = state.topic;
        container.innerHTML = `
            <div class="topic-filter-bar">
                ${TOPICS.filter(t => !t.restricted || (user && user.tier === 'pro')).map(t => `
                    <button class="topic-btn ${currentTopic === t.code ? 'topic-btn--active' : ''}" data-topic="${t.code}">
                        ${t.label}
                    </button>
                `).join('')}
            </div>
        `;
        container.querySelectorAll('.topic-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                state.setTopic((e.currentTarget as HTMLButtonElement).dataset.topic || null);
            });
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
        alertsContainer.innerHTML = '<div class="u-p-2 u-text-center">Loading expertise catalog...</div>';
        try {
            const reports = await fetchReport('all') as any[];
            alertsContainer.innerHTML = `
                <div class="reports-grid u-m-top-1">
                    ${reports.map(r => `
                        <div class="alert-card u-tier-3" style="cursor:pointer;" onclick="window.dispatchEvent(new CustomEvent('view-report', {detail:{reportId:'${r.id}'}}))">
                             <div class="u-flex-between">
                                <span class="severity-badge" style="background:var(--accent-soft); color:var(--accent); border:1px solid var(--accent);">${(r.report_type || 'daily').toUpperCase()}</span>
                                <span style="font-size:var(--font-xs); color:#8b949e;">${new Date(r.created_at).toLocaleDateString()}</span>
                            </div>
                            <h3 style="margin-top:0.5rem;">${r.title}</h3>
                            <div class="u-flex-between u-m-top-1">
                                <span style="font-size:var(--font-xs); color:var(--tier-grace); font-weight:600;">${getTopicLabel(r.topic_code)}</span>
                                <button class="btn-fb active u-tier-1">Read Analysis</button>
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
        } catch (e) { alertsContainer.innerHTML = '<div class="u-p-2 u-text-center">Unable to load reports.</div>'; }
    };

    const renderSingleReport = async (id: string) => {
        (window as any).stopPolling?.();
        mainTitle.textContent = 'Situation Report';
        healthContainer.innerHTML = '';
        try {
            const report = await fetchReport(id);
            renderReportDetail(report, alertsContainer, () => handleTabSwitch('feed'), (action) => {
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
