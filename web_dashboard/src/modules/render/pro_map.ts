import { renderTriggerMap } from './pro_trigger_map';

/**
 * Pro Interactive Map route — two-stage, news-triggered.
 *
 *   Stage 1: WHERE is something happening (one node per FIRING scenario).
 *   Stage 2: WHAT it affects (the full cascade, on click).
 *
 * Replaces the previous entry state, which opened straight into a global
 * multi-domain aggregate built by the legacy spatial engine. That view answered a
 * question nobody had asked, and it asserted an "epicenter" whether or not anything
 * was actually happening. The backend routes and the legacy engine are untouched —
 * other consumers still read those tables — but the map no longer opens on them.
 */
export function renderProMap() {
    const container = document.getElementById('pro-map-container');
    if (!container) return;

    if (container.dataset.triggerMapMounted === '1') {
        requestAnimationFrame(() => {
            window.dispatchEvent(new Event('resize'));
        });
        return;
    }
    container.dataset.triggerMapMounted = '1';
    renderTriggerMap(container);
}
