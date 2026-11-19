# Angel design system — Pearl Light / Roseglass

Owner: **the design owner**. Direction decided in `docs/BRAND_DIRECTIONS.md` (option A, with B's editorial
discipline and C's optics subordinated). Implemented as tokens in `website/src/styles/tokens.css`
and assets in `website/src/assets/brand/`. Consumers: every Astro page and component.

**Authority.** This document and `tokens.css` are the single source of truth for colour, type, spacing,
motion and logo usage. A component that hardcodes a hex, a duration or a spacing value is a bug even if
it looks right. The implementation does not re-decide. If a value is genuinely missing, it is added
here first.

---

## 1. Principles

1. **Arabic is the voice, not a translation.** Arabic is set in a Naskh display face at display sizes.
   Latin is the accompaniment — micro-labels, the secondary locale, command names. A page that only
   works when read left-to-right is not finished.
2. **Light is the subject.** The product is called Pearl Light and the surfaces behave like pearl: a
   pale warm field, one rose material, one specular highlight. Colour is used in islands, never as a
   field.
3. **Hairlines instead of boxes.** Structure comes from 1px rules, fields and air. No decorative
   rounded containers, no card grid as a default layout, no drop-shadowed panels to imply hierarchy.
4. **One accent.** Deep rose is the only saturated colour. It appears on at most ~5% of any viewport:
   the mark's pearl, one CTA, links, the active dot.
5. **Motion is light arriving.** Fades and short rises. No bounce, no parallax, no looping animation in
   the reading column.

## 2. Logo system

### 2.1 Construction — "the Nacre A"

An `A` drawn as two tapered blades that meet at a single flat apex, with a pearl suspended in the
aperture at crossbar height. Three ideas in one sign: the initial of **Angel**, a pair of wings folded,
and a **pearl held in an aperture** (the light/roseglass material). No halo, no feather, no mascot, no
angel silhouette — those are the clichés this mark exists to avoid.

| Property | Value |
|---|---|
| Design box | 96 × 96 units; ink occupies 80 × 80, centred (x 8–88, y 8–88) |
| Apex | flat, 5.6 units wide, at y = 8 |
| Outer base | x = 8 / 88 at y = 88 |
| Inner base | x = 33 / 63 (aperture 30 wide at the foot) |
| Crossbar height | y = 50 (54% of the ink height) |
| Pearl | circle, centre (48, 50), r = 6 (12 units = 15% of the ink height) |
| Counter area | 18.8% of the bounding box — the measure that keeps it a letterform and not a tent |

The pearl is the **only** element that carries the accent colour. In a one-colour reproduction it is
knocked out (see `angel-mark-mono.svg`), never filled with a second colour.

### 2.2 Clear space and minimum sizes

- **Clear space:** 25% of the mark's ink height on all four sides. Nothing (text, rule, image edge,
  another logo) enters that zone.
- **Minimum sizes:** mark with pearl **20px**; mark mono **14px**; wordmark AR **16px** ink height;
  wordmark EN **10px** ink height; lockups **22px** height (AR) / **18px** (EN).
- **Below those sizes use the dedicated optical artwork**, never a scaled-down copy:
  `angel-favicon.svg` / `favicon-32.png` are redrawn at 32 units with heavier blades and a smaller
  pearl. Scaling the primary mark to 16px is a known failure — the pearl merges into the blades.

### 2.3 Files and when to use which

