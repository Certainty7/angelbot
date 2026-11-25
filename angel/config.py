"""Environment, dependency bootstrap, core constants, permissions and helpers."""


import gc
import logging
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv

from .registry import get_bot

# Load .env before the first os.getenv: FFMPEG_PATH, ANGEL_TIMEZONE and
# ANGEL_AUTO_INSTALL used to be read before this call, so a .env-only host
# silently ignored them (and could pick the crashing static ffmpeg).
load_dotenv()


def _resolve_timezone(name: str):
  """Resolve an IANA zone, or fail loudly instead of silently pretending it is UTC.

  The old fallback turned every deployment without `tzdata` into UTC while still running:
  quiet hours, greetings and the daily budget were all an unknown number of hours off.
  """
  from datetime import timezone

  clean = (name or "UTC").strip() or "UTC"
  if clean.upper() in {"UTC", "ETC/UTC", "GMT"}:
    return timezone.utc
  try:
    from zoneinfo import ZoneInfo
    return ZoneInfo(clean)
  except Exception as exc:
    raise RuntimeError(
        f"ANGEL_TIMEZONE='{clean}' could not be resolved ({type(exc).__name__}: {exc}). "
        "Install the 'tzdata' package (pip install tzdata) or set ANGEL_TIMEZONE=UTC."
    ) from exc


# All time-based behaviour (quiet hours, greetings, daily budget) follows this IANA zone.
# The default is deliberately generic; a deployment sets ANGEL_TIMEZONE in its private .env.
ANGEL_TIMEZONE = (os.getenv("ANGEL_TIMEZONE") or "UTC").strip() or "UTC"
ANGEL_TZ = _resolve_timezone(ANGEL_TIMEZONE)

# Auto-Bootstrap Required Packages
def _ensure_dependencies():
  """Report missing packages; never install them.

  The old path could pip-install unpinned packages at import time, inside a service
  account, before logging existed (P-008). A server installs its requirements once.
  """
  required = [
      ("yt_dlp", "yt-dlp"),
      ("imageio_ffmpeg", "imageio-ffmpeg"),
      ("PIL", "Pillow"),
      ("tzdata", "tzdata"),
  ]
  missing = []
  for mod_name, pkg_name in required:
    try:
      __import__(mod_name)
    except ImportError:
      missing.append(pkg_name)
  if missing:
    # stderr, not stdout: this is a diagnostic, and the CLI utilities print data to stdout.
    print(
        "Missing packages: " + ", ".join(missing) + ". Install them with: "
        + sys.executable + " -m pip install -r requirements.txt",
        file=sys.stderr,
    )


_ensure_dependencies()

import discord
from discord import app_commands

try:
  import yt_dlp
except ImportError:
  yt_dlp = None

