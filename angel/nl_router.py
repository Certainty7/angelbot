"""Natural-language command router.

`try_execute_natural_command` and its helpers turn a plain message ("انجل اطردي فلان", "انجل شغلي
...") into a real action. The client is an explicit first parameter, so bot.py and the cogs can call
the router without an import cycle.
"""
import io
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

import discord

from angel import guard
from angel.confirmations import (
    CANCELLED,
    CONFIRMED,
    EXPIRED,
    WRONG_CHANNEL,
    confirmation_prompt,
    queue_confirmation,
    take_confirmation,
)
from angel.config import (
    can_assign_role,
    can_create_action_trigger,
    can_moderate_member,
    can_read_history,
    check_staff_action_permission,
    get_or_fetch_member,
    has_effective_perm,
    is_mistress,
    is_romantic_gif,
    is_server_staff,
    logger,
    safe_reply,
    SOVEREIGN_TOOLS_ENABLED,
)
from angel.dashboard import build_server_pulse_embed
from angel.media import perform_full_system_and_bot_update, perform_storage_cleanup
from angel.persona import angel_spontaneous_confirm, normalize_arabic_text
from angel.summarize import analyze_channel_history_deep
from angel.text import split_message
from angel.ui import ArtStudioView, GiveawayJoinView, TicketPanelView

_EXEC_INTENT_GUARDS: Dict[str, Tuple[str, ...]] = {
    "PIN_FACT": ("تذكر", "احفظ", "ثبت", "pin", "remember"),
    "SET_MODLOG": ("سجل", "لوج", "لوق", "modlog"),
    "GUARD_MODE": ("حماي", "سبام", "guard"),
    "AUTOROLE": ("تلقائي", "جدد", "autorole"),
    "ADD_ROLE": ("اعط", "أعط", "امنح", "رتب", "رول", "role"),
    "REMOVE_ROLE": ("اسحب", "شيل", "احذف", "رتب", "رول", "role"),
    "CREATE_ROLE": ("انشئ", "أنشئ", "سوي", "اصنع", "رتب", "رول"),
    "NICKNAME": ("لقب", "اسم", "سمي", "غير", "عدل", "nick"),
    "MOVE_TO_ME": ("اسحب", "إسحب", "انقل", "ودي", "جيب", "هات", "فويس", "عندي", "معي"),
    "DISCONNECT_VOICE": ("طلع", "افصل", "نزل", "اخرج", "فويس", "صوتي"),
    "VOICE_MUTE": ("اكتم", "ميوت", "مايك", "فويس", "صوت"),
    "VOICE_UNMUTE": ("فك", "شيل", "ميوت", "مايك", "فويس"),
    "VOICE_DEAFEN": ("صمم", "سماع", "ديفن", "فويس"),
    "VOICE_UNDEAFEN": ("فك", "شيل", "سماع", "ديفن"),
    "RENAME_CHANNEL": ("غير", "سمي", "عدل", "خلي", "اسم", "روم", "قنا"),
    "CREATE_TEXT": ("انشئ", "أنشئ", "سوي", "اصنع", "افتح", "روم", "قنا", "شات"),
    "CREATE_VOICE": ("انشئ", "أنشئ", "سوي", "اصنع", "افتح", "فويس", "صوتي", "روم"),
    "DELETE_CHANNEL": ("احذف", "امسح", "طير", "روم", "قنا", "غرف"),
    "CLONE_CHANNEL": ("انسخ", "نسخ", "كرر", "روم", "قنا", "شات"),
    "SET_TOPIC": ("وصف", "توبيك", "موضوع", "روم", "قنا", "شات"),
    "LOCK": ("اقفل", "قفل", "اغلق", "أغلق", "سكر", "lock"),
    "UNLOCK": ("افتح", "فك", "بطل", "unlock"),
    "HIDE": ("اخف", "إخف", "خب", "hide"),
    "UNHIDE": ("اظهر", "أظهر", "بين", "افتح", "unhide", "show"),
    "SLOWMODE": ("سلو", "بطيء", "بطئ", "slow"),
    "PURGE": ("امسح", "احذف", "نظف", "طهر", "مسح", "حذف", "purge", "clear"),
    "KICK": ("اطرد", "طرد", "كيك", "شوت", "طير", "انف", "kick"),
    "BAN": ("احظر", "حظر", "بند", "بان", "طير", "ban"),
    "UNBAN": ("فك", "شيل", "الغي", "حظر", "بان", "باند", "unban"),
    "TIMEOUT": ("اكتم", "كتم", "ميوت", "سكت", "تايم", "صمت", "mute", "timeout"),
    "UNTIMEOUT": ("فك", "شيل", "الغي", "كتم", "ميوت", "يتكلم", "unmute", "untimeout"),
    "WARN": ("حذر", "انذر", "أنذر", "تحذير", "انذار", "إنذار", "warn"),
    "CLEAR_WARNINGS": ("امسح", "احذف", "صفر", "سامح", "انذار", "تحذير"),
}

# Model-proposed actions that change or destroy something need a human "تأكيد" in between.
# The intent keyword alone is a word filter; this is the second layer the audit asked for.
_CONFIRM_REQUIRED = {
    "BAN", "KICK", "PURGE", "DELETE_CHANNEL",
    "ADD_ROLE", "REMOVE_ROLE", "CREATE_ROLE", "NICKNAME", "UNBAN",
    # State-changing actions that used to run immediately (C-013).
    "TIMEOUT", "UNTIMEOUT", "CLEAR_WARNINGS", "SET_MODLOG", "AUTOROLE",
    "HIDE", "UNHIDE", "LOCK", "UNLOCK", "SLOWMODE", "RENAME_CHANNEL",
    "CREATE_TEXT", "CREATE_VOICE", "CLONE_CHANNEL", "SET_TOPIC",
}
_CONFIRM_TTL = 60.0
# Bare "نفذ" and "لا" were triggers: both are ordinary Arabic words.
_CONFIRM_WORDS = ("تأكيد", "تاكيد", "confirm", "نفذي")
_CANCEL_WORDS = ("الغاء", "إلغاء", "كنسل", "cancel")


class _ActionBlocked(Exception):
  """A hierarchy or resolution check refused the action; nothing was executed."""


async def _fresh_target(guild, member_id: int):
  """Re-resolve the target when the confirmation arrives, so a stale snapshot cannot act."""
  member = guild.get_member(member_id)
  if member is not None:
    return member
  try:
    return await guild.fetch_member(member_id)
  except discord.HTTPException:
    return None


async def resolve_natural_target_member(
    bot, message: discord.Message, clean_text: str = "", strict_target: bool = False
) -> Optional[discord.Member]:
  """
  Resolve target member from:
  1. Direct @mentions (excluding Angel herself).
  2. Replying to a user's message (when no @mention is given).
  3. 17-20 digit Discord User ID written in text.
  4. Fuzzy display_name / username match among voice channel members & cached guild members.
  """
  guild = message.guild
  if not guild:
    return None

  # 1. Explicit @mentions
  targets = [u for u in message.mentions if u.id != (bot.user.id if bot.user else 0)]
  if targets:
    first = targets[0]
    bot.last_social_target[message.channel.id] = first.id
    if isinstance(first, discord.Member):
      return first
    return await get_or_fetch_member(guild, first.id)

  # 2. Referenced / Replied-to message author
  if message.reference and message.reference.message_id:
    ref_msg = message.reference.resolved
    if not isinstance(ref_msg, discord.Message):
      try:
        ref_msg = await message.channel.fetch_message(message.reference.message_id)
      except Exception:
        ref_msg = None
    if isinstance(ref_msg, discord.Message) and ref_msg.author and not ref_msg.author.bot:
      if isinstance(ref_msg.author, discord.Member):
        return ref_msg.author
      return await get_or_fetch_member(guild, ref_msg.author.id)

  # 3. Explicit numeric User ID (17-20 digits)
  id_match = re.search(r"\b(\d{17,20})\b", clean_text or message.content)
  if id_match:
    uid = int(id_match.group(1))
    if not bot.user or uid != bot.user.id:
      return await get_or_fetch_member(guild, uid)

  if strict_target:
    return None

  # 4. Fuzzy match against active voice channel members & cached guild members
  if clean_text:
    candidate_pool: Dict[int, discord.Member] = {}
    for m in guild.members:
      if not m.bot:
        candidate_pool[m.id] = m
    for vc in guild.voice_channels:
      for m in vc.members:
        if not m.bot:
          candidate_pool[m.id] = m
    norm_txt = normalize_arabic_text(clean_text.lower())
    for m in candidate_pool.values():
      dname = normalize_arabic_text(m.display_name.lower())
      uname = m.name.lower()
      if len(dname) >= 3 and dname in norm_txt:
        bot.last_social_target[message.channel.id] = m.id
        return m
      if len(uname) >= 3 and uname in norm_txt:
        bot.last_social_target[message.channel.id] = m.id
        return m

    # 5. Pronoun / Contextual Target Fallback ("اعطيها", "بوسيها", "احضنيها", "اعطي اللي معنا")
    if any(p in norm_txt for p in ("اعطيها", "عطيها", "اعطيه", "عطيه", "بوسيها", "احضنيها", "ضميها", "اللي معنا", "معانا", "لها ")):
      last_tid = bot.last_social_target.get(message.channel.id)
      if last_tid and last_tid != message.author.id:
        resolved_last = await get_or_fetch_member(guild, last_tid)
        if resolved_last:
          return resolved_last

  return None


def resolve_natural_role(guild: discord.Guild, message: discord.Message, query_hint: str = "") -> Optional[discord.Role]:
  """Resolve a role from @role mentions or fuzzy role name search in guild.roles."""
  if message.role_mentions:
    return message.role_mentions[0]
  hint = normalize_arabic_text(query_hint.strip().lower()).strip("\"'«»")
  if not hint:
    return None
  assignable = [r for r in guild.roles if r != guild.default_role and not r.managed]
  for r in assignable:
    if normalize_arabic_text(r.name.lower()) == hint:
      return r
  best = None
  for r in assignable:
    r_norm = normalize_arabic_text(r.name.lower())
    if hint in r_norm or (len(r_norm) >= 3 and r_norm in hint):
      if best is None or len(r_norm) > len(best[0]):
        best = (r_norm, r)
  if best:
    return best[1]
  return None


def resolve_natural_text_channel(
    guild: discord.Guild, message: discord.Message, query_hint: str = ""
) -> Optional[discord.TextChannel]:
  """Resolve a TextChannel from #channel mentions or channel name search."""
  for ch in message.channel_mentions:
    if isinstance(ch, discord.TextChannel):
      return ch
  hint = normalize_arabic_text(query_hint.strip().lower()).lstrip("#").strip()
  if hint:
    best = None
    for ch in guild.text_channels:
      c_norm = normalize_arabic_text(ch.name.lower())
      if c_norm == hint:
        return ch
      # A short name is contained in half the sentences people write ("روم السجلات" contains
      # "روم"), so the longest candidate wins instead of the first one in guild order.
      if len(c_norm) >= 3 and c_norm in hint and (best is None or len(c_norm) > len(best[0])):
        best = (c_norm, ch)
    if best:
      return best[1]
  return None


