"""Moderation and administration: kick, ban, timeout, warnings, channels, roles, announcements,
modlog and command sync.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from angel.config import can_assign_role, can_moderate_member, has_perm_or_mistress, is_mistress


class Admin(commands.Cog):
  """Kick/ban/timeout, warnings, channel and role management, announcements, modlog, sync."""

  def __init__(self, bot) -> None:
    self.bot = bot

  @app_commands.command(name="kick", description="طرد عضو من السيرفر")
  @app_commands.default_permissions(kick_members=True)
  @app_commands.describe(member="العضو", reason="السبب")
  @has_perm_or_mistress(kick_members=True)
  async def kick_cmd(self, interaction: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    allowed, why = can_moderate_member(interaction.user, member, interaction.guild)
    if not allowed:
      await interaction.response.send_message(why, ephemeral=True)
      return
    await member.kick(reason=f"By {interaction.user}: {reason}")
    desc = f"**العضو:** {member.mention}\n**السبب:** {reason}"
    embed = discord.Embed(title="👢 تم طرد العضو", description=desc, color=0x2B2D31)
    await interaction.response.send_message(embed=embed)
    await self.bot.send_modlog(interaction.guild, "👢 طرد عضو", desc)


  @app_commands.command(name="ban", description="حظر عضو من السيرفر")
  @app_commands.default_permissions(ban_members=True)
  @app_commands.describe(member="العضو", reason="السبب", delete_days="حذف رسائله (0-7 أيام)")
  @has_perm_or_mistress(ban_members=True)
  async def ban_cmd(
      self,
      interaction: discord.Interaction,
      member: discord.Member,
      reason: str = "بدون سبب",
      delete_days: app_commands.Range[int, 0, 7] = 0,
  ):
    allowed, why = can_moderate_member(interaction.user, member, interaction.guild)
    if not allowed:
      await interaction.response.send_message(why, ephemeral=True)
      return
    await member.ban(reason=f"By {interaction.user}: {reason}", delete_message_days=delete_days)
    desc = f"**العضو:** {member.mention}\n**السبب:** {reason}"
    embed = discord.Embed(title="🔨 تم حظر العضو", description=desc, color=discord.Color.red().value)
    await interaction.response.send_message(embed=embed)
    await self.bot.send_modlog(interaction.guild, "🔨 حظر عضو", desc, color=discord.Color.red().value)


  @app_commands.command(name="unban", description="فك الحظر عن مستخدم عبر معرفه")
  @app_commands.default_permissions(ban_members=True)
  @app_commands.describe(user_id="معرف المستخدم ID", reason="السبب")
  @has_perm_or_mistress(ban_members=True)
  async def unban_cmd(self, interaction: discord.Interaction, user_id: str, reason: str = "عفو"):
    if not user_id.isdigit():
      await interaction.response.send_message("⚠️ أدخل معرفاً رقمياً صحيحاً.", ephemeral=True)
      return
    try:
      await interaction.guild.unban(discord.Object(id=int(user_id)), reason=reason)
      await interaction.response.send_message(f"🔓 تم فك الحظر عن `{user_id}`.")
    except discord.NotFound:
      await interaction.response.send_message("⚠️ غير موجود في قائمة الحظر.", ephemeral=True)


  @app_commands.command(name="timeout", description="كتم عضو مؤقتاً")
  @app_commands.default_permissions(moderate_members=True)
  @app_commands.describe(member="العضو", minutes="الدقائق", reason="السبب")
  @has_perm_or_mistress(moderate_members=True)
  async def timeout_cmd(
      self,
      interaction: discord.Interaction,
      member: discord.Member,
      minutes: app_commands.Range[int, 1, 40320],
      reason: str = "بدون سبب",
  ):
    allowed, why = can_moderate_member(interaction.user, member, interaction.guild)
    if not allowed:
      await interaction.response.send_message(why, ephemeral=True)
      return
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await interaction.response.send_message(f"⏳ تم كتم {member.mention} لمدة **{minutes} دقيقة**.")
    await self.bot.send_modlog(interaction.guild, "⏳ كتم عضو", f"**العضو:** {member.mention} (`{minutes}m`)\n**السبب:** {reason}")


  @app_commands.command(name="untimeout", description="إلغاء الكتم عن عضو")
  @app_commands.default_permissions(moderate_members=True)
  @app_commands.describe(member="العضو")
  @has_perm_or_mistress(moderate_members=True)
  async def untimeout_cmd(self, interaction: discord.Interaction, member: discord.Member):
    allowed, why = can_moderate_member(interaction.user, member, interaction.guild)
    if not allowed:
      await interaction.response.send_message(why, ephemeral=True)
      return
    await member.timeout(None)
    await interaction.response.send_message(f"🔊 تم رفع الكتم عن {member.mention}.")
    await self.bot.send_modlog(interaction.guild, "🔊 رفع الكتم", f"**العضو:** {member.mention}")


  @app_commands.command(name="purge", description="مسح عدد من الرسائل في القناة")
  @app_commands.default_permissions(manage_messages=True)
  @app_commands.describe(amount="العدد (1-100)", member="تحديد عضو (اختياري)")
  @has_perm_or_mistress(manage_messages=True)
  async def purge_cmd(
      self,
      interaction: discord.Interaction,
      amount: app_commands.Range[int, 1, 100],
      member: Optional[discord.Member] = None,
  ):
    await interaction.response.defer(ephemeral=True)
    check_fn = (lambda m: m.author.id == member.id) if member else (lambda m: True)
    deleted = await interaction.channel.purge(limit=amount, check=check_fn)
    await interaction.followup.send(f"🧹 تم مسح **{len(deleted)}** رسالة.", ephemeral=True)
    await self.bot.send_modlog(interaction.guild, "🧹 مسح رسائل", f"تم مسح `{len(deleted)}` رسالة في {interaction.channel.mention}.")


  @app_commands.command(name="warn", description="توجيه إنذار لعضو")
  @app_commands.default_permissions(moderate_members=True)
  @app_commands.describe(member="العضو", reason="السبب")
  @has_perm_or_mistress(moderate_members=True)
  async def warn_cmd(self, interaction: discord.Interaction, member: discord.Member, reason: str):
    allowed, why = can_moderate_member(interaction.user, member, interaction.guild)
    if not allowed:
      await interaction.response.send_message(why, ephemeral=True)
      return
    total = await self.bot.db.add_warning(interaction.guild.id, member.id, interaction.user.id, reason)
    await interaction.response.send_message(
        f"⚠️ تم توجيه إنذار إلى {member.mention} — السبب: **{reason}** (الإجمالي: `{total}`)."
    )
    await self.bot.send_modlog(interaction.guild, "⚠️ إنذار عضو", f"**العضو:** {member.mention}\n**السبب:** {reason}")


  @app_commands.command(name="warnings", description="عرض إنذارات عضو")
  @app_commands.default_permissions(moderate_members=True)
  @app_commands.describe(member="العضو")
  @has_perm_or_mistress(moderate_members=True)
  async def warnings_cmd(self, interaction: discord.Interaction, member: discord.Member):
    records = await self.bot.db.get_warnings(interaction.guild.id, member.id)
    if not records:
      await interaction.response.send_message(f"✅ سجل {member.mention} خالٍ من الإنذارات.", ephemeral=True)
      return
    embed = discord.Embed(title=f"📋 إنذارات {member.display_name}"[:256], color=0x2B2D31)
    for rec in records[:10]:
      embed.add_field(
          name=f"#{rec['id']} • {rec['created_at']}"[:256],
          value=f"السبب: {str(rec['reason'])[:900]} | المشرف: <@{rec['moderator_id']}>"[:1024],
          inline=False,
      )
    await interaction.response.send_message(embed=embed, ephemeral=True)


  @app_commands.command(name="clear_warnings", description="مسح إنذارات عضو")
  @app_commands.default_permissions(moderate_members=True)
  @app_commands.describe(member="العضو")
  @has_perm_or_mistress(moderate_members=True)
  async def clear_warnings_cmd(self, interaction: discord.Interaction, member: discord.Member):
    allowed, why = can_moderate_member(interaction.user, member, interaction.guild)
    if not allowed:
      await interaction.response.send_message(why, ephemeral=True)
      return
    count = await self.bot.db.clear_warnings(interaction.guild.id, member.id)
    await interaction.response.send_message(f"✅ تم مسح **{count}** إنذار لـ {member.mention}.", ephemeral=True)


  @app_commands.command(name="lock", description="قفل القناة")
  @app_commands.default_permissions(manage_channels=True)
  @app_commands.describe(channel="القناة", reason="السبب")
  @has_perm_or_mistress(manage_channels=True)
  async def lock_cmd(
      self,
      interaction: discord.Interaction,
      channel: Optional[discord.TextChannel] = None,
      reason: str = "بأمر الإدارة",
  ):
    target = channel or interaction.channel
    overwrite = target.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await target.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=reason)
    await interaction.response.send_message(f"🔒 تم قفل {target.mention}.")


  @app_commands.command(name="unlock", description="فتح القناة")
  @app_commands.default_permissions(manage_channels=True)
  @app_commands.describe(channel="القناة")
  @has_perm_or_mistress(manage_channels=True)
  async def unlock_cmd(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    target = channel or interaction.channel
    overwrite = target.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None
    await target.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message(f"🔓 تم فتح {target.mention}.")


  @app_commands.command(name="slowmode", description="ضبط الوضع البطيء للقناة")
  @app_commands.default_permissions(manage_channels=True)
  @app_commands.describe(seconds="الثواني (0 للإلغاء)")
  @has_perm_or_mistress(manage_channels=True)
  async def slowmode_cmd(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
    await interaction.channel.edit(slowmode_delay=seconds)
    await interaction.response.send_message(
        "⚡ تم إلغاء الوضع البطيء." if seconds == 0 else f"🐢 تم ضبط الوضع البطيء على **{seconds} ثانية**."
    )


  @app_commands.command(name="add_role", description="منح رتبة لعضو")
  @app_commands.default_permissions(manage_roles=True)
  @app_commands.describe(member="العضو", role="الرتبة")
  @has_perm_or_mistress(manage_roles=True)
  async def add_role_cmd(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    ok_r, deny_r = can_assign_role(interaction.user, role, interaction.guild)
    if not ok_r:
      await interaction.response.send_message(deny_r, ephemeral=True)
      return
    ok_m, deny_m = can_moderate_member(interaction.user, member, interaction.guild)
    if not ok_m:
      await interaction.response.send_message(deny_m, ephemeral=True)
      return
    await member.add_roles(role, reason=f"By {interaction.user}")
    await interaction.response.send_message(f"✅ تم منح {role.mention} لـ {member.mention}.")
    await self.bot.send_modlog(interaction.guild, "🎭 منح رتبة", f"**العضو:** {member.mention}\n**الرتبة:** {role.mention}\n**بواسطة:** {interaction.user.mention}")


  @app_commands.command(name="remove_role", description="سحب رتبة من عضو")
  @app_commands.default_permissions(manage_roles=True)
  @app_commands.describe(member="العضو", role="الرتبة")
  @has_perm_or_mistress(manage_roles=True)
  async def remove_role_cmd(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    ok_r, deny_r = can_assign_role(interaction.user, role, interaction.guild)
    if not ok_r:
      await interaction.response.send_message(deny_r, ephemeral=True)
      return
    ok_m, deny_m = can_moderate_member(interaction.user, member, interaction.guild)
    if not ok_m:
      await interaction.response.send_message(deny_m, ephemeral=True)
      return
    await member.remove_roles(role, reason=f"By {interaction.user}")
    await interaction.response.send_message(f"✅ تم سحب {role.mention} من {member.mention}.")
    await self.bot.send_modlog(interaction.guild, "🎭 سحب رتبة", f"**العضو:** {member.mention}\n**الرتبة:** {role.mention}\n**بواسطة:** {interaction.user.mention}")


  @app_commands.command(name="announce", description="نشر إعلان منسق في قناة")
  @app_commands.default_permissions(manage_guild=True)
  @app_commands.describe(channel="القناة", title="العنوان", message="النص", ping_everyone="منشن للجميع؟")
  @has_perm_or_mistress(manage_guild=True)
  async def announce_cmd(
      self,
      interaction: discord.Interaction,
      channel: discord.TextChannel,
      title: str,
      message: str,
      ping_everyone: bool = False,
  ):
    embed = discord.Embed(
        title=f"📢 {title}"[:256],
        description=str(message)[:4096],
        color=0x2B2D31,
        timestamp=datetime.now(timezone.utc),
    )
    if ping_everyone:
      # `manage_guild` is not permission to ping the whole server; Discord has its own bit.
      perms = getattr(interaction.user, "guild_permissions", None)
      if not (perms and perms.mention_everyone):
        await interaction.response.send_message(
            "🚫 لا تملك صلاحية منشن الجميع (`Mention Everyone`).", ephemeral=True
        )
        return
    mentions_cfg = discord.AllowedMentions(everyone=True) if ping_everyone else discord.AllowedMentions.none()
    await channel.send(
        content="@everyone" if ping_everyone else None,
        embed=embed,
        allowed_mentions=mentions_cfg,
    )
    await interaction.response.send_message(f"✅ تم نشر الإعلان في {channel.mention}.", ephemeral=True)


  @app_commands.command(name="set_modlog", description="تحديد قناة سجل الإشراف")
  @app_commands.default_permissions(administrator=True)
  @app_commands.describe(channel="القناة")
  @has_perm_or_mistress(administrator=True)
  async def set_modlog_cmd(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    await self.bot.db.set_modlog_channel(interaction.guild.id, channel.id if channel else None)
    self.bot.modlog_cache[interaction.guild.id] = channel.id if channel else None
    await interaction.response.send_message(
        f"✅ تم تفعيل السجل في {channel.mention}." if channel else "✅ تم إيقاف السجل.",
        ephemeral=True,
    )


  @app_commands.command(name="sync", description="مزامنة وتحديث الأوامر")
  @app_commands.default_permissions(administrator=True)
  async def sync_cmd(self, interaction: discord.Interaction):
    if not is_mistress(interaction.user):
      await interaction.response.send_message("🚫 غير مصرح لك.", ephemeral=True)
      return
    await interaction.response.defer(ephemeral=True)
    await self.bot.sync_all_commands_cleanly()
    await interaction.followup.send("✅ تمت مزامنة الأوامر بنجاح.", ephemeral=True)


def install(bot) -> None:
  """Attach this cog's commands to the tree without an event loop (see module docstring).

  Guild-only is applied centrally: 17 administrative commands previously ran in DMs and
  raised raw tracebacks instead of refusing cleanly (C-011). `/sync` stays DM-capable
  because it is owner-only and touches no guild state.
  """
  dm_capable = {"sync"}
  for command in Admin(bot).get_app_commands():
    command.guild_only = command.name not in dm_capable
    bot.tree.add_command(command)
