# Dependency security

Date: 2026-11-14. Two dependency surfaces: the bot (Python, pinned) and the website (npm, lockfile).

## Bot — Python

`requirements.txt` pins 10 packages exactly. There is no floating range, no `~=`, no unpinned extra.

| Package | Pinned | OSV advisories |
|---|---|---|
| discord.py | 2.7.1 | none |
| PyNaCl | 1.6.2 | none |
| davey | 0.1.7 | none |
| yt-dlp | 2026.10.26 | none |
| yt-dlp-ejs | 0.8.0 | none |
| aiohttp | 3.14.5 | none |
| aiosqlite | 0.22.1 | none |
| Pillow | 13.0.0 | none |
| python-dotenv | 1.2.4 | none |
| imageio-ffmpeg | 0.6.0 | none |

Method: one `POST https://api.osv.dev/v1/query` per pinned package with
`{"version": …, "package": {"name": …, "ecosystem": "PyPI"}}`, 10 queries, **0 advisories returned**.

Note carried from the file itself: `discord.py[voice]` declares `PyNaCl<1.6` while DAVE needs
`1.6.2`, which is why the voice stack is pinned explicitly instead of using the `[voice]` extra. This
is a deliberate deviation, not an oversight — "simplifying" it back breaks installation.

## Website — npm

- Astro + TypeScript, installed with `npm ci` from a committed `website/package-lock.json`, so the
  transitive graph is reproducible.
- CI runs `npm ci --no-audit --no-fund` and Playwright **chromium only**, keeping the download small and
  the graph identical between local and CI.
- The dependency audit is a release gate: `npm audit --omit=dev` must report no high or critical
  finding before production. This line stays unchecked until the site's lockfile is final.

## Portal — `aetherisnode-home`

**Zero dependencies.** `package.json` declares no `dependencies` and no `devDependencies`; the build is
`node scripts/build.mjs` with the Node standard library. There is no lockfile to audit and no
supply-chain surface beyond the CI actions, which are pinned to commit SHAs.

## Policy

1. Pin exact versions; commit the lockfile.
2. A package is added only if the feature cannot be written in ~50 lines. A framework is not added for
   a decorative component.
3. Any critical or high advisory blocks the release; medium and low are reviewed and documented rather
   than auto-fixed, because an automatic bump can silently change behaviour.
4. GitHub Actions are pinned to immutable SHAs. Both workflows run with `contents: read`.
5. No paid plan is bought to enable a scanner. Where a cloud scanner is unavailable on the free plan,
   the local equivalent is used and named here.
