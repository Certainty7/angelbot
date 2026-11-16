import { test, expect } from '@playwright/test';
import { expectNoOverflow, open } from './helpers';

const widths = [360, 390, 768, 1024, 1280, 1440, 1920];
const themes = ['light', 'rose-night'] as const;
const paths = ['/', '/commands/', '/en/'];

for (const theme of themes) {
  for (const width of widths) {
    test(`${theme} at ${width}px`, async ({ page }) => {
      await page.addInitScript((value) => localStorage.setItem('angel-theme', value), theme);
      await page.setViewportSize({ width, height: 900 });

      for (const path of paths) {
        await open(page, path);
        await expectNoOverflow(page);
        await expect(page.locator('h1')).toBeVisible();
        await expect(page.locator('.site-header')).toBeVisible();
        await expect(page.locator('html')).toHaveAttribute('data-theme', theme);

        const toggle = page.locator('[data-theme-toggle]');
        await expect(toggle).toBeVisible();
        const box = await toggle.boundingBox();
        expect(box?.width).toBeGreaterThanOrEqual(44);
        expect(box?.height).toBeGreaterThanOrEqual(44);

        if (width < 900) {
          await expect(page.locator('[data-menu-toggle]')).toBeVisible();
        } else {
          await expect(page.locator('[data-menu-toggle]')).toBeHidden();
          await expect(page.locator('[data-site-nav]')).toBeVisible();
        }
      }

      await open(page, '/');
      const body = await page.locator('body').evaluate((element) => getComputedStyle(element).backgroundColor);
      expect(body).toBe(theme === 'light' ? 'rgb(253, 251, 250)' : 'rgb(20, 16, 15)');

      if (width === 1920) {
        const container = await page.locator('main .container').first().evaluate((element) => element.getBoundingClientRect().width);
        expect(container).toBeLessThanOrEqual(1400);
        const hero = await page.locator('.hero__grid').evaluate((element) => getComputedStyle(element).maxInlineSize ?? '');
        expect(hero).toBeTruthy();
      }
    });
  }
}

test('the hero stacks the aperture first on mobile and side-by-side on desktop', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await open(page, '/');
  const mobileObject = await page.locator('.hero__object').boundingBox();
  const mobileAperture = await page.locator('.aperture').boundingBox();
  const mobileText = await page.locator('.hero__col').boundingBox();
  expect(mobileObject!.y).toBeLessThan(mobileText!.y);
  expect(mobileAperture!.width).toBeLessThanOrEqual(240);

  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, '/');
  const object = await page.locator('.hero__object').boundingBox();
  const text = await page.locator('.hero__col').boundingBox();
  // RTL: text on the right, aperture on the left, with a real gutter between them.
  expect(text!.x).toBeGreaterThan(object!.x + object!.width);
  expect(text!.x - (object!.x + object!.width)).toBeGreaterThanOrEqual(48);
  expect(object!.width).toBeLessThanOrEqual(520);
});

// The headline is a design invariant, not a screenshot: the Arabic takes two lines and the English
// three at every desktop width, using the brand face. Both halves matter - a fallback font keeps the
// page working and quietly destroys the identity, and a token change can add a line without any
// element disappearing or overflowing.
test.describe('hero headline shape', () => {
  const cases = [
    { lang: 'ar', path: '/', lines: 2, face: 'amiri', check: '700 68px "Amiri"' },
    { lang: 'en', path: '/en/', lines: 3, face: 'instrument serif', check: '400 72px "Instrument Serif"' },
  ] as const;

  for (const item of cases) {
    for (const width of [1024, 1280, 1440]) {
      test(`${item.lang} stays ${item.lines} lines at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await open(page, item.path);
        await page.evaluate(() => document.fonts.ready);

        const shape = await page.locator('.hero__title').evaluate((element) => {
          const style = getComputedStyle(element);
          const lineHeight = Number.parseFloat(style.lineHeight);
          const rect = element.getBoundingClientRect();
          return {
            lines: Math.round(rect.height / lineHeight),
            family: style.fontFamily.toLowerCase(),
          };
        });

        expect(shape.lines).toBe(item.lines);
        expect(shape.family).toContain(item.face);
        expect(await page.evaluate((font) => document.fonts.check(font), item.check)).toBe(true);
      });
    }
  }
});
