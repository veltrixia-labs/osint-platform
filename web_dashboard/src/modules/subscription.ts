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

// ──────────────────────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────────────────────

const GRACE_PERIOD_DAYS = 3;

interface PlanConfig {
    id: string;
    name: string;
    subtitle: string;
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
        name: 'Free',
        subtitle: 'Get started with the basics',
        price: '$0',
        priceNote: 'forever',
        color: '#8b949e',
        directCheckout: false,
        contactUrl: '',
        features: [
            '5 alerts/day',
            'Daily intelligence reports',
            '3 watchlist keywords',
            'Community topics only',
            'Email support',
        ],
    },
    {
        id: 'pro',
        name: 'Pro',
        subtitle: 'Founding Member Access',
        price: '$19',
        originalPrice: '$49',
        priceNote: 'per month',
        color: '#58a6ff',
        directCheckout: true,  // → Stripe Checkout
        contactUrl: '',
        features: [
            'Entity-level intelligence',
            'Analytical confidence metrics',
            'Full source traceability',
            '100 alerts/day',
            'Daily + Monthly reports',
            '20 watchlist keywords',
        ],
    },
    {
        id: 'enterprise',
        name: 'Enterprise',
        subtitle: 'Custom intelligence at scale',
        price: 'Custom',
        priceNote: 'contact us',
        color: '#bc8cff',
        // ✦ Switchable: set directCheckout=true + price ID when ready for direct checkout
        directCheckout: false,
        contactUrl: 'mailto:sales@osint-platform.com?subject=Enterprise%20Plan%20Inquiry',
        features: [
            'Unlimited alerts',
            'All report types (incl. specialized)',
            '100 watchlist keywords',
            'Custom topic configuration',
            'Dedicated account manager',
            'SLA guarantee',
        ],
    },
];

/**
 * Feature comparison table rows.
 * Each row: [featureName, free, pro, enterprise]
 */
const FEATURE_COMPARISON: [string, string, string, string][] = [
    ['Alerts per day',      '5',         '100',         'Unlimited'],
    ['Daily reports',       '✓',         '✓',           '✓'],
    ['Monthly reports',     '✗',         '✓',           '✓'],
    ['Specialized topics',  '✗',         '✓ (Unlimited)', '✓ (Custom)'],
    ['Watchlist keywords',  '3',         '20',          '100'],
    ['Source Traceability', '✗',         '✓ (Full)',    '✓ (Full)'],
    ['Confidence Metrics',  '✗',         '✓ (Detailed)', '✓ (Detailed)'],
    ['Support',             'Community', 'Priority',    'Dedicated SLA'],
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

// ──────────────────────────────────────────────────────────────────────────────
// Tier Badge (for sidebar)
// ──────────────────────────────────────────────────────────────────────────────

export function renderTierBadge(user: UserMe): string {
    const colors: Record<string, string> = {
        free: '#8b949e',
        pro: '#58a6ff',
        enterprise: '#bc8cff',
    };
    const col = colors[user.tier] ?? '#8b949e';
    const grace = isInGracePeriod(user) ? ' tier-badge--grace' : '';
    return `<span class="tier-badge${grace}" style="background: ${col}22; color: ${col}; border-color: ${col}55;">${user.tier.toUpperCase()}</span>`;
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
    return `
    <div class="locked-feature-overlay">
        <div class="locked-feature-inner">
            <div class="locked-icon">🔒</div>
            <h3>${label}</h3>
            <p>This feature requires a <strong>${minTier.charAt(0).toUpperCase() + minTier.slice(1)}</strong> subscription or higher.</p>
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

        let ctaHtml = '';
        if (isCurrent) {
            ctaHtml = `<div class="plan-current-label">✓ Current Plan</div>`;
            if (plan.id !== 'free') {
                ctaHtml += `<button class="plan-cancel-btn" data-plan="${plan.id}">Manage Subscription</button>`;
            }
        } else if (plan.id === 'free') {
            // Free plan — users can't "downgrade" via button; show info only
            ctaHtml = `<div class="plan-downgrade-note">Downgrade happens automatically on subscription expiry.</div>`;
        } else if (plan.directCheckout) {
            ctaHtml = `<button class="plan-cta-btn" data-plan="${plan.id}" id="upgrade-btn-${plan.id}">Upgrade to ${plan.name}</button>`;
        } else {
            // Enterprise → contact-sales
            ctaHtml = `<a class="plan-cta-btn plan-cta-btn--contact" href="${plan.contactUrl}" target="_blank" rel="noopener">Contact Sales</a>`;
        }

        return `
        <div class="plan-card ${isCurrent ? 'plan-card--active' : ''}" style="--plan-color: ${plan.color}">
            ${plan.id === 'pro' ? '<div class="plan-badge-top">FOUNDING MEMBER</div>' : ''}
            <div class="plan-header">
                <h2 class="plan-name" style="color: ${plan.color}">${plan.name}</h2>
                <p class="plan-subtitle">${plan.subtitle}</p>
                <div class="plan-price">
                    ${plan.originalPrice ? `<span class="plan-price-old">${plan.originalPrice}</span>` : ''}
                    <span class="plan-price-amount" style="${plan.originalPrice ? 'color: var(--tier-grace);' : ''}">${plan.price}</span>
                    <span class="plan-price-note">/${plan.priceNote}</span>
                </div>
            </div>
            <ul class="plan-features">${featureList}</ul>
            <div class="plan-cta-area">${ctaHtml}</div>
        </div>`;
    }).join('');

    // Build feature comparison table
    const tableRows = FEATURE_COMPARISON.map(([feat, free, pro, ent]) => {
        const highlight = (val: string, tier: string) =>
            `<td class="${user.tier === tier ? 'cmp-current' : ''}">${val}</td>`;
        return `<tr>
            <td class="cmp-feature">${feat}</td>
            ${highlight(free, 'free')}
            ${highlight(pro, 'pro')}
            ${highlight(ent, 'enterprise')}
        </tr>`;
    }).join('');

    container.innerHTML = `
    <div class="subscription-tab">
        <!-- Current Status -->
        <div class="sub-status-card">
            <div class="sub-status-header">
                <h2>Subscription Status</h2>
                ${renderTierBadge(user)}
            </div>
            ${expiryHtml}
            ${grace ? `<div class="grace-period-banner">⚠️ You are in a grace period. Please renew to retain access.</div>` : ''}
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
                            <th class="${user.tier === 'free' ? 'cmp-current' : ''}">Free</th>
                            <th class="${user.tier === 'pro' ? 'cmp-current' : ''}">Pro</th>
                            <th class="${user.tier === 'enterprise' ? 'cmp-current' : ''}">Enterprise</th>
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
