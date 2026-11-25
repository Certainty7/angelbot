"""Safe interaction helpers shared by bot.py and the cogs.

A cog answers an interaction without importing `bot`, which would be an import cycle.
"""
from typing import Any, Awaitable, Callable, Dict, Optional

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
      if untrusted:
        # The fallback send must be as mute as the interaction send: without this the
        # client default (`users=True`) let a member-authored mention ping a user.
        ch_kwargs["allowed_mentions"] = discord.AllowedMentions.none()
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


async def run_moderation_action(
    interaction: discord.Interaction,
    action: Callable[[], Awaitable[Any]],
    *,
    content: Optional[Any] = None,
    embed: Optional[discord.Embed] = None,
    modlog: Optional[Callable[[], Awaitable[Any]]] = None,
    not_found: Optional[str] = None,
) -> bool:
  """Defer, mutate, report, best-effort modlog — in that order, for every moderator surface.

  Discord kills the first response at three seconds. Mutating first meant a slow kick could
  succeed while the ACK failed with 10062, so the moderator saw a failure and retried an
  action that had already happened (audit finding 13). Nothing is mutated until the
  acknowledgement is accepted; `content` may be a callable that receives the action result.
  """
  if not await _safe_interaction_defer(interaction, ephemeral=False):
    return False
  try:
    result = await action()
  except discord.NotFound as exc:
    logger.warning("moderation action not found: %s: %s", type(exc).__name__, exc)
    await _safe_interaction_reply(
        interaction, not_found or "⚠️ الهدف غير موجود.", ephemeral=False
    )
    return False
  except discord.HTTPException as exc:
    logger.warning("moderation action failed: %s: %s", type(exc).__name__, exc)
    await _safe_interaction_reply(interaction, "⚠️ فشل الإجراء، لم يُنفَّذ شيء.", ephemeral=False)
    return False
  text = content(result) if callable(content) else content
  await _safe_interaction_reply(interaction, text, ephemeral=False, embed=embed)
  if modlog is not None:
    try:
      await modlog()
    except Exception as log_err:  # noqa: BLE001 - the action succeeded; a modlog must not undo it
      logger.warning("modlog failed: %s: %s", type(log_err).__name__, log_err)
  return True
