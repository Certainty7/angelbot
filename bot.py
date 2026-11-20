"""Angel - Discord bot entry point.

Builds the client, registers the cogs and starts the gateway. The reusable parts live in the
`angel` package; this module wires them together.
"""

# Bootstrap first: angel.config resolves ffmpeg and loads .env at import time.
import angel.config  # noqa: F401
from angel.config import DB_PATH, DISCORD_TOKEN, GEMINI_API_KEY, MISTRESS_INT_ID, SOVEREIGN_TOOLS_ENABLED, TEXT_VISION_MODELS, is_mistress, is_server_staff, logger, safe_reply
from angel.interactions import _safe_interaction_reply
from angel.text import clean_social_url, plan_reply_delivery
from angel.client import AngelDiscordBot
from angel.net import close_shared_http_session, get_media_download_semaphore
from angel.persona import normalize_arabic_text
from angel.quota import QuotaGuard
from angel.database import BotDatabase
from angel.media import SOCIAL_URL_REGEX, chunk_slides, perform_storage_cleanup, process_social_media_url_multi
from angel.audio_source import ResolveError, parse_play_request
from angel.voice_engine import VoiceBusyError
from angel.images import extract_message_media
from angel.brain import AI_ERRORS, AngelBrainService
from angel import guard, memory
from angel.nl_router import try_execute_custom_action_trigger, try_execute_natural_command
import asyncio
import discord
import hashlib
import io
import os
import random
import re
import sys
import time
import uuid
from typing import List
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta, timezone

# --- Angel bot client ---


quota_guard = QuotaGuard()
db_manager = BotDatabase(DB_PATH)
angel_brain = AngelBrainService(
    api_key=GEMINI_API_KEY, models_list=TEXT_VISION_MODELS, quota_guard=quota_guard
)
bot = AngelDiscordBot(db=db_manager, ai=angel_brain, quota=quota_guard)

# --- Client injection -----------------------------------------------------
# One explicit registry replaces the per-module `bot = None` placeholders and the
# dynamic `globals()` lookups: every package module asks angel.registry.get_bot().
from angel import registry as _angel_registry

_angel_registry.install(bot)

# Cogs register their commands at import time, so the tree is complete before on_ready syncs it
# and tools/selftest.py can count it without a gateway connection.
from cogs import admin as _cog_admin
from cogs import ai_chat as _cog_ai_chat
from cogs import flagship as _cog_flagship
from cogs import fun_gif as _cog_fun_gif
from cogs import media_tools as _cog_media_tools
from cogs import memory_rules as _cog_memory_rules
from cogs import owner as _cog_owner
from cogs import productivity as _cog_productivity
from cogs import community as _cog_community
from cogs import context_menus as _cog_context_menus
from cogs import control as _cog_control
from cogs import setup_and_catchup as _cog_setup
from cogs import xp_profile as _cog_xp_profile

_cog_admin.install(bot)
_cog_fun_gif.install(bot)
_cog_xp_profile.install(bot)
_cog_media_tools.install(bot)
_cog_memory_rules.install(bot)
_cog_ai_chat.install(bot)
_cog_productivity.install(bot)
_cog_control.install(bot)
_cog_owner.install(bot)
_cog_community.install(bot)
_cog_flagship.install(bot)
_cog_context_menus.install(bot)
_cog_setup.install(bot)



# --- Action executor and natural-language command router ---
async def _is_opted_out_fail_closed(bot, user_id: int) -> bool:
  """A member who opted out stays opted out even when SQLite is momentarily unavailable."""
  try:
    return bool((await bot.db.get_user_prefs(user_id)).get("opt_out"))
  except Exception:
    return True


