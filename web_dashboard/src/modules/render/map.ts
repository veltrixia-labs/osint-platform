import L from 'leaflet';
import type { BackboneNode } from '../api';
import { fetchBackbone } from '../api';
import {
    BACKBONE_API_BY_STRATEGIC,
    STRATEGIC_TOPIC_CODES,
    getTopicColor,
    getTopicDisplayLabel,
    normalizeTopicCode,
    strategicTopicFromBackboneApi,
    type StrategicTopicCode,
} from '../topics';
import {
    applyMobileMapLayout,
    getMapNodeListBody,
    wireMobileMapLayout,
} from './map_mobile_layout';

type TaggedBackboneNode = BackboneNode & { strategicCode: StrategicTopicCode };

/** Prefer API sector segment so crypto backbone rows never inherit MARKET from node.sector text. */
function tagNode(node: BackboneNode, apiSector?: string): TaggedBackboneNode {
    const strategicCode = apiSector
        ? strategicTopicFromBackboneApi(apiSector)
        : normalizeTopicCode(node.sector);
    return {
        ...node,
        strategicCode,
    };
}

let map: L.Map | undefined;
let layerGroup: L.LayerGroup | undefined;
let hoverLayerGroup: L.LayerGroup | undefined;

const markerByNodeName = new Map<string, L.Marker>();
let currentRenderedNodes: TaggedBackboneNode[] = [];

let selectedNodeNames = new Set<string>();
let popupOpenNodeName: string | null = null;

let activeStrategicFilters = new Set<'all' | StrategicTopicCode>(['all']);

let mapRenderGeneration = 0;
let mapRouteListenersBound = false;

const MAP_SHELL_HTML = `
    <div class="map-page-shell">
        <div id="map-filter" class="map-filter-bar" aria-label="Map topic filters"></div>
        <div class="map-page-shell__body">
            <div id="map-instance" class="map-instance-host" role="application" aria-label="Global strategic map"></div>
            <aside id="map-node-list" class="map-node-list-panel map-node-list-panel--collapsed" data-map-list-panel aria-label="Visible entities">
                <div class="map-node-list-panel__header">
                    <button type="button" class="map-node-list-panel__toggle" data-map-list-toggle aria-expanded="false" aria-controls="map-node-list-body">
                        <span class="map-node-list-panel__toggle-icon" aria-hidden="true">📊</span>
                        <span class="map-node-list-panel__toggle-label" data-map-list-toggle-label>+ Expand List</span>
                    </button>
                </div>
                <div id="map-node-list-body" class="map-node-list-panel__body" data-map-list-body hidden></div>
            </aside>
        </div>
    </div>
`;

function mapLoadingHtml(): string {
    return `
        <div class="map-page-loading" role="status" aria-live="polite" aria-busy="true">
            <div class="map-page-loading__grid" aria-hidden="true"></div>
            <div class="map-page-loading__scan" aria-hidden="true"></div>
            <p class="map-page-loading__label">Loading Global Map…</p>
            <p class="map-page-loading__hint">Synchronizing strategic entity backbone</p>
        </div>
    `;
}

function isMapHashActive(): boolean {
    const base = window.location.hash.slice(1).split('?')[0];
    return base === 'map';
}

function isMapContainerVisible(container: HTMLElement): boolean {
    if (container.style.display === 'none') return false;
    const rect = container.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
}

function isMapEngineHealthy(container: HTMLElement): boolean {
    const mapEl = container.querySelector('#map-instance');
    if (!map || !layerGroup || !hoverLayerGroup || !mapEl) return false;
    const mapWithContainer = map as L.Map & { _container?: HTMLElement };
    return mapWithContainer._container === mapEl;
}

/** Tear down Leaflet when dashboard DOM is replaced (login / full re-init). */
export function resetMapEngine(): void {
    mapRenderGeneration += 1;
    popupOpenNodeName = null;
    markerByNodeName.clear();
    currentRenderedNodes = [];

    if (map) {
        try {
            map.off();
            map.remove();
        } catch {
            /* detached container */
        }
    }
    map = undefined;
    layerGroup = undefined;
    hoverLayerGroup = undefined;
}

