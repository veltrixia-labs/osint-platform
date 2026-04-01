# Implementation Plan: Full-Stack Dev Sync & Build Automation

This plan automates the synchronization between the OSINT backend and frontend, ensuring developers always work with up-to-date assets and high-fidelity test data.

## User Review Required

> [!IMPORTANT]
> The `setup_dev_env.py` script will now perform a **destructive clean** of the `web_dashboard/dist` folder and trigger a full rebuild. Ensure you have `node` and `npm` installed in your environment.

## Proposed Changes

### 1. Build-Sync Intelligence (Backend)
Ensures the API layer is aware of the frontend's freshness.

#### [MODIFY] [main.py](file:///c:/RDTP project/Development/OSINT_analytics/api/main.py)
* **Freshness Check**: On startup, compare the modification time of `web_dashboard/src` and `web_dashboard/dist`. Log a standard warning if `dist` is stale.
* **Cache Suppression**: Add a middleware (active in `DEBUG` mode) that injects `Cache-Control: no-store, no-cache, must-revalidate` into all responses to prevent browser-side asset stale-dating.

### 2. Full-Stack Setup Script
Upgrades the existing seeding utility into a comprehensive environment initializer.

#### [MODIFY] [setup_dev_env.py](file:///c:/RDTP project/Development/OSINT_analytics/scripts/setup_dev_env.py)
* **Clean Build**: Uses `shutil.rmtree` to purge `web_dashboard/dist`.
* **Subprocess Execution**: Automatically runs `npm install` and `npm run build`.
* **Database Alignment**:
    * Promotes `admin` and `testuser` to `enterprise` tier.
    * Seeds stakeholders with coordinates for the Global Map.
    * Generates a "Master Verification Alert" with full cascading impacts.

### 3. UI Translucency (Build Info)
Provides immediate visual feedback on the currently deployed version.

#### [MODIFY] [vite.config.ts](file:///c:/RDTP project/Development/OSINT_analytics/web_dashboard/vite.config.ts)
* Uses `define` to inject `__APP_BUILD_INFO__` (timestamp) into the bundle.

#### [MODIFY] [main.ts](file:///c:/RDTP project/Development/OSINT_analytics/web_dashboard/src/main.ts)
* Adds a small `div.build-info-tag` at the bottom of the sidebar.
* Displays: `Build: 2026.03.31.2045 | Expert Mode: ON`.

## Verification Plan

### Automated Verification
1. **Full-Stack Setup**:
   ```powershell
   py scripts/setup_dev_env.py
   ```
   * Verify `web_dashboard/dist` is recreated.
   * Verify console output shows "Build Success".
   
2. **Freshness Warning**:
   * Modify a file in `src` (without building).
   * Restart `api/main.py`.
   * Verify the warning: `[WARNING] Frontend assets are STALE. Run npm run build.`

### Manual Verification
1. Open the dashboard.
2. Check the bottom-left of the sidebar for the **Build Info Tag**.
3. Verify that the "NVIDIA" alert on the map shows **curved arcs** immediately after running the setup script.
4. Verify browser dev-tools show `Cache-Control: no-store` for API calls.
