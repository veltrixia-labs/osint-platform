import './style.css'
import { DashboardState } from './modules/poll'
import { renderAlerts, renderHealth, renderSidebar, renderReportDetail } from './modules/render'
import { login, fetchMe, logout, fetchUsage, fetchReport, fetchPublicReport } from './modules/api'
import type { UsageResponse } from './modules/api'
import {
    renderTierBadge,
    renderGracePeriodBanner,
    renderSubscriptionTab,
    renderLockedFeature,
} from './modules/subscription'

const TOPICS = [
    { code: 'global', label: '🌍 Global', restricted: false },
    { code: 'market', label: '📈 Market', restricted: false },
    { code: 'community', label: '🤝 Community', restricted: false },
    { code: 'energy_resource_risk', label: '⚡ Energy', restricted: true },
    { code: 'global_market_intelligence', label: '💰 Finance', restricted: true },
    { code: 'ai_semiconductor_intelligence', label: '🤖 AI/Semi', restricted: true },
    { code: 'crypto_geopolitics', label: '₿ Crypto', restricted: true },
    { code: 'defense_technology', label: '🛡️ Defense', restricted: true },
    { code: 'supply_chain_intelligence', label: '📦 Supply Chain', restricted: true },
];

const app = document.querySelector<HTMLDivElement>('#app')!

