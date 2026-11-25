#!/usr/bin/env python3
"""Angel — architecture diagram, drawn from a hand-written list of lanes and modules.

`LANES` is maintained by hand, so the picture cannot notice a module that landed or left on its
own; `tests/test_docs_assets.py` fails when a path printed here stops existing. Regenerate after
moving code:

    python3 tools/design/gen_architecture.py

Writes docs/screenshots/architecture.svg (RTL, self-contained styles, no external font fetch).
"""

from __future__ import annotations

import pathlib

W = 1200
PAD = 40
HEAD = 104
LANE_H = 96
LANE_GAP = 20
AR = "'Cairo', 'Noto Kufi Arabic', system-ui, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, monospace"
BG = "#0E1320"
CARD = "#141A28"
CHIP = "#1B2333"
GOLD = "#D4AF37"
INK = "#E9E4D6"
MUTED = "#8E8778"
BORDER = "#2A3247"

LANES: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "الوارد",
        "inbound",
        [("حدث ديسكورد", "bot.py"), ("أوامر السلاش", "cogs/*"), ("الصلاحيات", "angel/authz.py")],
    ),
    (
        "القرار",
        "decision",
        [("الموجّه اللغوي", "angel/nl_router.py"), ("الطابور", "angel/work_queue.py"), ("سلسلة النماذج", "angel/brain.py")],
    ),
    (
        "الحالة",
        "state",
        [("الذاكرة والأرشيف", "angel/database.py"), ("الوسائط", "angel/media.py"), ("الشبكة", "angel/net.py")],
    ),
    (
        "الخارج",
        "outbound",
        [("بوابة التأكيد", "angel/confirmations.py"), ("واجهة ديسكورد", "discord.py")],
    ),
]

CHIP_W = 210
CHIP_H = 58
CHIP_GAP = 14
CHIPS_RIGHT = 940


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def lane(index: int, title: str, subtitle: str, chips: list[tuple[str, str]]) -> str:
    y = HEAD + index * (LANE_H + LANE_GAP)
    parts = [
        f'  <rect x="{PAD}" y="{y}" width="{W - PAD * 2}" height="{LANE_H}" rx="12" fill="{CARD}" stroke="{BORDER}"/>',
        f'  <text x="{W - PAD - 26}" y="{y + 40}" text-anchor="start" direction="rtl" fill="{INK}" '
        f'font-family="{AR}" font-size="18" font-weight="700">{esc(title)}</text>',
        f'  <text x="{W - PAD - 26}" y="{y + 64}" text-anchor="end" direction="ltr" fill="{MUTED}" '
        f'font-family="{MONO}" font-size="11">{esc(subtitle)}</text>',
    ]
    for i, (label, module) in enumerate(chips):
        x = CHIPS_RIGHT - (i + 1) * CHIP_W - i * CHIP_GAP
        cy = y + LANE_H / 2
        parts += [
            f'  <rect x="{x}" y="{cy - CHIP_H / 2}" width="{CHIP_W}" height="{CHIP_H}" rx="9" fill="{CHIP}" stroke="{BORDER}"/>',
            f'  <text x="{x + CHIP_W / 2}" y="{cy - 6}" text-anchor="middle" direction="rtl" fill="{INK}" '
            f'font-family="{AR}" font-size="14">{esc(label)}</text>',
            f'  <text x="{x + CHIP_W / 2}" y="{cy + 15}" text-anchor="middle" direction="ltr" fill="{GOLD}" '
            f'font-family="{MONO}" font-size="11.5">{esc(module)}</text>',
        ]
    return "\n".join(parts)


def arrows() -> str:
    x = PAD + 26
    out = []
    for index in range(len(LANES) - 1):
        y1 = HEAD + index * (LANE_H + LANE_GAP) + LANE_H
        y2 = y1 + LANE_GAP
        out.append(
            f'  <path d="M{x} {y1} V{y2 - 2}" stroke="{GOLD}" stroke-width="1.4" opacity="0.65"/>'
            f'\n  <path d="M{x - 5} {y2 - 6} l5 7 l5 -7 z" fill="{GOLD}" opacity="0.65"/>'
        )
    return "\n".join(out)


def render() -> str:
    height = HEAD + len(LANES) * (LANE_H + LANE_GAP) + 28
    lanes = "\n".join(lane(i, title, sub, chips) for i, (title, sub, chips) in enumerate(LANES))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" role="img">
  <title>بنية أنجل</title>
  <desc>أربع طبقات من اليمين إلى اليسار: الوارد، ثم القرار، ثم الحالة، ثم الخارج. كل وحدة مكتوبة باسم ملفها.</desc>
  <rect width="{W}" height="{height}" fill="{BG}"/>
  <text x="{W - PAD}" y="52" text-anchor="start" direction="rtl" fill="{INK}" font-family="{AR}" font-size="30" font-weight="700">بنية أنجل</text>
  <text x="{W - PAD}" y="78" text-anchor="start" direction="rtl" fill="{MUTED}" font-family="{AR}" font-size="14">عملية واحدة، وقاعدة واحدة، ولا وسيط رسائل بينهما</text>
{lanes}
{arrows()}
</svg>
"""


def main() -> None:
    out = pathlib.Path(__file__).resolve().parents[2] / "docs/screenshots/architecture.svg"
    out.write_text(render(), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
