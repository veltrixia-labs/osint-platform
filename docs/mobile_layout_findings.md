# Mobile layout findings — repo-wide, 2026-10-05

**Status: measured, not fixed. No CSS or source file was edited for this note.**

Two findings that surfaced while measuring the relationship view on a phone
(`docs/mobile_relationship_view_measurement.md`) but are **not specific to the
`feat/relationship-map` branch**, so they are recorded separately rather than buried inside a
note about it.

> **Where this is filed, and why.** GitHub issues are enabled on this repo but **have never been
> used** — `gh issue list --state all` returns nothing. Filing here would have invented a
> convention rather than followed one. The repo's demonstrated convention for findings of this
> kind is `docs/<lowercase_snake_case>.md`, so that is what this is.

Measured on real Chrome 154 via Playwright at 393 × 852 (dSF 3, `isMobile`, `hasTouch`) and at
1800 × 852, as Pro.

---

## 1. `height: auto` on mobile, and which views it can starve

`src/mobile-responsive.css` under `@media (max-width: 768px)` sets
`#pro-map-container { min-height: 50vh; height: auto; }`. A child that sizes itself with a
`height: 100%` / `flex: 1 1 auto; min-height: 0` chain has nothing to divide against an
`auto` parent and collapses to content height.

**Measured — every page container, at both widths.** Containers normally carry
`display: none`; each was forced to `display: flex` to measure what it would resolve to if shown.

| container | 393 px used / min-height | 1800 px used / min-height | sizing | affected? |
|---|---|---|---|---|
| `#pro-map-container` | **426 / 426 (50vh), `height: auto`** | 640 / 640 | **auto** | **YES — the relationship view** |
| `#map-page-container` | **732 / 553.8 (65vh)** | 2 / auto | **definite** `calc(100dvh - 7.5rem - env(safe-area-inset-bottom))` | no |
| `#alerts-container` | 716 / auto | 774 / auto | content | no — a feed list, no height chain |
| `#impact-roster-container` | 0 / auto | 0 / auto | content | no — a table, no height chain |

**On this branch, only the relationship view is affected.** `#pro-map-container` is the single
container given `height: auto` whose child requires a definite height. `grep` confirms only
`src/modules/render/pro_map.ts:18` mounts into it on this branch.

★ **`#map-page-container` is the counter-example, and it matters.** The free Global Map page was
given exactly the treatment `#pro-map-container` was not — a definite
`height: calc(100dvh - 7.5rem - env(safe-area-inset-bottom, 0px))`, a `min-height: 65vh` floor,
**and** `.map-instance-host { flex: 1 1 auto; min-height: 65vh; height: 100% }`. Somebody solved
this problem once, for one container, and the fix was never generalised.

★ **On `main`, `#pro-map-container` hosts the legacy map, and that module defends itself in
JS.** `pro_map.ts` on `main` mounts `renderTriggerMap`, which delegates to the cascade renderer;
`pro_interactive_map.ts` stamps `minHeight: '520px'` inline at `:581`, and at `:612` has a
fallback that logs *"map container still has weak dimensions after waiting; forcing fallback
height"* before setting `height`/`minHeight` to `600px`. **That warning string is evidence the
same `height: auto` problem was already hit there and worked around in JS rather than in CSS.**
The relationship view has no equivalent defence, which is why it collapses instead of warning.

**No fix is proposed here.** The measurement is the deliverable.

---

## 2. The sidebar nav tap does not land below 768 px

At 393 px the sidebar is off-canvas: `#sidebar-nav-container` measures at **x = −376**, 246 × 786,
with `display: flex; visibility: visible; opacity: 1` — i.e. laid out and hit-testable in
principle, but positioned entirely outside the viewport. `#nav-pro-map` sits inside it at
**x = −376**, 246 × 44.

A `#mobile-menu-btn` exists and is the intended opener. Clicking `#nav-pro-map` directly is a
no-op at this width, so during measurement the view was reachable **only by hash route**
(`location.hash = '#pro-map'`).

This affects every tab in the sidebar, not just the Pro Interactive Map, and is independent of
the relationship-map branch. Not investigated further — whether the menu button opens the drawer
correctly on a real device was not tested.
