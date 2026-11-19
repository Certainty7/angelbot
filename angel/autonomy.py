"""Autonomous social engine: Angel starts conversations on her own.

Every tick (default 90s) it looks at channels where people actually talked
recently, picks one member (weighted by recency, never repeated too soon),
builds a short natural opener from that member's memory profile + the last
messages, and posts it with a mention. Hard limits keep it human, not spammy.
"""
import asyncio
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from . import evolution, guard, memory, scoring
from .config import logger
from .persona import _oman_hour_hint
from .registry import get_bot


QUIET_START = int(os.getenv("AUTONOMY_QUIET_START", "2"))       # owner's timezone (UTC+4)
QUIET_END = int(os.getenv("AUTONOMY_QUIET_END", "10"))          # owner's timezone (UTC+4)
MIN_GAP_CHANNEL = float(os.getenv("AUTONOMY_MIN_GAP_CHANNEL", "1200"))   # 20 min per channel
MIN_GAP_TARGET = float(os.getenv("AUTONOMY_MIN_GAP_TARGET", "21600"))    # 6 h per member
MAX_PER_HOUR = int(os.getenv("AUTONOMY_MAX_PER_HOUR", "4"))
MAX_PER_DAY = int(os.getenv("AUTONOMY_MAX_PER_DAY", "30"))
ACTIVITY_WINDOW = float(os.getenv("AUTONOMY_ACTIVITY_WINDOW", "2700"))   # 45 min
MIN_SPEAKERS = int(os.getenv("AUTONOMY_MIN_SPEAKERS", "1"))
TICK_SECONDS = float(os.getenv("AUTONOMY_TICK_SECONDS", "90"))

TOPIC_WORDS = ("شغل", "دراسة", "جامعة", "لعبة", "مباراة", "سفر", "أكل", "مشروع", "مشكلة", "امتحان")
PATTERN_HINTS = {
    "text": "علّقي على آخر رسالة بجملة قصيرة طبيعية.",
    "new_topic": "ابدئي سالفة جديدة قصيرة مرتبطة بشي في الرسائل.",
    "followup": "ارجعي لسالفة سابقة في الرسائل وكملّي عليها بجملة.",
    "media": "علّقي على الوسائط أو الرابط في آخر رسالة بجملة قصيرة.",
}


def _oman_now() -> datetime:
  return datetime.now(timezone.utc) + timedelta(hours=4)


