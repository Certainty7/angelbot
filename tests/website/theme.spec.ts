import { test, expect } from '@playwright/test';
import { open } from './helpers';

test('theme toggles, persists across reloads and updates the address bar colour', async ({ page }) => {
  await open(page, '/');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(253, 251, 250)');

  const toggle = page.locator('[data-theme-toggle]');
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await toggle.click();

  await expect(page.locator('html')).toHaveAttribute('data-theme', 'rose-night');
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(20, 16, 15)');
  expect(await page.evaluate(() => localStorage.getItem('angel-theme'))).toBe('rose-night');
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  expect(await page.locator('meta[data-theme-color]').getAttribute('content')).toBe('#14100F');

  // The next document paints the stored theme before first paint.
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'rose-night');
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(20, 16, 15)');

  await toggle.click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  expect(await page.evaluate(() => localStorage.getItem('angel-theme'))).toBe('light');
});

test('the system preference is the default when nothing is stored', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await open(page, '/');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'rose-night');
});

test('a stored preference wins over the system preference', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('angel-theme', 'light'));
  await page.emulateMedia({ colorScheme: 'dark' });
  await open(page, '/');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
});
