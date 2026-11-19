"""The Discord client.

Owns the caches, the conversation pipeline and the background tasks. It is a plain `commands.Bot`
subclass that imports what it needs from the package, so bot.py only constructs it and wires the
cogs.
"""
import asyncio
import os
import random
import time
from collections import Counter, deque
from .cache import BoundedDefaultDict, BoundedDict, WeakLockMap, channel_buffer, cooldown_map
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import discord
from discord import app_commands
from discord.ext import commands, tasks

from angel import archive, autonomy, evolution, guard, memory, persona_notes, sendqueue
from angel.brain import AIServiceError, AngelBrainService
from angel.config import (
    KEEP_RECENT_MESSAGES,
    MISTRESS_INT_ID,
    SESSION_TIMEOUT_HOURS,
    SUMMARIZE_THRESHOLD,
    _safe_gc_collect,
    is_mistress,
    logger,
)
from angel.database import BotDatabase
from angel.images import parse_ai_special_tags
from angel.media import perform_storage_cleanup
from angel.net import close_shared_http_session
from angel.nl_router import execute_ai_inferred_action
from angel.output_filter import filter_outgoing
from angel.persona import humanize as persona_humanize, humanize_reply, reply_directives, detect_reply_rhythm, trim_emoji
from angel.quota import QuotaGuard
from angel.ui import GiveawayJoinView, TicketCloseView, TicketPanelView

