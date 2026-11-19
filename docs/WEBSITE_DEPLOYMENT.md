# Website deployment — current production path

Last verified: **2026-11-19**.

## 1. What serves what

| FQDN | Served by | Source of the bytes |
|---|---|---|
| `aetherisnode.cloud` | Cloudflare Worker `aetheris-node` | `Certainty7/aetherisnode-home` |
| `www.aetherisnode.cloud` | same Worker | same |
| `angel.aetherisnode.cloud` | **Cloudflare Pages project `angel-site`** | this repository, branch `master` |

The Angel site used to be a manual copy in `Certainty7/angel-web` served by GitHub Pages.
That path is retired and the repository was deleted on 2026-11-19; the Pages project now
builds directly from `angelbot` on every push to `master`.

## 2. Build and deploy

Cloudflare Pages project settings:

| Setting | Value |
|---|---|
| Repository | `Certainty7/angelbot` |
| Production branch | `master` |
| Build command | `bash website/scripts/build.sh` |
| Output directory | `website/dist` |
| Root directory | repository root |
| Build image | v3 (Node 22.23.4, Python 3) |

The build script is the single source of truth. It regenerates `website/src/data/*.json`
from the bot source, refuses stale or non-deterministic data, runs `npm ci && npm run build`,
then guards the output (file count, asset size, no `.env`/database/credential files).

A push to `master` therefore updates the live site with no manual publish step.

> Troubleshooting (2026-11-19): an empty `path_includes` list made Pages skip every push
> with `skip_reason=path_config`. The project now watches `*`; a skipped deployment can be
> retried from the dashboard, or the push can be re-sent after fixing the filter. If a
> deployment shows as skipped, check this setting first.

## 3. Domain and TLS

- DNS: proxied `CNAME` record `angel` → `angel-site-8th.pages.dev` in the
  `aetherisnode.cloud` zone (Cloudflare).
- The Pages custom domain is `angel.aetherisnode.cloud`, status **active**, certificate
  issued by Google Trust Services through Cloudflare Pages.
- `https://` is enforced by the zone's Always Use HTTPS setting.

## 4. Response headers

Cloudflare Pages applies `website/public/_headers`. Measured live on 2026-11-19:

```
strict-transport-security: max-age=31536000; includeSubDomains; preload
content-security-policy: default-src 'self'; script-src 'self'; style-src 'self';
  img-src 'self' data:; font-src 'self'; connect-src 'self'; manifest-src 'self';
  form-action 'none'; frame-ancestors 'none'; base-uri 'none'; object-src 'none';
  upgrade-insecure-requests
x-frame-options: DENY
x-content-type-options: nosniff
referrer-policy: strict-origin-when-cross-origin
cross-origin-opener-policy: same-origin
permissions-policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
```

`_astro/*` is cached `public, max-age=31536000, immutable`; HTML is revalidated.
The GitHub Pages origin never applied these headers — this is the migration T-012
was waiting for.

## 5. Verification

```bash
curl -sI https://angel.aetherisnode.cloud/ | grep -Ei \
  'strict-transport-security|x-frame-options|content-security-policy'
curl -s https://angel.aetherisnode.cloud/ | grep -o 'data-count="[0-9]*"'
curl -sI https://angel.aetherisnode.cloud/privacy/ | head -1
```

Expected: `200 OK`, the three security headers, and `data-count="71"` /
`data-count="14"` on the home page.

The same checks run in CI (`website` workflow) against a local build, plus 67 Playwright
tests covering every page in Arabic and English.

## 6. Rollback

- **Fastest:** Cloudflare dashboard → Pages → `angel-site` → Deployments → previous
  deployment → *Rollback to this deployment*.
- **From code:** `git revert <bad-commit>` and push to `master`; Pages rebuilds.
- **Last resort:** restore the previous deployment from Cloudflare; there is no GitHub Pages
  fallback repository anymore.

## 7. Notes

- The `angel-aetherisnode` Pages project and the `angel-web` publish repository were
  removed on 2026-11-19 after the cutover; `angel-site` is the only Pages project left.
- `aetheris-node` is the Worker that serves the apex and `www`; it is unrelated to the
  Angel site build.
- If a Pages build stays queued for more than a few minutes, trigger a production
  deployment from the Cloudflare dashboard; the build itself is the same command.
