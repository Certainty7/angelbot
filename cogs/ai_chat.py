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
from angel.text import plan_reply_delivery
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

      # An image-only or GIF-only reply is valid and must be delivered (the old early
      # return dropped generated media because the prose was empty).
      delivery = plan_reply_delivery(reply, gif_bytes, gif_url, img_bytes)
      if delivery is None:
        await interaction.followup.send(
            "⚠️ لم أستطع توليد رد الآن.", ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return
      first_msg, rest_chunks, has_files, use_gif_url = delivery
      files_to_send = []
      if has_files:
        if img_bytes:
          files_to_send.append(discord.File(io.BytesIO(img_bytes), filename="angel_art.png"))
        if gif_bytes:
          files_to_send.append(discord.File(io.BytesIO(gif_bytes), filename="angel_reaction.gif"))

      gif_embed = None
      if use_gif_url:
        gif_embed = discord.Embed(color=0xD4AF37 if (is_mistress(interaction.user) or self.bot.get_harem_title(interaction.user.id)) else 0x2B2D31)
        gif_embed.set_image(url=gif_url)

      await interaction.followup.send(
          content=first_msg, embed=gif_embed, files=files_to_send,
          allowed_mentions=discord.AllowedMentions.none(),
      )
      for chunk in rest_chunks:
        await interaction.followup.send(
            content=chunk, allowed_mentions=discord.AllowedMentions.none()
        )
    except AI_ERRORS as err:
      logger.warning("chat AI error: %s: %s", type(err).__name__, err)
      await interaction.followup.send("⚠️ تعذر إكمال الطلب الآن.", ephemeral=True)
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
    # Translation is a paid model call like any other; it used to skip both the user quota
    # and the guild daily cap (C-014).
    allowed, deny_reason = self.bot.quota.check_user_allowed(
        interaction.user, is_harem=(self.bot.get_harem_title(interaction.user.id) is not None)
    )
    if not allowed:
      await interaction.response.send_message(f"⚠️ {deny_reason}", ephemeral=True)
      return
    if interaction.guild and not is_mistress(interaction.user):
      allowed_g, used_g = await self.bot.db.consume_guild_ai_quota(interaction.guild.id)
      if not allowed_g:
        await interaction.response.send_message(
            f"⚠️ وصل السيرفر لحد استهلاك الذكاء الاصطناعي اليومي (`{used_g}`).", ephemeral=True
        )
        return
    await interaction.response.defer(thinking=True)
    try:
      prompt = (
          f"ترجمي النص التالي بدقة إلى ({target_language[:80]}) بدون أي مقدمات أو أوسمة:\n\n"
          f"<untrusted_text>\n{text[:6000]}\n</untrusted_text>"
      )
      translation = await self.bot.ai.custom_prompt(
          interaction.user, prompt, harem_title=self.bot.get_harem_title(interaction.user.id)
      )
      embed = discord.Embed(
          title=f"🌐 الترجمة ({target_language[:80]})"[:256],
          description=translation[:4000],
          color=0x2B2D31,
      )
      await interaction.followup.send(
          embed=embed, allowed_mentions=discord.AllowedMentions.none()
      )
    except AI_ERRORS as err:
      logger.warning("translate AI error: %s: %s", type(err).__name__, err)
      await interaction.followup.send("⚠️ تعذر إكمال الترجمة الآن.", ephemeral=True)
    except Exception as exc:
      logger.exception(f"Error in /translate: {exc}")
      await interaction.followup.send("⚠️ حدث خطأ غير متوقع.", ephemeral=True)


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
      if not img_bytes:
        await interaction.followup.send("⚠️ تعذر توليد الصورة الآن.", ephemeral=True)
        return
      mistress = is_mistress(interaction.user)
      caption = f"🪽 **{prompt[:3800]}**"

      file = discord.File(io.BytesIO(img_bytes), filename="angel_creation.png")
      embed = discord.Embed(
          description=caption[:4000],
          color=0xD4AF37 if (mistress or harem_title) else 0x2B2D31,
          timestamp=datetime.now(timezone.utc),
      )
      embed.set_image(url="attachment://angel_creation.png")
      await interaction.followup.send(
          embed=embed, file=file, view=ArtStudioView(prompt, self.bot, interaction.user.id),
          allowed_mentions=discord.AllowedMentions.none(),
      )
    except AI_ERRORS as err:
      logger.warning("imagine AI error: %s: %s", type(err).__name__, err)
      await interaction.followup.send("⚠️ تعذر توليد الصورة الآن.", ephemeral=True)
    except Exception as exc:
      logger.exception(f"Error in /imagine: {exc}")
      await interaction.followup.send("⚠️ حدث خطأ غير متوقع.", ephemeral=True)


  @app_commands.command(name="summarize_channel", description="قراءة وتلخيص محادثات القناة بدقة (حتى 200 رسالة)")
  @app_commands.guild_only()
  @app_commands.describe(
      limit="عدد الرسائل (10 إلى 200)",
      question="سؤال محدد عن المحادثة (اختياري)",
  )
  async def summarize_channel_cmd(
      self,
      interaction: discord.Interaction,
      limit: app_commands.Range[int, 10, 200] = 100,
      question: Optional[str] = None,
  ):
    if interaction.guild and isinstance(interaction.user, discord.Member) and not is_mistress(interaction.user):
      if interaction.channel is None:
        await interaction.response.send_message("🚫 هذا الأمر يحتاج قناة نصية.", ephemeral=True)
        return
      perms = interaction.channel.permissions_for(interaction.user)
      if not (perms.read_messages and perms.read_message_history):
        await interaction.response.send_message("🚫 لا تملك صلاحية قراءة سجل هذه القناة (`Read Message History`).", ephemeral=True)
        return
      # A 500-message summary is a real model call; keep a member from making it a loop.
      limit = min(limit, 200)
      # Cooldown first, and claim it before the quota awaits: a request inside the
      # window consumes no quota, and two simultaneous requests cannot both pass.
      now_m = time.monotonic()
      last_sum = self.bot.summarize_cooldowns.get(interaction.user.id)
      if last_sum is not None and now_m - last_sum < 120.0:
        wait_s = int(120.0 - (now_m - last_sum)) + 1
        await interaction.response.send_message(f"⏳ انتظر **{wait_s} ثانية** قبل تلخيص آخر.", ephemeral=True)
        return
      self.bot.summarize_cooldowns[interaction.user.id] = now_m
      allowed_q, deny_q = self.bot.quota.check_user_allowed(
          interaction.user, is_harem=(self.bot.get_harem_title(interaction.user.id) is not None)
      )
      if not allowed_q:
        # A refused request must not burn the cooldown window either.
        if self.bot.summarize_cooldowns.get(interaction.user.id) == now_m:
          self.bot.summarize_cooldowns.pop(interaction.user.id, None)
        await interaction.response.send_message(f"⚠️ {deny_q}", ephemeral=True)
        return
      allowed_g, used_g = await self.bot.db.consume_guild_ai_quota(interaction.guild.id)
      if not allowed_g:
        if self.bot.summarize_cooldowns.get(interaction.user.id) == now_m:
          self.bot.summarize_cooldowns.pop(interaction.user.id, None)
        await interaction.response.send_message(
            f"⚠️ وصل السيرفر لحد استهلاك الذكاء الاصطناعي اليومي (`{used_g}`).", ephemeral=True
        )
        return
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
      await interaction.followup.send(
          embed=embed, allowed_mentions=discord.AllowedMentions.none()
      )
    except AI_ERRORS as err:
      logger.warning("summarize AI error: %s: %s", type(err).__name__, err)
      await interaction.followup.send("⚠️ تعذر تلخيص المحادثة الآن.", ephemeral=True)
    except (discord.Forbidden, discord.HTTPException) as exc:
      logger.warning("summarize history failed: %s: %s", type(exc).__name__, exc)
      await interaction.followup.send("⚠️ تعذر قراءة سجل هذه القناة.", ephemeral=True)


def install(bot) -> None:
  """Attach this cog's commands to the tree without an event loop (see module docstring)."""
  for command in AiChat(bot).get_app_commands():
    bot.tree.add_command(command)
