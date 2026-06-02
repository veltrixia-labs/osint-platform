# Clustering Quality Engineering Proposal

**Status:** Draft for review · **Author:** QE audit (Max Miyazaki) · **Date:** 2026-06-03
**Scope:** Ingestion → cluster → alert evidence-binding pipeline. Investigation only; **no pipeline code was modified** to produce this document.

---

## 1. Executive Summary

The platform runs **two independent keyword/Jaccard clustering layers** plus a **substring evidence-binding fallback**. None of the three validates that a bound source describes the *same event* as its master — they bind on shared *tokens*, dominated by a single geographic/actor anchor (`iran`, `china`, `hormuz`). There is **no embedding/cosine layer** anywhere in the pipeline; all matching is lexical set-overlap.

A read-only audit of the live database (latest 400 active alerts, `scripts/audit_clustering.py`, reusing the production `_event_tokens` / `_event_similarity` functions) found material data-integrity leakage:

| Metric | Result |
|---|---|
| Active clusters audited (≥3 evidence) | 321 |
| Clusters with ≥1 loosely-bound source (title sim < 0.12 vs master) | **293 (91%)** |
| Evidence items inspected | 5,350 |
| Evidence items loosely bound to their master | **3,704 (69.2%)** |
| Clusters spanning >1 distinct geo anchor | 84 |

**Concrete false positives observed:**
- `[MARKET] "A Draft U.S.-Iran Plan Is Said to Be on the Table…"` — 39/40 evidence loose; includes **`"One of the hottest crypto products in the world…"` at similarity 0.0 (zero shared tokens)**.
- `[MARKET] "…China's coal mine disaster…"` — merged with `"China's EV exports surge"`, `"China keeping its best AI talent"`, `"TikTok owner ByteDance … custom AI CPUs"` — distinct events bound **only by `china`**.
- A single Iran-war news theme is fragmented across `MARKET`, `DEFENSE`, `CRYPTO`, `AI_TECH`, and `SUPPLY_CHAIN` masters, each absorbing 35–40 sources sharing **only the token `iran`** (e.g. `"Bitcoin's drop … US-Iran tensions"` evidence under a gas-production headline).

**Verdict:** structural integrity is **weak**. The pipeline reliably groups *topically adjacent* news but routinely binds *contextually distinct* events under a shared anchor. This is a trust risk: a Pro consumer expanding an alert's "PRIMARY SOURCES" sees articles that do not corroborate the headline.

---

## 2. Current Pipeline — exact criteria, files, and line numbers

### 2.1 Layer A — Ingestion clustering (`analysis/clustering.py`)
Groups raw `Item`s into `EventCluster`s.

- **`cluster_items()`** — `analysis/clustering.py:166`. Greedy single-pass; per-item category threshold (`analysis/clustering.py:184-185`).
- **`calculate_merge_confidence()`** — `analysis/clustering.py:94`. Blended score:
  - `score = lex*0.2 + geo*0.2 + org*0.15 + sector*0.15` (`:120`), where `geo` is pre-multiplied ×1.2 (`:107`).
  - **Agreement bonus** (`:113-126`): `+0.30` if ≥2 weak signals match, `+0.25` more if ≥3. Match points trip at `lex>0.15, geo>0.5, org>0.3, sector>0.3` (`:114-117`).
- **Category thresholds** (`analysis/clustering.py:157-164`): geopolitics **0.12**, economy 0.14, cyber 0.18, supply_chain 0.12, defense 0.12, default 0.15 (function default 0.18, `:166`).
- **Hard location-conflict penalty** ×0.1 (`:193-194`) — **only fires when geos are disjoint**; does nothing when they share a single geo.
- **Over-merge detection** >2 geos (`:224`) — **metric only, never enforced**.
- **Reconciliation to existing clusters**: representative-title Jaccard **≥ 0.75** (`:278`, `:287`).

> Root weakness: a single shared geo token (`iran`) easily clears `geo>0.5`, contributing a match point and the geo term; combined with the agreement bonus this pushes weakly-related items over the low (0.12) category thresholds.

### 2.2 Layer B — Alert event clustering (`jobs/alert_manager.py`)
Decides whether a new `TrendSignal` is the same event as an active master alert.

