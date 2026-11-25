"""Audit finding 2: the SnapSave decoder must refuse work it cannot bound.

`_decode_snapsave_eval` decodes a JavaScript-style payload from a third-party site.
Before the fix it ran `str.replace` once per alphabet character per token, so a 20k/20k
response blocked the event loop for tens of seconds (audit reproduction: 38.1s).
"""

from __future__ import annotations

import time

import pytest

from angel.media import _decode_snapsave_eval

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"


def test_decodes_a_small_valid_payload():
    # separator is ALPHABET[10] == "a"; codes are plain decimal because base == 10.
    assert _decode_snapsave_eval("104a105", 0, ALPHABET, 0, 10) == "hi"


def test_rejects_oversized_payload():
    h = "0," * 40_000  # 80 KB, over the 64 KiB cap, but cheap to build
    with pytest.raises(ValueError):
        _decode_snapsave_eval(h, 0, ALPHABET, 0, 10)


def test_rejects_oversized_alphabet():
    with pytest.raises(ValueError):
        _decode_snapsave_eval("0,1", 0, "a" * 70_000, 0, 10)


def test_rejects_base_index_outside_the_alphabet():
    with pytest.raises(ValueError):
        _decode_snapsave_eval("104a105", 0, ALPHABET, 0, 99)


def test_rejects_duplicate_alphabet_characters():
    with pytest.raises(ValueError):
        _decode_snapsave_eval("0,1", 0, "aa!", 0, 2)


def test_rejects_offsets_that_would_produce_non_characters():
    with pytest.raises(ValueError):
        _decode_snapsave_eval("104a105", 10**9, ALPHABET, 0, 10)


def test_boundary_payload_decodes_within_the_time_budget():
    # 64 KiB of one-digit tokens is the largest accepted shape; a quadratic decoder
    # would take minutes here, the bounded one is milliseconds.
    h = "7a" * 32_000
    started = time.perf_counter()
    out = _decode_snapsave_eval(h, 0, ALPHABET, 0, 10)
    elapsed = time.perf_counter() - started
    assert len(out) == 32_000
    assert elapsed < 1.0, f"decoder took {elapsed:.3f}s on a bounded payload"
