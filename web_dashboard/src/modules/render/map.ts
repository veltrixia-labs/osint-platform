import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// [v9.1] Global Scope Fix: Plugins like markercluster expect L to be global
(window as any).L = L;

import 'leaflet.markercluster';
import 'leaflet.markercluster/dist/MarkerCluster.css';
import 'leaflet.markercluster/dist/MarkerCluster.Default.css';
import type { Alert } from '../api';
import { fetchAlerts, fetchAlert } from '../api';
import { getTopicDef } from '../topics';
import { STRATEGIC_ASSETS } from '../infrastructure';
import { getAlertCoords, getNodeCoords } from './utils';

// ──────────────────────────────────────────────────────────────────────────────
// Module State (Internal)
// ──────────────────────────────────────────────────────────────────────────────

let activeMapFilters = new Set(['global']);
let currentFilterControl: L.Control | null = null;
let activeDiscoveryId: string | null = null;
let lastDiscoveryTrigger: number = 0;
let currentGlobalMap: L.Map | null = null;
let currentDynamicLayer: L.LayerGroup | null = null;
let clusterLayer: L.MarkerClusterGroup | null = null;
let isRendering = false; // Mutex to prevent infinite recursion

// ──────────────────────────────────────────────────────────────────────────────
// Primary Render Entry
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Main entry point for the Global Intelligence Map.
 * Renders the persistent Leaflet instance and overlay layers.
 */
