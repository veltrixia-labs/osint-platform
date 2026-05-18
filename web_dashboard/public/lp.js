/**
 * LP scroll-driven dashboard preview — illustrates ingest → structure → scenario workflow.
 */
(function () {
  const section = document.getElementById('lp-preview');
  if (!section) return;

  const steps = Array.from(section.querySelectorAll('.lp-pipe-step'));
  const logLines = Array.from(section.querySelectorAll('.lp-log-line'));

  const stageForRatio = (r) => {
    if (r < 0.28) return 0;
    if (r < 0.58) return 1;
    return 2;
  };

  const applyStage = (stage) => {
    steps.forEach((el, i) => {
      el.classList.remove('is-active', 'is-done');
      if (i < stage) el.classList.add('is-done');
      else if (i === stage) el.classList.add('is-active');
    });

    const visibleCount =
      stage === 0 ? 4 : stage === 1 ? 7 : logLines.length;

    logLines.forEach((line, i) => {
      line.classList.toggle('is-visible', i < visibleCount);
    });
  };

  const update = () => {
    const rect = section.getBoundingClientRect();
    const vh = window.innerHeight;
    const start = vh * 0.85;
    const end = vh * 0.15;
    const progress = (start - rect.top) / (start - end + rect.height * 0.35);
    const clamped = Math.min(1, Math.max(0, progress));
    applyStage(stageForRatio(clamped));
  };

  applyStage(0);
  window.addEventListener('scroll', update, { passive: true });
  window.addEventListener('resize', update, { passive: true });
})();
