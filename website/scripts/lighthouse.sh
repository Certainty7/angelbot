#!/usr/bin/env bash
# Lighthouse evidence for the release gate. Runs against `astro preview`, which serves the exact
# dist/ that Cloudflare Pages publishes. Not part of the build and not a deploy dependency.
#
#   bash website/scripts/lighthouse.sh [port]
#
# Reports land in docs/QA/lighthouse/ as JSON (the machine record) and HTML (the readable one).
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${1:-4321}"
OUT="$ROOT/docs/QA/lighthouse"
LH_VERSION="13.6.0"
CHROME_PATH="${CHROME_PATH:-$(find "$HOME/.cache/ms-playwright" "${PLAYWRIGHT_BROWSERS_PATH:-/nonexistent}" \
  -maxdepth 3 -type f -name chrome 2>/dev/null | head -1)}"

[ -d "$ROOT/website/dist" ] || { echo "build first: bash website/scripts/build.sh" >&2; exit 1; }
[ -n "$CHROME_PATH" ] || { echo "no chromium found; run npx playwright install chromium" >&2; exit 1; }

mkdir -p "$OUT"
export CHROME_PATH

for page in "home:/" "en:/en/" "commands:/commands/"; do
  name="${page%%:*}"
  path="${page#*:}"
  echo "[lighthouse] $path -> $OUT/$name"
  npx --yes "lighthouse@$LH_VERSION" "http://127.0.0.1:$PORT$path" --quiet \
    --chrome-flags='--headless=new --no-sandbox --disable-dev-shm-usage' \
    --output=json --output=html --output-path="$OUT/$name" >/dev/null
done

python3 - "$OUT" <<'PY'
import json, pathlib, sys
out = pathlib.Path(sys.argv[1])
for path in sorted(out.glob('*.report.json')):
    data = json.loads(path.read_text())
    scores = {k: round(v['score'] * 100) for k, v in data['categories'].items() if v['score'] is not None}
    print(path.stem.replace('.report', ''), scores)
PY
