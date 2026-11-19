"""Message context menus.

discord.py does not allow a `context_menu` inside a Cog, so these stay module-level functions and
`install(bot)` adds them to the tree. The client is reached through `interaction.client`.
"""
import discord
from discord import app_commands

from angel.brain import AI_ERRORS
from angel.config import logger
from angel.guard import is_silent


async def _guard(interaction: discord.Interaction):
  """Silence, quota and cost checks shared by the three context menus."""
  if interaction.guild and is_silent(interaction.guild_id, interaction.channel_id):
    return "🔇 أنجل صامتة في هذه القناة."
  harem_title = interaction.client.get_harem_title(interaction.user.id)
  allowed, deny_reason = interaction.client.quota.check_user_allowed(
      interaction.user, is_harem=(harem_title is not None)
  )
  return None if allowed else deny_reason


def _untrusted(label: str, text: str) -> str:
  return f"{label}\n<untrusted_message>\n{text[:6000]}\n</untrusted_message>"


@app_commands.context_menu(name="تلخيص الرسالة")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def _summarize(interaction: discord.Interaction, message: discord.Message):
  deny = await _guard(interaction)
  if deny:
    await interaction.response.send_message(deny, ephemeral=True)
    return
  await interaction.response.defer(ephemeral=True, thinking=True)
  text = (message.content or "").strip()
  if not text:
    await interaction.followup.send("⚠️ هذه الرسالة لا تحتوي على نص لتلخيصه.", ephemeral=True)
    return
  prompt = _untrusted("لخّصي هذه الرسالة بوضوح واختصار في نقاط مركزة:", text)
  try:
    res = await interaction.client.ai.custom_prompt(interaction.user, prompt, harem_title=interaction.client.get_harem_title(interaction.user.id))
    embed = discord.Embed(title="📝 ملخص الرسالة", description=res[:4000], color=0x2B2D31)
    await interaction.followup.send(
        embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
    )
  except AI_ERRORS as err:
    logger.warning("context-menu summarize failed: %s: %s", type(err).__name__, err)
    await interaction.followup.send("⚠️ تعذر تلخيص الرسالة الآن.", ephemeral=True)


@app_commands.context_menu(name="ترجمة وتحليل")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def _translate(interaction: discord.Interaction, message: discord.Message):
  deny = await _guard(interaction)
  if deny:
    await interaction.response.send_message(deny, ephemeral=True)
    return
  await interaction.response.defer(ephemeral=True, thinking=True)
  text = (message.content or "").strip()
  if not text:
    await interaction.followup.send("⚠️ هذه الرسالة لا تحتوي على نص.", ephemeral=True)
    return
  prompt = _untrusted("ترجمي هذه الرسالة إلى العربية الفصحى الواضحة واشرحي المقصود منها باختصار:", text)
  try:
    res = await interaction.client.ai.custom_prompt(interaction.user, prompt, harem_title=interaction.client.get_harem_title(interaction.user.id))
    embed = discord.Embed(title="🌐 ترجمة وتحليل الرسالة", description=res[:4000], color=0x2B2D31)
    await interaction.followup.send(
        embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
    )
  except AI_ERRORS as err:
    logger.warning("context-menu translate failed: %s: %s", type(err).__name__, err)
    await interaction.followup.send("⚠️ تعذر تحليل الرسالة الآن.", ephemeral=True)


@app_commands.context_menu(name="اقتراح رد ومهام")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def _suggest(interaction: discord.Interaction, message: discord.Message):
  deny = await _guard(interaction)
  if deny:
    await interaction.response.send_message(deny, ephemeral=True)
    return
  await interaction.response.defer(ephemeral=True, thinking=True)
  text = (message.content or "").strip()
  if not text:
    await interaction.followup.send("⚠️ هذه الرسالة لا تحتوي على نص.", ephemeral=True)
    return
  prompt = _untrusted(
      f"بناءً على هذه الرسالة من ({message.author.display_name}):",
      text,
  ) + (
      "\n\n1. اقترحي ردّين مناسبين (رد دبلوماسي هادئ، ورد مختصر حازم).\n"
      "2. استخرجي أي مهمة مطلوبة في الرسالة إن وجدت."
  )
  try:
    res = await interaction.client.ai.custom_prompt(interaction.user, prompt, harem_title=interaction.client.get_harem_title(interaction.user.id))
    embed = discord.Embed(title="💡 اقتراح رد واستخراج مهام", description=res[:4000], color=0x2B2D31)
    await interaction.followup.send(
        embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
    )
  except AI_ERRORS as err:
    logger.warning("context-menu suggest failed: %s: %s", type(err).__name__, err)
    await interaction.followup.send("⚠️ تعذر اقتراح رد الآن.", ephemeral=True)


def install(bot) -> None:
  """Add the three context menus to the tree (they cannot live in a Cog)."""
  for command in (_summarize, _translate, _suggest):
    bot.tree.add_command(command)
