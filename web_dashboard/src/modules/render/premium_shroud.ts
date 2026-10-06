/**
 * premium_shroud.ts
 *
 * Commercial gating UI for the three premium modules (Market Pulse, Pro Insight,
 * Pro Interactive Map). When a FREE/guest session navigates into one of these
 * tabs, main.ts renders this frosted-glass shroud over the container INSTEAD of
 * loading the real component — so no Pro data is ever fetched (the backend would
 * 403 anyway), and the guest gets a persuasive sign-in / pricing CTA.
 *
 * The blur is a real glassmorphism effect (`backdrop-filter: blur`) layered over
 * a decorative faux preview, so the locked feature still feels tangible.
 */
import type { UserMe } from '../api';

export type ShroudFeature = 'market-pulse' | 'pro-insights' | 'pro-map';

type FeatureMeta = { icon: string; title: string; blurb: string; bullets: string[] };

const FEATURE_META: Record<ShroudFeature, FeatureMeta> = {
    'market-pulse': {
        icon: '📈',
        title: 'Market Pulse',
        blurb: 'Real-time quantitative domain pressure, sector distribution indices, and historical risk trend lines for tactical monitoring.',
        bullets: ['Live per-domain pressure gauges', 'Macro transmission & regime signals'],
    },
    'pro-insights': {
        icon: '💎',
        title: 'Pro Insight',
        blurb: 'In-depth structural intelligence briefs — qualitative transmission analysis, exposure matrices, and domain-filtered long-form reports.',
        bullets: ['Risk-contagion lead-lag tracker', 'Sector drill-down dossiers', 'Exposure & entity heat matrices'],
    },
    'pro-map': {
        icon: '🗺️',
        title: 'Pro Interactive Map',
        blurb: 'Global spatial surveillance — geolocated signal clusters, maritime choke-point flow, and collateral contagion networks.',
        bullets: ['Geospatial signal clustering', 'Maritime choke-point flow', 'Sanctions contagion graph'],
    },
};

const STYLE_ID = 'premium-shroud-style';

