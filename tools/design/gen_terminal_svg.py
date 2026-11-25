#!/usr/bin/env python3
"""Render a captured CLI run as a documentation card.

A screenshot taken by hand rots the moment the tool changes. This renders the real captured
output instead, so the picture in the README is the picture the command prints.

Usage:
    python3 tools/design/gen_terminal_svg.py --title "angelbot · deploy gate" \
        --in /tmp/gate.txt --out docs/screenshots/deploy-gate.svg
"""

from __future__ import annotations

import argparse
import pathlib

W = 920
PAD = 26
HEAD = 44
LINE = 20
MONO = "ui-monospace, SFMono-Regular, 'JetBrains Mono', Menlo, monospace"
INK = "#E9E4D6"
MUTED = "#8E8778"
GOLD = "#D4AF37"
RED = "#E06C75"
BG = "#0E1320"
BAR = "#161D2B"
BORDER = "#2A3247"


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


MAX_CHARS = 108


def _shown(lines: list[str], budget: int) -> list[str]:
    lines = [line if len(line) <= MAX_CHARS else line[: MAX_CHARS - 1] + "…" for line in lines]
    if len(lines) <= budget:
        return lines
    head = lines[:6]
    tail = lines[-(budget - 7):]
    return head + ["…"] + tail


def _colour(line: str) -> str:
    if "[FAIL]" in line:
        return RED
    if "[PASS]" in line or "checks passed" in line:
        return GOLD
    if line.lstrip().startswith("…"):
        return MUTED
    return INK


def render(title: str, lines: list[str], budget: int = 30) -> str:
    shown = _shown([line.rstrip("\n") for line in lines if line.strip()], budget)
    height = HEAD + PAD * 2 + LINE * len(shown)
    rows = "\n".join(
        f'    <text x="{PAD}" y="{HEAD + PAD + LINE * i + 14}" fill="{_colour(line)}" '
        f'xml:space="preserve">{esc(line)}</text>'
        for i, line in enumerate(shown)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" role="img">
  <title>{esc(title)}</title>
  <desc>Captured output of the deploy gate: every check passes before the service starts.</desc>
  <rect width="{W}" height="{height}" rx="14" fill="{BG}" stroke="{BORDER}"/>
  <path d="M0 14a14 14 0 0 1 14-14h{W - 28}a14 14 0 0 1 14 14v{HEAD - 14}H0Z" fill="{BAR}"/>
  <circle cx="24" cy="22" r="5" fill="#E06C75"/><circle cx="42" cy="22" r="5" fill="#E5C07B"/>
  <circle cx="60" cy="22" r="5" fill="#98C379"/>
  <text x="{W / 2}" y="27" text-anchor="middle" fill="{MUTED}" font-family="{MONO}" font-size="12">{esc(title)}</text>
  <g font-family="{MONO}" font-size="13">
{rows}
  </g>
</svg>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--in", dest="src", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    lines = pathlib.Path(args.src).read_text(encoding="utf-8").splitlines()
    pathlib.Path(args.out).write_text(render(args.title, lines), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
