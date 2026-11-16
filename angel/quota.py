"""Gemini quota, latency and rate-limit tracker."""

import asyncio
import discord
import math
import time
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone
from collections import defaultdict, deque
from .config import GLOBAL_MAX_RPM, HAREM_COOLDOWN_SECONDS, HAREM_DAILY_LIMIT, MORTAL_COOLDOWN_SECONDS, MORTAL_DAILY_LIMIT, is_mistress

# 2. Smart Quota & Diagnostics Tracker
class QuotaGuard:

  def __init__(self):
    self.user_last_call: Dict[int, float] = {}
    self.user_daily_counts: Dict[int, int] = defaultdict(int)
    self.current_day: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    self.recent_api_timestamps: deque = deque(maxlen=100)
    self.total_api_calls: int = 0
    self.model_usage_stats: Dict[str, int] = defaultdict(int)
    self.model_latency_ms: Dict[str, float] = {}
    self.last_scheduler_error: Optional[str] = None
    self.last_api_error: Optional[str] = None
    self._rpm_lock = asyncio.Lock()

  def _roll_day_if_needed(self):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != self.current_day:
      self.current_day = today
      self.user_daily_counts.clear()

  def check_user_allowed(
      self, user: discord.abc.User, is_harem: bool = False, dry_run: bool = False
  ) -> Tuple[bool, Optional[str]]:
    self._roll_day_if_needed()
    if is_mistress(user):
      return True, None

    now = time.monotonic()
    last = self.user_last_call.get(user.id, 0.0)
    elapsed = now - last

    cooldown = HAREM_COOLDOWN_SECONDS if is_harem else MORTAL_COOLDOWN_SECONDS
    daily_cap = HAREM_DAILY_LIMIT if is_harem else MORTAL_DAILY_LIMIT

    if elapsed < cooldown:
      wait_s = math.ceil(cooldown - elapsed)
      if is_harem:
        return False, f"💖 تمهلي **{wait_s} ثانية** فقط يا جميلة."
      return False, f"⚡ انتظر **{wait_s} ثانية** قبل إرسال رسالة أخرى."

    if self.user_daily_counts[user.id] >= daily_cap:
      return False, "⚡ انتهت حصتك اليومية من الرسائل."

    if not dry_run:
      self.user_last_call[user.id] = now
      self.user_daily_counts[user.id] += 1
    return True, None

  async def pace_global_rpm(self, high_priority: bool):
    async with self._rpm_lock:
      while True:
        now = time.monotonic()
        while self.recent_api_timestamps and now - self.recent_api_timestamps[0] > 60.0:
          self.recent_api_timestamps.popleft()

        if len(self.recent_api_timestamps) < GLOBAL_MAX_RPM:
          break
        if high_priority and len(self.recent_api_timestamps) < GLOBAL_MAX_RPM + 4:
          break
        wait_time = max(0.25, 60.0 - (now - self.recent_api_timestamps[0]) + 0.1)
        await asyncio.sleep(min(wait_time, 4.0))

      self.recent_api_timestamps.append(time.monotonic())
      self.total_api_calls += 1