| File | Use |
|---|---|
| `angel-mark.svg` | Preferred mark, light surfaces. Ink blades + deep-rose pearl. |
| `angel-mark-dark.svg` | Mark on Rose Night. Pearl-lit blades + lifted rose pearl. |
| `angel-mark-mono.svg` | One-colour contexts: stamping, favicon fallback, single-ink print. `currentColor`, pearl knocked out. |
| `angel-favicon.svg`, `favicon-32.png`, `favicon-48.png` | Browser tab. Rounded deep-rose tile, redrawn for 32px. |
| `favicon-180.png`, `icon-192.png`, `icon-512.png` | Home-screen / manifest. Full-bleed deep-rose square so the OS can apply its own mask. |
| `angel-icon-square.svg` | Editable source of the full-bleed icon. |
| `angel-wordmark-ar.svg` / `-dark` / `-mono` | Arabic wordmark «أنجل», Amiri Bold, baked to outlines. |
| `angel-wordmark-en.svg` / `-dark` / `-mono` | Latin wordmark `ANGEL`, Instrument Serif, +0.10em, baked to outlines. |
| `angel-lockup-ar.svg` / `-dark` | Mark + Arabic wordmark, composed for RTL (mark on the **right**). |
| `angel-lockup-en.svg` / `-dark` | Mark + Latin wordmark, composed for LTR (mark on the **left**). |
| `og-image.png` (+ `og-image.src.html`) | 1200×630 social card. The HTML is the editable source. |

All wordmarks are **outlines, not live text**, so they render identically before, during and after font
loading, and they cannot be broken by a missing font file. Do not retype the wordmark in HTML.

### 2.4 Lockup rules

- Arabic lockup: mark on the right, wordmark to its left, gap = 15/54 of the mark's height. The mark's
  optical centre sits **0.20 × the wordmark's ink height above the baseline** — Arabic ink includes the
  hamza above and the ج descender below, so centring on the ink box floats the mark.
- Latin lockup: mark on the left, wordmark right, gap = 16/44 of the mark height, mark centred on the
  cap height (0.5 × ink height above the baseline).
- The composed SVGs already contain these relationships: place them by height, `width: auto`, and do
  not re-space them.

### 2.5 Don't

- Don't recolour the mark. Blades are `--ink-900` (or `--ink-900` in Rose Night), pearl is `--rose-600`.
- Don't add gradients, shadows, outlines, strokes or glows to the mark or wordmark.
- Don't place the mark on a photograph or over the hero bloom's brightest point.
- Don't stretch, rotate, crop, or rebuild the mark from rectangles.
- Don't put the Latin wordmark above the Arabic one in the RTL lockup.

## 3. Colour

Palette roles are fixed. Measured WCAG 2.1 contrast ratios below were computed on these exact hexes
(relative luminance, sRGB), not estimated.

### 3.1 Pearl Light (default)

| Token | Hex | L* | Role |
|---|---|---|---|
| `--pearl-000` | `#FDFBFA` | 98.7 | Page ground. A warm off-white; never `#fff`. |
| `--pearl-050` | `#FAF6F3` | 97.1 | Raised ground, alternating bands. |
| `--ivory-100` | `#F5EEE7` | 94.5 | Warm ivory: cards, quote blocks, table headers. |
| `--ivory-150` | `#F0E7DF` | 93.1 | Inset wells, code blocks. |
| `--blush-200` | `#F1DFDC` | 90.2 | Blush: tinted bands, chips, hover wash. |
| `--quartz-300` | `#E4C2C6` | 81.4 | Rose quartz: decorative rules, gradient anchors. Never text. |
| `--quartz-400` | `#D3A0A8` | 70.7 | Deeper quartz: decorative only (2.17:1 — not a UI boundary). |
| `--rose-600` | `#8A2E45` | 33.5 | **Deep rose.** Accent ink, links, CTA fill, the pearl. |
| `--rose-700` | `#72243A` | 27.1 | Pressed/active CTA, gradient end. |
| `--ink-900` | `#221A1B` | 10.2 | Primary text. Charcoal with a rose undertone; never `#000`. |
| `--ink-700` | `#4A3C3E` | 26.8 | Secondary text, ledes. |
| `--ink-500` | `#6E5C5F` | 40.9 | Muted text, metadata, captions. |
| `--line-control` | `#96727A` | — | Border of any operable control. |

**Measured text contrast**

