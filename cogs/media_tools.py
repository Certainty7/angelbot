"""Media tools: `/fix` for social media links and `/cleanup` for storage and database housekeeping.
"""
import io
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from angel.config import is_mistress
from angel.media import chunk_slides, perform_storage_cleanup, process_social_media_url_multi
from angel.net import get_media_download_semaphore
from angel.output_filter import filter_outgoing

# One `/fix` per member every few seconds: a loop of distinct links otherwise keeps several
# yt-dlp subprocesses and large downloads in flight on a 580 MB cgroup.
_FIX_LAST_AT: dict[int, float] = {}
_FIX_COOLDOWN_S = 8.0


class MediaTools(commands.Cog):
  """Video/gallery fixer and the storage cleanup report."""

  def __init__(self, bot) -> None:
    self.bot = bot

  @app_commands.command(
      name="fix",
      description="عرض فيديو أو ألبوم صور TikTok أو Instagram أو X أو Reddit مباشرة في المحادثة",
  )
  @app_commands.allowed_installs(guilds=True, users=True)
  @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
  @app_commands.describe(url="رابط الفيديو أو البوست")
  async def fix_cmd(self, interaction: discord.Interaction, url: str):
    if interaction.guild and not self.bot.social_fixer_cache.get(interaction.guild.id, True):
      await interaction.response.send_message(
          "⚙️ مصلّح الروابط معطّل في هذا السيرفر. فعّليه من `/setup`.", ephemeral=True)
      return
    now = time.monotonic()
    last_fix = _FIX_LAST_AT.get(interaction.user.id)
    if last_fix is not None and now - last_fix < _FIX_COOLDOWN_S:
      await interaction.response.send_message("⏳ انتظر بضع ثوانٍ قبل الرابط التالي.", ephemeral=True)
      return
    # Prune only expired entries; clearing the whole map on size lets a loop of
    # distinct users bypass the cooldown.
    if len(_FIX_LAST_AT) > 2000:
      for uid, stamp in list(_FIX_LAST_AT.items()):
        if now - stamp >= _FIX_COOLDOWN_S:
          _FIX_LAST_AT.pop(uid, None)
    _FIX_LAST_AT[interaction.user.id] = now
    await interaction.response.defer()
    max_b = min(getattr(interaction.guild, "filesize_limit", 10 * 1024 * 1024), 25 * 1024 * 1024) if interaction.guild else 10 * 1024 * 1024
    async with get_media_download_semaphore():
      media_files, fixed_url, caption = await process_social_media_url_multi(url.strip(), max_bytes=max_b)
    caption = filter_outgoing((caption or "")[:1900]) if caption else None
    no_mentions = discord.AllowedMentions.none()
    if media_files:
      default_icon = "🎬" if any(fn.endswith(".mp4") for _, fn in media_files) else "📸"
      # Discord caps a message at 10 attachments: every batch goes out, no slide is dropped.
      for index, batch in enumerate(chunk_slides(media_files)):
        files = [discord.File(io.BytesIO(b), filename=fn) for b, fn in batch]
        if index == 0:
          await interaction.followup.send(content=caption or default_icon, files=files, allowed_mentions=no_mentions)
        else:
          await interaction.followup.send(files=files, allowed_mentions=no_mentions)
    elif fixed_url:
      await interaction.followup.send(
          content=filter_outgoing(fixed_url), allowed_mentions=no_mentions)
    else:
      await interaction.followup.send("⚠️ تعذر استخراج الوسائط من هذا الرابط (قد يكون الحساب خاصاً أو الرابط غير مدعوم).", ephemeral=True)


  @app_commands.command(
      name="cleanup",
      description="تنظيف تخزين البوت من الملفات المؤقتة والقمامة وضغط قاعدة البيانات",
  )
  @app_commands.default_permissions(manage_guild=True)
  async def cleanup_cmd(self, interaction: discord.Interaction):
    # This deletes GLOBAL storage, so a server admin is not allowed to trigger it.
    if not is_mistress(interaction.user):
      await interaction.response.send_message("🚫 أمر التنظيف الشامل مخصص للمالكة فقط.", ephemeral=True)
      return
    await interaction.response.defer(ephemeral=True, thinking=True)
    stats = await perform_storage_cleanup(deep=True)
    freed_str = (
        f"`{stats['freed_mb']} MB` (`{stats['deleted_files']}` ملف مؤقت)"
        if stats["freed_bytes"] >= 1024 * 100
        else f"`{round(stats['freed_bytes'] / 1024.0, 1)} KB` (`{stats['deleted_files']}` ملف مؤقت)"
    )
    embed = discord.Embed(
        title="🧹 تقرير تنظيف التخزين والذاكرة",
        description="تم مسح الملفات المؤقتة، كاش الصوت والفيديو، وضغط قاعدة البيانات بنجاح:",
        color=0xD4AF37 if is_mistress(interaction.user) else 0x2B2D31,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="🗑️ القمامة المحذوفة", value=freed_str, inline=True)
    embed.add_field(name="🗄️ قاعدة البيانات (SQLite)", value=f"`{stats['db_size_kb']} KB` (حُذف `{stats['pruned_rows']}` سجل قديم)", inline=True)
    embed.add_field(name="💾 المساحة الحرة بالسيرفر", value=f"`{stats['disk_free_gb']} GB` / `{stats['disk_total_gb']} GB`", inline=True)
    if stats["ram_mb"] > 0:
      embed.add_field(name="🧠 استهلاك الرام الحالي", value=f"`{stats['ram_mb']} MB`", inline=True)
    await interaction.followup.send(embed=embed)



def install(bot) -> None:
  """Attach this cog's commands to the tree without an event loop (see module docstring)."""
  for command in MediaTools(bot).get_app_commands():
    bot.tree.add_command(command)
