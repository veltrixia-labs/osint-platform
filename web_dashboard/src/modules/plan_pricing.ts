/**
 * Shared plan pricing display + billing toggle (LP + app Plans tab).
 */

export type BillingMode = 'monthly' | 'annual';

export interface TierPriceConfig {
    monthly: number;
    annual: number;
    monthlyOriginal?: number;
    annualOriginal?: number;
}

export const TIER_PRICES: Record<string, TierPriceConfig> = {
    pro: { monthly: 79, annual: 69 },
    experts: { monthly: 149, annual: 129, monthlyOriginal: 299, annualOriginal: 249 },
};

/**
 * Stripe Price IDs (server uses env vars with these defaults).
 * Checkout is created via POST /api/stripe/create-checkout with tier + billing.
 */
export const STRIPE_PRICE_IDS: Record<string, { monthly: string; annual: string }> = {
    pro: {
        monthly: 'price_1TYffzCc1F7MyO7MLab3Q6zu',
        annual: 'price_1TYffzCc1F7MyO7MET0aN1Fh',
    },
    experts: {
        monthly: 'price_1TYfhxCc1F7MyO7MtdZk1pEv',
        annual: 'price_1TYfhxCc1F7MyO7MaaibN5sL',
    },
};

export function formatUsd(amount: number): string {
    return `$${amount}`;
}

export function renderBillingToggleHtml(toggleId = 'vx-billing-toggle'): string {
    return `
    <div class="vx-pricing-billing" aria-label="Billing period">
        <span class="vx-pricing-billing-label" data-billing-label="monthly">Monthly</span>
        <button type="button" class="vx-pricing-switch" id="${toggleId}" role="switch" aria-checked="false" aria-label="Toggle annual billing">
            <span class="vx-pricing-switch-track">
                <span class="vx-pricing-switch-thumb"></span>
            </span>
        </button>
        <span class="vx-pricing-billing-label" data-billing-label="annual">Annual</span>
        <span class="vx-pricing-save-badge">Save ~20%</span>
    </div>`;
}

function updatePriceBlock(block: HTMLElement, mode: BillingMode): void {
    const tier = block.dataset.priceTier;
    if (!tier) return;
    const cfg = TIER_PRICES[tier];
    if (!cfg) return;

    const annual = mode === 'annual';
    const amount = annual ? cfg.annual : cfg.monthly;
    const original = annual ? cfg.annualOriginal : cfg.monthlyOriginal;

    const amountEl = block.querySelector<HTMLElement>('.vx-price-amount, .lp-pricing-amount, .plan-price-amount--dynamic');
    if (amountEl) {
        amountEl.textContent = amountEl.classList.contains('plan-price-amount--dynamic')
            ? formatUsd(amount)
            : String(amount);
    }

    const originalEl = block.querySelector<HTMLElement>('.vx-price-original, .plan-price-old--dynamic');
    if (originalEl && original != null) {
        originalEl.textContent = formatUsd(original);
    }

    const billedNote = block.querySelector<HTMLElement>('.vx-price-billed-note, .lp-pricing-billed-note, .plan-price-billed-note');
    if (billedNote) billedNote.hidden = !annual;
}

function updateCheckoutTargets(root: HTMLElement, mode: BillingMode): void {
    root.querySelectorAll<HTMLAnchorElement>('a[data-tier][data-href-monthly]').forEach((link) => {
        const tier = link.dataset.tier;
        if (!tier) return;
        const fallback = mode === 'annual' ? link.dataset.hrefAnnual : link.dataset.hrefMonthly;
        link.href = fallback || `app.html#plans?tier=${tier}&billing=${mode}`;
        link.dataset.stripePriceId = STRIPE_PRICE_IDS[tier]?.[mode] ?? '';
    });

    root.querySelectorAll<HTMLButtonElement>('button.plan-cta-btn[data-plan]').forEach((btn) => {
        btn.dataset.billing = mode;
    });
}

/** Wire billing toggle + price blocks; `scope` is subscription tab container or document for LP. */
export function initBillingToggle(scope: ParentNode = document, toggleId = 'vx-billing-toggle'): void {
    const toggle =
        scope instanceof Document
            ? scope.getElementById(toggleId)
            : (scope as HTMLElement).querySelector<HTMLButtonElement>(`#${toggleId}`) ??
              document.getElementById(toggleId);

    if (!toggle) return;

    const hostNode = toggle.closest('.subscription-tab, .lp-pricing-section');
    if (!hostNode || !(hostNode instanceof HTMLElement)) return;
    const hostEl: HTMLElement = hostNode;

    const toggleEl = toggle;
    const priceBlocks = hostEl.querySelectorAll<HTMLElement>('[data-price-tier], [data-price-monthly][data-price-annual]');

    function setBilling(mode: BillingMode): void {
        hostEl.dataset.billing = mode;
        toggleEl.setAttribute('aria-checked', String(mode === 'annual'));

        priceBlocks.forEach((block) => {
            if (block.dataset.priceTier) {
                updatePriceBlock(block, mode);
                return;
            }
            const amountEl = block.querySelector<HTMLElement>('.lp-pricing-amount');
            if (!amountEl) return;
            const monthly = block.dataset.priceMonthly;
            const annual = block.dataset.priceAnnual;
            if (monthly && annual) amountEl.textContent = mode === 'annual' ? annual : monthly;

            const originalEl = block.querySelector<HTMLElement>('.lp-pricing-original-amount');
            const origMonthly = block.dataset.originalMonthly;
            const origAnnual = block.dataset.originalAnnual;
            if (originalEl && origMonthly && origAnnual) {
                originalEl.textContent = mode === 'annual' ? `$${origAnnual}` : `$${origMonthly}`;
            }
        });

        updateCheckoutTargets(hostEl, mode);
    }

    toggleEl.addEventListener('click', () => {
        setBilling(hostEl.dataset.billing === 'annual' ? 'monthly' : 'annual');
    });

    setBilling((hostEl.dataset.billing as BillingMode) || 'monthly');
}
