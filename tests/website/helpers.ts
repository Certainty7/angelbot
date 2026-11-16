import { expect, type Page } from '@playwright/test';

export type SitePage = { path: string; lang: 'ar' | 'en'; dir: 'rtl' | 'ltr'; title: RegExp };

export const sitePages: SitePage[] = [
  { path: '/', lang: 'ar', dir: 'rtl', title: /أنجل/ },
  { path: '/features/', lang: 'ar', dir: 'rtl', title: /المزايا/ },
  { path: '/commands/', lang: 'ar', dir: 'rtl', title: /الأوامر/ },
  { path: '/permissions/', lang: 'ar', dir: 'rtl', title: /الصلاحيات/ },
  { path: '/how-it-works/', lang: 'ar', dir: 'rtl', title: /كيف يعمل/ },
  { path: '/security/', lang: 'ar', dir: 'rtl', title: /الأمان/ },
  { path: '/privacy/', lang: 'ar', dir: 'rtl', title: /الخصوصية/ },
  { path: '/faq/', lang: 'ar', dir: 'rtl', title: /الأسئلة/ },
  { path: '/changelog/', lang: 'ar', dir: 'rtl', title: /سجل التغييرات/ },
  { path: '/en/', lang: 'en', dir: 'ltr', title: /Angel/ },
  { path: '/en/features/', lang: 'en', dir: 'ltr', title: /Features/ },
  { path: '/en/commands/', lang: 'en', dir: 'ltr', title: /Commands/ },
  { path: '/en/permissions/', lang: 'en', dir: 'ltr', title: /Permissions/ },
  { path: '/en/how-it-works/', lang: 'en', dir: 'ltr', title: /How it works/ },
  { path: '/en/security/', lang: 'en', dir: 'ltr', title: /Security/ },
  { path: '/en/privacy/', lang: 'en', dir: 'ltr', title: /Privacy/ },
  { path: '/en/faq/', lang: 'en', dir: 'ltr', title: /FAQ/ },
  { path: '/en/changelog/', lang: 'en', dir: 'ltr', title: /Changelog/ },
];

/** Collects real console errors and uncaught page errors for a flow. */
export function trackErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  page.on('pageerror', (error) => errors.push(error.message));
  return errors;
}

export async function open(page: Page, path: string) {
  const response = await page.goto(path, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready.then(() => true));
  return response;
}

export async function expectNoOverflow(page: Page): Promise<void> {
  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(metrics.scrollWidth, `horizontal overflow: ${metrics.scrollWidth} > ${metrics.clientWidth}`).toBeLessThanOrEqual(
    metrics.clientWidth + 1,
  );
}
