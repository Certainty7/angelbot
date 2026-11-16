"""Interactive views shared by bot.py and the cogs.

The views take the client explicitly, so a cog can build one without importing the entry module.
"""
import asyncio
import io
from datetime import datetime, timezone
from typing import Optional

import discord

from angel.config import MISTRESS_INT_ID, get_or_fetch_member, is_mistress, is_server_staff
from angel.dashboard import build_server_pulse_embed
from angel.database import BotDatabase
from angel.interactions import _safe_interaction_defer, _safe_interaction_reply


class ArtStudioView(discord.ui.View):

  def __init__(self, prompt: str, bot) -> None:
    super().__init__(timeout=600)
    self.prompt = prompt
    self.bot = bot

  async def _regenerate(self, interaction: discord.Interaction, style_preset: str, label_ar: str):
    harem_title = self.bot.get_harem_title(interaction.user.id)
    allowed, deny_reason = self.bot.quota.check_user_allowed(
        interaction.user, is_harem=(harem_title is not None)
    )
    if not allowed:
      await interaction.response.send_message(deny_reason, ephemeral=True)
      return
    await interaction.response.defer(thinking=True)
    try:
      img_bytes, _ = await self.bot.ai.generate_image_bytes(self.prompt, style_Preset=style_preset)
      file = discord.File(io.BytesIO(img_bytes), filename="angel_studio.png")
      embed = discord.Embed(
          description=f"🎨 **{self.prompt}** (`{label_ar}`)",
          color=0xD4AF37 if (is_mistress(interaction.user) or harem_title) else 0x2B2D31,
          timestamp=datetime.now(timezone.utc),
      )
      embed.set_image(url="attachment://angel_studio.png")
      await interaction.followup.send(embed=embed, file=file, view=ArtStudioView(self.prompt, self.bot))
    except Exception as exc:
      await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)

  @discord.ui.button(label="🔄 نسخة أخرى", style=discord.ButtonStyle.primary)
  async def reroll_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
    await self._regenerate(interaction, "anime", "نسخة جديدة")

  @discord.ui.button(label="✨ أسلوب أنمي فائق", style=discord.ButtonStyle.secondary)
  async def anime_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
    await self._regenerate(interaction, "anime", "أنمي فائق")

  @discord.ui.button(label="🌙 إضاءة سينمائية", style=discord.ButtonStyle.secondary)
  async def cinematic_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
    await self._regenerate(interaction, "cinematic", "سينمائي")


class TicketCloseView(discord.ui.View):

  def __init__(self, bot) -> None:
    self.bot = bot
    super().__init__(timeout=None)

  @discord.ui.button(
      label="🔒 إغلاق التذكرة",
      style=discord.ButtonStyle.danger,
      custom_id="angel_ticket_close_btn",
  )
  async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
      return
    topic_str = interaction.channel.topic or ""
    is_ticket_owner = f"owner_id:{interaction.user.id}" in topic_str or interaction.channel.name == f"ticket-{interaction.user.id}"
    has_manage = isinstance(interaction.user, discord.Member) and interaction.channel.permissions_for(interaction.user).manage_channels
    if not (is_ticket_owner or has_manage or is_mistress(interaction.user)):
      await interaction.response.send_message("🚫 إغلاق التذكرة متاح لصاحبها أو لإدارة السيرفر فقط.", ephemeral=True)
      return
    await interaction.response.send_message("🪽 جاري إغلاق التذكرة...")
    await self.bot.send_modlog(
        interaction.guild,
        "🔒 إغلاق تذكرة",
        f"**التذكرة:** `{interaction.channel.name}`\n**أُغلقت بواسطة:** {interaction.user.mention}",
    )
    await asyncio.sleep(2)
    try:
      await interaction.channel.delete(reason=f"Closed by {interaction.user}")
    except Exception:
      pass