export const renderMap = async (container: HTMLElement, _tier: string, focusAlertId?: string) => {
    if (isRendering) return;
    isRendering = true;

    console.log(`[Antigravity] Map Engine: Viewport update [Focus: ${focusAlertId || 'GLOBAL'}]`);
    
    // Safety delay for container transition
    await new Promise(r => setTimeout(r, 100));

    // 1. Lifecycle Recovery: Re-anchor existing map if detached from DOM
    const existingMapEl = document.getElementById('map-instance');
    if (currentGlobalMap && !existingMapEl) {
        console.log("[Antigravity] Map Anchor Recovered: Restoring engine to DOM");
        container.innerHTML = '<div id="map-instance" style="height:100%; width:100%; min-height:500px; background:#0b0e14;"></div>';
        
        await new Promise(r => requestAnimationFrame(r));
        currentGlobalMap.invalidateSize();
        
        // Restore HUD & Context (Moved to main render loop for sync)
    }

    // 2. Initial Setup: Create Persistent Map Canvas
    if (!currentGlobalMap) {
        container.innerHTML = '<div id="map-instance" style="height:100%; width:100%; min-height:500px; background:#09111f;"></div>';
        await new Promise(r => setTimeout(r, 100));
        
        const mapElement = document.getElementById('map-instance');
        if (!mapElement) {
            isRendering = false;
            return;
        }

        currentGlobalMap = L.map('map-instance', {
            zoomControl: false,
            attributionControl: false,
            minZoom: 2,
            maxZoom: 16,
            worldCopyJump: true
        }).setView([20, 0], 2);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 20
        }).addTo(currentGlobalMap);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}.png', {
            subdomains: 'abcd',
            maxZoom: 20,
            opacity: 0.9
        }).addTo(currentGlobalMap);

        // [v10.6] Dedicated Tactical Overlay Pane
        // Forced to top-layer (Z:650) to ensure animations are never hidden by labels or clusters.
        currentGlobalMap.createPane('vlt-tactical-pane');
        const tacticalPane = currentGlobalMap.getPane('vlt-tactical-pane');
        if (tacticalPane) {
            tacticalPane.style.zIndex = '650';
            tacticalPane.style.pointerEvents = 'none';
        }

        L.control.zoom({ position: 'bottomright' }).addTo(currentGlobalMap);
        currentDynamicLayer = L.layerGroup().addTo(currentGlobalMap);
        
        clusterLayer = (L as any).markerClusterGroup({
            showCoverageOnHover: false,
            maxClusterRadius: 60,
            iconCreateFunction: function(cluster: any) {
                const markers = cluster.getAllChildMarkers();
                const total = markers.length;
                const topicCounts: Record<string, number> = {};

                markers.forEach((m: any) => {
                    const alert = m.options.alertData as Alert;
                    const topic = alert?.topic || 'global';
                    topicCounts[topic] = (topicCounts[topic] || 0) + 1;
                });

                const sortedTopics = Object.keys(topicCounts).sort((a, b) => topicCounts[b] - topicCounts[a]);
                let gradientString = 'conic-gradient(';
                let currentPct = 0;
                
                sortedTopics.forEach((topic, idx) => {
                    const topicDef = getTopicDef(topic);
                    const color = topicDef?.color || '#58a6ff';
                    const pct = (topicCounts[topic] / total) * 100;
                    gradientString += `${color} ${currentPct}% ${currentPct + pct}%`;
                    currentPct += pct;
                    if (idx < sortedTopics.length - 1) gradientString += ', ';
                });
                gradientString += ')';

                return L.divIcon({
                    html: `
                        <div class="marker-cluster-base" style="width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; background: rgba(13, 17, 23, 0.85); backdrop-filter: blur(4px); border-radius: 50%; border: 1.5px solid rgba(255,255,255,0.2); box-shadow: 0 4px 12px rgba(0,0,0,0.5);">
                            <span style="color: #fff; font-weight: 800; font-size: 13px;">${total}</span>
                        </div>
                    `,
                    className: `marker-cluster marker-cluster-refined`,
                    iconSize: [40, 40]
                });
            }
        }).addTo(currentGlobalMap);

        // Filter UI moved to main render loop for state synchronization
    }

    const map = currentGlobalMap;
    const layerGroup = currentDynamicLayer!;
    if (!map.hasLayer(layerGroup)) layerGroup.addTo(map);

    try {
        // [v8.4] Tactical Zoom-Watcher with Health Guard
        const updateZoomFactor = () => {
            const cont = map.getContainer();
            if (!cont || !cont.isConnected) return;
            const zoom = map.getZoom();
            const factor = Math.max(1.0, 1.0 + (zoom - 3) * 0.15);
            cont.style.setProperty('--map-zoom-scale', factor.toString());
        };
        map.off('zoomend', updateZoomFactor);
        map.on('zoomend', updateZoomFactor);
        updateZoomFactor();

        // Handle Focal Suppression Class
        const mapCont = map.getContainer();
        if (mapCont && mapCont.isConnected) {
            if (focusAlertId) mapCont.classList.add('strategic-focal-active');
            else mapCont.classList.remove('strategic-focal-active');
        }

        // Async invalidation to handle tab layouts
        setTimeout(() => { 
            if (map.getContainer()?.isConnected) {
                map.invalidateSize(); 
                updateZoomFactor();
            }
        }, 150);

        if (!focusAlertId) {
            map.setView([20, 0], 2);
        }

        // [v8.7] Discovery Lock: Prevent polling from cutting off active animations
        const isReTrigger = (window as any)._mapTriggerTimestamp && (window as any)._mapTriggerTimestamp !== lastDiscoveryTrigger;
        if (focusAlertId && focusAlertId === activeDiscoveryId && !isReTrigger) {
            console.log("[Antigravity] Discovery Active - Skipping polling re-render to preserve narrative.");
            isRendering = false;
            return;
        }

        // [v8.9] Dynamic Strategy: Fetch all alerts from the last 24h (Maximum Visibility)
        const twentyFourHoursAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
        const [alerts] = await Promise.all([
            fetchAlerts({ since: twentyFourHoursAgo, limit: '500' })
        ]);
        
        // --- Mode Logic Integration (v1.6) ---
        layerGroup.clearLayers();
        clusterLayer?.clearLayers();

        if (!focusAlertId) {
            // MODE A: GLOBAL MONITORING
            console.log("[Antigravity] Map Mode: GLOBAL_MONITOR");
            
            // 1. Plot Clustered Alerts
            alerts.forEach(alert => {
                const coords = getAlertCoords(alert);
                if (!coords) return;

                const topicDef = getTopicDef(alert.topic);
                const topicColor = topicDef?.color || '#58a6ff';
                const baseSize = 8;

                const markerIcon = L.divIcon({
                    className: 'none',
                    html: `<div class="marker-ring-tactical" style="width:${baseSize}px; height:${baseSize}px; --ring-color:${topicColor}"><div class="ring-inner"></div></div>`,
                    iconSize: [baseSize, baseSize],
                    iconAnchor: [baseSize/2, baseSize/2]
                });

                const marker = L.marker([coords.lat, coords.lng], { 
                    icon: markerIcon,
                    alertData: alert 
                } as any);
                marker.bindPopup(createTacticalPopup(alert, topicColor), { className: 'tactical-popup', maxWidth: 320 });
                clusterLayer?.addLayer(marker);
            });

            // 2. Plot Persistent Strategic Infrastructure
            renderStrategicInfrastructure(layerGroup);
            
            if (!map.hasLayer(clusterLayer!)) clusterLayer?.addTo(map);
        } else {
            // MODE B: TACTICAL IMPACT ANALYSIS
            console.log(`[Antigravity] Map Mode: TACTICAL_FOCUS [${focusAlertId}]`);
            
            // Hide Cluster and Infrastructure for maximum clarity per user request
            if (map.hasLayer(clusterLayer!)) map.removeLayer(clusterLayer!);

            let focusedAlert = alerts.find(a => a.id === focusAlertId);
            
            // Fallback: If not in the main 24h bulk list (e.g. low-significance), fetch individually
            if (!focusedAlert) {
                try {
                    console.log(`[Antigravity] Alert ${focusAlertId} not in bulk list, performing explicit retrieval...`);
                    focusedAlert = await fetchAlert(focusAlertId);
                } catch (e) {
                    console.error("[Antigravity] Failed to resolve focused alert:", e);
                }
            }

            if (focusedAlert) {
                renderFocusedAlert(map, layerGroup, focusedAlert);
            } else {
                console.warn("[Antigravity] Focused alert context lost (24h retention limit reached).");
            }
        }

        // [v9.9] UI Sync: Refresh Filter Panel on every render to ensure active states match
        initMapFilter(map, container, () => {
            renderMap(container, _tier, focusAlertId);
        });

        isRendering = false;
    } catch (err) {
        console.error("[Antigravity] Map Strategy Render fault:", err);
        isRendering = false;
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// Sub-Renderers & Mode Components
// ──────────────────────────────────────────────────────────────────────────────

function renderStrategicInfrastructure(layer: L.LayerGroup) {
    STRATEGIC_ASSETS.forEach(asset => {
        const isVisible = !asset.topic_code || activeMapFilters.has(asset.topic_code as string) || activeMapFilters.has('global');
        if (!isVisible) return;

        const topicDef = asset.topic_code ? getTopicDef(asset.topic_code) : null;
        const color = topicDef?.color || '#bc8cff';
        
         const assetIcon = L.divIcon({
            className: 'infrastructure-node',
            html: `
                <div class="infra-marker-container ${asset.type}" title="${asset.name}">
                    <div class="infra-dot" style="background: ${color};"></div>
                    <div class="infra-label">${asset.name}</div>
                </div>
            `,
            iconSize: [100, 24],
            iconAnchor: [50, 12]
        });

        const popupContent = `
            <div class="tactical-card entity-card" style="--topic-color: ${color}">
                <div class="tactical-card-accent"></div>
                <div class="tactical-card-header">
                    <strong style="color:#fff; font-size:1rem;">${asset.name}</strong>
                    <div style="font-size:0.6rem; color:${color}; font-weight:800; letter-spacing:1px; text-transform:uppercase;">
                        ${asset.type.replace('_', ' ')} • STRATEGIC NODE
                    </div>
                </div>
                <div class="tactical-card-body">
                    ${asset.marketData ? `
                        <div class="market-strip u-flex-between" style="background:rgba(255,255,255,0.03); padding:8px; border-radius:6px; margin-bottom:12px; border:1px solid rgba(255,255,255,0.05);">
                            <div>
                                <span style="font-size:0.6rem; opacity:0.5; display:block;">${asset.marketData.ticker || 'INDEX'}</span>
                                <span style="font-weight:700; font-size:0.9rem;">${asset.marketData.price || asset.marketData.status}</span>
                            </div>
                            <div style="text-align:right;">
                                <span style="color:${asset.marketData.change! < 0 ? 'var(--danger)' : 'var(--success)'}; font-weight:700; font-size:0.9rem;">
                                    ${asset.marketData.change! > 0 ? '+' : ''}${asset.marketData.change}%
                                </span>
                                <span style="font-size:0.6rem; opacity:0.5; display:block;">24h CHANGE</span>
                            </div>
                        </div>
                    ` : ''}
                    
                    ${asset.strategicRole ? `
                        <div style="background: rgba(88, 166, 255, 0.1); border-left: 2px solid ${color}; padding: 6px 10px; margin-top: 10px; border-radius: 0 4px 4px 0;">
                            <div style="font-size: 0.55rem; color: ${color}; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 2px;">Strategic Role</div>
                            <div style="font-size: 0.75rem; color: #adbac7; line-height: 1.3;">${asset.strategicRole}</div>
                        </div>
                    ` : `
                        <p style="font-size:0.75rem; opacity:0.6; line-height:1.4; margin-bottom:8px;">${asset.description}</p>
                    `}
                </div>
                <div class="tactical-card-footer" style="padding-top:8px; margin-top:8px; border-top:1px solid rgba(255,255,255,0.05); font-size:0.6rem; opacity:0.4;">
                    STRATEGIC INFRASTRUCTURE • V.1.6
                </div>
            </div>
        `;

        L.marker([asset.lat, asset.lng], { icon: assetIcon, zIndexOffset: 500, pane: 'overlayPane' })
            .addTo(layer)
            .bindPopup(popupContent, { className: 'tactical-popup', maxWidth: 280 });
    });
}

function renderFocusedAlert(map: L.Map, layer: L.LayerGroup, alert: Alert) {
    const coords = getAlertCoords(alert);
    if (!coords) return;

    const intensity = alert.intensity || 5;
    const topicDef = getTopicDef(alert.topic);
    const topicColor = topicDef?.color || '#58a6ff';
    const baseSize = 16 + (intensity * 2);
    
    const markerIcon = L.divIcon({
        className: 'none',
        html: `
            <div class="marker-ring-tactical marker-ring-tactical--l1" 
                 style="width: calc(${baseSize}px * var(--map-zoom-scale, 1)); height: calc(${baseSize}px * var(--map-zoom-scale, 1)); --ring-color: ${topicColor}">
                <div class="glow-ring"></div>
                <div class="ring-inner"></div>
            </div>
        `,
        iconSize: [baseSize * 1.5, baseSize * 1.5],
        iconAnchor: [baseSize * 0.75, baseSize * 0.75]
    });

    const marker = L.marker([coords.lat, coords.lng], { icon: markerIcon, zIndexOffset: 5000 }).addTo(layer);
    marker.bindPopup(createTacticalPopup(alert, topicColor, true), { className: 'tactical-popup', maxWidth: 320 });

    const cascadingImpacts = alert.metadata_json?.cascading_impacts || [];

    setTimeout(() => {
        map.flyTo([coords.lat, coords.lng], 4, { duration: 1.5 });
        map.once('moveend', () => {
            marker.openPopup();
            if (cascadingImpacts.length > 0) {
                renderImpactChain(map, layer, coords, cascadingImpacts, 1, intensity, alert);
            }
        });
    }, 300);
}

function createTacticalPopup(alert: Alert, color: string, detailed = false): string {
    const geography = (alert as any).country || 'GLOBAL EVENT';
    const description = (alert as any).description || alert.target_label;
    const evidence = alert.evidence_list || (alert.metadata_json as any)?.evidence_list;
    const sourceUrl = evidence?.[0]?.url || '#';
    const cascadingImpacts = alert.metadata_json?.cascading_impacts || [];

    return `
        <div class="tactical-card" style="--topic-color: ${color}">
            <div class="tactical-card-accent"></div>
            <div class="tactical-card-header">
                <div class="geography-label">${alert.severity} • ${geography}</div>
                <h3 class="tactical-card-title">${alert.target_label}</h3>
            </div>
            <div class="tactical-card-body">
                <div class="tactical-card-summary">
                    <a href="${sourceUrl}" target="_blank" style="color: inherit; text-decoration: none; display: block; transition: opacity 0.2s;" onmouseover="this.style.opacity='0.7'" onmouseout="this.style.opacity='1.0'">
                        ${description}
                    </a>
                </div>
                
                ${detailed && cascadingImpacts.length > 0 ? `
                    <div style="margin: 12px 0 6px 0; font-size: 0.65rem; color: ${color}; font-weight: 800; text-transform: uppercase;">Supply Chain Ripple Effects</div>
                    <div style="display: flex; flex-direction: column; gap: 6px;">
                        ${cascadingImpacts.slice(0, 3).map((imp: any) => `
                            <div style="display: flex; justify-content: space-between; font-size: 0.75rem;">
                                <span style="opacity: 0.8;">${imp.entity_name}</span>
                                <span style="color: ${imp.impact_alpha < 0 ? 'var(--danger)' : 'var(--success)'}; font-weight: 800;">
                                    ${imp.impact_alpha > 0 ? '+' : ''}${imp.impact_alpha}%
                                </span>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
                
                <div style="font-size: 0.65rem; opacity: 0.5; margin-top: 10px;">
                    DETECTED: ${new Date(alert.triggered_at).toLocaleString('en-US', { timeStyle: 'short', dateStyle: 'medium' })}
                </div>
            </div>
            <div class="tactical-card-footer" style="justify-content: flex-end;">
                <div class="tactical-version-tag">V1.6 HUD</div>
            </div>
        </div>
    `;
}

/**
 * [v10.5] Renders a tactical expanding pulse to represent abstract impact waves.
 */
function renderTacticalRipple(layer: L.LayerGroup, latLng: L.LatLngExpression, color: string, level: number) {
    const size = 30 + (level * 40);
    const duration = 1500;
    
    const icon = L.divIcon({
        className: 'none',
        html: `
            <div class="tactical-mesh-pulse" style="--ripple-color: ${color}; --ripple-size: ${size}px; --ripple-duration: ${duration}ms">
                <div class="pulse-ring"></div>
            </div>
        `,
        iconSize: [size, size],
        iconAnchor: [size/2, size/2]
    });

    const marker = L.marker(latLng, { 
        icon, 
        interactive: false,
        pane: 'vlt-tactical-pane' 
    }).addTo(layer);
    setTimeout(() => {
        if (layer.hasLayer(marker)) layer.removeLayer(marker);
    }, duration);
}

// ── Deprecated Sub-Renderers ────────────────────────────────────────────────
// renderRegionalContext removed in v1.6 (Clustering and Split-View implemented)

function renderImpactChain(map: L.Map, layer: L.LayerGroup, parentCoords: {lat: number, lng: number}, impacts: any[], level: number, baseIntensity: number, originalAlert: Alert) {
    if (level > 3 || !impacts) return;

    const levelDelay = 1500; // [v10.5] Sequenced timing for distinct wave recognition

    impacts.forEach((finding, index) => {
        setTimeout(() => {
            let nodeCoords = getNodeCoords(finding);

            // [v9.10] Entity-Name Coordinate Resolution Fallback
            if (!nodeCoords && finding.entity_name) {
                const asset = STRATEGIC_ASSETS.find(a => 
                    a.name.toLowerCase().includes(finding.entity_name.toLowerCase()) ||
                    finding.entity_name.toLowerCase().includes(a.name.toLowerCase())
                );
                if (asset) {
                    nodeCoords = { lat: asset.lat, lng: asset.lng, source: 'Name-Lookup' };
                    console.log(`[Antigravity] Resolved coordinates for ${finding.entity_name} via ${asset.name}`);
                }
            }

            const pathColor = finding.impact_alpha < 0 ? '#f43f5e' : '#10b981';

            // [v10.5] Tactical Mesh Fallback: If no coordinates, render a ripple at origin
            // Fix [v10.7]: Remove early return to allow recursion to continue for abstract alerts.
            if (!nodeCoords) {
                renderTacticalRipple(layer, L.latLng(parentCoords.lat, parentCoords.lng), pathColor, level);
                // We proceed even if nodeCoords is missing, using parentCoords as the next origin.
                nodeCoords = { lat: parentCoords.lat, lng: parentCoords.lng, source: 'Abstract-Carryover' };
            } else {
                // Arc Path Calculation (Only if real destination exists)
                const start = L.latLng(parentCoords.lat, parentCoords.lng);
                const end = L.latLng(nodeCoords.lat, nodeCoords.lng);
                const points: L.LatLng[] = [];
                const steps = 100;
                
                const dLat = end.lat - start.lat;
                const dLng = end.lng - start.lng;
                const dist = Math.sqrt(dLat*dLat + dLng*dLng);
                
                const heightAttenuation = 1.0 - (level - 1) * 0.2; 
                const offsetFactor = (0.15 + (Math.min(dist, 40) / 200)) * heightAttenuation + (index % 2 === 0 ? 0.05 : -0.05);

                const midLat = (start.lat + end.lat) / 2;
                const midLng = (start.lng + end.lng) / 2;
                const cpLat = midLat - dLng * offsetFactor;
                const cpLng = midLng + dLat * offsetFactor;

                for (let i = 0; i <= steps; i++) {
                    const t = i / steps;
                    const lat = (1-t)**2 * start.lat + 2*(1-t)*t * cpLat + t**2 * end.lat;
                    const lng = (1-t)**2 * start.lng + 2*(1-t)*t * cpLng + t**2 * end.lng;
                    points.push(L.latLng(lat, lng));
                }

                const arc = L.polyline(points, {
                    className: `propagation-arc-curved`,
                    color: pathColor,
                    weight: 2.5, // [v10.7] High-visibility constant weight
                    opacity: 0.8,
                    smoothFactor: 1.5,
                    interactive: false,
                    pane: 'vlt-tactical-pane' // Force to top-layer
                }).addTo(layer);

                // [v10.6] Sync CSS Variable to SVG element for glow effect
                setTimeout(() => {
                    const el = arc.getElement() as HTMLElement;
                    if (el) el.style.setProperty('--ring-color', pathColor);
                }, 0);

                if (level === 1) {
                    const centerPoint = L.latLng((start.lat + end.lat)/2, (start.lng + end.lng)/2);
                    map.panTo(centerPoint, { animate: true, duration: 1.2 });
                }
            }

            setTimeout(() => {
                const baseSize = 10 - (level * 1.5);
                const markerClass = `marker-ring-tactical marker-ring-tactical--l${Math.min(level + 1, 3)} node-ignite`;
                
                const nodeIcon = L.divIcon({
                    className: 'none',
                    html: `
                        <div class="${markerClass}" 
                             style="width: calc(${baseSize}px * var(--map-zoom-scale, 1)); height: calc(${baseSize}px * var(--map-zoom-scale, 1)); --ring-color: ${pathColor}">
                            <div class="glow-ring"></div>
                            <div class="ring-inner" style="width:2px; height:2px;"></div>
                        </div>
                    `,
                    iconSize: [baseSize * 1.5, baseSize * 1.5],
                    iconAnchor: [baseSize * 0.75, baseSize * 0.75]
                });

                 const nodeMarker = L.marker([nodeCoords.lat, nodeCoords.lng], { 
                     icon: nodeIcon, 
                     pane: 'vlt-tactical-pane' 
                 }).addTo(layer);

                if (level === 3) {
                    const impactPopupContent = `
                        <div class="tactical-card entity-card" style="--topic-color: ${pathColor}">
                            <div class="tactical-card-accent"></div>
                            <div class="tactical-card-header">
                                <strong style="color:#fff; font-size:1rem;">${finding.entity_name}</strong>
                                <div style="font-size:0.6rem; color:${pathColor}; font-weight:800; letter-spacing:1px; text-transform:uppercase;">
                                    CAUSAL IMPACT • LEVEL 3
                                </div>
                            </div>
                            <div class="tactical-card-body">
                                <div class="market-strip u-flex-between" style="background:rgba(255,255,255,0.03); padding:8px; border-radius:6px; margin-bottom:12px; border:1px solid rgba(255,255,255,0.05);">
                                    <div>
                                        <span style="font-size:0.6rem; opacity:0.5; display:block;">IMPACT ALPHA</span>
                                        <span style="font-weight:700; font-size:0.9rem;">${finding.impact_alpha > 0 ? '+' : ''}${finding.impact_alpha}%</span>
                                    </div>
                                    <div style="text-align:right;">
                                        <span style="color:${pathColor}; font-weight:700; font-size:0.9rem;">TARGETED</span>
                                        <span style="font-size:0.6rem; opacity:0.5; display:block;">DISCOVERY COMPLETE</span>
                                    </div>
                                </div>
                                <p style="font-size:0.75rem; color:#8b949e; line-height:1.4;">
                                    Strategic dependency confirmed. This entity is currently being monitored for second-order volatility risks.
                                </p>
                                ${originalAlert.related_report_id ? `
                                    <button class="tactical-action-btn u-m-top-1" style="width:100%;" onclick="window.dispatchEvent(new CustomEvent('map-view-report', {detail: {id: '${originalAlert.related_report_id}'}}))">
                                        Open Full Analysis &rarr;
                                    </button>
                                ` : ''}
                            </div>
                        </div>
                    `;
                    nodeMarker.bindPopup(impactPopupContent, { className: 'tactical-popup', maxWidth: 280 }).openPopup();
                }

                const subImpacts = finding.cascading_impacts || finding.metadata_json?.cascading_impacts;
                
                // [v10.5] MONITOR Organization Sync:
                // When reaching wave 2 or 3, if fewer than 3 sub-impacts exist, 
                // supplement with Strategic Assets matching the alert topic.
                if (level >= 2 && (!subImpacts || subImpacts.length < 2)) {
                    const targetTopic = originalAlert.topic;
                    const metaTopic = (originalAlert.metadata_json as any)?.topic;
                    const effectiveTopic = targetTopic || metaTopic;

                    if (effectiveTopic) {
                        const relatedAssets = STRATEGIC_ASSETS.filter(a => a.topic_code === effectiveTopic && a.importance >= 0.9);
                        const topAssets = relatedAssets.slice(0, 3);
                        
                        topAssets.forEach((asset, i) => {
                            // Inject virtual impacts targeting real map organizations
                            const virtualImpact = {
                                entity_name: asset.name,
                                location_lat: asset.lat,
                                location_lng: asset.lng,
                                impact_alpha: finding.impact_alpha * 0.8,
                                is_virtual: true
                            };
                            
                            // Delay virtual arcs slightly for visual layering
                            setTimeout(() => {
                                renderImpactChain(map, layer, nodeCoords, [virtualImpact], level + 1, baseIntensity, originalAlert);
                            }, i * 300);
                        });
                    }
                }

                if (subImpacts && level < 3) {
                    renderImpactChain(map, layer, nodeCoords, subImpacts, level + 1, baseIntensity, originalAlert);
                }
            }, levelDelay);

        }, index * 200);
    });
}

function initMapFilter(map: L.Map, _container: HTMLElement, onUpdate: () => void) {
    if (currentFilterControl) {
        currentFilterControl.remove();
    }

    const FilterControl = L.Control.extend({
        options: { position: 'topleft' },
        onAdd: function() {
            const div = L.DomUtil.create('div', 'map-filter-control map-filter-panel');
            L.DomEvent.disableClickPropagation(div);
            L.DomEvent.disableScrollPropagation(div);

            const TOPICS = [
                { id: 'global', label: 'Monitor', icon: '🌐', color: '#58a6ff' },
                { id: 'energy_resource_risk', label: 'Energy', icon: '⚡', color: '#d29922' },
                { id: 'global_market_intelligence', label: 'Market', icon: '🏛️', color: '#3fb950' },
                { id: 'crypto_geopolitics', label: 'Crypto', icon: '₿', color: '#f78166' },
                { id: 'ai_semiconductor_intelligence', label: 'AI/Tech', icon: '🤖', color: '#bc8cff' },
                { id: 'defense_technology', label: 'Defense', icon: '🛡️', color: '#ff7b72' },
                { id: 'supply_chain_intelligence', label: 'Trade', icon: '🚢', color: '#79c0ff' }
            ];

            div.innerHTML = `
                <div class="monitor-header" style="display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 0.6rem; border-bottom: 1px solid rgba(255,255,255,0.15); padding-bottom: 6px; white-space: nowrap;">
                    <h3 style="font-size: 0.75rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent); flex-shrink: 0;">Strategic Monitoring</h3>
                    <span style="font-size: 0.55rem; opacity: 0.5; letter-spacing: 1.5px; font-weight: 700;">LIVE V1.5</span>
                </div>
                <div class="monitor-hotbar">
                    ${TOPICS.map(t => `
                        <button class="preset-btn ${activeMapFilters.has(t.id) ? 'active' : ''}" 
                                data-preset="${t.id}" 
                                style="--accent-color: ${t.color}"
                                title="${t.label} Intelligence">
                            <span class="btn-icon">${t.icon}</span>
                            <span class="btn-label">${t.label}</span>
                        </button>
                    `).join('')}
                </div>
            `;
            
            div.querySelectorAll('.preset-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const preset = (e.currentTarget as HTMLElement).dataset.preset!;
                    
                    // [v9.8] Strict Selection Mutex:
                    // If already active, toggle off. Otherwise, clear everything and set only the new one.
                    if (activeMapFilters.has(preset)) {
                        activeMapFilters.clear();
                    } else {
                        activeMapFilters.clear();
                        activeMapFilters.add(preset);
                    }
                    
                    onUpdate();
                });
            });

            return div;
        }
    });

    currentFilterControl = new (FilterControl as any)();
    currentFilterControl?.addTo(map);

    // Removed Silent Monitor status per user request
}
