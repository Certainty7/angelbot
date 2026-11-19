import { readFileSync } from 'node:fs';
import { test, expect } from '@playwright/test';
import { expectNoOverflow, open, trackErrors } from './helpers';

const changelog = JSON.parse(readFileSync('../website/src/data/changelog.json', 'utf8')) as {
  releases: {
    version: string;
    date: string;
    summary: { ar: string; en: string };
    sections: { title: { ar: string; en: string }; items: { ar: string; en: string }[] }[];
  }[];
};

const latest = changelog.releases[0];

test.describe('changelog', () => {
  test('renders every release from the generated data in Arabic', async ({ page }) => {
    const errors = trackErrors(page);
    await open(page, '/changelog/');

    await expect(page.locator('[data-release]')).toHaveCount(changelog.releases.length);
    const first = page.locator('[data-release]').first();
    await expect(first).toHaveAttribute('data-version', latest.version);
    await expect(first.locator('.release__tag')).toHaveText(`v${latest.version}`);
    await expect(first.locator('.release__date')).toHaveAttribute('datetime', latest.date);
    await expect(first.locator('.release__summary')).toHaveText(latest.summary.ar);
    await expect(first.locator('.release__section')).toHaveCount(latest.sections.length);
    await expectNoOverflow(page);
    expect(errors).toEqual([]);
  });

  test('offers the release sections wide enough to read on desktop', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await open(page, '/changelog/');
    const box = await page.locator('[data-release]').first().boundingBox();
    expect(box?.width ?? 0).toBeGreaterThan(600);
    const firstList = page.locator('.release__list').first();
    await expect(firstList.locator('li').first()).toBeVisible();
    await expect(firstList).toBeInViewport();
  });

  test('stays readable without horizontal overflow on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page, '/changelog/');
    await expect(page.locator('[data-release]').first()).toBeVisible();
    await expectNoOverflow(page);
    const box = await page.locator('.release__summary').first().boundingBox();
    expect(box?.width ?? 0).toBeGreaterThan(280);
  });

  test('renders the English release summary on /en/', async ({ page }) => {
    await open(page, '/en/changelog/');
    const first = page.locator('[data-release]').first();
    await expect(first.locator('.release__summary')).toHaveText(latest.summary.en);
    await expect(first.locator('.release__link')).toBeVisible();
    await expectNoOverflow(page);
  });
});
