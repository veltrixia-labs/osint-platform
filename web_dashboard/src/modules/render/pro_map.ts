import { renderRelationshipView } from './relationship_view';

/**
 * Pro Interactive Map route — now the RELATIONSHIP VIEW.
 *
 * Search an entity, see what the vault records about its relations: edge type, direction, role,
 * weight with its unit, the provenance of that weight, and a link to the source document.
 *
 * Replaces the news-triggered chokepoint entry (renderTriggerMap). pro_trigger_map.ts and
 * pro_interactive_map.ts stay in the tree and are unreferenced from nav — the chokepoint surface
 * is still the right view for Pro Insight, and removing it is a separate decision. The
 * relationship view deliberately carries none of its apparatus: no impact_score, no order-3
 * country×DECAY expansion, no coordinate gate. Those answer "what would a shock do"; this
 * answers "what is recorded here", and joining them would let the second inherit the first's
 * derived numbers. See the vault's CLAUDE.md §5.
 */
export function renderProMap() {
    const container = document.getElementById('pro-map-container');
    if (!container) return;
    if (container.dataset.relViewMounted === '1') return;
    container.dataset.relViewMounted = '1';
    void renderRelationshipView(container);
}
