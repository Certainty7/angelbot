"""AI quota gates (C-014).

`/translate` used to be a free, unlimited model call; the test drives the real command
callback and asserts the model is never reached once the quota refuses.
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from cogs.ai_chat import AiChat


def _member(uid=7):
    member = MagicMock(spec=discord.Member)
    member.id = uid
    member.display_name = "member"
    return member


def _interaction(member):
    interaction = MagicMock()
    interaction.user = member
    interaction.guild = MagicMock()
    interaction.guild.id = 1
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _bot(allowed=True, reason=None):
    bot = MagicMock()
    bot.quota.check_user_allowed = MagicMock(return_value=(allowed, reason))
    bot.ai.custom_prompt = AsyncMock(return_value="translated")
    bot.db.consume_guild_ai_quota = AsyncMock(return_value=(True, 1))
    bot.get_harem_title = MagicMock(return_value=None)
    return bot


class TranslateQuotaTest(unittest.TestCase):
    def test_a_refused_user_never_reaches_the_model(self):
        cog = AiChat(_bot(allowed=False, reason="انتهت حصتك اليومية"))
        interaction = _interaction(_member())
        asyncio.run(
            AiChat.translate_cmd.callback(cog, interaction, "hello", "Arabic")
        )
        interaction.response.send_message.assert_awaited()
        cog.bot.ai.custom_prompt.assert_not_awaited()

    def test_the_guild_cap_is_consumed_before_the_call(self):
        bot = _bot()
        bot.db.consume_guild_ai_quota = AsyncMock(return_value=(False, 40))
        cog = AiChat(bot)
        interaction = _interaction(_member())
        asyncio.run(
            AiChat.translate_cmd.callback(cog, interaction, "hello", "Arabic")
        )
        bot.db.consume_guild_ai_quota.assert_awaited_once()
        bot.ai.custom_prompt.assert_not_awaited()

    def test_an_allowed_user_reaches_the_model(self):
        bot = _bot()
        cog = AiChat(bot)
        interaction = _interaction(_member())
        asyncio.run(
            AiChat.translate_cmd.callback(cog, interaction, "hello", "Arabic")
        )
        bot.ai.custom_prompt.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()


class GuildQuotaTest(unittest.TestCase):
    def test_the_daily_cap_is_enforced_per_guild(self):
        from angel.database import BotDatabase
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db = BotDatabase(path)

        async def _run():
            await db.initialize()
            outcomes = [await db.consume_guild_ai_quota(1) for _ in range(42)]
            return outcomes

        try:
            outcomes = asyncio.run(_run())
        finally:
            asyncio.run(db.close())
            os.unlink(path)

        self.assertTrue(all(allowed for allowed, _used in outcomes[:40]))
        self.assertFalse(outcomes[40][0], "the 41st call must be refused")
        self.assertEqual(outcomes[40][1], 40)


if __name__ == "__main__":
    unittest.main()