# --- Event listeners: voice state guard, snipe, edit snipe, modlog routing, ghost pings ---
@bot.event
async def on_message_delete(message: discord.Message):
  if not message.guild or message.author.bot:
    return
  if await _is_opted_out_fail_closed(bot, message.author.id):
    return
  if is_mistress(message.author):
    return

  att_url = message.attachments[0].url if message.attachments else None
  bot.snipe_cache[message.channel.id] = {
      "author_name": message.author.display_name,
      "author_avatar": message.author.display_avatar.url,
      "content": message.content or "*[مرفق]*",
      "attachment": att_url,
      "deleted_at": datetime.now(timezone.utc),
  }

  # Log deleted message to #السجلات (ModLog).
  await bot.send_modlog(
      message.guild,
      "🗑️ رسالة محذوفة",
      f"**المرسل:** {message.author.mention} في {message.channel.mention}\n**المحتوى:**\n> {(message.content or '*[مرفق]*')[:800]}",
  )

  real_mentions = [u for u in message.mentions if not u.bot and u.id != message.author.id]
  age_seconds = (datetime.now(timezone.utc) - message.created_at).total_seconds()
  if real_mentions and age_seconds < 45:
    mentioned_str = ", ".join(u.mention for u in real_mentions)
    ghost_desc = (
        f"**المرسل:** {message.author.mention}\n"
        f"**أشار إلى:** {mentioned_str}\n"
        f"**الرسالة المحذوفة:**\n> {message.content[:800]}"
    )
    modlog_ch_id = await bot.db.get_modlog_channel(message.guild.id)
    if modlog_ch_id:
      await bot.send_modlog(message.guild, "👻 كاشف المنشن الخفي", ghost_desc[:4096])
    else:
      # Without a private log channel the deleted text stays deleted: re-posting it in the
      # public channel defeated the deletion (C-019).
      logger.info(
          "ghost-ping detected in guild=%s channel=%s author=%s (no modlog configured)",
          message.guild.id, message.channel.id, message.author.id,
      )


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
  if not before.guild or before.author.bot or before.content == after.content:
    return
  # The guard runs before the opt-out return: opting out stops storage, not moderation. An
  # opted-out member could otherwise edit a clean line into an invite link unpunished. The
  # edit call keeps link inspection but does not feed the flood counter.
  await _run_angel_guard(bot, after, is_edit=True)
  if await _is_opted_out_fail_closed(bot, before.author.id):
    return
  if is_mistress(before.author):
    return
  bot.editsnipe_cache[before.channel.id] = {
      "author_name": before.author.display_name,
      "author_avatar": before.author.display_avatar.url,
      "before": before.content or "*[فارغ]*",
      "after": after.content or "*[فارغ]*",
      "edited_at": datetime.now(timezone.utc),
  }
  await bot.send_modlog(
      before.guild,
      "✏️ تعديل رسالة",
      f"**العضو:** {before.author.mention} في {before.channel.mention}\n**قبل:** {(before.content or '')[:400]}\n**بعد:** {(after.content or '')[:400]}",
  )


# --- Global slash command error handler ---
@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
  orig = getattr(error, "original", error)
  if isinstance(orig, discord.NotFound) or getattr(orig, "code", None) == 10062:
    return
  if isinstance(error, app_commands.MissingPermissions):
    msg = "🚫 لا تملك الصلاحية لاستخدام هذا الأمر."
  elif isinstance(error, app_commands.BotMissingPermissions):
    perms = ", ".join(error.missing_permissions)
    msg = f"⚠️ أحتاج لصلاحية (`{perms}`) في السيرفر لتنفيذ ذلك."
  elif isinstance(error, app_commands.CommandOnCooldown):
    msg = f"⏳ انتظر **{int(error.retry_after) + 1} ثانية** قبل المحاولة مرة أخرى."
  elif isinstance(error, app_commands.CheckFailure):
    msg = "🚫 لا تملك الصلاحية لاستخدام هذا الأمر."
  else:
    # One log line and one user-facing reply, both carrying the same short
    # correlation id, so a screenshot of the reply can be matched to the traceback.
    corr = uuid.uuid4().hex[:12]
    logger.error(f"Command error corr_id={corr}: {error}", exc_info=orig)
    msg = f"⚠️ تعذر تنفيذ الأمر في هذه اللحظة. (المرجع: `{corr}`)"

  await _safe_interaction_reply(interaction, msg, ephemeral=True)


# --- Main message handler ---
# Tuning knobs: an experiment must cost an .env edit + restart, not a commit.
FOLLOWUP_WINDOW_S = float(os.getenv("FOLLOWUP_WINDOW_S", "90"))
SOCIAL_DEDUPE_WINDOW_S = float(os.getenv("SOCIAL_DEDUPE_WINDOW_S", "600"))

# Two link jobs at a time, shared with `/fix` via angel.net.get_media_download_semaphore(): a
# private semaphore here plus the one in cogs/media_tools.py allowed four concurrent jobs, each
# holding a full carousel in RAM. The byte budget lives in angel.media.MAX_JOB_BYTES.