function showMapLoading(container: HTMLElement): void {
    container.classList.add('map-page-container--loading');
    container.innerHTML = mapLoadingHtml();
}

function scheduleMapInvalidate(): void {
    if (!map) return;
    const run = () => {
        try {
            map?.invalidateSize({ animate: false, pan: false });
        } catch {
            /* ignore */
        }
    };
    run();
    [50, 150, 350, 600].forEach(ms => window.setTimeout(run, ms));
}

async function waitForVisibleMapContainer(container: HTMLElement, maxMs = 900): Promise<void> {
    const started = performance.now();
    while (performance.now() - started < maxMs) {
        const mapEl = container.querySelector('#map-instance') as HTMLElement | null;
        if (mapEl && isMapContainerVisible(container) && mapEl.offsetWidth > 0 && mapEl.offsetHeight > 0) {
            return;
        }
        await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    }
}

async function ensureMapEngine(container: HTMLElement): Promise<L.Map> {
    if (isMapEngineHealthy(container)) {
        return map!;
    }

    if (map) {
        resetMapEngine();
    }

    container.innerHTML = MAP_SHELL_HTML;
    container.classList.remove('map-page-container--loading');

    await waitForVisibleMapContainer(container);

    const mapElement = container.querySelector('#map-instance');
    if (!mapElement) {
        throw new Error('Map mount point missing');
    }

    map = L.map(mapElement as HTMLElement, {
        zoomControl: false,
        worldCopyJump: true,
    }).setView([20, 0], 2);

    L.control.zoom({
        position: 'bottomright',
    }).addTo(map);

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap &copy; CARTO',
        subdomains: 'abcd',
        maxZoom: 20,
    }).addTo(map);

    layerGroup = L.layerGroup().addTo(map);
    hoverLayerGroup = L.layerGroup().addTo(map);

    initMapFilter();
    wireMobileMapLayout(container, scheduleMapInvalidate);

    map.on('zoomend', () => {
        if (popupOpenNodeName) return;
        void renderBackboneMap();
    });

    return map;
}

function bindMapRouteListeners(): void {
    if (mapRouteListenersBound) return;
    mapRouteListenersBound = true;

    let routeRefreshTimer: number | undefined;
    const refreshIfMapRoute = () => {
        if (!isMapHashActive()) return;
        const container = document.getElementById('map-page-container') as HTMLElement | null;
        if (!container || container.style.display === 'none') return;
        window.clearTimeout(routeRefreshTimer);
        routeRefreshTimer = window.setTimeout(() => {
            void renderMap(container);
        }, 120);
    };

    window.addEventListener('hashchange', refreshIfMapRoute);
    window.addEventListener('popstate', refreshIfMapRoute);
    window.addEventListener('pageshow', (ev: PageTransitionEvent) => {
        if (!ev.persisted) return;
        refreshIfMapRoute();
    });
}

export const renderMap = async (container: HTMLElement, _tier?: string, _focusAlertId?: string) => {
    bindMapRouteListeners();
    const generation = ++mapRenderGeneration;
    const needsShell = !isMapEngineHealthy(container);

    if (needsShell) {
        showMapLoading(container);
    } else {
        container.classList.add('map-page-container--loading');
    }

    try {
        await ensureMapEngine(container);
        if (generation !== mapRenderGeneration) return;

        await waitForVisibleMapContainer(container);
        if (generation !== mapRenderGeneration) return;

        await renderBackboneMap();
        if (generation !== mapRenderGeneration) return;

        const mapContainer = container;
        applyMobileMapLayout(mapContainer, scheduleMapInvalidate);
        scheduleMapInvalidate();
    } catch (e) {
        console.error('[Map] render failed:', e);
        if (generation !== mapRenderGeneration) return;
        container.innerHTML = `
            <div class="map-page-loading map-page-loading--error" role="alert">
                <p class="map-page-loading__label">Global Map unavailable</p>
                <p class="map-page-loading__hint">Could not initialize the map view. Retry in a moment.</p>
                <button type="button" class="map-page-loading__retry" data-map-retry>Retry</button>
            </div>
        `;
        container.querySelector('[data-map-retry]')?.addEventListener('click', () => {
            resetMapEngine();
            void renderMap(container, _tier, _focusAlertId);
        });
    } finally {
        if (generation === mapRenderGeneration) {
            container.classList.remove('map-page-container--loading');
        }
    }
};

