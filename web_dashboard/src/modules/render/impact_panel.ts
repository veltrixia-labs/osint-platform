import type { Alert } from '../api';
import { getTopicDef } from '../topics';

/**
 * Initializes and manages the Strategic Impact Sidebar.
 * This panel provides a deep, filterable view of cascading impacts 
 * without cluttering the spatial map canvas.
 */

let activeSort: 'severity' | 'sector' | 'order' = 'severity';

export function renderImpactSidebar(containerId: string, alert: Alert, mapInstance: L.Map) {
    const container = document.getElementById(containerId);
    if (!container) return;

    // Show container
    container.style.display = 'flex';
    container.style.flexDirection = 'column';

    const currentStatus = alert.backbone_discovery_status || 'idle';
    const rawImpacts = alert.cascading_impacts || (alert.metadata_json as any)?.cascading_impacts || [];
    
    // Sort logic (Non-destructive)
    let impacts = [...rawImpacts];
    if (activeSort === 'severity') {
        impacts.sort((a, b) => Math.abs(b.impact_alpha || 0) - Math.abs(a.impact_alpha || 0));
    } else if (activeSort === 'sector') {
        impacts.sort((a, b) => (a.sector || '').localeCompare(b.sector || ''));
    } else if (activeSort === 'order') {
        impacts.sort((a, b) => (a.order || a.level || 0) - (b.order || b.level || 0));
    }

    const color = getTopicDef(alert.topic)?.color || '#58a6ff';

    const headerHtml = `
        <div class="impact-panel-header" style="border-bottom: 2px solid ${color}; padding: 1rem;">
            <div style="font-size: 0.65rem; color: #8b949e; letter-spacing: 1px; margin-bottom: 4px;">STRATEGIC CHAIN</div>
            <h3 style="margin: 0; font-size: 1rem; color: #c9d1d9;">${alert.target_label || 'Active Event'}</h3>
            
            <div style="display: flex; justify-content: space-between; margin-top: 1rem; font-size: 0.75rem;">
                <div style="padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.05); color: ${currentStatus === 'complete' ? '#3fb950' : (currentStatus === 'failed' ? '#f85149' : '#58a6ff')}">
                    ${currentStatus === 'complete' ? 'ANALYSIS COMPLETE' : (currentStatus === 'failed' ? 'ANALYSIS FAILED' : 'ANALYZING...')}
                </div>
                <div style="color: #8b949e;">${impacts.length} NODES</div>
            </div>

            ${impacts.length > 0 ? `
            <div class="impact-panel-filters" style="display: flex; gap: 8px; margin-top: 1rem;">
                <button class="sort-btn ${activeSort === 'severity' ? 'active' : ''}" data-sort="severity" style="flex:1; padding:4px; font-size:0.7rem; background: ${activeSort === 'severity' ? 'rgba(255,255,255,0.1)' : 'transparent'}; border: 1px solid rgba(255,255,255,0.1); color: #c9d1d9; cursor: pointer; border-radius: 4px;">Severity</button>
                <button class="sort-btn ${activeSort === 'sector' ? 'active' : ''}" data-sort="sector" style="flex:1; padding:4px; font-size:0.7rem; background: ${activeSort === 'sector' ? 'rgba(255,255,255,0.1)' : 'transparent'}; border: 1px solid rgba(255,255,255,0.1); color: #c9d1d9; cursor: pointer; border-radius: 4px;">Sector</button>
                <button class="sort-btn ${activeSort === 'order' ? 'active' : ''}" data-sort="order" style="flex:1; padding:4px; font-size:0.7rem; background: ${activeSort === 'order' ? 'rgba(255,255,255,0.1)' : 'transparent'}; border: 1px solid rgba(255,255,255,0.1); color: #c9d1d9; cursor: pointer; border-radius: 4px;">Order</button>
            </div>
            ` : ''}
        </div>
    `;

    let bodyHtml = `<div class="impact-panel-body" style="flex: 1; overflow-y: auto; padding: 1rem; display: flex; flex-direction: column; gap: 12px;">`;

    if (impacts.length === 0) {
        bodyHtml += `
            <div style="text-align: center; padding: 2rem 0; color: #8b949e; opacity: 0.6;">
                <div style="font-size: 2rem; margin-bottom: 0.5rem;">${currentStatus === 'failed' ? '⚠️' : '⚡'}</div>
                <div style="font-size: 0.8rem;">${currentStatus === 'processing' ? 'Loading Findings...' : (currentStatus === 'failed' ? 'Analysis Failed' : 'No cascaded impacts detected.')}</div>
            </div>
        `;
    } else {
        impacts.forEach(finding => {
            const alpha = finding.impact_alpha ?? 0;
            const alphaFormatted = `${alpha >= 0 ? '+' : ''}${alpha.toFixed(1)}%`;
            const sentimentColor = alpha >= 0 ? '#3fb950' : '#f85149';
            const shortSummary = finding.impact_summary || finding.reasoning?.split('.')[0]?.slice(0, 100) || 'Strategic Impact Detected';
            const nodeId = finding.entity_name?.replace(/\\s+/g, '-');

            const latAttr = (finding as any)._rendered_lat || finding.lat || '';
            const lngAttr = (finding as any)._rendered_lng || finding.lng || '';

            const level = finding.order || finding.level || 1;
            const sector = finding.sector || 'Resource';

            bodyHtml += `
                <div class="sidebar-item" data-id="${nodeId}" data-lat="${latAttr}" data-lng="${lngAttr}" style="background: rgba(13, 17, 23, 0.4); border: 1px solid rgba(255,255,255,0.05); padding: 12px; border-radius: 8px; cursor: pointer; transition: all 0.2s; position: relative; overflow: hidden; backdrop-filter: blur(8px);" onmouseover="this.style.background='rgba(88, 166, 255, 0.05)'; this.style.borderColor='rgba(88, 166, 255, 0.2)'" onmouseout="this.style.background='rgba(13, 17, 23, 0.4)'; this.style.borderColor='rgba(255,255,255,0.05)'">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
                        <span style="font-weight: 800; font-size: 0.8rem; color: #fff; text-shadow: 0 0 10px rgba(255,255,255,0.1);">${finding.entity_name || 'Strategic Hub'}</span>
                        <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 4px;">
                            <span style="color: ${sentimentColor}; font-weight: 900; font-size: 0.85rem; letter-spacing: -0.5px;">${alphaFormatted}</span>
                            <span style="font-size: 0.55rem; color: #8b949e; letter-spacing: 1px; font-weight: 700; text-transform: uppercase;">ORDER ${level}</span>
                        </div>
                    </div>
                    <div style="font-size: 0.75rem; color: #adbac7; line-height: 1.4; margin-bottom: 8px; opacity: 0.8;">
                        ${shortSummary}
                    </div>
                    <div style="display: flex; gap: 6px; margin-bottom: 0;">
                        <span style="font-size: 0.55rem; background: rgba(88, 166, 255, 0.1); color: #58a6ff; padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(88, 166, 255, 0.2); font-weight: 800; text-transform: uppercase;">${sector}</span>
                    </div>
                    <div class="sidebar-item-details" style="display: none; padding-top: 8px; margin-top: 8px; border-top: 1px dashed rgba(255,255,255,0.1); font-size: 0.75rem; color: #adbac7;">
                        <div style="color: #58a6ff; font-weight: 600; margin-bottom: 4px;">Strategic Recommendation:</div>
                        ${finding.recommendation || finding.action_recommendation || "Monitor for volatility spillover."}
                    </div>
                </div>
            `;
        });
    }

    bodyHtml += `</div>`;
    container.innerHTML = headerHtml + bodyHtml;

    // Attach Event Listeners
    container.querySelectorAll('.sort-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const el = e.currentTarget as HTMLElement;
            activeSort = el.dataset.sort as any;
            renderImpactSidebar(containerId, alert, mapInstance);
        });
    });

    container.querySelectorAll('.sidebar-item').forEach(item => {
        const el = item as HTMLElement;
        
        // Hover -> highlight map logic could go here via CustomEvent
        
        // Click -> Expand details and focus map
        el.addEventListener('click', () => {
            // Toggle detail visibility
            const details = el.querySelector('.sidebar-item-details') as HTMLElement;
            const isVisible = details.style.display !== 'none';
            
            // Close all
            container.querySelectorAll('.sidebar-item-details').forEach(d => (d as HTMLElement).style.display = 'none');
            container.querySelectorAll('.sidebar-item').forEach(d => (d as HTMLElement).style.borderColor = 'rgba(255,255,255,0.05)');

            if (!isVisible) {
                details.style.display = 'block';
                el.style.borderColor = color;

                // Sync with map (emit event that map.ts listens to)
                window.dispatchEvent(new CustomEvent('sidebar-node-focus', { 
                    detail: { 
                        entity_name: el.dataset.id,
                        lat: parseFloat(el.dataset.lat || '0'),
                        lng: parseFloat(el.dataset.lng || '0')
                    }
                }));
            }
        });
    });
}

export function hideImpactSidebar(containerId: string) {
    const container = document.getElementById(containerId);
    if (container) {
        container.style.display = 'none';
        container.innerHTML = '';
    }
}

// Add Global Styling for Sidebar
const style = document.createElement('style');
style.textContent = `
    #impact-panel-container {
        scrollbar-width: thin;
        scrollbar-color: rgba(255,255,255,0.1) transparent;
        animation: slideInRight 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        box-shadow: -10px 0 30px rgba(0,0,0,0.5);
        z-index: 1000;
        backdrop-filter: blur(16px);
    }
    #impact-panel-container::-webkit-scrollbar {
        width: 4px;
    }
    #impact-panel-container::-webkit-scrollbar-thumb {
        background: rgba(255,255,255,0.1);
        border-radius: 2px;
    }
    .impact-panel-body {
        scroll-behavior: smooth;
    }
    .sidebar-item {
        animation: fadeInNode 0.4s ease-out;
    }
    @keyframes slideInRight {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes fadeInNode {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
`;
document.head.appendChild(style);
