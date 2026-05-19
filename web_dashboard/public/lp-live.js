/**
 * LP Live Engine — production API sync, rotating alert & brief cards.
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
      related_entities_count: 14,
      sector_impacts: [
        { sector: 'Energy', matched_entities: 12 },
        { sector: 'Marine Transportation', matched_entities: 8 },
        { sector: 'Geopolitical Risk', matched_entities: 5 },
      ],
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
      sector_impacts: [
        { sector: 'Semiconductors', matched_entities: 9 },
        { sector: 'Global Markets', matched_entities: 6 },
        { sector: 'Defense Technology', matched_entities: 4 },
      ],
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
      sector_impacts: [
        { sector: 'Energy', matched_entities: 7 },
        { sector: 'Marine Transportation', matched_entities: 5 },
      ],
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
      sector_impacts: [
        { sector: 'Defense Technology', matched_entities: 10 },
        { sector: 'Military Ops', matched_entities: 6 },
      ],
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
      sector_impacts: [
        { sector: 'Global Markets', matched_entities: 8 },
        { sector: 'Finance', matched_entities: 4 },
      ],
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
      related_news_count: 3,
    },
    {
      id: 'fl-003',
      title: 'Strategic AI Infrastructure Surge',
      target_label: 'Strategic AI Infrastructure Surge',
      topic: 'ai_semiconductor_intelligence',
      severity: 'high',
      triggered_at: '2026-05-03T06:30:00.000Z',
    },
    {
      id: 'fl-004',
      title: 'Taiwan Strait — elevated airspace notices',
      target_label: 'Taiwan Strait — elevated airspace notices',
      topic: 'defense_technology',
      severity: 'elevated',
      triggered_at: '2026-05-02T22:18:00.000Z',
    },
    {
      id: 'fl-005',
      title: 'Ukraine border — energy infrastructure strike pattern',
      target_label: 'Ukraine border — energy infrastructure strike pattern',
      topic: 'energy_resource_risk',
      severity: 'critical',
      triggered_at: '2026-05-02T19:44:00.000Z',
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

  const state = {
    mode: 'fallback',
    alertPool: [],
    briefPool: [],
    alertOffset: 0,
    briefOffset: 0,
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

  function extractTeaser(markdown) {
    if (!markdown) {
      return 'Rule-based context, related news, and matched entities — open the full brief for detail.';
    }
    let t = markdown.replace(/^#\s+[^\n]*\n?/m, '').trim();
    const summaryMatch = t.match(/##\s*Summary[^\n]*\n+([\s\S]*?)(?=\n##|\n*$)/i);
    if (summaryMatch) t = summaryMatch[1].trim();
    else t = (t.split(/\n\n+/)[0] || t).replace(/^##[^\n]+\n/m, '').trim();
    t = t.replace(/\*\*([^*]+)\*\*/g, '$1').replace(/\s+/g, ' ').trim();
    if (t.length > 220) return t.slice(0, 220).trim() + '…';
    return t || 'Open the full brief for structured context and evidence.';
  }

  function classifySectorTagKind(sector) {
    const s = (sector || '').toLowerCase();
    if (/\b(oil|gas|lng|energy|petrol|crude|power)\b/.test(s)) return 'energy';
    if (/\b(marine|maritime|shipping|logistics|port|vessel|tanker|freight)\b/.test(s)) return 'marine';
    if (/\b(refin|industrial|manufact|chemic|materials|semiconductor)\b/.test(s)) return 'industry';
    if (/\b(finance|bank|market|macro|rates|fx)\b/.test(s)) return 'finance';
    if (/\b(defense|military|aerospace|security|nato|weapon)\b/.test(s)) return 'defense';
    return 'default';
  }

  function isRegionalSector(sector) {
    const s = (sector || '').trim().toLowerCase();
    return s === 'country' || s === 'geography' || s === 'region' || s.includes('geopolitical');
  }

  function sectorPillHtml(row) {
    const sector = row.sector || '';
    const matched = row.matched_entities ?? row.matched ?? 0;
    const regional = isRegionalSector(sector);
    const kind = classifySectorTagKind(sector);
    const base = regional
      ? 'cb-sector-pill cb-sector-pill--regional'
      : 'cb-sector-pill cb-sector-pill--structural cb-sector-pill--' + kind;
    return '<div class="' + base + '" role="listitem"><span class="cb-sector-pill-label">' + escapeHtml(sector) + '</span><span class="cb-sector-pill-count">' + matched + '</span></div>';
  }

  function briefSectorPreview(item, maxPills) {
    const rows = Array.isArray(item.sector_impacts) ? item.sector_impacts : [];
    if (!rows.length) return '';
    return '<div class="cb-brief-card-tags" role="list" aria-label="Structural exposure">' + rows.slice(0, maxPills || 6).map(sectorPillHtml).join('') + '</div>';
  }

  function briefCardHtml(item, index) {
    const meta = topicMeta(item.topic);
    const title = cleanTitle(item.title || item.target_label);
    const ts = formatTs(item.triggered_at);
    const teaser = escapeHtml(extractTeaser(item.content_markdown));
    const newsCount = item.related_news_count ?? 0;
    const entitiesCount = item.related_entities_count ?? 0;
    const topicVars = '--topic-color:' + meta.color + ';--domain-accent:' + meta.color + ';';
    const sectorTagsHtml = briefSectorPreview(item, 6);
    return (
      '<article class="pro-brief-card cb-brief-card lp-brief-slot" data-slot="' + index + '" data-domain-card="1" style="' + topicVars + '">' +
        '<div class="cb-brief-card-head u-flex-between">' +
          '<span class="domain-chip meta-item-topic--tag">' + escapeHtml(meta.label) + '</span>' +
          '<div class="cb-brief-card-head-meta">' +
            '<span class="cb-brief-kind">OSINT Intelligence Briefing</span>' +
            '<span class="cb-brief-ts">' + escapeHtml(ts) + '</span>' +
          '</div>' +
        '</div>' +
        '<h4 class="cb-brief-card-title">' + escapeHtml(title) + '</h4>' +
        '<p class="cb-brief-card-teaser">' + teaser + '</p>' +
        sectorTagsHtml +
        '<div class="cb-brief-card-stats" aria-label="Evidence counts">' +
          '<span class="cb-brief-stat-chip">📰 ' + newsCount + ' news</span>' +
          '<span class="cb-brief-stat-chip">🏢 ' + entitiesCount + ' entities</span>' +
        '</div>' +
      '</article>'
    );
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

    const alertRoot = document.getElementById('lp-alert-stream');
    const briefRoot = document.getElementById('lp-brief-grid');

    renderAlerts(alertRoot, windowItems(state.alertPool, state.alertOffset, CARD_COUNT), true);
    renderBriefs(briefRoot, windowItems(state.briefPool, state.briefOffset, CARD_COUNT), true);
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

    renderAlerts(alertRoot, windowItems(state.alertPool, 0, CARD_COUNT), false);
    renderBriefs(briefRoot, windowItems(state.briefPool, 0, CARD_COUNT), false);
    renderHeroTerminal(heroRoot, heroAlerts(state.alertPool, 0));

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
