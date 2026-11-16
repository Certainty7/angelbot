"""Deep channel reader and summarizer.

The client is passed explicitly (bot, channel, requester, ...), so both the context menu and
/summarize_channel can use it from a cog.
"""
import discord


async def analyze_channel_history_deep(
    bot,
    channel: discord.abc.Messageable,
    requester: discord.abc.User,
    limit: int = 120,
    focus_query: str = "",
) -> str:
  collected = []
  try:
    async for msg in channel.history(limit=min(max(limit, 10), 500)):
      if msg.author.bot and not msg.embeds:
        continue
      time_str = msg.created_at.strftime("%H:%M")
      content = msg.content.strip()
      if msg.attachments:
        content += f" [مرفق: {', '.join(a.filename for a in msg.attachments)}]"
      if content:
        collected.append(f"[{time_str}] {msg.author.display_name}: {content}")
  except discord.Forbidden:
    return "⚠️ لا أملك صلاحية قراءة سجل الرسائل (`Read Message History`) في هذه القناة."
  except Exception as exc:
    return f"⚠️ تعذر قراءة سجل القناة: {exc}"

  if not collected:
    return "لا توجد رسائل كافية في هذه القناة لتحليلها."

  collected.reverse()
  transcript = "\n".join(collected)
  if len(transcript) > 28000:
    transcript = transcript[-28000:]

  instruction = (
      f"اقرئي سجل محادثات هذه القناة بدقة ({len(collected)} رسالة) وقدمي ملخصاً شاملاً وواضحاً يبين:\n"
      "1. **ملخص عام للمحادثة**.\n"
      "2. **أبرز ما قاله كل شخص**.\n"
      "3. **أهم النقاط أو القرارات**.\n"
  )
  if focus_query:
    instruction += f"\nركزي على الإجابة عن هذا الطلب من واقع المحادثة: ({focus_query})\n"
  instruction += f"\nسجل المحادثة:\n{transcript}"

  return await bot.ai.custom_prompt(
      requester,
      instruction,
      harem_title=bot.get_harem_title(requester.id),
      max_tokens=1400,
  )
