// Reusable visual-capture for the Pro Interactive Map (Stage 1 + Stage 2 cascade).
// Run from web_dashboard/ so `playwright` resolves:  node scripts/shoot_map.mjs
//
// Requires:
//   - the dev frontend on :5173  (npm run dev)
//   - the API on :8000 in NON-prod  (ENV unset)  — see repo notes
//   - VEL_TOKEN = a VALID session access_token (any tier). The backend requires a
//     live DB session, so this must come from a real login (e.g. copy
//     localStorage['access_token'] from a logged-in browser).
//
// Auth mechanism (replicates the dev console's "LOCAL DEV TIER" toggle):
//   - localStorage.access_token  -> boots the app; /auth/me validates the session.
//   - sessionStorage.vel_dev_tier_override='pro'  -> the api client sends the
//     `X-Dev-Tier: pro` header, so (a) the backend serves Pro data and (b) /auth/me
//     returns EFFECTIVE tier 'pro', which passes the frontend's pro-map gate.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

const TOKEN = process.env.VEL_TOKEN || '';
const BASE = process.env.VEL_BASE || 'http://localhost:5173';
const OUT = process.env.VEL_OUT || path.resolve('.map-shots');
const SCENARIO = process.env.VEL_SCENARIO || 'strait_of_hormuz';
mkdirSync(OUT, { recursive: true });

if (!TOKEN) console.warn('[shoot_map] VEL_TOKEN is empty — the app will show the login page and Stage 1 will time out.');

const browser = await chromium.launch({
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'],
});
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();

await page.addInitScript(([token]) => {
    try { localStorage.setItem('access_token', token); } catch {}
    try { sessionStorage.setItem('vel_dev_tier_override', 'pro'); } catch {}
}, [TOKEN]);

page.on('console', (m) => { if (m.type() === 'error') console.log('[page console error]', m.text()); });
page.on('response', (r) => { if (r.url().includes('/api/pro/') && !r.ok()) console.log('[api]', r.status(), r.url()); });

console.log('[shoot_map] →', `${BASE}/#pro-map`);
await page.goto(`${BASE}/#pro-map`, { waitUntil: 'networkidle' });

// ── Stage 1 — trigger reticles ──────────────────────────────────────────────
await page.waitForSelector('.tm2-marker', { timeout: 30000 });
await page.waitForTimeout(1500);                       // basemap tiles + markers settle
await page.screenshot({ path: path.join(OUT, 'stage1.png') });
console.log('[shoot_map] stage1.png');

// ── Stage 2 — the cascade for SCENARIO ──────────────────────────────────────
const viewBtn = page.locator(`button.tm2-view[data-scenario="${SCENARIO}"]`);
if (await viewBtn.count()) await viewBtn.first().click();
else await page.locator('.tm2-marker').first().click();

await page.waitForSelector('.sc-map-canvas canvas', { timeout: 30000 }).catch(() => {});
// No stable deck.gl "settled" event exists; the loading overlay removal is the best
// signal, then a fixed settle for the animation to reach steady state.
await page.waitForFunction(() => !document.querySelector('[id^="sc-loading-"]'), { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(4000);
await page.screenshot({ path: path.join(OUT, 'stage2-full.png') });
console.log('[shoot_map] stage2-full.png');

// Heuristic crops of the map stage (exact node pixels aren't known ahead of time).
const box = await page.locator('.tm2-stage').boundingBox();
if (box) {
    await page.screenshot({
        path: path.join(OUT, 'stage2-epicenter.png'),
        clip: { x: box.x + box.width * 0.28, y: box.y + box.height * 0.28, width: box.width * 0.38, height: box.height * 0.42 },
    });
    await page.screenshot({
        path: path.join(OUT, 'stage2-tokyo.png'),
        clip: { x: box.x + box.width * 0.60, y: box.y + box.height * 0.18, width: box.width * 0.36, height: box.height * 0.46 },
    });
    console.log('[shoot_map] stage2-epicenter.png, stage2-tokyo.png');
}

console.log('[shoot_map] done →', OUT);
await browser.close();
