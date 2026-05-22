/**
 * Session resolution for dashboard boot — prevents free-tier paywall flicker while /auth/me runs.
 */
import type { UserMe } from './api';
import { fetchMeDetailed } from './api';

export type AuthSessionStatus = 'pending' | 'ready' | 'redirect_login';

let sessionStatus: AuthSessionStatus = 'pending';
let resolvedUser: UserMe | null = null;

export function getAuthSessionStatus(): AuthSessionStatus {
    return sessionStatus;
}

export function isAuthSessionPending(): boolean {
    return sessionStatus === 'pending';
}

export function isAuthSessionReady(): boolean {
    return sessionStatus === 'ready';
}

export function getResolvedSessionUser(): UserMe | null {
    return resolvedUser;
}

export function clearStaleAuthTokens(): void {
    localStorage.removeItem('access_token');
    sessionStorage.removeItem('isLoggingOut');
}

export function isLoginPath(pathname?: string): boolean {
    const path = (pathname ?? window.location.pathname).replace(/\/$/, '') || '/';
    return path === '/login' || path.endsWith('/login');
}

export function redirectToLogin(message?: string): void {
    clearStaleAuthTokens();
    sessionStatus = 'redirect_login';
    resolvedUser = null;

    const qs = message ? `?msg=${encodeURIComponent(message)}` : '';
    const target = `/login${qs}`;
    if (isLoginPath()) {
        return;
    }
    window.location.replace(target);
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

export type ResolveAuthOptions = {
    hasToken: boolean;
    applyDevOverride: (user: UserMe | null) => UserMe;
};

/**
 * Resolves the current user for dashboard render. Call once per initDashboard after initApiBase.
 */
export async function resolveAuthSession(options: ResolveAuthOptions): Promise<UserMe> {
    const { hasToken, applyDevOverride } = options;

    if (!hasToken) {
        sessionStatus = 'ready';
        resolvedUser = applyDevOverride(null);
        return resolvedUser;
    }

    sessionStatus = 'pending';
    resolvedUser = null;

    const maxAttempts = 3;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
        const result = await fetchMeDetailed();
        if (result.status === 'ok' && result.user) {
            sessionStatus = 'ready';
            resolvedUser = applyDevOverride(result.user);
            return resolvedUser;
        }
        if (result.status === 'unauthorized') {
            redirectToLogin('Your session has expired. Please sign in again.');
            throw new AuthRedirectError();
        }
        if (attempt < maxAttempts - 1) {
            await sleep(400 * (attempt + 1));
        }
    }

    // Transient errors: one more pass before treating as invalid session
    const final = await fetchMeDetailed();
    if (final.status === 'ok' && final.user) {
        sessionStatus = 'ready';
        resolvedUser = applyDevOverride(final.user);
        return resolvedUser;
    }
    if (final.status === 'unauthorized') {
        redirectToLogin('Your session has expired. Please sign in again.');
        throw new AuthRedirectError();
    }

    if (hasToken) {
        redirectToLogin('Could not verify your session. Please sign in again.');
        throw new AuthRedirectError();
    }

    sessionStatus = 'ready';
    resolvedUser = applyDevOverride(null);
    return resolvedUser;
}

export class AuthRedirectError extends Error {
    constructor() {
        super('auth_redirect');
        this.name = 'AuthRedirectError';
    }
}

export function renderAuthBootScreen(root: HTMLElement): void {
    root.classList.remove('login-page');
    root.innerHTML = `
      <div class="auth-boot-screen" role="status" aria-live="polite" aria-busy="true">
        <div class="auth-boot-inner">
          <span class="sync-dot sync-dot--init" aria-hidden="true"></span>
          <span class="sync-label">SYNC: INITIALIZING...</span>
          <p class="auth-boot-sub">Validating your session…</p>
        </div>
      </div>
    `;
}
