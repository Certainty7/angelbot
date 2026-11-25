#!/usr/bin/env python3
"""Render the recall probe as an RTL table.

Arabic inside a terminal transcript re-orders unpredictably, so the probe's own output is parsed
and laid out as a table instead of pasted as a screenshot.

Usage:
    python3 tools/design/gen_recall_svg.py --in /tmp/recall.txt --out docs/screenshots/recall-probe.svg
"""

from __future__ import annotations

import argparse
import pathlib
import re

W = 920
PAD = 36
HEAD_H = 96
ROW = 40
AR = "'Cairo', 'Noto Kufi Arabic', system-ui, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, monospace"
BG = "#0E1320"
CARD = "#141A28"
GOLD = "#D4AF37"
INK = "#E9E4D6"
MUTED = "#8E8778"
BORDER = "#2A3247"

LINE = re.compile(r"^\[(HIT|MISS)\s*\]\s+(\S+)\s+'(.*?)'\s+q='(.*?)'\s+n=(\d+)")


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def parse(text: str) -> list[tuple[str, str, str, str, str]]:
    rows = []
    for line in text.splitlines():
        match = LINE.match(line.strip())
        if match:
            rows.append(match.groups())
    return rows


def render(rows: list[tuple[str, str, str, str, str]]) -> str:
    height = HEAD_H + ROW * (len(rows) + 1) + 78
    right = W - PAD
    cols = {"cat": right - 16, "fact": right - 150, "q": right - 450, "n": PAD + 26}
    body = []
    for i, (hit, cat, fact, question, n) in enumerate(rows):
        y = HEAD_H + ROW * (i + 1) + 20
        mark = GOLD if hit == "HIT" else "#E06C75"
        body.append(
            f'    <text x="{cols["cat"]}" y="{y}" text-anchor="start" direction="rtl" fill="{mark}" '
            f'font-family="{MONO}" font-size="12">{esc(cat)}</text>\n'
            f'    <text x="{cols["fact"]}" y="{y}" text-anchor="start" direction="rtl" fill="{INK}" '
            f'font-family="{AR}" font-size="15">{esc(fact)}</text>\n'
            f'    <text x="{cols["q"]}" y="{y}" text-anchor="start" direction="rtl" fill="{MUTED}" '
            f'font-family="{AR}" font-size="14">{esc(question)}</text>\n'
            f'    <text x="{cols["n"]}" y="{y}" text-anchor="end" direction="ltr" fill="{MUTED}" '
            f'font-family="{MONO}" font-size="12">n={esc(n)}</text>'
        )
    header_y = HEAD_H + 20
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" role="img">
  <title>recall probe — 10/10</title>
  <desc>Ten stored facts are retrieved by a paraphrased question, on a temporary copy of the database.</desc>
  <rect width="{W}" height="{height}" rx="14" fill="{BG}" stroke="{BORDER}"/>
  <text x="{right}" y="52" text-anchor="start" direction="rtl" fill="{INK}" font-family="{AR}" font-size="20" font-weight="700">فحص الاستدعاء: عشرة أسئلة مُعاد صياغتها</text>
  <text x="{right}" y="76" text-anchor="start" direction="rtl" fill="{MUTED}" font-family="{AR}" font-size="13">قاعدة مؤقتة، بيانات تجريبية، ولا اتصال بأي مزوّد</text>
  <g font-size="12" fill="{MUTED}" font-family="{AR}">
    <text x="{cols["cat"]}" y="{header_y}" text-anchor="start" direction="rtl">التصنيف</text>
    <text x="{cols["fact"]}" y="{header_y}" text-anchor="start" direction="rtl">الحقيقة المخزّنة</text>
    <text x="{cols["q"]}" y="{header_y}" text-anchor="start" direction="rtl">السؤال</text>
    <text x="{cols["n"]}" y="{header_y}" text-anchor="end" direction="ltr">rows</text>
  </g>
  <path d="M{PAD} {HEAD_H + 30} H{right}" stroke="{BORDER}" stroke-width="1"/>
  <g>
{chr(10).join(body)}
  </g>
  <text x="{right}" y="{height - 20}" text-anchor="start" direction="rtl" fill="{GOLD}" font-family="{AR}" font-size="15" font-weight="700">النتيجة 10/10 — كل حقيقة عادت من سؤال مُعاد صياغته</text>
</svg>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="src", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    text = pathlib.Path(args.src).read_text(encoding="utf-8")
    rows = parse(text)
    if len(rows) != 10 or any(row[0] != "HIT" for row in rows):
        raise SystemExit(f"expected 10 HIT rows, parsed {len(rows)}: {[r[0] for r in rows]}")
    pathlib.Path(args.out).write_text(render(rows), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
