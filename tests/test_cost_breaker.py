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

    def test_simultaneous_reservations_cannot_pass_the_same_check(self):
        async def _run():
            ai = _service(_FakeDB(spent=0.94))
            results = await asyncio.gather(
                *(ai._reserve_budget(None) for _ in range(20))
            )
            return results

        admitted = [r for r in asyncio.run(_run()) if r]
        # 0.94 + n*0.002 <= 0.95 -> at most 5 reservations fit, under one lock.
        self.assertLessEqual(len(admitted), 5, f"{len(admitted)} reservations passed the ceiling")

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


class _FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def text(self):
        return ""


class _FakePostContext:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        if self._exc is not None:
            raise self._exc
        return self._response

    async def __aexit__(self, *_exc):
        return False


class _FakeSession:
    """Serves canned payloads chosen by the model name inside the endpoint."""

    def __init__(self, responder):
        self._responder = responder
        self.calls = 0

    def post(self, endpoint, headers=None, json=None, timeout=None):
        self.calls += 1
        return _FakePostContext(response=self._responder(endpoint))


def _thought_only_payload(tokens):
    return {
        "candidates": [{"content": {"parts": [{"text": "…", "thought": True}]}}],
        "usageMetadata": {"promptTokenCount": tokens, "candidatesTokenCount": 1},
    }


def _success_payload(tokens):
    return {
        "candidates": [{"content": {"parts": [{"text": "hi"}]}}],
        "usageMetadata": {"promptTokenCount": tokens, "candidatesTokenCount": 5},
    }


def _patched_brain_session(fake_session):
    from unittest.mock import patch
    import angel.brain as brain_module

    async def _fake_get_session():
        return fake_session

    return patch.object(brain_module, "get_shared_http_session", _fake_get_session)


class PerAttemptBudgetTest(unittest.TestCase):
    """One reservation per provider attempt, settled with its usage atomically (C-003).

    The old design held one reservation for the whole fallback chain: a thought-only
    response still spent real tokens, and every following attempt was admitted against a
    recorded-spend check that did not count outstanding reservations.
    """

    def setUp(self):
        self._limit, self._ratio, self._estimate = (
            cost.DAILY_LIMIT_USD, cost.STOP_RATIO, cost.ESTIMATED_CALL_USD
        )
        # stop_at = 0.004: two 0.002 estimate slots fit, the third does not.
        cost.DAILY_LIMIT_USD = 0.008
        cost.STOP_RATIO = 0.5
        cost.ESTIMATED_CALL_USD = 0.002

    def tearDown(self):
        cost.DAILY_LIMIT_USD, cost.STOP_RATIO, cost.ESTIMATED_CALL_USD = (
            self._limit, self._ratio, self._estimate
        )

    def _service(self, db):
        ai = AngelBrainService(
            api_key="test-key", models_list=["m1", "m2"], quota_guard=QuotaGuard()
        )
        ai.db = db
        return ai

    def test_a_thought_only_attempt_then_fallback_stays_within_the_ceiling(self):
        async def _run():
            from unittest.mock import patch

            db = _FakeDB(spent=0.0)
            ai = self._service(db)

            def responder(endpoint):
                # m1 answers with a thought-only payload (still charged); m2 answers
                # normally, so the fallback is a real second paid attempt.
                if "m1" in endpoint:
                    return _FakeResponse(200, _thought_only_payload(10))
                return _FakeResponse(200, _success_payload(10))

            fake = _FakeSession(responder)
            # A canned provider charge equal to the estimate keeps the accounting exact.
            with patch.object(cost, "cost_of", lambda _i, _o: 0.002), \
                    _patched_brain_session(fake):
                reply = await ai._post_with_retry({"contents": []})
            return reply, db.spent, ai._inflight_usd, fake.calls

        reply, spent, inflight, calls = asyncio.run(_run())
        self.assertEqual(reply, "hi")
        self.assertEqual(spent, 0.004, "both attempts were charged and settled")
        self.assertEqual(inflight, 0.0, "no reservation may leak after the chain returns")
        self.assertEqual(calls, 2)

    def test_concurrent_chains_cannot_overspend_the_ceiling(self):
        async def _run():
            from unittest.mock import patch

            class SlowDB(_FakeDB):
                async def add_usage(self, day, in_tok, out_tok, usd, blocked=False):
                    # A visible await inside the settle: concurrent admissions
                    # interleave with it instead of queueing behind one fast write.
                    await asyncio.sleep(0.01)
                    return await super().add_usage(day, in_tok, out_tok, usd, blocked=blocked)

            slow = SlowDB(spent=0.0)
            ai = self._service(slow)

            def responder(endpoint):
                if "m1" in endpoint:
                    return _FakeResponse(200, _thought_only_payload(10))
                return _FakeResponse(200, _success_payload(10))

            with patch.object(cost, "cost_of", lambda _i, _o: 0.002), \
                    _patched_brain_session(_FakeSession(responder)):
                results = await asyncio.gather(
                    *(ai._post_with_retry({"contents": []}) for _ in range(6)),
                    return_exceptions=True,
                )
            return slow.spent, ai._inflight_usd, results

        spent, inflight, results = asyncio.run(_run())
        self.assertLessEqual(spent, cost.stop_at() + 1e-9,
                             f"the ceiling was bypassed: {spent} recorded")
        self.assertEqual(inflight, 0.0, "all reservations were released or settled")
        self.assertGreater(spent, 0.0)
        self.assertTrue(
            any(isinstance(r, cost.BudgetExhausted) for r in results),
            "the ceiling admitted everything; the estimate slots gated nothing",
        )

    def test_provider_errors_release_every_reservation(self):
        import aiohttp

        async def _run():
            db = _FakeDB(spent=0.0)
            ai = self._service(db)

            class ExplodingSession(_FakeSession):
                def post(self, endpoint, headers=None, json=None, timeout=None):
                    self.calls += 1
                    return _FakePostContext(exc=aiohttp.ClientError("boom"))

            with _patched_brain_session(ExplodingSession(None)):
                try:
                    await ai._post_with_retry({"contents": []})
                except Exception:
                    pass
            return ai._inflight_usd, db.spent

        inflight, spent = asyncio.run(_run())
        self.assertEqual(inflight, 0.0, "a failed chain must not hold its reservations")
        self.assertEqual(spent, 0.0)

    def test_settling_never_double_counts_a_call_for_the_next_admission(self):
        async def _run():
            from unittest.mock import patch

            # A settled chain recorded 0.004 and released its reservation: the next
            # admission must see 0.004 spent, not 0.004 recorded plus a phantom slot.
            db = _FakeDB(spent=0.0)
            ai = self._service(db)

            def responder(endpoint):
                if "m1" in endpoint:
                    return _FakeResponse(200, _thought_only_payload(10))
                return _FakeResponse(200, _success_payload(10))

            with patch.object(cost, "cost_of", lambda _i, _o: 0.002), \
                    _patched_brain_session(_FakeSession(responder)):
                first = await ai._post_with_retry({"contents": []})
                try:
                    await ai._post_with_retry({"contents": []})
                    second = "admitted"
                except cost.BudgetExhausted:
                    second = "refused"
            return first, second, db.spent

        first, second, spent = asyncio.run(_run())
        self.assertEqual(first, "hi")
        self.assertEqual(second, "refused", "the settled spend was double-counted")
        self.assertEqual(spent, 0.004)


if __name__ == "__main__":
    unittest.main()
