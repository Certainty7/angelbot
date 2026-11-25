# Website deployment — public overview

Last verified: **2026-11-25** (v1.1.0).

## 1. What serves the site

The Angel site is a static Astro build of `website/`, produced by
`bash website/scripts/build.sh` and published to a managed static host.
The public URL is `https://angel.aetherisnode.cloud`.

The host project, DNS records, account settings, build filters and deployment tokens are
**operator-managed** and are deliberately not recorded in this public repository. Keep the
private runbook outside the repository.

## 2. Build and deploy

- Build command: `bash website/scripts/build.sh` from the repository root.
- Output directory: `website/dist`.
- The build script regenerates `website/src/data/*.json` from the bot source, refuses stale or
  non-deterministic data, runs `npm ci && npm run build`, then guards the output (file count,
  asset size, no `.env`/database/credential files).
- A push to `master` triggers the host's production build. The operator configures the branch,
  project and path filter in the host dashboard.
- If a deployment is skipped, check the host's path filter first. A filter that does not match
  the changed paths skips the build; correct it in the dashboard, then trigger a production
  deployment.

## 3. Domain and TLS

The public domain is `https://angel.aetherisnode.cloud`. DNS and TLS certificates are managed
by the host; the zone and account settings stay private to the operator.

## 4. Response headers

The static host applies `website/public/_headers`. Measured live on 2026-11-19:

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

## 5. Verification

```bash
curl -sI https://angel.aetherisnode.cloud/ | grep -Ei \
  'strict-transport-security|x-frame-options|content-security-policy'
curl -s https://angel.aetherisnode.cloud/ | grep -o 'data-count="[0-9]*"'
curl -sI https://angel.aetherisnode.cloud/privacy/ | head -1
```

Expected: `200 OK`, the security headers, and `data-count="71"` / `data-count="14"` on the
home page.

The same checks run in CI (`website` workflow) against a local build, plus 67 Playwright
tests covering every page in Arabic and English.

## 6. Rollback

- **Fastest:** use the host dashboard to roll production back to the previous successful
  deployment.
- **From code:** `git revert <bad-commit>` and push to `master`; the host rebuilds.

## 7. Notes

- The build is static: no application server, no database, no deploy token in the workflows.
- Keep account-specific runbooks, project names and DNS records in the operator's private
  notes rather than this repository.
