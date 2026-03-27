/**
 * subscription.ts
 * Phase 31 - Subscription UI Module
 *
 * Responsibilities:
 * - renderSubscriptionTab: full Plans & Billing page (plan cards + comparison table)
 * - renderTierBadge: inline sidebar tier pill
 * - renderLockedFeature: locked-feature overlay that sends users to Plans & Billing
 * - renderGracePeriodBanner: warning banner rendered in the header
 */

import type { UserMe } from './api';
import { fetchCheckoutSession, cancelSubscription } from './api';
import { ENTITLEMENT_MATRIX } from './topics';

// ──────────────────────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────────────────────

const GRACE_PERIOD_DAYS = 3;

/** Mapping internal tier IDs to user-facing display names */
const PLAN_NAME_MAP: Record<string, string> = {
    free: 'Free',
    pro: 'Pro',
    expert: 'Expert',
    experts: 'Expert',
    enterprise: 'Enterprise',
};

/** "Best For" labels for conversion guidance */
const TIER_BEST_FOR: Record<string, string> = {
    free: 'Basic risk monitoring',
    pro: 'Operational risk intelligence',
    experts: 'Strategic risk intelligence',
    enterprise: 'Organization-scale custom intelligence',
};

interface PlanConfig {
    id: string;
    name: string;
    subtitle: string;
    bestFor: string;
    price: string;
    originalPrice?: string;
    priceNote: string;
    color: string;
    /** true = Stripe Checkout, false = contact-sales redirect */
    directCheckout: boolean;
    contactUrl: string;
    features: string[];
}

const PLANS: PlanConfig[] = [
    {
        id: 'free',
        name: PLAN_NAME_MAP.free,
        subtitle: 'Foundational awareness',
        bestFor: TIER_BEST_FOR.free,
        price: '$0',
        priceNote: 'forever',
        color: '#8b949e',
        directCheckout: false,
        contactUrl: '',
        features: [
            '5 alerts/day',
            'Daily intelligence reports',
            '3 watchlist keywords',
            'Global situational briefing only',
            'Email support',
        ],
    },
    {
        id: 'pro',
        name: PLAN_NAME_MAP.pro,
        subtitle: 'Advanced individual analysis',
        bestFor: TIER_BEST_FOR.pro,
        price: '$19',
        priceNote: 'per month',
        color: '#58a6ff',
        directCheckout: true,  // → Stripe Checkout
        contactUrl: '',
        features: [
            'Entity-level intelligence',
            'Analytical confidence metrics',
            'Full source traceability',
            '100 alerts/day',
            'Daily + Weekly reports',
            'Core specialized topics (Energy/Market/Crypto)',
            '20 watchlist keywords',
        ],
    },
    {
        id: 'experts',
        name: PLAN_NAME_MAP.experts,
        subtitle: 'Strategic foresight & forecasting',
        bestFor: TIER_BEST_FOR.experts,
        price: '$49',
        priceNote: 'per month',
        color: '#3fb950', // Emerald/Green
        directCheckout: true,
        contactUrl: '',
        features: [
            'Monthly full LLM analysis',
            'Scenario analysis (Best/Base/Worst)',
            'Risk forecasting (30–60 days)',
            'Full Specialized Coverage (AI/Defense/Supply)',
            'High self-serve limits',
            'Unlimited alerts',
        ],
    },
    {
        id: 'enterprise',
        name: PLAN_NAME_MAP.enterprise,
        subtitle: 'The full intelligence suite',
        bestFor: TIER_BEST_FOR.enterprise,
        price: 'Custom',
        priceNote: 'contact us',
        color: '#bc8cff',
        directCheckout: false,
        contactUrl: 'mailto:sales@osint-platform.com?subject=Enterprise%20Plan%20Inquiry',
        features: [
            'All Expert features',
            'Custom topic configuration',
            'Team/Organization support',
            'SLA guarantee',
            'Dedicated account manager',
            'Custom intelligence workflows',
        ],
    },
];

/**
 * Feature comparison table rows.
 * Each row: [featureName, free, pro, expert, enterprise]
 */
