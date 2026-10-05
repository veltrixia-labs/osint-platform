# Relationship view on a phone — measurement, 2026-10-05

**Status: measured, not fixed. No code, CSS or view changes were made for this note.**

Branch `feat/relationship-map` at `ccbe5d7`. Measured on real Chrome 154 driven by Playwright
(`channel: 'chrome'`) at **393×852, deviceScaleFactor 3, `isMobile: true`, `hasTouch: true`**,
as Pro (`sessionStorage.vel_dev_tier_override`) and as Free.

> **Filename note.** This was requested at `docs/_MOBILE_RELATIONSHIP_VIEW_2026-10-05.md`. The
> repo's convention for notes of this kind is `docs/<lowercase_snake_case>.md` with no leading
> underscore and no date in the filename — `clustering_quality_proposal.md`,
> `free_tier_specification.md`, `pro_report_schema.md` — so the date lives in the heading
> instead and the path follows the convention.

## Verdict

**The view is not viable at this size.** Not "cramped": in Globe mode the map has zero height,
and in Graph mode selecting a node puts the view into a state the user cannot exit.

## Measured

### Box chain

```
#pro-map-container  426
  .rv-root          393
    .rv-body        149
      .rv-canvas-host 149
        canvas      293 × 147
```

### Globe

`.rv-globe canvas` measures **293 × 0** CSS px — backing store 879 × 900, i.e. MapLibre is
rendering into nothing. It becomes visible only in fullscreen, where it gets **534 px**.

### The bottom sheet, with a node selected

- `sheetCoversHostPx: 149` of `hostH: 149`; **`canvasVisibleHeight: 0`**.
- The sheet's layout box is **383 px** tall (`max-height: 45vh` of 852) but `.rv-body` is 149 px
  and clips it, so **234 px is clipped away — including the sheet's own collapse tab at its top
  edge, and the `×`.**
- `elementFromPoint` returns **`.page-title`** for the collapse tab and **`.header-row`** for the
  `×`. Neither is reachable.
- Every canvas probe point — centre, top, left, bottom — returns **`.pm-co-nb-w` /
  `.pm-co-nb-rel`**, i.e. a drawer row. Drag and pan never reach the canvas.

### Node tap targets

Live zoom `k = 0.071`; radius is `3 + log1p(deg) × 1.9` in graph space.

| | degree | graph r | on-screen CSS px | hit radius `(r+4)·k` |
|---|---|---|---|---|
| smallest | 0 | 3.00 | **0.21** | 0.50 |
| median | 7 | 6.95 | **0.49** | 0.78 |
| largest | 132 | 12.29 | **0.87** | 1.16 |

Against the **44 px** Apple HIG minimum touch target, the largest node in the graph is about
1/50th of the minimum.

### Other

- Backing store is capped at `Math.min(devicePixelRatio, 2) = 2` on a dSF 3 screen — 586 × 294
  backing for a 293 × 147 box. Softness only, not a functional break.
- **Zero pageerrors in every state tested**, both tiers: Graph, Globe, sheet open, fullscreen
  enter and exit.
- No horizontal overflow at any point: `scrollWidth 393 = clientWidth 393`, `body.scrollWidth 393`.
- With the sheet open, the search box, GRAPH/GLOBE toggle, EXPAND button and legend all remain
  reachable. Only the collapse tab and the `×` are not.
- Free tier never reaches the view: `#pro-map-container` shows the premium shroud
  ("🔒 PRO FEATURE"), `.rv-root` is absent, host height 0.

## Root cause

`src/mobile-responsive.css`, under `@media (max-width: 768px)`:

```css
#pro-map-container { min-height: 50vh; height: auto; padding: 8px; }
```

This beats the base rule in `src/style.css`:

```css
#pro-map-container { height: calc(100vh - 80px); min-height: 640px; }
```

426 px is 50vh of 852. The relationship view's layout assumes a **definite** container height —
`.rv-root { height: 100% }`, then `.rv-body` and `.rv-canvas-host` as `flex: 1 1 auto;
min-height: 0`. Against `height: auto` that chain has nothing to divide, so it resolves to
near-minimum content height, which is the 149 px body and the 0 px globe above.

**This rule predates this branch.** It is not a regression introduced by the relationship-map
work.

## What a definite height would and would not fix

A definite height would fix **1 (globe zero height)**, **2 (sheet covering the whole canvas)**
and **5 (the graph rendered as a smudge)**.

It would **not** fix **3, the sub-pixel nodes.** That is a consequence of fitting 303 nodes into
293 px of width; at any plausible phone height the fitted zoom stays near `k = 0.071` and the
median node stays well under 1 px. **That needs a different UI at this breakpoint, not more
height.**

## Measurement caveat

This was taken on **emulated mobile Chrome, which is not a substitute for real iOS Safari.** It
is desktop Chrome with a resized viewport and a spoofed user agent: the Fullscreen API is fully
present there and absent on iOS for non-`<video>` elements. The native fullscreen path was
exercised here (`document.fullscreenElement === .rv-root`, root 393 × 852, globe canvas 534 px);
**the `.rv-pseudo-fs` CSS fallback remains unverified on a real device.**

## Decisions taken — do not re-investigate

- **Nobody is affected today.** The branch is **not merged and not deployed**, and the view is
  Pro-gated; Free never reaches it.
- **A mobile-specific layout is DEFERRED by the operator until the desktop view is otherwise
  complete.** This is a deliberate sequencing choice, not an oversight or an unknown.
- **The open question at merge time** is whether to gate this view below 768 px rather than ship
  a view that renders but cannot be used.

## Out of scope for this note

Two findings surfaced here belong outside a note about this branch and are recorded in
`docs/mobile_layout_findings.md`: the `height: auto` starvation risk for other views, and the
sidebar nav tap not landing below 768 px.
