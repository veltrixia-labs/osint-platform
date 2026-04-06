export interface StategicAsset {
    id: string;
    name: string;
    lat: number;
    lng: number;
    type: 'choke_point' | 'energy' | 'tech' | 'corpHQ' | 'military' | 'crypto' | 'market';
    topic_code: string | null; 
    description: string;
    strategicRole?: string; // [v17] Intelligence snippet
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
        id: 'suez', name: 'Suez Canal', lat: 30.5852, lng: 32.2654, type: 'choke_point', topic_code: 'supply_chain_intelligence', description: 'Global trade bottleneck (Suez)', strategicRole: 'Primary transcontinental trade pivot.', importance: 1.0, symbol: '🚢',
        marketData: { status: 'NORMAL', change: -0.2 }
    },
    { 
        id: 'hormuz', name: 'Strait of Hormuz', lat: 26.5667, lng: 56.25, type: 'choke_point', topic_code: 'energy_resource_risk', description: 'Primary oil transit nexus', strategicRole: '20% of global oil flows here.', importance: 1.0, symbol: '🛢️',
        marketData: { status: 'MONITORED', change: 1.4 }
    },
    { id: 'malacca', name: 'Strait of Malacca', lat: 2.25, lng: 102.25, type: 'choke_point', topic_code: 'supply_chain_intelligence', description: 'Critical Indo-Pacific trade artery', strategicRole: 'Pivot of the String of Pearls.', importance: 0.95, symbol: '🚢' },
    { id: 'bab_el_mandeb', name: 'Bab-el-Mandeb', lat: 12.6, lng: 43.34, type: 'choke_point', topic_code: 'energy_resource_risk', description: 'Gate of Tears choke point', strategicRole: 'High-risk red sea entrance.', importance: 0.95, symbol: '🚢' },
    { id: 'panama_canal', name: 'Panama Canal', lat: 9.11, lng: -79.72, type: 'choke_point', topic_code: 'supply_chain_intelligence', description: 'Trans-American maritime link', strategicRole: 'Sensitive to climate & US-China trade.', importance: 0.9, symbol: '🚢' },
    { id: 'northern_sea_route', name: 'Northern Sea Route', lat: 71.27, lng: 72.07, type: 'choke_point', topic_code: 'supply_chain_intelligence', description: 'Arctic transit corridor', strategicRole: 'Emerging RU-China trade bypass.', importance: 0.7, symbol: '❄️' },
    
    // --- Global Market & Financial Hubs ---
    { 
        id: 'nyse', name: 'NYSE', lat: 40.7069, lng: -74.0113, type: 'market', topic_code: 'global_market_intelligence', description: 'Global financial epicenter', importance: 1.0, symbol: '🏛️',
        marketData: { ticker: 'VIX', price: '14.85', change: -2.1, status: 'OPEN' }
    },
    { id: 'fed', name: 'Federal Reserve', lat: 38.8921, lng: -77.0460, type: 'market', topic_code: 'global_market_intelligence', description: 'US Monetary Authority', strategicRole: 'Source of global dollar liquidity.', importance: 1.0, symbol: '🏛️' },
    { id: 'ecb_hq', name: 'ECB (Frankfurt)', lat: 50.11, lng: 8.68, type: 'market', topic_code: 'global_market_intelligence', description: 'Eurozone monetary pivot', strategicRole: 'Guardian of Euro stability.', importance: 1.0, symbol: '🏛️' },
    { id: 'jpm_hq', name: 'JPMorgan Chase', lat: 40.75, lng: -73.97, type: 'market', topic_code: 'global_market_intelligence', description: 'Systemically important bank', strategicRole: 'Barometer of global capital flows.', importance: 0.95, symbol: '🏦' },
    { id: 'gs_hq', name: 'Goldman Sachs', lat: 40.71, lng: -74.01, type: 'market', topic_code: 'global_market_intelligence', description: 'Global sentiment maker', strategicRole: 'Key proxy for institutional intent.', importance: 0.9, symbol: '💰' },
    { id: 'citadel_hq', name: 'Citadel Securities', lat: 41.87, lng: -87.63, type: 'market', topic_code: 'global_market_intelligence', description: 'Systemic liquidity provider', strategicRole: 'Largest US equity market maker.', importance: 0.9, symbol: '📈' },
    { id: 'blackrock', name: 'BlackRock', lat: 40.7589, lng: -73.9790, type: 'corpHQ', topic_code: 'global_market_intelligence', description: 'Global capital flow proxy', strategicRole: 'Worlds largest asset manager.', importance: 0.9, symbol: '💰' },
    { id: 'swift', name: 'SWIFT', lat: 50.8503, lng: 4.3517, type: 'market', topic_code: 'global_market_intelligence', description: 'International payments backbone', importance: 0.95, symbol: '🌐' },

    // --- AI & Semiconductor Intelligence ---
    { id: 'nvda_hq', name: 'NVIDIA', lat: 37.3871, lng: -121.9667, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'AI compute leadership hub', strategicRole: 'Sole source for AI training chips.', importance: 1.0, symbol: '🤖' },
    { id: 'tsmc_hq', name: 'TSMC (Hsinchu)', lat: 24.7736, lng: 121.0117, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'Critical foundry node', strategicRole: 'Advanced node monopoly stakeholder.', importance: 1.0, symbol: '🤖' },
    { id: 'samsung_px', name: 'Samsung (Pyeongtaek)', lat: 37.0, lng: 127.05, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'World largest memory complex', strategicRole: 'HBM & Foundry duopoly player.', importance: 0.95, symbol: '🤖' },
    { id: 'intel_or', name: 'Intel (Oregon)', lat: 45.53, lng: -122.95, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'US logic manufacturing hub', strategicRole: 'Central to US CHIPS Act success.', importance: 0.95, symbol: '🤖' },
    { id: 'asml_hq', name: 'ASML (Veldhoven)', lat: 51.4231, lng: 5.4211, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'EUV lithography monopoly', strategicRole: 'Sole source for EUV scanners.', importance: 1.0, symbol: '🤖' },
    { id: 'tel_hq', name: 'Tokyo Electron', lat: 35.66, lng: 139.73, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'Essential equipment supplier', strategicRole: 'Japanese semi-equipment pivot.', importance: 0.9, symbol: '🤖' },
    { id: 'arm_hq', name: 'Arm Holdings', lat: 52.17, lng: 0.17, type: 'tech', topic_code: 'ai_semiconductor_intelligence', description: 'Architecture IP licensor', strategicRole: 'Foundation of AI & Mobile CPUs.', importance: 0.9, symbol: '🤖' },

    // --- Energy & Resource Risk ---
    { id: 'aramco_hq', name: 'Saudi Aramco', lat: 26.2886, lng: 50.1140, type: 'energy', topic_code: 'energy_resource_risk', description: 'Worlds largest oil exporter', strategicRole: 'Global energy swing producer.', importance: 1.0, symbol: '🛢️' },
    { id: 'gazprom_hq', name: 'Gazprom', lat: 59.93, lng: 30.36, type: 'energy', topic_code: 'energy_resource_risk', description: 'Russian energy pivot', strategicRole: 'Key weapon in energy diplomacy.', importance: 0.95, symbol: '🔥' },
    { id: 'rio_tinto', name: 'Rio Tinto / BHP', lat: -37.81, lng: 144.96, type: 'energy', topic_code: 'energy_resource_risk', description: 'Resource extraction titan', strategicRole: 'Primary iron & lithium supplier.', importance: 0.9, symbol: '⛏️' },
    { id: 'rare_earth_cn', name: 'Rare Earth (Baotou)', lat: 40.65, lng: 109.84, type: 'energy', topic_code: 'energy_resource_risk', description: 'REE refining epicenter', strategicRole: '90% of heavy REE processing.', importance: 1.0, symbol: '🧭' },
    { id: 'catl_hq', name: 'CATL', lat: 26.6669, lng: 119.5333, type: 'energy', topic_code: 'energy_resource_risk', description: 'Global EV battery leader', importance: 0.9, symbol: '🔋' },

    // --- Defense Technology ---
    { id: 'lmt_hq', name: 'Lockheed Martin', lat: 39.0253, lng: -77.1775, type: 'military', topic_code: 'defense_technology', description: 'Strategic systems leader', strategicRole: 'US/NATO aerospace backbone.', importance: 1.0, symbol: '🛡️' },
    { id: 'pltr_hq', name: 'Palantir', lat: 39.73, lng: -104.99, type: 'tech', topic_code: 'defense_technology', description: 'AI-driven warfare pioneer', strategicRole: 'Western battlefield AI standard.', importance: 0.95, symbol: '🛰️' },
    { id: 'bae_hq', name: 'BAE Systems', lat: 51.52, lng: -0.16, type: 'military', topic_code: 'defense_technology', description: 'UK defense flagship', strategicRole: 'Key EU muni & maritime supplier.', importance: 0.9, symbol: '🛡️' },
    { id: 'noc_hq', name: 'Northrop Grumman', lat: 38.88, lng: -77.22, type: 'military', topic_code: 'defense_technology', description: 'Stealth & Space leader', strategicRole: 'ICBM and B-21 stealth provider.', importance: 0.9, symbol: '🛡️' },
    { id: 'andersen_afb', name: 'Andersen AFB (Guam)', lat: 13.58, lng: 144.92, type: 'military', topic_code: 'defense_technology', description: 'Pacific strike hub', strategicRole: 'Western Pacific bomber base.', importance: 1.0, symbol: '⚓' },
    { id: 'spacex_hq', name: 'SpaceX/Starlink', lat: 33.9213, lng: -118.3267, type: 'military', topic_code: 'defense_technology', description: 'Strategic satellite communications', importance: 0.95, symbol: '🚀' },

    // --- Supply Chain & Logistics ---
    { id: 'maersk_hq', name: 'Maersk', lat: 55.6841, lng: 12.5925, type: 'corpHQ', topic_code: 'supply_chain_intelligence', description: 'Global logistics barometer', strategicRole: 'Freight pricing benchmark.', importance: 0.9, symbol: '🚢' },
    { id: 'dp_world', name: 'DP World', lat: 25.04, lng: 55.05, type: 'corpHQ', topic_code: 'supply_chain_intelligence', description: 'Port terminal operator', strategicRole: 'MEAST logistics nexus.', importance: 0.9, symbol: '🏗️' },
    { id: 'dhl_hq', name: 'DHL / Deutsche Post', lat: 50.71, lng: 7.12, type: 'corpHQ', topic_code: 'supply_chain_intelligence', description: 'EU logistics powerhouse', strategicRole: 'Cross-border express leader.', importance: 0.9, symbol: '✈️' },
    { id: 'fedex_hub', name: 'FedEx (Memphis)', lat: 35.14, lng: -90.04, type: 'corpHQ', topic_code: 'supply_chain_intelligence', description: 'World air cargo hub', importance: 0.9, symbol: '✈️' },

    // --- Crypto & Geopolitics ---
    { id: 'coinbase_hq', name: 'Coinbase', lat: 37.77, lng: -122.41, type: 'crypto', topic_code: 'crypto_geopolitics', description: 'US crypto conduit', strategicRole: 'US/Fiat compliant gateway.', importance: 0.9, symbol: '₿' },
    { id: 'circle_hq', name: 'Circle', lat: 42.36, lng: -71.06, type: 'crypto', topic_code: 'crypto_geopolitics', description: 'USDC token issuer', strategicRole: 'Digital dollar standard pivot.', importance: 0.9, symbol: '💵' },
    { id: 'mstr_hq', name: 'MicroStrategy', lat: 38.92, lng: -77.22, type: 'crypto', topic_code: 'crypto_geopolitics', description: 'Institutional BTC reserve', strategicRole: 'Corporate BTC adoption flag.', importance: 0.9, symbol: '📊' },
    { id: 'binance_hub', name: 'Binance', lat: 1.3521, lng: 103.8198, type: 'crypto', topic_code: 'crypto_geopolitics', description: 'Global liquidity node', importance: 1.0, symbol: '₿' },
    { id: 'tether_hub', name: 'Tether', lat: 19.3133, lng: -81.2546, type: 'crypto', topic_code: 'crypto_geopolitics', description: 'Shadow liquidity pivot', importance: 1.0, symbol: '💵' }
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
