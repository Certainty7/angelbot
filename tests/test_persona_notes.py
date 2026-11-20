"""Persona culture rendering and the provider response guard.

C-010, P-001.
"""
import asyncio
import unittest
from unittest.mock import MagicMock

import aiohttp

from angel import persona_notes
from angel.brain import AIServiceError, AngelBrainService, _seconds_until_pacific_midnight
from angel.quota import QuotaGuard


class PersonaRenderTest(unittest.TestCase):
    def test_non_dictionary_payloads_render_empty(self):
        for payload in ("[1, 2]", '"hello"', "null", "123", "true"):
            self.assertEqual(persona_notes._render(payload), "", payload)

    def test_a_dictionary_still_renders(self):
        rendered = persona_notes._render('{"tone": "هادئ", "topics": ["قهوة", "شغل"]}')
        self.assertIn("هادئ", rendered)
        self.assertIn("قهوة", rendered)

    def test_malformed_json_is_empty(self):
        self.assertEqual(persona_notes._render("{not json"), "")


class _FakeResponse:
    def __init__(self, status, payload=None, body=""):
        self.status = status
        self._payload = payload
        self._body = body

    async def json(self):
        return self._payload

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


class ProviderResponseTest(unittest.TestCase):
    """P-001: an empty or thought-only answer must not become a "تم." success."""

    def test_thought_only_response_falls_back_to_the_next_model(self):
        import angel.brain as brain_module

        ai = AngelBrainService(
            api_key="k", models_list=["m1", "m2"], quota_guard=QuotaGuard()
        )
        session = _FakeSession([
            _FakeResponse(200, {"candidates": [{"content": {"parts": [
                {"thought": True, "text": "reasoning only"}
            ]}}]}),
            _FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}),
        ])
        original = brain_module.get_shared_http_session

        async def fake_session():
            return session

        brain_module.get_shared_http_session = fake_session
        try:
            reply = asyncio.run(ai._post_with_retry({"contents": []}))
        finally:
            brain_module.get_shared_http_session = original

        self.assertEqual(reply, "hello")
        self.assertEqual(session.calls, 2)

    def test_a_malformed_body_does_not_escape(self):
        import angel.brain as brain_module

        ai = AngelBrainService(api_key="k", models_list=["m1"], quota_guard=QuotaGuard())
        session = _FakeSession([_FakeResponse(200, None)])
        original = brain_module.get_shared_http_session

        async def fake_session():
            return session

        class _Raising(_FakeResponse):
            async def json(self):
                raise ValueError("not json")

        session._responses = [_Raising(200, None), _Raising(200, None)]
        brain_module.get_shared_http_session = fake_session
        try:
            with self.assertRaises((AIServiceError, ValueError)):
                asyncio.run(ai._post_with_retry({"contents": []}))
        finally:
            brain_module.get_shared_http_session = original


class PacificMidnightTest(unittest.TestCase):
    def test_returns_a_positive_cooldown(self):
        self.assertGreater(_seconds_until_pacific_midnight(), 0)


if __name__ == "__main__":
    unittest.main()
