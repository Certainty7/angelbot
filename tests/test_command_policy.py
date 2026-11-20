"""Every registered action must declare an authorization policy (Stage 3A).

The inventory in `angel/authz.py` is only useful if it cannot drift: this test fails when a
command exists without an entry, when an entry is stale, or when the declared `guild_only` /
permission disagrees with the live command tree.
"""
import inspect
import os
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ.setdefault("ANGEL_OWNER_ID", "42")
os.environ.setdefault("ANGEL_AUTO_INSTALL", "0")
os.environ.setdefault("ANGEL_DB_PATH", str(Path(os.environ.get("TEMP", ".")) / "angel-policy.db"))
sys.path.insert(0, str(REPO))

from angel import authz  # noqa: E402


def _lazy_music_commands():
    source = (REPO / "cogs" / "music.py").read_text(encoding="utf-8")
    return set(re.findall(r'@app_commands\.command\(name="([^"]+)"', source))


class PolicyInventoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import bot  # noqa: F401 - importing registers every eager command
        cls.bot = bot.bot
        cls.commands = {c.name: c for c in cls.bot.tree.get_commands()}

    def test_every_live_command_is_declared(self):
        missing = authz.missing_policies(self.commands)
        self.assertFalse(missing, "commands with no authorization policy: " + ", ".join(missing))

    def test_the_inventory_has_no_stale_entries(self):
        live = set(self.commands) | _lazy_music_commands()
        stale = sorted(set(authz.POLICIES) - live)
        self.assertFalse(stale, "policy entries for commands that do not exist: " + ", ".join(stale))

    def test_guild_only_declaration_matches_the_tree(self):
        wrong = []
        for name, command in self.commands.items():
            policy = authz.POLICIES[name]
            if bool(getattr(command, "guild_only", False)) != policy.guild_only:
                wrong.append(f"{name}: declared={policy.guild_only} live={command.guild_only}")
        self.assertFalse(wrong, "; ".join(wrong))

    def test_declared_permission_matches_default_permissions(self):
        wrong = []
        for name, command in self.commands.items():
            policy = authz.POLICIES[name]
            perms = getattr(command, "default_permissions", None)
            if policy.permission is None:
                continue
            if perms is None or not getattr(perms, policy.permission, False):
                wrong.append(f"{name}: expected {policy.permission}")
        self.assertFalse(wrong, "; ".join(wrong))

    def test_scopes_are_known_values(self):
        for name, policy in authz.POLICIES.items():
            self.assertIn(policy.scope, {"owner", "staff", "member"}, name)
            self.assertTrue(policy.intent.strip(), f"{name} has no documented intent")

    def test_lazy_music_commands_are_declared(self):
        for name in _lazy_music_commands():
            self.assertIn(name, authz.POLICIES, f"music command {name} has no policy")

    def test_owner_only_commands_really_check_the_owner(self):
        """A command declared `owner` must consult is_mistress in its own body."""
        offenders = []
        for name, policy in authz.POLICIES.items():
            if policy.scope != "owner" or name not in self.commands:
                continue
            try:
                source = inspect.getsource(self.commands[name].callback)
            except (OSError, TypeError):
                continue
            if "is_mistress" not in source and "has_perm_or_mistress" not in source:
                offenders.append(name)
        self.assertFalse(offenders, "declared owner-only but no owner check: " + ", ".join(offenders))


class ContextMenuPolicyTest(unittest.TestCase):
    def test_context_menus_are_not_guild_locked(self):
        # They are used on messages in DMs too; a guild_only menu would be unusable there.
        for name in ("تلخيص الرسالة", "ترجمة وتحليل", "اقتراح رد ومهام"):
            self.assertFalse(authz.POLICIES[name].guild_only)


if __name__ == "__main__":
    unittest.main()
