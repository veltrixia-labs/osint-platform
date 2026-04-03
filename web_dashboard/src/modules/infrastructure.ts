export interface StategicAsset {
    id: string;
    name: string;
    lat: number;
    lng: number;
    type: 'choke_point' | 'energy' | 'tech' | 'corpHQ';
    description: string;
    importance: number; // 0.0 to 1.0
}

export const STRATEGIC_ASSETS: StategicAsset[] = [
    // Choke Points (Maritime Infrastructure)
    { id: 'suez', name: 'Suez Canal', lat: 30.5852, lng: 32.2654, type: 'choke_point', description: 'Global trade bottleneck (Suez)', importance: 1.0 },
    { id: 'hormuz', name: 'Strait of Hormuz', lat: 26.5667, lng: 56.25, type: 'choke_point', description: 'Primary oil transit nexus', importance: 1.0 },
    { id: 'malacca', name: 'Strait of Malacca', lat: 2.25, lng: 102.25, type: 'choke_point', description: 'Main shipping channel between Indian & Pacific oceans', importance: 0.95 },
    { id: 'mandeb', name: 'Bab-el-Mandeb', lat: 12.58, lng: 43.34, type: 'choke_point', description: 'Red Sea entrance / Suez Gateway', importance: 0.9 },
    { id: 'panama', name: 'Panama Canal', lat: 9.08, lng: -79.68, type: 'choke_point', description: 'Atlantic/Pacific transit hub', importance: 0.85 },
    { id: 'gibraltar', name: 'Strait of Gibraltar', lat: 35.95, lng: -5.48, type: 'choke_point', description: 'Mediterranean entrance', importance: 0.8 },
    { id: 'bosphorus', name: 'Turkish Straits', lat: 41.02, lng: 29.02, type: 'choke_point', description: 'Black Sea to Mediterranean access', importance: 0.8 },

    // Energy Backbone
    { id: 'druzhba', name: 'Druzhba Pipeline Hub', lat: 52.88, lng: 31.91, type: 'energy', description: 'Major oil supply route to Europe', importance: 0.9 },
    { id: 'yamal', name: 'Yamal-Europe Hub', lat: 51.95, lng: 20.3, type: 'energy', description: 'Strategic natural gas artery', importance: 0.85 },
    { id: 'eastwest', name: 'East-West Pipeline', lat: 23.95, lng: 45.1, type: 'energy', description: 'Saudi Arabia crude oil corridor', importance: 0.8 },
    { id: 'ras_tanura', name: 'Ras Tanura Terminal', lat: 26.63, lng: 50.12, type: 'energy', description: 'World largest crude oil export facility', importance: 0.95 },

    // Technology Clusters & Semiconductor Hubs
    { id: 'silicon_valley', name: 'Silicon Valley', lat: 37.38, lng: -122.08, type: 'tech', description: 'Global high-tech innovation center', importance: 1.0 },
    { id: 'hsinchu', name: 'Hsinchu Science Park (TSMC)', lat: 24.78, lng: 121.01, type: 'tech', description: 'Crucial semiconductor foundry hub (TSMC)', importance: 1.0 },
    { id: 'seoul', name: 'Seoul-Gyeonggi Hub (Samsung)', lat: 37.2, lng: 127.1, type: 'tech', description: 'Memory and logic chip production center', importance: 0.95 },
    { id: 'shenzhen', name: 'Shenzhen Tech Hub', lat: 22.54, lng: 114.05, type: 'tech', description: 'Manufacturing & hardware innovation nexus', importance: 0.9 },
    { id: 'shanghai_waigaoqiao', name: 'Waigaoqiao Free Trade Zone', lat: 31.33, lng: 121.58, type: 'tech', description: 'Strategic logistics & semiconductor center in PRC', importance: 0.85 },

    // Corporate Strategic Nodes
    { id: 'nvda_hq', name: 'NVIDIA HQ', lat: 37.3541, lng: -121.9552, type: 'corpHQ', description: 'Global AI compute leadership center', importance: 0.95 },
    { id: 'asml_hq', name: 'ASML HQ (Veldhoven)', lat: 51.40, lng: 5.40, type: 'corpHQ', description: 'Monopolistic lithography tool manufacturing (EUV)', importance: 1.0 }
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
