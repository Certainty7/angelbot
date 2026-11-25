"""Audit finding 19d: a reaction GIF must be a GIF, not arbitrary bytes.

The fetch only checked `status == 200 and len >= 500`, so an HTML error page or an SVG served
with a 200 was uploaded to Discord as `angel_reaction.gif` (evidence: HTML bytes returned as a
GIF). The type check belongs at the boundary: magic bytes always, declared content type when it
contradicts them.
"""

import asyncio
import unittest
from unittest.mock import patch

from angel import brain
from angel.media import is_gif_payload

GIF = b"GIF89a" + b"\x00" * 600
HTML = b"<!DOCTYPE html><html><body>nope</body></html>" + b" " * 600
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>" + b" " * 600


class GifPayloadTest(unittest.TestCase):
    def test_a_real_gif_is_accepted(self):
        self.assertTrue(is_gif_payload(GIF, "image/gif"))

    def test_an_html_page_is_refused_even_when_declared_as_a_gif(self):
        self.assertFalse(is_gif_payload(HTML, "image/gif"))

    def test_an_svg_declared_as_html_is_refused(self):
        self.assertFalse(is_gif_payload(SVG, "text/html"))

    def test_gif_magic_with_a_contradicting_content_type_is_refused(self):
        self.assertFalse(is_gif_payload(GIF, "text/html"))

    def test_a_short_body_is_refused(self):
        self.assertFalse(is_gif_payload(b"GIF89a", "image/gif"))


class GifCandidateTest(unittest.TestCase):
    def _load(self, payload, ctype):
        async def fake_fetch(*a, **k):
            return ("https://x/y", 200, ctype, payload)

        async def run():
            with patch.object(brain, "safe_fetch_response", fake_fetch):
                return await brain.load_gif_candidate(None, "https://x/y", None)

        return asyncio.run(run())

    def test_the_candidate_loader_rejects_html(self):
        self.assertIsNone(self._load(HTML, "text/html"))

    def test_the_candidate_loader_accepts_a_gif(self):
        self.assertEqual(self._load(GIF, "image/gif"), GIF)


if __name__ == "__main__":
    unittest.main()