async def execute_ai_inferred_action(bot, message: discord.Message, cmd_str: str, confirmed: bool = False,
                                     actor: Optional[discord.Member] = None):
  """Run one model-proposed action.

  `actor` is the member whose CURRENT authority authorizes the mutation. The default
  (the original message author) is only a snapshot: when a confirmation arrives later,
  the caller must pass the confirmer's freshly resolved membership, otherwise a staff
  member who lost the role inside the 60-second window still executes (CWE-863).
  """
  guild = message.guild
  author = message.author
  actor = actor or author
  if not guild:
    return "none"

  parts = [p.strip() for p in cmd_str.split("|")]
  action_name = parts[0].upper()
  params: Dict[str, str] = {}
  for p in parts[1:]:
    if "=" in p:
      k, v = p.split("=", 1)
      params[k.strip().lower()] = v.strip()

  # The current message must carry the intent keyword. This is a weak signal on purpose:
  # it stops ambient/archived text, not a manipulated insider. Destructive actions get the
  # explicit confirmation below as the second layer.
  norm_msg = normalize_arabic_text((message.content or "").lower())

  if action_name == "PIN_FACT":
    required = _EXEC_INTENT_GUARDS.get("PIN_FACT", ())
    if not any(kw in norm_msg for kw in required):
      logger.warning("Blocked unverified AI action PIN_FACT (intent keyword missing).")
      return "blocked"
    fact_val = params.get("fact") or ""
    if fact_val:
      await bot.db.pin_user_fact(author.id, fact_val)
    return "executed"

  if action_name == "FORGET_KEYWORD":
    # Self-service erasure, not a staff action: the requester's own rows only. It runs
    # only through the pending-confirmation flow, so the actor is the requester.
    kw_forget = params.get("kw") or ""
    if kw_forget:
      await bot.db.forget_user_keyword(author.id, kw_forget)
    return "executed"

  if not check_staff_action_permission(actor, guild, action_name):
    return "blocked"
  required_kws = _EXEC_INTENT_GUARDS.get(action_name)
  if not confirmed and required_kws and not any(kw in norm_msg for kw in required_kws):
    logger.warning(f"Blocked unverified AI action {action_name} (intent keyword missing in current message).")
    return "blocked"

  # The model proposed a destructive action: hold it until the same human types "تأكيد".
  # The original message is kept so its mention/reply still resolves the target.
  if not confirmed and action_name in _CONFIRM_REQUIRED:
    now_c = time.monotonic()
    for _key, _val in list(bot.pending_confirm.items()):
      _ts = _val.get("ts")
      if _ts is None or now_c - _ts > _CONFIRM_TTL:
        bot.pending_confirm.pop(_key, None)
    bot.pending_confirm[(guild.id, author.id)] = {
        "cmd": cmd_str,
        "message": message,
        "channel_id": message.channel.id,
        "ts": time.monotonic(),
    }
    await safe_reply(
        message,
        f"⚠️ إجراء **{action_name}** جاهز. اكتب **تأكيد** خلال 60 ثانية لتنفيذه، أو أي كلمة أخرى للإلغاء.",
    )
    return "queued"

  target_member = await resolve_natural_target_member(bot, message, message.content or "")

  try:
    if action_name == "SET_MODLOG":
      target_ch = resolve_natural_text_channel(guild, message) or message.channel
      await bot.db.set_modlog_channel(guild.id, target_ch.id)
      bot.modlog_cache[guild.id] = target_ch.id
    elif action_name == "GUARD_MODE":
      gmode = params.get("mode", "active").lower()
      if gmode not in ("active", "dry_run", "off"):
        gmode = "active"
      await bot.db.set_guard_mode(guild.id, gmode)
      bot.guard_modes_cache[guild.id] = gmode
    elif action_name == "KICK":
      strict_mem = await resolve_natural_target_member(bot, message, message.content or "", strict_target=True)
      if not (strict_mem and can_moderate_member(actor, strict_mem, guild)[0]):
        raise _ActionBlocked
      await strict_mem.kick(reason=f"AI Order by {author}")
      await bot.send_modlog(guild, "👢 طرد عضو", f"**العضو:** {strict_mem.mention}\n**بواسطة:** {author.mention}")
    elif action_name == "BAN":
      strict_mem = await resolve_natural_target_member(bot, message, message.content or "", strict_target=True)
      if not (strict_mem and can_moderate_member(actor, strict_mem, guild)[0]):
        raise _ActionBlocked
      await strict_mem.ban(reason=f"AI Order by {author}")
      await bot.send_modlog(guild, "🔨 حظر عضو", f"**العضو:** {strict_mem.mention}\n**بواسطة:** {author.mention}", color=discord.Color.red().value)
    elif action_name == "TIMEOUT":
      strict_mem = await resolve_natural_target_member(bot, message, message.content or "", strict_target=True)
      if not (strict_mem and can_moderate_member(actor, strict_mem, guild)[0]):
        raise _ActionBlocked
      mins = max(1, min(40320, int(params.get("minutes", "15"))))
      await strict_mem.timeout(timedelta(minutes=mins), reason=f"AI Order by {author}")
      await bot.send_modlog(guild, "⏳ كتم عضو", f"**العضو:** {strict_mem.mention} (`{mins}m`)\n**بواسطة:** {author.mention}")
    elif action_name == "UNTIMEOUT":
      if not (target_member and can_moderate_member(actor, target_member, guild)[0]):
        raise _ActionBlocked
      await target_member.timeout(None, reason=f"AI Order by {author}")
    elif action_name == "WARN":
      if not (target_member and can_moderate_member(actor, target_member, guild)[0]):
        raise _ActionBlocked
      rsn = params.get("reason", "توجيه إداري")
      await bot.db.add_warning(guild.id, target_member.id, author.id, rsn)
    elif action_name == "CLEAR_WARNINGS":
      if not (target_member and can_moderate_member(actor, target_member, guild)[0]):
        raise _ActionBlocked
      await bot.db.clear_warnings(guild.id, target_member.id)
    elif action_name == "UNBAN":
      uid_str = params.get("user_id") or ""
      if not uid_str:
        m_id = re.search(r"\b(\d{17,20})\b", message.content or "")
        if m_id:
          uid_str = m_id.group(1)
      if uid_str.isdigit():
        await guild.unban(discord.Object(id=int(uid_str)), reason=f"AI Order by {author}")
    elif action_name == "AUTOROLE":
      r_obj = resolve_natural_role(guild, message, params.get("role", ""))
      if not (r_obj and can_assign_role(actor, r_obj, guild)[0]):
        raise _ActionBlocked
      await bot.db.set_autorole(guild.id, r_obj.id)
      bot.autorole_cache[guild.id] = r_obj.id
    elif action_name == "DELETE_CHANNEL":
      target_ch = resolve_natural_text_channel(guild, message, params.get("name", ""))
      if target_ch:
        await target_ch.delete(reason=f"AI Order by {author}")
    elif action_name == "RENAME_CHANNEL":
      new_name = params.get("name")
      if new_name:
        target_ch = resolve_natural_text_channel(guild, message)
        if not target_ch and guild.id in bot.last_target_channel:
          target_ch = guild.get_channel(bot.last_target_channel[guild.id])
        target_ch = target_ch or message.channel
        await target_ch.edit(name=new_name)
    elif action_name == "CLONE_CHANNEL":
      target_ch = resolve_natural_text_channel(guild, message) or message.channel
      cloned = await target_ch.clone(reason=f"Cloned by {author}")
      bot.last_target_channel[guild.id] = cloned.id
    elif action_name == "SET_TOPIC":
      topic_txt = params.get("topic") or params.get("name")
      if topic_txt and isinstance(message.channel, discord.TextChannel):
        await message.channel.edit(topic=topic_txt[:1024])
    elif action_name == "CREATE_TEXT":
      name = params.get("name")
      if name:
        ch = await guild.create_text_channel(name=name)
        bot.last_target_channel[guild.id] = ch.id
    elif action_name == "CREATE_VOICE":
      name = params.get("name")
      if name:
        ch = await guild.create_voice_channel(name=name)
        bot.last_target_channel[guild.id] = ch.id
    elif action_name == "ADD_ROLE":
      r_obj = resolve_natural_role(guild, message, params.get("role", ""))
      if not (r_obj and target_member and can_assign_role(actor, r_obj, guild)[0]
              and can_moderate_member(actor, target_member, guild)[0]):
        raise _ActionBlocked
      await target_member.add_roles(r_obj)
    elif action_name == "REMOVE_ROLE":
      r_obj = resolve_natural_role(guild, message, params.get("role", ""))
      if not (r_obj and target_member and can_assign_role(actor, r_obj, guild)[0]
              and can_moderate_member(actor, target_member, guild)[0]):
        raise _ActionBlocked
      await target_member.remove_roles(r_obj)
    elif action_name == "CREATE_ROLE":
      r_name = params.get("name")
      if r_name:
        await guild.create_role(name=r_name, color=discord.Color.from_rgb(212, 175, 55))
    elif action_name == "NICKNAME":
      new_nick = params.get("name", "")[:32]
      t_mem = target_member or (author if isinstance(author, discord.Member) else None)
      if not (t_mem and new_nick and can_moderate_member(actor, t_mem, guild)[0]):
        raise _ActionBlocked
      await t_mem.edit(nick=new_nick)
    elif action_name == "LOCK":
      target_ch = resolve_natural_text_channel(guild, message) or message.channel
      overwrite = target_ch.overwrites_for(guild.default_role)
      overwrite.send_messages = False
      await target_ch.set_permissions(guild.default_role, overwrite=overwrite)
    elif action_name == "UNLOCK":
      target_ch = resolve_natural_text_channel(guild, message) or message.channel
      overwrite = target_ch.overwrites_for(guild.default_role)
      overwrite.send_messages = None
      await target_ch.set_permissions(guild.default_role, overwrite=overwrite)
    elif action_name == "HIDE":
      target_ch = resolve_natural_text_channel(guild, message) or message.channel
      overwrite = target_ch.overwrites_for(guild.default_role)
      overwrite.view_channel = False
      await target_ch.set_permissions(guild.default_role, overwrite=overwrite)
    elif action_name == "UNHIDE":
      target_ch = resolve_natural_text_channel(guild, message) or message.channel
      overwrite = target_ch.overwrites_for(guild.default_role)
      overwrite.view_channel = None
      await target_ch.set_permissions(guild.default_role, overwrite=overwrite)
    elif action_name == "SLOWMODE":
      sec = max(0, min(21600, int(params.get("seconds", "5"))))
      await message.channel.edit(slowmode_delay=sec)
    elif action_name == "PURGE":
      val = max(1, min(100, int(params.get("value", "15"))))
      await message.channel.purge(limit=val + 1)
    else:
      # An action the model named but this dispatcher has no branch for (MOVE_TO_ME,
      # VOICE_MUTE, PIN_MSG, ...) did nothing; reporting "executed" would be a false success.
      logger.warning(f"AI inferred action has no handler: {action_name}")
      return "failed"
    return "executed"
  except _ActionBlocked:
    logger.warning(f"AI inferred action blocked by authorization ({action_name})")
    return "blocked"
  except Exception as exc:
    logger.warning(f"AI inferred action warning ({action_name}): {exc}")
    return "failed"


def parse_arabic_duration_minutes(text: str, default_mins: int = 10) -> int:
  """Parse numeric and spoken Arabic time durations into minutes (supports fractions & spoken numbers)."""
  lower = normalize_arabic_text(text.lower())
  text_no_mentions = re.sub(r"<@!?\d+>", "", lower)
  text_no_mentions = re.sub(r"<#\d+>", "", text_no_mentions)
  text_no_mentions = re.sub(r"\b\d{17,20}\b", "", text_no_mentions)

  if "اسبوعين" in lower or "أسبوعين" in lower:
    return 20160
  if "اسبوع" in lower or "أسبوع" in lower or "week" in lower:
    return 10080
  if "يومين" in lower:
    return 2880
  if "نص يوم" in lower or "نصف يوم" in lower:
    return 720
  if "ساعة ونص" in lower or "ساعه ونص" in lower:
    return 90
  if "ساعتين" in lower:
    return 120
  if "نص ساعة" in lower or "نص ساعه" in lower or "نصف ساعة" in lower:
    return 30
  if "ربع ساعة" in lower or "ربع ساعه" in lower:
    return 15
  if "ثلث ساعة" in lower or "ثلث ساعه" in lower:
    return 20
  if "دقيقتين" in lower:
    return 2
  if "خمس دقايق" in lower or "خمس دقائق" in lower:
    return 5
  if "عشر دقايق" in lower or "عشر دقائق" in lower:
    return 10

  nums = [int(n) for n in re.findall(r"\b(\d+)\b", text_no_mentions)]
  val = nums[0] if nums else None

  if any(w in lower for w in ("يوم", "ايام", "أيام", "day")):
    return max(1, min(40320, (val * 1440) if val else 1440))
  if any(w in lower for w in ("ساعة", "ساعه", "ساعات", "hour", "hr")):
    return max(1, min(40320, (val * 60) if val else 60))
  if any(w in lower for w in ("ثانية", "ثانيه", "ثواني", "sec")):
    return 1
  if val is not None:
    return max(1, min(40320, val))
  return default_mins


async def try_execute_custom_action_trigger(bot, message: discord.Message) -> bool:
  guild = message.guild
  if not guild:
    return False

  if guild.id not in bot.action_triggers_cache:
    bot.action_triggers_cache[guild.id] = await bot.db.get_action_triggers(guild.id)

  triggers = bot.action_triggers_cache.get(guild.id, {})
  if not triggers:
    return False

  content_no_mentions = re.sub(r"<@!?\d+>", "", message.content).strip().lower()
  full_lower = message.content.strip().lower()

  def _phrase_hit(text: str, phrase: str) -> bool:
    # Word boundaries: a trigger "قفل" must not fire on "قفلت الباب". Arabic letters are \w,
    # so the lookarounds keep the phrase from matching inside a longer word.
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None

  matched_cfg = None
  for phrase, cfg in triggers.items():
    if _phrase_hit(content_no_mentions, phrase) or _phrase_hit(full_lower, phrase):
      matched_cfg = cfg
      break

  if not matched_cfg:
    return False

  author = message.author
  mistress = is_mistress(author)
  act = matched_cfg["action_type"]
  pval = int(matched_cfg.get("param_value") or 15)
  custom_reply = (matched_cfg.get("custom_reply") or "").strip()

  await bot.db.increment_trigger_usage(guild.id, matched_cfg["phrase"])
  if matched_cfg["phrase"] in bot.action_triggers_cache.get(guild.id, {}):
    bot.action_triggers_cache[guild.id][matched_cfg["phrase"]]["usage_count"] = (
        bot.action_triggers_cache[guild.id][matched_cfg["phrase"]].get("usage_count", 0) + 1
    )

  if act == "reply":
    if custom_reply:
      await safe_reply(message, custom_reply)
      return True
    return False

  if not check_staff_action_permission(author, guild, act):
    return False

  strict_req = act in ("kick", "ban", "timeout")
  target_member = await resolve_natural_target_member(bot, message, message.content or "", strict_target=strict_req)

  try:
    if act in ("kick", "ban", "timeout", "untimeout", "warn") and target_member:
      ok_mod, deny_mod = can_moderate_member(author, target_member, guild)
      if not ok_mod:
        await safe_reply(message, deny_mod)
        return True

    if act == "kick" and target_member:
      await target_member.kick(reason=f"Trigger ({matched_cfg['phrase']}) by {author}")
      await safe_reply(message, custom_reply or angel_spontaneous_confirm(author, "kick", f"👢 تم طرد {target_member.mention}."))
      await bot.send_modlog(guild, "👢 طرد عبر اختصار", f"**العضو:** {target_member.mention}\n**بواسطة:** {author.mention}")
      return True

    if act == "ban" and target_member:
      async def _run_trigger_ban(confirm_message, _tid=target_member.id, _reply=custom_reply, bot=bot):
        actor = confirm_message.author
        if not (is_mistress(actor) or getattr(actor.guild_permissions, "ban_members", False)):
          return "🚫 ما نفذت الحظر: صلاحيتك تغيّرت."
        target = await _fresh_target(guild, _tid)
        if target is None:
          return "⚠️ العضو لم يعد موجوداً."
        ok_mod, deny_mod = can_moderate_member(actor, target, guild)
        if not ok_mod:
          return deny_mod
        try:
          await target.ban(reason=f"Trigger ({matched_cfg['phrase']}) by {actor} (confirmed)")
        except Exception:
          return "⚠️ لا أستطيع حظر هذا العضو (رتبته أعلى من رتبتي)."
        await bot.send_modlog(guild, "🔨 حظر عبر اختصار", f"**العضو:** {target.mention}\n**بواسطة:** {actor.mention}", color=discord.Color.red().value)
        return _reply or angel_spontaneous_confirm(actor, "ban", f"🔨 تم حظر {target.mention}.")

      await safe_reply(message, queue_confirmation(
          bot,
          guild_id=guild.id,
          author_id=author.id,
          channel_id=message.channel.id,
          summary=f"حظر {target_member.mention} عبر الاختصار «{matched_cfg['phrase']}»",
          run=_run_trigger_ban,
      ))
      return True

    if act == "timeout" and target_member:
      await target_member.timeout(timedelta(minutes=max(1, pval)), reason=f"Trigger by {author}")
      await safe_reply(message, custom_reply or angel_spontaneous_confirm(author, "timeout", f"⏳ تم كتم {target_member.mention} لمدة **{pval} دقيقة**."))
      await bot.send_modlog(guild, "⏳ كتم عبر اختصار", f"**العضو:** {target_member.mention} (`{pval}m`)\n**بواسطة:** {author.mention}")
      return True

    if act == "untimeout" and target_member:
      await target_member.timeout(None, reason=f"Trigger by {author}")
      await safe_reply(message, custom_reply or angel_spontaneous_confirm(author, "untimeout", f"🔊 تم رفع الكتم عن {target_member.mention}."))
      return True

    if act == "warn" and target_member:
      total = await bot.db.add_warning(guild.id, target_member.id, author.id, matched_cfg["phrase"])
      await safe_reply(message, custom_reply or angel_spontaneous_confirm(author, "warn", f"⚠️ تم توجيه إنذار إلى {target_member.mention} (الإجمالي: `{total}`)."))
      return True

    if act == "add_harem" and mistress and target_member:
      await bot.db.add_harem_member(target_member.id, target_member.display_name, custom_reply or "الحريم")
      bot.harem_cache = await bot.db.get_all_harem_members()
      await safe_reply(message, f"💖 تم ضم {target_member.mention} إلى قائمة الحريم.")
      return True

    if act == "purge":
      async def _run_trigger_purge(confirm_message, _limit=max(1, min(100, pval)), _reply=custom_reply, bot=bot):
        actor = confirm_message.author
        if not (is_mistress(actor) or getattr(actor.guild_permissions, "manage_messages", False)):
          return "🚫 ما نفذت المسح: صلاحيتك تغيّرت."
        try:
          deleted = await confirm_message.channel.purge(limit=_limit + 1)
        except Exception:
          return "⚠️ أحتاج لصلاحية `Manage Messages` في هذه القناة."
        return _reply or f"🧹 تم مسح **{max(1, len(deleted)-1)}** رسالة."

      await safe_reply(message, queue_confirmation(
          bot,
          guild_id=guild.id,
          author_id=author.id,
          channel_id=message.channel.id,
          summary=f"مسح {max(1, min(100, pval))} رسالة عبر الاختصار «{matched_cfg['phrase']}»",
          run=_run_trigger_purge,
      ))
      return True

    if act == "lock":
      overwrite = message.channel.overwrites_for(guild.default_role)
      overwrite.send_messages = False
      await message.channel.set_permissions(guild.default_role, overwrite=overwrite)
      await safe_reply(message, custom_reply or angel_spontaneous_confirm(author, "channel", "🔒 تم قفل القناة."))
      return True

    if act == "unlock":
      overwrite = message.channel.overwrites_for(guild.default_role)
      overwrite.send_messages = None
      await message.channel.set_permissions(guild.default_role, overwrite=overwrite)
      await safe_reply(message, custom_reply or angel_spontaneous_confirm(author, "channel", "🔓 تم فتح القناة."))
      return True
  except Exception as exc:
    logger.warning(f"Custom trigger execution error: {exc}")
    await safe_reply(message, "⚠️ تعذر تنفيذ الاختصار؛ تأكد من صلاحيات البوت وترتيب الرتب.")
    return True

  return False


