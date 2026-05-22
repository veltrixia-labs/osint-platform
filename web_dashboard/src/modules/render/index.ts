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
export { renderProInsights, renderExpertIntel } from './insights';
export { renderMarketPulse, disposeMarketPulseView } from './market_pulse';
export { renderFreeAlertFeed } from './context_briefs';
export { renderProMap } from './pro_map';
