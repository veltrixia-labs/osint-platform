# Map Intelligence Visualization & Interaction Implementation Plan

We will enhance the Global Map to serve as a high-fidelity spatial intelligence layer. This involves dynamic marker styling, responsive transitions, and foundational logic for regional risk visualization.

## User Review Required

> [!IMPORTANT]
> The map markers will now dynamically scale based on "Signal Intensity". High-risk areas will feature larger, deeper red pulsing rings. 
> 
> *   Do you have specific Gaussian/Heatmap preferences, or is the "Pulsing Ring" approach sufficient for the initial risk intensity visualization?
> *   The "Related Domains" (Evidence) will be mapped similarly to cascading impacts if coordinate data is available.

---

## Proposed Changes

### 1. Dynamic Spatial Markers (`render.ts` & `style.css`)
We will move away from a static icon to a multi-layered pulsing ring system.

#### [MODIFY] `web_dashboard/src/style.css`
*   **Redesign `.map-marker-pulse`**: 
    *   Transition from a simple blue dot to a red ring (`#f43f5e`).
    *   Add an inner "core" dot for sharper visual focus.
    *   Optimize the `@keyframes pulse-ring` for a more "ominous" rhythm.

#### [MODIFY] `web_dashboard/src/modules/render.ts`
*   **Dynamic Icon Generation**: Move the `L.divIcon` creation inside the `alerts.forEach` loop.
*   **Intensity Mapping**: 
    *   Scale the `iconSize` and pulse spread based on `alert.intensity` (e.g., scale factor of 1.0 to 2.5).
    *   Adjust CSS `filter: saturate()` or `opacity` dynamically via inline styles in the `html` string of the icon.
*   **Logging**:
    *   `[Antigravity] Mapping Alert: {Title} at {Lat, Lng}`
    *   `[Antigravity] Starting Transition to {Lat, Lng}`

### 2. Interaction Sequence & Transition (`render.ts`)
#### [MODIFY] `web_dashboard/src/modules/render.ts`
*   **Refined `flyTo`**: Ensure the camera sequence is prioritized.
*   **Delayed Arc Trigger**: Start the high-resolution arc and particle animation *after* or *during* the flyTo move for maximum impact.

### 3. Regional Glow Foundation (`render.ts`)
*   **New Function `renderRegionalContext`**: 
    *   A foundational function that can eventually load GeoJSON.
    *   Initial implementation: Large, very low-opacity circles (`L.circle`) around clusters of high-intensity alerts to simulate a "hot zone" glow.

---

## Verification Plan

### Automated/Console Verification
*   Verify presence of `[Antigravity]` logs in the browser console during navigation.
*   Check for CSS variable overrides in the DOM for marker sizing.

### Manual Verification
*   **Spatial Check**: Zoom into different alerts. Verify that a "9.5 Intensity" alert has a significantly larger and more vibrant pulse than a "2.0 Intensity" alert.
*   **Transition Check**: Click an alert in the Feed. The map should "dive" to the location, and the red ring should be the center of the arc propagation.
