/**
 * Glassmorphism checkout email modal — replaces window.prompt for guest Stripe checkout.
 */

const MODAL_ROOT_ID = 'checkout-email-modal-root';

/** Simple format check: local@domain.tld (no spaces, at least one dot in domain). */
export function isValidCheckoutEmail(raw: string): boolean {
    const email = raw.trim().toLowerCase();
    if (!email || email.length > 254) return false;
    return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email);
}

function normalizeCheckoutEmail(raw: string): string {
    return raw.trim().toLowerCase();
}

function getOrCreateCheckoutEmailModal(): HTMLElement {
    let root = document.getElementById(MODAL_ROOT_ID) as HTMLElement | null;
    if (root) return root;

    root = document.createElement('div');
    root.id = MODAL_ROOT_ID;
    root.className = 'checkout-email-modal-root';
    root.setAttribute('aria-hidden', 'true');
    root.innerHTML = `
        <div class="checkout-email-modal-backdrop" tabindex="-1" aria-hidden="true"></div>
        <div
            class="checkout-email-modal-panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="checkout-email-modal-title"
        >
            <button type="button" class="checkout-email-modal-close" aria-label="閉じる">×</button>
            <h2 id="checkout-email-modal-title" class="checkout-email-modal-title">
                Founding メンバーとして参加
            </h2>
            <p class="checkout-email-modal-desc">
                決済後にアカウントが作成されます。領収書を受け取るメールアドレスを入力してください。
            </p>
            <form class="checkout-email-modal-form" novalidate>
                <label class="checkout-email-modal-label" for="checkout-email-input">メールアドレス</label>
                <input
                    id="checkout-email-input"
                    class="checkout-email-modal-input"
                    type="email"
                    name="email"
                    autocomplete="email"
                    inputmode="email"
                    placeholder="email@example.com"
                    required
                />
                <p class="checkout-email-modal-error" role="alert" hidden></p>
                <button type="submit" class="checkout-email-modal-submit" disabled>
                    Stripe 決済へ進む（安全な外部サイト）
                </button>
            </form>
        </div>
    `;
    document.body.appendChild(root);
    return root;
}

let checkoutEmailModalWired = false;

function wireCheckoutEmailModalOnce(modalRoot: HTMLElement): void {
    if (checkoutEmailModalWired) return;
    checkoutEmailModalWired = true;

    const backdrop = modalRoot.querySelector('.checkout-email-modal-backdrop') as HTMLElement;
    const closeBtn = modalRoot.querySelector('.checkout-email-modal-close') as HTMLButtonElement;
    const form = modalRoot.querySelector('.checkout-email-modal-form') as HTMLFormElement;
    const input = modalRoot.querySelector('#checkout-email-input') as HTMLInputElement;
    const submitBtn = modalRoot.querySelector('.checkout-email-modal-submit') as HTMLButtonElement;
    const errorEl = modalRoot.querySelector('.checkout-email-modal-error') as HTMLParagraphElement;

    let resolvePending: ((value: string | null) => void) | null = null;

    const setError = (message: string | null) => {
        if (!message) {
            errorEl.hidden = true;
            errorEl.textContent = '';
            input.classList.remove('checkout-email-modal-input--invalid');
            return;
        }
        errorEl.hidden = false;
        errorEl.textContent = message;
        input.classList.add('checkout-email-modal-input--invalid');
    };

    const updateSubmitState = () => {
        submitBtn.disabled = !isValidCheckoutEmail(input.value);
        if (isValidCheckoutEmail(input.value)) {
            setError(null);
        }
    };

    const finish = (email: string | null) => {
        if (!resolvePending) return;
        const resolve = resolvePending;
        resolvePending = null;
        modalRoot.classList.remove('checkout-email-modal-root--open');
        modalRoot.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('checkout-email-modal-scroll-lock');
        setError(null);
        input.value = '';
        submitBtn.disabled = true;
        resolve(email);
    };

    const closeModal = () => finish(null);

    const openModal = (resolve: (value: string | null) => void) => {
        resolvePending = resolve;
        input.value = '';
        setError(null);
        submitBtn.disabled = true;
        modalRoot.classList.add('checkout-email-modal-root--open');
        modalRoot.setAttribute('aria-hidden', 'false');
        document.body.classList.add('checkout-email-modal-scroll-lock');
        requestAnimationFrame(() => input.focus());
    };

    (
        modalRoot as HTMLElement & { __openCheckoutEmailModal?: (r: (v: string | null) => void) => void }
    ).__openCheckoutEmailModal = openModal;

    backdrop.addEventListener('click', closeModal);
    closeBtn.addEventListener('click', closeModal);

    input.addEventListener('input', updateSubmitState);
    input.addEventListener('blur', () => {
        if (input.value.trim() && !isValidCheckoutEmail(input.value)) {
            setError('有効なメールアドレスを入力してください。');
        }
    });

    form.addEventListener('submit', (e) => {
        e.preventDefault();
        const normalized = normalizeCheckoutEmail(input.value);
        if (!isValidCheckoutEmail(normalized)) {
            setError('有効なメールアドレスを入力してください。');
            input.focus();
            return;
        }
        finish(normalized);
    });

    document.addEventListener('keydown', (ev: KeyboardEvent) => {
        if (ev.key !== 'Escape' || !modalRoot.classList.contains('checkout-email-modal-root--open')) return;
        ev.preventDefault();
        closeModal();
    });
}

/** Opens the checkout email modal; resolves with normalized email or null if dismissed. */
export function promptCheckoutEmail(): Promise<string | null> {
    const modalRoot = getOrCreateCheckoutEmailModal();
    wireCheckoutEmailModalOnce(modalRoot);
    const opener = (
        modalRoot as HTMLElement & { __openCheckoutEmailModal?: (r: (v: string | null) => void) => void }
    ).__openCheckoutEmailModal;
    return new Promise((resolve) => {
        if (!opener) {
            resolve(null);
            return;
        }
        opener(resolve);
    });
}
