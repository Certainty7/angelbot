"""Audit finding 14: one confirmation gate, and a documented scope for it.

AGENTS.md and the README promise that destructive actions are queued and need the same person
to type `تأكيد` within 60 seconds. Only the model-proposed `[EXEC]` path kept that promise:
`/ban`, `/purge`, `/clear_warnings`, the direct natural-language commands and custom triggers
mutated Discord immediately.

The owner chose a narrowed, documented invariant: irreversible actions (message purge, ban,
warning erasure) are gated on every surface — slash, natural language, trigger, model — while
reversible single-target commands (`/timeout`, `/kick`, `/lock`, role changes) are an approved
documented exception. These tests pin both halves so neither can drift silently.
"""

import asyncio
import types
import unittest
from unittest import mock

import discord

import angel.confirmations as confirmations
import angel.nl_router as nl_router
import cogs.admin as admin_module
from cogs.admin import Admin

PROMPT_HINTS = ("تأكيد", "60")


def _run(coro):
    return asyncio.run(coro)


class _Role:
    """discord.Role compares by position; the guard relies on that ordering."""

    def __init__(self, position):
        self.position = position

    def __ge__(self, other):
        return self.position >= other.position

    def __gt__(self, other):
        return self.position > other.position

    def __lt__(self, other):
        return self.position < other.position

    def __le__(self, other):
        return self.position <= other.position


def _member(uid, position=10, **perms):
    member = types.SimpleNamespace(
        id=uid,
        top_role=_Role(position),
        guild_permissions=discord.Permissions(**perms),
        display_name=f"m{uid}",
        name=f"m{uid}",
        nickname=None,
        mention=f"<@{uid}>",
        bot=False,
    )
    return member


class _Response:
    def __init__(self):
        self._done = False
        self.sent = []

    def is_done(self):
        return self._done

    async def defer(self, ephemeral=False):
        self._done = True

    async def send_message(self, *args, **kwargs):
        self._done = True
        if args:
            kwargs["content"] = args[0]
        self.sent.append(kwargs)


class _Followup:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        if args:
            kwargs["content"] = args[0]
        self.sent.append(kwargs)


class _Interaction:
    def __init__(self, guild, author, bot):
        self.guild = guild
        self.user = author
        self.client = bot
        self.response = _Response()
        self.followup = _Followup()
        self.channel = guild.channels[0]
        self.channel_id = self.channel.id

    @property
    def deferred(self):
        return self.response.is_done()


def _guild(author, target, **bot_perms):
    channel = types.SimpleNamespace(
        id=77, mention="<#77>", purge=mock.AsyncMock(), send=mock.AsyncMock()
    )
    guild = types.SimpleNamespace(
        id=1,
        owner_id=999,
        me=_member(555, 100, **bot_perms),
        default_role=types.SimpleNamespace(id=2),
        channels=[channel],
        voice_channels=[],
        roles=[],
        emojis=[],
        stickers=[],
        members=[target],
        get_member=lambda uid: target if uid == target.id else None,
        fetch_member=mock.AsyncMock(return_value=target),
    )
    return guild


def _bot():
    bot = mock.MagicMock()
    bot.user = types.SimpleNamespace(id=555)
    bot.pending_confirm = {}
    bot.pending_step = {}
    bot.active_chat_window = {}
    bot.last_social_target = {}
    bot.last_target_channel = {}
    bot.action_triggers_cache = {}
    bot.send_modlog = mock.AsyncMock()
    bot.db = mock.MagicMock()
    bot.db.clear_warnings = mock.AsyncMock(return_value=2)
    bot.db.forget_user_keyword = mock.AsyncMock()
    bot.db.increment_trigger_usage = mock.AsyncMock()
    return bot


def _message(author, guild, content, mentions=()):
    channel = guild.channels[0]
    message = mock.MagicMock(spec=discord.Message)
    message.guild = guild
    message.author = author
    message.content = content
    message.channel = channel
    message.mentions = list(mentions)
    message.role_mentions = []
    message.channel_mentions = []
    message.embeds = []
    message.reference = None
    message.attachments = []
    message.created_at = discord.utils.utcnow()
    message.id = 4242
    return message


