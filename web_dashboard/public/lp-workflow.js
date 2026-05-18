/**
 * System Workflow — stage typing (left) + fleet-wide backend stream (right).
 */
(function () {
  const section = document.getElementById('workflow');
  if (!section) return;

  const steps = Array.from(section.querySelectorAll('.lp-pipe-step'));
  const stageLogRoot = document.getElementById('lp-stage-log');
  const stageLogBody = document.getElementById('lp-stage-log-body');
  const streamRoot = document.getElementById('lp-sys-stream');

  const STAGE_LINES = [
    [
      { tag: 'INGEST', cls: 'ingest', text: 'GET https://api.energy-intel.org/v3/updates?since=1715810400 → 200 OK (218ms)' },
      { tag: 'INGEST', cls: 'ingest', text: 'HEAD reuters.com/world/middle-east/transit-advisory → ETag 8f2a…c91 · 304 Not Modified' },
      { tag: 'INGEST', cls: 'ingest', text: 'manifest poll 2,847 feeds · batch 14/128 · TLS fingerprint OK' },
      { tag: 'INGEST', cls: 'ingest', text: 'retained 3/14 raw hits · sha256 dedupe · lang=en,ar verified' },
    ],
    [
      { tag: 'PROCESS', cls: 'process', text: 'NER: LOC[Strait of Hormuz] ORG[IRGC Navy] COMMODITY[Brent crude]' },
      { tag: 'PROCESS', cls: 'process', text: 'entity_link: Q3766 ↔ Wikidata · confidence 0.94' },
      { tag: 'PROCESS', cls: 'process', text: 'near-dup cluster #8821 collapsed · 11 → 2 canonical docs' },
      { tag: 'PROCESS', cls: 'process', text: 'trust_score=0.87 · consensus≥2 sources · tier=PRIMARY+MACRO' },
    ],
    [
      { tag: 'CONTEXT', cls: 'context', text: 'analogue: 2019-09 Hormuz incident · similarity 0.81' },
      { tag: 'CONTEXT', cls: 'context', text: 'macro_map: Brent $84.12 (+2.1%) · VLCC rates · US CPI 3.4% pass-through' },
      { tag: 'CONTEXT', cls: 'context', text: 'graph_edge: transit_restrict → supply_chain → energy_resource_risk' },
      { tag: 'CONTEXT', cls: 'context', text: 'attach_series: FRED DCOILBRENTEU · BEA IO energy column 324' },
    ],
    [
      { tag: 'INFER', cls: 'infer', text: 'scenario_fork: A=escalation (p=0.42) · B=contained (p=0.38) · C=noise (p=0.20)' },
      { tag: 'INFER', cls: 'infer', text: 'logic_check: no contradictions · evidence_coverage=HIGH' },
      { tag: 'INFER', cls: 'infer', text: 'brief_id=RPT-2026-0516-7F3A · citations=7 · chain_hash=0x9c4e…' },
      { tag: 'INFER', cls: 'infer', text: 'publish_queue: Context Brief ready · map pulse lat/lng locked' },
    ],
  ];

  const STREAM_POOL = [
    { tag: 'INGEST', cls: 'ingest', text: 'GET https://api.energy-intel.org/v3/updates → 200 OK (184ms)' },
    { tag: 'INGEST', cls: 'ingest', text: 'GET https://feeds.defense.gov/rss/exercises.xml → 200 OK (96ms)' },
    { tag: 'INGEST', cls: 'ingest', text: 'POST ingest-worker/claim batch=8821 · ack 14 docs' },
    { tag: 'INGEST', cls: 'ingest', text: 'HEAD bis.doc.gov/index.php/policy → 200 · cache-hit' },
    { tag: 'PROCESS', cls: 'process', text: 'tokenizer: 2,401 tokens · lang mix en:91% ar:9%' },
    { tag: 'PROCESS', cls: 'process', text: 'NER pipeline v2.4 · 38 entities · 6 LOC · 12 ORG' },
    { tag: 'PROCESS', cls: 'process', text: 'dedupe simhash Hamming≤3 · merged 9 pairs' },
    { tag: 'PROCESS', cls: 'process', text: 'trust_score dist: μ=0.74 σ=0.11 · floor=0.55' },
    { tag: 'CONTEXT', cls: 'context', text: 'GET fred.stlouisfed.org/series/DCOILBRENTEU → 200 (142ms)' },
    { tag: 'CONTEXT', cls: 'context', text: 'macro attach CPI YoY 3.4% · breakeven 2.31%' },
    { tag: 'CONTEXT', cls: 'context', text: 'knowledge_graph expand depth=2 · 44 edges' },
    { tag: 'CONTEXT', cls: 'context', text: 'analogue_retrieval top_k=5 · best=2019-Q3 Hormuz' },
    { tag: 'INFER', cls: 'infer', text: 'scenario_engine branch_count=3 · entropy=0.91' },
    { tag: 'INFER', cls: 'infer', text: 'consistency_solver SAT · 0 violations' },
    { tag: 'INGEST', cls: 'ingest', text: 'ws://stream.osint-hub.net/v1/ticker · connected' },
    { tag: 'PROCESS', cls: 'process', text: 'embedding batch cuda:0 · 512 dims · 22ms/doc' },
    { tag: 'CONTEXT', cls: 'context', text: 'VLCC spot TCE $42,800/day · delta +6.2%' },
    { tag: 'INFER', cls: 'infer', text: 'alert_id=fl-002 queued · severity=elevated' },
  ];

  let currentStage = 0;
  let typingGen = 0;
  let autoTimer = null;
  let streamTimer = null;
  let sectionVisible = false;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const stageForRatio = (r) => {
    if (r < 0.22) return 0;
    if (r < 0.48) return 1;
    if (r < 0.72) return 2;
    return 3;
  };

  const applyStepClasses = (stage) => {
    steps.forEach((el, i) => {
      el.classList.remove('is-active', 'is-done');
      if (i < stage) el.classList.add('is-done');
      else if (i === stage) el.classList.add('is-active');
    });
  };

  const flashScanline = () => {
    if (!stageLogRoot) return;
    stageLogRoot.classList.remove('is-stage-flash');
    void stageLogRoot.offsetWidth;
    stageLogRoot.classList.add('is-stage-flash');
    setTimeout(() => stageLogRoot.classList.remove('is-stage-flash'), 700);
  };

  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const typeChar = async (el, text, gen) => {
    if (prefersReducedMotion) {
      el.textContent = text;
      return;
    }
    el.textContent = '';
    const cursor = document.createElement('span');
    cursor.className = 'lp-stage-cursor';
    cursor.setAttribute('aria-hidden', 'true');
    el.appendChild(cursor);
    for (let i = 0; i < text.length; i += 1) {
      if (gen !== typingGen) return;
      el.insertBefore(document.createTextNode(text[i]), cursor);
      await sleep(10 + Math.random() * 8);
    }
    cursor.remove();
  };

  const renderStageLine = (entry) => {
    const row = document.createElement('div');
    row.className = `lp-stage-log-line lp-stage-log-line--${entry.cls}`;
    row.innerHTML = `<span class="lvl lvl--${entry.cls}">[${entry.tag}]</span> <span class="lp-stage-log-text"></span>`;
    const textEl = row.querySelector('.lp-stage-log-text');
    return { row, textEl, entry };
  };

  const runStageTyping = async (stage, gen) => {
    if (!stageLogBody) return;
    stageLogBody.innerHTML = '';
    const lines = STAGE_LINES[stage] || [];
    for (const entry of lines) {
      if (gen !== typingGen) return;
      const { row, textEl } = renderStageLine(entry);
      stageLogBody.appendChild(row);
      row.classList.add('is-typing');
      await typeChar(textEl, entry.text, gen);
      if (gen !== typingGen) return;
      row.classList.remove('is-typing');
      row.classList.add('is-complete');
      await sleep(120);
    }
  };

  const setStage = (stage, opts = {}) => {
    const next = Math.max(0, Math.min(3, stage));
    if (next === currentStage && !opts.force) return;
    currentStage = next;
    typingGen += 1;
    const gen = typingGen;
    applyStepClasses(next);
    flashScanline();
    runStageTyping(next, gen);
    if (opts.resetAuto) scheduleAutoAdvance();
  };

  const scheduleAutoAdvance = () => {
    if (autoTimer) clearTimeout(autoTimer);
    if (!sectionVisible) return;
    autoTimer = setTimeout(() => {
      const next = (currentStage + 1) % 4;
      setStage(next, { force: true, resetAuto: true });
    }, 7200);
  };

  const updateFromScroll = () => {
    const rect = section.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) return;
    const vh = window.innerHeight;
    const start = vh * 0.88;
    const end = vh * 0.12;
    const progress = (start - rect.top) / (start - end + rect.height * 0.4);
    const stage = stageForRatio(Math.min(1, Math.max(0, progress)));
    setStage(stage, { resetAuto: true });
  };

  /* ── Right panel: continuous backend stream ── */
  const tagClass = (cls) => `lp-log-tag lp-log-tag--${cls}`;

  const appendStreamLine = () => {
    if (!streamRoot || !document.body.contains(streamRoot)) return;
    const item = STREAM_POOL[Math.floor(Math.random() * STREAM_POOL.length)];
    const row = document.createElement('div');
    row.className = 'lp-sys-line is-new';
    row.innerHTML =
      `<span class="${tagClass(item.cls)} lp-mono">[${item.tag}]</span>` +
      `<span class="lp-sys-msg">${item.text}</span>`;
    streamRoot.appendChild(row);
    requestAnimationFrame(() => {
      row.classList.remove('is-new');
      row.classList.add('is-settled');
    });

    const maxVisible = 14;
    while (streamRoot.children.length > maxVisible) {
      const oldest = streamRoot.firstElementChild;
      if (!oldest) break;
      oldest.classList.add('is-exit');
      setTimeout(() => {
        if (oldest.parentNode) oldest.remove();
      }, 420);
      break;
    }
  };

  const startStream = () => {
    if (streamTimer || !streamRoot) return;
    appendStreamLine();
    const tick = () => {
      appendStreamLine();
      const delay = 280 + Math.random() * 420;
      streamTimer = setTimeout(tick, delay);
    };
    streamTimer = setTimeout(tick, 320);
  };

  const stopStream = () => {
    if (streamTimer) {
      clearTimeout(streamTimer);
      streamTimer = null;
    }
  };

  const io = new IntersectionObserver(
    (entries) => {
      sectionVisible = entries.some((e) => e.isIntersecting);
      if (sectionVisible) {
        setStage(currentStage, { force: true });
        scheduleAutoAdvance();
        startStream();
      } else {
        if (autoTimer) clearTimeout(autoTimer);
        stopStream();
      }
    },
    { threshold: 0.2 }
  );

  io.observe(section);
  window.addEventListener('scroll', updateFromScroll, { passive: true });
  window.addEventListener('resize', updateFromScroll, { passive: true });
})();
