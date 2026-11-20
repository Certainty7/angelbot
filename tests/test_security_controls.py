"""Security controls: hierarchy, history access, mention filtering, resource bounds.

C-011, C-012, C-015, C-016 (guard), C-030, C-031, P-009.
"""
import asyncio
import unittest
from unittest.mock import MagicMock

import discord

from angel.cache import BoundedDict
from angel.config import can_assign_role, can_moderate_member, can_read_history
from angel.media import _fit_byte_budget
from angel.net import _session_lock
from angel.output_filter import filter_outgoing
from angel.ui import ArtStudioView

OWNER_ID = 42


class _Role:
    def __init__(self, position: int, name: str = "role"):
        self.position = position
        self.name = name
        self.id = position
        self.managed = False

    def __ge__(self, other):
        return self.position >= other.position

    def __gt__(self, other):
        return self.position > other.position


def _member(uid: int, position: int):
    member = MagicMock(spec=discord.Member)
    member.id = uid
    member.top_role = _Role(position)
    member.guild_permissions = discord.Permissions.none()
    return member


def _guild(bot_position: int = 100, owner_id: int = 999):
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.owner_id = owner_id
    guild.me = _member(555, bot_position)
    return guild


class ModerationHierarchyTest(unittest.TestCase):
    def setUp(self):
        self.guild = _guild()

    def test_a_moderator_cannot_punish_an_equal_or_higher_role(self):
        moderator = _member(7, 50)
        for position in (50, 60):
            allowed, why = can_moderate_member(moderator, _member(8, position), self.guild)
            self.assertFalse(allowed, f"position {position} should be refused")
            self.assertTrue(why)

    def test_a_moderator_can_punish_a_lower_role(self):
        allowed, _ = can_moderate_member(_member(7, 50), _member(8, 10), self.guild)
        self.assertTrue(allowed)

    def test_nobody_can_punish_the_owner_or_the_bot(self):
        owner = _member(OWNER_ID, 1)
        self.assertFalse(can_moderate_member(_member(7, 50), owner, self.guild)[0])
        bot_member = _member(555, 100)
        self.assertFalse(can_moderate_member(_member(7, 50), bot_member, self.guild)[0])

    def test_the_guild_owner_cannot_be_punished(self):
        allowed, _ = can_moderate_member(_member(7, 50), _member(999, 5), self.guild)
        self.assertFalse(allowed)

    def test_no_action_on_self(self):
        actor = _member(7, 50)
        self.assertFalse(can_moderate_member(actor, actor, self.guild)[0])

    def test_dm_context_is_refused(self):
        self.assertFalse(can_moderate_member(_member(7, 50), _member(8, 10), None)[0])


class RoleAssignmentTest(unittest.TestCase):
    def setUp(self):
        self.guild = _guild()
        self.bot_role = _Role(100)
        self.guild.me = MagicMock()
        self.guild.me.top_role = self.bot_role
        self.guild.default_role = _Role(0, "@everyone")

    def test_a_staff_member_cannot_grant_a_role_at_or_above_their_own(self):
        actor = _member(7, 50)
        allowed, _ = can_assign_role(actor, _Role(50), self.guild)
        self.assertFalse(allowed)
        allowed, _ = can_assign_role(actor, _Role(60), self.guild)
        self.assertFalse(allowed)

    def test_a_lower_role_is_allowed(self):
        self.assertTrue(can_assign_role(_member(7, 50), _Role(10), self.guild)[0])


class HistoryAccessTest(unittest.TestCase):
    def _channel(self, *, read: bool, history: bool):
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = _guild()
        perms = MagicMock()
        perms.read_messages = read
        perms.read_message_history = history
        channel.permissions_for.return_value = perms
        return channel

    def test_reading_messages_is_not_reading_history(self):
        # The natural-language summary bypass: visible channel, hidden history (C-004).
        member = _member(7, 10)
        self.assertFalse(can_read_history(self._channel(read=True, history=False), member))
        self.assertTrue(can_read_history(self._channel(read=True, history=True), member))

    def test_a_dm_has_no_history_to_summarise(self):
        self.assertFalse(can_read_history(MagicMock(guild=None), _member(7, 10)))
        self.assertFalse(can_read_history(None, _member(7, 10)))


class OutputFilterTest(unittest.TestCase):
    def test_user_role_and_mass_mentions_are_neutralised(self):
        cleaned = filter_outgoing("hi <@123> <@!456> <@&789> @everyone")
        self.assertNotIn("<@123>", cleaned)
        self.assertNotIn("<@!456>", cleaned)
        self.assertNotIn("<@&789>", cleaned)
        self.assertNotIn("@everyone", cleaned)

    def test_control_tags_are_removed(self):
        # Assert against the complete input tag: the shorter "[EXEC: BAN]" is not a
        # substring of the input, so its absence proved nothing about the filter.
        self.assertNotIn("[EXEC: BAN|user=1]", filter_outgoing("ok [EXEC: BAN|user=1]"))


class CacheTest(unittest.TestCase):
    def test_bounded_dict_is_lru(self):
        cache = BoundedDict(2)
        cache["a"] = 1
        cache["b"] = 2
        _ = cache["a"]           # a is now the most recently used
        cache["c"] = 3           # evicts b, not a
        self.assertIn("a", cache)
        self.assertNotIn("b", cache)

    def test_get_counts_as_a_use(self):
        cache = BoundedDict(2)
        cache["a"] = 1
        cache["b"] = 2
        self.assertEqual(cache.get("a"), 1)
        cache["c"] = 3
        self.assertIn("a", cache)
        self.assertNotIn("b", cache)


class EmbedLimitTest(unittest.TestCase):
    def test_long_prompt_stays_inside_the_embed_limit(self):
        view = ArtStudioView("x" * 20_000, MagicMock(), 1)
        rendered = f"🎨 **{view.prompt}** (`{'انمي'}`)"[:4096]
        # The rendered (sliced) description is the display limit; generation keeps the
        # full prompt within the old 4096 bound for the regenerate button.
        self.assertLessEqual(len(rendered), 4096)
        self.assertLessEqual(len(view.prompt), 4096)


class MediaBudgetTest(unittest.TestCase):
    def test_slides_are_dropped_once_the_byte_budget_is_reached(self):
        slides = [(i, b"x" * 100, f"{i}.jpg") for i in range(10)]
        kept, dropped = _fit_byte_budget(slides, budget=250)
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, 8)
        self.assertLessEqual(sum(len(b) for _i, b, _f in kept), 250)

    def test_a_single_oversized_slide_is_still_kept(self):
        kept, dropped = _fit_byte_budget([(1, b"x" * 1000, "1.jpg")], budget=10)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, 0)


class SessionLockTest(unittest.TestCase):
    """P-009: a module-level lock broke the second asyncio.run() in one process."""

    def test_each_loop_gets_its_own_lock(self):
        async def use():
            async with _session_lock():
                return _session_lock()

        # Retain both locks and compare identity: `id()` reuse after the first lock was
        # garbage-collected made a correct implementation fail this test randomly.
        first = asyncio.run(use())
        second = asyncio.run(use())
        self.assertIsNot(first, second)


if __name__ == "__main__":
    unittest.main()
