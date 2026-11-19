"""Interaction guardrails: harem-only romance, silence map, in-character refusals.

`bot` is late-bound by bot.py after the client is constructed.
"""
import random
import re
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
  except Exception as exc:
    logger.debug("harem cache lookup failed: %s: %s", type(exc).__name__, exc)
    return None


def romantic_allowed(user) -> bool:
  """Romantic reactions/GIFs are mistress + harem only (hard rule)."""
  return bool(is_mistress(user) or harem_title(user) is not None)


def refusal_line() -> str:
  logger.info("ai-guard reason=harem-gate")
  return random.choice(_REFUSALS)


# --- Arabizi / Arabic scam normaliser (zero AI cost) ---
_ARABIC_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0670\u0640]")
_ARABIZI_TRANS = str.maketrans({"3": "ع", "7": "ح", "5": "خ", "2": "أ", "8": "ق", "9": "ص"})
_SCAM_PATTERNS = (
    re.compile(r"(?:نيترو|nitro).{0,24}(?:مجان|free|هدي|gift|هدية)", re.I),
    re.compile(r"(?:اربح|ربح|اكسب).{0,24}(?:دولار|رصيد|شحن|usdt)", re.I),
    re.compile(r"(?:steam|discord|نيت?رو).{0,20}(?:free|gift|airdrop|مجان).{0,40}https?://", re.I),
)


def normalize_arabic_and_arabizi(text: str) -> str:
  """Fold Arabic variants and common Arabizi digits for matching; leaves URLs/numbers alone."""
  folded = _ARABIC_DIACRITICS_RE.sub("", text or "")
  for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه")):
    folded = folded.replace(src, dst)
  tokens = []
  for token in folded.split():
    if token.startswith(("http://", "https://")) or token.isdigit():
      tokens.append(token)
    else:
      tokens.append(token.translate(_ARABIZI_TRANS))
  return " ".join(tokens)


def is_suspicious_arabic_scam(text: str) -> bool:
  """Fast heuristic for Arabic/Arabizi Nitro & phishing spam."""
  norm = normalize_arabic_and_arabizi(text)
  return any(pattern.search(norm) for pattern in _SCAM_PATTERNS)


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
