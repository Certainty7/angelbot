const THEME_KEY = 'angel-theme';
const root = document.documentElement;

type Theme = 'light' | 'rose-night';

function currentTheme(): Theme {
  return root.dataset.theme === 'rose-night' || root.dataset.theme === 'dark' ? 'rose-night' : 'light';
}

function syncThemeUi(): void {
  const dark = currentTheme() === 'rose-night';
  for (const button of document.querySelectorAll<HTMLButtonElement>('[data-theme-toggle]')) {
    button.setAttribute('aria-pressed', String(dark));
    const label = dark ? button.dataset.labelLight : button.dataset.labelDark;
    if (label) button.setAttribute('aria-label', label);
  }
  const meta = document.querySelector<HTMLMetaElement>('meta[data-theme-color]');
  if (meta) meta.content = dark ? '#14100F' : '#FDFBFA';
}

function setTheme(theme: Theme, persist: boolean): void {
  root.dataset.theme = theme;
  if (persist) {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage can be unavailable; the theme still applies for this page */
    }
  }
  syncThemeUi();
}

function setupTheme(): void {
  syncThemeUi();
  for (const button of document.querySelectorAll<HTMLButtonElement>('[data-theme-toggle]')) {
    button.addEventListener('click', () => {
      setTheme(currentTheme() === 'rose-night' ? 'light' : 'rose-night', true);
    });
  }
}

function setupMenu(): void {
  const header = document.querySelector<HTMLElement>('[data-site-header]');
  const toggle = header?.querySelector<HTMLButtonElement>('[data-menu-toggle]');
  const nav = header?.querySelector<HTMLElement>('[data-site-nav]');
  if (!header || !toggle || !nav) return;

  const label = toggle.querySelector<HTMLElement>('[data-menu-label]');
  const setOpen = (open: boolean): void => {
    header.toggleAttribute('data-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    const text = open ? toggle.dataset.labelClose : toggle.dataset.labelOpen;
    if (text) {
      toggle.setAttribute('aria-label', text);
      if (label) label.textContent = text;
    }
  };

  setOpen(false);
  toggle.addEventListener('click', () => setOpen(!header.hasAttribute('data-open')));
  for (const link of nav.querySelectorAll('a')) {
    link.addEventListener('click', () => setOpen(false));
  }
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && header.hasAttribute('data-open')) {
      setOpen(false);
      toggle.focus();
    }
  });
  document.addEventListener('click', (event) => {
    if (header.hasAttribute('data-open') && event.target instanceof Node && !header.contains(event.target)) {
      setOpen(false);
    }
  });
  window.matchMedia('(min-width: 900px)').addEventListener('change', (event) => {
    if (event.matches) setOpen(false);
  });
}

function setupReveal(): void {
  const items = document.querySelectorAll<HTMLElement>('[data-reveal]');
  if (!items.length) return;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduced || !('IntersectionObserver' in window)) {
    for (const item of items) item.classList.add('is-in');
    return;
  }
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add('is-in');
        observer.unobserve(entry.target);
      }
    },
    { rootMargin: '0px 0px -8% 0px', threshold: 0.12 },
  );
  for (const item of items) observer.observe(item);
}

function setupCounters(): void {
  const nodes = document.querySelectorAll<HTMLElement>('[data-count]');
  if (!nodes.length) return;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduced || !('IntersectionObserver' in window)) return;

  const run = (el: HTMLElement): void => {
    const target = Number(el.dataset.count || '0');
    if (!Number.isFinite(target) || target === 0) return;
    const started = performance.now();
    const tick = (now: number): void => {
      const progress = Math.min(1, (now - started) / 900);
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = String(Math.round(target * eased));
      if (progress < 1) requestAnimationFrame(tick);
      else el.textContent = String(target);
    };
    el.textContent = '0';
    requestAnimationFrame(tick);
    // If the tab is backgrounded the rAF loop can stall; the printed value must still land.
    window.setTimeout(() => {
      el.textContent = String(target);
    }, 1400);
  };

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        run(entry.target as HTMLElement);
        observer.unobserve(entry.target);
      }
    },
    { threshold: 0.4 },
  );
  for (const node of nodes) observer.observe(node);
}

export function initSite(): void {
  setupTheme();
  setupMenu();
  setupReveal();
  setupCounters();
}
