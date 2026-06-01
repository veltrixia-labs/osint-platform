/**
 * dev_mode.ts
 *
 * Single source of truth for the "Dev Mode / Audit Build" toggle.
 *
 * When DEV_MODE_AUDIT is true:
 *   - Locked UI overlays (paywall cards, ghost nodes, mosaic masks) are
 *     suppressed so analysts and reviewers see the full feature set.
 *   - `<body>` gets the `dev-mode-audit` class so CSS can neutralise legacy
 *     locked styles globally.
 *
 * NOTE: the on-screen "DEV MODE" badge has been retired for a clean,
 * production-like UI. The lock-neutralisation behaviour below is retained so
 * the platform stays fully open (no paywalls / masks). Any stale badge left in
 * the DOM by an earlier build is purged on init.
 *
 * Flip the flag to `false` to restore standard tier-gated rendering without
 * touching any call sites.
 */

export const DEV_MODE_AUDIT = true;

const BODY_CLASS = 'dev-mode-audit';
const BADGE_ID = 'dev-mode-audit-badge';
const STYLE_ID = 'dev-mode-audit-style';

/** Idempotent: safe to call multiple times during boot. */
export function initDevModeAudit(): void {
    if (!DEV_MODE_AUDIT || typeof document === 'undefined') return;

    if (document.body && !document.body.classList.contains(BODY_CLASS)) {
        document.body.classList.add(BODY_CLASS);
    } else if (!document.body) {
        // Body not ready yet — defer to DOMContentLoaded.
        document.addEventListener('DOMContentLoaded', () => {
            document.body.classList.add(BODY_CLASS);
            injectStyles();
            purgeBadge();
        }, { once: true });
        return;
    }

    injectStyles();
    purgeBadge();
}

/** Remove any DEV MODE badge left in the DOM by a previous build / HMR load. */
function purgeBadge(): void {
    document.getElementById(BADGE_ID)?.remove();
}

function injectStyles(): void {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
        /* === Neutralise legacy locked / ghost / mosaic UI ============ */
        body.${BODY_CLASS} .nav-lock-icon,
        body.${BODY_CLASS} .locked-tier-tag,
        body.${BODY_CLASS} .locked-icon {
            display: none !important;
        }
        body.${BODY_CLASS} .sidebar-nav-link--premium-gate,
        body.${BODY_CLASS} .sidebar-nav-link--locked,
        body.${BODY_CLASS} .topic-tab--locked,
        body.${BODY_CLASS} .report-row--locked,
        body.${BODY_CLASS} .alert-card--locked,
        body.${BODY_CLASS} .alert-card-compact.locked,
        body.${BODY_CLASS} .map-viz-link.btn--locked,
        body.${BODY_CLASS} .mode-btn.locked {
            opacity: 1 !important;
            filter: none !important;
            cursor: pointer !important;
            pointer-events: auto !important;
        }
        body.${BODY_CLASS} .locked-feature-overlay,
        body.${BODY_CLASS} .locked-topic-container {
            display: none !important;
        }
    `;
    document.head.appendChild(style);
}
