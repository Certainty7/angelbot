"""Text -> SVG path conversion with real HarfBuzz shaping.

Used to bake the Angel wordmarks as outlines so they render identically without
depending on web-font loading. Supports variable-font instancing.
"""
import io
import os

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer


def instantiate(font_bytes_or_path, axes=None):
    """Return TTFont with the requested variable axes pinned (or as-is)."""
    if isinstance(font_bytes_or_path, str):
        tt = TTFont(font_bytes_or_path)
    else:
        tt = TTFont(io.BytesIO(font_bytes_or_path))
    if axes and "fvar" in tt:
        tt = instancer.instantiateVariableFont(tt, axes, inplace=False, updateFontNames=False)
    return tt


class Shaper:
    def __init__(self, tt, features=None):
        self.tt = tt
        buf = io.BytesIO()
        tt.save(buf)
        data = buf.getvalue()
        self.face = hb.Face(hb.Blob(data))
        self.font = hb.Font(self.face)
        self.upem = tt["head"].unitsPerEm
        self.font.scale = (self.upem, self.upem)
        self.features = features or {"kern": True, "liga": True, "calt": True}
        self.glyph_set = tt.getGlyphSet()
        self.glyph_order = tt.getGlyphOrder()

    def shape(self, text, direction="ltr", script=None, language=None):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.direction = direction
        if script:
            buf.script = script
        if language:
            buf.language = language
        hb.shape(self.font, buf, self.features)
        return list(zip(buf.glyph_infos, buf.glyph_positions))

    def path_for(self, text, size_px, direction="ltr", script=None, language=None,
                 tracking=0.0, x=0.0, y=0.0, precision=3):
        """Return (d, width_px, bbox) — y is the BASELINE position, SVG coords.

        tracking: extra advance per glyph as a fraction of size_px (Latin only).
        """
        shaped = self.shape(text, direction, script, language)
        s = size_px / self.upem
        parts = []
        pen_all = []
        cursor = 0.0
        for info, pos in shaped:
            gname = self.glyph_order[info.codepoint]
            spen = SVGPathPen(self.glyph_set, ntos=lambda v: ("%.*f" % (precision, v)).rstrip("0").rstrip(".") or "0")
            tpen = TransformPen(spen, (s, 0, 0, -s, x + (cursor + pos.x_offset) * s, y - pos.y_offset * s))
            self.glyph_set[gname].draw(tpen)
            d = spen.getCommands()
            if d:
                parts.append(d)
            cursor += pos.x_advance + (tracking * self.upem if tracking else 0)
        d_all = " ".join(parts)
        bpen = BoundsPen(self.glyph_set)
        bounds_cursor = 0.0
        minx = miny = 1e9
        maxx = maxy = -1e9
        for info, pos in shaped:
            gname = self.glyph_order[info.codepoint]
            bp = BoundsPen(self.glyph_set)
            tp = TransformPen(bp, (s, 0, 0, -s, x + (bounds_cursor + pos.x_offset) * s, y - pos.y_offset * s))
            self.glyph_set[gname].draw(tp)
            if bp.bounds:
                x0, y0, x1, y1 = bp.bounds
                minx, miny = min(minx, x0), min(miny, y0)
                maxx, maxy = max(maxx, x1), max(maxy, y1)
            bounds_cursor += pos.x_advance + (tracking * self.upem if tracking else 0)
        bbox = None if minx > maxx else (minx, miny, maxx, maxy)
        return d_all, (cursor) * s, bbox

    def metrics(self):
        os2 = self.tt["OS/2"]
        hhea = self.tt["hhea"]
        return {
            "upem": self.upem,
            "ascender": hhea.ascent,
            "descender": hhea.descent,
            "cap_height": getattr(os2, "sCapHeight", None),
            "x_height": getattr(os2, "sxHeight", None),
        }
