# Render deployment — what is actually configured

**Confirmed on 2026-10-06** from the Render dashboard (screenshots supplied by the operator), and by the three releases deployed that afternoon (see "What this means for merging").
**The dashboard is authoritative.** If this file and the dashboard disagree, the dashboard is right and this file is stale.
Re-read the dashboard before relying on any value here, and record the new date when you do.
This file is a record of one reading. It is not a specification, and nothing reads it.

## Services

| service | type | region | branch | root dir | build command | start command | pre-deploy | Auto-Deploy |
|---|---|---|---|---|---|---|---|---|
| `osint-platform` | Web Service, Python 3 | Oregon | `main` | unset | `pip install -r requirements.txt && pip install -e . --no-deps` | `alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port $PORT` | empty | **On Commit** |
| `osint-web` | Static Site | Global | `main` | `web_dashboard` | `npm install && npm run build` | — (publish `web_dashboard/dist`) | — | **On Commit**, no ignored paths |
| `osint-scheduler` | Background Worker, Python 3 | Oregon | `main` | unset | `pip install -r requirements.txt` | `python -m jobs.main_scheduler` | empty | ★ **OFF** |
| `osint-db` | PostgreSQL 18 | Oregon | — | — | — | — | — | — |

All three services build from the same repository, `veltrixia-labs/osint-platform`.

## What this means for merging to `main`

- **Every commit to `main` deploys the API immediately. The web dashboard deploys only when the commit changes something under `web_dashboard/`.** There is no staging environment, so a merge is a release.
  - ★ **Corrected 2026-10-06.** This line used to say that a merge deploys both. That was wrong: osint-web's Root Directory is `web_dashboard`, and Render auto-deploys a service only on changes inside its Root Directory.
  - Measured: merge `3f87572` (fix/test-env-isolation, nothing under `web_dashboard/`) redeployed the API (dashboard: Live, 1m50s), while osint-web stayed on `9278aec` and the live asset stayed `main-CLDPSrle.js`.
  - Merges `4d39420` and `fd7aaf3` both changed `web_dashboard/`, and both rebuilt the web (`main-BYxvfQTw.js`, then `main-YcsGd-zy.js`).
  - API and web deploys are therefore decoupled. A web-only fix still redeploys the API (whose Root Directory is unset), but an API-only change leaves the web untouched.
- ★ **The scheduler: the SETTING and the PRACTICE are different facts, so they are kept separate here.**
  - **Setting:** osint-scheduler's Auto-Deploy is **Off**. Nothing deploys it automatically. After a merge it keeps running its previously deployed commit against the **same shared database**.
  - **Practice:** the operator **deploys osint-scheduler by hand after every merge**, as a deliberate step, and checks its settings each time (operator-confirmed 2026-10-06).
  - **So version skew between scheduler and API/web is possible in principle but does not normally occur,** because a human closes it. The window is from the merge to that manual deploy.
  - ★ This file said until 2026-10-06 that the scheduler "keeps running the previously deployed commit" after a merge. That was an inference from the setting alone, and it described a drift that the practice prevents.
  - A change to scheduler code (`jobs/`), or to anything the scheduler imports (`db/models.py`, `config/`, `data_sources/`), reaches production only through that manual deploy.
  - ★ **2026-10-06 is an exception by decision, not by omission.** The three merges (`3f87572`, `4d39420`, `fd7aaf3`) were deployed to the API and web, and **osint-scheduler was deliberately NOT redeployed.** None of them touches scheduler behaviour, as measured below, so it is being left as it is. Do not read this as the practice having been skipped.
  - Measured across `5cf6e8e..fd7aaf3`:
    - `config/settings.py` and `data_sources/base_client.py`: `load_dotenv` override `True` → `False` only.
    - `db/models.py`: comments only.
    - `jobs/load_impact_roster.py` (deleted) and `jobs/load_scenarios.py` (guard): the scheduler references neither.
    - No migration.
  - **The three merges are a no-op for the scheduler, whether or not it is ever deployed by hand. Measured 2026-10-06.** The operator confirmed in the dashboard that osint-scheduler has **no Secret Files** (the list is empty). `.env` is gitignored, and Render builds from the git checkout. So there is **no `.env` in the scheduler's runtime**, and `load_dotenv` has nothing to read, with or without `override`.
    - ★ The reason is the **absence of that file, not the absence of changes.** The code the scheduler imports did change (`config/settings.py`, `data_sources/base_client.py`). The change cannot act on a file that does not exist.
    - This closes the one open condition in the earlier analysis, and it is recorded as measured, not inferred.
    - ★ **How the conclusion was reached.** The earlier "no manual scheduler deploy is needed now" (the operator's reading, and this file's analysis) was reasoned from the **configuration** (Auto-Deploy Off), without knowing the manual-deploy practice existed. It holds on its own terms: nothing the merges changed can act on the scheduler. But it was derived from how the system is configured, not from how it is actually run. That is the distinction this note exists to record.
  - **A manual scheduler deploy becomes necessary when:**
    - a merge changes `jobs/`, `analysis/`, `config/`, `data_sources/` or non-comment `db/` code
    - a migration lands that the old code would conflict with
    - a Secret File named `.env` is added to the scheduler (none exists as of 2026-10-06)
  - When deploying it by hand, make sure only one instance runs. `render.yaml:35-36` records a past incident in which two schedulers contended for a database lock.
