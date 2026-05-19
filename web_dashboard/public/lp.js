/**
 * LP interactions: hero terminal pulse + pricing billing toggle.
 * System Workflow: see lp-workflow.js
 */
(function () {
  let heroPulseTimer = null;

  function startHeroPulse() {
    const initial = document.querySelectorAll('.lp-hero .lp-terminal-body .lp-terminal-line');
    if (!initial.length) return;
    if (heroPulseTimer) clearInterval(heroPulseTimer);
    let hi = 0;
    heroPulseTimer = setInterval(() => {
      const lines = document.querySelectorAll('.lp-hero .lp-terminal-body .lp-terminal-line');
      if (!lines.length) return;
      lines.forEach((el, i) => el.classList.toggle('is-hot', i === hi));
      hi = (hi + 1) % lines.length;
    }, 2800);
  }

  /** Stripe Payment Link URLs — set when available; falls back to app.html#plans */
  const STRIPE_CHECKOUT = {
    pro: { monthly: '', annual: '' },
    experts: { monthly: '', annual: '' },
  };

  function initPricingBilling() {
    const section = document.getElementById('pricing');
    const toggle = document.getElementById('lp-billing-toggle');
    if (!section || !toggle) return;

    const priceBlocks = section.querySelectorAll('[data-price-tier], [data-price-monthly][data-price-annual]');
    const trialLinks = section.querySelectorAll('a[data-tier][data-href-monthly]');

    function setBilling(mode) {
      const annual = mode === 'annual';
      section.dataset.billing = mode;
      toggle.setAttribute('aria-checked', String(annual));

      priceBlocks.forEach((block) => {
        const amountEl = block.querySelector('.lp-pricing-amount');
        if (!amountEl) return;

        if (block.dataset.priceTier === 'pro' || block.dataset.priceTier === 'experts') {
          const monthly = block.dataset.priceMonthly;
          const annualAmt = block.dataset.priceAnnual;
          if (monthly && annualAmt) amountEl.textContent = annual ? annualAmt : monthly;
        }

        const originalEl = block.querySelector('.lp-pricing-original-amount');
        const origM = block.dataset.originalMonthly;
        const origA = block.dataset.originalAnnual;
        if (originalEl && origM && origA) {
          originalEl.textContent = annual ? '$' + origA : '$' + origM;
        }
      });

      trialLinks.forEach((link) => {
        const tier = link.dataset.tier;
        const stripeUrl = tier && STRIPE_CHECKOUT[tier] ? STRIPE_CHECKOUT[tier][mode] : '';
        const fallback = annual ? link.dataset.hrefAnnual : link.dataset.hrefMonthly;
        link.href = stripeUrl || fallback || 'app.html#plans';
      });
    }

    toggle.addEventListener('click', () => {
      setBilling(section.dataset.billing === 'annual' ? 'monthly' : 'annual');
    });

    setBilling('monthly');
  }

  startHeroPulse();
  document.addEventListener('lp-data-ready', startHeroPulse);
  initPricingBilling();
})();
