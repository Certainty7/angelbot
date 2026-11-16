"""Reaction GIFs and character lore.

The harem-only romance gate runs before any fetch, so a refused request never reaches a source.
"""
import io
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from angel import guard
from angel.config import ARABIC_GIF_KEYWORDS, is_mistress, is_romantic_gif
from angel.persona import ANGEL_BACKSTORY_AR


class FunGif(commands.Cog):
  """`/gif` reaction pool and `/lore` persona blurb."""

  def __init__(self, bot) -> None:
    self.bot = bot

  @app_commands.command(name="gif", description="إرسال صورة أنمي متحركة (بوسة، حضن، غرور، ضحك، إلخ)")
  @app_commands.allowed_installs(guilds=True, users=True)
  @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
  @app_commands.describe(action="نوع الحركة", target="الشخص الموجه له (اختياري)")
  @app_commands.choices(
      action=[
          app_commands.Choice(name="💋 Kiss (قبلة)", value="kiss"),
          app_commands.Choice(name="☺️ Cheek Kiss (بوسة خد)", value="cheek_kiss"),
          app_commands.Choice(name="🫂 Hug (حضن / عناق)", value="hug"),
          app_commands.Choice(name="💞 Cuddle (دلال / حنان)", value="cuddle"),
          app_commands.Choice(name="🤝 Handhold (مسكة يد)", value="handhold"),
          app_commands.Choice(name="🤚 Pat (طبطبة)", value="pat"),
          app_commands.Choice(name="😏 Smug (غرور)", value="smug"),
          app_commands.Choice(name="😊 Smile (ابتسامة)", value="smile"),
          app_commands.Choice(name="😂 Laugh (ضحك)", value="laugh"),
          app_commands.Choice(name="😢 Cry (بكاء)", value="cry"),
          app_commands.Choice(name="😳 Blush (خجل)", value="blush"),
          app_commands.Choice(name="👋 Wave (تحية)", value="wave"),
          app_commands.Choice(name="😉 Wink (غمزة)", value="wink"),
          app_commands.Choice(name="👋 Slap (صفعة)", value="slap"),
          app_commands.Choice(name="💃 Dance (رقص)", value="dance"),
          app_commands.Choice(name="😤 Pout (عبوس)", value="pout"),
          app_commands.Choice(name="🤔 Think (تفكير)", value="think"),
          app_commands.Choice(name="🙌 Highfive (هاي فايف)", value="highfive"),
      ]
  )
  async def gif_cmd(
      self,
      interaction: discord.Interaction,
      action: str,
      target: Optional[discord.User] = None,
  ):
    await interaction.response.defer()
    mistress = is_mistress(interaction.user)
    harem_title = self.bot.get_harem_title(interaction.user.id)
    is_female_tier = mistress or (harem_title is not None)
    resolved_action = ARABIC_GIF_KEYWORDS.get((action or "").lower().strip(), (action or "").lower().strip())

    # HAREM-ONLY romance: refuse physical-affection reactions for everyone else, in character and without a GIF.
    if is_romantic_gif(resolved_action) and not is_female_tier:
      await interaction.followup.send(f"🪽 {interaction.user.mention} {guard.refusal_line()}", ephemeral=True)
      return

    # Internal private routing: Mistress & Harem automatically receive girl-x-girl GIFs without any public label exposure
    gif_bytes, gif_url = await self.bot.ai.fetch_anime_gif_data(
        resolved_action, for_female_pair=is_female_tier, allow_romantic=is_female_tier)
    if not gif_bytes and not gif_url:
      await interaction.followup.send("⚠️ تعذر إحضار الصورة المتحركة حالياً.", ephemeral=True)
      return

    if target and interaction.channel_id:
      self.bot.last_social_target[interaction.channel_id] = target.id

    target_mention = f" إلى {target.mention}" if target else ""
    header = f"🪽 {interaction.user.mention}{target_mention}"

    embed = discord.Embed(
        description=header,
        color=0xD4AF37 if is_female_tier else 0x2B2D31,
    )
    if gif_bytes:
      file = discord.File(io.BytesIO(gif_bytes), filename="angel_reaction.gif")
      embed.set_image(url="attachment://angel_reaction.gif")
      await interaction.followup.send(embed=embed, file=file)
    else:
      embed.set_image(url=gif_url)
      await interaction.followup.send(embed=embed)


  @app_commands.command(name="lore", description="نبذة عن شخصية أنجل")
  async def lore_cmd(self, interaction: discord.Interaction):
    embed = discord.Embed(
        title="🪽 Angel",
        description=ANGEL_BACKSTORY_AR,
        color=0x2B2D31,
    )
    await interaction.response.send_message(embed=embed)



def install(bot) -> None:
  """Attach this cog's commands to the tree without an event loop (see module docstring)."""
  for command in FunGif(bot).get_app_commands():
    bot.tree.add_command(command)