- ★ **API and web deploy independently, and their order is not controlled.** Measured 2026-10-06:
  - Merge `4d39420`: the web asset switched at 16:19:42 JST, and the API reached its new route count at 16:20:45. For about a minute the **new frontend ran against the old API**.
  - Merge `fd7aaf3` had the same shape: web 16:24:21, API 16:25:23.

  **Why it was harmless that day:**
  - In `4d39420` the new frontend's only callers of the new routes are in the Pro Interactive Map. `/api/relationships` is fetched when a **Pro** user opens that tab (`renderRelationshipView`). `/api/relationships/coordinates` is fetched only from the Globe button. Neither is called on page load, and neither is reachable below Pro.
  - A Pro user who opened that tab during that minute would have received a 404 from the old API. The view renders that as "Relationship graph unavailable — HTTP 404" and the rest of the app keeps working, so the failure is visible and contained, not a crash.
  - Whether anyone actually hit it is **not known** (no traffic data was read).
  - In `fd7aaf3` the window ran the other way: the new frontend, with no roster tab, against an old API that still served the roster routes. Nothing calls a route that is missing, so it is harmless by construction.

  **What would make it unsafe:**
  - a frontend change that calls a new or changed route **on page load**, or for all tiers
  - a frontend that treats a 404 or 5xx as fatal
  - an API change that **removes or changes** a route the currently deployed frontend still calls, if the API happens to deploy first

  The safe pattern is to ship API additions in a merge before the frontend that uses them, and to remove a route only after the frontend that called it is gone.
- **Every API deploy runs a migration against production.** The start command begins with `alembic upgrade head`. API startup also calls `run_migrations()` (`api/main.py`), and so does scheduler startup (`jobs/main_scheduler.py`). On 2026-10-06 this was verified to be a **no-op** for the pending merges: production's `alembic_version` is `b4e1c7a2f9d3`, which equals the repository head, and no pending branch touches `alembic/`.
  - Any future migration runs on the very next merge to `main`.
  - Production's schema is not fully reproducible from migrations: three live tables (`system_metrics`, `stripe_events`, `analytics_events`) exist outside every migration. A migration that touches them must be written knowing they already exist (vault audit §12.53).
- **osint-web runs `npm install`, not `npm ci`.** On 2026-10-06 the merged tree was build-checked with `npm ci && npm run build`, taken from `render.yaml`. That check was **stricter than what Render actually runs, by accident, not by design**. It passed, and `npm ci` passing implies `npm install` passes, so the conclusion holds. But `npm install` can resolve versions the lockfile does not pin, and may rewrite the lockfile during the build. A local `npm ci` therefore does not reproduce Render's install exactly.

## `render.yaml` is not read by Render for these services

As far as can be determined, **`render.yaml` is decorative: Render does not apply it to the existing services, and its contents are wrong.**
- **It does not take effect:** `f275cb2` added `DEV_MODE` to it and was deployed, but the variable never reached the service. It had to be set by hand in the dashboard (measured 2026-08-21; recorded in the file's own header).
- **It contradicts the dashboard** on every point where they can be compared, except the API start command:

| field | `render.yaml` | dashboard (2026-10-06) |
|---|---|---|
| `osint-platform` build | `… && alembic upgrade head` (`:33`) | no `alembic upgrade head` |
| `osint-web` build | `cd web_dashboard && npm ci && npm run build` (`:64`) | `npm install && npm run build`, with root dir `web_dashboard` |
| `osint-web` root dir | not set (uses `cd`) | `web_dashboard` |
| `osint-scheduler` | absent | exists, Auto-Deploy OFF |
| branch / Auto-Deploy | not declared for any service | `main`, On Commit (scheduler OFF) |
| envVars | declared | not applied (see `DEV_MODE`) |
| `osint-platform` start | `:37` | identical |

- **Not determinable from the repository:** whether a Render Blueprint is linked to this file at all, for example for recreating services. Check the dashboard's Blueprints page. If one is linked, recreating a service from it would apply the wrong values above.
- **Do not edit `render.yaml` to change production.** Change the dashboard, then update this file with the new date.