async function renderBackboneMap() {
    if (!layerGroup || !map) return;

    const list = getMapNodeListBody();
    if (list) {
        list.innerHTML = '<div class="map-node-list-loading">Loading entities…</div>';
    }

    layerGroup.clearLayers();
    hoverLayerGroup?.clearLayers();

    try {
        const sectorsToLoad = activeStrategicFilters.has('all')
            ? STRATEGIC_TOPIC_CODES.map(code => BACKBONE_API_BY_STRATEGIC[code])
            : Array.from(activeStrategicFilters)
                .filter((id): id is StrategicTopicCode => id !== 'all')
                .map(code => BACKBONE_API_BY_STRATEGIC[code]);

        const results = await Promise.all(
            sectorsToLoad.map(async sector => {
                const nodes = await fetchBackbone(sector);
                return nodes.map(node => tagNode(node, sector));
            })
        );

        renderBackboneNodes(results.flat());
        updateFilterButtonStates();
    } catch (e) {
        console.error('Failed to load backbone:', e);
        if (list) {
            list.innerHTML = '<div class="map-node-list-loading map-node-list-loading--error">Failed to load entities.</div>';
        }
    }
}

function renderBackboneNodes(nodes: TaggedBackboneNode[]) {
    const activeMap = map;
    const activeLayerGroup = layerGroup;
    const activeHoverLayerGroup = hoverLayerGroup;
    if (!activeMap || !activeLayerGroup || !activeHoverLayerGroup) return;

    currentRenderedNodes = nodes;
    markerByNodeName.clear();

    const nodeByName = new Map<string, TaggedBackboneNode>();

    nodes.forEach(node => {
        nodeByName.set(node.name, node);
    });

    selectedNodeNames.forEach(name => {
        const selected = nodeByName.get(name);
        if (selected) {
            renderSelectedDependencyLines(selected, nodeByName);
        }
    });

    nodes.forEach(node => {
        if (!node.location) return;

        const color = getTopicColor(node.strategicCode);

        const isSelected = selectedNodeNames.has(node.name);

        const isDependencyTarget = Array.from(selectedNodeNames).some(name => {
            const selectedNode = nodeByName.get(name);
            return !!selectedNode?.top_dependencies?.some(dep => dep.target === node.name);
        });

        const zoom = activeMap.getZoom();
        const showLabel = zoom >= 6 || isSelected || isDependencyTarget;

        const icon = L.divIcon({
            className: 'backbone-node',
            html: `
                <div class="
                    backbone-marker
                    ${isSelected ? 'backbone-marker--selected' : ''}
                    ${isDependencyTarget ? 'backbone-marker--dependency' : ''}
                " style="--node-color:${color};">
                    <div class="backbone-marker-dot"></div>
                    ${showLabel ? `<span class="backbone-marker-label">${node.name}</span>` : ''}
                </div>
            `,
            iconSize: undefined,
            iconAnchor: [0, 12]
        });

        const deps = node.top_dependencies || [];
        const avgWeight = deps.length
            ? Math.round((deps.reduce((sum, d) => sum + d.weight, 0) / deps.length) * 100)
            : 0;

        const strongestDep = deps.length
            ? deps.reduce((max, d) => d.weight > max.weight ? d : max, deps[0])
            : null;

        const popup = `
            <div style="color:white;">
                <strong>${node.name}</strong><br/>
                <small>${node.country}</small>
                <p style="font-size:12px; opacity:0.7;">
                    ${node.description}
                </p>
                <div style="margin-top:10px; padding:8px; border:1px solid rgba(255,255,255,0.08); border-radius:6px; background:rgba(255,255,255,0.04);">
                    <div style="
                        font-size:11px;
                        font-weight:700;
                        color:#fff;
                        margin-bottom:6px;
                        letter-spacing:0.3px;
                    ">
                        Dependency Overview
                    </div>
                    <div style="font-size:11px; opacity:0.75;">
                        Top links: ${deps.length}<br/>
                        Avg strength: 
                        <span style="color:${getStrengthColor(avgWeight / 100)}; font-weight:700;">
                            ${avgWeight}%
                        </span><br/>
                        ${strongestDep ? `
                            Strongest:
                            <strong style="color:#fff;">
                                ${strongestDep.target}
                            </strong>
                            <span style="color:${getStrengthColor(strongestDep.weight)};">
                                (${Math.round(strongestDep.weight * 100)}%)
                            </span>
                        ` : ''}
                    </div>
                </div>
                <div style="font-size:11px; margin-top:6px;">
                <button class="dependency-toggle-btn" data-node="${node.name}">
                    ${selectedNodeNames.has(node.name) ? 'Hide Dependencies' : 'Show Dependencies'}
                </button>

                <div style="margin-top:6px;">
                    <strong>Dependencies</strong>
                </div>

                    ${(node.top_dependencies || []).slice(0, 3).map(d => `
                        <div style="margin-top:3px; opacity:0.85;">
                            ${d.target} (${Math.round(d.weight * 100)}%)
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        const marker = L.marker([node.location.lat, node.location.lng], { icon })
            .addTo(activeLayerGroup)
            .bindPopup(popup)
            .on('click', () => {
                if (!node.location) return;

                activeMap.flyTo(
                    [node.location.lat, node.location.lng],
                    5,
                    {
                        duration: 0.8,
                        easeLinearity: 0.25
                    }
                );
            });

        markerByNodeName.set(node.name, marker);

        marker.on('popupopen', () => {
            popupOpenNodeName = node.name;

            const btn = document.querySelector(
                `.dependency-toggle-btn[data-node="${CSS.escape(node.name)}"]`
            ) as HTMLButtonElement | null;

            if (!btn) return;

            btn.addEventListener('click', (e) => {
                e.stopPropagation();

                if (selectedNodeNames.has(node.name)) {
                    selectedNodeNames.delete(node.name);
                } else {
                    selectedNodeNames.add(node.name);
                }

                void renderBackboneMap();
            });
        });

        marker.on('popupclose', () => {
            if (popupOpenNodeName === node.name) {
                popupOpenNodeName = null;
            }
        });

        marker.on('mouseover', () => {
            activeHoverLayerGroup.clearLayers();

            if (selectedNodeNames.has(node.name)) return;

            renderSelectedDependencyLines(node, nodeByName, activeHoverLayerGroup, true);

            marker.getElement()
                ?.querySelector('.backbone-marker')
                ?.classList.add('backbone-marker--hover');
        });

        marker.on('mouseout', () => {
            activeHoverLayerGroup.clearLayers();

            marker.getElement()
                ?.querySelector('.backbone-marker')
                ?.classList.remove('backbone-marker--hover');
        });
    });

    renderNodeList(nodes);
}

