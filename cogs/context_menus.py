"""Message context menus.

discord.py does not allow a `context_menu` inside a Cog, so these stay module-level functions and
`install(bot)` adds them to the tree. The client is reached through `interaction.client`.
"""
import discord
from discord import app_commands

from angel.brain import AI_ERRORS


@app_commands.context_menu(name="تلخيص الرسالة")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def _summarize(interaction: discord.Interaction, message: discord.Message):
  await interaction.response.defer(ephemeral=True, thinking=True)
  text = (message.content or "").strip()
  if not text:
    await interaction.followup.send("⚠️ هذه الرسالة لا تحتوي على نص لتلخيصه.", ephemeral=True)
    return
  prompt = f"لخّصي هذه الرسالة بوضوح واختصار في نقاط مركزة:\n\n{text}"
  try:
    res = await interaction.client.ai.custom_prompt(interaction.user, prompt, harem_title=interaction.client.get_harem_title(interaction.user.id))
    embed = discord.Embed(title="📝 ملخص الرسالة", description=res[:4000], color=0x2B2D31)
    await interaction.followup.send(embed=embed, ephemeral=True)
  except AI_ERRORS as err:
    await interaction.followup.send(f"⚠️ {err}", ephemeral=True)


@app_commands.context_menu(name="ترجمة وتحليل")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def _translate(interaction: discord.Interaction, message: discord.Message):
  await interaction.response.defer(ephemeral=True, thinking=True)
  text = (message.content or "").strip()
  if not text:
    await interaction.followup.send("⚠️ هذه الرسالة لا تحتوي على نص.", ephemeral=True)
    return
  prompt = f"ترجمي هذه الرسالة إلى العربية الفصحى الواضحة واشرحي المقصود منها باختصار:\n\n{text}"
  try:
    res = await interaction.client.ai.custom_prompt(interaction.user, prompt, harem_title=interaction.client.get_harem_title(interaction.user.id))
    embed = discord.Embed(title="🌐 ترجمة وتحليل الرسالة", description=res[:4000], color=0x2B2D31)
    await interaction.followup.send(embed=embed, ephemeral=True)
  except AI_ERRORS as err:
    await interaction.followup.send(f"⚠️ {err}", ephemeral=True)


@app_commands.context_menu(name="اقتراح رد ومهام")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def _suggest(interaction: discord.Interaction, message: discord.Message):
  await interaction.response.defer(ephemeral=True, thinking=True)
  text = (message.content or "").strip()
  if not text:
    await interaction.followup.send("⚠️ هذه الرسالة لا تحتوي على نص.", ephemeral=True)
    return
  prompt = (
      f"بناءً على هذه الرسالة من ({message.author.display_name}):\n\"{text}\"\n\n"
      "1. اقترحي ردّين مناسبين (رد دبلوماسي هادئ، ورد مختصر حازم).\n"
      "2. استخرجي أي مهمة مطلوبة في الرسالة إن وجدت."
  )
  try:
    res = await interaction.client.ai.custom_prompt(interaction.user, prompt, harem_title=interaction.client.get_harem_title(interaction.user.id))
    embed = discord.Embed(title="💡 اقتراح رد واستخراج مهام", description=res[:4000], color=0x2B2D31)
    await interaction.followup.send(embed=embed, ephemeral=True)
  except AI_ERRORS as err:
    await interaction.followup.send(f"⚠️ {err}", ephemeral=True)


def install(bot) -> None:
  """Add the three context menus to the tree (they cannot live in a Cog)."""
  for command in (_summarize, _translate, _suggest):
    bot.tree.add_command(command)
