# Implementation Plan: Phase 2.1 - UX Refinement & Watchlist Fix

This phase addresses user feedback regarding unintuitive UI elements (feedback ratings) and a functional gap in the Watchlist (Key Entities) update logic.

## Proposed Changes

### [Dashboard UI]

#### [MODIFY] [render.ts](file:///c:/RDTP%20project/Development/OSINT_analytics/web_dashboard/src/modules/render.ts)
- **Remove Feedback Ratings**: Delete the `1-5` button group from `renderAlerts`. Replace with a simple, non-interactive "Intelligence Verified" or "Broadcast Alert" label to declutter the card.
- **Watchlist UI Enhancement**: 
    - Update `renderSidebar` to include "Active Watchlist" as a clear list of chips.
    - Ensure the "Add" button providing immediate visual feedback.

#### [MODIFY] [main.ts](file:///c:/RDTP%20project/Development/OSINT_analytics/web_dashboard/src/main.ts)
- **State Synchronization**: Fix `refreshWatchlist` to update the local `user` object's keywords after a successful API call.
- **Optimistic UI**: Implement immediate tag rendering upon clicking "Add" to provide instant confirmation.

## Verification Plan

### Manual Verification
1. **Watchlist Test**: Add "Semiconductor" to Key Entities.
   - Verify: A blue tag with "Semiconductor" appears immediately.
   - Verify: The tag persists after switching tabs.
2. **Alert Card Test**: 
   - Verify: The "1 2 3 4 5" buttons are no longer visible.
   - Verify: The card layout remains balanced and professional.
