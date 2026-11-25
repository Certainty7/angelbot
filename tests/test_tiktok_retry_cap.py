"""Audit finding 19a: a TikTok photo retry must not overshoot the retained-payload cap.

The cap was applied once, before the re-quote retry. Retried slides were added afterwards with
no second pass, so a 35-slide post could retain far past 25 MiB while its claims stayed taken
(evidence: 50 MiB retained against a 25 MiB cap, 85 MiB peak). The retry also never released the
claims of slides it failed to replace.
"""

import unittest

from angel.media import cap_retained_photos
from angel.net import SharedByteBudget

MIB = 1024 * 1024
CAP = 25 * MIB


def _photo(size):
    return (b"x" * size, "slide.jpg")


class RetainedCapTest(unittest.TestCase):
    def test_a_retry_that_overshoots_is_trimmed_back(self):
        items = {1: _photo(10 * MIB), 2: _photo(10 * MIB), 3: _photo(10 * MIB)}
        budget = SharedByteBudget(100 * MIB)
        budget.claim(30 * MIB)
        kept = cap_retained_photos(items, CAP, budget)
        self.assertLessEqual(sum(len(b) for b, _ in kept.values()), CAP)
        self.assertEqual(budget.remaining, 100 * MIB - 20 * MIB)

    def test_nothing_is_dropped_when_it_already_fits(self):
        items = {1: _photo(5 * MIB), 2: _photo(5 * MIB)}
        budget = SharedByteBudget(100 * MIB)
        budget.claim(10 * MIB)
        kept = cap_retained_photos(items, CAP, budget)
        self.assertEqual(sorted(kept), [1, 2])
        self.assertEqual(budget.remaining, 90 * MIB)

    def test_every_dropped_payload_releases_its_claim(self):
        items = {1: _photo(20 * MIB), 2: _photo(20 * MIB)}
        budget = SharedByteBudget(100 * MIB)
        budget.claim(40 * MIB)
        cap_retained_photos(items, CAP, budget)
        self.assertEqual(budget.remaining, 80 * MIB)


if __name__ == "__main__":
    unittest.main()
