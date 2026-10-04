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
const ALLOWED = ['maplibre-gl', './relationship_graph_canvas'];

const imports = [...src.matchAll(/^import[^;]*?from\s+'([^']+)'/gm)].map((m) => m[1]);
const fail = [];
for (const i of imports) if (!ALLOWED.includes(i)) fail.push(`disallowed import: ${i}`);
for (const b of BANNED_IMPORTS) if (imports.some((i) => i.includes(b))) fail.push(`banned import substring: ${b}`);
const body = src.replace(/\/\*\*[\s\S]*?\*\//, '');   // skip the contract block, which names them on purpose
for (const f of BANNED_FIELDS) if (body.includes(f)) fail.push(`banned field reference: ${f}`);

if (fail.length) {
  console.error('globe isolation FAILED:');
  for (const f of fail) console.error('  -', f);
  process.exit(1);
}
console.log(`globe isolation OK — imports: ${imports.join(', ')}`);
