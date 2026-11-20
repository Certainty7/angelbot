"""What this server is like, learned from its own messages.

evolve_persona.py distils the last few hundred human lines into a compact culture note
(tone, running topics, in-jokes, what to avoid) and stores it per guild. The brain reads the
cached note on every reply, so Angel sounds like she has been in the room all along instead of
reciting a static persona card.
"""
import json
import time
from typing import Optional

from .registry import get_bot

_TTL = 1800.0
_CACHE: dict = {}


async def current(guild_id: Optional[int]) -> Optional[str]:
    """The culture block for this guild, or None when nothing was learned yet."""
    if not guild_id or get_bot() is None:
        return None
    hit = _CACHE.get(guild_id)
    now = time.monotonic()
    if hit and now - hit[1] < _TTL:
        return hit[0] or None
    try:
        raw = await get_bot().db.get_persona_culture(guild_id)
    except Exception:
        return None
    text = _render(raw)
    _CACHE[guild_id] = (text, now)
    return text or None


def _render(raw) -> str:
    if not raw:
        return ""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return ""
    # A list, a bare string or null in this column used to raise AttributeError on .get,
    # which took down every AI reply in the guild (C-010).
    if not isinstance(data, dict):
        return ""
    parts = []
    for key, label in (
        ("tone", "نبرة المكان"),
        ("topics", "المواضيع الدارجة"),
        ("jokes", "دعابات داخلية"),
        ("avoid", "تجنّبي"),
    ):
        value = data.get(key)
        if isinstance(value, list):
            value = "، ".join(str(v) for v in value[:5] if v)
        if value:
            parts.append(f"- {label}: {str(value)[:160]}")
    return "\n".join(parts)
