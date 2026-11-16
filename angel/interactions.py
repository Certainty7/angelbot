"""Safe interaction helpers shared by bot.py and the cogs.

A cog answers an interaction without importing `bot`, which would be an import cycle.
"""
from typing import Any, Dict, Optional

import discord


async def _safe_interaction_reply(
    interaction: discord.Interaction,
    content: Optional[str] = None,
    ephemeral: bool = True,
    *,
    embed: Optional[discord.Embed] = None,
    view: Optional[discord.ui.View] = None,
):
  """Send an interaction response or followup safely without crashing on expired 10062 tokens."""
  kwargs: Dict[str, Any] = {"ephemeral": ephemeral}
  if content is not None:
    kwargs["content"] = content
  if embed is not None:
    kwargs["embed"] = embed
  if view is not None:
    kwargs["view"] = view
  try:
    if not interaction.response.is_done():
      await interaction.response.send_message(**kwargs)
      return
  except (discord.NotFound, discord.HTTPException):
    pass
  try:
    await interaction.followup.send(**kwargs)
    return
  except (discord.NotFound, discord.HTTPException):
    pass
  if interaction.channel and isinstance(interaction.channel, discord.abc.Messageable) and not ephemeral:
    try:
      ch_kwargs: Dict[str, Any] = {}
      if content is not None:
        ch_kwargs["content"] = content
      if embed is not None:
        ch_kwargs["embed"] = embed
      if view is not None:
        ch_kwargs["view"] = view
      await interaction.channel.send(**ch_kwargs)
    except Exception:
      pass


async def _safe_interaction_defer(interaction: discord.Interaction, ephemeral: bool = True) -> bool:
  try:
    if not interaction.response.is_done():
      await interaction.response.defer(ephemeral=ephemeral)
    return True
  except (discord.NotFound, discord.HTTPException):
    return False
