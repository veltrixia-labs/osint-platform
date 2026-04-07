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
    guest: 'Guest',
    free: 'Free Member',
    pro: 'Pro',
    experts: 'Expert',
    enterprise: 'Enterprise',
};

/** "Best For" labels for conversion guidance */
const TIER_BEST_FOR: Record<string, string> = {
    guest: 'Public risk monitoring (limited)',
    free: 'Basic analyst access',
    pro: 'Operational risk intelligence',
    experts: 'Strategic risk intelligence',
    enterprise: 'Organizations requiring onboarding & customization',
};

interface PlanConfig {
    id: string;
    name: string;
    subtitle: string;
    explanation?: string;
    bestFor: string;
    price: string;
    originalPrice?: string;
    priceNote: string;
    color: string;
    /** true = Stripe Checkout, false = contact-sales redirect */
    directCheckout: boolean;
    contactUrl: string;
    features: string[];
    ctaText?: string;
    highlight?: string;
}

const PLANS: PlanConfig[] = [
    {
        id: 'free',
        name: PLAN_NAME_MAP.free,
        subtitle: 'Foundational Awareness',
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
            'Real-time Signal Detection',
            'Email support',
        ],
        ctaText: 'Start Monitoring',
    },
    {
        id: 'pro',
        name: PLAN_NAME_MAP.pro,
        subtitle: 'Understand why signals matter',
        explanation: 'Understand what signals mean and why they matter',
        bestFor: TIER_BEST_FOR.pro,
        price: '$19',
        priceNote: 'per month',
        color: '#58a6ff',
        directCheckout: true,
        contactUrl: '',
        features: [
            'Entity-level intelligence',
            'AI-powered insight generation',
            'Full source traceability',
            '100 alerts/day',
            'Daily + Weekly reports',
            'Core specialized topics',
            'AI-generated analysis', // Microcopy
        ],
        ctaText: 'Unlock AI Insights',
    },
    {
        id: 'experts',
        name: PLAN_NAME_MAP.experts,
        subtitle: 'Decision-grade intelligence for leads',
        explanation: 'Turn insights into strategic action',
        bestFor: TIER_BEST_FOR.experts,
        price: '$49',
        priceNote: 'per month',
        color: '#3fb950',
        directCheckout: true,
        contactUrl: '',
        features: [
            'Strategic Scenarios',
            'Cross-domain impact analysis',
            '30–60 day outlook',
            'Strategic decision support',
            'Decision-Grade Intelligence',
            'Unlimited alerts',
        ],
        ctaText: 'Unlock Strategic Intelligence',
        highlight: 'Best for decision-makers',
    },
    {
        id: 'enterprise',
        name: PLAN_NAME_MAP.enterprise,
        subtitle: 'Expert Intelligence + Priority Support',
        bestFor: TIER_BEST_FOR.enterprise,
        price: 'Custom',
        priceNote: 'contact us',
        color: '#bc8cff',
        directCheckout: false,
        contactUrl: 'mailto:sales@osint-platform.com?subject=Enterprise%20Plan%20Inquiry',
        features: [
            'All Expert features',
            'Custom topic configuration',
            'Custom onboarding',
            'Priority support escalation',
            'Strategic Intelligence workflow',
        ],
        ctaText: 'Contact Sales',
    },
];

interface ComparisonSection {
    type: 'section';
    label: string;
    subtitle: string;
}
interface ComparisonRow {
    type: 'row';
    feat: string;
    vals: [string, string, string, string];
    isHighlight?: boolean;
}
type ComparisonItem = ComparisonSection | ComparisonRow;

