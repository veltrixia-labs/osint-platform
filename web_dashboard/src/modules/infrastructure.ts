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
    
    // --- Global Market & Financial Hubs ---
    { 
        id: 'nyse', name: 'NYSE', lat: 40.7069, lng: -74.0113, type: 'market', topic_code: 'global_market_intelligence', description: 'Global financial epicenter', importance: 1.0, symbol: '🏛️',
        marketData: { ticker: 'VIX', price: '14.85', change: -2.1, status: 'OPEN' }
    },
    { id: 'fed', name: 'Federal Reserve', lat: 38.8921, lng: -77.0460, type: 'market', topic_code: 'global_market_intelligence', description: 'US Monetary Authority', importance: 1.0, symbol: '🏛️' },
    { id: 'blackrock', name: 'BlackRock', lat: 40.7589, lng: -73.9790, type: 'corpHQ', topic_code: 'global_market_intelligence', description: 'Global capital flow proxy', importance: 0.9, symbol: '💰' },
    { id: 'swift', name: 'SWIFT', lat: 50.8503, lng: 4.3517, type: 'market', topic_code: 'global_market_intelligence', description: 'International payments backbone', importance: 0.95, symbol: '🌐' },

    // --- AI & Semiconductor Intelligence ---
    { 
        id: 'nvda_hq', name: 'NVIDIA (Silicon Valley)', lat: 37.3871, lng: -121.9667, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'AI compute leadership hub', importance: 1.0, symbol: '🤖',
        marketData: { ticker: 'NVDA', price: '894.22', change: 1.25, status: 'ACTIVE' }
    },
    { 
        id: 'tsmc_hq', name: 'TSMC (Hsinchu)', lat: 24.7736, lng: 121.0117, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'Critical semiconductor foundry node', importance: 1.0, symbol: '🤖',
        marketData: { ticker: '2330.TW', price: '780.00', change: 3.4, status: 'ACTIVE' }
    },
    { 
        id: 'asml_hq', name: 'ASML (Veldhoven)', lat: 51.4231, lng: 5.4211, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'Sole EUV lithography supplier', importance: 1.0, symbol: '🤖',
        marketData: { ticker: 'ASML.AS', price: '921.40', change: -0.8, status: 'OPEN' }
    },

    // --- Energy & Resource Risk ---
    { id: 'aramco_hq', name: 'Saudi Aramco', lat: 26.2886, lng: 50.1140, type: 'energy', topic_code: 'energy_resource_risk', description: 'Worlds largest oil exporter', importance: 1.0, symbol: '🛢️' },
    { id: 'opec_vienna', name: 'OPEC+', lat: 48.2082, lng: 16.3738, type: 'energy', topic_code: 'energy_resource_risk', description: 'Oil production policy center', importance: 1.0, symbol: '🌍' },
    { id: 'catl_hq', name: 'CATL', lat: 26.6669, lng: 119.5333, type: 'energy', topic_code: 'energy_resource_risk', description: 'Global EV battery leader', importance: 0.9, symbol: '🔋' },

    // --- Defense Technology ---
    { id: 'lmt_hq', name: 'Lockheed Martin', lat: 39.0253, lng: -77.1775, type: 'military', topic_code: 'defense_technology', description: 'Strategic defense systems leader', importance: 1.0, symbol: '🛡️' },
    { id: 'spacex_hq', name: 'SpaceX/Starlink', lat: 33.9213, lng: -118.3267, type: 'military', topic_code: 'defense_technology', description: 'Strategic satellite communications', importance: 0.95, symbol: '🚀' },

    // --- Supply Chain & Logistics ---
    { id: 'maersk_hq', name: 'Maersk', lat: 55.6841, lng: 12.5925, type: 'corpHQ', topic_code: 'supply_chain_intelligence', description: 'Global logistics barometer', importance: 0.9, symbol: '🚢' },
    { id: 'fedex_hub', name: 'FedEx (Memphis Hub)', lat: 35.1495, lng: -90.0490, type: 'corpHQ', topic_code: 'supply_chain_intelligence', description: 'Global air logistics hub', importance: 0.9, symbol: '✈️' },

    // --- Crypto & Geopolitics ---
    { id: 'binance_hub', name: 'Binance', lat: 1.3521, lng: 103.8198, type: 'crypto', topic_code: 'crypto_geopolitics', description: 'Critical crypto liquidity node', importance: 0.9, symbol: '₿' },
    { id: 'tether_hub', name: 'Tether', lat: 19.3133, lng: -81.2546, type: 'crypto', topic_code: 'crypto_geopolitics', description: 'Digital shadow liquidity backbone', importance: 0.9, symbol: '💵' }
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
