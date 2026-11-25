"""One confirmation primitive: typed, expiring, bound to guild + author + channel.

AGENTS.md and the README promise that destructive actions are queued and need the same person
to type `تأكيد` within 60 seconds, in the channel that requested them, with the permission
checked again at execution. Audit finding 14 found that only the model-proposed `[EXEC]` path
kept that promise.

The owner narrowed the invariant instead of widening the friction: **irreversible** actions
(message purge, ban, warning erasure) are gated on every surface — slash, natural language,
custom trigger, model — while reversible single-target commands stay immediate and are listed
as an approved exception in `docs/remediation/14-confirmation-scope.md`.

Every surface queues through `queue_confirmation` and every surface executes through
`take_confirmation`, so the invariant is one module rather than four copies.
"""

import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import discord

CONFIRM_TTL = 60.0
# Bare "نفذ" and "لا" were triggers once; both are ordinary Arabic words.
CONFIRM_WORDS = ("تأكيد", "تاكيد", "confirm", "نفذي")
CANCEL_WORDS = ("الغاء", "إلغاء", "كنسل", "cancel")

# Verdicts returned by `take_confirmation`.
NONE = "none"
EXPIRED = "expired"
WRONG_CHANNEL = "wrong_channel"
CONFIRMED = "confirmed"
CANCELLED = "cancelled"


def confirmation_prompt(summary: str) -> str:
    """The single prompt wording, so no surface can promise a different window."""
    return (
        f"⚠️ {summary}\n"
        "هذا الإجراء لا يمكن التراجع عنه. اكتب **تأكيد** خلال 60 ثانية لتنفيذه، "
        "أو أي كلمة أخرى للإلغاء."
    )


def queue_confirmation(
    bot,
    *,
    guild_id: int,
    author_id: int,
    channel_id: int,
    summary: str,
    run: Callable[[discord.Message], Awaitable[str]],
    now: Optional[float] = None,
) -> str:
    """Store the pending action and return the prompt to send.

    `run` receives the confirmation message: it must re-check the permission and re-resolve
    the target, then return the line to show. One entry per (guild, author), so a second
    request replaces the first rather than stacking two irreversible actions.
    """
    stamp = time.monotonic() if now is None else now
    _sweep(bot, stamp)
    bot.pending_confirm[(guild_id, author_id)] = {
        "summary": summary,
        "channel_id": channel_id,
        "ts": stamp,
        "run": run,
    }
    return confirmation_prompt(summary)


def take_confirmation(
    bot,
    *,
    guild_id: int,
    author_id: int,
    channel_id: int,
    text: str,
    now: Optional[float] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Decide what the message means for the pending action; pop it when it decides.

    Returns (verdict, entry). `NONE` leaves the entry alone: an ordinary word neither
    confirms nor cancels, and the minute keeps running.
    """
    key = (guild_id, author_id)
    pending = bot.pending_confirm.get(key)
    if not isinstance(pending, dict):
        return NONE, None
    stamp = time.monotonic() if now is None else now
    created = pending.get("ts")
    if not isinstance(created, (int, float)) or stamp - created > CONFIRM_TTL:
        bot.pending_confirm.pop(key, None)
        return EXPIRED, pending
    if pending.get("channel_id") and pending["channel_id"] != channel_id:
        # A confirmation typed in another channel is not consent for this one.
        bot.pending_confirm.pop(key, None)
        return WRONG_CHANNEL, pending
    lowered = (text or "").strip().lower()
    if lowered in CONFIRM_WORDS:
        bot.pending_confirm.pop(key, None)
        return CONFIRMED, pending
    if lowered in CANCEL_WORDS:
        bot.pending_confirm.pop(key, None)
        return CANCELLED, pending
    return NONE, pending


def _sweep(bot, now: float) -> None:
    """Drop expired entries so a dead request cannot be confirmed later."""
    if not isinstance(bot.pending_confirm, dict):
        return
    for key, value in list(bot.pending_confirm.items()):
        stamp = value.get("ts") if isinstance(value, dict) else None
        if not isinstance(stamp, (int, float)) or now - stamp > CONFIRM_TTL:
            bot.pending_confirm.pop(key, None)


async def queue_slash_confirmation(interaction, *, summary: str, run) -> bool:
    """Slash surfaces: acknowledge first (finding 13), then queue, then show the prompt.

    The interaction token dies long before the minute is up, so the action runs later from
    the confirmation message, never from the interaction.
    """
    from angel.interactions import _safe_interaction_defer, _safe_interaction_reply

    if not await _safe_interaction_defer(interaction, ephemeral=False):
        return False
    channel_id = getattr(interaction, "channel_id", None)
    if channel_id is None:
        channel_id = getattr(getattr(interaction, "channel", None), "id", None)
    prompt = queue_confirmation(
        interaction.client,
        guild_id=interaction.guild.id,
        author_id=interaction.user.id,
        channel_id=channel_id,
        summary=summary,
        run=run,
    )
    await _safe_interaction_reply(interaction, prompt, ephemeral=False)
    return True
