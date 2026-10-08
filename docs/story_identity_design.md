# Story identity: one story, one alert — design for review

**Status:** design for review. Nothing in this document is built; no code and no schema change.
**Date:** 2026-10-08. **Scope:** going forward only. By the operator's decision, past months are not repaired; the
duplicated August–October counts age out of Monthly Trend Flow within three months.
**Related:** vault audit §12.68 (the Monthly Trend Flow double count); `docs/clustering_quality_proposal.md`
(2026-06-03, cluster over-merge), which this design depends on but does not solve.

All numbers below were measured on production through read-only queries on 2026-10-08, or read from code at
`main` `0fc1b1e`. Where a number is a proxy, the proxy is named.

---

## 0. The defect, as measured

- **The visible symptom:** Monthly Trend Flow counts the same story more than once: 47.5% of August's 1,076 counted
  alerts, 42.2% of September's 1,300, 31.9% of October's 226 so far. The same is true of the Alert Stream and
  everything else that reads `alert_logs`. Re-fires come almost exactly 24.0h apart.
- **Where the duplicate is born: the alert layer.** In live data, three stories re-alerted 24h + 1–2 min after
  their first alert from **the same single signal**, with no new signal or cluster in between. One example:
  "Russian firm completes country's first 130nm-capable chipmaking tool": one signal at 10-05 10:56:09, alerts at
  10-05 10:57:45 and 10-06 10:59:24.
  - **Input outlives memory.** `run_alert_manager` re-reads every signal from the last **30h** on each 5-minute run
    (`jobs/alert_manager.py:1398-1400`).
  - **No link back.** The alert stores no signal or cluster id (`:770-781`).
  - **Its only memory is 24h.** That is the match window (`CLUSTER_WINDOW_HOURS = 24`) plus the hourly purge
    (`ALERT_RETENTION_HOURS = 24`).
  - Absorbing a duplicate does not refresh an alert's clock; only an escalation bump does.
- **The two layers below also forget at 24h.**
  - **Clusters:** reconciliation compares only against clusters *created* in the last 24h, by title-token Jaccard
    ≥ 0.75 (`analysis/clustering.py:390-441`). The September bond-yield story got six clusters with an identical
    title on six consecutive days, and its items were moved to each new one.
  - **Signals:** the duplicate guard is `(trend_type, title)` for 24h (`jobs/signal_job.py:36`, `:423`). A fresh
    signal for the same story appears daily, which is what sustains the cycle past day 2.
- **The only identifier that survives:** the item URL hash (`items.dedup_key`), kept 30 days.

## 1. A measurement that rules out the obvious key

The obvious key is "a story is identified by the URLs it shares". **It does not separate stories.** Membership was
proxied by each frozen alert's `evidence_list` (2,603 alert payloads in `monthly_trend_reports`; normalised with the
alert manager's own `_normalize_article_url`).

| pairs | count | share ≥1 evidence URL |
|---|---|---|
| same story (consecutive alerts with the same primary URL) | 1,078 | **100%** |
| different stories (different primary URL, headline similarity < 0.3, within 7 days) | — | **2,833 pairs share ≥1** |

- A stricter rule (≥2 shared, overlap ≥ 0.5) still falsely links 781 different-story pairs, and catches only 31% of
  the real repeats.
- In 1,416 of the 2,833 different-story pairs, one alert's own headline URL appears in the other's evidence.
- **Why:** evidence lists are built from cluster membership, and clusters bind topically adjacent coverage. That is
  the June proposal's finding: 69% of evidence items loosely bound, an "Iran" theme spread across five domains.
- **Consequence for this design:** identity cannot be *re-derived* from overlapping URLs. It has to be **assigned
  once and carried**: an item is assigned to a story, and that assignment is the stable fact.

---

## A. The story record

### A.1 What identifies a story

