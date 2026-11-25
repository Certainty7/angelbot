"""Audit finding 8: the natural-language owner tools must honour `ENABLE_SOVEREIGN_TOOLS`.

`/sovereign` refuses self-role escalation and puppet messages while the flag is false, but
`انجل اعطيني ادمن` and `انجل قولي في الشات ...` ran anyway. Outbound DMs are a separate
policy question and stay out of this ticket.
"""

import asyncio
import unittest
from unittest import mock
from unittest.mock import MagicMock

import discord

from angel import nl_router


class _Role:
    def __init__(self, position, name="role"):
        self.id = position
        self.position = position
        self.name = name
        self.mention = f"<@&{position}>"
        self.managed = False

    def __lt__(self, other):
        return self.position < other.position

    def __ge__(self, other):
        return self.position >= other.position

    def __gt__(self, other):
        return self.position > other.position


def _mistress():
    member = MagicMock(spec=discord.Member)
    member.id = 42
    member.top_role = _Role(90)
    member.guild_permissions = discord.Permissions(administrator=True)
    member.display_name = "mistress"
    member.mention = "<@42>"
    return member


def _guild():
    guild = MagicMock()
    guild.id = 1
    guild.me.top_role = _Role(100, "angel")
    guild.default_role = _Role(0, "@everyone")
    guild.roles = [_Role(0, "@everyone"), _Role(10, "VIP"), _Role(100, "angel")]
    return guild


def _message(author, guild, content):
    message = MagicMock(spec=discord.Message)
    message.guild = guild
    message.author = author
    message.content = content
    message.mentions = []
    message.role_mentions = []
    message.channel = MagicMock(id=77)
    message.channel.guild = guild
    return message


def _run(content, *, enabled, nickname="angel"):
    author = _mistress()
    guild = _guild()
    message = _message(author, guild, content)
    bot = MagicMock()
    bot.user = MagicMock(id=555, display_name=nickname)
    bot.last_social_target = {}
    bot.last_target_channel = {}

    target_role = _Role(10, "VIP")
    member = MagicMock(spec=discord.Member)
    member.add_roles = mock.AsyncMock()
    dest = MagicMock()
    dest.send = mock.AsyncMock()

    with mock.patch.object(nl_router, "SOVEREIGN_TOOLS_ENABLED", enabled), \
         mock.patch.object(nl_router, "safe_reply", new=mock.AsyncMock()) as reply, \
         mock.patch.object(nl_router, "get_or_fetch_member",
                           new=mock.AsyncMock(return_value=member)), \
         mock.patch.object(nl_router, "resolve_natural_text_channel", return_value=dest):
        handled = asyncio.run(nl_router.try_execute_natural_command(bot, message, content))

    return handled, reply, member, dest


def _said(reply):
    return " ".join(str(c.args) for c in reply.await_args_list if c.args)


class SelfRoleTest(unittest.TestCase):
    def test_a_disabled_flag_refuses_self_role_escalation(self):
        handled, reply, member, _ = _run("انجل اعطيني ادمن", enabled=False)

        self.assertTrue(handled)
        member.add_roles.assert_not_called()
        self.assertIn("ENABLE_SOVEREIGN_TOOLS", _said(reply))

    def test_the_owner_still_gets_the_role_when_the_flag_is_on(self):
        _, _, member, _ = _run("انجل اعطيني ادمن", enabled=True)

        member.add_roles.assert_awaited_once()


class PuppetMessageTest(unittest.TestCase):
    def test_a_disabled_flag_refuses_the_puppet_message(self):
        handled, reply, _, dest = _run("انجل قولي في الشات نص سري", enabled=False)

        self.assertTrue(handled)
        dest.send.assert_not_called()
        self.assertIn("ENABLE_SOVEREIGN_TOOLS", _said(reply))

    def test_the_puppet_message_goes_out_when_the_flag_is_on(self):
        _, _, _, dest = _run("انجل قولي في الشات نص سري", enabled=True)

        dest.send.assert_awaited_once()
        self.assertEqual(dest.send.await_args.args[0], "نص سري")


if __name__ == "__main__":
    unittest.main()
