# Brand directions — three, evaluated, one chosen

Status: decided 2026-11-14 by the design owner (design owner). The card asks for three genuinely different
directions, an evaluation, and a decision without asking the owner. This file is the evaluation;
the winner is specified in `docs/DESIGN_SYSTEM.md` and implemented in `website/src/assets/brand/`.

**Chosen: A — Pearl Light / Roseglass.**

A direction is not a mood board. Each direction below is described by the four things that actually
decide whether a site can be built and sustained: its material logic (what the surfaces are made of),
its typographic voice, its composition grammar, and its motion law. Anything that could not be
described that way was rejected before the brief was written.

---

## A. Pearl Light / Roseglass — *the chosen direction*

**Premise.** Angel is a quiet guardian, not a gadget. The site should feel like a lit room with a
jeweller's bench in it: a warm, luminous field (pearl white → warm ivory), a single precious material
(rose), and hairline structure that never shouts.

**Material logic — nacre, not "pink".** The whole system is derived from one physical behaviour: light
passing through a thin rose film over a pale shell. That gives three repeatable devices and nothing
else:
1. **Specular bloom** — a radial highlight inside a soft rose field, used once per viewport
   (`--grad-bloom`), never as a decorative blob behind text.
2. **Hairline structure** — 1px rules at 14–30% rose alpha doing the work that borders and boxes do in
   lesser systems. The page has almost no containers; it has rules, fields and air.
3. **The pearl** — a small solid disc of deep rose. It appears in the mark, in list bullets, in the
   active-state dot, nowhere else. It is the only fully saturated thing on the page.

**Typographic voice.** Arabic leads, always: **Amiri** (Naskh revival, OFL) for Arabic display — its
calligraphic contrast is the single most premium signal available to an Arabic-first product, and it is
what separates this from every Discord-bot site that sets Arabic in a geometric sans. Arabic text is
**IBM Plex Sans Arabic**; Latin display is **Instrument Serif** (high-contrast, editorial); Latin and
command text is **IBM Plex Sans / Plex Mono**. Latin is the *accompaniment*: it appears as letterspaced
micro-labels and as the secondary locale, never as the headline.

**Composition grammar.** Asymmetric editorial grid: a wide text column that starts on the reading edge,
one large quiet object (the mark in its aperture), generous vertical rhythm, and a hairline frame that
sets the page like a print folio. No three-card rows. No icon-in-a-rounded-square feature grid.

**Motion law.** Light arrives, it does not bounce. Reveals are opacity + ≤14px translate + 6px blur
clearing, 520–800ms, `cubic-bezier(.22,1,.36,1)`, staggered 60ms. One ambient sheen pass per viewport,
1200ms, never looping in the reading area.

**Why it wins.** It is the only one of the three that satisfies the brief's hard constraint *and* its
spirit: light-first, with a dark variant that is a different composition (Rose Night) rather than an
inversion — because the material logic (light through film) generates both a daylight face and a
night-time face honestly. It is also the cheapest to build correctly: no WebGL, no stock, no raster
art beyond the social card, every asset is SVG or CSS.

**Cost / risk.** Arabic display type at 100px+ needs explicit line-height discipline (≥1.15; this system
uses 1.28) or the م/ي descenders collide with the line below. Hairline aesthetics punish sloppy
implementation: sub-pixel rules and warm-tinted shadows have to be specified, not improvised. Both are
handled in the design system rather than left to the implementer.

---

## B. Vellum & Seal — *rejected as the identity, kept as a discipline*

**Premise.** The product's real differentiator is evidence: an archive you can search, facts admitted
only with two supporting messages, moderation that waits for a confirmation. Direction B makes the
website a *document*: warm vellum, letterpress impression, folio numbers, a wax-seal monogram, rules
and marginalia.

**Material logic.** Paper and wax. Slightly mottled ivory stock, debossed rules, one deep-rose wax seal
carrying the monogram. Everything is printed.

**Typographic voice.** Amiri at text sizes (not display), long measure, small caps Latin folios,
marginal notes in Plex Mono. Genuinely beautiful, and the most "made by a person" of the three.

**Composition grammar.** Single column, symmetric margins, numbered sections, footnotes, a colophon
footer. Pages read top-to-bottom like a pamphlet.

