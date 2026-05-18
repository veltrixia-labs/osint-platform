/**
 * LP Live Engine — sync preview panels with /api/free/alerts and /api/alerts/live.
 * Fallback matches scratch/free_alert_feed_sample.md (canonical product reference).
 */
(function () {
  const TOPIC_LABELS = {
    energy_resource_risk: { label: 'Energy & Resource Risk', color: '#d29922' },
    global_market_intelligence: { label: 'Global Market Intel', color: '#58a6ff' },
    crypto_geopolitics: { label: 'Crypto & Geopolitics', color: '#db6d28' },
    ai_semiconductor_intelligence: { label: 'AI & Semiconductors', color: '#bc8cff' },
    defense_technology: { label: 'Defense Technology', color: '#f85149' },
    supply_chain_intelligence: { label: 'Supply Chain Intel', color: '#3fb950' },
    global: { label: 'Global Briefing', color: '#58a6ff' },
  };

  /** Canonical Context Brief — same as scratch/free_alert_feed_sample.md */
  const FALLBACK_FREE = [
    {
      alert_id: 'canonical-energy-001',
      title: 'United States Ambivalent to Russian Oil Sanctions',
      target_label: 'United States Ambivalent to Russian Oil Sanctions',
      topic: 'energy_resource_risk',
      triggered_at: '2026-05-03T08:40:56.000Z',
      related_news_count: 3,
      related_entities_count: 0,
      content_markdown:
        '## Summary\nReport: Russian Oil Output Falls After Ukrainian Drone Strikes. EU defers maritime services ban. United States ambivalent on enforcement timing.',
    },
  ];

  const FALLBACK_LIVE = [
    {
      id: 'canonical-live-001',
      target_label: 'United States Ambivalent to Russian Oil Sanctions',
      title: 'United States Ambivalent to Russian Oil Sanctions',
      topic: 'energy_resource_risk',
      severity: 'elevated',
      triggered_at: '2026-05-03T08:40:56.000Z',
      intensity: 6.2,
      location_lat: null,
      location_lng: null,
    },
    {
      id: 'canonical-live-002',
      target_label: 'Strategic AI Infrastructure Surge',
      title: 'Strategic AI Infrastructure Surge',
      topic: 'ai_semiconductor_intelligence',
      severity: 'high',
      triggered_at: new Date().toISOString(),
      intensity: 9.5,
      location_lat: 37.3871,
      location_lng: -121.9667,
    },
  ];

  const GEOPOLITICAL_MARKERS = [
    { name: 'Hormuz Strait', lat: 26.56, lng: 56.25, level: 'critical' },
    { name: 'Taiwan', lat: 23.6978, lng: 120.9605, level: 'elevated' },
    { name: 'Ukraine', lat: 48.3794, lng: 31.1656, level: 'elevated' },
    { name: 'South China Sea', lat: 15.0, lng: 115.0, level: 'watch' },
  ];

  function topicMeta(topic) {
    const key = (topic || 'global').toLowerCase();
    return TOPIC_LABELS[key] || { label: topic || 'Global', color: '#58a6ff' };
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
    if (!md) return 'Rule-based context, related news, and matched entities — open the full brief for detail.';
    let t = md.replace(/^#\s+[^\n]*\n?/m, '').trim();
    const m = t.match(/##\s*Summary[^\n]*\n+([\s\S]*?)(?=\n##|\n*$)/i);
    if (m) t = m[1].trim();
    t = t.replace(/\*\*/g, '').replace(/\s+/g, ' ').trim();
    if (t.length > 200) return t.slice(0, 200).trim() + '…';
    return t || 'Open the full brief for structured context and evidence.';
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

  function setSyncBadge(mode) {
    document.querySelectorAll('[data-lp-sync]').forEach((el) => {
      el.textContent = mode === 'live' ? 'LIVE DATA' : 'CANONICAL SAMPLE';
      el.classList.toggle('lp-sync-badge--live', mode === 'live');
      el.setAttribute('title', mode === 'live' ? 'Loaded from production API' : 'Canonical sample from product reference');
    });
  }

  function renderAlerts(container, alerts, source) {
    if (!container) return;
    container.innerHTML = alerts
      .slice(0, 4)
      .map((a) => {
        const meta = topicMeta(a.topic);
        const sev = severityClass(a.severity);
        const title = cleanTitle(a.title || a.target_label);
        const ts = formatTs(a.triggered_at);
        const sources =
          a.evidence_list?.length ||
          (a.related_news_count != null ? `${a.related_news_count} sources` : 'live');
        return `
        <article class="lp-alert" style="--lp-alert-topic:${meta.color}">
          <div class="lp-alert-meta">
            <span class="lp-alert-topic">${escapeHtml(meta.label)}</span>
            <span class="lp-alert-sev lp-alert-sev--${sev}">${sev.toUpperCase()}</span>
          </div>
          <h4 class="lp-alert-title">${escapeHtml(title)}</h4>
          <p class="lp-alert-ts lp-mono">${escapeHtml(ts)} · ${escapeHtml(String(sources))}</p>
        </article>`;
      })
      .join('');
    container.dataset.source = source;
  }

  function renderBriefs(container, items, source) {
    if (!container) return;
    const cards = items.slice(0, 2);
    container.innerHTML = cards
      .map((item, i) => {
        const meta = topicMeta(item.topic);
        const title = cleanTitle(item.title || item.target_label);
        const teaser = extractTeaser(item.content_markdown);
        const ts = formatTs(item.triggered_at);
        const border = i === 0 ? 'lp-brief-card--accent' : 'lp-brief-card--warn';
        return `
        <article class="lp-brief-card ${border}" style="border-left-color:${meta.color}">
          <div class="lp-brief-head">
            <span class="lp-brief-chip" style="color:${meta.color}">${escapeHtml(meta.label)}</span>
            <span class="lp-brief-kind lp-mono">Context Brief · ${escapeHtml(ts)}</span>
          </div>
          <h4 class="lp-brief-title">${escapeHtml(title)}</h4>
          <p class="lp-brief-teaser">${escapeHtml(teaser)}</p>
          <div class="lp-brief-stats lp-mono">
            <span class="lp-brief-stat">📰 ${item.related_news_count ?? 0} news</span>
            <span class="lp-brief-stat">🏢 ${item.related_entities_count ?? 0} entities</span>
          </div>
        </article>`;
      })
      .join('');
    container.dataset.source = source;
  }

  function project(lat, lng, w, h) {
    return { x: (lng + 180) * (w / 360), y: (90 - lat) * (h / 180) };
  }

  function renderMap(svg, markers) {
    if (!svg) return;
    const g = svg.querySelector('#lp-map-markers');
    const labels = svg.querySelector('#lp-map-labels');
    if (!g) return;
    const w = 800;
    const h = 220;
    g.innerHTML = markers
      .map((m) => {
        const { x, y } = project(m.lat, m.lng, w, h);
        const cls =
          m.level === 'critical'
            ? 'lp-map-dot--critical'
            : m.level === 'elevated'
              ? 'lp-map-dot--elevated'
              : 'lp-map-dot--std';
        return `
        <g class="lp-map-marker" transform="translate(${x},${y})">
          <circle class="lp-map-pulse-ring" r="14" fill="none" stroke="#58a6ff" stroke-width="1" opacity="0.35"/>
          <circle class="lp-map-dot lp-map-pulse-neon ${cls}" r="4"/>
        </g>`;
      })
      .join('');
    if (labels) {
      labels.innerHTML = markers
        .slice(0, 4)
        .map((m) => {
          const { x, y } = project(m.lat, m.lng, w, h);
          return `<text class="lp-map-label" x="${x + 8}" y="${y - 6}">${escapeHtml(m.name)}</text>`;
        })
        .join('');
    }
  }

  function renderHeroTerminal(container, alerts) {
    if (!container || !alerts.length) return;
    container.innerHTML = alerts
      .slice(0, 5)
      .map((a) => {
        const tag = (a.topic || 'SIG').split('_')[0].slice(0, 3).toUpperCase();
        const d = new Date(a.triggered_at || Date.now());
        const ts = Number.isNaN(d.getTime())
          ? '—'
          : d.toISOString().slice(11, 19) + 'Z';
        const val = cleanTitle(a.title || a.target_label);
        return `<span class="lp-terminal-line"><span class="ts">${ts}</span><span class="tag">${tag}</span><span class="val">${escapeHtml(val)}</span></span>`;
      })
      .join('');
  }

  function markersFromAlerts(live) {
    const fromAlerts = live
      .filter((a) => a.location_lat != null && a.location_lng != null)
      .map((a) => ({
        name: cleanTitle(a.target_label).slice(0, 28),
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
    return merged.slice(0, 8);
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

    let freeItems = FALLBACK_FREE;
    let liveItems = FALLBACK_LIVE;
    let mode = 'fallback';

    try {
      const [free, live] = await Promise.all([
        fetchJson('/api/free/alerts?limit=4'),
        fetchJson('/api/alerts/live?limit=6'),
      ]);
      if (Array.isArray(free) && free.length) {
        freeItems = free;
        mode = 'live';
      }
      if (Array.isArray(live) && live.length) {
        liveItems = live;
        mode = 'live';
      }
    } catch {
      /* canonical fallback */
    }

    renderAlerts(alertRoot, liveItems, mode);
    renderBriefs(briefRoot, freeItems, mode);
    renderHeroTerminal(heroRoot, liveItems.length ? liveItems : freeItems);
    renderMap(mapSvg, markersFromAlerts(liveItems));
    setSyncBadge(mode);

    [alertRoot, briefRoot].forEach((el) => {
      if (!el) return;
      el.classList.remove('lp-panel-loading');
      el.removeAttribute('aria-busy');
    });

    document.dispatchEvent(
      new CustomEvent('lp-data-ready', { detail: { mode, freeItems, liveItems } })
    );
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', hydrate);
  } else {
    hydrate();
  }
})();
