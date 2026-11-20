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


if __name__ == "__main__":
    unittest.main()
