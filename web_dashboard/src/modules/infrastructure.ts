export interface StategicAsset {
    id: string;
    name: string;
    lat: number;
    lng: number;
    type: 'choke_point' | 'energy' | 'tech' | 'corpHQ' | 'military' | 'crypto' | 'market';
    topic_code: string | null; 
    description: string;
    importance: number; 
    symbol?: string;    
    marketData?: {
        ticker?: string;
        price?: string;
        change?: number; // percentage
        status?: string;
    };
    newsSnippet?: {
        headline: string;
        source: string;
        timestamp: string;
    };
}

export const STRATEGIC_ASSETS: StategicAsset[] = [
    // --- Geopolitical & Trade Choke Points ---
    { 
        id: 'suez', name: 'Suez Canal', lat: 30.5852, lng: 32.2654, type: 'choke_point', topic_code: 'supply_chain_intelligence', description: 'Global trade bottleneck (Suez)', importance: 1.0, symbol: '🚢',
        marketData: { status: 'NORMAL', change: -0.2 },
        newsSnippet: { headline: 'Transit volume stabilized after Red Sea disruption', source: 'REUTERS', timestamp: '2h ago' }
    },
    { 
        id: 'hormuz', name: 'Strait of Hormuz', lat: 26.5667, lng: 56.25, type: 'choke_point', topic_code: 'energy_resource_risk', description: 'Primary oil transit nexus', importance: 1.0, symbol: '🛢️',
        marketData: { status: 'MONITORED', change: 1.4 },
        newsSnippet: { headline: 'Escort patrols increased in Gulf of Oman', source: 'BLOOMBERG', timestamp: '5h ago' }
    },
    { id: 'malacca', name: 'Strait of Malacca', lat: 2.25, lng: 102.25, type: 'choke_point', topic_code: 'supply_chain_intelligence', description: 'Critical Indo-Pacific trade artery', importance: 0.95, symbol: '🚢' },
    
    // --- Global Market & Exchanges ---
    { 
        id: 'nyse', name: 'New York Stock Exchange', lat: 40.7069, lng: -74.0113, type: 'market', topic_code: 'global_market_intelligence', description: 'Global financial epicenter', importance: 1.0, symbol: '🏛️',
        marketData: { ticker: 'VIX', price: '14.85', change: -2.1, status: 'OPEN' },
        newsSnippet: { headline: 'Treasury yields dip as inflation cooling signals emerge', source: 'CNBC', timestamp: '1h ago' }
    },

    // --- AI & Semiconductor Intelligence ---
    { 
        id: 'silicon_valley', name: 'Silicon Valley (NVDA)', lat: 37.38, lng: -122.08, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'AI innovation center', importance: 1.0, symbol: '🤖',
        marketData: { ticker: 'NVDA', price: '894.22', change: 1.25, status: 'ACTIVE' },
        newsSnippet: { headline: 'NVIDIA expands Blackwell allocation for AWS clouds', source: 'THE VERGE', timestamp: '3h ago' }
    },
    { 
        id: 'hsinchu', name: 'Hsinchu (TSMC)', lat: 24.78, lng: 121.01, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'Semiconductor foundry hub', importance: 1.0, symbol: '🤖',
        marketData: { ticker: '2330.TW', price: '780.00', change: 3.4, status: 'ACTIVE' },
        newsSnippet: { headline: '2nm yield targets met ahead of Apple A19 production', source: 'DIGITIMES', timestamp: '4h ago' }
    },
    { 
        id: 'asml_hq', name: 'ASML (Veldhoven)', lat: 51.40, lng: 5.40, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'EUV lithography manufacturing', importance: 1.0, symbol: '🤖',
        marketData: { ticker: 'ASML.AS', price: '921.40', change: -0.8, status: 'OPEN' },
        newsSnippet: { headline: 'High-NA EUV tool shipping to Intel fab complete', source: 'TECHCRUNCH', timestamp: '6h ago' }
    }
];

/**
 * [v35] Haversine Distance Utility for Proximity Detection
 */
export function getDistanceKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
    const R = 6371; // Earth radius in km
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLng = (lng2 - lng1) * Math.PI / 180;
    const a = 
        Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * 
        Math.sin(dLng / 2) * Math.sin(dLng / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
}

/**
 * [v35] Detects if an event is near a strategic choke point or asset.
 */
export function getStrategicContext(lat: number, lng: number, thresholdKm: number = 500): StategicAsset | null {
    for (const asset of STRATEGIC_ASSETS) {
        const dist = getDistanceKm(lat, lng, asset.lat, asset.lng);
        if (dist <= thresholdKm) {
            return asset;
        }
    }
    return null;
}
