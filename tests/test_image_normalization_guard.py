"""Audit finding 3: image normalization must be serialized and pixel-capped.

WebP (and other non-JPEG/PNG) photos are decoded to RGB before upload. Before the fix
the decode ignored the image semaphore and never checked dimensions, so four 0.8 KiB
WebP files at 18.4 MP each peaked at 281 MiB of allocations.
"""

from __future__ import annotations

import asyncio
import io
import threading

from angel import media
from angel.net import SharedByteBudget

WEBP_HEADER = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 512


class _FakeImage:
    def __init__(self, size, delay=0.0, payload=b"\xff\xd8\xfffakejpeg"):
        self.size = size
        self.delay = delay
        self.payload = payload
        self.converted = False

    def __enter__(self):
        if self.delay:
            threading.Event().wait(self.delay)
        return self

    def __exit__(self, *exc):
        return False

    def convert(self, mode):
        self.converted = True
        return self

    def save(self, buffer, format=None, quality=None):
        buffer.write(self.payload)


def _patch_open(monkeypatch, fake_factory):
    opened: list[_FakeImage] = []

    def fake_open(_buf):
        img = fake_factory()
        opened.append(img)
        return img

    monkeypatch.setattr(media, "Image", type("PIL", (), {"open": staticmethod(fake_open)}))
    return opened


def test_oversized_dimensions_are_rejected_before_any_rgb_allocation(monkeypatch):
    opened = _patch_open(monkeypatch, lambda: _FakeImage((6000, 6000)))  # 36 MP

    assert media._normalize_image_bytes_sync(WEBP_HEADER) is None
    assert opened and opened[0].converted is False


def test_a_12_megapixel_image_is_still_accepted(monkeypatch):
    opened = _patch_open(monkeypatch, lambda: _FakeImage((4000, 3000)))  # exactly 12 MP

    assert media._normalize_image_bytes_sync(WEBP_HEADER) is not None
    assert opened[0].converted is True


def test_normalization_runs_one_at_a_time(monkeypatch):
    _patch_open(monkeypatch, lambda: _FakeImage((100, 100), delay=0.05))
    state = {"now": 0, "peak": 0}
    lock = threading.Lock()
    original_enter = _FakeImage.__enter__

    def counting_enter(self):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        return original_enter(self)

    def counting_exit(self, *exc):
        with lock:
            state["now"] -= 1
        return False

    monkeypatch.setattr(_FakeImage, "__enter__", counting_enter)
    monkeypatch.setattr(_FakeImage, "__exit__", counting_exit)

    async def _run():
        return await media.asyncio.gather(
            *(media._normalize_image_bytes(WEBP_HEADER) for _ in range(4))
        )

    asyncio.run(_run())

    assert state["peak"] == 1, "normalization must hold the image semaphore"


def test_budget_swaps_the_compressed_claim_for_the_normalized_size(monkeypatch):
    payload = b"x" * 700
    monkeypatch.setattr(media, "_normalize_image_bytes_sync", lambda _data: payload)
    budget = SharedByteBudget(1000)
    budget.claim(len(WEBP_HEADER))  # the download already claimed the compressed bytes

    out = asyncio.run(media._normalize_image_bytes(WEBP_HEADER, budget=budget))

    assert out == payload
    assert budget.remaining == 300  # 1000 - 700, not 1000 - 700 - 400


def test_budget_exhaustion_drops_the_image_instead_of_overcommitting(monkeypatch):
    monkeypatch.setattr(media, "_normalize_image_bytes_sync", lambda _data: b"x" * 700)
    budget = SharedByteBudget(400)
    budget.claim(400)

    assert asyncio.run(media._normalize_image_bytes(WEBP_HEADER, budget=budget)) is None
    assert budget.remaining == 0


def test_shrinking_normalization_returns_bytes_to_the_budget(monkeypatch):
    monkeypatch.setattr(media, "_normalize_image_bytes_sync", lambda _data: b"x" * 100)
    budget = SharedByteBudget(1000)
    budget.claim(len(WEBP_HEADER))

    asyncio.run(media._normalize_image_bytes(WEBP_HEADER, budget=budget))

    assert budget.remaining == 900
