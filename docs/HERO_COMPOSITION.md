# Hero composition — "The Aperture"

Implementable specification for the `/` hero. Anything not fixed here is a normal component decision;
everything fixed here is **not** open to interpretation. Written by Certina. Tokens refer to
`website/src/styles/tokens.css`.

The hero is the only place on the site where a large graphic object is allowed. It carries the identity
in one gesture: an aperture holding the pearl-A, a typographic column on the reading edge, and one
pass of light. No stock art, no mascot, no WebGL, no emoji, no three-card row underneath.

---

## 1. Copy (approved — use verbatim)

> **Amended 2026-11-15.** The lede no longer mentions member notes: the evidence-built member file was
> removed from the bot (Discord Developer Policy forbids profiling members from API Data). The strings
> below are the ones the site ships; a lede that advertises member notes is a stale claim.

| Slot | Arabic (primary) | English mirror |
|---|---|---|
| Eyebrow | `بوت ديسكورد · سيرفرات المجتمع` | `DISCORD BOT · COMMUNITY SERVERS` |
| H1 | `أرشيفٌ يُبحث فيه، وإشرافٌ لا يُنفَّذ إلا بتأكيد.` | `A searchable archive. Moderation that never acts unconfirmed.` |
| Lede | `يحتفظ أنجل بأرشيف قابل للبحث لما يراه، ويحوّل روابط التواصل الاجتماعي إلى ملفات.` | `Angel keeps a searchable archive of what it sees and turns social links into files.` |
| CTA primary | `أضف أنجل إلى سيرفرك` | `Add Angel to your server` |
| CTA secondary | `تصفّح الأوامر` | `Browse the commands` |
| Under-CTA note | `مفتوح للإضافة — لا حساب مطلوب.` | `Open to invite — no account needed.` |

Every claim above is traceable to `README.ar.md` (searchable archive, media extraction,
`bot_public: true`). Do not add a number, a user count, an uptime claim or a testimonial to
this hero. The command count is not printed in the hero at all — it lives on `/commands/` and comes from
the generated JSON.

RTL ordering inside the hero: **eyebrow → H1 → lede → CTA row → note**, reading right to left. In the
LTR mirror the same order reads left to right.

## 2. Layout

Desktop (≥1024px), RTL:

```
┌─ viewport ────────────────────────────────────────────────────────────────┐
│  folio hairline (top, 1px, inside --container, full width)                │
│                                                                           │
│   ┌ aperture 520×520 ┐                       eyebrow                       │
│   │  ○ ring 520      │                       H1  (max 2 lines)            │
│   │    ○ ring 428    │                       ─────────────────────        │
│   │      ○ bloom 336 │                       lede (max 46ch)             │
│   │        ✦ mark    │                                                   │
│   │          150px   │                       [ CTA ]  تصفّح الأوامر       │
│   └──────────────────┘                       note                          │
│                                                                           │
│  folio hairline (bottom)                                                  │
└───────────────────────────────────────────────────────────────────────────┘
      cols 1–6 (RTL right: text)          ← grid gap 24 →    cols 7–12 (aperture)
```

| Item | Value |
|---|---|
| Section | `padding-block: clamp(64px, 9vw, 112px) clamp(72px, 10vw, 128px)` |
| Grid | `--container` 1248px, 12 columns, `--grid-gap` |
| Text column | spans **7 columns** (RTL: starts at the right edge), `max-inline-size: 620px` |
| Aperture column | spans **5 columns**, object `520×520`, centred in its half |
| Column gutter | ≥ 48px at 1024, ≥ 64px at 1280 — never let the ring touch the text |
| Folio rules | `--border-hair`, full `--container` width, 1px; margin-block `--space-6` |

Breakpoint behaviour:

| Viewport | Layout | Aperture | Mark inside | H1 |
|---|---|---|---|---|
| 360–639 | single column, **aperture first**, text below | 240×240, centred, `margin-block-end: 40px` | 96px | `--fs-display-1` lower bound (52px) |
| 640–1023 | single column, aperture first | 360×360 | 120px | clamp mid |
| 1024–1279 | 2 columns, text right (RTL) | 440×440 | 132px | `--fs-display-1` mid |
| ≥1280 | 2 columns | 520×520 | 150px | `--fs-display-1` upper (104px) |

The aperture is always **radially symmetric**, so it needs no RTL/LTR variant: only its grid column
changes. The mark inside is centred, never offset by direction.

## 3. Layer stack (exact)

