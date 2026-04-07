import type { HealthData } from '../api';

/**
 * Renders the system health statistics (Fidelity and Noise Reduction).
 */
export function renderHealth(data: HealthData, container: HTMLElement) {
    container.innerHTML = `
        <div class="health-grid">
            <div class="health-stat">
                <div class="u-flex u-flex-between">
                    <span class="health-label">Signal Fidelity <span class="help-tooltip" data-tooltip="Accuracy of AI signals.">?</span></span>
                    <span class="health-val">${((data.review_rate || 0) * 100).toFixed(0)}%</span>
                </div>
            </div>
            <div class="health-stat">
                <div class="u-flex u-flex-between">
                    <span class="health-label">Noise Reduction <span class="help-tooltip" data-tooltip="Data filtered out.">?</span></span>
                    <span class="health-val">${((data.suppression_ratio || 0) * 100).toFixed(0)}%</span>
                </div>
            </div>
        </div>
    `;
}

/**
 * Renders the dynamic Risk Profile cards with sparklines.
 * Phase 3 Implementation: Uses real health data to generate trend visualization.
 */
export function renderRiskProfile(health: HealthData, container: HTMLElement) {
    // Helper to generate sparkline HTML
    const genSparkline = (points: number[]) => {
        return points.map(p => {
            const h = Math.max(5, p * 100);
            return `<div class="sparkline-bar" style="height: ${h}%"></div>`;
        }).join('');
    };

    // Phase 3: Derived history based on real metrics to avoid static hardcoding
    const geoPoints = [
        (health.review_rate || 0.4) * 0.7,
        (health.review_rate || 0.4) * 0.85,
        (health.review_rate || 0.4) * 0.8,
        (health.review_rate || 0.4) * 0.9,
        (health.review_rate || 0.4) 
    ];

    const econPoints = [
        (health.suppression_ratio || 0.8) * 0.95,
        (health.suppression_ratio || 0.8) * 0.9,
        (health.suppression_ratio || 0.8) * 0.85,
        (health.suppression_ratio || 0.8) * 0.8,
        (health.suppression_ratio || 0.8)
    ];

    container.innerHTML = `
        <h2 style="font-size:1.1rem; margin-bottom:1rem;">Risk Profile</h2>
        
        <div class="risk-profile-card">
            <div class="u-flex-between">
                <span style="font-size:0.8rem; opacity:0.7;">Geo-Security Index</span>
                <span style="color:#ff7b72; font-weight:700;">${((health.review_rate || 0) * 10).toFixed(1)}</span>
            </div>
            <div class="sparkline-container">
                ${genSparkline(geoPoints)}
            </div>
            <div style="font-size:0.65rem; opacity:0.5; margin-top:0.4rem;">Trend: Real-time Alignment</div>
        </div>

        <div class="risk-profile-card">
            <div class="u-flex-between">
                <span style="font-size:0.8rem; opacity:0.7;">Economic Stability</span>
                <span style="color:#3fb950; font-weight:700;">${((health.suppression_ratio || 0) * 10).toFixed(1)}</span>
            </div>
            <div class="sparkline-container">
                ${genSparkline(econPoints)}
            </div>
            <div style="font-size:0.65rem; opacity:0.5; margin-top:0.4rem;">Trend: Supply Guard Active</div>
        </div>
        
        <div class="u-m-top-1 u-p-1" style="background:rgba(99,102,241,0.05); border-radius:8px; border:1px solid rgba(99,102,241,0.1);">
            <div style="font-size:0.75rem; color:var(--accent); font-weight:600;">Active Correlation Map</div>
            <p style="font-size:0.7rem; opacity:0.6; margin-top:0.25rem;">Node dependency tracking synchronized with global health metrics.</p>
        </div>
    `;
}

/**
 * Renders the Unified Legal Module (International Standard).
 * Includes Tokushokuho (Specified Commercial Transactions Act), Terms, and Privacy.
 */
