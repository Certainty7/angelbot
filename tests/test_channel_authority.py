"""Audit finding 16: the alternate moderation paths must use the shared guards.

Two gaps: the natural-language warning commands never called `can_moderate_member`, so a
lower-ranked moderator could warn — or erase the warnings of — someone above them; and every
channel mutation authorized against the channel the command was typed in, so a caller denied
`manage_channels` in the target could still lock or hide it.

The invariant under test: a refusal leaves Discord untouched, and the allowed case still works.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import discord

from angel import config, nl_router
from cogs.admin import Admin

AUTHOR_ID = 5
BOT_ID = 555
TARGET_ID = 7
GUILD_ID = 1


class _Role:
    def __init__(self, position):
        self.position = position
        self.id = position
        self.managed = False

    def __ge__(self, other):
        return self.position >= other.position

    def __gt__(self, other):
        return self.position > other.position


def _member(uid, position=10, **perms):
    member = MagicMock(spec=discord.Member)
    member.id = uid
    member.bot = False
    member.top_role = _Role(position)
    member.guild_permissions = discord.Permissions(**perms)
    member.display_name = f"m{uid}"
    member.name = f"m{uid}"
    member.nickname = None
    member.mention = f"<@{uid}>"
    return member


def _channel(cid, guild, *, author_manage=False, bot_manage=True):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = cid
    channel.name = f"ch{cid}"
    channel.guild = guild
    channel.mention = f"<#{cid}>"
    perms = {
        AUTHOR_ID: discord.Permissions(manage_channels=author_manage),
        BOT_ID: discord.Permissions(manage_channels=bot_manage),
    }
    channel.permissions_for = MagicMock(
        side_effect=lambda member: perms.get(getattr(member, "id", None), discord.Permissions.none())
    )
    channel.set_permissions = AsyncMock()
    channel.edit = AsyncMock()
    channel.overwrites_for = MagicMock(
        return_value=SimpleNamespace(send_messages=True, view_channel=True)
    )
    return channel


def _guild(author_position=10):
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.owner_id = 999
    guild.me = _member(BOT_ID, position=50, manage_channels=True)
    guild.default_role = MagicMock(id=GUILD_ID)
    guild.get_member = MagicMock(return_value=None)
    guild.fetch_member = AsyncMock(return_value=None)
    guild.roles = []
    guild.emojis = []
    guild.stickers = []
    guild.voice_channels = []
    guild.text_channels = []
    guild.self_role = None
    return guild


def _message(author, channel, content, mentions=(), channel_mentions=()):
    message = MagicMock(spec=discord.Message)
    message.guild = channel.guild
    message.author = author
    message.content = content
    message.channel = channel
    message.mentions = list(mentions)
    message.channel_mentions = list(channel_mentions)
    message.role_mentions = []
    message.embeds = []
    message.reference = None
    message.attachments = []
    message.id = 1000
    return message


def _bot():
    bot = MagicMock()
    bot.user = MagicMock(id=BOT_ID)
    bot.pending_confirm = {}
    bot.action_triggers_cache = {}
    bot.last_social_target = {}
    bot.last_target_channel = {}
    bot.db = MagicMock()
    bot.db.add_warning = AsyncMock(return_value=1)
    bot.db.clear_warnings = AsyncMock(return_value=2)
    bot.db.get_warnings = AsyncMock(return_value=[])
    bot.send_modlog = AsyncMock()
    return bot


def _replies():
    return []


class WarningHierarchyTest(unittest.TestCase):
    """Part one: NL warnings answer to the same hierarchy guard as the slash command."""

    def _run(self, content, *, author_position, target_position):
        async def _go():
            guild = _guild()
            author = _member(AUTHOR_ID, position=author_position, moderate_members=True)
            target = _member(TARGET_ID, position=target_position)
            channel = _channel(77, guild)
            message = _message(author, channel, content, mentions=[target])
            bot = _bot()
            sent = []
            with mock.patch.object(
                nl_router, "safe_reply", AsyncMock(side_effect=lambda m, *a, **k: sent.append(a[0] if a else k.get("content")))
            ):
                handled = await nl_router.try_execute_natural_command(bot, message, content)
            return handled, sent, bot

        return asyncio.run(_go())

    def test_warning_a_higher_ranked_member_is_refused(self):
        handled, sent, bot = self._run(
            "انجل حذري <@7> بسبب سبام", author_position=5, target_position=10
        )
        self.assertTrue(handled)
        bot.db.add_warning.assert_not_called()
        self.assertTrue(any("رتب" in str(line) for line in sent), sent)

    def test_warning_an_equal_ranked_member_is_refused(self):
        _handled, _sent, bot = self._run(
            "انجل حذري <@7> بسبب سبام", author_position=10, target_position=10
        )
        bot.db.add_warning.assert_not_called()

    def test_warning_a_lower_ranked_member_still_works(self):
        _handled, _sent, bot = self._run(
            "انجل حذري <@7> بسبب سبام", author_position=20, target_position=10
        )
        bot.db.add_warning.assert_awaited_once()

    def test_clearing_warnings_of_a_higher_ranked_member_is_refused(self):
        _handled, sent, bot = self._run(
            "انجل امسحي انذارات <@7>", author_position=5, target_position=10
        )
        self.assertEqual(bot.pending_confirm, {})
        bot.db.clear_warnings.assert_not_called()
        self.assertTrue(any("رتب" in str(line) for line in sent), sent)

    def test_clearing_warnings_of_a_lower_ranked_member_is_queued(self):
        _handled, _sent, bot = self._run(
            "انجل امسحي انذارات <@7>", author_position=20, target_position=10
        )
        self.assertEqual(len(bot.pending_confirm), 1)
        bot.db.clear_warnings.assert_not_called()


class TargetChannelAuthorityTest(unittest.TestCase):
    """Part two: a channel mutation is authorized against the channel it changes."""

    def _run(self, content, *, author_manage, bot_manage=True, include_target=True):
        async def _go():
            guild = _guild()
            author = _member(AUTHOR_ID, position=20, manage_channels=True)
            invocation = _channel(77, guild, author_manage=True)
            target = _channel(88, guild, author_manage=author_manage, bot_manage=bot_manage)
            guild.text_channels = [invocation, target]
            message = _message(
                author,
                invocation,
                content,
                channel_mentions=[target] if include_target else [],
            )
            bot = _bot()
            sent = []
            with mock.patch.object(
                nl_router, "safe_reply", AsyncMock(side_effect=lambda m, *a, **k: sent.append(a[0] if a else k.get("content")))
            ):
                handled = await nl_router.try_execute_natural_command(bot, message, content)
            return handled, sent, target, invocation

        return asyncio.run(_go())

    def test_lock_in_a_channel_where_the_caller_is_denied_is_refused(self):
        handled, sent, target, _invocation = self._run("انجل اقفلي الشات", author_manage=False)
        self.assertTrue(handled)
        target.set_permissions.assert_not_called()
        self.assertTrue(any("صلاحية" in str(line) for line in sent), sent)

    def test_hide_in_a_channel_where_the_caller_is_denied_is_refused(self):
        _handled, _sent, target, _invocation = self._run("انجل اخفي الشات", author_manage=False)
        target.set_permissions.assert_not_called()

    def test_lock_in_a_channel_where_the_bot_is_denied_is_refused(self):
        _handled, sent, target, _invocation = self._run(
            "انجل اقفلي الشات", author_manage=True, bot_manage=False
        )
        target.set_permissions.assert_not_called()
        self.assertTrue(any("صلاحية" in str(line) for line in sent), sent)

    def test_lock_in_a_permitted_channel_still_works(self):
        _handled, _sent, target, _invocation = self._run("انجل اقفلي الشات", author_manage=True)
        target.set_permissions.assert_awaited_once()

    def test_slash_lock_refuses_a_target_channel_it_cannot_manage(self):
        async def _go():
            guild = _guild()
            author = _member(AUTHOR_ID, position=20, manage_channels=True)
            invocation = _channel(77, guild, author_manage=True)
            target = _channel(88, guild, author_manage=False)
            bot = _bot()
            interaction = MagicMock()
            interaction.guild = guild
            interaction.user = author
            interaction.channel = invocation
            interaction.channel_id = invocation.id
            interaction.client = bot
            interaction.response.send_message = AsyncMock()
            interaction.followup.send = AsyncMock()
            cog = Admin(bot)
            await Admin.lock_cmd.callback(cog, interaction, target, "اختبار")
            return target, interaction

        target, interaction = asyncio.run(_go())
        target.set_permissions.assert_not_called()
        interaction.response.send_message.assert_awaited()
        self.assertFalse(interaction.response.defer.called)


if __name__ == "__main__":
    unittest.main()
