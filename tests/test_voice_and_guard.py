"""Voice ownership and the message-edit guard (C-016, C-018, C-019)."""
import asyncio
import unittest
from collections import deque
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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


class StaleAdvanceRetryTest(unittest.TestCase):
    """A DAVE-blocked retry must not dequeue a track another /play already started."""

    def _guild(self, *, playing, current):
        guild = MagicMock()
        guild.id = 1
        voice = MagicMock()
        voice.is_playing.return_value = playing
        voice.is_paused.return_value = False
        voice.is_connected.return_value = True
        guild.voice_client = voice
        engine = MusicEngine(MagicMock())
        state = engine.state(1)
        state.current = current
        engine._play_next_locked = AsyncMock()
        return guild, engine, state

    def test_a_stale_retry_returns_without_dequeuing(self):
        guild, engine, state = self._guild(playing=True, current=MagicMock())
        state.tracks.append(MagicMock())
        asyncio.run(engine._advance_if_idle(guild))
        engine._play_next_locked.assert_not_awaited()
        self.assertEqual(len(state.tracks), 1, "the stale retry ate the queue")

    def test_an_idle_engine_still_advances(self):
        guild, engine, state = self._guild(playing=False, current=None)
        state.tracks.append(MagicMock())
        asyncio.run(engine._advance_if_idle(guild))
        engine._play_next_locked.assert_awaited_once()


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

    def test_edits_are_inspected_but_never_flood_counted(self):
        module = _bot_module()
        bot = self._fake_bot()
        message = self._message("just chatting")
        # One message plus five edits used to be six entries and a five-minute timeout.
        for _ in range(6):
            asyncio.run(module._run_angel_guard(bot, message, is_edit=True))
        self.assertEqual(len(bot.spam_tracker[(1, 7)]), 0, "edits fed the flood counter")
        message.author.timeout.assert_not_awaited()
        # Link inspection still runs on edits (C-018).
        message.content = "join discord.gg/example"
        asyncio.run(module._run_angel_guard(bot, message, is_edit=True))
        message.author.timeout.assert_awaited()

    def test_six_new_messages_still_trip_the_flood_gate(self):
        module = _bot_module()
        bot = self._fake_bot()
        message = self._message("spam")
        for _ in range(6):
            asyncio.run(module._run_angel_guard(bot, message, is_edit=False))
        self.assertEqual(len(bot.spam_tracker[(1, 7)]), 6)
        message.author.timeout.assert_awaited()


class GhostPingTest(unittest.TestCase):
    def test_without_a_modlog_channel_nothing_is_broadcast(self):
        module = _bot_module()
        bot = MagicMock()
        bot.db.get_user_prefs = AsyncMock(return_value={})
        bot.db.get_modlog_channel = AsyncMock(return_value=None)
        bot.db.close = AsyncMock()
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

        # The handler reads the module-global client; without this patch it would use the
        # real one, open a database the test never closes, and its non-daemon aiosqlite
        # thread would keep the whole pytest process alive forever.
        with patch.object(module, "bot", bot):
            asyncio.run(module.on_message_delete(message))
        message.channel.send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
