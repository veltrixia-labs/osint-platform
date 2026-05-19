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
    supply_chain_disruption: { label: 'Supply Chain Intel', color: '#3fb950' },
    global: { label: 'Global Briefing', color: '#58a6ff' },
  };

  const TRIGGER_PREFIX =
    /^(acceleration|entity_surge|pattern_risk|sector_surge|event_continuation|sustained_event|risk_pattern|risk_acceleration)\s*:\s*/i;

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
      title: 'Semiconductor fab input \u2014 export control ripple',
      target_label: 'Semiconductor fab input \u2014 export control ripple',
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
      title: 'Strait transit advisory \u2014 commercial lane restriction',
      target_label: 'Strait transit advisory \u2014 commercial lane restriction',
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
      title: 'Defense procurement surge \u2014 dual-use components',
      target_label: 'Defense procurement surge \u2014 dual-use components',
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
      title: 'Rates desk \u2014 CPI pass-through watch activated',
      target_label: 'Rates desk \u2014 CPI pass-through watch activated',
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
      evidence_list: [{}, {}, {}, {}, {}, {}, {}, {}, {}, {}],
    },
    {
      id: 'fl-002',
      title: 'Strait of Hormuz \u2014 commercial transit advisory',
      target_label: 'Strait of Hormuz \u2014 commercial transit advisory',
      topic: 'energy_resource_risk',
      severity: 'critical',
      triggered_at: '2026-05-03T07:12:00.000Z',
      related_news_count: 3,
      evidence_list: [{}, {}, {}],
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
      title: 'Taiwan Strait \u2014 elevated airspace notices',
      target_label: 'Taiwan Strait \u2014 elevated airspace notices',
      topic: 'defense_technology',
      severity: 'elevated',
      triggered_at: '2026-05-02T22:18:00.000Z',
    },
    {
      id: 'fl-005',
      title: 'Ukraine border \u2014 energy infrastructure strike pattern',
      target_label: 'Ukraine border \u2014 energy infrastructure strike pattern',
      topic: 'energy_resource_risk',
      severity: 'critical',
      triggered_at: '2026-05-02T19:44:00.000Z',
    },
    {
      id: 'fl-006',
      title: 'Supply chain disruption \u2014 port congestion index',
      target_label: 'Supply chain disruption \u2014 port congestion index',
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

  function resolveTimestamp(item) {
    if (!item) return null;
    return item.triggered_at || item.timestamp || item.generated_at || null;
  }

  function formatDisplayDateJa(iso) {
    if (!iso) return '\u2014';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    return d.getMonth() + 1 + '\u6708' + d.getDate() + '\u65e5 ' + h + ':' + m;
  }

  /** Same-day: absolute JP time; within 7d: relative; older: absolute date. */
  function formatDisplayTimestamp(iso) {
    if (!iso) return '\u2014';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    const now = new Date();
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate();
    if (sameDay) return formatDisplayDateJa(iso);
    const diffMs = now.getTime() - d.getTime();
    if (diffMs >= 0 && diffMs < 7 * 24 * 60 * 60 * 1000) {
      const mins = Math.floor(diffMs / 60000);
      if (mins < 1) return '\u305f\u3063\u305f\u4eca';
      if (mins < 60) return mins + '\u5206\u524d';
      const hours = Math.floor(mins / 60);
      if (hours < 24) return hours + '\u6642\u9593\u524d';
      const days = Math.floor(hours / 24);
      return days + '\u65e5\u524d';
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

  function severityLabel(sev) {
    return severityClass(sev).toUpperCase();
  }

  function sourceCount(alert) {
    if (!alert) return 0;
    if (typeof alert.sources_count === 'number' && Number.isFinite(alert.sources_count)) {
      return Math.max(0, Math.floor(alert.sources_count));
    }
    if (Array.isArray(alert.sources) && alert.sources.length) return alert.sources.length;
    if (typeof alert.source_count === 'number' && Number.isFinite(alert.source_count)) {
      return Math.max(0, Math.floor(alert.source_count));
    }
    if (Array.isArray(alert.evidence_list)) return alert.evidence_list.length;
    if (Array.isArray(alert.related_news)) return alert.related_news.length;
    return pickCount(alert.related_news_count, 0);
  }

  function normalizeLiveAlert(raw) {
    const evidence = Array.isArray(raw.evidence_list) ? raw.evidence_list : [];
    const sources = Array.isArray(raw.sources) ? raw.sources : [];
    const count = sourceCount(raw);
    return {
      ...raw,
      triggered_at: resolveTimestamp(raw),
      evidence_list: evidence,
      sources_count: count,
    };
  }

  function normalizeBriefItem(raw) {
    const relatedNews = Array.isArray(raw.related_news) ? raw.related_news : [];
    const companyImpacts = Array.isArray(raw.company_impacts) ? raw.company_impacts : [];
    return {
      ...raw,
      triggered_at: resolveTimestamp(raw),
      related_news: relatedNews,
      related_news_count: pickCount(raw.related_news_count, relatedNews.length),
      related_entities_count: pickCount(raw.related_entities_count, companyImpacts.length),
      company_impacts: companyImpacts,
      sector_impacts: Array.isArray(raw.sector_impacts) ? raw.sector_impacts : raw.sector_impacts,
    };
  }

  function parseMarkdownTable(markdown) {
    const lines = String(markdown || '')
      .trim()
      .split('\n')
      .filter((l) => l.trim().includes('|'));
    if (lines.length < 3) return [];
    const headers = lines[0]
      .split('|')
      .map((c) => c.trim())
      .filter(Boolean);
    return lines.slice(2).map((row) => {
      const cells = row
        .split('|')
        .map((c) => c.trim())
        .filter((_, i, arr) => i > 0 && i < arr.length - 1);
      const obj = {};
      headers.forEach((h, i) => {
        obj[h.toLowerCase().replace(/\s+/g, '_')] = cells[i] || '';
      });
      return obj;
    });
  }

  function sectorRowsFromNamedList(list) {
    if (!Array.isArray(list)) return [];
    return list
      .map((entry) => {
        if (typeof entry === 'string') {
          return { sector: entry.trim(), matched: 0 };
        }
        if (!entry || typeof entry !== 'object') return null;
        const sector = String(
          entry.sector || entry.name || entry.label || entry.category || entry.tag || '',
        ).trim();
        if (!sector) return null;
        const matched = pickCount(
          entry.matched_entities ?? entry.matched ?? entry.count ?? entry.entity_count ?? entry.score,
          0,
        );
        return { sector, matched };
      })
      .filter(Boolean);
  }

  function sectorRowsFromCompanyImpacts(impacts) {
    if (!Array.isArray(impacts) || !impacts.length) return [];
    const map = new Map();
    impacts.forEach((c) => {
      const sector = String(c.sector || c.industry || 'Exposure').trim();
      if (!sector) return;
      map.set(sector, (map.get(sector) || 0) + 1);
    });
    return [...map.entries()].map(([sector, matched]) => ({ sector, matched }));
  }

  function sectorRowsFromMarkdown(body) {
    return parseMarkdownTable(body)
      .map((obj) => {
        const sector = String(obj.sector || obj.name || obj.category || '').trim();
        const rawN = obj.matched_entities ?? obj.entities ?? obj.count ?? '0';
        const matched = parseInt(String(rawN).replace(/[^\d-]/g, ''), 10) || 0;
        return { sector, matched };
      })
      .filter((r) => r.sector && !r.sector.toLowerCase().includes('no sector coverage'));
  }

  function dedupeSectorRows(rows) {
    const seen = new Set();
    const out = [];
    rows.forEach((r) => {
      const key = (r.sector || '').trim().toLowerCase();
      if (!key || seen.has(key)) return;
      seen.add(key);
      out.push({ sector: r.sector, matched: r.matched || 0 });
    });
    return out.sort((a, b) => b.matched - a.matched);
  }

  function normalizeSectorRowsForBrief(item) {
    const rows = [];
    if (Array.isArray(item.sector_impacts) && item.sector_impacts.length) {
      item.sector_impacts.forEach((r) => {
        rows.push({
          sector: String(r.sector || '').trim(),
          matched: pickCount(r.matched_entities ?? r.matched, 0),
        });
      });
    }
    rows.push(...sectorRowsFromNamedList(item.tags));
    rows.push(...sectorRowsFromNamedList(item.categories));
    if (!rows.length) rows.push(...sectorRowsFromCompanyImpacts(item.company_impacts));
    if (!rows.length) rows.push(...sectorRowsFromMarkdown(item.content_markdown || ''));
    return dedupeSectorRows(rows.filter((r) => r.sector));
  }

  function newsCountForBrief(item) {
    const relatedNews = Array.isArray(item.related_news) ? item.related_news : [];
    return pickCount(item.related_news_count, relatedNews.length);
  }

  function entitiesCountForBrief(item) {
    const companyImpacts = Array.isArray(item.company_impacts) ? item.company_impacts : [];
    const sectorRows = normalizeSectorRowsForBrief(item);
    const fromSectors = sectorRows.reduce((sum, r) => sum + (r.matched || 0), 0);
    const fromCompanies = companyImpacts.length;
    const declared = pickCount(item.related_entities_count, fromCompanies);
    return Math.max(declared, fromCompanies, fromSectors > 0 ? fromSectors : 0);
  }

  function extractTriggerDetail(raw) {
    if (!raw) return '';
    const m = raw.match(TRIGGER_PREFIX);
    if (!m) return '';
    const type = m[1].replace(/_/g, ' ').toUpperCase();
    const rest = raw.replace(TRIGGER_PREFIX, '').trim();
    return rest ? `${type} · ${rest}` : type;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function expandPool(pool, fallback) {
    const minLen = Math.max(CARD_COUNT * 2, HERO_STREAM_COUNT + 2);
    if (!pool.length) {
      const out = [];
      let i = 0;
      while (out.length < minLen) {
        out.push(fallback[i % fallback.length]);
        i += 1;
      }
      return out;
    }
    const base = pool.map((row) => ({ ...row }));
    let i = 0;
    while (base.length < minLen) {
      base.push({ ...pool[i % pool.length] });
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
      const live = mode === 'live';
      if (live) {
        el.hidden = false;
        el.className = 'lp-live-indicator';
        el.textContent = 'LIVE PRODUCTION DATA';
        el.setAttribute('data-lp-mode', 'live');
        el.title = 'Synced with production API';
      } else {
        el.hidden = true;
        el.className = 'lp-live-indicator';
        el.textContent = '';
        el.setAttribute('data-lp-mode', 'fallback');
        el.removeAttribute('title');
      }
    });
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

  function briefCardHtml(item, index) {
    const meta = topicMeta(item.topic);
    const rawTitle = item.title || item.target_label || '';
    const title = cleanTitle(rawTitle);
    const ts = formatDisplayTimestamp(resolveTimestamp(item));
    const teaser = escapeHtml(extractTeaser(item.content_markdown));
    const newsCount = newsCountForBrief(item);
    const entitiesCount = entitiesCountForBrief(item);
    const topicVars = topicCssVars(item.topic);
    return (
      '<article class="pro-brief-card cb-brief-card cb-brief-card--preview lp-brief-slot" data-slot="' + index + '" data-domain-card="1" style="' + topicVars + '">' +
        '<div class="cb-brief-card-head cb-brief-card-head--row">' +
          '<span class="domain-chip meta-item-topic--tag">' + escapeHtml(meta.label) + '</span>' +
          '<span class="cb-brief-ts">' + escapeHtml(ts) + '</span>' +
        '</div>' +
        '<h4 class="cb-brief-card-title">' + escapeHtml(title) + '</h4>' +
        '<p class="cb-brief-card-teaser">' + teaser + '</p>' +
        '<div class="cb-brief-card-footer">' +
          '<div class="cb-brief-card-stats" aria-label="Evidence counts">' +
            '<span class="cb-brief-stat-chip">📰 ' + newsCount + ' news</span>' +
            '<span class="cb-brief-stat-chip">🏢 ' + entitiesCount + ' entities</span>' +
          '</div>' +
          '<a class="btn-fb cb-open-context-btn" href="app.html#briefs">View Full Context \u2192</a>' +
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
        const tsIso = resolveTimestamp(a) || new Date().toISOString();
        const ts = formatDisplayTimestamp(tsIso);
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

    let freeItems = FALLBACK_FREE.map(normalizeBriefItem);
    let liveItems = FALLBACK_LIVE.map(normalizeLiveAlert);
    state.mode = 'fallback';

    try {
      const [free, live] = await Promise.all([
        fetchJson(`/api/free/alerts?limit=${FETCH_LIMIT}`),
        fetchJson(`/api/alerts/live?limit=${FETCH_LIMIT}`),
      ]);
      if (Array.isArray(free) && free.length) {
        freeItems = free.map(normalizeBriefItem);
        state.mode = 'live';
      }
      if (Array.isArray(live) && live.length) {
        liveItems = live.map(normalizeLiveAlert);
        state.mode = 'live';
      }
    } catch {
      /* fallback */
    }

    state.briefPool = expandPool(freeItems, FALLBACK_FREE.map(normalizeBriefItem));
    state.alertPool = expandPool(liveItems, FALLBACK_LIVE.map(normalizeLiveAlert));

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
