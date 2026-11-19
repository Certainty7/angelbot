# Website security — what is actually enforced on the live host

> **2026-11-19 update (T-012):** `website/public/_headers` now carries HSTS,
> `X-Frame-Options: DENY`, COOP, Permissions-Policy and the full CSP. Those headers apply
> only on a host that honours the Cloudflare Pages `_headers` convention. Until the Pages
> cutover is done, the measurements below still describe the GitHub Pages origin.
> Verify after cutover with:
> `curl -sI https://angel.aetherisnode.cloud | grep -Ei 'strict-transport-security|x-frame-options|content-security-policy'`.

Owner: infrastructure. Measured **2026-11-15, 11:05–11:30 UTC** with `curl
-D -`, a full TLS handshake per name, and the GitHub REST API. This file records measured behaviour
only. It is deliberately hostile to claims made elsewhere in the docs: if a header is not in the
response, it is not in this file.

Scope: the two production names — `https://aetherisnode.cloud` (portal) and
`https://angel.aetherisnode.cloud` (Angel site) — plus `www.aetherisnode.cloud`. The bot host is out of
scope here.

## 1. Measured response headers

`HTTP/2 200` on `https://angel.aetherisnode.cloud/`:

```
server: GitHub.com
content-type: text/html; charset=utf-8
last-modified: Sun, 15 Nov 2026 18:20:30 GMT
access-control-allow-origin: *
etag: "6af9f7ee-3cb5"
expires: …  cache-control: max-age=600
x-proxy-cache: MISS  x-served-by: cache-par-…  x-cache: HIT  age: 0  via: 1.1 varnish
vary: Accept-Encoding    accept-ranges: bytes
```

`etag` here is a deploy marker: the root's bytes were unchanged between two publishes while its `etag`
moved `"6af99fe1-3cb5"` → `"6af9f7ee-3cb5"`. Gate on `sha256` of the live document, never on `etag`.

`https://aetherisnode.cloud/` returns the same shape (`etag`, `cache-control: max-age=600`,
`server: GitHub.com`). **Absent on all three names**, checked explicitly:

| Header | Present? | Consequence |
|---|---|---|
| `Content-Security-Policy` | **no** (a `<meta http-equiv>` exists instead) | CSP enforced after HTML parse, cannot express `frame-ancestors` |
| `Strict-Transport-Security` | **no** | first request in a session can still be downgraded; no HSTS preload |
| `X-Frame-Options` | **no** | clickjacking protection rests on `frame-ancestors`, which a meta CSP cannot set → **no framing protection at all** |
| `X-Content-Type-Options` | **no** | relies on Pages sending correct `content-type` (it does) |
| `Referrer-Policy` | **no** | browser default (`strict-origin-when-cross-origin` in current browsers) |
| `Permissions-Policy` | **no** | no feature policy |
| `Cross-Origin-Opener-Policy` | **no** | irrelevant here: no popups, no cross-origin windows |

### Why

GitHub Pages serves static files and applies **no custom response headers**. The `_headers` files in
this repository (`website/public/_headers`) and in `aetherisnode-home` (`public/_headers`) are a
Cloudflare Pages / Netlify convention. **They are inert in production.** Any document that describes
them as effective is wrong; the honest statement is "declared, not applied".

## 2. What is enforced

* **CSP, as a `<meta http-equiv>` in every page** of both sites (portal: all four pages; Angel: the
  live document plus its 404 — the meta tag sits at byte 544, before the first `<script>` at 2880).
  Angel site:

  ```
  default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
  font-src 'self'; connect-src 'self'; manifest-src 'self'; form-action 'none';
  base-uri 'none'; object-src 'none'
  ```

  Portal (stricter — `default-src 'none'`, nothing is allowed that is not named):

  ```
  default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:;
  font-src 'self'; base-uri 'none'; form-action 'none'
  ```

  Enforced: no third-party script/style/font/connect origins, no inline script or style (neither
  policy carries `'unsafe-inline'` and neither uses a hash; measured inline `<script>` count is **0**
  on both sites, and the Angel page loads exactly two external scripts — `/theme-init.js` and one
  Astro module), no plugins, no form submission, no `<base>` hijack.
  Not enforced: `frame-ancestors`, `upgrade-insecure-requests`, any transport policy.
