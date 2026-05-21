import './theme.css'
import './style.css'
import './theme-terminal.css'
import './mobile-responsive.css'
declare const __APP_BUILD_INFO__: string;
console.log(`[Antigravity] Resolved API base: ${getResolvedApiBase()} (VITE_API_BASE_URL=${String(import.meta.env.VITE_API_BASE_URL ?? '')})`);
console.log(`[Antigravity] Mode: ${import.meta.env.MODE}`);
console.log(`[Antigravity] VITE_DEV_TIER: ${String(import.meta.env.VITE_DEV_TIER ?? '(unset)')}`);
console.log(`[Antigravity] Build Version: v11.1.2-AURORA-SYNC`);
console.log(`[Antigravity] Deploy Signature: AURORA-SYNC-${Date.now()}`);
console.log(`[Antigravity] Build Timestamp: ${new Date().toLocaleString()}`);
import { DashboardState } from './modules/poll'
import { renderAlerts, renderReportDetail, renderLiveFeed, renderMap, resetMapEngine, renderNavigation, updateNavActiveState, renderMarketPulse, renderProInsights as renderPro, renderExpertIntel as renderExpert, renderFreeAlertFeed, renderProMap, renderTopicFilterBar } from './modules/render/index'
import { normalizeTopicCode, type StrategicTopicCode } from './modules/topics'
import { formatIntelTime } from './modules/render/utils'
// (Pro reports now handled within Pro Insights hub)
import { login, signup, fetchMe, logout, fetchReports, fetchReport, fetchFreeAlerts, confirmCheckoutSession, completeStripeSignup, CONTEXT_BRIEFS_DISPLAY_LIMIT, getResolvedApiBase, initApiBase } from './modules/api'
import type { UserMe } from './modules/api'
import {
    renderGracePeriodBanner,
    renderSubscriptionTab,
} from './modules/subscription'
import { bindMobileSidebarControls, closeMobileSidebar } from './modules/mobile_nav'



const app = document.querySelector<HTMLDivElement>('#app')!

let dashboardInitGeneration = 0

function isAuthenticatedUser(user: UserMe | null): boolean {
    if (!user || user.id === 'free-access') return false
    if (user.id === 'dev-override') return true
    return Boolean(user.email?.trim())
}

function dashboardBasePath(): string {
    const path = window.location.pathname.split('?')[0] || '/app.html'
    if (path === '/' || path.endsWith('/index.html')) return 'app.html'
    return path
}

function setFeedHash(): void {
    history.replaceState({ tab: 'feed' }, '', `${dashboardBasePath()}#feed`)
}

function dismissLoginUI(): void {
    app.classList.remove('login-page')
    document.getElementById('login-overlay')?.remove()
    if (!document.querySelector('.app-container') && app.querySelector('.login-container, .login-card')) {
        app.innerHTML = ''
    }
}

function isLoginScreenVisible(): boolean {
    return (
        app.classList.contains('login-page')
        || Boolean(app.querySelector('.login-container, .login-card, #login-overlay'))
    )
}

async function resumeDashboardAfterAuth(): Promise<void> {
    dismissLoginUI()
    await initDashboard()
}

async function openLoginOrFeed(): Promise<void> {
    if (localStorage.getItem('access_token')) {
        try {
            const me = await fetchMe()
            if (me && isAuthenticatedUser(me)) {
                dismissLoginUI()
                if (!parseHashRoute(me.tier)) setFeedHash()
                await initDashboard()
                return
            }
        } catch {
            /* fall through to login form */
        }
    }
    await renderLogin()
}

function bindGlobalAppHandlers(): void {
    const appEl = app as HTMLDivElement & { __authHandlersBound?: boolean }
    if (appEl.__authHandlersBound) return
    appEl.__authHandlersBound = true

    app.addEventListener('click', (e) => {
        const target = e.target as HTMLElement
        if (target.id === 'sidebar-login-btn') {
            void openLoginOrFeed()
        }
        if (target.id === 'sidebar-logout-btn') {
            if (confirm('Sign out?')) {
                logout().then(() => {
                    localStorage.removeItem('access_token')
                    window.location.href = '/app.html#feed'
                    window.location.reload()
                })
            }
        }
    })
}

bindGlobalAppHandlers()
bindHashRouteSync()