def tidy_caption(text: str, limit: int = 280) -> str:
  """Post captions arrive with hashtag walls and tracking lines; keep the human part."""
  if not text:
    return ""
  kept = []
  for line in text.splitlines():
    stripped = line.strip()
    if not stripped:
      continue
    words = stripped.split()
    if words and all(w.startswith(("#", "@", "http")) for w in words):
      continue
    kept.append(stripped)
  joined = "\n".join(kept).strip()
  if len(joined) > limit:
    joined = joined[: limit - 1].rstrip() + "…"
  return joined


WAKE_WORD_REGEX = re.compile(r"(?:^|\s)(?:يا\s*)?(?:انجل|أنجل|إنجل|نجل|angel)(?:\s|$|[،,.!؟?])", re.IGNORECASE)
SUSPICIOUS_LINK_REGEX = re.compile(r"(?:discord\.gg/|discordapp\.com/invite/|free-nitro|steamcommunnity)", re.IGNORECASE)


async def _run_angel_guard(bot, message: discord.Message, is_edit: bool = False) -> None:
    """Anti-spam / anti-scam check shared by new messages and edits (C-018).

    Editing a clean line into an invite link was a complete bypass of the guard. Delete,
    timeout and modlog are also independent: a failed delete (no Manage Messages) must not
    cancel the timeout or the log entry.

    Edits still get link/scam inspection, but only new messages feed the flood counter:
    one message plus five edits was six entries and a five-minute timeout.
    """
    if not message.guild or not isinstance(message.author, discord.Member):
        return
    if is_server_staff(message.author, message.guild):
        return
    gmode = bot.guard_modes_cache.get(message.guild.id, "off")
    if gmode not in ("active", "dry_run"):
        return
    now_t = time.monotonic()
    is_flood = False
    if not is_edit:
        user_times = bot.spam_tracker[(message.guild.id, message.author.id)]
        user_times.append(now_t)
        is_flood = len(user_times) >= 6 and (now_t - user_times[0]) < 5.0
    content = message.content or ""
    is_sus_link = bool(SUSPICIOUS_LINK_REGEX.search(content)) or guard.is_suspicious_arabic_scam(content)
    if not (is_flood or is_sus_link):
        return
    reason_ar = "إغراق رسائل سريع (Spam Flood)" if is_flood else "رابط دعوة/رابط مشبوه"
    if gmode == "dry_run":
        await bot.send_modlog(
            message.guild,
            "🧪 تنبيه الحماية (وضع تجريبي Dry-Run)",
            f"**العضو:** {message.author.mention}\n**السبب المرصود:** {reason_ar}\n**القناة:** {message.channel.mention}",
        )
        return
    if is_sus_link:
        try:
            await message.delete()
        except Exception as exc:  # noqa: BLE001 - missing Manage Messages must not stop the timeout
            logger.warning("guard delete failed: %s: %s", type(exc).__name__, exc)
    try:
        await message.author.timeout(timedelta(minutes=5), reason=f"Angel Guard: {reason_ar}")
    except Exception as exc:  # noqa: BLE001 - missing Moderate Members is reported, not hidden
        logger.warning("guard timeout failed: %s: %s", type(exc).__name__, exc)
    await bot.send_modlog(
        message.guild,
        "🛡️ تدخل الحماية التلقائي (Angel Guard)",
        f"**العضو:** {message.author.mention}\n**الإجراء:** كتم 5 دقائق\n**السبب:** {reason_ar}",
    )


async def _play_from_message(message: discord.Message, query: str) -> None:
  """Music shortcut: play `query` in the author's voice room, or explain why not."""
  cog = bot.get_cog("Music")
  if cog is None:
    await safe_reply(message, "🎧 الموسيقى غير مفعّلة الآن.")
    return
  voice_state = getattr(message.author, "voice", None)
  channel = getattr(voice_state, "channel", None)
  if not isinstance(channel, discord.VoiceChannel):
    await safe_reply(message, "🎧 ادخل روم صوتي أولاً وأنا أشغّلها لك.")
    return
  voice = message.guild.voice_client if message.guild else None
  if voice is not None and voice.is_connected() and voice.channel and voice.channel.id != channel.id:
    await safe_reply(message, f"🎧 أنجل مشغّلة في {voice.channel.mention} الآن. انضم لنفس الروم أولاً.")
    return
  state = cog.engine.state(message.guild.id)
  try:
    async with message.channel.typing():
      await cog.engine.ensure_connected(channel)
      track = await cog.engine.enqueue(channel, query, message.author)
  except VoiceBusyError as exc:
    await safe_reply(message, f"🎧 أنجل مشغّلة في {exc.channel.mention} الآن. انضم لنفس الروم أولاً.")
    return
  except ResolveError as exc:
    await safe_reply(message, f"⚠️ ما لقيت الصوت: `{str(exc)[:160]}`")
    return
  except Exception as exc:  # noqa: BLE001 - voice join failures must be answered
    logger.warning(f"music-trigger join failed: {type(exc).__name__}: {exc}")
    await safe_reply(message, "⚠️ تعذر الدخول للروم الصوتي الآن.")
    return
  # Set only after admission: a rejected request must not retarget the session's
  # notification channel (the busy-channel rejection used to claim it first).
  state.text_channel_id = message.channel.id
  playing = await cog.engine.start(message.guild)
  if playing is track:
    await safe_reply(
        message,
        f"🎶 أشغّل الآن: **{track.title[:180]}** (`{track.duration_text}`) من `{track.source}`",
        untrusted=True,
    )
  else:
    await safe_reply(
        message,
        f"➕ أضفتها للقائمة: **{track.title[:180]}** (`{track.duration_text}`)",
        untrusted=True,
    )


