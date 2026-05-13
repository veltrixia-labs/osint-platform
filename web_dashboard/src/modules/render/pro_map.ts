import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

/**
 * pro_map.ts
 * Implementation of the Pro Interactive Map using Leaflet.js
 */

let map: L.Map | null = null;

export function renderProMap() {
    const container = document.getElementById('pro-map-container');
    if (!container) return;

    // If container is empty, initialize the structure
    if (container.innerHTML === '') {
        container.innerHTML = `
            <aside class="pro-map-sidebar">
                <h2 style="font-size: 1.2rem; margin-bottom: 1rem; color: var(--accent);">Strategic Analysis</h2>
                <div class="pro-map-controls">
                    <p style="font-size: 0.85rem; color: var(--text-secondary); line-height: 1.4;">
                        Professional-grade spatial intelligence. Use this layer to identify geographic correlations between signals and infrastructure.
                    </p>
                    <hr style="border: 0; border-top: 1px solid var(--border); margin: 1.5rem 0;" />
                    <div style="opacity: 0.5; font-size: 0.8rem; text-align: center; margin-top: 2rem;">
                        [ Geographic Filters & Analysis Tools – Coming Soon ]
                    </div>
                </div>
            </aside>
            <div id="pro-map-canvas"></div>
        `;
    }

    // Initialize map if not already done
    if (!map) {
        // We need a slight delay to ensure the canvas is rendered in the DOM before Leaflet tries to attach
        setTimeout(() => {
            map = L.map('pro-map-canvas', {
                zoomControl: true,
                attributionControl: false
            }).setView([20, 0], 2);

            L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                maxZoom: 19
            }).addTo(map!);

            map!.invalidateSize();
        }, 100);
    } else {
        // If map already exists, just refresh size
        setTimeout(() => {
            map?.invalidateSize();
        }, 100);
    }
}
