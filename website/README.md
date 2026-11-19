# Angel website

Static, Arabic-first site for the Angel Discord bot. Astro 7 + TypeScript, no adapter, no
runtime backend, no client tracking.

```
website/
  src/
    pages/        route files (AR at the root, EN under /en/)
    layouts/      Base.astro — head, theme boot, header/footer
    components/   Hero, Header, Footer, Blocks, CommandExplorer, …
    i18n/         ui.ts (labels), content.ts (every page, AR + EN), permission-notes.ts
    data/         commands.json, invite.json (generated), changelog.json
    styles/       fonts.css → tokens.css → base.css → site.css
    scripts/      site.ts (theme, menu, reveals), commands.ts (search/filter/copy)
    assets/brand/ the identity artwork (the design owner, WEB-1)
  public/         fonts, icons, robots.txt, manifest, _headers
  scripts/        build.sh (Pages entry point), changelog.mjs
```

## Commands

```bash
cd website
npm ci
npm run dev        # local dev server
npm run build      # astro build → dist/
npm run preview    # serve dist/
npm run typecheck  # astro check
npm run test:e2e   # Playwright, Chromium only, serves dist/ itself
npm run changelog   # refresh src/data/changelog.json from `git log`
```

The deploy path is **`bash website/scripts/build.sh`** from the repository root — the exact
Cloudflare Pages command. It runs the data generator, `npm ci`, the build, then the publish-output
guards. CI runs the same script; do not add a second build path.

In this development container Playwright browsers live outside the repo, so point the runner at them:

```bash
PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright" npm run test:e2e
```

The suite lives in `tests/website/` (outside this package), so `test:e2e` sets `NODE_PATH` to this
directory's `node_modules`; that is why the npm script is not a bare `playwright test`.

## Data and accuracy

- `src/data/commands.json` and `invite.json` are generated from `cogs/`, `bot.py` and
  `angel/client.py` by `tools/website-data-generator/generate.py`. Never hand-edit them: the
  build regenerates and fails on a one-byte difference.
- The command explorer renders the JSON at build time; the client script only filters the DOM.
- `changelog.json` is a snapshot of real `git log` history; refresh it with `npm run changelog`
  when the page should move forward.
- No invented counts, testimonials or uptime claims. The only numbers on the site come from the
  catalogue (`68` registered, `65` slash, `3` context menus) and the invite mask.

## Design system

`tokens.css`, `base.css` and `src/assets/brand/` are owned by the design system
(`docs/DESIGN_SYSTEM.md`, WEB-1). This package composes them in `site.css`; it does not
redefine palette values. Page copy lives in `src/i18n/content.ts` as `{ ar, en }` pairs.

Arabic is the document language: `dir="rtl"` on `<html>`, logical CSS properties, and inline Latin
terms wrapped as `<bdi dir="ltr">` by the content formatter (`src/lib/inline.ts`).

## Themes and motion

The theme is applied before first paint by `public/theme-init.js` (external, so the CSP stays
`script-src 'self'` without a hash) from `localStorage` → `prefers-color-scheme` → light.
Every animation is CSS or IntersectionObserver-based; `prefers-reduced-motion: reduce` removes
entrance animations, hides the hero sheen, and renders revealed content in its final state.
Content is visible with JavaScript disabled — the observer only *adds* motion.

## Content Security Policy

`public/_headers` ships a strict CSP (`default-src 'self'`, no `unsafe-inline`). Two build
settings keep it valid: `build.inlineStylesheets: 'never'` and `vite.build.assetsInlineLimit: 0`
so Astro never inlines a stylesheet or a script. Do not add inline `style=` attributes or inline
scripts without updating the policy; `public/theme-init.js` is the only hand-written client file.