**Why it was rejected.** Three reasons, in order of weight:
1. **It makes a Discord bot look like a literary journal.** The visitor's job is "can I trust this bot
   in my server?" — a pamphlet answers a question nobody asked, and it makes the product feel older and
   smaller than it is.
2. **Letterpress cannot be done honestly in a browser.** Deboss is a text-shadow/filter trick; at 2×
   zoom it reads as a blur, and on a phone it costs legibility. The direction's best idea is the one
   that survives implementation worst.
3. **Its dark variant is a page at night** — an inversion by construction, which the brief explicitly
   forbids.

**What was kept.** Its editorial discipline: the hairline folio frame, the rule-as-structure, the
generous measure, and the refusal of card-grid layouts. All of that lives inside direction A.

---

## C. Rose Night Instrument — *rejected as the identity, kept as the hero's physics*

**Premise.** Read "Roseglass" literally and technically: smoked rose glass over a deep charcoal
instrument panel. Monospaced labels, precise ticks, an aperture that behaves like an optic. This is the
direction that would look most at home on a Linear/Vercel-adjacent product page.

**Material logic.** Smoked glass and emitted light. Surfaces are lacquer; light comes from inside them;
elevation is a halo, not a shadow.

**Typographic voice.** Plex Mono for everything structural (labels, counts, command names), one
high-contrast serif for numbers, Arabic in Plex Arabic. Very "instrument".

**Why it was rejected as the identity.**
1. **It is the default of the category.** Every Discord-bot and dev-tool site is dark-first with
   glowing accents; picking it would have made the brief's "not a Discord-bot template" clause the one
   thing the site failed.
2. **It contradicts the brief's own naming.** "Pearl Light" is the daylight face of this brand; making
   the dark face primary would have inverted the brand to satisfy the category.
3. **Dark-first is expensive to make premium** — glow, glass and gradient ramps all need per-component
   tuning, and they degrade badly at low brightness and in reduced-transparency modes.

**What was kept.** Its optics: the hero's concentric aperture, the specular highlight, and the
"instrument" micro-label in Plex Mono. Those are exactly the parts of Rose Night that make the light
theme feel engineered rather than soft. And Rose Night survives as the real dark variant — an
independently composed night composition using this direction's elevation law (luminance + halo instead
of drop shadows).

---

## Evaluation

Scored 1–5 against the constraints that actually decide the outcome, not against taste.

| Criterion | A. Pearl Light | B. Vellum & Seal | C. Rose Night |
|---|---|---|---|
| Premium, not a Discord-bot template | **5** — no category convention is reused | 4 — distinctive but reads as print, not product | 2 — visually identical to the category default |
| Arabic-first integrity | **5** — Arabic is the display voice, not a translation layer | 4 — beautiful at text size, weak at display | 3 — Arabic in a UI sans at small sizes, Latin-led |
| Light primary + *independent* dark | **5** — material logic generates both faces | 2 — dark is a page at night (inversion) | 3 — dark is primary, so the light face is the afterthought |
| Buildable with SVG/CSS only (no WebGL, stock, AI art) | **5** — one bloom, hairlines, one pearl | 3 — deboss/letterpress is a filter trick that fails at zoom | 4 — glass and glow need per-component tuning |
| Distinctiveness in the Arabic bot market | **5** — nobody in this space looks like a jeweller's window | 4 | 2 |
| Longevity (will not look dated in 3 years) | **5** — neutral field, one accent, no trend devices | 3 — the editorial-print revival is already cycling out | 2 — dark-glow UI dates fastest of all |
| **Total** | **30 / 30** | 20 / 30 | 16 / 30 |

**Decision: A.** Directions B and C are not discarded, they are *subordinated*: B supplies the editorial
discipline (folio frame, hairlines, measure), C supplies the optics (aperture, specular bloom, instrument
labels), and A owns the palette, the type pairing and the composition. That is why the chosen system can
describe a dark variant without inverting anything: Rose Night is C's elevation law applied to A's
palette.

## What "premium" is allowed to mean here

A short list, because this is where these projects usually drift: premium means (1) one accent colour
used sparingly, (2) real type with real licensing, (3) optical alignment and optical sizing, (4) motion
that a person would not notice but would miss, (5) nothing that exists only to fill space. It does not
mean gold, marble, glassmorphism, 3D, or a dark hero with a glowing gradient — all four are banned.
