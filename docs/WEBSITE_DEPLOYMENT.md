# Website deployment — the path that is actually live

Owner: infrastructure. Measured **2026-11-15, 11:05–11:30 UTC** from a host
outside the bot host, with `curl`, direct TLS handshakes, DNS-over-HTTPS, the GitHub REST API, and a
fresh clone of every repository. Every value below was re-measured in that window; nothing is copied
from an earlier plan. **§2.1 records every publish; its values were re-measured from outside the
publishing machine after the latest one (18:20 UTC) and are the current production state.**

This file replaces the pre-cutover Cloudflare plan that used to live here. That plan described a
migration that was **never executed**; production has been GitHub Pages throughout.

## 1. What serves what

| FQDN | Served by | Source of the bytes | Verified build |
|---|---|---|---|
| `aetherisnode.cloud` | GitHub Pages | `Certainty7/aetherisnode-home`, branch `gh-pages`, root | Pages run for `8e83260` at `2026-11-15T10:46:13Z` |
| `www.aetherisnode.cloud` | GitHub Pages | same | `301 → https://aetherisnode.cloud<path><query>` (path and query preserved, verified on `/privacy/` and `?x=1`) |
| `angel.aetherisnode.cloud` | GitHub Pages | `Certainty7/angel-web`, branch `main`, root | `8dac8d4`, `last-modified: Sun, 15 Nov 2026 18:20:30 GMT` |

Byte-identity, not "the page loads" — the live document against the committed file:

```
angel.aetherisnode.cloud/          sha256 542b9f47eba86a95a4da1bd34d7f08810dd98b35646cc7d0c30a60f089b123de  (15,541 B)
angel-web:index.html (8dac8d4)     same hash — the root did not move in the third publish
angel.aetherisnode.cloud/privacy/  sha256 cce86fda…  (13,244 B)  = angel-web:privacy/index.html
aetherisnode.cloud/                sha256 c414de5db949f1c084aa791a6f6366172a65f97fc6fbdcc0a7a7812cd38b0cc6  (7,291 B)
aetherisnode-home:gh-pages:index.html  same hash
```

## 2. Source of truth, and the copy that is served

```
Certainty7/angelbot  website/  --bash website/scripts/build.sh-->  website/dist
                                                                      │  manual publish (rsync)
                                                                      ▼
                                                     Certainty7/angel-web  (main)  -->  GitHub Pages
                                                                                               │
                                                                            angel.aetherisnode.cloud
```

**`website/` in this repository is the source; `angel-web` is a published copy, not a second source
tree.** The copy exists because GitHub Pages cannot serve a private repository on a free plan, and
`angelbot` is private. The consequence is the one that always follows manual copying: the live site
can be older than the branch it claims to serve. That is a real risk, so it has a gate.

### Drift gate — run it before every publish

`website/scripts/check-published.sh` builds nothing itself: it diffs `website/dist` against a fresh
clone of `angel-web`, ignoring the publishing artefacts `CNAME` and `.nojekyll`, and asks the live host
for one hashed asset so a Jekyll-stripped `_astro/` bundle is caught even when the bytes match.

```bash
bash website/scripts/build.sh            # exit 0 = publishable
bash website/scripts/check-published.sh  # exit 0 = live copy matches this build
```

### Publish

```bash
git clone --depth 1 https://github.com/Certainty7/angel-web.git /tmp/angel-web
rsync -a --delete --exclude .git --exclude CNAME --exclude .nojekyll website/dist/ /tmp/angel-web/
cd /tmp/angel-web && git add -A && git commit -m "Publish: <what>" && git push origin main
```

`CNAME` (`angel.aetherisnode.cloud`) and `.nojekyll` are publishing artefacts and must survive the
sync. Without `.nojekyll`, Pages runs Jekyll and every `_astro/*` directory 404s — the site loads
unstyled.

### 2.1 Publish log — the deploy is done, not pending

The manual publish this document used to describe as "the step to perform" has been performed, and
then re-verified from outside the machine that did it:

