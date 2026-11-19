import { readFileSync } from 'node:fs';
import { test, expect } from '@playwright/test';
import { open, trackErrors } from './helpers';

const commands = JSON.parse(readFileSync('src/data/commands.json', 'utf8')) as {
  totals: { all: number; slash: number; context_menu: number; per_category: Record<string, number> };
  commands: Array<{ owner_only: boolean }>;
};
const total = commands.totals.all;
const ownerCount = commands.commands.filter((c) => c.owner_only).length;

test.describe('command explorer', () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test('renders the full catalogue from the generated JSON', async ({ page }) => {
    const errors = trackErrors(page);
    await open(page, '/commands/');

    await expect(page.locator('[data-command]')).toHaveCount(total);
    await expect(page.locator('[data-visible]')).toHaveText(String(total));
    await expect(page.locator('.block-heading')).toContainText(String(total));
    // 3 message context menus come from the same catalogue, not a hand-written list.
    await expect(page.locator('[data-category="context_menus"]')).toHaveCount(3);

    expect(errors).toEqual([]);
  });

  test('Arabic search normalises letter variants and narrows the list', async ({ page }) => {
    await open(page, '/commands/');
    const search = page.locator('[data-command-search]');

    await search.fill('حظر');
    const visible = await page.locator('[data-command]:visible').count();
    expect(visible).toBeGreaterThan(0);
    expect(visible).toBeLessThan(total);
    await expect(page.locator('[data-command]').filter({ has: page.locator('code.cmd__name', { hasText: /^\/ban$/ }) })).toBeVisible();
    await expect(page.locator('[data-visible]')).toHaveText(String(visible));

    // A different Arabic spelling (أ vs ا) matches the same rows.
    await search.fill('انجل');
    expect(await page.locator('[data-command]:visible').count()).toBeGreaterThan(0);

    await search.fill('zzzz not a command');
    await expect(page.locator('[data-command]:visible')).toHaveCount(0);
    await expect(page.locator('[data-empty]')).toBeVisible();

    await search.press('Escape');
    await expect(page.locator('[data-visible]')).toHaveText(String(total));
    // Owner rows live in the collapsed group by contract.
    await expect(page.locator('[data-command]:visible')).toHaveCount(total - ownerCount);
    await expect(page.locator('[data-empty]')).toBeHidden();
  });

  test('category filter and search compose, and reset cleanly', async ({ page }) => {
    await open(page, '/commands/');
    const music = page.locator('[data-cat="music"]');
    await music.click();
    await expect(music).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('[data-cat="music"]')).toHaveCount(1);
    await expect(page.locator('[data-command]:visible')).toHaveCount(commands.totals.per_category.music);
    for (const row of await page.locator('[data-command]:visible').all()) {
      expect(await row.getAttribute('data-category')).toBe('music');
    }

    await page.locator('[data-command-search]').fill('skip');
    await expect(page.locator('[data-command]:visible')).toHaveCount(1);
    await expect(page.locator('[data-command]:visible .cmd__name')).toHaveText('/skip');

    await page.locator('[data-cat=""]').click();
    await expect(page.locator('[data-command]:visible')).toHaveCount(1);
    await page.locator('[data-command-search]').fill('');
    // Everything back: open rows plus the closed owner group.
    await expect(page.locator('[data-command]:visible')).toHaveCount(total - ownerCount);
    await expect(page.locator('[data-owner-group]')).not.toHaveAttribute('open', '');
  });

  test('rows expand by keyboard, expose permissions, and copy the command', async ({ page }) => {
    const errors = trackErrors(page);
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
    await open(page, '/commands/');

    const ban = page.locator('[data-command]').filter({
      has: page.locator('code.cmd__name', { hasText: /^\/ban$/ }),
    });
    await expect(ban.locator('.badge--perm', { hasText: 'ban_members' })).toBeVisible();

    const summary = ban.locator('summary');
    await summary.focus();
    await page.keyboard.press('Enter');
    await expect(ban.locator('details')).toHaveAttribute('open', '');
    await expect(ban.locator('.cmd__body')).toBeVisible();
    await expect(ban.locator('.cmd__option code', { hasText: 'member' })).toBeVisible();

    const copy = ban.locator('[data-copy]');
    await copy.click();
    await expect(copy.locator('[data-copy-label]')).toHaveText('تم النسخ');
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('/ban');

    // Owner-only commands are marked from the catalogue, not from a static list.
    await page.locator('[data-cat="owner"]').click();
    await expect(page.locator('[data-command]:visible .badge--owner').first()).toBeVisible();

    expect(errors).toEqual([]);
  });
});

test('the built page never prints administrator as a permission', async ({ page }) => {
  await open(page, '/commands/');
  // `administrator` gates the invoking member; showing it beside kick_members would imply the bot
  // requests it at invite time, which is the opposite of what the permissions page states.
  const text = await page.locator('[data-explorer]').innerText();
  expect(text.toLowerCase()).not.toContain('administrator');
});

test.describe('owner tools section', () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test('is a native collapsed group that holds every owner-only command', async ({ page }) => {
    await open(page, '/commands/');
    const group = page.locator('[data-owner-group]');
    await expect(group).toHaveCount(1);
    await expect(group).not.toHaveAttribute('open', '');
    await expect(group.locator('.owner-group__summary')).toContainText('أدوات المالكة');
    await expect(group.locator('[data-command]')).toHaveCount(ownerCount);
    // The rows exist in the DOM while closed: find-in-page and the browser's own search see them.
    await expect(group.locator('[data-command]').first()).toBeAttached();
    // No permission chips here: `administrator` in those rows gates the caller, not the bot.
    await expect(group.locator('.badge--perm')).toHaveCount(0);
    await expect(group.locator('.badge--owner')).toHaveCount(ownerCount);
    await expect(group.locator('.cmd__desc').first()).not.toContainText('للمالكة فقط');
  });

  test('searching an owner command opens the group so the hit is visible', async ({ page }) => {
    await open(page, '/commands/');
    const group = page.locator('[data-owner-group]');
    await page.locator('[data-command-search]').fill('sovereign');
    await expect(group).toHaveAttribute('open', '');
    await expect(group.locator('[data-command]:visible code.cmd__name', { hasText: /^\/sovereign$/ })).toBeVisible();

    await page.locator('[data-command-search]').fill('');
    await expect(group).not.toHaveAttribute('open', '');
  });

  test('the owner filter chip isolates them and the headline states their count', async ({ page }) => {
    await open(page, '/commands/');
    await expect(page.locator('.block-heading')).toContainText(String(total));
    await expect(page.locator('.block-heading')).toContainText(String(ownerCount));
    await page.locator('[data-cat="__owner__"]').click();
    await expect(page.locator('[data-visible]')).toHaveText(String(ownerCount));
    await expect(page.locator('[data-command]:visible')).toHaveCount(ownerCount);
  });
});