def _slash(cog, bot, guild, author, name, *args):
    command = getattr(Admin, name)
    interaction = _Interaction(guild, author, bot)
    _run(command.callback(cog, interaction, *args))
    return interaction


class _Base(unittest.TestCase):
    def setUp(self):
        patcher_a = mock.patch.object(admin_module, "can_moderate_member", return_value=(True, ""))
        patcher_b = mock.patch.object(admin_module, "can_assign_role", return_value=(True, ""))
        patcher_a.start()
        patcher_b.start()
        self.addCleanup(patcher_a.stop)
        self.addCleanup(patcher_b.stop)
        self.bot = _bot()
        self.author = _member(7, 50, ban_members=True, manage_messages=True, moderate_members=True,
                                 manage_nicknames=True)
        self.target = _member(8, 10)
        self.target.ban = mock.AsyncMock()
        self.target.kick = mock.AsyncMock()
        self.target.timeout = mock.AsyncMock()
        self.guild = _guild(self.author, self.target, ban_members=True, manage_messages=True)
        self.cog = Admin(self.bot)

    def confirm(self, text="تأكيد", author=None, channel=None):
        message = _message(author or self.author, self.guild, text)
        if channel is not None:
            message.channel = channel
        return _run(nl_router.try_execute_natural_command(self.bot, message, text)), message


class SlashScopeTest(_Base):
    def test_ban_queues_instead_of_mutating(self):
        interaction = _slash(self.cog, self.bot, self.guild, self.author, "ban_cmd", self.target, "سبب")

        self.target.ban.assert_not_awaited()
        self.assertIn((self.guild.id, self.author.id), self.bot.pending_confirm)
        prompt = interaction.followup.sent[0]["content"]
        for hint in PROMPT_HINTS:
            self.assertIn(hint, prompt)

    def test_the_typed_confirmation_executes_the_ban_once(self):
        _slash(self.cog, self.bot, self.guild, self.author, "ban_cmd", self.target, "سبب")

        handled, _ = self.confirm()

        self.assertTrue(handled)
        self.target.ban.assert_awaited_once()
        self.bot.send_modlog.assert_awaited_once()
        self.assertNotIn((self.guild.id, self.author.id), self.bot.pending_confirm)

    def test_purge_and_clear_warnings_are_gated_too(self):
        cases = {
            "purge_cmd": ((5,), lambda: self.guild.channels[0].purge),
            "clear_warnings_cmd": ((self.target,), lambda: self.bot.db.clear_warnings),
        }
        for name, (args, mutation) in cases.items():
            with self.subTest(command=name):
                self.bot.pending_confirm.clear()
                interaction = _slash(self.cog, self.bot, self.guild, self.author, name, *args)
                mutation().assert_not_awaited()
                self.assertIn((self.guild.id, self.author.id), self.bot.pending_confirm)
                self.assertIn("تأكيد", interaction.followup.sent[0]["content"])

    def test_a_reversible_command_stays_immediate(self):
        # Documented exception: /timeout is reversible, so it is not gated.
        _slash(self.cog, self.bot, self.guild, self.author, "timeout_cmd", self.target, 10, "سبب")

        self.target.timeout.assert_awaited_once()
        self.assertEqual(self.bot.pending_confirm, {})


