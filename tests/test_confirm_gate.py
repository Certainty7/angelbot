"""Confirmation gate and model-proposed action safety (C-013, P-005).

The gate is verified on the two properties that made it unsafe: it must bind the pending
action to the channel it was requested in, and it must report the real outcome instead of a
fixed success message.
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from angel import nl_router

OWNER_ID = 42


class _Role:
    def __init__(self, position):
        self.position = position
        self.id = position
        self.managed = False

    def __ge__(self, other):
        return self.position >= other.position

    def __gt__(self, other):
        return self.position > other.position


def _member(uid, position, **perms):
    member = MagicMock(spec=discord.Member)
    member.id = uid
    member.top_role = _Role(position)
    member.guild_permissions = discord.Permissions(**perms)
    member.display_name = f"m{uid}"
    member.mention = f"<@{uid}>"
    member.edit = AsyncMock()
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    member.timeout = AsyncMock()
    member.kick = AsyncMock()
    member.ban = AsyncMock()
    return member


def _guild():
    guild = MagicMock()
    guild.id = 1
    guild.owner_id = 999
    guild.me = _member(555, 100)
    guild.default_role = _Role(0)
    return guild


def _message(author, guild, content):
    message = MagicMock(spec=discord.Message)
    message.guild = guild
    message.author = author
    message.content = content
    message.channel = MagicMock()
    message.channel.id = 77
    message.channel.mention = "<#77>"
    message.mentions = []
    return message


def _bot():
    bot = MagicMock()
    bot.user = MagicMock(id=555)
    bot.pending_confirm = {}
    bot.last_social_target = {}
    bot.last_target_channel = {}
    bot.send_modlog = AsyncMock()
    bot.db = MagicMock()
    bot.db.set_modlog_channel = AsyncMock()
    bot.db.set_guard_mode = AsyncMock()
    bot.db.add_warning = AsyncMock()
    bot.db.clear_warnings = AsyncMock()
    bot.db.set_autorole = AsyncMock()
    return bot


class ConfirmationQueueTest(unittest.TestCase):
    def test_a_destructive_action_is_queued_with_its_channel(self):
        guild = _guild()
        author = _member(7, 50, manage_nicknames=True)
        message = _message(author, guild, "غير اللقب")
        bot = _bot()

        outcome = asyncio.run(
            nl_router.execute_ai_inferred_action(bot, message, "NICKNAME|name=new", confirmed=False)
        )

        self.assertEqual(outcome, "queued")
        pending = bot.pending_confirm[(guild.id, author.id)]
        self.assertEqual(pending["channel_id"], message.channel.id)
        author.edit.assert_not_awaited()

    def test_a_non_destructive_action_executes_immediately(self):
        guild = _guild()
        author = _member(7, 50, manage_guild=True)
        message = _message(author, guild, "شغلي الحماية")
        bot = _bot()

        outcome = asyncio.run(
            nl_router.execute_ai_inferred_action(
                bot, message, "GUARD_MODE|mode=dry_run", confirmed=False
            )
        )

        self.assertEqual(outcome, "executed")
        bot.db.set_guard_mode.assert_awaited()

    def test_a_state_changing_action_is_queued(self):
        # SET_MODLOG, TIMEOUT, HIDE and friends used to run with no confirmation (C-013).
        guild = _guild()
        author = _member(7, 50, manage_guild=True)
        message = _message(author, guild, "سجل")
        bot = _bot()

        outcome = asyncio.run(
            nl_router.execute_ai_inferred_action(bot, message, "SET_MODLOG", confirmed=False)
        )

        self.assertEqual(outcome, "queued")
        bot.db.set_modlog_channel.assert_not_awaited()


class HierarchyRefusalTest(unittest.TestCase):
    def test_nickname_on_a_higher_role_is_blocked_not_announced(self):
        guild = _guild()
        author = _member(7, 50, manage_nicknames=True)
        target = _member(8, 60)  # above the actor
        message = _message(author, guild, "غير اللقب")
        message.mentions = [target]
        bot = _bot()

        outcome = asyncio.run(
            nl_router.execute_ai_inferred_action(bot, message, "NICKNAME|name=new", confirmed=True)
        )

        self.assertEqual(outcome, "blocked")
        target.edit.assert_not_awaited()

    def test_nickname_on_a_lower_role_is_applied(self):
        guild = _guild()
        author = _member(7, 50, manage_nicknames=True)
        target = _member(8, 10)
        message = _message(author, guild, "غير اللقب")
        message.mentions = [target]
        bot = _bot()

        outcome = asyncio.run(
            nl_router.execute_ai_inferred_action(bot, message, "NICKNAME|name=new", confirmed=True)
        )

        self.assertEqual(outcome, "executed")
        target.edit.assert_awaited_once_with(nick="new")

    def test_kick_without_a_target_is_blocked(self):
        guild = _guild()
        author = _member(7, 50, kick_members=True)
        message = _message(author, guild, "اطرد")
        bot = _bot()

        outcome = asyncio.run(
            nl_router.execute_ai_inferred_action(bot, message, "KICK", confirmed=True)
        )

        self.assertEqual(outcome, "blocked")


class ConfirmWordTest(unittest.TestCase):
    def test_ordinary_words_are_not_confirmations(self):
        # "نفذ" and "لا" used to confirm/cancel; they are ordinary Arabic words (C-013).
        for word in ("نفذ", "لا", "طيب"):
            self.assertNotIn(word, nl_router._CONFIRM_WORDS)


class _SilentReply:
    """Patch context: nl_router.safe_reply becomes an AsyncMock we can inspect."""

    def __init__(self):
        from unittest.mock import patch
        self._patcher = patch("angel.nl_router.safe_reply", new=AsyncMock())

    def __enter__(self):
        self.mock = self._patcher.start()
        return self.mock

    def __exit__(self, *_exc):
        self._patcher.stop()
        return False


def _patched_safe_reply():
    return _SilentReply()


def _queue_action(bot, guild, author, target):
    message = _message(author, guild, "غير اللقب")
    message.mentions = [target]
    import time as _time
    bot.pending_confirm[(guild.id, author.id)] = {
        "cmd": "NICKNAME|name=new", "message": message,
        "channel_id": message.channel.id, "ts": _time.monotonic(),
    }
    return message


class ConfirmReauthorizationTest(unittest.TestCase):
    """E (CWE-863): the confirmer's CURRENT membership re-authorizes the mutation.

    A moderator queues an action, loses the role inside the 60-second window, then
    types the confirmation. The retained requester snapshot must not decide the outcome.
    """

    def test_a_demoted_confirmer_is_refused(self):
        guild = _guild()
        queued_by = _member(7, 50, manage_nicknames=True)
        bot = _bot()
        target = _member(8, 10)
        _queue_action(bot, guild, queued_by, target)
        # The confirmation carries the *current* member payload: the role was lost
        # after queueing, while the retained requester object still has it.
        demoted = _member(7, 50, manage_nicknames=False)
        confirm_msg = _message(demoted, guild, "تأكيد")
        guild.fetch_member = AsyncMock(return_value=demoted)

        with _patched_safe_reply() as reply:
            handled = asyncio.run(
                nl_router.try_execute_natural_command(bot, confirm_msg, "تأكيد")
            )

        self.assertTrue(handled)
        target.edit.assert_not_awaited()
        replies = " ".join(str(c.args) for c in reply.await_args_list if c.args)
        self.assertIn("ما نفذت", replies)

    def test_a_still_authorized_confirmer_executes(self):
        guild = _guild()
        queued_by = _member(7, 50, manage_nicknames=True)
        bot = _bot()
        target = _member(8, 10)
        _queue_action(bot, guild, queued_by, target)
        still_ok = _member(7, 50, manage_nicknames=True)
        confirm_msg = _message(still_ok, guild, "تأكيد")
        guild.fetch_member = AsyncMock(return_value=still_ok)

        with _patched_safe_reply():
            handled = asyncio.run(
                nl_router.try_execute_natural_command(bot, confirm_msg, "تأكيد")
            )

        self.assertTrue(handled)
        target.edit.assert_awaited_once_with(nick="new")


class NaturalForgetKeywordTest(unittest.TestCase):
    """The NL "انسي كلمة ..." twin must confirm like /memory forget, not delete at once."""

    def _bot(self):
        bot = _bot()
        bot.db.forget_user_keyword = AsyncMock()
        bot.db.clear_user_memory = AsyncMock()
        bot.summarize_cooldowns = {}
        return bot

    def _run(self, bot, guild, content, author=None, channel_id=77):
        message = _message(author or _member(7, 50), guild, content)
        if channel_id != 77:
            message.channel = MagicMock()
            message.channel.id = channel_id
        with _patched_safe_reply() as reply:
            asyncio.run(nl_router.try_execute_natural_command(bot, message, content))
        return message, reply

    def test_the_first_request_queues_instead_of_deleting(self):
        guild = _guild()
        bot = self._bot()
        message, reply = self._run(bot, guild, "انسي كلمة القهوة")

        bot.db.forget_user_keyword.assert_not_awaited()
        pending = bot.pending_confirm[(guild.id, message.author.id)]
        self.assertIn("FORGET_KEYWORD", pending["cmd"])
        self.assertEqual(pending["channel_id"], message.channel.id)
        replies = " ".join(str(c.args) for c in reply.await_args_list if c.args)
        self.assertIn("تأكيد", replies)

    def test_a_confirmation_in_the_same_channel_executes_the_forget(self):
        guild = _guild()
        bot = self._bot()
        first, _reply = self._run(bot, guild, "انسي كلمة القهوة")
        guild.fetch_member = AsyncMock(return_value=first.author)
        self._run(bot, guild, "تأكيد", author=first.author)

        bot.db.forget_user_keyword.assert_awaited_once_with(first.author.id, "القهوة")

    def test_a_confirmation_in_another_channel_is_refused(self):
        guild = _guild()
        bot = self._bot()
        first, _reply = self._run(bot, guild, "انسي كلمة القهوة")
        self._run(bot, guild, "تأكيد", author=first.author, channel_id=999)

        bot.db.forget_user_keyword.assert_not_awaited()
        self.assertNotIn((guild.id, first.author.id), bot.pending_confirm)


if __name__ == "__main__":
    unittest.main()
