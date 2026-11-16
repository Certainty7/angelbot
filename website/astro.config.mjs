// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// Static site: `astro build` writes website/dist, which is what Cloudflare Pages publishes.
// No adapter, no SSR, no server runtime — the site must be safe to leave online unattended.
export default defineConfig({
  site: 'https://angel.aetherisnode.cloud',
  output: 'static',
  trailingSlash: 'always',
  // Arabic is the primary locale and lives at the root; English is mirrored under /en/.
  i18n: {
    defaultLocale: 'ar',
    locales: ['ar', 'en'],
    routing: { prefixDefaultLocale: false },
  },
  integrations: [sitemap({ filter: (page) => !page.includes('/404') })],
  build: {
    format: 'directory',
    // External stylesheets keep the deployed Content-Security-Policy free of
    // `style-src 'unsafe-inline'`.
    inlineStylesheets: 'never',
  },
  compressHTML: true,
  // Astro inlines scripts under Vite's asset limit; inlining would force a CSP hash
  // (or 'unsafe-inline'). Keeping every script external lets `script-src 'self'` hold.
  vite: { build: { assetsInlineLimit: 0 } },
});