| Fact | Value |
|---|---|
| Source commit on `master` | `2aaae7f`; the published content comes from `1d26212` (chat retention 60 → 50) on top of the member-file and a11y fixes |
| **Current publish — the rollback reference** | `angel-web` `8dac8d4`, `2026-11-15T18:20:04Z` |
| Previous publishes (superseded) | `54cdb48` (`12:04:30Z`, a11y fixes), `f0ed296` (`11:42:29Z`, corrected content) |
| Pages rebuild | `last-modified: Sun, 15 Nov 2026 18:20:30 GMT`, `etag "6af9f7ee-3cb5"` (root), `"6af9f7ee-33bc"` (`/privacy/`) |
| Live documents | `/` `15,541 B` `sha256 542b9f47…23de` (unchanged); `/privacy/` `13,244 B` `sha256 cce86fda…` — both byte-identical to `angel-web` |
| Chat retention, as published | `50` messages per member on `/privacy/` and `/en/privacy/` — the value the 30-minute `cleanup_and_vacuum` actually enforces (`database.py:1631`), not the 60 of the write path |
| Retired claim «ويبني ملفات أعضاء من الأدلة» | **0 occurrences** on the live homepage (and 0 in the build) |
| Heading order, `/features/` | `1-2-2-2…` on the live bytes (was `1-3-3-3…`) |
| Language switch | `aria-label="English — عرض الصفحة بالإنجليزية"` on the header link, mirror `«العربية — View this page in Arabic»` on `/en/` |
| Unknown paths | `/nope-xyz/` → `404`, `/en/nope-xyz/` → `404` (the `en/404.html` copy made it real in both locales) |
| Internal references on `/` | 22/22 answered `200` — no broken asset in the new hash set |
| HTML pages in the publish | 21 |

**`etag` is a deploy marker, not a content hash.** The root kept `sha256 542b9f47…` across two publishes
while its `etag` moved `"6af99fe1-3cb5"` → `"6af9f7ee-3cb5"`. Anyone gating on `etag` will re-open a
review after a documentation→publish cycle that changed no byte; the binding check is `sha256` of the
live document against the served branch.

`check-published.sh` exited clean at publish time ("published copy matches this build"). The
independent check — `curl | sha256sum` against `git show origin/main:index.html` — is the one recorded
above, because a gate that runs on the publishing machine is not proof of what the world receives.

### 2.2 Repository visibility — public since 20:2xZ, and the footer links now resolve

`Certainty7/angelbot` was flipped to **public** on 2026-11-15 after the credential rotation, which is
what the three repository links in the site footer were waiting for. Measured anonymously, no token and
no cookie:

```
https://github.com/Certainty7/angelbot                        200  (343,720 B)
https://github.com/Certainty7/angelbot/blob/master/SECURITY.md 200  (185,647 B)
https://github.com/Certainty7/angelbot/commits/master          200  (422,047 B)
git clone https://github.com/Certainty7/angelbot.git          ok   (60c9e85)
api.github.com/repos/Certainty7/angelbot                      200  (anonymous)
private-vulnerability-reporting                              {"enabled": true}
```

Read-only by construction: the only collaborator is `Certainty7`, and `master` is protected against
force-push and deletion with `selftest` and `website-build` required. Before the flip the same three
URLs answered `404` — that was the only user-visible defect the private repository caused, and it is
closed by measurement, not by assumption.

Two anchors carry `class="lang-switch"` on every page (mobile drawer + header actions). Only the header
one carries an `aria-label`; the drawer link's accessible name is its visible text, which is why both
satisfy WCAG 2.5.3 without duplicating the label.

## 3. DNS — the registrar's nameservers are authoritative

| Name | Type | Value | TTL |
|---|---|---|---|
| `aetherisnode.cloud` | `A` ×4 | `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153` | 300 |
| `www.aetherisnode.cloud` | `CNAME` | `certainty7.github.io.` | 300 |
| `angel.aetherisnode.cloud` | `CNAME` | `certainty7.github.io.` | 300 |

`NS`: two nameservers of the registrar's DNS service — SOA serial `2026111501`. No `MX`, no root
`TXT` (so no SPF/DMARC), no `CAA`, no `AAAA` on the apex; `www` and `angel` inherit GitHub's IPv6
through the CNAME. **No record points at the bot host or at the web host**: the bot host
answers nothing on `80`/`443` (verified from an unrelated network), so no public website traffic can
originate there.

## 4. TLS

