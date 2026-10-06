# Globe arcs across the antimeridian: before/after evidence (2026-10-06)

These screenshots are the evidence for commit **`032d46a`** ("globe: arcs stay continuous across the Pacific"). The diff shows `renderWorldCopies: true` and a longitude normalisation in `fitEgo`. It cannot show that the arcs were cut before and are continuous after. Only these images show that. Without them, the claim that the fix works is a sentence with nothing behind it.

## How they were taken

- **Browser and GPU:** Chrome 154, headless, driven by Playwright (`channel: 'chrome'`). WebGL renderer `ANGLE (Apple, ANGLE Metal Renderer: Apple M5)`, which is a real GPU, not SwiftShader. Viewport 1600×1000.
- **Environment:** a disposable clone with no `.env`. The local API (`uvicorn`, `ENV` unset) ran against a **local test Postgres** started by `scripts/test_db_local.sh`, never production. A harness page mounted `renderRelationshipView` with the dev Pro tier (`X-Dev-Tier: pro`, honoured only in non-production). Data: `data/scenarios/relationship_graph.json` and `node_coordinates.json` at `612e69e`.
- **Sequence:** "Globe" mode, then each node selected through the search box. Each screenshot was taken about 3.5 s after selection, which covers the 900 ms `fitEgo` camera move and the arc fade-in.
- **Code:** `before_*` is `612e69e` (`renderWorldCopies: false`, plain min/max bounds). `after_*` is the `032d46a` version of `relationship_globe.ts`.
- **Why screenshots:** they are the only valid evidence on this surface. Reading the WebGL canvas through `drawImage` without `preserveDrawingBuffer` returns an empty buffer, so "painted %" metrics mean nothing here.

## What each pair shows

| file | node | before | after |
|---|---|---|---|
| `*_00_default.png` | none (initial view) | grey parallelogram with black bands, one world | one world, no repetition, no bands |
| `*_01_NVIDIA.png` | NVIDIA (7 crossing arcs) | arcs to TSMC, Samsung and SK_hynix run off the **left edge** and are cut; frame centred on the Atlantic | the same arcs cross the Pacific continuously into Japan, Korea and Taiwan on the adjacent world copy; frame centred on the Pacific |
| `*_02_TSMC.png` | TSMC (17 of 18 crossing arcs drawn) | framed on the Atlantic with **TSMC itself off-screen**; arcs to the US enter cut from the left | TSMC centred; arcs to AMD, Apple, Broadcom and others go east across the Pacific unbroken; arcs to Europe go west |
| `*_03_ASML.png` | ASML (no crossing arcs) | correct | unchanged, which is the contrast case |
| `*_04_Canon.png` | Canon (no crossing arcs) | see the finding below | see the finding below |
| `after_05_Tokyo_Electron.png` | Tokyo_Electron (crossing arcs and zero-length arcs) | (no "before": the name search found nothing in that run; the "after" run searched by ticker 8035) | US arcs cross the Pacific; its zero-length arcs (both directions with Shin-Etsu_Chemical) show nothing beyond the marker |

## ★ Finding: "arcs arriving from off the right edge" near Canon were not a dateline break

The operator's screenshot showed arcs that seemed to arrive at Japan from beyond the right edge of the map, near Canon. Both the operator and the investigating session first read this as a **horizontal** overflow at ±180°. It was a **vertical** one.

None of Canon's arcs cross the antimeridian. Its arcs are Canon→Japan (short), ASML→Canon (from Eindhoven, to the west) and Canon→Nikon (zero length). The ArcLayer lifts every arc (`getHeight: 0.45`), and at `fitEgo`'s pitch of 65 a long arc such as ASML→Canon rises above the top of the frame. Its far half then comes back down into Japan from the **upper right**. `after_04_Canon.png` shows exactly that.

When an arc seems to enter from a screen edge, check the arc's height and the camera pitch before suspecting the dateline.

## Open item (recorded, not fixed): zero-length arcs

**13 drawn edges join two nodes with identical coordinates** (measured on `relationship_graph.json` and `node_coordinates.json` at `032d46a`):

| place | coordinate | zero-length edges |
|---|---|---|
| Tokyo | `35.6895, 139.6917` | Canon→Nikon, Shin-Etsu_Chemical→Tokyo_Electron, Tokyo_Electron→Shin-Etsu_Chemical, Shin-Etsu_Chemical→SUMCO |
| Tokyo | `35.69, 139.7` | Fujitsu→Mitsubishi_Electric, Fujitsu→NEC, Mitsubishi_Electric→NEC, Mitsui_OSK→NYK |
| Seoul | `37.566, 126.978` | LG_Energy_Solution→Hyundai, LG_Energy_Solution→SK_On, SK_On→Hyundai |
| Mumbai | `19.076, 72.878` | HDFC_Bank→State_Bank_of_India |
| Shenzhen | `22.543, 114.058` | Huawei→ZTE |

That is 8 in Tokyo and 5 elsewhere, not "13 Tokyo pairs" as first stated on 2026-10-06. The commit message of `032d46a` also says "Tokyo_Electron->Shin-Etsu/SUMCO/JSR". That is wrong: SUMCO and JSR share Tokyo_Electron's coordinate but **have no edge to it**. Tokyo_Electron's only zero-length edges are the two with Shin-Etsu_Chemical. The coordinates are city-level geocodes, which is why companies headquartered in the same city collapse to one point.

- For a zero-length arc the ArcLayer shader evaluates `atan(0, 0)` (`@deck.gl/layers` `arc-layer-vertex.glsl`), which GLSL leaves **undefined**.
- On this GPU (ANGLE Metal, Apple M5) **nothing visible** appeared for Canon→Nikon or the Tokyo_Electron↔Shin-Etsu_Chemical pair. The Seoul, Mumbai and Shenzhen pairs were not screenshotted.
- **Not tested on any other GPU or driver.**
- A fix would be to skip arcs whose endpoints coincide, as the comet code already does with `d === 0` in `relationship_arcs.ts`. That was deliberately not done on 2026-10-06.

## Related

- The 133 arcs spanning more than 180° of longitude (TSMC 18, Samsung 16, United_States 13, Micron 13), and why they were not routed the long way round: commit `032d46a`, and the comment above `renderWorldCopies` in `web_dashboard/src/modules/render/relationship_globe.ts`.