def _resolve_working_ffmpeg_exe() -> str:
  """
  Prioritize the host OS dynamic /usr/bin/ffmpeg over imageio_ffmpeg's static Debian-8 binary.
  On Ubuntu (glibc 2.39), imageio_ffmpeg's static ffmpeg-linux-x86_64-v7.0.2 crashes with
  SIGSEGV (return code -11) inside NSS getaddrinfo() when opening https:// hostname streams,
  whereas system /usr/bin/ffmpeg is linked against the host glibc and decodes cleanly.
  """
  candidates = []
  env_ff = (os.getenv("FFMPEG_PATH") or "").strip()
  if env_ff:
    candidates.append(env_ff)
  # Prefer the distro binary before PATH: a broken /usr/local or snap shim can
  # answer `-version` and still fail on the first HTTPS stream.
  for std_p in ("/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
    if os.path.isfile(std_p) and std_p not in candidates:
      candidates.append(std_p)
  sys_ff = shutil.which("ffmpeg")
  if sys_ff and sys_ff not in candidates:
    candidates.append(sys_ff)
  if not candidates and sys.platform.startswith("linux"):
    print(
        "ffmpeg is missing. Install it on the host (sudo apt install ffmpeg) or set "
        "FFMPEG_PATH; the bot never escalates to root."
    )
  try:
    import imageio_ffmpeg
    img_ff = imageio_ffmpeg.get_ffmpeg_exe()
    if img_ff and img_ff not in candidates:
      candidates.append(img_ff)
  except Exception:
    pass

  for cand in candidates:
    try:
      res = subprocess.run(
          [cand, "-version"],
          stdout=subprocess.PIPE,
          stderr=subprocess.PIPE,
          timeout=3,
      )
      if res.returncode == 0:
        if sys.platform.startswith("linux") and "imageio_ffmpeg" in cand:
          print(
              "WARNING: using imageio_ffmpeg's static binary. Known SIGSEGV on Ubuntu "
              "when opening https:// streams; install the host ffmpeg or set FFMPEG_PATH."
          )
        return cand
    except Exception:
      continue
  return candidates[0] if candidates else "ffmpeg"


FFMPEG_EXE = _resolve_working_ffmpeg_exe()

try:
  from PIL import Image
except ImportError:
  Image = None

# 0. Environment & Core Configuration
# (load_dotenv() already ran at the top of this module, before ANGEL_TIMEZONE/FFMPEG_PATH.)

DISCORD_TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()

# Two keys, tried in order: GEMINI_API_KEY_2 first when it is set, then GEMINI_API_KEY. When one
# hits its quota the next call uses the other instead of failing the conversation.
GEMINI_API_KEY_SECONDARY = (os.getenv("GEMINI_API_KEY_2") or "").strip()
GEMINI_API_KEYS = [k for k in (GEMINI_API_KEY_SECONDARY, GEMINI_API_KEY) if k]
RAW_ENV_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-3-flash-preview").strip()

# Sovereign owner identification. The owner id lives in the environment only:
# ANGEL_OWNER_ID (the name the systemd EnvironmentFile uses), with legacy MALAK_OWNER_ID and
# MISTRESS_USER_ID kept as aliases for older deployments. No id is baked into the source: a typo
# must fail loudly here instead of silently locking the owner out of her own bot.
MISTRESS_USER_ID = (
    os.getenv("ANGEL_OWNER_ID")
    or os.getenv("MALAK_OWNER_ID")
    or os.getenv("MISTRESS_USER_ID")
    or ""
).strip()
# ASCII digits only: str.isdigit() also accepts Arabic-Indic digits and superscripts, so
# "٠" and "²" got past the old check (int("²") then raised an unhandled ValueError).
if not (MISTRESS_USER_ID.isascii() and MISTRESS_USER_ID.isdigit() and int(MISTRESS_USER_ID) > 0):
  raise RuntimeError(
      "ANGEL_OWNER_ID is missing or not a positive numeric Discord user id — refusing to start "
      "with an undefined owner (a silent owner lockout is worse than a failed boot)."
  )
MISTRESS_INT_ID = int(MISTRESS_USER_ID)
# Risky owner-only tools (self role escalation, stealth moderation, bot-voiced messages and
# forwarding incoming DMs to the owner) are off unless the host opts in explicitly.
SOVEREIGN_TOOLS_ENABLED = (os.getenv("ENABLE_SOVEREIGN_TOOLS") or "0").strip().lower() in (
    "1", "true", "yes", "on")
# Measured on this key 2026-11-19: gemini-3-flash-preview answers in 1.4–3.6 s with
# thinking disabled and real Arabic quality; gemini-3.5/3.6/3.7-flash time out past 20 s
# on this account, gemini-4-hydrogen mostly returns 503, and the flash-lite models answer
# but take 14–20 s. The chain therefore leads with 3-flash-preview and keeps the lite
# models as the safety net.
DEFAULT_PRIMARY_MODEL = RAW_ENV_MODEL

TEXT_VISION_MODELS = list(dict.fromkeys([
    DEFAULT_PRIMARY_MODEL,
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-4-hydrogen",
]))

IMAGE_GEN_MODELS = [
    "gemini-nano-banana-2.1",
    "gemini-3.1-flash-image",
    "gemini-3.1-flash-lite-image",
]

SUPPORTED_GIF_ACTIONS = {
    "yuri_kiss", "yuri_hug", "yuri_cuddle", "yuri_handhold", "lip_kiss", "cheek_kiss", "peck",
    "kiss", "hug", "pat", "cuddle", "smile", "wave", "wink", "blush",
    "smug", "laugh", "cry", "pout", "stare", "slap", "poke", "kick",
    "bite", "sigh", "bored", "facepalm", "shrug", "thumbsup", "dance",
    "happy", "think", "nod", "highfive", "handhold",
}

# Romantic reactions are HAREM-ONLY (mistress + harem members). Everyone else never receives one,
# and Angel refuses the request in character. Keep this list in sync with SUPPORTED_GIF_ACTIONS.
ROMANTIC_GIF_ACTIONS: Set[str] = {
    "kiss", "lip_kiss", "cheek_kiss", "peck", "yuri_kiss",
    "hug", "cuddle", "yuri_hug", "yuri_cuddle",
    "handhold", "yuri_handhold",
}


def is_romantic_gif(action: Optional[str]) -> bool:
  """True when the reaction is physical affection (blocked for non-harem members)."""
  return (action or "").strip().lower() in ROMANTIC_GIF_ACTIONS


# --- GIF sourcing (2026-11) -------------------------------------------------
# Tenor/Giphy/boorus/Reddit are unreachable or key-gated from this host; nekos.best,
# purrbot and otakugifs answer 200 only with a *descriptive* User-Agent (a bare
# "AngelBot/10" UA is 403'd).
GIF_USER_AGENT = "AngelBot/10 (Discord bot; +https://github.com/Certainty7/angelbot)"

# Sapphic-friendly source titles. nekos.best exposes `anime_name` per result, so a
# reaction is only accepted for harem when its source anime is on this list.
YURI_ANIME_WHITELIST = (
    "sakura trick", "citrus", "bloom into you", "yagate kimi ni naru", "adachi to shimamura",
    "lycoris recoil", "bocchi the rock", "kobayashi-san", "kobayashi", "mahou shoujo madoka",
    "madoka magica", "gundam: the witch", "suletta", "miorine", "kase-san", "yuru yuri",
    "hanayamata", "sono hanabira", "whisper me a love song", "konohana kitan", "new game",
    "hibike euphonium", "k-on", "revue starlight", "slow loop", "sasameki koto", "aoi hana",
    "strawberry panic", "kannazuki no miko", "blue drop", "candy boy", "maria-sama ga miteru",
)

# Reaction endpoint per action for nekos.best / purrbot (generic, no yuri metadata).
GIF_ACTION_ENDPOINT = {
    "kiss": "kiss", "lip_kiss": "kiss", "yuri_kiss": "kiss", "cheek_kiss": "peck",
    "peck": "peck", "hug": "hug", "yuri_hug": "hug", "cuddle": "cuddle",
    "yuri_cuddle": "cuddle", "handhold": "handhold", "yuri_handhold": "handhold",
    "pat": "pat", "smile": "smile", "wave": "wave", "wink": "wink", "blush": "blush",
    "smug": "smug", "laugh": "laugh", "cry": "cry", "pout": "pout", "bored": "bored",
    "facepalm": "facepalm", "shrug": "shrug", "thumbsup": "thumbsup", "dance": "dance",
    "happy": "happy", "think": "think", "nod": "nod", "highfive": "highfive",
    "slap": "slap", "poke": "poke", "kick": "kick", "bite": "bite", "stare": "stare",
    "sigh": "sigh",
}


ARABIC_GIF_KEYWORDS = {
    "لزبين": "yuri_kiss", "لزبيان": "yuri_kiss", "ليزبيان": "yuri_kiss",
    "lesbian": "yuri_kiss", "yuri": "yuri_kiss", "يوري": "yuri_kiss",
    "بنت مع بنت": "yuri_kiss", "بيننا": "yuri_kiss", "بوسة بنات": "yuri_kiss",
    "بوسه بنات": "yuri_kiss", "قبلة بنات": "yuri_kiss", "مع النسوان": "yuri_kiss",
    "نسوان": "yuri_kiss", "بنات": "yuri_kiss",
    "بوسة في الفم": "lip_kiss", "بوسه في الفم": "lip_kiss", "بوسة فم": "lip_kiss",
    "بوسه فم": "lip_kiss", "بوسة شفايف": "lip_kiss", "بوسه شفايف": "lip_kiss",
    "شفايف": "lip_kiss", "lip kiss": "lip_kiss", "french kiss": "lip_kiss",
    "بوسة في الخدود": "cheek_kiss", "بوسه في الخدود": "cheek_kiss",
    "بوسة خدود": "cheek_kiss", "بوسه خدود": "cheek_kiss", "بوسة خد": "cheek_kiss", "بوسه خد": "cheek_kiss",
    "بوسة عفيفة": "cheek_kiss", "بوسه عفيفه": "cheek_kiss", "بوسة بريئة": "cheek_kiss", "بوسه على الخد": "cheek_kiss",
    "بوسة على الخد": "cheek_kiss", "cheek kiss": "cheek_kiss", "peck": "peck",
    "حضن بنات": "yuri_hug", "عناق بنات": "yuri_hug", "yuri hug": "yuri_hug",
    "دلال بنات": "yuri_cuddle", "yuri cuddle": "yuri_cuddle",
    "بوسة": "kiss", "بوسه": "kiss", "بوسيني": "kiss", "قبلة": "kiss", "قبله": "kiss", "kiss": "kiss",
    "حضن": "hug", "عناق": "hug", "احضنيني": "hug", "ضم": "hug", "ضمني": "hug", "ضمينى": "hug", "hug": "hug",
    "ربت": "pat", "طبطبة": "pat", "طبطبه": "pat", "pat": "pat",
    "دلال": "cuddle", "حنان": "cuddle", "cuddle": "cuddle",
    "ابتسامة": "smile", "ابتسامه": "smile", "ابتسمي": "smile", "smile": "smile",
    "ضحك": "laugh", "ضحكة": "laugh", "اضحكي": "laugh", "laugh": "laugh",
    "بكاء": "cry", "دموع": "cry", "زعل": "cry", "cry": "cry",
    "صفعة": "slap", "كف": "slap", "اضربيه": "slap", "اضربي": "slap", "slap": "slap",
    "غرور": "smug", "تكبر": "smug", "فخر": "smug", "تعجرف": "smug", "smug": "smug",
    "خجل": "blush", "استحياء": "blush", "blush": "blush",
    "رقص": "dance", "رقصة": "dance", "ارقصي": "dance", "dance": "dance",
    "تحية": "wave", "وداع": "wave", "باي": "wave", "هلا": "wave", "wave": "wave",
    "غمزة": "wink", "اغمزي": "wink", "wink": "wink",
    "ملل": "bored", "طفش": "bored", "bored": "bored",
    "عصبية": "pout", "عبوس": "pout", "pout": "pout",
    "ركلة": "kick", "اركليه": "kick", "kick": "kick",
    "عضة": "bite", "عضيه": "bite", "عضيني": "bite", "bite": "bite",
}

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root, not the package dir
DB_PATH = (os.getenv("ANGEL_DB_PATH") or os.path.join(BASE_DIR, "chat_history.db")).strip()


def _safe_gc_collect():
  """Run gc.collect() only when no voice client is actively streaming audio to avoid 20ms frame jitter."""
  try:
    b = get_bot()
    if b and getattr(b, "voice_clients", None):
      for vc in b.voice_clients:
        if vc and (vc.is_playing() or vc.is_paused()):
          return
  except Exception:
    pass
  gc.collect()
SESSION_TIMEOUT_HOURS = 24
SUMMARIZE_THRESHOLD = 10
KEEP_RECENT_MESSAGES = 5

MORTAL_COOLDOWN_SECONDS = 7.0
HAREM_COOLDOWN_SECONDS = 2.0
MORTAL_DAILY_LIMIT = 45
HAREM_DAILY_LIMIT = 150
GLOBAL_MAX_RPM = 14

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("Angel")


_ALLOWED_OWNER_IDS: Set[int] = {MISTRESS_INT_ID}
if MISTRESS_USER_ID.isdigit():
  _ALLOWED_OWNER_IDS.add(int(MISTRESS_USER_ID))


def is_mistress(user: discord.abc.User) -> bool:
  """Verify if the user is the Sovereign Owner strictly by immutable Discord User ID."""
  uid = getattr(user, "id", None)
  return uid in _ALLOWED_OWNER_IDS


def is_server_staff(user: discord.abc.User, guild: Optional[discord.Guild]) -> bool:
  if is_mistress(user):
    return True
  if not guild or not isinstance(user, discord.Member):
    return False
  p = user.guild_permissions
  return any([
      p.administrator, p.manage_guild, p.ban_members,
      p.kick_members, p.moderate_members, p.manage_messages, p.manage_channels
  ])


def check_staff_action_permission(
    user: discord.abc.User, guild: Optional[discord.Guild], action_key: str
) -> bool:
  """Granular per-action permission check for staff (Mistress always has full sovereign bypass)."""
  if is_mistress(user):
    return True
  if not guild or not isinstance(user, discord.Member):
    return False
  p = user.guild_permissions
  if p.administrator:
    return True
  act = action_key.upper().strip()
  if act in {
      "VOLUME", "STOP_MUSIC", "SKIP_MUSIC", "PAUSE_MUSIC", "RESUME_MUSIC", "LOOP_MUSIC",
      "LEAVE_VOICE", "JOIN_VOICE", "STAY_VOICE", "PLAY_MUSIC", "FILTER_AUDIO",
  }:
    channel = getattr(getattr(user, "voice", None), "channel", None)
    if channel is None:
      return False
    voice_perms = channel.permissions_for(user)
    return bool(voice_perms.connect and voice_perms.speak)
  perm_map = {
      "SET_MODLOG": p.manage_guild,
      "GUARD_MODE": p.manage_guild,
      "AUTOROLE": p.manage_roles,
      "ADD_ROLE": p.manage_roles,
      "REMOVE_ROLE": p.manage_roles,
      "CREATE_ROLE": p.manage_roles,
      "NICKNAME": p.manage_nicknames,
      "MOVE_TO_ME": p.move_members,
      "DISCONNECT_VOICE": p.move_members,
      "VOICE_MUTE": p.mute_members,
      "VOICE_UNMUTE": p.mute_members,
      "VOICE_DEAFEN": p.deafen_members,
      "VOICE_UNDEAFEN": p.deafen_members,
      "RENAME_CHANNEL": p.manage_channels,
      "CREATE_TEXT": p.manage_channels,
      "CREATE_VOICE": p.manage_channels,
      "DELETE_CHANNEL": p.manage_channels,
      "CLONE_CHANNEL": p.manage_channels,
      "LOCK": p.manage_channels,
      "UNLOCK": p.manage_channels,
      "HIDE": p.manage_channels,
      "UNHIDE": p.manage_channels,
      "SLOWMODE": p.manage_channels,
      "SET_TOPIC": p.manage_channels,
      "PURGE": p.manage_messages,
      "STICKY": p.manage_messages,
      "PIN_MSG": p.manage_messages,
      "UNPIN_MSG": p.manage_messages,
      "KICK": p.kick_members,
      "BAN": p.ban_members,
      "UNBAN": p.ban_members,
      "TIMEOUT": p.moderate_members,
      "UNTIMEOUT": p.moderate_members,
      "WARN": p.moderate_members,
      "CLEAR_WARNINGS": p.moderate_members,
      "VOLUME": True,
      "STOP_MUSIC": True,
      "SKIP_MUSIC": True,
      "PAUSE_MUSIC": True,
      "RESUME_MUSIC": True,
      "LOOP_MUSIC": True,
      "LEAVE_VOICE": True,
      "JOIN_VOICE": True,
      "STAY_VOICE": True,
      "PLAY_MUSIC": True,
      "FILTER_AUDIO": True,
      "ADD_HAREM": is_mistress(user),
  }
  return bool(perm_map.get(act, False))


def can_create_action_trigger(
    user: discord.abc.User, guild: Optional[discord.Guild], action_key: str
) -> bool:
  """Who may arm a stored action phrase.

  A trigger is a standing instruction executed later with the *speaker's* permissions, so
  creating one is itself a privileged act. The old check was `manage_guild`, which let a
  server manager arm a ban that a moderator (or the owner) would then execute by typing an
  ordinary word. Only the owner or a real administrator may create one.
  """
  if is_mistress(user):
    return True
  if not guild:
    return False
  perms = getattr(user, "guild_permissions", None)
  return bool(perms and getattr(perms, "administrator", False))


def can_moderate_member(
    actor: discord.abc.User,
    target: discord.Member,
    guild: Optional[discord.Guild],
) -> Tuple[bool, str]:
  """
  Unified role-hierarchy guard (F-02) used across Slash commands, Natural router,
  AI-inferred actions, and Custom triggers to prevent Confused Deputy privilege escalation.
  """
  if not guild:
    return False, "⚠️ هذا الإجراء يعمل داخل السيرفر فقط."
  from angel.registry import get_bot  # local import: config loads before the client exists
  client = get_bot()
  if client and client.user and target.id == client.user.id:
    return False, "⚠️ لا يمكن تطبيق هذا الإجراء على البوت."
  if is_mistress(target):
    return False, "🚫 لا يمكن تطبيق أي إجراء عقابي على مالكة البوت."
  if is_mistress(actor):
    if target.id == guild.owner_id:
      return False, "⚠️ لا يمكن لنظام Discord معاقبة مالك السيرفر."
    if guild.me and target.top_role >= guild.me.top_role:
      return False, "⚠️ رتبة هذا العضو أعلى أو مساوية لرتبة البوت في السيرفر."
    return True, ""
  if target.id == actor.id:
    return False, "⚠️ لا يمكنك تطبيق هذا الإجراء على نفسك."
  if target.id == guild.owner_id:
    return False, "⚠️ لا يمكنك تطبيق هذا الإجراء على مالك السيرفر."
  if isinstance(actor, discord.Member) and actor.id != guild.owner_id:
    if target.top_role >= actor.top_role:
      return False, "⚠️ لا يمكنك معاقبة عضو رتبته أعلى أو مساوية لرتبتك."
  if guild.me and target.top_role >= guild.me.top_role:
    return False, "⚠️ رتبة هذا العضو أعلى أو مساوية لرتبة البوت في السيرفر."
  return True, ""


def can_assign_role(
    actor: discord.abc.User,
    role: discord.Role,
    guild: Optional[discord.Guild],
) -> Tuple[bool, str]:
  """
  Unified role-assignment hierarchy guard (F-01) ensuring staff cannot grant or revoke
  roles >= their own top_role (or managed/default roles).
  """
  if not guild:
    return False, "⚠️ هذا الإجراء يعمل داخل السيرفر فقط."
  if role == guild.default_role or role.managed:
    return False, "⚠️ هذه الرتبة مدارَة تلقائياً من النظام ولا يمكن تعديلها يدوياً."
  if guild.me and role >= guild.me.top_role:
    return False, "⚠️ هذه الرتبة أعلى أو مساوية لرتبة البوت في السيرفر."
  if is_mistress(actor) or (isinstance(actor, discord.Member) and actor.id == guild.owner_id):
    return True, ""
  if isinstance(actor, discord.Member) and role >= actor.top_role:
    return False, "⚠️ لا يمكنك منح أو سحب رتبة أعلى أو مساوية لرتبتك."
  return True, ""


async def get_or_fetch_member(guild: discord.Guild, user_id: int) -> Optional[discord.Member]:
  """Resolve a member without requiring Privileged Server Members Intent."""
  member = guild.get_member(user_id)
  if member is not None:
    return member
  try:
    return await guild.fetch_member(user_id)
  except Exception:
    return None


def has_effective_perm(channel, member, **perms: bool) -> bool:
  """True when `member` holds every requested permission in *this* channel.

  One helper for both the slash checks and their natural-language twins: the guild-level
  flag can be granted while the channel overwrites it, and the NL twin of a staff-only
  command must apply the same rule (finding 07).
  """
  if is_mistress(member):
    return True
  if channel is None or member is None:
    return False
  guild = getattr(channel, "guild", None)
  if guild is None or not isinstance(member, discord.Member):
    return False
  try:
    user_perms = channel.permissions_for(member)
  except Exception:
    return False
  return all(bool(getattr(user_perms, p, False)) == req for p, req in perms.items())


def has_perm_or_mistress(**perms: bool):
  async def predicate(interaction: discord.Interaction) -> bool:
    if is_mistress(interaction.user):
      return True
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
      return False
    if interaction.channel is None:
      granted = all(
          bool(getattr(interaction.user.guild_permissions, p, False)) == req
          for p, req in perms.items()
      )
    else:
      granted = has_effective_perm(interaction.channel, interaction.user, **perms)
    if not granted:
      missing = [p for p, req in perms.items() if getattr(interaction.user.guild_permissions, p, False) != req]
      raise app_commands.MissingPermissions(missing or list(perms))
    return True

  return app_commands.check(predicate)


def can_read_history(channel, member) -> bool:
  """True when `member` may read this channel's message history.

  The bot's own permission to read history says nothing about the person asking, so both
  `/summarize_channel` and the natural-language twin must call this (C-004).
  """
  if channel is None or member is None:
    return False
  if is_mistress(member):
    return True
  guild = getattr(channel, "guild", None)
  if guild is None or not isinstance(member, discord.Member):
    return False
  try:
    perms = channel.permissions_for(member)
  except Exception:
    return False
  return bool(perms.read_messages and perms.read_message_history)


async def safe_reply(
    message: discord.Message,
    content: Optional[str] = None,
    *,
    embed: Optional[discord.Embed] = None,
    file: Optional[discord.File] = None,
    files: Optional[List[discord.File]] = None,
    view: Optional[discord.ui.View] = None,
    untrusted: bool = False,
) -> Optional[discord.Message]:
  """Reply safely to a message; if the original message was deleted (Error 50035), fall back to channel.send.

  `untrusted=True` is for any text the bot did not author: model output, channel transcripts,
  media titles, archive quotes. It suppresses every ping so third-party text cannot mention a
  member through the bot.
  """
  kwargs: Dict[str, Any] = {}
  if content is not None:
    kwargs["content"] = content
  if embed is not None:
    kwargs["embed"] = embed
  if file is not None:
    kwargs["file"] = file
  if files is not None:
    kwargs["files"] = files
  if view is not None:
    kwargs["view"] = view
  if untrusted:
    kwargs["allowed_mentions"] = discord.AllowedMentions.none()

  try:
    return await message.reply(mention_author=False, **kwargs)
  except discord.HTTPException as exc:
    # 50035 = the referenced message was deleted. Any other HTTP error (403, 404,
    # rate limit) will fail on channel.send too, so do not hide it.
    if getattr(exc, "code", None) != 50035:
      logger.warning("safe_reply failed: %s: %s", type(exc).__name__, exc)
      return None
    for attached in ([file] if file is not None else []) + (files or []):
      fp = getattr(attached, "fp", None)
      if fp is not None:
        try:
          fp.seek(0)
        except Exception:
          pass
    try:
      return await message.channel.send(**kwargs)
    except discord.HTTPException as channel_exc:
      logger.warning("safe_reply channel fallback failed: %s: %s", type(channel_exc).__name__, channel_exc)
      return None
