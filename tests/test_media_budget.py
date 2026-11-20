"""The shared per-job byte budget (C-007).

The old design finished `asyncio.gather` and only then trimmed the returned list: peak
RAM during the parallel download was unbounded. `SharedByteBudget` claims every chunk
before it is buffered, so a whole job stays near the ceiling while downloads run.
"""
import asyncio
import unittest

from angel.net import SharedByteBudget, read_bounded_stream


class _FakeContent:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.consumed = 0

    async def iter_chunked(self, _size):
        for chunk in self._chunks:
            self.consumed += 1
            yield chunk


class _FakeResp:
    def __init__(self, chunks, headers=None):
        self.content = _FakeContent(chunks)
        self.headers = headers or {}


class SharedByteBudgetTest(unittest.TestCase):
    def test_claims_never_exceed_the_ceiling(self):
        budget = SharedByteBudget(100)
        self.assertEqual(budget.claim(60), 60)
        self.assertEqual(budget.claim(60), 40)
        self.assertEqual(budget.remaining, 0)
        self.assertEqual(budget.claim(10), 0)

    def test_release_gives_bytes_back(self):
        budget = SharedByteBudget(100)
        budget.claim(80)
        budget.release(80)
        self.assertEqual(budget.remaining, 100)


class BudgetedReadTest(unittest.TestCase):
    def _read(self, resp, **kwargs):
        return asyncio.run(read_bounded_stream(resp, **kwargs))

    def test_a_successful_read_keeps_its_claim(self):
        resp = _FakeResp([b"x" * 60])
        budget = SharedByteBudget(100)
        data = self._read(resp, max_bytes=200, min_bytes=1, budget=budget)
        self.assertEqual(len(data), 60)
        self.assertEqual(budget.remaining, 40, "the payload is retained, the claim stays")

    def test_an_exhausted_budget_aborts_and_releases(self):
        resp = _FakeResp([b"x" * 60, b"y" * 60])
        budget = SharedByteBudget(100)
        data = self._read(resp, max_bytes=200, min_bytes=1, budget=budget)
        self.assertIsNone(data, "a grant smaller than the chunk must abort the read")
        self.assertEqual(budget.remaining, 100, "a failed read releases its claims")

    def test_a_content_length_over_the_rest_is_refused_before_reading(self):
        resp = _FakeResp([b"x" * 60])
        resp.headers = {"Content-Length": "500"}
        budget = SharedByteBudget(100)
        data = self._read(resp, max_bytes=1000, min_bytes=1, budget=budget)
        self.assertIsNone(data)
        self.assertEqual(resp.content.consumed, 0, "the body was still buffered")
        self.assertEqual(budget.remaining, 100)

    def test_a_too_small_read_releases_its_claim(self):
        resp = _FakeResp([b"x" * 5])
        budget = SharedByteBudget(100)
        data = self._read(resp, max_bytes=200, min_bytes=10, budget=budget)
        self.assertIsNone(data)
        self.assertEqual(budget.remaining, 100, "the discarded payload was never retained")


class ConcurrentDownloadBudgetTest(unittest.TestCase):
    def test_parallel_reads_cannot_retain_more_than_the_ceiling(self):
        async def _run():
            budget = SharedByteBudget(100)

            async def one(size):
                resp = _FakeResp([b"x" * size])
                return await read_bounded_stream(resp, max_bytes=1000, min_bytes=1, budget=budget)

            return await asyncio.gather(*(one(30) for _ in range(6)))

        payloads = asyncio.run(_run())
        kept = [p for p in payloads if p is not None]
        self.assertEqual(len(kept), 3, "only three 30-byte payloads fit a 100-byte budget")
        self.assertLessEqual(sum(len(p) for p in kept), 100)


if __name__ == "__main__":
    unittest.main()