const FEATURE_COMPARISON: ComparisonItem[] = [
    { type: 'section', label: 'SIGNAL', subtitle: 'What is happening' },
    { type: 'row', feat: 'Alerts per day', vals: ['5', '100', 'Unlimited', 'Unlimited'] },
    { type: 'row', feat: 'Daily reports', vals: [
        ENTITLEMENT_MATRIX.free.reports.includes('daily') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.pro.reports.includes('daily') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.experts.reports.includes('daily') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.enterprise.reports.includes('daily') ? '✓' : '✗'
    ]},
    { type: 'row', feat: 'Weekly reports', vals: [
        ENTITLEMENT_MATRIX.free.reports.includes('weekly') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.pro.reports.includes('weekly') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.experts.reports.includes('weekly') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.enterprise.reports.includes('weekly') ? '✓' : '✗'
    ]},
    { type: 'row', feat: 'Watchlist keywords', vals: ['3', '20', '100', 'Unlimited'] },

    { type: 'section', label: 'ANALYSIS', subtitle: 'Why it matters' },
    { type: 'row', feat: 'Report Depth', isHighlight: true, vals: ['Baseline', 'AI-Enhanced', 'Strategic', 'Strategic'] },
    { type: 'row', feat: 'Entity-level intelligence', vals: ['✓', '✓', '✓', '✓'] },
    { type: 'row', feat: 'Confidence metrics', vals: ['✓', '✓', '✓', '✓'] },
    { type: 'row', feat: 'Source traceability', vals: ['✓', '✓', '✓', '✓'] },
    { type: 'row', feat: 'Core Specialty Topics', vals: [
        ENTITLEMENT_MATRIX.free.topics.includes('energy_resource_risk') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.pro.topics.includes('energy_resource_risk') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.experts.topics.includes('energy_resource_risk') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.enterprise.topics.includes('energy_resource_risk') ? '✓' : '✗'
    ]},

    { type: 'section', label: 'STRATEGY', subtitle: 'What to do next' },
    { type: 'row', feat: 'Scenario Analysis', isHighlight: true, vals: ['Basic (Rule-based)', 'Basic (Rule-based)', 'Strategic (LLM-driven)', 'Strategic (LLM-driven)'] },
    { type: 'row', feat: 'Risk Forecasting', isHighlight: true, vals: ['Monitoring Signals', 'AI-Enhanced Insights', 'Strategic Forecast (30–60 days)', 'Strategic Forecast (30–60 days)'] },
    { type: 'row', feat: 'Expert Specialty Topics', vals: [
        ENTITLEMENT_MATRIX.free.topics.includes('ai_semiconductor_intelligence') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.pro.topics.includes('ai_semiconductor_intelligence') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.experts.topics.includes('ai_semiconductor_intelligence') ? '✓' : '✗',
        ENTITLEMENT_MATRIX.enterprise.topics.includes('ai_semiconductor_intelligence') ? '✓' : '✗'
    ]},
    { type: 'row', feat: 'Cross-domain impact', vals: ['✗', '✗', '✓', '✓'] },
    { type: 'row', feat: 'Custom topics', vals: ['✗', '✗', '✗', '✓'] },
    { type: 'row', feat: 'Support', vals: ['Community', 'Priority', 'Priority', 'Dedicated Escalation'] },
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

    const ctaText = plan.ctaText || `Upgrade to ${plan.name}`;

    // Determine if it's an upgrade or contact sales
    if (!plan.directCheckout) {
        return `<a class="plan-cta-btn plan-cta-btn--contact" href="${plan.contactUrl}" target="_blank" rel="noopener">${ctaText}</a>`;
    }

    // Direct Stripe Checkout
    return `<button class="plan-cta-btn" data-plan="${plan.id}" id="upgrade-btn-${plan.id}">${ctaText}</button>`;
}

// ──────────────────────────────────────────────────────────────────────────────
// Tier Badge (for sidebar)
// ──────────────────────────────────────────────────────────────────────────────

export function renderTierBadge(user: UserMe): string {
    const colors: Record<string, string> = {
        guest: '#6e7681',
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
            ${plan.highlight ? `<div class="plan-ribbon plan-ribbon--premium">${plan.highlight}</div>` : ''}
            
            <div class="plan-header">
                <div class="plan-best-for">${plan.bestFor}</div>
                <h2 class="plan-name">${plan.name}</h2>
                <p class="plan-subtitle">${plan.subtitle}</p>
                ${plan.explanation ? `<p class="plan-explanation">${plan.explanation}</p>` : ''}
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
    const tableRows = FEATURE_COMPARISON.map((item) => {
        if (item.type === 'section') {
            return `
            <tr class="comparison-section-header">
                <td colspan="5">
                    <div class="section-label">${item.label}</div>
                    <div class="comparison-section-subtitle">${item.subtitle}</div>
                </td>
            </tr>`;
        }
        
        const { feat, vals, isHighlight } = item;
        const [free, pro, exp, ent] = vals;
        
        const highlightCell = (val: string, tier: string) => {
            const isExpertCol = tier === 'experts' || tier === 'enterprise';
            const classes = [
                user.tier === tier ? 'cmp-current' : '',
                isExpertCol ? 'comparison-column--expert-highlight' : ''
            ].filter(Boolean).join(' ');
            return `<td class="${classes}">${val}</td>`;
        };

        return `<tr class="${isHighlight ? 'comparison-row--highlight' : ''}">
            <td class="cmp-feature">${feat}</td>
            ${highlightCell(free, 'free')}
            ${highlightCell(pro, 'pro')}
            ${highlightCell(exp, 'experts')}
            ${highlightCell(ent, 'enterprise')}
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