| Name | Issuer | Valid from | Valid to | SAN |
|---|---|---|---|---|
| `aetherisnode.cloud` | Let's Encrypt `YR1` | `2026-11-15 00:03:22Z` | `2027-02-13 00:03:21Z` | `aetherisnode.cloud`, `www.aetherisnode.cloud` |
| `angel.aetherisnode.cloud` | Let's Encrypt `YR1` | `2026-11-14 23:31:57Z` | `2027-02-12 23:31:56Z` | `angel.aetherisnode.cloud` |

Issued and renewed by GitHub Pages about 30 days before expiry; there is no certbot, no cron job and
no certificate file in either repository. A lapse means the custom-domain setting or the DNS record is
wrong — never "issue a certificate on the host". `http://` on all three names answers `301` to
`https://`.

## 5. What GitHub Pages cannot do — and does not do here

Pages does not apply custom response headers, so `angel-web/_headers` and
`aetherisnode-home/public/_headers` are **inert in production**. Measured on
`angel.aetherisnode.cloud`: no `Content-Security-Policy` header, no `Strict-Transport-Security`, no
`X-Frame-Options`, no `X-Content-Type-Options`, no `Referrer-Policy`, no `Permissions-Policy`. What
the pages do carry is a CSP `<meta http-equiv>`, which cannot express `frame-ancestors` or a
transport policy. Caching is `cache-control: max-age=600` for HTML **and** for hashed `_astro/`
assets and fonts — Pages' default, not the year-long immutable policy written in `_headers`.

Full inventory, the residual risks and what is genuinely enforced: `docs/WEBSITE_SECURITY.md`.

## 6. CDN option — deliberately deferred

A CDN deployment exists but **no DNS record points at it**, so it is not production hosting. Moving the
sites there would bring response headers and long-lived asset caching, at the cost of a nameserver
cutover on live names and an external credential dependency.

**Decision: GitHub Pages stays the production provider.**

## 7. Open items owned here

| Item | State |
|---|---|
| `angel-web` is a manual copy of `website/dist` | Mitigated by `check-published.sh` (clean at `8dac8d4`); moving Pages onto `angelbot` is now **unblocked** — the repository is public — but deferred behind the freeze |
| `angel-site` (public, older dashboard snapshot) | Not referenced by production; archive is now safe, still the release owner's call |
| Repository visibility | **public**, verified anonymously on the three footer links and by clone (§2.2) |
| Homepage claim «ويبني ملفات أعضاء من الأدلة» | **Removed and live**: 0 occurrences at `8dac8d4` (§2.1) |
| A11y: heading order + language-switch label | **Fixed and live** since `54cdb48`, still live at `8dac8d4`: `1-2-2-2` on `/features/`, label present on the header link |
| Chat-retention figure | **Corrected and live**: `50` on both locales at `8dac8d4`, matching the 30-minute vacuum |
| Response headers | Not obtainable on Pages; documented, accepted, deferred with Cloudflare |
| Branch protection | Verified 2026-11-15: force-push and deletion blocked on all three default branches; required checks `selftest` + `website-build` on `angelbot`, `build` on `aetherisnode-home`, none on `angel-web`; admin bypass still allowed. The three required names are **jobs inside one workflow** (`checks`), which is not path-filtered, so they report on docs-only PRs too — a docs PR merges cleanly without bypass (measured on `e0b54b2`) |

## 8. Rollback

Angel: `git revert <publish-sha>` on `angel-web` `main` and push — Pages rebuilds in ~20 s and the
previous bytes are back. Nothing in the path holds state, and no DNS record changes. Portal: see
`aetherisnode-home/docs/ROLLBACK.md`. In both cases the check is byte-identity between the live page
and the file in the serving branch.

## 9. Re-measure

```bash
curl -s -o /dev/null -D - https://angel.aetherisnode.cloud/ | tr -d '\r'   # status + real headers
curl -s https://angel.aetherisnode.cloud/ | sha256sum                     # vs angel-web:index.html
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://www.aetherisnode.cloud/privacy/
echo | openssl s_client -connect angel.aetherisnode.cloud:443 -servername angel.aetherisnode.cloud \
  2>/dev/null | openssl x509 -noout -subject -issuer -dates
git ls-remote --heads https://github.com/Certainty7/angel-web.git
```
