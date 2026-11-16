"""Productivity commands: /todo, /sticky and /autorole.

The todo board has five actions, sticky keeps a per-channel cache and cooldown, and autorole keeps
the assignability check and the members-intent notice.
"""
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from angel.config import can_assign_role, has_perm_or_mistress


class Productivity(commands.Cog):
  """`/todo`, `/sticky`, `/autorole`."""

  def __init__(self, bot) -> None:
    self.bot = bot

  @app_commands.command(name="sticky", description="تثبيت رسالة ذكية تبقى دائماً في أسفل القناة")
  @app_commands.default_permissions(manage_messages=True)
  @app_commands.describe(mode="تفعيل أو إلغاء", message="نص الرسالة المثبتة في أسفل الشات")
  @app_commands.choices(
      mode=[
          app_commands.Choice(name="تفعيل / تحديث (Set)", value="set"),
          app_commands.Choice(name="إيقاف وحذف (Remove)", value="remove"),
      ]
  )
  @has_perm_or_mistress(manage_messages=True)
  async def sticky_cmd(
      self,
      interaction: discord.Interaction,
      mode: str,
      message: Optional[str] = None,
  ):
    cid = interaction.channel.id
    if mode == "remove":
      await self.bot.db.remove_sticky(cid)
      self.bot.stickies_cache.pop(cid, None)
      await interaction.response.send_message("✅ تم إلغاء الرسالة المثبتة في أسفل القناة.", ephemeral=True)
      return
    if not message:
      await interaction.response.send_message("⚠️ اكتبي نص الرسالة في خانة `message`.", ephemeral=True)
      return
    embed = discord.Embed(description=f"📌 **{message}**", color=0x2B2D31)
    sent = await interaction.channel.send(embed=embed)
    await self.bot.db.set_sticky(cid, interaction.guild.id, message, sent.id)
    self.bot.stickies_cache[cid] = {"channel_id": cid, "guild_id": interaction.guild.id, "content": message, "last_message_id": sent.id}
    await interaction.response.send_message("✅ تم تفعيل الرسالة المثبتة بأسفل القناة.", ephemeral=True)


  @app_commands.command(name="autorole", description="تحديد رتبة تُمنح تلقائياً لكل عضو جديد ينضم للسيرفر")
  @app_commands.default_permissions(manage_roles=True)
  @app_commands.describe(role="الرتبة التلقائية (اتركيها فارغة لإلغاء التفعيل)")
  @has_perm_or_mistress(manage_roles=True)
  async def autorole_cmd(self, interaction: discord.Interaction, role: Optional[discord.Role] = None):
    if role:
      ok_r, deny_r = can_assign_role(interaction.user, role, interaction.guild)
      if not ok_r:
        await interaction.response.send_message(deny_r, ephemeral=True)
        return
    await self.bot.db.set_autorole(interaction.guild.id, role.id if role else None)
    self.bot.autorole_cache[interaction.guild.id] = role.id if role else None
    if role:
      intent_notice = (
          "\n💡 *ملاحظة: لتعمل الرتبة التلقائية فور دخول الأعضاء، تأكدي من تفعيل `Server Members Intent` في بوابة مطوري Discord وإضافة `ENABLE_MEMBERS_INTENT=1` في `.env`.*"
          if not self.bot.intents.members
          else ""
      )
      await interaction.response.send_message(
          f"✅ سيتم منح رتبة {role.mention} تلقائياً للأعضاء الجدد.{intent_notice}", ephemeral=True
      )
    else:
      await interaction.response.send_message("✅ تم إيقاف الرتبة التلقائية.", ephemeral=True)



def install(bot) -> None:
  """Attach this cog's commands to the tree without an event loop (see module docstring)."""
  for command in Productivity(bot).get_app_commands():
    bot.tree.add_command(command)
