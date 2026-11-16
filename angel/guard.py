"""Interaction guardrails: harem-only romance, silence map, in-character refusals.

`bot` is late-bound by bot.py after the client is constructed.
"""
import random
from typing import Any, Optional

from .config import is_mistress, logger
from .registry import get_bot


_REFUSALS = (
    "هالشي مو لك.",
    "ما عندي لك من هالقبيل.",
    "لا، هذي ما تنفع معك.",
    "اطلب شي ثاني، هذا مو مكانه.",
)


def harem_title(user) -> Optional[str]:
  """Title if the user is in the harem cache, else None."""
  try:
    if get_bot() is None:
      return None
    return get_bot().get_harem_title(getattr(user, "id", 0))
  except Exception:
    return None


def romantic_allowed(user) -> bool:
  """Romantic reactions/GIFs are mistress + harem only (hard rule)."""
  return bool(is_mistress(user) or harem_title(user) is not None)


def refusal_line() -> str:
  logger.info("ai-guard reason=harem-gate")
  return random.choice(_REFUSALS)


def is_silent(guild_id: Optional[int], channel_id: Optional[int]) -> bool:
  """True when the owner muted Angel in this channel or across the guild."""
  if not guild_id or get_bot() is None:
    return False
  mapping = getattr(get_bot(), "silent_cache", {}) or {}
  silenced = mapping.get(guild_id) or set()
  return bool(0 in silenced or (channel_id is not None and channel_id in silenced))


def autonomy_enabled(guild_id: Optional[int]) -> bool:
  if get_bot() is None or not guild_id:
    return False
  return guild_id in getattr(get_bot(), "autonomy_guilds", set())


async def set_silent(guild_id: int, channel_id: int, silent: bool, added_by: int = 0) -> None:
  """Persist + update the in-memory cache atomically."""
  if get_bot() is None:
    return
  await get_bot().db.set_silent(guild_id, channel_id, silent, added_by)
  cache = getattr(get_bot(), "silent_cache", None)
  if cache is None:
    get_bot().silent_cache = cache = {}
  bucket = cache.setdefault(guild_id, set())
  if silent:
    bucket.add(channel_id)
  else:
    bucket.discard(channel_id)
  logger.info("silence %s guild=%s channel=%s", "ON" if silent else "OFF", guild_id, channel_id or "ALL")
