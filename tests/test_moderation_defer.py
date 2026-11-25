"""Audit finding 13: moderation mutations must follow an acknowledgement, never race it.

Discord kills the first response at three seconds. The old commands mutated first and
acknowledged after, so a 3.05-second kick succeeded while the ACK failed with 10062 and no
modlog was sent: the moderator sees a failure and retries an action that already happened.

The gate is `run_moderation_action`: defer, mutate, report, best-effort modlog.
"""

import asyncio
import types
import unittest
from unittest import mock

import discord

import cogs.admin as admin_module
from cogs.admin import Admin


def _run(coro):
    return asyncio.run(coro)


def _http_error(status=500, code=None, text="boom"):
    exc = discord.HTTPException(types.SimpleNamespace(status=status, reason=text), text)
    exc.code = code
    exc.status = status
    exc.text = text
    return exc


class _Response:
    def __init__(self, fail=None):
        self._done = False
        self.fail = fail
        self.sent = []

    def is_done(self):
        return self._done

    async def defer(self, ephemeral=False):
        if self.fail == "defer":
            raise _http_error(code=10062, text="Unknown interaction")
        self._done = True
        self.ephemeral = ephemeral

    async def send_message(self, *args, **kwargs):
        self._done = True
        if args:
            kwargs["content"] = args[0]
        self.sent.append(kwargs)


class _Followup:
    def __init__(self, log, fail=False):
        self.log = log
        self.fail = fail
        self.sent = []

    async def send(self, **kwargs):
        if self.fail:
            raise _http_error()
        self.log.append("followup")
        self.sent.append(kwargs)


class _Interaction:
    def __init__(self, log, fail_defer=False, fail_followup=False):
        self.log = log
        self.response = _Response(fail="defer" if fail_defer else None)
        self.followup = _Followup(log, fail=fail_followup)
        self.guild = types.SimpleNamespace(
            id=7, owner_id=1, default_role=types.SimpleNamespace(id=2), me=types.SimpleNamespace(id=3)
        )
        self.user = types.SimpleNamespace(id=10, mention="<@10>", guild_permissions=types.SimpleNamespace(administrator=False))
        self.channel = types.SimpleNamespace(id=11, mention="#general", edit=None)

    @property
    def deferred(self):
        return self.response.is_done()


class _Actor:
    """A member whose mutation records whether the interaction had been acknowledged."""

    def __init__(self, name, log, interaction, fail=False):
        self.name = name
        self.log = log
        self.interaction = interaction
        self.fail = fail
        self.deferred_when_called = None
        self.id = 42
        self.mention = "<@42>"
        self.display_name = "Target"

    async def _mutate(self, *args, **kwargs):
        self.deferred_when_called = self.interaction.deferred
        if self.fail:
            raise _http_error()
        self.log.append(self.name)

    kick = ban = add_roles = remove_roles = _mutate

    async def timeout(self, *args, **kwargs):
        await self._mutate(*args, **kwargs)


class _Guild:
    def __init__(self, log, interaction, fail=False):
        self.log = log
        self.interaction = interaction
        self.fail = fail
        self.default_role = types.SimpleNamespace(id=2)

    async def unban(self, *args, **kwargs):
        self.deferred_when_called = self.interaction.deferred
        if self.interaction.deferred is not True:
            raise AssertionError("unban ran before the interaction was acknowledged")
        if self.fail:
            raise _http_error(code=10026, text="Unknown Ban")
        self.log.append("unban")


class _Channel:
    def __init__(self, log, interaction):
        self.log = log
        self.interaction = interaction
        self.id = 11
        self.mention = "#general"

    def overwrites_for(self, role):
        return types.SimpleNamespace(send_messages=True)

    async def set_permissions(self, *args, **kwargs):
        self.deferred_when_called = self.interaction.deferred
        if self.interaction.deferred is not True:
            raise AssertionError("channel mutation ran before acknowledgement")
        self.log.append("set_permissions")

    async def edit(self, *args, **kwargs):
        self.deferred_when_called = self.interaction.deferred
        if self.interaction.deferred is not True:
            raise AssertionError("channel edit ran before acknowledgement")
        self.log.append("edit")


class _DB:
    def __init__(self, log, interaction):
        self.log = log
        self.interaction = interaction

    async def add_warning(self, *args, **kwargs):
        self.deferred_when_called = self.interaction.deferred
        if self.interaction.deferred is not True:
            raise AssertionError("add_warning ran before acknowledgement")
        self.log.append("add_warning")
        return 3

    async def clear_warnings(self, *args, **kwargs):
        self.deferred_when_called = self.interaction.deferred
        if self.interaction.deferred is not True:
            raise AssertionError("clear_warnings ran before acknowledgement")
        self.log.append("clear_warnings")
        return 2


class _Bot:
    def __init__(self, db):
        self.db = db
        self.mods = []
        self.pending_confirm = {}

    async def send_modlog(self, guild, title, desc, color=None):
        self.mods.append((title, desc))


def _cog(log, interaction, actor_fail=False, guild_fail=False):
    db = _DB(log, interaction)
    bot = _Bot(db)
    cog = Admin(bot)
    interaction.client = bot
    return cog, bot


