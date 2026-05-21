import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// [v9.1] Global Scope Fix: Plugins like markercluster expect L to be global
(window as any).L = L;

import 'leaflet.markercluster';
import 'leaflet.markercluster/dist/MarkerCluster.css';
import 'leaflet.markercluster/dist/MarkerCluster.Default.css';
import type { Alert } from '../api';
import { fetchAlerts, fetchAlert, apiClient } from '../api';
import { getTopicDef } from '../topics';
import { STRATEGIC_ASSETS } from '../infrastructure';
import { getAlertCoords, getNodeCoords, formatIntelDateTime } from './utils';
import { renderImpactSidebar, hideImpactSidebar } from './impact_panel';

// ──────────────────────────────────────────────────────────────────────────────
// Module State (Internal)
// ──────────────────────────────────────────────────────────────────────────────

let activeMapFilters = new Set(['global']);
let currentFilterControl: L.Control | null = null;
let currentGlobalMap: L.Map | null = null;
let currentDynamicLayer: L.LayerGroup | null = null;
let clusterLayer: L.MarkerClusterGroup | null = null;
let isRendering = false; // Mutex to prevent infinite recursion
let currentMapMode: 'public' | 'analysis' | 'strategic' = 'public';

// ──────────────────────────────────────────────────────────────────────────────
// Primary Render Entry
// ──────────────────────────────────────────────────────────────────────────────

/**
 * Main entry point for the Global Intelligence Map.
 * Renders the persistent Leaflet instance and overlay layers.
 */
