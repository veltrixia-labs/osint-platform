import './style.css'
import { DashboardState } from './modules/poll'
import { renderAlerts, renderHealth, renderSidebar, renderReportDetail } from './modules/render'
import { login, fetchMe, logout, fetchUsage, fetchReport, fetchPublicReport, logAnalyticsEvent } from './modules/api'
import type { UsageResponse } from './modules/api'
import {
    renderTierBadge,
    renderGracePeriodBanner,
    renderSubscriptionTab,
    renderLockedFeature,
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
    // Stop any active polling from guest dashboard to avoid redundant UI renders
    (window as any).stopPolling?.();
    
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

    // Handle Payment Success Confirmation Synchronously 
    const paymentStatus = urlParams.get('payment');
    const sessionId = urlParams.get('session_id');

    if (sessionId && user) {
        try {
            const { confirmCheckoutSession } = await import('./modules/api');
            await confirmCheckoutSession(sessionId);
            // Refresh user state immediately to reflect Pro tier before fetching report
            user = await fetchMe();
        } catch (err) {
            console.error("Fulfillment Error:", err);
        }
    }

    if (paymentStatus === 'success' && sessionId && !user) {
        app.innerHTML = `
            <div style="padding: 4rem; text-align: center; max-width: 600px; margin: 0 auto;">
                <h2 style="color:#3fb950; display:flex; align-items:center; justify-content:center; gap:0.5rem;">
                    <span>✨</span> Payment Received
                </h2>
                <p style="color:#8b949e; margin-bottom:2rem; line-height:1.6;">Your subscription payment was successfully processed by Stripe, but your browser session has expired or you are on a different device.</p>
                <div style="background: rgba(88,166,255,0.1); border: 1px solid rgba(88,166,255,0.2); padding: 1.5rem; border-radius: 8px; margin-bottom: 2rem;">
                    <p style="margin:0; color:#c9d1d9;">Please log in again to instantly unlock your report.</p>
                </div>
                <button class="plan-cta-btn" id="relogin-btn" style="width: 100%;">Log In Now</button>
            </div>
        `;
        document.querySelector('#relogin-btn')?.addEventListener('click', () => renderLogin());
        return; // Halt render, keeping URL params intact
    }

    if (paymentStatus) {
        const notify = document.createElement('div');
        notify.className = `payment-notification ${paymentStatus}`;
        
        if (paymentStatus === 'success') {
            notify.innerHTML = `
                <div style="background: rgba(63, 185, 80, 0.15); border: 1px solid #3fb950; color: #3fb950; padding: 1rem; border-radius: 8px; margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem;">
                    ✨ <span id="payment-msg"><b>Payment Successful!</b> Welcome to Founding Member Access. Your Pro features are now active.</span>
                </div>
            `;
            setTimeout(() => notify.remove(), 8000);
        } else if (paymentStatus === 'cancel') {
            notify.innerHTML = `
                <div style="background: rgba(248, 81, 73, 0.1); border: 1px solid #f85149; color: #8b949e; padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
                    Payment canceled. You are still on the Free plan.
                </div>
            `;
            setTimeout(() => notify.remove(), 5000);
        }

        // Wait for DOM to be ready to prepend to .main-content
        requestAnimationFrame(() => {
            const mainContent = document.querySelector('.main-content');
            if (mainContent) mainContent.prepend(notify);
        });
    }

    const graceBannerHtml = user ? renderGracePeriodBanner(user) : '';
    const tierBadgeHtml = user ? renderTierBadge(user) : '<span class="tier-badge-free">GUEST</span>';

    app.innerHTML = `
      <div class="mobile-header">
          <div class="u-flex">
              <button class="hamburger" id="hamburger-btn">☰</button>
              <h2 style="font-size: 1.1rem; margin:0;">OSINT Intel</h2>
          </div>
          ${tierBadgeHtml}
      </div>
      <div class="mobile-overlay" id="mobile-overlay"></div>

      <aside class="sidebar" id="sidebar">
          <div class="user-info">
              <div class="u-flex" style="flex-wrap:wrap;">
                <span class="role-badge">${user ? user.role : 'Guest'}</span>
                ${tierBadgeHtml}
              </div>
              <span class="chat-id">${user ? user.chat_id : 'Not Logged In'}</span>
              ${user ? '<button id="logout-btn" class="logout-btn">Logout</button>' : '<button id="login-goto-btn" class="logout-btn" style="background:var(--tier-grace);">Log In</button>'}
          </div>

          <nav id="sidebar-nav">
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
          <div class="u-p-2 u-text-center">Initializing intelligence feed...</div>
        </div>
      </main>
    `

    // Mobile Sidebar Logic
    const sidebar = document.querySelector('#sidebar') as HTMLElement;
    const overlay = document.querySelector('#mobile-overlay') as HTMLElement;
    const hamburger = document.querySelector('#hamburger-btn') as HTMLElement;

    const toggleSidebar = (forceClose = false) => {
        const isActive = forceClose ? true : sidebar.classList.contains('active');
        if (isActive) {
            sidebar.classList.remove('active');
            overlay.classList.remove('active');
            document.body.classList.remove('no-scroll');
        } else {
            sidebar.classList.add('active');
            overlay.classList.add('active');
            document.body.classList.add('no-scroll');
        }
    };

    hamburger?.addEventListener('click', () => toggleSidebar());
    overlay?.addEventListener('click', () => toggleSidebar(true));
    
    // Close sidebar on nav click (mobile)
    document.querySelectorAll('.sidebar-nav-link').forEach(link => {
        link.addEventListener('click', () => {
            if (window.innerWidth <= 768) toggleSidebar(true);
        });
    });

    window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') toggleSidebar(true);
    });

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
    
    // Expose stopPolling to allow other modules/functions to clean up UI before login
    (window as any).stopPolling = stopPolling;

    // ── State Preservation ──────────────────────────────────────────────────
    let lastFeedHTML: string | null = null;
    let lastReportsHTML: string | null = null;

    function renderTopicFilters(container: HTMLElement, currentTopic: string | null) {
        container.innerHTML = '';
        const wrap = document.createElement('div');
        wrap.className = 'topic-filter-bar';

        const allBtn = document.createElement('button');
        allBtn.className = `topic-btn ${currentTopic === null ? 'topic-btn--active' : ''}`;
        allBtn.textContent = 'All Topics';
        allBtn.onclick = () => startFeedTab(null);
        wrap.appendChild(allBtn);

        TOPICS.forEach(t => {
            const btn = document.createElement('button');
            const isRestricted = usage?.topics.restricted.includes(t.code);
            btn.className = `topic-btn ${currentTopic === t.code ? 'topic-btn--active' : ''} ${isRestricted ? 'topic-btn--locked' : ''}`;
            btn.innerHTML = `${t.label}${isRestricted ? ' 🔒' : ''}`;
            
            btn.onclick = () => {
                if (isRestricted) {
                    const alertsContainer = document.querySelector<HTMLDivElement>('#alerts-container');
                    if (alertsContainer) alertsContainer.innerHTML = renderLockedFeature(t.label, 'pro');
                    stopPolling();
                } else {
                    startFeedTab(t.code);
                }
            };
            wrap.appendChild(btn);
        });

        container.appendChild(wrap);
    }
    
    function startFeedTab(topic: string | null = null, restoreOnly: boolean = false) {
        stopPolling()
        if (!user) {
            alertsContainer.innerHTML = renderLockedFeature('Intelligence Dashboard', 'free');
            mainTitle.innerHTML = 'Analyst Intelligence'
            healthContainer.innerHTML = ''
            return;
        }

        const proBadgeHtml = user.tier === 'pro' ? '<span style="font-size: 0.9rem; margin-left:1rem; padding: 4px 12px; background: rgba(88,166,255,0.1); border: 1px solid rgba(88,166,255,0.3); color: #c9d1d9; border-radius: 20px; vertical-align:middle; box-shadow: 0 0 10px rgba(88,166,255,0.2);">💎 PRO: Full Access Active</span>' : '';
        mainTitle.innerHTML = `Dashboard ${proBadgeHtml}`;
        healthContainer.innerHTML = ''

        if (restoreOnly && lastFeedHTML) {
            // Restore cached HTML and re-bind handlers
            alertsContainer.innerHTML = lastFeedHTML;
            attachFeedClicks(topic);
        } else {
            alertsContainer.innerHTML = `
                <div id="topic-filters-container"></div>
                <div id="featured-reports-container" class="u-flex" style="margin-bottom:2rem; flex-wrap:wrap; gap:var(--space-m);"></div>
                <div id="topic-reports-grid" class="reports-grid" style="margin-bottom:1rem;"></div>
                <h3 class="u-m-top-1" style="margin-bottom: 1rem; color: #c9d1d9; border-bottom: 1px solid #30363d; padding-bottom: 0.5rem;">Live Alert Stream</h3>
                <div id="feed-alerts-inner"><div class="u-p-2 u-text-center">Fetching Intelligence Feed...</div></div>
            `;

            const filtersContainer = alertsContainer.querySelector('#topic-filters-container') as HTMLElement;
            const featuredContainer = alertsContainer.querySelector('#featured-reports-container') as HTMLElement;
            const reportsGrid = alertsContainer.querySelector('#topic-reports-grid') as HTMLElement;

            renderTopicFilters(filtersContainer, topic);

            // Fetch and render the static reports section
            import('./modules/api').then(async m => {
                try {
                    const reports = await m.fetchReports(20, topic ? topic : undefined);
                    let gridReports = reports;

                    if (!topic) {
                        const latestPremium = reports.find((r: any) => r.is_premium);
                        const latestFree = reports.find((r: any) => !r.is_premium);
                        
                        if (latestPremium) {
                            featuredContainer.innerHTML += `
                                <div class="report-card report-card--premium" style="flex:1; min-width:300px; border: 2px solid var(--tier-pro);">
                                    <div class="premium-lock-badge" style="margin-bottom:0.5rem; display:inline-block; font-size:0.75rem;">💎 Featured Premium Intelligence</div>
                                    <h2 style="margin: 0 0 1rem 0; font-size: 1.4rem;">${latestPremium.content_markdown.split('\n')[0].replace('# ', '')}</h2>
                                    <div style="color:#8b949e; font-size:0.9rem; margin-bottom: 1.5rem;">
                                        ${getMarkdownPreview(latestPremium.content_markdown)}
                                    </div>
                                    <button class="btn-fb active view-report-btn" data-id="${latestPremium.id}">Unlock Full Analysis</button>
                                </div>
                            `;
                        }
                        if (latestFree) {
                            featuredContainer.innerHTML += `
                                <div class="report-card" style="flex:1; min-width:300px; border: 1px solid var(--tier-grace); background: rgba(255,255,255,0.03);">
                                    <div class="role-badge" style="margin-bottom:0.5rem; display:inline-block; font-size:0.75rem; background:rgba(255,255,255,0.1);">🌍 Daily Free Briefing</div>
                                    <h3 style="margin: 0 0 1rem 0; font-size: 1.25rem;">${latestFree.content_markdown.split('\n')[0].replace('# ', '')}</h3>
                                    <div style="color:#8b949e; font-size:0.9rem; margin-bottom: 1.5rem;">
                                        ${getMarkdownPreview(latestFree.content_markdown)}
                                    </div>
                                    <button class="btn-fb active view-report-btn" data-id="${latestFree.id}">Read Briefing</button>
                                </div>
                            `;
                        }
                        
                        // Filter featured ones out of the grid
                        gridReports = reports.filter((r: any) => r.id !== latestPremium?.id && r.id !== latestFree?.id);
                    } else {
                        featuredContainer.style.display = 'none';
                    }

                    if (gridReports.length > 0) {
                        reportsGrid.innerHTML = gridReports.map((r: any) => `
                            <div class="report-card ${r.is_premium ? 'report-card--premium' : ''}" data-id="${r.id}">
                                <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:1rem;">
                                    <span class="report-topic-badge">${getTopicLabel(r.topic_code)}</span>
                                    ${r.is_premium ? '<span class="premium-lock-badge">🔒 Premium</span>' : ''}
                                </div>
                                <h3 style="margin: 0 0 0.5rem 0; font-size: 1.1rem;">${r.content_markdown.split('\n')[0].replace('# ', '')}</h3>
                                <p style="font-size: 0.85rem; color: #8b949e; margin-bottom: 1.5rem; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; height: 2.4rem;">
                                    ${getMarkdownPreview(r.content_markdown)}
                                </p>
                                <div class="report-meta" style="font-size: 0.75rem; color: #8b949e; margin-bottom: 1rem; display: flex; gap: 0.8rem;">
                                    <span>🔍 ${r.source_count || 0}</span>
                                    <span>⚖️ ${r.confidence_level || 'Medium'}</span>
                                </div>
                                <button class="btn-fb active view-report-btn" style="width:100%; margin-top: auto;" data-id="${r.id}">View Intelligence</button>
                            </div>
                        `).join('');
                    } else if (topic) {
                        reportsGrid.innerHTML = '<div style="color:#8b949e; text-align:center; grid-column: 1 / -1; padding: 1rem 0;">No reports available for this topic yet. Generate one via alerts to see it here.</div>';
                    }

                    attachFeedClicks(topic);
                } catch (err) {
                    console.error("Dashboard reports error:", err);
                }
            });
        }

        const feedAlertsInner = alertsContainer.querySelector('#feed-alerts-inner') as HTMLElement;
        const state = new DashboardState()
        state.topic = topic; // So alert feed matches topic
        state.subscribe((s: DashboardState) => {
            if (feedAlertsInner) renderAlerts(s.alerts, feedAlertsInner)
            if (s.health) renderHealth(s.health, healthContainer)
            renderSidebar(s.analysts, sidebarContainer)
        })
        state.startPolling(5000)
        polling = state
    }

    function attachFeedClicks(topic: string | null) {
        import('./modules/api').then(m => {
            alertsContainer.querySelectorAll('.view-report-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    const id = (e.currentTarget as HTMLElement).dataset.id!;
                    try {
                        const fullReport = await m.fetchReport(id);
                        // Preserve current list HTML before rendering detail
                        lastFeedHTML = alertsContainer.innerHTML;
                        renderReportDetail(fullReport, alertsContainer, () => {
                             // Context-aware Back navigation with state preservation
                             if (lastFeedHTML) {
                                 startFeedTab(topic, true); // Use the restoreOnly flag
                             } else {
                                 startFeedTab(topic);
                             }
                        }, async (actionType) => {
                             if (actionType === 'upgrade') {
                                 try {
                                     const response = await m.fetchCheckoutSession('pro', id);
                                     if (response.url) window.location.href = response.url;
                                 } catch (err) {
                                     document.querySelector<HTMLElement>('#nav-plans')?.click();
                                 }
                             }
                        });
                    } catch (err) {
                        alert("Failed to load report detail (Missing auth?): " + err);
                    }
                });
            });
        });
    }
    
    async function renderReportsTab(restoreOnly: boolean = false) {
        if (activeTab === 'reports' && !restoreOnly) return
        activeTab = 'reports'
        setNavActive('reports')
        stopPolling()
        mainTitle.textContent = 'Intelligence Reports'
        healthContainer.innerHTML = ''
        sidebarContainer.innerHTML = ''

        if (restoreOnly && lastReportsHTML) {
            // HTML already set, just re-bind handlers
            attachReportGridClicks();
            return;
        }

        alertsContainer.innerHTML = '<div style="padding:2rem;text-align:center;color:#8b949e;">Loading reports…</div>'
        
        try {
            const reports = await import('./modules/api').then(m => m.fetchReports(20));
            
            if (reports.length === 0) {
                alertsContainer.innerHTML = '<div style="padding:2rem;text-align:center;color:#8b949e;">No reports found. Generate one to see it here.</div>';
                return;
            }

            alertsContainer.innerHTML = `
                <div class="reports-grid" style="display:grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1.5rem;">
                    ${reports.map((r: any) => {
                        const planLabel = (r.plan_required || 'free').toUpperCase();
                        const typeLabel = (r.report_type || 'daily').toUpperCase();
                        const isPremium = r.is_premium || r.plan_required !== 'free';

                        return `
                            <div class="report-card ${isPremium ? 'report-card--premium' : ''}" data-id="${r.id}">
                                <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:1rem;">
                                    <div style="display:flex; flex-direction:column; gap:4px;">
                                        <span class="report-topic-badge">${getTopicLabel(r.topic_code)}</span>
                                        <span style="font-size:0.65rem; color:#8b949e; background:rgba(255,255,255,0.05); padding:2px 6px; border-radius:4px; border:1px solid rgba(255,255,255,0.1); width:fit-content;">
                                            ${typeLabel}
                                        </span>
                                    </div>
                                    <div style="display:flex; flex-direction:column; align-items:flex-end; gap:4px;">
                                        ${isPremium ? `<span class="premium-lock-badge" style="background:rgba(210,153,34,0.1); color:#d29922; border:1px solid rgba(210,153,34,0.3);">🔒 ${planLabel}</span>` : '<span class="premium-lock-badge" style="background:rgba(63,185,80,0.1); color:#3fb950; border:1px solid rgba(63,185,80,0.3);">✓ FREE</span>'}
                                    </div>
                                </div>
                                <h3 style="margin: 0 0 0.5rem 0; font-size: 1.1rem; line-height: 1.4; color: #c9d1d9;">${r.title}</h3>
                                <p style="font-size: 0.85rem; color: #8b949e; margin-bottom: 1.5rem; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; height: 3.6rem; min-height: 3.6rem;">
                                    ${r.teaser_md || 'Detailed OSINT intelligence analysis and trend forecasting regarding identified signals.'}
                                </p>
                                <div class="report-meta" style="font-size: 0.8rem; color: #8b949e; margin-bottom: 1.5rem; display: flex; gap: 1rem;">
                                    <span>🔍 ${r.source_count || 0} Sources</span>
                                    <span>⚖️ ${r.confidence_level || 'Medium'}</span>
                                </div>
                                <button class="btn-fb active view-report-btn" data-id="${r.id}" style="width:100%;">View Intelligence</button>
                            </div>
                        `;
                    }).join('')}
                </div>
            `;

            attachReportGridClicks();

        } catch (err) {
            alertsContainer.innerHTML = `<div style="padding:2rem;text-align:center;color:#f85149;">Error loading reports: ${err}</div>`;
        }
    }

    function attachReportGridClicks() {
        alertsContainer.querySelectorAll('.view-report-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = (e.currentTarget as HTMLElement).dataset.id!;
                try {
                    const { fetchReport: getFullReport } = await import('./modules/api');
                    const fullReport = await getFullReport(id);
                    lastReportsHTML = alertsContainer.innerHTML;
                    renderReportDetail(fullReport, alertsContainer, () => {
                        if (lastReportsHTML) {
                            alertsContainer.innerHTML = lastReportsHTML;
                            renderReportsTab(true);
                        } else {
                            renderReportsTab();
                        }
                    }, async (actionType) => {
                         if (actionType === 'upgrade') {
                             try {
                                 const { fetchCheckoutSession } = await import('./modules/api');
                                 const response = await fetchCheckoutSession('pro', id);
                                 if (response.url) window.location.href = response.url;
                             } catch (err) {
                                 document.querySelector<HTMLElement>('#nav-plans')?.click();
                             }
                         }
                    });
                } catch (err) {
                    alert("Failed to load report detail: " + err);
                }
            });
        });
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


    function setNavActive(tab: TabId) {
        document.querySelectorAll('.sidebar-nav-link').forEach(el => {
            el.classList.toggle('sidebar-nav-link--active', el.getAttribute('data-tab') === tab)
        })
    }

    // ── Nav click handlers ────────────────────────────────────────────────────
    document.querySelector('#nav-feed')?.addEventListener('click', navigateToFeed)
    document.querySelector('#nav-reports')?.addEventListener('click', () => renderReportsTab())
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
            const utms = captureUtms(urlParams);
            const report = user 
                ? await fetchReport(reportId) 
                : await fetchPublicReport(reportId);
            
            // Log analytics event
            logAnalyticsEvent(user ? 'full_view' : 'preview_view', reportId, utms);

            renderReportDetail(report, alertsContainer, () => {
                // Return to reports tab
                renderReportsTab();
            }, async (actionType) => {
                if (!user) {
                    renderLogin();
                } else if (actionType === 'upgrade') {
                    // Direct to Pro checkout for Founding Member Access
                    try {
                        const { fetchCheckoutSession } = await import('./modules/api');
                        const response = await fetchCheckoutSession('pro', reportId);
                        if (response.url) {
                            window.location.href = response.url;
                        } else {
                            throw new Error("No checkout URL returned");
                        }
                    } catch (err) {
                        console.error("Checkout redirect failed:", err);
                        // Fallback to plans tab if direct checkout fails
                        (document.querySelector('#nav-plans') as HTMLElement)?.click();
                    }
                }
            });
            
            // Clean URL for clean experience only if logged in 
            if (user) {
                window.history.replaceState({}, '', window.location.pathname);
            }
        } catch (err: any) {
            alertsContainer.innerHTML = `
                <div style="padding:4rem; text-align:center;">
                    <h2 style="color:#f85149;">Report Unavailable</h2>
                    <p style="color:#8b949e; margin-bottom:2rem;">${err.message || 'The specified report could not be found or access is restricted.'}</p>
                    <button class="btn-fb active" id="error-back-btn">Return to Dashboard</button>
                </div>
            `;
            document.querySelector('#error-back-btn')?.addEventListener('click', () => {
                window.history.replaceState({}, '', window.location.pathname);
                initDashboard();
            });
        }
    }
    // ── Alert Report Navigation (Phase 36) ──────────────────────────────────
    window.addEventListener('view-report', async (e: any) => {
        const { reportId } = e.detail;
        if (!reportId) return;

        try {
            const { fetchReport: getFullReport } = await import('./modules/api');
            const fullReport = await getFullReport(reportId);
            
            // Note: We don't necessarily have a 'lastFeedHTML' or 'lastReportsHTML' 
            // if we are jumping directly from the alert stream, so we'll just 
            // set a default back behavior.
            renderReportDetail(fullReport, alertsContainer, () => {
                startFeedTab(); // Return to feed dashboard
            }, async (actionType: string) => {
                if (actionType === 'upgrade') {
                    const { fetchCheckoutSession } = await import('./modules/api');
                    const response = await fetchCheckoutSession('pro', reportId);
                    if (response.url) window.location.href = response.url;
                }
            });
        } catch (err) {
            console.error("Failed to jump to report from alert:", err);
        }
    });
}

// Entry Point
initDashboard().catch(() => renderLogin())

// Export for use in other modules (e.g., render.ts locked-feature insertion)
export { renderLockedFeature }
