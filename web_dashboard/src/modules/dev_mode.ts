/**
 * dev_mode.ts
 *
 * Single source of truth for the legacy "Dev Mode / Audit Build" full-unlock.
 *
 * PRODUCTION DEFAULT: this flag is `false`. Standard tier-gated rendering is
 * active — Free users see the proper locked treatments (withheld content,
 * shrouds, mosaic masks), and the LOCAL DEV TIER toggle drives the visible tier.
 *
 * When DEV_MODE_AUDIT is `true` (audit builds only):
 *   - Locked UI overlays (paywall cards, ghost nodes, mosaic masks) are
 *     suppressed so reviewers see the full feature set regardless of tier.
 *   - `<body>` gets the `dev-mode-audit` class so CSS can neutralise legacy
 *     locked styles globally, and a fixed "UNLOCKED" badge is mounted.
 *
 * Leave this `false` for the production access model. Flip to `true` only for a
 * one-off full-unlock audit pass — no call sites need to change either way.
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
            mountDevModeBadge();
        }, { once: true });
        return;
    }

    injectStyles();
    mountDevModeBadge();
}

/** Mount the sleek "UNLOCKED" badge (idempotent). Signals that tier restrictions
 *  are bypassed for this DEV / audit build — all payloads served in full. */
function mountDevModeBadge(): void {
    if (typeof document === 'undefined' || document.getElementById(BADGE_ID)) return;
    const badge = document.createElement('div');
    badge.id = BADGE_ID;
    badge.className = 'dev-mode-badge';
    badge.title = 'DEV / audit build — tier restrictions bypassed; all payloads unlocked';
    badge.innerHTML = '<span class="dev-mode-badge-dot" aria-hidden="true"></span>UNLOCKED';
    document.body.appendChild(badge);
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
        /* === Dev Mode "UNLOCKED" badge ============================== */
        #${BADGE_ID}.dev-mode-badge {
            position: fixed; top: 10px; right: 14px; z-index: 9000;
            display: inline-flex; align-items: center; gap: 7px;
            padding: 5px 12px; border-radius: 999px;
            font: 700 0.62rem/1 ui-monospace, "Cascadia Code", Consolas, monospace;
            letter-spacing: 0.16em; text-transform: uppercase;
            color: #5df2a8;
            background: rgba(8, 20, 16, 0.78);
            border: 1px solid rgba(87, 245, 163, 0.5);
            box-shadow: 0 0 14px rgba(87, 245, 163, 0.28), inset 0 0 10px rgba(87, 245, 163, 0.08);
            -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
            pointer-events: none; user-select: none;
        }
        #${BADGE_ID} .dev-mode-badge-dot {
            width: 7px; height: 7px; border-radius: 50%;
            background: #5df2a8; box-shadow: 0 0 8px #5df2a8;
            animation: dev-mode-pulse 2s ease-in-out infinite;
        }
        @keyframes dev-mode-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
    `;
    document.head.appendChild(style);
}
