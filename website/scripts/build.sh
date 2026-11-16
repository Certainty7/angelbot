#!/usr/bin/env bash
# Angel website build — single source of truth for Cloudflare Pages and CI.
#
# Contract
#   input : repository root (bot source + website/)
#   output: website/dist — static files only, no backend, no secrets
#   exit  : 0 = publishable, non-zero = do not deploy
#
# Cloudflare Pages build command: bash website/scripts/build.sh
# Root directory: repository root (the command generator reads cogs/ and bot.py)
# Build output directory: website/dist
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

log() { printf '[website-build] %s\n' "$*"; }
die() { printf '[website-build] FATAL: %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || die "python3 not found in the build image"
command -v npm     >/dev/null 2>&1 || die "npm not found in the build image"

# Version floor. Astro 7 requires Node >= 22.23.4 and the Cloudflare v3 build image
# defaults to exactly that; `engines` in package.json is ignored by the v3 image, so a
# wrong NODE_VERSION or .node-version must fail here, with a readable reason.
require_min() { # actual, minimum, label
  if [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" != "$2" ]; then
    die "$3 $1 is older than the required $2"
  fi
}
node_version="$(node -v 2>/dev/null | sed 's/^v//')"
py_version="$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
require_min "$node_version" "22.23.4" "Node.js"
require_min "$py_version" "3.9.0" "Python"
log "python=$py_version node=$node_version npm=$(npm -v 2>/dev/null || echo '?')"

# ---------------------------------------------------------------- step 1/3
# Static product data is derived from the bot source at build time.
# Stdlib only: no pip install, no network, no credentials.
log "step 1/3 — generating product data from bot source"
python3 tools/website-data-generator/generate.py
python3 tools/website-data-generator/generate.py --check \
  || die "generator --check failed: generated data is stale or non-deterministic"

# ---------------------------------------------------------------- step 2/3
log "step 2/3 — installing and building the static site"
[ -f website/package.json ]      || die "website/package.json is missing — the Astro scaffold has not landed"
[ -f website/package-lock.json ] || die "website/package-lock.json is missing — npm ci needs a committed lockfile"
( cd website && npm ci --no-audit --no-fund && npm run build )

# ---------------------------------------------------------------- step 3/3
# Publish-output guards: Cloudflare Pages limits and private-material leaks.
log "step 3/3 — verifying publish output"
DIST="website/dist"
[ -d "$DIST" ]            || die "$DIST was not produced"
[ -f "$DIST/index.html" ] || die "$DIST/index.html is missing"

# Pages answers an unknown path from the closest 404.html, walking up to the root; Astro emits a
# nested 404 route as a directory. Ship the file Pages asks for so English visitors get the
# English 404 instead of falling back to the Arabic root one.
[ -f "$DIST/en/404/index.html" ] || die "$DIST/en/404/index.html is missing — the English 404 route did not build"
cp "$DIST/en/404/index.html" "$DIST/en/404.html"

files=$(find "$DIST" -type f | wc -l | tr -d ' ')
[ "$files" -le 20000 ] || die "$files files exceeds the Cloudflare Pages limit of 20,000"

oversized=$(find "$DIST" -type f -size +25M -print -quit)
[ -z "$oversized" ] || die "asset larger than 25 MiB: $oversized"

leaked=$(find "$DIST" \( -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name '*.key' \
        -o -name '*.sqlite*' -o -name '*.db' -o -name '.git' -o -name 'node_modules' \) -print -quit)
[ -z "$leaked" ] || die "private file in publish output: $leaked"

log "publishable: files=$files bytes=$(du -sb "$DIST" | cut -f1) size=$(du -sh "$DIST" | cut -f1)"
log "largest assets:"
find "$DIST" -type f -printf '%s\t%p\n' | sort -rn | head -3 | while read -r size path; do
  printf '[website-build]   %8s  %s\n' "$size" "$path"
done
log "build OK"
