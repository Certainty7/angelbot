"""Owner controls and the tiered /help.

/silence keeps a silent cache plus a DB flag; /autonomy keeps a per-guild flag for the engine;
/help has three tiers, with the staff and owner sections shown only to staff or the owner.
"""
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from angel import autonomy, guard
from angel.config import is_mistress, is_server_staff
from angel.interactions import _safe_interaction_reply


class Control(commands.Cog):
  """`/silence`, `/autonomy`, `/help`."""

  def __init__(self, bot) -> None:
    self.bot = bot

  @app_commands.command(name="silence", description="منع أنجل من الكلام في قناة أو السيرفر كله (للمالكة فقط)")
  @app_commands.describe(mode="on = صامتة، off = تتكلم", channel="اتركها فارغة لكتم السيرفر كله")
  @app_commands.choices(mode=[
      app_commands.Choice(name="🔇 on — اسكتي", value="on"),
      app_commands.Choice(name="🔊 off — تكلمي", value="off"),
  ])
  async def silence_cmd(
      self,
      interaction: discord.Interaction,
      mode: app_commands.Choice[str],
      channel: Optional[discord.TextChannel] = None,
  ):
    if not is_mistress(interaction.user) or not interaction.guild:
      if interaction.guild:
        await _safe_interaction_reply(interaction, "🚫 هذا الأمر لصاحبتي فقط.", ephemeral=True)
      return
    target_id = channel.id if channel else 0
    silent = (mode.value == "on")
    await guard.set_silent(interaction.guild.id, target_id, silent, interaction.user.id)
    scope = channel.mention if channel else "كل السيرفر"
    if silent:
      await _safe_interaction_reply(interaction, f"🔇 تم. أنجل صامتة الآن في {scope} (لن ترد ولن تبدأ أي حديث).", ephemeral=True)
    else:
      await _safe_interaction_reply(interaction, f"🔊 رجعت أنجل تتكلم في {scope}.", ephemeral=True)


  @app_commands.command(name="autonomy", description="تفعيل/إيقاف تفاعل أنجل التلقائي وبدء الأحاديث من نفسها (للمالكة)")
  @app_commands.choices(mode=[
      app_commands.Choice(name="✅ تشغيل", value="on"),
      app_commands.Choice(name="⛔ إيقاف", value="off"),
      app_commands.Choice(name="📊 الحالة", value="status"),
  ])
  async def autonomy_cmd(self, interaction: discord.Interaction, mode: Optional[app_commands.Choice[str]] = None):
    if not is_mistress(interaction.user) or not interaction.guild:
      if interaction.guild:
        await _safe_interaction_reply(interaction, "🚫 هذا الأمر لصاحبتي فقط.", ephemeral=True)
      return
    gid = interaction.guild.id
    choice = (mode.value if mode else "status")
    if choice == "status":
      engine = autonomy.engine
      on = gid in self.bot.autonomy_guilds
      await _safe_interaction_reply(
          interaction,
          f"{'✅ مفعّل' if on else '⛔ متوقف'} — أرسلت أنجل **{engine.daily_count}** رسالة اليوم.\n"
          f"الحدود: {autonomy.MAX_PER_HOUR}/ساعة · {autonomy.MAX_PER_DAY}/يوم · هدوء من {autonomy.QUIET_START}:00 إلى {autonomy.QUIET_END}:00 (عُمان).",
          ephemeral=True,
      )
      return
    if choice == "on":
      self.bot.autonomy_guilds.add(gid)
      await self.bot.db.set_flag(f"autonomy:{gid}", "1")
      await _safe_interaction_reply(interaction, "✅ صار عند أنجل إذن تبدأ أحاديث من نفسها في هذا السيرفر.", ephemeral=True)
    else:
      self.bot.autonomy_guilds.discard(gid)
      await self.bot.db.set_flag(f"autonomy:{gid}", "0")
      await _safe_interaction_reply(interaction, "⛔ أوقفت تفاعل أنجل التلقائي في هذا السيرفر.", ephemeral=True)


  @app_commands.command(name="help", description="عرض قائمة الأوامر المتاحة")
  async def help_cmd(self, interaction: discord.Interaction):
    mistress = is_mistress(interaction.user)
    staff = is_server_staff(interaction.user, interaction.guild)
    harem_title = self.bot.get_harem_title(interaction.user.id)

    if mistress:
      title = "👑 لوحة الأوامر الخاصة بكِ"
      intro = "جميع الأوامر الخاصة، الصوتية، الإنتاجية، والإدارية (أو استخدمي `/angel` للوحة التفاعلية):"
      color = 0xD4AF37
    elif harem_title:
      title = "💖 قائمة الأوامر"
      intro = "الأوامر المتاحة لكِ (أو استخدمي `/angel` للوحة التفاعلية):"
      color = 0xD4AF37
    elif staff:
      title = "🪽 قائمة الأوامر (الإشراف والأعضاء)"
      intro = "الأوامر المتاحة بحسب صلاحياتك في السيرفر:"
      color = 0x2B2D31
    else:
      title = "🪽 الأوامر المتاحة"
      intro = "الأوامر العامة المتاحة للاستخدام:"
      color = 0x2B2D31

    embed = discord.Embed(title=title, description=intro, color=color)

    embed.add_field(
        name="🚀 ابدأ من هنا",
        value=(
            "• `/angel` — لوحة التحكم وأسلوب الحديث\n"
            "• `انجل شغلي <اسم أغنية أو رابط>` — تشغيل موسيقى\n"
            "• `انجل متى تكلمنا عن …؟` — تبحث في أرشيف السيرفر\n"
            "• `انجل وش تعرفين عني؟` — تعرض ما تعرفه عنك باقتباس وتاريخ\n"
            "• `/memory` — خزنة الذاكرة (عرض/تثبيت/نسيان)"
        ),
        inline=False,
    )

    if mistress:
      embed.add_field(
          name="👑 الأوامر السرية الخاصة (تظهر لكِ وحدكِ فقط)",
          value=(
              "• `/angel` — مركز التحكم التفاعلي الشامل\n"
              "• `/diagnostics` — تشخيص النظام والاتصال والنماذج\n"
              "• `/harem` — إدارة قائمة الحريم\n"
              "• `/sovereign` — التحكم الخفي بالسيرفرات وفحص حالة النظام\n"
              "• `/custom_action` — ربط أي كلمة أو عبارة بإجراء إداري تلقائي\n"
              "• `/dm_send` • `/whisper` • `/dm_logs` — مراسلة أي حساب ومراقبة الخاص\n"
              "• **أوامر الشات المباشرة (بمناداة `انجل` فقط):**\n"
              "  `انجل اسحبي @شخص لعندي` | `انجل خلي السجلات في #السجلات` | `انجل شغلي ...` | `انجل صفي الصوت`"
          ),
          inline=False,
      )

    embed.add_field(
        name="✨ المركز التفاعلي، الذاكرة، الصوتيات، والفيديو",
        value=(
            "• `/angel` — لوحة التحكم وضبط أسلوب الحديث\n"
            "• `/memory` — خزنة الذاكرة (عرض، تثبيت تفضيل دائم، نسيان معلومة)\n"
            "• `/silence` (كتمها) • `/autonomy` (تفاعلها التلقائي) • `/lore`\n"
            "• `/fix` • `/chat` • `/imagine` • `/gif` • `/translate` • `/knowledge` • `/summarize_channel`\n"
            "• **أوامر النقر بالزر الأيمن على أي رسالة (Apps):** `تلخيص الرسالة` • `ترجمة وتحليل` • `اقتراح رد ومهام`"
        ),
        inline=False,
    )
    embed.add_field(
        name="🌟 أدوات عامة",
        value=(
            "• `/rep` • `/afk` • `/snipe` • `/editsnipe`\n"
            "• `/rank` • `/leaderboard` • `/userinfo` • `/avatar` • `/serverinfo` • `/poll` • `/ping`\n"
            "• اسأليها مباشرة: `انجل وش تعرفين عني` — تجيبك من ملفها عنك بمقتطف وتاريخه"
        ),
        inline=False,
    )

    if staff or mistress:
      embed.add_field(
          name="🛡️ إدارة السيرفر ونبض المجتمع (للمشرفين فقط)",
          value=(
              "• `/pulse` • `/guard` • `/knowledge` • `/custom_action` • `/auto_reply` • `/sticky` • `/autorole`\n"
              "• `/kick` • `/ban` • `/unban` • `/timeout` • `/untimeout` • `/purge`\n"
              "• `/warn` • `/warnings` • `/clear_warnings` • `/lock` • `/unlock` • `/slowmode`\n"
              "• `/add_role` • `/remove_role` • `/announce` • `/giveaway` • `/ticket_panel` • `/set_modlog`"
          ),
          inline=False,
      )

    await interaction.response.send_message(embed=embed, ephemeral=True)



def install(bot) -> None:
  """Attach this cog's commands to the tree without an event loop (see module docstring)."""
  for command in Control(bot).get_app_commands():
    bot.tree.add_command(command)
