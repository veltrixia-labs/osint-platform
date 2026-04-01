# Implementation Plan: Phase 3 - Intelligence Mapping (Hybrid Approach)

Following the research of the `worldmonitor` repository and Gemini consultation, we will implement a cost-effective geo-spatial layer.

## User Review Required

> [!IMPORTANT]
> **Hybrid Geotagging**: To minimize LLM API costs, we will implement a "Heuristic First" approach using a static `location_map.json` (coordinates for countries/major cities) before falling back to LLM analysis for specific entities.
> [!TIP]
> **Map Engine**: We will start with **Leaflet.js** for high-performance 2D mapping, with a path to upgrade to **Deck.gl** for advanced 3D visual arcs if requested.

## Proposed Changes

### [Backend: Geotagging Engine]

#### [NEW] [location_resolver.py](file:///c:/RDTP%20project/Development/OSINT_analytics/processor/location_resolver.py)
- Implement `resolve_coordinates(text)`:
    1. Check `static_locations.json` for matches (Heuristics).
    2. Fallback to LLM extraction only for high-fidelity signals.

#### [MODIFY] [models.py](file:///c:/RDTP%20project/Development/OSINT_analytics/db/models.py)
- Add `lat` (Float) and `lng` (Float) to `AlertLog` and `Report`.

### [Frontend: Global Map Page]

#### [MODIFY] [main.ts](file:///c:/RDTP%20project/Development/OSINT_analytics/web_dashboard/src/main.ts)
- Replace "Active Correlation Map" placeholder with a link/tab to the **Global Map**.
- Add `nav-map` navigation logic.

#### [NEW] [map.ts](file:///c:/RDTP%20project/Development/OSINT_analytics/web_dashboard/src/modules/map.ts)
- Initialize map with **CartoDB Dark Matter** tiles.
- Render dynamic markers for alerts with `severity`-based colors.

## Verification Plan

### Automated Tests
- `pytest` for `location_resolver.py` to ensure static matches work without API calls.
- Functional test for DB schema update.

### Manual Verification
- Verify the "Global Map" tab appears and loads a dark-themed map.
- Confirm "Semiconductor" signals (if tagged with 'Taiwan/US') appear on the map.
