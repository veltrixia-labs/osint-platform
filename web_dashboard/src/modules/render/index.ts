/**
 * Dashboard render barrel — names here must match `src/main.ts` imports.
 */
export * from './utils';
export * from './alerts';
export * from './system';
export * from './reports';
export * from './analysts';
export * from './impact_panel';

export { renderMap, resetMapEngine } from './map';
export { renderNavigation, updateNavActiveState } from './nav';
export { renderProInsights, renderExpertIntel, disposeProInsightsView } from './insights';
export { renderMarketPulse, disposeMarketPulseView } from './market_pulse';
export { renderProMap } from './pro_map';
export { renderImpactRoster } from './impact_roster';
export { renderTrendFlow, disposeTrendFlow } from './trend_flow';
export { renderPremiumShroud } from './premium_shroud';
export type { ShroudFeature } from './premium_shroud';
