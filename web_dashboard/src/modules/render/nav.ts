import type { UserMe } from '../api';
import { toggleAdminTier } from '../api';
import { closeMobileSidebar } from '../mobile_nav';

/**
 * [Phase 3] Role-aware Navigation Renderer
 *
 * Renders the full sidebar navigation shell based on the current user's tier.
 * Replaces the static HTML nav block previously in renderBaseUI / main.ts.
 *
 * Tier hierarchy: free < pro < experts
 */

type NavItem = {
    id: string;
    label: string;
    icon: string;
    minTier: 'free' | 'pro' | 'experts';
    group: 'core' | 'premium' | 'account';
};

const NAV_ITEMS: NavItem[] = [
    // Core – available to all
    { id: 'feed',         label: 'Alert Stream',        icon: '📡', minTier: 'free',    group: 'core' },
    { id: 'briefs',       label: 'Context Briefs',       icon: '🛰',  minTier: 'free',    group: 'core' },
    { id: 'map',          label: 'Global Map',           icon: '🌐', minTier: 'free',    group: 'core' },
    // Premium – gated
    { id: 'pro-insights', label: 'Pro Insight',          icon: '💎', minTier: 'pro',     group: 'premium' },
    { id: 'pro-map',      label: 'Pro Interactive Map', icon: 'travel_explore', minTier: 'pro', group: 'premium' },
    { id: 'expert-intel', label: 'Expert Intelligence',  icon: '🔬', minTier: 'experts', group: 'premium' },
    // Account
    { id: 'plans',        label: 'Subscription Plans',   icon: '⭐', minTier: 'free',    group: 'account' },
];

const FREE_LOCKED_TABS = new Set(['pro-insights', 'pro-map']);

const TIER_ORDER = ['free', 'pro', 'experts'];

function tierRank(tier: string): number {
    const idx = TIER_ORDER.indexOf(tier);
    // Any unrecognized tier maps to free (index 0)
    return idx >= 0 ? idx : 0;
}

function canAccess(userTier: string, minTier: string): boolean {
    return tierRank(userTier) >= tierRank(minTier);
}

const TIER_LABELS: Record<string, string> = {
    free:    'Free Access',
    pro:     'Pro',
    experts: 'Expert',
};

const TIER_COLORS: Record<string, string> = {
    free:    '#8b949e',
    pro:     '#58a6ff',
    experts: '#bc8cff',
};

/**
 * Renders the role-aware navigation into a container element.
 * Locks premium items for ineligible tiers and redirects them to Plans.
 *
 * @param user        Current user object
 * @param container   The <aside> or containing element for the nav
 * @param onTabSwitch Callback to switch tabs – receives tab ID string
 * @param activeTab   Currently active tab ID
 */
