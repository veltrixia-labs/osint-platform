/**
 * LP interactions: scroll-driven workflow stages + live system log stream + alert tick.
 */
(function () {
  /* ── Scroll-driven pipeline (System Workflow) ── */
  const section = document.getElementById('lp-preview');
  if (section) {
    const steps = Array.from(section.querySelectorAll('.lp-pipe-step'));
    const logLines = Array.from(section.querySelectorAll('.lp-log-line'));

    const stageForRatio = (r) => {
      if (r < 0.22) return 0;
      if (r < 0.48) return 1;
      if (r < 0.72) return 2;
      return 3;
    };

    const visibleForStage = (stage) => {
      const counts = [3, 5, 7, logLines.length];
      return counts[Math.min(stage, counts.length - 1)];
    };

    const applyStage = (stage) => {
      steps.forEach((el, i) => {
        el.classList.remove('is-active', 'is-done');
        if (i < stage) el.classList.add('is-done');
        else if (i === stage) el.classList.add('is-active');
      });
      const n = visibleForStage(stage);
      logLines.forEach((line, i) => line.classList.toggle('is-visible', i < n));
    };

    const update = () => {
      const rect = section.getBoundingClientRect();
      const vh = window.innerHeight;
      const start = vh * 0.88;
      const end = vh * 0.12;
      const progress = (start - rect.top) / (start - end + rect.height * 0.4);
      applyStage(stageForRatio(Math.min(1, Math.max(0, progress))));
    };

    applyStage(0);
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update, { passive: true });
  }

  /* ── Auto-streaming backend log (when terminal panel is visible) ── */
  const streamRoot = document.getElementById('lp-sys-stream');
  if (streamRoot) {
    const lines = [
      '[INGEST] Polling 2,847 sources...',
      '[PROCESS] Identifying high-fidelity signals in Energy/Defense...',
      "[CONTEXT] Linking 'Hormuz Strait' to 'Global Oil Supply Chain'...",
      '[INFER] Generating Scenario A (Escalation) vs Scenario B (De-escalation)...',
      '[INGEST] Candidate: United States Ambivalent to Russian Oil Sanctions',
      '[PROCESS] Consensus filter: ≥2 independent sources',
      '[CONTEXT] Macro attach: Brent · VLCC · CPI pass-through',
      '[INFER] Brief ready — evidence chain attached',
    ];

    let idx = 0;
    const maxVisible = 6;

    const tagClass = (text) => {
      if (text.startsWith('[INGEST]')) return 'lp-log-tag--ingest';
      if (text.startsWith('[PROCESS]')) return 'lp-log-tag--process';
      if (text.startsWith('[CONTEXT]')) return 'lp-log-tag--context';
      if (text.startsWith('[INFER]')) return 'lp-log-tag--infer';
      return '';
    };

    const appendLine = () => {
      const text = lines[idx % lines.length];
      idx += 1;

      const row = document.createElement('div');
      row.className = 'lp-sys-line is-new';
      const tag = text.match(/^\[[^\]]+\]/)?.[0] || '';
      const body = text.replace(/^\[[^\]]+\]\s*/, '');
      row.innerHTML =
        `<span class="lp-log-tag ${tagClass(text)} lp-mono">${tag}</span>` +
        `<span class="lp-sys-msg">${body}</span>`;

      streamRoot.appendChild(row);
      requestAnimationFrame(() => row.classList.remove('is-new'));

      while (streamRoot.children.length > maxVisible) {
        streamRoot.removeChild(streamRoot.firstElementChild);
      }
    };

    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries.some((e) => e.isIntersecting);
        if (visible && !streamRoot.dataset.running) {
          streamRoot.dataset.running = '1';
          appendLine();
          const timer = setInterval(() => {
            if (!document.body.contains(streamRoot)) {
              clearInterval(timer);
              return;
            }
            appendLine();
          }, 2200);
          streamRoot.dataset.timer = String(timer);
        }
      },
      { threshold: 0.25 }
    );
    io.observe(streamRoot);
  }

  function startHeroPulse() {
    const heroLines = document.querySelectorAll('.lp-terminal-body .lp-terminal-line');
    if (!heroLines.length) return;
    let hi = 0;
    setInterval(() => {
      heroLines.forEach((el, i) => el.classList.toggle('is-hot', i === hi));
      hi = (hi + 1) % heroLines.length;
    }, 2800);
  }

  startHeroPulse();
  document.addEventListener('lp-data-ready', startHeroPulse);
})();
