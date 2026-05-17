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
import type { TopicDef } from './topics';
import { fetchCheckoutSession, cancelSubscription } from './api';
import { ENTITLEMENT_MATRIX } from './topics';

// ──────────────────────────────────────────────────────────────────────────────
// Constants
// ──────────────────────────────────────────────────────────────────────────────

const GRACE_PERIOD_DAYS = 3;

/** Mapping internal tier IDs to user-facing display names */
const PLAN_NAME_MAP: Record<string, string> = {
    free: 'Free Access',
    pro: 'Founding Pro',
    experts: 'Founding Expert',
    enterprise: 'Enterprise',
};

/** "Best For" labels for conversion guidance */
const TIER_BEST_FOR: Record<string, string> = {
    free: 'Public Monitoring & Context Briefs',
    pro: 'Strategic Market Intelligence',
    experts: 'Strategic Foresight & Forecasting',
    enterprise: 'Organization-wide Strategy',
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
        subtitle: 'The Entry Point for Global Intelligence',
        bestFor: TIER_BEST_FOR.free,
        price: '$0',
        priceNote: 'forever',
        color: '#8b949e',
        directCheckout: false,
        contactUrl: '',
        features: [
            'Real-time Alert Stream headlines',
            'Full Global Map access',
            'Context Briefs (Free-tier limited)',
            'Base news evidence',
            'Community support',
        ],
        ctaText: 'Start Monitoring',
    },
    {
        id: 'pro',
        name: PLAN_NAME_MAP.pro,
        subtitle: 'Deep Structural Analysis',
        explanation: 'Limited to the first 1,000 members',
        bestFor: TIER_BEST_FOR.pro,
        price: '$39',
        originalPrice: '$79',
        priceNote: 'month',
        color: '#58a6ff',
        directCheckout: true,
        contactUrl: '',
        features: [
            'Pro Insights Dashboard',
            'Full Structural Briefs',
            'Market Confirmation Breakdown',
            'Exposure Matrix Analysis',
            'High-Fidelity Signal Access',
            'Transmission Flow Visualization',
            'Key Findings Analysis',
        ],
        ctaText: 'Become a Founding Pro',
        highlight: 'EARLY ACCESS',
    },
    {
        id: 'experts',
        name: PLAN_NAME_MAP.experts,
        subtitle: 'Advanced Strategic Foresight',
        explanation: 'Limited to the first 100 members',
        bestFor: TIER_BEST_FOR.experts,
        price: '$149',
        originalPrice: '$299',
        priceNote: 'month',
        color: '#3fb950',
        directCheckout: true,
        contactUrl: '',
        features: [
            'Coming Soon: Expert Foresight',
            'Cross-domain Risk Forecasting',
            'Strategic Scenario Analysis',
            'Recommended Strategic Actions',
            'Waitlist Priority for New Tools',
            'Direct Analyst Access (Coming)',
            'Unlimited Strategic Alerts',
        ],
        ctaText: 'Secure Founding Expert Spot',
        highlight: 'FOUNDING MEMBER',
    },
    {
        id: 'enterprise',
        name: PLAN_NAME_MAP.enterprise,
        subtitle: 'Expert Intelligence + Organization Controls',
        bestFor: TIER_BEST_FOR.enterprise,
        price: 'Contact',
        priceNote: 'us',
        color: '#bc8cff',
        directCheckout: false,
        contactUrl: 'mailto:sales@osint-platform.com?subject=Enterprise%20Plan%20Inquiry',
        features: [
            'Full Expert-tier features',
            'Team & Admin Management',
            'Custom domain configuration',
            'Priority 1-on-1 support',
            'Enterprise API Access',
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
export function renderLockedFeature(label: string, minTier: string, context?: string): string {
    const minTierDisplay = PLAN_NAME_MAP[minTier] || minTier.charAt(0).toUpperCase() + minTier.slice(1);
    
    // Context-aware value proposition
    let valueProp = context;
    if (!valueProp) {
        if (minTier === 'pro') {
            valueProp = `Upgrade to Pro / Expert to unlock real-time sector intensity metrics and early-warning signals for ${label.toLowerCase()}.`;
        } else if (minTier === 'experts') {
            valueProp = `Expert access required to visualize recursive causal chains and 60-day strategic scenarios for ${label.toLowerCase()}.`;
        } else {
            valueProp = `This feature requires an ${minTierDisplay} subscription or higher.`;
        }
    }

    return `
    <div class="locked-feature-overlay">
        <div class="locked-feature-inner">
            <div class="locked-tier-tag" style="background: ${PLAN_NAME_MAP[minTier] === 'Expert' ? '#bc8cff' : '#58a6ff'}">${minTierDisplay} Required</div>
            <div class="locked-icon">🔒</div>
            <h3>${label}</h3>
            <p>${valueProp}</p>
            
            <div class="locked-perks">
                ${minTier === 'pro' ? `
                    <div class="locked-perk"><span>✓</span> AI-Powered Sector Summaries</div>
                    <div class="locked-perk"><span>✓</span> Signal Momentum Tracking</div>
                ` : `
                    <div class="locked-perk"><span>✓</span> Full Impact Chain Mapping</div>
                    <div class="locked-perk"><span>✓</span> Strategic Recommended Actions</div>
                `}
            </div>

            <button class="plan-cta-btn" id="locked-goto-plans" data-target-tab="plans">
                View Plans & Upgrade
            </button>
        </div>
    </div>`;
}

/**
 * Renders a full-screen or modal-style overlay for a locked topic.
 */
export function renderLockedTopicOverlay(container: HTMLElement, topic: TopicDef, onNavigatePlans: () => void) {
    container.innerHTML = `
    <div class="locked-topic-container" style="--topic-color: ${topic.color}">
        <div class="locked-topic-inner">
            <div class="topic-icon-large">${topic.icon}</div>
            <div class="topic-tier-badge">${(PLAN_NAME_MAP[topic.minTier] || topic.minTier).toUpperCase()} ONLY</div>
            <h2>${topic.label}</h2>
            <p class="topic-description">${topic.description}</p>
            
            <div class="topic-value-card">
                <div class="value-statement">${topic.valueProposition}</div>
                <ul class="value-bullets">
                    <li>✓ Exclusive real-time indicators</li>
                    <li>✓ Deep forensic signal analysis</li>
                    <li>✓ Strategic causal mapping</li>
                </ul>
            </div>

            <div class="conversion-actions">
                <button class="plan-cta-btn" id="locked-topic-upgrade">
                    Upgrade to ${PLAN_NAME_MAP[topic.minTier] || topic.minTier} to Access
                </button>
                <button class="ghost-btn" id="locked-topic-back">Return to Feed</button>
            </div>
        </div>
    </div>`;

    container.querySelector('#locked-topic-upgrade')?.addEventListener('click', () => onNavigatePlans());
    container.querySelector('#locked-topic-back')?.addEventListener('click', () => {
        window.location.hash = '#feed';
    });
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
        if (plan.originalPrice) {
            priceHtml = `
                <div class="plan-price-standard">
                    <span class="plan-price-old">${plan.originalPrice}</span>
                    <span class="plan-price-standard-label">Standard</span>
                </div>
                <div class="plan-price-founding">
                    <span class="plan-price-amount ${plan.id === 'pro' ? 'pro-price-highlight' : ''}">${plan.price}</span>
                    <span class="plan-price-note">/${plan.priceNote}</span>
                </div>
            `;
        } else {
            priceHtml = `
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

    let upsellMessage: string | null = null;
    const upsellRaw = sessionStorage.getItem('plansContextBriefUpsell');
    if (upsellRaw) {
        sessionStorage.removeItem('plansContextBriefUpsell');
        try {
            const j = JSON.parse(upsellRaw) as { message?: string };
            if (typeof j.message === 'string' && j.message.trim()) {
                upsellMessage = j.message.trim();
            }
        } catch {
            /* ignore */
        }
    }
    const upsellBannerHtml = upsellMessage
        ? `
        <div class="sub-upsell-banner" id="plans-context-brief-upsell" role="status">
            <p class="sub-upsell-banner__text"></p>
            <button type="button" class="sub-upsell-banner__dismiss" aria-label="Dismiss notice">×</button>
        </div>`
        : '';

    container.innerHTML = `
    <div class="subscription-tab">
        ${upsellBannerHtml}
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

    if (upsellMessage) {
        const p = container.querySelector('.sub-upsell-banner__text');
        if (p) p.textContent = upsellMessage;
        container.querySelector('.sub-upsell-banner__dismiss')?.addEventListener('click', () => {
            document.getElementById('plans-context-brief-upsell')?.remove();
        });
    }

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
