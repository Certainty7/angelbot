# Brand assets — register and rules

Owner: the design owner. Spec: `docs/DESIGN_SYSTEM.md` §2. Direction: `docs/BRAND_DIRECTIONS.md` (A, Pearl Light).

Every file here is original artwork generated from the geometry and fonts described in the design
system — no stock, no traced artwork, no AI-generated imagery, no WebGL. Wordmarks are **baked to
outlines** with HarfBuzz, so they never depend on a font being loaded.

## Files

| File | Size | Box | Use |
|---|---|---|---|
| `angel-mark.svg` | 391 B | 104×104 | Primary mark on light. Ink blades, deep-rose pearl. |
| `angel-mark-dark.svg` | 391 B | 104×104 | Primary mark on Rose Night. Pearl-lit blades, lifted rose pearl. |
| `angel-mark-mono.svg` | 281 B | 104×104 | One-colour use. `currentColor`, pearl omitted (knocked out by the aperture). |
| `angel-favicon.svg` | 428 B | 32×32 | Tab icon, redrawn at 32 units (not a scaled copy). |
| `angel-icon-square.svg` | 419 B | 32×32 | Full-bleed source for OS-masked icons. |
| `angel-wordmark-ar.svg` `-dark` `-mono` | 3.4 KB | 295×282 | Arabic wordmark «أنجل», Amiri Bold, outlines. |
| `angel-wordmark-en.svg` `-dark` `-mono` | 3.4 KB | 553×152 | Latin wordmark `ANGEL`, Instrument Serif, +0.10em, outlines. |
| `angel-lockup-ar.svg` `-dark` | 2.4 KB | 128×66 | Mark + Arabic wordmark, composed for RTL (mark on the right). |
| `angel-lockup-en.svg` `-dark` | 3.5 KB | 176×56 | Mark + Latin wordmark, composed for LTR (mark on the left). |
| `favicon-32.png` | 863 B | 32×32 | Raster tab icon, transparent corners. |
| `favicon-48.png` | 1.4 KB | 48×48 | 2× / Windows small icon. |
| `favicon-180.png` | 3.0 KB | 180×180 | `apple-touch-icon`, full-bleed (iOS masks it). |
| `icon-192.png`, `icon-512.png` | 3.2 / 9.6 KB | 192, 512 | `manifest.webmanifest` icons. |
| `og-image.png` | 212 KB | 1200×630 | Social share card. |
| `og-image.src.html` | 5.7 KB | — | Editable source of the card (fonts + CSS + the SVGs). |

`_gen/` holds the generator (`build_brand.py`, `typo.py`). It is tooling, not an asset: it is never
imported by the site.

### Sizing

Size these by **height** with `width: auto`. The mark's ink occupies 80 of the 104 viewBox units, so a
`height: 32px` mark paints ~24.6px of ink. Minimum sizes, clear space and the do/don't list are in
`docs/DESIGN_SYSTEM.md` §2.2–2.5.

### Regenerating

```bash
# needs: fontTools, uharfbuzz, brotli (python), and the upstream OFL TTFs
python3 website/src/assets/brand/_gen/build_brand.py --fonts <dir-with-ttf> --out website/src/assets/brand
```

The generator prints the shaped glyph runs it produced (`glyph01694 … uni0623` for «أنجل», `A N G E L`
for the Latin wordmark) — an empty or short run means the font did not load and the output must not be
committed.

## Verification (2026-11-14)

| Check | Result |
|---|---|
| Arabic outlines vs. Chrome's own render of «أنجل» at 200px | ink bbox **291×278 in both**; ink area Δ **0.33%** |
| Latin outlines vs. Chrome's own render of `ANGEL` at 200px, +0.10em | bbox width **777 in both**; height 132 vs 131 (1px AA); ink Δ **0.57%** |
| Arabic shaping | 4 shaped glyphs for 4 codepoints: isolated أ + joined ن ج ل (correct: alef is right-joining) |
| Mark symmetry | built from mirrored parameters; rendered at 128/64/32/24/16px on both grounds and inspected |
| Mark legibility | holds to 24px with the pearl; the dedicated 32px artwork is used below that |
| Icon rasters | exact pixel sizes verified (32/48/180/192/512), transparent corners only where intended |
| Social card | rendered by headless Chrome at exactly 1200×630; Arabic descender clear of the Latin line; no clipping |

## Known duplication

`website/public/brand/*.svg` predates this system and is a different mark and wordmark set. Nothing
should reference it; move components to imports from `src/assets/brand/` and delete the old directory.
