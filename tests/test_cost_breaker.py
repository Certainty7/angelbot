"""Daily budget breaker (C-003).

Three defects are covered: a missing database handle opened the breaker, an out-of-range
STOP_RATIO raised or lowered the ceiling unpredictably, and concurrent requests all read the
same spend total before any of them recorded a cost.
"""
import asyncio
import importlib
import unittest

from angel import cost
from angel.brain import AngelBrainService
from angel.quota import QuotaGuard


class _FakeDB:
    def __init__(self, spent: float = 0.0):
        self.spent = spent
        self.calls = []

    async def day_cost(self, _day):
        return self.spent

    async def add_usage(self, day, in_tok, out_tok, usd, blocked=False):
        self.calls.append((day, usd, blocked))
        if not blocked:
            self.spent += usd
        return self.spent


def _service(db):
    ai = AngelBrainService(api_key="test-key", models_list=["test-model"], quota_guard=QuotaGuard())
    ai.db = db
    return ai


class BudgetFailClosedTest(unittest.TestCase):
    def setUp(self):
        self._limit, self._ratio = cost.DAILY_LIMIT_USD, cost.STOP_RATIO

    def tearDown(self):
        cost.DAILY_LIMIT_USD, cost.STOP_RATIO = self._limit, self._ratio

    def test_missing_database_handle_blocks_when_a_cap_is_configured(self):
        cost.DAILY_LIMIT_USD = 1.0
        ai = _service(None)
        self.assertTrue(asyncio.run(ai.budget_blocked()))

    def test_missing_database_handle_is_allowed_when_the_cap_is_disabled(self):
        cost.DAILY_LIMIT_USD = 0.0
        ai = _service(None)
        self.assertFalse(asyncio.run(ai.budget_blocked()))

    def test_owner_keeps_access_past_the_ceiling(self):
        cost.DAILY_LIMIT_USD = 1.0
        cost.STOP_RATIO = 0.95

        class Owner:
            id = 42

        ai = _service(_FakeDB(spent=5.0))
        self.assertTrue(asyncio.run(ai.budget_blocked()))
        self.assertFalse(asyncio.run(ai.budget_blocked(Owner())))


class StopRatioTest(unittest.TestCase):
    def _reload_with(self, value):
        import os
        old = os.environ.get("ANGEL_COST_STOP_RATIO")
        os.environ["ANGEL_COST_STOP_RATIO"] = value
        try:
            return importlib.reload(cost)
        finally:
            if old is None:
                os.environ.pop("ANGEL_COST_STOP_RATIO", None)
            else:
                os.environ["ANGEL_COST_STOP_RATIO"] = old

    def test_zero_and_above_one_snap_to_the_default(self):
        self.assertEqual(self._reload_with("0").STOP_RATIO, 0.95)
        self.assertEqual(self._reload_with("1.5").STOP_RATIO, 0.95)

    def test_a_valid_ratio_is_kept(self):
        self.assertEqual(self._reload_with("0.5").STOP_RATIO, 0.5)


class ConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self._limit, self._ratio, self._estimate = (
            cost.DAILY_LIMIT_USD, cost.STOP_RATIO, cost.ESTIMATED_CALL_USD
        )
        cost.DAILY_LIMIT_USD = 1.0
        cost.STOP_RATIO = 0.95
        cost.ESTIMATED_CALL_USD = 0.002

    def tearDown(self):
        cost.DAILY_LIMIT_USD, cost.STOP_RATIO, cost.ESTIMATED_CALL_USD = (
            self._limit, self._ratio, self._estimate
        )

    def test_simultaneous_requests_cannot_pass_the_same_check(self):
        async def _run():
            ai = _service(_FakeDB(spent=0.94))

            async def free_call(*_args, **_kwargs):
                await asyncio.sleep(0.01)  # hold the reservation while others check
                return "ok"

            ai._post_models = free_call
            results = await asyncio.gather(
                *(ai._post_with_retry({"contents": []}) for _ in range(20)),
                return_exceptions=True,
            )
            admitted = [r for r in results if r == "ok"]
            refused = [r for r in results if isinstance(r, cost.BudgetExhausted)]
            return admitted, refused

        admitted, refused = asyncio.run(_run())
        # 0.94 + n*0.002 <= 0.95 -> at most 5 reservations fit.
        self.assertLessEqual(len(admitted), 5, f"{len(admitted)} requests passed the ceiling")
        self.assertEqual(len(admitted) + len(refused), 20)

    def test_a_refused_call_records_a_blocked_usage_row(self):
        async def _run():
            db = _FakeDB(spent=0.99)
            ai = _service(db)
            try:
                await ai._post_with_retry({"contents": []})
            except cost.BudgetExhausted:
                return db.calls
            return []

        calls = asyncio.run(_run())
        self.assertTrue(calls and calls[-1][2] is True, "a blocked call must be accounted for")


if __name__ == "__main__":
    unittest.main()