@bot.event
async def on_message(message: discord.Message):
  if message.author.bot:
    return

  # 0.0 Owner silence switch: she observes but never replies while muted here.
  if message.guild and guard.is_silent(message.guild.id, message.channel.id):
    return

  # A member who ran `/data delete` keeps `opt_out = 1`; nothing below may store them again.
  # Any database error is treated as opt-out: leaking a private message is worse than silence.
  # DMs are included: opt-out used to be evaluated only when `message.guild` existed, so a
  # member who erased their data had their DMs mirrored again on the next message (C-006).
  _opted_out = await _is_opted_out_fail_closed(bot, message.author.id)

  # 0.05 Durable server log: every human line is kept for learning (bounded to one year).
  # Runs before the music shortcut so a play request is not the one message class missing
  # from the archive. Fire-and-forget must hold a reference or the task can be GC'd.
  if message.guild and message.content.strip() and not _opted_out:
    try:
      _log_t = asyncio.create_task(bot.db.log_server_message(
          message.guild.id, message.channel.id, message.author.id,
          getattr(message.author, "display_name", "") or "", message.content,
          message_id=message.id))
      bot._bg_tasks.add(_log_t)
      _log_t.add_done_callback(bot._bg_tasks.discard)
    except Exception as _log_err:  # noqa: BLE001 - logging must never break the pipeline
      logger.debug(f"server-log skip: {_log_err}")

  # 0.06 Music shortcut: "انجل شغلي <اسم أغنية أو رابط>" plays in the author's voice room.
  if message.guild:
    _play_query = parse_play_request(message.content or "")
    if _play_query:
      try:
        await _play_from_message(message, _play_query)
      except Exception as _play_err:  # noqa: BLE001 - never break the message pipeline
        logger.warning(f"music-trigger failed: {type(_play_err).__name__}: {_play_err}")
      return

  # 0.1 Keep a rolling per-channel speaker buffer for the autonomous engine.
  if message.guild and message.content.strip() and not _opted_out:
    bot.recent_speakers[message.channel.id].append({
        "user_id": message.author.id,
        "name": message.author.display_name,
        "ts": time.monotonic(),
        "text": message.content.strip()[:200],
        "msg_id": message.id,
        "bot": message.author.bot,
    })
    if len(message.content) > 12 and not _opted_out:
      _touch_t = asyncio.create_task(memory.touch(
          message.guild.id, message.author.id, message.author.display_name, message.content))
      bot._bg_tasks.add(_touch_t)
      _touch_t.add_done_callback(bot._bg_tasks.discard)

  if message.content.strip().lower() == "!sync" and is_mistress(message.author):
    await bot.sync_all_commands_cleanly()
    await safe_reply(message, "✅ تمت مزامنة الأوامر بنجاح.")
    return

  # 0. Track Channel Activity for /pulse & Run Angel Guard
  if message.guild:
    bot.channel_activity_counter[message.guild.id][message.channel.id] += 1
    await _run_angel_guard(bot, message)

  # 1. AFK auto-remove: an O(1) RAM check first, so non-AFK users cost no SQLite queries
  if message.guild:
    afk_key = (message.guild.id, message.author.id)
    if afk_key in bot.afk_cache:
      bot.afk_cache.pop(afk_key, None)
      afk_removed = await bot.db.remove_afk(message.guild.id, message.author.id)
      if afk_removed:
        try:
          await message.channel.send(
              f"👋 أهلاً بعودتك {message.author.mention}، تم إلغاء وضع الغياب.", delete_after=6
          )
        except Exception:
          pass

  # 2. AFK Mention Responder (O(1) RAM lookup, scoped to this guild)
  if message.guild and message.mentions and bot.afk_cache:
    for mentioned in message.mentions:
      if mentioned.bot or mentioned.id == message.author.id:
        continue
      afk_info = bot.afk_cache.get((message.guild.id, mentioned.id))
      if afk_info:
        reason, _ = afk_info
        await safe_reply(
            message,
            f"💤 **{mentioned.display_name}** غائب حالياً — **السبب:** {reason}",
            untrusted=True,
        )

  # 3. Sticky Message Handler
  if message.guild and message.channel.id in bot.stickies_cache:
    now_m = time.monotonic()
    last_sticky = bot.sticky_cooldowns.get(message.channel.id)
    if last_sticky is None or now_m - last_sticky >= 6.0:
      bot.sticky_cooldowns[message.channel.id] = now_m
      sticky_data = bot.stickies_cache[message.channel.id]
      old_id = sticky_data.get("last_message_id")
      if old_id:
        try:
          old_msg = await message.channel.fetch_message(old_id)
          await old_msg.delete()
        except Exception:
          pass
      try:
        emb = discord.Embed(description=f"📌 **{sticky_data['content']}**"[:4096], color=0x2B2D31)
        new_sticky = await message.channel.send(embed=emb)
        sticky_data["last_message_id"] = new_sticky.id
        await bot.db.set_sticky(message.channel.id, message.guild.id, sticky_data["content"], new_sticky.id)
      except Exception:
        pass

  # 4. Custom Phrase Action Triggers
  if message.guild and await try_execute_custom_action_trigger(bot, message):
    return

  # 5. Automatic Social Media Video & Multi-Photo Link Fixer (TikTok, Instagram, X, Reddit)
  social_urls = list(dict.fromkeys(m.group(0) for m in SOCIAL_URL_REGEX.finditer(message.content)))
  # Also support replying "@Angel" or "انجل" to a message that contains a TikTok/Instagram link!
  if not social_urls and message.reference and message.reference.message_id and (
      bot.user in message.mentions or WAKE_WORD_REGEX.search(message.content)
  ):
    stripped_wake = re.sub(r"<@!?\d+>", "", message.content)
    stripped_wake = re.sub(r"(?:يا\s*)?(?:انجل|أنجل|إنجل|نجل|angel|شوفي|صلحي|فكي|حملي|هاتي)", "", stripped_wake, flags=re.IGNORECASE).strip()
    if not stripped_wake:
      ref_m = message.reference.resolved
      if not isinstance(ref_m, discord.Message):
        try:
          ref_m = await message.channel.fetch_message(message.reference.message_id)
        except Exception:
          ref_m = None
      if isinstance(ref_m, discord.Message) and ref_m.content:
        social_urls = list(dict.fromkeys(m.group(0) for m in SOCIAL_URL_REGEX.finditer(ref_m.content)))

  if social_urls:
    social_urls = [clean_social_url(u) for u in dict.fromkeys(social_urls)]
    # The same post re-posted (or two people pasting one link) must not be downloaded twice.
    now_social = time.monotonic()
    fresh_urls = []
    for _u in social_urls:
      _tag = hashlib.sha256(_u.encode()).hexdigest()[:8]
      last_seen = bot.recent_social_links.get(_tag)
      if last_seen is not None and now_social - last_seen < SOCIAL_DEDUPE_WINDOW_S:
        logger.info("social outcome=duplicate url=%s n=0 ms=0 class=-", _tag)
        continue
      bot.recent_social_links[_tag] = now_social
      fresh_urls.append(_u)
    if fresh_urls and len(bot.recent_social_links) > 256:
      for _k, _v in list(bot.recent_social_links.items()):
        if now_social - _v > max(300.0, SOCIAL_DEDUPE_WINDOW_S * 3):
          bot.recent_social_links.pop(_k, None)
    social_urls = fresh_urls

  if social_urls and (not message.guild or bot.social_fixer_cache.get(message.guild.id, True)):
    async def _handle_social_links_bg(msg_obj: discord.Message, urls_to_fix: List[str]):
      max_b = (
          min(getattr(msg_obj.guild, "filesize_limit", 10 * 1024 * 1024), 25 * 1024 * 1024)
          if msg_obj.guild
          else 10 * 1024 * 1024
      )
      for s_url in urls_to_fix[:3]:
        started = time.monotonic()
        url_tag = hashlib.sha256(s_url.encode()).hexdigest()[:8]
        # Visible progress at zero token cost: the owner sees that the link was received.
        try:
          await msg_obj.add_reaction("⏳")
        except Exception:
          pass
        try:
          async with msg_obj.channel.typing():
            media_files, fixed_url, caption = await process_social_media_url_multi(s_url, max_bytes=max_b)
            caption = tidy_caption(caption)
          logger.info(
              "social outcome=%s url=%s n=%d ms=%d class=-",
              "files" if media_files else ("fallback" if fixed_url else "empty"),
              url_tag,
              len(media_files or []),
              int((time.monotonic() - started) * 1000),
          )
          try:
            await msg_obj.remove_reaction("⏳", msg_obj.guild.me if msg_obj.guild else bot.user)
            await msg_obj.add_reaction("✅" if (media_files or fixed_url) else "⚠️")
          except Exception:
            pass
          if media_files or fixed_url:
            if msg_obj.guild:
              try:
                await msg_obj.edit(suppress=True)
              except Exception:
                pass
            if media_files:
              default_icon = "🎬" if any(fn.endswith(".mp4") for _, fn in media_files) else "📸"
              # Discord caps a message at 10 attachments: every batch goes out, no slide is dropped.
              for index, batch in enumerate(chunk_slides(media_files)):
                files = [discord.File(io.BytesIO(b), filename=fn) for b, fn in batch]
                if index == 0:
                  await safe_reply(msg_obj, content=caption or default_icon, files=files, untrusted=True)
                else:
                  await msg_obj.channel.send(files=files)
            elif fixed_url:
              await safe_reply(msg_obj, content=fixed_url, untrusted=True)
        except Exception as s_err:
          logger.warning(
              "social outcome=error url=%s n=0 ms=%d class=%s notice=%s",
              url_tag,
              int((time.monotonic() - started) * 1000),
              type(s_err).__name__,
              str(s_err)[:160],
          )
        finally:
          try:
            await msg_obj.remove_reaction("⏳", msg_obj.guild.me if msg_obj.guild else bot.user)
          except Exception:
            pass

    async def _run_social_bounded(msg_obj: discord.Message, urls_to_fix: List[str]):
      async with get_media_download_semaphore():
        await _handle_social_links_bg(msg_obj, urls_to_fix)

    bg_social_t = asyncio.create_task(_run_social_bounded(message, social_urls))
    bot._bg_tasks.add(bg_social_t)
    bg_social_t.add_done_callback(bot._bg_tasks.discard)
    # If the message was ONLY the social link (or "@Angel <link>" / "انجل <link>" with no other question), return here so AI chat doesn't double-reply!
    residual_txt = SOCIAL_URL_REGEX.sub("", message.content)
    residual_txt = re.sub(r"<@!?\d+>", "", residual_txt)
    residual_txt = re.sub(r"(?:يا\s*)?(?:انجل|أنجل|إنجل|نجل|angel|شوفي|هاتي|حملي)", "", residual_txt, flags=re.IGNORECASE).strip(" ،,.!؟?\n\t")
    if not residual_txt:
      return

  # 6. Guild XP & Custom Text Auto-Triggers
  if message.guild:
    # No XP for a member who erased their data: the row would be re-created immediately.
    now_mono = time.monotonic()
    xp_key = (message.guild.id, message.author.id)
    last_xp = bot.xp_cooldowns.get(xp_key)
    if not _opted_out and (last_xp is None or now_mono - last_xp >= 45.0):
      bot.xp_cooldowns[xp_key] = now_mono
      _, new_lvl, leveled_up = await bot.db.add_xp(
          message.guild.id, message.author.id, random.randint(15, 25)
      )
      if leveled_up:
        try:
          await message.channel.send(
              f"🎉 ارتفع مستوى {message.author.mention} إلى **Lv.{new_lvl}**!"
          )
        except Exception:
          pass

    if message.guild.id not in bot.auto_triggers_cache:
      bot.auto_triggers_cache[message.guild.id] = await bot.db.get_auto_triggers(message.guild.id)
    triggers = bot.auto_triggers_cache.get(message.guild.id, {})
    lower_content = message.content.lower().strip()
    if lower_content in triggers:
      await safe_reply(message, triggers[lower_content])

  # Prefix commands (!help, !sync ...) must work in DMs and when the bot is mentioned too;
  # before this they were skipped by every early return above. An unknown `!word` falls
  # through to the normal AI path instead of being silently swallowed.
  if message.content.startswith("!") and len(message.content) > 1 and message.content[1].isalpha():
    ctx = await bot.get_context(message)
    if ctx.valid:
      await bot.invoke(ctx)
      return

  # 7. Detect Conversation, Follow-up Window, or Pending Step Trigger
  is_dm = isinstance(message.channel, discord.DMChannel)
  is_mentioned = bot.user in message.mentions
  is_reply_to_bot = False
  if message.reference:
    ref_obj = message.reference.resolved or getattr(message.reference, "cached_message", None)
    if isinstance(ref_obj, discord.Message) and bot.user and ref_obj.author.id == bot.user.id:
      is_reply_to_bot = True

  called_by_name = bool(WAKE_WORD_REGEX.search(message.content))
  has_pending = bool(message.guild and (message.guild.id, message.author.id) in bot.pending_step)
  # A destructive [EXEC] waiting for "تأكيد" must be reachable without a wake word.
  has_confirm = bool(message.guild and (message.guild.id, message.author.id) in bot.pending_confirm)

  # Follow-up window: for 90s after her reply a short command ("اعطيها بوسة", "احضنيها") is accepted
  in_followup_window = False
  if message.guild:
    norm_c = normalize_arabic_text(message.content.lower().strip())
    last_win = bot.active_chat_window.get((message.channel.id, message.author.id))
    if last_win is not None and (time.monotonic() - last_win) <= FOLLOWUP_WINDOW_S:
      if any(
          norm_c.startswith(prefix_w)
          for prefix_w in (
              "اعطيها", "عطيها", "اعطيه", "عطيه", "بوسيها", "احضنيها", "ضميها",
              "اعطي ", "عطي ", "طيب اعطي",
          )
      ):
        in_followup_window = True

  # Record message in O(1) RAM buffer for ambient context (eliminating slow channel.history REST calls).
  if message.guild and message.content.strip() and not _opted_out:
    prev_ambient_list = list(bot.recent_channel_msgs[message.channel.id])
    # Entries carry the author id: deletion filters on it. The old "name: text" format
    # had no reliable author marker, so a deleted member's lines survived in prompts.
    bot.recent_channel_msgs[message.channel.id].append(
        (message.author.id, f"{message.author.display_name}: {message.content.strip()[:120]}")
    )
    if not message.author.bot and message.author.id != MISTRESS_INT_ID:
      bot.last_social_target[message.channel.id] = message.author.id
  else:
    prev_ambient_list = []

  if is_dm or is_mentioned or is_reply_to_bot or called_by_name or has_pending or has_confirm or in_followup_window:
    prompt = message.content
    if bot.user is not None:
      prompt = prompt.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "")
    prompt = prompt.strip()

    if prompt and await try_execute_natural_command(bot, message, prompt):
      if message.guild:
        bot.active_chat_window[(message.channel.id, message.author.id)] = time.monotonic()
      return

    # Pre-check user quota before downloading any attachments into RAM (F-09)
    harem_t = bot.get_harem_title(message.author.id)
    allowed_pre, deny_pre = bot.quota.check_user_allowed(
        message.author, is_harem=(harem_t is not None), dry_run=True
    )
    if not allowed_pre:
      await safe_reply(message, f"⚠️ {deny_pre}")
      return

    media_items = await extract_message_media(message)
    if not prompt and not media_items:
      return

    ambient_context = "\n".join(
        (entry[1] if isinstance(entry, tuple) else str(entry))
        for entry in prev_ambient_list[-8:]
    ) if prev_ambient_list else None

    async with message.channel.typing():
      try:
        reply, gif_bytes, gif_url, img_bytes, _ = await bot.handle_conversation(
            message.author,
            prompt,
            media_items=media_items,
            ambient_context=ambient_context,
            message_Context=message,
        )

        if message.guild:
          bot.active_chat_window[(message.channel.id, message.author.id)] = time.monotonic()
          _angel_uid = bot.user.id if bot.user else 0
          bot.recent_channel_msgs[message.channel.id].append((_angel_uid, f"Angel: {reply[:120]}"))

        if is_dm and SOVEREIGN_TOOLS_ENABLED and not _opted_out:
          await bot.forward_dm_to_mistress(message, reply)

        # Media-only replies (an image or GIF with no prose) are delivered; a reply
        # with neither text nor media stays silent instead of a fake fallback line.
        delivery = plan_reply_delivery(reply, gif_bytes, gif_url, img_bytes)
        if delivery is None:
          return
        first_chunk, rest_chunks, has_files, use_gif_url = delivery
        files_to_send = []
        if has_files:
          if img_bytes:
            files_to_send.append(discord.File(io.BytesIO(img_bytes), filename="angel_art.png"))
          if gif_bytes:
            files_to_send.append(discord.File(io.BytesIO(gif_bytes), filename="angel_reaction.gif"))

        gif_embed = None
        if use_gif_url:
          gif_embed = discord.Embed(color=0xD4AF37 if (is_mistress(message.author) or harem_t) else 0x2B2D31)
          gif_embed.set_image(url=gif_url)

        await safe_reply(message, content=first_chunk, embed=gif_embed, files=files_to_send, untrusted=True)
        for chunk in rest_chunks:
          await message.channel.send(content=chunk, allowed_mentions=discord.AllowedMentions.none())

      except AI_ERRORS as err:
        await safe_reply(message, f"⚠️ {err}")
      except Exception as exc:
        logger.exception(f"Unexpected error in on_message: {exc}")
        await safe_reply(message, "⚠️ حدث خطأ غير متوقع.")
    return


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
  if isinstance(error, commands.CommandNotFound):
    return
  logger.warning(f"Prefix command notice: {error}")


