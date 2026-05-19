/**
 * Mobile sidebar drawer — open/close and overlay handling.
 */

export function isMobileNavViewport(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches;
}

export function closeMobileSidebar(): void {
  document.getElementById('sidebar')?.classList.remove('active');
  document.getElementById('mobile-overlay')?.classList.remove('active');
  document.body.classList.remove('mobile-nav-open');
  const btn = document.getElementById('mobile-menu-btn');
  btn?.setAttribute('aria-expanded', 'false');
  btn?.setAttribute('aria-label', 'Open menu');
}

export function openMobileSidebar(): void {
  document.getElementById('sidebar')?.classList.add('active');
  document.getElementById('mobile-overlay')?.classList.add('active');
  document.body.classList.add('mobile-nav-open');
  const btn = document.getElementById('mobile-menu-btn');
  btn?.setAttribute('aria-expanded', 'true');
  btn?.setAttribute('aria-label', 'Close menu');
}

export function toggleMobileSidebar(): void {
  const sidebar = document.getElementById('sidebar');
  if (sidebar?.classList.contains('active')) {
    closeMobileSidebar();
  } else {
    openMobileSidebar();
  }
}

let globalMobileNavHooksBound = false;

/** Bind hamburger + overlay for the current dashboard shell. */
export function bindMobileSidebarControls(): void {
  const btn = document.getElementById('mobile-menu-btn');
  const overlay = document.getElementById('mobile-overlay');

  if (btn && btn.dataset.mobileNavBound !== 'true') {
    btn.dataset.mobileNavBound = 'true';
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleMobileSidebar();
    });
  }

  if (overlay && overlay.dataset.mobileNavBound !== 'true') {
    overlay.dataset.mobileNavBound = 'true';
    overlay.addEventListener('click', () => {
      closeMobileSidebar();
    });
  }

  if (globalMobileNavHooksBound) return;
  globalMobileNavHooksBound = true;

  window.addEventListener('resize', () => {
    if (!isMobileNavViewport()) {
      closeMobileSidebar();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeMobileSidebar();
    }
  });
}