class ConfirmationLifecycleTest(_Base):
    def _queue_ban(self):
        _slash(self.cog, self.bot, self.guild, self.author, "ban_cmd", self.target, "سبب")

    def test_another_channel_cancels_instead_of_executing(self):
        self._queue_ban()
        other = types.SimpleNamespace(id=88, mention="<#88>")

        handled, _ = self.confirm(channel=other)

        self.assertTrue(handled)
        self.target.ban.assert_not_awaited()
        self.assertEqual(self.bot.pending_confirm, {})

    def test_an_expired_confirmation_does_nothing(self):
        self._queue_ban()
        key = (self.guild.id, self.author.id)
        self.bot.pending_confirm[key]["ts"] -= confirmations.CONFIRM_TTL + 1

        handled, _ = self.confirm()

        self.assertTrue(handled)
        self.target.ban.assert_not_awaited()
        self.assertEqual(self.bot.pending_confirm, {})

    def test_a_cancel_word_clears_the_pending_action(self):
        self._queue_ban()

        handled, _ = self.confirm("الغاء")

        self.assertTrue(handled)
        self.target.ban.assert_not_awaited()
        self.assertEqual(self.bot.pending_confirm, {})

    def test_a_lost_permission_blocks_at_confirmation_time(self):
        self._queue_ban()
        self.author.guild_permissions = discord.Permissions.none()
        self.guild.get_member = lambda uid: self.author
        self.guild.fetch_member = mock.AsyncMock(return_value=self.author)

        with mock.patch.object(nl_router, "safe_reply", new=mock.AsyncMock()) as reply:
            handled, _ = self.confirm()

        self.assertTrue(handled)
        self.target.ban.assert_not_awaited()
        self.assertIn("🚫", reply.await_args.args[1])

    def test_only_the_requester_can_confirm(self):
        self._queue_ban()
        stranger = _member(9, 60, ban_members=True)
        self.guild.get_member = lambda uid: stranger if uid == stranger.id else self.target
        self.guild.fetch_member = mock.AsyncMock(return_value=stranger)

        self.confirm(author=stranger)

        self.target.ban.assert_not_awaited()
        self.assertIn((self.guild.id, self.author.id), self.bot.pending_confirm)


class NaturalLanguageScopeTest(_Base):
    def test_a_direct_nl_ban_is_queued(self):
        message = _message(self.author, self.guild, "انجل احظري m8", mentions=[self.target])

        handled = _run(nl_router.try_execute_natural_command(self.bot, message, message.content))

        self.assertTrue(handled)
        self.target.ban.assert_not_awaited()
        self.assertIn((self.guild.id, self.author.id), self.bot.pending_confirm)

    def test_a_direct_nl_purge_is_queued(self):
        message = _message(self.author, self.guild, "انجل امسحي 5 رسائل")

        _run(nl_router.try_execute_natural_command(self.bot, message, message.content))

        self.guild.channels[0].purge.assert_not_awaited()
        self.assertIn((self.guild.id, self.author.id), self.bot.pending_confirm)


class TriggerScopeTest(_Base):
    def test_a_custom_trigger_ban_is_queued(self):
        patcher = mock.patch.object(nl_router, "check_staff_action_permission", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bot.action_triggers_cache[self.guild.id] = {
            "احظر": {"phrase": "احظر", "action_type": "ban", "param_value": None, "custom_reply": ""}
        }
        message = _message(self.author, self.guild, "احظر m8", mentions=[self.target])

        _run(nl_router.try_execute_custom_action_trigger(self.bot, message))

        self.target.ban.assert_not_awaited()
        self.assertIn((self.guild.id, self.author.id), self.bot.pending_confirm)


class LegacyEntryTest(_Base):
    def test_an_entry_without_a_closure_still_runs_the_exec_path(self):
        message = _message(self.author, self.guild, "غير اللقب", mentions=[self.target])
        self.bot.pending_confirm[(self.guild.id, self.author.id)] = {
            "cmd": "NICKNAME|name=new",
            "message": message,
            "channel_id": message.channel.id,
            "ts": confirmations.time.monotonic(),
        }
        self.target.edit = mock.AsyncMock()
        self.guild.fetch_member = mock.AsyncMock(return_value=self.author)
        patcher = mock.patch.object(nl_router, "check_staff_action_permission", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

        handled, _ = self.confirm()

        self.assertTrue(handled)
        self.target.edit.assert_awaited_once()
