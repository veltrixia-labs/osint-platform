/**
 * LP Live Engine — production API sync, 4×4 rotating cards, map pulse linkage.
 */
(function () {
  const CARD_COUNT = 4;
  const HERO_STREAM_COUNT = 9;
  const ROTATE_MS = 4200;
  const FETCH_LIMIT = 24;

  const TOPIC_LABELS = {
    energy_resource_risk: { label: 'Energy & Resource Risk', color: '#d29922' },
    global_market_intelligence: { label: 'Global Market Intel', color: '#58a6ff' },
    crypto_geopolitics: { label: 'Crypto & Geopolitics', color: '#db6d28' },
    ai_semiconductor_intelligence: { label: 'AI & Semiconductors', color: '#bc8cff' },
    defense_technology: { label: 'Defense Technology', color: '#f85149' },
    supply_chain_intelligence: { label: 'Supply Chain Intel', color: '#3fb950' },
    supply_chain_disruption: { label: 'Supply Chain Disruption', color: '#3fb950' },
    global: { label: 'Global Briefing', color: '#58a6ff' },
  };

  const FALLBACK_FREE = [
    {
      alert_id: 'fb-001',
      title: 'United States Ambivalent to Russian Oil Sanctions',
      target_label: 'United States Ambivalent to Russian Oil Sanctions',
      topic: 'energy_resource_risk',
      triggered_at: '2026-05-03T08:40:56.000Z',
      related_news_count: 3,
      related_entities_count: 0,
      context_chain: ['Russian oil output', 'maritime sanctions', 'Brent repricing'],
      content_markdown:
        '## Summary\nReport: Russian Oil Output Falls After Ukrainian Drone Strikes. EU defers maritime services ban.',
    },
    {
      alert_id: 'fb-002',
      title: 'Semiconductor fab input — export control ripple',
      target_label: 'Semiconductor fab input — export control ripple',
      topic: 'supply_chain_intelligence',
      triggered_at: '2026-05-02T14:22:00.000Z',
      related_news_count: 7,
      related_entities_count: 14,
      context_chain: ['export notice', 'fab inputs', 'lead times'],
      content_markdown: '## Summary\nAdvanced semiconductor inputs flagged across tier-2 suppliers.',
    },
    {
      alert_id: 'fb-003',
      title: 'Strait transit advisory — commercial lane restriction',
      target_label: 'Strait transit advisory — commercial lane restriction',
      topic: 'energy_resource_risk',
      triggered_at: '2026-05-02T09:15:00.000Z',
      related_news_count: 5,
      related_entities_count: 8,
      context_chain: ['Hormuz transit', 'VLCC rates', 'crude flows'],
      content_markdown: '## Summary\nCommercial lane restriction linked to VLCC operator exposure.',
    },
    {
      alert_id: 'fb-004',
      title: 'Defense procurement surge — dual-use components',
      target_label: 'Defense procurement surge — dual-use components',
      topic: 'defense_technology',
      triggered_at: '2026-05-01T18:40:00.000Z',
      related_news_count: 4,
      related_entities_count: 11,
      context_chain: ['procurement notice', 'dual-use', 'supply guard'],
      content_markdown: '## Summary\nDual-use component demand spike across NATO supply chains.',
    },
    {
      alert_id: 'fb-005',
      title: 'Rates desk — CPI pass-through watch activated',
      target_label: 'Rates desk — CPI pass-through watch activated',
      topic: 'global_market_intelligence',
      triggered_at: '2026-05-01T11:05:00.000Z',
      related_news_count: 6,
      related_entities_count: 3,
      context_chain: ['CPI print', 'rates', 'FX volatility'],
      content_markdown: '## Summary\nMacro series linkage activated for cross-asset pass-through.',
    },
  ];

  const FALLBACK_LIVE = [
    {
      id: 'fl-001',
      title: 'United States Ambivalent to Russian Oil Sanctions',
      target_label: 'United States Ambivalent to Russian Oil Sanctions',
      topic: 'energy_resource_risk',
      severity: 'elevated',
      triggered_at: '2026-05-03T08:40:56.000Z',
      related_news_count: 3,
    },
    {
      id: 'fl-002',
      title: 'Strait of Hormuz — commercial transit advisory',
      target_label: 'Strait of Hormuz — commercial transit advisory',
      topic: 'energy_resource_risk',
      severity: 'critical',
      triggered_at: '2026-05-03T07:12:00.000Z',
      location_lat: 26.56,
      location_lng: 56.25,
      related_news_count: 3,
    },
    {
      id: 'fl-003',
      title: 'Strategic AI Infrastructure Surge',
      target_label: 'Strategic AI Infrastructure Surge',
      topic: 'ai_semiconductor_intelligence',
      severity: 'high',
      triggered_at: '2026-05-03T06:30:00.000Z',
      location_lat: 37.3871,
      location_lng: -121.9667,
    },
    {
      id: 'fl-004',
      title: 'Taiwan Strait — elevated airspace notices',
      target_label: 'Taiwan Strait — elevated airspace notices',
      topic: 'defense_technology',
      severity: 'elevated',
      triggered_at: '2026-05-02T22:18:00.000Z',
      location_lat: 23.6978,
      location_lng: 120.9605,
    },
    {
      id: 'fl-005',
      title: 'Ukraine border — energy infrastructure strike pattern',
      target_label: 'Ukraine border — energy infrastructure strike pattern',
      topic: 'energy_resource_risk',
      severity: 'critical',
      triggered_at: '2026-05-02T19:44:00.000Z',
      location_lat: 48.3794,
      location_lng: 31.1656,
    },
    {
      id: 'fl-006',
      title: 'Supply chain disruption — port congestion index',
      target_label: 'Supply chain disruption — port congestion index',
      topic: 'supply_chain_disruption',
      severity: 'elevated',
      triggered_at: '2026-05-02T16:02:00.000Z',
      related_news_count: 9,
    },
  ];

  const GEOPOLITICAL_MARKERS = [
    { name: 'Hormuz Strait', lat: 26.56, lng: 56.25, level: 'critical' },
    { name: 'Taiwan Strait', lat: 24.0, lng: 121.0, level: 'elevated' },
    { name: 'Ukraine', lat: 48.3794, lng: 31.1656, level: 'critical' },
    { name: 'South China Sea', lat: 15.0, lng: 115.0, level: 'watch' },
  ];

  const state = {
    mode: 'fallback',
    alertPool: [],
    briefPool: [],
    livePool: [],
    alertOffset: 0,
    briefOffset: 0,
    mapHighlightIndex: 0,
    rotateTimer: null,
  };

  function topicMeta(topic) {
    const key = (topic || 'global').toLowerCase();
    return TOPIC_LABELS[key] || { label: (topic || 'Global').replace(/_/g, ' '), color: '#58a6ff' };
  }

  function formatTs(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'UTC',
      timeZoneName: 'short',
    });
  }

  function cleanTitle(raw) {
    if (!raw) return 'Strategic Intelligence Alert';
    return raw
      .replace(/^(acceleration|entity_surge|pattern_risk|sector_surge|event_continuation)\s*:\s*/i, '')
      .trim() || raw;
  }

  function extractTeaser(md) {
    if (!md) return 'Structured context and evidence — open full brief.';
    let t = md.replace(/^#\s+[^\n]*\n?/m, '').trim();
    const m = t.match(/##\s*Summary[^\n]*\n+([\s\S]*?)(?=\n##|\n*$)/i);
    if (m) t = m[1].trim();
    t = t.replace(/\*\*/g, '').replace(/\s+/g, ' ').trim();
    if (t.length > 120) return t.slice(0, 120).trim() + '…';
    return t;
  }

  function contextChainFromItem(item) {
    if (Array.isArray(item.context_chain) && item.context_chain.length) {
      return item.context_chain;
    }
    const news = item.related_news;
    if (Array.isArray(news) && news.length) {
      return news.slice(0, 3).map((n) => {
        const t = (n.title || n.source || 'source').trim();
        return t.length > 28 ? t.slice(0, 28) + '…' : t;
      });
    }
    const topic = (item.topic || '').toLowerCase();
    const defaults = {
      energy_resource_risk: ['signal spike', 'oil supply', 'shipping lane'],
      supply_chain_intelligence: ['port delay', 'inputs', 'lead time'],
      supply_chain_disruption: ['congestion', 'routes', 'inventory'],
      defense_technology: ['procurement', 'dual-use', 'alliance'],
      global_market_intelligence: ['macro', 'rates', 'FX'],
    };
    return defaults[topic] || ['event', 'context', 'linkage'];
  }

  function severityClass(sev) {
    const s = (sev || 'watch').toLowerCase();
    if (s === 'critical' || s === 'high') return 'critical';
    if (s === 'elevated' || s === 'medium') return 'elevated';
    return 'watch';
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function expandPool(pool, fallback) {
    const base = pool.length ? [...pool] : [];
    let i = 0;
    while (base.length < Math.max(CARD_COUNT * 2, HERO_STREAM_COUNT + 2)) {
      base.push(fallback[i % fallback.length]);
      i += 1;
    }
    return base;
  }

  function windowItems(pool, offset, count) {
    const out = [];
    for (let i = 0; i < count; i += 1) {
      out.push(pool[(offset + i) % pool.length]);
    }
    return out;
  }

  function setSyncBadge(mode) {
    document.querySelectorAll('[data-lp-sync]').forEach((el) => {
      el.classList.add('lp-neon-badge');
      const live = mode === 'live';
      el.textContent = live ? 'LIVE DATA' : 'SAMPLE';
      el.classList.toggle('lp-neon-badge--on', live);
      el.setAttribute('data-lp-mode', live ? 'live' : 'sample');
      el.title = live ? 'Synced with production API' : 'Canonical sample — API offline';
    });
  }

  function alertCardHtml(a, index) {
    const meta = topicMeta(a.topic);
    const sev = severityClass(a.severity);
    const title = cleanTitle(a.title || a.target_label);
    const ts = formatTs(a.triggered_at);
    const src =
      a.evidence_list?.length != null
        ? `${a.evidence_list.length} sources`
        : a.related_news_count != null
          ? `${a.related_news_count} sources`
          : 'live';
    return `
      <article class="lp-alert lp-alert-slot" data-slot="${index}" style="--lp-alert-topic:${meta.color}">
        <div class="lp-alert-meta">
          <span class="lp-alert-topic">${escapeHtml(meta.label)}</span>
          <span class="lp-alert-sev lp-alert-sev--${sev}">${sev.toUpperCase()}</span>
        </div>
        <h4 class="lp-alert-title">${escapeHtml(title)}</h4>
        <p class="lp-alert-ts lp-mono">${escapeHtml(ts)} · ${escapeHtml(String(src))}</p>
      </article>`;
  }

  function briefCardHtml(item, index) {
    const meta = topicMeta(item.topic);
    const title = cleanTitle(item.title || item.target_label);
    const chain = contextChainFromItem(item);
    const chainHtml = chain
      .map(
        (node, i) =>
          `<span class="lp-chain-node">${escapeHtml(node)}</span>` +
          (i < chain.length - 1 ? '<span class="lp-chain-arrow">→</span>' : '')
      )
      .join('');
    return `
      <article class="lp-brief-card lp-brief-slot" data-slot="${index}" style="border-left:3px solid ${meta.color}">
        <div class="lp-brief-head">
          <span class="lp-brief-chip" style="color:${meta.color}">${escapeHtml(meta.label)}</span>
          <span class="lp-brief-kind lp-mono">Context Brief</span>
        </div>
        <h4 class="lp-brief-title">${escapeHtml(title)}</h4>
        <div class="lp-brief-chain lp-mono" aria-label="Context chain">${chainHtml}</div>
        <div class="lp-brief-stats lp-mono">
          <span class="lp-brief-stat">📰 ${item.related_news_count ?? 0} news</span>
          <span class="lp-brief-stat">🏢 ${item.related_entities_count ?? 0} entities</span>
        </div>
      </article>`;
  }

  function renderAlerts(container, alerts, animate) {
    if (!container) return;
    const html = alerts.slice(0, CARD_COUNT).map((a, i) => alertCardHtml(a, i)).join('');
    if (animate) container.classList.add('lp-panel-swapping');
    container.innerHTML = html;
    if (animate) {
      requestAnimationFrame(() => {
        setTimeout(() => container.classList.remove('lp-panel-swapping'), 520);
      });
    }
  }

  function renderBriefs(container, items, animate) {
    if (!container) return;
    const html = items.slice(0, CARD_COUNT).map((item, i) => briefCardHtml(item, i)).join('');
    if (animate) container.classList.add('lp-panel-swapping');
    container.innerHTML = html;
    if (animate) {
      requestAnimationFrame(() => {
        setTimeout(() => container.classList.remove('lp-panel-swapping'), 520);
      });
    }
  }

  function project(lat, lng, w, h) {
    return { x: (lng + 180) * (w / 360), y: (90 - lat) * (h / 180) };
  }

  function renderMap(svg, markers, activeIndex) {
    if (!svg) return;
    const g = svg.querySelector('#lp-map-markers');
    const labels = svg.querySelector('#lp-map-labels');
    if (!g) return;
    const w = 1000;
    const h = 420;
    g.innerHTML = markers
      .map((m, i) => {
        const { x, y } = project(m.lat, m.lng, w, h);
        const cls =
          m.level === 'critical'
            ? 'lp-map-dot--critical'
            : m.level === 'elevated'
              ? 'lp-map-dot--elevated'
              : 'lp-map-dot--std';
        const hot = i === activeIndex ? ' lp-map-marker--hot' : '';
        return `
        <g class="lp-map-marker${hot}" data-marker-index="${i}" transform="translate(${x},${y})">
          <circle class="lp-map-pulse-ring" r="10" fill="none" stroke="#58a6ff" stroke-width="1.2"/>
          <circle class="lp-map-pulse-ring lp-map-pulse-ring--delay" r="10" fill="none" stroke="#58a6ff" stroke-width="0.8"/>
          <circle class="lp-map-dot lp-map-pulse-neon ${cls}" r="5"/>
        </g>`;
      })
      .join('');
    if (labels) {
      labels.innerHTML = markers
        .map((m, i) => {
          const { x, y } = project(m.lat, m.lng, w, h);
          const hot = i === activeIndex ? ' lp-map-label--hot' : '';
          return `<text class="lp-map-label${hot}" x="${x + 10}" y="${y - 8}">${escapeHtml(m.name)}</text>`;
        })
        .join('');
    }
  }

  function markersFromAlerts(live, highlightAlert) {
    const fromAlerts = live
      .filter((a) => a.location_lat != null && a.location_lng != null)
      .map((a) => ({
        name: cleanTitle(a.target_label).slice(0, 24),
        lat: a.location_lat,
        lng: a.location_lng,
        level: severityClass(a.severity),
      }));
    const seen = new Set();
    const merged = [];
    [...GEOPOLITICAL_MARKERS, ...fromAlerts].forEach((m) => {
      const k = `${m.lat.toFixed(2)},${m.lng.toFixed(2)}`;
      if (seen.has(k)) return;
      seen.add(k);
      merged.push(m);
    });
    let activeIndex = 0;
    if (highlightAlert?.location_lat != null) {
      const hi = merged.findIndex(
        (m) =>
          Math.abs(m.lat - highlightAlert.location_lat) < 0.5 &&
          Math.abs(m.lng - highlightAlert.location_lng) < 0.5
      );
      if (hi >= 0) activeIndex = hi;
    }
    return { markers: merged.slice(0, 10), activeIndex };
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

  function heroAlerts(pool, offset) {
    return windowItems(pool, offset, HERO_STREAM_COUNT);
  }

  function renderHeroTerminal(container, alerts) {
    if (!container) return;
    const rows = alerts.length ? alerts.slice(0, HERO_STREAM_COUNT) : [];
    if (!rows.length) return;
    container.innerHTML = rows
      .map((a) => {
        const tag = heroTopicTag(a.topic);
        const d = new Date(a.triggered_at || Date.now());
        const ts = Number.isNaN(d.getTime()) ? '—' : d.toISOString().slice(11, 19) + 'Z';
        return `<span class="lp-terminal-line"><span class="ts">${ts}</span><span class="tag">${tag}</span><span class="val">${escapeHtml(cleanTitle(a.title || a.target_label))}</span></span>`;
      })
      .join('');
  }

  function tickRotate() {
    state.alertOffset = (state.alertOffset + 1) % state.alertPool.length;
    state.briefOffset = (state.briefOffset + 1) % state.briefPool.length;
    state.mapHighlightIndex = (state.mapHighlightIndex + 1) % GEOPOLITICAL_MARKERS.length;

    const alertRoot = document.getElementById('lp-alert-stream');
    const briefRoot = document.getElementById('lp-brief-grid');
    const mapSvg = document.getElementById('lp-world-map');

    const alerts = windowItems(state.alertPool, state.alertOffset, CARD_COUNT);
    const briefs = windowItems(state.briefPool, state.briefOffset, CARD_COUNT);

    renderAlerts(alertRoot, alerts, true);
    renderBriefs(briefRoot, briefs, true);

    const highlight = alerts[0];
    const { markers, activeIndex } = markersFromAlerts(state.livePool, highlight);
    const idx =
      highlight?.location_lat != null ? activeIndex : state.mapHighlightIndex % markers.length;
    renderMap(mapSvg, markers, idx);
    renderHeroTerminal(
      document.querySelector('.lp-hero .lp-terminal-body'),
      heroAlerts(state.alertPool, state.alertOffset)
    );
  }

  async function fetchJson(path) {
    const res = await fetch(path, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(String(res.status));
    return res.json();
  }

  async function hydrate() {
    const alertRoot = document.getElementById('lp-alert-stream');
    const briefRoot = document.getElementById('lp-brief-grid');
    const heroRoot = document.querySelector('.lp-hero .lp-terminal-body');
    const mapSvg = document.getElementById('lp-world-map');

    let freeItems = [...FALLBACK_FREE];
    let liveItems = [...FALLBACK_LIVE];
    state.mode = 'fallback';

    try {
      const [free, live] = await Promise.all([
        fetchJson(`/api/free/alerts?limit=${FETCH_LIMIT}`),
        fetchJson(`/api/alerts/live?limit=${FETCH_LIMIT}`),
      ]);
      if (Array.isArray(free) && free.length) {
        freeItems = free;
        state.mode = 'live';
      }
      if (Array.isArray(live) && live.length) {
        liveItems = live;
        state.mode = 'live';
      }
    } catch {
      /* fallback */
    }

    state.briefPool = expandPool(freeItems, FALLBACK_FREE);
    state.alertPool = expandPool(liveItems, FALLBACK_LIVE);
    state.livePool = liveItems;

    renderAlerts(alertRoot, windowItems(state.alertPool, 0, CARD_COUNT), false);
    renderBriefs(briefRoot, windowItems(state.briefPool, 0, CARD_COUNT), false);
    renderHeroTerminal(heroRoot, heroAlerts(state.alertPool, 0));

    const { markers, activeIndex } = markersFromAlerts(state.livePool, state.alertPool[0]);
    renderMap(mapSvg, markers, activeIndex);

    setSyncBadge(state.mode);

    [alertRoot, briefRoot].forEach((el) => {
      if (!el) return;
      el.classList.remove('lp-panel-loading');
      el.removeAttribute('aria-busy');
    });

    if (state.rotateTimer) clearInterval(state.rotateTimer);
    state.rotateTimer = setInterval(tickRotate, ROTATE_MS);

    document.dispatchEvent(
      new CustomEvent('lp-data-ready', {
        detail: { mode: state.mode, freeItems, liveItems },
      })
    );
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', hydrate);
  } else {
    hydrate();
  }
})();