const FEATURE_COMPARISON: [string, string, string, string, string][] = [
    ['Alerts per day',              '5',         '100',         'Unlimited',   'Unlimited'],
    ['Daily reports',               
        ENTITLEMENT_MATRIX.free.reports.includes('daily') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.pro.reports.includes('daily') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.experts.reports.includes('daily') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.enterprise.reports.includes('daily') ? '✓' : '✗'
    ],
    ['Weekly reports',              
        ENTITLEMENT_MATRIX.free.reports.includes('weekly') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.pro.reports.includes('weekly') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.experts.reports.includes('weekly') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.enterprise.reports.includes('weekly') ? '✓' : '✗'
    ],
    ['Monthly reports',             
        ENTITLEMENT_MATRIX.free.reports.includes('monthly') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.pro.reports.includes('monthly') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.experts.reports.includes('monthly') ? '✓ (Full LLM)' : '✗',
        ENTITLEMENT_MATRIX.enterprise.reports.includes('monthly') ? '✓ (Full LLM)' : '✗'
    ],
    ['Scenario analysis',           '✗',         '✗',           '✓',           '✓'],
    ['Risk forecasting',            '✗',         '✗',           '✓',           '✓'],
    ['Core Specialty Topics',       
        ENTITLEMENT_MATRIX.free.topics.includes('energy_resource_risk') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.pro.topics.includes('energy_resource_risk') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.experts.topics.includes('energy_resource_risk') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.enterprise.topics.includes('energy_resource_risk') ? '✓' : '✗'
    ],
    ['Expert Specialty Topics',     
        ENTITLEMENT_MATRIX.free.topics.includes('ai_semiconductor_intelligence') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.pro.topics.includes('ai_semiconductor_intelligence') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.experts.topics.includes('ai_semiconductor_intelligence') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.enterprise.topics.includes('ai_semiconductor_intelligence') ? '✓' : '✗'
    ],
    ['Custom topics',               '✗',         '✗',           '✗',           '✓'],
    ['Watchlist keywords',          '3',         '20',          '100',         'Unlimited'],
    ['Support',                     'Community', 'Priority',    'Priority',    'Dedicated SLA'],
    ['Entity-level intelligence',   '✗',         '✓',           '✓',           '✓'],
    ['Confidence metrics',          '✗',         '✓',           '✓',           '✓'],
    ['Source traceability',         '✗',         '✓',           '✓',           '✓'],
    ['Cross-domain impact',         '✗',         '✗',           '✓',           '✓'],
    ['Self-serve limits',           'Low',       'Medium',      'High',        'Custom'],
    ['Team/Org support',            '✗',         '✗',           '✗',           '✓'],
    ['Dedicated Account Manager',   '✗',         '✗',           '✗',           '✓'],
    ['Custom Workflows',            '✗',         '✗',           '✗',           '✓'],
];

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function getDaysUntilExpiry(expiresAt: string | null): number | null {
    if (!expiresAt) return null;
    const exp = new Date(expiresAt);
    const now = new Date();
    return Math.ceil((exp.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
}

function isInGracePeriod(user: UserMe): boolean {
    const days = getDaysUntilExpiry(user.expires_at);
    return days !== null && days <= GRACE_PERIOD_DAYS && days > -GRACE_PERIOD_DAYS;
}

/** Centralized normalization and labeling */
const getTierDisplayName = (tier: string) => PLAN_NAME_MAP[tier.toLowerCase()] || 'Free';
const getTierBadgeLabel = (tier: string) => getTierDisplayName(tier).toUpperCase();

/** CTA Logic: Distinguish current plan vs higher tiers vs contact sales */
function renderUpgradeButton(plan: PlanConfig, currentUser: UserMe): string {
    const isCurrent = currentUser.tier === plan.id;
    
    if (isCurrent) {
        let html = `<div class="plan-current-label">✓ Current Plan</div>`;
        if (plan.id !== 'free') {
            html += `<button class="plan-cancel-btn" data-plan="${plan.id}">Manage Subscription</button>`;
        }
        return html;
    }

    // Determine if it's an upgrade or contact sales
    if (!plan.directCheckout) {
        return `<a class="plan-cta-btn plan-cta-btn--contact" href="${plan.contactUrl}" target="_blank" rel="noopener">Contact Sales</a>`;
    }

    // Direct Stripe Checkout
    return `<button class="plan-cta-btn" data-plan="${plan.id}" id="upgrade-btn-${plan.id}">Upgrade to ${plan.name}</button>`;
}

// ──────────────────────────────────────────────────────────────────────────────
// Tier Badge (for sidebar)
// ──────────────────────────────────────────────────────────────────────────────

export function renderTierBadge(user: UserMe): string {
    const colors: Record<string, string> = {
        free: '#8b949e',
        pro: '#58a6ff',
        experts: '#3fb950',
        enterprise: '#bc8cff',
    };
    const col = colors[user.tier] ?? '#8b949e';
    const grace = isInGracePeriod(user) ? ' tier-badge--grace' : '';
    const badgeLabel = getTierBadgeLabel(user.tier);
    return `<span class="tier-badge${grace}" style="background: ${col}22; color: ${col}; border-color: ${col}55;">${badgeLabel}</span>`;
}

// ──────────────────────────────────────────────────────────────────────────────
// Grace Period Banner (for header)
// ──────────────────────────────────────────────────────────────────────────────

export function renderGracePeriodBanner(user: UserMe): string {
    const days = getDaysUntilExpiry(user.expires_at);
    if (days === null) return '';

    if (days <= 0 && days > -GRACE_PERIOD_DAYS) {
        return `<div class="grace-period-banner" id="grace-banner">
            ⚠️ Your <strong>${user.tier} subscription</strong> expired. 
            You are in a ${GRACE_PERIOD_DAYS}-day grace period — 
            <a href="#" id="grace-upgrade-link">renew now</a> to avoid downgrade.
        </div>`;
    }

    if (days > 0 && days <= GRACE_PERIOD_DAYS) {
        return `<div class="grace-period-banner" id="grace-banner">
            ⚠️ Your <strong>${user.tier} subscription</strong> expires in <strong>${days} day${days === 1 ? '' : 's'}</strong>.
            <a href="#" id="grace-upgrade-link">Renew now</a>
        </div>`;
    }

    return '';
}

// ──────────────────────────────────────────────────────────────────────────────
// Locked Feature Overlay
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Returns an overlay card for content the current user cannot access.
 * CTA always routes to the Plans & Billing tab (unified navigation).
 */
export function renderLockedFeature(label: string, minTier: string): string {
    const minTierDisplay = PLAN_NAME_MAP[minTier] || minTier.charAt(0).toUpperCase() + minTier.slice(1);
    return `
    <div class="locked-feature-overlay">
        <div class="locked-feature-inner">
            <div class="locked-icon">🔒</div>
            <h3>${label}</h3>
            <p>This feature requires an <strong>${minTierDisplay}</strong> subscription or higher.</p>
            <button class="plan-cta-btn" id="locked-goto-plans" data-target-tab="plans">
                View Plans & Billing
            </button>
        </div>
    </div>`;
}

// ──────────────────────────────────────────────────────────────────────────────
// Plans & Billing Page
// ──────────────────────────────────────────────────────────────────────────────

export function renderSubscriptionTab(user: UserMe, container: HTMLElement, onNavigatePlans: () => void): void {
    const days = getDaysUntilExpiry(user.expires_at);
    const grace = isInGracePeriod(user);

    // Build expiry string
    let expiryHtml = '';
    if (user.expires_at) {
        const formatted = new Date(user.expires_at).toLocaleDateString('en-US', {
            year: 'numeric', month: 'long', day: 'numeric'
        });
        if (grace) {
            expiryHtml = `<div class="sub-expiry sub-expiry--warning">⚠️ Expires/Expired: ${formatted}</div>`;
        } else if (days !== null && days > 0) {
            expiryHtml = `<div class="sub-expiry">Renews: ${formatted}</div>`;
        }
    }

    // Build plan cards
    const planCards = PLANS.map(plan => {
        const isCurrent = user.tier === plan.id;
        const featureList = plan.features.map(f => `<li>${f}</li>`).join('');
        const ctaHtml = renderUpgradeButton(plan, user);

        // Pricing Display Logic
        let priceHtml = '';
        if (plan.id === 'pro') {
            priceHtml = `
                <span class="plan-price-amount pro-price-highlight">${plan.price}</span>
                <span class="plan-price-note">/${plan.priceNote}</span>
            `;
        } else {
            priceHtml = `
                ${plan.originalPrice ? `<span class="plan-price-old">${plan.originalPrice}</span>` : ''}
                <span class="plan-price-amount">${plan.price}</span>
                <span class="plan-price-note">/${plan.priceNote}</span>
            `;
        }

        return `
        <div class="plan-card plan-card--${plan.id} ${isCurrent ? 'plan-card--active' : ''}" style="--plan-color: ${plan.color}">
            ${plan.id === 'pro' ? '<div class="plan-ribbon">Most Popular</div>' : ''}
            ${plan.id === 'experts' ? '<div class="plan-ribbon plan-ribbon--premium">Expert Choice</div>' : ''}
            
            <div class="plan-header">
                <div class="plan-best-for">${plan.bestFor}</div>
                <h2 class="plan-name">${plan.name}</h2>
                <p class="plan-subtitle">${plan.subtitle}</p>
            </div>

            <div class="plan-price">
                ${priceHtml}
            </div>

            <div class="plan-features-wrap">
                <ul class="plan-features">${featureList}</ul>
            </div>

            <div class="plan-cta-area">${ctaHtml}</div>
        </div>`;
    }).join('');

    // Build feature comparison table
    const tableRows = FEATURE_COMPARISON.map(([feat, free, pro, exp, ent]) => {
        const highlight = (val: string, tier: string) =>
            `<td class="${user.tier === tier ? 'cmp-current' : ''}">${val}</td>`;
        return `<tr>
            <td class="cmp-feature">${feat}</td>
            ${highlight(free, 'free')}
            ${highlight(pro, 'pro')}
            ${highlight(exp, 'experts')}
            ${highlight(ent, 'enterprise')}
        </tr>`;
    }).join('');

    container.innerHTML = `
    <div class="subscription-tab">
        <!-- Current Status Redesign -->
        <div class="sub-status-card">
            <div class="sub-status-layout">
                <div class="sub-status-info">
                    <h2>Subscription Status</h2>
                    ${renderTierBadge(user)}
                    <div class="sub-status-current-row">
                        <span class="label">Current Plan</span>
                        <span class="value">${getTierDisplayName(user.tier)}</span>
                    </div>
                </div>
                <div class="sub-status-meta">
                    ${expiryHtml}
                    ${grace ? `<div class="sub-expiry sub-expiry--warning">⚠️ Grace Period Active</div>` : ''}
                </div>
            </div>
        </div>

        <!-- Plan Cards -->
        <div class="plans-grid">
            ${planCards}
        </div>

        <!-- Feature Comparison -->
        <div class="comparison-section">
            <h3>Feature Comparison</h3>
            <div class="comparison-table-wrap">
                <table class="comparison-table">
                    <thead>
                        <tr>
                            <th>Feature</th>
                            <th class="${user.tier === 'free' ? 'cmp-current' : ''}">${getTierDisplayName('free')}</th>
                            <th class="${user.tier === 'pro' ? 'cmp-current' : ''}">${getTierDisplayName('pro')}</th>
                            <th class="${user.tier === 'experts' ? 'cmp-current' : ''}">${getTierDisplayName('experts')}</th>
                            <th class="${user.tier === 'enterprise' ? 'cmp-current' : ''}">${getTierDisplayName('enterprise')}</th>
                        </tr>
                    </thead>
                    <tbody>${tableRows}</tbody>
                </table>
            </div>
        </div>
    </div>`;

    // ── Event handlers ────────────────────────────────────────────────────────

    // Upgrade CTA buttons
    container.querySelectorAll<HTMLButtonElement>('.plan-cta-btn[data-plan]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const tier = btn.dataset.plan!;
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = 'Redirecting…';

            try {
                const urlParams = new URLSearchParams(window.location.search);
                const reportId = urlParams.get('report_id');
                const response = await fetchCheckoutSession(tier, reportId || undefined);
                if (response.success) {
                    btn.textContent = 'Success! Updating...';
                    setTimeout(() => window.location.reload(), 800);
                    return;
                }
                if (response.url) {
                    window.location.href = response.url;
                }
            } catch (err: any) {
                btn.textContent = '⚠ Failed — try again';
                btn.classList.add('plan-cta-btn--error');
                console.error('Checkout error:', err.message);
                setTimeout(() => {
                    btn.disabled = false;
                    btn.textContent = originalText;
                    btn.classList.remove('plan-cta-btn--error');
                }, 3500);
            }
        });
    });

    // Manage Subscription (Stripe Portal)
    container.querySelectorAll<HTMLButtonElement>('.plan-cancel-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = 'Opening Portal…';
            try {
                const result = await cancelSubscription();
                if (result.url) {
                    window.location.href = result.url;
                }
            } catch (err: any) {
                btn.textContent = 'Portal unavailable';
                btn.classList.add('plan-cta-btn--error');
                console.error('Portal error:', err.message);
                setTimeout(() => {
                    btn.disabled = false;
                    btn.textContent = originalText;
                    btn.classList.remove('plan-cta-btn--error');
                }, 3000);
            }
        });
    });

    // Locked-feature overlay → Plans tab
    container.querySelectorAll<HTMLButtonElement>('#locked-goto-plans, [id="locked-goto-plans"]').forEach(btn => {
        btn.addEventListener('click', (e) => { e.preventDefault(); onNavigatePlans(); });
    });

    // Grace period banner link
    container.querySelector<HTMLAnchorElement>('#grace-upgrade-link')?.addEventListener('click', (e) => {
        e.preventDefault(); onNavigatePlans();
    });
}
