"""Memory vault, response style, rules index, budget and mood.

`/budget` reports the local-day spend and the 95% stop line; `/admin_note` requires the admin
context.
"""
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from angel import context_acl, cost
from angel import rules as rules_mod
from angel.config import is_mistress, logger


class MemoryRules(commands.Cog):
  """`/memory`, `/clear_history`, `/rules`, `/budget`, `/mood`, `/admin_note`."""

  def __init__(self, bot) -> None:
    self.bot = bot

  @app_commands.command(name="memory", description="خزنة الذاكرة: عرض أو تثبيت ملاحظة دائمة أو نسيان معلومة")
  @app_commands.allowed_installs(guilds=True, users=True)
  @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
  @app_commands.describe(
      action="العملية المطلوبة",
      text="المعلومة المراد تثبيتها أو الكلمة المراد نسيانها",
      style="ضبط أسلوب حديث أنجل معك",
  )
  @app_commands.choices(
      action=[
          app_commands.Choice(name="عرض خزنة الذاكرة (View)", value="view"),
          app_commands.Choice(name="تثبيت معلومة دائمة (Pin Fact)", value="pin"),
          app_commands.Choice(name="نسيان معلومة محددة (Forget Keyword)", value="forget"),
          app_commands.Choice(name="تغيير أسلوب الحديث (Set Style)", value="style"),
          app_commands.Choice(name="مسح سجل الجلسة (Clear Session)", value="clear"),
      ],
      style=[
          app_commands.Choice(name="واقعي وعفوي (Realistic)", value="realistic"),
          app_commands.Choice(name="مشاكس ومرح ودلوع (Playful)", value="playful"),
          app_commands.Choice(name="دافئ وحنون (Warm)", value="warm"),
          app_commands.Choice(name="مختصر ومباشر (Concise)", value="concise"),
          app_commands.Choice(name="بارد وحاد (Cold)", value="cold"),
      ],
  )
  async def memory_cmd(
      self,
      interaction: discord.Interaction,
      action: str = "view",
      text: Optional[str] = None,
      style: Optional[str] = None,
      confirm: bool = False,
  ):
    uid = interaction.user.id
    mistress = is_mistress(interaction.user)
    harem_title = self.bot.get_harem_title(uid)

    if action == "view":
      summary, _ = await self.bot.db.get_context_data(interaction.channel_id, uid)
      prefs = await self.bot.db.get_user_prefs(uid)
      embed = discord.Embed(
          title="🧠 خزنة الذاكرة (Angel Memory Vault)",
          color=0xD4AF37 if (mistress or harem_title) else 0x2B2D31,
      )
      embed.add_field(
          name="📌 التفضيلات والملاحظات الدائمة",
          value=(prefs.get("pinned_facts") or "*لا توجد ملاحظات مثبتة بعد.*")[:1024],
          inline=False,
      )
      embed.add_field(
          name="📝 ملخص المحادثة الحالية",
          value=(summary or "*لا توجد ملاحظات مسجلة بعد.*")[:1024],
          inline=False,
      )
      embed.add_field(name="🎭 نمط الأسلوب", value=f"`{prefs.get('style_mode', 'realistic')}`", inline=True)
      await interaction.response.send_message(embed=embed, ephemeral=True)
    elif action == "pin":
      if not text:
        await interaction.response.send_message("⚠️ اكتبي المعلومة أو التفضيل المراد تثبيته في `text`.", ephemeral=True)
        return
      await self.bot.db.pin_user_fact(uid, text[:1024])
      await interaction.response.send_message(f"📌 تم تثبيت هذه المعلومة في خزنة ذاكرتكِ الدائمة: **{text[:1024]}**", ephemeral=True)
    elif action == "forget":
      if not text:
        await interaction.response.send_message("⚠️ اكتبي الكلمة أو المعلومة المراد حذفها في `text`.", ephemeral=True)
        return
      if not confirm:
        # This scrubs the archive too, so it is irreversible and needs an explicit second step.
        await interaction.response.send_message(
            f"⚠️ سيُحذف كل ذكر لـ **({text[:60]})** من محادثاتك وأرشيف السيرفر وملاحظاتك، "
            "ولا يمكن التراجع. أعد الأمر مع `confirm` على «نعم» للتأكيد.",
            ephemeral=True,
        )
        return
      # Defer first: the archive delete can fail, and the receipt has to be sendable after
      # the database work (an expired interaction could no longer answer).
      await interaction.response.defer(ephemeral=True, thinking=True)
      try:
        await self.bot.db.forget_user_keyword(uid, text)
      except Exception as exc:
        logger.warning("memory forget failed for %s: %s: %s", uid, type(exc).__name__, exc)
        await interaction.followup.send(
            f"⚠️ لم يُحذف شيء: تعذّر الوصول إلى أرشيف المحادثات، فبقيت الكلمة **({text[:60]})** "
            "قابلة للاسترجاع. أعد المحاولة لاحقاً.",
            ephemeral=True,
        )
        return
      await interaction.followup.send(
          f"🗑️ تم حذف أي إشارة إلى **({text})** من ذاكرتكِ.", ephemeral=True)
    elif action == "style":
      chosen = style or "realistic"
      await self.bot.db.set_user_style(uid, chosen)
      await interaction.response.send_message(f"🎭 تم ضبط أسلوب حديث أنجل معك على: **`{chosen}`**.", ephemeral=True)
    elif action == "clear":
      await self.bot.db.clear_user_memory(interaction.channel_id, uid)
      await interaction.response.send_message(
          "✅ تم مسح سجل هذه المحادثة فقط (مع الاحتفاظ بتفضيلاتك المثبتة).", ephemeral=True)


  @app_commands.command(name="clear_history", description="مسح سجل المحادثة السابقة")
  async def clear_cmd(self, interaction: discord.Interaction):
    await self.bot.db.clear_user_memory(interaction.channel_id, interaction.user.id)
    await interaction.response.send_message("✅ تم مسح سجل هذه المحادثة فقط.", ephemeral=True)

  @app_commands.command(name="data", description="بياناتك عند أنجل: اعرض ما يُخزَّن عنك أو احذفه بالكامل")
  @app_commands.allowed_installs(guilds=True, users=True)
  @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
  @app_commands.describe(action="العملية المطلوبة", confirm="ضعها على نعم لتأكيد الحذف")
  @app_commands.choices(
      action=[
          app_commands.Choice(name="عرض بياناتي (View)", value="view"),
          app_commands.Choice(name="حذف بياناتي (Delete)", value="delete"),
      ]
  )
  async def data_cmd(
      self,
      interaction: discord.Interaction,
      action: str = "view",
      confirm: bool = False,
  ):
    """Member-facing data access and erasure, the `/data` half of the policy fix."""
    uid = interaction.user.id
    if action == "view":
      counts = await self.bot.db.count_user_data(uid)
      prefs = await self.bot.db.get_user_prefs(uid)
      embed = discord.Embed(
          title="🗂️ بياناتك عند أنجل",
          description=(
              "أنجل لا يبني ملفاً تعريفياً عنك. ما يلي هو كل ما يُخزَّن عنك شخصياً، وحذفه "
              "متاح بأمر واحد. تبقى سجلات الإشراف (الإنذارات) لأنها ملك للسيرفر، لا لك."
          ),
          color=0x2B2D31,
      )
      # Keys are the table names the deletion path actually uses; the old aliases made this
      # command raise KeyError right after the deletion set was widened (C-006).
      embed.add_field(name="رسائل مؤرشفة", value=f"`{counts.get('server_messages', 0)}`", inline=True)
      embed.add_field(name="رسائل محادثة البوت", value=f"`{counts.get('messages', 0)}`", inline=True)
      embed.add_field(name="ملاحظات محفوظة", value=f"`{counts.get('user_profile', 0)}`", inline=True)
      embed.add_field(name="رسائل خاصة مسجلة", value=f"`{counts.get('dm_logs', 0)}`", inline=True)
      embed.add_field(name="نقاط الخبرة", value=f"`{counts.get('user_xp', 0)}`", inline=True)
      embed.add_field(name="ملاحظات محيطة", value=f"`{counts.get('ambient_log', 0)}`", inline=True)
      embed.add_field(name="الحفظ التلقائي", value="موقوف" if prefs.get("opt_out") else "مفعّل", inline=True)
      failed_tables = counts.get("_failed_tables") or []
      if failed_tables:
        # A locked or damaged table must not vanish from the list the member is told is
        # complete: the counts above are partial until these tables are readable.
        embed.add_field(
            name="⚠️ جداول لم يمكن عدّها",
            value="`" + "`, `".join(failed_tables) + "` — القائمة أعلاه غير مكتملة لهذه الجداول.",
            inline=False,
        )
      embed.add_field(
          name="ملاحظاتك المثبتة بنفسك",
          value=(prefs.get("pinned_facts") or "*لا شيء*")[:1000],
          inline=False,
      )
      embed.set_footer(text="للحذف الكامل: /data action: حذف بياناتي confirm: نعم")
      await interaction.response.send_message(embed=embed, ephemeral=True)
      return

    if not confirm:
      await interaction.response.send_message(
          "⚠️ هذا يحذف رسائلك المؤرشفة وملاحظاتك ورسائلك الخاصة المسجلة، ولا يمكن التراجع عنه. "
          "أعد الأمر مع `confirm` على «نعم» إذا كنت متأكداً.",
          ephemeral=True,
      )
      return

    counts = await self.bot.db.delete_all_user_data(uid)
    # `/data delete` must also drop the in-memory copies: duplicate prevention, ambient
    # buffers and per-user locks survive a DB delete otherwise.
    for buffer in getattr(self.bot, "recent_speakers", {}).values():
      if hasattr(buffer, "clear"):
        kept = [row for row in buffer if int(row.get("user_id") or 0) != uid]
        buffer.clear()
        buffer.extend(kept)
    for channel_id, target in list(getattr(self.bot, "last_social_target", {}).items()):
      if target == uid:
        self.bot.last_social_target.pop(channel_id, None)
    for key in list(getattr(self.bot, "active_chat_window", {})):
      if isinstance(key, tuple) and key[-1] == uid:
        self.bot.active_chat_window.pop(key, None)
    for cache in (getattr(self.bot, "pending_step", {}), getattr(self.bot, "pending_confirm", {})):
      for key in list(cache):
        if isinstance(key, tuple) and key[-1] == uid:
          cache.pop(key, None)
    # The DB is not the only copy: AFK reasons, harem titles and the ambient buffer are
    # injected into other members' prompts and must drop the deleted member too.
    getattr(self.bot, "afk_cache", {}).pop((interaction.guild.id if interaction.guild else 0, uid), None)
    for afk_key in [k for k in getattr(self.bot, "afk_cache", {}) if isinstance(k, tuple) and k[-1] == uid]:
      self.bot.afk_cache.pop(afk_key, None)
    getattr(self.bot, "harem_cache", {}).pop(uid, None)
    ambient = getattr(self.bot, "recent_channel_msgs", {})
    for channel_id in list(ambient):
      buffer = ambient[channel_id]
      try:
        # Entries are (author_id, text) tuples. A plain string is a legacy entry whose
        # author cannot be identified: privacy-safe cleanup drops it rather than keep a
        # deleted member's line flowing into other members' prompts.
        kept_lines = [
            entry for entry in list(buffer)
            if isinstance(entry, tuple) and entry[0] != uid
        ]
        buffer.clear()
        buffer.extend(kept_lines)
      except Exception:
        ambient.pop(channel_id, None)
    self.bot.user_locks.pop(uid, None)

    failed = counts.get("_failed_tables") or []
    receipt = (
        "🗑️ حُذفت بياناتك: "
        f"`{counts.get('server_messages', 0)}` رسالة مؤرشفة، "
        f"`{counts.get('messages', 0)}` رسالة محادثة، "
        f"`{counts.get('user_profile', 0)}` ملاحظة، "
        f"`{counts.get('dm_logs', 0)}` رسالة خاصة. "
        "أُوقف الحفظ التلقائي عنك، ولن يُخزَّن جديد."
    )
    if failed:
      receipt += (
          "\n⚠️ تعذّر حذف بعض الجداول الآن: " + ", ".join(failed) +
          ". راسلي المالكة قبل اعتبار الحذف مكتملاً."
      )
    await interaction.response.send_message(receipt, ephemeral=True)


  @app_commands.command(name="rules", description="اسألي أنجل عن قوانين السيرفر وتجيبك من الفهرس")
  @app_commands.guild_only()
  @app_commands.describe(question="سؤالك عن القوانين", refresh="إعادة فهرسة قناة القوانين (للإدارة فقط)")
  async def rules_cmd(
      self, interaction: discord.Interaction, question: str, refresh: bool = False
  ):
    if not interaction.guild:
      await interaction.response.send_message("هذا الأمر للسيرفرات فقط.", ephemeral=True)
      return
    allowed, deny_reason = self.bot.quota.check_user_allowed(
        interaction.user, is_harem=(self.bot.get_harem_title(interaction.user.id) is not None)
    )
    if not allowed:
      await interaction.response.send_message(f"⚠️ {deny_reason}", ephemeral=True)
      return
    await interaction.response.defer(thinking=True)
    is_staff = is_mistress(interaction.user) or (
        isinstance(interaction.user, discord.Member)
        and interaction.user.guild_permissions.manage_guild
    )
    rules_channel = getattr(interaction.guild, "rules_channel", None)
    try:
      index = await self.bot.db.search_rules(interaction.guild.id, question, 1)
      # Separate "the corpus is empty" from "the question matched nothing": a populated
      # corpus with no match must answer normally, not trigger a rebuild that replaced
      # staff rules with whatever channel the caller is standing in.
      has_corpus = await self.bot.db.rules_corpus_exists(interaction.guild.id)
      if refresh or not has_corpus:
        if refresh and not is_staff:
          await interaction.followup.send("🚫 إعادة الفهرسة للإدارة فقط.", ephemeral=True)
          return
        if rules_channel is None:
          if not has_corpus:
            await interaction.followup.send(
                "📭 ما فيه فهرس قوانين بعد. اضبطي قناة القوانين في السيرفر ثم أعيدي المحاولة، "
                "أو شغّلي `/rules refresh: نعم` من قناة القوانين (للإدارة فقط).",
                ephemeral=True,
            )
            return
        elif is_staff:
          await rules_mod.index_channel(
              self.bot, self.bot.db, interaction.guild.id, rules_channel.id
          )
        elif not has_corpus:
          await interaction.followup.send(
              "📭 فهرس القوانين غير جاهز بعد. اطلبي من الإدارة تشغيل `/rules refresh: نعم`.",
              ephemeral=True,
          )
          return
      text = await rules_mod.answer(
          self.bot.ai, self.bot.db, interaction.guild.id, question, user=interaction.user
      )
    except Exception as exc:
      logger.warning(f"rules command failed: {exc}")
      text = "ما قدرت أطلع القوانين الآن."
    await interaction.followup.send(text[:1900], allowed_mentions=discord.AllowedMentions.none())


  @app_commands.command(name="budget", description="استهلاك أنجل من ميزانية النماذج اليوم (للإدارة فقط)")
  @app_commands.default_permissions(administrator=True)
  @app_commands.guild_only()
  async def budget_cmd(self, interaction: discord.Interaction):
    is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator
    if not (is_mistress(interaction.user) or is_admin):
      await interaction.response.send_message("هذا الأمر للإدارة فقط.", ephemeral=True)
      return
    await interaction.response.defer(ephemeral=True, thinking=True)
    embed = discord.Embed(title="💳 ميزانية اليوم", color=0x2B2D31)
    if is_mistress(interaction.user):
      day = cost.local_day()
      spent = await self.bot.db.day_cost(day)
      stats = self.bot.sender.stats() if self.bot.sender else {}
      embed.add_field(name="المصروف (عام)", value=f"${spent:.4f}", inline=True)
      embed.add_field(name="حد التوقف (95%)", value=f"${cost.stop_at():.4f}", inline=True)
      embed.add_field(name="وضع الاستماع", value="نعم" if self.bot.listening else "لا", inline=True)
      if stats:
        embed.add_field(name="الطابور", value=f"مرسل: {stats.get('sent', 0)} • معاد: {stats.get('retried', 0)} • معلّق: {stats.get('pending', 0)}", inline=False)
    else:
      used, limit = await self.bot.db.get_guild_ai_usage(interaction.guild.id)
      embed.add_field(name="حصتك اليومية", value=f"`{used}` / `{limit}`", inline=True)
      embed.add_field(name="المتبقي", value=f"`{max(0, limit - used)}`", inline=True)
    embed.set_footer(text="التوقيت المحلي")
    await interaction.followup.send(embed=embed, ephemeral=True)


  @app_commands.command(name="mood", description="تعديل مزاج أنجل الحالي (للمالكة فقط)")
  @app_commands.describe(value="قيمة بين 0.15 و0.85")
  async def mood_cmd(self, interaction: discord.Interaction, value: app_commands.Range[float, 0.15, 0.85]):
    if not is_mistress(interaction.user):
      await interaction.response.send_message("هذا الأمر للمالكة فقط.", ephemeral=True)
      return
    self.bot.mood = float(value)
    await self.bot.db.set_state_value("mood", self.bot.mood)
    await self.bot.db.set_state_value("settings", self.bot.settings)
    await interaction.response.send_message(f"تم. مزاج أنجل الآن {self.bot.mood:.2f}.", ephemeral=True)


  @app_commands.command(name="admin_note", description="حفظ ملاحظة إدارية خاصة (رتبة إدارية + قناة إدارية فقط)")
  @app_commands.describe(topic="الموضوع", content="التفاصيل")
  async def admin_note_cmd(self, interaction: discord.Interaction, topic: str, content: str):
    if not interaction.guild:
      await interaction.response.send_message("هذا الأمر للسيرفرات فقط.", ephemeral=True)
      return
    try:
      ctx = context_acl.require_admin_context(interaction.user, interaction.channel)
    except context_acl.AclError:
      await interaction.response.send_message("ما ينفع هنا. هذا محتوى إداري وقناتك أو رتبتك غير مصرّح لها.", ephemeral=True)
      return
    await self.bot.db.add_admin_memory(interaction.guild.id, ctx.channel_id, topic, content, interaction.user.id)
    await interaction.response.send_message("انحفظت في ذاكرة الإدارة (ما تُقرأ خارج القنوات الإدارية).", ephemeral=True)



def install(bot) -> None:
  """Attach this cog's commands to the tree without an event loop (see module docstring)."""
  for command in MemoryRules(bot).get_app_commands():
    bot.tree.add_command(command)
