"""Admin dispatch: `/announce` effective channel permissions and media-only replies.

H (CWE-863): guild-level `mention_everyone` ignores channel overwrites, so a caller
could make the bot ping a channel the caller cannot ping in. The check must use the
effective permissions in the selected channel — and the bot must actually be able to
send there.
B: an image-only or GIF-only model reply is a valid outcome and must be delivered.
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from angel.text import plan_reply_delivery
from cogs.admin import Admin


def _perms(**kw):
    base = {"view_channel": True, "send_messages": True, "mention_everyone": False}
    base.update(kw)
    return discord.Permissions(**base)


def _interaction(user_channel_perms, bot_channel_perms, user_guild_perms=None):
    """One member with three permission views: guild snapshot, channel view for the
    caller, channel view for the bot."""
    user = MagicMock(spec=discord.Member)
    user.id = 7
    user.guild_permissions = user_guild_perms if user_guild_perms is not None else user_channel_perms

    me = MagicMock(spec=discord.Member)
    me.id = 555

    guild = MagicMock()
    guild.id = 1
    guild.me = me
    guild.owner_id = 999

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 77
    channel.mention = "<#77>"
    channel.permissions_for = lambda who: user_channel_perms if who is user else bot_channel_perms

    interaction = MagicMock()
    interaction.user = user
    interaction.guild = guild
    interaction.channel = channel
    interaction.response.send_message = AsyncMock()
    return interaction, channel


class AnnounceChannelPermissionsTest(unittest.TestCase):
    def _announce(self, user_channel, bot_channel, user_guild=None, ping_everyone=True):
        interaction, channel = _interaction(user_channel, bot_channel, user_guild)
        channel.send = AsyncMock()
        cog = Admin.__new__(Admin)
        cog.bot = MagicMock()
        asyncio.run(
            Admin.announce_cmd.callback(
                cog, interaction, channel, "title", "body", ping_everyone=ping_everyone
            )
        )
        return interaction, channel

    def test_a_channel_deny_overrides_guild_level_mention_everyone(self):
        # The guild snapshot says yes, the selected channel denies it: the old
        # guild-level check let the caller ping through the bot anyway.
        interaction, channel = self._announce(
            user_channel=_perms(mention_everyone=False),
            bot_channel=_perms(mention_everyone=True),
            user_guild=_perms(mention_everyone=True),
        )
        channel.send.assert_not_awaited()
        reply = str(interaction.response.send_message.await_args)
        self.assertIn("Mention Everyone", reply)

    def test_a_channel_allow_grants_the_ping_without_the_guild_bit(self):
        interaction, channel = self._announce(
            user_channel=_perms(mention_everyone=True),
            bot_channel=_perms(mention_everyone=True),
            user_guild=_perms(mention_everyone=False),
        )
        channel.send.assert_awaited_once()
        self.assertEqual(channel.send.await_args.kwargs["content"], "@everyone")

    def test_an_ordinary_guild_permission_still_announces(self):
        interaction, channel = self._announce(
            user_channel=_perms(mention_everyone=True),
            bot_channel=_perms(mention_everyone=True),
            user_guild=_perms(mention_everyone=True),
        )
        channel.send.assert_awaited_once()
        self.assertEqual(channel.send.await_args.kwargs["content"], "@everyone")

    def test_the_bot_cannot_send_into_a_channel_it_cannot_write(self):
        interaction, channel = self._announce(
            user_channel=_perms(),
            bot_channel=_perms(view_channel=True, send_messages=False),
            ping_everyone=False,
        )
        channel.send.assert_not_awaited()
        self.assertIn("لا أستطيع", str(interaction.response.send_message.await_args))

    def test_ping_everyone_without_the_bot_permission_is_refused(self):
        interaction, channel = self._announce(
            user_channel=_perms(mention_everyone=True),
            bot_channel=_perms(mention_everyone=False),
        )
        channel.send.assert_not_awaited()
        self.assertIn("Mention Everyone", str(interaction.response.send_message.await_args))


class ReplyDeliveryPlanTest(unittest.TestCase):
    def test_text_only_delivery(self):
        plan = plan_reply_delivery("hello", None, None, None)
        self.assertIsNotNone(plan)
        first, rest, has_files, use_gif_url = plan
        self.assertEqual(first, "hello")
        self.assertEqual(rest, [])
        self.assertFalse(has_files)
        self.assertFalse(use_gif_url)

    def test_image_only_delivery_has_no_text(self):
        plan = plan_reply_delivery("", None, None, b"PNGDATA")
        first, rest, has_files, use_gif_url = plan
        self.assertIsNone(first)
        self.assertTrue(has_files)
        self.assertFalse(use_gif_url)

    def test_gif_only_delivery_uses_the_embed(self):
        plan = plan_reply_delivery("", None, "https://cdn.example/a.gif", None)
        first, _rest, has_files, use_gif_url = plan
        self.assertIsNone(first)
        self.assertFalse(has_files)
        self.assertTrue(use_gif_url)

    def test_a_reply_with_neither_text_nor_media_stays_silent(self):
        self.assertIsNone(plan_reply_delivery("", None, None, None))
        self.assertIsNone(plan_reply_delivery("   ", None, None, None))

    def test_text_and_media_are_delivered_together(self):
        plan = plan_reply_delivery("here you go", b"GIFDATA", None, b"PNGDATA")
        first, rest, has_files, use_gif_url = plan
        self.assertEqual(first, "here you go")
        self.assertTrue(has_files)
        self.assertFalse(use_gif_url)


if __name__ == "__main__":
    unittest.main()
