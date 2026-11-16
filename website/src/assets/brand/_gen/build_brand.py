"""Build every Angel brand asset (SVG marks, wordmarks, lockups, favicon, OG card source)."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from typo import Shaper, instantiate

INK, PEARL, IVORY = "#221A1B", "#FDFBFA", "#F5EEE7"
ROSE, QUARTZ = "#8A2E45", "#E4C2C6"
NIGHT_INK, NIGHT_ROSE, NIGHT_GROUND = "#F6EEEC", "#E9A9B6", "#14100F"

A_Y, B_Y, A_HALF, OUT_B, IN_B, BAR_Y, PEARL_R = 8.0, 88.0, 2.8, 8.0, 33.0, 50.0, 6.0

FONT_FILES = {
    "ar-display": ("Amiri-Bold.ttf", None),
    "en-display": ("instrument-InstrumentSerif-Regular.ttf", None),
    "ar-text": ("IBMPlexSansArabic-Regular.ttf", None),
    "ar-text-sb": ("IBMPlexSansArabic-SemiBold.ttf", None),
    "en-text": ("IBMPlexSans-var.ttf", {"wght": 400}),
}


def blade(side):
    return ("M {a:.2f} {y:.2f} L {b:.2f} {y:.2f} L {c:.2f} {yb:.2f} L {d:.2f} {yb:.2f} Z").format(
        a=48 + side * A_HALF, b=48.0,
        c=IN_B if side < 0 else 96 - IN_B, d=OUT_B if side < 0 else 96 - OUT_B,
        y=A_Y, yb=B_Y)


def mark_body(blade_color="currentColor", pearl_color=ROSE, with_pearl=True, pearl_r=PEARL_R):
    out = ['<path d="%s" fill="%s"/>' % (blade(-1), blade_color),
           '<path d="%s" fill="%s"/>' % (blade(1), blade_color)]
    if with_pearl:
        out.append('<circle cx="48" cy="%.2f" r="%.2f" fill="%s"/>' % (BAR_Y, pearl_r, pearl_color))
    return "\n  ".join(out)


def svg_doc(body, vb, title, color=None, desc=None, width=None, height=None):
    d = "<desc>%s</desc>" % desc if desc else ""
    c = ' color="%s"' % color if color else ""
    wh = ""
    if width:
        wh = ' width="%g" height="%g"' % (width, height)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s"%s role="img" aria-label="%s"%s>%s\n  %s\n</svg>\n'
            % (vb, wh, title, c, d, body))


def mark_svg(color, pearl, pad=4.0):
    vb = "%g %g %g %g" % (-pad, -pad, 96 + 2 * pad, 96 + 2 * pad)
    return svg_doc(mark_body(color, pearl), vb, "Angel",
                   desc="Angel mark — a pearl held in the aperture of an A.")


def favicon_svg(fullbleed=False):
    """Optical-size tile: redrawn (not scaled) for the pixel grid."""
    ay, by, ah, ob, ib, cy, pr = 6.5, 25.5, 1.2, 6.4, 11.2, 18.4, 2.6
    def bl(side):
        return ("M {a:.2f} {y:.2f} L {b:.2f} {y:.2f} L {c:.2f} {yb:.2f} L {d:.2f} {yb:.2f} Z").format(
            a=16 + side * ah, b=16.0,
            c=ib if side < 0 else 32 - ib, d=ob if side < 0 else 32 - ob, y=ay, yb=by)
    tile = ('<rect width="32" height="32" fill="%s"/>' % ROSE if fullbleed
            else '<rect width="32" height="32" rx="7.5" fill="%s"/>' % ROSE)
    body = ('%s\n  '
            '<path d="%s" fill="%s"/>\n  <path d="%s" fill="%s"/>\n  '
            '<circle cx="16" cy="%.2f" r="%.2f" fill="%s"/>') % (
        tile, bl(-1), PEARL, bl(1), PEARL, cy, pr, QUARTZ)
    return svg_doc(body, "0 0 32 32", "Angel",
                   desc="Angel icon — pearl A on deep rose.")


class Fonts:
    def __init__(self, src):
        self.sh = {k: Shaper(instantiate(os.path.join(src, f), axes)) for k, (f, axes) in FONT_FILES.items()}

    def shape(self, key, text, size, **kw):
        if key.startswith("ar"):
            kw.setdefault("direction", "rtl")
            kw.setdefault("script", "arab")
            kw.setdefault("language", "ar")
        else:
            kw.setdefault("direction", "ltr")
            kw.setdefault("script", "latn")
            kw.setdefault("language", "en")
        return self.sh[key].path_for(text, size, **kw)

    def glyphs(self, key, text):
        d = {"ar": ("rtl", "arab", "ar"), "en": ("ltr", "latn", "en")}[key.split("-")[0]]
        return [self.sh[key].glyph_order[i.codepoint] for i, p in self.sh[key].shape(text, *d)]


def wordmark(fonts, text, key, color, pad=2.0, tracking=0.0, size=200.0):
    d, adv, bb = fonts.shape(key, text, size, tracking=tracking)
    x0, y0, x1, y1 = bb
    d2, _, _ = fonts.shape(key, text, size, tracking=tracking, x=pad - x0, y=pad - y0)
    vb = "0 0 %.2f %.2f" % (x1 - x0 + 2 * pad, y1 - y0 + 2 * pad)
    return svg_doc('<path d="%s" fill="%s"/>' % (d2, color), vb, text, color=color), (x1 - x0, y1 - y0)


def lockup(fonts, text, key, color, pearl, tracking, mark_h=56.0, word_h=38.0, gap=14.0, rtl=True,
           pad=3.0, center_ratio=0.5):
    """mark + wordmark, baseline-anchored, tight viewBox.

    mark_h / word_h are ink heights in viewBox units; center_ratio is where the mark's
    optical centre sits above the baseline, as a fraction of word_h.
    """
    d, adv, bb = fonts.shape(key, text, 1000.0, tracking=tracking)
    x0, y0, x1, y1 = bb          # y is relative to the baseline: y0 < 0 (above), y1 > 0 (below)
    ink_w, ink_h = x1 - x0, y1 - y0
    s = word_h / ink_h
    w = ink_w * s
    s_mark = mark_h / 80.0
    mark_side = 96 * s_mark
    total_w = mark_side + gap + w

    mark_cy = -center_ratio * word_h          # relative to baseline
    top = min(y0 * s, mark_cy - mark_h / 2)
    bottom = max(y1 * s, mark_cy + mark_h / 2)
    B = -top + pad                            # baseline y in the final viewBox
    total_h = bottom - top + 2 * pad

    mx = (total_w - mark_side) if rtl else 0.0
    wx = 0.0 if rtl else mark_side + gap
    my = B + mark_cy - mark_side / 2
    body = ['<g transform="translate(%.3f %.3f) scale(%.6f)">%s</g>'
            % (mx, my, s_mark, mark_body(color, pearl))]
    body.append('<g transform="translate(%.3f %.3f) scale(%.6f)"><path d="%s" fill="%s"/></g>'
                % (wx - x0 * s, B, s, d, color))
    vb = "%g %g %.2f %.2f" % (-pad, -pad, total_w + 2 * pad, total_h + 2 * pad)
    return svg_doc("\n  ".join(body), vb, text, color=color)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    F = Fonts(a.fonts)

    print("glyphs AR:", F.glyphs("ar-display", "أنجل"))
    print("glyphs EN:", F.glyphs("en-display", "ANGEL"))

    AR, EN = "أنجل", "ANGEL"
    out = {}
    out["angel-mark.svg"] = mark_svg(INK, ROSE)
    out["angel-mark-dark.svg"] = mark_svg(NIGHT_INK, NIGHT_ROSE)
    out["angel-mark-mono.svg"] = svg_doc(mark_body("currentColor", "none", with_pearl=False),
                                         "-4 -4 104 104", "Angel")
    out["angel-favicon.svg"] = favicon_svg()
    out["angel-icon-square.svg"] = favicon_svg(fullbleed=True)

    ar_light, ar_ink = wordmark(F, AR, "ar-display", INK)
    ar_dark, _ = wordmark(F, AR, "ar-display", NIGHT_INK)
    out["angel-wordmark-ar.svg"] = ar_light
    out["angel-wordmark-ar-dark.svg"] = ar_dark
    out["angel-wordmark-ar-mono.svg"] = wordmark(F, AR, "ar-display", "currentColor")[0].replace('color="currentColor"', "")
    en_light, en_dims = wordmark(F, EN, "en-display", INK, tracking=0.10)
    en_dark, _ = wordmark(F, EN, "en-display", NIGHT_INK, tracking=0.10)
    out["angel-wordmark-en.svg"] = en_light
    out["angel-wordmark-en-dark.svg"] = en_dark
    out["angel-wordmark-en-mono.svg"] = wordmark(F, EN, "en-display", "currentColor", tracking=0.10)[0].replace('color="currentColor"', "")

    out["angel-lockup-ar.svg"] = lockup(F, AR, "ar-display", INK, ROSE, 0.0, rtl=True, mark_h=54, word_h=40, gap=15, center_ratio=0.20)
    out["angel-lockup-ar-dark.svg"] = lockup(F, AR, "ar-display", NIGHT_INK, NIGHT_ROSE, 0.0, rtl=True, mark_h=54, word_h=40, gap=15, center_ratio=0.20)
    out["angel-lockup-en.svg"] = lockup(F, EN, "en-display", INK, ROSE, 0.16, rtl=False, mark_h=44, word_h=25, gap=16, center_ratio=0.5)
    out["angel-lockup-en-dark.svg"] = lockup(F, EN, "en-display", NIGHT_INK, NIGHT_ROSE, 0.16, rtl=False, mark_h=44, word_h=25, gap=16, center_ratio=0.5)

    for name, body in out.items():
        with open(os.path.join(a.out, name), "w") as fh:
            fh.write(body)
        print("%-34s %6d B" % (name, len(body.encode())))
    print("EN wordmark ink px at size 200: %.1f x %.1f" % en_dims)


if __name__ == "__main__":
    main()