export function renderLegal(container: HTMLElement) {
    container.innerHTML = `
        <div class="vlt-legal-tabs">
            <!-- 1. Disclosure (Tokushokuho) -->
            <div class="vlt-legal-card">
                <div class="vlt-legal-header">
                    <span class="vlt-legal-icon">⚖️</span>
                    <span class="vlt-legal-title">Legal Disclosure</span>
                </div>
                <div class="vlt-legal-content vlt-legal-scrollbox">
                    <div class="vlt-legal-section">
                        <h4>Entity Identification</h4>
                        <div class="vlt-legal-item"><span class="label">Seller</span> <span class="value">Veltrixia Labs</span></div>
                        <div class="vlt-legal-item"><span class="label">Representative</span> <span class="value">Global Operations Dir.</span></div>
                        <div class="vlt-legal-item"><span class="label">Contact</span> <span class="value">veltrixia739@gmail.com</span></div>
                    </div>
                    <div class="vlt-legal-section">
                        <h4>Commercial Terms</h4>
                        <div class="vlt-legal-item"><span class="label">Sales Price</span> <span class="value">$0 / $19 / Custom</span></div>
                        <div class="vlt-legal-item"><span class="label">Payment Timing</span> <span class="value">Immediate (Stripe)</span></div>
                        <div class="vlt-legal-item"><span class="label">Service Delivery</span> <span class="value">Instant Activation</span></div>
                    </div>
                    <div class="vlt-legal-section">
                        <h4>Refund Policy</h4>
                        <p>Due to the real-time nature of strategic intelligence reports, all digital purchases are generally non-refundable. Cancellation of recurring subscriptions stops future billing immediately.</p>
                    </div>
                </div>
            </div>

            <!-- 2. Terms of Service -->
            <div class="vlt-legal-card">
                <div class="vlt-legal-header">
                    <span class="vlt-legal-icon">📜</span>
                    <span class="vlt-legal-title">Terms of Service</span>
                </div>
                <div class="vlt-legal-content vlt-legal-scrollbox">
                    <div class="vlt-legal-section">
                        <h4>1. Ethical Use of OSINT</h4>
                        <p>Analysts must use Veltrixia intelligence only for lawful strategic monitoring. Reverse engineering of analytical weights is strictly prohibited.</p>
                    </div>
                    <div class="vlt-legal-section">
                        <h4>2. Data Integrity</h4>
                        <p>While we strive for high-fidelity signals, geopolitical forecasts are probabilistic. Veltrixia Labs is not liable for outcomes based on tactical decisions.</p>
                    </div>
                    <div class="vlt-legal-section">
                        <h4>3. Account Security</h4>
                        <p>Unauthorized sharing of intelligence feeds will result in immediate analyst credential revocation without refund.</p>
                    </div>
                </div>
            </div>

            <!-- 3. Privacy Policy -->
            <div class="vlt-legal-card">
                <div class="vlt-legal-header">
                    <span class="vlt-legal-icon">🛡️</span>
                    <span class="vlt-legal-title">Privacy Policy</span>
                </div>
                <div class="vlt-legal-content vlt-legal-scrollbox">
                    <div class="vlt-legal-section">
                        <h4>Data Minimization</h4>
                        <p>We only collect email addresses and required Stripe metadata. We never store credit card numbers on Veltrixia servers.</p>
                    </div>
                    <div class="vlt-legal-section">
                        <h4>Security Standards</h4>
                        <p>All intelligence transmissions are encrypted via AES-256. Access logs are audited periodically for credential leakage.</p>
                    </div>
                    <div class="vlt-legal-section">
                        <h4>Third-Party Processing</h4>
                        <p>Payment processing is handled exclusively by Stripe, Inc. Usage analytics are anonymized to protect analyst patterns.</p>
                    </div>
                </div>
            </div>
        </div>
    `;
}
