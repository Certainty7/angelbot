# Website security — what is enforced on the live host

Last verified: **2026-11-25** against `https://angel.aetherisnode.cloud` (v1.1.0).

The Angel site is served by a **managed static host** from this repository's `master`
branch. The previous GitHub Pages origin applied no custom response headers; that limitation
no longer applies.

## 1. Measured response headers

`curl -sI https://angel.aetherisnode.cloud/` returns:

| Header | Value |
|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` |
| `Content-Security-Policy` | `default-src 'self'`; no inline script/style; `frame-ancestors 'none'`; `base-uri 'none'`; `object-src 'none'`; `upgrade-insecure-requests` |
| `X-Frame-Options` | `DENY` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Cross-Origin-Opener-Policy` | `same-origin` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=(), usb=()` |

Caching: `_astro/*` is `public, max-age=31536000, immutable`; HTML is
`max-age=0, must-revalidate`. The source of these rules is `website/public/_headers`,
which the static host honours.

## 2. What is enforced

- **CSP** is a real response header now, so `frame-ancestors` and
  `upgrade-insecure-requests` are enforced (a `<meta>` CSP cannot express them).
- **TLS**: host-managed certificate for the public domain, HTTP redirected to HTTPS.
- **No state, no tracking**: no cookies, no analytics, no third-party requests. The only
  client storage is the theme preference in `localStorage`.
- **No secrets in the published bytes**: the build script fails on `.env*`, `*.pem`,
  `*.key`, `*.sqlite*`, `*.db`, `.git` and `node_modules` inside `website/dist`.
- **Supply chain**: the Pages build runs `bash website/scripts/build.sh` from this
  repository; the CI workflow is pinned to commit SHAs and holds no deploy token.

## 3. Residual risks

| Risk | Impact | Mitigation |
|---|---|---|
| Public static content can be mirrored | None beyond what is already public | Content is marketing copy; no member data |
| Hosting account compromise | Site defacement | Account-level 2FA and scoped tokens (owner action) |
| The `_headers` file is only as good as the host | If the site moves back to GitHub Pages, headers silently disappear | `docs/WEBSITE_DEPLOYMENT.md` records the current host and verification command |

## 4. Verification

```bash
curl -sI https://angel.aetherisnode.cloud/ | grep -Ei \
  'strict-transport-security|x-frame-options|content-security-policy|cross-origin-opener-policy'
```

This is the command CI cannot run against production; run it after any DNS or hosting
change.
