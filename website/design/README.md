# `website/design/` — visual reference, not published

This folder is the **design reference implementation** of the home hero, written by Certina and
measured in `docs/QA/WEB-1-hero-measurements.md`. It is a single static page with the same
markup as `src/components/Hero.astro`, the same `tokens.css`, and its own `aperture.css`.

It is **not** part of the build: Astro only renders `src/pages/`, and only `public/` is copied
verbatim, so nothing here reaches `dist/`. Keep it that way — it is the artefact the visual
review is done against, and the place where a hero change is prototyped before it touches a
component.

## Run it

```bash
python3 -m http.server 8742 --directory website/design
# but the page also needs /fonts, /styles and /assets on the same origin
```

The reliable way (what the measurements used) is a throwaway document root:

```bash
mkdir -p /tmp/angel-design && cd /tmp/angel-design
ln -sfn "$REPO/website/public/fonts"   fonts
ln -sfn "$REPO/website/src/styles"     styles
ln -sfn "$REPO/website/src/assets"     assets
ln -sfn "$REPO/website/design/aperture.css" aperture.css
ln -sfn "$REPO/website/design/aperture.js"  aperture.js
ln -sfn "$REPO/website/design/theme-init.js" theme-init.js
ln -sfn "$REPO/website/design/index.html"    index.html
python3 -m http.server 8742 --bind 127.0.0.1
```

## Files

| File | What it is |
|---|---|
| `index.html` | The hero, verbatim from `HERO_COMPOSITION.md`, with the approved Arabic copy. |
| `aperture.css` | The hero layer: ground, ring stack, bloom, specular, mark, sheen, timeline, breakpoints, header shell. |
| `aperture.js` | Theme toggle + persistence, sticky-header hairline. ~1.6 KB, no dependency. |
| `theme-init.js` | The one blocking script: restores the saved theme before first paint, so there is no flash. |
