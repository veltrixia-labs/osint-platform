# OSINT Analytics API Contract

This document outlines the endpoint structure and authentication requirements for the OSINT Platform backend.

## 1. Endpoint Prefixing
All functional API routes are prefixed with `/api` to allow the Nginx proxy to distinguish between static frontend assets and dynamic backend calls.

- **Frontend Access**: `${VITE_API_BASE_URL}/<path>` (where base URL is usually `/api`)
- **Backend Definition**: `@app.get("/api/<path>")` or `app.include_router(..., prefix="/api")`

## 2. Health & Monitoring
The system provides several health check endpoints to cater to different infrastructure providers (Render, GCP, Docker).

| Endpoint | Auth | Purpose |
| :--- | :--- | :--- |
| `/healthz` | None | Legacy/Platform root health check. |
| `/api/health` | None | Public status of API + DB connectivity. |
| `/api/system/health` | Optional | Tiered health metrics for the analyst dashboard. |
| `/api/status` | None | Basic uptime and version tag check. |

## 3. Core Analyst Contract
The analyst profile data is standardized to match session management fields.

| Model Field | API Field | Purpose |
| :--- | :--- | :--- |
| `id` | `id` | UUID string. |
| `email` | `email` | Canonical analyst email. |
| `telegram_chat_id` | `chat_id` | **Unified field** for session mapping. |
| `watch_keywords` | `watch_keywords` | Monitoring list. |

## 4. Authentication
All protected routes require an `Authorization: Bearer <token>` header.
The `access_token` has a short TTL, while the `refresh_token` is handled via HttpOnly cookies at `/api/auth/refresh`.