export async function renderLogin(message?: string, initialEmail?: string) {
    (window as any).stopPolling?.();

    if (localStorage.getItem('access_token')) {
        try {
            const me = await fetchMe()
            if (isAuthenticatedUser(me)) {
                await resumeDashboardAfterAuth()
                return
            }
        } catch {
            /* show login form */
        }
    }

    app.className = 'login-page'
    app.innerHTML = `
    <div class="login-container">
        <div class="login-card">
            <h1>VELTRIXIA LABS</h1>
            <p class="login-subtitle">Sign in with your email</p>
            ${message ? `<div id="login-message" style="color: #3fb950; margin-bottom: 1rem; font-size: 0.9rem;">${message}</div>` : ''}
            <input type="email" id="login-email" placeholder="Email Address" required value="${initialEmail || ''}" />
            <input type="password" id="password" placeholder="Password" required />
            <button type="button" id="login-btn" class="login-primary-btn">Log In</button>
            <div id="login-error" style="color: #ff7b72; margin-top: 1rem; font-size: 0.9rem;"></div>
            <div style="margin-top: 1.5rem; font-size: 0.85rem; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 1rem;">
                <span style="opacity: 0.6;">New analyst?</span>
                <a href="#" id="go-signup" class="login-link">Sign Up</a>
            </div>
        </div>
    </div>
    `
    const loginBtn = document.querySelector('#login-btn')!
    const signupLink = document.querySelector('#go-signup')!
    signupLink.addEventListener('click', (e) => { e.preventDefault(); renderSignup(); });
    const submitLogin = async () => {
        const email = (document.querySelector('#login-email') as HTMLInputElement).value;
        const pwd = (document.querySelector('#password') as HTMLInputElement).value;
        const errorDiv = document.querySelector('#login-error') as HTMLElement;
        errorDiv.textContent = '';
        loginBtn.setAttribute('disabled', 'true');
        try {
            await login(email, pwd);
            dashboardInitGeneration += 1
            setFeedHash()
            await resumeDashboardAfterAuth();
        } catch {
            errorDiv.textContent = 'Invalid email or password.';
        } finally {
            loginBtn.removeAttribute('disabled');
        }
    };
    loginBtn.addEventListener('click', submitLogin);
    document.querySelector('#password')?.addEventListener('keydown', (e) => {
        if ((e as KeyboardEvent).key === 'Enter') submitLogin();
    });
}

export async function renderSignup() {
    app.className = 'login-page'
    app.innerHTML = `
    <div class="login-container">
        <div class="login-card">
            <h1>Sign Up</h1>
            <p class="login-subtitle">Create an analyst account</p>
            <label class="login-field">
                <span class="login-label">Email</span>
                <input type="email" id="signup-email" autocomplete="email" placeholder="you@company.com" required />
            </label>
            <label class="login-field">
                <span class="login-label">Password</span>
                <input type="password" id="signup-password" autocomplete="new-password" placeholder="At least 8 characters" required minlength="8" />
            </label>
            <button type="button" id="signup-btn" class="login-primary-btn">Create Account</button>
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
        const email = (document.querySelector('#signup-email') as HTMLInputElement).value;
        const pwd = (document.querySelector('#signup-password') as HTMLInputElement).value;
        const errorDiv = document.querySelector('#signup-error') as HTMLElement;
        errorDiv.textContent = '';
        signupBtn.setAttribute('disabled', 'true');
        try {
            await signup(email, pwd);
            renderLogin('Account created. Please sign in.', email);
        } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : '';
            errorDiv.textContent = msg.includes('8') ? 'Password must be at least 8 characters.' : 'Registration failed. Email may already be in use.';
        } finally {
            signupBtn.removeAttribute('disabled');
        }
    });
}

type TabId = 'feed' | 'briefs' | 'plans' | 'reports' | 'map' | 'legal' | 'market-pulse' | 'pro-insights' | 'pro-map' | 'expert-intel'

const BOOT_TABS: TabId[] = ['feed', 'briefs', 'map', 'plans', 'legal', 'market-pulse', 'pro-insights', 'pro-map', 'expert-intel']

/** Legacy hash aliases (e.g. bookmarks, old LP links). */
const HASH_TAB_ALIASES: Record<string, TabId> = {
    'free-feed': 'briefs',
}

type HashRoute = { tab: TabId; alertId?: string }

type TabSwitchFn = (tab: TabId, focusAlertId?: string, skipPushState?: boolean) => void

function normalizeHashTab(raw: string, tier?: string): TabId | null {
    const resolved = (HASH_TAB_ALIASES[raw] ?? raw) as TabId
    let tab = resolved
    if (tab === 'reports') {
        if (tier && ['pro', 'experts', 'enterprise'].includes(tier)) return 'market-pulse'
        return 'briefs'
    }
    return BOOT_TABS.includes(tab) ? tab : null
}

function parseHashRoute(tier?: string): HashRoute | null {
    const hash = window.location.hash.slice(1)
    if (!hash) return null
    const [base, query] = hash.split('?')
    const tab = normalizeHashTab(base, tier)
    if (!tab) return null
    const alertId = new URLSearchParams(query || '').get('alert')
    return { tab, alertId: alertId || undefined }
}

let hashRouteSyncBound = false
let routeSyncInFlight: Promise<void> | null = null

async function syncRouteFromHash(): Promise<void> {
    if (routeSyncInFlight) return routeSyncInFlight

    routeSyncInFlight = (async () => {
        const onLogin = isLoginScreenVisible()
        const dashboardReady = Boolean(document.querySelector('.app-container'))
        const switchTab = (window as Window & { __dashboardHandleTabSwitch?: TabSwitchFn })
            .__dashboardHandleTabSwitch

        if (onLogin) {
            dismissLoginUI()
            await initDashboard()
            return
        }

        if (dashboardReady && typeof switchTab === 'function') {
            let tier: string | undefined
            try {
                const me = await fetchMe()
                tier = me?.tier
            } catch {
                tier = undefined
            }
            const route = parseHashRoute(tier)
            if (!route) return

            const rawBase = window.location.hash.slice(1).split('?')[0]
            if (rawBase === 'reports' || rawBase === 'free-feed') {
                history.replaceState(null, '', `#${route.tab}`)
            }
            switchTab(route.tab, route.alertId, true)
            return
        }

        if (!dashboardReady) {
            await initDashboard()
        }
    })().finally(() => {
        routeSyncInFlight = null
    })

    return routeSyncInFlight
}

