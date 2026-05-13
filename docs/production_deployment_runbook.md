# Veltrixia Production Deployment Runbook

## 1) Pre-Migration Audit

### Threads auto-posting
- Runtime path: `jobs/threads_publisher_job.py` -> `integrations/threads_client.py`
- Guardrails confirmed:
  - Quiet hours: UTC 01:00-05:00
  - Cooldown: 60 minutes
  - Daily cap: 5 successful posts/day
  - Polling cadence: every 10 minutes in `jobs/main_scheduler.py`
- Credential mode:
  - Production requires `THREADS_ACCESS_TOKEN` and `THREADS_USER_ID`
  - `jobs/threads_post_job.py` now fails fast in production if credentials are missing

### Stripe checkout + webhook
- Checkout endpoint: `GET /api/payments/checkout-session` in `api/payments.py`
- Webhook endpoint: `POST /api/payments/webhook`
- Webhook behavior:
  - Signature validation (`STRIPE_WEBHOOK_SECRET`)
  - Idempotency via `StripeEvent.event_id`
  - Tier sync updates `AnalystProfile.subscription_tier`

### Tier gating hardening
- Disabled production usage of local tier overrides:
  - `api/gating.py` only honors `LOCAL_DEV_TIER` when:
    - `ENV != production`
    - `ALLOW_DEV_TIER_OVERRIDE=true`
- Frontend unauthenticated fallback is fixed to `free` in `web_dashboard/src/main.ts`

## 2) Environment and Secrets

1. Copy `.env.production.example` -> `.env.production`
2. Fill real values:
   - `DATABASE_URL`
   - `JWT_SECRET_KEY` (and optional `SECRET_KEY` fallback)
   - Stripe live keys/secrets
   - Threads/Meta keys
3. Ensure:
   - `ENV=production`
   - `DEBUG=false`
   - `DRY_RUN_THREADS=false`
   - `ALLOW_DEV_TIER_OVERRIDE=false`

## 3) Database Migration (PostgreSQL)

```bash
alembic upgrade head
```

Validation:
- Confirm all `alembic/versions/*` revisions are applied
- Smoke-check API startup against PostgreSQL DSN

## 4) Frontend Build and API Base

```bash
cd web_dashboard
npm ci
npm run build
```

- Production base URL is `VITE_API_BASE_URL=/api` (`web_dashboard/.env.production.example`)
- Serve `web_dashboard/dist` behind Nginx

## 5) Runtime Deployment Options

### Option A: Docker Compose
- File: `deploy/docker-compose.production.yml`
- Services:
  - `api` (Gunicorn/Uvicorn worker)
  - `jobs` (scheduler)
  - `nginx` (TLS + reverse proxy + static)

### Option B: systemd
- Units:
  - `deploy/systemd/veltrixia-api.service`
  - `deploy/systemd/veltrixia-jobs.service`
- Both units set `Environment=PYTHONPATH=` to the app root (same as `WorkingDirectory`) so `import api.*` and `import jobs.*` resolve reliably.

Install example:

```bash
sudo cp deploy/systemd/veltrixia-api.service /etc/systemd/system/
sudo cp deploy/systemd/veltrixia-jobs.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now veltrixia-api veltrixia-jobs
```

### Option C: Render (osint-platform Web Service)

Python resolves the `api` package from **the process working directory** plus `PYTHONPATH`. On Render, set the **Start Command** so the repo root is on the module search path:

**Recommended Start Command (API service, e.g. `osint-platform`):**

```bash
alembic upgrade head && PYTHONPATH=. uvicorn api.main:app --host 0.0.0.0 --port $PORT
```

- `PYTHONPATH=.` makes the **project root** (Render’s root directory for the service) importable, so `from api.routes.free_feed import ...` in `api/main.py` works even if the runtime’s default path list is minimal.
- Ensure `Root Directory` (if set) is the repository root where the `api/` folder lives.

**Scheduler service (e.g. `osint-scheduler`):**

```bash
PYTHONPATH=. python jobs/main_scheduler.py
```

**Package markers:** the repo must include empty or minimal `api/__init__.py` and `api/routes/__init__.py` so `api` and `api.routes` are normal packages on all Python versions.

## 6) Nginx and Stripe Webhook Routing

- Nginx config template: `deploy/nginx/veltrixia.conf`
- Required:
  - Public HTTPS endpoint for `POST /api/payments/webhook`
  - Proxy pass to API upstream
  - Stripe webhook URL must match dashboard endpoint exactly

## 7) Go-Live Checklist

- [ ] `alembic upgrade head` succeeds on production DB
- [ ] `/api/system/health` returns healthy
- [ ] Stripe checkout redirects to live Stripe
- [ ] Stripe webhook updates `AnalystProfile.subscription_tier`
- [ ] Threads post succeeds with live credentials (no dry-run)
- [ ] Free user cannot bypass tier gating
- [ ] `ALLOW_DEV_TIER_OVERRIDE=false` in production env
