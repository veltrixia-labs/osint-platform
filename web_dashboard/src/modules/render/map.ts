import L from 'leaflet';
import type { BackboneNode } from '../api';
import { fetchBackbone } from '../api';

let map: L.Map;
let layerGroup: L.LayerGroup;
let hoverLayerGroup: L.LayerGroup;

const markerByNodeName = new Map<string, L.Marker>();
let currentRenderedNodes: BackboneNode[] = [];

let selectedNodeNames = new Set<string>();
let popupOpenNodeName: string | null = null;

let activeBackboneSectors = new Set<string>(['all']);

export const renderMap = async (container: HTMLElement, _tier?: string, _focusAlertId?: string) => {
    if (!map) {
        container.innerHTML = `
            <div style="width:100%; height:100%; min-height:650px; position:relative;">
                <div id="map-filter" style="position:absolute; top:12px; left:12px; z-index:1000;"></div>
                <div style="display:flex; width:100%; height:100%; min-height:650px;">
                    <div id="map-instance" style="flex:1; min-height:650px;"></div>
                    <div id="map-node-list" style="
                        width:280px;
                        padding:10px;
                        background:rgba(10,14,20,0.92);
                        border-left:1px solid rgba(255,255,255,0.08);
                        overflow-y:auto;
                        font-size:12px;
                    "></div>
                </div>
            </div>
        `;

        map = L.map('map-instance', {
            zoomControl: false,
            worldCopyJump: true
        }).setView([20, 0], 2);

        L.control.zoom({
            position: 'bottomright'
        }).addTo(map);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap &copy; CARTO',
            subdomains: 'abcd',
            maxZoom: 20
        }).addTo(map);

        layerGroup = L.layerGroup().addTo(map);
        hoverLayerGroup = L.layerGroup().addTo(map);

        initMapFilter();

        map.on('zoomend', () => {
            if (popupOpenNodeName) return;
            renderBackboneMap();
        });
    }

    await renderBackboneMap();

    setTimeout(() => {
        map.invalidateSize();
    }, 100);
};

async function renderBackboneMap() {
    layerGroup.clearLayers();

    try {
        const allSectors = ['energy', 'market', 'crypto', 'ai', 'defense', 'trade'];

        const sectorsToLoad = activeBackboneSectors.has('all')
            ? allSectors
            : Array.from(activeBackboneSectors);

        const results = await Promise.all(
            sectorsToLoad.map(sector => fetchBackbone(sector))
        );

        renderBackboneNodes(results.flat());
        updateFilterButtonStates();
    } catch (e) {
        console.error('Failed to load backbone:', e);
    }
}

function renderBackboneNodes(nodes: BackboneNode[]) {
    currentRenderedNodes = nodes;
    markerByNodeName.clear();

    const nodeByName = new Map<string, BackboneNode>();

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

        const color = getBackboneSectorColor(node.sector);

        const isSelected = selectedNodeNames.has(node.name);

        const isDependencyTarget = Array.from(selectedNodeNames).some(name => {
            const selectedNode = nodeByName.get(name);
            return !!selectedNode?.top_dependencies?.some(dep => dep.target === node.name);
        });

        const zoom = map.getZoom();
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
            .addTo(layerGroup)
            .bindPopup(popup)
            .on('click', () => {
                if (!node.location) return;

                map.flyTo(
                    [node.location.lat, node.location.lng],
                    5, // ← ズームレベル（後で調整OK）
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

                renderBackboneMap();
            });
        });

        marker.on('popupclose', () => {
            if (popupOpenNodeName === node.name) {
                popupOpenNodeName = null;
            }
        });

        marker.on('mouseover', () => {
            hoverLayerGroup.clearLayers();

            if (selectedNodeNames.has(node.name)) return;

            renderSelectedDependencyLines(node, nodeByName, hoverLayerGroup, true);

            marker.getElement()
                ?.querySelector('.backbone-marker')
                ?.classList.add('backbone-marker--hover');
        });

        marker.on('mouseout', () => {
            hoverLayerGroup.clearLayers();

            marker.getElement()
                ?.querySelector('.backbone-marker')
                ?.classList.remove('backbone-marker--hover');
        });
    });

    renderNodeList(nodes);
}