function bindHashRouteSync(): void {
    if (hashRouteSyncBound) return
    hashRouteSyncBound = true
    window.addEventListener('hashchange', () => {
        void syncRouteFromHash()
    })
    window.addEventListener('popstate', () => {
        void syncRouteFromHash()
    })
}

type PageHeaderMeta = {
    icon?: string
    title: string
    subtitle?: string
    proCta?: { label: string; href: string }
    showExpertUpsell?: boolean
}

const PAGE_HEADER_META: Partial<Record<TabId, PageHeaderMeta>> = {
    feed: {
        icon: '📡',
        title: 'Alert Stream',
        subtitle: 'Real-time intelligence signals — high-frequency monitoring of global volatility.',
    },
    briefs: {
        icon: '🛰',
        title: 'Context Briefs',
        subtitle: 'Strategic intelligence synthesis — bridging global news signals with high-fidelity structural analysis.',
        proCta: {
            label: 'Unlock Pro / Expert for institutional-grade analytics & deep-sector intelligence',
            href: '/subscription',
        },
    },
    map: {
        icon: '🌐',
        title: 'Global Map',
        subtitle: 'Strategic entity mapping — visualizing structural relationships and geopolitical actors.',
        proCta: {
            label: 'Unlock Pro / Expert for real-time motion and live entity tracking',
            href: '/subscription',
        },
    },
    'pro-map': { title: 'Pro Interactive Map' },
    'market-pulse': {
        icon: '📈',
        title: 'Market Pulse',
        subtitle:
            'Real-time quantitative domain pressure, sector distribution indices, and historical risk trend lines for tactical monitoring.',
    },
    'pro-insights': {
        icon: '💎',
        title: 'Pro Insight',
        subtitle:
            'In-depth structural intelligence briefs — qualitative transmission analysis, exposure matrices, and domain-filtered long-form reports.',
        showExpertUpsell: true,
    },
    'expert-intel': { title: 'Expert Intelligence' },
    plans: { title: 'Plans & Access' },
    reports: { title: 'Reports' },
    legal: { title: 'Legal' },
}

function isLocalDevHost(): boolean {
    const host = window.location.hostname;
    return host === 'localhost' || host === '127.0.0.1';
}

const DEV_TIER_SESSION_KEY = 'vel_dev_tier_override';

