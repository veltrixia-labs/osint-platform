# OSINT Command Center - Risk Intelligence Platform

A high-fidelity spatial intelligence platform for monitoring global geopolitical, market, and supply chain risks.

## Geospatial Intelligence Specification

### Hierarchical Coordinate Fallback (v16_recovery)
To ensure reliable plotting of alerts even with inconsistent data structures, the rendering engine implements a hierarchical search for coordinates:

1.  **Top-level Alert Data**: Checks for `location_lat` and `location_lng` at the primary alert object level.
2.  **Metadata Injection**: Checks inside `alert.metadata_json` for explicit coordinate overrides.
3.  **Recursive Stakeholder Search**: If top-level coordinates are missing, the engine searches within the `cascading_impacts` array for representative stakeholder locations (e.g., NVIDIA HQ) to provide an anchor point for the event.

### Relational Intelligence Graph
The platform visualizes 3rd-order cascading impacts using:
- **Cubic Bezier Curves**: Dynamic arcs representing the flow of impact between entities.
- **Refined Labels**: Multi-line markers with topic categorization and trend indicators (Alpha Prediction).
- **Auto-Dodge Logic**: Dynamic vertical offsets for high-order nodes (Level 2/3) to prevent label overlap in dense geographical clusters (e.g., US West Coast).

## Monetization & Feature Gating
- **Free/Pro**: Provides primary impact analysis and basic arcs.
- **Expert**: Unlocks 2nd and 3rd-order recursive impact chains, high-fidelity trend indicators, and "Expert Analysis" reports.