function injectStyles(): void {
    if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
    .premium-shroud {
        position: relative; flex: 1; width: 100%; min-height: 440px;
        border-radius: 14px; overflow: hidden;
        border: 1px solid rgba(255,255,255,0.08);
    }
    .premium-shroud-preview {
        position: absolute; inset: 0; padding: 26px; display: grid;
        grid-template-columns: repeat(3, 1fr); grid-auto-rows: 78px; gap: 16px;
        filter: blur(9px) saturate(1.15); opacity: 0.40; pointer-events: none;
    }
    .premium-shroud-preview span {
        border-radius: 10px;
        background: linear-gradient(135deg, rgba(88,166,255,0.35), rgba(188,140,255,0.20));
        border: 1px solid rgba(255,255,255,0.06);
    }
    .premium-shroud-preview span:nth-child(3n) { background: linear-gradient(135deg, rgba(63,185,80,0.30), rgba(88,166,255,0.15)); }
    .premium-shroud-preview span:nth-child(3n+1) { grid-row: span 2; }
    .premium-shroud-overlay {
        position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
        padding: 24px;
        background: rgba(13,17,23,0.30);
        -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px);
    }
    .premium-shroud-card {
        max-width: 480px; width: 100%; text-align: center; padding: 34px 30px;
        border-radius: 18px; border: 1px solid rgba(255,255,255,0.12);
        background: rgba(22,27,34,0.62);
        box-shadow: 0 10px 48px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.06);
    }
    .premium-shroud-badge {
        display: inline-flex; align-items: center; gap: 6px; font-size: 0.7rem;
        letter-spacing: 0.12em; text-transform: uppercase; color: #58a6ff;
        border: 1px solid rgba(88,166,255,0.4); border-radius: 999px; padding: 4px 12px; margin-bottom: 14px;
    }
    .premium-shroud-icon { font-size: 2.4rem; line-height: 1; margin-bottom: 10px; }
    .premium-shroud-card h2 { margin: 0 0 8px; font-size: 1.4rem; color: #f0f6fc; }
    .premium-shroud-card p { margin: 0 auto 18px; font-size: 0.9rem; color: #8b949e; max-width: 400px; line-height: 1.5; }
    .premium-shroud-bullets { list-style: none; padding: 0; margin: 0 0 22px; display: grid; gap: 8px; text-align: left; max-width: 320px; margin-inline: auto; }
    .premium-shroud-bullets li { font-size: 0.82rem; color: #c9d1d9; display: flex; gap: 8px; align-items: center; }
    .premium-shroud-bullets li::before { content: '✦'; color: #58a6ff; font-size: 0.75rem; }
    .premium-shroud-actions { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }
    .premium-shroud-cta {
        cursor: pointer; border: none; border-radius: 10px; padding: 11px 22px; font-size: 0.9rem; font-weight: 600;
        color: #fff; background: linear-gradient(135deg, #58a6ff, #6e5bff);
        box-shadow: 0 4px 18px rgba(88,166,255,0.35); transition: transform 0.12s ease, box-shadow 0.12s ease;
    }
    .premium-shroud-cta:hover { transform: translateY(-1px); box-shadow: 0 6px 24px rgba(88,166,255,0.5); }
    .premium-shroud-signin {
        cursor: pointer; border: 1px solid rgba(255,255,255,0.18); border-radius: 10px; padding: 11px 22px;
        font-size: 0.9rem; font-weight: 600; color: #c9d1d9; background: transparent; transition: border-color 0.12s ease, color 0.12s ease;
    }
    .premium-shroud-signin:hover { border-color: rgba(255,255,255,0.4); color: #fff; }
    `;
    document.head.appendChild(style);
}

function isAnonymousGuest(user: UserMe | null | undefined): boolean {
    if (!user) return true;
    if (user.id === 'dev-override') return false;
    if (user.id === 'free-access') return true;
    return !user.email?.trim();
}

/**
 * Render the frosted-glass premium gate into `host`. `onViewPlans` routes to the
 * pricing tab; the Sign In CTA (guests only) dispatches `trigger-login`.
 */
export function renderPremiumShroud(
    host: HTMLElement,
    feature: ShroudFeature,
    user: UserMe | null,
    onViewPlans: () => void,
): void {
    injectStyles();
    const meta = FEATURE_META[feature];
    const guest = isAnonymousGuest(user);
    const previewCells = Array.from({ length: 6 }, () => '<span></span>').join('');
    const signInBtn = guest
        ? '<button type="button" class="premium-shroud-signin" id="premium-shroud-signin">Sign In</button>'
        : '';

    host.innerHTML = `
        <div class="premium-shroud" role="region" aria-label="${meta.title} — Pro feature locked">
            <div class="premium-shroud-preview" aria-hidden="true">${previewCells}</div>
            <div class="premium-shroud-overlay">
                <div class="premium-shroud-card">
                    <span class="premium-shroud-badge">🔒 Pro Feature</span>
                    <div class="premium-shroud-icon" aria-hidden="true">${meta.icon}</div>
                    <h2>${meta.title}</h2>
                    <p>${meta.blurb}</p>
                    <ul class="premium-shroud-bullets">
                        ${meta.bullets.map((b) => `<li>${b}</li>`).join('')}
                    </ul>
                    <div class="premium-shroud-actions">
                        <button type="button" class="premium-shroud-cta" id="premium-shroud-plans">View Pricing Plans</button>
                        ${signInBtn}
                    </div>
                </div>
            </div>
        </div>
    `;

    host.querySelector('#premium-shroud-plans')?.addEventListener('click', () => onViewPlans());
    if (guest) {
        host.querySelector('#premium-shroud-signin')?.addEventListener('click', () => {
            window.dispatchEvent(new CustomEvent('trigger-login'));
        });
    }
}
