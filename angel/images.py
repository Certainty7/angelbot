"""Image and GIF fetching, watermark crop, tag sanitizer."""

import aiohttp
import asyncio
import base64
import discord
import io
import re
import urllib.parse
from typing import List, Optional, Tuple
from .config import ARABIC_GIF_KEYWORDS, Image, is_romantic_gif
from .net import (
    _lower_worker_cpu_priority,
    get_image_proc_semaphore,
    get_media_download_semaphore,
    get_shared_http_session,
    is_safe_public_http_url_sync,
    read_bounded_stream,
)
from .persona import RELIGIOUS_TERMS_FILTER, normalize_arabic_text

if Image is not None:
  Image.MAX_IMAGE_PIXELS = 20_000_000

# 6. Media, GIF Downloader, Watermark Crop & Tag Sanitizer
# Patterns that strip repetitive vocatives ('يا اليقين', 'يا سيدتي') & stiff servant clichés
_REPETITIVE_VOCATIVES_RE = [
    (re.compile(r"عيون\s*أنجل\s*وقلبها[،,.!؟…\s]*", re.IGNORECASE), ""),
    (re.compile(r"(?:تفضلي\s*)?(?:يا\s*اليقين[،,.!؟…\s]*)?(?:آمريني|أمريني|امريني)[،,.!؟…\s]*", re.IGNORECASE), ""),
    (re.compile(r"(?:^|\s)(?:تأمرين|تامرين|تؤمرين|أمركِ?|امرك)\s*(?:يا\s*اليقين)?[،,.!؟…\s]*", re.IGNORECASE), " "),
    (re.compile(r"(?:^|\s)(?:سمعا\s*وطاعة|سمعاً\s*وطاعة)[،,.!؟…\s]*", re.IGNORECASE), " "),
    (re.compile(r"[،,\s]*يا\s*اليقين[،,.!؟…]*", re.IGNORECASE), ""),
    (re.compile(r"\bاليقين\b[،,.!؟…]*", re.IGNORECASE), ""),
    (re.compile(r"[،,\s]*يا\s*سيدتي[،,.!؟…]*", re.IGNORECASE), ""),
    (re.compile(r"ما\s*أقدر\s*أرفض\s*لكِ?\s*طلب[،,.!؟…]*", re.IGNORECASE), ""),
    (re.compile(r"ما\s*يردكِ?\s*شيء[،,.!؟…]*", re.IGNORECASE), ""),
    (re.compile(r"^(?:بالتأكيد|بكل\s*سرور|طبعاً\s*بكل\s*سرور)[!،,.\s]+", re.IGNORECASE), ""),
]


