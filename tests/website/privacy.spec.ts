import { test, expect } from '@playwright/test';
import { open, sitePages } from './helpers';

// The site is static and self-hosted: no analytics, no CDN fonts, no third-party calls,
// and no cookies. This test fails if a dependency ever phones home.
test('no third-party requests and no cookies on any page', async ({ page, context }) => {
  const foreign: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.protocol === 'data:' || url.protocol === 'blob:') return;
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) foreign.push(request.url());
  });

  for (const sitePage of sitePages) {
    await open(page, sitePage.path);
  }

  expect(foreign).toEqual([]);
  expect(await context.cookies()).toEqual([]);
  expect(await page.evaluate(() => document.cookie)).toBe('');
});