class AutonomyEngine:
  """Schedules and writes Angel's self-initiated messages."""

  def __init__(self):
    self.last_channel: Dict[int, float] = {}
    self.last_target: Dict[int, float] = {}
    self.sent_times: List[float] = []
    self.daily_count = 0
    self.day = _oman_now().strftime("%Y-%m-%d")
    self._running = False
    self._tick_lock: Optional[asyncio.Lock] = None

  # ---------- limits ----------
  def _roll_day(self):
    today = _oman_now().strftime("%Y-%m-%d")
    if today != self.day:
      self.day = today
      self.daily_count = 0
      self.sent_times.clear()

  def in_quiet_hours(self) -> bool:
    hour = _oman_now().hour
    if QUIET_START <= QUIET_END:
      return QUIET_START <= hour < QUIET_END
    return hour >= QUIET_START or hour < QUIET_END

  def can_send(self) -> bool:
    self._roll_day()
    now = time.monotonic()
    self.sent_times = [t for t in self.sent_times if now - t < 3600]
    if len(self.sent_times) >= MAX_PER_HOUR:
      return False
    return self.daily_count < MAX_PER_DAY

  # ---------- selection ----------
  def _pick_target(self, speakers: List[dict], guild) -> Optional[dict]:
    now = time.monotonic()
    pool = []
    for sp in speakers:
      uid = int(sp.get("user_id") or 0)
      if not uid or sp.get("bot"):
        continue
      if now - float(sp.get("ts") or 0) > ACTIVITY_WINDOW:
        continue
      if now - self.last_target.get(uid, 0.0) < MIN_GAP_TARGET:
        continue
      pool.append(sp)
    if len(pool) < MIN_SPEAKERS:
      return None
    # Prefer whoever spoke most recently, with a little randomness.
    pool.sort(key=lambda s: float(s.get("ts") or 0), reverse=True)
    head = pool[: min(4, len(pool))]
    return random.choice(head)

  async def _allowed_target(self, user_id: int) -> bool:
    try:
      prefs = await get_bot().db.get_user_prefs(user_id)
      return not bool(prefs.get("opt_out"))
    except Exception:
      # Fail closed: a database hiccup must never expose an opted-out member.
      return False

  # ---------- main tick ----------
  async def tick(self) -> int:
    if self._tick_lock is None:
      self._tick_lock = asyncio.Lock()
    if self._tick_lock.locked():
      return 0
    async with self._tick_lock:
      return await self._tick_locked()

  async def _tick_locked(self) -> int:
    if get_bot() is None:
      return 0
    # Mood and behaviour settings drift once per local day, always inside hard ranges.
    try:
      _state = await evolution.maybe_daily_step(get_bot().db)
      if _state:
        get_bot().mood = float(_state["mood"])
        get_bot().settings = dict(_state["settings"])
    except Exception:
      pass
    if self.in_quiet_hours() or not self.can_send():
      return 0
    sent = 0
    now = time.monotonic()
    for guild in list(get_bot().guilds):
      if not guard.autonomy_enabled(guild.id):
        continue
      for channel_id, speakers in list(getattr(get_bot(), "recent_speakers", {}).items()):
        if sent or not self.can_send():
          break
        channel = get_bot().get_channel(channel_id)
        if channel is None or getattr(channel, "guild", None) is None or channel.guild.id != guild.id:
          continue
        if guard.is_silent(guild.id, channel_id):
          continue
        if now - self.last_channel.get(channel_id, 0.0) < MIN_GAP_CHANNEL:
          continue
        last_activity = max((float(s.get("ts") or 0) for s in speakers), default=0.0)
        if not last_activity or now - last_activity > ACTIVITY_WINDOW:
          continue
        if now - getattr(get_bot(), "angel_last_spoke", {}).get(channel_id, 0.0) < MIN_GAP_CHANNEL:
          continue

        target = self._pick_target(list(speakers), guild)
        if not target or not await self._allowed_target(int(target["user_id"])):
          continue

        # Probabilistic gate: P(reply) from activity / mention / topic / mood / recency.
        recent_items = [x for x in speakers if now - float(x.get("ts") or 0) <= ACTIVITY_WINDOW]
        topic_hits = sum(1 for kw in TOPIC_WORDS if kw in " ".join(str(x.get("text", "")) for x in recent_items[-3:]))
        signals = scoring.Signals(
            msgs_in_window=len(recent_items),
            window_seconds=ACTIVITY_WINDOW,
            mentioned=False,
            called_by_name=False,
            topic_hits=topic_hits,
            mood=float(getattr(get_bot(), "mood", 0.55)),
            seconds_since_last_reply=now - getattr(get_bot(), "angel_last_spoke", {}).get(channel_id, 0.0),
            has_media=bool(recent_items and ("http" in str(recent_items[-1].get("text", "")))),
        )
        p = scoring.reply_probability(signals)
        if random.random() > p:
          continue
        pattern = scoring.pick_pattern(
            p,
            has_media=signals.has_media,
            has_history=len(recent_items) > 3,
        )
        if pattern == "reaction":
          msg_id = recent_items[-1].get("msg_id") if recent_items else None
          try:
            if msg_id:
              await channel.get_partial_message(int(msg_id)).add_reaction(random.choice(["😂", "👀", "❤️", "🔥", "😅"]))
              self.last_channel[channel_id] = now
              self.sent_times.append(now)
              self.daily_count += 1
              sent += 1
              continue
          except Exception:
            pass  # fall through to a text reply

        uid = int(target["user_id"])
        name = str(target.get("name") or "").strip() or "عضو"
        recent_lines = list(get_bot().recent_channel_msgs.get(channel_id, []))
        try:
          facts = memory.format_facts(await memory.recall(uid, " ".join(recent_lines[-3:])))
          avoid = await get_bot().db.get_recent_ambient(guild.id, channel_id, 8)
        except Exception:
          facts, avoid = [], []

        text = await get_bot().ai.generate_ambient_message(
            display_name=name,
            recent_lines=recent_lines,
            facts=facts,
            avoid_lines=avoid,
            time_hint=_oman_hour_hint(),
            topic_hint=PATTERN_HINTS.get(pattern, ""),
        )
        if not text:
          continue

        try:
          await channel.send(f"<@{uid}> {text}", allowed_mentions=discord_allowed())
        except Exception as exc:
          logger.warning("autonomy send failed in %s: %s", channel_id, exc)
          continue

        self.last_channel[channel_id] = now
        self.last_target[uid] = now
        self.sent_times.append(now)
        self.daily_count += 1
        sent += 1
        try:
          get_bot().angel_last_spoke[channel_id] = now
          get_bot().recent_channel_msgs[channel_id].append(f"Angel: {text[:120]}")
          await get_bot().db.log_ambient(guild.id, channel_id, uid, text)
          await memory.touch(guild.id, uid, name, text)
        except Exception:
          pass
        logger.info("Autonomy: Angel opened a conversation with %s in #%s", name, getattr(channel, "name", channel_id))
    return sent

  async def run_forever(self):
    """Background loop started once in setup_hook."""
    if self._running:
      return
    self._running = True
    try:
      await get_bot().wait_until_ready()
      while not get_bot().is_closed():
        try:
          await self.tick()
        except asyncio.CancelledError:
          raise
        except Exception as exc:
          logger.warning("autonomy tick error: %s", exc)
        await asyncio.sleep(TICK_SECONDS)
    finally:
      self._running = False


def discord_allowed():
  """Mention only the targeted user, never @everyone/@here."""
  import discord

  return discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False)


engine = AutonomyEngine()
