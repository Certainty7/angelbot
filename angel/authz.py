"""Central authorization inventory for every registered action.

Discord enforces the *bot's* permissions, not the *caller's* hierarchy, so each command has
to declare its own policy. This module is the single list of those declarations:

* `guild_only` and `permission` are the values the decorators must set, and
  `tests/test_command_policy.py` fails when the live command tree disagrees with them;
* `scope` records who is meant to be able to run it (`owner`, `staff`, `member`);
* `intent` records the human-readable reason, so a reviewer does not have to re-derive it.

A new command cannot ship without an entry: the test enumerates the tree and fails on an
undeclared name. Dead entries fail too, so the inventory cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class Policy:
    scope: str  # "owner" | "staff" | "member"
    guild_only: bool
    permission: Optional[str]  # a discord.Permissions attribute, or None
    intent: str


POLICIES: Dict[str, Policy] = {
    # --- moderation -------------------------------------------------------
    "kick": Policy("staff", True, "kick_members", "remove a member, hierarchy checked"),
    "ban": Policy("staff", True, "ban_members", "ban a member, hierarchy checked"),
    "unban": Policy("staff", True, "ban_members", "lift a ban by user id"),
    "timeout": Policy("staff", True, "moderate_members", "temporary mute, hierarchy checked"),
    "untimeout": Policy("staff", True, "moderate_members", "lift a mute, hierarchy checked"),
    "warn": Policy("staff", True, "moderate_members", "record a warning, hierarchy checked"),
    "warnings": Policy("staff", True, "moderate_members", "read a member's warning log"),
    "clear_warnings": Policy("staff", True, "moderate_members", "erase warnings, hierarchy checked"),
    "purge": Policy("staff", True, "manage_messages", "bulk delete in the current channel"),
    "snipe": Policy("staff", True, "manage_messages", "reveal the last deleted message"),
    "editsnipe": Policy("staff", True, "manage_messages", "reveal the last edited message"),
    "announce": Policy(
        "staff", True, "manage_guild",
        "post an embed; @everyone additionally needs mention_everyone",
    ),
    "set_modlog": Policy("staff", True, "administrator", "choose the moderation log channel"),
    "guard": Policy("staff", True, "manage_guild", "configure the anti-spam guard"),
    "pulse": Policy("staff", True, "manage_guild", "server activity dashboard"),
    "auto_reply": Policy("staff", True, "manage_guild", "manage stored reply triggers"),
    "giveaway": Policy("staff", True, "manage_guild", "create and end giveaways"),
    "autorole": Policy("staff", True, "manage_roles", "pick the join role (assignability checked)"),
    "ticket_panel": Policy("staff", True, "manage_channels", "post the ticket panel"),
    "sticky": Policy("staff", True, "manage_messages", "pin a repeating channel message"),
    "lock": Policy("staff", True, "manage_channels", "deny send_messages for @everyone"),
    "unlock": Policy("staff", True, "manage_channels", "restore send_messages for @everyone"),
    "slowmode": Policy("staff", True, "manage_channels", "set channel slowmode"),
    "add_role": Policy("staff", True, "manage_roles", "grant a role (role + member hierarchy)"),
    "remove_role": Policy("staff", True, "manage_roles", "revoke a role (role + member hierarchy)"),
    "setup": Policy("staff", False, "manage_guild", "guided server configuration"),
    "knowledge": Policy("staff", False, "manage_guild", "server knowledge base entries"),
    "custom_action": Policy("staff", False, "administrator", "arm a stored action phrase"),
    "catchup": Policy("member", True, None, "summarise what the member missed"),
    "fix": Policy(
        "member", False, None,
        "re-upload a linked post's media, bounded by the shared download semaphore",
    ),

    # --- owner-only -------------------------------------------------------
    "sync": Policy("owner", False, "administrator", "push the global command tree"),
    "cleanup": Policy("owner", False, "manage_guild", "delete temp files and vacuum the database"),
    "diagnostics": Policy("owner", False, "administrator", "runtime and provider diagnostics"),
    "budget": Policy("owner", True, "administrator", "daily USD spend and the stop line"),
    "mood": Policy("owner", False, None, "read the persona mood state"),
    "silence": Policy("owner", True, None, "mute the bot in a channel"),
    "autonomy": Policy("owner", True, None, "toggle the autonomous engine"),
    "sovereign": Policy("owner", False, "administrator", "owner-only sovereign tools"),
    "harem": Policy("owner", False, "administrator", "harem roster management"),
    "dm_send": Policy("owner", False, "administrator", "send a DM as the bot"),
    "dm_logs": Policy("owner", False, "administrator", "read the DM mirror"),
    "whisper": Policy("owner", False, "administrator", "private message to one member"),
    "admin_note": Policy(
        "staff", False, None,
        "admin-context note: requires an admin role inside an admin channel",
    ),
    "angel": Policy("owner", False, None, "owner greeting/diagnostics shortcut"),

    # --- member-facing ----------------------------------------------------
    "gif": Policy("member", False, None, "reaction GIF, romantic actions harem-only"),
    "lore": Policy("member", False, None, "server lore lookup"),
    "rank": Policy("member", True, None, "own XP card"),
    "leaderboard": Policy("member", True, None, "guild XP leaderboard"),
    "rep": Policy("member", True, None, "give reputation to another member"),
    "memory": Policy("member", False, None, "pin or read own memory facts"),
    "clear_history": Policy("member", False, None, "erase own rolling chat window"),
    "data": Policy("member", False, None, "view or delete own stored data"),
    "rules": Policy("member", True, None, "answer from the indexed server rules"),
    "chat": Policy("member", False, None, "one-shot model conversation"),
    "translate": Policy("member", False, None, "translate text"),
    "imagine": Policy("member", False, None, "generate an image"),
    "summarize_channel": Policy("member", True, None, "summarise a channel the caller can read"),
    "afk": Policy("member", True, None, "set or clear own AFK state"),
    "serverinfo": Policy("member", True, None, "guild metadata"),
    "userinfo": Policy("member", False, None, "member metadata"),
    "avatar": Policy("member", False, None, "member avatar"),
    "poll": Policy("member", True, None, "start a reaction poll"),
    "ping": Policy("member", False, None, "gateway latency"),
    "help": Policy("member", False, None, "command index"),

    # --- context menus ----------------------------------------------------
    "تلخيص الرسالة": Policy("member", False, None, "summarise one message"),
    "ترجمة وتحليل": Policy("member", False, None, "translate and analyse one message"),
    "اقتراح رد ومهام": Policy("member", False, None, "draft a reply or task list"),

    # --- lazy music extension (loaded in setup_hook) ----------------------
    "play": Policy("member", True, None, "queue a track, never hijack another channel"),
    "skip": Policy("member", True, None, "advance the queue"),
    "queue": Policy("member", True, None, "show the queue"),
    "playlist": Policy("member", True, None, "load a saved playlist"),
}


def policy_for(name: str) -> Optional[Policy]:
    return POLICIES.get(name)


def missing_policies(command_names) -> list:
    """Names present in the tree but absent from the inventory."""
    return sorted(n for n in command_names if n not in POLICIES)


def stale_policies(command_names) -> list:
    """Inventory entries that no longer correspond to a registered command."""
    live = set(command_names)
    return sorted(n for n in POLICIES if n not in live)