def _force_utf8_console() -> None:
  """CLI output must never crash on a legacy Windows code page.

  PowerShell 5.1 hands the child a cp1252 stdout; the checkpoint message contains an emoji
  and raised UnicodeEncodeError, turning a successful gate into exit 1.
  """
  for stream in (sys.stdout, sys.stderr):
    try:
      stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
      pass


def _run_sqlite_cli_utility(mode: str) -> int:
  import sqlite3
  _force_utf8_console()
  print(f"=== AngelBot SQLite Database Utility ({mode}) ===")
  if not os.path.exists(DB_PATH):
    if mode == "checkpoint":
      # A pre-start gate must not demand the artifact the bot creates on its first
      # setup_hook(). Failing here blocked systemd, Docker and the Windows launcher.
      print(f"ℹ️ No database yet at '{DB_PATH}' — the first start creates it. Nothing to checkpoint.")
      return 0
    print(f"⚠️ Database file '{DB_PATH}' not found in {os.getcwd()}.")
    return 1
  conn = sqlite3.connect(DB_PATH, timeout=15.0)
  try:
    if mode == "checkpoint":
      res = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
      conn.commit()
      print(f"✅ WAL Checkpoint (TRUNCATE) result: {res} (0 = full success)")
    integrity = conn.execute("PRAGMA integrity_check;").fetchone()
    print(f"✅ PRAGMA integrity_check: {integrity[0] if integrity else 'unknown'}")
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    print(f"✅ Tables found ({len(tables)}): {', '.join(tables)}")
    for tbl in ("messages", "user_summaries", "user_preferences", "harem_members", "guild_settings", "user_xp"):
      if tbl in tables:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"   • {tbl}: {cnt} rows")
    return 0 if (integrity and integrity[0] == "ok") else 2
  finally:
    conn.close()


