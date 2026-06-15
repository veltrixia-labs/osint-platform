# Monthly Trend Flow — Technical Architecture Plan

> Status: **PROPOSAL (read-only investigation complete; no application code modified)**
> Scope: aggregate the last month of high-signal Alert Stream events, render their
> cross-sector geopolitical/market ripple as a flow/network, and archive each month
> as a browsable historical snapshot.

---

## 0. Executive Summary

The platform **already contains every primitive** this feature needs — we should
compose existing engines rather than build new ones:

| Need | Existing asset to reuse |
|---|---|
| Source events | `AlertLog` (`db/models.py:221`) — already 24h-cluster-deduped at creation |
| Spike / 1.5× logic | `analysis/intensity_pressure.py` (`spike_vs_baseline`, `decayed_domain_baseline`) + `_PRO_MIN_REIGNITE_FACTOR = 1.5` (`jobs/alert_manager.py:34`) |
| Sector → geo flow graph | `analysis/spatial_physics_engine.py` (`SpatialPhysicsEngine`, `GEO_REGISTRY`, `DOMAIN_EDGE_TOPOLOGY`, `PRO_DOMAIN_TO_OMNI`) |
| Snapshot-storage pattern | `ContagionHistory` (`db/models.py:779`) — append-only `nodes_payload`/`edges_payload` JSONB |
| Monthly cron pattern | `schedule.every().day.at("09:00")` + `monthly_reports_wrapper` (`jobs/main_scheduler.py:129,256`) |
| Spatial flow renderer (deck.gl) | `web_dashboard/src/modules/render/pro_interactive_map.ts` (arcs + nodes over MapLibre) |
| Evidence modal + open-UI | `showEvidenceModal()` (`render/alerts.ts`), `DEV_MODE_AUDIT` (`modules/dev_mode.ts`) |
| Archive list/serve pattern | `GET /api/reports` (`api/routes/reports.py:73`) |

**Headline recommendation:** create a dedicated **`monthly_trend_reports`** table that
stores the precomputed snapshot (nodes/edges/summary as JSONB). Generate it once per
month via an idempotent, date-gated scheduler job. The frontend reads the stored JSON
directly — **zero historical recalculation**. The visualization reuses the existing
deck.gl spatial-flow engine; every node/edge deep-links to the raw `AlertLog` rows via a
glassmorphism evidence modal. **No tier gating, no locked masks, no ghost nodes.**

---

## 1. Data Extraction Logic (Backend)

### 1.1 What the pipeline already guarantees
- **24h clustering is already applied.** Every `AlertLog` row is created by
  `AlertManager.evaluate_and_send` (`jobs/alert_manager.py`) only after the 24h
  dedup/cluster window (`_PRO_MIN_DEDUP_WINDOW_HOURS = 24`). So month-level extraction does
  **not** re-cluster — it consumes already-clustered, deduped alert rows.
- **The 1.5× spike is a first-class concept.** `_PRO_MIN_REIGNITE_FACTOR = 1.5` gates
  re-triggers, and `analysis/intensity_pressure.py:spike_vs_baseline(raw_current,
  baseline_raw, reignite_factor=1.5)` is the canonical "did it spike ≥1.5×" predicate.
  `AlertLog.metadata_json` persists `raw_intensity`, `spike_delta`, and `domain_count`.
- **Geo + sector are on the row.** `AlertLog.location_lat/lng` (`models.py:240`) and
  `AlertLog.topic` → sector via `PRO_DOMAIN_TO_OMNI` (`spatial_physics_engine.py:35`).

### 1.2 Extraction query (one indexed pass over the month)
```sql
SELECT * FROM alert_logs
WHERE triggered_at >= :month_start          -- e.g. 2026-04-01T00:00Z
  AND triggered_at <  :month_end            -- e.g. 2026-05-01T00:00Z
  AND suppressed = false
ORDER BY triggered_at ASC;
```
Then apply the **established spike filter in Python** (so we reuse the exact production
logic, not a re-implemented SQL heuristic):

