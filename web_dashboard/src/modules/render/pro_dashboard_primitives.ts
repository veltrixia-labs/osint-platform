/**
 * Shared Pro dashboard UI primitives (Market Pulse + Pro Insights + Expert).
 */



export const SECTOR_DISTRIBUTION_GUIDE_HTML = `
<p class="intel-guide-title"><strong>Sector Distribution Guide</strong></p>
<ul class="intel-guide-list">
<li><strong>Intelligence Volume Index:</strong> Represents the total cumulative data points, active alerts, and structured contextual inputs currently ingested within each specific domain.</li>
<li><strong>Operational Utility:</strong> This bar ratio visualizes VELTRIXIA&rsquo;s cognitive focus. A sudden spike or extension in a specific sector&rsquo;s bar reflects a heavy influx of real-time signals, indicating an escalating operational friction or high-density risk event in that market vertical.</li>
</ul>`;

/** Module A — Risk Contagion & Lead-Lag Tracker */
export const LEAD_LAG_GUIDE_HTML = `
<div class="pro-guide-content">
  <strong>Risk Contagion & Lead-Lag Tracker</strong>
  <p>Quantifies the directional propagation of risk across sectors by calculating the real-time Cross-Correlation Function (CCF).</p>
  <ul style="margin-top: 8px; padding-left: 16px; opacity: 0.9; line-height: 1.4;">
    <li style="margin-bottom: 4px;"><strong>Lag (e.g., +6.0h):</strong> The time delay before the source sector's risk impacts the target sector.</li>
    <li><strong>R (Correlation):</strong> Measures relationship strength (-1.0 to 1.0).
      <ul style="margin-top: 4px; padding-left: 16px; list-style-type: circle;">
        <li><strong>R &gt; 0:</strong> Positive correlation (moves in the same direction).</li>
        <li><strong>R &lt; 0:</strong> Inverse correlation (moves in the opposite direction). <em>*A negative R is a strong predictive signal, not a lack of correlation.</em></li>
      </ul>
    </li>
  </ul>
</div>`;








export function escHtml(s: string): string {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

export function escAttr(s: string): string {
    return escHtml(s).replace(/'/g, '&#39;');
}

export type PanelGuidePlacement = 'below' | 'above';

/** ℹ️ guide control — shared glassmorphism popover (inline next to panel titles). */
export function renderPanelGuide(
    ariaLabel: string,
    guideInnerHtml: string,
    placement: PanelGuidePlacement = 'below',
): string {
    const placementClass =
        placement === 'above' ? ' intel-section-guide-wrap--popover-above' : '';
    return `<span class="intel-section-guide-wrap intel-section-guide-wrap--inline${placementClass}">
            <button type="button" class="intel-section-guide" aria-label="About ${escAttr(ariaLabel)}" aria-expanded="false">
                <span class="intel-section-guide-icon" aria-hidden="true">ℹ</span>
            </button>
            <span class="intel-section-guide-popover intel-section-guide-popover--rich" role="tooltip">
                <button type="button" class="intel-section-guide-close" aria-label="Close guide" tabindex="0">×</button>
                ${guideInnerHtml}
            </span>
           </span>`;
}

/** Wire up all guide ℹ️ buttons in root: click to open, × or outside-click to close. */
export function wirePanelGuideTooltips(root: HTMLElement): void {
    root.querySelectorAll<HTMLElement>('.intel-section-guide').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const wrap = btn.closest('.intel-section-guide-wrap');
            const pop = wrap?.querySelector('.intel-section-guide-popover');
            if (!pop) return;
            const wasOpen = pop.classList.contains('is-open');
            // Close all open popovers in this root first
            root.querySelectorAll('.intel-section-guide-popover.is-open').forEach((el) => {
                el.classList.remove('is-open');
                el.closest('.intel-section-guide-wrap')?.querySelector('.intel-section-guide')?.setAttribute('aria-expanded', 'false');
            });
            if (!wasOpen) {
                pop.classList.add('is-open');
                btn.setAttribute('aria-expanded', 'true');
            }
        });
    });

    root.querySelectorAll<HTMLElement>('.intel-section-guide-close').forEach((closeBtn) => {
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const pop = closeBtn.closest('.intel-section-guide-popover');
            if (!pop) return;
            pop.classList.remove('is-open');
            pop.closest('.intel-section-guide-wrap')?.querySelector('.intel-section-guide')?.setAttribute('aria-expanded', 'false');
        });
    });
}

/** Glass panel wrapper (Sector Distribution chrome). */
export function renderProPanel(
    title: string,
    content: string,
    footer?: string,
    accentColor = '#58a6ff',
    guideHtml?: string,
): string {
    const headerClass = guideHtml
        ? 'insight-card-header insight-card-header--with-guide'
        : 'insight-card-header';
    return `
    <div class="insight-card pro-insight-panel" style="--accent: ${accentColor}">
        <div class="${headerClass}">
            <h3 class="insight-card-title">${title}</h3>
            ${guideHtml || ''}
        </div>
        <div class="insight-card-body">
            ${content}
        </div>
        ${footer ? `<div class="insight-card-footer">${footer}</div>` : ''}
    </div>`;
}

export function renderIntensityBar(value: number, label: string, color = '#58a6ff'): string {
    const percent = Math.min(Math.max(value * 10, 0), 100);
    return `
    <div class="intensity-bar-wrap">
        <div class="intensity-bar-label">
            <span>${label}</span>
            <span style="color: ${color}">${value.toFixed(1)}</span>
        </div>
        <div class="intensity-bar-bg">
            <div class="intensity-bar-fill" style="width: ${percent}%; background: ${color}; box-shadow: 0 0 10px ${color}44;"></div>
        </div>
    </div>`;
}



// ── Module A: Risk Contagion & Lead-Lag Tracker ────────────────────────────────



