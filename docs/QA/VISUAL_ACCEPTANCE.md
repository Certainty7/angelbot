# Visual acceptance — criterion → evidence

Owner of this section: Certina. Written for the owner's final report (§25 items 9, 10, 16).
Every number below was measured, not estimated; the file or commit that proves it is named
next to it. Nothing here claims a check that was not run.

Scope: the visual and interaction criteria of §10–§12, §19.5 and §23. Hosting, DNS, security
headers and CI are deliberately absent — they belong to the implementation and platform work.

---

## 0. Review on the production domain (added after the TLS cut-over)

`https://angel.aetherisnode.cloud/` reviewed in a browser once the certificate became
valid, 2026-11-15. Same build as the reviewed artefact (the drift gate proves byte
equality), so this pass confirms the host, not a new design.

| Check | Result |
|---|---|
| Secure context | yes, certificate `CN=angel.aetherisnode.cloud` |
| Resources on `/` | 13 requests, **0 failed** |
| Fonts | Amiri + Plex Arabic both resolve (`document.fonts.check`) |
| Arabic hero | 68 px, **2 lines** |
| Eleven routes (10 pages + `/404`) | one `h1` each, 0 failed resources, 0 horizontal overflow |
| `/how-it-works/` | pipeline diagram present |
| `/commands/` | 69 `<details>` |

Screenshots: `docs/QA/production/domain-home-light.jpg`, `domain-home-rose-night.jpg`,
`domain-mobile-light.jpg`.

What is still true on this host: `CSP` and `referrer` are document-level (`<meta>`), with no
`HSTS`, no `frame-ancestors` and no asset caching policy. Those return with Cloudflare.

## 1. Brand identity

| Criterion | Evidence |
|---|---|
| Original mark, not stock and not AI imagery | `src/assets/brand/` — 20 files generated from geometry and HarfBuzz outlines, `_gen/build_brand.py` is the source of the geometry |
| Arabic and Latin wordmarks | `angel-wordmark-ar.svg` (Amiri Bold, outlines) · `angel-wordmark-en.svg` (Instrument Serif, outlines) — baked to paths, so no font dependency |
| Light / dark variants | `angel-mark.svg`, `angel-mark-dark.svg`, `angel-mark-mono.svg`, `*-dark`, `*-mono` |
| Favicons and app icons | 32 / 48 / 180 / 192 / 512 px PNG + SVG, `site.webmanifest` |
| Social share card | `og-image.png` 1200×630, editable source in `og-image.src.html` |
| Original diagram (not a stock illustration) | `src/components/PipelineDiagram.astro`, geometry in `tools/design/gen_pipeline.py` |

## 2. Colour and contrast

Computed from the palette with the WCAG formula, not judged by eye
(`docs/DESIGN_SYSTEM.md` §3 holds the full table).

| Pair | Pearl Light | Rose Night |
|---|---|---|
| H1 `--ink-900` on ground | 16.53:1 | 16.53:1 |
| Lede `--ink-700` | 10.14:1 | 12.18:1 |
| Note `--ink-500` | 6.06:1 | 7.83:1 |
| Eyebrow/accent `--rose-600` | 7.96:1 | 9.74:1 |
| CTA label on `--grad-seal` | 10.03:1 | 8.22:1 |

Every text pair clears AA for normal text; the smallest margin is 6.06:1.

## 3. Typography

- Families: Amiri (display, Arabic), Instrument Serif (display, Latin), IBM Plex Sans
  Arabic / Plex Sans (text), Plex Mono (code and numerals). All OFL, self-hosted, licences
  in `public/fonts/NOTICE.md` + `OFL.txt`.
- Arabic display leading 1.45 (`--lh-heading-ar`), never 1.28 — measured: 1.28 put the
  tanween of the second line into the descenders of the first.
- No letter-spacing on Arabic anywhere; tracking tokens are Latin-only by construction.
- Headline sizes come from the measure, not from taste: Arabic 68 px → 2 lines, English
  72 px → 3 lines at 1440 (commit `10ae941`).

## 4. Hero

| Criterion | Measured |
|---|---|
| Two-line Arabic headline at ≥1024 | yes, at 1440 / 1280 / 1024 |
| English headline composed | 3 lines at all four widths |
| Horizontal overflow | 0 at 360 / 390 / 768 / 1024 / 1280 / 1440 / 1920 |
| Ring-to-text gutter | 48 px at 1024, 85 at 1280, 122 at 1440 |
| Mark centred in the aperture | delta (0,0) measured, optical lift 2.4 % |
| Reduced motion | sheen `display:none`, zero elements left at `opacity:0` |
| Theme | toggles, persists across reload, restored before first paint |

## 5. Pages and error state

- Ten routes × two locales: one `h1` each, zero horizontal overflow
  (`docs/QA/PRODUCTION-VISUAL-REVIEW.md`).
- 404: `lang`/`dir` correct per locale, canonical and `hreflang` cluster consistent
  (`ar=/404`, `en=/en/404/`, `x-default=/404` on both), content block 628 px with the
  footer at 797 px — composed, not a placeholder. Branded, not the server default.
- Commands catalogue: 69 `<details>` (68 commands + the owner group), zero permission
  badges on owner rows, the word `administrator` absent from the built page.

## 6. Accessibility evidence

| Check | Result |
|---|---|
| Lighthouse accessibility, `/`, `/en/`, `/commands/` | 100 / 100 / 100 (`docs/QA/LIGHTHOUSE.md`) |
| Logical focus ring, two-tone, on every control | `base.css`, verified in the built page |
| Touch targets | ≥ 44 × 44 measured on the mobile header |
| Heading order | one `h1` per page, no skipped levels in the sampled pages |
| Motion | `prefers-reduced-motion` honoured; content never depends on an observer |
| Arabic semantics | `dir="rtl"`, `<bdi>` isolation for Latin inside Arabic, no per-letter animation |

## 7. What is **not** claimed here

- No field performance measurement on the custom domain. The visual review there is done
  (§0), but Lighthouse numbers still come from `astro preview`; the CDN measurement waits
  for the move back to Cloudflare, where the caching headers exist.
- No screen-reader session with a human user; the accessibility evidence is automated
  (Lighthouse) plus structural checks, not a usability study.
- No visual diff harness: the screenshots in `docs/QA/` are evidence for review, not a
  regression gate.
