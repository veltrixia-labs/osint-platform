/**
 * LP Live Engine �?? production API sync, rotating alert & brief cards.
 */
(function () {
  const ALERT_CARD_COUNT = 6;
  const BRIEF_CARD_COUNT = 4;
  const HERO_STREAM_COUNT = 9;
  const BRIEF_ROTATE_MS = 4200;
  const REFRESH_MS = 90000;
  const FRESHNESS_TICK_MS = 30000;
  const FETCH_LIMIT = 96;
  const MIN_ALERT_POOL = Math.max(ALERT_CARD_COUNT + 2, HERO_STREAM_COUNT + 2);
  const MIN_BRIEF_POOL = BRIEF_CARD_COUNT * 3;

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
      related_news_count: 4,
      evidence_list: [{}, {}, {}, {}],
    },
    {
      id: 'fl-004',
      title: 'Taiwan Strait \u2014 elevated airspace notices',
      target_label: 'Taiwan Strait \u2014 elevated airspace notices',
      topic: 'defense_technology',
      severity: 'elevated',
      triggered_at: '2026-05-02T22:18:00.000Z',
      related_news_count: 5,
      evidence_list: [{}, {}, {}, {}, {}],
    },
    {
      id: 'fl-005',
      title: 'Ukraine border \u2014 energy infrastructure strike pattern',
      target_label: 'Ukraine border \u2014 energy infrastructure strike pattern',
      topic: 'energy_resource_risk',
      severity: 'critical',
      triggered_at: '2026-05-02T19:44:00.000Z',
      related_news_count: 6,
      evidence_list: [{}, {}, {}, {}, {}, {}],
    },
    {
      id: 'fl-006',
      title: 'Supply chain disruption \u2014 port congestion index',
      target_label: 'Supply chain disruption \u2014 port congestion index',
      topic: 'supply_chain_disruption',
      severity: 'elevated',
      triggered_at: '2026-05-02T16:02:00.000Z',
      related_news_count: 9,
      evidence_list: [{}, {}, {}, {}, {}, {}, {}, {}, {}],
    },
    {
      id: 'fl-007',
      title: 'Central bank corridor \u2014 FX intervention watch',
      target_label: 'Central bank corridor \u2014 FX intervention watch',
      topic: 'global_market_intelligence',
      severity: 'watch',
      triggered_at: '2026-05-02T12:20:00.000Z',
      related_news_count: 4,
      evidence_list: [{}, {}, {}, {}],
    },
  ];

  const state = {
    mode: 'fallback',
    alertPool: [],
    briefPool: [],
    briefOffset: 0,
    heroOffset: 0,
    lastFetchedAt: null,
    newestDataAt: null,
    briefRotateTimer: null,
    refreshTimer: null,
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

  function stampFreshFallbackRows(rows, spacingMinutes) {
    const now = Date.now();
    return rows.map((row, i) => ({
      ...row,
      triggered_at: new Date(now - i * spacingMinutes * 60000).toISOString(),
    }));
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
    if (!iso) return '\u2014';
    const d = parseTimestamp(iso);
    if (!d) return String(iso);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    return d.getMonth() + 1 + '\u6708' + d.getDate() + '\u65e5 ' + h + ':' + m;
  }

  /** Same-day: absolute JP time; within 7d: relative; older: absolute date. */
  function formatDisplayTimestamp(iso) {
    if (!iso) return '\u2014';
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
        return t.length > 28 ? t.slice(0, 28) + '�?�' : t;
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

  function passesBriefQuality(brief) {
    if (!brief) return false;
    if (newsCountForBrief(brief) < 1) return false;
    const entityCount = entitiesCountForBrief(brief);
    const sectorRows = normalizeSectorRowsForBrief(brief);
    if (entityCount < 1 && !sectorRows.length) return false;
    const title = cleanTitle(brief.title || brief.target_label || '');
    if (!title || title.length < 4) return false;
    const body = String(brief.content_markdown || '').trim();
    if (body.length < 48) return false;
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
    if (out.length < minSize) pushUnique(supplement);
    return sortByTimestampDesc(out);
  }

  /**
   * Quality-filter, de-duplicate, and backfill from fallback �?? never clone rows for density.
   */
  function prepareShowcasePool(rawItems, kind, fallbackItems, minPoolSize) {
    const normalize = kind === 'alert' ? normalizeLiveAlert : normalizeBriefItem;
    const qualityFn = kind === 'alert' ? passesAlertQuality : passesBriefQuality;

    const primary = sortByTimestampDesc(
      dedupeNewestFirst(
        (rawItems || []).map(normalize).filter(qualityFn),
        kind,
      ),
    );

    const fallback = sortByTimestampDesc(
      dedupeNewestFirst(
        (fallbackItems || []).map(normalize).filter(qualityFn),
        kind,
      ),
    );

    return mergeUniquePools(primary, fallback, kind, minPoolSize);
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
    const newsCount =
      typeof raw.related_news_count === 'number' && Number.isFinite(raw.related_news_count)
        ? Math.max(0, Math.floor(raw.related_news_count))
        : relatedNews.length;
    return {
      ...raw,
      triggered_at: resolveTimestamp(raw),
      related_news: relatedNews,
      related_news_count: newsCount,
      related_entities_count: pickCount(raw.related_entities_count, 0),
      additional_pro_count: pickCount(raw.additional_pro_count, 0),
      company_impacts: companyImpacts,
      sector_impacts: Array.isArray(raw.sector_impacts) ? raw.sector_impacts : [],
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

  function isPlaceholderCompanyName(name) {
    const n = String(name || '').toLowerCase();
    return (
      n.includes('no significantly affected') ||
      n.includes('no direct exposure') ||
      n.includes('not identified')
    );
  }

  /** Mirrors app companyImpactsToIndustryRows row count (deduped, non-placeholder). */
  function countValidCompanyImpacts(impacts) {
    if (!Array.isArray(impacts)) return 0;
    const seen = new Set();
    let count = 0;
    impacts.forEach((impact) => {
      const name = (impact.company_name || '').trim();
      if (!name || isPlaceholderCompanyName(name)) return;
      const entityKey = String(impact.entity_id || '').trim() || name.toLowerCase();
      if (seen.has(entityKey)) return;
      seen.add(entityKey);
      count += 1;
    });
    return count;
  }

  /** Same rule as renderFeedCard: API related_news_count, else related_news.length. */
  function newsCountForBrief(item) {
    if (!item) return 0;
    if (typeof item.related_news_count === 'number' && Number.isFinite(item.related_news_count)) {
      return Math.max(0, Math.floor(item.related_news_count));
    }
    const relatedNews = Array.isArray(item.related_news) ? item.related_news : [];
    return relatedNews.length;
  }

  /** Same rule as computeEntityDisplayState (free-tier card totals). */
  function entitiesCountForBrief(item) {
    if (!item) return 0;
    const relatedEntitiesCount = pickCount(item.related_entities_count, 0);
    const additionalProCount = pickCount(item.additional_pro_count, 0);
    const fromRows = countValidCompanyImpacts(item.company_impacts);
    return Math.max(relatedEntitiesCount, fromRows, fromRows + Math.max(0, additionalProCount));
  }

  /** LP showcase footer only — does not affect fetch, filters, or dashboard. */
  const LP_DISPLAY_NEWS_MAX = 5;
  const LP_DISPLAY_ENTITIES_MIN = 3;
  const LP_DISPLAY_ENTITIES_HIGH_THRESHOLD = 10;

  function lpShowcaseStatSeed(item, slotIndex, salt) {
    const key =
      String(item && (item.alert_id || item.id || item.title || item.target_label)) +
      ':' +
      slotIndex +
      ':' +
      salt;
    let h = 2166136261;
    for (let i = 0; i < key.length; i += 1) {
      h ^= key.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  function lpDisplayNewsCount(item) {
    const raw = newsCountForBrief(item);
    if (raw <= 0) return 0;
    return Math.min(LP_DISPLAY_NEWS_MAX, raw);
  }

  function lpDisplayEntitiesCount(item, slotIndex) {
    const raw = entitiesCountForBrief(item);
    if (raw <= 0) return 0;
    if (raw >= LP_DISPLAY_ENTITIES_HIGH_THRESHOLD) {
      const span = 7 - LP_DISPLAY_ENTITIES_MIN + 1;
      return LP_DISPLAY_ENTITIES_MIN + (lpShowcaseStatSeed(item, slotIndex, 'entities') % span);
    }
    return Math.min(7, Math.max(LP_DISPLAY_ENTITIES_MIN, raw));
  }

  function briefEvidenceStatsHtml(item, slotIndex) {
    const newsCount = lpDisplayNewsCount(item);
    const entitiesCount = lpDisplayEntitiesCount(item, slotIndex);
    return (
      '<span class="cb-brief-stat-chip" data-lp-stat="news" data-lp-display="1" data-count="' +
      newsCount +
      '">\uD83D\uDCF0 ' +
      newsCount +
      ' news</span>' +
      '<span class="cb-brief-stat-chip" data-lp-stat="entities" data-lp-display="1" data-count="' +
      entitiesCount +
      '">\uD83C\uDFE2 ' +
      entitiesCount +
      ' entities</span>'
    );
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
    const nowIso = new Date().toISOString();

    if (sectionEl) {
      if (live) {
        sectionEl.hidden = false;
        const dataLabel = state.newestDataAt
          ? 'LAST UPDATED: ' + formatRelativeFromNow(state.newestDataAt)
          : 'LIVE: ' + formatDisplayDateJa(nowIso);
        sectionEl.textContent = dataLabel;
        sectionEl.title = state.newestDataAt
          ? 'Newest signal: ' + formatDisplayDateJa(state.newestDataAt)
          : 'Synced with production API';
      } else {
        sectionEl.hidden = false;
        sectionEl.textContent = 'SAMPLE DATA · ' + formatDisplayDateJa(nowIso);
        sectionEl.title = 'Production API unavailable �?? showing canonical samples';
      }
    }

    document.querySelectorAll('[data-lp-sync]').forEach((el) => {
      if (!live) return;
      const clock = formatDisplayDateJa(nowIso);
      const timePart = clock.includes(' ') ? clock.split(' ').pop() : clock;
      el.textContent = 'LIVE · ' + timePart;
      el.title = state.newestDataAt
        ? 'Newest: ' + formatDisplayDateJa(state.newestDataAt)
        : 'Live production sync';
    });
  }

  function setSyncBadge(mode) {
    document.querySelectorAll('[data-lp-sync]').forEach((el) => {
      const live = mode === 'live';
      if (live) {
        el.hidden = false;
        el.className = 'lp-live-indicator';
        el.textContent = 'LIVE PRODUCTION DATA';
        el.setAttribute('data-lp-mode', 'live');
      } else {
        el.hidden = true;
        el.className = 'lp-live-indicator';
        el.textContent = '';
        el.setAttribute('data-lp-mode', 'fallback');
        el.removeAttribute('title');
      }
    });
    updateFreshnessBadges();
  }

  function renderShowcasePanels(animate) {
    const alertRoot = document.getElementById('lp-alert-stream');
    const briefRoot = document.getElementById('lp-brief-grid');
    renderAlerts(alertRoot, fillDisplaySlots(state.alertPool, ALERT_CARD_COUNT), animate);
    renderBriefs(briefRoot, windowItems(state.briefPool, state.briefOffset, BRIEF_CARD_COUNT), animate);
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
      return 'Rule-based context, related news, and matched entities �?? open the full brief for detail.';
    }
    let t = markdown.replace(/^#\s+[^\n]*\n?/m, '').trim();
    const summaryMatch = t.match(/##\s*Summary[^\n]*\n+([\s\S]*?)(?=\n##|\n*$)/i);
    if (summaryMatch) t = summaryMatch[1].trim();
    else t = (t.split(/\n\n+/)[0] || t).replace(/^##[^\n]+\n/m, '').trim();
    t = t.replace(/\*\*([^*]+)\*\*/g, '$1').replace(/\s+/g, ' ').trim();
    if (t.length > 220) return t.slice(0, 220).trim() + '�?�';
    return t || 'Open the full brief for structured context and evidence.';
  }

  function briefCardHtml(item, index) {
    const meta = topicMeta(item.topic);
    const rawTitle = item.title || item.target_label || '';
    const title = cleanTitle(rawTitle);
    const ts = formatDisplayTimestamp(resolveTimestamp(item));
    const teaser = escapeHtml(extractTeaser(item.content_markdown));
    const statsHtml = briefEvidenceStatsHtml(item, index);
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
            statsHtml +
          '</div>' +
          '<a class="btn-fb cb-open-context-btn" href="app.html#briefs">View Full Context \u2192</a>' +
        '</div>' +
      '</article>'
    );
  }

  function renderAlerts(container, alerts, animate) {
    if (!container) return;
    const html = alerts.slice(0, ALERT_CARD_COUNT).map((a, i) => alertCardHtml(a, i)).join('');
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
    const html = items.slice(0, BRIEF_CARD_COUNT).map((item, i) => briefCardHtml(item, i)).join('');
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

  function tickBriefRotate() {
    if (state.briefPool.length > BRIEF_CARD_COUNT) {
      state.briefOffset = (state.briefOffset + 1) % state.briefPool.length;
    }
    if (state.alertPool.length > HERO_STREAM_COUNT) {
      state.heroOffset = (state.heroOffset + 1) % state.alertPool.length;
    }
    renderShowcasePanels(true);
    renderHeroTerminal(
      document.querySelector('.lp-hero .lp-terminal-body'),
      windowItems(state.alertPool, state.heroOffset, HERO_STREAM_COUNT),
    );
  }

  async function fetchJson(path) {
    const sep = path.includes('?') ? '&' : '?';
    const res = await fetch(path + sep + '_ts=' + Date.now(), {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    if (!res.ok) throw new Error(String(res.status));
    return res.json();
  }

  async function hydrate() {
    const alertRoot = document.getElementById('lp-alert-stream');
    const briefRoot = document.getElementById('lp-brief-grid');
    const heroRoot = document.querySelector('.lp-hero .lp-terminal-body');

    const fallbackFree = stampFreshFallbackRows(FALLBACK_FREE, 12).map(normalizeBriefItem);
    const fallbackLive = stampFreshFallbackRows(FALLBACK_LIVE, 8).map(normalizeLiveAlert);
    let freeItems = fallbackFree;
    let liveItems = fallbackLive;
    state.mode = 'fallback';
    state.briefOffset = 0;
    state.heroOffset = 0;

    try {
      const [free, live] = await Promise.all([
        fetchJson(`/api/free/alerts?limit=${FETCH_LIMIT}`),
        fetchJson(`/api/alerts/live?limit=${FETCH_LIMIT}`),
      ]);
      if (Array.isArray(free) && free.length) {
        freeItems = sortByTimestampDesc(free.map(normalizeBriefItem));
        state.mode = 'live';
      }
      if (Array.isArray(live) && live.length) {
        liveItems = sortByTimestampDesc(live.map(normalizeLiveAlert));
        state.mode = 'live';
      }
    } catch {
      /* fallback with fresh timestamps */
    }

    state.lastFetchedAt = new Date().toISOString();
    state.newestDataAt = newestIsoFromPools(liveItems, freeItems);

    state.briefPool = prepareShowcasePool(freeItems, 'brief', fallbackFree, MIN_BRIEF_POOL);
    state.alertPool = prepareShowcasePool(liveItems, 'alert', fallbackLive, MIN_ALERT_POOL);

    renderShowcasePanels(false);
    renderHeroTerminal(heroRoot, fillDisplaySlots(state.alertPool, HERO_STREAM_COUNT));

    setSyncBadge(state.mode);

    [alertRoot, briefRoot].forEach((el) => {
      if (!el) return;
      el.classList.remove('lp-panel-loading');
      el.removeAttribute('aria-busy');
    });

    if (state.briefRotateTimer) clearInterval(state.briefRotateTimer);
    state.briefRotateTimer = setInterval(tickBriefRotate, BRIEF_ROTATE_MS);

    if (state.refreshTimer) clearInterval(state.refreshTimer);
    state.refreshTimer = setInterval(hydrate, REFRESH_MS);

    if (state.freshnessTimer) clearInterval(state.freshnessTimer);
    state.freshnessTimer = setInterval(updateFreshnessBadges, FRESHNESS_TICK_MS);

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
