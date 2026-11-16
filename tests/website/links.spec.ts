import { expect, test } from '@playwright/test';

/**
 * Every internal link the site ships must resolve.
 *
 * This exists because of a real defect: the 404 pages passed their own slug into the header's
 * language switch, so `/en/404/` linked to `/404/` — a path the build never emits. Nothing failed,
 * because no test followed links; the page looked perfect and the link was dead. Collect the hrefs
 * the browser actually sees, then ask the server for each one.
 */
const pages = ['/', '/features/', '/commands/', '/permissions/', '/how-it-works/', '/security/', '/privacy/', '/faq/', '/changelog/', '/en/'];

test('every internal link resolves', async ({ page, request }) => {
  const seen = new Set<string>();
  for (const path of pages) {
    await page.goto(path);
    const hrefs = await page.locator('a[href]').evaluateAll((nodes) =>
      nodes.map((node) => (node as HTMLAnchorElement).getAttribute('href') ?? ''),
    );
    for (const href of hrefs) {
      if (!href || href.startsWith('#')) continue;
      if (href.startsWith('http') && !href.startsWith('https://angel.aetherisnode.cloud')) continue;
      if (href.startsWith('mailto:') || href.startsWith('tel:')) continue;
      const url = href.startsWith('https://angel.aetherisnode.cloud')
        ? new URL(href).pathname + new URL(href).search
        : href;
      seen.add(url);
    }
  }

  expect(seen.size).toBeGreaterThan(10);
  const broken: string[] = [];
  for (const url of [...seen].sort()) {
    const response = await request.get(url);
    if (response.status() >= 400) broken.push(`${response.status()} ${url}`);
  }
  expect(broken).toEqual([]);
});

test('no advertised URL is one Cloudflare Pages redirects', async ({ page }) => {
  // Pages redirects `/x.html` to `/x` with a 308, so a canonical or hreflang that ends in .html
  // points at a redirect instead of the document. Measured on the live preview: /404.html -> 308.
  for (const path of [...pages, '/404.html', '/en/404/']) {
    await page.goto(path);
    const advertised = await page
      .locator('link[rel="canonical"], link[rel="alternate"][hreflang]')
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('href') ?? ''));
    for (const href of advertised) {
      expect(href, `${path} advertises ${href}`).not.toMatch(/\.html$/);
    }
  }
});

test('x-default names the same served path on both locales', async ({ page }) => {
  // The 404 cluster used to advertise /404/ (308 on Pages) and /en/404/ from the English page, so the
  // two locales disagreed about the default document. One path, served with 200, on both.
  const seen: Record<string, string> = {};
  for (const [lang, path] of [['ar', '/404.html'], ['en', '/en/404/']]) {
    await page.goto(path);
    const href = await page.locator('link[rel="alternate"][hreflang="x-default"]').getAttribute('href');
    expect(href, path).toBeTruthy();
    const { pathname } = new URL(href!);
    expect(pathname, path).not.toMatch(/\.html$/);
    expect(pathname, path).not.toMatch(/\/404\/$/);
    if (lang === 'en') expect(pathname).toBe(seen.ar);
    seen[lang] = pathname;
  }
});
