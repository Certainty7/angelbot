"""Music cog: /play, /skip, /queue, /playlist.

Playback lives in `angel.voice_engine`, which uses the public voice API only. This cog is the
user-facing shell: defer first, answer every failure with a reason, never raise into the loop.
"""
from __future__ import annotations

import os
from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from angel.audio_source import ResolveError, clean_reason
from angel.config import is_mistress, logger
from angel.voice_engine import MusicEngine

MUSIC_ENABLED = os.environ.get("MUSIC_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
MAX_QUEUE = 50
# The kill switch and "you are not in a voice channel" are different answers.
DISABLED_REPLY = "🔇 ميزة الموسيقى معطّلة مؤقتاً (`MUSIC_ENABLED=0`)."
NO_VOICE_REPLY = "🎧 ادخلي روم صوتي أولاً حتى أستطيع التشغيل."


def _fmt(seconds: float) -> str:
  total = int(seconds or 0)
  hours, rest = divmod(total, 3600)
  minutes, secs = divmod(rest, 60)
  return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class Music(commands.Cog):
  """Voice playback for one guild at a time, rate-limited by the queue cap."""

  def __init__(self, bot: commands.Bot):
    self.bot = bot
    self.engine = MusicEngine(bot)

  # ---- guards ------------------------------------------------------------
  @staticmethod
  def _member_channel(interaction: discord.Interaction) -> Optional[discord.VoiceChannel]:
    state = getattr(interaction.user, "voice", None)
    channel = getattr(state, "channel", None)
    return channel if isinstance(channel, discord.VoiceChannel) else None

  async def _require_voice(self, interaction: discord.Interaction) -> Optional[discord.VoiceChannel]:
    if not MUSIC_ENABLED:
      raise app_commands.CheckFailure("music disabled by MUSIC_ENABLED")
    channel = self._member_channel(interaction)
    if channel is None:
      raise app_commands.CheckFailure("no voice channel")
    return channel

  @staticmethod
  def _check_failure_reply() -> str:
    """The reason a CheckFailure happened decides the sentence."""
    return DISABLED_REPLY if not MUSIC_ENABLED else NO_VOICE_REPLY

  # ---- commands ----------------------------------------------------------
  @app_commands.command(name="play", description="تشغيل أغنية أو قائمة من رابط أو بحث")
  @app_commands.guild_only()
  @app_commands.describe(query="رابط SoundCloud/YouTube أو نص للبحث")
  async def play(self, interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    try:
      channel = await self._require_voice(interaction)
    except app_commands.CheckFailure:
      await interaction.followup.send(self._check_failure_reply(), ephemeral=True)
      return

    guild = interaction.guild
    voice = guild.voice_client
    if voice is not None and voice.is_connected() and voice.channel and voice.channel.id != channel.id:
      await interaction.followup.send(
          f"🎧 أنجل مشغّلة في {voice.channel.mention} الآن. انضمي لنفس الروم أو أوقفيها أولاً.",
          ephemeral=True,
      )
      return
    state = self.engine.state(guild.id)
    state.text_channel_id = interaction.channel_id
    if len(state.tracks) >= MAX_QUEUE:
      await interaction.followup.send(
          f"📚 القائمة ممتلئة (`{MAX_QUEUE}`). استخدمي `/skip` أو انتظري.", ephemeral=True
      )
      return

    try:
      await self.engine.ensure_connected(channel)
      track = await self.engine.enqueue(channel, query, interaction.user)
    except ResolveError as exc:
      await interaction.followup.send(f"⚠️ تعذر إيجاد الصوت: `{clean_reason(str(exc))}`", ephemeral=True)
      return
    except Exception as exc:  # noqa: BLE001 - voice join failures must be answered, not raised
      logger.warning(f"music-join failed: {type(exc).__name__}: {exc}")
      await interaction.followup.send(
          f"⚠️ تعذر الدخول للروم الصوتي: `{type(exc).__name__}`", ephemeral=True
      )
      return

    if len(state.tracks) > MAX_QUEUE:
      state.remove_at(len(state.tracks) - 1)
      await interaction.followup.send(
          f"📚 القائمة ممتلئة (`{MAX_QUEUE}`). استخدمي `/skip` أو انتظري.", ephemeral=True
      )
      return

    playing = await self.engine.start(guild)
    if playing is track:
      msg = f"🎶 أشغّل الآن: **{track.title}** (`{track.duration_text}`) من `{track.source}`"
      dave = self.engine.last_dave.get(guild.id) or {}
      if dave.get("ver") and not dave.get("can_encrypt"):
        msg += "\n🔇 التشفير الصوتي لم يكتمل بعد — إن لم تسمعي شيئاً أعيدي المحاولة بعد ثانية."
      await interaction.followup.send(msg)
    else:
      position = len(state.tracks)
      await interaction.followup.send(
          f"➕ أُضيفت للقائمة (#{position}): **{track.title}** (`{track.duration_text}`)"
      )

  @app_commands.command(name="skip", description="تخطي الأغنية الحالية")
  @app_commands.guild_only()
  async def skip(self, interaction: discord.Interaction):
    await interaction.response.defer()
    try:
      channel = await self._require_voice(interaction)
    except app_commands.CheckFailure:
      await interaction.followup.send(self._check_failure_reply(), ephemeral=True)
      return
    voice = interaction.guild.voice_client if interaction.guild else None
    if voice is None:
      await interaction.followup.send("🔇 لا يوجد تشغيل الآن.", ephemeral=True)
      return
    if voice.channel and voice.channel.id != channel.id:
      await interaction.followup.send(
          f"🎧 انضمي إلى {voice.channel.mention} حتى تتمكني من التخطي.", ephemeral=True
      )
      return
    skipped = await self.engine.skip(interaction.guild)
    nxt = self.engine.state(interaction.guild.id).current
    if skipped is None:
      await interaction.followup.send("🔇 القائمة فارغة.", ephemeral=True)
    elif nxt is None:
      await interaction.followup.send(f"⏭️ تخطيت **{skipped.title}** — لا شيء بعدها.")
    else:
      await interaction.followup.send(f"⏭️ تخطيت **{skipped.title}** → **{nxt.title}**")

  @app_commands.command(name="queue", description="عرض قائمة التشغيل الحالية")
  @app_commands.guild_only()
  async def queue(self, interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    state = self.engine.state(interaction.guild.id)
    embed = discord.Embed(title="🎧 قائمة التشغيل", color=0x2B2D31)
    current = state.current
    embed.add_field(
        name="الآن",
        value=f"**{current.title}** (`{current.duration_text}`)" if current else "—",
        inline=False,
    )
    upcoming = state.snapshot(10)
    if upcoming:
      lines = [
          f"`{i}.` **{t.title}** (`{t.duration_text}`) — {t.requester_name}"
          for i, t in enumerate(upcoming, 1)
      ]
      embed.add_field(name=f"التالي ({len(state.tracks)})", value="\n".join(lines)[:1000], inline=False)
    else:
      embed.add_field(name="التالي", value="القائمة فارغة.", inline=False)
    embed.set_footer(
        text=f"loop={'on' if state.loop else 'off'} · volume={int(state.volume * 100)}%"
        f" · المدة الكلية {_fmt(state.total_duration)}"
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

  @app_commands.command(name="playlist", description="حفظ قائمة أو استعراضها أو حذفها")
  @app_commands.guild_only()
  @app_commands.describe(action="list أو save أو load أو delete", name="اسم القائمة", query="رابط أو بحث (مع save)")
  @app_commands.choices(
      action=[
          app_commands.Choice(name="استعراض", value="list"),
          app_commands.Choice(name="حفظ", value="save"),
          app_commands.Choice(name="تشغيل", value="load"),
          app_commands.Choice(name="حذف", value="delete"),
      ]
  )
  async def playlist(
      self,
      interaction: discord.Interaction,
      action: app_commands.Choice[str],
      name: Optional[str] = None,
      query: Optional[str] = None,
  ):
    await interaction.response.defer(ephemeral=action.value != "load")
    guild_id = interaction.guild.id

    if action.value == "list":
      rows = await self.bot.db.get_saved_playlists(guild_id)
      if not rows:
        await interaction.followup.send("📭 لا توجد قوائم محفوظة بعد.", ephemeral=True)
        return
      by_name: dict[str, List[str]] = {}
      for row in rows:
        by_name.setdefault(row["name"], []).append(row["query"])
      lines = [f"**{n}** — `{len(q)}` عنصراً" for n, q in sorted(by_name.items())]
      await interaction.followup.send(
          embed=discord.Embed(title="📚 القوائم المحفوظة", description="\n".join(lines)[:2000], color=0x2B2D31),
          ephemeral=True,
      )
      return

    if not name:
      await interaction.followup.send("⚠️ اكتبي اسم القائمة.", ephemeral=True)
      return

    if action.value == "save":
      if not query:
        await interaction.followup.send("⚠️ أضيفي `query` (رابط أو بحث) للحفظ.", ephemeral=True)
        return
      await self.bot.db.save_playlist_track(guild_id, name.strip(), query.strip(), interaction.user.id)
      await interaction.followup.send(f"💾 حُفظت `{query.strip()[:80]}` في **{name}**.", ephemeral=True)
      return

    if action.value == "delete":
      if not (is_mistress(interaction.user) or interaction.user.guild_permissions.manage_guild):
        await interaction.followup.send(
            "🚫 حذف قائمة محفوظة متاح لإدارة السيرفر فقط.", ephemeral=True
        )
        return
      removed = await self.bot.db.delete_playlist_track(guild_id, name.strip())
      await interaction.followup.send(
          f"🗑️ حُذفت **{name}**." if removed else f"⚠️ لا توجد قائمة باسم **{name}**.", ephemeral=True
      )
      return

    # load
    rows = await self.bot.db.get_saved_playlists(guild_id)
    tracks = [r["query"] for r in rows if r["name"] == name.strip()]
    if not tracks:
      await interaction.followup.send(f"⚠️ لا توجد قائمة باسم **{name}**.", ephemeral=True)
      return
    try:
      channel = await self._require_voice(interaction)
    except app_commands.CheckFailure:
      await interaction.followup.send(self._check_failure_reply(), ephemeral=True)
      return
    state = self.engine.state(guild_id)
    state.text_channel_id = interaction.channel_id
    room = MAX_QUEUE - len(state.tracks)
    if room <= 0:
      await interaction.followup.send(
          f"📚 القائمة ممتلئة (`{MAX_QUEUE}`).", ephemeral=True
      )
      return
    tracks = tracks[:room]
    voice = interaction.guild.voice_client
    if voice is not None and voice.is_connected() and voice.channel and voice.channel.id != channel.id:
      await interaction.followup.send(
          f"🎧 أنجل مشغّلة في {voice.channel.mention} الآن. انضمي لنفس الروم أولاً.",
          ephemeral=True,
      )
      return
    try:
      await self.engine.ensure_connected(channel)
    except Exception as exc:  # noqa: BLE001 - answer the failure instead of crashing the interaction
      logger.warning(f"music-playlist join failed: {type(exc).__name__}: {exc}")
      await interaction.followup.send("⚠️ تعذر الدخول للروم الصوتي.", ephemeral=True)
      return
    added, failed = 0, 0
    for item in tracks:
      try:
        await self.engine.enqueue(channel, item, interaction.user)
        added += 1
      except ResolveError:
        failed += 1
    await self.engine.start(interaction.guild)
    msg = f"▶️ شغّلت **{name}**: `{added}` عنصراً"
    if failed:
      msg += f" (`{failed}` فشل)"
    await interaction.followup.send(msg)


async def setup(bot: commands.Bot) -> None:
  await bot.add_cog(Music(bot))
  logger.info("music cog loaded")
