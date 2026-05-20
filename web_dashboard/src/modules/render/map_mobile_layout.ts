/**
 * Mobile Global Map layout — collapsed entity list, resize invalidation.
 */

const MAP_LIST_PANEL_SEL = '[data-map-list-panel]';
const MAP_LIST_BODY_ID = 'map-node-list-body';
const MAP_LIST_TOGGLE_SEL = '[data-map-list-toggle]';
const MAP_LIST_LABEL_SEL = '[data-map-list-toggle-label]';

export function isMobileMapViewport(): boolean {
    return typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches;
}

export function getMapNodeListBody(container?: ParentNode | null): HTMLElement | null {
    const root = container ?? document;
    return root.querySelector<HTMLElement>(`#${MAP_LIST_BODY_ID}`);
}

function setListExpanded(
    panel: HTMLElement,
    body: HTMLElement,
    toggle: HTMLButtonElement,
    label: HTMLElement | null,
    expanded: boolean,
): void {
    panel.classList.toggle('map-node-list-panel--collapsed', !expanded);
    if (expanded) {
        body.removeAttribute('hidden');
        toggle.setAttribute('aria-expanded', 'true');
        if (label) label.textContent = '− Collapse List';
        panel.setAttribute('data-map-user-expanded', '1');
    } else {
        body.setAttribute('hidden', '');
        toggle.setAttribute('aria-expanded', 'false');
        if (label) label.textContent = '+ Expand List';
        panel.removeAttribute('data-map-user-expanded');
    }
}

/** Apply mobile vs desktop panel state (respects user expand on mobile). */
export function applyMobileMapLayout(container: HTMLElement, onInvalidate?: () => void): void {
    const shell = container.querySelector('.map-page-shell');
    const panel = container.querySelector<HTMLElement>(MAP_LIST_PANEL_SEL);
    const body = getMapNodeListBody(container);
    const toggle = container.querySelector<HTMLButtonElement>(MAP_LIST_TOGGLE_SEL);
    const label = container.querySelector<HTMLElement>(MAP_LIST_LABEL_SEL);

    if (!panel || !body || !toggle) return;

    const mobile = isMobileMapViewport();
    shell?.classList.toggle('map-page-shell--mobile', mobile);

    if (mobile) {
        const userExpanded = panel.getAttribute('data-map-user-expanded') === '1';
        setListExpanded(panel, body, toggle, label, userExpanded);
    } else {
        panel.classList.remove('map-node-list-panel--collapsed');
        panel.removeAttribute('data-map-user-expanded');
        body.removeAttribute('hidden');
        toggle.setAttribute('aria-expanded', 'true');
        if (label) label.textContent = 'Entity List';
    }

    onInvalidate?.();
}

let mobileMapLayoutBound = false;
let mobileMapResizeObserver: ResizeObserver | undefined;

export function wireMobileMapLayout(
    container: HTMLElement,
    onInvalidate: () => void,
): void {
    const panel = container.querySelector<HTMLElement>(MAP_LIST_PANEL_SEL);
    const toggle = container.querySelector<HTMLButtonElement>(MAP_LIST_TOGGLE_SEL);

    if (toggle && panel && toggle.dataset.mobileMapBound !== 'true') {
        toggle.dataset.mobileMapBound = 'true';
        toggle.addEventListener('click', () => {
            const body = getMapNodeListBody(container);
            const label = container.querySelector<HTMLElement>(MAP_LIST_LABEL_SEL);
            if (!body) return;

            const willExpand = panel.classList.contains('map-node-list-panel--collapsed');
            setListExpanded(panel, body, toggle, label, willExpand);

            window.requestAnimationFrame(() => {
                window.requestAnimationFrame(onInvalidate);
            });
        });
    }

    if (!mobileMapLayoutBound) {
        mobileMapLayoutBound = true;
        const mq = window.matchMedia('(max-width: 768px)');
        const onMq = () => {
            const mapContainer = document.getElementById('map-page-container');
            if (mapContainer && mapContainer.style.display !== 'none') {
                applyMobileMapLayout(mapContainer, onInvalidate);
            }
        };
        mq.addEventListener('change', onMq);
        window.addEventListener('orientationchange', () => {
            window.setTimeout(onMq, 100);
        });
    }

    if (typeof ResizeObserver !== 'undefined') {
        mobileMapResizeObserver?.disconnect();
        mobileMapResizeObserver = new ResizeObserver(() => {
            if (!isMobileMapViewport()) return;
            if (container.style.display === 'none') return;
            onInvalidate();
        });
        mobileMapResizeObserver.observe(container);
        const mapEl = container.querySelector('#map-instance');
        if (mapEl) mobileMapResizeObserver.observe(mapEl);
    }

    applyMobileMapLayout(container, onInvalidate);
}