| z | Layer | Element | Build |
|---|---|---|---|
| 0 | Ground | `.hero` background | `--grad-pearl` **plus** one `radial-gradient(760px 520px at 6% 106%, rgba(228,194,198,.45), transparent 62%)` corner wash. Two gradients total, nothing animated. |
| 1 | Ring 1 | `div.ring.ring--1` | 520×520, `border-radius: 50%`, `1px solid rgba(138,46,69,.14)` |
| 1 | Ring 2 | `div.ring.ring--2` | inset 46px (428×428), `1px solid rgba(138,46,69,.10)` |
| 2 | Bloom | `div.aperture__bloom` | inset 92px (336×336), `background: var(--grad-bloom)`, `border-radius: 50%` |
| 2 | Specular | `div.aperture__specular` | same box, `radial-gradient(circle at 66% 18%, rgba(255,255,255,.95), transparent 34%)` |
| 3 | Ring 3 | `div.ring.ring--3` | inset 92px, `1px solid rgba(138,46,69,.28)` — the ring that defines the aperture edge |
| 4 | Mark | `<svg>` from `angel-mark.svg` | 150×150 (see table above), centred: `inset-block-start: 50%; inset-inline-start: 50%; translate: -50% -50%` |
| 5 | Sheen | `div.aperture__sheen` | full aperture box, `background: var(--grad-sheen)`, `mix-blend-mode: screen`, `opacity: .9`, `pointer-events: none`, clipped by `border-radius: 50%` |
| 6 | Text | `.hero__col` | grid column, contains eyebrow/H1/lede/CTA/note |
| — | Header | site header | `--z-header` (200), above everything, sticky |

The whole aperture is one element with `position: relative; isolation: isolate; contain: paint` so the
sheen cannot leak and the blend mode cannot affect the page.

Skeleton to paste (the ring values are the spec, not a suggestion):

```css
.aperture { position: relative; inline-size: 100%; aspect-ratio: 1; max-inline-size: 520px;
            margin-inline: auto; }              /* radius via clamp() at <1024 */
.aperture .ring { position: absolute; border-radius: 50%;
                  border: 1px solid rgba(138,46,69,.14); }
.aperture .ring--1 { inset: 0; }
.aperture .ring--2 { inset: 46px; border-color: rgba(138,46,69,.10); }
.aperture .ring--3 { inset: 92px; border-color: rgba(138,46,69,.28); }
.aperture .bloom { position: absolute; inset: 92px; border-radius: 50%;
                   background: var(--grad-bloom); }
.aperture .specular { position: absolute; inset: 92px; border-radius: 50%;
                      background: radial-gradient(circle at 66% 18%,
                        rgba(255,255,255,.95), rgba(255,255,255,0) 34%); }
.aperture .mark { position: absolute; inline-size: 150px; block-size: 150px;
                  inset-block-start: 50%; inset-inline-start: 50%;
                  translate: -50% -50%; }
```

In Rose Night the same stack works unchanged: `--grad-bloom` and `--grad-sheen` are theme-aware, and the
ring borders must switch to `rgba(243,207,214,…)` at the same alphas (14 / 10 / 28 %) — the aperture is
the one place where the dark variant *emits* rather than reflects.

## 4. Typography in the hero

| Slot | Family / token | Size | Line-height | Colour | Notes |
|---|---|---|---|---|---|
| Eyebrow | `--font-lat-text` 500, tracked `--track-label`, uppercase | 12px | 1.4 | `--rose-600` | Latin only. In the AR page it sits above an Arabic H1; it may be Arabic in `--font-ar-text` 600 at 13px with **no** tracking. |
| H1 | `--font-ar-display` 700 | `--fs-display-1` × `--ar-display-scale` (49 → 98px) | 1.28 | `--ink-900` | Max 2 lines at ≥1024, 3 at 360. `text-wrap: balance`. No letter-spacing. |
| H1 (EN page) | `--font-lat-display` 400 | `--fs-display-1` (52 → 104px) | 1.08 | `--ink-900` | Latin gets `--track-display` (−0.018em). |
| Lede | `--font-ar-text` 400 | `--fs-body-lg` (17 → 19) | 1.78 | `--ink-700` | `max-inline-size: 46ch`, not 60 — the hero lede is short by design. |
| CTA | `--font-ar-text` 600 | 16px | 1 | `--text-on-accent` | Pill, 48px height, padding-inline 28px. |
| Note | `--font-ar-text` 400 | `--fs-caption` 13 | 1.6 | `--ink-500` | Sits 12px under the CTA row. |

Spacing inside the column: eyebrow → H1 `--space-4` (16) · H1 → rule `--space-6` (24) · rule → lede
`--space-6` (24) · lede → CTA row `--space-8` (32) · CTA row → note `--space-3` (12).
The rule is `1px`, `--grad-hairline`, `inline-size: 72px`, `margin-block: 0`.

## 5. Animation

