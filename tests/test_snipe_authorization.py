"""Audit finding 7: the natural-language snipe twins must respect the slash permission.

`/snipe` and `/editsnipe` require `manage_messages`; `انجل سنايب` and `انجل وش تعدل` read the
same caches with no check, so any member could recover deleted or edited text.
"""

import asyncio
import unittest
from datetime import datetime, timezone
from unittest import mock
from unittest.mock import MagicMock

import discord

from angel import nl_router

CACHED_TEXT = "DELETED-PRIVATE-TEXT"


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
    return member


def _channel(*, manage_messages=False):
    channel = MagicMock()
    channel.id = 77
    channel.guild = MagicMock(id=1)
    channel.permissions_for = MagicMock(
        return_value=discord.Permissions(manage_messages=manage_messages)
    )
    return channel


def _message(author, channel, content):
    message = MagicMock(spec=discord.Message)
    message.guild = channel.guild
    message.author = author
    message.content = content
    message.channel = channel
    message.mentions = []
    return message


def _bot():
    bot = MagicMock()
    bot.user = MagicMock(id=555)
    bot.last_social_target = {}
    bot.last_target_channel = {}
    bot.snipe_cache = {
        77: {
            "content": CACHED_TEXT,
            "author_name": "someone",
            "author_avatar": "https://example.invalid/a.png",
            "attachment": None,
            "deleted_at": datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc),
        }
    }
    bot.editsnipe_cache = {
        77: {
            "before": CACHED_TEXT,
            "after": "EDITED-PRIVATE-TEXT",
            "author_name": "someone",
            "author_avatar": "https://example.invalid/a.png",
            "edited_at": datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc),
        }
    }
    return bot


def _replies(patch):
    return " ".join(str(c.args) for c in patch.await_args_list if c.args)


def _embeds(patch):
    return [c.kwargs["embed"] for c in patch.await_args_list if c.kwargs.get("embed")]


def _run(content, author, channel, bot):
    message = _message(author, channel, content)
    with mock.patch.object(nl_router, "safe_reply", new=mock.AsyncMock()) as reply:
        handled = asyncio.run(nl_router.try_execute_natural_command(bot, message, content))
    return handled, _replies(reply), _embeds(reply)


class SnipeAuthorizationTest(unittest.TestCase):
    def test_an_unprivileged_member_gets_no_deleted_content(self):
        handled, replies, embeds = _run(
            "انجل سنايب", _member(7, 10), _channel(manage_messages=False), _bot()
        )

        self.assertTrue(handled)
        self.assertEqual(embeds, [])
        self.assertNotIn(CACHED_TEXT, replies)

    def test_staff_with_channel_permission_still_gets_it(self):
        _, replies, embeds = _run(
            "انجل سنايب", _member(7, 50), _channel(manage_messages=True), _bot()
        )

        self.assertEqual(len(embeds), 1)
        self.assertEqual(embeds[0].description, CACHED_TEXT)

    def test_the_owner_bypass_still_works(self):
        _, _, embeds = _run(
            "انجل سنايب", _member(42, 10), _channel(manage_messages=False), _bot()
        )

        self.assertEqual(len(embeds), 1)
        self.assertEqual(embeds[0].description, CACHED_TEXT)


class EditSnipeAuthorizationTest(unittest.TestCase):
    def test_an_unprivileged_member_gets_no_edited_content(self):
        handled, replies, embeds = _run(
            "انجل وش تعدل", _member(7, 10), _channel(manage_messages=False), _bot()
        )

        self.assertTrue(handled)
        self.assertEqual(embeds, [])
        self.assertNotIn(CACHED_TEXT, replies)

    def test_staff_with_channel_permission_still_gets_it(self):
        _, _, embeds = _run(
            "انجل وش تعدل", _member(7, 50), _channel(manage_messages=True), _bot()
        )

        self.assertEqual(len(embeds), 1)
        fields = {f.name: f.value for f in embeds[0].fields}
        self.assertEqual(fields["قبل"], CACHED_TEXT)


class ChannelScopedPermissionTest(unittest.TestCase):
    """`manage_messages` granted by a role but denied in this channel must not open the cache."""

    def test_a_guild_level_grant_is_not_enough_when_the_channel_denies_it(self):
        member = _member(7, 50, manage_messages=True)
        channel = _channel(manage_messages=False)

        _, _, embeds = _run("انجل سنايب", member, channel, _bot())

        self.assertEqual(embeds, [])
        channel.permissions_for.assert_called()


if __name__ == "__main__":
    unittest.main()
