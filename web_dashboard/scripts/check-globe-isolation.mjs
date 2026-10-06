#!/usr/bin/env node
/**
 * Enforces the isolation contract at the top of relationship_globe.ts.
 *
 * The globe may carry coordinates and nothing else from the chokepoint-scenario side, because a
 * globe is precisely where a coordinate turns a derived number into a published one.
 *
 * (Comment corrected 2026-10-06.) This comment used to justify the check with order-3 as a live
 * mechanism and cited export_scenarios.py:456-475. That is stale: order-3 (a firm impact derived
 * as country x DECAY 0.7 with NO edge predicate) was removed from the vault's payloads on
 * 2026-10-05 (vault f2795b0), and the line range no longer holds it. The check is still correct
 * and still needed. The scenario surface still carries derived, hub-relative numbers
 * (impact_score, raw_impact, credit_gaps, ...) that must not reach the globe, and this script is
 * what stops any of them, or a re-introduced order-3, from being joined to it. See the vault's
 * CLAUDE.md §5.
 */
import { readFileSync } from 'fs';
const FILE = 'src/modules/render/relationship_globe.ts';
const src = readFileSync(FILE, 'utf8');

const BANNED_IMPORTS = ['pro_interactive_map', 'pro_trigger_map', 'pro_map', 'spatial', 'impact_roster', 'contagion', 'scenarios/'];
const BANNED_FIELDS = ['impact_score', 'raw_impact', 'viscosity_coefficient', 'entropy_index', 'is_epicenter', 'order_level', 'no_map', 'credit_gaps', 'honest_gaps'];
const ALLOWED = ['maplibre-gl', 'maplibre-gl/dist/maplibre-gl.css', './relationship_graph_canvas',
                 // Pure math (great-circle slerp + easing). Imports NOTHING itself, which is what
                 // keeps it allowlistable: it cannot become a back door to the scenario apparatus.
                 './relationship_arcs',
                 // deck.gl is a LIBRARY. The same three packages the legacy map loads
                 // (pro_interactive_map.ts:970-972, :987), carrying none of its code. Allowing the
                 // renderer is not allowing the model: the legacy MODULES stay in BANNED_IMPORTS
                 // and the banned-field scan below is what actually enforces the boundary.
                 '@deck.gl/core', '@deck.gl/layers', '@deck.gl/mapbox'];

// ★ THREE forms, and the third one matters. `import X from 'y'`, bare `import 'y'`, AND
//   dynamic `import('y')`. Without the dynamic form the allowlist is decorative: the legacy map
//   itself reaches deck.gl through `await import('@deck.gl/layers')` (:970-972), so anyone
//   copying that idiom here would sail straight past a static-only check. The `m` flag plus ^ on
//   the first two is deliberate — a top-level static import only — while the dynamic form is
//   matched anywhere, because that is where it is legal to appear.
const extractImports = (text) => [
  ...[...text.matchAll(/^import[^;]*?from\s+'([^']+)'/gm)].map((m) => m[1]),
  ...[...text.matchAll(/^import\s+'([^']+)'/gm)].map((m) => m[1]),
  ...[...text.matchAll(/\bimport\s*\(\s*'([^']+)'\s*\)/g)].map((m) => m[1]),
];
const imports = extractImports(src);
const fail = [];
for (const i of imports) if (!ALLOWED.includes(i)) fail.push(`disallowed import: ${i}`);
for (const b of BANNED_IMPORTS) if (imports.some((i) => i.includes(b))) fail.push(`banned import substring: ${b}`);
const body = src.replace(/\/\*\*[\s\S]*?\*\//, '');   // skip the contract block, which names them on purpose
for (const f of BANNED_FIELDS) if (body.includes(f)) fail.push(`banned field reference: ${f}`);

// ★ The allowlist entry for ./relationship_arcs is only safe while that file imports nothing.
//   Allowlisting a module without checking ITS imports just moves the back door one file along:
//   relationship_arcs.ts could import pro_interactive_map tomorrow and this check would pass.
const ARCS = 'src/modules/render/relationship_arcs.ts';
const arcSrc = readFileSync(ARCS, 'utf8');
const arcImports = extractImports(arcSrc);
if (arcImports.length) fail.push(`relationship_arcs.ts must import nothing, found: ${arcImports.join(', ')}`);
for (const f of BANNED_FIELDS) {
  if (arcSrc.replace(/\/\*\*[\s\S]*?\*\//, '').includes(f)) fail.push(`banned field in relationship_arcs.ts: ${f}`);
}

if (fail.length) {
  console.error('globe isolation FAILED:');
  for (const f of fail) console.error('  -', f);
  process.exit(1);
}
console.log(`globe isolation OK — imports: ${imports.join(', ')} · relationship_arcs.ts imports: none`);
