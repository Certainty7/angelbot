# Production visual review — the published site

Author: Certina. Date: 2026-11-14, against the live preview deployment before the custom domain
was pointed at it.
Method: real browser, 1440 and 390 CSS px, measured in the DOM — not judged from source.

---

## 1. What was checked, and what the numbers are

| Page | `h1` | Horizontal overflow | Page height | SVG | `<details>` |
|---|---|---|---|---|---|
| `/` | 1 | 0 | 3110 | 5 | 0 |
| `/features/` | 1 | 0 | 3146 | 3 | 0 |
| `/commands/` | 1 | 0 | 5532 | 72 | 69 |
| `/permissions/` | 1 | 0 | 2703 | 3 | 0 |
| `/how-it-works/` | 1 | 0 | 3274 | 4 | 0 |
| `/security/` | 1 | 0 | 2355 | 3 | 0 |
| `/privacy/` | 1 | 0 | 1888 | 3 | 0 |
| `/faq/` | 1 | 0 | 2135 | 3 | 8 |
| `/changelog/` | 1 | 0 | 3609 | 3 | 0 |
| `/en/` | 1 | 0 | 3499 | 5 | 0 |

- `lang`/`dir` correct on both locales; the LTR mirror is a real mirror — text left,
  aperture right, lockup **not** flipped, Latin display type set at `--track-display`.
- The pipeline diagram is integrated on `/how-it-works/` at 1248 × 374, aligned to the
  same rules as the numbered list above it, and reads as part of the page rather than an
  inserted image. Verified in both themes.
- Mobile (390): header stays a single row, every control ≥ 44 × 44, the hero stacks
  aperture → eyebrow → H1 → rule → lede → CTAs → note, Arabic headline holds two balanced
  lines, and no text touches the viewport edge.
- Below-fold reveals: with JavaScript disabled every reveal element is at `opacity: 1`;
  with JavaScript on they appear on scroll. Content never depends on the observer.

## 2. One defect found — the English hero headline

Measured on production, three widths:

| Viewport | Arabic H1 | English H1 |
|---|---|---|
| 1440 | 68 px, **2 lines** (column 610) | 104 px, **5 lines** (column 691) |
| 1280 | 67 px, 2 lines (601) | 100 px, 5 lines (654) |
| 1024 | 57 px, 2 lines (512) | 83 px, 5 lines (520) |

The English line is 2195 px wide at 104 px, so inside a 691 px column it can only break
into five ragged lines — a poster, not a headline, and it does not mirror the two-line
Arabic composition it is supposed to answer.

Fix (site.css, the `html[lang="en"] .hero__title` rule):

```diff
 html[lang="en"] .hero__title {
   font-family: var(--font-lat-display);
   font-weight: 400;
-  font-size: var(--fs-display-1);
-  line-height: 1.04;
+  font-size: var(--fs-display-2);   /* 72 px: 1519 px intrinsic → 3 lines in 691 */
+  line-height: 1.06;
   letter-spacing: var(--track-display);
-  max-inline-size: 16ch;
+  max-inline-size: 22ch;
 }
```

At Display 2 the same string measures 1519 px, which breaks into three lines with room to
spare at 1440 and at 1024. This is the same correction the Arabic headline received
(Display 1 → Display 2); the English rule was simply left behind.

## 3. Not defects, recorded so they are not re-opened

- **`/404` returns `200` on Pages.** The file exists and is served as the nearest
  `404.html`; a request to a *non-existent* path returns `404` correctly. `/404` must not
  be used as a status probe.
- **Full-page screenshots show a blank band** under a below-fold heading: Chromium does
  not run `IntersectionObserver` for content outside the viewport during a full-page
  capture. Scrolling to the band reveals it (`opacity: 1` measured).
- **`/commands/` at 5532 px** is the longest page by design (68 commands + the owner
  group). Search, category filters and the folded group all work; the length is the
  catalogue, not a layout fault.

## 4. Evidence

`docs/QA/production/`: `home-desktop.jpg`, `home-en-desktop.jpg`, `home-mobile.jpg`,
`how-it-works-diagram.jpg`.
