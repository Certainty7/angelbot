import { test, expect } from '@playwright/test';
import { open, sitePages, trackErrors } from './helpers';

test.describe('pages', () => {
  for (const sitePage of sitePages) {
    test(`${sitePage.path} renders in ${sitePage.lang}`, async ({ page }) => {
      const errors = trackErrors(page);
      const response = await open(page, sitePage.path);

      expect(response?.status()).toBe(200);
      await expect(page.locator('html')).toHaveAttribute('lang', sitePage.lang);
      await expect(page.locator('html')).toHaveAttribute('dir', sitePage.dir);
      await expect(page).toHaveTitle(sitePage.title);
      await expect(page.locator('h1')).toHaveCount(1);
      await expect(page.locator('main#main')).toHaveCount(1);

      const canonical = await page.locator('link[rel="canonical"]').getAttribute('href');
      expect(canonical).toBe(`https://angel.aetherisnode.cloud${sitePage.path}`);
      expect(await page.locator('meta[property="og:image"]').getAttribute('content')).toBe(
        'https://angel.aetherisnode.cloud/og-image.png',
      );
      expect(await page.locator('meta[name="twitter:card"]').getAttribute('content')).toBe('summary_large_image');
      expect(await page.locator('link[rel="manifest"]').getAttribute('href')).toBe('/site.webmanifest');
      expect(await page.locator('link[rel="alternate"][hreflang="x-default"]').count()).toBe(1);

      expect(errors).toEqual([]);
    });
  }
});

test('Arabic is native RTL with isolated Latin terms and Arabic typography', async ({ page }) => {
  await open(page, '/');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  // Backticked Latin terms in the copy become <bdi dir="ltr">, never a bare bidi run.
  expect(await page.locator('main bdi[dir="ltr"]').count()).toBeGreaterThan(3);

  const heading = page.locator('.hero__title');
  const style = await heading.evaluate((element) => {
    const computed = getComputedStyle(element);
    return { family: computed.fontFamily, spacing: computed.letterSpacing };
  });
  expect(style.family).toContain('Amiri');
  expect(['normal', '0px']).toContain(style.spacing);
});

test('primary navigation, language switch, invite and footer', async ({ page }) => {
  const errors = trackErrors(page);
  await open(page, '/');

  const nav = page.getByRole('navigation', { name: 'التنقّل الرئيسي' });
  await nav.getByRole('link', { name: 'الأوامر' }).click();
  await expect(page).toHaveURL(/\/commands\/$/);
  await expect(page.locator('h1')).toContainText('كل أمر مسجَّل');

  // The header language switch keeps the reader on the same page in the mirror locale.
  await page.locator('header .lang-switch:visible').click();
  await expect(page).toHaveURL(/\/en\/commands\/$/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');

  await page.locator('header .lang-switch:visible').click();
  await expect(page).toHaveURL(/\/commands\/$/);

  // Every invite link points at the live application, asks for scopes only, and never
  // requests Administrator (bit 3). A mask with that bit is a real security bug.
  const invite = page.locator('header a[href*="discord.com/oauth2/authorize"]').first();
  const href = await invite.getAttribute('href');
  expect(href).toBeTruthy();
  const url = new URL(href as string);
  expect(url.searchParams.get('client_id')).toBe('1559932443102941284');
  expect(url.searchParams.get('scope')).toBe('bot applications.commands');
  const mask = BigInt(url.searchParams.get('permissions') as string);
  expect(mask & 8n).toBe(0n);

  // The footer carries the legal/trust links and the repository.
  await expect(page.locator('footer a[href="https://github.com/Certainty7/angelbot"]')).toHaveCount(1);
  await expect(page.locator('footer a[href$="/privacy/"]').first()).toBeVisible();

  expect(errors).toEqual([]);
});

test('FAQ opens by mouse and by keyboard', async ({ page }) => {
  await open(page, '/faq/');
  const first = page.locator('.faq__item').first();
  await expect(first).not.toHaveAttribute('open', '');
  await first.locator('summary').click();
  await expect(first).toHaveAttribute('open', '');
  await expect(first.locator('.faq__a')).toBeVisible();

  const second = page.locator('.faq__item').nth(1);
  await second.locator('summary').focus();
  await page.keyboard.press('Enter');
  await expect(second).toHaveAttribute('open', '');
});

test('unknown route serves the Arabic 404 with working exits', async ({ page }) => {
  const response = await page.goto('/this-page-does-not-exist/');
  expect(response?.status()).toBe(404);
  await expect(page.locator('html')).toHaveAttribute('lang', 'ar');
  await expect(page.locator('h1')).toContainText('غير موجودة');
  await page.locator('.not-found__actions').getByRole('link', { name: 'الصفحة الرئيسية', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
});

test('the skip link takes focus first', async ({ page }) => {
  await open(page, '/');
  await page.keyboard.press('Tab');
  await expect(page.locator('.skip-link')).toBeFocused();
});

test.describe('without JavaScript', () => {
  test.use({ javaScriptEnabled: false });

  test('the content is complete and visible without an observer', async ({ page }) => {
    const response = await page.goto('/');
    expect(response?.status()).toBe(200);
    await expect(page.locator('.rows').first()).toBeVisible();
    expect(await page.locator('.rows').first().evaluate((element) => getComputedStyle(element).opacity)).toBe('1');
    await expect(
      page.getByRole('navigation', { name: 'التنقّل الرئيسي' }).getByRole('link', { name: 'الأوامر' }),
    ).toBeVisible();

    // The catalogue is server-rendered, never fetched by the client.
    await page.goto('/commands/');
    await expect(page.locator('[data-command]')).toHaveCount(69);
  });
});

test.describe('reduced motion', () => {
  test.use({ reducedMotion: 'reduce' });

  test('the hero and below-fold content settle without animation', async ({ page }) => {
    await open(page, '/');
    await expect(page.locator('.hero__title')).toBeVisible();
    await expect(page.locator('.aperture .sheen')).toBeHidden();
    expect(await page.locator('.hero__line').first().evaluate((element) => getComputedStyle(element).animationName)).toBe(
      'none',
    );
    // Revealed blocks must not depend on an observer when motion is off.
    await expect(page.locator('.rows').first()).toHaveCSS('opacity', '1');
    await expect(page.locator('.rows').first()).toBeVisible();
  });
});