- **Thresholds** (`jobs/alert_manager.py:185-190`): `CLUSTER_WINDOW_HOURS=24`, `CLUSTER_SIM_THRESHOLD=0.6`, `CLUSTER_OVERLAP_THRESHOLD=0.75`, `CLUSTER_MIN_SHARED=4`, `CLUSTER_ESCALATION_FACTOR=1.5`, `CLUSTER_MAX_EVIDENCE=40`.
- **`_event_tokens()`** (`:237`) — lowercase, stemmed (`_stem` `:205`), ≥3 chars, stopword-filtered (`:192`); distinctifier tags stripped (`:226`).
- **`_event_similarity()`** (`:248-267`) — **Jaccard** by default; **containment override** returns `max(jaccard, overlap)` when `inter ≥ 4` AND `overlap ≥ 0.75`.
- **`_find_event_cluster()`** (`:753-801`) — **title-only** tokens; **topic silo intentionally removed** (`:775 _ = topic`); picks best master with `sim ≥ 0.6` in the 24h window.

> Master *selection* at 0.6 Jaccard is reasonably strict. The leak is **downstream of selection**: evidence merging does not re-validate sources.

### 2.3 Layer C — Evidence binding (`jobs/alert_manager.py:609-677`)
Resolves the source list shown to users. Three strategies, tried in order:
1. **cluster_id** (`:620-632`) — all `Item`s with `cluster_id == sig.cluster_id`. Inherits **all** of Layer A's over-merge.
2. **Exact title match** (`:635-637`) — `Item.title.in_(titles)`. Safe.
3. **Substring fallback** (`:639-655`) — **`Item.title.ilike("%{sig.target_label}%")`** (`:643`) and **`Item.title.ilike("%{title_fragment}%")`** (`:651`). Pure substring; **no semantic check**. This is the most direct anchor-leak path (any title containing "Hormuz"/"Iran" qualifies).

### 2.4 Evidence merge on absorption (`jobs/alert_manager.py:803-863`)
`_absorb_into_master()` / `_bump_master()` merge an absorbed signal's `evidence_list` into the master, **deduped by URL/title only** — there is **no per-evidence similarity gate** against the master headline. Over repeated absorptions a master accumulates a grab-bag up to `CLUSTER_MAX_EVIDENCE=40`.

---

## 3. Root-Cause Analysis of Leakage

**RC-1 — Anchor-dominated similarity (Layers A & B).** Similarity is token-set overlap with no notion of *event type*. A shared actor/geo (`iran`) + the agreement bonus is sufficient. Distinct actions (sanction vs air-strike vs gas-production vs crypto-price) are invisible to the score.

**RC-2 — No event-type / action validation anywhere.** The entity model (`extract_entities`, `analysis/clustering.py:59`) extracts geo/org/sector but **never the action/verb**. "Israel *evacuates* Tyre" and "Iran *restores* gas" share `iran`/`israel` region context but are different events.

**RC-3 — Unvalidated evidence merge (Layer C + absorption).** Even when master *selection* is strict (0.6), the `evidence_list` is filled from (a) the over-merged ingestion cluster_id, (b) the substring ILIKE fallback, and (c) wholesale merge of absorbed signals' evidence — none re-checked against the master. The observed **sim = 0.0** bindings can only arise here.

**RC-4 — Topic silo removed for *everything*.** Removing the topic gate (`:775`) was correct for *master selection* (same event re-classified across topics). But it also means **evidence binding has no domain backstop**, so a `CRYPTO` price article and a `DEFENSE` strike article coexist in one master's sources.

**RC-5 — Low ingestion thresholds + unenforced safeguards.** Category thresholds 0.12–0.18 are permissive; the >2-geo over-merge check is logged but never acted upon.

---

## 4. Feasibility Study

### 4.A Strict Entity / Sector validation (actor **and** action must match)
**Idea:** bind two texts only if they share (i) an anchor (geo/org) **and** (ii) at least one **action/event-type** token from a curated lexicon (`sanction, strike, attack, seiz*, deal, ceasefire, blackout, outage, export, tariff, price, drop, surge, evacuat*, nuclear, …`).

