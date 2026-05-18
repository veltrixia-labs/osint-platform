/**
 * LP interactions: hero terminal pulse.
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

  startHeroPulse();
  document.addEventListener('lp-data-ready', startHeroPulse);
})();