async function renderLogin() {
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
    
    let user = await fetchMe();
    
    if (!user && !reportId) {
        renderLogin();
        return;
    }

    const graceBannerHtml = user ? renderGracePeriodBanner(user) : '';
    const tierBadgeHtml = user ? renderTierBadge(user) : '<span class="tier-badge-free">GUEST</span>';

    app.innerHTML = `
      <aside class="sidebar" id="sidebar">
          <div class="user-info">
              <div style="display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap;">
                <span class="role-badge">${user ? user.role : 'Guest'}</span>
                ${tierBadgeHtml}
              </div>
              <span class="chat-id">${user ? user.chat_id : 'Not Logged In'}</span>
              ${user ? '<button id="logout-btn" class="logout-btn">Logout</button>' : '<button id="login-goto-btn" class="logout-btn" style="background:var(--tier-grace);">Log In</button>'}
          </div>

          <!-- Navigation -->
          <nav id="sidebar-nav" style="margin-bottom:1rem;">
              <div class="sidebar-nav-link sidebar-nav-link--active" data-tab="feed" id="nav-feed">
                  📡 Intelligence Feed
              </div>
              <div class="sidebar-nav-link" data-tab="reports" id="nav-reports">
                  📜 Intelligence Reports
              </div>
              <div class="sidebar-nav-link" data-tab="plans" id="nav-plans">
                  💳 Plans & Billing
              </div>
          </nav>

          <!-- Usage Widget (Phase 33) -->
          <div id="usage-widget"></div>

          <div id="sidebar-content"></div>
      </aside>

      <main class="main-content">
        ${graceBannerHtml ? `<div id="grace-header">${graceBannerHtml}</div>` : ''}
        <div class="header-row">
          <h1 id="main-title">Analyst Intelligence</h1>
          <div id="health-container"></div>
        </div>
        <div class="main-feed" id="alerts-container">
          <div style="padding: 2rem; text-align: center; color: #8b949e;">Initializing intelligence feed...</div>
        </div>
      </main>
    `

    document.querySelector('#logout-btn')?.addEventListener('click', logout)
    document.querySelector('#login-goto-btn')?.addEventListener('click', () => renderLogin())

    const alertsContainer = document.querySelector<HTMLDivElement>('#alerts-container')!
    const healthContainer = document.querySelector<HTMLDivElement>('#health-container')!
    const sidebarContainer = document.querySelector<HTMLDivElement>('#sidebar-content')!
    const mainTitle = document.querySelector<HTMLHeadingElement>('#main-title')!

    // ── Polling state ─────────────────────────────────────────────────────────
    let activeTab: TabId = 'feed'
    let polling: DashboardState | null = null
    let usage: UsageResponse | null = null

    function stopPolling() {
        if (polling) { polling.stopPolling(); polling = null; }
    }

    function renderTopicFilters(container: HTMLElement, state: DashboardState) {
        const wrap = document.createElement('div');
        wrap.className = 'topic-filter-bar';
        wrap.style.display = 'flex';
        wrap.style.gap = '0.5rem';
        wrap.style.overflowX = 'auto';
        wrap.style.paddingBottom = '1rem';
        wrap.style.marginBottom = '1rem';
        wrap.style.borderBottom = '1px solid var(--border)';

        const allBtn = document.createElement('button');
        allBtn.className = `topic-btn ${state.topic === null ? 'topic-btn--active' : ''}`;
        allBtn.textContent = 'All Topics';
        allBtn.onclick = () => state.setTopic(null);
        wrap.appendChild(allBtn);

        TOPICS.forEach(t => {
            const btn = document.createElement('button');
            const isRestricted = usage?.topics.restricted.includes(t.code);
            btn.className = `topic-btn ${state.topic === t.code ? 'topic-btn--active' : ''} ${isRestricted ? 'topic-btn--locked' : ''}`;
            btn.innerHTML = `${t.label}${isRestricted ? ' 🔒' : ''}`;
            
            btn.onclick = () => {
                if (isRestricted) {
                    alertsContainer.innerHTML = renderLockedFeature(t.label, 'pro');
                    state.stopPolling();
                } else {
                    state.setTopic(t.code);
                    if (!state.isPolling) state.startPolling(5000);
                }
            };
            wrap.appendChild(btn);
        });

        container.prepend(wrap);
    }

    function startFeedTab() {
        stopPolling()
        if (!user) {
            alertsContainer.innerHTML = renderLockedFeature('Intelligence Feed', 'free');
            mainTitle.textContent = 'Analyst Intelligence'
            healthContainer.innerHTML = ''
            return;
        }
        mainTitle.textContent = 'Analyst Intelligence'
        alertsContainer.innerHTML = '<div style="padding:2rem;text-align:center;color:#8b949e;">Loading feed…</div>'
        healthContainer.innerHTML = ''

        const state = new DashboardState()
        state.subscribe((s: DashboardState) => {
            renderAlerts(s.alerts, alertsContainer)
            if (s.health) renderHealth(s.health, healthContainer)
            renderSidebar(s.analysts, sidebarContainer)
            renderTopicFilters(alertsContainer, s)
        })
        state.startPolling(5000)
        polling = state
    }

    function renderReportsTab() {
        if (activeTab === 'reports') return
        activeTab = 'reports'
        setNavActive('reports')
        stopPolling()
        mainTitle.textContent = 'Intelligence Reports'
        healthContainer.innerHTML = ''
        sidebarContainer.innerHTML = ''

        const isLocked = usage?.reports.monthly === false;

        alertsContainer.innerHTML = `
            <div class="reports-container" style="display:grid; grid-template-columns: 1fr 1fr; gap: 1.5rem;">
                <div class="report-card">
                    <h3>📅 Daily Intelligence Briefing</h3>
                    <p>Comprehensive summary of the last 24 hours of detected signals.</p>
                    <button class="btn-fb active">View Latest</button>
                </div>
                <div class="report-card ${isLocked ? 'report-card--locked' : ''}">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <h3>📊 Monthly Risk Outlook</h3>
                        ${isLocked ? '<span style="color:var(--tier-grace);">🔒 Pro Preferred</span>' : ''}
                    </div>
                    <p>Macro-scale trend analysis and long-term risk projections.</p>
                    ${isLocked 
                        ? `<button class="plan-cta-btn" id="locked-monthly-btn">Unlock with Pro</button>`
                        : `<button class="btn-fb active">View Latest</button>`
                    }
                </div>
            </div>
        `;

        if (isLocked) {
            document.querySelector('#locked-monthly-btn')?.addEventListener('click', () => {
                alertsContainer.innerHTML = renderLockedFeature('Monthly Risk Outlook', 'pro');
            });
        }
    }

    function navigateToPlans() {
        if (activeTab === 'plans') return
        activeTab = 'plans'
        setNavActive('plans')
        stopPolling()
        mainTitle.textContent = 'Plans & Billing'
        healthContainer.innerHTML = ''
        sidebarContainer.innerHTML = ''
        renderSubscriptionTab(user!, alertsContainer, navigateToPlans)
    }

    function navigateToFeed() {
        if (activeTab === 'feed') return
        activeTab = 'feed'
        setNavActive('feed')
        startFeedTab()
    }

    function navigateToReports() {
        renderReportsTab()
    }

    function setNavActive(tab: TabId) {
        document.querySelectorAll('.sidebar-nav-link').forEach(el => {
            el.classList.toggle('sidebar-nav-link--active', el.getAttribute('data-tab') === tab)
        })
    }

    // ── Nav click handlers ────────────────────────────────────────────────────
    document.querySelector('#nav-feed')?.addEventListener('click', navigateToFeed)
    document.querySelector('#nav-reports')?.addEventListener('click', navigateToReports)
    document.querySelector('#nav-plans')?.addEventListener('click', navigateToPlans)

    // Grace period banner → Plans tab
    document.querySelector('#grace-upgrade-link')?.addEventListener('click', (e) => {
        e.preventDefault(); navigateToPlans()
    })

    // Locked-feature overlays that might be rendered inside the feed
    alertsContainer.addEventListener('click', (e) => {
        const target = e.target as HTMLElement
        if (target.id === 'locked-goto-plans' || target.closest('#locked-goto-plans')) {
            e.preventDefault(); navigateToPlans()
        }
    })

    // ── Usage Widget ──────────────────────────────────────────────────────────
    const usageWidget = document.querySelector<HTMLDivElement>('#usage-widget')!
    let currentUsage: UsageResponse | null = null;

    function renderUsageWidget(u: UsageResponse) {
        usage = u;
        currentUsage = u;
        const alertPct = u.alerts.limit > 0
            ? Math.min(100, Math.round((u.alerts.used / u.alerts.limit) * 100))
            : 0;
        const kwPct = u.keywords.limit > 0
            ? Math.min(100, Math.round((u.keywords.used / u.keywords.limit) * 100))
            : 0;
        const alertLimit = u.alerts.limit === -1 ? '∞' : u.alerts.limit;
        const alertBarColor = alertPct >= 90 ? '#f85149' : alertPct >= 70 ? '#d29922' : '#3fb950';
        const kwBarColor = kwPct >= 90 ? '#f85149' : kwPct >= 70 ? '#d29922' : '#3fb950';

        const restrictedHtml = u.topics.restricted.length > 0
            ? `<div class="usage-restricted">🔒 ${u.topics.restricted.length} topic${u.topics.restricted.length > 1 ? 's' : ''} locked</div>`
            : '';
        const monthlyHtml = u.reports.monthly
            ? ''
            : '<div class="usage-restricted">🔒 Monthly reports locked</div>';

        usageWidget.innerHTML = `
          <div class="usage-card">
            <h4 class="usage-title">Usage</h4>
            <div class="usage-row">
              <span class="usage-label">Alerts today</span>
              <span class="usage-value">${u.alerts.used} / ${alertLimit}</span>
            </div>
            <div class="usage-bar"><div class="usage-bar-fill" style="width:${alertPct}%;background:${alertBarColor}"></div></div>
            <div class="usage-row">
              <span class="usage-label">Keywords</span>
              <span class="usage-value">${u.keywords.used} / ${u.keywords.limit}</span>
            </div>
            <div class="usage-bar"><div class="usage-bar-fill" style="width:${kwPct}%;background:${kwBarColor}"></div></div>
            ${restrictedHtml}
            ${monthlyHtml}
          </div>
        `;
    }

    async function refreshUsage() {
        try {
            const usage = await fetchUsage();
            renderUsageWidget(usage);
            return usage;
        } catch (e) {
            console.warn('Failed to fetch usage:', e);
            return null;
        }
    }

    // Re-expose to global window for other modules to access easily in SPA
    (window as any).refreshUsage = refreshUsage;
    (window as any).getCurrentUsage = () => currentUsage;

    // ── Initial render ────────────────────────────────────────────────────────
    startFeedTab()
    // ── Phase 34: Report ID Direct Access Routing ─────────────────────────────
    if (reportId) {
        // Switch to reports tab UI state
        activeTab = 'reports';
        setNavActive('reports');
        stopPolling();
        mainTitle.textContent = 'Intelligence Report';
        healthContainer.innerHTML = '';
        sidebarContainer.innerHTML = '';
        alertsContainer.innerHTML = '<div style="padding:2rem;text-align:center;color:#8b949e;">Loading report details...</div>';
        
        try {
            const report = user 
                ? await fetchReport(reportId) 
                : await fetchPublicReport(reportId);
            renderReportDetail(report, alertsContainer);
            
            // Clean URL for clean experience only if logged in 
            // If NOT logged in, we might want to keep it to allow login redirect back? 
            // But the user didn't ask for full return path yet.
            if (user) window.history.replaceState({}, '', window.location.pathname);
        } catch (err: any) {
            alertsContainer.innerHTML = `
                <div style="padding:4rem; text-align:center;">
                    <h2 style="color:#f85149;">Report Unavailable</h2>
                    <p style="color:#8b949e; margin-bottom:2rem;">${err.message || 'The specified report could not be found or access is restricted.'}</p>
                    <button class="btn-fb active" onclick="location.href='/'">Return to Dashboard</button>
                </div>
            `;
        }
    }
}

// Entry Point
initDashboard().catch(() => renderLogin())

// Export for use in other modules (e.g., render.ts locked-feature insertion)
export { renderLockedFeature }
