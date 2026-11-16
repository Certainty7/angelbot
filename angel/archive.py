"""Ask the server's own history: "متى تكلمنا عن السوني؟"

The archive (server_messages, 170k+ lines) is the only asset here nobody can copy. This module turns
a recall-shaped question into a few real lines with dates and speakers, so the reply can cite the room
instead of guessing.

Two guards live here, not in the prompt: the question must look like a recall, and the rows returned
must be in the guild and channel the asker is allowed to read (the archive holds tickets and staff
rooms too).
"""
import re
from typing import Optional, Set

import discord

from .registry import get_bot

# only these phrasings cost a lookup; ordinary chat must not touch the archive
_RECALL = re.compile(
    r"(متى|وقت|اذكر|تذكر|تتذكرين|قلنا|تكلمنا|سالفة|سالفتنا|قبل|وش صار|شصار|تاريخ)\s*(عن|في|على|بخصوص)?",
    re.IGNORECASE,
)


def is_recall(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 8:
        return False
    return bool(_RECALL.search(t)) and any(w in t for w in ("قلنا", "تكلمنا", "تكلمن", "سالفة", "متى", "تذكر", "قبل"))


def _readable_channels(guild, member) -> Optional[Set[int]]:
    """Channels this member can read, or None when we cannot tell (then no lookup)."""
    if guild is None or not isinstance(member, discord.Member):
        return None
    out: Set[int] = set()
    for channel in guild.text_channels:
        try:
            if channel.permissions_for(member).read_messages:
                out.add(channel.id)
        except Exception:
            continue
    return out


async def lookup(prompt: str, guild=None, member=None, limit: int = 6) -> Optional[str]:
    bot = get_bot()
    if bot is None or not is_recall(prompt):
        return None
    # A DM has no guild: the archive is server content and must not be quoted to a stranger.
    if guild is None:
        return None
    allowed = _readable_channels(guild, member)
    if not allowed:
        return None
    words = [w for w in re.findall(r"[\w\u0621-\u064A]{3,}", prompt.lower())
             if w not in {"انجل", "انج", "متى", "وش", "قلنا", "تكلمنا", "عن", "في", "قبل", "تذكر", "تتذكرين"}]
    if not words:
        return None
    rows = await bot.db.search_archive(
        words, limit, guild_id=getattr(guild, "id", None), allowed_channels=allowed
    )
    if not rows:
        return None
    lines = []
    for r in rows:
        when = (r.get("created_at") or "")[:10]
        who = (r.get("display_name") or "عضو")[:20]
        text = (r.get("content") or "").replace("\n", " ")[:160]
        lines.append(f"- {when} · {who}: {text}")
    return "\n".join(lines)
