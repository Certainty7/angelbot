"""Server pulse dashboard.

The client is passed explicitly, so a cog or a view can build the embed without importing bot.py.
"""
import re
from collections import Counter
from datetime import datetime, timezone

import discord


async def build_server_pulse_embed(bot, guild: discord.Guild) -> discord.Embed:
  """Build Angel Server Pulse dashboard for staff and owner."""
  open_tickets = sum(
      1 for ch in guild.text_channels
      if ch.topic and re.search(r"\bowner_id:\d+\b", ch.topic)
  )
  triggers = await bot.db.get_action_triggers(guild.id)
  top_triggers = sorted(triggers.values(), key=lambda x: x.get("usage_count", 0), reverse=True)[:5]
  trig_str = "\n".join(
      f"• `{t['phrase']}` ({t['action_type']}) — استُخدم `{t.get('usage_count', 0)}` مرة"
      for t in top_triggers
  )[:1024] or "لا توجد اختصارات مسجلة."

  ch_counts = bot.channel_activity_counter.get(guild.id, Counter())
  top_channels = ch_counts.most_common(5)
  ch_str = "\n".join(f"• <#{cid}> — `{cnt}` رسالة" for cid, cnt in top_channels) or "لا توجد بيانات نشاط بعد."

  knowledge_items = await bot.db.get_guild_knowledge(guild.id)
  modlog_id = await bot.db.get_modlog_channel(guild.id)
  guard_mode = await bot.db.get_guard_mode(guild.id)

  embed = discord.Embed(
      title=f"📊 نبض السيرفر — {guild.name}",
      color=0x2B2D31,
      timestamp=datetime.now(timezone.utc),
  )
  embed.add_field(name="👥 الأعضاء", value=f"`{guild.member_count}`", inline=True)
  embed.add_field(name="🎫 التذاكر المفتوحة", value=f"`{open_tickets}`", inline=True)
  embed.add_field(name="📚 معرفة السيرفر", value=f"`{len(knowledge_items)}` قاعدة", inline=True)
  embed.add_field(name="🛡️ وضع الحماية (Guard)", value=f"`{guard_mode}`", inline=True)
  embed.add_field(name="📋 قناة السجلات (ModLog)", value=f"<#{modlog_id}>" if modlog_id else "`غير محددة`", inline=True)
  embed.add_field(name="🔥 أنشط القنوات (الجلسة الحالية)", value=ch_str[:1024], inline=False)
  embed.add_field(name="⚡ أبرز الاختصارات الإدارية", value=trig_str[:1024], inline=False)
  return embed
