# Final QA — desktop, mobile, accessibility, performance

Date: 2026-11-15. Evidence owner: design review. Independent re-checks: second reviewer.
All Angel numbers are against the live bytes at the audited commit (source in this repository),
fingerprint `etag "6af99fe1-3cb5"`, `sha256 542b9f47…`, 15,541 B. Raw captures and JSON:
`<deliverables-dir>` (12 screenshots, three Lighthouse runs,
`README.md`).

## 1. Layout and typography

| Check | Angel | Portal |
|---|---|---|
| Widths 360 / 390 / 768 / 1024 / 1280 / 1440 / 1920 / 2560 | horizontal overflow **0** at every width | **0** |
| `h1` per page | exactly 1 | exactly 1 |
| Heading sequence | `1-2-2-2…` on `/`, `/features/`, `/privacy/`, `/how-it-works/`, `/en/features/` | — |
| Console errors / failed internal requests | 0 / 0 (22 of 22 references return 200) | 0 / 0 |
| Contrast, both themes | 0 failures (light + `rose-night`) | 0 failures (dark default + light) |
| `prefers-reduced-motion` | no element left hidden, animations off | same |
| Arabic / English direction | RTL on `ar`, LTR on `/en/`, lang-switch names include their visible text | — |

## 2. Accessibility

axe (through Lighthouse) reports **100** on `/` desktop, `/en/` desktop, `/features/`,
`/privacy/`, `/how-it-works/`; portal **100** on `/`, `/projects/`, `/projects/angel/`.
Two defects were found on the previous build and closed in `angelbot@462da9e`, verified live:
`label-content-name-mismatch` on the language switch, and `heading-order` on the rows/steps
components (`h3` after `h1`). Nothing else scored below 100 on six routes.

Portal SEO scores 92 as a **measurement artefact**: the page's `default-src 'none'` CSP blocks
Lighthouse's own `robots.txt` fetch. `robots.txt` returns 200. It must not be "fixed" by
weakening the policy.

## 3. Performance (median of repeated runs)

| Metric | Angel | Portal |
|---|---|---|
| Performance, mobile | **97** (84 / 97 / 100) | **95.5** (93 / 98) |
| Performance, desktop | **100** | **100** |
| LCP | 1.5–1.7 s | 1.1–1.2 s |
| CLS | 0 | 0 |
| TBT | 70–600 ms | 140–310 ms |

## 4. Behaviour

- `/nope-xyz/` and `/en/nope-xyz/` return a real `404`; the portal also returns `404`.
- Theme persistence verified across navigation; default is dark on the portal.
- Keyboard access and skip-link verified by focus, not by screenshot.
- No layout shift on font load: the two display faces are self-hosted and preloaded.

## 5. Defects rejected as non-defects (with the measurement)

1. "Header covers the heading" at 360/390: header occupies `[0,0,360,73]`, `h1` starts at y=456 —
   no intersection.
2. "344 px empty space above the hero": the object is a 320×240 pearl mark on an ivory floor
   (`stddev 0.045`, `min 134` on a 253 background) — visible in pixels, an identity choice.
3. Portal SEO 92 — see §2.

## 6. Verification limits

Screenshots were judged by DOM geometry and pixel statistics, not by a vision model reading Arabic
text. The 13 `h2` headings on `/features/` are intentional: a catalogue page with 13 equal
sections is a correct outline; adding a hidden `h2` would add a navigation level with no benefit.