* **TLS on every name**: Let's Encrypt `YR1`, valid `2026-11-15` → `2027-02-13` (apex, SAN includes
  `www`) and `2026-11-14` → `2027-02-12` (`angel`); `http://` answers `301` to `https://` on all
  three. Certificates are renewed by GitHub Pages, not by any job in these repositories.
* **Canonical host**: `www` → apex `301` with path and query preserved (verified `/privacy/` and
  `?x=1`). One origin per site, no duplicate-content surface.
* **No state, no tracking**: no `Set-Cookie` observed on either site, no analytics, no third-party
  request, no login, no user input beyond a theme switch stored in `localStorage`. There is nothing
  to hijack a session for — which is what makes the missing framing protection tolerable instead of
  critical.
* **No secrets in the published bytes**: `website/scripts/build.sh` fails the build on `.env*`,
  `*.pem`, `*.key`, `*.sqlite*`, `*.db`, `node_modules` inside `website/dist`; the portal CI fails if
  `public/` differs from a fresh build. `gitleaks 8.30.1` over the full history of `angelbot`,
  `angel-web`, `aetherisnode-home` and `angel-site` (all refs, all commits) returned **0 findings**,
  and 0 on the working trees — measured 2026-11-15.

## 3. Residual risks, accepted knowingly

| # | Risk | Realistic impact | Accepted because |
|---|---|---|---|
| S-1 | No clickjacking protection (no `X-Frame-Options`, no `frame-ancestors`) | A third party can frame the marketing site | No authenticated UI, no forms (`form-action 'none'`), no cookies; framing gains an attacker nothing but visual deception, and the brand is one page deep |
| S-2 | No HSTS | A first-visit MITM could downgrade to `http`; Pages answers `301` but headers cannot pin the browser | Public static content, no credentials, no session. Mitigation only possible by moving to a host that sets headers (Cloudflare) |
| S-3 | Hashed assets cached `max-age=600`, not `immutable` | Slower repeat views; a changed asset is picked up within 10 min | Pages default; cannot be changed without custom headers. Correctness is preserved (revalidation), only performance suffers |
| S-4 | `access-control-allow-origin: *` on responses | Any origin may read the public pages programmatically | The content is already public by definition |
| S-5 | CSP via `<meta>` | A policy violation before the meta tag is parsed is not blocked | All scripts are external and appear after the meta tag in `<head>`; no inline code exists to exploit the gap |

None of these is a vulnerability in the application code; all five are properties of the hosting
provider. They are documented so that nobody "fixes" them by editing `_headers` and believing it
worked.

## 4. If the hosting changes

Moving to Cloudflare Pages (see `docs/WEBSITE_DEPLOYMENT.md` §6) would let the existing `_headers`
files take effect — full CSP with `frame-ancestors 'none'`, HSTS, `nosniff`, `Referrer-Policy`,
`Permissions-Policy`, and `immutable` caching for `_astro/*`. That migration is **blocked** on a
Cloudflare token with `Zone:DNS:Edit` and an owner-approved nameserver change, and it is **not** a
closeout requirement. Until it happens, the table in §1 is the truth.

## 5. Re-measure

```bash
for u in https://aetherisnode.cloud/ https://www.aetherisnode.cloud/ https://angel.aetherisnode.cloud/; do
  echo "--- $u"; curl -s -o /dev/null -D - "$u" | tr -d '\r' | grep -iE '^(HTTP|server|cache-control|strict|content-security|x-frame|x-content|referrer|permissions)'
done
curl -s https://angel.aetherisnode.cloud/ | grep -o '<meta http-equiv="Content-Security-Policy"[^>]*>'
```