```python
from analysis.intensity_pressure import (
    raw_intensity_from_alert, decayed_domain_baseline, spike_vs_baseline,
)
# Group the month's alerts by spatial domain (PRO_DOMAIN_TO_OMNI[alert.topic]).
# For each alert, compare its raw intensity to the domain's decayed baseline.
baseline = decayed_domain_baseline(domain_alerts_so_far, now=alert.triggered_at)
is_spike = spike_vs_baseline(raw_intensity_from_alert(alert), baseline, ui_delta=...)
# Keep alert iff is_spike (≥1.5× reignite) OR severity in ('critical','elevated').
```
> **Index:** an existing `bdf0d08f0ffd_add_created_at_indexes` migration adds time indexes;
> confirm/add `ix_alert_logs_triggered_at` so the month window stays a range scan.

### 1.3 Building the flow/graph (reuse the physics engine)
This is exactly what `jobs/omni_spatial_worker.py` does for a **24h** window — we run the
same engine over a **30-day** window:

1. Resolve each spiked alert to a `GEO_REGISTRY` site (nearest of the 10 canonical nodes,
   or its `location_lat/lng`).
2. Feed the events into `SpatialPhysicsEngine.build_domain_graph(domain_id, events, …)`
   per spatial domain (`global / energy / shipping`) → produces `ComputedSpatialNode[]`
   (epicenters, impact_score, entropy) and `ComputedSpatialEdge[]` (directed sector→sector
   ripple, `order_level`, `edge_intensity`, `viscosity_coefficient`).
3. Serialize via the same `_node_payload` / `_edge_payload` shapes used by
   `api/routes/pro_spatial.py` so the **frontend renderer needs no new adapter**.
4. Attach provenance: each node/edge carries `source_alert_ids: [uuid]` so the evidence
   modal can link back to raw alerts (see §3.3).

**Output structure (per month):**
```jsonc
{
  "schema_version": "monthly_trend_v1",
  "period": { "year": 2026, "month": 4, "start": "...", "end": "..." },
  "summary": { "alerts_total": 0, "alerts_spiked": 0, "entropy_index": 0.0,
               "viscosity_coefficient": 0.0, "top_sectors": ["energy", "shipping"] },
  "nodes": [ { "id", "site_key", "name", "lat", "lon", "domain_id",
               "impact_score", "entropy_index", "type": "epicenter|affected",
               "source_alert_ids": ["…"] } ],
  "edges": [ { "source_id", "target_id", "domain_id", "order_level",
               "edge_intensity", "viscosity_coefficient", "source_alert_ids": ["…"] } ]
}
```

---

## 2. Monthly Generation & Archive Storage (Database & Cron)

### 2.1 Schema — **dedicated table (recommended)**
Do **not** overload the `Report` table (it carries Substack/premium/gating fields and a
narrative-report contract). Create a clean, snapshot-first table that mirrors the proven
`ContagionHistory` pattern but is archival/monthly:

```python
class MonthlyTrendReport(Base):
    __tablename__ = "monthly_trend_reports"
    __table_args__ = (
        UniqueConstraint("period_year", "period_month", name="uq_monthly_trend_period"),
        Index("ix_monthly_trend_period", "period_year", "period_month"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    period_year   = Column(Integer, nullable=False)   # 2026
    period_month  = Column(Integer, nullable=False)   # 4  (April)
    period_start  = Column(DateTime(timezone=True), nullable=False)
    period_end    = Column(DateTime(timezone=True), nullable=False)
    label         = Column(String, nullable=False)    # "April 2026"
    generated_at  = Column(DateTime(timezone=True), server_default=func.now())
    schema_version = Column(String, default="monthly_trend_v1")
    # Precomputed snapshot — read directly, never recomputed:
    nodes_payload = Column(JSONB, nullable=False)
    edges_payload = Column(JSONB, nullable=False)
    summary_json  = Column(JSONB, nullable=False)     # counts, entropy, top sectors
    alerts_total   = Column(Integer, default=0)
    alerts_spiked  = Column(Integer, default=0)
```
- **Why store the snapshot JSON:** the source `AlertLog` rows are subject to 24h
  `ContagionHistory` retention purges and ongoing topic re-categorization
  (`scripts/backfill_crypto_categories.py`). A frozen monthly snapshot guarantees
  reproducibility and makes browsing O(1) (no month-long recompute on every page view).
