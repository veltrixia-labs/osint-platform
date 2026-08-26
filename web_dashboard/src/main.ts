import './theme.css'
import './style.css'
import './theme-terminal.css'
import './mobile-responsive.css'
declare const __APP_BUILD_INFO__: string;
console.log(`[Antigravity] Resolved API base: ${getResolvedApiBase()} (VITE_API_BASE_URL=${String(import.meta.env.VITE_API_BASE_URL ?? '')})`);
console.log(`[Antigravity] Mode: ${import.meta.env.MODE}`);
console.log(`[Antigravity] Build Version: v11.1.2-AURORA-SYNC`);
console.log(`[Antigravity] Deploy Signature: AURORA-SYNC-${Date.now()}`);
console.log(`[Antigravity] Build Timestamp: ${new Date().toLocaleString()}`);
import { DashboardState } from './modules/poll'
import { renderAlerts, renderReportDetail, renderLiveFeed, renderMap, resetMapEngine, renderNavigation, updateNavActiveState, renderMarketPulse, disposeMarketPulseView, disposeProInsightsView, renderProInsights as renderPro, renderExpertIntel as renderExpert, renderProMap, renderImpactRoster, renderTopicFilterBar, renderDomainItems, renderDomainItemsHint, clearDomainItems, renderTrendFlow, disposeTrendFlow, renderPremiumShroud } from './modules/render/index'
import { normalizeTopicCode, STRATEGIC_TOPIC_FILTERS, type StrategicTopicCode } from './modules/topics'
import { formatIntelTime } from './modules/render/utils'
// (Pro reports now handled within Pro Insights hub)
import { login, signup, fetchMe, logout, fetchReports, fetchReport, confirmCheckoutSession, completeStripeSignup, getResolvedApiBase, initApiBase, fetchItems } from './modules/api'
import type { UserMe } from './modules/api'
import {
    AuthRedirectError,
    clearStaleAuthTokens,
    isAuthSessionPending,
    isLoginPath,
    redirectToLogin,
    renderAuthBootScreen,
    resolveAuthSession,
} from './modules/auth_session'
import {
    renderGracePeriodBanner,
    renderSubscriptionTab,
} from './modules/subscription'
import { bindMobileSidebarControls, closeMobileSidebar } from './modules/mobile_nav'
import { initDevModeAudit, DEV_MODE_AUDIT } from './modules/dev_mode'

// Neutralise locked overlays for the audit build (badge retired for clean UI).
initDevModeAudit()



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
            clearStaleAuthTokens()
        } catch {
            clearStaleAuthTokens()
        }
    }
    if (!isLoginPath()) {
        redirectToLogin()
        return
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

    // Close any open guide popover when clicking outside of a guide wrap
    document.addEventListener('click', (e) => {
        const target = e.target as HTMLElement
        if (!target.closest('.intel-section-guide-wrap')) {
            document.querySelectorAll('.intel-section-guide-popover.is-open').forEach((el) => {
                el.classList.remove('is-open')
                el.closest('.intel-section-guide-wrap')?.querySelector('.intel-section-guide')?.setAttribute('aria-expanded', 'false')
            })
        }
    }, { capture: false })
}

let hashRouteSyncBound = false
let routeSyncInFlight: Promise<void> | null = null

bindGlobalAppHandlers()
bindHashRouteSync()

