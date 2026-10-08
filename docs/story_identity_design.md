# Story identity: one story, one alert — design for review

**Status:** design for review. Nothing in this document is built; no code and no schema change.
**Revised 2026-10-08 after operator review:** continuity floor of two (§B.4), absorption record (§B.5), headline rule C.1.4, and the replay as a precondition (§G). §B.4 also records a correction to a claim made during review.
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
1. **Look up memberships.** Collect the stories the group's items are already assigned to, and count the group's
   members in each.
2. **Continuity needs a floor of two.** A group maps to an existing story only if **at least two of its items already
   belong to that story** (§B.4 gives the measurement behind this).
3. **No story reaches the floor:** mint a new story and assign the group's **unassigned** items to it. Any members
   already assigned elsewhere stay where they are, because membership is assign-once.
4. **Exactly one story reaches the floor:** that is the story. Append the group's unassigned items, and record the
   mapping (§B.5).
5. **Two or more stories reach the floor:** merge, per §B.3.

**The key is item membership, through the URL-hash item identity.** It is never title similarity across runs, and
there is no time window on "existing", other than stories pruned by §A.4.

### B.2 Why this fixes the 24h break

The cluster layer broke because "existing" meant "a cluster created in the last 24h, with a similar representative
title". Under §B.1, an existing story is found **however old it is**, as long as the regrouping contains at least two
of its members.

### B.3 Merges and splits

- **Merge (two or more stories each reach the floor of two members in one group):**
  - The story with the earliest `first_seen_at` survives. The other gets `merged_into = survivor`.
  - `story_items` rows are **not rewritten**. Reads resolve `merged_into` one step. Chains are flattened at merge
    time, so it is never more than one hop.
  - The two `alert_state`s are combined: earliest alert, highest severity alerted. So a merge does not by itself
    trigger a new alert.
  - Every merge is recorded (§B.5).