- **Feasibility: HIGH.** Reuses existing tokenization. Add one frozenset lexicon + an `_event_action_tokens()` helper. Pure in-memory set ops; O(tokens). No new data, no model.
- **Risk:** a too-small action lexicon could *reject* valid merges (recall loss). Mitigate by shipping in **shadow mode** first (measure, don't filter) and tuning the lexicon against the audit set.

### 4.B Hard domain boundary constraints (Defense vs Market vs Crypto)
**Idea:** for **evidence binding only** (not master selection), reject a source whose inferred domain conflicts with the master's, using `infer_domain_from_topic` (`analysis/pro_domain_config.py`) + the `SECTOR_ENTITIES` map.

- **Feasibility: MEDIUM.** Must **not** re-break the cross-topic *same-event* merge that the topic-silo removal fixed (RC-4). Solution: apply the domain guard to **individual evidence items vs the master domain**, with an explicit **spillover allow-list** for legitimate cross-domain pairs (e.g. `ENERGY↔MARKET`, `DEFENSE↔ENERGY` for oil-shock stories). Keep master selection title-only.
- **Risk:** allow-list maintenance. Acceptable; it is a small static map.

### 4.C (Considered, not recommended now) Embedding/cosine similarity
- Would solve RC-1/RC-2 robustly but introduces a model dependency, per-item latency, and infra cost — **violates the zero-regression constraint**. Defer; the lexical action-gate captures most of the benefit at near-zero cost.

---

## 5. Implementation Plan — ZERO performance regression

**Performance guarantee basis:** every proposed check is an in-memory set operation on titles that are *already tokenized* for the existing similarity computation. No embeddings, no network, no extra DB round-trips; work is bounded by `CLUSTER_MAX_EVIDENCE = 40` per master. The audit itself scored 5,350 evidence items against their masters in seconds, single-threaded.

**Phase 0 — Guardrails (no behavior change)**
- Land all new logic behind an env flag `CLUSTER_STRICT_BINDING` (default `false`) for instant rollback.
- Committed `scripts/audit_clustering.py` as the permanent regression oracle.

**Phase 1 — Shadow measurement (no filtering)**
- Add `_evidence_coheres(master_tokens, ev_tokens) -> bool` = `_event_similarity ≥ τ` **OR** shared anchor **AND** shared action token.
- Compute and **log only** the per-cluster loose-fraction during ingestion/alerting. Zero behavior change; gather a real precision/recall curve to set `τ` and the action lexicon. Exit criterion: tuned config that prunes ≥90% of audited false positives while dropping <2% of valid sources.

**Phase 2 — Gate evidence binding (the highest-leverage, lowest-risk fix)**
- In `_get_evidence_metrics` (`:639-655`): replace the `ILIKE "%label%"` substring fallback with a tokenized-overlap filter (reuse `_event_tokens`) — same single indexed query, then in-memory filter.
- In `_absorb_into_master` / `_bump_master` (`:803-863`): drop incoming evidence items failing `_evidence_coheres` before the URL/title dedupe. O(n≤40).

**Phase 3 — Tighten ingestion (`analysis/clustering.py`)**
- Require a shared **action** token (not just geo) before the `+0.30` agreement bonus applies (`:123`).
- **Enforce** the >2-geo over-merge guard (`:224`) by splitting/penalising instead of only counting.

**Phase 4 — Domain backstop for evidence (4.B)**
- Add the domain-conflict rejection + spillover allow-list to the evidence path only. Master selection unchanged.

**Phase 5 — One-off backfill (reversible)**
- Read-mostly script to re-score existing `evidence_list`s and move loose items out (mark, don't delete) — mirrors the existing `--dry-run` pattern in `scripts/collapse_duplicate_events.py`. Run dry first; report counts; commit only on approval.

**Rollout & verification**
- Ship `false`→shadow→canary→on. After each phase, re-run the audit; gate on loose-evidence % dropping toward 0 and the valid-source retention staying ≥98%.
- Rollback = flip the env flag; no schema changes required.

---

## Appendix — Audit reproduction
Read-only, no writes: `py -3 scripts/audit_clustering.py`. Reuses production `jobs.alert_manager._event_tokens` / `_event_similarity` and `analysis.clustering.GEO_ENTITIES` so the audit mirrors live clustering exactly. Thresholds used: `LOOSE_SIM = 0.12`, `MIN_EVIDENCE = 3`, latest 400 active (unsuppressed) alerts.