function renderNodeList(nodes: BackboneNode[]) {
    const list = document.getElementById('map-node-list');
    if (!list) return;

    const groups = new Map<string, BackboneNode[]>();

    nodes.forEach(node => {
        const sector = node.sector || 'OTHER';
        if (!groups.has(sector)) groups.set(sector, []);
        groups.get(sector)!.push(node);
    });

    list.innerHTML = `
        <div style="font-weight:700; color:#fff; margin-bottom:8px;">
            Visible Entities
        </div>

        ${Array.from(groups.entries()).map(([sector, sectorNodes]) => `
            <div class="map-node-sector">
                <button class="map-node-sector-btn" data-sector="${sector}" style="--sector-color:${getBackboneSectorColor(sector)};">
                    <span>${sector}</span>
                    <span>${sectorNodes.length}</span>
                </button>

                <div class="map-node-sector-list" data-sector-list="${sector}" style="display:none;">
                    ${sectorNodes.map(node => `
                        <button class="map-node-list-item" data-node="${node.name}">
                            <span style="color:${getBackboneSectorColor(node.sector)};">●</span>
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

            if (!node?.location || !marker) return;

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
    selectedNode: BackboneNode,
    nodeByName: Map<string, BackboneNode>,
    targetLayer: L.LayerGroup = layerGroup,
    isPreview: boolean = false
) {
    if (!selectedNode.location) return;

    const color = getBackboneSectorColor(selectedNode.sector);

    (selectedNode.top_dependencies || []).slice(0, 5).forEach(dep => {
        let target = nodeByName.get(dep.target);

        // 完全一致しない場合のゆるい検索
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

function getBackboneSectorColor(sector: string): string {
    const key = sector.toUpperCase();

    if (key.includes('ENERGY')) return '#d29922';
    if (key.includes('MARKET')) return '#3fb950';
    if (key.includes('CRYPTO')) return '#f97316';
    if (key.includes('AI') || key.includes('TECH') || key.includes('SEMICONDUCTOR')) return '#bc8cff';
    if (key.includes('DEFENSE')) return '#ff4d6d';
    if (key.includes('TRADE') || key.includes('SUPPLY')) return '#79c0ff';

    return '#58a6ff';
}

function getStrengthColor(value: number): string {
    if (value >= 0.7) return '#ff6b6b'; // 赤
    if (value >= 0.4) return '#f1c40f'; // 黄
    return '#2ecc71'; // 緑
}

function initMapFilter() {
    const container = document.getElementById('map-filter');
    if (!container) return;

    const TOPICS = [
        { id: 'all', label: 'All', color: '#ffffff' },
        { id: 'energy', label: 'Energy', color: '#d29922' },
        { id: 'market', label: 'Market', color: '#3fb950' },
        { id: 'crypto', label: 'Crypto', color: '#f97316' },
        { id: 'ai', label: 'AI/Tech', color: '#bc8cff' },
        { id: 'defense', label: 'Defense', color: '#ff4d6d' },
        { id: 'trade', label: 'Trade', color: '#79c0ff' }
    ];

    container.innerHTML = TOPICS.map(t => `
        <button
            class="map-filter-btn ${activeBackboneSectors.has(t.id) ? 'active' : ''}"
            data-id="${t.id}"
            style="--filter-color:${t.color};"
        >
            ${t.label}
        </button>
    `).join('');

    container.querySelectorAll('.map-filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = (btn as HTMLElement).dataset.id!;

            if (id === 'all') {
                if (activeBackboneSectors.has('all')) {
                    activeBackboneSectors.clear();
                    activeBackboneSectors.add('energy');
                } else {
                    activeBackboneSectors.clear();
                    activeBackboneSectors.add('all');
                }
            } else {
                activeBackboneSectors.delete('all');

                if (activeBackboneSectors.has(id)) {
                    activeBackboneSectors.delete(id);
                } else {
                    activeBackboneSectors.add(id);
                }

                if (activeBackboneSectors.size === 0) {
                    activeBackboneSectors.add('all');
                }
            }

            renderBackboneMap();
        });
    });
}

function updateFilterButtonStates() {
    document.querySelectorAll('.map-filter-btn').forEach(btn => {
        const el = btn as HTMLElement;
        const id = el.dataset.id;
        if (!id) return;

        const isActive = activeBackboneSectors.has(id);
        el.classList.toggle('active', isActive);
    });
}