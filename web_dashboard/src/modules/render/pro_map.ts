import { renderGlobalSurveillanceMap } from './pro_interactive_map';

/**
 * Pro Interactive Map route.
 *
 * The sidebar route is a global surveillance monitor by default. It uses the
 * same MapLibre + deck.gl interleaved renderer as Pro report spatial sections,
 * but starts from the global fallback data set when no specific domain/report
 * context is available.
 */

export function renderProMap() {
    const container = document.getElementById('pro-map-container');
    if (!container) return;

    if (container.dataset.globalSurveillanceMounted === '1') {
        requestAnimationFrame(() => {
            window.dispatchEvent(new Event('resize'));
        });
        return;
    }
    container.dataset.globalSurveillanceMounted = '1';
    renderGlobalSurveillanceMap(container);
}