Everything is **CSS only** — no JavaScript is required to reach the final state. Use `@keyframes` with
`animation-delay`, `animation-fill-mode: both`. The hero never animates on scroll (it is above the fold).

| t (ms) | Element | From → to | Duration | Easing |
|---|---|---|---|---|
| 0 | rings 1/2/3 | `opacity 0; scale .985` → `1; 1` | 520 | `--ease-out` |
| 0 / 120 / 240 | ring 1 / 2 / 3 delay | — | — | staggered 120ms, **outer ring first** |
| 120 | bloom + specular | `opacity 0` → `1` | 520 | `--ease-out` |
| 240 | mark | `opacity 0; translateY 8px; filter blur(6px)` → `1; 0; blur(0)` | 800 | `--ease-out` |
| 320 | eyebrow | `opacity 0; translateY 10px` → final | 520 | `--ease-out` |
| 400 | H1 line 1 | `opacity 0; translateY 14px` → final | 520 | `--ease-out` |
| 480 | H1 line 2 | same | 520 | `--ease-out` |
| 560 | lede | same | 520 | `--ease-out` |
| 640 | CTA row + note | same | 520 | `--ease-out` |
| 1600 | sheen | `translateX(-120%)` → `translateX(120%)`, one pass, `animation-iteration-count: 1` | 1200 | `--ease-linear` |

Nearest-total finish: ~2800ms including the sheen. Nothing loops. The sheen element is
`pointer-events: none` and sits above the mark but below the text column; it must not cross the text.

H1 line splitting: wrap each visual line in a `<span>` (two spans at ≥1024, three at 360) purely for the
stagger. Arabic must be split **by line, never by letter** — per-letter animation destroys the cursive
joining.

## 6. `prefers-reduced-motion: reduce`

| Behaviour | Required state |
|---|---|
| All entrance animations | Not run at all (`animation: none`), elements render at final state. |
| Sheen | Element hidden (`display: none`) — a static sweep looks like a rendering bug. |
| Rings / bloom / mark | Fully visible and static from first paint. |
| Below-fold reveals | `opacity: 1; translate: none` — content must never depend on an observer to become visible. |
| Hover/press transitions | May remain at 90ms; they are user-initiated and small. |

Acceptance: a screenshot taken with reduced motion enabled must be indistinguishable from the settled
state of the animated version — same layout, same contrast, nothing missing, nothing half-drawn.

## 7. Performance and loading

- The aperture is CSS gradients + inline SVG: no raster image, no filter beyond one `blur` on the mark.
- Fonts: preload `amiri-700.woff2` and `plex-ar-400.woff2` in the layout `<head>`
  (`<link rel="preload" as="font" type="font/woff2" crossorigin>`). Nothing else in the hero needs
  preloading.
- The mark SVG is inline (≈400 B) rather than an `<img>` so it paints with the document. It carries a
  `<desc>` and `aria-label="Angel"`; the wrapper is `aria-hidden="false"` only if no adjacent text names
  the product — here the H1 does, so add `aria-hidden="true"` to the aperture and keep the hero's
  accessible name on the H1.
- No layout shift: the aperture has `aspect-ratio: 1` and an explicit `max-inline-size`, so the column
  is stable before the SVG paints.

## 8. Don't

- Don't put the primary CTA inside the aperture, or the mark on top of the H1.
- Don't add a third gradient, a glow, a particle, or a mouse-follow effect.
- Don't animate the Arabic H1 per letter or per word.
- Don't rotate, scale or "breathe" the mark — the aperture is the only object allowed to move.
- Don't place anything else inside the ring stack (no badges, no numbers, no screenshots).
- Don't stack this hero with a second display-scale element below the fold. The next section starts at
  `--fs-h1` at most.

## 9. Acceptance checklist

- [ ] At 360/390/768/1024/1280/1440/1920: no horizontal scroll (`scrollWidth − innerWidth ≤ 0`), no text
      clipped, ring never touches the text column.
- [ ] H1 line count as specified; no orphan word on line 2 at 1024.
- [ ] Text measure ≤ 46ch for the lede; H1 ≤ 18 words.
- [ ] Contrast: H1 `--ink-900` on the ground ≥ 15:1; lede ≥ 9:1; note ≥ 5:1 (see DESIGN_SYSTEM §3).
- [ ] Focus visible on both CTAs at all breakpoints, two-tone ring, 44×44 minimum.
- [ ] Reduced motion: identical settled screenshot, sheen absent, no `opacity: 0` left anywhere.
- [ ] Both themes: Rose Night renders the aperture with emitted bloom, and the text keeps ≥ 14:1.
- [ ] LTR mirror: text left, aperture right, no mirrored logo or numeral reversal.
- [ ] No JS required for the final state; zero console errors; CLS 0 on a clean load.