function renderNodeList(nodes: TaggedBackboneNode[]) {
    const list = getMapNodeListBody();
    if (!list) return;

    const groups = new Map<StrategicTopicCode, TaggedBackboneNode[]>();
    for (const code of STRATEGIC_TOPIC_CODES) {
        groups.set(code, []);
    }
    nodes.forEach(node => {
        const bucket = groups.get(node.strategicCode);
        if (bucket) {
            bucket.push(node);
        } else {
            groups.get('MARKET')!.push(node);
        }
    });

    const visibleGroups = STRATEGIC_TOPIC_CODES.map(
        code => [code, groups.get(code) ?? []] as const
    );

    list.innerHTML = `
        <div style="font-weight:700; color:#fff; margin-bottom:8px;">
            Visible Entities
        </div>

        ${visibleGroups.map(([code, sectorNodes]) => `
            <div class="map-node-sector ${sectorNodes.length === 0 ? 'map-node-sector--empty' : ''}">
                <button class="map-node-sector-btn" data-sector="${code}" style="--sector-color:${getTopicColor(code)};">
                    <span>${getTopicDisplayLabel(code)}</span>
                    <span class="map-node-sector-count">${sectorNodes.length}</span>
                </button>

                <div class="map-node-sector-list" data-sector-list="${code}" style="display:none;">
                    ${sectorNodes.map(node => `
                        <button class="map-node-list-item" data-node="${node.name}">
                            <span style="color:${getTopicColor(node.strategicCode)};">●</span>
                            ${node.name}
                        </button>
                    `).join('')}
                </div>
            </div>
        `).join('')}
    `;

    list.querySelectorAll('.map-node-sector-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const sector = (btn as HTMLElement).dataset.sector!;
            const target = list.querySelector(
                `.map-node-sector-list[data-sector-list="${CSS.escape(sector)}"]`
            ) as HTMLElement | null;

            if (!target) return;

            target.style.display = target.style.display === 'none' ? 'block' : 'none';
        });
    });

    list.querySelectorAll('.map-node-list-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const name = (btn as HTMLElement).dataset.node!;
            const node = currentRenderedNodes.find(n => n.name === name);
            const marker = markerByNodeName.get(name);

            if (!node?.location || !marker || !map) return;

            map.flyTo([node.location.lat, node.location.lng], 6, {
                duration: 0.8,
                easeLinearity: 0.25
            });

            setTimeout(() => {
                marker.openPopup();
            }, 600);
        });
    });
}