| Pair | Ratio | Verdict |
|---|---|---|
| `ink-900` on `pearl-000` | **16.53:1** | AAA |
| `ink-900` on `ivory-100` | **14.83:1** | AAA |
| `ink-700` on `pearl-000` | **10.14:1** | AAA |
| `ink-700` on `ivory-100` | **9.10:1** | AAA |
| `ink-500` on `pearl-000` | **6.06:1** | AA (small text ok) |
| `ink-500` on `ivory-100` | **5.44:1** | AA |
| `rose-600` on `pearl-000` | **7.96:1** | AAA |
| `rose-600` on `ivory-100` | **7.14:1** | AAA |
| `rose-600` on `blush-200` | **6.38:1** | AA |
| `pearl-000` on `rose-600` (CTA) | **7.96:1** | AAA |
| `pearl-000` on `rose-700` | **10.03:1** | AAA |
| `line-control` vs `pearl-000` / `ivory-100` / `blush-200` | **4.08 / 3.66 / 3.28** | ≥3:1 everywhere ✓ |

**Non-text rules.** `--border-hair` (14% rose) and `--border-soft` (22%) are *decorative* and exempt
from WCAG 1.4.11 — they separate, they do not identify. Anything a user can operate uses
`--border-control` (≥3:1 on every light ground above). `--quartz-300/400` never carry meaning.

### 3.2 Rose Night (dark variant)

Independently composed, **not** an inversion: a rose-black charcoal ground, warm pearl text, and an
accent **lifted** to a rose light because deep rose would vanish at this luminance. Elevation is
luminance plus a rose halo, never a black drop shadow.

| Token | Rose Night | L* | Role |
|---|---|---|---|
| `--pearl-000` | `#14100F` | 5.0 | Night ground (charcoal, rose undertone). |
| `--pearl-050` | `#1C1617` | 8.0 | Raised ground. |
| `--ivory-100` | `#241C1E` | 11.3 | Rose-black card. |
| `--ivory-150` | `#2A2023` | — | Inset. |
| `--blush-200` | `#33262A` | — | Tinted band — a rose-black, not pink. |
| `--quartz-300` | `#4A383C` | — | Decorative rule. |
| `--rose-600` | `#E9A9B6` | 75.5 | **Lifted rose**: accent ink, CTA fill. |
| `--rose-700` | `#F3CFD6` | 86.3 | Accent hover. |
| `--ink-900` | `#F6EEEC` | 94.7 | Warm pearl text (never `#fff`). |
| `--ink-700` | `#DCCCCA` | 83.3 | Secondary. |
| `--ink-500` | `#B7A2A1` | 68.4 | Muted. |
| `--line-control` | `#92747A` | — | Control border. |

| Pair | Ratio |
|---|---|
| `ink-900` on night / on card | **16.53 / 14.57** |
| `ink-700` on night / on card | **12.18 / 10.74** |
| `ink-500` on night / on card | **7.83 / 6.90** |
| `rose-600` on night / on card | **9.74 / 8.58** |
| `text-on-accent` `#3A1620` on `rose-600` | **8.22** |
| `line-control` vs night / raise / card | **4.50 / 4.25 / 3.97** |

### 3.3 Gradients

Five, all low-contrast by design; nothing here reads as a colour block.

| Token | What it is | Where it is allowed |
|---|---|---|
| `--grad-pearl` | 178° pearl → ivory | Page and section grounds. |
| `--grad-roseglass` | 142° ivory → blush → quartz | One framed object per page (the hero aperture, a pull-quote plate). |
| `--grad-seal` | 160° deep rose → rose-700 | Primary CTA fill, the seal/number badge. |
| `--grad-sheen` | 100° transparent → white 78% → transparent | The single ambient sheen pass in the hero. |
| `--grad-bloom` | radial specular bloom | Inside the hero aperture only. |

Forbidden: multi-hue ramps, purple/blue, rainbow text, gradient-filled body text, animated gradient
backgrounds.

### 3.4 Theme switching rules

- The theme is set by `data-theme="rose-night"` on `<html>` **before first paint** by a small head
  script (localStorage → `prefers-color-scheme` → light). `data-theme="dark"` is accepted as an alias.
- **Never transition `color`, `background-color`, `border-color` or `fill`.** Palette flips are instant.
  A transition on a palette-driven property restarts on every recalculation and Chrome can leave
  inherited colours on the old palette — the classic "only some text is wrong" bug.