- **Migration:** new Alembic revision chained to current head
  `b7e1c9d4a2f0` (the latest, post-Context-Brief migration). DDL only — `create_table`.

### 2.2 Generation job (idempotent, date-gated)
The `schedule` library has no native "last day of month", so follow the **existing
`monthly_reports_wrapper` pattern** (`main_scheduler.py:129`): a daily-at-time job that
gates on the calendar.

```python
# jobs/monthly_trend_worker.py  (new)
async def run_monthly_trend_worker(session, *, force=False, year=None, month=None):
    # Default target = the *just-completed* previous month.
    # Idempotency: skip if (year, month) row already exists unless force=True.
    # 1) extract spiked alerts for [month_start, month_end)  (§1.2)
    # 2) build nodes/edges via SpatialPhysicsEngine over the 30d window  (§1.3)
    # 3) upsert one MonthlyTrendReport row.
```
Register in `main_scheduler.py` alongside the others:
```python
schedule.every().day.at("09:30").do(schedule_async, "monthly_trend", monthly_trend_wrapper)
# wrapper fires the worker only when date.day == 1 (snapshots the prior month)
```
Plus a manual CLI entrypoint (`python -m jobs.monthly_trend_worker --year 2026 --month 4
[--force]`) for backfilling historical months, mirroring `omni_spatial_worker`'s `_main()`.

### 2.3 Backfill
A one-off `scripts/backfill_monthly_trends.py` loops over the prior N months calling the
worker with `force=False` so existing months are skipped — lets us populate
"March 2026", "April 2026" archives immediately on launch.

---

## 3. Frontend & UI Architecture

### 3.1 Navigation & archive browsing
- Add a core nav item in `render/nav.ts:NAV_ITEMS`:
  `{ id: 'trend-flow', label: 'Trend Flow', icon: '🌊', minTier: 'free', group: 'core' }`.
- Wire the tab in `main.ts`: add `'trend-flow'` to `TabId`, `BOOT_TABS`, `PAGE_HEADERS`
  (title "Monthly Trend Flow", subtitle), and a `handleTabSwitch` branch
  `else if (tab === 'trend-flow') renderTrendFlow()`.
- **Archive selector:** a month-pill / dropdown bar (reuse the `renderTopicFilterBar`
  styling idiom) populated from `GET /api/monthly-trends` → `["April 2026", "March 2026", …]`.
  Deep-link friendly: `app.html#trend-flow/2026-04`.

### 3.2 The flow/network visualization (reuse, don't rebuild)
The monthly snapshot's `nodes`/`edges` use the **same shape** the deck.gl engine in
`render/pro_interactive_map.ts` already renders (ArcLayer ripple edges + Scatterplot
epicenter nodes over a MapLibre dark-matter basemap). Plan:
- Extract/parameterize the renderer so it accepts a **static** `{nodes, edges}` payload
  (the live map already supports a payload-driven attach via `_attachDomain`). No live
  polling for archives — it's a frozen month.
- Sector framing (shipping / energy / markets / defense) comes from each node's
  `domain_id`; edges encode propagation order (`order_level` 1→3) and `edge_intensity`,
  exactly as today's contagion arcs.
- A lightweight fallback: if WebGL/deck.gl is unavailable, render the same nodes/edges as
  the existing CSS/SVG topology mini-graph (`chud-topo-*` in `render/alerts.ts`).

### 3.3 Absolute data transparency (per our UI principles)
- **No locked masks, mosaics, or ghost nodes.** Every node and edge is fully rendered for
  all tiers. (`monthly-trends` endpoints are **ungated** — see §4.)
- **Glassmorphism evidence modal:** clicking a node/edge opens the existing
  `showEvidenceModal()` (`render/alerts.ts`) populated from `source_alert_ids` →
  `/api/alerts/{id}` (or the resolved evidence list), with direct links to the raw
  underlying sources, matching the Cryo-Glass styling.
- **Dev Mode:** surface a `DEV_MODE_AUDIT` badge (`modules/dev_mode.ts`) rather than any
  paywall overlay, consistent with the open-interface principle.