/** Pro/Expert tier from VITE_DEV_TIER and optional session override (localhost only). */
function getConfiguredDevTier(): string | undefined {
    const fromEnv = (import.meta.env.VITE_DEV_TIER as string | undefined)?.toLowerCase()?.trim();
    const fromSession = sessionStorage.getItem(DEV_TIER_SESSION_KEY)?.toLowerCase()?.trim();
    const tier = fromSession || fromEnv;
    if (!tier || tier === 'free') return undefined;
    return tier;
}

function shouldApplyDevOverride(hasToken: boolean, user: UserMe | null): boolean {
    const devTier = getConfiguredDevTier();
    // Use MODE (not DEV): `vite build` sets DEV=false even for --mode development.
    if (import.meta.env.MODE !== 'development' || !isLocalDevHost() || !devTier) return false;
    if (!hasToken) return true;
    if (!user) return true;
    if (user.id === 'dev-override') return true;
    if (user.tier === 'free' || user.id === 'free-access') return true;
    return false;
}

function buildAnonymousUser(): UserMe {
    return {
        id: 'free-access',
        email: '',
        chat_id: '',
        role: 'anonymous',
        tier: 'free',
        expires_at: null,
        features: {
            pro_insights: false,
            expert_intelligence: false,
            team_admin: false,
            custom_topics: false,
            onboarding: false,
            support: false,
        },
        limits: {
            impact_depth: 0,
            topics: [],
            reports: [],
        },
    };
}

function buildDevOverrideUser(tier: string): UserMe {
    const isPro = tier === 'pro' || tier === 'experts' || tier === 'enterprise';
    const isExperts = tier === 'experts' || tier === 'enterprise';
    return {
        id: 'dev-override',
        email: 'Local Dev Override',
        chat_id: '',
        role: 'dev',
        tier,
        expires_at: null,
        features: {
            pro_insights: isPro,
            expert_intelligence: isExperts,
            team_admin: tier === 'enterprise',
            custom_topics: tier === 'enterprise',
            onboarding: tier === 'enterprise',
            support: tier === 'enterprise',
        },
        limits: {
            impact_depth: isExperts ? 999 : isPro ? 2 : 0,
            topics: [],
            reports: [],
        },
    };
}

async function handlePaymentReturn(): Promise<UserMe | null> {
    const params = new URLSearchParams(window.location.search);
    if (params.get('payment') !== 'success') return null;

    const sessionId = params.get('session_id');
    if (sessionId && localStorage.getItem('access_token')) {
        try {
            await confirmCheckoutSession(sessionId);
        } catch {
            /* webhook may already have applied tier */
        }
    } else if (sessionId && !localStorage.getItem('access_token')) {
        const password = window.prompt(
            'Payment successful. Create a password for your new account (min 8 characters):'
        );
        if (password && password.length >= 8) {
            try {
                const result = await completeStripeSignup(sessionId, password);
                if (result.access_token) {
                    localStorage.setItem('access_token', result.access_token);
                }
            } catch {
                alert('Account created. Please use Sign In with your email and the password you chose.');
            }
        }
    }

    const hash = window.location.hash || '#plans';
    const pathOnly = window.location.pathname.split('?')[0] || '/dashboard';
    window.history.replaceState({}, '', `${pathOnly}${hash}`);
    return fetchMe();
}