- Keep `<meta name="theme-color">` in sync with `--pearl-000` per theme.

## 4. Typography

### 4.1 Families and licences

| Role | Family | File(s) | Licence |
|---|---|---|---|
| Arabic display | **Amiri** 700 / 400 | `fonts/amiri-700.woff2`, `amiri-400.woff2` | SIL OFL 1.1 — Amiri Project Authors |
| Latin display | **Instrument Serif** 400 | `fonts/iserif-400.woff2` | SIL OFL 1.1 — Instrument Serif Project Authors |
| Arabic text | **IBM Plex Sans Arabic** 400/500/600 | `fonts/plex-ar-400/500/600.woff2` | SIL OFL 1.1 — IBM Corp. |
| Latin text | **IBM Plex Sans** 400/500 | `fonts/plex-lat-400/500.woff2` | SIL OFL 1.1 — IBM Corp. |
| Command / code | **IBM Plex Mono** 400/500 | `fonts/plex-mono-400/500.woff2` | SIL OFL 1.1 — IBM Corp. |

Licences ship beside the files (`website/public/fonts/OFL.txt`, `NOTICE.md`). All five are self-hosted
and subset; **no external font CDN** — that is a CSP and privacy requirement, not a preference.

**Why this pairing.** Amiri is a Naskh revival: at display size its calligraphic contrast is the most
premium signal an Arabic-first product can send, and it is the opposite of the geometric sans every
Discord bot uses. Instrument Serif carries the same high-contrast editorial temperament for Latin, so
the two display faces are siblings rather than translations of each other. Plex Arabic + Plex Sans +
Plex Mono are one superfamily, so bilingual body text and command names share metrics and rhythm.

### 4.2 Scale

Fluid: the lower bound applies at 360px, the upper at ≥1280px.

| Token | 360px | 1280px+ | Line-height (AR / LAT) | Used for |
|---|---|---|---|---|
| `--fs-display-1` | 52 | 104 | 1.28 / 1.12 | Hero headline only. One per page. |
| `--fs-display-2` | 40 | 72 | 1.28 / 1.12 | Page titles on inner pages. |
| `--fs-h1` | 34 | 52 | 1.45 / 1.28 | Section headline. |
| `--fs-h2` | 28 | 40 | 1.45 / 1.28 | Sub-section. |
| `--fs-h3` | 22 | 28 | 1.45 / 1.28 | Card / feature title. |
| `--fs-h4` | 18 | 21 | 1.45 / 1.28 | List group title. |
| `--fs-body-lg` | 17 | 19 | 1.78 / 1.62 | Lede paragraph. |
| `--fs-body` | 17 | 17 | 1.78 / 1.62 | Body. |
| `--fs-body-sm` | 15 | 15 | 1.70 / 1.55 | Secondary body, table cells. |
| `--fs-caption` | 13 | 13 | 1.55 / 1.45 | Captions, footnotes. |
| `--fs-micro` | 11 | 11 | 1.45 | Overline / micro-label (Latin only, tracked). |

**Arabic optical adjustment.** At the same px, Arabic reads larger than Latin, so Arabic display is set
at **0.94 ×** the Latin step (`--ar-display-scale`). Arabic line-height is always the larger of the two
values and **never below 1.15 on display sizes** — at 1.06 the م/ي descenders collide with the line
below.

### 4.3 Typographic rules

- **No letter-spacing on Arabic.** Ever. Tracking cuts the cursive joins. `--track-label` (0.16em) and
  `--track-micro` (0.2em) are Latin-only, as is `--track-display` (−0.018em).
- **Measure:** `--measure` 68ch for Latin, `--measure-ar` 60ch for Arabic prose. Never full-bleed body
  text.
- **Numerals:** Western Arabic numerals (0–9) throughout, including inside Arabic text. They are the
  convention for technical Arabic audiences and they keep command lists, ports and permission names
  consistent. Wrap a numeral that sits between two Arabic words in `<bdi>` when it could be misordered.
