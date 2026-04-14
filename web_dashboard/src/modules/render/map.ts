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
let lastDiscoveryTrigger: number = 0;
let currentGlobalMap: L.Map | null = null;
let currentDynamicLayer: L.LayerGroup | null = null;
let clusterLayer: L.MarkerClusterGroup | null = null;
let isRendering = false; // Mutex to prevent infinite recursion
let _isTacticalDiscoveryActive = false; // [v10.8] Critical Polling Lock
let _activeDiscoveryId: string | null = null; // [v10.9] Sticky State Guard

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
        
        // [v10.9] ID Switch Guard: If the focus ID has changed, we MUST break the lock
        if (focusAlertId && focusAlertId !== _activeDiscoveryId) {
            console.log(`[Antigravity] Focus Shift: ${_activeDiscoveryId} -> ${focusAlertId}. Resetting lock.`);
            _isTacticalDiscoveryActive = false;
        }

        if (focusAlertId && _isTacticalDiscoveryActive && !isReTrigger) {
            console.log("[Antigravity] Discovery Active - Skipping polling re-render to preserve narrative.");
            isRendering = false;
            return;
        }

        // [v10.8] Manual Reset: If switching to Global View, ensure lock is released
        if (!focusAlertId) {
            _isTacticalDiscoveryActive = false;
            _activeDiscoveryId = null;
        }
        
        // Sync trigger state
        if (isReTrigger) {
            lastDiscoveryTrigger = (window as any)._mapTriggerTimestamp;
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

/**
 * [v10.8] Displays a tactical status indicator on the map during discovery.
 */
function renderTacticalStatusHud(_layer: L.LayerGroup, text: string) {
    const hudId = 'tactical-discovery-hud';
    const existing = document.getElementById(hudId);
    if (existing) existing.remove();

    const HUD_HTML = `
        <div class="hud-inner">
            <span class="hud-pulse"></span>
            <span class="hud-text">${text}</span>
        </div>
    `;

    const hud = L.DomUtil.create('div', 'tactical-status-hud', document.getElementById('map-instance') || undefined);
    hud.id = hudId;
    hud.innerHTML = HUD_HTML;
    
    // [v10.9] Visual Variants
    if (text.includes('ENHANCING')) hud.classList.add('enhancing');
    
    setTimeout(() => hud.classList.add('active'), 100);
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
    let rawCoords = getAlertCoords(alert);
    
    // [v10.12] Geographic Fallback: If no explicit coords, use first Strategic Asset for topic
    if (!rawCoords && alert.topic) {
        const topicAsset = STRATEGIC_ASSETS.find(a => a.topic_code === alert.topic);
        if (topicAsset) {
            rawCoords = { lat: topicAsset.lat, lng: topicAsset.lng, source: 'Topic-Asset-Fallback' };
            console.log(`[Antigravity] No Alert coords. Falling back to Topic Asset: ${topicAsset.name}`);
        }
    }

    if (!rawCoords) {
        console.error(`[Antigravity] Map Engine Halt: Could not resolve coordinates for ${alert.id}`);
        return;
    }

    const coords = { lat: Number(rawCoords.lat), lng: Number(rawCoords.lng) };

    _isTacticalDiscoveryActive = true; 
    _activeDiscoveryId = alert.id;
    
    const intensity = alert.intensity || 5;
    const topicDef = getTopicDef(alert.topic);
    const topicColor = topicDef?.color || '#58a6ff';

    renderTacticalStatusHud(layer, "SYNCING GLOBAL POSITION...");
    console.log(`[Antigravity] Narrative Start: ${alert.target_label} @ ${coords.lat},${coords.lng} (Src: ${rawCoords.source})`);

    // [v10.16.2] Origin Card: No symbols (A/B), just the facts.
    const alertFinding = {
        entity_name: alert.target_label || "Active Event",
        impact_summary: alert.description || alert.target_label || "Strategic Signal Detected",
        impact_alpha: alert.intensity || 5
    };
    renderTacticalNodeLabel(layer, [coords.lat, coords.lng], alertFinding, topicColor, 1, 0, 1);

    // [v10.12] Modern API Path (Top-level) vs Legacy Path (Nested)
    const cascadingImpactsRaw = alert.cascading_impacts || alert.metadata_json?.cascading_impacts || [];
    let cascadingImpacts = [...cascadingImpactsRaw];

    // [v10.21] BACKBONE-DRIVEN FALLBACK
    // If cascading_impacts is empty, trigger on-demand AI analysis via the backbone DB.
    // This replaces the old static STRATEGIC_ASSETS fallback with live DB-driven impact discovery.
    if (cascadingImpacts.length === 0) {
        // [v10.32] RESTORATION: Instant Static Render (Wave 1)
        const currentStatus = alert.backbone_discovery_status || 'idle';
        console.log(`[Antigravity] Backbone State Check for ${alert.id}: ${currentStatus}`);

        // Ensure the backbone appears immediately while AI deep-dives in background.
        const rawTopic = alert.topic || (alert.metadata_json as any)?.topic;
        const topicMap: Record<string, string> = {
            'market': 'global_market_intelligence', 'energy': 'energy_resource_risk',
            'tech': 'ai_semiconductor_intelligence', 'defense': 'defense_technology',
            'supply_chain': 'supply_chain_intelligence', 'crypto': 'crypto_geopolitics'
        };
        const effectiveTopic = topicMap[rawTopic || ''] || rawTopic;
        if (effectiveTopic) {
            const relatedAssets = STRATEGIC_ASSETS.filter(a => a.topic_code === effectiveTopic && a.importance >= 0.85);
            const staticFallback = relatedAssets.slice(0, 3).map(asset => ({
                stakeholder_id: asset.id, entity_name: asset.name, impact_alpha: -2.5,
                source: 'static_fallback', reasoning: `Strategic risk synchronization with ${asset.name}.`,
                location_lat: asset.lat, location_lng: asset.lng
            }));
            if (staticFallback.length > 0) {
                renderImpactChain(map, layer, coords, staticFallback, 2, intensity, alert);
                // initial HUD set happens inside startPoller or analyze fetch
            }
        }

        const hasDirectImpacts = alert.cascading_impacts && alert.cascading_impacts.length > 0;
        const hasMetaImpacts = (alert.metadata_json as any)?.cascading_impacts?.length > 0;
        
        if (currentStatus === 'complete' && (hasDirectImpacts || hasMetaImpacts)) {
            const finalImpacts = alert.cascading_impacts || (alert.metadata_json as any).cascading_impacts;
            // Already analyzed proactively, just draw.
            layer.clearLayers();
            renderTacticalNodeLabel(layer, [coords.lat, coords.lng], alertFinding, topicColor, 1, 0, 1);
            renderImpactChain(map, layer, coords, finalImpacts, 2, intensity, alert);
            return;
        }

        // Start Poller immediately if already processing or starting
        const startPoller = (initialMsg: string) => {
            renderTacticalStatusHud(layer, initialMsg);
            let pollCount = 0;
            const poller = setInterval(() => {
                pollCount++;
                if (pollCount > 36) { clearInterval(poller); return; }
                renderTacticalStatusHud(layer, `AI REFINING [${pollCount}/36]...`);
                fetch(`/api/alerts/${alert.id}`)
                    .then(r => r.json())
                    .then(data => {
                        if (data.backbone_discovery_status === 'complete' && (data.cascading_impacts?.length > 0 || data.metadata_json?.cascading_impacts?.length > 0)) {
                            clearInterval(poller);
                            const updatedImpacts = data.cascading_impacts || data.metadata_json.cascading_impacts;
                            console.log(`[Antigravity] AI Enrichment Received. Upgrading map nodes...`);
                            renderTacticalStatusHud(layer, "BACKBONE ANALYTICS: OPTIMIZED");
                            layer.clearLayers();
                            renderTacticalNodeLabel(layer, [coords.lat, coords.lng], alertFinding, topicColor, 1, 0, 1);
                            renderImpactChain(map, layer, coords, updatedImpacts, 2, intensity, alert);
                            setTimeout(() => {
                                const hud = document.getElementById('tactical-discovery-hud');
                                if (hud) {
                                    hud.classList.remove('active');
                                    setTimeout(() => hud.remove(), 500);
                                }
                            }, 5000);
                        }
                    });
            }, 5000);
        };

        if (currentStatus === 'processing') {
            console.log(`[Antigravity] Analysis already running (Proactive). Joining task...`);
            startPoller("AI REFINING: JOINING PROACTIVE TASK...");
            return;
        }

        // Only if IDLE, trigger the upgrade
        fetch(`/api/alerts/${alert.id}/analyze`, { method: 'POST' })
            .then(r => r.json())
            .then(result => {
                if (result.status === 'processing' || result.status === 'success') {
                    console.log(`[Antigravity] Backbone analysis initiated: ${result.message}`);
                    startPoller("AI REFINING: REQUESTING BACKBONE UPGRADE...");
                }
            })
            .catch(err => {
                console.warn("[Antigravity] Background analysis trigger warning:", err);
            });
    }

    // [v10.8] Guaranteed Pipeline: Don't rely solely on flaky 'moveend'
    setTimeout(() => {
        map.flyTo([coords.lat, coords.lng], 4, { duration: 1.5 });
        
        const startNarrative = () => {
             const currentHud = document.getElementById('tactical-discovery-hud');
             if (currentHud) {
                // If we aren't in backbone analysis mode, transition to tracing
                if (currentHud.innerText.includes("POSITION")) {
                    renderTacticalStatusHud(layer, "TRACING CASCADE VECTORS...");
                }
                
                // [v10.16.2] Branch from Level 1 (Alert) to Level 2 (Order 1 Findings)
                // Only render immediately if pre-computed impacts exist (backbone analysis runs async above)
                if (cascadingImpacts.length > 0) {
                    renderImpactChain(map, layer, coords, cascadingImpacts, 2, intensity, alert);
                }
                
                // Auto-dismiss HUD after 12s (extended to allow backbone analysis to complete)
                setTimeout(() => {
                    const hud = document.getElementById('tactical-discovery-hud');
                    if (hud) {
                        hud.classList.remove('active');
                        setTimeout(() => hud.remove(), 500);
                    }
                }, 12000);
             }
        };

        map.once('moveend', startNarrative);
        setTimeout(startNarrative, 3000); // Safety fallback

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

/**
 * [v10.14] High-Fidelity Tactical Card.
 * Includes vertical offset for collision avoidance.
 */
function renderTacticalNodeLabel(layer: L.LayerGroup, latLng: [number, number], finding: any, _color: string, level: number, index: number, total: number) {
    const impactSummary = finding.impact_summary || finding.reasoning?.split('.')[0]?.slice(0, 80) || 'Strategic Impact Detected';
    
    // [v10.19] Sentiment-driven color: positive = blue, negative = red
    const alpha = finding.impact_alpha ?? 0;
    const sentimentColor = alpha >= 0 ? '#388bfd' : '#ff7b72';
    const alphaFormatted = `${alpha >= 0 ? '+' : ''}${alpha.toFixed(1)}%`;
    const sentimentClass = alpha >= 0 ? 'sentiment-positive' : 'sentiment-negative';

    // Smart Radial Placement
    const distance = 95; 
    const angleStep = (2 * Math.PI) / Math.max(1, total);
    const angle = (index * angleStep) - (Math.PI / 4);
    const xOffset = Math.cos(angle) * distance;
    const yOffset = Math.sin(angle) * distance;

    const isOrigin = level === 1;
    const initialClass = isOrigin ? 'expanded' : 'collapsed';

    // Quantum metrics
    const resilience = finding.quantum_metrics?.resilience?.toFixed(1) ?? '50.0';
    const contagion = finding.quantum_metrics?.contagion?.toFixed(2) ?? '0.30';
    const metricsSource = finding.quantum_metrics?.metrics_source ?? 'probabilistic_estimation';
    const metricsLabel = metricsSource === 'graph_tensor' ? '📊 Graph Tensor' : 
                         metricsSource === 'sector_baseline' ? '📐 Sector Baseline' : '🔢 Estimated';

    const icon = L.divIcon({
        className: 'none',
        html: `
            <div id="tnode-${finding.stakeholder_id || index}-${level}" 
                 class="tactical-node-wrapper ${initialClass} ${sentimentClass}" 
                 style="--node-color: ${sentimentColor}; --x-off: ${xOffset}px; --y-off: ${yOffset}px">
                
                <div class="tactical-node-trigger">
                    <div class="node-type-dot"></div>
                    <div class="node-name-mini">${finding.entity_name || 'Node'}</div>
                </div>

                <div class="node-label-inner card-high-fidelity">
                    <div class="node-label-header">
                        <span class="node-type-dot"></span>
                        <span class="node-name">${finding.entity_name || 'Strategic Hub'}</span>
                        <span class="node-time-tag">${finding.time_to_impact || 'Immediate'}</span>
                    </div>

                    <div class="node-impact-summary">${impactSummary}</div>

                    <!-- [v10.19] Quantum Metrics Grid with source label -->
                    <div class="node-metrics-grid">
                        <div class="metric-item">
                            <span class="metric-label">Resilience (Ω)</span>
                            <span class="metric-value">${resilience}%</span>
                        </div>
                        <div class="metric-item">
                            <span class="metric-label">Contagion (ΔC)</span>
                            <span class="metric-value">${contagion}</span>
                        </div>
                    </div>
                    <div class="metrics-source-tag">${metricsLabel}</div>

                    <!-- [v10.18] Tactical Recommendation -->
                    <div class="node-action-container">
                        <div class="action-header">CONTAINMENT ACTION</div>
                        <div class="action-text">${finding.containment_action || 'Monitor for volatility spillover.'}</div>
                    </div>

                    <div class="node-footer">
                        <span class="node-level-tag">${isOrigin ? 'ORIGIN' : `ORDER ${level - 1}`}</span>
                        <span class="node-impact-alpha">${alphaFormatted}</span>
                    </div>
                </div>
            </div>
        `,
        iconSize: [240, 140],
        iconAnchor: [120, 70] 
    });

    const marker = L.marker(latLng, { 
        icon, 
        interactive: true,
        pane: 'vlt-tactical-pane' 
    }).addTo(layer);

    marker.on('click', (e) => {
        L.DomEvent.stopPropagation(e);
        const el = document.getElementById(`tnode-${finding.stakeholder_id || index}-${level}`);
        if (el) {
            const isExpanding = el.classList.contains('collapsed');
            
            if (isExpanding) {
                document.querySelectorAll('.tactical-node-wrapper.expanded').forEach(other => {
                    if (other.id !== el.id && !other.classList.contains('origin-permanent')) {
                       other.classList.remove('expanded');
                       other.classList.add('collapsed');
                    }
                });
            }
            el.classList.toggle('collapsed');
            el.classList.toggle('expanded');
        }
    });

    if (isOrigin) {
        marker.getElement()?.classList.add('origin-permanent');
    }
}

function renderImpactChain(map: L.Map, layer: L.LayerGroup, parentCoords: {lat: number, lng: number}, impacts: any[], level: number, baseIntensity: number, originalAlert: Alert) {
    if (level > 4 || !impacts || impacts.length === 0) {
        if (level > 1) setTimeout(() => renderTacticalStatusHud(layer, "CASCADING ANALYSIS COMPLETE"), 2000);
        return;
    }

    // [v10.14] Staggered Wave Propagation
    impacts.forEach((finding, index) => {
        const branchDelay = index * 350; // Simultaneous-but-staggered fan-out

        setTimeout(() => {
            try {
                let nodeCoords = getNodeCoords(finding);
                
                // [v10.27] Strict Validation: If coordinates remain invalid after all fallbacks, skip this branch
                if (!nodeCoords || isNaN(nodeCoords.lat) || isNaN(nodeCoords.lng)) {
                    console.warn(`[Antigravity] Skipping node rendering: Invalid coordinates for ${finding.entity_name}`);
                    return;
                }

                // [v9.10] Coordinate Resolution Fallback
                if (!nodeCoords && finding.entity_name) {
                    const asset = STRATEGIC_ASSETS.find(a => 
                        a.name.toLowerCase().includes(finding.entity_name.toLowerCase()) ||
                        finding.entity_name.toLowerCase().includes(a.name.toLowerCase())
                    );
                    if (asset) nodeCoords = { lat: asset.lat, lng: asset.lng, source: 'Name-Lookup' };
                }

                const pathColor = (finding.impact_alpha || 0) < 0 ? '#f43f5e' : '#10b981';

                // [v10.16] RESTORED CORE FLOW: Source node is NOT suppressed.
                // We draw lines from Alert (A) -> Finding 1 (B, C, D) -> Finding 2
                
                if (!nodeCoords) {
                    renderTacticalRipple(layer, L.latLng(parentCoords.lat, parentCoords.lng), pathColor, level);
                    nodeCoords = { lat: parentCoords.lat, lng: parentCoords.lng, source: 'Abstract-Carryover' };
                } else {
                    const start = L.latLng(parentCoords.lat, parentCoords.lng);
                    const end = L.latLng(nodeCoords.lat, nodeCoords.lng);
                    
                    // Don't draw arc if it's the exact same spot (rare but possible if LLM recurses on same entity)
                    const distance = L.latLng(start).distanceTo(end);
                    if (distance > 1000) {
                        const points: L.LatLng[] = [];
                        const steps = Math.max(30, Math.min(60, Math.floor(distance / 50000)));
                        
                        const dLat = end.lat - start.lat;
                        const dLng = end.lng - start.lng;
                        const dist = Math.sqrt(dLat*dLat + dLng*dLng);
                        
                        const offsetBase = (0.15 + (Math.min(dist, 40) / 200)) * (1.0 - (level - 1) * 0.2);
                        const siblingOffset = (index % 2 === 0 ? 0.08 : -0.08) * (index + 1);
                        const offsetFactor = offsetBase + siblingOffset;

                        const cpLat = (start.lat + end.lat) / 2 - dLng * offsetFactor;
                        const cpLng = (start.lng + end.lng) / 2 + dLat * offsetFactor;

                        for (let i = 0; i <= steps; i++) {
                            const t = i / steps;
                            const lat = (1-t)**2 * start.lat + 2*(1-t)*t * cpLat + t**2 * end.lat;
                            const lng = (1-t)**2 * start.lng + 2*(1-t)*t * cpLng + t**2 * end.lng;
                            points.push(L.latLng(lat, lng));
                        }

                        const arc = L.polyline(points, {
                            className: `propagation-arc-curved`,
                            color: pathColor,
                            weight: 3.5,
                            opacity: 0.8,
                            smoothFactor: 1.5,
                            interactive: false,
                            pane: 'vlt-arc-pane'  // [v10.19] Arc stays in lower pane
                        }).addTo(layer);

                        setTimeout(() => {
                            const el = arc.getElement() as HTMLElement;
                            if (el) el.style.setProperty('--ring-color', pathColor);
                        }, 50);
                    }

                    if (level === 2 && index === 0) {
                        const centerPoint = L.latLng((start.lat + end.lat)/2, (start.lng + end.lng)/2);
                        map.panTo(centerPoint, { animate: true, duration: 1.2 });
                    }
                }

                // Wave Arrival Narrative
                const arrivalDelay = 1200; 
                setTimeout(() => {
                    const baseSize = 10;
                    const markerClass = `marker-ring-tactical marker-ring-tactical--l${Math.min(level, 3)} node-ignite`;
                    const nodeIcon = L.divIcon({
                        className: 'none',
                        html: `<div class="${markerClass}" style="width:${baseSize}px; height:${baseSize}px; --ring-color:${pathColor}"><div class="glow-ring"></div></div>`,
                        iconSize: [baseSize, baseSize],
                        iconAnchor: [baseSize/2, baseSize/2]
                    });

                    L.marker([nodeCoords!.lat, nodeCoords!.lng], { icon: nodeIcon, pane: 'vlt-tactical-pane' }).addTo(layer);

                    const entityName = finding.entity_name || 'Strategic Node';
                    console.log(`[Antigravity] Map Node Arrival: ${entityName} (Level ${level})`);
                    if (finding.quantum_metrics) {
                        console.log(`[Antigravity] Quantum baseline for ${entityName}:`, finding.quantum_metrics);
                    }

                    renderTacticalNodeLabel(layer, [nodeCoords!.lat, nodeCoords!.lng], finding, pathColor, level, index, impacts.length);
                    renderTacticalStatusHud(layer, `WAVE ${level - 1}: ANALYZING ${entityName.toUpperCase()}...`);

                    // Branching Recursion: Sync level increment (Alert=1, Order1=2, Order2=3...)
                    const subImpacts = finding.cascading_impacts || (finding.metadata_json as any)?.cascading_impacts;
                    if (subImpacts && subImpacts.length > 0 && level < 3) {
                        console.log(`[Antigravity] Propagating Wave ${level}...`);
                        setTimeout(() => {
                           renderImpactChain(map, layer, nodeCoords!, subImpacts, level + 1, baseIntensity, originalAlert);
                        }, 500); 
                    }
                }, arrivalDelay);

            } catch (e) {
                console.error("[v10.14] Branch fault:", e);
            }
        }, branchDelay);
    });
}

function initMapFilter(map: L.Map, _container: HTMLElement, onUpdate: () => void) {
    if (currentFilterControl) currentFilterControl.remove();

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
