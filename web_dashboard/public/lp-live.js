/**
 * LP Live Engine - production API sync, rotating alert stream cards.
 */
(function () {
  const ALERT_CARD_COUNT = 6;
  const HERO_STREAM_COUNT = 9;
  const ROTATE_MS = 4200;
  const FRESHNESS_TICK_MS = 30000;
  const FETCH_LIMIT = 96;

  // Copy for the two non-live states. They are different facts: 'error' is a transport
  // failure, 'empty' is a measured absence of qualifying rows. Never collapse them.
  const EMPTY_COPY = {
    error: {
      showcase: 'signal feed unreachable · retry on next load',
      hero: 'feed unreachable',
    },
    empty: {
      showcase: 'no signals cleared the stream threshold in the last 24h',
      hero: 'no signals in the last 24h',
    },
  };

  const TOPIC_LABELS = {
    energy_resource_risk: { label: 'Energy & Resource Risk', color: '#d29922' },
    global_market_intelligence: { label: 'Global Market Intel', color: '#58a6ff' },
    crypto_geopolitics: { label: 'Crypto & Geopolitics', color: '#db6d28' },
    ai_semiconductor_intelligence: { label: 'AI & Semiconductors', color: '#bc8cff' },
    defense_technology: { label: 'Defense Technology', color: '#f85149' },
    supply_chain_intelligence: { label: 'Supply Chain Intel', color: '#3fb950' },
    supply_chain_disruption: { label: 'Supply Chain Intel', color: '#3fb950' },
    global: { label: 'Global Briefing', color: '#58a6ff' },
  };

  // mode is one of 'live' | 'empty' | 'error'. There is no 'fallback' any more: the
  // synthetic pool that used to back it was deleted, so an unsuccessful load now
  // renders a stated condition rather than invented rows.
  const state = {
    mode: 'error',
    alertPool: [],
    heroOffset: 0,
    lastFetchedAt: null,
    newestDataAt: null,
    rotateTimer: null,
    freshnessTimer: null,
  };

  function topicMeta(topic) {
    const key = (topic || 'global').toLowerCase();
    return TOPIC_LABELS[key] || { label: (topic || 'Global').replace(/_/g, ' '), color: '#58a6ff' };
  }

  function resolveTimestamp(item) {
    if (!item) return null;
    return item.triggered_at || item.timestamp || item.generated_at || null;
  }

  function parseTimestamp(iso) {
    if (iso == null || iso === '') return null;
    let s = String(iso).trim();
    if (!s) return null;
    if (/^\d{4}-\d{2}-\d{2}\s/.test(s)) s = s.replace(' ', 'T');
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function timestampMs(item) {
    const d = parseTimestamp(resolveTimestamp(item));
    return d ? d.getTime() : 0;
  }

  function sortByTimestampDesc(pool) {
    return [...pool].sort((a, b) => timestampMs(b) - timestampMs(a));
  }

  function newestIsoFromPools(...pools) {
    let max = 0;
    pools.flat().forEach((item) => {
      const ms = timestampMs(item);
      if (ms > max) max = ms;
    });
    return max ? new Date(max).toISOString() : null;
  }

  function formatRelativeFromNow(iso) {
    const d = parseTimestamp(iso);
    if (!d) return 'just now';
    const mins = Math.floor((Date.now() - d.getTime()) / 60000);
    if (mins < 1) return 'just now';
    if (mins === 1) return '1 min ago';
    if (mins < 60) return mins + ' mins ago';
    const hours = Math.floor(mins / 60);
    if (hours === 1) return '1 hour ago';
    if (hours < 24) return hours + ' hours ago';
    const days = Math.floor(hours / 24);
    return days === 1 ? '1 day ago' : days + ' days ago';
  }

  function formatDisplayDateJa(iso) {
    if (!iso) return '—';
    const d = parseTimestamp(iso);
    if (!d) return String(iso);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    return d.getMonth() + 1 + '月' + d.getDate() + '日 ' + h + ':' + m;
  }

  /** Same-day: absolute JP time; within 7d: relative; older: absolute date. */
  function formatDisplayTimestamp(iso) {
    if (!iso) return '—';
    const d = parseTimestamp(iso);
    if (!d) return String(iso);
    const now = new Date();
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate();
    if (sameDay) return formatDisplayDateJa(iso);
    const diffMs = now.getTime() - d.getTime();
    if (diffMs >= 0 && diffMs < 7 * 24 * 60 * 60 * 1000) {
      const mins = Math.floor(diffMs / 60000);
      if (mins < 1) return 'たった今';
      if (mins < 60) return mins + '分前';
      const hours = Math.floor(mins / 60);
      if (hours < 24) return hours + '時間前';
      const days = Math.floor(hours / 24);
      return days + '日前';
    }
    return formatDisplayDateJa(iso);
  }

  function pickCount(primary, fallbackLen) {
    if (typeof primary === 'number' && Number.isFinite(primary)) return Math.max(0, Math.floor(primary));
    if (typeof primary === 'string' && primary.trim() !== '' && !Number.isNaN(Number(primary))) {
      return Math.max(0, Math.floor(Number(primary)));
    }
    return typeof fallbackLen === 'number' ? Math.max(0, fallbackLen) : 0;
  }

  function topicCssVars(topic) {
    const meta = topicMeta(topic);
    return `--topic-color:${meta.color};--domain-accent:${meta.color};`;
  }

  function cleanTitle(raw) {
    if (!raw) return 'Strategic Intelligence Alert';
    return raw
      .replace(/^(acceleration|entity_surge|pattern_risk|sector_surge|event_continuation)\s*:\s*/i, '')
      .trim() || raw;
  }

  function severityClass(sev) {
    const s = (sev || 'watch').toLowerCase();
    if (s === 'critical' || s === 'high') return 'critical';
    if (s === 'elevated' || s === 'medium') return 'elevated';
    return 'watch';
  }

  function severityLabel(sev) {
    return severityClass(sev).toUpperCase();
  }

  function hasUsableSources(alert) {
    if (!alert) return false;
    if (Array.isArray(alert.sources) && alert.sources.length > 0) return true;
    if (Array.isArray(alert.evidence_list) && alert.evidence_list.length > 0) return true;
    return false;
  }

  function sourceCount(alert) {
    if (!alert) return 0;
    if (Array.isArray(alert.sources) && alert.sources.length) return alert.sources.length;
    if (Array.isArray(alert.evidence_list) && alert.evidence_list.length) return alert.evidence_list.length;
    if (typeof alert.sources_count === 'number' && Number.isFinite(alert.sources_count)) {
      return Math.max(0, Math.floor(alert.sources_count));
    }
    if (typeof alert.source_count === 'number' && Number.isFinite(alert.source_count)) {
      return Math.max(0, Math.floor(alert.source_count));
    }
    if (Array.isArray(alert.related_news) && alert.related_news.length) return alert.related_news.length;
    return pickCount(alert.related_news_count, 0);
  }

  function itemStableId(item) {
    const id = item && (item.id ?? item.alert_id);
    return id != null && String(id).trim() !== '' ? String(id).trim() : '';
  }

  function titleDedupeKey(item) {
    const title = cleanTitle(item && (item.title || item.target_label || ''))
      .toLowerCase()
      .replace(/\s+/g, ' ')
      .trim();
    if (!title || title === 'strategic intelligence alert') return '';
    const topic = String((item && item.topic) || 'global')
      .toLowerCase()
      .trim();
    return topic + '::' + title;
  }

  function dedupeKey(item, kind) {
    const id = itemStableId(item);
    if (id) return kind + ':id:' + id;
    const titleKey = titleDedupeKey(item);
    if (titleKey) return kind + ':title:' + titleKey;
    return kind + ':ts:' + String(timestampMs(item));
  }

  /** Keep the newest row per id/title key. */
  function dedupeNewestFirst(items, kind) {
    const best = new Map();
    items.forEach((item) => {
      const key = dedupeKey(item, kind);
      const prev = best.get(key);
      if (!prev || timestampMs(item) >= timestampMs(prev)) {
        best.set(key, item);
      }
    });
    return [...best.values()];
  }

  function passesAlertQuality(alert) {
    if (!alert) return false;
    if (!hasUsableSources(alert)) return false;
    const title = cleanTitle(alert.title || alert.target_label || '');
    if (!title || title.length < 4) return false;
    return true;
  }

  function mergeUniquePools(primary, supplement, kind, minSize) {
    const seen = new Set();
    const out = [];
    const pushUnique = (list) => {
      list.forEach((item) => {
        const key = dedupeKey(item, kind);
        if (seen.has(key)) return;
        seen.add(key);
        out.push(item);
      });
    };
    pushUnique(primary);
    // The supplement branch is gone with FALLBACK_LIVE. `supplement` and `minSize` are
    // now unread; the signature is kept so the dedupe contract is unchanged for any
    // future second pool. A short pool stays short — it is never padded.
    return sortByTimestampDesc(out);
  }

  /**
   * Quality-filter and de-duplicate. Never clones rows and never pads: the pool is
   * exactly what the endpoint returned, minus duplicates and sourceless rows.
   */
  function prepareShowcasePool(rawItems, fallbackItems, minPoolSize) {
    const primary = sortByTimestampDesc(
      dedupeNewestFirst(
        (rawItems || []).map(normalizeLiveAlert).filter(passesAlertQuality),
        'alert',
      ),
    );

    return mergeUniquePools(primary, [], 'alert', minPoolSize);
  }

  function normalizeLiveAlert(raw) {
    const evidence = Array.isArray(raw.evidence_list) ? raw.evidence_list : [];
    const count = sourceCount(raw);
    return {
      ...raw,
      triggered_at: resolveTimestamp(raw),
      evidence_list: evidence,
      sources_count: count,
    };
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function windowItems(pool, offset, count) {
    const sorted = sortByTimestampDesc(pool);
    if (!sorted.length) return [];
    const out = [];
    const limit = Math.min(count, sorted.length);
    for (let i = 0; i < limit; i += 1) {
      out.push(sorted[(offset + i) % sorted.length]);
    }
    return out;
  }

  function newestItems(pool, count) {
    return sortByTimestampDesc(pool).slice(0, Math.min(count, pool.length));
  }

  function fillDisplaySlots(pool, count) {
    return newestItems(pool, count);
  }

  function updateFreshnessBadges() {
    const sectionEl = document.getElementById('lp-terminal-freshness');
    const live = state.mode === 'live';
    if (!sectionEl) return;

    // A freshness badge reports freshness. With no rows there is none to report, and
    // the panels already state the condition — one fact, one place. Hidden, not reworded.
    if (!live) {
      sectionEl.hidden = true;
      sectionEl.textContent = '';
      sectionEl.removeAttribute('title');
      return;
    }

    const nowIso = new Date().toISOString();
    const dataLabel = state.newestDataAt
      ? 'LAST UPDATED: ' + formatRelativeFromNow(state.newestDataAt)
      : 'SYNCED: ' + formatDisplayDateJa(nowIso);
    // Disclose a short pool rather than padding it. Renders only when it is true.
    const shortfall =
      state.alertPool.length < ALERT_CARD_COUNT
        ? ' · ' + state.alertPool.length + ' SIGNALS'
        : '';
    sectionEl.hidden = false;
    sectionEl.textContent = dataLabel + shortfall;
    sectionEl.title = state.newestDataAt
      ? 'Newest signal: ' + formatDisplayDateJa(state.newestDataAt)
      : 'Synced with production API';
  }

  function setSyncBadge(mode) {
    const live = mode === 'live';
    // Sole writer of [data-lp-sync]. "LIVE" is dropped: the badge can only say that
    // real rows arrived, and the newest of them may be hours old. Age is reported once,
    // by #lp-terminal-freshness beside it.
    document.querySelectorAll('[data-lp-sync]').forEach((el) => {
      if (live) {
        el.hidden = false;
        el.className = 'lp-live-indicator';
        el.textContent = 'PRODUCTION DATA';
        el.setAttribute('data-lp-mode', 'live');
      } else {
        el.hidden = true;
        el.className = 'lp-live-indicator';
        el.textContent = '';
        el.setAttribute('data-lp-mode', mode);
        el.removeAttribute('title');
      }
    });
    // The hero status dot follows the same boolean. Without --live it renders
    // var(--lp-dim) from the base class, so no new colour is introduced.
    document.querySelectorAll('.lp-terminal-dot').forEach((el) => {
      el.classList.toggle('lp-terminal-dot--live', live);
    });
    updateFreshnessBadges();
  }

  function renderShowcasePanels(animate) {
    const alertRoot = document.getElementById('lp-alert-stream');
    renderAlerts(alertRoot, fillDisplaySlots(state.alertPool, ALERT_CARD_COUNT), animate);
  }

  function alertCardHtml(a, index) {
    const meta = topicMeta(a.topic);
    const sev = severityClass(a.severity);
    const sevText = severityLabel(a.severity);
    const title = cleanTitle(a.title || a.target_label);
    const ts = formatDisplayTimestamp(resolveTimestamp(a));
    const count = sourceCount(a);
    const vars = topicCssVars(a.topic);
    return `
      <div class="alert-card-compact severity-${sev} lp-alert-slot" data-slot="${index}" style="${vars}">
        <div class="alert-header u-flex-between">
          <div class="u-flex" style="gap:8px;align-items:center;">
            <span class="severity-badge ${sev}">${escapeHtml(sevText)}</span>
            <span class="timestamp">${escapeHtml(ts)}</span>
          </div>
          <div class="alert-header-meta">
            <span class="meta-item-topic meta-item-topic--tag">${escapeHtml(meta.label)}</span>
          </div>
        </div>
        <div class="alert-content-terminal">
          <div class="alert-main-row">
            <h3 class="alert-headline-compact">${escapeHtml(title)}</h3>
          </div>
          ${
            count > 0
              ? `<div class="source-terminal-row">
            <span class="source-label">SOURCES:</span>
            <a class="source-modal-trigger" href="app.html#feed">View Sources (${count})</a>
          </div>`
              : ''
          }
        </div>
      </div>`;
  }

  function emptyCopy(slot) {
    return (EMPTY_COPY[state.mode] || EMPTY_COPY.error)[slot];
  }

  function renderAlerts(container, alerts, animate) {
    if (!container) return;
    if (!alerts.length) {
      container.innerHTML = `<p class="lp-panel-empty lp-mono">${escapeHtml(emptyCopy('showcase'))}</p>`;
      return;
    }
    const html = alerts.slice(0, ALERT_CARD_COUNT).map((a, i) => alertCardHtml(a, i)).join('');
    if (animate) container.classList.add('lp-panel-swapping');
    container.innerHTML = html;
    if (animate) {
      requestAnimationFrame(() => {
        setTimeout(() => container.classList.remove('lp-panel-swapping'), 520);
      });
    }
  }

  function heroTopicTag(topic) {
    const key = (topic || 'global').toLowerCase();
    const short = {
      energy_resource_risk: 'ENR',
      global_market_intelligence: 'MKT',
      crypto_geopolitics: 'CRY',
      ai_semiconductor_intelligence: 'SEM',
      defense_technology: 'DEF',
      supply_chain_intelligence: 'SUP',
      supply_chain_disruption: 'SCD',
      global: 'GLB',
    };
    if (short[key]) return short[key];
    const parts = key.split('_').filter(Boolean);
    if (parts.length >= 2) return (parts[0].slice(0, 2) + parts[1].slice(0, 1)).toUpperCase();
    return (parts[0] || 'sig').slice(0, 3).toUpperCase();
  }

  function renderHeroTerminal(container, alerts) {
    if (!container) return;
    const rows = alerts.slice(0, HERO_STREAM_COUNT);
    if (!rows.length) {
      // Must WRITE, not return. index.html's static placeholder reads "Loading signal
      // stream…"; returning early here leaves that on screen permanently, which is a
      // worse claim than the one this commit removes.
      container.innerHTML =
        `<span class="lp-terminal-line lp-panel-empty">${escapeHtml(emptyCopy('hero'))}</span>`;
      return;
    }
    container.innerHTML = rows
      .map((a) => {
        const tag = heroTopicTag(a.topic);
        const tsIso = resolveTimestamp(a) || new Date().toISOString();
        const ts = formatDisplayTimestamp(tsIso);
        return `<span class="lp-terminal-line"><span class="ts">${ts}</span><span class="tag">${tag}</span><span class="val">${escapeHtml(cleanTitle(a.title || a.target_label))}</span></span>`;
      })
      .join('');
  }

  function tickRotate() {
    if (state.alertPool.length > HERO_STREAM_COUNT) {
      state.heroOffset = (state.heroOffset + 1) % state.alertPool.length;
    }
    renderShowcasePanels(true);
    renderHeroTerminal(
      document.querySelector('.lp-hero .lp-terminal-body'),
      windowItems(state.alertPool, state.heroOffset, HERO_STREAM_COUNT),
    );
  }

  function apiPrefix() {
    var meta = document.querySelector('meta[name="veltrixia-api-base"]');
    var origin = meta && meta.getAttribute('content');
    if (origin) return origin.replace(/\/$/, '') + '/api';
    return window.location.origin + '/api';
  }

  function apiUrl(path) {
    var rel = path.indexOf('/api') === 0 ? path.slice(4) : path;
    return apiPrefix() + rel;
  }

  async function fetchJson(path) {
    const sep = path.includes('?') ? '&' : '?';
    const url = apiUrl(path) + sep + '_ts=' + Date.now();
    const res = await fetch(url, {
      mode: 'cors',
      credentials: 'include',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    if (!res.ok) throw new Error(String(res.status));
    return res.json();
  }

  async function hydrate() {
    const alertRoot = document.getElementById('lp-alert-stream');
    const heroRoot = document.querySelector('.lp-hero .lp-terminal-body');

    let liveItems = [];
    // Anything that is not a successful array response is a transport failure until
    // proven otherwise; the try below narrows it.
    state.mode = 'error';
    state.heroOffset = 0;

    try {
      const live = await fetchJson(`/api/alerts?limit=${FETCH_LIMIT}`);
      if (Array.isArray(live)) {
        liveItems = sortByTimestampDesc(live.map(normalizeLiveAlert));
        // 200 with [] is a measured absence of qualifying rows, not a failed fetch.
        // They render different copy, so they must not collapse into one state here.
        state.mode = liveItems.length ? 'live' : 'empty';
      }
    } catch (err) {
      // fetchJson throws Error(String(res.status)) on a non-2xx, so the status survives
      // in the message. Surface it instead of swallowing it — a 429 (guest limit is
      // 5/min per IP on this endpoint) is a different problem from a network drop.
      state.mode = 'error';
      console.warn('[lp-live] alert fetch failed:', (err && err.message) || err);
    }

    state.lastFetchedAt = new Date().toISOString();
    state.newestDataAt = newestIsoFromPools(liveItems);

    state.alertPool = prepareShowcasePool(liveItems);

    renderShowcasePanels(false);
    renderHeroTerminal(heroRoot, fillDisplaySlots(state.alertPool, HERO_STREAM_COUNT));

    setSyncBadge(state.mode);

    if (alertRoot) {
      alertRoot.classList.remove('lp-panel-loading');
      alertRoot.removeAttribute('aria-busy');
    }

    if (state.rotateTimer) clearInterval(state.rotateTimer);
    state.rotateTimer = setInterval(tickRotate, ROTATE_MS);

    // No refetch timer. /api/alerts allows a guest 5 requests per 60s per IP
    // (api/rate_limit.py), a sixth of what /alerts/live allowed, and a shared egress IP
    // pools visitors against it. One page load now costs exactly one request.
    // rotateTimer and freshnessTimer stay: both are display-only and issue no requests.

    if (state.freshnessTimer) clearInterval(state.freshnessTimer);
    state.freshnessTimer = setInterval(updateFreshnessBadges, FRESHNESS_TICK_MS);

    document.dispatchEvent(
      new CustomEvent('lp-data-ready', {
        detail: { mode: state.mode, liveItems },
      })
    );
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', hydrate);
  } else {
    hydrate();
  }
})();