- **Inline English** inside an Arabic sentence (`Discord`, `SQLite`, a command name) gets `<bdi dir="ltr">`
  or `dir="ltr"` on the element — never a bare Latin run in an RTL paragraph.
- **Weights:** Arabic display 700 only; Arabic text 400/500/600 (600 for emphasis and UI labels);
  Latin display 400 only; Latin text 400/500. No faux-bold, no faux-italic (no italics are shipped).
- **Underlines** on links are 1px, offset 0.18em, colour `--rose-600` at 45% alpha, removed on hover when
  the colour change carries the affordance.
- **Max two display sizes per viewport.** A page with three competing display lines has no hierarchy.

## 5. Spacing, grid and layout

### 5.1 Spacing scale (4px base)

`--space-1` 4 · `2` 8 · `3` 12 · `4` 16 · `5` 20 · `6` 24 · `8` 32 · `10` 40 · `12` 48 · `16` 64 ·
`20` 80 · `24` 96 · `32` 128 · `40` 160 (all px at 16px root).

Rhythm: related items 8–12, group separation 24–32, section separation 64–96 (mobile) / 96–160
(desktop). Never use a spacing value outside the scale.

### 5.2 Grid

- 12 columns, `--grid-gap` clamp(16 → 24), `--container` 1248px, `--gutter` clamp(20 → 72).
- Prose pages: `--container-narrow` 736px, single column.
- Editorial layouts are composed on the 12-col grid with **unequal** spans (e.g. 7/5, 8/4). A symmetric
  3-up or 4-up card row is forbidden as a default; if items must be parallel, use a ruled list or a
  2-column editorial split with a hairline between.

### 5.3 Breakpoints

| Name | min-width | What changes |
|---|---|---|
| `xs` | 360 | Baseline. Single column, stacked hero, 64px sections. |
| `sm` | 480 | Two-up micro grids, larger display. |
| `md` | 640 | Ledger/tables allow 2 columns, nav collapses to a sheet. |
| `lg` | 768 | 2-col editorial spans begin; hero goes side-by-side. |
| `xl` | 1024 | Full 12-col grid, sticky sub-nav, 3-up only where a table legitimises it. |
| `2xl` | 1280 | Display sizes hit their upper bound, container 1248 locked. |
| `3xl` | 1440 | Gutter maxes at 72; content does not grow. |
| `4xl` | 1920 | Ground extends, content stays 1248 — no fluid full-width text. |

Media queries are mobile-first (`min-width`). Container queries are allowed for components.

## 6. Elevation, borders, radii

| Token | Light | Rose Night |
|---|---|---|
| `--shadow-1` | 2-layer warm micro-shadow | 1px inner pearl highlight |
| `--shadow-2` | card at rest | inner highlight + deep soft shadow |
| `--shadow-3` | floating panel / sticky header | inner highlight + wide soft shadow |
| `--shadow-inset-top` | 1px white top edge for "pressed paper" | 1px pearl top edge |
| `--shadow-accent` | rose glow under a primary CTA | rose halo around a primary CTA |

- Shadows are **warm-tinted** (`rgba(58,32,38,…)`), never neutral black: grey on ivory reads as dirt.
- **Dark elevation inverts the mechanism:** a surface rises by becoming *lighter* (`#1C1617 → #241C1E →
  #2A2023`) plus a rose halo. Do not copy light-mode drop shadows into Rose Night.
- **Borders:** `--border-hair` 1px 14% rose (decorative), `--border-soft` 1px 22% (decorative),
  `--border-control` 1px `#96727A` (operable controls, ≥3:1). The folio frame uses hair + 7px offset.
- **Radii:** `--radius-xs` 2 · `sm` 4 · `md` 8 · `lg` 16 · `xl` 24 · `pill` 999. Rule: **soft where the
  user acts, crisp where the page is structured.** Buttons and chips are pills; cards are 16; media and
  inputs are 8; the og card and the folio frame are 10/8. Never mix radii within one component.

## 7. Iconography

