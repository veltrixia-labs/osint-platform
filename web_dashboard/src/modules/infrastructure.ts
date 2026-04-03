export interface StategicAsset {
    id: string;
    name: string;
    lat: number;
    lng: number;
    type: 'choke_point' | 'energy' | 'tech' | 'corpHQ' | 'military' | 'crypto' | 'market';
    topic_code: string | null; // Links to ACCESS_MAP topic_code
    description: string;
    importance: number; // 0.0 to 1.0
    symbol?: string;    // Override icon
}

export const STRATEGIC_ASSETS: StategicAsset[] = [
    // --- Geopolitical & Trade Choke Points ---
    { id: 'suez', name: 'Suez Canal', lat: 30.5852, lng: 32.2654, type: 'choke_point', topic_code: 'supply_chain_intelligence', description: 'Global trade bottleneck (Suez)', importance: 1.0, symbol: '🚢' },
    { id: 'hormuz', name: 'Strait of Hormuz', lat: 26.5667, lng: 56.25, type: 'choke_point', topic_code: 'energy_resource_risk', description: 'Primary oil transit nexus', importance: 1.0, symbol: '🛢️' },
    { id: 'malacca', name: 'Strait of Malacca', lat: 2.25, lng: 102.25, type: 'choke_point', topic_code: 'supply_chain_intelligence', description: 'Critical Indo-Pacific trade artery', importance: 0.95, symbol: '🚢' },
    { id: 'mandeb', name: 'Bab-el-Mandeb', lat: 12.58, lng: 43.34, type: 'choke_point', topic_code: 'supply_chain_intelligence', description: 'Red Sea Gateway', importance: 0.9, symbol: '🚢' },
    { id: 'panama', name: 'Panama Canal', lat: 9.08, lng: -79.68, type: 'choke_point', topic_code: 'supply_chain_intelligence', description: 'Atlantic/Pacific transit', importance: 0.85, symbol: '🚢' },

    // --- Defense & Military (New) ---
    { id: 'norfolk', name: 'Naval Station Norfolk', lat: 36.93, lng: -76.32, type: 'military', topic_code: 'defense_technology', description: 'World largest naval station (US East Coast)', importance: 1.0, symbol: '⚓' },
    { id: 'yokosuka', name: 'Yokosuka Naval Base', lat: 35.29, lng: 139.67, type: 'military', topic_code: 'defense_technology', description: 'Strategic Indo-Pacific naval hub', importance: 0.95, symbol: '⚓' },
    { id: 'sevastopol', name: 'Sevastopol Naval Base', lat: 44.61, lng: 33.52, type: 'military', topic_code: 'defense_technology', description: 'Black Sea strategic bastion', importance: 0.9, symbol: '⚓' },
    { id: 'ramstein', name: 'Ramstein Air Base', lat: 49.43, lng: 7.6, type: 'military', topic_code: 'defense_technology', description: 'Major NATO logistics & command hub', importance: 0.85, symbol: '🛫' },

    // --- Energy & Resource Backbone ---
    { id: 'druzhba', name: 'Druzhba Pipeline Hub', lat: 52.88, lng: 31.91, type: 'energy', topic_code: 'energy_resource_risk', description: 'Oil supply route to Europe', importance: 0.9, symbol: '⚡' },
    { id: 'ras_tanura', name: 'Ras Tanura Terminal', lat: 26.63, lng: 50.12, type: 'energy', topic_code: 'energy_resource_risk', description: 'World largest oil export plant', importance: 1.0, symbol: '🔥' },
    { id: 'nordstream', name: 'Nord Stream Exit (Germany)', lat: 54.12, lng: 13.68, type: 'energy', topic_code: 'energy_resource_risk', description: 'Critical gas infrastructure point', importance: 0.85, symbol: '⚡' },

    // --- Global Market & Exchanges (New) ---
    { id: 'nyse', name: 'New York Stock Exchange', lat: 40.7069, lng: -74.0113, type: 'market', topic_code: 'global_market_intelligence', description: 'Global financial epicenter', importance: 1.0, symbol: '🏛️' },
    { id: 'hkex', name: 'Hong Kong Exchange', lat: 22.28, lng: 114.15, type: 'market', topic_code: 'global_market_intelligence', description: 'Asian capital market nexus', importance: 0.95, symbol: '🏛️' },
    { id: 'lse', name: 'London Stock Exchange', lat: 51.51, lng: -0.09, type: 'market', topic_code: 'global_market_intelligence', description: 'European financial hub', importance: 0.9, symbol: '🏛️' },

    // --- Crypto & Digital Assets (New) ---
    { id: 'texas_mining', name: 'Texas Bitcoin Mining Cluster', lat: 31.96, lng: -99.9, type: 'crypto', topic_code: 'crypto_geopolitics', description: 'Massive hash-rate industrial zone', importance: 0.8, symbol: '₿' },
    { id: 'kazakh_mining', name: 'Kazakhstan Mining Hub', lat: 48.0, lng: 67.0, type: 'crypto', topic_code: 'crypto_geopolitics', description: 'Central Asian crypto mining nexus', importance: 0.75, symbol: '₿' },

    // --- AI & Semiconductor Intelligence ---
    { id: 'silicon_valley', name: 'Silicon Valley', lat: 37.38, lng: -122.08, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'AI innovation center', importance: 1.0, symbol: '🤖' },
    { id: 'hsinchu', name: 'Hsinchu (TSMC)', lat: 24.78, lng: 121.01, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'Semiconductor foundry hub', importance: 1.0, symbol: '🤖' },
    { id: 'asml_hq', name: 'ASML HQ (Veldhoven)', lat: 51.40, lng: 5.40, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'EUV lithography manufacturing', importance: 1.0, symbol: '🤖' }
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