export const renderMap = async (container: HTMLElement, tier: string, focusAlertId?: string) => {
    // 0. Mode Initialization based on Tier
    if (!currentGlobalMap) {
        if (tier === 'free') currentMapMode = 'public';
        else if (tier === 'pro') currentMapMode = 'analysis';
        else if (tier === 'experts' || tier === 'enterprise') currentMapMode = 'strategic';
    }
    if (isRendering) return;
    isRendering = true;

    console.log(`[Antigravity] Map Engine: Viewport update [Focus: ${focusAlertId || 'GLOBAL'}]`);

    // Safety delay for container transition
    await new Promise(r => setTimeout(r, 100));

    // 1. Lifecycle Recovery: Re-anchor existing map if detached from DOM
    const existingMapEl = document.getElementById('map-instance');
    if (currentGlobalMap && !existingMapEl) {
        console.log("[Antigravity] Map Anchor Recovered: Restoring engine to DOM");
        container.innerHTML = `
            <div style="display:flex; height:100%; width:100%; position:relative;">
                <div id="map-instance" style="flex:1; min-height:500px; background:#0b0e14; position:relative;"></div>
                <div id="impact-panel-container" style="display:none; width:350px; min-width:350px; background:var(--bg-secondary); border-left:1px solid var(--border); overflow:hidden;"></div>
            </div>
        `;

        await new Promise(r => requestAnimationFrame(r));
        currentGlobalMap.invalidateSize();

        // Restore HUD & Context (Moved to main render loop for sync)
    }

    // 2. Initial Setup: Create Persistent Map Canvas
    if (!currentGlobalMap) {
        container.innerHTML = `
            <div style="display:flex; height:100%; width:100%; position:relative;">
                <div id="map-instance" style="flex:1; min-height:500px; background:#0b0e14; position:relative;"></div>
                <div id="impact-panel-container" style="display:none; width:350px; min-width:350px; background:var(--bg-secondary); border-left:1px solid var(--border); overflow:hidden;"></div>
            </div>
        `;
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

        // [v10.19] PHYSICAL PANE SEGREGATION
        // Arc pane (BELOW): Lines and propagation paths — never overlaps nodes
        currentGlobalMap.createPane('vlt-arc-pane');
        const arcPane = currentGlobalMap.getPane('vlt-arc-pane');
        if (arcPane) {
            arcPane.style.zIndex = '350'; // Below tilePane(400) labels but above base
            arcPane.style.pointerEvents = 'none';
        }

        // Node pane (ABOVE): Cards, markers, HUD — always on top
        currentGlobalMap.createPane('vlt-tactical-pane');
        const tacticalPane = currentGlobalMap.getPane('vlt-tactical-pane');
        if (tacticalPane) {
            tacticalPane.style.zIndex = '900'; // Above everything: markerPane(600), popupPane(700), tooltipPane(650)
            tacticalPane.style.pointerEvents = 'none';
        }

        L.control.zoom({ position: 'bottomright' }).addTo(currentGlobalMap);

        // 2.2 Segmented Mode Control

        currentDynamicLayer = L.layerGroup().addTo(currentGlobalMap);

        clusterLayer = (L as any).markerClusterGroup({
            showCoverageOnHover: false,
            maxClusterRadius: 60,
            iconCreateFunction: function (cluster: any) {
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

        // [v15.0] Discovery Lock Removed: The static pipeline must always reflect the immediate state.

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

            hideImpactSidebar('impact-panel-container');

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
                    iconAnchor: [baseSize / 2, baseSize / 2]
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
            renderMap(container, tier, focusAlertId);
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

/**
 * [v10.8] Displays a tactical status indicator on the map during discovery.
 */
function renderTacticalStatusHud(_layer: L.LayerGroup, text: string, status: string = 'processing') {
    const hudId = 'tactical-discovery-hud';
    const existing = document.getElementById(hudId);
    if (existing) existing.remove();

    const colorMap: Record<string, string> = {
        'processing': 'rgba(88, 166, 255, 0.2)',
        'complete': 'rgba(46, 160, 67, 0.2)',
        'failed': 'rgba(248, 81, 73, 0.2)'
    };

    const HUD_HTML = `
        <div class="hud-inner" style="background: rgba(13, 17, 23, 0.95); border: 1px solid ${colorMap[status] || 'rgba(255,255,255,0.1)'}; padding: 8px 16px; border-radius: 4px;">
            <span class="hud-text" style="font-weight: 800; font-family: monospace;">[${status.toUpperCase()}] ${text}</span>
        </div>
    `;

    const hud = L.DomUtil.create('div', `tactical-status-hud status-${status} active`, document.getElementById('map-instance') || undefined);
    hud.id = hudId;
    hud.innerHTML = HUD_HTML;
}

// [v10.9] Global HUD Controller
window.addEventListener('map-status-update', (e: any) => {
    // Note: This requires a layer reference. In on-demand mode, we use the active map instance.
    const mapEl = document.getElementById('map-instance');
    if (mapEl) {
        renderTacticalStatusHud({} as any, e.detail.message);
    }
});

export function renderFocusedAlert(map: L.Map, layer: L.LayerGroup, alert: Alert) {
    // [v10.35] FATAL CRASH PROTECTION
    try {
        let rawCoords = getAlertCoords(alert);

        // [v10.12] Geographic Fallback: If no explicit coords, use first Strategic Asset for topic
        if (!rawCoords && alert.topic) {
            const topicAsset = STRATEGIC_ASSETS.find(a => a.topic_code === alert.topic);
            if (topicAsset) {
                rawCoords = { lat: topicAsset.lat, lng: topicAsset.lng, source: 'Topic-Asset-Fallback' };
            }
        }

        if (!rawCoords || isNaN(Number(rawCoords.lat)) || isNaN(Number(rawCoords.lng))) {
            console.error(`[Antigravity] Map Engine Halt: Invalid coordinates for ${alert.id}`, rawCoords);
            renderTacticalStatusHud(layer, "ERROR: POSITION_INVALID");
            return;
        }

        const coords = { lat: Number(rawCoords.lat), lng: Number(rawCoords.lng) };
        const intensity = alert.intensity || 5;
        const topicDef = getTopicDef(alert.topic);
        const topicColor = topicDef?.color || '#58a6ff';

        // [v15.0] Instant Render Core
        renderTacticalStatusHud(layer, `Tracking: ${alert.target_label.split(' | ')[0]}`, "processing");

        const alertFinding = {
            entity_name: alert.target_label || "Active Event",
            impact_summary: alert.description || alert.target_label || "Strategic Signal Detected",
            impact_alpha: alert.intensity || 5
        };
        renderTacticalNodeLabel(layer, [coords.lat, coords.lng], alertFinding, topicColor, 0, 0, 1.0);

        const cascadingImpactsRaw = alert.cascading_impacts || alert.metadata_json?.cascading_impacts || [];
        let cascadingImpacts = [...cascadingImpactsRaw];

        const currentStatus = alert.backbone_discovery_status || 'idle';

        if (currentStatus === 'complete' && cascadingImpacts.length > 0) {
            renderTacticalStatusHud(layer, "AI ANALYSIS COMPLETE", "complete");
            renderImpactChain(map, layer, coords, cascadingImpacts, 1, intensity, alert, new Set());
            renderImpactSidebar('impact-panel-container', alert, map);
        } else if (currentStatus === 'failed') {
            renderImpactSidebar('impact-panel-container', alert, map);
            renderTacticalStatusHud(layer, "AI ANALYSIS FAILED", "failed");
        } else {
            // Processing mode - poll but do not lock animations
            const startPoller = (initialMsg: string) => {
                if ((window as any)._activeTacticalPoller) clearInterval((window as any)._activeTacticalPoller);
                renderTacticalStatusHud(layer, initialMsg, "processing");
                let pollCount = 0;
                const poller = setInterval(() => {
                    pollCount++;
                    if (pollCount > 120) {
                        clearInterval(poller);
                        renderTacticalStatusHud(layer, "TIMED OUT", "failed");
                        alert.backbone_discovery_status = 'failed';
                        renderImpactSidebar('impact-panel-container', alert, map);
                        return;
                    }

                    fetchAlert(alert.id).then(data => {
                        if (!data) return;
                        if (data.backbone_discovery_status === 'complete') {
                            clearInterval(poller);
                            renderTacticalStatusHud(layer, "AI ANALYSIS COMPLETE", "complete");
                            alert.cascading_impacts = data.cascading_impacts;
                            alert.backbone_discovery_status = 'complete';

                            layer.clearLayers();
                            renderTacticalNodeLabel(layer, [coords.lat, coords.lng], alert, topicColor, 1, 0, 1.0);
                            renderImpactChain(map, layer, coords, data.cascading_impacts || [], 2, intensity, alert, new Set());
                            renderImpactSidebar('impact-panel-container', alert, map);
                        } else if (data.backbone_discovery_status === 'failed') {
                            clearInterval(poller);
                            alert.backbone_discovery_status = 'failed';
                            renderImpactSidebar('impact-panel-container', alert, map);
                            renderTacticalStatusHud(layer, "AI ANALYSIS FAILED", "failed");
                        } else {
                            renderTacticalStatusHud(layer, `AI REFINING [${pollCount}]`, "processing");
                        }
                    });
                }, 5000);
                (window as any)._activeTacticalPoller = poller;
            };

            if (currentStatus === 'processing') {
                renderImpactSidebar('impact-panel-container', alert, map);
                startPoller("ANALYZING");
            } else {
                renderImpactSidebar('impact-panel-container', alert, map);
                // Discovery HUD and API triggers only for Analysis+
                if (currentMapMode !== 'public') {
                    apiClient.post(`/alerts/${alert.id}/analyze`).then(() => startPoller("DISCOVERY TRIGGERED"));
                }
            }
        }

        // Final Filter: if Public mode, ensure all discovery layers are hidden
        if (currentMapMode === 'public') {
            layer.clearLayers();
            renderTacticalNodeLabel(layer, [coords.lat, coords.lng], alertFinding, topicColor, 1, 0, 1.0);
            renderTacticalStatusHud(layer, "PUBLIC_DATA_SYNCED", "complete");
        }

        // Static Camera Snap
        map.setView([coords.lat, coords.lng], 4);

    } catch (e) {
        console.error("[Antigravity] FATAL MAP ERROR:", e);
        renderTacticalStatusHud(layer, "MAP_ENGINE_FAULT: RENDER_ABORTED");
    }
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
                    DETECTED: ${formatIntelDateTime(alert.triggered_at)}
                </div>
            </div>
            <div class="tactical-card-footer" style="justify-content: flex-end;">
                <div class="tactical-version-tag">V1.6 HUD</div>
            </div>
        </div>
    `;
}

/**
 * [v53] Robust Tactical Node Label Rendering (High-Fidelity Sync)
 */
function renderTacticalNodeLabel(layer: L.LayerGroup, coords: [number, number], finding: any, color: string, _level: number, _index: number, opacity: number) {
    try {
        const alpha = finding.impact_alpha ?? 0;
        const alphaFormatted = `${alpha >= 0 ? '+' : ''}${alpha.toFixed(1)}%`;
        const sentimentClass = alpha >= 0 ? 'sentiment-positive' : 'sentiment-negative';

        const hexToRgb = (hex: string) => {
            const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
            return result ? `${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}` : '88, 166, 255';
        };
        const colorRgb = hexToRgb(color);

        const labelHtml = `
            <div class="tactical-node-wrapper ${sentimentClass}" style="--node-color: ${color}; --node-color-rgb: ${colorRgb}; opacity: ${opacity};">
                <div class="node-label-inner card-high-fidelity" style="padding: 8px;">
                    <div class="node-label-header" style="margin-bottom: 2px;">
                        <span class="node-name" style="font-weight: 800; font-size: 0.8rem;">${finding.entity_name || 'Strategic Hub'}</span>
                    </div>
                    <div class="node-footer" style="margin-top: 0; padding-top: 0; border-top: none;">
                        <span class="node-impact-alpha" style="font-size: 0.85rem;">${alphaFormatted} ALPHA</span>
                    </div>
                </div>
            </div>
        `;

        const labelIcon = L.divIcon({
            className: 'none',
            html: labelHtml,
            iconSize: [180, 60],
            iconAnchor: [-15, 30]
        });

        const labelMarker = L.marker(coords, {
            icon: labelIcon,
            pane: 'vlt-tactical-pane',
            zIndexOffset: 1000
        });

        labelMarker.addTo(layer);
        const el = labelMarker.getElement();
        if (el) {
            el.style.pointerEvents = 'auto';
            el.addEventListener('click', () => {
                const nodeId = (finding.entity_name || '').replace(/\s+/g, '-');
                const sidebarItem = document.querySelector(`.sidebar-item[data-id="${nodeId}"]`) as HTMLElement;
                if (sidebarItem) {
                    sidebarItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    // Prevent infinite bounce if already expanded
                    const details = sidebarItem.querySelector('.sidebar-item-details') as HTMLElement;
                    if (details && details.style.display === 'none') {
                        sidebarItem.click();
                    }
                }
            });
        }

    } catch (err) {
        console.error("[Antigravity] FAILED to render tactical node label:", err, finding);
    }
}

function renderImpactChain(map: L.Map, layer: L.LayerGroup, parentCoords: { lat: number, lng: number }, impacts: any[], level: number, baseIntensity: number, originalAlert: Alert, visited: Set<string> = new Set()) {
    // [v3.0] Tier-based Depth Enforcement
    if (currentMapMode === 'public') return;
    if (currentMapMode === 'analysis' && level > 2) return;
    if (level > 4 || !impacts || impacts.length === 0) return;

    // [v15.0] Synchronous Propagation
    impacts.forEach((finding, index) => {
        try {
            let nodeCoords = getNodeCoords(finding);

            if (!nodeCoords && finding.entity_name) {
                const asset = STRATEGIC_ASSETS.find(a =>
                    a.name.toLowerCase().includes(finding.entity_name.toLowerCase()) ||
                    finding.entity_name.toLowerCase().includes(a.name.toLowerCase())
                );
                if (asset) nodeCoords = { lat: asset.lat, lng: asset.lng, source: 'Name-Lookup' };
            }

            // Fixed Polar Offset (No random jitter)
            const impactCount = impacts.length;
            const fanAngle = 140;
            const startAngle = -70;
            const angleStep = impactCount > 1 ? fanAngle / (impactCount - 1) : 0;
            const currentAngle = startAngle + (index * angleStep);

            const rad = (currentAngle * Math.PI) / 180;
            const radius = 18.0 + (level * 4);

            const opacityLevels = [1.0, 0.8, 0.5, 0.3];
            let currentOpacity = opacityLevels[Math.min(level, 3)];

            // [v15.1] Selection & Neighbor Boost
            // If we are at level 1 (direct neighbors of root alert), boost to 0.85
            if (level === 1) currentOpacity = 0.85;

            const dispLat = radius * Math.cos(rad);
            const dispLng = radius * Math.sin(rad);

            if (!nodeCoords) {
                // Exact deterministic offset
                nodeCoords = {
                    lat: parentCoords.lat + dispLat,
                    lng: parentCoords.lng + dispLng,
                    source: 'Polar-Fixed'
                };
            }

            finding._derived_from_parent_coords = true;

            if (!nodeCoords || isNaN(nodeCoords.lat) || isNaN(nodeCoords.lng)) return;

            finding._rendered_lat = nodeCoords.lat;
            finding._rendered_lng = nodeCoords.lng;

            const pathColor = (finding.impact_alpha || 0) < 0 ? '#f43f5e' : '#10b981';

            // Immediate Path Render
            const start = L.latLng(parentCoords.lat, parentCoords.lng);
            const end = L.latLng(nodeCoords.lat, nodeCoords.lng);
            const distance = L.latLng(start).distanceTo(end);

            if (distance > 100) {
                L.polyline([start, end], {
                    className: `propagation-arc-static`,
                    color: pathColor,
                    weight: 2,
                    opacity: currentOpacity * 0.5,
                    interactive: false,
                    pane: 'vlt-arc-pane'
                }).addTo(layer);

                // [v15.2] Arc-based Impact Labeling (PRIMARY / SECONDARY IMPACT)
                if (level <= 2) {
                    const labelText = level === 1 ? 'PRIMARY IMPACT' : 'SECONDARY IMPACT';
                    const midPoint = {
                        lat: (parentCoords.lat + nodeCoords.lat) / 2,
                        lng: (parentCoords.lng + nodeCoords.lng) / 2
                    };
                    const arcLabelIcon = L.divIcon({
                        className: 'none',
                        html: `<div style="color: ${pathColor}; font-size: 0.5rem; font-weight: 900; text-transform: uppercase; white-space: nowrap; opacity: ${currentOpacity * 0.7}; text-shadow: 0 0 4px #000;">${labelText}</div>`,
                        iconSize: [80, 10],
                        iconAnchor: [40, 5]
                    });
                    L.marker([midPoint.lat, midPoint.lng], {
                        icon: arcLabelIcon,
                        pane: 'vlt-tactical-pane',
                        interactive: false
                    }).addTo(layer);
                }
            }

            // Immediate Node Render
            const baseSize = 12;
            const markerClass = `marker-ring-tactical marker-ring-tactical--l${Math.min(level, 3)}`;
            const nodeIcon = L.divIcon({
                className: 'none',
                html: `<div class="${markerClass}" style="width:${baseSize}px; height:${baseSize}px; --ring-color:${pathColor}; box-shadow: 0 0 8px ${pathColor}; border-radius: 50%; opacity: ${currentOpacity};"><div class="glow-ring"></div></div>`,
                iconSize: [baseSize, baseSize],
                iconAnchor: [baseSize / 2, baseSize / 2]
            });

            L.marker([nodeCoords.lat, nodeCoords.lng], {
                icon: nodeIcon,
                pane: 'vlt-tactical-pane',
                zIndexOffset: 500
            }).addTo(layer);

            renderTacticalNodeLabel(layer, [nodeCoords.lat, nodeCoords.lng], finding, pathColor, level, index, currentOpacity);

            // Recursive Chain (Synchronous)
            const subImpacts = finding.cascading_impacts || (finding.metadata_json as any)?.cascading_impacts;
            const nodeId = finding.stakeholder_id || finding.entity_name;
            if (subImpacts && subImpacts.length > 0 && level < 4 && !visited.has(nodeId)) {
                visited.add(nodeId);
                renderImpactChain(map, layer, nodeCoords, subImpacts, level + 1, baseIntensity, originalAlert, visited);
            }
        } catch (e) {
            console.error("[v15.0] Static Map Error:", e);
        }
    });
}

function initMapFilter(map: L.Map, _container: HTMLElement, onUpdate: () => void) {
    if (currentFilterControl) currentFilterControl.remove();

    const FilterControl = L.Control.extend({
        options: { position: 'topleft' },
        onAdd: function () {
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
                    if (activeMapFilters.has(preset)) activeMapFilters.clear();
                    else {
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
}

// [Phase 2] Listen for sidebar item click to focus map
window.addEventListener('sidebar-node-focus', (e: any) => {
    if (currentGlobalMap && e.detail.lat && e.detail.lng) {
        currentGlobalMap.setView([e.detail.lat, e.detail.lng], 5, { animate: true, duration: 0.5 });
    }
});