- **Grid:** 24×24, keyline padding 2px, stroke **1.5px**, `stroke-linecap="round"`,
  `stroke-linejoin="round"`, `fill="none"`, `stroke="currentColor"`. At 16px use 1.25px stroke.
- **Construction:** every icon is built from four primitives — a 90°/45° line, a circular arc, a
  rounded rectangle, a 1.5u dot. Diagonals at 45°, never 30°/60°.
- **Set size:** keep the shipped set small and semantic. If an icon needs a legend, it is not an icon.
- **Meaning:** decorative icons are `aria-hidden="true"` and sit next to text. A meaningful icon alone
  needs `role="img"` + `<title>`. Icon-only buttons need `aria-label`.
- **Mirroring in RTL:** mirror directional icons (chevrons, arrows, undo/redo, reply, progress,
  breadcrumb separators). Do **not** mirror logos, media transport controls, clocks, or anything with a
  fixed real-world orientation.
- **Forbidden:** emoji as icons, icon fonts, filled two-tone icon packs, icons with their own palette,
  icons inside decorative colour blobs, hand-drawn "playful" strokes.

## 8. Motion

Motion tokens are in `tokens.css`; this section is the law for using them.

| Token | ms | Used for |
|---|---|---|
| `--dur-instant` | 90 | Press feedback, toggle knob. |
| `--dur-fast` | 140 | Hover states, focus ring appearance. |
| `--dur-base` | 200 | Most component transitions (drawer edge, chevron). |
| `--dur-slow` | 320 | Panels, mobile sheet, tab content swap. |
| `--dur-slower` | 520 | Section reveals on scroll. |
| `--dur-reveal` | 800 | Hero entrance — once per page load. |
| `--dur-breathe` | 1200 | The single ambient sheen pass. |

| Easing | Curve | Used for |
|---|---|---|
| `--ease-out` | `cubic-bezier(.22,1,.36,1)` | Everything entering. The default. |
| `--ease-in-out` | `cubic-bezier(.65,0,.35,1)` | Things that move and return. |
| `--ease-soft` | `cubic-bezier(.4,0,.2,1)` | Colour-free state cross-fades. |
| `--ease-spring` | `cubic-bezier(.34,1.4,.64,1)` | Chips/badges only. Never on layout. |
| `--ease-linear` | `linear` | Only the sheen sweep and progress bars. |

**Choreography.** Stagger 60ms, max 6 items, then reveal the remainder as one group. Translate ≤14px
(`--rise`). Blur 6px → 0 is allowed on the hero only. Scale 0.985 → 1 on cards, never on text.

