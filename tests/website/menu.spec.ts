import { test, expect } from '@playwright/test';
import { open } from './helpers';

test.describe('mobile navigation', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('the menu opens, closes with Escape and navigates', async ({ page }) => {
    await open(page, '/');
    const toggle = page.locator('[data-menu-toggle]');
    const nav = page.locator('[data-site-nav]');

    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(nav).toBeHidden();

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(nav).toBeVisible();
    await expect(nav.getByRole('link', { name: 'الأوامر' })).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(nav).toBeHidden();
    await expect(toggle).toBeFocused();

    await toggle.click();
    await nav.getByRole('link', { name: 'المزايا' }).click();
    await expect(page).toHaveURL(/\/features\/$/);
    await expect(page.locator('[data-menu-toggle]')).toHaveAttribute('aria-expanded', 'false');
  });
});

test.describe('desktop navigation', () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test('the nav is inline and the menu button is gone', async ({ page }) => {
    await open(page, '/commands/');
    await expect(page.locator('[data-menu-toggle]')).toBeHidden();
    const nav = page.locator('[data-site-nav]');
    await expect(nav).toBeVisible();
    await expect(nav.locator('ul a')).toHaveCount(6);
    await expect(nav.locator('a[aria-current="page"]')).toHaveText('الأوامر');
  });
});
