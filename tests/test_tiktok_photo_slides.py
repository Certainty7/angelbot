"""Offline proof for TikTok photo-post extraction (no network).

Fixture in -> slide list out, through the real `extract_tiktok_media_items` with a
fake HTTP session. Guards three behaviours the live CDN made expensive to discover:
  * a slide the CDN refuses is retried from a fresh TikWM quote instead of dropped
  * a post is capped at 10 slides to protect the 1 GB host
  * chunk_slides sends every batch (10 attachments per Discord message)

Run: venv/bin/python tests/test_tiktok_photo_slides.py
"""
import asyncio
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import PIL.Image  # noqa: E402

from angel import media  # noqa: E402
from angel.net import SafeAsyncResolver  # noqa: E402


def _jpeg(seed: int) -> bytes:
    buf = io.BytesIO()
    PIL.Image.new("RGB", (8, 8), (seed % 256, (seed * 7) % 256, (seed * 13) % 256)).save(buf, "JPEG")
    return buf.getvalue()


class _Chunks:
    def __init__(self, body: bytes):
        self.body = body

    async def iter_chunked(self, n: int):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]


class _Resp:
    def __init__(self, status: int, body: bytes, ctype: str = "image/jpeg"):
        self.status = status
        self._body = body
        self.headers = {"Content-Type": ctype}
        self.content = _Chunks(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return json.loads(self._body)

    async def text(self):
        return self._body.decode("utf-8", "replace")


class FakeTikTok:
    """Quotes slides twice (the second quote re-signs them) and refuses chosen URLs."""

    def __init__(self, slides: int, refused_first_quote=()):
        self.slides = slides
        self.refused = set(refused_first_quote)
        self.quotes = 0
        self.image_hits = []
        # safe_fetch_response only accepts sessions backed by the connect-time SSRF resolver.
        self.connector = SimpleNamespace(_resolver=SafeAsyncResolver())

    def _api_body(self) -> bytes:
        self.quotes += 1
        nums = range(1, self.slides + 1)
        urls = [f"https://p16.mock.cdn/slide{i}.jpeg?q={self.quotes}" for i in nums]
        return json.dumps({"code": 0, "msg": "success", "data": {"title": "t", "author": {"nickname": "a"}, "images": urls}}).encode()

    def get(self, url, **kwargs):
        if "tikwm.com/api" in url:
            return _Resp(200, self._api_body(), "application/json")
        self.image_hits.append(url)
        idx = int(url.split("/slide")[1].split(".")[0].split("?")[0])
        bad = self.quotes == 1 and idx in self.refused
        return _Resp(403 if bad else 200, b"" if bad else _jpeg(idx))


async def _extract(fake):
    async def _session():
        return fake

    media.get_shared_http_session = _session
    try:
        return await media.extract_tiktok_media_items("https://www.tiktok.com/@a/photo/1")
    finally:
        media.get_shared_http_session = _orig_session


_orig_session = media.get_shared_http_session


async def main():
    # 1. Two slides refused by the first quote's CDN node are recovered by the retry.
    fake = FakeTikTok(slides=10, refused_first_quote=(5, 7))
    files, fixed, caption = await _extract(fake)
    names = [fn for _, fn in files]
    assert len(files) == 10, f"expected all 10 slides, got {len(files)}: {names}"
    assert names == [f"tiktok_{i}.jpg" for i in range(1, 11)], f"slide order/names wrong: {names}"
    assert fixed is None and caption.startswith("📸"), f"photo post must not fall back: {fixed!r} {caption!r}"
    assert fake.quotes == 2, f"expected one requote, saw {fake.quotes} quotes"

    # 2. A complete first pass never re-quotes.
    fake = FakeTikTok(slides=3)
    files, _, _ = await _extract(fake)
    assert len(files) == 3 and fake.quotes == 1, f"unexpected requote or missed slide: {len(files)} {fake.quotes}"

    # 3. The downloader caps a post at 10 slides / 25 MB to protect the small host.
    fake = FakeTikTok(slides=40)
    files, _, _ = await _extract(fake)
    assert len(files) == 10, f"expected the 10-slide cap, got {len(files)}"

    # 4. Sending: every batch goes out, 10 attachments per message.
    slides = [(b"x", f"tiktok_{i}.jpg") for i in range(1, 36)]
    assert len(media.chunk_slides(slides)) == 4, "35 slides must be sent as 4 batches"
    assert len(media.chunk_slides(slides)[0]) == 10, "Discord takes 10 attachments per message"
    assert media.chunk_slides([]) == [], "an empty post must not send a message"

    print("[PASS] tiktok-photo-slides: 10/10 slides recovered, 10 cap, 4 send batches")


def test_tiktok_photo_slides():
    """Pytest entry point; the assertions live in main() for direct runs."""
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