async function initDashboard() {
    const generation = ++dashboardInitGeneration
    await initApiBase();
    console.log(`[Antigravity] Resolved API base (after probe): ${getResolvedApiBase()}`);

    let user: UserMe | null = null;
    const hasToken = Boolean(localStorage.getItem('access_token'));

    try {
        user = await fetchMe();
    } catch {
        user = null;
    }

    if (user) {
        const refreshed = await handlePaymentReturn();
        if (refreshed) user = refreshed;
    } else {
        const refreshed = await handlePaymentReturn();
        if (refreshed) user = refreshed;
    }

    if (shouldApplyDevOverride(hasToken, user)) {
        user = buildDevOverrideUser(getConfiguredDevTier()!);
        console.log(`[Antigravity] Dev override active: tier=${user.tier} (id=${user.id})`);
    } else if (!user) {
        user = buildAnonymousUser();
    }

    if (generation !== dashboardInitGeneration) return

    if (user) app.classList.remove('login-page');

    let currentTab: TabId = 'feed';

    const renderBaseUI = () => {
        resetMapEngine()
        const graceBanner = user ? renderGracePeriodBanner(user) : '';
        app.innerHTML = `
      <header class="mobile-header">
        <span class="mobile-header-brand">VELTRIXIA LABS</span>
        <button class="hamburger" id="mobile-menu-btn" type="button" aria-label="Open menu" aria-expanded="false" aria-controls="sidebar">&#9776;</button>
      </header>
      <div class="mobile-overlay" id="mobile-overlay" aria-hidden="true"></div>
      <div class="app-container dashboard-terminal">
        <aside class="sidebar" id="sidebar">
          <div class="sidebar-header u-flex"><h2>VELTRIXIA LABS</h2></div>
          <div id="sidebar-nav-container" style="display:flex; flex-direction:column; flex:1;"></div>
        </aside>
        <main class="main-content">
          ${graceBanner ? `<div id="grace-header">${graceBanner}</div>` : ''}
          <div class="header-row">
            <div class="page-header-block">
              <h1 id="main-title" class="page-title">
                <span id="page-title-icon" class="page-title-icon" aria-hidden="true" hidden></span>
                <span id="page-title-text">Analyst Intelligence</span>
              </h1>
              <div id="page-subtitle-wrap" class="page-subtitle-wrap" hidden>
                <p id="page-subtitle" class="page-subtitle"></p>
                <p id="page-expert-upsell-lead" class="page-expert-upsell-lead" hidden>
                  Unlock Advanced LLM Analytics &amp; Risk Forecasting — Elevate your tactical edge with deep intelligence modeling, trend projections, and full predictive simulations.
                </p>
                <button type="button" id="page-expert-upsell-link" class="page-premium-cta page-premium-cta--expert" hidden>
                  Upgrade to Expert<span class="page-premium-cta-arrow" aria-hidden="true">→</span>
                </button>
                <a id="page-pro-cta" class="page-premium-cta" href="/subscription" hidden></a>
              </div>
            </div>
          </div>
          <div class="main-feed" id="alerts-container">
            <div id="pulse-bar" class="pulse-bar"></div>
            <div id="topic-filter-bar" class="topic-filter-bar"></div>
            <div id="alerts-list"></div>
          </div>
          <div id="map-page-container" style="display:none;"></div>
          <div id="pro-map-container" style="display:none;"></div>
        </main>
      </div>
      <footer class="mobile-status-bar" aria-live="polite">
        <div id="mobile-sync-hud" class="nav-sync-hud">
          <span class="sync-dot sync-dot--init"></span>
          <span class="sync-label">SYNC: INITIALIZING...</span>
          <span class="sync-time"></span>
        </div>
      </footer>
      `;
        bindMobileSidebarControls();
    };

    if (generation !== dashboardInitGeneration) return

    renderBaseUI();
    const alertsContainer = document.querySelector<HTMLElement>('#alerts-list')!
    const pulseBar = document.querySelector<HTMLElement>('#pulse-bar')!
    const topicFilterBar = document.querySelector<HTMLElement>('#topic-filter-bar')!
    const pageSubtitleWrap = document.querySelector<HTMLElement>('#page-subtitle-wrap')
    const pageSubtitle = document.querySelector<HTMLElement>('#page-subtitle')
    const pageProCta = document.querySelector<HTMLAnchorElement>('#page-pro-cta')
    const pageExpertUpsellLead = document.querySelector<HTMLElement>('#page-expert-upsell-lead')
    const pageExpertUpsellLink = document.querySelector<HTMLButtonElement>('#page-expert-upsell-link')

    const pageTitleIcon = document.querySelector<HTMLElement>('#page-title-icon')
    const pageTitleText = document.querySelector<HTMLElement>('#page-title-text')

    const isProOrAbove = (tier?: string) =>
        tier === 'pro' || tier === 'experts' || tier === 'enterprise'

    const applyPageHeader = (tab: TabId) => {
        const meta = PAGE_HEADER_META[tab]
        if (pageTitleText) {
            pageTitleText.textContent = meta?.title ?? 'Analyst Intelligence'
        }
        if (pageTitleIcon) {
            if (meta?.icon) {
                pageTitleIcon.textContent = meta.icon
                pageTitleIcon.hidden = false
            } else {
                pageTitleIcon.textContent = ''
                pageTitleIcon.hidden = true
            }
        }

        const showSubtitle = Boolean(meta?.subtitle)
        const showProCta = Boolean(
            meta?.proCta
            && (tab === 'map' || tab === 'briefs')
            && !isProOrAbove(user?.tier)
        )
        const showExpertUpsell = Boolean(meta?.showExpertUpsell && tab === 'pro-insights')

        if (pageSubtitle) {
            pageSubtitle.textContent = showSubtitle ? meta!.subtitle! : ''
        }
        if (pageExpertUpsellLead) {
            pageExpertUpsellLead.hidden = !showExpertUpsell
        }
        if (pageExpertUpsellLink) {
            pageExpertUpsellLink.hidden = !showExpertUpsell
        }
        if (pageProCta) {
            if (showProCta && meta?.proCta) {
                pageProCta.href = meta.proCta.href
                pageProCta.innerHTML =
                    `${meta.proCta.label}<span class="page-premium-cta-arrow" aria-hidden="true">→</span>`
                pageProCta.hidden = false
            } else {
                pageProCta.innerHTML = ''
                pageProCta.hidden = true
            }
        }
        if (pageSubtitleWrap) {
            pageSubtitleWrap.hidden = !(showSubtitle || showProCta || showExpertUpsell)
        }
    }

    // [v42] Connectivity Sync Listener: Restores real-time HUD status updates
    window.addEventListener('api-sync-status' as any, (e: CustomEvent) => {
        const { status } = e.detail;
        document.querySelectorAll('#sync-hud, #mobile-sync-hud').forEach((hud) => {
            const dot = hud.querySelector('.sync-dot');
            const label = hud.querySelector('.sync-label');
            const time = hud.querySelector('.sync-time');

            if (dot) {
                dot.classList.remove('sync-dot--init', 'sync-dot--stable', 'sync-dot--retrying', 'sync-dot--offline');
                dot.classList.add(`sync-dot--${status}`);
            }
            if (label) {
                label.textContent = `SYNC: ${status.toUpperCase()}`;
            }
            if (time) {
                time.textContent = formatIntelTime(new Date(), { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            }
        });
    });

    renderNavigation(user, document.querySelector('#sidebar-nav-container')!, (tabId) => handleTabSwitch(tabId as TabId));

    const routeToExpertPricing = () => {
        sessionStorage.setItem('plansFocusTier', 'experts');
        sessionStorage.setItem(
            'plansContextBriefUpsell',
            JSON.stringify({
                message:
                    'Expert tier unlocks LLM predictive vectoring, cross-border scenario modeling, and elevated alert intensity protocols.',
                ts: Date.now(),
            }),
        );
        document.querySelector<HTMLElement>('.main-content')?.scrollTo({ top: 0, behavior: 'smooth' });
        handleTabSwitch('plans');
    };

    const handleTabSwitch = (tab: TabId, focusAlertId?: string, skipPushState = false) => {
        closeMobileSidebar();
        currentTab = tab;
        updateNavActiveState('sidebar-nav-container', tab);
        if (!skipPushState) {
            const newHash = `#${tab}${focusAlertId ? `?alert=${focusAlertId}` : ''}`;
            if (window.location.hash !== newHash) history.pushState({ tab, focusAlertId }, '', newHash);
        }

        const mainContent = document.querySelector<HTMLElement>('.main-content');
        const feedContainer = document.querySelector<HTMLElement>('#alerts-container');
        const mapContainer = document.querySelector<HTMLElement>('#map-page-container');
        const proMapContainer = document.querySelector<HTMLElement>('#pro-map-container');
        applyPageHeader(tab);
        mainContent?.classList.toggle('main-content--global-map', tab === 'map');

        const pulseBarEl = document.querySelector<HTMLElement>('#pulse-bar');
        if (pulseBarEl) {
            if (tab === 'feed') {
                pulseBarEl.style.display = 'block';
            } else {
                pulseBarEl.style.display = 'none';
                pulseBarEl.innerHTML = '';
            }
        }
        if (topicFilterBar) {
            topicFilterBar.style.display = tab === 'feed' || tab === 'briefs' ? 'flex' : 'none';
        }

        // Stop any active DashboardState polling to prevent background /api/alerts requests
        (window as any).stopPolling?.();

        if (mainContent) mainContent.style.opacity = '0';
        setTimeout(() => {
            const isFeedLike = ['feed', 'briefs', 'plans', 'reports', 'legal', 'market-pulse', 'pro-insights', 'expert-intel'].includes(tab);
            if (feedContainer) feedContainer.style.display = isFeedLike ? 'block' : 'none';
            if (mapContainer) mapContainer.style.display = (tab === 'map') ? 'block' : 'none';
            if (proMapContainer) proMapContainer.style.display = (tab === 'pro-map') ? 'flex' : 'none';

            if (tab === 'feed') renderIntelligenceFeed();
            else if (tab === 'briefs') renderFreeFeed();
            else if (tab === 'plans') renderSubscriptionTab(user!, alertsContainer, () => handleTabSwitch('plans'));
            else if (tab === 'reports') renderReports();
            else if (tab === 'map') {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        void renderMap(mapContainer!, user!.tier, focusAlertId);
                    });
                });
            }
            else if (tab === 'market-pulse') renderMarketPulse(alertsContainer, user!, () => handleTabSwitch('plans'));
            else if (tab === 'pro-insights') renderPro(alertsContainer, user!, () => handleTabSwitch('plans'));
            else if (tab === 'pro-map') renderProMap();
            else if (tab === 'expert-intel') {
                const isExpertPlus =
                    user!.tier === 'experts' || user!.tier === 'enterprise'
                if (!isExpertPlus) {
                    routeToExpertPricing()
                } else {
                    renderExpert(alertsContainer, user!, () => handleTabSwitch('plans'))
                }
            }

            if (mainContent) mainContent.style.opacity = '1';
        }, 50);
    };

    pageProCta?.addEventListener('click', (e) => {
        e.preventDefault();
        history.pushState({ tab: 'plans' }, '', '/subscription');
        document.querySelector<HTMLElement>('.main-content')?.scrollTo({ top: 0, behavior: 'smooth' });
        handleTabSwitch('plans', undefined, true);
    });

    ;(window as Window & { __dashboardHandleTabSwitch?: TabSwitchFn }).__dashboardHandleTabSwitch =
        handleTabSwitch;

    pageExpertUpsellLink?.addEventListener('click', (e) => {
        e.preventDefault()
        routeToExpertPricing()
    })

    window.addEventListener('view-report', (e: any) => {
        renderSingleReport(e.detail.reportId, currentTab);
    });

    const renderIntelligenceFeed = async () => {
        const state = new DashboardState(user!.tier);
        let activeTopicFilter: StrategicTopicCode | null = null;

        const bindTopicFilterBar = () => {
            renderTopicFilterBar(topicFilterBar, activeTopicFilter, (topic) => {
                activeTopicFilter = topic;
                state.setTopic(topic);
                bindTopicFilterBar();
            });
        };
        bindTopicFilterBar();

        state.subscribe((data) => {
            if (currentTab !== 'feed') return;

            // [v12.0] Feed Error Separation Logic — keep last good data during retries / rate limits
            const showFeedOffline =
                data.error &&
                data.lastStatus !== 429 &&
                (data.lastStatus === 401 ||
                    data.lastStatus === 403 ||
                    (data.consecutiveFailures >= 3 && data.lastStatus >= 500));

            if (showFeedOffline && data.alerts.length === 0) {
                alertsContainer.innerHTML = `
                    <div class="u-p-2 u-text-center" style="border: 1px solid rgba(255,123,114,0.2); border-radius: 8px; background: rgba(255,123,114,0.05); margin-top: 2rem;">
                        <div style="font-size: 1.5rem; margin-bottom: 0.5rem;" aria-hidden="true">&#9888;</div>
                        <div style="color: #ff7b72; font-weight: 600;">${data.lastStatus === 401 || data.lastStatus === 403 ? 'Intelligence Access Restricted' : 'Strategic Pipeline Offline'}</div>
                        <div style="font-size: var(--font-xs); color: #8b949e; margin-top: 0.5rem;">
                            ${data.lastStatus === 401 || data.lastStatus === 403 ? 'Your current tier does not have clearance for this signal stream.' : 'The analysis engine is currently unreachable. Reconnecting...'}
                        </div>
                        ${data.lastStatus === 401 || data.lastStatus === 403 ? `<button class="btn-fb u-m-top-1" onclick="window.dispatchEvent(new CustomEvent('trigger-tab', {detail:{tab:'plans'}}))">Upgrade Clearance</button>` : ''}
                    </div>
                `;
                return;
            }

            if (data.alerts) {
                pulseBar.style.display = 'block';
                topicFilterBar.style.display = 'flex';
                const filtered = activeTopicFilter
                    ? data.alerts.filter(a => normalizeTopicCode(a.topic) === activeTopicFilter)
                    : data.alerts;
                renderAlerts(data.alerts, alertsContainer, user!.tier, activeTopicFilter);
                renderLiveFeed(filtered, pulseBar);
            }
        });
        (window as any).stopPolling = () => state.stopPolling();
        state.startPolling();
    };

    let contextBriefsItems: Awaited<ReturnType<typeof fetchFreeAlerts>> = [];
    let contextBriefsTopicFilter: StrategicTopicCode | null = null;

    const renderContextBriefsView = () => {
        renderFreeAlertFeed(
            contextBriefsItems,
            alertsContainer,
            user?.tier ?? 'free',
            contextBriefsTopicFilter,
            contextBriefsItems.length,
        );
    };

    const bindContextBriefsFilterBar = () => {
        renderTopicFilterBar(topicFilterBar, contextBriefsTopicFilter, (topic) => {
            contextBriefsTopicFilter = topic;
            bindContextBriefsFilterBar();
            renderContextBriefsView();
        });
    };

    const renderFreeFeed = async () => {
        topicFilterBar.style.display = 'flex';
        alertsContainer.innerHTML = '<div class="u-p-2 u-text-center" style="opacity:0.5;">Loading Context Briefs...</div>';
        try {
            const items = await fetchFreeAlerts({ limit: CONTEXT_BRIEFS_DISPLAY_LIMIT });
            if (!Array.isArray(items)) {
                throw new Error('Unexpected server response (not a list).');
            }
            contextBriefsItems = items;
            bindContextBriefsFilterBar();
            renderContextBriefsView();
        } catch (err: any) {
            const msg = err?.message || 'Connection error';
            alertsContainer.innerHTML = `
                <div class="empty-state u-p-2 u-text-center" style="border: 1px solid rgba(255,123,114,0.2); border-radius: 12px; margin-top: 2rem; max-width: 520px; margin-left: auto; margin-right: auto;">
                    <div class="empty-icon" aria-hidden="true">&#9888;</div>
                    <div class="empty-title" style="color: #ff7b72;">Could not load Context Briefs</div>
                    <div class="empty-subtitle" style="margin-top: 0.5rem;">${msg}</div>
                    <div class="empty-subtitle" style="margin-top: 0.75rem; font-size: 0.8rem; color: #8b949e;">
                        If this persists, confirm the API is reachable at <code style="color:#58a6ff;">${getResolvedApiBase()}</code>
                        and that the database has AlertLog rows with <code>free_alert</code> payloads (see <code>scripts/check_dashboard_data.py</code>).
                    </div>
                </div>`;
        }
    };

    const renderReports = async () => {
        alertsContainer.innerHTML = '<div class="u-p-2 u-text-center" style="opacity:0.5;">Loading reports...</div>';
        try {
            const reports = await fetchReports();
            if (reports.length === 0) {
                alertsContainer.innerHTML = `
                    <div class="u-p-2 u-text-center" style="opacity:0.5; border: 1px dashed var(--border); border-radius: 8px; margin-top: 2rem;">
                        <div style="font-size: 1.5rem; margin-bottom: 0.5rem;" aria-hidden="true">&#9888;</div>
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

    // (renderStructuralBriefs removed from top-level routing, now handled inside Pro Insights)

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

    const initialRoute = parseHashRoute(user?.tier);
    const onSubscriptionPath = /\/subscription\/?$/.test(window.location.pathname);

    if (generation !== dashboardInitGeneration) return

    if (onSubscriptionPath) {
        history.replaceState({ tab: 'plans' }, '', '/subscription');
        handleTabSwitch('plans', undefined, true);
    } else if (initialRoute) {
        const rawBase = window.location.hash.slice(1).split('?')[0];
        if (rawBase === 'reports' || rawBase === 'free-feed') {
            history.replaceState(null, '', `#${initialRoute.tab}`);
        }
        handleTabSwitch(initialRoute.tab, initialRoute.alertId, true);
    } else {
        handleTabSwitch('feed');
    }
}

// Global Core
const startHeartbeat = () => {
    setInterval(async () => { try { await fetchMe(); } catch (e) { } }, 5 * 60 * 1000);
};

function bootstrapApp(): void {
    void syncRouteFromHash().then(() => {
        startHeartbeat();
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapApp);
} else {
    bootstrapApp();
}

window.addEventListener('trigger-login', () => {
    void openLoginOrFeed();
});
