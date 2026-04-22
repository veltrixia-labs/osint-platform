import type { UserMe } from '../api';

/**
 * [Phase 3] Role-aware Navigation Renderer
 *
 * Renders the full sidebar navigation shell based on the current user's tier.
 * Replaces the static HTML nav block previously in renderBaseUI / main.ts.
 *
 * Tier hierarchy: guest < free < pro < experts
 */

type NavItem = {
    id: string;
    label: string;
    icon: string;
    minTier: 'guest' | 'free' | 'pro' | 'experts';
    group: 'core' | 'premium' | 'account';
};

const NAV_ITEMS: NavItem[] = [
    // Core – available to all
    { id: 'feed',         label: 'Intelligence Feed',   icon: '📡', minTier: 'guest',   group: 'core' },
    { id: 'map',          label: 'Global Map',           icon: '🌐', minTier: 'guest',   group: 'core' },
    { id: 'reports',      label: 'Reports',              icon: '📋', minTier: 'guest',   group: 'core' },
    // Premium – gated
    { id: 'pro-insights', label: 'Pro Insights',         icon: '💎', minTier: 'pro',     group: 'premium' },
    { id: 'expert-intel', label: 'Expert Intelligence',  icon: '🔬', minTier: 'experts', group: 'premium' },
    // Account
    { id: 'plans',        label: 'Subscription Plans',   icon: '⭐', minTier: 'guest',   group: 'account' },
];

const TIER_ORDER = ['guest', 'free', 'pro', 'experts'];

function tierRank(tier: string): number {
    return TIER_ORDER.indexOf(tier) ?? 0;
}

function canAccess(userTier: string, minTier: string): boolean {
    return tierRank(userTier) >= tierRank(minTier);
}

const TIER_LABELS: Record<string, string> = {
    guest:   'Guest Analyst',
    free:    'Free',
    pro:     'Pro',
    experts: 'Expert',
};

const TIER_COLORS: Record<string, string> = {
    guest:   '#8b949e',
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
    const tier = user.tier || 'guest';
    const isGuest = user.id === 'guest';
    const tierLabel = TIER_LABELS[tier] || 'Free';
    const tierColor = TIER_COLORS[tier] || '#8b949e';

    const groups: Record<string, NavItem[]> = { core: [], premium: [], account: [] };
    NAV_ITEMS.forEach(item => groups[item.group].push(item));

    const renderGroup = (title: string, items: NavItem[]): string => `
        <div class="nav-group">
            <div class="nav-group-label">${title}</div>
            ${items.map(item => {
                const accessible = canAccess(tier, item.minTier);
                const isActive = item.id === activeTab;
                const lockHtml = accessible ? '' : `<span class="nav-lock-icon">🔒</span>`;
                const upgradeLabel = item.minTier === 'experts' ? 'Expert' : 'Pro';
                return `
                    <div
                        class="sidebar-nav-link ${isActive ? 'sidebar-nav-link--active' : ''} ${!accessible ? 'sidebar-nav-link--locked' : ''}"
                        id="nav-${item.id}"
                        data-tab="${item.id}"
                        data-accessible="${accessible}"
                        title="${accessible ? item.label : `Upgrade to ${upgradeLabel} to unlock`}"
                    >
                        <span class="nav-item-icon">${item.icon}</span>
                        <span class="nav-item-label">${item.label}</span>
                        ${lockHtml}
                    </div>
                `;
            }).join('')}
        </div>
    `;

    // Role-Based Access footer
    const footerHtml = `
        <div class="nav-role-footer">
            <div id="sync-hud" class="nav-sync-hud">
                <span class="sync-dot sync-dot--init"></span>
                <span class="sync-label">SYNC: INITIALIZING...</span>
                <span class="sync-time"></span>
            </div>
            <div class="nav-role-tier" style="border-left: 3px solid ${tierColor};">
                <div class="nav-role-tier-label" style="color: ${tierColor};">${tierLabel.toUpperCase()}</div>
                <div class="nav-role-email" title="${user.email}">${isGuest ? 'Guest Mode' : user.email}</div>
            </div>
            ${isGuest ? `
                <button class="trigger-login-btn nav-upgrade-btn" style="background: var(--accent);">
                    Enable Full Access
                </button>
            ` : (tier === 'free' || tier === 'pro') ? `
                <button class="nav-upgrade-btn nav-upgrade-btn--ghost" id="nav-footer-upgrade-btn">
                    Upgrade Plan →
                </button>
            ` : `
                <div style="font-size: 0.65rem; color: #3fb950; text-align: center; letter-spacing: 0.5px; padding: 4px 0;">
                    ✓ Full Access Active
                </div>
            `}
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
                // Redirect locked items to plans
                onTabSwitch('plans');
            } else {
                onTabSwitch(tabId);
            }
        });
    });

    // Footer upgrade button
    container.querySelector('#nav-footer-upgrade-btn')?.addEventListener('click', () => {
        onTabSwitch('plans');
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
