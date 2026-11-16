/*
 * Theme bootstrap — loaded synchronously in <head> so the stored palette applies
 * before the first paint. Kept as an external file (not inline) so the deployed
 * Content-Security-Policy can stay `script-src 'self'` with no hash to maintain.
 */
(() => {
  const root = document.documentElement;
  root.classList.add('js');
  try {
    const stored = localStorage.getItem('angel-theme');
    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = stored === 'rose-night' || stored === 'dark'
      ? 'rose-night'
      : stored === 'light'
        ? 'light'
        : dark
          ? 'rose-night'
          : 'light';
    root.dataset.theme = theme;
  } catch {
    root.dataset.theme = 'light';
  }
})();
