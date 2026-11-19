"""Chat, vision and translation.

`/chat` routes through `handle_conversation` with its working memory, chunking and attachment
handling; `/translate` uses the custom-prompt path.
"""
import io
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from angel.brain import AI_ERRORS
from angel.config import is_mistress, logger
from angel.images import download_media_as_base64
from angel.summarize import analyze_channel_history_deep
from angel.text import split_message
from angel.ui import ArtStudioView


class AiChat(commands.Cog):
  """`/chat`, `/translate`, `/imagine` and `/summarize_channel`."""

  def __init__(self, bot) -> None:
    self.bot = bot

  @app_commands.command(name="chat", description="التحدث مع أنجل (مع إمكانية إرفاق صورة أو GIF)")
  @app_commands.allowed_installs(guilds=True, users=True)
  @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
  @app_commands.describe(message="رسالتك", image="صورة أو GIF (اختياري)")
  async def chat_cmd(
      self,
      interaction: discord.Interaction,
      message: str,
      image: Optional[discord.Attachment] = None,
  ):
    await interaction.response.defer(thinking=True)
    try:
      media_items: List[Tuple[str, str]] = []
      if image:
        downloaded = await download_media_as_base64(image.url)
        if downloaded:
          media_items.append(downloaded)

      reply, gif_bytes, gif_url, img_bytes, _ = await self.bot.handle_conversation(
          interaction.user, message, media_items=media_items, cmd="chat"
      )

      chunks = split_message(reply)
      files_to_send = []
      if img_bytes:
        files_to_send.append(discord.File(io.BytesIO(img_bytes), filename="angel_art.png"))
      if gif_bytes:
        files_to_send.append(discord.File(io.BytesIO(gif_bytes), filename="angel_reaction.gif"))

      first_msg = chunks[0]
      gif_embed = None
      if gif_url and not gif_bytes:
        gif_embed = discord.Embed(color=0xD4AF37 if (is_mistress(interaction.user) or self.bot.get_harem_title(interaction.user.id)) else 0x2B2D31)
        gif_embed.set_image(url=gif_url)

      if gif_embed:
        await interaction.followup.send(content=first_msg, embed=gif_embed, files=files_to_send)
      else:
        await interaction.followup.send(content=first_msg, files=files_to_send)
      for chunk in chunks[1:]:
        await interaction.followup.send(content=chunk)
    except AI_ERRORS as err:
      await interaction.followup.send(f"⚠️ {err}", ephemeral=True)
    except Exception as exc:
      logger.exception(f"Error in /chat: {exc}")
      await interaction.followup.send("⚠️ حدث خطأ غير متوقع.", ephemeral=True)


  @app_commands.command(name="translate", description="ترجمة أي نص إلى أي لغة")
  @app_commands.allowed_installs(guilds=True, users=True)
  @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
  @app_commands.describe(text="النص المراد ترجمته", target_language="اللغة المطلوبة")
  async def translate_cmd(
      self,
      interaction: discord.Interaction, text: str, target_language: str
  ):
    await interaction.response.defer(thinking=True)
    try:
      prompt = f"ترجمي النص التالي بدقة إلى ({target_language}) بدون أي مقدمات أو أوسمة:\n\n{text}"
      translation = await self.bot.ai.custom_prompt(
          interaction.user, prompt, harem_title=self.bot.get_harem_title(interaction.user.id)
      )
      embed = discord.Embed(
          title=f"🌐 الترجمة ({target_language})",
          description=translation[:4000],
          color=0x2B2D31,
      )
      await interaction.followup.send(embed=embed)
    except AI_ERRORS as err:
      await interaction.followup.send(f"⚠️ {err}", ephemeral=True)


  @app_commands.command(name="imagine", description="تصميم أو رسم صورة فنية عبر استوديو أنجل")
  @app_commands.allowed_installs(guilds=True, users=True)
  @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
  @app_commands.describe(prompt="وصف الصورة المطلوبة", style="الأسلوب الفني")
  @app_commands.choices(
      style=[
          app_commands.Choice(name="✨ أنمي فائق (Anime Masterpiece)", value="anime"),
          app_commands.Choice(name="🌙 سينمائي واقعي (Cinematic)", value="cinematic"),
          app_commands.Choice(name="🔮 فانتازيا (Fantasy)", value="fantasy"),
      ]
  )
  async def imagine_cmd(self, interaction: discord.Interaction, prompt: str, style: str = "anime"):
    harem_title = self.bot.get_harem_title(interaction.user.id)
    allowed, deny_reason = self.bot.quota.check_user_allowed(
        interaction.user, is_harem=(harem_title is not None)
    )
    if not allowed:
      await interaction.response.send_message(deny_reason, ephemeral=True)
      return

    await interaction.response.defer(thinking=True)
    try:
      img_bytes, _ = await self.bot.ai.generate_image_bytes(
          prompt, style_Preset=style, user=interaction.user)
      mistress = is_mistress(interaction.user)
      caption = f"🪽 **{prompt}**"

      file = discord.File(io.BytesIO(img_bytes), filename="angel_creation.png")
      embed = discord.Embed(
          description=caption,
          color=0xD4AF37 if (mistress or harem_title) else 0x2B2D31,
          timestamp=datetime.now(timezone.utc),
      )
      embed.set_image(url="attachment://angel_creation.png")
      await interaction.followup.send(embed=embed, file=file, view=ArtStudioView(prompt, self.bot))
    except AI_ERRORS as err:
      await interaction.followup.send(f"⚠️ {err}", ephemeral=True)


  @app_commands.command(name="summarize_channel", description="قراءة وتلخيص محادثات القناة بدقة (حتى 500 رسالة)")
  @app_commands.describe(
      limit="عدد الرسائل (10 إلى 500)",
      question="سؤال محدد عن المحادثة (اختياري)",
  )
  async def summarize_channel_cmd(
      self,
      interaction: discord.Interaction,
      limit: app_commands.Range[int, 10, 500] = 100,
      question: Optional[str] = None,
  ):
    if interaction.guild and isinstance(interaction.user, discord.Member) and not is_mistress(interaction.user):
      perms = interaction.channel.permissions_for(interaction.user)
      if not (perms.read_messages and perms.read_message_history):
        await interaction.response.send_message("🚫 لا تملك صلاحية قراءة سجل هذه القناة (`Read Message History`).", ephemeral=True)
        return
      # A 500-message summary is a real model call; keep a member from making it a loop.
      limit = min(limit, 200)
      now_m = time.monotonic()
      if now_m - self.bot.summarize_cooldowns.get(interaction.user.id, 0.0) < 120.0:
        wait_s = int(120.0 - (now_m - self.bot.summarize_cooldowns.get(interaction.user.id, 0.0))) + 1
        await interaction.response.send_message(f"⏳ انتظر **{wait_s} ثانية** قبل تلخيص آخر.", ephemeral=True)
        return
      self.bot.summarize_cooldowns[interaction.user.id] = now_m
    await interaction.response.defer(thinking=True)
    try:
      report = await analyze_channel_history_deep(
          self.bot,
          interaction.channel, interaction.user, limit=limit, focus_query=question or ""
      )
      embed = discord.Embed(
          title=f"📝 ملخص المحادثة (آخر {limit} رسالة)",
          description=report[:4000],
          color=0x2B2D31,
      )
      await interaction.followup.send(embed=embed)
    except AI_ERRORS as err:
      await interaction.followup.send(f"⚠️ {err}", ephemeral=True)


def install(bot) -> None:
  """Attach this cog's commands to the tree without an event loop (see module docstring)."""
  for command in AiChat(bot).get_app_commands():
    bot.tree.add_command(command)