class TicketPanelView(discord.ui.View):

  def __init__(self, bot) -> None:
    self.bot = bot
    super().__init__(timeout=None)

  @discord.ui.button(
      label="📩 فتح تذكرة",
      style=discord.ButtonStyle.primary,
      custom_id="angel_ticket_open_btn",
  )
  async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
    guild = interaction.guild
    if not guild:
      return
    channel_name = f"ticket-{interaction.user.id}"
    owner_tag = f"owner_id:{interaction.user.id}"
    existing = next(
        (
            ch for ch in guild.text_channels
            if ch.name == channel_name or (ch.topic and owner_tag in ch.topic)
        ),
        None,
    )
    if existing:
      await interaction.response.send_message(
          f"⚠️ لديك تذكرة مفتوحة بالفعل: {existing.mention}", ephemeral=True
      )
      return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(
            read_messages=True, send_messages=True, attach_files=True
        ),
        guild.me: discord.PermissionOverwrite(
            read_messages=True, send_messages=True, manage_channels=True
        ),
    }
    mistress_member = await get_or_fetch_member(guild, MISTRESS_INT_ID)
    if mistress_member:
      overwrites[mistress_member] = discord.PermissionOverwrite(
          read_messages=True, send_messages=True
      )

    try:
      ticket_ch = await guild.create_text_channel(
          name=channel_name,
          topic=f"تذكرة خاصة لـ {interaction.user.display_name} | {owner_tag}",
          overwrites=overwrites,
          reason=f"Ticket by {interaction.user}",
      )
      embed = discord.Embed(
          title="🎫 تذكرة خاصة",
          description=f"مرحباً {interaction.user.mention}، اكتب طلبك هنا.",
          color=0x2B2D31,
      )
      await ticket_ch.send(content=interaction.user.mention, embed=embed, view=TicketCloseView(self.bot))
      await interaction.response.send_message(
          f"✅ تم فتح تذكرتك: {ticket_ch.mention}", ephemeral=True
      )
    except discord.Forbidden:
      await interaction.response.send_message(
          "⚠️ أحتاج لصلاحية `Manage Channels` لإنشاء التذاكر.", ephemeral=True
      )


class GiveawayJoinView(discord.ui.View):

  def __init__(self, db: BotDatabase):
    super().__init__(timeout=None)
    self.db = db

  @discord.ui.button(
      label="🎉 المشاركة في السحب",
      style=discord.ButtonStyle.success,
      custom_id="angel_giveaway_enter_btn",
  )
  async def enter_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
    entered, total = await self.db.toggle_giveaway_participant(
        interaction.message.id, interaction.user.id
    )
    if entered:
      await interaction.response.send_message(
          f"🎉 تم تسجيل مشاركتك! (المشاركون: **{total}**)", ephemeral=True
      )
    else:
      await interaction.response.send_message(
          f"📤 تم إلغاء مشاركتك. (المشاركون: **{total}**)", ephemeral=True
      )



class AngelControlCenterView(discord.ui.View):

  def __init__(self, bot, user: discord.abc.User, guild: Optional[discord.Guild]):
    super().__init__(timeout=600)
    self.bot = bot
    self.user = user
    self.guild = guild

  @discord.ui.select(
      placeholder="🎭 ضبط أسلوب حديث أنجل معك...",
      options=[
          discord.SelectOption(label="واقعي وعفوي (الافتراضي)", value="realistic", emoji="🪽"),
          discord.SelectOption(label="مشاكس ومرح ودلوع", value="playful", emoji="✨"),
          discord.SelectOption(label="دافئ وحنون", value="warm", emoji="💖"),
          discord.SelectOption(label="مختصر ومباشر جداً", value="concise", emoji="⚡"),
          discord.SelectOption(label="بارد وحاد", value="cold", emoji="❄️"),
      ],
  )
  async def select_style(self, interaction: discord.Interaction, select: discord.ui.Select):
    await _safe_interaction_defer(interaction, ephemeral=True)
    chosen = select.values[0]
    await self.bot.db.set_user_style(interaction.user.id, chosen)
    await _safe_interaction_reply(
        interaction, f"✅ تم تحديث أسلوب حديث أنجل معك إلى: **`{chosen}`**.", ephemeral=True
    )

  @discord.ui.button(label="🧠 خزنة الذاكرة", style=discord.ButtonStyle.secondary)
  async def memory_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
    await _safe_interaction_defer(interaction, ephemeral=True)
    summary, _ = await self.bot.db.get_context_data(interaction.user.id)
    prefs = await self.bot.db.get_user_prefs(interaction.user.id)
    embed = discord.Embed(title="🧠 خزنة الذاكرة (Memory Vault)", color=0x2B2D31)
    embed.add_field(
        name="📌 التفضيلات المثبتة",
        value=prefs.get("pinned_facts") or "*لا توجد ملاحظات مثبتة بعد (`/memory action:pin`).*",
        inline=False,
    )
    embed.add_field(
        name="📝 ملخص المحادثات",
        value=summary or "*لا يوجد ملخص مسجل بعد.*",
        inline=False,
    )
    embed.add_field(name="🎭 نمط الأسلوب", value=f"`{prefs.get('style_mode', 'realistic')}`", inline=True)
    try:
      await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception:
      pass

  @discord.ui.button(label="📊 نبض السيرفر", style=discord.ButtonStyle.secondary)
  async def pulse_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
    if not interaction.guild or not is_server_staff(interaction.user, interaction.guild):
      await _safe_interaction_reply(interaction, "🚫 هذه اللوحة مخصصة لإدارة السيرفر فقط.", ephemeral=True)
      return
    await _safe_interaction_defer(interaction, ephemeral=True)
    embed = await build_server_pulse_embed(self.bot, interaction.guild)
    try:
      await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception:
      pass