export function renderNavigation(
    user: UserMe,
    container: HTMLElement,
    onTabSwitch: (tabId: string) => void,
    activeTab: string = 'feed'
): void {
    const tier = user.tier || 'free';
    const isDevOverride = user.id === 'dev-override';
    const isAnonymous = user.id === 'free-access' || (!isDevOverride && !user.email);
    
    // Determine tier display label
    let displayTierLabel = TIER_LABELS[tier] || 'Free Access';
    let displayEmail = user.email;
    
    if (isDevOverride) {
        displayTierLabel = tier === 'pro' ? 'PRO ACCESS' : (TIER_LABELS[tier] || tier.toUpperCase());
        displayEmail = 'Local Dev Override';
    } else if (isAnonymous) {
        displayTierLabel = 'FREE ACCESS';
        displayEmail = 'Free Access';
    }
    
    const tierColor = TIER_COLORS[tier] || '#8b949e';
    const isPaidTier = tier === 'pro' || tier === 'experts' || tier === 'enterprise';
    const canManageSubscription = tier === 'pro' || tier === 'experts' || tier === 'enterprise';

    const setPlansUpsellContext = (message: string) => {
        sessionStorage.setItem(
            'plansContextBriefUpsell',
            JSON.stringify({
                message,
                ts: Date.now(),
            })
        );
    };

    const groups: Record<string, NavItem[]> = { core: [], premium: [], account: [] };
    NAV_ITEMS.forEach(item => groups[item.group].push(item));

    const renderGroup = (title: string, items: NavItem[]): string => {
        const visibleItems = items.filter(item => {
            if (tier === 'free' && FREE_LOCKED_TABS.has(item.id)) return true;
            return canAccess(tier, item.minTier);
        });
        if (visibleItems.length === 0) return '';
        
        return `
            <div class="nav-group">
                <div class="nav-group-label">${title}</div>
                ${visibleItems.map(item => {
                    const isActive = item.id === activeTab;
                    const isLockedForFree = tier === 'free' && FREE_LOCKED_TABS.has(item.id);
                    const accessible = !isLockedForFree && canAccess(tier, item.minTier);
                    return `
                        <div
                            class="sidebar-nav-link ${isActive ? 'sidebar-nav-link--active' : ''} ${isLockedForFree ? 'sidebar-nav-link--premium-gate' : ''}"
                            id="nav-${item.id}"
                            data-tab="${item.id}"
                            data-accessible="${accessible ? 'true' : 'false'}"
                            title="${isLockedForFree ? 'Upgrade to Unlock' : item.label}"
                        >
                            <span class="nav-item-icon ${item.icon.length > 2 ? 'material-icons' : ''}">${item.icon}</span>
                            <span class="nav-item-label">${item.label}</span>
                            ${isLockedForFree ? '<span class="nav-lock-icon" aria-hidden="true">🔒</span>' : ''}
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    };

    // Role-Based Access footer
    const authFooterHtml = isAnonymous
        ? `<button type="button" class="nav-upgrade-btn nav-upgrade-btn--ghost" id="sidebar-login-btn">Sign In</button>`
        : `<button type="button" class="nav-upgrade-btn nav-upgrade-btn--ghost" id="sidebar-logout-btn">Sign Out</button>`;

    const footerCtaHtml = !isPaidTier
        ? `
                <button class="nav-upgrade-btn nav-upgrade-btn--premium" id="upgrade-button">
                    Upgrade to Pro / Expert
                </button>
          `
        : canManageSubscription
            ? `
                <button class="nav-upgrade-btn nav-upgrade-btn--ghost" id="upgrade-button">
                    ${tier === 'pro' ? 'Manage Pro / Expert Access' : 'Account Settings'}
                </button>
              `
            : `
                <div style="font-size: 0.65rem; color: #3fb950; text-align: center; letter-spacing: 0.5px; padding: 4px 0;">
                    ✓ Full Access Active
                </div>
              `;

    const isAdmin = user.is_admin === true || user.role === 'admin';
    const localDevConsoleHtml = isDevOverride
        ? `
            <div class="nav-dev-console">
                <div class="nav-dev-console-label">Local Dev Tier</div>
                <div class="nav-dev-console-actions">
                    <button type="button" class="nav-dev-btn" data-local-dev-tier="experts">Expert UI</button>
                    <button type="button" class="nav-dev-btn" data-local-dev-tier="pro">Pro UI</button>
                    <button type="button" class="nav-dev-btn nav-dev-btn--reset" data-local-dev-tier="">Reset tier</button>
                </div>
                <div class="nav-dev-console-hint">Set LOCAL_DEV_TIER=${tier} in API .env for matching API access.</div>
            </div>
        `
        : '';
    const adminDevConsoleHtml = isAdmin
        ? `
            <div class="nav-dev-console">
                <div class="nav-dev-console-label">Dev Console</div>
                <div class="nav-dev-console-actions">
                    <button type="button" class="nav-dev-btn" data-dev-tier="experts">Switch to Expert</button>
                    <button type="button" class="nav-dev-btn" data-dev-tier="pro">Switch to Pro</button>
                    <button type="button" class="nav-dev-btn nav-dev-btn--reset" data-dev-tier="">Reset to Standard</button>
                </div>
                ${user.manual_tier ? `<div class="nav-dev-console-hint">Override: ${user.manual_tier}</div>` : ''}
            </div>
        `
        : '';
    const devConsoleHtml = localDevConsoleHtml || adminDevConsoleHtml;

    const footerHtml = `
        <div class="nav-role-footer">
            <div id="sync-hud" class="nav-sync-hud">
                <span class="sync-dot sync-dot--init"></span>
                <span class="sync-label">SYNC: INITIALIZING...</span>
                <span class="sync-time"></span>
            </div>
            <div class="nav-role-tier" style="border-left: 3px solid ${tierColor};">
                <div class="nav-role-tier-label" style="color: ${tierColor};">${displayTierLabel.toUpperCase()}</div>
                <div class="nav-role-email" title="${displayEmail}">${displayEmail}</div>
            </div>
            ${devConsoleHtml}
            ${authFooterHtml}
            ${footerCtaHtml}
            <div class="nav-legal-row">
                <a href="#legal">Disclosure</a>
                <a href="#legal">Terms</a>
                <a href="#legal">Privacy</a>
            </div>
        </div>
    `;

    container.innerHTML = `
        <div class="nav-groups">
            ${renderGroup('', groups.core)}
            <hr class="nav-divider" />
            ${renderGroup('', groups.premium)}
            <hr class="nav-divider" />
            ${renderGroup('', groups.account)}
        </div>
        ${footerHtml}
    `;

    // Attach click handlers
    container.querySelectorAll('.sidebar-nav-link').forEach(el => {
        el.addEventListener('click', () => {
            const accessible = (el as HTMLElement).dataset.accessible === 'true';
            const tabId = (el as HTMLElement).dataset.tab!;

            if (!accessible) {
                setPlansUpsellContext('Pro / Expert access is required for this module. Please review the full scope of Pro / Expert capabilities.');
                onTabSwitch('plans');
            } else {
                onTabSwitch(tabId);
            }
            closeMobileSidebar();
        });
    });

    container.querySelectorAll('.nav-legal-row a').forEach((link) => {
        link.addEventListener('click', () => {
            closeMobileSidebar();
        });
    });

    // Footer upgrade button
    container.querySelector('#upgrade-button')?.addEventListener('click', () => {
        setPlansUpsellContext(
            'Explore Founding plans to unlock advanced structural intelligence and predictive foresight.',
        );
        onTabSwitch('plans');
        closeMobileSidebar();
    });

    container.querySelector('#sidebar-login-btn')?.addEventListener('click', () => {
        closeMobileSidebar();
    });

    container.querySelectorAll('[data-local-dev-tier]').forEach(btn => {
        btn.addEventListener('click', () => {
            const tier = (btn as HTMLElement).dataset.localDevTier ?? '';
            if (tier) {
                sessionStorage.setItem('vel_dev_tier_override', tier);
            } else {
                sessionStorage.removeItem('vel_dev_tier_override');
            }
            window.location.reload();
        });
    });

    container.querySelectorAll('.nav-dev-btn[data-dev-tier]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const tier = (btn as HTMLElement).dataset.devTier ?? '';
            const targetTier = tier === '' ? null : tier;
            (btn as HTMLButtonElement).disabled = true;
            try {
                const result = await toggleAdminTier(targetTier);
                if (result.ok) {
                    window.location.reload();
                } else {
                    alert('Failed to update tier override. Ensure you are logged in as admin.');
                }
            } catch {
                alert('Failed to update tier override.');
            } finally {
                (btn as HTMLButtonElement).disabled = false;
            }
        });
    });
}

/**
 * Updates the active state of nav links without full re-render.
 * Call this whenever the active tab changes.
 */
export function updateNavActiveState(containerId: string, activeTab: string): void {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.querySelectorAll('.sidebar-nav-link').forEach(el => {
        const tab = (el as HTMLElement).dataset.tab;
        el.classList.toggle('sidebar-nav-link--active', tab === activeTab);
    });
}
