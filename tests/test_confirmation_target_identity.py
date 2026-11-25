"""Audit finding 17: a confirmation must execute against the target that was queued.

The pending model action stored the request message and re-resolved its target at confirmation
time. `RENAME_CHANNEL` falls back to `bot.last_target_channel`, so queuing a rename for channel
A, pointing that cache at B, and confirming renamed B while A was untouched — the human approved
one target and the bot mutated another.

The invariant under test: the target identity is frozen when the action is queued, and a target
that disappeared is a refusal rather than a silent no-op or a different mutation.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import discord

from angel import nl_router

AUTHOR_ID = 5
BOT_ID = 555
GUILD_ID = 1


def _role(position):
    role = MagicMock()
    role.position = position
    role.id = position
    return role


def _member(uid, position=50):
    member = MagicMock(spec=discord.Member)
    member.id = uid
    member.bot = False
    member.top_role = _role(position)
    member.guild_permissions = discord.Permissions(administrator=True)
    member.display_name = f"m{uid}"
    member.name = f"m{uid}"
    member.nickname = None
    member.mention = f"<@{uid}>"
    member.edit = AsyncMock()
    member.ban = AsyncMock()
    member.kick = AsyncMock()
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    return member


def _channel(cid, guild, name):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = cid
    channel.name = name
    channel.guild = guild
    channel.mention = f"<#{cid}>"
    channel.edit = AsyncMock()
    channel.delete = AsyncMock()
    channel.set_permissions = AsyncMock()
    channel.permissions_for = MagicMock(return_value=discord.Permissions.all())
    channel.overwrites_for = MagicMock(
        return_value=SimpleNamespace(send_messages=True, view_channel=True)
    )
    return channel


def _guild(channels):
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.owner_id = 999
    guild.me = _member(BOT_ID, position=90)
    guild.default_role = MagicMock(id=GUILD_ID)
    guild.text_channels = list(channels)
    guild.voice_channels = []
    guild.roles = []
    guild.emojis = []
    guild.stickers = []
    guild.get_channel = MagicMock(side_effect=lambda cid: {c.id: c for c in channels}.get(cid))
    guild.get_member = MagicMock(return_value=None)
    guild.fetch_member = AsyncMock(return_value=None)
    return guild


def _message(author, channel, content, mentions=(), channel_mentions=()):
    message = MagicMock(spec=discord.Message)
    message.guild = channel.guild
    message.author = author
    message.content = content
    message.channel = channel
    message.channel_id = channel.id
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
    bot.last_target_channel = {}
    bot.last_social_target = {}
    bot.action_triggers_cache = {}
    bot.active_chat_window = {}
    bot.db = MagicMock()
    bot.send_modlog = AsyncMock()
    return bot


class FrozenTargetTest(unittest.TestCase):
    async def _queue(self, *, action_cmd, content, guild, message, bot):
        with mock.patch.object(nl_router, "check_staff_action_permission", return_value=True):
            return await nl_router.execute_ai_inferred_action(bot, message, action_cmd)

    async def _confirm(self, guild, channel, author, bot):
        message = _message(author, channel, "تأكيد")
        sent = []
        with mock.patch.object(
            nl_router,
            "safe_reply",
            AsyncMock(side_effect=lambda m, *a, **k: sent.append(a[0] if a else k.get("content"))),
        ), mock.patch.object(nl_router, "check_staff_action_permission", return_value=True):
            await nl_router.try_execute_natural_command(bot, message, "تأكيد")
        return sent

    def test_rename_uses_the_channel_that_was_queued(self):
        async def _go():
            general = _channel(11, None, "general")
            alpha = _channel(21, None, "alpha")
            beta = _channel(22, None, "beta")
            guild = _guild([general, alpha, beta])
            general.guild = alpha.guild = beta.guild = guild
            author = _member(AUTHOR_ID)
            bot = _bot()
            bot.last_target_channel[GUILD_ID] = alpha.id
            message = _message(author, general, "غيري اسم الروم [EXEC: RENAME_CHANNEL|name=جديد]")
            outcome = await self._queue(
                action_cmd="RENAME_CHANNEL|name=جديد",
                content=message.content,
                guild=guild,
                message=message,
                bot=bot,
            )
            self.assertEqual(outcome, "queued")
            # The target cache moves after the human saw the prompt.
            bot.last_target_channel[GUILD_ID] = beta.id
            sent = await self._confirm(guild, general, author, bot)
            return alpha, beta, sent

        alpha, beta, sent = asyncio.run(_go())
        alpha.edit.assert_awaited_once()
        beta.edit.assert_not_called()

    def test_a_deleted_channel_target_is_refused(self):
        async def _go():
            general = _channel(11, None, "general")
            alpha = _channel(21, None, "alpha")
            beta = _channel(22, None, "beta")
            guild = _guild([general, alpha, beta])
            general.guild = alpha.guild = beta.guild = guild
            author = _member(AUTHOR_ID)
            bot = _bot()
            bot.last_target_channel[GUILD_ID] = alpha.id
            message = _message(author, general, "غيري اسم الروم [EXEC: RENAME_CHANNEL|name=جديد]")
            await self._queue(
                action_cmd="RENAME_CHANNEL|name=جديد",
                content=message.content,
                guild=guild,
                message=message,
                bot=bot,
            )
            guild.text_channels = [general, beta]
            guild.get_channel = MagicMock(
                side_effect=lambda cid: {c.id: c for c in (general, beta)}.get(cid)
            )
            bot.last_target_channel[GUILD_ID] = beta.id
            sent = await self._confirm(guild, general, author, bot)
            return alpha, beta, sent

        alpha, beta, sent = asyncio.run(_go())
        alpha.edit.assert_not_called()
        beta.edit.assert_not_called()
        self.assertTrue(sent)

    def test_a_departed_member_target_is_refused(self):
        async def _go():
            general = _channel(11, None, "general")
            guild = _guild([general])
            general.guild = guild
            author = _member(AUTHOR_ID)
            target = _member(77, position=10)
            bot = _bot()
            message = _message(
                author, general, "اطردي <@77> [EXEC: KICK]", mentions=[target]
            )
            outcome = await self._queue(
                action_cmd="KICK", content=message.content, guild=guild, message=message, bot=bot
            )
            self.assertEqual(outcome, "queued")
            guild.get_member = MagicMock(return_value=None)
            guild.fetch_member = AsyncMock(return_value=None)
            sent = await self._confirm(guild, general, author, bot)
            return target, sent

        target, sent = asyncio.run(_go())
        target.kick.assert_not_called()
        self.assertTrue(sent)

    def test_a_targetless_action_records_that_explicitly(self):
        async def _go():
            general = _channel(11, None, "general")
            guild = _guild([general])
            general.guild = guild
            author = _member(AUTHOR_ID)
            bot = _bot()
            guild.create_text_channel = AsyncMock(return_value=general)
            message = _message(author, general, "انشئ روم جديد [EXEC: CREATE_TEXT|name=جديد]")
            await self._queue(
                action_cmd="CREATE_TEXT|name=جديد",
                content=message.content,
                guild=guild,
                message=message,
                bot=bot,
            )
            return bot.pending_confirm[(GUILD_ID, AUTHOR_ID)]

        entry = asyncio.run(_go())
        self.assertEqual(entry["targets"], {})


if __name__ == "__main__":
    unittest.main()
