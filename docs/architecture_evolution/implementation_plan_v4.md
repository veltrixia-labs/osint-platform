# Implementation Plan: Phase 3 - Intelligence Mapping

This phase introduces a geo-spatial visualization layer to the OSINT platform, allowing analysts to track risk events on an interactive map as requested.

## User Review Required

> [!IMPORTANT]
> **Data Enrichment**: Existing alerts do not have coordinates. We will implement an LLM-based geotagging process to retrospective-tag high-priority alerts.
> [!NOTE]
> **Library Choice**: We will use Leaflet.js for its performance and ease of integration with vanilla JS.

## Proposed Changes

### [Backend: Geo-Spatial Data]

#### [MODIFY] [models.py](file:///c:/RDTP%20project/Development/OSINT_analytics/db/models.py)
- Add `lat` (Float) and `lng` (Float) columns to `AlertLog` and `Report`.

#### [MODIFY] [alert_manager.py](file:///c:/RDTP%20project/Development/OSINT_analytics/jobs/alert_manager.py)
- Update the signal processing logic to extract location data using the LLM from the signal description.

### [Frontend: Map Interface]

#### [NEW] [map.ts](file:///c:/RDTP%20project/Development/OSINT_analytics/web_dashboard/src/modules/map.ts)
- Initialize Leaflet map with a dark theme (Protonmaps or CartoDB Dark Matter).
- Implement marker clustering for high-density alert areas.
- Create a "Map Layers" toggle (Conflict Zones, Infrastructure, Signal Density).

#### [MODIFY] [main.ts](file:///c:/RDTP%20project/Development/OSINT_analytics/web_dashboard/src/main.ts)
- Add a "Global Map" tab to the main navigation.
- Integrate the `renderMap` function.

## Verification Plan

### Automated Tests
- Test coordinate extraction logic with sample news strings.
- Verify API returns `lat`/`lng` for the new map endpoint.

### Manual Verification
- Verify the map loads and displays markers for "AI Semiconductor" and "Black Sea" signals.
- Test the 2D/3D toggle (simulated via tilt/zoom).