def strip_all_control_tags(text: str, allow_secret_name: bool = False) -> str:
  cleaned = re.sub(r"\*?\*?`?\[SEND_GIF:\s*[^\]]*\]`?\*?\*?", "", text, flags=re.IGNORECASE)
  cleaned = re.sub(r"\*?\*?`?\[GENERATE_IMAGE:\s*[^\]]*\]`?\*?\*?", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
  cleaned = re.sub(r"\*?\*?`?\[EXEC:\s*[^\]]*\]`?\*?\*?", "", cleaned, flags=re.IGNORECASE)
  cleaned = re.sub(r"\(\s*vs\._?7\s*\)", "", cleaned, flags=re.IGNORECASE)
  cleaned = re.sub(r"\b(?:لزبين|لزبيان|ليزبيان|يوري|lesbian|yuri)\b", "", cleaned, flags=re.IGNORECASE)
  # Strip stray Latin characters glued directly onto Arabic words (e.g. 'عيونof' -> 'عيون')
  cleaned = re.sub(r"(?<=[\u0600-\u06FF])[a-zA-Z]{1,6}(?=[^a-zA-Z]|$)", "", cleaned)
  cleaned = re.sub(r"(?:^|(?<=[^a-zA-Z]))[a-zA-Z]{1,6}(?=[\u0600-\u06FF])", "", cleaned)
  for pat, repl in RELIGIOUS_TERMS_FILTER:
    cleaned = pat.sub(repl, cleaned)
  if not allow_secret_name:
    for vpat, vrepl in _REPETITIVE_VOCATIVES_RE:
      cleaned = vpat.sub(vrepl, cleaned)
  cleaned = re.sub(r"\s{2,}", " ", cleaned)
  cleaned = re.sub(r"^[،,.!؟…\s]+", "", cleaned)
  return cleaned.strip()


def parse_ai_special_tags(
    reply_text: str, user_prompt: str, is_female_tier: bool = False, allow_romantic: bool = True
) -> Tuple[str, Optional[str], Optional[str], List[str]]:
  gif_action: Optional[str] = None
  image_prompt: Optional[str] = None
  exec_commands: List[str] = []

  gif_match = re.search(r"\[SEND_GIF:\s*([a-zA-Z_]+)\s*\]", reply_text, re.IGNORECASE)
  if gif_match:
    gif_action = gif_match.group(1).lower().strip()

  img_match = re.search(r"\[GENERATE_IMAGE:\s*(.+?)\s*\]", reply_text, re.IGNORECASE | re.DOTALL)
  if img_match:
    if not any(w in user_prompt for w in ("روم", "قناة", "شات", "رتبة", "فويس", "سجل", "لوج", "channel", "role")):
      image_prompt = img_match.group(1).strip()

  for exec_m in re.finditer(r"\[EXEC:\s*([^\]]+)\]", reply_text, re.IGNORECASE):
    exec_commands.append(exec_m.group(1).strip())

  lower_prompt = normalize_arabic_text(user_prompt.lower())
  asks_name = any(k in lower_prompt for k in ("وش اسمي", "ما هو اسمي", "شو اسمي", "من انا", "مين انا", "وش تناديني"))
  # HAREM-ONLY: never let a romantic reaction reach anyone outside mistress+harem,
  # even if the model itself produced the tag.
  if gif_action and is_romantic_gif(gif_action) and not allow_romantic:
    gif_action = None

  clean_text = strip_all_control_tags(reply_text, allow_secret_name=asks_name)

  # Prioritize cheek kiss / chaste kiss detection so it never gets confused with lip kiss
  if any(w in lower_prompt for w in (
      "بوسة في الخدود", "بوسه في الخدود", "بوسة خد", "بوسه خد", "بوسة خدود", "بوسه خدود",
      "بوسة عفيفة", "بوسه عفيفه", "بوسة بريئة", "بوسة على الخد", "بوسه على الخد", "cheek kiss", "peck"
  )):
    gif_action = "cheek_kiss"
  elif any(w in lower_prompt for w in ("بوسة في الفم", "بوسه في الفم", "بوسة فم", "بوسه فم", "بوسة شفايف", "بوسه شفايف", "lip kiss", "french kiss")):
    gif_action = "lip_kiss" if is_female_tier else "kiss"
  elif is_female_tier and any(w in lower_prompt for w in ("lesbian", "yuri", "لزبين", "لزبيان", "ليزبيان", "بنت مع بنت", "بوسة بنات", "بوسه بنات", "مع النسوان")):
    if any(h in lower_prompt for h in ("hug", "حضن", "ضم", "عناق")):
      gif_action = "yuri_hug"
    elif any(c in lower_prompt for c in ("cuddle", "دلال", "حنان")):
      gif_action = "yuri_cuddle"
    else:
      gif_action = "yuri_kiss"
  elif not gif_action and any(
      trig in lower_prompt
      for trig in ("جيف", "gif", "بوسيني", "احضنيني", "عطيني بوسة", "عطيني بوسه", "ابغى بوسة", "ابغى بوسه", "ارسل جيف", "ارسلي جيف", "اعطي ", "عطي ", "give me a kiss", "kiss me")
  ):
    for kw, act in ARABIC_GIF_KEYWORDS.items():
      if kw in lower_prompt:
        gif_action = act
        break
    if not gif_action:
      gif_action = "yuri_kiss" if is_female_tier else "smug"

  # Privacy & Tier Guard:
  # - For Mistress/Harem (is_female_tier=True), upgrade generic kiss/hug/cuddle/handhold to girl-x-girl internally.
  # - For regular public users (is_female_tier=False), downgrade any yuri_* or lip_kiss to standard anime reactions.
  if is_female_tier:
    if gif_action in ("kiss", "hug", "cuddle", "handhold"):
      sapphic_map = {
          "kiss": "yuri_kiss",
          "hug": "yuri_hug",
          "cuddle": "yuri_cuddle",
          "handhold": "yuri_handhold",
      }
      gif_action = sapphic_map.get(gif_action, gif_action)
  else:
    if gif_action in ("yuri_kiss", "lip_kiss"):
      gif_action = "kiss"
    elif gif_action == "yuri_hug":
      gif_action = "hug"
    elif gif_action == "yuri_cuddle":
      gif_action = "cuddle"
    elif gif_action == "yuri_handhold":
      gif_action = "handhold"

  return clean_text, gif_action, image_prompt, exec_commands


def remove_bottom_watermark_if_needed(img_bytes: bytes) -> bytes:
  if not Image:
    return img_bytes
  try:
    _lower_worker_cpu_priority()
    with Image.open(io.BytesIO(img_bytes)) as im:
      w, h = im.size
      if h > 400:
        with im.crop((0, 0, w, h - 38)) as cropped:
          out = io.BytesIO()
          cropped.save(out, format="PNG", compress_level=1)
          return out.getvalue()
  except Exception:
    pass
  return img_bytes


async def remove_bottom_watermark_async(img_bytes: bytes) -> bytes:
  """Run Pillow crop off the asyncio event loop so voice heartbeats never drop."""
  if not Image:
    return img_bytes
  loop = asyncio.get_running_loop()
  async with get_image_proc_semaphore():
    return await loop.run_in_executor(None, remove_bottom_watermark_if_needed, img_bytes)


def _is_safe_public_http_url(url: str) -> bool:
  """SSRF gate shared with angel.net: strict syntax plus DNS resolution of every address."""
  return is_safe_public_http_url_sync(url)


def _sniff_raster_mime(data: bytes) -> Optional[str]:
  """Return a raster MIME only when the magic bytes prove it; an HTML 200 is rejected."""
  if data.startswith(b"\x89PNG\r\n\x1a\n"):
    return "image/png"
  if data.startswith(b"\xff\xd8\xff"):
    return "image/jpeg"
  if data.startswith((b"GIF87a", b"GIF89a")):
    return "image/gif"
  if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
    return "image/webp"
  return None


async def download_media_as_base64(url: str) -> Optional[Tuple[str, str]]:
  curr_url = (url or "").strip()
  if not curr_url.lower().startswith(("https://", "http://")):
    return None
  loop = asyncio.get_running_loop()
  timeout = aiohttp.ClientTimeout(total=15)
  async with get_media_download_semaphore():
    try:
      session = await get_shared_http_session()
      for _hop in range(4):
        if not await loop.run_in_executor(None, _is_safe_public_http_url, curr_url):
          return None
        async with session.get(
            curr_url,
            headers={"User-Agent": "AngelBot/8.0"},
            allow_redirects=False,
            timeout=timeout,
        ) as resp:
          if resp.status in (301, 302, 303, 307, 308):
            loc = (resp.headers.get("Location") or "").strip()
            if not loc:
              return None
            curr_url = urllib.parse.urljoin(curr_url, loc)
            continue
          if resp.status != 200:
            return None
          content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
          data = await read_bounded_stream(resp, max_bytes=10 * 1024 * 1024, min_bytes=64)
          if not data:
            return None
          if content_type == "image/svg+xml":
            return None
          sniffed = _sniff_raster_mime(data)
          if sniffed is None:
            return None
          return sniffed, base64.b64encode(data).decode("utf-8")
      return None
    except Exception:
      return None


async def extract_message_media(message: discord.Message) -> List[Tuple[str, str]]:
  urls: List[str] = []

  def collect_from_msg(msg: discord.Message):
    for att in msg.attachments:
      ct = (att.content_type or "").lower()
      if ct.startswith("image/") or any(
          att.filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")
      ):
        urls.append(att.url)
    for emb in msg.embeds:
      if emb.image and emb.image.url:
        urls.append(emb.image.url)
      elif emb.thumbnail and emb.thumbnail.url:
        urls.append(emb.thumbnail.url)

  collect_from_msg(message)

  if not urls and message.reference and message.reference.message_id:
    ref_msg = message.reference.resolved
    if not isinstance(ref_msg, discord.Message):
      try:
        ref_msg = await message.channel.fetch_message(message.reference.message_id)
      except Exception:
        ref_msg = None
    if isinstance(ref_msg, discord.Message):
      collect_from_msg(ref_msg)

  media_list: List[Tuple[str, str]] = []
  for u in urls[:2]:
    res = await download_media_as_base64(u)
    if res:
      media_list.append(res)
  return media_list