export async function renderLogin(message?: string, initialEmail?: string) {
    (window as any).stopPolling?.();

    const urlMsg = new URLSearchParams(window.location.search).get('msg');
    const displayMessage = message || urlMsg || undefined;

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
            ${displayMessage ? `<div id="login-message" style="color: #ff7b72; margin-bottom: 1rem; font-size: 0.9rem;">${displayMessage}</div>` : ''}
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
            if (isLoginPath()) {
                window.location.replace(`${dashboardBasePath()}#feed`);
                return;
            }
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

type TabId = 'feed' | 'trend-flow' | 'plans' | 'reports' | 'map' | 'legal' | 'market-pulse' | 'pro-insights' | 'pro-map' | 'impact-roster' | 'expert-intel'

const BOOT_TABS: TabId[] = ['feed', 'trend-flow', 'map', 'plans', 'legal', 'market-pulse', 'pro-insights', 'pro-map', 'impact-roster', 'expert-intel']

/** Legacy hash aliases (e.g. bookmarks, old LP links). */
const HASH_TAB_ALIASES: Record<string, TabId> = {
    'free-feed': 'feed',
}

type HashRoute = { tab: TabId; alertId?: string }

type TabSwitchFn = (tab: TabId, focusAlertId?: string, skipPushState?: boolean) => void

const SIDEBAR_COLLAPSE_KEY = 'sidebar-collapsed';

/**
 * Desktop left-rail collapse. Toggles a shell class that closes the grid track (a real reflow,
 * so MapLibre's trackResize observer resizes both map canvases with no manual plumbing). State
 * persists to localStorage and is restored on every shell render, so it survives reload.
 *
 * Orthogonal to the mobile off-canvas drawer (mobile_nav.ts): that is position:fixed + .active
 * and ignores the grid, and the mobile breakpoint neutralises this (flex-column shell, hidden
 * collapse button, force-hidden re-open handle). Escape belongs to the drawer — untouched here.
 */
function bindSidebarCollapse(): void {
    const shell = document.querySelector<HTMLElement>('.app-container');
    const collapseBtn = document.getElementById('sidebar-collapse-btn');
    const reopenBtn = document.getElementById('sidebar-reopen-btn');
    if (!shell || !collapseBtn || !reopenBtn) return;

    const apply = (collapsed: boolean): void => {
        shell.classList.toggle('app-container--nav-collapsed', collapsed);
        collapseBtn.setAttribute('aria-expanded', String(!collapsed));
        reopenBtn.setAttribute('aria-expanded', String(!collapsed));
        (reopenBtn as HTMLButtonElement).hidden = !collapsed;
    };

    // Restore persisted state before this shell is interacted with.
    apply(localStorage.getItem(SIDEBAR_COLLAPSE_KEY) === '1');

    // Guard against double-binding the same shell element (same idiom as mobile_nav.ts).
    if (shell.dataset.collapseBound === 'true') return;
    shell.dataset.collapseBound = 'true';

    const set = (collapsed: boolean): void => {
        apply(collapsed);
        try { localStorage.setItem(SIDEBAR_COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* ignore */ }
    };
    collapseBtn.addEventListener('click', () => set(true));
    reopenBtn.addEventListener('click', () => set(false));
}

function normalizeHashTab(raw: string, tier?: string): TabId | null {
    const resolved = (HASH_TAB_ALIASES[raw] ?? raw) as TabId
    let tab = resolved
    if (tab === 'reports') {
        if (tier && ['pro', 'experts', 'enterprise'].includes(tier)) return 'market-pulse'
        return 'feed'
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
    'trend-flow': {
        icon: '🌊',
        title: 'Monthly Trend Flow',
        subtitle: 'Each month’s high-impact signals, archived by day and sector — browse how global pressure built up.',
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
    'impact-roster': { title: 'Impact Roster' },
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
        // showExpertUpsell dropped 2026-08-26 with the in-app Expert card: the button it
        // revealed (:670) routed to a Plans tab that no longer names the tier. The flag
        // itself is kept on PageHeaderMeta so the header CTA returns when Expert ships.
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

/**
 * Dev tier override — driven EXCLUSIVELY by the triple-tier toggle's
 * sessionStorage key. The legacy `VITE_DEV_TIER` env fallback is intentionally
 * NOT consulted: it was the "zombie" that stomped the toggle (clicking FREE
 * clears the key, but the env value used to drag it back to pro). With the env
 * fallback gone, an empty/`free` key strictly resolves to public guest tier.
 */
function getConfiguredDevTier(): string | undefined {
    const tier = sessionStorage.getItem(DEV_TIER_SESSION_KEY)?.toLowerCase()?.trim();
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

function applyDevOverrideToUser(hasToken: boolean, user: UserMe | null): UserMe {
    if (shouldApplyDevOverride(hasToken, user)) {
        const devUser = buildDevOverrideUser(getConfiguredDevTier()!);
        console.log(`[Antigravity] Dev override active: tier=${devUser.tier} (id=${devUser.id})`);
        return devUser;
    }
    if (!user || !isAuthenticatedUser(user)) {
        return buildAnonymousUser();
    }
    return user;
}

async function initDashboard() {
    const generation = ++dashboardInitGeneration
    const hasToken = Boolean(localStorage.getItem('access_token'));

    if (hasToken) {
        renderAuthBootScreen(app);
    }

    await initApiBase();
    console.log(`[Antigravity] Resolved API base (after probe): ${getResolvedApiBase()}`);

    // ── Non-blocking auth boot ───────────────────────────────────────────────
    // A slow/pending /api/token (or /auth/me) handshake must NEVER brick the open
    // public stream. We kick off session resolution but, for any token-bearing
    // boot, race it against a fast 800ms timeout: if auth doesn't return in time,
    // render the public free view immediately and let the session re-sync silently
    // in the background. A guest (no token) resolves instantly with no wait at all.
    const AUTH_RACE_MS = 800;
    const AUTH_TIMEOUT = Symbol('auth-timeout');
    const authPromise: Promise<UserMe> = resolveAuthSession({
        hasToken,
        applyDevOverride: (me) => applyDevOverrideToUser(hasToken, me),
    }).catch((e) => {
        if (e instanceof AuthRedirectError) throw e;
        console.warn('[Antigravity] Auth init failed; falling back to public free view.', e);
        clearStaleAuthTokens();
        return buildAnonymousUser();
    });

    const scrubAuthQuery = () => {
        try {
            const url = new URL(window.location.href);
            if (url.search) history.replaceState(null, '', url.pathname + url.hash);
        } catch { /* noop */ }
    };

    let user: UserMe;
    try {
        if (!hasToken) {
            // No session → pure public guest. Resolves instantly; never blocks.
            user = await authPromise;
        } else {
            const raced = await Promise.race([
                authPromise,
                new Promise<typeof AUTH_TIMEOUT>((resolve) => setTimeout(() => resolve(AUTH_TIMEOUT), AUTH_RACE_MS)),
            ]);
            if (raced === AUTH_TIMEOUT) {
                console.warn(`[Antigravity] Auth handshake slow (>${AUTH_RACE_MS}ms) — advancing to public stream; session re-syncs in background.`);
                scrubAuthQuery();
                user = buildAnonymousUser();
                // Background re-sync (non-blocking): if the real session eventually
                // resolves to a paid tier, re-init to upgrade the live view.
                void authPromise.then((resolved) => {
                    if (
                        generation === dashboardInitGeneration
                        && resolved && isAuthenticatedUser(resolved)
                        && (resolved.tier === 'pro' || resolved.tier === 'experts' || resolved.tier === 'enterprise')
                    ) {
                        console.log('[Antigravity] Background session re-sync → upgrading to', resolved.tier);
                        void initDashboard();
                    }
                }).catch(() => { /* handled above */ });
            } else {
                user = raced as UserMe;
            }
        }
    } catch (e) {
        if (e instanceof AuthRedirectError) return;
        // Defensive: never freeze the boot on an unexpected auth error.
        clearStaleAuthTokens();
        scrubAuthQuery();
        user = buildAnonymousUser();
    }

    if (generation !== dashboardInitGeneration) return

    const paymentRefresh = await handlePaymentReturn();
    if (paymentRefresh && isAuthenticatedUser(paymentRefresh)) {
        user = applyDevOverrideToUser(hasToken, paymentRefresh);
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
        <button type="button" id="sidebar-reopen-btn" class="sidebar-reopen" aria-label="Expand sidebar" aria-controls="sidebar" aria-expanded="true" hidden>&rsaquo;</button>
        <aside class="sidebar" id="sidebar">
          <div class="sidebar-header u-flex">
            <h2>VELTRIXIA LABS</h2>
            <button type="button" id="sidebar-collapse-btn" class="sidebar-collapse" aria-label="Collapse sidebar" aria-controls="sidebar" aria-expanded="true">&lsaquo;</button>
          </div>
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
            <div id="domain-items-hint"></div>
            <div id="alerts-list"></div>
            <div id="domain-items"></div>
          </div>
          <div id="map-page-container" style="display:none;"></div>
          <div id="pro-map-container" style="display:none;"></div>
          <div id="impact-roster-container" style="display:none;"></div>
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
        bindSidebarCollapse();
    };

    if (generation !== dashboardInitGeneration) return

    renderBaseUI();
    const alertsContainer = document.querySelector<HTMLElement>('#alerts-list')!
    const pulseBar = document.querySelector<HTMLElement>('#pulse-bar')!
    const topicFilterBar = document.querySelector<HTMLElement>('#topic-filter-bar')!
    const domainItemsHost = document.querySelector<HTMLElement>('#domain-items')!
    const domainItemsHint = document.querySelector<HTMLElement>('#domain-items-hint')!
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
            && tab === 'map'
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
        // The upsell banner written here was removed 2026-08-26 along with the in-app
        // Expert card: it named LLM predictive vectoring, cross-border scenario modeling
        // and elevated alert intensity, none of which is implemented, and it would have
        // rendered above a comparison table that no longer has an Expert column.
        sessionStorage.setItem('plansFocusTier', 'experts');
        document.querySelector<HTMLElement>('.main-content')?.scrollTo({ top: 0, behavior: 'smooth' });
        handleTabSwitch('plans');
    };

    const handleTabSwitch = (tab: TabId, focusAlertId?: string, skipPushState = false) => {
        closeMobileSidebar();
        if (tab !== 'market-pulse') {
            disposeMarketPulseView();
            const alertsHost = document.querySelector<HTMLElement>('#alerts-list');
            if (alertsHost) delete alertsHost.dataset.dashboardView;
        }
        if (tab !== 'pro-insights') {
            disposeProInsightsView();
        }
        if (tab !== 'trend-flow') {
            disposeTrendFlow();
        }
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
        const impactRosterContainer = document.querySelector<HTMLElement>('#impact-roster-container');
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
            topicFilterBar.style.display = tab === 'feed' ? 'flex' : 'none';
        }
        const domainItemsEl = document.querySelector<HTMLElement>('#domain-items');
        if (domainItemsEl) {
            domainItemsEl.style.display = tab === 'feed' ? 'block' : 'none';
            if (tab !== 'feed') domainItemsEl.innerHTML = '';
        }
        const domainItemsHintEl = document.querySelector<HTMLElement>('#domain-items-hint');
        if (domainItemsHintEl) {
            domainItemsHintEl.style.display = tab === 'feed' ? 'block' : 'none';
            if (tab !== 'feed') domainItemsHintEl.innerHTML = '';
        }

        // Stop any active DashboardState polling to prevent background /api/alerts requests
        (window as any).stopPolling?.();

        if (mainContent) mainContent.style.opacity = '0';
        setTimeout(() => {
            const isFeedLike = ['feed', 'trend-flow', 'plans', 'reports', 'legal', 'market-pulse', 'pro-insights', 'expert-intel'].includes(tab);
            if (feedContainer) feedContainer.style.display = isFeedLike ? 'block' : 'none';
            if (mapContainer) mapContainer.style.display = (tab === 'map') ? 'block' : 'none';
            if (proMapContainer) proMapContainer.style.display = (tab === 'pro-map') ? 'flex' : 'none';
            if (impactRosterContainer) impactRosterContainer.style.display = (tab === 'impact-roster') ? 'flex' : 'none';

            if (tab === 'feed') renderIntelligenceFeed();
            else if (tab === 'trend-flow') void renderTrendFlow(alertsContainer, user!.tier);
            else if (tab === 'plans') renderSubscriptionTab(user!, alertsContainer, () => handleTabSwitch('plans'));
            else if (tab === 'reports') renderReports();
            else if (tab === 'map') {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        void renderMap(mapContainer!, user!.tier, focusAlertId);
                    });
                });
            }
            else if (tab === 'market-pulse') {
                if (isAuthSessionPending()) return;
                if (!isProOrAbove(user!.tier) && !DEV_MODE_AUDIT) { renderPremiumShroud(alertsContainer, 'market-pulse', user!, () => handleTabSwitch('plans')); if (mainContent) mainContent.style.opacity = '1'; return; }
                renderMarketPulse(alertsContainer, user!, () => handleTabSwitch('plans'));
            }
            else if (tab === 'pro-insights') {
                if (isAuthSessionPending()) return;
                if (!isProOrAbove(user!.tier) && !DEV_MODE_AUDIT) { renderPremiumShroud(alertsContainer, 'pro-insights', user!, () => handleTabSwitch('plans')); if (mainContent) mainContent.style.opacity = '1'; return; }
                renderPro(alertsContainer, user!, () => handleTabSwitch('plans'));
            }
            else if (tab === 'pro-map') {
                if (isAuthSessionPending()) return;
                if (!isProOrAbove(user!.tier) && !DEV_MODE_AUDIT) { renderPremiumShroud(proMapContainer!, 'pro-map', user!, () => handleTabSwitch('plans')); if (mainContent) mainContent.style.opacity = '1'; return; }
                renderProMap();
            }
            else if (tab === 'impact-roster') {
                if (isAuthSessionPending()) return;
                if (!isProOrAbove(user!.tier) && !DEV_MODE_AUDIT) { renderPremiumShroud(impactRosterContainer!, 'impact-roster', user!, () => handleTabSwitch('plans')); if (mainContent) mainContent.style.opacity = '1'; return; }
                renderImpactRoster();
            }
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

        const loadDomainItems = async (topic: StrategicTopicCode | null) => {
            // "All" (null) shows only the curated stream - no comprehensive list.
            if (!topic) { clearDomainItems(domainItemsHost); domainItemsHint.innerHTML = ''; return; }
            const meta = STRATEGIC_TOPIC_FILTERS.find(f => f.code === topic);
            const items = await fetchItems(topic);
            // Guard a race: user may have switched tab/topic mid-fetch.
            if (currentTab !== 'feed' || activeTopicFilter !== topic) return;
            renderDomainItems(domainItemsHost, items, meta?.label ?? 'Sector', meta?.color ?? '#58a6ff');
            // Discoverability: the curated stream above caps to the viewport, so the
            // comprehensive list below sits off-screen. Mount a visible, poll-safe
            // hint chip (outside .chud-root) that smooth-scrolls down on click.
            renderDomainItemsHint(domainItemsHint, items.length, meta?.label ?? 'Sector', meta?.color ?? '#58a6ff', () => {
                domainItemsHost.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
        };

        const bindTopicFilterBar = () => {
            renderTopicFilterBar(topicFilterBar, activeTopicFilter, (topic) => {
                activeTopicFilter = topic;
                state.setTopic(topic);
                bindTopicFilterBar();
                void loadDomainItems(topic);
            });
        };
        bindTopicFilterBar();
        void loadDomainItems(activeTopicFilter);

        state.subscribe((data) => {
            if (currentTab !== 'feed') return;

            // [v12.1] Public-first feed gating. The Alert Stream is 100% PUBLIC,
            // so a free/guest session can NEVER be "access restricted" — that
            // clearance wall is reserved strictly for PAID tiers. A free guest
            // shows, at most, a neutral offline notice during a sustained outage,
            // and otherwise always falls through to render the open public feed.
            const isFreeTier = (user?.tier ?? 'free') === 'free';
            const accessRestricted =
                !isFreeTier && (data.lastStatus === 401 || data.lastStatus === 403);
            const pipelineOffline = data.consecutiveFailures >= 3 && data.lastStatus >= 500;
            const showFeedOffline =
                Boolean(data.error) && data.lastStatus !== 429 && (accessRestricted || pipelineOffline);

            if (showFeedOffline && data.alerts.length === 0) {
                alertsContainer.innerHTML = `
                    <div class="u-p-2 u-text-center" style="border: 1px solid rgba(255,123,114,0.2); border-radius: 8px; background: rgba(255,123,114,0.05); margin-top: 2rem;">
                        <div style="font-size: 1.5rem; margin-bottom: 0.5rem;" aria-hidden="true">&#9888;</div>
                        <div style="color: #ff7b72; font-weight: 600;">${accessRestricted ? 'Intelligence Access Restricted' : 'Strategic Pipeline Offline'}</div>
                        <div style="font-size: var(--font-xs); color: #8b949e; margin-top: 0.5rem;">
                            ${accessRestricted ? 'This stream requires Pro / Expert clearance.' : 'The analysis engine is currently unreachable. Reconnecting...'}
                        </div>
                        ${accessRestricted ? `<button class="btn-fb u-m-top-1" onclick="window.dispatchEvent(new CustomEvent('trigger-tab', {detail:{tab:'plans'}}))">Upgrade Clearance</button>` : ''}
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
    if (isLoginPath()) {
        void (async () => {
            await initApiBase();
            const msg = new URLSearchParams(window.location.search).get('msg');
            await renderLogin(msg || undefined);
        })();
        return;
    }

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
