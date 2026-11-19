"""Flagship systems: /angel, /knowledge, /pulse, /guard, /diagnostics and /rep.

The control-center view, the knowledge board, the pulse dashboard, the guard switch, the
diagnostics report and the reputation cooldown.
"""
import math
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from angel.config import FFMPEG_EXE, has_perm_or_mistress, is_mistress, is_server_staff, logger
from angel.dashboard import build_server_pulse_embed
from angel.ui import AngelControlCenterView


class Flagship(commands.Cog):
  """`/angel`, `/knowledge`, `/pulse`, `/guard`, `/diagnostics`, `/rep`."""

  def __init__(self, bot) -> None:
    self.bot = bot

  @app_commands.command(name="angel", description="فتح مركز تحكم أنجل التفاعلي (Control Center)")
  @app_commands.allowed_installs(guilds=True, users=True)
  @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
  async def angel_control_center_cmd(self, interaction: discord.Interaction):
    mistress = is_mistress(interaction.user)
    staff = is_server_staff(interaction.user, interaction.guild)
    harem_title = self.bot.get_harem_title(interaction.user.id)

    role_badge = "👑 المالكة" if mistress else ("💖 الحريم" if harem_title else ("🛡️ مشرف" if staff else "👤 عضو"))
    embed = discord.Embed(
        title="🪽 مركز تحكم أنجل (Angel Control Center)",
        description=(
            f"مرحباً {interaction.user.mention} ({role_badge})، يمكنكِ التحكم في إعداداتكِ، ذاكرتكِ، الصوتيات، والسيرفر مباشرة من الأزرار بالأسفل:"
        ),
        color=0xD4AF37 if (mistress or harem_title) else 0x2B2D31,
    )
    await interaction.response.send_message(
        embed=embed,
        view=AngelControlCenterView(self.bot, interaction.user, interaction.guild),
        ephemeral=True,
    )


  @app_commands.command(name="knowledge", description="إدارة قاعدة معرفة السيرفر (القوانين، الأسئلة الشائعة، الأدلة)")
  @app_commands.default_permissions(manage_guild=True)
  @app_commands.describe(
      action="العملية المطلوبة",
      topic="عنوان الموضوع أو السؤال (عند الإضافة)",
      content="المحتوى أو الإجابة المعتمدة (عند الإضافة)",
      entry_id="رقم القاعدة (عند الحذف)",
  )
  @app_commands.choices(
      action=[
          app_commands.Choice(name="إضافة معرفة للسيرفر (Add)", value="add"),
          app_commands.Choice(name="عرض قاعدة المعرفة (List)", value="list"),
          app_commands.Choice(name="حذف قاعدة (Remove)", value="remove"),
      ]
  )
  async def knowledge_cmd(
      self,
      interaction: discord.Interaction,
      action: str,
      topic: Optional[str] = None,
      content: Optional[str] = None,
      entry_id: Optional[int] = None,
  ):
    if not interaction.guild:
      await interaction.response.send_message("⚠️ يعمل داخل السيرفرات فقط.", ephemeral=True)
      return

    if not (
        is_mistress(interaction.user)
        or (
            isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.manage_guild
        )
    ):
      await interaction.response.send_message("🚫 قاعدة المعرفة مخصصة للإدارة فقط.", ephemeral=True)
      return

    if action == "list":
      items = await self.bot.db.get_guild_knowledge(interaction.guild.id)
      if not items:
        await interaction.response.send_message("📭 قاعدة معرفة السيرفر فارغة حالياً.", ephemeral=True)
        return
      lines = [f"• **`#{it['id']}` [{it['topic']}]:** {it['content'][:180]}" for it in items[:20]]
      # Discord rejects an embed whose description exceeds 4096 characters.
      embed = discord.Embed(title=f"📚 قاعدة معرفة {interaction.guild.name}"[:256],
                            description="\n".join(lines)[:4096], color=0x2B2D31)
      await interaction.response.send_message(embed=embed, ephemeral=True)
      return

    if action == "add":
      if not topic or not content:
        await interaction.response.send_message("⚠️ أدخلي العنوان في `topic` والمحتوى في `content`.", ephemeral=True)
        return
      kid = await self.bot.db.add_knowledge(interaction.guild.id, topic, content, interaction.user.id)
      await interaction.response.send_message(f"✅ تم حفظ القاعدة **`#{kid}`** ({topic}) في عقل السيرفر.", ephemeral=True)
    elif action == "remove":
      if not entry_id:
        await interaction.response.send_message("⚠️ حددي رقم القاعدة في `entry_id`.", ephemeral=True)
        return
      ok = await self.bot.db.delete_knowledge(interaction.guild.id, entry_id)
      await interaction.response.send_message("✅ تم الحذف." if ok else "⚠️ لم أجد قاعدة بهذا الرقم.", ephemeral=True)


  @app_commands.command(name="pulse", description="عرض لوحة نبض السيرفر ومؤشرات النشاط")
  @app_commands.default_permissions(manage_guild=True)
  @app_commands.guild_only()
  @has_perm_or_mistress(manage_guild=True)
  async def pulse_cmd(self, interaction: discord.Interaction):
    embed = await build_server_pulse_embed(self.bot, interaction.guild)
    await interaction.response.send_message(embed=embed, ephemeral=True)


  @app_commands.command(name="guard", description="إدارة نظام الحماية الذكية ومكافحة السبام (Angel Guard)")
  @app_commands.default_permissions(manage_guild=True)
  @app_commands.guild_only()
  @app_commands.describe(mode="وضع الحماية المطلوب")
  @app_commands.choices(
      mode=[
          app_commands.Choice(name="🛡️ تفعيل الحماية الكاملة (Active)", value="active"),
          app_commands.Choice(name="🧪 وضع تجريبي يسجل في السجلات بدون عقوبة (Dry-Run)", value="dry_run"),
          app_commands.Choice(name="⏹️ إيقاف (Off)", value="off"),
      ]
  )
  @has_perm_or_mistress(manage_guild=True)
  async def guard_cmd(self, interaction: discord.Interaction, mode: str):
    await self.bot.db.set_guard_mode(interaction.guild.id, mode)
    self.bot.guard_modes_cache[interaction.guild.id] = mode
    labels = {
        "active": "🛡️ الحماية الفعالة (كشف السبام والروابط المشبوهة مع كتم تلقائي)",
        "dry_run": "🧪 الوضع التجريبي (Dry-Run: يرسل تنبيهاً في قناة السجلات دون معاقبة العضو)",
        "off": "⏹️ متوقف",
    }
    await interaction.response.send_message(f"✅ تم ضبط **Angel Guard** على: {labels.get(mode, mode)}", ephemeral=True)


  @app_commands.command(name="diagnostics", description="فحص شامل لصحة النظام والاتصال والنماذج")
  @app_commands.default_permissions(administrator=True)
  async def diagnostics_cmd(self, interaction: discord.Interaction):
    if not is_mistress(interaction.user):
      await interaction.response.send_message("🚫 غير مصرح لك باستخدام هذا الأمر.", ephemeral=True)
      return
    await interaction.response.defer(ephemeral=True, thinking=True)

    api_ok, api_ms, api_msg = await self.bot.ai.check_api_models_health()
    ffmpeg_ok = bool(FFMPEG_EXE and (os.path.exists(FFMPEG_EXE) or shutil.which(FFMPEG_EXE)))
    try:
      db_ok, table_count = await self.bot.db.health_check()
    except Exception as exc:
      logger.warning("diagnostics db check failed: %s: %s", type(exc).__name__, exc)
      db_ok, table_count = False, 0
    latency = self.bot.latency
    latency_text = f"{round(latency * 1000)}ms" if math.isfinite(latency) else "—"
    uptime = datetime.now(timezone.utc) - self.bot.start_time
    h, rem = divmod(int(uptime.total_seconds()), 3600)
    m, s = divmod(rem, 60)

    lat_lines = [
        f"• `{mod}`: `{self.bot.quota.model_usage_stats[mod]}` طلب (آخر زمن: `{self.bot.quota.model_latency_ms.get(mod, 0)}ms`)"
        for mod in self.bot.quota.model_usage_stats
    ] or ["• لا توجد طلبات مسجلة بعد"]

    embed = discord.Embed(title="🔬 تشخيص النظام الشامل (Angel Diagnostics)", color=0xD4AF37, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="🌐 بوابة Discord", value=f"✅ متصل (`{latency_text}`)", inline=True)
    embed.add_field(name="🧠 واجهة الذكاء", value=f"{'✅' if api_ok else '⚠️'} {api_msg[:1024]} (`{api_ms}ms`)", inline=True)
    embed.add_field(name="🎙️ محرك الصوت FFmpeg", value="✅ جاهز (`48kHz Opus`)" if ffmpeg_ok else "⚠️ غير متوفر", inline=True)
    embed.add_field(name="🗄️ قاعدة البيانات SQLite", value=f"{'✅ متصلة' if db_ok else '⚠️ تعذر الفحص'} (`{table_count}` جدولاً)", inline=True)
    embed.add_field(name="⏱️ مدة التشغيل", value=f"`{h}h {m}m {s}s`", inline=True)
    embed.add_field(name="🛠️ حالة المجدول", value=(self.bot.quota.last_scheduler_error or "✅ يعمل بدون أخطاء")[:1024], inline=True)
    embed.add_field(name="📊 إحصاءات المحركات وزمن الاستجابة", value="\n".join(lat_lines)[:1024], inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


  @app_commands.command(name="rep", description="منح نقطة سمعة وتقدير لعضو في السيرفر")
  @app_commands.guild_only()
  @app_commands.describe(member="اختر العضو")
  async def rep_cmd(self, interaction: discord.Interaction, member: discord.Member):
    if member.id == interaction.user.id or member.bot:
      await interaction.response.send_message("⚠️ لا يمكنك منح نقاط سمعة لنفسك أو لبوت.", ephemeral=True)
      return
    now_m = time.monotonic()
    rep_key = (interaction.guild.id, interaction.user.id)
    last_rep = self.bot.rep_cooldowns.get(rep_key)
    if last_rep is not None and now_m - last_rep < 3600 and not is_mistress(interaction.user):
      rem_m = int((3600 - (now_m - last_rep)) // 60) + 1
      await interaction.response.send_message(f"⏳ يمكنك منح نقطة سمعة جديدة بعد **{rem_m} دقيقة**.", ephemeral=True)
      return
    new_rep = await self.bot.db.add_rep(interaction.guild.id, member.id)
    self.bot.rep_cooldowns[rep_key] = now_m
    await interaction.response.send_message(f"🌟 منح {interaction.user.mention} نقطة سمعة إلى {member.mention}! (إجمالي السمعة: **`+{new_rep}`**)")



def install(bot) -> None:
  """Attach this cog's commands to the tree without an event loop (see module docstring)."""
  for command in Flagship(bot).get_app_commands():
    bot.tree.add_command(command)