**Banned:** parallax beyond 12px, infinite loops inside the reading column, bouncing, spring on layout,
scroll-jacking, animated gradients, per-letter Arabic animation (it breaks the word's shape), counters
that animate numbers on a factual page.

**Reduced motion (`prefers-reduced-motion: reduce`).** Durations collapse to 0 and `--rise` to 0px via
the token layer, so every consumer inherits the stop. Additionally: reveals must render their **final**
state (no `opacity: 0` left behind), the sheen pass is not run, and the hero must be complete without
any motion. The site must look composed with motion off, not merely frozen mid-transition.

## 9. Components — the short contract

| Component | Rules |
|---|---|
| Primary button | Pill, `--grad-seal` fill, `--text-on-accent`, 1px inner top highlight, `--shadow-accent`. Height 48 (44 on mobile). Press: `--surface-accent-press`, translateY 1px. |
| Secondary button | Pill, transparent, `--border-control`, `--text-primary`. Hover: `--surface-tint`. |
| Text link | `--text-accent`, 1px underline at 45% alpha, 0.18em offset. Hover: underline 100%. |
| Chip / badge | Pill, `--surface-tint`, `--text-secondary`, `--fs-caption`, 24px height, no icon by default. |
| Permission badge | Mono, `--fs-micro`, 1px `--border-soft`, `--surface-raised`. Long names wrap, never truncate silently. |
| Card | `--surface-card`, `--radius-lg`, `--border-hair`, `--shadow-2`, padding `--space-6`. No decorative icon blob. |
| Ruled list | Hairline between rows, 20px vertical padding, no card. Preferred over cards for feature lists. |
| Command row | Mono name + Arabic description + permission badges + copy button. Whole row is one focus stop with `aria-expanded` details. |
| Table | Header `--surface-raised`, `--fs-body-sm`, hairline rows, numeric columns tabular (`font-variant-numeric: tabular-nums`). |
| Input | 44px min height, `--border-control`, `--radius-md`, `--surface-raised`, focus draws the two-tone ring. |
| Focus | `outline: none` **only** when replaced by the two-tone ring: inner `--focus-ring-inner` 2px + outer `--focus-ring` 2px, offset 2px. Never remove focus styling. |
| Empty / error state | One sentence + one action. No illustration, no sad face. |

**Minimum hit target:** 44×44 CSS px, including icon-only controls and row-level actions.

## 10. Accessibility baseline (non-negotiable)

1. Text ≥ 4.5:1, large text ≥ 3:1, operable borders ≥ 3:1 — the measured table in §3 is the proof.
2. Every interactive element reachable and operable by keyboard, in reading order (RTL: right to left).
3. Visible focus at all times; the ring is two-tone so it survives on both grounds and on the CTA.
4. No meaning by colour alone: the accent dot always has a label or a text state.
5. `dir="rtl" lang="ar"` on the document; `dir="ltr" lang="en"` on the English mirror; `<bdi>` for inline
   Latin/numerals inside Arabic.
6. Headings in order, one `h1` per page, landmarks (`header/nav/main/footer`), skip link first in DOM.
7. Motion honours `prefers-reduced-motion`; no autoplay audio; no infinite animation.
8. Images: decorative → `alt=""`; the mark has `aria-label="Angel"` inside the SVG and `alt=""` on the
   `<img>` when adjacent text already names the product.

## 11. Handoff — what the implementation consumes

**Use:**
- `website/src/styles/tokens.css` — imported first, values owned by the design owner. Do not edit values; add
  component-scoped custom properties in a separate file if needed.
- `website/public/fonts/*` + the `@font-face` block already in `base.css`.
- `website/src/assets/brand/*` — imported so Astro fingerprints them, or referenced from `public/` if a
  component needs a URL. Either is fine; do not duplicate the artwork.
- `docs/HERO_COMPOSITION.md` — the hero is specified layer by layer, including the reduced-motion state.

**Do not:** retype the wordmarks, recolour the mark, add a second accent hue, animate Arabic per letter,
transition palette colours, or introduce a card grid as a page's primary layout.

**Known duplication to retire:** `website/public/brand/*.svg` was produced before this system landed and
is not the specified artwork (different mark, different wordmark files). Components should move to
`website/src/assets/brand/`; the `public/brand/` directory can be deleted once no component references
it.

## 12. Verification record (2026-11-14)

| Check | Method | Result |
|---|---|---|
| Arabic wordmark outlines | Baked HarfBuzz shaping compared pixel-wise with Chrome's own render of «أنجل» at 200px | ink bbox **291×278 in both**, ink area Δ **0.33%** |
| Latin wordmark outlines | same, `ANGEL` at 200px, tracking 0.10em | bbox width **777 in both**, height 132 vs 131 (1px AA), ink Δ **0.57%** |
| Arabic shaping | HarfBuzz glyph run | 4 glyphs for 4 codepoints, positional forms selected (isolated أ + joined ن ج ل) |
| Contrast | WCAG 2.1 relative-luminance computation on the shipped hexes | all text pairs ≥ 4.5:1; all control borders ≥ 3:1 |
| Mark legibility | rendered at 128/64/32/24/16 px on both grounds, inspected | holds to 24px; dedicated 32px artwork for favicon sizes |
| Social card | rendered at exactly 1200×630 by headless Chrome, inspected | dimensions verified, no clipping, Arabic descender clear of the Latin line |
| Icons | rendered at 32/48/180/192/512 | exact pixel sizes; transparent corners on the tab icon, full-bleed on manifest icons |