function renderSelectedDependencyLines(
    selectedNode: TaggedBackboneNode,
    nodeByName: Map<string, TaggedBackboneNode>,
    targetLayer: L.LayerGroup = layerGroup!,
    isPreview: boolean = false
) {
    if (!selectedNode.location || !targetLayer) return;

    const color = getTopicColor(selectedNode.strategicCode);

    (selectedNode.top_dependencies || []).slice(0, 5).forEach(dep => {
        let target = nodeByName.get(dep.target);

        if (!target) {
            target = Array.from(nodeByName.values()).find(n =>
                n.name.toLowerCase().includes(dep.target.toLowerCase()) ||
                dep.target.toLowerCase().includes(n.name.toLowerCase())
            );
        }

        if (!target || !target.location) {
            console.warn("Dependency target not found:", dep.target);
            return;
        }

        const weight = dep.weight ?? 0.5;

        L.polyline(
            [
                [selectedNode.location.lat, selectedNode.location.lng],
                [target.location.lat, target.location.lng]
            ],
            {
                color,
                weight: Math.max(3, weight * 6),
                opacity: 0.9,
                interactive: false,
                className: isPreview
                    ? 'dependency-line dependency-line--preview'
                    : 'dependency-line dependency-line--active'
            }
        ).addTo(targetLayer);
    });
}

function getStrengthColor(value: number): string {
    if (value >= 0.7) return '#ff6b6b';
    if (value >= 0.4) return '#f1c40f';
    return '#2ecc71';
}

function initMapFilter() {
    const container = document.getElementById('map-filter');
    if (!container) return;

    const FILTER_IDS: readonly ('all' | StrategicTopicCode)[] = ['all', ...STRATEGIC_TOPIC_CODES];

    container.innerHTML = FILTER_IDS.map(id => {
        const color = id === 'all' ? '#ffffff' : getTopicColor(id);
        const label = id === 'all' ? 'All' : getTopicDisplayLabel(id);
        return `
        <button
            class="map-filter-btn ${activeStrategicFilters.has(id) ? 'active' : ''}"
            data-id="${id}"
            style="--filter-color:${color};"
        >
            ${label}
        </button>`;
    }).join('');

    container.querySelectorAll('.map-filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = (btn as HTMLElement).dataset.id! as 'all' | StrategicTopicCode;

            if (id === 'all') {
                if (activeStrategicFilters.has('all')) {
                    activeStrategicFilters.clear();
                    activeStrategicFilters.add('ENERGY');
                } else {
                    activeStrategicFilters.clear();
                    activeStrategicFilters.add('all');
                }
            } else {
                activeStrategicFilters.delete('all');

                if (activeStrategicFilters.has(id)) {
                    activeStrategicFilters.delete(id);
                } else {
                    activeStrategicFilters.add(id);
                }

                if (activeStrategicFilters.size === 0) {
                    activeStrategicFilters.add('all');
                }
            }

            void renderBackboneMap();
        });
    });
}

function updateFilterButtonStates() {
    document.querySelectorAll('.map-filter-btn').forEach(btn => {
        const el = btn as HTMLElement;
        const id = el.dataset.id as 'all' | StrategicTopicCode | undefined;
        if (!id) return;

        const isActive = activeStrategicFilters.has(id);
        el.classList.toggle('active', isActive);
    });
}
