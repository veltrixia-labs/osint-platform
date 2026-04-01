# Implementation Plan: Local UI Consistency & Developer Tooling

This plan addresses the discrepancy between the documented "Premium UX" and the local rendering by introducing a "Developer Pulse" mode and a robust setup script.

## User Review Required

> [!IMPORTANT]
> To see the premium UI (Great Circle Arcs, Glassmorphism), you must run **`npm run build`** in the `web_dashboard` directory or use the **Vite Dev Server**. The FastAPI server serves the static `dist` folder, which may be stale.

## Proposed Changes

### 1. Developer Tooling & Automation
Created a specialized setup script to ensure the local database and user permissions are perfectly aligned with the Expert-tier requirements.

#### [NEW] [setup_dev_env.py](file:///c:/RDTP project/Development/OSINT_analytics/scripts/setup_dev_env.py)
* Automatically promotes `admin` and `testuser` to `enterprise` tier.
* Seeds the `stakeholders` table with valid geographic coordinates.
* Generates a "High Fidelity" alert with pre-populated `cascading_impacts` metadata for immediate visual verification.

### 2. Frontend Debug Mode
Added a "Developer Pulse" toggle in the frontend to bypass backend tier gating for local UI testing.

#### [MODIFY] [main.ts](file:///c:/RDTP project/Development/OSINT_analytics/web_dashboard/src/main.ts)
* Adds a global `window.__OSINT_DEBUG_MODE__` flag.
* When enabled, the frontend will treat all alerts as "Expert" tier for rendering purposes (ignoring `is_locked` flags where safe).

#### [MODIFY] [render.ts](file:///c:/RDTP project/Development/OSINT_analytics/web_dashboard/src/modules/render.ts)
* Adjusts coordinate parsing robustness to handle optional nesting.
* Ensures `map.invalidateSize()` is called more aggressively on tab switch to prevent Leaflet tiling issues.

### 3. Documentation & Paths
#### [MODIFY] [walkthrough.md](file:///C:/Users/Owner/.gemini/antigravity/brain/e7b001f4-4f1c-4e15-a40b-bec8635d8167/walkthrough.md)
* Updates image paths to be relative/static-server friendly.
* Includes a "Troubleshooting local UI" section with clear build and seeding instructions.

## Verification Plan

### Automated Verification
1. **Database Consistency**:
   ```powershell
   py scripts/setup_dev_env.py
   ```
   * Verify that the `analysts` table shows `enterprise` for the admin user.
   * Verify that `alert_logs` contains the newly seeded alert with JSON metadata.

2. **Frontend Build**:
   ```powershell
   cd web_dashboard
   npm run build
   ```
   * Verify that `dist/` is updated and contains the new CSS classes (`.propagation-arc-curved`).

### Manual Verification
1. Log in as `admin`.
2. Navigate to "Global Map".
3. Verify that the "NVIDIA" alert is present and displays the **curved arcs** and **pulse nodes**.
4. Open the browser console and set `window.__OSINT_DEBUG_MODE__ = true` to verify the bypass logic works.
