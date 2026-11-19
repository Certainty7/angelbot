#!/usr/bin/env python3
"""Angel — pipeline diagram, generated once and emitted in two places that must match:
   1. website/src/components/PipelineDiagram.astro  (inline SVG, theme-aware via CSS vars)
   2. website/design/pipeline.html                  (QA proof page, same markup)
"""
import pathlib

W, H = 1200, 360
Y = 150
XS = [1080, 840, 600, 360, 120]          # RTL: stage 1 is rightmost
R_OUT, R_IN = 46, 30

STAGES = [
    ("حدث من Discord", "on_message · interaction"),
    ("الموجّه اللغوي", "angel/nl_router.py"),
    ("الذاكرة والأرشيف", "angel/database.py"),
    ("قرار مقترح", "angel/brain.py"),
    ("تنفيذ بعد التأكيد", "cogs/*"),
]
GATE_X = (XS[3] + XS[4]) / 2


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def node(i, x):
    title, module = STAGES[i]
    return f"""      <g class="stage" transform="translate({x} {Y})">
        <circle class="stage__ring" r="{R_OUT}"/>
        <circle class="stage__disc" r="{R_IN}"/>
        <text class="stage__num" y="1" text-anchor="middle" dominant-baseline="middle">{i + 1}</text>
        <g transform="translate(0 {R_OUT + 34})">
          <text class="stage__title" text-anchor="middle" direction="rtl">{esc(title)}</text>
          <text class="stage__module" y="22" text-anchor="middle" direction="ltr">{esc(module)}</text>
        </g>
      </g>"""


def connector(x_from, x_to, cls="link"):
    """Arrow pointing left (the direction of the flow in RTL)."""
    x1, x2 = x_from - R_OUT - 12, x_to + R_OUT + 12
    return (f'      <path class="{cls}" d="M{x1} {Y} H{x2 + 16}"/>'
            f'\n      <path class="{cls}__head" d="M{x2 + 16} {Y} l14 -7 v14 z"/>')


def gate():
    return f"""      <g class="gate" transform="translate({GATE_X} {Y})">
        <path class="gate__mark" d="M0 -18 L15 0 L0 18 L-15 0 Z"/>
        <text class="gate__label" y="46" text-anchor="middle" direction="rtl">بوابة التأكيد</text>
      </g>"""


def return_arc():
    """Dashed return path under the labels: no confirmation, nothing executes.
    It runs 66 px below the module line so it can never graze a label, then turns
    up into the bottom of stage 4 with a small arrowhead."""
    x_gate, x_prev = GATE_X, XS[3]
    y_lane = Y + 150
    y_turn = Y + R_OUT + 10
    return (f'      <path class="return" d="M{x_gate} {Y + 22} V{y_lane} H{x_prev} V{y_turn}"/>'
            f'\n      <path class="return__head" d="M{x_prev} {y_turn} l-6 12 h12 z"/>'
            f'\n      <text class="return__label" x="{(x_gate + x_prev) / 2 + 18}" y="{y_lane - 12}" '
            f'text-anchor="middle" direction="rtl">بلا تأكيد: لا تنفيذ</text>')


svg = f"""<svg class="pipeline" viewBox="0 0 {W} {H}" role="img" aria-labelledby="pipeline-title pipeline-desc">
  <title id="pipeline-title">مسار الرسالة في أنجل</title>
  <desc id="pipeline-desc">خمس مراحل من اليمين إلى اليسار: حدث من ديسكورد، الموجّه اللغوي، الذاكرة والأرشيف،
  قرار مقترح، ثم بوابة التأكيد قبل التنفيذ. إن لم يُؤكَّد القرار لا يُنفَّذ شيء.</desc>

  <g class="pipeline__body">
{connector(XS[0], XS[1])}
{connector(XS[1], XS[2])}
{connector(XS[2], XS[3])}
      <path class="link" d="M{XS[3] - R_OUT - 12} {Y} H{GATE_X + 16}"/>
      <path class="link" d="M{GATE_X - 16} {Y} H{XS[4] + R_OUT + 28}"/>
      <path class="link__head" d="M{XS[4] + R_OUT + 16} {Y} l14 -7 v14 z"/>
{gate()}
{return_arc()}
{node(0, XS[0])}
{node(1, XS[1])}
{node(2, XS[2])}
{node(3, XS[3])}
{node(4, XS[4])}
  </g>

  <text class="pipeline__foot" x="{W - 40}" y="{H - 14}" text-anchor="end" direction="rtl">
    النموذج يقترح، والبوابة تُقرّر — ولا إجراء إشرافي يُنفَّذ بلا تأكيد.
  </text>
</svg>"""

