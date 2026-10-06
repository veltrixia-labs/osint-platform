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
- ★ **The scheduler does not auto-deploy.** After a merge it keeps running the **previously deployed commit** against the **same shared database**. The API and web can therefore be on one version while the scheduler is on another.
  - A change to scheduler code (`jobs/`), or to anything the scheduler imports (`db/models.py`, `config/`, `data_sources/`), does not reach production until someone deploys `osint-scheduler` by hand.
  - The three merges of 2026-10-06 (`3f87572`, `4d39420`, `fd7aaf3`) are deployed to the API and web. **The scheduler was not redeployed and still runs its previously deployed commit, which the repository cannot identify.**
  - Measured across `5cf6e8e..fd7aaf3`:
    - `config/settings.py` and `data_sources/base_client.py`: `load_dotenv` override `True` → `False` only.
    - `db/models.py`: comments only.
    - `jobs/load_impact_roster.py` (deleted) and `jobs/load_scenarios.py` (guard): the scheduler references neither.
    - No migration.
  - **No manual scheduler deploy is needed for these merges.** The only behavioural change it would pick up is `.env` precedence, which matters only if a `.env` file exists in its runtime directory. `.env` is gitignored, and Render builds from git. **Check the dashboard for a Secret File named `.env`.** If one exists, the old scheduler lets it override env vars and the new code would not.
  - **A manual scheduler deploy becomes necessary when:**
    - a merge changes `jobs/`, `analysis/`, `config/`, `data_sources/` or non-comment `db/` code
    - a migration lands that the old code would conflict with
    - such a Secret File exists
  - When deploying it by hand, make sure only one instance runs. `render.yaml:35-36` records a past incident in which two schedulers contended for a database lock.
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
