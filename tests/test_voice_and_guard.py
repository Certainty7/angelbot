"""Voice ownership and the message-edit guard (C-016, C-018, C-019)."""
import asyncio
import unittest
from collections import deque
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import discord

from angel.voice_engine import MusicEngine, VoiceBusyError


class _Voice:
    def __init__(self, channel):
        self.channel = channel
        self.is_moving = False

    def is_connected(self):
        return True


class VoiceChannelGuardTest(unittest.TestCase):
    def _guild(self, current_channel_id):
        guild = MagicMock()
        guild.id = 1
        guild.voice_client = _Voice(MagicMock(id=current_channel_id, mention="<#2>"))
        return guild

    def test_joining_another_channel_raises_instead_of_hijacking(self):
        guild = self._guild(2)
        target = MagicMock()
        target.guild = guild
        target.id = 3
        target.connect = AsyncMock()
        engine = MusicEngine(MagicMock())
        with self.assertRaises(VoiceBusyError):
            asyncio.run(engine.ensure_connected(target))
        target.connect.assert_not_called()

    def test_joining_the_same_channel_reuses_the_client(self):
        guild = self._guild(2)
        target = MagicMock()
        target.guild = guild
        target.id = 2
        engine = MusicEngine(MagicMock())
        voice = asyncio.run(engine.ensure_connected(target))
        self.assertIs(voice, guild.voice_client)


def _bot_module():
    import bot as bot_module
    return bot_module


class GuardTest(unittest.TestCase):
    def _fake_bot(self):
        bot = MagicMock()
        bot.guard_modes_cache = {1: "active"}
        bot.spam_tracker = {(1, 7): deque(maxlen=10)}
        bot.send_modlog = AsyncMock()
        return bot

    def _message(self, content):
        member = MagicMock(spec=discord.Member)
        member.id = 7
        member.guild_permissions = discord.Permissions.none()
        member.timeout = AsyncMock()
        member.bot = False
        message = MagicMock(spec=discord.Message)
        message.guild = MagicMock()
        message.guild.id = 1
        message.author = member
        message.content = content
        message.channel = MagicMock(mention="<#3>")
        message.delete = AsyncMock()
        return message

    def test_an_edited_scam_link_is_caught(self):
        module = _bot_module()
        bot = self._fake_bot()
        message = self._message("join discord.gg/example")
        asyncio.run(module._run_angel_guard(bot, message))
        message.delete.assert_awaited()
        message.author.timeout.assert_awaited()
        bot.send_modlog.assert_awaited()

    def test_a_failed_delete_does_not_cancel_the_timeout(self):
        module = _bot_module()
        bot = self._fake_bot()
        message = self._message("join discord.gg/example")
        message.delete.side_effect = discord.Forbidden(MagicMock(status=403), "no permission")
        asyncio.run(module._run_angel_guard(bot, message))
        message.author.timeout.assert_awaited()
        bot.send_modlog.assert_awaited()

    def test_staff_are_exempt(self):
        module = _bot_module()
        bot = self._fake_bot()
        message = self._message("discord.gg/example")
        message.author.guild_permissions = discord.Permissions(manage_messages=True)
        asyncio.run(module._run_angel_guard(bot, message))
        message.delete.assert_not_awaited()


class GhostPingTest(unittest.TestCase):
    def test_without_a_modlog_channel_nothing_is_broadcast(self):
        module = _bot_module()
        bot = MagicMock()
        bot.db.get_user_prefs = AsyncMock(return_value={})
        bot.db.get_modlog_channel = AsyncMock(return_value=None)
        bot.send_modlog = AsyncMock()
        bot.snipe_cache = {}

        member = MagicMock(spec=discord.Member)
        member.id = 7
        member.bot = False
        member.display_name = "member"
        member.display_avatar.url = "https://example.invalid/a.png"

        mentioned = MagicMock(spec=discord.Member)
        mentioned.id = 8
        mentioned.bot = False
        mentioned.mention = "<@8>"

        message = MagicMock(spec=discord.Message)
        message.guild = MagicMock()
        message.guild.id = 1
        message.author = member
        message.content = "secret deleted text"
        message.attachments = []
        message.mentions = [mentioned]
        message.created_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        message.channel.send = AsyncMock()

        asyncio.run(module.on_message_delete(message))
        message.channel.send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