if __name__ == "__main__":
  if "--checkpoint-db" in sys.argv:
    sys.exit(_run_sqlite_cli_utility("checkpoint"))
  if "--verify-db" in sys.argv:
    sys.exit(_run_sqlite_cli_utility("verify"))
  if "--cleanup" in sys.argv:
    async def _cli_cleanup():
      try:
        return await perform_storage_cleanup(deep=True)
      finally:
        await bot.db.close()
        await close_shared_http_session()
    _force_utf8_console()
    res = asyncio.run(_cli_cleanup())
    print(f"=== AngelBot Storage Cleanup Complete ===\n{res}", flush=True)
    sys.exit(0)

  import signal
  def _graceful_sigterm_handler(signum, frame):
    # A Python signal handler must not log or await: build the shutdown on the loop thread.
    try:
      loop = asyncio.get_running_loop()
      loop.call_soon_threadsafe(lambda: asyncio.create_task(bot.close()))
    except RuntimeError:
      sys.exit(0)

  for _sig in ( getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None) ):
    if _sig is not None:
      try:
        signal.signal(_sig, _graceful_sigterm_handler)
      except Exception:
        pass

  if not DISCORD_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Missing DISCORD_TOKEN or GEMINI_API_KEY in .env")
  bot.run(DISCORD_TOKEN, reconnect=True, log_handler=None)
