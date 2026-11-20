"""Community utilities: snipe, edit snipe, AFK, reminders, info cards, polls, ping and the
auto-reply board.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from angel.config import has_perm_or_mistress
from angel.interactions import _safe_interaction_reply
from angel.ui import GiveawayJoinView, TicketPanelView


class Community(commands.Cog):
  """`/snipe`, `/editsnipe`, `/afk`, `/remind`, `/serverinfo`, `/userinfo`, `/avatar`, `/poll`,
  `/ping`, `/auto_reply`, `/giveaway`, `/ticket_panel`."""

  def __init__(self, bot) -> None:
    self.bot = bot

  @app_commands.command(name="snipe", description="كشف آخر رسالة حُذفت في القناة")
  @app_commands.guild_only()
  @app_commands.default_permissions(manage_messages=True)
  @has_perm_or_mistress(manage_messages=True)
  async def snipe_cmd(self, interaction: discord.Interaction):
    data = self.bot.snipe_cache.get(interaction.channel.id)
    if not data:
      await interaction.response.send_message("🔍 لا توجد رسائل محذوفة مؤخراً هنا.", ephemeral=True)
      return
    embed = discord.Embed(
        title="🕵️ رسالة محذوفة",
        description=data["content"],
        color=0x2B2D31,
        timestamp=data["deleted_at"],
    )
    embed.set_author(name=data["author_name"], icon_url=data["author_avatar"])
    if data["attachment"]:
      embed.set_image(url=data["attachment"])
    await interaction.response.send_message(embed=embed)


  @app_commands.command(name="editsnipe", description="كشف آخر رسالة تم تعديلها في القناة")
  @app_commands.guild_only()
  @app_commands.default_permissions(manage_messages=True)
  @has_perm_or_mistress(manage_messages=True)
  async def editsnipe_cmd(self, interaction: discord.Interaction):
    data = self.bot.editsnipe_cache.get(interaction.channel.id)
    if not data:
      await interaction.response.send_message("🔍 لا توجد رسائل معدلة مؤخراً هنا.", ephemeral=True)
      return
    embed = discord.Embed(title="✏️ رسالة معدلة", color=0x2B2D31, timestamp=data["edited_at"])
    embed.set_author(name=data["author_name"], icon_url=data["author_avatar"])
    embed.add_field(name="قبل", value=data["before"][:1020], inline=False)
    embed.add_field(name="بعد", value=data["after"][:1020], inline=False)
    await interaction.response.send_message(embed=embed)


  @app_commands.command(name="afk", description="تفعيل وضع الغياب التلقائي (AFK)")
  @app_commands.guild_only()
  @app_commands.describe(reason="سبب الغياب")
  async def afk_cmd(self, interaction: discord.Interaction, reason: str = "مشغول حالياً"):
    # The reason is member-authored and echoed later by the bot: cap it and never let it ping.
    reason = (reason or "مشغول حالياً").strip()[:120]
    self.bot.afk_cache[(interaction.guild.id, interaction.user.id)] = (
        reason, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    await _safe_interaction_reply(
        interaction, f"💤 تم تفعيل وضع الغياب: **{reason}**", ephemeral=False, untrusted=True
    )
    await self.bot.db.set_afk(interaction.guild.id, interaction.user.id, reason)


  @app_commands.command(name="serverinfo", description="عرض معلومات السيرفر")
  @app_commands.guild_only()
  async def serverinfo_cmd(self, interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"🏰 {guild.name}"[:256], color=0x2B2D31, timestamp=datetime.now(timezone.utc))
    if guild.icon:
      embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="المالك", value=f"<@{guild.owner_id}>", inline=True)
    embed.add_field(name="الأعضاء", value=str(guild.member_count), inline=True)
    embed.add_field(name="الرتب", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="تاريخ التأسيس", value=discord.utils.format_dt(guild.created_at, style="D"), inline=False)
    await interaction.response.send_message(embed=embed)


  @app_commands.command(name="userinfo", description="عرض بطاقة معلومات عضو")
  @app_commands.describe(member="اختر العضو")
  async def userinfo_cmd(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    embed = discord.Embed(title=f"👤 {target.display_name}"[:256], color=0x2B2D31)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="الحساب", value=f"`{target.name}`", inline=True)
    embed.add_field(name="المعرف", value=f"`{target.id}`", inline=True)
    embed.add_field(name="تاريخ الحساب", value=discord.utils.format_dt(target.created_at, style="R"), inline=True)
    if isinstance(target, discord.Member) and target.joined_at:
      embed.add_field(name="انضم للسيرفر", value=discord.utils.format_dt(target.joined_at, style="R"), inline=True)
    await interaction.response.send_message(embed=embed)


  @app_commands.command(name="avatar", description="عرض الصورة الشخصية لعضو")
  @app_commands.allowed_installs(guilds=True, users=True)
  @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
  @app_commands.describe(member="اختر العضو")
  async def avatar_cmd(self, interaction: discord.Interaction, member: Optional[discord.User] = None):
    target = member or interaction.user
    embed = discord.Embed(title=f"🖼️ {target.display_name}", color=0x2B2D31)
    embed.set_image(url=target.display_avatar.with_size(1024).url)
    await interaction.response.send_message(embed=embed)


  @app_commands.command(name="poll", description="إنشاء تصويت في القناة")
  @app_commands.guild_only()
  @app_commands.describe(question="السؤال", option1="الخيار 1", option2="الخيار 2", option3="الخيار 3", option4="الخيار 4")
  async def poll_cmd(
      self,
      interaction: discord.Interaction,
      question: str,
      option1: str,
      option2: str,
      option3: Optional[str] = None,
      option4: Optional[str] = None,
  ):
    options = [o[:200] for o in (option1, option2, option3, option4) if o]
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    desc = "\n\n".join(f"{emojis[i]} {opt}" for i, opt in enumerate(options))
    embed = discord.Embed(title=f"📊 {question}"[:256], description=desc[:4096], color=0x2B2D31)
    await interaction.response.send_message(embed=embed)
    poll_msg = await interaction.original_response()
    for i in range(len(options)):
      await poll_msg.add_reaction(emojis[i])


  @app_commands.command(name="ping", description="فحص سرعة الاستجابة")
  async def ping_cmd(self, interaction: discord.Interaction):
    uptime = datetime.now(timezone.utc) - self.bot.start_time
    h, rem = divmod(int(uptime.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    latency = self.bot.latency
    latency_text = f"{round(latency * 1000)}ms" if math.isfinite(latency) else "—"
    embed = discord.Embed(title="🪽 Angel", color=0x2B2D31)
    embed.add_field(name="الاستجابة", value=f"`{latency_text}`", inline=True)
    embed.add_field(name="مدة التواجد", value=f"`{h}h {m}m {s}s`", inline=True)
    await interaction.response.send_message(embed=embed)


  @app_commands.command(name="auto_reply", description="إدارة الردود التلقائية النصية في السيرفر")
  @app_commands.default_permissions(manage_guild=True)
  @app_commands.guild_only()
  @app_commands.describe(action="العملية", trigger="الكلمة", response="الرد")
  @app_commands.choices(
      action=[
          app_commands.Choice(name="إضافة (Add)", value="add"),
          app_commands.Choice(name="حذف (Remove)", value="remove"),
          app_commands.Choice(name="عرض القائمة (List)", value="list"),
      ]
  )
  @has_perm_or_mistress(manage_guild=True)
  async def auto_reply_cmd(
      self,
      interaction: discord.Interaction,
      action: str,
      trigger: Optional[str] = None,
      response: Optional[str] = None,
  ):
    gid = interaction.guild.id
    if action == "list":
      triggers = await self.bot.db.get_auto_triggers(gid)
      if not triggers:
        await interaction.response.send_message("📭 لا توجد ردود تلقائية.", ephemeral=True)
        return
      desc = "\n".join(f"• **`{k}`** ⬅️ {v[:100]}" for k, v in triggers.items())
      embed = discord.Embed(title="الردود التلقائية", description=desc[:4000], color=0x2B2D31)
      await interaction.response.send_message(embed=embed, ephemeral=True)
    elif action == "add":
      if not trigger or not response:
        await interaction.response.send_message("⚠️ أكملي الحقول المطلوبة.", ephemeral=True)
        return
      await self.bot.db.set_auto_trigger(gid, trigger[:100], response[:1000])
      self.bot.auto_triggers_cache[gid] = await self.bot.db.get_auto_triggers(gid)
      await interaction.response.send_message(f"✅ تم حفظ الرد للكلمة `{trigger[:100]}`.", ephemeral=True)
    elif action == "remove":
      if not trigger:
        await interaction.response.send_message("⚠️ حددي الكلمة.", ephemeral=True)
        return
      deleted = await self.bot.db.remove_auto_trigger(gid, trigger[:100])
      self.bot.auto_triggers_cache[gid] = await self.bot.db.get_auto_triggers(gid)
      await interaction.response.send_message("✅ تم الحذف." if deleted else "⚠️ غير موجودة.", ephemeral=True)


  @app_commands.command(name="giveaway", description="بدء سحب تفاعلي في القناة")
  @app_commands.default_permissions(manage_guild=True)
  @app_commands.guild_only()
  @app_commands.describe(minutes="المدة بالدقائق", winners="عدد الفائزين", prize="الجائزة")
  @has_perm_or_mistress(manage_guild=True)
  async def giveaway_cmd(
      self,
      interaction: discord.Interaction,
      minutes: app_commands.Range[int, 1, 10080],
      winners: app_commands.Range[int, 1, 10],
      prize: str,
  ):
    end_time = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
    embed = discord.Embed(
        title=f"🎉 سحب: {prize}"[:256],
        description=(
            f"اضغط على الزر بالأسفل للمشاركة!\n\n"
            f"👑 **المقدم:** {interaction.user.mention}\n"
            f"🏆 **عدد الفائزين:** `{winners}`\n"
            f"⏳ **ينتهي:** {discord.utils.format_dt(end_time, style='R')}"
        )[:4096],
        color=0x2B2D31,
        timestamp=end_time,
    )
    await interaction.response.send_message(embed=embed, view=GiveawayJoinView(self.bot.db))
    msg = await interaction.original_response()
    await self.bot.db.create_giveaway(msg.id, interaction.channel.id, interaction.guild.id, prize[:200], winners, end_str)


  @app_commands.command(name="ticket_panel", description="نشر لوحة فتح التذاكر الخاصة")
  @app_commands.default_permissions(manage_channels=True)
  @app_commands.guild_only()
  @app_commands.describe(title="العنوان", description="الوصف")
  @has_perm_or_mistress(manage_channels=True)
  async def ticket_panel_cmd(
      self,
      interaction: discord.Interaction,
      title: str = "🎫 التذاكر الخاصة",
      description: str = "اضغط على الزر بالأسفل لفتح تذكرة خاصة.",
  ):
    embed = discord.Embed(title=title[:256], description=description[:4096], color=0x2B2D31)
    await interaction.channel.send(embed=embed, view=TicketPanelView(self.bot))
    await interaction.response.send_message("✅ تم نشر اللوحة.", ephemeral=True)


def install(bot) -> None:
  """Attach this cog's commands to the tree without an event loop (see module docstring)."""
  for command in Community(bot).get_app_commands():
    bot.tree.add_command(command)
