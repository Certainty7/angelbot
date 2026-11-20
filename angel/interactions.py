"""Safe interaction helpers shared by bot.py and the cogs.

A cog answers an interaction without importing `bot`, which would be an import cycle.
"""
from typing import Any, Dict, Optional

import discord

from .config import logger


def _terminal_interaction_error(exc: discord.HTTPException) -> bool:
    """10062 (unknown/expired) and 400 payload errors cannot be fixed by retrying."""
    return getattr(exc, "code", None) == 10062 or getattr(exc, "status", None) == 400


async def _safe_interaction_reply(
    interaction: discord.Interaction,
    content: Optional[str] = None,
    ephemeral: bool = True,
    *,
    embed: Optional[discord.Embed] = None,
    view: Optional[discord.ui.View] = None,
    untrusted: bool = False,
):
  """Send an interaction response or followup safely without crashing on expired 10062 tokens.

  `untrusted=True` suppresses every ping for member-authored text echoed by the bot.
  """
  kwargs: Dict[str, Any] = {"ephemeral": ephemeral}
  if content is not None:
    kwargs["content"] = content
  if embed is not None:
    kwargs["embed"] = embed
  if view is not None:
    kwargs["view"] = view
  if untrusted:
    kwargs["allowed_mentions"] = discord.AllowedMentions.none()
  try:
    if not interaction.response.is_done():
      await interaction.response.send_message(**kwargs)
      return
  except (discord.NotFound, discord.HTTPException) as exc:
    logger.debug("interaction response failed: %s: %s", type(exc).__name__, exc)
    if _terminal_interaction_error(exc):
      return
  try:
    await interaction.followup.send(**kwargs)
    return
  except (discord.NotFound, discord.HTTPException) as exc:
    logger.debug("interaction followup failed: %s: %s", type(exc).__name__, exc)
    if _terminal_interaction_error(exc):
      return
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
    except discord.HTTPException as exc:
      logger.warning("interaction channel fallback failed: %s: %s", type(exc).__name__, exc)


async def _safe_interaction_defer(interaction: discord.Interaction, ephemeral: bool = True) -> bool:
  try:
    if not interaction.response.is_done():
      await interaction.response.defer(ephemeral=ephemeral)
    return True
  except (discord.NotFound, discord.HTTPException):
    return False
