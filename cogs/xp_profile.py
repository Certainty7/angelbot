"""XP, rank and reputation commands."""
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from angel.interactions import _safe_interaction_reply


class XpProfile(commands.Cog):
  """`/rank` card and `/leaderboard` top-10."""

  def __init__(self, bot) -> None:
    self.bot = bot

  @app_commands.command(name="rank", description="عرض مستواك وترتيبك ونقاط السمعة في السيرفر")
  @app_commands.guild_only()
  @app_commands.describe(member="اختر العضو (اختياري)")
  async def rank_cmd(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    xp, lvl, msgs, rank_pos, rep = await self.bot.db.get_user_rank(interaction.guild.id, target.id)
    next_lvl_xp = int(((lvl + 1) / 0.1) ** 2)
    embed = discord.Embed(title=f"🏆 بطاقة {target.display_name}"[:256], color=0x2B2D31)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="الترتيب", value=f"`#{rank_pos}`" if rank_pos else "`—`", inline=True)
    embed.add_field(name="المستوى", value=f"`Lv.{lvl}`", inline=True)
    embed.add_field(name="الخبرة (XP)", value=f"`{xp} / {next_lvl_xp}`", inline=True)
    embed.add_field(name="🌟 السمعة (Rep)", value=f"`+{rep}`", inline=True)
    embed.add_field(name="💬 الرسائل", value=f"`{msgs}`", inline=True)
    await _safe_interaction_reply(interaction, embed=embed, ephemeral=False)


  @app_commands.command(name="leaderboard", description="عرض قائمة أعلى الأعضاء تفاعلاً في السيرفر")
  @app_commands.guild_only()
  async def leaderboard_cmd(self, interaction: discord.Interaction):
    top_users = await self.bot.db.get_leaderboard(interaction.guild.id, 10)
    if not top_users:
      await _safe_interaction_reply(interaction, "📊 لا توجد بيانات تفاعل بعد.", ephemeral=False)
      return
    medals = ["🥇", "🥈", "🥉"]
    lines = [
        f"{medals[i-1] if i <= 3 else f'`#{i}`'} <@{u['user_id']}> — **Lv.{u['level']}** (`{u['xp']} XP` | 🌟 `+{u['rep_points']}`)"
        for i, u in enumerate(top_users, start=1)
    ]
    embed = discord.Embed(
        title=f"🏅 المتصدرون في {interaction.guild.name}"[:256],
        description="\n".join(lines)[:4096],
        color=0x2B2D31,
    )
    await _safe_interaction_reply(interaction, embed=embed, ephemeral=False)



def install(bot) -> None:
  """Attach this cog's commands to the tree without an event loop (see module docstring)."""
  for command in XpProfile(bot).get_app_commands():
    bot.tree.add_command(command)
