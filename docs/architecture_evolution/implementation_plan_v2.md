# Implementation Plan: Phase 2 - Intelligence Segmentation & Conversion

## Goal Description
Transform the dashboard into a strategic conversion engine by segmenting intelligence into three layers (Live, Regional, Expert) and implementing high-impact visual triggers for the Expert plan ($49/month).

## Proposed Changes

### [Frontend] Dashboard Re-architecture
#### [MODIFY] [index.html](file:///c:/RDTP project/Development/OSINT_analytics/web_dashboard/index.html)
- Replace static "Global Briefing" buttons with a dynamic `Live Intelligence Feed` section.
- Add containers for `Regional Analysis` and `Current Risk Profile` sidebar.

#### [MODIFY] [render.ts](file:///c:/RDTP project/Development/OSINT_analytics/web_dashboard/src/modules/render.ts)
- Implement `renderLiveFeed()`: Use pulsing indicators and high-speed scrolling for real-time alerts.
- Implement `renderRiskProfile()`: A sidebar widget showing aggregate risk scores across sectors.
- Update `renderReportDetail()`:
    - For Free users: Show full thematic reports.
    - For Expert reports: 
        - **Ghost Nodes**: Generate a Nexus Graph preview where key nodes are replaced by "?" or locked icons.
        - **Unlock Comparison**: Overlay comparing "Global View" vs "Expert Deep-Dive" reach.
        - Show only the first sentence of BLUF, followed by a blurred `PremiumPaywall`.

#### [MODIFY] [style.css](file:///c:/RDTP project/Development/OSINT_analytics/web_dashboard/src/style.css)
- **Intelligence Pulse**: CSS animations for "active data scanning" effect on the Live Feed.
- **Ghost Nodes Styling**: Specialized styles for Nexus Graph previews (blurred/locked nodes).
- **Sidebar Sparklines**: Compact trend visualizations for the Risk Profile sidebar.
- Styling for the enhanced `PremiumPaywall` with "Unlock Comparison" UI.

### [Backend] Data Gating & Previews
#### [MODIFY] [api/main.py](file:///c:/RDTP project/Development/OSINT_analytics/api/main.py)
- Refine gating logic to support the three layers.
- Add an endpoint for `Live Intelligence Feed` (direct stream of High-Fidelity signals).
- **Tighter Coupling**: Add metadata to Feed items linking directly to protected Expert Reports via "lock" symbols.

#### [MODIFY] [jobs/report_generator.py](file:///c:/RDTP project/Development/OSINT_analytics/jobs/report_generator.py)
- Update LLM prompts to explicitly generate "Preview Snippets" and "Correlation Map Metadata" for Expert reports.

## Verification Plan
### Automated Tests
- Browser tests to verify that `Live Feed` updates in real-time.
- API tests to ensure Level 3 content is properly masked for Free users.

### Manual Verification
- Visual audit of the new dashboard hierarchy and sidebar.
- Functional test of the "Unlock" conversion triggers.