STYLE = """
  .pipeline { inline-size: 100%; block-size: auto; color: var(--ink-900); }
  .pipeline .link { fill: none; stroke: var(--quartz-400); stroke-width: 1; }
  .pipeline .link__head { fill: var(--quartz-400); }
  .pipeline .stage__ring { fill: none; stroke: var(--quartz-400); stroke-width: 1; opacity: .85; }
  .pipeline .stage__disc { fill: var(--surface-card); stroke: var(--border-hair-color); }
  .pipeline .stage__num {
    font-family: var(--font-mono); font-size: 17px; font-weight: 500;
    fill: var(--rose-600);
  }
  .pipeline .stage__title {
    font-family: var(--font-ar-display); font-weight: 700; font-size: 20px;
    fill: var(--text-primary);
  }
  .pipeline .stage__module {
    font-family: var(--font-mono); font-size: 11.5px; fill: var(--text-muted);
    letter-spacing: .02em;
  }
  .pipeline .gate__mark { fill: none; stroke: var(--rose-600); stroke-width: 1.4; }
  .pipeline .gate__label {
    font-family: var(--font-ar-text); font-size: 12px; font-weight: 600; fill: var(--rose-600);
  }
  .pipeline .return { fill: none; stroke: var(--rose-600); stroke-width: 1;
    stroke-dasharray: 3 5; opacity: .55; }
  .pipeline .return__head { fill: var(--rose-600); opacity: .55; }
  .pipeline .return__label {
    font-family: var(--font-ar-text); font-size: 11.5px; fill: var(--text-muted);
  }
  /* Below 640 px the diagram would be 6 px type; the ordered list is the
     accessible equivalent and carries the same five stages. */
  @media (max-width: 640px) {
    .pipeline { display: none; }
  }
  .pipeline .pipeline__foot {
    font-family: var(--font-ar-text); font-size: 12px; fill: var(--text-muted);
  }
"""

ROOT = pathlib.Path(__file__).resolve().parents[2] / "website"
(ROOT / "src/components/PipelineDiagram.astro").write_text(
    "---\n"
    "/** Angel — the message pipeline, as one original diagram.\n"
    " *  Inline SVG (not an <img>) so every stroke reads tokens and the diagram\n"
    " *  follows the theme. Generated by tools/…/gen_pipeline.py; edit there. */\n"
    "interface Props { class?: string }\n"
    "const { class: className = '' } = Astro.props;\n"
    "---\n\n"
    f'<figure class:list={{["pipeline-figure", className]}}>\n{svg}\n'
    "  <figcaption>مسار الرسالة: من الحدث إلى التنفيذ، وبوابة تأكيد في المنتصف.</figcaption>\n"
    "</figure>\n\n"
    f"<style is:global>{STYLE}</style>\n"
)
print("wrote PipelineDiagram.astro")

(ROOT / "design/pipeline.html").write_text(
    '<!doctype html>\n<html lang="ar" dir="rtl" data-theme="light">\n<head>\n'
    '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "<title>pipeline diagram — proof</title>\n"
    '<link rel="stylesheet" href="/styles/fonts.css">\n'
    '<link rel="stylesheet" href="/styles/tokens.css">\n'
    '<link rel="stylesheet" href="/styles/base.css">\n'
    f"<style>{STYLE}\n  body {{ margin:0; padding:48px; background: var(--surface-page); }}\n"
    "  .pipeline-figure { margin:0 auto; max-inline-size: 1200px; }\n"
    "  figcaption { margin-block-start: 12px; font-family: var(--font-ar-text); font-size: 13px; color: var(--text-muted); }\n"
    "</style>\n</head>\n<body>\n"
    f'<figure class="pipeline-figure">{svg}<figcaption>مسار الرسالة: من الحدث إلى التنفيذ، وبوابة تأكيد في المنتصف.</figcaption></figure>\n'
    "</body></html>\n"
)
print("wrote design/pipeline.html")