class DeferOrderTest(unittest.TestCase):
    def setUp(self):
        patcher_a = mock.patch.object(admin_module, "can_moderate_member", return_value=(True, ""))
        patcher_b = mock.patch.object(admin_module, "can_assign_role", return_value=(True, ""))
        patcher_a.start()
        patcher_b.start()
        self.addCleanup(patcher_a.stop)
        self.addCleanup(patcher_b.stop)

    def _run_command(self, name, **kwargs):
        log = []
        interaction = _Interaction(log)
        cog, bot = _cog(log, interaction)
        actor = _Actor("member.kick", log, interaction)
        guild_mutations = _Guild(log, interaction)
        interaction.guild = types.SimpleNamespace(
            id=7, owner_id=1, default_role=types.SimpleNamespace(id=2),
            me=types.SimpleNamespace(id=3),
            unban=guild_mutations.unban,
            _mutations=guild_mutations,
        )
        interaction.channel = _Channel(log, interaction)
        cog.bot.db = _DB(log, interaction)
        cog.bot.db.interaction = interaction
        interaction._db = cog.bot.db
        args = {
            "kick_cmd": (actor,),
            "ban_cmd": (actor,),
            "unban_cmd": ("42",),
            "timeout_cmd": (actor, 10),
            "untimeout_cmd": (actor,),
            "add_role_cmd": (actor, types.SimpleNamespace(id=5, mention="<@&5>")),
            "remove_role_cmd": (actor, types.SimpleNamespace(id=5, mention="<@&5>")),
            "warn_cmd": (actor, "سبب"),
            "clear_warnings_cmd": (actor,),
            "lock_cmd": (None, "سبب"),
            "unlock_cmd": (None,),
            "slowmode_cmd": (30,),
        }[name]
        command = getattr(Admin, name)
        _run(command.callback(cog, interaction, *args, **kwargs))
        return log, interaction, actor, bot

    def test_every_moderation_surface_acknowledges_before_mutating(self):
        cases = {
            "kick_cmd": "member.kick",
            "ban_cmd": "member.kick",
            "unban_cmd": "unban",
            "timeout_cmd": "member.kick",
            "untimeout_cmd": "member.kick",
            "add_role_cmd": "member.kick",
            "remove_role_cmd": "member.kick",
            "warn_cmd": "add_warning",
            "clear_warnings_cmd": "clear_warnings",
            "lock_cmd": "set_permissions",
            "unlock_cmd": "set_permissions",
            "slowmode_cmd": "edit",
        }
        # Finding 14 gates the irreversible surfaces: they acknowledge, queue, and mutate only
        # after the typed confirmation — so the first interaction must show no mutation at all.
        gated = {"ban_cmd", "clear_warnings_cmd"}
        for name, mutation in cases.items():
            with self.subTest(command=name):
                log, interaction, actor, bot = self._run_command(name)
                if name in gated:
                    self.assertNotIn(mutation, log, f"{name}: mutated before confirmation")
                    self.assertEqual(log, ["followup"], f"{name}: order was {log}")
                    continue
                self.assertEqual(log[:2], [mutation, "followup"], f"{name}: order was {log}")
                witness = actor.deferred_when_called
                if witness is None:
                    witness = getattr(getattr(interaction.guild, "_mutations", None), "deferred_when_called", None)
                if witness is None:
                    witness = getattr(getattr(interaction, "_db", None), "deferred_when_called", None)
                if witness is None:
                    witness = getattr(interaction.channel, "deferred_when_called", None)
                self.assertIs(witness, True, f"{name} mutated before the ACK")

    def test_the_modlog_still_runs_after_a_slow_mutation(self):
        log, interaction, actor, bot = self._run_command("kick_cmd")
        self.assertEqual(log, ["member.kick", "followup"])
        self.assertEqual(len(bot.mods), 1)

    def test_a_failed_mutation_is_reported_and_logged_nowhere(self):
        log = []
        interaction = _Interaction(log)
        cog, bot = _cog(log, interaction)
        actor = _Actor("member.kick", log, interaction, fail=True)

        _run(Admin.kick_cmd.callback(cog, interaction, actor))

        self.assertEqual(log, ["followup"], "a failed mutation must be reported, not logged as done")
        self.assertEqual(bot.mods, [])
        self.assertIn("⚠️", interaction.followup.sent[0]["content"])

    def test_an_expired_interaction_never_mutates(self):
        log = []
        interaction = _Interaction(log, fail_defer=True)
        cog, bot = _cog(log, interaction)
        actor = _Actor("member.kick", log, interaction)

        _run(Admin.kick_cmd.callback(cog, interaction, actor))

        self.assertEqual(log, [], "the mutation ran although no response could ever be sent")
        self.assertIsNone(actor.deferred_when_called)

    def test_a_denied_moderator_gets_no_defer_and_no_mutation(self):
        log = []
        interaction = _Interaction(log)
        cog, bot = _cog(log, interaction)
        actor = _Actor("member.kick", log, interaction)
        with mock.patch.object(admin_module, "can_moderate_member", return_value=(False, "🚫 لا")):
            _run(Admin.kick_cmd.callback(cog, interaction, actor))

        self.assertEqual(log, [])
        self.assertEqual(interaction.response.sent[0]["content"], "🚫 لا")
