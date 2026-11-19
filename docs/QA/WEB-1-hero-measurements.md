# WEB-1 — hero measurements and the three corrections site.css needs

Author: the design owner. Date: 2026-11-14. Scope: the `/` hero (`website/src/components/Hero.astro`
+ the hero block of `website/src/styles/site.css`), measured in Chrome 1440 / 1280 / 1024 /
768 / 390 / 360 on the reference implementation in `website/design/`.

The reference implementation is `website/design/index.html` (same markup as `Hero.astro`,
same tokens, plus `aperture.css`). It exists so the values below can be re-measured rather
than argued about: `python3 -m http.server` at the repo root, open `/website/design/`.

---

## 1. `--fs-display-1` cannot hold the approved headline

Measured at 1440 px, column `max-inline-size: 620px`:

| Token | Computed | Line 1 ink | Line 2 ink | Rendered lines |
|---|---|---|---|---|
| `--fs-display-1` × `.94` | 97.76 px | 561 px | **854 px** | **3** |
| `--fs-display-2` × `.94` | 67.68 px | 389 px | **591 px** | **2** |

The approved H1 (`أرشيفٌ يُبحث فيه، وإشرافٌ لا يُنفَّذ إلا بتأكيد.`) is 44 characters. At
Display 1 its second line is 854 px wide inside a 620 px column, so it wraps: the hero
renders **3** lines, not the 2 that `HERO_COMPOSITION.md` §2 requires. Display 2 gives two
lines with 29 px of slack.

**Correction (site.css, `.hero__title`):**

```diff
-  font-size: calc(var(--fs-display-1) * var(--ar-display-scale));
-  line-height: var(--lh-display-ar);
+  font-size: calc(var(--fs-display-2) * var(--ar-display-scale));
+  line-height: var(--lh-heading-ar);
```

## 2. `--lh-display-ar: 1.28` collides with Amiri's tanween

At 1.28 the two display lines overlap their diacritics: Amiri carries fatha, damma, shadda
and tanween well above the alef height, and 1.28 does not clear them. `--lh-heading-ar`
(1.45) does. Verified by cropping the rendered H1 at 1.5× after the change: no contact
between the descenders of line 1 and the marks of line 2.

Same correction as above — it is one rule, and both numbers move together.

## 3. The aperture rings were below the threshold of visibility

`rgba(138,46,69,.14)` over `#FDFBFA` composites to `#E9E2DF` — **1.07:1**, which is
correct for a decorative hairline but disappears at 520 px on a retina-class ground: the
"aperture" reads as a soft blob instead of a constructed ring stack.

| Ring | Spec | Renders as | Recommended | Renders as |
|---|---|---|---|---|
| 1 | `.14` | 1.07:1 | **`.20`** | 1.30:1 |
| 2 | `.10` | 1.05:1 | **`.14`** | 1.07:1 |
| 3 | `.28` | 1.55:1 | **`.30`** | 1.62:1 |

All three stay decorative (far below 3:1), so WCAG 1.4.11 does not apply; the change is
pure legibility of the object. In Rose Night the ring alphas are `.26 / .18 / .34` — at
`.20` the rings read at 1.6:1 on `#14100F` and the circle looked like an outline only.

## 4. Two implementation bugs that only appear in RTL

- **Mark centring.** `inset-inline-start: 50%; translate: -50% -50%` centres in LTR and
  puts the mark half a mark off-centre in RTL, because `inset-inline-start` is `right` in
  RTL while `translate` is physical. Centre with `inset: 0; margin: auto` instead.
  Measured after the fix: aperture centre `(342,463)`, mark centre `(342,463)`, delta `0,0`.
- **Optical, not geometric, centring of the A.** The letterform is base-heavy; after exact
  centring it still reads low. Lift it `2.4%` of its own height: `translate: 0 -2.4%`.
- **The corner wash** in `HERO_COMPOSITION.md` §3 is specified at `6% 106%` — the physical
  bottom-left. That is `inset-inline-END` in RTL (the aperture side). Written as
  `inset-inline-start` it lands behind the text column as a grey band.

## 5. Gutter at 1024

Seven text columns + five aperture columns at 1024 px leaves a 20 px gutter between ring
and text; §2 requires ≥ 48. Holding 28 px on the text side costs the ring 28 px:

```css
@media (min-width: 1024px) and (max-width: 1279px) {
  .aperture { max-inline-size: min(440px, calc(100% - 28px)); margin-inline-start: 28px; }
}
```

Measured after: aperture 353 px, gutter **48 px**.

---

## 6. Verification record (measured, not estimated)

| Check | 360 | 390 | 768 | 1024 | 1280 | 1440 | 1920 |
|---|---|---|---|---|---|---|---|
| Horizontal overflow (px) | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| H1 lines | 3 | 2 | 2 | 2 | 2 | 2 | 2 |
| H1 px | 38 | 38 | 47 | 57 | 67 | 68 | 68 |
| Aperture px | 240 | 240 | 360 | 353 | 481 | 506 | 506 |
| Ring → text gutter (px) | — | — | — | 48 | 85 | 122 | 122 |

Contrast, computed from the palette (not by eye):

| Pair | Ratio |
|---|---|
| H1 `--ink-900` on `--surface-page` | 16.53 |
| Lede `--ink-700` on `--surface-page` | 10.14 |
| Note `--ink-500` on `--surface-page` | 6.06 |
| Eyebrow `--rose-600` on `--surface-page` | 7.96 |
| CTA text on `--grad-seal` | 10.03 |
| Night: H1 / lede / note | 16.53 / 12.18 / 7.83 |

Reduced motion (`prefers-reduced-motion: reduce`): sheen `display: none`, zero elements at
`opacity: 0`, identical layout — checked programmatically over every node in `.hero`.

Theme: `data-theme="rose-night"` set by the toggle, persisted in `localStorage`, restored
before first paint by `theme-init.js`, and survives a reload.

Screenshots: `docs/QA/hero/` (desktop light, desktop Rose Night, tablet, mobile light,
mobile Rose Night).
