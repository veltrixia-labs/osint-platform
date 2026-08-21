/**
 * System Workflow — timer-driven auto loop (no scroll coupling).
 */
(function () {
  const section = document.getElementById('workflow');
  if (!section) return;

  const steps = Array.from(section.querySelectorAll('.lp-pipe-step'));
  const stageLogRoot = document.getElementById('lp-stage-log');
  const stageLogBody = document.getElementById('lp-stage-log-body');

  const STAGE_MIN_MS = 5600;
  const STAGE_LOOP_GAP_MS = 1400;

  // These lines describe what each stage DOES. They carry no number, price, probability,
  // hash value, identifier or latency, because none of that is measured at render time —
  // the previous set invented all of it, including an upstream host (api.energy-intel.org)
  // that exists nowhere in this codebase. FRED and BEA are named because they are real
  // integrations (data_sources/fred_client.py, data_sources/bea_client.py, both driven by
  // jobs/external_data_sync.py); Wikidata and Reuters were removed because they are not.
  // sha256 is an algorithm name, verifiable at jobs/ingest_job.py:105, not a hash value.
  // The PROCESS cluster line describes jobs/alert_manager.py:955-994: prior headline keys
  // are matched inside ALERT_DEDUP_WINDOW_HOURS (:68) and a repeat is re-admitted when it
  // clears REIGNITE_INTENSITY_FACTOR (:69). It does NOT describe AlertLog.suppressed —
  // nothing in production writes that column; see this commit's message.
  const STAGE_LINES = [
    [
      { tag: 'INGEST', cls: 'ingest', text: 'feed_poll: registered rss sources · per-source batch · fields sanitised' },
      { tag: 'INGEST', cls: 'ingest', text: 'hash: payload serialised with sorted keys · sha256 digest per item' },
      { tag: 'INGEST', cls: 'ingest', text: 'dedupe: digests matched against stored set · only new items inserted' },
      { tag: 'INGEST', cls: 'ingest', text: 'retain: language and source country recorded · raw item persisted' },
    ],
    [
      { tag: 'PROCESS', cls: 'process', text: 'normalise: text cleaned · dedup key derived · duplicate items dropped' },
      { tag: 'PROCESS', cls: 'process', text: 'classify: keyword lexicon · word-boundary match · title-anchored gate' },
      { tag: 'PROCESS', cls: 'process', text: 'cluster: prior headlines matched in window · intensity decides re-entry' },
      { tag: 'PROCESS', cls: 'process', text: 'score: evidence density · cross-domain spread · importance assigned' },
    ],
    [
      { tag: 'CONTEXT', cls: 'context', text: 'related_events: same-domain window · clustered by topic · ranked' },
      { tag: 'CONTEXT', cls: 'context', text: 'macro_attach: FRED series · BEA industry tables · window aligned' },
      { tag: 'CONTEXT', cls: 'context', text: 'graph_edge: transit_restrict → supply_chain → energy_resource_risk' },
      { tag: 'CONTEXT', cls: 'context', text: 'exposure_map: transmission channels · sector linkage · watch indicators' },
    ],
    [
      { tag: 'INFER', cls: 'infer', text: 'compile: domain sections assembled · evidence bound per section' },
      { tag: 'INFER', cls: 'infer', text: 'logic_check: no contradictions · evidence_coverage=HIGH' },
      { tag: 'INFER', cls: 'infer', text: 'brief_assemble: sections ordered · citations attached · payload stored' },
      { tag: 'INFER', cls: 'infer', text: 'publish_queue: structural brief ready · map pulse lat/lng locked' },
    ],
  ];

  let typingGen = 0;
  let loopGen = 0;
  let sectionVisible = false;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const applyStepClasses = (stage) => {
    steps.forEach((el, i) => {
      el.classList.remove('is-active', 'is-done');
      if (i < stage) el.classList.add('is-done');
      else if (i === stage) el.classList.add('is-active');
    });
    section.dataset.workflowStage = String(stage + 1);
  };

  const flashScanline = () => {
    if (!stageLogRoot) return;
    stageLogRoot.classList.remove('is-stage-flash');
    void stageLogRoot.offsetWidth;
    stageLogRoot.classList.add('is-stage-flash');
    setTimeout(() => stageLogRoot.classList.remove('is-stage-flash'), 700);
  };

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

  const runStageTyping = async (stage, gen) => {
    if (!stageLogBody) return;
    stageLogBody.innerHTML = '';
    const lines = STAGE_LINES[stage] || [];
    for (const entry of lines) {
      if (gen !== typingGen) return;
      const row = document.createElement('div');
      row.className = `lp-stage-log-line lp-stage-log-line--${entry.cls}`;
      row.innerHTML = `<span class="lvl lvl--${entry.cls}">[${entry.tag}]</span> <span class="lp-stage-log-text"></span>`;
      const textEl = row.querySelector('.lp-stage-log-text');
      stageLogBody.appendChild(row);
      row.classList.add('is-typing');
      await typeChar(textEl, entry.text, gen);
      if (gen !== typingGen) return;
      row.classList.remove('is-typing');
      row.classList.add('is-complete');
      await sleep(100);
    }
  };

  const enterStage = (stage) => {
    typingGen += 1;
    applyStepClasses(stage);
    flashScanline();
    return typingGen;
  };

  const runAutoLoop = async (startStage, token) => {
    let stage = startStage;
    while (sectionVisible && token === loopGen) {
      const gen = enterStage(stage);
      const typingDone = runStageTyping(stage, gen);
      const minHold = sleep(STAGE_MIN_MS);
      await Promise.all([typingDone, minHold]);
      if (!sectionVisible || token !== loopGen || gen !== typingGen) return;

      const next = (stage + 1) % 4;
      if (next === 0) {
        section.classList.add('is-loop-reset');
        await sleep(STAGE_LOOP_GAP_MS);
        section.classList.remove('is-loop-reset');
      }
      stage = next;
    }
  };

  const startLoop = () => {
    loopGen += 1;
    const token = loopGen;
    section.classList.add('is-auto-running');
    applyStepClasses(0);
    runAutoLoop(0, token);
  };

  const stopLoop = () => {
    loopGen += 1;
    typingGen += 1;
    section.classList.remove('is-auto-running', 'is-loop-reset');
    section.removeAttribute('data-workflow-stage');
  };

  const onSectionEnter = () => {
    sectionVisible = true;
    startLoop();
  };

  const onSectionLeave = () => {
    sectionVisible = false;
    stopLoop();
    applyStepClasses(0);
    if (stageLogBody) stageLogBody.innerHTML = '';
  };

  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) onSectionEnter();
        else onSectionLeave();
      });
    },
    { threshold: 0.22 }
  );

  io.observe(section);
})();