- **Split (a group contains only some of a story's members):** nothing happens. The story keeps all its members;
  the group's unassigned items join it (if the floor is met) or start a new story (if not). There is no split
  operation. With assign-once membership a split cannot be expressed without reassigning items, which is what this
  design forbids.

### B.4 The guard against over-broad stories: a floor of two members, not a majority

- **The risk:** the June proposal found groups bind topically adjacent but distinct events. With assign-once
  membership, a group that carries one stray article of an earlier story would map onto that story. A distinct event
  would then be **absorbed**: it never gets its own story, and therefore never its own alert.
- **Measured (2026-10-08, alert evidence lists as the membership proxy):**
  - **253 of 1,523 distinct stories (16.6%)** in August–October had their own headline article already sitting in
    an earlier, unrelated alert's evidence within 7 days. Those are the candidates to be absorbed.
  - In a random sample of 14 such pairs: 5 were the same developing story (absorption is right), 5 were the same
    theme but a different incident (debatable), and **4 were unrelated events** (absorption hides a real event).
    That is roughly **4–6% of all stories** lost to an unrelated earlier story. This is an estimate from a 14-item
    sample and a proxy; §G requires it to be measured.
  - **A real example:**
    - The 08-20 19:05 Supply Chain alert "China growth straining global auto shipping capacity: Liner CEO" carried in
      its evidence the article that, about 24h later (08-21 18:55), headlined its own alert: "Panama Canal to limit
      shipping ahead of extreme weather during El Nino". Today it then re-alerted daily on 08-22 and 08-23.
    - Under assign-once, that article would already belong to the China story. The Panama Canal event would appear
      as one evidence line for 24h and never headline.
    - Nothing would record that it was absorbed.
  - **★ Correction, recorded rather than overwritten.** An earlier draft of this section, and the review message
    that preceded it, said "every one of the 253 rests on a single bridging article". **That was wrong.** The query
    selected pairs on one shared article (the later story's headline) and never counted how many each pair shares.
    Measured afterwards:

    | evidence articles shared by the earlier alert and the later story's first alert | candidates |
    |---|---|
    | exactly 1 | **77 (30%)** |
    | 2 | 67 |
    | 3 | 54 |
    | 4 | 32 |
    | 5 or more | 23 |

    So **176 of 253 (70%) share two or more.** The Panama Canal example shares **all six**: the two alerts' evidence
    lists are identical. Both were leads drawn from one over-broad "shipping" group, which also contained "South
    Korea Tests Arctic Shipping Route", a malware story about "shipping" network drivers, and a Corpus Christi
    nuclear-shipping item. That is the June over-merge exactly.
- **Why the floor is two members, not "a majority of the assigned members".**
  - The first draft of this design proposed "a group maps to an existing story only if at least half of its
    already-assigned members belong to that story". **A single bridging article satisfies that as 1 of 1**, so the
    guard passes in exactly the case it exists to catch.
  - That is the same shape as the vault's self-comparing assert (`staleness_sweep.py`'s guard that compared a value
    with itself, vault audit §12.57) and its stale node-count literals: **a check that cannot fail for the case it
    exists to catch.**
  - A floor of two shared members cannot be satisfied by one bridging article.
- **★ What the floor does and does not do, measured:** it closes the 1-of-1 hole, so it is **necessary**. But by the
  evidence proxy it would block only about **30%** of absorption candidates. **It is not sufficient.**
  - The other 70%, Panama included, arise inside one over-broad group, where any number of shared members is
    available.
  - **That residue is a property of the grouping (the June over-merge), not of story identity.** No membership
    threshold can separate two events that the grouping has already put in one bag.
  - **What does surface the Panama case is rule C.1.4:** on 08-21 the Panama article became the group's headline, a
    never-before headline for that story, so under C.1.4 it alerts once under its own title.
  - So the protection against silent absorption is **the floor (for single-bridge cases), plus C.1.4 (for events
    that become the lead), plus §B.5's record (for everything else, so it is measured).**
  - An absorbed event that never becomes its group's lead is still lost to the headline. The replay must count how
    often that happens.
- **What the floor costs:**
  - A genuine continuation whose regrouping carries only one prior member will start a new story instead of
    continuing the old one. That is a duplicate, the visible and information-preserving failure, not an absorption.
  - **The trade is deliberate: when in doubt, prefer a visible duplicate to a silent loss.**
  - **Whether two is the right floor is not known until the replay (§G).**
- Improving the grouping itself (the June proposal) is separate work, and makes this guard matter less without
  changing it.

### B.5 Recording absorptions and merges, so the failure is measurable

- **The model is `ingest_rejections`**, which shipped on 2026-10-07 for the same reason: a filter that drops things
  silently hides its own failure.
- **A new table, `story_absorptions`. One row per mapping of a group onto an existing story, and one per merge:**

| column | meaning |
|---|---|
| `id` | row id |
| `story_id` | the existing (or surviving) story the group was mapped onto |
| `kind` | `continuation` (§B.1 step 4) or `merge` (§B.3) |
| `bridging_item_ids` | the already-assigned members that carried the mapping (two or more by the floor), **named**, not counted |
| `joined_item_ids` | the previously unassigned items that joined the story in this mapping |
| `merged_story_id` | for `merge`: the story that was merged in |
| `group_representative_title` | what the group was "about" when it was mapped, so a reader can see a mismatch |
| `story_representative_title` | what the story was about before the mapping |
| `created_at` | when |

- **It is readable with SQL, not a log line.** For example, the mappings that rested on the minimum bridge, with both
  titles side by side so a mismatch is visible:

```sql
SELECT created_at, kind,
       story_representative_title, group_representative_title,
       cardinality(bridging_item_ids) AS bridges,
       cardinality(joined_item_ids)   AS joined
FROM story_absorptions
WHERE created_at > now() - interval '7 days'
  AND cardinality(bridging_item_ids) = 2
ORDER BY created_at DESC;
```

- **Retention:** as for stories (35 days after creation), pruned by the daily retention job.
- **Exposure:** it is not served by any API route. That includes `GET /api/metrics`, which is public.
- **What this changes:** the Panama Canal case stops being silent. Each absorption leaves a row naming the bridge
  and both titles, so the absorption rate can be measured daily rather than estimated once.

## C. The alert rule

### C.1 "Already alerted", and what justifies a new alert

- An alert is minted for a `(story, domain)` pair only if one of these holds:
  1. **No alert yet:** that pair has never alerted.
  2. **Severity escalated** by at least one tier above the severity last alerted (watch → elevated → critical).
  3. **Genuinely new reporting:** the story gained **at least N members created after its last alert**, from **at
     least one source not already among its members**. N is proposed as 2; to be confirmed by replay.
  4. **A member's first appearance as the headline:** the story's representative (headline) item changed to an item
     that has never been the story's headline before, **even if that item already existed when the last alert
     fired**.
- **Why rule 4 is needed.**
  - The benign absorption case is an escalating development whose article already existed. For example, "Saudi
    Aramco's Jizan Refinery Hit Again as Houthi Attacks Escalate" sat in the evidence of the 09-08 alert "Oil Prices
    Near $100 After Fresh Attacks on Saudi Energy Sites", then headlined its own alert on 09-09.
  - Rule 3 counts only members **created** after the last alert, so it can never fire for that article. Without
    rule 4, the design **suppresses exactly the thing it should surface**: an existing article becoming the lead of
    an escalating story.
  - Rule 4 is scoped to a never-before headline, so the same headline re-surfacing day after day (the 74.5% repeat
    case) still does not re-alert.
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
| **story mapping** (new, with clustering) | Writes `story_items` (insert-only) and `story_absorptions` (§B.5); tracks each story's headline history for rule C.1.4. | none directly; `story_absorptions` is the operator's measurement surface |
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

1. **The continuity floor (§B.4):** two shared members, not a majority.
   - A majority test is satisfied 1 of 1 by a single bridging article, so it cannot fail for the case it exists to
     catch.
   - ★ **But the floor is necessary, not sufficient.** The earlier claim that every absorption rests on one bridging
     article was wrong: measured, 30% do and 70% share two or more (§B.4).
   - Most absorption risk comes from the over-broad grouping itself. Against that, the protection is rule C.1.4 plus
     the §B.5 record, not the floor.
   - Whether two is right, and how much absorption survives all three, is decided by the replay (§G).
2. **The re-alert threshold (§C.1):** N new members (proposed 2) plus the new-source condition, and rule C.1.4
   (a never-before headline re-alerts). Likewise decided by the replay.
3. **Cross-domain alerts:** keep one alert per `(story, domain)` (today's behaviour), or one per story.
4. **Story and absorption-record retention:** 35 days after last seen / after creation.
5. **`items.cluster_id` and `event_clusters`:** keep writing them as a per-run log, or stop. The decision depends on
   who reads them; that reader list is a short measurement still to do (§G).

## G. Measured before building — the replay is a precondition, not a validation

**Nothing in §B or §C is built until the replay has run and its results have been reviewed.**
- The design rests on numbers that have never been measured against real grouping: the continuity floor of two
  (§B.4), N = 2 new members (§C.1.3), and the 4–6% absorption estimate. That estimate comes from a 14-item sample and
  an evidence-list proxy.
- **If the replay measures absorption at, say, 10% rather than 4–6%, or shows the floor turning most continuations
  into duplicates, the design changes before any code exists.** A replay run after building would only describe a
  defect already shipped.

**1. The replay.**
- **Method:** take the items from the 168h signal window at a fixed point in time. Run the existing in-memory
  grouping, then the §B.1 mapping (with the §B.4 floor), then the §C rule, in a copy of the database. Then step
  forward run by run over at least 7 days of real items, so continuations, merges and absorptions actually occur.
- **It must report, explicitly:**
  - stories created, continuations, merges, and members per story (distribution);
  - **every absorption, not only minimum-bridge ones** (70% of candidates share 2+ members, §B.4). Each listed with
    its bridge size and both titles side by side;
  - in particular, **every mapping that rested on exactly the minimum bridge (two members), listed with both titles side by side:**
    the story's representative title and the group's representative title. A reader must be able to see absorptions
    like Panama Canal → China auto shipping directly. **The 4–6% absorption estimate is then measured, not
    estimated;**
  - groups that fell below the floor and started a new story despite sharing one member with an existing story,
    i.e. the duplicates the floor deliberately creates, also with titles;
  - **the re-alerts each rule would mint (C.1.1–C.1.4) against the same period's actual alerts:** how many of the
    measured 1,078 repeats are suppressed. The 85–90% estimate is then measured;
  - for rule C.1.4: how many re-alerts it adds, with titles, so the escalating-development case (Jizan "hit again")
    and the over-broad-group case (Panama Canal) can be checked to fire, and the daily-repeat case to stay
    suppressed;
  - **absorbed events that never became their group's lead:** the residue that neither the floor nor C.1.4 surfaces,
    with titles. This is the number that decides whether the design is acceptable without first fixing the grouping
    (the June proposal).
- **Stop conditions:** if measured absorption (unrelated events lost) exceeds the operator's tolerance, or if the
  floor turns most continuations into duplicates, revise §B.4 or §C before building. The operator sets the
  tolerance before the replay runs, not after seeing the number.

**2. Readers.** Find every reader of `items.cluster_id`, `event_clusters.article_count`, and
`TrendSignal.metrics_json["cluster_id"]` before changing their writers.

**3. After shipping:**
- the repeat rate in the Alert Stream and in Monthly Trend Flow, measured daily with the same primary-URL proxy as
  §12.68. The target is the residual rate the replay predicted, not zero: escalations, genuinely new reporting and
  new headlines re-alert by design;
- `story_absorptions` read daily with the §B.5 query, comparing the minimum-bridge mappings against the replay's
  rate. A rise means the grouping has drifted and the floor needs revisiting.
