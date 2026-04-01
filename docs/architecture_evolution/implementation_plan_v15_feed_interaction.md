# Feed Interaction & Visual Feedback Implementation Plan

We will resolve the issue where Feed cards are not recognizably clickable or associated with the map focus event.

## User Review Required

> [!IMPORTANT]
> The interaction will now be bound to the **entire alert card**. We will ensure that internal buttons (like "View Analysis") do not conflict with the card-level click by maintaining `e.stopPropagation()`.

---

## Proposed Changes

### 1. Visual Feedback (`style.css`)
*   **Pointer Cursor**: Add `cursor: pointer;` to `.alert-card`.
*   **Hover State**:
    *   Brighten the background `rgba(255, 255, 255, 0.05)`.
    *   Glow the border `border-color: var(--accent)`.
    *   Slightly lift the card `transform: translateY(-2px)`.

### 2. Interaction Binding (`render.ts`)
*   **Logging**: Add `console.log("[Antigravity] Alert Card Clicked: ID = " + alertId)` inside the card click listener.
*   **Event Refinement**: Ensure the `focus-map` event is dispatched correctly from the card click, while checking for `!alert-card--locked` status if necessary (though clicking locked cards to see the map info is often helpful, I will follow the user's lead).

---

## Verification Plan

### Manual Verification
1.  **Visual Check**: Hover over an alert card in the feed. It should glow and show the hand cursor.
2.  **Click Test**: Click any part of the card (except the buttons).
3.  **Console Check**: Verify that `[Antigravity] Alert Card Clicked: ID = ...` appears in the log, followed by the map transition logs.
