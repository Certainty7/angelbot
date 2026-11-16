"""Server rules: index the rules channel and answer from the index (with citations)."""
import re

from .cost import BudgetExhausted

_NUMBERED = re.compile(r"^\s*(?:\d{1,2}[).\-:]|[-•*])\s*(.+)$")


async def index_channel(client, db, guild_id: int, channel_id: int, limit: int = 200) -> int:
    channel = client.get_channel(channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(channel_id)
        except Exception:
            return 0
    stored = idx = 0
    async for msg in channel.history(limit=limit, oldest_first=True):
        text = (msg.content or "").strip()
        if not text:
            continue
        lines = [m.group(1).strip() for m in (_NUMBERED.match(l) for l in text.splitlines()) if m]
        chunks = lines or [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 12]
        for chunk in chunks:
            if len(chunk) < 8:
                continue
            idx += 1
            await db.upsert_rule(guild_id, f"قاعدة {idx}", chunk[:1200])
            stored += 1
    return stored


async def answer(ai, db, guild_id: int, question: str) -> str:
    hits = await db.search_rules(guild_id, question, 3)
    if not hits:
        return "ما لقيت قاعدة تنطبق على هالسؤال في قوانين السيرفر."
    bullets = "\n".join(f"{h['rule_key']}: {h['content']}" for h in hits)
    prompt = (
        "هذي قواعد السيرفر ذات الصلة:\n" + bullets +
        f"\n\nالسؤال: {question}\n"
        "جاوبي بجملة أو جملتين بموضوعية واذكري رقم القاعدة بين قوسين. "
        "إذا القواعد ما تغطي السؤال بالضبط قولي إنها ما تغطيه."
    )
    try:
        raw = await ai.generate_angel_reply_raw(prompt, max_tokens=220, temperature=0.2)
        return (raw or "").strip() or ("القواعد المتعلقة:\n" + bullets)
    except BudgetExhausted:
        return "القواعد المتعلقة:\n" + bullets
    except Exception:
        return "القواعد المتعلقة:\n" + bullets
