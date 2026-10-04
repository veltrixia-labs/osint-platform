#!/usr/bin/env node
/**
 * Enforces the isolation contract at the top of relationship_globe.ts.
 *
 * The globe may carry coordinates and nothing else from the chokepoint-scenario side. order-3
 * (export_scenarios.py:456-475) assigns a firm impact = country x DECAY(0.7) with NO edge
 * predicate, and the coordinate gate is the only thing keeping such a node off a map — a globe
 * is precisely where a coordinate turns a derived number into a published one. See the vault's
 * CLAUDE.md §5.
 */
import { readFileSync } from 'fs';
const FILE = 'src/modules/render/relationship_globe.ts';
const src = readFileSync(FILE, 'utf8');

const BANNED_IMPORTS = ['pro_interactive_map', 'pro_trigger_map', 'pro_map', 'spatial', 'impact_roster', 'contagion', 'scenarios/'];
const BANNED_FIELDS = ['impact_score', 'raw_impact', 'viscosity_coefficient', 'entropy_index', 'is_epicenter', 'order_level', 'no_map', 'credit_gaps', 'honest_gaps'];
const ALLOWED = ['maplibre-gl', 'maplibre-gl/dist/maplibre-gl.css', './relationship_graph_canvas',
                 // Pure arc geometry + easing. Imports NOTHING itself, which is what keeps it
                 // allowlistable: it cannot become a back door to the scenario apparatus.
                 './relationship_arcs'];

// Both forms: `import X from 'y'` AND bare side-effect `import 'y'` (the CSS import).
const imports = [
  ...[...src.matchAll(/^import[^;]*?from\s+'([^']+)'/gm)].map((m) => m[1]),
  ...[...src.matchAll(/^import\s+'([^']+)'/gm)].map((m) => m[1]),
];
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
const arcImports = [
  ...[...arcSrc.matchAll(/^import[^;]*?from\s+'([^']+)'/gm)].map((m) => m[1]),
  ...[...arcSrc.matchAll(/^import\s+'([^']+)'/gm)].map((m) => m[1]),
];
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