---

## 4. API Contract (new, ungated)

Register a `monthly_trends` router in `api/main.py` (mirrors `pro_spatial`/`reports`),
**without** the `_require_pro` gate used in `pro_spatial.py`:

| Method / Path | Returns |
|---|---|
| `GET /api/monthly-trends` | Archive index: `[{ year, month, label, generated_at, alerts_total, alerts_spiked }]`, newest first |
| `GET /api/monthly-trends/{year}/{month}` | Full snapshot: `{ period, summary, nodes, edges }` straight from `MonthlyTrendReport` JSONB |
| `GET /api/monthly-trends/latest` | Convenience alias for the newest archived month |

`no-store` headers; 404 when a month isn't generated yet. Reuse the
`AsyncSessionLocal` dependency pattern from `pro_spatial.py`.

---

## 5. Phased Implementation Roadmap

1. **Schema** — `MonthlyTrendReport` model + Alembic migration (head → new). *(DDL only.)*
2. **Extraction + engine** — `analysis/monthly_trend_builder.py`: month query + spike
   filter (`intensity_pressure`) + `SpatialPhysicsEngine` graph build + provenance.
3. **Worker + cron + backfill** — `jobs/monthly_trend_worker.py`, scheduler registration,
   `scripts/backfill_monthly_trends.py`.
4. **API** — `api/routes/monthly_trends.py` (3 endpoints, ungated) + router registration.
5. **Frontend** — nav tab, `render/trend_flow.ts` (archive selector + deck.gl reuse +
   evidence modal), `main.ts` routing, `api.ts` fetchers + types.
6. **Verify** — `alembic upgrade`, `tsc && vite build`, manual month backfill, click-through
   to raw alert sources.

---

## 6. Risks & Open Questions (for your decision)

1. **Spike definition precision.** `spike_delta` in metadata is an *absolute* UI-index
   delta, while 1.5× is the *raw* reignite ratio. Recommendation: use
   `intensity_pressure.spike_vs_baseline()` (raw ratio, the canonical source of truth).
   Confirm whether "spiked 1.5×" should be **OR severity≥elevated** (broader) or **strict
   ratio only** (narrower).
2. **Geo coverage.** Alerts without `location_lat/lng` fall back to nearest `GEO_REGISTRY`
   site by topic; alerts with neither geo nor mappable topic are counted in `summary` but
   omitted from the map (logged, never silently dropped).
3. **Edge semantics.** Reuse the curated `DOMAIN_EDGE_TOPOLOGY` (deterministic, explainable)
   vs. deriving edges purely from observed alert co-occurrence. Recommendation: start with
   the curated topology weighted by the month's observed intensities (transparent + stable).
4. **Naming.** "Monthly Trend Flow" tab/route id — proposed `trend-flow`. Confirm label.
5. **Retention.** `MonthlyTrendReport` is archival (keep all months). Confirm no purge.

---

### Appendix — key source references
- `db/models.py`: `AlertLog:221`, `Report:61`, `ContagionHistory:779`, `TrendSignal:208`, `EventCluster:182`
- `jobs/alert_manager.py`: dedup/reignite floors `:33-34`, severity gates `:159`, spike calc `_calculate_spike`
- `analysis/intensity_pressure.py`: `spike_vs_baseline`, `decayed_domain_baseline`, `ui_display_intensity`
- `analysis/spatial_physics_engine.py`: `OMNI_SPATIAL_DOMAINS:32`, `PRO_DOMAIN_TO_OMNI:35`, `GEO_REGISTRY:45`, `DOMAIN_EDGE_TOPOLOGY:59`
- `jobs/omni_spatial_worker.py`: 24h graph-build reference implementation
- `jobs/main_scheduler.py`: cron registration `:234-331`, monthly wrapper `:129`
- `api/routes/pro_spatial.py`: node/edge serialization + session pattern; `api/routes/reports.py:73`: archive listing
- `web_dashboard/src/modules/render/pro_interactive_map.ts`: deck.gl flow renderer; `render/alerts.ts`: `showEvidenceModal`, topology fallback; `modules/dev_mode.ts`: `DEV_MODE_AUDIT`