_COMPOUND_CMD_SPLIT_RE = re.compile(
    r"\s+(?:وبعدين|ثم|وبعدها|و\s*(?=(?:اقفل|قفل|افتح|امسح|احذف|نظف|اخف|اظهر|شغل|وقف|تخط|ادخل|اخرج|اسحب|اعط|شيل|بند|اطرد|اكتم|فك|ثبت|غير|سمي)))\s*",
    re.IGNORECASE,
)


async def try_execute_natural_command(
    bot, message: discord.Message, clean_text: str, _depth: int = 0
) -> bool:
  author = message.author
  guild = message.guild
  mistress = is_mistress(author)

  cmd_body = re.sub(
      r"^(?:يا\s*)?(?:انجل|أنجل|إنجل|نجل|angel)[\s،,.!؟:]*",
      "",
      clean_text.strip(),
      flags=re.IGNORECASE,
  ).strip()
  harem_title_fast = bot.get_harem_title(author.id)
  if not cmd_body or normalize_arabic_text(cmd_body.lower()) in ("هلا", "اهلين", "أهلين", "هاي", "موجودة", "موجوده", "تسمعيني"):
    if not message.attachments:
      if mistress:
        greetings = [
            "هلا بقلبي، قولي وش في خاطرك؟ ✨",
            "عيوني لك، سولفي لي 💖",
            "معك عالخط ياحلوة، وش بغيتي؟ 🪽",
            "هلا والله، اسمعك كلي لك ✨",
        ]
      elif harem_title_fast:
        greetings = [
            "هلا والله بجميلتنا، قولي وش بخاطرك؟ 💖",
            "معك يا جميلة، سولفي لي ✨",
            "عيوني، وش بغيتي؟ 🪽",
        ]
      else:
        greetings = [
            "نعم؟ اختصر.",
            "أسمعك، وش عندك؟",
            "تفضل، وش بغيت؟",
        ]
      if guild:
        bot.active_chat_window[(message.channel.id, author.id)] = time.monotonic()
      await safe_reply(message, random.choice(greetings))
      return True
    return False

  # Support compound/chained natural commands (e.g. "انجل اقفلي الشات وامسحي 15 رسالة")
  if _depth == 0 and "\n" not in cmd_body:
    sub_cmds = [s.strip() for s in _COMPOUND_CMD_SPLIT_RE.split(cmd_body) if s.strip()]
    if 1 < len(sub_cmds) <= 3:
      any_executed = False
      for sub_c in sub_cmds:
        if await try_execute_natural_command(bot, message, sub_c, _depth=1):
          any_executed = True
      if any_executed:
        return True

  cmd_lower = normalize_arabic_text(cmd_body.lower())

  # 0. A destructive action is waiting for this human's confirmation (finding 14).
  confirm_key = (guild.id, author.id) if guild else None
  if confirm_key:
    verdict, pending = take_confirmation(
        bot,
        guild_id=guild.id,
        author_id=author.id,
        channel_id=message.channel.id,
        text=cmd_lower,
    )
    if verdict == WRONG_CHANNEL:
      await safe_reply(message, "⚠️ التأكيد لازم يكون في نفس القناة اللي طُلب فيها الإجراء. ألغيته.")
      return True
    if verdict == CONFIRMED:
      run = (pending or {}).get("run")
      if run is not None:
        try:
          outcome_text = await run(message)
        except Exception as exc:  # noqa: BLE001 - a confirmed action must report, not crash
          logger.warning("confirmed action failed: %s: %s", type(exc).__name__, exc)
          outcome_text = "⚠️ تعذر تنفيذ الإجراء المؤكد. راجعي السجل."
        await safe_reply(message, outcome_text)
        return True
      # Re-resolve the confirmer's CURRENT membership: the retained requester snapshot
      # keeps its old role list, so a moderator who lost the role inside the window
      # would otherwise still execute (CWE-863). The fresh confirmation message carries
      # the gateway's current member payload; one REST fetch makes it authoritative.
      confirm_actor = message.author
      if isinstance(message.author, discord.Member):
        try:
          fetched_actor = await guild.fetch_member(author.id)
          if isinstance(fetched_actor, discord.Member):
            confirm_actor = fetched_actor
        except discord.HTTPException:
          pass  # fall back to the confirmation message's member payload
      outcome = await execute_ai_inferred_action(
          bot, pending["message"], pending["cmd"], confirmed=True, actor=confirm_actor
      )
      if outcome == "executed":
        await safe_reply(message, "✅ تم تنفيذ الإجراء المؤكد.")
      elif outcome == "blocked":
        await safe_reply(message, "🚫 ما نفذت الإجراء: الصلاحية أو الرتبة ما تسمح الآن.")
      else:
        await safe_reply(message, "⚠️ تعذر تنفيذ الإجراء المؤكد. راجعي السجل.")
      return True
    if verdict == EXPIRED:
      await safe_reply(message, "⌛ انتهت مهلة التأكيد، ما نفذت شيئاً. أطلبي الإجراء من جديد.")
      return True
    if verdict == CANCELLED:
      await safe_reply(message, "✅ ألغيت الإجراء المعلّق.")
      return True

  # 0. Check scoped pending step (keyed by (guild_id, user_id) with 90s TTL & permission re-verification)
  pending_key = (guild.id, author.id) if guild else None
  if pending_key and pending_key in bot.pending_step:
    step_data = bot.pending_step.pop(pending_key)
    step_type = step_data["type"] if isinstance(step_data, dict) else str(step_data)
    created_at = step_data.get("created_at") if isinstance(step_data, dict) else time.monotonic()
    if created_at is None:
      created_at = 0.0
    if time.monotonic() - created_at <= 90.0:
      if cmd_lower in ("الغاء", "إلغاء", "كنسل", "cancel"):
        await safe_reply(message, "✅ تم إلغاء عملية إنشاء الروم.")
        return True
      if not (mistress or (isinstance(author, discord.Member) and author.guild_permissions.manage_channels)):
        await safe_reply(message, "⚡ لا تملك صلاحية إدارة القنوات في هذا السيرفر.")
        return True
      room_name = re.sub(r"^(?:باسم|بأسم|اسمه|إسمه|سميه|خليه)\s*", "", cmd_body).strip()[:90]
      if room_name:
        try:
          if step_type == "voice":
            ch = await guild.create_voice_channel(name=room_name, reason=f"By {author}")
            bot.last_target_channel[guild.id] = ch.id
            await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ أنشأت الروم الصوتي الجديد: {ch.mention}"))
          else:
            ch = await guild.create_text_channel(name=room_name, reason=f"By {author}")
            bot.last_target_channel[guild.id] = ch.id
            await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ أنشأت الروم الجديد: {ch.mention}"))
          return True
        except Exception:
          await safe_reply(message, "⚠️ أحتاج لصلاحية `Manage Channels` لإنشاء الروم.")
          return True

  # 1. Memory Vault & Style Mode via Natural Chat ("انجل تذكري دايما اني ..." / "انجل انسي ..." / "انجل خلي اسلوبك مشاكس")
  pin_fact_m = re.match(
      r"^(?:تذكري|احفظي|ثبتي)(?:\s+عندي|\s+عندك|\s+في\s+ذاكرتك|\s+دايما|\s+دائما|\s+دائماً)?(?:\s+ان|\s+أن|\s+اني|\s+أني|\s*:)?\s+(.+)$",
      cmd_body,
      re.IGNORECASE,
  )
  if pin_fact_m and not any(w in cmd_lower for w in ("رسالة", "الرسالة", "الشات", "روم", "قوانين السيرفر", "معرفة السيرفر")):
    fact_str = pin_fact_m.group(1).strip()
    if len(fact_str) >= 3:
      await bot.db.pin_user_fact(author.id, fact_str)
      await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"📌 حفظتها في بالي ومستحيل أنساها: **{fact_str}**"))
      return True

  forget_m = re.match(r"^(?:انسي|إنسى|احذفي\s+من\s+ذاكرتك)\s+(?:كلمة|معلومة|سيرة)?\s*(.+)$", cmd_body, re.IGNORECASE)
  if forget_m:
    kw_forget = forget_m.group(1).strip()
    if kw_forget in ("كل شي", "كل شيء", "المحادثة", "السجل", "ذاكرتي"):
      await bot.db.clear_user_memory(message.channel.id, author.id)
      await safe_reply(message, "🧹 مسحت سجل محادثتنا المؤقت ونبدأ صفحة جديدة.")
    elif guild:
      # The deletion is irreversible and substring-matched, so it needs the same explicit
      # confirmation as `/memory forget` (typed anywhere, it used to run immediately).
      # Keyed by guild+author and bound to this channel exactly like a pending EXEC.
      bot.pending_confirm[(guild.id, author.id)] = {
          "cmd": f"FORGET_KEYWORD|kw={kw_forget[:200]}",
          "message": message,
          "channel_id": message.channel.id,
          "ts": time.monotonic(),
      }
      await safe_reply(
          message,
          f"⚠️ سيُحذف كل ذكر لـ **({kw_forget[:60]})** من محادثاتك وأرشيف السيرفر وملاحظاتك، "
          "ولا يمكن التراجع. اكتبي **تأكيد** خلال 60 ثانية لتنفيذه، أو أي كلمة أخرى للإلغاء.",
      )
    else:
      await bot.db.forget_user_keyword(author.id, kw_forget)
      await safe_reply(message, f"🗑️ مسحت أي ذكر لـ **({kw_forget})** من ذاكرتي.")
    return True

  if any(k in cmd_lower for k in ("صفري ذاكرتي", "امسحي ذاكرتي", "امسحي سجل محادثتنا", "نسيتيني")):
    await bot.db.clear_user_memory(message.channel.id, author.id)
    await safe_reply(message, "🧹 تم تصفير سجل المحادثة المؤقت بنجاح.")
    return True

  style_m = re.search(
      r"(?:خلي|غيري|اضبطي)\s+(?:اسلوبك|أسلوبك|طريقتك|مودك)\s*(?:معي\s+)?(?:الى|إلى|لـ|يكون)?\s*(واقعي|عفوي|طبيعي|مشاكس|مرح|دلع|دلوع|دافئ|حنون|مختصر|مباشر|بارد|حاد)",
      cmd_lower,
  )
  if style_m:
    st_word = style_m.group(1)
    st_map = {
        "واقعي": "realistic", "عفوي": "realistic", "طبيعي": "realistic",
        "مشاكس": "playful", "مرح": "playful", "دلع": "playful", "دلوع": "playful",
        "دافئ": "warm", "حنون": "warm",
        "مختصر": "concise", "مباشر": "concise",
        "بارد": "cold", "حاد": "cold",
    }
    chosen_st = st_map.get(st_word, "realistic")
    await bot.db.set_user_style(author.id, chosen_st)
    await safe_reply(message, f"🎭 تم! غيرت أسلوبي معكِ إلى نمط **`{chosen_st}`** ({st_word}).")
    return True

  # 1.8 AFK via Natural Chat ("انجل انا برب ...")
  afk_m = re.match(
      r"^(?:انا\s+)?(?:برب|افك|غايبة|غايب|مشغولة|مشغول|سجليني\s+غايبة|سجلني\s+غايب|afk)(?:\s+(.+))?$",
      cmd_body,
      re.IGNORECASE,
  )
  if afk_m:
    rsn = (afk_m.group(1) or "مشغولة حالياً").strip()
    stored = await bot.db.set_afk(guild.id if guild else 0, author.id, rsn)
    if stored:
      bot.afk_cache[(guild.id if guild else 0, author.id)] = (
          rsn, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
      await safe_reply(message, f"💤 تم تفعيل وضع الغياب (AFK): **{rsn}** — خذي راحتك!")
    else:
      # An opted-out member keeps no AFK state; the DB guard and the cache agree.
      await safe_reply(message, "💤 وضع الغياب محفوظ لك مؤقتاً فقط، لأنك أوقفت حفظ بياناتك.")
    return True

  # 2. Direct Image Generation in Chat (with Art Studio buttons)
  img_req_match = re.match(
      r"^(?:انشئ|انشئي|أنشئي|ارسم|ارسمي|صمم|صممي|سوي|اعطيني|عطيني|ابغى|ابي)?\s*(?:لي\s+)?(?:صورة|صوره|رسمة|رسمه|لوحة|لوحه)\s+(.+)$",
      cmd_body,
      re.IGNORECASE | re.DOTALL,
  )
  if img_req_match and not any(w in cmd_lower for w in ("روم", "قناة", "شات", "رتبة", "افاتار", "افتار", "بروفايل")):
    art_prompt = img_req_match.group(1).strip()
    harem_title = bot.get_harem_title(author.id)
    allowed, deny_reason = bot.quota.check_user_allowed(author, is_harem=(harem_title is not None))
    if not allowed:
      await safe_reply(message, deny_reason)
      return True
    async with message.channel.typing():
      try:
        img_bytes, _ = await bot.ai.generate_image_bytes(art_prompt)
        file = discord.File(io.BytesIO(img_bytes), filename="angel_art.png")
        caption = "🎨 هذي الرسمة جهزتها لكِ على ذوقك:" if (mistress or harem_title) else "🎨 هذه اللوحة التي طلبتها:"
        await safe_reply(message, content=caption, file=file, view=ArtStudioView(art_prompt, bot, getattr(message.author, "id", 0)))
      except Exception as exc:
        await safe_reply(message, f"⚠️ {exc}")
    return True

  # Resolve target member (from @mention, Reply, User ID, or Fuzzy Name)
  target_member: Optional[discord.Member] = await resolve_natural_target_member(bot, message, cmd_body)
  raw_mentions = [u for u in message.mentions if not bot.user or u.id != bot.user.id]
  target_user_any: Optional[discord.abc.User] = target_member or (raw_mentions[0] if raw_mentions else None)

  # 2.5 Secret Name Query for Mistress (Only when she explicitly asks "وش اسمي عندك" / "وش تناديني")
  if mistress and any(k in cmd_lower for k in ("وش اسمي عندك", "ايش اسمي عندك", "شو اسمي عندك", "وش سميتيني", "وش تناديني بيني وبينك")):
    await safe_reply(message, "اسمكِ بقلبي هو **اليقين**.. بس مخليته سر بيننا زي ما تحبين 💖")
    return True

  # 2.8 Direct Social & Affection GIF Actions in Chat ("انجل اعطي @فلانة بوسة / بوسة خدود / بوسة عفيفة / حضن / كف")
  social_verb_hit = any(
      sv in cmd_lower
      for sv in ("اعطي", "أعطي", "عطي", "اعطيها", "عطيها", "اعطيه", "عطيه", "بوسي", "بوسيلي", "احضني", "ضمي", "طبطبي", "اصفعي", "اضربي", "اركلي", "عضي")
  )
  social_noun_hit = any(
      sn in cmd_lower
      for sn in ("بوسة", "بوسه", "قبلة", "قبله", "حضن", "عناق", "طبطبة", "طبطبه", "دلال", "كف", "صفعة", "صفعه", "ركلة", "ركله", "عضة", "عضه")
  )
  standalone_affection_hit = cmd_lower in (
      "بوسة", "بوسه", "قبلة", "قبله", "بوسيني", "عطيني بوسة", "عطيني بوسه", "ابغى بوسة", "ابغى بوسه", "ابي بوسة", "ابي بوسه",
      "حضن", "عناق", "احضنيني", "ضميني", "عطيني حضن", "ابغى حضن", "طبطبة", "طبطبه", "طبطبي علي",
  ) or (social_noun_hit and len(cmd_lower.split()) <= 3 and not any(q in cmd_lower for q in ("ليش", "كيف", "متى", "وش", "ايش", "معنى")))
  if (social_verb_hit and social_noun_hit) or standalone_affection_hit or any(
      direct_w in cmd_lower for direct_w in ("بوسة خدود", "بوسه خدود", "بوسة خد", "بوسه خد", "بوسة عفيفة", "بوسه عفيفه", "بوسيها", "احضنيها", "ضميها", "بوسيني", "احضنيني", "ضميني")
  ):
    if not any(admin_w in cmd_lower for admin_w in ("رتبة", "رول", "انذار", "تحذير", "ميوت", "باند", "كيك", "صلاحية", "سمعة")):
      is_fem = mistress or (bot.get_harem_title(author.id) is not None)
      if any(ck in cmd_lower for ck in ("خدود", "خد", "عفيفة", "عفيفه", "بريئة", "بريئه", "جبين", "راس")):
        s_action = "cheek_kiss"
        s_lines = [
            "وهذي أحلى بوسة خد لطيفة وعفيفة عالسريع ☺️💖",
            "بوسة خد ناعمة وخفيفة لعيونك ✨",
            "تستاهل بوسة خد لطيفة ومؤدبة 🌸",
        ]
      elif any(hk in cmd_lower for hk in ("حضن", "عناق", "احضني", "ضمي")):
        s_action = "yuri_hug" if is_fem else "hug"
        s_lines = [
            "أدفى وأطيب حضن لعيونك 🫂💖",
            "تعالي هنا، حضن دافي يرد الروح ✨",
            "أحلى عناق من القلب 🌸",
        ]
      elif any(pk in cmd_lower for pk in ("طبطب", "ربت")):
        s_action = "pat"
        s_lines = ["طبطبة لطيفة وحنونة 🌸", "تستاهل أحلى طبطبة ✨"]
      elif any(sk in cmd_lower for sk in ("كف", "صفع", "اضرب")):
        s_action = "slap"
        s_lines = ["وهذا كف يصحصحك مضبوط! 👋😌", "طلبتيها وجاتك عالسريع 👋✨"]
      elif any(kk in cmd_lower for kk in ("ركل", "اركل", "شوت")):
        s_action = "kick"
        s_lines = ["وهذي شوتة سريعة! 🦵😌"]
      elif any(bk in cmd_lower for bk in ("عضة", "عضه", "عضي")):
        s_action = "bite"
        s_lines = ["عضة خفيفة عشان تنتبهين! 😌✨"]
      else:
        s_action = "yuri_kiss" if is_fem else "kiss"
        s_lines = [
            "وهذي أحلى بوسة لعيونك، ما أرد لكِ طلب 😉💖",
            "تستاهل بوسة حلوة عشان خاطركِ بس ✨",
            "دام الطلب منكِ، هذي بوسة خاصة عالسريع 💋",
        ]

      if is_romantic_gif(s_action) and not is_fem:
        await safe_reply(message, f"🪽 {author.mention} {guard.refusal_line()}")
        return True

      gif_b, gif_u = await bot.ai.fetch_anime_gif_data(
          s_action, for_female_pair=is_fem, allow_romantic=is_fem)
      target_disp = f" إلى {target_user_any.mention}" if target_user_any else ""
      chosen_line = random.choice(s_lines) if (mistress or is_fem) else f"🪽 {author.mention}{target_disp}"
      emb = discord.Embed(
          description=f"{chosen_line}\n🪽 {author.mention}{target_disp}" if target_user_any else chosen_line,
          color=0xD4AF37 if is_fem else 0x2B2D31,
      )
      if guild:
        bot.active_chat_window[(message.channel.id, author.id)] = time.monotonic()
      if gif_b:
        f_obj = discord.File(io.BytesIO(gif_b), filename="angel_reaction.gif")
        emb.set_image(url="attachment://angel_reaction.gif")
        await safe_reply(message, embed=emb, file=f_obj)
      elif gif_u:
        emb.set_image(url=gif_u)
        await safe_reply(message, embed=emb)
      else:
        await safe_reply(message, chosen_line)
      return True

  # 2.9 Conversational QoL Tools: Quick Choice, Coinflip, Dice, Ship/Compatibility
  choice_m = re.match(
      r"^(?:اختاري|وش\s+اختار|ايش\s+اختار|محتارة\s+بين|محتار\s+بين|خيريني\s+بين)\s+(?:بين\s+)?(.+)$",
      cmd_body,
      re.IGNORECASE,
  )
  if choice_m:
    raw_c = choice_m.group(1).strip()
    c_parts = [x.strip() for x in re.split(r"\s+(?:ولا|أو|او|ام|أم|\||/|-|،|,)\s+", raw_c) if x.strip()]
    if len(c_parts) >= 2:
      picked = random.choice(c_parts)
      await safe_reply(message, f"🎲 بدون تفكير طويل.. أختار لكِ: **{picked}** ✨")
      return True

  if any(k in cmd_lower for k in ("ارمي عملة", "ارمي قرش", "قرعة", "حجرة ورقة مقص", "نرد", "ارمي نرد")):
    if "نرد" in cmd_lower:
      await safe_reply(message, f"🎲 رميت النرد وطلع لك الرقم: **`{random.randint(1, 6)}`**!")
    else:
      side = random.choice(["صورة (Heads) 🪙", "كتابة (Tails) 🪙"])
      await safe_reply(message, f"🪙 رميت العملة بالهواء وطلعت: **{side}**!")
    return True

  if any(k in cmd_lower for k in ("نسبة التوافق", "كم نسبة التوافق", "نسبة الحب")):
    u1 = raw_mentions[0] if len(raw_mentions) >= 1 else author
    u2 = raw_mentions[1] if len(raw_mentions) >= 2 else (target_user_any or author)
    seed_val = (u1.id ^ u2.id) + int(datetime.now(timezone.utc).strftime("%Y%m%d"))
    pct = 98 if (is_mistress(u1) or is_mistress(u2)) else (55 + (seed_val % 45))
    bar = "💖" * (pct // 10) + "🤍" * (10 - (pct // 10))
    await safe_reply(message, f"💞 **نسبة التوافق بين {u1.display_name} و {u2.display_name}:** **`{pct}%`**\n{bar}")
    return True

  # 3. Sovereign Owner Exclusive Natural Commands (Harem, Puppet Say, DM Send, DM Logs, Server List)
  if mistress:
    if any(k in cmd_lower for k in ("قائمة الحريم", "وريني الحريم", "من في الحريم", "اعرضي الحريم")):
      bot.harem_cache = await bot.db.get_all_harem_members()
      if not bot.harem_cache:
        await safe_reply(message, "📭 قائمة الحريم فاضية حالياً.")
        return True
      lines = [f"💖 <@{uid}> (`{info['display_name']}`) — **{info['custom_title']}**" for uid, info in bot.harem_cache.items()]
      embed = discord.Embed(title=f"💖 قائمة الحريم ({len(lines)})", description="\n".join(lines), color=0xD4AF37)
      await safe_reply(message, embed=embed)
      return True

    if target_user_any and any(k in cmd_lower for k in ("ضيفي", "اضفي", "أضيفي", "ضمي", "ضم", "حطي")) and any(
        h in cmd_lower for h in ("حريم", "الحريم", "حريمي")
    ):
      await bot.db.add_harem_member(target_user_any.id, target_user_any.display_name, "الحريم")
      bot.harem_cache = await bot.db.get_all_harem_members()
      await safe_reply(message, f"💖 من عيوني! ضميت {target_user_any.mention} إلى قائمة الحريم الخاصة فينا.")
      return True

    if target_user_any and any(k in cmd_lower for k in ("احذفي", "شيلي", "ازيلي", "أزيلي", "اطردي", "طلعي")) and any(
        h in cmd_lower for h in ("حريم", "الحريم", "حريمي")
    ):
      await bot.db.remove_harem_member(target_user_any.id)
      bot.harem_cache = await bot.db.get_all_harem_members()
      await safe_reply(message, f"✅ طلعت {target_user_any.mention} من قائمة الحريم.")
      return True

    # Puppet Say via Chat ("انجل قولي في الشات ..." / "انجل قولي في #العام ...")
    puppet_m = re.match(
        r"^(?:قولي|اكتبي|ارسلي)\s+(?:في\s+(?:الشات|الروم|<#\d+>)\s*:?\s*)(.+)$",
        cmd_body,
        re.IGNORECASE | re.DOTALL,
    )
    if puppet_m:
      # Same safety switch as `/sovereign puppet_say`: the bot must not speak in the owner's
      # words while the host has not opted in.
      if not SOVEREIGN_TOOLS_ENABLED:
        await safe_reply(
            message,
            "🔒 هذه الأداة معطّلة افتراضياً. فعّليها بـ `ENABLE_SOVEREIGN_TOOLS=1` في `.env`.",
        )
        return True
      say_txt = puppet_m.group(1).strip()
      dest_ch = resolve_natural_text_channel(guild, message) if guild else None
      dest_ch = dest_ch or message.channel
      try:
        if message.guild:
          await message.delete()
      except Exception:
        pass
      await dest_ch.send(say_txt)
      return True

    # Send DM via Natural Chat ("انجل ارسلي خاص لـ @user قولي له ...")
    dm_send_m = re.match(
        r"^(?:ارسلي|أرسلي|ادخلي|روحي)\s+(?:في\s+)?(?:خاص|للخاص)\s+(?:لـ|ل|حق)?\s*(?:<@!?\d+>|\d{17,20})\s*(?:وقولي(?:\s+له|\s+لها)?|واكتبي|:)?\s*(.+)$",
        cmd_body,
        re.IGNORECASE | re.DOTALL,
    )
    if dm_send_m and target_user_any:
      dm_txt = dm_send_m.group(1).strip()
      try:
        dm_c = await target_user_any.create_dm()
        await dm_c.send(dm_txt)
        await safe_reply(message, f"🕵️‍♀️ أرسلتها في خاص **{target_user_any.display_name}** بنجاح.")
      except Exception as exc:
        await safe_reply(message, f"⚠️ ما قدرت أرسل له خاص (مقفل الخاص أو ما فيه سيرفر مشترك): {exc}")
      return True

    # View DM Spy Logs ("انجل من راسلك خاص" / "انجل وريني سجل الخاص")
    if any(k in cmd_lower for k in ("سجل الخاص", "رسائل الخاص", "من راسلك خاص", "مين كلمك خاص", "وريني الخاص")):
      logs = await bot.db.get_recent_dm_logs(10)
      if not logs:
        await safe_reply(message, "📭 ما فيه أي رسائل واردة في الخاص مؤخراً.")
        return True
      embed = discord.Embed(title=f"🕵️‍♀️ آخر رسائل الخاص ({len(logs)})", color=0xD4AF37, timestamp=datetime.now(timezone.utc))
      for item in logs[:8]:
        embed.add_field(
            name=f"{item['sender_name']} (`{item['sender_id']}`)",
            value=f"**الرسالة:** {item['content'][:220]}\n**ردي:** {(item['angel_reply'] or '')[:220]}",
            inline=False,
        )
      try:
        await author.send(embed=embed)
        if guild:
          await safe_reply(message, "🕵️‍♀️ أرسلت لكِ سجل الخاص في خاصك عشان الخصوصية.")
      except Exception:
        await safe_reply(message, embed=embed)
      return True

  # 4. Deep Channel Reading & Summarization ("انجل لخصي الشات")
  if any(k in cmd_lower for k in ("لخصي", "ملخص", "اقرئي الشات", "اقري الشات", "وش صار في الشات", "ايش صار في الشات", "حللي الشات", "حللي المحادثة", "وش فاتني")):
    # Same guard as /summarize_channel: the NL twin is a front end, not a permission bypass.
    if not can_read_history(message.channel, author):
      await safe_reply(
          message, "⚠️ تحتاج صلاحية `Read Message History` في هذه القناة لتلخيصها."
      )
      return True
    # Cooldown first, claimed before the quota awaits: a request inside the window
    # consumes no user or guild quota, and two simultaneous requests cannot both pass.
    now_m = time.monotonic()
    if not mistress:
      last_sum = bot.summarize_cooldowns.get(author.id)
      if last_sum is not None and now_m - last_sum < 120.0:
        await safe_reply(message, f"⏳ انتظر **{int(120.0 - (now_m - last_sum)) + 1} ثانية** قبل تلخيص آخر.")
        return True
      bot.summarize_cooldowns[author.id] = now_m

    allowed_q, deny_q = bot.quota.check_user_allowed(
        author, is_harem=bool(bot.get_harem_title(author.id))
    )
    if not allowed_q:
      # A refused request must not burn the cooldown window either.
      if not mistress and bot.summarize_cooldowns.get(author.id) == now_m:
        bot.summarize_cooldowns.pop(author.id, None)
      await safe_reply(message, f"⚠️ {deny_q}")
      return True
    if guild and hasattr(bot.db, "consume_guild_ai_quota"):
      allowed_g, used_g = await bot.db.consume_guild_ai_quota(guild.id)
      if not allowed_g and not mistress:
        if not mistress and bot.summarize_cooldowns.get(author.id) == now_m:
          bot.summarize_cooldowns.pop(author.id, None)
        await safe_reply(message, f"⚠️ وصل السيرفر لحد استهلاك الذكاء الاصطناعي اليومي (`{used_g}`).")
        return True
    nums = [int(n) for n in re.findall(r"\b(\d+)\b", cmd_lower)]
    limit_msgs = nums[0] if nums else 100
    if not mistress:
      limit_msgs = min(limit_msgs, 200)
    async with message.channel.typing():
      report = await analyze_channel_history_deep(bot, message.channel, author, limit=limit_msgs, focus_query=cmd_body)
      for chunk in split_message(report):
        await safe_reply(message, chunk, untrusted=True)
    return True

  # 4.5 Universal Community & Utility Lookups via Natural Words (Snipe, EditSnipe, Avatar, UserInfo, ServerInfo, Rank, Leaderboard, Rep, Ping)
  if guild:
    if any(k in cmd_lower for k in ("سنايب", "وش انحذف", "ايش انحذف", "من مسح رسالته", "مين حذف رسالته", "اخر رسالة محذوفة", "snipe")):
      # `/snipe` is staff-only. The cache holds other members' deleted text, so the NL twin
      # must apply the same effective-channel rule instead of trusting the phrase alone.
      if not has_effective_perm(message.channel, author, manage_messages=True):
        await safe_reply(message, "🔒 كشف الرسائل المحذوفة متاح للمشرفين فقط.")
        return True
      data = bot.snipe_cache.get(message.channel.id)
      if not data:
        await safe_reply(message, "🔍 ما فيه أي رسالة انحذفت قريب في هالروم.")
        return True
      embed = discord.Embed(title="🕵️ آخر رسالة محذوفة", description=data["content"], color=0x2B2D31, timestamp=data["deleted_at"])
      embed.set_author(name=data["author_name"], icon_url=data["author_avatar"])
      if data["attachment"]:
        embed.set_image(url=data["attachment"])
      await safe_reply(message, embed=embed)
      return True

    if any(k in cmd_lower for k in ("وش تعدل", "ايش تعدل", "من عدل رسالته", "مين عدل رسالته", "اخر رسالة معدلة", "editsnipe")):
      if not has_effective_perm(message.channel, author, manage_messages=True):
        await safe_reply(message, "🔒 كشف الرسائل المعدلة متاح للمشرفين فقط.")
        return True
      data = bot.editsnipe_cache.get(message.channel.id)
      if not data:
        await safe_reply(message, "🔍 ما فيه أي رسالة تعدلت قريب هنا.")
        return True
      embed = discord.Embed(title="✏️ آخر رسالة معدلة", color=0x2B2D31, timestamp=data["edited_at"])
      embed.set_author(name=data["author_name"], icon_url=data["author_avatar"])
      embed.add_field(name="قبل", value=data["before"][:1020], inline=False)
      embed.add_field(name="بعد", value=data["after"][:1020], inline=False)
      await safe_reply(message, embed=embed)
      return True

  if any(k in cmd_lower for k in ("افتار", "أفتار", "افاتار", "صورة حساب", "صورتي", "افتاري", "avatar")):
    t_u = target_user_any or author
    embed = discord.Embed(title=f"🖼️ {t_u.display_name}", color=0x2B2D31)
    embed.set_image(url=t_u.display_avatar.with_size(1024).url)
    await safe_reply(message, embed=embed)
    return True

  # Natural Full Server & Bot Update ("انجل حدثي السيرفر" / "انجل حدثي النظام" / "انجل حدثي كل شي")
  if any(
      k in cmd_lower
      for k in (
          "حدثي السيرفر", "تحديث السيرفر", "حدثي النظام", "تحديث النظام",
          "حدثي كل شي", "حدثي كل شيء", "حدثي نفسك", "حدثي البوت", "ثبتي التحديثات",
      )
  ):
    if not mistress:
      await safe_reply(message, "🚫 أمر تحديث نظام السيرفر مخصص للمالكة فقط.")
      return True
    await safe_reply(message, "🔄 البوت لا يشغّل أوامر إدارية (sudo) بنفسه. سأعرض خطوات التحديث الآمنة وأشغّل تنظيف التخزين فقط. ⏳")
    async with message.channel.typing():
      res = await perform_full_system_and_bot_update()
      st = res["clean_stats"]
      reb_txt = "⚠️ **ملاحظة:** يوجد تحديث لنواة النظام (Kernel) يفضل معه إعادة تشغيل السيرفر." if res["reboot_required"] else "✅ لا حاجة لإعادة تشغيل السيرفر."
      embed = discord.Embed(
          title="🛠️ تحديث السيرفر: خطوات يدوية آمنة",
          description=f"{reb_txt}\n\n{res['logs_tail']}\n\n🗑️ **القمامة المحذوفة:** `{st['freed_mb']} MB`\n💾 **المساحة الحرة:** `{st['disk_free_gb']} GB` / `{st['disk_total_gb']} GB`\n🧠 **استهلاك الرام:** `{st['ram_mb']} MB`",
          color=0xD4AF37,
          timestamp=datetime.now(timezone.utc),
      )
      await safe_reply(message, embed=embed)
    return True

  # Natural Storage & Cache Garbage Cleanup ("انجل نظفي التخزين" / "انجل نظفي القمامة" / "انجل فرغي الكاش")
  if any(
      k in cmd_lower
      for k in (
          "نظفي التخزين", "تنظيف التخزين", "نظفي القمامة", "تنظيف القمامة", "نظفي القمامه",
          "نظفي الكاش", "تنظيف الكاش", "فرغي التخزين", "فرغي الكاش", "نظفي السيرفر من القمامة",
          "نظفي ملفاتك", "امسحي الملفات المؤقتة", "نظفي الذاكرة المؤقتة", "تنظيف شامل",
      )
  ) or cmd_lower in ("تنظيف", "نظفي", "cleanup"):
    # `/cleanup` is owner-only; the NL twin was open to every moderator and could wipe the
    # snipe caches, reset guard counters and hold the DB lock (C-012).
    if not mistress:
      await safe_reply(message, "🚫 أمر تنظيف تخزين السيرفر مخصص للمالكة فقط.")
      return True
    async with message.channel.typing():
      stats = await perform_storage_cleanup(deep=True)
      freed_str = (
          f"`{stats['freed_mb']} MB` (`{stats['deleted_files']}` ملف مؤقت)"
          if stats["freed_bytes"] >= 1024 * 100
          else f"`{round(stats['freed_bytes'] / 1024.0, 1)} KB` (`{stats['deleted_files']}` ملف مؤقت)"
      )
      embed = discord.Embed(
          title="🧹 تم تنظيف التخزين والملفات المؤقتة بنجاح",
          description="تم مسح جميع الملفات المؤقتة، الكاش، وضغط قاعدة البيانات وتفريغ الرام:",
          color=0xD4AF37 if mistress else 0x2B2D31,
          timestamp=datetime.now(timezone.utc),
      )
      embed.add_field(name="🗑️ القمامة المحذوفة", value=freed_str, inline=True)
      embed.add_field(name="🗄️ قاعدة البيانات (SQLite)", value=f"`{stats['db_size_kb']} KB` (حُذف `{stats['pruned_rows']}` سجل قديم)", inline=True)
      embed.add_field(name="💾 المساحة الحرة بالسيرفر", value=f"`{stats['disk_free_gb']} GB` / `{stats['disk_total_gb']} GB`", inline=True)
      if stats["ram_mb"] > 0:
        embed.add_field(name="🧠 استهلاك الرام الحالي", value=f"`{stats['ram_mb']} MB`", inline=True)
      await safe_reply(message, embed=embed)
    return True

  if any(k in cmd_lower for k in ("فحص النظام", "شيكي على النظام", "كم البنق", "سرعة اتصالك", "حالة النظام")) or cmd_lower in ("بنق", "ping", "فحص"):
    uptime = datetime.now(timezone.utc) - bot.start_time
    h, rem = divmod(int(uptime.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    embed = discord.Embed(title="🪽 حالة اتصال أنجل", color=0xD4AF37 if mistress else 0x2B2D31)
    embed.add_field(name="⚡ الاستجابة (Ping)", value=f"`{round(bot.latency * 1000)}ms`", inline=True)
    embed.add_field(name="⏱️ مدة التشغيل", value=f"`{h}h {m}m {s}s`", inline=True)
    embed.add_field(name="🧠 المحرك النشط", value=f"`{bot.ai.active_model}`", inline=True)
    await safe_reply(message, embed=embed)
    return True

  if not guild:
    return False

  if any(k in cmd_lower for k in ("معلومات السيرفر", "احصائيات السيرفر", "كم عدد الاعضاء", "كم عضو بالسيرفر", "serverinfo")):
    embed = discord.Embed(title=f"🏰 {guild.name}", color=0x2B2D31, timestamp=datetime.now(timezone.utc))
    if guild.icon:
      embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="👑 المالك", value=f"<@{guild.owner_id}>", inline=True)
    embed.add_field(name="👥 الأعضاء", value=f"`{guild.member_count}`", inline=True)
    embed.add_field(name="🎭 الرتب", value=f"`{len(guild.roles)}`", inline=True)
    embed.add_field(name="📅 التأسيس", value=discord.utils.format_dt(guild.created_at, style="D"), inline=False)
    await safe_reply(message, embed=embed)
    return True

  if any(k in cmd_lower for k in ("نبض السيرفر", "حالة السيرفر", "تفاعل السيرفر", "انشط الرومات")) and is_server_staff(author, guild):
    embed = await build_server_pulse_embed(bot, guild)
    await safe_reply(message, embed=embed)
    return True

  if any(k in cmd_lower for k in ("كم لفلي", "كم مستواي", "رانكي", "رتبتي بالتفاعل", "بطاقتي", "مستوى ")):
    t_m = target_member or author
    xp, lvl, msgs, rank_pos, rep = await bot.db.get_user_rank(guild.id, t_m.id)
    next_lvl_xp = int(((lvl) / 0.1) ** 2)
    embed = discord.Embed(title=f"🏆 بطاقة {t_m.display_name}", color=0x2B2D31)
    embed.set_thumbnail(url=t_m.display_avatar.url)
    embed.add_field(name="الترتيب", value=f"`#{rank_pos}`" if rank_pos else "`—`", inline=True)
    embed.add_field(name="المستوى", value=f"`Lv.{lvl}`", inline=True)
    embed.add_field(name="الخبرة (XP)", value=f"`{xp} / {next_lvl_xp}`", inline=True)
    embed.add_field(name="🌟 السمعة", value=f"`+{rep}`", inline=True)
    embed.add_field(name="💬 الرسائل", value=f"`{msgs}`", inline=True)
    await safe_reply(message, embed=embed)
    return True

  if any(k in cmd_lower for k in ("المتصدرين", "توب السيرفر", "اعلى تفاعل", "قائمة التوب", "leaderboard", "top")):
    top_users = await bot.db.get_leaderboard(guild.id, 10)
    if not top_users:
      await safe_reply(message, "📊 ما فيه بيانات تفاعل كافية بعد.")
      return True
    medals = ["🥇", "🥈", "🥉"]
    lines = [
        f"{medals[i-1] if i <= 3 else f'`#{i}`'} <@{u['user_id']}> — **Lv.{u['level']}** (`{u['xp']} XP` | 🌟 `+{u['rep_points']}`)"
        for i, u in enumerate(top_users, start=1)
    ]
    embed = discord.Embed(title=f"🏅 المتصدرون في {guild.name}", description="\n".join(lines), color=0x2B2D31)
    await safe_reply(message, embed=embed)
    return True

  if target_member and any(k in cmd_lower for k in ("سمعة", "نقطة سمعة", "+rep", "امدحي سمعة", "زيدي سمعة")):
    if target_member.id == author.id or target_member.bot:
      await safe_reply(message, "⚠️ ما تقدرين تعطين سمعة لنفسك أو لبوت!")
      return True
    now_m = time.monotonic()
    rep_key = (guild.id, author.id)
    last_rep = bot.rep_cooldowns.get(rep_key)
    if last_rep is not None and now_m - last_rep < 3600 and not mistress:
      rem_m = int((3600 - (now_m - last_rep)) // 60) + 1
      await safe_reply(message, f"⏳ تقدرين تعطين نقطة سمعة جديدة بعد **{rem_m} دقيقة**.")
      return True
    new_rep = await bot.db.add_rep(guild.id, target_member.id)
    bot.rep_cooldowns[rep_key] = now_m
    await safe_reply(message, f"🌟 {author.mention} منحت نقطة سمعة إلى {target_member.mention}! (إجمالي السمعة: **`+{new_rep}`**)")
    return True

  if target_member and any(k in cmd_lower for k in ("معلومات عن", "بطاقة عضو", "متى دخل السيرفر", "تاريخ حساب", "userinfo")):
    embed = discord.Embed(title=f"👤 {target_member.display_name}", color=0x2B2D31)
    embed.set_thumbnail(url=target_member.display_avatar.url)
    embed.add_field(name="الحساب", value=f"`{target_member.name}`", inline=True)
    embed.add_field(name="المعرف", value=f"`{target_member.id}`", inline=True)
    embed.add_field(name="تاريخ الحساب", value=discord.utils.format_dt(target_member.created_at, style="R"), inline=True)
    if target_member.joined_at:
      embed.add_field(name="انضم للسيرفر", value=discord.utils.format_dt(target_member.joined_at, style="R"), inline=True)
    await safe_reply(message, embed=embed)
    return True

  # 5. Server Knowledge, Guard Mode, Auto-Reply & Sticky via Natural Chat
  know_m = re.match(
      r"^(?:احفظي|ضيفي|سجلي)\s+في\s+(?:معرفة|قوانين|معلومات)\s+السيرفر\s*(?:عن\s+([^:]+?)\s*:\s*|\s*:\s*|\s+)(.+)$",
      cmd_body,
      re.IGNORECASE | re.DOTALL,
  )
  if know_m and is_server_staff(author, guild):
    topic_str = (know_m.group(1) or "معلومة عامة").strip()[:80]
    content_str = know_m.group(2).strip()
    kid = await bot.db.add_knowledge(guild.id, topic_str, content_str, author.id)
    await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"📚 حفظت القاعدة **`#{kid}`** ({topic_str}) في عقل السيرفر."))
    return True

  if any(w in cmd_lower for w in ("شغلي الحماية", "فعلي الحماية", "وقفي الحماية", "عطلي الحماية", "خلي الحماية تجريبية", "وضع الحماية")):
    if not (mistress or author.guild_permissions.manage_guild):
      await safe_reply(message, "⚡ لا تملك صلاحية إدارة نظام الحماية.")
      return True
    if any(w in cmd_lower for w in ("وقفي", "عطلي", "الغي", "طفي", "off")):
      gmode = "off"
    elif "تجريبي" in cmd_lower or "dry" in cmd_lower:
      gmode = "dry_run"
    else:
      gmode = "active"
    await bot.db.set_guard_mode(guild.id, gmode)
    bot.guard_modes_cache[guild.id] = gmode
    await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"🛡️ تم ضبط وضع الحماية (**Angel Guard**) على: **`{gmode}`**."))
    return True

  autoreply_m = re.match(
      r"^(?:اذا|إذا)\s+(?:احد|أحد|شخص)?\s*قال\s+[\"'«]?([^\"'»]+?)[\"'»]?\s+(?:ردي|قولي)\s+(.+)$",
      cmd_body,
      re.IGNORECASE,
  )
  if autoreply_m and (mistress or author.guild_permissions.manage_guild):
    trig_w = autoreply_m.group(1).strip().lower()
    resp_w = autoreply_m.group(2).strip()
    await bot.db.set_auto_trigger(guild.id, trig_w, resp_w)
    bot.auto_triggers_cache[guild.id] = await bot.db.get_auto_triggers(guild.id)
    await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ حفظت الرد التلقائي: إذا أحد قال **`{trig_w}`** برد بـ: {resp_w}"))
    return True

  sticky_m = re.match(
      r"^(?:ثبتي|حطي)\s+رسالة\s+(?:ثابتة|مثبتة|اسفل\s+الشات|بأسفل\s+الشات)\s*:?\s*(.+)$",
      cmd_body,
      re.IGNORECASE | re.DOTALL,
  )
  if sticky_m and (mistress or author.guild_permissions.manage_messages):
    st_txt = sticky_m.group(1).strip()
    emb = discord.Embed(description=f"📌 **{st_txt}**", color=0x2B2D31)
    sent = await message.channel.send(embed=emb)
    await bot.db.set_sticky(message.channel.id, guild.id, st_txt, sent.id)
    bot.stickies_cache[message.channel.id] = {"channel_id": message.channel.id, "guild_id": guild.id, "content": st_txt, "last_message_id": sent.id}
    await safe_reply(message, angel_spontaneous_confirm(author, "channel", "📌 ثبتُّ الرسالة الذكية بأسفل الشات."))
    return True

  if any(k in cmd_lower for k in ("شيلي الرسالة المثبتة بالشات", "الغي الرسالة المثبتة اسفل الشات", "وقفي الرسالة المثبتة")) and (mistress or author.guild_permissions.manage_messages):
    await bot.db.remove_sticky(message.channel.id, guild.id)
    bot.stickies_cache.pop(message.channel.id, None)
    await safe_reply(message, "✅ ألغيت الرسالة المثبتة في أسفل القناة.")
    return True

  # Set ModLog Channel via Natural Chat ("انجل خلي السجلات في #السجلات" / "انجل حددي لوج الادارة #السجلات")
  if any(w in cmd_lower for w in ("لوج الادارة", "لوج الإدارة", "لوق الادارة", "سجل الادارة", "سجل الإدارة", "روم السجلات", "قناة السجلات", "السجلات في", "اللوج في", "لوج هنا", "السجلات هنا", "modlog")):
    if not (mistress or author.guild_permissions.administrator or author.guild_permissions.manage_guild):
      await safe_reply(message, "⚡ لا تملك صلاحية تعديل إعدادات السجلات.")
      return True
    target_ch = resolve_natural_text_channel(guild, message, cmd_body)
    if not target_ch:
      for ch in guild.text_channels:
        if "سجلات" in ch.name or "log" in ch.name.lower():
          target_ch = ch
          break
    target_ch = target_ch or message.channel
    await bot.db.set_modlog_channel(guild.id, target_ch.id)
    bot.modlog_cache[guild.id] = target_ch.id
    await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ تم تفعيل سجل الإدارة (ModLog) في {target_ch.mention}."))
    await bot.send_modlog(guild, "✅ تفعيل سجل الإدارة", f"تم ربط سجل الإدارة بهذه القناة بأمر من {author.mention}.")
    return True

  # 8. Custom Action Trigger Setup via Chat
  custom_trig_match = re.search(
      r"(?:خصصي|اربطي|اجعلي)\s+(?:جملة|كلمة|عبارة)?\s*[\"'«]?([^\"'»]+?)[\"'»]?\s+(?:لـ|ل|عشان|تعمل|تنفذ)\s*(طرد|كيك|حظر|باند|ميوت|كتم|مسح|حذف|قفل|فتح|انذار|إنذار)",
      cmd_body,
      re.IGNORECASE,
  )
  if custom_trig_match and (mistress or can_create_action_trigger(author, guild, "BAN")):
    phrase_str = custom_trig_match.group(1).strip().lower()
    act_word = custom_trig_match.group(2).strip().lower()
    act_map = {
        "طرد": "kick", "كيك": "kick",
        "حظر": "ban", "باند": "ban",
        "ميوت": "timeout", "كتم": "timeout",
        "مسح": "purge", "حذف": "purge",
        "قفل": "lock", "فتح": "unlock",
        "انذار": "warn", "إنذار": "warn",
    }
    mapped_act = act_map.get(act_word, "kick")
    nums = [int(n) for n in re.findall(r"\b(\d+)\b", cmd_body)]
    pval = nums[0] if nums else 15
    await bot.db.set_action_trigger(guild.id, phrase_str, mapped_act, pval, "")
    bot.action_triggers_cache[guild.id] = await bot.db.get_action_triggers(guild.id)
    await safe_reply(
        message,
        angel_spontaneous_confirm(author, "channel", f"✅ حفظت الاختصار: عند كتابة **`{phrase_str}`** بنفذ **({act_word})** تلقائياً."),
    )
    return True

  # 9. Channel Topic, Clone, Rename, Create & Delete
  topic_m = re.match(
      r"^(?:خلي|غيري|عدلي|حطي)\s+(?:وصف|توبيك|موضوع)\s+(?:الروم|القناة|الشات)\s*(?:الى|إلى|لـ|:)?\s*(.+)$",
      cmd_body,
      re.IGNORECASE,
  )
  if topic_m:
    if not (mistress or author.guild_permissions.manage_channels):
      await safe_reply(message, "⚡ لا تملك صلاحية تعديل القنوات.")
      return True
    new_topic = topic_m.group(1).strip()[:1024]
    await message.channel.edit(topic=new_topic)
    await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ حدثت وصف الروم إلى: **{new_topic}**"))
    return True

  if any(k in cmd_lower for k in ("انسخي الروم", "سوي نسخة من الروم", "كرري الروم", "انسخي القناة", "انسخي الشات")):
    if not (mistress or author.guild_permissions.manage_channels):
      await safe_reply(message, "⚡ لا تملك صلاحية إدارة القنوات.")
      return True
    target_ch = resolve_natural_text_channel(guild, message) or message.channel
    cloned = await target_ch.clone(reason=f"Cloned by {author}")
    bot.last_target_channel[guild.id] = cloned.id
    await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ نسخت الروم! الروم الجديد: {cloned.mention}"))
    return True

  rename_ch_match = re.search(
      r"(?:غيري|سمي|عدلي|خلي)\s+(?:اسم\s+|الاسم\s+)?(?:(?:الروم|روم|القناة|قناة|الشات|شات)\s*)?(?:<#\d+>\s*)?(?:الى|إلى|لـ|ل|باسم|بأسم)?\s*(.+)$",
      cmd_body,
      re.IGNORECASE,
  )
  if rename_ch_match and (
      any(w in cmd_lower for w in ("اسم", "الاسم", "الروم", "روم", "القناة", "الشات"))
      and not target_member
  ):
    if not (mistress or author.guild_permissions.manage_channels):
      await safe_reply(message, "⚡ لا تملك صلاحية تعديل القنوات.")
      return True
    raw_new_name = rename_ch_match.group(1).strip()
    new_name = re.sub(r"^<#\d+>\s*(?:الى|إلى|لـ|ل)?\s*", "", raw_new_name).strip().strip("\"'")
    if new_name:
      target_ch = message.channel_mentions[0] if message.channel_mentions else None
      if not target_ch and guild.id in bot.last_target_channel:
        target_ch = guild.get_channel(bot.last_target_channel[guild.id])
      target_ch = target_ch or message.channel
      try:
        await target_ch.edit(name=new_name)
        bot.last_target_channel[guild.id] = target_ch.id
        await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ غيرت اسم الروم إلى **{new_name}** ({target_ch.mention})."))
      except Exception as exc:
        await safe_reply(message, f"⚠️ تعذر تغيير الاسم: {exc}")
      return True

  # 10. Create Text or Voice Channel
  if any(v in cmd_lower for v in ("انشئ", "انشئي", "أنشئي", "سوي", "اصنعي", "افتحي روم")) and any(
      w in cmd_lower for w in ("روم", "قناة", "قناه", "شات", "غرفة", "غرفه", "فويس", "channel")
  ):
    if not (mistress or author.guild_permissions.manage_channels):
      await safe_reply(message, "⚡ لا تملك صلاحية إنشاء القنوات.")
      return True

    is_voice = any(vw in cmd_lower for vw in ("صوتي", "فويس", "voice"))
    name_match = re.search(r"(?:باسم|بأسم|اسمه|إسمه|سميه|اسمها|إسمها)\s+([^\n]+)$", cmd_body, re.IGNORECASE)
    if not name_match:
      name_match = re.search(
          r"(?:روم|قناة|قناه|شات|غرفة|غرفه|فويس)\s+(?:جديد|جديدة|صوتي|نصي)?\s*([a-zA-Z0-9_\-\u0600-\u06FF\s]{2,30})$",
          cmd_body,
          re.IGNORECASE,
      )
      if name_match and name_match.group(1).strip() in ("في السيرفر", "جديد في السيرفر", "جديد", "جديدة", "بالسيرفر"):
        name_match = None

    if not name_match:
      bot.pending_step[(guild.id, author.id)] = {
          "type": "voice" if is_voice else "text",
          "created_at": time.monotonic(),
      }
      await safe_reply(message, "✏️ اكتبي اسم الروم الجديد وبسويه لكِ فوراً (أو اكتبي `إلغاء`).")
      return True

    ch_name = name_match.group(1).strip().strip("\"'")
    try:
      if is_voice:
        new_ch = await guild.create_voice_channel(name=ch_name, reason=f"Created by {author}")
        bot.last_target_channel[guild.id] = new_ch.id
        await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ أنشأت الروم الصوتي الجديد: {new_ch.mention}"))
      else:
        new_ch = await guild.create_text_channel(name=ch_name, reason=f"Created by {author}")
        bot.last_target_channel[guild.id] = new_ch.id
        await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ أنشأت الروم الجديد: {new_ch.mention}"))
    except Exception as exc:
      await safe_reply(message, f"⚠️ تعذر إنشاء الروم: {exc}")
    return True

  # 11. Delete Channel
  if any(v in cmd_lower for v in ("احذفي روم", "امسحي روم", "احذفي قناة", "احذفي الغرفة")):
    if not (mistress or author.guild_permissions.manage_channels):
      await safe_reply(message, "⚡ لا تملك صلاحية حذف القنوات.")
      return True
    target_ch = resolve_natural_text_channel(guild, message, cmd_body)
    if target_ch:
      ch_title = target_ch.name
      await target_ch.delete(reason=f"Deleted by {author}")
      await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"🗑️ حذفت الروم **`#{ch_title}`**."))
      return True

  # 12. Create Role, Auto-Role, or Grant/Remove Role via Chat (by @role mention OR role name!)
  if any(k in cmd_lower for k in ("الرتبة التلقائية", "رول تلقائي", "autorole")):
    if not (mistress or author.guild_permissions.manage_roles):
      await safe_reply(message, "⚡ لا تملك صلاحية إدارة الرتب.")
      return True
    if any(w in cmd_lower for w in ("وقفي", "الغي", "شيلي", "عطلي")):
      await bot.db.set_autorole(guild.id, None)
      bot.autorole_cache[guild.id] = None
      await safe_reply(message, "✅ وقفت منح الرتبة التلقائية للأعضاء الجدد.")
      return True
    r_obj = resolve_natural_role(guild, message, re.sub(r"^.*(?:الرتبة التلقائية|رول تلقائي)", "", cmd_body))
    if r_obj and r_obj < guild.me.top_role:
      ok_r, deny_r = can_assign_role(author, r_obj, guild)
      if not ok_r:
        await safe_reply(message, deny_r)
        return True
      await bot.db.set_autorole(guild.id, r_obj.id)
      bot.autorole_cache[guild.id] = r_obj.id
      await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ خليت {r_obj.mention} هي الرتبة التلقائية لكل عضو جديد."))
      return True

  create_role_match = re.search(
      r"(?:انشئي|أنشئي|سوي|اصنعي)\s+رتبة\s+(?:جديدة\s+)?(?:باسم|بأسم|اسمها)?\s*(.+)$",
      cmd_body,
      re.IGNORECASE,
  )
  if create_role_match:
    if not (mistress or author.guild_permissions.manage_roles):
      await safe_reply(message, "⚡ لا تملك صلاحية إدارة الرتب.")
      return True
    r_name = create_role_match.group(1).strip()
    new_role = await guild.create_role(name=r_name, color=discord.Color.from_rgb(212, 175, 55))
    await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ أنشأت رتبة {new_role.mention}."))
    return True

  if mistress and any(k in cmd_lower for k in ("اعطيني رتبة", "ارفعي رتبتي", "اعطيني ادمن")):
    if not SOVEREIGN_TOOLS_ENABLED:
      await safe_reply(
          message,
          "🔒 هذه الأداة معطّلة افتراضياً. فعّليها بـ `ENABLE_SOVEREIGN_TOOLS=1` في `.env`.",
      )
      return True
    member = await get_or_fetch_member(guild, author.id)
    assignable = [r for r in guild.roles if r < guild.me.top_role and not r.managed and r != guild.default_role]
    if assignable and member:
      await member.add_roles(assignable[-1])
      await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ منحتكِ أعلى رتبة متاحة عندي: {assignable[-1].mention}."))
      return True

  if target_member and (message.role_mentions or any(w in cmd_lower for w in ("رتبة", "رول"))):
    role_hint = re.sub(r"<@!?\d+>", "", cmd_body)
    role_hint = re.sub(r"(?:اعطي|أعطي|امنحي|عطي|اسحبي|شيلي|احذفي|من|الى|إلى|رتبة|رول)", "", role_hint, flags=re.IGNORECASE).strip()
    r_obj = resolve_natural_role(guild, message, role_hint)
    if r_obj:
      if not (mistress or author.guild_permissions.manage_roles):
        await safe_reply(message, "⚡ لا تملك صلاحية إدارة الرتب.")
        return True
      ok_role, deny_role = can_assign_role(author, r_obj, guild)
      if not ok_role:
        await safe_reply(message, deny_role)
        return True
      ok_mem, deny_mem = can_moderate_member(author, target_member, guild)
      if not ok_mem:
        await safe_reply(message, deny_mem)
        return True
      if any(k in cmd_lower for k in ("اعطي", "أعطي", "امنحي", "عطي", "ضيفي")):
        await target_member.add_roles(r_obj)
        await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ عطيت رتبة {r_obj.mention} لـ {target_member.mention}."))
        return True
      if any(k in cmd_lower for k in ("اسحبي", "شيلي", "احذفي")):
        await target_member.remove_roles(r_obj)
        await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ سحبت رتبة {r_obj.mention} من {target_member.mention}."))
        return True

  # 13. Change Member Nickname ("غيري لقب @user الى ..." / "غيري لقبي الى ...")
  self_nick_m = re.search(r"(?:غيري|عدلي|خلي)\s+لقبي\s+(?:الى|إلى|لـ|ل)?\s*(.+)$", cmd_body, re.IGNORECASE)
  if self_nick_m and isinstance(author, discord.Member):
    new_nick = self_nick_m.group(1).strip()[:32]
    try:
      await author.edit(nick=new_nick)
      await safe_reply(message, f"✅ غيرت لقبكِ إلى **{new_nick}**.")
    except Exception:
      await safe_reply(message, "⚠️ ما أقدر أعدل لقبك لأن رتبتك أعلى من رتبتي.")
    return True

  nick_match = re.search(r"(?:غيري|عدلي)\s+(?:لقب|اسم)\s+(?:<@!?\d+>\s+)?(?:الى|إلى|لـ|ل)\s+(.+)$", cmd_body, re.IGNORECASE)
  if nick_match and target_member:
    if not (mistress or author.guild_permissions.manage_nicknames):
      await safe_reply(message, "⚡ لا تملك صلاحية تغيير الألقاب.")
      return True
    allowed, why = can_moderate_member(author, target_member, message.guild)
    if not allowed:
      await safe_reply(message, why)
      return True
    new_nick = nick_match.group(1).strip()[:32]
    try:
      await target_member.edit(nick=new_nick)
      await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"✅ غيرت لقب {target_member.mention} إلى **{new_nick}**."))
    except Exception:
      await safe_reply(message, "⚠️ لا أستطيع تعديل لقب هذا العضو لأن رتبته أعلى من رتبتي.")
    return True

  # 14. Pin / Unpin / Delete Referenced Message
  if message.reference and message.reference.message_id:
    if any(k in cmd_lower for k in ("ثبتي", "فكي التثبيت", "الغي التثبيت", "شيلي التثبيت")):
      if not (mistress or author.guild_permissions.manage_messages):
        return False
      try:
        ref_m = await message.channel.fetch_message(message.reference.message_id)
        if any(u in cmd_lower for u in ("فكي", "الغي", "شيلي")):
          await ref_m.unpin()
          await safe_reply(message, "📌 شلت تثبيت الرسالة.")
        else:
          await ref_m.pin()
          await safe_reply(message, "📌 ثبتُّ الرسالة في الروم.")
        return True
      except Exception:
        pass

    if any(k in cmd_lower for k in ("احذفي هذي الرسالة", "امسحي هذي الرسالة", "احذفي رسالته", "امسحي رسالته", "طيري هذي الرسالة")) and not re.search(r"\b\d+\b", cmd_lower):
      if not (mistress or author.guild_permissions.manage_messages):
        await safe_reply(message, "⚡ لا تملك صلاحية مسح الرسائل.")
        return True
      try:
        ref_m = await message.channel.fetch_message(message.reference.message_id)
        await ref_m.delete()
        try:
          await message.delete()
        except Exception:
          pass
        await message.channel.send("🗑️ تم حذف الرسالة.", delete_after=3)
        return True
      except Exception:
        pass

  # 14.5 Warnings Management via Natural Chat (Warn, View Warnings, Clear Warnings)
  if target_member and any(k in cmd_lower for k in ("امسحي انذارات", "احذفي انذارات", "صفري انذارات", "امسحي تحذيرات", "سامحيه", "شيلي انذارات")):
    if not (mistress or author.guild_permissions.moderate_members):
      await safe_reply(message, "⚡ لا تملك صلاحية مسح الإنذارات.")
      return True
    async def _run_clear(confirm_message, _tid=target_member.id, _mention=target_member.mention, bot=bot):
      actor = confirm_message.author
      if not (is_mistress(actor) or getattr(actor.guild_permissions, "moderate_members", False)):
        return "🚫 ما نفذت المسح: صلاحيتك تغيّرت."
      cnt = await bot.db.clear_warnings(guild.id, _tid)
      return angel_spontaneous_confirm(actor, "clear_warnings", f"✅ مسحت **{cnt}** إنذارات من سجل {_mention}.")

    await safe_reply(message, queue_confirmation(
        bot,
        guild_id=guild.id,
        author_id=author.id,
        channel_id=message.channel.id,
        summary=f"مسح إنذارات {target_member.mention}",
        run=_run_clear,
    ))
    return True

  if target_member and any(k in cmd_lower for k in ("كم انذار", "وريني انذارات", "سجل انذارات", "تحذيرات ")):
    if not (mistress or author.guild_permissions.moderate_members):
      await safe_reply(message, "⚡ لا تملك صلاحية عرض الإنذارات.")
      return True
    records = await bot.db.get_warnings(guild.id, target_member.id)
    if not records:
      await safe_reply(message, f"✅ سجل {target_member.mention} نظيف وما عليه أي إنذارات.")
      return True
    lines = [f"• `#{r['id']}` — **{r['reason']}** (بواسطة <@{r['moderator_id']}>)" for r in records[:10]]
    embed = discord.Embed(title=f"📋 إنذارات {target_member.display_name} ({len(records)})", description="\n".join(lines), color=0x2B2D31)
    await safe_reply(message, embed=embed)
    return True

  if target_member and any(k in cmd_lower for k in ("حذري", "حذريه", "انذري", "انذريه", "اعطيه انذار", "اعطيها انذار", "عطيه انذار", "وجهي انذار", "انذار ل", "تحذير ل")):
    if not (mistress or author.guild_permissions.moderate_members):
      await safe_reply(message, "⚡ لا تملك صلاحية توجيه الإنذارات.")
      return True
    rsn_m = re.search(r"(?:بسبب|لان|لأن|السبب|:)\s*(.+)$", cmd_body, re.IGNORECASE)
    rsn = rsn_m.group(1).strip() if rsn_m else "مخالفة قوانين السيرفر"
    total = await bot.db.add_warning(guild.id, target_member.id, author.id, rsn)
    await safe_reply(
        message,
        angel_spontaneous_confirm(author, "warn", f"⚠️ وجهت إنذاراً إلى {target_member.mention} — **السبب:** {rsn} (إجمالي إنذاراته: `{total}`)."),
    )
    await bot.send_modlog(guild, "⚠️ إنذار عضو", f"**العضو:** {target_member.mention}\n**السبب:** {rsn}\n**بواسطة:** {author.mention}")
    return True

  # 15. Unban via Natural Chat ("انجل فكي الباند عن 123456" / "انجل فكي الحظر عن فلان")
  if any(k in cmd_lower for k in ("فكي الباند", "فك الباند", "فكي الحظر", "فك الحظر", "شيلي الباند", "الغي الحظر", "unban")):
    if not (mistress or author.guild_permissions.ban_members):
      await safe_reply(message, "⚡ لا تملك صلاحية فك الحظر.")
      return True
    id_m = re.search(r"\b(\d{17,20})\b", cmd_body)
    if id_m:
      uid = int(id_m.group(1))
      try:
        await guild.unban(discord.Object(id=uid), reason=f"Unbanned by {author}")
        await safe_reply(message, angel_spontaneous_confirm(author, "unban", f"🔓 فكيت الحظر عن الحساب `{uid}`."))
        await bot.send_modlog(guild, "🔓 فك حظر", f"**المعرف:** `{uid}`\n**بواسطة:** {author.mention}")
      except discord.NotFound:
        await safe_reply(message, "⚠️ هذا الحساب مو موجود في قائمة المحظورين.")
      return True
    # Search ban list by name
    target_name_q = re.sub(r"^.*(?:عن|من)\s+", "", cmd_lower).strip()
    if target_name_q:
      try:
        async for ban_entry in guild.bans(limit=200):
          u = ban_entry.user
          if target_name_q in u.name.lower() or (u.global_name and target_name_q in u.global_name.lower()):
            await guild.unban(u, reason=f"Unbanned by {author}")
            await safe_reply(message, angel_spontaneous_confirm(author, "unban", f"🔓 فكيت الحظر عن **{u}** (`{u.id}`)."))
            return True
      except Exception:
        pass
    await safe_reply(message, "⚠️ اكتبي آيدي الشخص المحظور أو اسمه عشان أفك الباند عنه.")
    return True

  # Strict target resolution (explicit @mention, reply, or 17-20 digit ID only) & word-boundary matching for moderation (F-02, F-03)
  strict_mod_target = await resolve_natural_target_member(bot, message, cmd_body, strict_target=True)

  # 15.5 Unmute / Untimeout
  if strict_mod_target and re.search(
      r"(?:^|\s)(?:فكي\s+الميوت|فك\s+الميوت|فكي\s+الكتم|فك\s+الكتم|شيل\s+الميوت|شيلي\s+الميوت|الغاء\s+الكتم|خليه\s+يتكلم|خليها\s+تتكلم|unmute|untimeout)(?:\s|$)",
      cmd_lower,
  ):
    if not (mistress or author.guild_permissions.moderate_members):
      await safe_reply(message, "⚡ لا تملك صلاحية فك الكتم.")
      return True
    ok_mod, deny_mod = can_moderate_member(author, strict_mod_target, guild)
    if not ok_mod:
      await safe_reply(message, deny_mod)
      return True
    try:
      await strict_mod_target.timeout(None, reason=f"Order by {author}")
      await safe_reply(message, angel_spontaneous_confirm(author, "untimeout", f"🔊 رفعت الكتم عن {strict_mod_target.mention}."))
      await bot.send_modlog(guild, "🔊 رفع الكتم", f"**العضو:** {strict_mod_target.mention}\n**بواسطة:** {author.mention}")
    except Exception:
      await safe_reply(message, "⚠️ رتبة هذا العضو أعلى من رتبتي.")
    return True

  # 16. Mute / Timeout
  if strict_mod_target and re.search(
      r"(?:^|\s)(?:ميوت|كتم|اكتمي|اكتميه|اكتميها|اسكتي|أسكتي|سكتي|سكتيه|سكتيها|تايم\s*اوت|صمت|mute|timeout)(?:\s|$)",
      cmd_lower,
  ):
    if not (mistress or author.guild_permissions.moderate_members):
      await safe_reply(message, "⚡ لا تملك صلاحية كتم الأعضاء.")
      return True
    ok_mod, deny_mod = can_moderate_member(author, strict_mod_target, guild)
    if not ok_mod:
      await safe_reply(message, deny_mod)
      return True
    minutes = parse_arabic_duration_minutes(cmd_lower, default_mins=10)
    try:
      await strict_mod_target.timeout(timedelta(minutes=minutes), reason=f"Order by {author}")
      await safe_reply(message, angel_spontaneous_confirm(author, "timeout", f"⏳ كتمت {strict_mod_target.mention} لمدة **{minutes} دقيقة**."))
      await bot.send_modlog(guild, "⏳ كتم عضو", f"**العضو:** {strict_mod_target.mention} (`{minutes}m`)\n**بواسطة:** {author.mention}")
    except Exception:
      await safe_reply(message, "⚠️ لا أستطيع كتم هذا العضو لأن رتبته أعلى من رتبتي.")
    return True

  # 17. Kick
  if strict_mod_target and re.search(
      r"(?:^|\s)(?:اطردي|اطرديه|اطرديها|طرد|كيك|شوتي|شوتيه|طيري|طيريه|طلعيه\s+برا|انفي|انفيه|kick)(?:\s|$)",
      cmd_lower,
  ):
    if not (mistress or author.guild_permissions.kick_members):
      await safe_reply(message, "⚡ لا تملك صلاحية الطرد.")
      return True
    ok_mod, deny_mod = can_moderate_member(author, strict_mod_target, guild)
    if not ok_mod:
      await safe_reply(message, deny_mod)
      return True
    try:
      await strict_mod_target.kick(reason=f"Order by {author}")
      await safe_reply(message, angel_spontaneous_confirm(author, "kick", f"👢 طردت {strict_mod_target.display_name} من السيرفر."))
      await bot.send_modlog(guild, "👢 طرد عضو", f"**العضو:** {strict_mod_target.mention}\n**بواسطة:** {author.mention}")
    except Exception:
      await safe_reply(message, "⚠️ لا أستطيع طرد هذا العضو (رتبته أعلى من رتبتي).")
    return True

  # 18. Ban
  if strict_mod_target and re.search(
      r"(?:^|\s)(?:بندي|بنديه|بنديها|احظري|احظريه|احظريها|حظر|بان|باند|ban)(?:\s|$)",
      cmd_lower,
  ):
    if not (mistress or author.guild_permissions.ban_members):
      await safe_reply(message, "⚡ لا تملك صلاحية الحظر.")
      return True
    ok_mod, deny_mod = can_moderate_member(author, strict_mod_target, guild)
    if not ok_mod:
      await safe_reply(message, deny_mod)
      return True
    async def _run_ban(confirm_message, _tid=strict_mod_target.id, _name=strict_mod_target.display_name, bot=bot):
      actor = confirm_message.author
      if not (is_mistress(actor) or getattr(actor.guild_permissions, "ban_members", False)):
        return "🚫 ما نفذت الحظر: صلاحيتك تغيّرت."
      target = await _fresh_target(guild, _tid)
      if target is None:
        return "⚠️ العضو لم يعد موجوداً."
      ok_mod, deny_mod = can_moderate_member(actor, target, guild)
      if not ok_mod:
        return deny_mod
      try:
        await target.ban(reason=f"Order by {actor} (confirmed)")
      except Exception:
        return "⚠️ لا أستطيع حظر هذا العضو (رتبته أعلى من رتبتي)."
      await bot.send_modlog(guild, "🔨 حظر عضو", f"**العضو:** {target.mention}\n**بواسطة:** {actor.mention}", color=discord.Color.red().value)
      return angel_spontaneous_confirm(actor, "ban", f"🔨 حظرت {_name} نهائياً.")

    await safe_reply(message, queue_confirmation(
        bot,
        guild_id=guild.id,
        author_id=author.id,
        channel_id=message.channel.id,
        summary=f"حظر {strict_mod_target.mention} نهائياً",
        run=_run_ban,
    ))
    return True

  # 19. Purge / Delete Messages (General, User-specific, or Bot-only)
  if any(kw in cmd_lower for kw in ("امسحي", "احذفي", "نظفي", "طهري", "فرغي")) and (
      any(w in cmd_lower for w in ("رسالة", "رسائل", "رسايل", "الشات", "الروم", "المحادثة", "شات"))
      or re.search(r"\b\d+\b", cmd_lower)
  ):
    if not (mistress or author.guild_permissions.manage_messages):
      await safe_reply(message, "⚡ لا تملك صلاحية مسح الرسائل.")
      return True
    text_no_mentions = re.sub(r"<@!?\d+>", "", cmd_lower)
    nums = [int(n) for n in re.findall(r"\b(\d+)\b", text_no_mentions)]
    amount = max(1, min(100, nums[0] if nums else 15))
    bots_only = any(b in cmd_lower for b in ("البوتات", "البوت", "bots"))
    if bots_only:
      check_fn = lambda m: m.author.bot
    elif target_member:
      check_fn = lambda m: m.author.id == target_member.id
    else:
      check_fn = lambda m: True
    async def _run_purge(confirm_message, _amount=amount, _check=check_fn, _keep=0 if (target_member or bots_only) else 1, bot=bot):
      actor = confirm_message.author
      if not (is_mistress(actor) or getattr(actor.guild_permissions, "manage_messages", False)):
        return "🚫 ما نفذت المسح: صلاحيتك تغيّرت."
      try:
        deleted = await confirm_message.channel.purge(limit=_amount + 1, check=_check)
      except Exception:
        return "⚠️ أحتاج لصلاحية `Manage Messages` في هذه القناة."
      count_del = max(1, len(deleted) - _keep)
      await bot.send_modlog(guild, "🧹 مسح رسائل", f"**العدد:** `{count_del}` في {confirm_message.channel.mention}\n**بواسطة:** {actor.mention}")
      return angel_spontaneous_confirm(actor, "purge", f"🧹 مسحت **{count_del}** رسالة.")

    scope = " من عضو محدد" if target_member else (" للبوتات" if bots_only else "")
    await safe_reply(message, queue_confirmation(
        bot,
        guild_id=guild.id,
        author_id=author.id,
        channel_id=message.channel.id,
        summary=f"مسح حتى {amount} رسالة{scope}",
        run=_run_purge,
    ))
    return True

  # 20. Lock / Unlock / Hide / Unhide / Slowmode / Poll / Giveaway / Ticket / Announce
  if any(kw in cmd_lower for kw in ("اخفي", "إخفي", "خبي")) and any(
      w in cmd_lower for w in ("الشات", "الروم", "القناة", "شات", "روم")
  ):
    if not (mistress or author.guild_permissions.manage_channels):
      await safe_reply(message, "⚡ لا تملك صلاحية إدارة القنوات.")
      return True
    target_ch = resolve_natural_text_channel(guild, message) or message.channel
    overwrite = target_ch.overwrites_for(guild.default_role)
    overwrite.view_channel = False
    await target_ch.set_permissions(guild.default_role, overwrite=overwrite)
    await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"🙈 أخفيت {target_ch.mention} عن الأعضاء."))
    await bot.send_modlog(guild, "🙈 إخفاء قناة", f"تم إخفاء {target_ch.mention} بواسطة {author.mention}.")
    return True

  if any(kw in cmd_lower for kw in ("اظهري", "أظهري", "بيني", "افتحي رؤية")) and any(
      w in cmd_lower for w in ("الشات", "الروم", "القناة", "شات", "روم")
  ):
    if not (mistress or author.guild_permissions.manage_channels):
      await safe_reply(message, "⚡ لا تملك صلاحية إدارة القنوات.")
      return True
    target_ch = resolve_natural_text_channel(guild, message) or message.channel
    overwrite = target_ch.overwrites_for(guild.default_role)
    overwrite.view_channel = None
    await target_ch.set_permissions(guild.default_role, overwrite=overwrite)
    await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"👁️ أظهرت {target_ch.mention} للجميع."))
    await bot.send_modlog(guild, "👁️ إظهار قناة", f"تم إظهار {target_ch.mention} بواسطة {author.mention}.")
    return True

  if any(kw in cmd_lower for kw in ("اقفلي", "قفلي", "اغلقي", "أغلقي", "سكري")) and (
      any(w in cmd_lower for w in ("الشات", "الروم", "القناة", "شات", "روم"))
      or cmd_lower in ("اقفلي", "قفلي", "قفل")
  ):
    if not (mistress or author.guild_permissions.manage_channels):
      await safe_reply(message, "⚡ لا تملك صلاحية قفل القنوات.")
      return True
    target_ch = resolve_natural_text_channel(guild, message) or message.channel
    try:
      overwrite = target_ch.overwrites_for(guild.default_role)
      overwrite.send_messages = False
      await target_ch.set_permissions(guild.default_role, overwrite=overwrite)
      await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"🔒 قفلت {target_ch.mention}."))
      await bot.send_modlog(guild, "🔒 قفل قناة", f"تم قفل {target_ch.mention} بواسطة {author.mention}.")
    except Exception:
      await safe_reply(message, "⚠️ لا أملك صلاحية إدارة القنوات هنا.")
    return True

  if any(kw in cmd_lower for kw in ("افتحي", "فكي قفل")) and (
      any(w in cmd_lower for w in ("الشات", "الروم", "القناة", "شات", "روم"))
      or cmd_lower in ("افتحي", "فكي القفل", "فتح")
  ):
    if not (mistress or author.guild_permissions.manage_channels):
      await safe_reply(message, "⚡ لا تملك صلاحية فتح القنوات.")
      return True
    target_ch = resolve_natural_text_channel(guild, message) or message.channel
    try:
      overwrite = target_ch.overwrites_for(guild.default_role)
      overwrite.send_messages = None
      await target_ch.set_permissions(guild.default_role, overwrite=overwrite)
      await safe_reply(message, angel_spontaneous_confirm(author, "channel", f"🔓 فتحت {target_ch.mention}."))
      await bot.send_modlog(guild, "🔓 فتح قناة", f"تم فتح {target_ch.mention} بواسطة {author.mention}.")
    except Exception:
      await safe_reply(message, "⚠️ لا أملك صلاحية إدارة القنوات هنا.")
    return True

  if any(k in cmd_lower for k in ("سلو مود", "الوضع البطيء", "بطئي الشات", "slowmode")):
    if not (mistress or author.guild_permissions.manage_channels):
      return False
    nums = [int(n) for n in re.findall(r"\b(\d+)\b", cmd_lower)]
    sec = 0 if any(u in cmd_lower for u in ("الغي", "شيل", "شيلي", "فك", "فكي", "وقفي")) else (nums[0] if nums else 5)
    await message.channel.edit(slowmode_delay=max(0, min(21600, sec)))
    await safe_reply(
        message,
        angel_spontaneous_confirm(author, "channel", "⚡ ألغيت الوضع البطيء." if sec == 0 else f"🐢 ضبطت الوضع البطيء على **{sec} ثانية**."),
    )
    return True

  # 21. Polls, Giveaways, Announcements & Tickets via Natural Words
  poll_m = re.match(r"^(?:سوي|انشئي|أنشئي|حطي)\s+تصويت\s*(?:عن|:)?\s*(.+)$", cmd_body, re.IGNORECASE)
  if poll_m:
    q_raw = poll_m.group(1).strip()
    opts = [x.strip() for x in re.split(r"\s+(?:ولا|أو|او|\||/|-)\s+", q_raw) if x.strip()]
    if len(opts) >= 2:
      question_title = "تصويت السيرفر 📊"
      choices_list = opts[:4]
    else:
      question_title = q_raw
      choices_list = ["موافق ✅", "غير موافق ❌"]
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    desc = "\n\n".join(f"{emojis[i]} {opt}" for i, opt in enumerate(choices_list))
    embed = discord.Embed(title=f"📊 {question_title}", description=desc, color=0x2B2D31)
    poll_msg = await safe_reply(message, embed=embed)
    if poll_msg:
      for i in range(len(choices_list)):
        try:
          await poll_msg.add_reaction(emojis[i])
        except Exception:
          pass
    return True

  gw_m = re.match(r"^(?:سوي|ابدئي|انشئي)\s+(?:سحب|قيف اواي|جيف اواي)\s+(?:على\s+)?(.+)$", cmd_body, re.IGNORECASE)
  if gw_m and (mistress or author.guild_permissions.manage_guild):
    gw_tail = gw_m.group(1).strip()
    mins = parse_arabic_duration_minutes(gw_tail, default_mins=30)
    prize_txt = re.sub(r"(?:لمدة|بعد)\s+.*$", "", gw_tail).strip() or "جائزة خاصة 🎁"
    end_time = datetime.now(timezone.utc) + timedelta(minutes=mins)
    end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
    embed = discord.Embed(
        title=f"🎉 سحب: {prize_txt}",
        description=(
            f"اضغط على الزر بالأسفل للمشاركة!\n\n"
            f"👑 **المقدم:** {author.mention}\n"
            f"🏆 **عدد الفائزين:** `1`\n"
            f"⏳ **ينتهي:** {discord.utils.format_dt(end_time, style='R')}"
        ),
        color=0xD4AF37 if mistress else 0x2B2D31,
        timestamp=end_time,
    )
    gw_msg = await message.channel.send(embed=embed, view=GiveawayJoinView(bot.db))
    await bot.db.create_giveaway(gw_msg.id, message.channel.id, guild.id, prize_txt, 1, end_str)
    return True

  ann_m = re.match(r"^(?:اعلني|أعلني|انشري\s+اعلان|انشري\s+إعلان)\s*(?:في\s+<#\d+>\s*)?:?\s*(.+)$", cmd_body, re.IGNORECASE | re.DOTALL)
  if ann_m and (mistress or author.guild_permissions.manage_guild):
    ann_txt = ann_m.group(1).strip()
    dest_ch = resolve_natural_text_channel(guild, message) or message.channel
    embed = discord.Embed(title="📢 إعلان هام", description=ann_txt, color=0xD4AF37 if mistress else 0x2B2D31, timestamp=datetime.now(timezone.utc))
    await dest_ch.send(embed=embed)
    if dest_ch.id != message.channel.id:
      await safe_reply(message, f"✅ نشرت الإعلان في {dest_ch.mention}.")
    return True

  if any(k in cmd_lower for k in ("انشري لوحة التذاكر", "حطي لوحة التذاكر", "لوحة التذاكر هنا")) and (mistress or author.guild_permissions.manage_channels):
    embed = discord.Embed(title="🎫 التذاكر الخاصة", description="اضغط على الزر بالأسفل لفتح تذكرة خاصة.", color=0x2B2D31)
    await message.channel.send(embed=embed, view=TicketPanelView(bot))
    return True

  return False
