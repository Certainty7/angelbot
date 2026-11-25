"""Audit finding 11: a conversation turn is persisted only after Discord accepts every chunk.

The old flow wrote rolling memory, ambient state and the owner forward inside
`handle_conversation`, before `safe_reply` had a chance to fail — so an HTTP 500 left SQLite
holding a reply the user never saw.
"""

import asyncio
import types
import unittest
from unittest import mock

import discord

from angel.client import AngelDiscordBot, ConversationTurn


def _run(coro):
    return asyncio.run(coro)


class _FakeDB:
    def __init__(self):
        self.add_exchange = mock.AsyncMock()
        self.get_context_data = mock.AsyncMock(return_value=(None, []))
        self.check_and_expire_old_session = mock.AsyncMock(return_value=False)
        self.get_user_prefs = mock.AsyncMock(return_value={})
        self.search_knowledge_for_prompt = mock.AsyncMock(return_value="")

    def calls(self):
        return self.add_exchange.await_count


class _FakeAI:
    def __init__(self, reply="رد تجريبي"):
        self.reply = reply
        self.generate_angel_reply = mock.AsyncMock(side_effect=lambda **_: self.reply)
        self.fetch_anime_gif_data = mock.AsyncMock(return_value=(None, None))
        self.generate_image_bytes = mock.AsyncMock(return_value=(None, None))
        self.summarize_messages = mock.AsyncMock(return_value="ملخص")


def _bot(reply="رد تجريبي"):
    bot = object.__new__(AngelDiscordBot)
    bot.db = _FakeDB()
    bot.ai = _FakeAI(reply)
    bot.settings = {}
    bot.harem_cache = {}
    bot.guild_dialects = {}
    bot.angel_last_spoke = {}
    bot.recent_channel_msgs = {}
    bot.active_chat_window = {}
    bot._bg_tasks = set()
    bot._connection = types.SimpleNamespace(user=types.SimpleNamespace(id=999))
    bot.quota = types.SimpleNamespace(
        check_user_allowed=lambda user, is_harem=False, dry_run=False: (True, None)
    )
    bot.user_locks = {}
    bot.forward_dm_to_mistress = mock.AsyncMock()
    return bot


class _Channel:
    def __init__(self, fail_index=None, send_returns=None):
        self.id = 77
        self.sent = []
        self.fail_index = fail_index
        self.guild = types.SimpleNamespace(id=5)

    async def send(self, **kwargs):
        self.sent.append(kwargs.get("content"))
        if self.fail_index is not None and len(self.sent) - 1 == self.fail_index:
            raise discord.HTTPException(
                types.SimpleNamespace(status=500, reason="boom"), "boom"
            )
        return mock.MagicMock()


class _Message:
    def __init__(self, channel=None, guild=True):
        self.channel = channel or _Channel()
        self.guild = types.SimpleNamespace(id=5) if guild else None
        self.author = types.SimpleNamespace(id=42, display_name="Tester", bot=False)
        self.id = 300


def _turn(text="نص", **overrides):
    turn = ConversationTurn(
        text=text,
        channel_id=77,
        user_id=42,
        prompt="سؤال",
        is_dm=False,
        message_context=_Message(),
        context_len=0,
    )
    for key, value in overrides.items():
        setattr(turn, key, value)
    return turn


class DeliveryTest(unittest.TestCase):
    def test_a_failed_first_chunk_persists_nothing(self):
        bot = _bot()
        message = _Message()

        async def scenario():
            with mock.patch("angel.client.safe_reply", mock.AsyncMock(return_value=None)):
                return await bot.deliver_turn(message, _turn())

        delivered = _run(scenario())

        self.assertFalse(delivered)
        self.assertEqual(bot.db.calls(), 0)
        self.assertEqual(bot.recent_channel_msgs, {})
        self.assertEqual(bot.angel_last_spoke, {})

    def test_a_failed_later_chunk_persists_nothing(self):
        bot = _bot()
        channel = _Channel(fail_index=1)
        message = _Message(channel=channel)
        long_text = "ط" * 5000

        async def scenario():
            with mock.patch("angel.client.safe_reply", mock.AsyncMock(return_value=mock.MagicMock())):
                return await bot.deliver_turn(message, _turn(long_text))

        delivered = _run(scenario())

        self.assertFalse(delivered)
        self.assertEqual(len(channel.sent), 2, "the first chunk went out before the failure")
        self.assertEqual(bot.db.calls(), 0)

    def test_one_complete_delivery_stores_the_turn_exactly_once(self):
        bot = _bot()
        message = _Message()

        async def scenario():
            with mock.patch("angel.client.safe_reply", mock.AsyncMock(return_value=mock.MagicMock())):
                return await bot.deliver_turn(message, _turn())

        delivered = _run(scenario())

        self.assertTrue(delivered)
        self.assertEqual(bot.db.calls(), 1)
        bot.db.add_exchange.assert_awaited_once_with(77, 42, "سؤال", "نص")
        self.assertIn(77, bot.angel_last_spoke)

    def test_a_dm_forward_happens_after_delivery_only(self):
        bot = _bot()
        message = _Message(guild=False)

        async def scenario():
            with mock.patch("angel.client.SOVEREIGN_TOOLS_ENABLED", True):
                with mock.patch("angel.client.safe_reply", mock.AsyncMock(return_value=None)):
                    await bot.deliver_turn(message, _turn(is_dm=True))
                self.assertEqual(bot.forward_dm_to_mistress.await_count, 0)
                with mock.patch("angel.client.safe_reply", mock.AsyncMock(return_value=mock.MagicMock())):
                    await bot.deliver_turn(message, _turn(is_dm=True))

        _run(scenario())

        self.assertEqual(bot.forward_dm_to_mistress.await_count, 1)


class ClaimTest(unittest.TestCase):
    def test_a_claim_before_delivery_becomes_a_promise_not_a_success(self):
        from angel.output_filter import filter_outgoing

        out = filter_outgoing("تم، حظرت العضو.", action_status="pending")

        self.assertNotIn("حظرت", out)
        self.assertIn("أنفّذ", out)


class PreparationTest(unittest.TestCase):
    """`handle_conversation` may generate the turn; it may not record it."""

    def _user(self):
        return types.SimpleNamespace(
            id=42, display_name="Tester", bot=False, guild=None,
            guild_permissions=types.SimpleNamespace(administrator=False),
        )

    def test_handle_conversation_records_nothing(self):
        bot = _bot(reply="مرحبا بك")
        bot.user_locks = {}

        async def scenario():
            with mock.patch("angel.client.archive.lookup", mock.AsyncMock(return_value=None)), \
                 mock.patch("angel.client.memory.recall", mock.AsyncMock(return_value=[])):
                from angel.cache import WeakLockMap
                bot.user_locks = WeakLockMap()
                return await bot.handle_conversation(self._user(), "سؤال")

        turn = _run(scenario())

        self.assertEqual(turn.text, "مرحبا بك")
        self.assertEqual(bot.db.calls(), 0)
        self.assertEqual(bot.angel_last_spoke, {})

    def test_commit_then_records_it_once(self):
        bot = _bot(reply="مرحبا بك")
        turn = _turn(text="مرحبا بك")

        _run(bot.commit_turn(turn))

        self.assertEqual(bot.db.calls(), 1)

    def test_pipeline_has_no_second_memory_writer(self):
        import pathlib

        source = (pathlib.Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")

        self.assertNotIn('f"Angel: {reply[:120]}"', source)
        self.assertNotIn("forward_dm_to_mistress(message", source)
        self.assertEqual(source.count("bot.deliver_turn("), 1)