class AngelDiscordBot(commands.Bot):

  def __init__(self, db: BotDatabase, ai: AngelBrainService, quota: QuotaGuard):
    intents = discord.Intents.default()
    intents.message_content = True
    # Enable Server Members Intent automatically if ENABLE_MEMBERS_INTENT=1 in .env (F-04)
    intents.members = (os.getenv("ENABLE_MEMBERS_INTENT", "0").strip().lower() in ("1", "true", "yes"))
    super().__init__(
        command_prefix="!",
        intents=intents,
        help_command=None,
        allowed_mentions=discord.AllowedMentions(
            everyone=False, roles=False, users=True, replied_user=False
        ),
        allowed_installs=app_commands.AppInstallationType(guild=True, user=True),
        allowed_contexts=app_commands.AppCommandContext(
            guild=True, dm_channel=True, private_channel=True
        ),
    )
    self.db = db
    self.ai = ai
    self.quota = quota
    self.user_locks = WeakLockMap()
    self.start_time = datetime.now(timezone.utc)
    self._InitialSyncDone = False

    self.snipe_cache: Dict[int, Dict[str, Any]] = BoundedDict(2000)
    self.editsnipe_cache: Dict[int, Dict[str, Any]] = BoundedDict(2000)
    self.xp_cooldowns: Dict[Tuple[int, int], float] = cooldown_map()
    self.rep_cooldowns: Dict[int, float] = cooldown_map()
    self.auto_triggers_cache: Dict[int, Dict[str, str]] = BoundedDict(2000)
    self.action_triggers_cache: Dict[int, Dict[str, Dict[str, Any]]] = BoundedDict(2000)
    self.harem_cache: Dict[int, Dict[str, Any]] = BoundedDict(10000)
    self.stickies_cache: Dict[int, Dict[str, Any]] = BoundedDict(5000)
    self.sticky_cooldowns: Dict[int, float] = cooldown_map()
    self.guard_modes_cache: Dict[int, str] = BoundedDict(5000)
    self.afk_cache: Dict[int, Tuple[str, str]] = BoundedDict(10000)
    self.modlog_cache: Dict[int, Optional[int]] = BoundedDict(5000)
    self.autorole_cache: Dict[int, Optional[int]] = BoundedDict(5000)
    self.spam_tracker: Dict[Tuple[int, int], deque] = BoundedDefaultDict(lambda: deque(maxlen=8), maxsize=10000)
    self.channel_activity_counter: Dict[int, Counter] = BoundedDefaultDict(Counter, maxsize=5000)
    self.pending_step: Dict[Any, Any] = BoundedDict(2000)
    self.last_target_channel: Dict[int, int] = BoundedDict(5000)
    self.last_social_target: Dict[int, int] = BoundedDict(5000)
    self.recent_channel_msgs: Dict[int, deque] = channel_buffer(12)
    self.active_chat_window: Dict[Tuple[int, int], float] = cooldown_map()
    self.social_url_cooldowns: Dict[int, float] = cooldown_map()
    self._bg_tasks: Set[asyncio.Task] = set()
    # Interaction state: silence map, recent speakers (for autonomy), audit timers
    self.silent_cache: Dict[int, set] = BoundedDict(5000)
    self.autonomy_guilds: set = set()
    self.recent_speakers: Dict[int, deque] = channel_buffer(60)
    # url hash -> monotonic timestamp, so a re-posted link is not downloaded twice
    self.recent_social_links: Dict[str, float] = BoundedDict(512)
    self.angel_last_spoke: Dict[int, float] = BoundedDict(5000)
    self.guild_dialects: Dict[int, str] = BoundedDict(5000)
    self.social_fixer_cache: Dict[int, bool] = BoundedDict(5000)
    # Merged from the Malak build: evolving mood/settings, listening mode, send queue
    self.mood: float = 0.55
    self.settings: Dict[str, float] = {"verbosity": 0.4, "emoji_rate": 0.05, "typo_rate": 0.01, "curiosity": 0.55}
    self.listening: bool = False
    self.sender: Optional[sendqueue.Sender] = None
    # Destructive [EXEC] commands wait here for an explicit "تأكيد" from the same user.
    self.pending_confirm: Dict[Any, Dict[str, Any]] = BoundedDict(2000)
    # /summarize_channel and the natural-language twin share one per-user cooldown.
    self.summarize_cooldowns: Dict[int, float] = cooldown_map()

  async def setup_hook(self):
    await self.db.initialize()
    self.harem_cache.clear()
    self.harem_cache.update(await self.db.get_all_harem_members() or {})
    self.stickies_cache.clear()
    self.stickies_cache.update(await self.db.get_all_stickies() or {})
    self.afk_cache.clear()
    self.afk_cache.update(await self.db.get_all_afk() or {})
    g_settings = await self.db.get_all_guild_settings_map()
    for gid, srow in g_settings.items():
      self.modlog_cache[gid] = srow.get("modlog_channel_id")
      self.autorole_cache[gid] = srow.get("autorole_id")
      self.guard_modes_cache[gid] = srow.get("guard_mode") or "off"
      self.guild_dialects[gid] = srow.get("dialect") or "gulf"
      _fixer = srow.get("social_fixer_enabled")
      self.social_fixer_cache[gid] = True if _fixer is None else bool(_fixer)
    self.add_view(TicketPanelView(self))
    self.add_view(TicketCloseView(self))
    self.add_view(GiveawayJoinView(self.db))
    # Music is its own cog with its own failure mode, so it can never stop the bot.
    if os.environ.get("MUSIC_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}:
      try:
        await self.load_extension("cogs.music")
      except Exception as music_err:  # noqa: BLE001 - a broken voice stack must not block startup
        logger.warning(f"Music cog disabled: {type(music_err).__name__}: {music_err}")
    self.background_scheduler.start()
    self.event_loop_lag_monitor.start()
    try:
      self.silent_cache = await self.db.get_silent_map()
      await self._load_autonomy_guilds()
      self._autonomy_task = asyncio.create_task(autonomy.engine.run_forever())
    except Exception as silence_err:
      logger.warning(f"Interaction state init notice: {silence_err}")
    try:
      state = await evolution.load(self.db)
      self.mood = float(state["mood"])
      self.settings = dict(state["settings"])
      self.ai.db = self.db
      self.sender = sendqueue.Sender(self, capacity=5, rate_per_sec=0.6)
      self.sender.start()
      logger.info(f"Interaction engine ready: mood={self.mood:.2f} settings={self.settings}")
    except Exception as merge_err:
      logger.warning(f"Interaction engine init notice: {merge_err}")

  async def close(self):
    try:
      self.background_scheduler.cancel()
    except Exception:
      pass
    try:
      self.event_loop_lag_monitor.cancel()
    except Exception:
      pass
    try:
      task = getattr(self, "_autonomy_task", None)
      if task is not None and not task.done():
        task.cancel()
    except Exception:
      pass
    pending = [t for t in self._bg_tasks if not t.done()]
    for task in pending:
      task.cancel()
    try:
      if self.sender is not None:
        await self.sender.stop()
    except Exception:
      pass
    try:
      if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
      try:
        await close_shared_http_session()
      finally:
        try:
          await self.db.close()
        finally:
          await super().close()

  def get_harem_title(self, user_id: int) -> Optional[str]:
    info = self.harem_cache.get(user_id)
    return info.get("custom_title") if info else None

  async def _load_autonomy_guilds(self) -> None:
    """Load autonomy flags from SQLite; `self.guilds` is empty inside setup_hook()."""
    flags = await self.db.get_flags_with_prefix("autonomy:")
    enabled = set()
    for key, value in flags.items():
      guild_id = key.split(":", 1)[1]
      if guild_id.isdigit() and value != "0":
        enabled.add(int(guild_id))
    # Guilds with no explicit flag keep the historical default: autonomy on.
    for guild in self.guilds:
      if f"autonomy:{guild.id}" not in flags:
        enabled.add(guild.id)
    self.autonomy_guilds = enabled

  @tasks.loop(seconds=45)
  async def background_scheduler(self):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    try:
      due_giveaways = await self.db.get_due_giveaways(now_str)
      for gw in due_giveaways:
        channel = self.get_channel(gw["channel_id"])
        if not channel:
          try:
            channel = await self.fetch_channel(gw["channel_id"])
          except Exception:
            channel = None
        if not isinstance(channel, discord.abc.Messageable):
          await self.db.mark_giveaway_ended(gw["message_id"])
          continue
        raw_parts = [x for x in (gw["participants"] or "").split(",") if x.strip()]
        try:
          if not raw_parts:
            await channel.send(f"🎉 انتهى السحب على **{gw['prize']}** دون مشاركين.")
          else:
            winners = random.sample(raw_parts, min(gw["winners_count"], len(raw_parts)))
            winners_mentions = ", ".join(f"<@{w}>" for w in winners)
            embed = discord.Embed(
                title="🎊 نتائج السحب",
                description=f"🎁 **الجائزة:** {gw['prize']}\n👑 **الفائزون:** {winners_mentions}",
                color=0xD4AF37,
            )
            await channel.send(content=f"🎉 مبروك {winners_mentions}!", embed=embed)
        except Exception:
          pass
        finally:
          # Mark it closed even when the send failed: a closed channel must not retry
          # the same giveaway every 45 seconds forever.
          await self.db.mark_giveaway_ended(gw["message_id"])
    except Exception as exc:
      self.quota.last_scheduler_error = str(exc)[:120]

    # Periodic RAM maintenance: prune stale cooldowns and locks (voice engine removed).
    try:
      now_mono = time.monotonic()
      # Prune stale cooldowns and locks to prevent memory creep over days of uptime
      if len(self.xp_cooldowns) > 2000:
        cutoff = now_mono - 120.0
        fresh_xp = cooldown_map()
        for key, stamp in self.xp_cooldowns.items():
          if stamp > cutoff:
            fresh_xp[key] = stamp
        self.xp_cooldowns = fresh_xp
      if len(self.rep_cooldowns) > 1000:
        cutoff_rep = now_mono - 3600.0
        fresh_rep = cooldown_map()
        for key, stamp in self.rep_cooldowns.items():
          if stamp > cutoff_rep:
            fresh_rep[key] = stamp
        self.rep_cooldowns = fresh_rep
      if len(self.user_locks) > 500:
        unlocked = [uid for uid, lk in self.user_locks.items() if not lk.locked()]
        for uid in unlocked[:400]:
          self.user_locks.pop(uid, None)
      if len(self.spam_tracker) > 1000:
        self.spam_tracker.clear()
      # Automatic periodic storage & temp garbage cleanup every 30 minutes (deep every 6 hours)
      last_clean = getattr(self, "_last_auto_cleanup_at", 0.0)
      if now_mono - last_clean >= 1800.0:
        is_deep = (now_mono - getattr(self, "_last_deep_cleanup_at", 0.0)) >= 21600.0
        self._last_auto_cleanup_at = now_mono
        if is_deep:
          self._last_deep_cleanup_at = now_mono
        await perform_storage_cleanup(deep=is_deep)
    except Exception:
      pass

  @background_scheduler.before_loop
  async def before_scheduler(self):
    await self.wait_until_ready()

  @tasks.loop(seconds=30.0)
  async def event_loop_lag_monitor(self):
    """Warn when the asyncio event loop stalls (GIL/CPU contention) instead of silently lagging replies."""
    t0 = time.perf_counter()
    await asyncio.sleep(0.5)
    lag_ms = (time.perf_counter() - t0 - 0.5) * 1000.0
    if lag_ms > 65.0:
      logger.warning(f"EVENT-LOOP-LAG {lag_ms:.1f}ms (CPU contention detected)")

  @event_loop_lag_monitor.before_loop
  async def before_lag_monitor(self):
    await self.wait_until_ready()

  async def sync_all_commands_cleanly(self, clear_guild_dups: bool = False):
    try:
      for guild in self.guilds:
        self.auto_triggers_cache[guild.id] = await self.db.get_auto_triggers(guild.id)
        self.action_triggers_cache[guild.id] = await self.db.get_action_triggers(guild.id)
        self.guard_modes_cache[guild.id] = await self.db.get_guard_mode(guild.id)
        if clear_guild_dups:
          self.tree.clear_commands(guild=guild)
          await self.tree.sync(guild=guild)

      await self.tree.sync()
      _safe_gc_collect()
      logger.info("Commands synced cleanly.")
    except Exception as sync_err:
      logger.warning(f"Sync notice: {sync_err}")

  async def on_ready(self):
    if not self._InitialSyncDone:
      self._InitialSyncDone = True
      await self._load_autonomy_guilds()
      await self.sync_all_commands_cleanly()

    await self.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="Certainty 🪽",
        )
    )
    logger.info(
        "Intents: members=%s message_content=%s presences=%s",
        self.intents.members, self.intents.message_content, self.intents.presences,
    )
    logger.info(f"Angel is online as: {self.user} (ID: {self.user.id})")

  async def on_member_join(self, member: discord.Member):
    if member.bot:
      return
    if member.guild.id not in self.autorole_cache:
      self.autorole_cache[member.guild.id] = await self.db.get_autorole(member.guild.id)
    role_id = self.autorole_cache.get(member.guild.id)
    if role_id:
      role = member.guild.get_role(role_id)
      if role and role < member.guild.me.top_role and member.guild.me.guild_permissions.manage_roles:
        try:
          await member.add_roles(role, reason="Auto-Role on Join")
        except (discord.Forbidden, discord.HTTPException) as exc:
          logger.warning("autorole failed guild=%s: %s: %s", member.guild.id, type(exc).__name__, exc)
    await self.send_modlog(
        member.guild,
        "📥 انضمام عضو جديد",
        f"**العضو:** {member.mention} (`{member.id}`)\n**تاريخ الحساب:** {discord.utils.format_dt(member.created_at, style='R')}",
    )

  async def on_guild_join(self, guild: discord.Guild):
    self.auto_triggers_cache[guild.id] = await self.db.get_auto_triggers(guild.id)
    self.action_triggers_cache[guild.id] = await self.db.get_action_triggers(guild.id)
    self.guard_modes_cache[guild.id] = await self.db.get_guard_mode(guild.id)
    try:
      mistress_user = await self.fetch_user(MISTRESS_INT_ID)
      embed = discord.Embed(
          title="🪽 إشعار: دخلتُ سيرفراً جديداً",
          description=(
              f"**السيرفر:** {guild.name}\n"
              f"**المعرف:** `{guild.id}`\n"
              f"**الأعضاء:** `{guild.member_count}`"
          ),
          color=0x2B2D31,
          timestamp=datetime.now(timezone.utc),
      )
      await mistress_user.send(embed=embed)
    except Exception:
      pass

  async def forward_dm_to_mistress(self, message: discord.Message, angel_reply: str):
    att_urls = ", ".join(a.url for a in message.attachments) if message.attachments else ""
    await self.db.log_dm(
        sender_id=message.author.id,
        sender_name=f"{message.author} ({message.author.display_name})",
        content=message.content or "[مرفق]",
        attachments=att_urls,
        angel_reply=angel_reply,
    )
    if is_mistress(message.author):
      return
    try:
      mistress_user = await self.fetch_user(MISTRESS_INT_ID)
      embed = discord.Embed(
          title="🕵️‍♀️ رسالة واردة في الخاص",
          color=0x2B2D31,
          timestamp=datetime.now(timezone.utc),
      )
      embed.set_author(
          name=f"{message.author.display_name} (@{message.author.name})",
          icon_url=message.author.display_avatar.url,
      )
      embed.add_field(name="المرسل", value=f"{message.author.mention} (`{message.author.id}`)", inline=False)
      embed.add_field(name="الرسالة", value=(message.content[:1020] if message.content else "*[مرفق]*"), inline=False)
      if att_urls:
        embed.add_field(name="المرفقات", value=att_urls[:1020], inline=False)
        if message.attachments[0].content_type and message.attachments[0].content_type.startswith("image/"):
          embed.set_image(url=message.attachments[0].url)
      embed.add_field(name="الرد", value=angel_reply[:1020] if angel_reply else "—", inline=False)
      embed.set_footer(text=f"للرد: /dm_send user_id:{message.author.id}")
      await mistress_user.send(embed=embed)
    except Exception:
      pass

  async def send_modlog(
      self, guild: Optional[discord.Guild], title: str, description: str, color: int = 0x2B2D31
  ):
    if not guild:
      return
    if guild.id not in self.modlog_cache:
      self.modlog_cache[guild.id] = await self.db.get_modlog_channel(guild.id)
    channel_id = self.modlog_cache.get(guild.id)
    if not channel_id:
      return
    channel = guild.get_channel(channel_id)
    if not channel:
      try:
        channel = await guild.fetch_channel(channel_id)
      except Exception:
        channel = None
    if isinstance(channel, discord.abc.Messageable):
      embed = discord.Embed(
          title=title[:256], description=description[:4096], color=color,
          timestamp=datetime.now(timezone.utc),
      )
      try:
        await channel.send(embed=embed)
      except Exception:
        pass

  async def handle_conversation(
      self,
      user: discord.abc.User,
      prompt: str,
      media_items: Optional[List[Tuple[str, str]]] = None,
      ambient_context: Optional[str] = None,
      message_Context: Optional[discord.Message] = None,
      cmd: str = "message",
  ) -> Tuple[str, Optional[bytes], Optional[str], Optional[bytes], bool]:
    harem_title = self.get_harem_title(user.id)
    allowed, deny_reason = self.quota.check_user_allowed(user, is_harem=(harem_title is not None))
    if not allowed:
      raise AIServiceError(deny_reason)

    async with self.user_locks[user.id]:
      session_expired = await self.db.check_and_expire_old_session(user.id, SESSION_TIMEOUT_HOURS)
      summary, messages = await self.db.get_context_data(user.id)
      prefs = await self.db.get_user_prefs(user.id)

      # Archive recall is scoped to this guild and to the channels this member can read;
      # a DM gets no archive at all (see archive.lookup).
      knowledge_snippets = await archive.lookup(
          prompt,
          guild=getattr(message_Context, "guild", None),
          member=getattr(message_Context, "author", None),
      )
      if knowledge_snippets:
        knowledge_snippets = "【من أرشيف السيرفر — رسائل حقيقية بتواريخها】\n" + knowledge_snippets
      if message_Context and message_Context.guild and prompt:
        _kb = await self.db.search_knowledge_for_prompt(message_Context.guild.id, prompt)
        knowledge_snippets = ((knowledge_snippets or "") + "\n" + _kb).strip() if _kb else knowledge_snippets

      profile_facts = await memory.recall(user.id, prompt) if prompt else []
      if profile_facts:
        logger.info("ai-guard reason=recall-hit")
      allow_romantic = guard.romantic_allowed(user)

      raw_reply = await self.ai.generate_angel_reply(
          user=user,
          summary=summary,
          recent_messages=messages,
          user_prompt=prompt,
          media_items=media_items,
          harem_title=harem_title,
          ambient_context=ambient_context,
          pinned_prefs=prefs.get("pinned_facts") or None,
          style_mode=prefs.get("style_mode", "realistic"),
          knowledge_snippets=knowledge_snippets,
          profile_facts=profile_facts,
          cmd=cmd,
          culture=await persona_notes.current(getattr(getattr(user, "guild", None), "id", None)),
          rhythm_hint=reply_directives(
              detect_reply_rhythm(prompt),
              self.guild_dialects.get(
                  getattr(getattr(message_Context, "guild", None), "id", 0)
                  or getattr(getattr(user, "guild", None), "id", 0)
              ),
          ),
      )

      clean_reply, gif_action, image_prompt, exec_cmds = parse_ai_special_tags(
          raw_reply, prompt,
          is_female_tier=(is_mistress(user) or harem_title is not None),
          allow_romantic=allow_romantic,
      )
      if not clean_reply:
        clean_reply = "تم." if is_mistress(user) else "حسناً."
      clean_reply = humanize_reply(clean_reply)
      clean_reply = trim_emoji(persona_humanize(clean_reply, self.settings), 1)

      action_status = "none"
      if exec_cmds and message_Context and message_Context.guild:
        statuses = []
        for cmd_str in exec_cmds:
          statuses.append(await execute_ai_inferred_action(self, message_Context, cmd_str))
        if "queued" in statuses:
          action_status = "queued"
        elif "failed" in statuses:
          action_status = "failed"
        elif "executed" in statuses:
          action_status = "executed"
        elif "blocked" in statuses:
          action_status = "blocked"
      # The model's prose is generated before the action gate runs; never let it claim an
      # execution that was queued, blocked or failed. Also strips cheap unsafe classes.
      clean_reply = filter_outgoing(clean_reply, action_status=action_status)

      if not prefs.get("opt_out"):
        await self.db.add_exchange(user.id, prompt or "[صورة]", clean_reply)
        if message_Context and message_Context.guild:
          self.angel_last_spoke[message_Context.channel.id] = time.monotonic()

      is_female_tier = is_mistress(user) or harem_title is not None
      gif_bytes: Optional[bytes] = None
      gif_url: Optional[str] = None
      if gif_action:
        gif_bytes, gif_url = await self.ai.fetch_anime_gif_data(
            gif_action, for_female_pair=is_female_tier, allow_romantic=allow_romantic
        )

      gen_image_bytes: Optional[bytes] = None
      if image_prompt:
        try:
          gen_image_bytes, _ = await self.ai.generate_image_bytes(image_prompt)
        except Exception as img_err:
          logger.warning(f"Image generation error: {img_err}")

      # Non-blocking background summarization with strong task reference so GC never drops it
      if len(messages) + 2 >= SUMMARIZE_THRESHOLD:
        bg_t = asyncio.create_task(self._background_summarize_user(user.id))
        self._bg_tasks.add(bg_t)
        bg_t.add_done_callback(self._bg_tasks.discard)

      return clean_reply, gif_bytes, gif_url, gen_image_bytes, session_expired

  async def _background_summarize_user(self, user_id: int):
    try:
      async with self.user_locks[user_id]:
        summary, updated_messages = await self.db.get_context_data(user_id)
        if len(updated_messages) >= SUMMARIZE_THRESHOLD:
          to_summarize = updated_messages[:-KEEP_RECENT_MESSAGES]
          if to_summarize:
            new_summary = await self.ai.summarize_messages(summary, to_summarize)
            max_id = to_summarize[-1]["id"]
            await self.db.apply_summary_and_prune(user_id, new_summary, max_id)
    except Exception:
      pass