**A story is identified by its own id, minted once. Its identity is carried by the items assigned to it.**
- When the pipeline groups items (today's in-memory `cluster_items`, unchanged in method), the group is mapped to a
  story by **the items it already contains**. Each item already assigned to a story votes for that story.
- **Growth works by construction.** On day 1 the story has 3 items. On day 2 the regrouping contains those 3 plus 5
  new ones. The 3 old members vote, the group maps to the same story, and the 5 new items are appended.
- **Titles never decide whether a group is an existing story.** Titles (today's similarity test) decide only how
  brand-new items are grouped, which is what the in-memory clustering already does. Identity rides on assignments,
  which the URL-hash item identity makes stable.
- **An anchor item is recorded:** the first item assigned, kept for display and debugging. Identity does not depend
  on it.
- **Measured basis:** in the bond-yield trace the day-2…day-6 clusters contained the same earlier items (they were
  moved into each new cluster), so the regrouping does keep returning the old members. The mechanism this design
  needs is already happening; today it is thrown away by minting a new UUID.

### A.2 How membership is stored, and why it must not repeat `items.cluster_id`

- **A new membership record, `story_items(item_id PK, story_id, assigned_at)`. Insert only.**
- An item is assigned **once**, the first time it lands in a group. It is never reassigned.
- **Contrast with today:** `items.cluster_id` is overwritten on every reconcile or create
  (`clustering.py:451-452`, `:509-510`), seven times per run (once per topic loop) plus once by report generation
  (`report_generator.py:370`).
- The primary key on `item_id` enforces "one story per item" in the schema, not by convention.
- **Accepted cost:** an item mis-grouped on first sight stays with that story. Given the measured over-merge, this is
  the main limit of the design; see §B.4.
- `items.cluster_id` is not repurposed. Once nothing reads it for identity, it can be left as-is or removed later
  (§D).

### A.3 What a story carries

| field | purpose |
|---|---|
| `id` | the stable identity |
| `anchor_item_id` | first assigned item (display, debugging) |
| `first_seen_at` / `last_seen_at` | first and latest member item's `created_at` |
| `representative_title` | display only; may be refreshed; never used for matching |
| `category` / domain | as clusters carry today |
| `member_count` | derived from `story_items` (replaces the inflating `article_count`; §D.6) |
| `merged_into` | set when two stories merge (§B.3); null otherwise |
| `alert_state` | per domain: last alerted at, the severity alerted, member count at that alert (§C) |

**`alert_state` lives on the story, not in `alert_logs`.** That is what lets "already alerted" outlive the 24h purge
without changing `ALERT_RETENTION_HOURS`. The audit of the ~30 `alert_logs` readers (2026-10-08) showed raising that
setting would silently change several screens.

### A.4 Lifetime and pruning

- **Measured chain duration** (first to last occurrence of the same story, 862 multi-occurrence stories):
  median 1.0 day, p90 3.8 days, max 8.2 days. The signal lookback is 168h (`SIGNAL_LOOKBACK_HOURS`).
- **A story must outlive its member items:** `story_items.item_id` references `items`, which are deleted at 30
  days. Also, "already alerted" must hold for the whole life of a story's re-firing, up to 8.2 days measured, far
  beyond the 24h alert memory.
- **Proposed:** prune a story **35 days after `last_seen_at`**. That exceeds the 30-day item retention, so a story
  never outlives the evidence of its membership by much, and never dies while its items still exist. It is pruned
  by the existing daily retention job. `story_items` rows go with their items (`ON DELETE CASCADE` from `items`).
- **Volume:** 38.3 alerts/day, and 1,523 distinct primary URLs across August to October (about 2.25 months; roughly
  680 a month) by the measured primary-URL proxy. At 35-day retention the story table stays in the low thousands.

## B. How items are matched to a story

### B.1 The rule

On each run, after the in-memory grouping:
1. **Look up memberships.** Collect the stories the group's items are already assigned to.
2. **No assigned members:** mint a new story. Assign all the group's unassigned items to it.
3. **Members from exactly one story:** that is the story. Append the group's unassigned items.
4. **Members from two or more stories:** see §B.3.

**The key is item membership, through the URL-hash item identity.** It is never title similarity across runs, and
there is no time window on "existing", other than stories pruned by §A.4.

### B.2 Why this fixes the 24h break

The cluster layer broke because "existing" meant "a cluster created in the last 24h, with a similar representative
title". Under §B.1, an existing story is found **however old it is**, as long as the regrouping contains one of its
members.

### B.3 Merges and splits

- **Merge (a group spans two stories):**
  - The story with the earliest `first_seen_at` survives. The other gets `merged_into = survivor`.
  - `story_items` rows are **not rewritten**. Reads resolve `merged_into` one step. Chains are flattened at merge
    time, so it is never more than one hop.
  - The two `alert_state`s are combined: earliest alert, highest severity alerted. So a merge does not by itself
    trigger a new alert.
- **Split (a group contains only some of a story's members):** nothing happens. The story keeps all its members;
  the group's unassigned items join it. There is no split operation. With assign-once membership a split cannot be
  expressed without reassigning items, which is what this design forbids.
- **Recorded as the trade-off:** over-merged early groups produce over-broad stories. That is better than today,
  where the same breadth is re-minted daily and alerted daily.

### B.4 Interaction with cluster over-merge (not solved here)

- The June proposal found groups bind topically adjacent but distinct events. With assign-once membership, **an
  over-broad group makes an over-broad story permanently.**
- And because §B.3 merges on any shared member, a few bridging items could chain distinct stories together.
- **Guard, proposed for review:** a group maps to an existing story only if **at least half** of its
  already-assigned members belong to that story. Two stories merge only if each contributes **at least two**
  members to the group. A single bridging item otherwise cannot fuse two stories.
- **Measure this before building it**, by replaying recent groups: how many merges each threshold produces. The
  thresholds above are proposals, not measurements.
- Improving the grouping itself (the June proposal) is separate work, and makes this design better without changing
  it.

## C. The alert rule

### C.1 "Already alerted", and what justifies a new alert

- An alert is minted for a `(story, domain)` pair only if one of these holds:
  1. **No alert yet:** that pair has never alerted.
  2. **Severity escalated** by at least one tier above the severity last alerted (watch → elevated → critical).
  3. **Genuinely new reporting:** the story gained **at least N members created after its last alert**, from **at
     least one source not already among its members**. N is proposed as 2; to be confirmed by replay.
- **Not enough on its own:** a changed headline, or a different evidence list. Evidence lists are reshuffled
  between runs (measured below).
- The 24h text-match path (`_find_event_cluster`) is kept only to absorb corroboration into a live alert's evidence
  within the day. It no longer decides whether an alert is created.

### C.2 What today's data says the rule would do

Consecutive same-story re-alerts, August–October (1,078 pairs):

| change between consecutive alerts | pairs | share | rule outcome |
|---|---|---|---|
| title same, no new evidence | 803 | 74.5% | **suppressed** |
| title same + new evidence URL(s) | 175 | 16.2% | **depends on whether the new evidence is new reporting** (below) |
| title changed, no new evidence | 52 | 4.8% | suppressed (a headline change alone is not new information) |
| title changed + new evidence | 36 | 3.3% | depends, as above |
| severity raised (any title/evidence) | 12 | 1.1% | **re-alert**, by rule C.1.2 |

Severity was lowered in 20 pairs; a lowering never re-alerts.

**"New evidence" is half reshuffling.** Of the new evidence URLs in September–October repeats, **102 belonged to items
created after the previous alert** (genuinely new reporting) and **96 to items that already existed** (the evidence
list was re-drawn from the same coverage). That is why rule C.1.3 counts **story members created after the last
alert**, not differences in the evidence list. Under it, about half of the ~20% "new evidence" repeats would still be
suppressed.

**Estimated effect:** of the 1,078 measured re-alerts, roughly **85–90% would not be minted**. This is an estimate from
the proxy: evidence lists stand in for membership.

### C.3 Domains

- 29 of the 1,078 same-story pairs crossed domains. Today the alert manager deliberately never merges across
  domains, so one story can alert once in Energy and once in Defense.
- **This design keeps that:** alert state is per `(story, domain)`. Whether a story should alert in only one domain
  is a product decision, listed in §F. It is not a defect of this design.

## D. What changes in each component, and what each change affects

| component | change | user-visible effect |
|---|---|---|
| **clustering** (`analysis/clustering.py`) | Grouping method unchanged. **Replace reconciliation** (24h `created_at` window, title Jaccard ≥ 0.75, reassignment of `items.cluster_id`) with §B.1 against `story_items`. `event_clusters` writes stop or become a per-run log; nothing should depend on them for identity. | none directly |
| **report generation** (`jobs/report_generator.py:370`) | Stop calling `cluster_items` itself (it re-clusters and reassigns `cluster_id` outside the pipeline). Read stories and members instead. | report trend sections reference stable stories |
| **signal job / trend engine** | Carry `story_id` on every `TrendSignal`. Change the duplicate guard from `(trend_type, title)` for 24h to `(trend_type, story_id)`, **updating** the story's signal instead of re-inserting. Signal retention (72h) unchanged. | none directly |
| **alert manager** | Read `story_id` from the signal. Apply §C. Store `story_id` in the alert's metadata, so Monthly Trend Flow and others can see it. | **Alert Stream: the daily re-fires stop.** 38.3 alerts/day today. About 42% are repeats and §C.2 estimates 85–90% of those are suppressed, so roughly 24/day after (estimate) |
| **Monthly Trend Flow** | **No change needed.** It counts alerts; once duplicates are not minted, it counts stories. Optionally key the union on `story_id` later. | counts from the cutover date forward reflect distinct stories |
| **event-driven report triggering** (`trigger_detector_job`, `signal_rankings`) | Rankings reference `story_id`. Triggers fire on a story's first ranking, or its escalation, rather than on a re-minted cluster. | fewer repeated event-driven reports for one story (not measured; measure before and after) |

### D.5 The two dead mechanisms

- **`_check_recent_duplicate`** (`jobs/alert_manager.py:1071`). A headline-dedup with a reignite factor. **Nothing
  calls it.** §C replaces its purpose: "already alerted, unless it escalated". **Remove it** in the same change,
  rather than leave a second, uncalled answer to the same question.
- **The cross-day `sustained_event` detector** (`analysis/trend_engine.py:468-475`). It reads
  `summary_data["top_entities"]`, but clusters only write `top_geos` / `top_orgs` (`clustering.py:500-506`), so
  `ent_overlap` is always 0 and it can never fire. It was the one mechanism meant to link a story across days; the
  story record replaces it with an actual identity. **Remove it.** Fixing the key would revive an entity-overlap
  heuristic that §1 shows cannot separate stories.

### D.6 `article_count` — in scope

- Reconciliation does `article_count += len(cluster)` on every run, seven times per run. Measured: **2,019** for a
  story with four articles.
- Once membership lives in `story_items`, the story's `member_count` is a count of rows. Nothing is incremented, so
  it cannot inflate.
- `event_clusters.article_count` stops being written. It is in scope because §B replaces the code that inflates it;
  there is nothing separate to fix.
- **Readers of `article_count` must be found and repointed to `member_count`.** That is not yet measured.

## E. Migration (what exists on the day this ships)

- **`event_clusters` (31-day retention):** not converted. Stories start empty at cutover, and old clusters age out
  on their own. No backfill: the operator decided against repairing the past, and cluster membership history does
  not exist anyway (`items.cluster_id` was overwritten).
- **Items already in the 168h signal window:** on the first run after cutover, every current group mints a story and
  assigns its items. **This is the cutover risk:** each active story would look like "never alerted" and could alert
  once more, even if it alerted in the last 24h.
- **Seeding `alert_state` from `alert_logs`** (the last 24h; 69 rows on 2026-10-07): for each live alert, find the
  story that its `related_item_ids` (stored in alert metadata) are now assigned to, and record that alert as the
  story's last alert. That converts the cutover spike into at most a re-alert of stories whose last alert is older
  than 24h, which today re-alert daily anyway.
- **Signals in flight (72h, no `story_id`):** the alert manager ignores signals without `story_id` from the cutover.
  New signals carry it from the first run, within 5 minutes. Ignoring legacy signals costs nothing, because their
  stories regroup and re-signal immediately.
- **Alerts in flight:** untouched. They age out at 24h as today.
- **Monthly Trend Flow:** October's snapshot keeps its duplicates. From the cutover, new entries stop duplicating.
  October's figure is therefore part-duplicated, and will read as such until it ages out.
- **Order:**
  1. the migration (the story tables, created under the existence-check discipline of `6b365c6550e8` /
     `c7d2e4f1a9b3`);
  2. the code;
  3. the scheduler deploy (clustering, signals and alerts all run in the scheduler).
  The API redeploy alone changes nothing.

## F. Decisions for the operator

1. **Re-alert threshold:** N new members (proposed 2) and the new-source condition, to be confirmed by replaying a
   week of groups.
2. **Merge guards:** the majority and two-member thresholds (§B.4), likewise by replay.
3. **Cross-domain alerts:** keep one alert per `(story, domain)` (today's behaviour), or one per story.
4. **Story retention:** 35 days after last seen.
5. **`items.cluster_id` and `event_clusters`:** keep writing them as a per-run log, or stop. The decision depends on
   who reads them; that reader list is a short measurement still to do.

## G. Measured before building (verification plan)

- **Replay before shipping.** Using the 168h of items at a fixed time, run the new grouping and story mapping in a
  copy of the database. Report: stories created, merges, members per story, and how many of the last week's alerts
  would have been suppressed by §C. The 85–90% estimate is then measured rather than estimated.
- **Readers.** Find every reader of `items.cluster_id`, `event_clusters.article_count`, and `TrendSignal.metrics_json
  ["cluster_id"]` before changing their writers.
- **After shipping:** the repeat rate in the Alert Stream and in Monthly Trend Flow, measured daily with the same
  primary-URL proxy as §12.68. The target is the residual rate the replay predicts, not zero: escalations and
  genuinely new reporting re-alert by design.
