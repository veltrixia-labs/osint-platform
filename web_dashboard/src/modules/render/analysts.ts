import { updateWatchlist } from '../api';
import type { AnalystProfile } from '../api';

/**
 * Renders the primary sidebar containing strategic entities and analyst profile info.
 */
export function renderSidebar(analysts: AnalystProfile[], container: HTMLElement) {
    if (!analysts.length) return;
    const a = analysts[0];
    const usage = (window as any).getCurrentUsage?.() || { keywords: { used: 0, limit: 3 } };
    const isGuest = a.id === 'guest';

    container.innerHTML = `
        <div class="sidebar-header" style="margin-bottom: 1rem;">
            <h3 style="font-size: 0.85rem; letter-spacing: 0.05em; font-weight: 800; color: var(--accent); text-transform: uppercase;">
                Watchlist (Active Monitoring)
            </h3>
        </div>
        <div class="keyword-list">
            ${(a.watch_keywords || []).map(k => `
                <div class="kw-item u-flex-between">
                    <span>${k}</span>
                    <button class="remove-kw" data-keyword="${k}">&times;</button>
                </div>
            `).join('')}
        </div>
        <div class="add-kw-container u-m-top-1">
            <input type="text" id="new-keyword" placeholder="${isGuest ? 'Join to add' : 'Add entity...'}" ${isGuest ? 'disabled' : ''} />
            <button id="add-keyword-btn" class="u-tier-1" ${isGuest ? 'disabled' : ''}>Add</button>
            ${isGuest ? `
                <div class="guest-lock-msg" style="font-size: 0.7rem; color: var(--accent); margin-top: 8px; font-weight: 600;">
                    🔒 Account required for alerts
                </div>
            ` : (usage.keywords?.used >= usage.keywords?.limit ? `
                <div style="font-size: 0.7rem; color: #ff7b72; margin-top: 8px;">
                    Keyword limit reached (${usage.keywords.limit}/${usage.keywords.limit}). 
                    <a href="#" id="watchlist-upgrade-link" style="color:#58a6ff; text-decoration:none;">Upgrade to Pro</a>
                </div>
            ` : '')}
        </div>

        <div class="sidebar-footer-nav" style="margin-top: auto; padding-top: 1.5rem; border-top: 1px solid var(--border);">
            <div class="analyst-profile-section" style="margin-bottom: 1.5rem; padding: 1rem; background: rgba(255,255,255,0.03); border-radius: 12px; border: 1px solid rgba(255,255,255,0.05);">
                <div style="font-size: 0.7rem; color: #8b949e; margin-bottom: 0.5rem; text-transform: uppercase; font-weight: 700; letter-spacing: 0.05em;">Analyst Profile</div>
                ${isGuest ? `
                    <div style="margin-bottom: 0.75rem; font-size: 0.85rem; color: #c9d1d9;">Mode: <span style="color: var(--accent);">Guest Analyst</span></div>
                    <button id="sidebar-login-btn" style="width: 100%; padding: 8px; background: var(--accent); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 0.85rem;">Sign In / Join</button>
                ` : `
                    <div style="margin-bottom: 0.5rem; font-size: 0.85rem; color: #c9d1d9; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${a.email}">
                        ${a.email}
                    </div>
                    <div style="margin-bottom: 0.75rem; font-size: 0.7rem; opacity: 0.5;">ID: ${a.id.slice(0, 8)}...</div>
                    <button id="sidebar-logout-btn" style="width: 100%; padding: 8px; background: rgba(248,81,73,0.15); color: #ff7b72; border: 1px solid rgba(248,81,73,0.4); border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 0.85rem; transition: all 0.2s;">Sign Out</button>
                `}
            </div>

            <div class="legal-links" style="font-size: 0.65rem; opacity: 0.4; text-align: center; display: flex; flex-wrap: wrap; justify-content: center; gap: 8px;">
                <a href="#legal" style="color: inherit; text-decoration: none;">Disclosure</a>
                <a href="#legal" style="color: inherit; text-decoration: none;">Terms</a>
                <a href="#legal" style="color: inherit; text-decoration: none;">Privacy</a>
            </div>
            <div style="font-size: 0.65rem; opacity: 0.8; text-align: center; margin-top: 1rem; color: var(--accent);">
                API Version: 7.5-FINAL-SYNC | <span id="data-pulse" style="color: #3fb950;">📡 Connected</span>
            </div>
            <div style="font-size: 0.6rem; opacity: 0.4; text-align: center; margin-top: 0.5rem; line-height: 1.4;">
                System Status: <span style="color:#3fb950;">Stable</span><br>
                Last Refined: ${new Date().toLocaleTimeString()}
            </div>
            <div style="font-size: 0.6rem; opacity: 0.3; text-align: center; margin-top: 8px;">&copy; 2026 VELTRIXIA LABS</div>
        </div>
    `;

    const addBtn = container.querySelector('#add-keyword-btn') as HTMLButtonElement | null;
    const input = container.querySelector('#new-keyword') as HTMLInputElement | null;
    const upgradeLink = container.querySelector('#watchlist-upgrade-link');

    if (addBtn && input) {
        addBtn.addEventListener('click', async () => {
            const val = input.value.trim();
            if (!val) return;
            const currentKws = a.watch_keywords || [];
            if (currentKws.includes(val)) return;
            try {
                addBtn.textContent = "...";
                const updatedKws = [...currentKws, val];
                await updateWatchlist(a.id, updatedKws);
                
                a.watch_keywords = updatedKws;
                input.value = ""; 
                
                if ((window as any).refreshUsage) (window as any).refreshUsage();
            } catch (err: any) {
                alert(err.message);
            } finally {
                addBtn.textContent = "Add";
            }
        });
    }

    if (upgradeLink) {
        upgradeLink.addEventListener('click', (e) => {
            e.preventDefault();
            document.querySelector<HTMLElement>('#nav-plans')?.click();
        });
    }

    container.querySelectorAll('.remove-kw').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const target = e.currentTarget as HTMLElement;
            const kw = target.dataset.keyword;
            const currentKws = a.watch_keywords || [];
            try {
                const updatedKws = currentKws.filter(k => k !== kw);
                await updateWatchlist(a.id, updatedKws);
                a.watch_keywords = updatedKws; 
                if ((window as any).refreshUsage) (window as any).refreshUsage();
            } catch (err: any) {
                alert(err.message);
            }
        });
    });
}
