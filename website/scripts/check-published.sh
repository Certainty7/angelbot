#!/usr/bin/env bash
# Drift gate for the GitHub Pages fallback.
#
# `Certainty7/angel-web` is a published copy of `website/dist`, not a second source tree. Publishing
# is a manual copy today, which is exactly how a live site ends up older than the branch it claims to
# serve. This compares a fresh build of the current checkout against what the repository actually
# publishes and fails on any difference.
#
#   bash website/scripts/check-published.sh [owner/repo]
#
# Requires network and git. Not part of build.sh: Cloudflare Pages builds from the source repository
# and never needs the fallback.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO="${1:-Certainty7/angel-web}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

[ -d "$ROOT/website/dist" ] || { echo "build first: bash website/scripts/build.sh" >&2; exit 1; }

git clone --quiet --depth 1 "https://github.com/$REPO.git" "$WORK/published"
rm -rf "$WORK/published/.git"

# CNAME is a GitHub Pages publishing artefact (the custom domain), not build output. .nojekyll is
# *required* in the published root: without it GitHub runs Jekyll, which drops every directory whose
# name starts with an underscore - the whole `_astro/` bundle (CSS, modules, brand SVGs) then returns
# 404 and the site loads unstyled and inert. It ships from `public/`, so it must match the build.
rm -f "$WORK/published/CNAME"

# A committed file is not a served file. GitHub Pages runs Jekyll unless .nojekyll exists, and Jekyll
# silently drops `_astro/`, so the build can match the repository byte for byte while the live site is
# unstyled. Ask the host for one real asset.
LIVE="${2:-https://angel.aetherisnode.cloud}"
ASSET="$(grep -o '/_astro/[A-Za-z0-9._-]*\.css' "$ROOT/website/dist/index.html" | head -1)"
if [ -n "$ASSET" ]; then
  # -L: the host answers plain http with a 301 now, and a redirect is not a broken asset.
  code="$(curl -sL -o /dev/null -w '%{http_code}' --max-time 20 "$LIVE$ASSET" || true)"
  if [ "$code" = "200" ]; then
    echo "live asset ok: $code $ASSET"
  else
    echo "LIVE BROKEN: $LIVE$ASSET -> ${code:-no-response} (is .nojekyll published?)" >&2
    exit 1
  fi
fi

if diff -r --brief "$ROOT/website/dist" "$WORK/published"; then
  count=$(find "$ROOT/website/dist" -type f | wc -l | tr -d ' ')
  echo "published copy matches this build ($count files)"
  exit 0
fi

echo "DRIFT: $REPO does not match website/dist of this checkout" >&2
exit 1
