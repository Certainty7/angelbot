"""Audit finding 19b: a bounded read must not hold the payload twice.

`read_bounded_stream` accumulated chunks in a `bytearray` and then returned `bytes(buf)`, so a
50 MiB body peaked at 100 MiB: the mutable buffer and the immutable result exist at once. When
the server declares `Content-Length`, the read can fill one exact buffer and hand it back as is.
"""

import asyncio
import tracemalloc
import unittest

from angel.net import read_bounded_stream

MIB = 1024 * 1024


class _Content:
    def __init__(self, payload, chunk=65536):
        self._payload = payload
        self._chunk = chunk

    async def iter_chunked(self, n):
        step = min(n, self._chunk)
        for i in range(0, len(self._payload), step):
            yield self._payload[i : i + step]


class _Response:
    def __init__(self, payload, content_length=True):
        self.headers = {}
        if content_length:
            self.headers["Content-Length"] = str(len(payload))
        self.content = _Content(payload)


class BoundedReadPeakTest(unittest.TestCase):
    def _peak(self, payload, content_length):
        async def run():
            return await read_bounded_stream(_Response(payload, content_length), max_bytes=64 * MIB)

        tracemalloc.start()
        try:
            result = asyncio.run(run())
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertIsNotNone(result)
        self.assertEqual(len(result), len(payload))
        self.assertEqual(result[:8], payload[:8])
        return peak

    def test_a_known_length_body_is_not_copied(self):
        payload = b"z" * (8 * MIB)
        peak = self._peak(payload, content_length=True)
        self.assertLess(peak, 8 * MIB * 1.4, f"peak {peak} for an 8 MiB body")

    def test_an_unknown_length_body_is_not_copied_either(self):
        payload = b"z" * (8 * MIB)
        peak = self._peak(payload, content_length=False)
        self.assertLess(peak, 8 * MIB * 1.4, f"peak {peak} for an 8 MiB body")

    def test_the_cap_still_refuses_an_oversized_body(self):
        async def run():
            return await read_bounded_stream(_Response(b"z" * 1000, True), max_bytes=100)

        self.assertIsNone(asyncio.run(run()))


if __name__ == "__main__":
    unittest.main()
