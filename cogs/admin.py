"""Moderation and administration: kick, ban, timeout, warnings, channels, roles, announcements,
modlog and command sync.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from angel.config import can_assign_role, can_moderate_member, has_perm_or_mistress, is_mistress
from angel.confirmations import queue_slash_confirmation
from angel.interactions import run_moderation_action


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
    desc = f"**العضو:** {member.mention}\n**السبب:** {reason}"
    embed = discord.Embed(title="👢 تم طرد العضو", description=desc, color=0x2B2D31)
    await run_moderation_action(
        interaction,
        lambda: member.kick(reason=f"By {interaction.user}: {reason}"),
        embed=embed,
        modlog=lambda: self.bot.send_modlog(interaction.guild, "👢 طرد عضو", desc),
    )


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
    desc = f"**العضو:** {member.mention}\n**السبب:** {reason}"

    async def _run(confirm_message):
      actor = confirm_message.author
      if not (is_mistress(actor) or getattr(actor.guild_permissions, "ban_members", False)):
        return "🚫 ما نفذت الحظر: صلاحيتك تغيّرت."
      target = interaction.guild.get_member(member.id)
      if target is None:
        try:
          target = await interaction.guild.fetch_member(member.id)
        except discord.HTTPException:
          return "⚠️ العضو لم يعد موجوداً."
      ok, deny = can_moderate_member(actor, target, interaction.guild)
      if not ok:
        return deny
      try:
        await target.ban(reason=f"By {actor}: {reason}", delete_message_days=delete_days)
      except discord.HTTPException:
        return "⚠️ فشل الحظر، لم يُنفَّذ شيء."
      await self.bot.send_modlog(interaction.guild, "🔨 حظر عضو", desc, color=discord.Color.red().value)
      return f"🔨 تم حظر {member.mention}."

    await queue_slash_confirmation(interaction, summary=f"حظر {member.mention} — {reason}", run=_run)


  @app_commands.command(name="unban", description="فك الحظر عن مستخدم عبر معرفه")
  @app_commands.default_permissions(ban_members=True)
  @app_commands.describe(user_id="معرف المستخدم ID", reason="السبب")
  @has_perm_or_mistress(ban_members=True)
  async def unban_cmd(self, interaction: discord.Interaction, user_id: str, reason: str = "عفو"):
    if not user_id.isdigit():
      await interaction.response.send_message("⚠️ أدخل معرفاً رقمياً صحيحاً.", ephemeral=True)
      return
    await run_moderation_action(
        interaction,
        lambda: interaction.guild.unban(discord.Object(id=int(user_id)), reason=reason),
        content=f"🔓 تم فك الحظر عن `{user_id}`.",
        not_found="⚠️ غير موجود في قائمة الحظر.",
    )


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
    await run_moderation_action(
        interaction,
        lambda: member.timeout(timedelta(minutes=minutes), reason=reason),
        content=f"⏳ تم كتم {member.mention} لمدة **{minutes} دقيقة**.",
        modlog=lambda: self.bot.send_modlog(interaction.guild, "⏳ كتم عضو", f"**العضو:** {member.mention} (`{minutes}m`)\n**السبب:** {reason}"),
    )


  @app_commands.command(name="untimeout", description="إلغاء الكتم عن عضو")
  @app_commands.default_permissions(moderate_members=True)
  @app_commands.describe(member="العضو")
  @has_perm_or_mistress(moderate_members=True)
  async def untimeout_cmd(self, interaction: discord.Interaction, member: discord.Member):
    allowed, why = can_moderate_member(interaction.user, member, interaction.guild)
    if not allowed:
      await interaction.response.send_message(why, ephemeral=True)
      return
    await run_moderation_action(
        interaction,
        lambda: member.timeout(None),
        content=f"🔊 تم رفع الكتم عن {member.mention}.",
        modlog=lambda: self.bot.send_modlog(interaction.guild, "🔊 رفع الكتم", f"**العضو:** {member.mention}"),
    )


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
    check_fn = (lambda m: m.author.id == member.id) if member else (lambda m: True)

    async def _run(confirm_message):
      actor = confirm_message.author
      if not (is_mistress(actor) or getattr(actor.guild_permissions, "manage_messages", False)):
        return "🚫 ما نفذت المسح: صلاحيتك تغيّرت."
      deleted = await confirm_message.channel.purge(limit=amount, check=check_fn)
      await self.bot.send_modlog(confirm_message.guild, "🧹 مسح رسائل", f"تم مسح `{len(deleted)}` رسالة في {confirm_message.channel.mention}.")
      return f"🧹 تم مسح **{len(deleted)}** رسالة."

    target = f" ({member.mention})" if member else ""
    await queue_slash_confirmation(interaction, summary=f"مسح {amount} رسالة{target}", run=_run)


  @app_commands.command(name="warn", description="توجيه إنذار لعضو")
  @app_commands.default_permissions(moderate_members=True)
  @app_commands.describe(member="العضو", reason="السبب")
  @has_perm_or_mistress(moderate_members=True)
  async def warn_cmd(self, interaction: discord.Interaction, member: discord.Member, reason: str):
    allowed, why = can_moderate_member(interaction.user, member, interaction.guild)
    if not allowed:
      await interaction.response.send_message(why, ephemeral=True)
      return
    await run_moderation_action(
        interaction,
        lambda: self.bot.db.add_warning(interaction.guild.id, member.id, interaction.user.id, reason),
        content=lambda total: f"⚠️ تم توجيه إنذار إلى {member.mention} — السبب: **{reason}** (الإجمالي: `{total}`).",
        modlog=lambda: self.bot.send_modlog(interaction.guild, "⚠️ إنذار عضو", f"**العضو:** {member.mention}\n**السبب:** {reason}"),
    )


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
    # Discord rejects an embed whose *aggregate* size passes 6000 characters even when
    # every field is within its own limit: keep a running budget and stop adding fields
    # when it is exhausted instead of losing the whole record list.
    budget = 6000 - len(embed.title or "")
    shown = 0
    for rec in records[:10]:
      field_name = f"#{rec['id']} • {rec['created_at']}"[:256]
      field_value = f"السبب: {str(rec['reason'])[:400]} | المشرف: <@{rec['moderator_id']}>"[:1024]
      cost = len(field_name) + len(field_value)
      if shown and budget - cost < 400:
        embed.set_footer(text=f"⚠️ اكتفيت بأول {shown} إنذار لحد حجم الرسالة.")
        break
      embed.add_field(name=field_name, value=field_value, inline=False)
      budget -= cost
      shown += 1
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
    async def _run(confirm_message):
      actor = confirm_message.author
      if not (is_mistress(actor) or getattr(actor.guild_permissions, "moderate_members", False)):
        return "🚫 ما نفذت المسح: صلاحيتك تغيّرت."
      count = await self.bot.db.clear_warnings(interaction.guild.id, member.id)
      await self.bot.send_modlog(interaction.guild, "🧽 مسح إنذارات", f"**العضو:** {member.mention}")
      return f"✅ تم مسح **{count}** إنذار لـ {member.mention}."

    await queue_slash_confirmation(interaction, summary=f"مسح إنذارات {member.mention}", run=_run)


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
    await run_moderation_action(
        interaction,
        lambda: target.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=reason),
        content=f"🔒 تم قفل {target.mention}.",
    )


  @app_commands.command(name="unlock", description="فتح القناة")
  @app_commands.default_permissions(manage_channels=True)
  @app_commands.describe(channel="القناة")
  @has_perm_or_mistress(manage_channels=True)
  async def unlock_cmd(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    target = channel or interaction.channel
    overwrite = target.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None
    await run_moderation_action(
        interaction,
        lambda: target.set_permissions(interaction.guild.default_role, overwrite=overwrite),
        content=f"🔓 تم فتح {target.mention}.",
    )


  @app_commands.command(name="slowmode", description="ضبط الوضع البطيء للقناة")
  @app_commands.default_permissions(manage_channels=True)
  @app_commands.describe(seconds="الثواني (0 للإلغاء)")
  @has_perm_or_mistress(manage_channels=True)
  async def slowmode_cmd(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
    await run_moderation_action(
        interaction,
        lambda: interaction.channel.edit(slowmode_delay=seconds),
        content="⚡ تم إلغاء الوضع البطيء." if seconds == 0 else f"🐢 تم ضبط الوضع البطيء على **{seconds} ثانية**.",
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
    await run_moderation_action(
        interaction,
        lambda: member.add_roles(role, reason=f"By {interaction.user}"),
        content=f"✅ تم منح {role.mention} لـ {member.mention}.",
        modlog=lambda: self.bot.send_modlog(interaction.guild, "🎭 منح رتبة", f"**العضو:** {member.mention}\n**الرتبة:** {role.mention}\n**بواسطة:** {interaction.user.mention}"),
    )


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
    await run_moderation_action(
        interaction,
        lambda: member.remove_roles(role, reason=f"By {interaction.user}"),
        content=f"✅ تم سحب {role.mention} من {member.mention}.",
        modlog=lambda: self.bot.send_modlog(interaction.guild, "🎭 سحب رتبة", f"**العضو:** {member.mention}\n**الرتبة:** {role.mention}\n**بواسطة:** {interaction.user.mention}"),
    )


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
      # `manage_guild` is not permission to ping the whole server; Discord has its own
      # bit. Guild-level permissions ignore channel overwrites, so the check must use
      # the effective permissions in the *selected* channel (a channel allow counts too).
      perms = channel.permissions_for(interaction.user)
      if not perms.mention_everyone:
        await interaction.response.send_message(
            "🚫 لا تملك صلاحية منشن الجميع (`Mention Everyone`) في هذه القناة.", ephemeral=True
        )
        return
    # The announcement is sent by the bot, not the caller: it must actually be able to
    # read and write the target channel, or the send fails with a raw HTTP error.
    me = interaction.guild.me or interaction.client.user
    bot_perms = channel.permissions_for(me)
    if not (bot_perms.view_channel and bot_perms.send_messages):
        await interaction.response.send_message(
            "🚫 لا أستطيع إرسال الإعلان في تلك القناة (أحتاج صلاحية العرض والإرسال فيها).",
            ephemeral=True,
        )
        return
    if ping_everyone and not bot_perms.mention_everyone:
        await interaction.response.send_message(
            "🚫 أحتاج صلاحية `Mention Everyone` في تلك القناة حتى ينفع منشن الجميع.", ephemeral=True
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
    if command.guild_only:
      # `guild_only` alone leaves the payload's `contexts` field on the tree default,
      # which still permits DM invocation; `contexts` replaced `dm_permission`.
      command.allowed_contexts = app_commands.AppCommandContext(guild=True)
    bot.tree.add_command(command)
