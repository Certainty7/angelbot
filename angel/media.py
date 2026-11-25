"""TikTok / Instagram / X / Reddit resolvers and storage cleaner."""

import aiohttp
import asyncio
import base64
import hashlib
import html as html_lib
import io
import json
import os
import random
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Set, Tuple
from .config import BASE_DIR, FFMPEG_EXE, Image, _safe_gc_collect, logger, yt_dlp
from .images import _is_safe_public_http_url
from .net import (
    SharedByteBudget,
    get_shared_http_session,
    is_allowed_hostname,
    read_bounded_stream,
    safe_fetch_response,
    validate_ig_shortcode,
)
from .downloader import _AUDIO_STREAM_CACHE, _KNOWN_PREVIEW_URLS, run_ytdlp_json
from .registry import get_bot

# 4. Multi-Stage Social Media Video & Multi-Photo Resolver (TikTok Videos/Slideshows, Instagram Reels/Carousels, X, Reddit) + Storage Garbage Cleaner
SOCIAL_URL_REGEX = re.compile(
    r"https?://(?:www\.|vm\.|vt\.|m\.|lite\.|dd|vx|kk|fx|tn)?(?:tiktok\.com|tnktok\.com|tfxktok\.com|vxtiktok\.com|instagram\.com|instagr\.am|twitter\.com|x\.com|reddit\.com|redd\.it)/[^\s<>\"']+",
    re.IGNORECASE,
)

# A member link is routed by its parsed host, never by a substring: a URL such as
# `http://169.254.169.254/?tiktok.com` must not reach the TikTok resolver.
_SOCIAL_ALLOWED_HOSTS = (
    "tiktok.com", "tnktok.com", "tfxktok.com", "vxtiktok.com",
    "instagram.com", "instagr.am", "ddinstagram.com",
    "x.com", "twitter.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com",
    "reddit.com", "redd.it", "rxddit.com", "vxreddit.com",
)


def _allowed_social_host(url: str) -> bool:
  return is_allowed_hostname(url, _SOCIAL_ALLOWED_HOSTS)


_FFMPEG_SEMS: Dict[int, asyncio.Semaphore] = {}

# One media job may hold at most this much image/video data in RAM. The container is capped
# at 1 GB and also runs Python, Pillow and the Discord client; 20 carousel slides at the
# 25 MB upload ceiling would be 500 MB for a single job (C-007).
MAX_JOB_BYTES = 50 * 1024 * 1024


def _fit_byte_budget(
    items: List[Tuple[int, bytes, str]], budget: int = MAX_JOB_BYTES
) -> Tuple[List[Tuple[int, bytes, str]], int]:
    """Keep slides until their combined payload reaches `budget`; return (kept, dropped)."""
    kept: List[Tuple[int, bytes, str]] = []
    total = 0
    dropped = 0
    for item in items:
        size = len(item[1])
        if kept and total + size > budget:
            dropped += 1
            continue
        kept.append(item)
        total += size
    return kept, dropped


def _fit_file_budget(
    files: List[Tuple[bytes, str]], budget: int = MAX_JOB_BYTES
) -> Tuple[List[Tuple[bytes, str]], int]:
    """Same budget for the (bytes, filename) shape the extractors return."""
    kept: List[Tuple[bytes, str]] = []
    total = 0
    dropped = 0
    for data, name in files:
        if kept and total + len(data) > budget:
            dropped += 1
            continue
        kept.append((data, name))
        total += len(data)
    return kept, dropped


def _get_ffmpeg_semaphore(limit: int = 2) -> asyncio.Semaphore:
  """Loop-scoped semaphore capping concurrent libx264 transcodes."""
  lid = id(asyncio.get_running_loop())
  sem = _FFMPEG_SEMS.get(lid)
  if sem is None:
    sem = asyncio.Semaphore(limit)
    _FFMPEG_SEMS[lid] = sem
  return sem


def _dedupe_downloaded_slides(
    valid_items: List[Tuple[int, bytes, str]], seen_hashes: Set[str]
) -> Tuple[List[Tuple[int, bytes, str]], int, List[int]]:
  """Split downloaded slides into (kept, discarded_bytes, missing_indices).

  The caller must drop its own references to the discarded payloads (clear the gather
  result and the valid-item list) *before* releasing `discarded_bytes` from the job
  budget: releasing while a duplicate is still referenced lets the repair download
  claim memory the duplicate still occupies, and real peak RAM passes the ceiling.
  """
  kept: List[Tuple[int, bytes, str]] = []
  missing: List[int] = []
  discarded_bytes = 0
  for item in valid_items:
    idx, b_data, _fname = item
    h = hashlib.md5(b_data).hexdigest()
    if h not in seen_hashes:
      seen_hashes.add(h)
      kept.append(item)
    else:
      missing.append(idx)
      discarded_bytes += len(b_data)
  return kept, discarded_bytes, missing


def _create_private_temp_dir(prefix: str = "angelbot_social_") -> str:
  path = tempfile.mkdtemp(prefix=prefix)
  try:
    os.chmod(path, 0o700)
  except OSError:
    pass
  return path

_TIKWM_LOCK = asyncio.Lock()
_LAST_TIKWM_CALL_AT: float = 0.0


def chunk_slides(items, size: int = 10):
  """Batch extracted slides into Discord-sized groups (10 attachments per message).

  The old call sites sent a fixed first and second batch, so slide 21 and beyond
  were dropped silently. Callers must send every batch returned here.
  """
  size = max(1, int(size))
  items = list(items or [])
  return [items[i:i + size] for i in range(0, len(items), size)]


async def resolve_social_redirect_and_clean(url: str) -> str:
  clean_url = url.strip().strip("<>")
  # Normalize any third-party proxy domains back to canonical domains before resolving
  clean_url = re.sub(
      r"https?://(?:[a-z0-9]+\.)?(?:vxtiktok|tnktok|tfxktok|tiktxk|kktiktok)\.com",
      "https://www.tiktok.com",
      clean_url,
      flags=re.IGNORECASE,
  )
  clean_url = re.sub(
      r"https?://(?:[a-z0-9]+\.)?(?:vxinstagram|ddinstagram|kkinstagram|instagramez|eeinstagram|uuinstagram)\.com",
      "https://www.instagram.com",
      clean_url,
      flags=re.IGNORECASE,
  )
  # X/Reddit "fixer" hosts (what other bots and /fix replies hand back) must be un-fixed before the
  # rewrite below, which matches the bare domain inside the host: a second pass produced dead
  # fxfxtwitter.com / vxrxddit.com mirrors and the post lost its embed.
  clean_url = re.sub(
      r"https?://(?:[a-z0-9]+\.)?(?:fxtwitter|vxtwitter|fixupx)\.com",
      "https://x.com",
      clean_url,
      flags=re.IGNORECASE,
  )
  clean_url = re.sub(
      r"https?://(?:[a-z0-9]+\.)?(?:rxddit|vxreddit)\.com",
      "https://www.reddit.com",
      clean_url,
      flags=re.IGNORECASE,
  )

  headers = {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9",
  }
  lower_u = clean_url.lower()
  if any(
      s in lower_u
      for s in ("/share/", "/t/", "instagr.am/", "vm.tiktok.com", "vt.tiktok.com", "lite.tiktok.com", "redd.it/")
  ):
    # A share short-link is still a URL from a member: never fetch loopback, the VPN subnet or
    # the cloud metadata address just because the text happens to contain "/share/".
    # getaddrinfo is blocking; running it inline froze the event loop (and voice) on a slow DNS.
    if not await asyncio.to_thread(_is_safe_public_http_url, clean_url):
      return clean_url
    try:
      session = await get_shared_http_session()
      # Redirects are followed one hop at a time and every target is re-validated; following
      # them inside aiohttp would let a public host bounce the request to 127.0.0.1 or the
      # cloud metadata address after the guard has already approved the first URL.
      final_u, status, _ctype, _body = await safe_fetch_response(
          clean_url, max_bytes=256 * 1024, headers=headers, session=session
      )
      if status == 200:
        # If TikTok redirected to a login wall with ?redirect_url=..., extract the real target URL!
        if "redirect_url=" in final_u:
          q_params = urllib.parse.parse_qs(urllib.parse.urlsplit(final_u).query)
          red_list = q_params.get("redirect_url")
          if red_list and red_list[0].startswith("http") and _allowed_social_host(red_list[0]):
            if await asyncio.to_thread(_is_safe_public_http_url, red_list[0]):
              final_u = red_list[0]
        clean_url = final_u
    except Exception:
      pass

  parsed = urllib.parse.urlsplit(clean_url)
  if _allowed_social_host(clean_url):
    clean_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
  return clean_url


def _unescape_ig_url(raw_u: str) -> str:
  """Unescape double-escaped or unicode-escaped URLs from Instagram contextJSON / GraphQL / data-sjs."""
  if not raw_u:
    return ""
  s = raw_u.strip()
  for _ in range(2):
    s = s.replace(r"\\/", "/").replace(r"\/", "/").replace(r"\u0026", "&").replace(r"\u0025", "%")
    try:
      if r"\u" in s:
        s = s.encode("utf-8").decode("unicode_escape")
    except Exception:
      pass
  s = html_lib.unescape(s).strip('"\'')
  return s


def _is_valid_mp4_video_bytes(data: Optional[bytes], content_type: str = "") -> bool:
  """
  Verify that downloaded bytes are a genuine playable video container (MP4/MOV/WebM)
  and NOT an MP3 audio track (ID3 / MPEG audio sync), static image, or HTML error page.
  """
  if not data or len(data) < 4096:
    return False
  ct = (content_type or "").lower()
  if any(bad_ct in ct for bad_ct in ("audio/", "image/", "text/html", "application/json")):
    return False
  head = data[:64]
  head_lstrip = head.lstrip()
  if head_lstrip.startswith((b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML", b"{", b"[")):
    return False
  # Reject MP3 audio files (ID3v2 tag or MPEG ADTS/MP3 sync word 0xFFFx)
  if head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
    return False
  # Reject JPEG / PNG / GIF / WebP static images masquerading as video
  if head.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a")):
    return False
  if head.startswith(b"RIFF") and b"WEBP" in head[:16]:
    return False
  # Reject audio-only M4A containers
  if b"ftypM4A " in head[:24] or b"ftypmp4a" in head[:24]:
    return False
  # Valid MP4/MOV has 'ftyp' or 'moov'/'mdat', valid WebM/Matroska starts with 0x1A45DFA3
  if b"ftyp" in head[:32] or b"moov" in head[:64] or b"mdat" in head[:64] or head.startswith(b"\x1a\x45\xdf\xa3"):
    return True
  return "video/" in ct


def _normalize_image_bytes_sync(data: bytes) -> Optional[bytes]:
  """
  Validate image bytes and convert WebP / non-standard image formats into high-quality JPEG
  so Discord renders every photo inline in a clean multi-image grid without attachment glitches.
  """
  if not data or len(data) < 400:
    return None
  head = data[:32].lstrip()
  if head.startswith((b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML", b"{")):
    return None
  # Reject MP3 or MP4 video bytes accidentally passed to image normalizer
  if data[:3] == b"ID3" or b"ftyp" in data[:24]:
    return None
  # If already standard JPEG or PNG, return directly without CPU overhead
  if data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n"):
    return data
  if Image is not None:
    try:
      with Image.open(io.BytesIO(data)) as im:
        rgb = im.convert("RGB")
        out = io.BytesIO()
        rgb.save(out, format="JPEG", quality=92)
        return out.getvalue()
    except Exception:
      pass
  if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
    return data
  return None


async def _normalize_image_bytes(data: Optional[bytes]) -> Optional[bytes]:
  if not data:
    return None
  if data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n"):
    return data
  loop = asyncio.get_running_loop()
  return await loop.run_in_executor(None, _normalize_image_bytes_sync, data)


async def _ensure_discord_playable_mp4(video_bytes: bytes, max_bytes: int = 10 * 1024 * 1024) -> bytes:
  """
  If a downloaded TikTok/Instagram MP4 uses HEVC/ByteVC1 (`hvc1` / `hev1` without `avc1`),
  which renders as a black screen on many Discord clients, fast-transcode it to H.264 via FFmpeg.
  """
  if not video_bytes or not FFMPEG_EXE:
    return video_bytes
  head_sample = video_bytes[: min(len(video_bytes), 131072)]
  tail_sample = video_bytes[max(0, len(video_bytes) - 131072) :]
  has_hevc = (b"hvc1" in head_sample or b"hev1" in head_sample or b"hvc1" in tail_sample or b"hev1" in tail_sample)
  has_avc1 = (b"avc1" in head_sample or b"avc1" in tail_sample)
  if not (has_hevc and not has_avc1):
    return video_bytes

  tmp_dir = _create_private_temp_dir("angelbot_transcode_")
  try:
    rnd = f"{os.getpid()}_{random.randint(1000, 9999)}"
    in_p = os.path.join(tmp_dir, f"in_{rnd}.mp4")
    out_p = os.path.join(tmp_dir, f"out_{rnd}.mp4")
    async with _get_ffmpeg_semaphore():
      await asyncio.to_thread(_write_file_sync, in_p, video_bytes)
      proc = await asyncio.create_subprocess_exec(
          FFMPEG_EXE, "-nostdin", "-y", "-loglevel", "error",
          "-i", in_p,
          "-c:v", "libx264", "-preset", "ultrafast", "-crf", "25",
          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
          "-movflags", "+faststart", out_p,
          stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
      )
      try:
        await asyncio.wait_for(proc.wait(), timeout=14.0)
      except asyncio.TimeoutError:
        raise
      finally:
        # A cancelled transcode used to delete tmp_dir while ffmpeg was still writing.
        if proc.returncode is None:
          try:
            proc.kill()
          except ProcessLookupError:
            pass
          try:
            asyncio.get_running_loop().create_task(proc.wait())
          except RuntimeError:
            pass
      if os.path.isfile(out_p):
        sz = os.path.getsize(out_p)
        if 4096 < sz <= max_bytes:
          video_bytes = await asyncio.to_thread(_read_file_sync, out_p)
  except Exception:
    pass
  finally:
    await asyncio.to_thread(shutil.rmtree, tmp_dir, True)
  return video_bytes


def _write_file_sync(path: str, data: bytes) -> None:
  with open(path, "wb") as handle:
    handle.write(data)


def _read_file_sync(path: str) -> bytes:
  with open(path, "rb") as handle:
    return handle.read()


def _decode_snapsave_eval(h: str, u: int, n: str, t: int, e: int) -> str:
  """
  Pure-Python decoder for SnapSave's obfuscated `eval(function(h,u,n,t,e,r){...})` response.

  Every field is attacker-controlled, so the decoder has a contract: it raises
  `ValueError` instead of doing unbounded work. `h` and `n` are capped at 64 KiB,
  the alphabet must be unique, `e` must index it, and one `str.translate` pass
  replaces the per-character `str.replace` loop that made the cost quadratic.
  """
  MAX_FIELD = 64 * 1024
  MAX_OUTPUT = 2 * 1024 * 1024
  MAX_OFFSET = 1_000_000
  alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"

  if not isinstance(h, str) or not isinstance(n, str):
    raise ValueError("snapsave payload fields must be strings")
  if len(h) > MAX_FIELD or len(n) > MAX_FIELD:
    raise ValueError("snapsave payload exceeds the 64 KiB field cap")
  if len(n) < 2 or len(n) > 128:
    raise ValueError("snapsave alphabet has an unsupported length")
  if len(set(n)) != len(n):
    raise ValueError("snapsave alphabet characters must be unique")
  if not (0 <= u <= MAX_OFFSET):
    raise ValueError("snapsave offset out of range")
  if not (0 <= t <= 0x10FFFF):
    raise ValueError("snapsave code offset out of range")
  if not (2 <= e < len(n)):
    raise ValueError("snapsave base must index the alphabet")

  table = {ord(ch): str(idx) for idx, ch in enumerate(n)}
  sep_char = n[e]

  res: List[str] = []
  total = 0
  for token in h.split(sep_char):
    if not token:
      continue
    digits = token.translate(table)
    # base-`e` digits, most significant first; the value only grows as we scan, so a
    # token that is already past every valid code point can stop early.
    val = 0
    for ch in digits:
      pos = alphabet.find(ch)
      if pos == -1 or pos >= e:
        val = -1
        break
      val = val * e + pos
      if val - u > 0x10FFFF:
        val = -1
        break
    if val < 0:
      continue
    code_val = val - u
    if 0 <= code_val <= 0x10FFFF:
      res.append(chr(code_val))
      total += 1
      if total > MAX_OUTPUT:
        raise ValueError("snapsave decoded output exceeds the 2 MiB cap")

  raw_latin1 = "".join(res)
  try:
    decoded_utf8 = raw_latin1.encode("latin-1").decode("utf-8")
  except Exception:
    decoded_utf8 = raw_latin1
  return urllib.parse.unquote(decoded_utf8)


async def _fetch_snapsave_instagram_slides(
    session: aiohttp.ClientSession, clean_ig_url: str, is_reel_url: bool
) -> List[Tuple[str, str]]:
  """
  Race SnapSave / SaveIG endpoints concurrently (instead of sequentially!) and return an ordered list
  of `("video" | "image", url)` for all slides in an Instagram Reel or Carousel Post.
  Deduplicates multi-resolution buttons within the same slide box so each carousel slide appears once.
  """
  import json as json_mod

  async def _query_one_endpoint(action_ep: str) -> List[Tuple[str, str]]:
    slides_found: List[Tuple[str, str]] = []
    seen_keys: Set[str] = set()
    try:
      is_snapsave_php = "action.php" in action_ep
      form_data = {"url": clean_ig_url} if is_snapsave_php else {"q": clean_ig_url, "t": "media", "lang": "en"}
      origin_host = (
          "https://snapsave.app"
          if is_snapsave_php
          else ("https://snapsave.io" if "snapsave.io" in action_ep else "https://saveig.app")
      )
      headers = {
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
          "Origin": origin_host,
          "Referer": f"{origin_host}/",
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
          "X-Requested-With": "XMLHttpRequest",
      }
      async with session.post(
          action_ep,
          data=form_data,
          headers=headers,
          timeout=aiohttp.ClientTimeout(total=5.5),
      ) as resp:
        if resp.status != 200:
          return []
        body_bytes = await read_bounded_stream(resp, max_bytes=2 * 1024 * 1024)
        if not body_bytes:
          return []
        body_txt = body_bytes.decode("utf-8", "replace")
        decoded_html = body_txt
        eval_m = re.search(
            r'\(\s*"([^"]+)"\s*,\s*(\d+)\s*,\s*"([^"]+)"\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
            body_txt,
        )
        if eval_m:
          try:
            decoded_html = _decode_snapsave_eval(
                eval_m.group(1),
                int(eval_m.group(2)),
                eval_m.group(3),
                int(eval_m.group(4)),
                int(eval_m.group(5)),
            )
          except ValueError:
            # Malformed or oversized payload: fail closed instead of parsing the envelope.
            return []
        elif body_txt.lstrip().startswith("{"):
          try:
            j_obj = json_mod.loads(body_txt)
            decoded_html = str(j_obj.get("data") or "")
          except Exception:
            pass

        decoded_html = decoded_html.replace(r'\"', '"').replace(r"\/", "/")

        # Split by download-items__btn or media card if present so we pick 1 best link per carousel item
        blocks = re.split(r'class="[^"]*download-items__', decoded_html)
        search_chunks = blocks[1:] if len(blocks) > 1 else [decoded_html]

        for chunk in search_chunks:
          for a_m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.IGNORECASE | re.DOTALL):
            href = _unescape_ig_url(a_m.group(1))
            inner = a_m.group(2).lower()
            if not href.startswith("http") or "play.google.com" in href or "apps.apple.com" in href:
              continue
            is_vid_link = ("video" in inner) or (".mp4" in href.lower()) or ("icon-dlvideo" in chunk and is_reel_url)
            dedup_key = href.split("?")[0]
            tok_m = re.search(r"token=([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)", href)
            if tok_m:
              try:
                b64_part = tok_m.group(1).split(".")[1]
                b64_part += "=" * ((4 - len(b64_part) % 4) % 4)
                jwt_json = json_mod.loads(base64.urlsafe_b64decode(b64_part).decode("utf-8", errors="ignore"))
                inner_u = str(jwt_json.get("url") or "")
                inner_fn = str(jwt_json.get("filename") or "").lower()
                if inner_u:
                  dedup_key = inner_u.split("?")[0]
                if ".mp4" in inner_u.lower() or inner_fn.endswith(".mp4"):
                  is_vid_link = True
                elif any(ext in inner_u.lower() or inner_fn.endswith(ext) for ext in (".jpg", ".jpeg", ".webp", ".png")):
                  is_vid_link = False
              except Exception:
                pass
            if dedup_key not in seen_keys:
              seen_keys.add(dedup_key)
              slides_found.append(("video" if is_vid_link else "image", href))
              if len(blocks) > 1:
                # Pick only the highest quality link (first button) for this carousel card
                break
    except Exception:
      pass
    return slides_found

  results = await asyncio.gather(
      _query_one_endpoint("https://snapsave.app/action.php?lang=en"),
      _query_one_endpoint("https://snapsave.io/api/ajaxSearch"),
      _query_one_endpoint("https://saveig.app/api/ajaxSearch"),
      return_exceptions=True,
  )
  best_slides: List[Tuple[str, str]] = []
  for r in results:
    if isinstance(r, list) and len(r) > len(best_slides):
      best_slides = r
  return best_slides


def _extract_single_ig_node_media(node: Dict[str, Any]) -> Optional[Tuple[str, str]]:
  """Extract the single best ('video' | 'image', url) from one Instagram media or sidecar child node."""
  if not isinstance(node, dict):
    return None
  is_vid = node.get("is_video")
  m_type = node.get("media_type")
  v_u = node.get("video_url")
  if isinstance(v_u, str) and v_u.startswith("http"):
    return ("video", _unescape_ig_url(v_u))
  v_vers = node.get("video_versions")
  if isinstance(v_vers, list) and v_vers:
    first_v = v_vers[0]
    if isinstance(first_v, dict) and isinstance(first_v.get("url"), str) and first_v["url"].startswith("http"):
      return ("video", _unescape_ig_url(first_v["url"]))

  if is_vid is True or m_type == 2:
    return None

  # Photo node: prefer display_resources[-1]['src'] -> display_url -> image_versions2.candidates[0]['url']
  d_res = node.get("display_resources")
  if isinstance(d_res, list) and d_res:
    last_r = d_res[-1]
    if isinstance(last_r, dict) and isinstance(last_r.get("src"), str) and last_r["src"].startswith("http"):
      u_clean = _unescape_ig_url(last_r["src"])
      if not any(av in u_clean for av in ("s150x150", "s320x320", "p150x150")):
        return ("image", u_clean)

  d_u = node.get("display_url") or node.get("display_src")
  if isinstance(d_u, str) and d_u.startswith("http"):
    u_clean = _unescape_ig_url(d_u)
    if not any(av in u_clean for av in ("s150x150", "s320x320", "p150x150")):
      return ("image", u_clean)

  img_v2 = node.get("image_versions2")
  if isinstance(img_v2, dict):
    cands = img_v2.get("candidates")
    if isinstance(cands, list) and cands:
      best_img = cands[0]
      if isinstance(best_img, dict) and isinstance(best_img.get("url"), str) and best_img["url"].startswith("http"):
        u_clean = _unescape_ig_url(best_img["url"])
        if not any(av in u_clean for av in ("s150x150", "s320x320", "p150x150")):
          return ("image", u_clean)
  return None


def _collect_ig_slides_from_json_obj(
    obj: Any,
    slides: List[Tuple[str, str]],
    seen_urls: Set[str],
    _depth: int = 0,
    _max_depth: int = 32,
):
  """
  Walk Instagram GraphQL / contextJSON / xig_polaris_media objects.
  If a carousel container (`edge_sidecar_to_children` or `carousel_media`) is found,
  collects ALL child slides in exact order and returns without recursing into duplicate thumbnail trees.
  """
  if _depth > _max_depth:
    return
  if isinstance(obj, dict):
    sidecar = obj.get("edge_sidecar_to_children")
    if isinstance(sidecar, dict) and isinstance(sidecar.get("edges"), list) and sidecar["edges"]:
      for edge in sidecar["edges"]:
        child_node = edge.get("node") if isinstance(edge, dict) else None
        if isinstance(child_node, dict):
          item = _extract_single_ig_node_media(child_node)
          if item and item[1].split("?")[0] not in seen_urls:
            seen_urls.add(item[1].split("?")[0])
            slides.append(item)
      return

    c_media = obj.get("carousel_media")
    if isinstance(c_media, list) and c_media:
      for child_node in c_media:
        if isinstance(child_node, dict):
          item = _extract_single_ig_node_media(child_node)
          if item and item[1].split("?")[0] not in seen_urls:
            seen_urls.add(item[1].split("?")[0])
            slides.append(item)
      return

    # Check if this dict itself is a top-level media node (has shortcode or code or video_versions/display_url)
    if any(k in obj for k in ("shortcode", "code", "video_url", "video_versions")) and not any(
        k in obj for k in ("edge_sidecar_to_children", "carousel_media")
    ):
      item = _extract_single_ig_node_media(obj)
      if item and item[1].split("?")[0] not in seen_urls:
        seen_urls.add(item[1].split("?")[0])
        slides.append(item)
        return

    for k, val in obj.items():
      if k in (
          "owner", "user", "comment", "edge_media_to_comment", "edge_media_preview_comment",
          "caption", "edge_web_media_to_related_media", "edge_owner_to_timeline_media",
          "thumbnail_resources", "thumbnail_src",
      ):
        continue
      _collect_ig_slides_from_json_obj(val, slides, seen_urls, _depth + 1, _max_depth)
  elif isinstance(obj, list):
    for elem in obj:
      _collect_ig_slides_from_json_obj(elem, slides, seen_urls, _depth + 1, _max_depth)


async def _fetch_ig_embed_and_graphql_slides(
    session: aiohttp.ClientSession, shortcode: str, is_reel_url: bool
) -> List[Tuple[str, str]]:
  """
  Extract all slides (single Reel, single Photo, or multi-slide Carousel) from:
  1. Instagram `/p/{shortcode}/embed/captioned/` (`contextJSON` + `<script data-sjs>` + HTML tags)
  2. Instagram Public GraphQL API (`doc_id`)
  """
  import json as json_mod
  slides: List[Tuple[str, str]] = []
  seen_urls: Set[str] = set()

  embed_u = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
  try:
    async with session.get(
        embed_u,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=aiohttp.ClientTimeout(total=5.5),
    ) as resp:
      if resp.status == 200:
        _html_bytes = await read_bounded_stream(resp, max_bytes=3 * 1024 * 1024)
        html_txt = _html_bytes.decode("utf-8", "replace") if _html_bytes else ""

        # 1A. Parse contextJSON string inside /embed/captioned/ (contains full edge_sidecar_to_children for carousels!)
        ctx_m = re.search(r'"contextJSON"\s*:\s*("(?:\\.|[^"\\])*")', html_txt)
        if ctx_m:
          try:
            ctx_raw_str = json_mod.loads(ctx_m.group(1))
            ctx_obj = json_mod.loads(ctx_raw_str)
            _collect_ig_slides_from_json_obj(ctx_obj, slides, seen_urls)
          except Exception:
            pass

        # 1B. Parse <script type="application/json" data-sjs> blocks
        if not slides:
          for sjs_m in re.finditer(r"<script[^>]*data-sjs[^>]*>(.*?)</script>", html_txt, re.DOTALL):
            sjs_body = sjs_m.group(1)
            if any(k in sjs_body for k in ("xig_polaris_media", "xdt_shortcode_media", "edge_sidecar_to_children", "carousel_media", "video_versions", "display_url")):
              try:
                sjs_json = json_mod.loads(sjs_body)
                _collect_ig_slides_from_json_obj(sjs_json, slides, seen_urls)
              except Exception:
                pass

        # 1C. Fallback to unescaped HTML regex if JSON blocks were stripped
        if not slides:
          unesc_txt = html_txt.replace(r'\\"', '"').replace(r'\"', '"').replace(r"\\/", "/").replace(r"\/", "/")
          for vpat in (
              r'"video_url"\s*:\s*"(https?:[^"]+)"',
              r'property="og:video(?::secure_url)?"\s+content="(https?:[^"]+)"',
              r'<video[^>]+src="(https?:[^"]+)"',
          ):
            for vm in re.finditer(vpat, unesc_txt, re.IGNORECASE):
              vu = _unescape_ig_url(vm.group(1))
              if vu.startswith("http") and vu.split("?")[0] not in seen_urls:
                seen_urls.add(vu.split("?")[0])
                slides.append(("video", vu))

          if not slides and not is_reel_url:
            for ipat in (
                r'"display_url"\s*:\s*"(https?:[^"]+)"',
                r'<img[^>]+class="[^"]*EmbeddedMediaImage[^"]*"[^>]+src="([^"]+)"',
                r'<img[^>]+src="([^"]+)"[^>]+class="[^"]*EmbeddedMediaImage[^"]*"',
            ):
              for im in re.finditer(ipat, unesc_txt, re.IGNORECASE):
                iu = _unescape_ig_url(im.group(1))
                if iu.startswith("http") and not any(av in iu for av in ("s150x150", "s320x320", "p150x150", "rsrc.php")):
                  if iu.split("?")[0] not in seen_urls:
                    seen_urls.add(iu.split("?")[0])
                    slides.append(("image", iu))
  except Exception:
    pass

  if slides:
    return slides

  # 2. Instagram Public GraphQL API fallback
  graphql_vars = json_mod.dumps({"shortcode": shortcode})
  encoded_vars = urllib.parse.quote(graphql_vars)
  for doc_id in ("8845758582119845", "24368985919464652", "10015901848480474"):
    gql_body = f"av=0&__d=www&__user=0&__a=1&__req=1&lsd=AVqbxe3J_YA&variables={encoded_vars}&doc_id={doc_id}"
    gql_headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "X-IG-App-ID": "936619743392459",
        "X-FB-LSD": "AVqbxe3J_YA",
        "X-ASBD-ID": "129477",
        "Origin": "https://www.instagram.com",
        "Referer": f"https://www.instagram.com/p/{shortcode}/",
    }
    try:
      async with session.post(
          "https://www.instagram.com/graphql/query",
          headers=gql_headers,
          data=gql_body,
          timeout=aiohttp.ClientTimeout(total=4.5),
      ) as gresp:
        if gresp.status == 200:
          _gql_bytes = await read_bounded_stream(gresp, max_bytes=2 * 1024 * 1024)
          gdata = json_mod.loads(_gql_bytes.decode("utf-8", "replace")) if _gql_bytes else None
          if isinstance(gdata, dict) and gdata.get("data"):
            _collect_ig_slides_from_json_obj(gdata["data"], slides, seen_urls)
            if slides:
              break
    except Exception:
      continue

  return slides


async def extract_instagram_media_items(
    clean_ig_url: str, max_bytes: int = 10 * 1024 * 1024
) -> Tuple[List[Tuple[bytes, str]], Optional[str], Optional[str]]:
  """
  Fast Parallel Instagram Reel & Multi-Photo Carousel Extractor:
  Returns: (list_of_(file_bytes, filename), fallback_embed_url, caption)
  - Races SnapSave/SaveIG and Instagram `/embed/captioned/` (`contextJSON`) + GraphQL concurrently!
  - Downloads ALL photos/videos in a carousel post (up to 15 slides) in parallel instead of stopping at the 1st photo!
  """
  shortcode_m = re.search(r"/(reel|reels|p|tv)/([A-Za-z0-9_\-]+)", clean_ig_url, re.IGNORECASE)
  url_kind = (shortcode_m.group(1).lower() if shortcode_m else "p")
  shortcode = shortcode_m.group(2) if shortcode_m else None
  if shortcode:
    try:
      validate_ig_shortcode(shortcode)
    except ValueError:
      shortcode = None
  is_reel_url = url_kind in ("reel", "reels", "tv")
  session = await get_shared_http_session()

  slides: List[Tuple[str, str]] = []
  ss_list: List[Tuple[str, str]] = []
  em_list: List[Tuple[str, str]] = []
  if shortcode:
    # Wave 1: Run SnapSave/SaveIG and Embed/GraphQL in parallel (cuts latency from 25s -> ~2s!)
    ss_task = asyncio.create_task(_fetch_snapsave_instagram_slides(session, clean_ig_url, is_reel_url))
    em_task = asyncio.create_task(_fetch_ig_embed_and_graphql_slides(session, shortcode, is_reel_url))
    ss_slides, em_slides = await asyncio.gather(ss_task, em_task, return_exceptions=True)
    ss_list = ss_slides if isinstance(ss_slides, list) else []
    em_list = em_slides if isinstance(em_slides, list) else []

    # Prefer whichever source returned more carousel items, or prefer SnapSave if equal (signed CDN bypasses IP blocks)
    if len(em_list) > len(ss_list):
      slides = em_list + [s for s in ss_list if s not in em_list]
    elif ss_list:
      slides = ss_list
    else:
      slides = em_list

  # Wave 2: Multi-Host OGP & Direct Proxy Scrapers (kkinstagram, instagramez, vxinstagram, ddinstagram)
  if shortcode and not slides:
    async def _probe_ig_proxy(proxy_host: str) -> List[Tuple[str, str]]:
      p_slides: List[Tuple[str, str]] = []
      proxy_url = f"https://{proxy_host}/{'reel' if is_reel_url else 'p'}/{shortcode}/"
      try:
        final_url, status, ctype, body = await safe_fetch_response(
            proxy_url,
            allowed_domains=("kkinstagram.com", "instagramez.com", "vxinstagram.com", "ddinstagram.com"),
            max_bytes=2 * 1024 * 1024,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)"},
            session=session,
        )
        if status != 200:
          return []
        if "video/" in ctype or "image/" in ctype:
          return [("video" if "video/" in ctype else "image", final_url)]
        phtml = (body or b"").decode("utf-8", "replace")
        if "Login • Instagram" in phtml or "accounts/login" in final_url or "Due to a legal request" in phtml:
          return []
        for og_vpat in (
            r'<meta[^>]+property="og:video(?::secure_url)?"[^>]+content="([^"]+)"',
            r'<meta[^>]+content="([^"]+)"[^>]+property="og:video(?::secure_url)?"',
        ):
          for om in re.finditer(og_vpat, phtml, re.IGNORECASE):
            vlink = _unescape_ig_url(om.group(1))
            if vlink.startswith("http") and ("video", vlink) not in p_slides:
              p_slides.append(("video", vlink))
        if not is_reel_url:
          for og_ipat in (
              r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
              r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"',
          ):
            for im in re.finditer(og_ipat, phtml, re.IGNORECASE):
              ilink = _unescape_ig_url(im.group(1))
              if ilink.startswith("http") and not any(av in ilink for av in ("s150x150", "rsrc.php")):
                if ("image", ilink) not in p_slides:
                  p_slides.append(("image", ilink))
      except Exception:
        pass
      return p_slides

    proxy_results = await asyncio.gather(
        *(
            _probe_ig_proxy(h)
            for h in ("kkinstagram.com", "instagramez.com", "www.vxinstagram.com", "www.ddinstagram.com")
        ),
        return_exceptions=True,
    )
    for pr in proxy_results:
      if isinstance(pr, list) and len(pr) > len(slides):
        slides = pr

  # Download all discovered slides in parallel (up to 15 slides)
  dl_sem = asyncio.Semaphore(4)
  # One shared ceiling for every download in this job, including the repair passes:
  # the old shape finished `asyncio.gather` first and only then trimmed the result, so
  # twenty 25 MiB slides were all held in RAM before the filter ran (C-007).
  job_budget = SharedByteBudget(MAX_JOB_BYTES)

  async def _download_slide(idx: int, kind: str, media_u: str) -> Optional[Tuple[int, bytes, str]]:
    if job_budget.remaining <= 0:
      return None  # the job budget is exhausted: do not start another download
    async with dl_sem:
      try:
        _final, status, m_ctype, raw_bytes = await safe_fetch_response(
            media_u,
            max_bytes=max_bytes,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Referer": "https://www.instagram.com/"},
            session=session,
            budget=job_budget,
        )
        if status != 200 or len(raw_bytes or b"") < 500:
          job_budget.release(len(raw_bytes or b""))
          return None
        if "text/html" in m_ctype or "application/json" in m_ctype:
          job_budget.release(len(raw_bytes))
          return None
        if kind == "video" or "video/" in m_ctype:
          if not _is_valid_mp4_video_bytes(raw_bytes, m_ctype):
            # If a photo slide was mislabeled as video, check if it is actually a valid image
            if not is_reel_url:
              norm_img = await _normalize_image_bytes(raw_bytes)
              if norm_img:
                return (idx, norm_img, f"ig_{idx}.jpg")
            job_budget.release(len(raw_bytes))
            return None
          clean_vid = await _ensure_discord_playable_mp4(raw_bytes, max_bytes=max_bytes)
          return (idx, clean_vid, f"ig_{idx}.mp4")
        else:
          norm_img = await _normalize_image_bytes(raw_bytes)
          if not norm_img:
            job_budget.release(len(raw_bytes))
            return None
          ext = "png" if norm_img.startswith(b"\x89PNG") else "jpg"
          return (idx, norm_img, f"ig_{idx}.{ext}")
      except Exception:
        return None

  downloaded_files: List[Tuple[bytes, str]] = []
  if slides:
    # If it is a strict /reel/ URL, only download video slides so cover thumbnails are never sent alongside the reel
    filtered_slides = [s for s in slides if s[0] == "video"] if is_reel_url else slides
    if not filtered_slides:
      filtered_slides = slides
    # 20 is Instagram's own carousel ceiling; the old 15 silently truncated longer posts.
    filtered_slides = filtered_slides[:20]
    discovered = len(filtered_slides)
    tried_urls = {u for _k, u in filtered_slides}
    tasks_dl = [
        _download_slide(i, k, u)
        for i, (k, u) in enumerate(filtered_slides, start=1)
    ]
    dl_results = await asyncio.gather(*tasks_dl, return_exceptions=True)
    valid_items = [r for r in dl_results if isinstance(r, tuple) and len(r) == 3]
    valid_items.sort(key=lambda x: x[0])
    # Deduplicate identical byte payloads (two CDN URLs can point at the same slide). A stale
    # mirror answers every slide of one media type with the same placeholder, which collapses
    # here, so the dropped indices are remembered and repaired instead of posting a short
    # carousel with no trace in the journal.
    seen_hashes: Set[str] = set()
    kept, duplicate_bytes, missing = _dedupe_downloaded_slides(valid_items, seen_hashes)
    # Drop every remaining reference to the discarded payloads *before* releasing their
    # claims: the gather result and the valid-item list keep duplicates alive, and a
    # repair that claims the released budget would push real peak RAM past the ceiling.
    valid_items.clear()
    dl_results.clear()
    job_budget.release(duplicate_bytes)
    kept_indices = {i for i, _b, _f in kept}
    missing = sorted(set(missing) | {i for i in range(1, discovered + 1) if i not in kept_indices})

    if missing:
      async def _repair_from(candidate: List[Tuple[str, str]]) -> None:
        """Re-download only the still-missing indices from one other source's list.

        Same shape as the TikTok photo repair: a positional retry needs a list of the
        same length, URLs already pulled are skipped (they hand back the same placeholder),
        and a payload that duplicates one we hold is rejected, so the index stays missing
        and the next source gets a turn instead of the loss being accepted.
        """
        if not isinstance(candidate, list) or len(candidate) != discovered:
          return
        pending = [(i, candidate[i - 1][0], candidate[i - 1][1]) for i in list(missing) if 1 <= i <= len(candidate)]
        pending = [p for p in pending if p[2] not in tried_urls]
        if not pending:
          return
        for r in await asyncio.gather(*(_download_slide(i, k, u) for i, k, u in pending), return_exceptions=True):
          if not (isinstance(r, tuple) and len(r) == 3) or r[0] not in missing:
            continue
          h = hashlib.md5(r[1]).hexdigest()
          if h in seen_hashes:
            continue
          seen_hashes.add(h)
          kept.append((r[0], r[1], r[2]))
          tried_urls.add(r[2])
          missing.remove(r[0])

      # 1. A Wave-1 list we did not download from is already in hand: free repair.
      for alt in (em_list, ss_list):
        if not missing:
          break
        await _repair_from(alt)

      # 2. One fresh re-quote from the network (bounded), for mirrors that re-sign their
      #    tokens per request. Only reached when nothing in hand covered the gap.
      if missing:
        async def _no_embed() -> List[Tuple[str, str]]:
          return []

        async def _requote() -> List[Tuple[str, str]]:
          a, b = await asyncio.gather(
              _fetch_snapsave_instagram_slides(session, clean_ig_url, is_reel_url),
              _fetch_ig_embed_and_graphql_slides(session, shortcode, is_reel_url) if shortcode else _no_embed(),
              return_exceptions=True,
          )
          fresh = [x for x in (a, b) if isinstance(x, list) and len(x) == discovered]
          fresh.sort(key=lambda lst: sum(1 for _k, u in lst if u not in tried_urls), reverse=True)
          return fresh[0] if fresh else []

        await asyncio.sleep(1.0)  # a placeholder-serving mirror needs the second ask to be a new request
        try:
          fresh_list = await asyncio.wait_for(_requote(), timeout=8.0)
        except Exception:
          fresh_list = []
        if missing and fresh_list:
          await _repair_from(fresh_list)

    kept.sort(key=lambda x: x[0])
    kept, over_budget = _fit_byte_budget(kept)
    if over_budget:
        logger.info(
            "gallery-budget platform=instagram dropped=%d kept=%d budget_mb=%d url=%s",
            over_budget, len(kept), MAX_JOB_BYTES // (1024 * 1024), clean_ig_url,
        )
    downloaded_files = [(b, f) for _i, b, f in kept]
    if discovered and len(downloaded_files) < discovered:
      # Never degrade silently: journalctl -u angelbot has to show the loss.
      logger.info(
          "gallery-shortfall platform=instagram discovered=%d delivered=%d url=%s",
          discovered, len(downloaded_files), clean_ig_url,
      )

  if downloaded_files:
    _safe_gc_collect()
    has_video = any(fn.endswith(".mp4") for _, fn in downloaded_files)
    if is_reel_url or (len(downloaded_files) == 1 and has_video):
      cap = "🎬 **Instagram Reel**"
    elif len(downloaded_files) > 1:
      cap = f"📸 **Instagram Post ({len(downloaded_files)})**"
    else:
      cap = "📸 **Instagram Post**"
    return downloaded_files, None, cap

  # Fallback embed link if media exceeded size limit or required login
  fallback_u = re.sub(
      r"(?:www\.|m\.)?(?:instagram\.com|instagr\.am)",
      "www.kkinstagram.com",
      clean_ig_url,
      flags=re.IGNORECASE,
  )
  return [], fallback_u, None


async def extract_instagram_media(
    clean_ig_url: str,
) -> Tuple[Optional[bytes], Optional[str], str]:
  """Backward-compatible single-item wrapper around extract_instagram_media_items."""
  files, _, cap = await extract_instagram_media_items(clean_ig_url)
  if files:
    return files[0][0], cap, files[0][1]
  return None, None, "video.mp4"


async def extract_instagram_direct_mp4(clean_ig_url: str) -> Tuple[Optional[bytes], Optional[str]]:
  """Backward-compatible wrapper returning (media_bytes, caption)."""
  media_bytes, cap, _ = await extract_instagram_media(clean_ig_url)
  return media_bytes, cap


async def extract_tiktok_media_items(
    resolved_url: str, max_bytes: int = 10 * 1024 * 1024
) -> Tuple[List[Tuple[bytes, str]], Optional[str], Optional[str]]:
  """
  TikTok video and photo slideshow extraction, in order:
  1. TikWM API, paced against its rate limit and retried once; handles `vdata['images']` photo
     slideshows, and validates the payload is real MP4 so background audio is never posted as video.
  2. Tiklydown API and the tnktok / tfxktok OGP scrape.
  3. Local yt-dlp H.264 fallback.
  4. The tfxktok embed URL, replacing the dead vxtiktok one.
  """
  global _LAST_TIKWM_CALL_AT
  session = await get_shared_http_session()
  timeout = aiohttp.ClientTimeout(total=14)
  dl_sem = asyncio.Semaphore(2)  # TikTok's photo CDN answers 403 to bursts above ~2 concurrent
  # Shared ceiling for every media download in this job, including photo retries: claims
  # are taken per chunk, so concurrent downloads cannot retain more than the ceiling (C-007).
  job_budget = SharedByteBudget(MAX_JOB_BYTES)

  async def _download_photo_list(img_urls: List[str], requote=None) -> List[Tuple[bytes, str]]:
    async def _dl_one_img(idx: int, u: str) -> Optional[Tuple[int, bytes, str]]:
      if job_budget.remaining <= 0:
        return None  # job budget exhausted: do not start another download
      async with dl_sem:
        try:
          _final, istatus, _ict, raw = await safe_fetch_response(
              u,
              max_bytes=max_bytes,
              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Referer": "https://www.tiktok.com/"},
              session=session,
              budget=job_budget,
          )
          if istatus != 200 or not raw or len(raw) < 400:
            job_budget.release(len(raw or b""))
            return None
          norm = await _normalize_image_bytes(raw)
          if norm:
            ext = "png" if norm.startswith(b"\x89PNG") else "jpg"
            return (idx, norm, f"tiktok_{idx}.{ext}")
          job_budget.release(len(raw))
        except Exception:
          pass
        return None

    # Cap slides and total RAM: a 35-photo post buffered in memory can OOM a 1 GB host.
    urls = img_urls[:10]
    res_list = await asyncio.gather(*(_dl_one_img(i, u) for i, u in enumerate(urls, start=1)), return_exceptions=True)
    got: Dict[int, Tuple[bytes, str]] = {r[0]: (r[1], r[2]) for r in res_list if isinstance(r, tuple) and len(r) == 3}
    total_bytes = sum(len(b) for b, _ in got.values())
    for idx in list(got):
      if total_bytes <= 25 * 1024 * 1024:
        break
      total_bytes -= len(got[idx][0])
      job_budget.release(len(got[idx][0]))
      got.pop(idx)
    if requote and len(got) < len(urls):
      # TikTok signs every slide to one CDN node and sometimes refuses the node TikWM
      # quoted (403, same URL forever); a fresh quote re-signs, so retry only the
      # missing slides instead of posting a partial carousel.
      await asyncio.sleep(1.0)
      fresh = [u for u in (await requote() or []) if isinstance(u, str) and u.startswith("http")][:10]
      if len(fresh) == len(urls):
        missing = [(i, fresh[i - 1]) for i in range(1, len(urls) + 1) if i not in got]

        async def _retry_slide(pos: int, idx: int, u: str):
          await asyncio.sleep(0.25 * pos)  # a second burst gets refused the same way
          return await _dl_one_img(idx, u)

        for r in await asyncio.gather(*(_retry_slide(p, i, u) for p, (i, u) in enumerate(missing)), return_exceptions=True):
          if isinstance(r, tuple) and len(r) == 3:
            got[r[0]] = (r[1], r[2])
    seen_h: Set[str] = set()
    out_files: List[Tuple[bytes, str]] = []
    for idx in sorted(got):
      b_data, fn = got[idx]
      h = hashlib.md5(b_data).hexdigest()
      if h not in seen_h:
        seen_h.add(h)
        out_files.append((b_data, fn))
      else:
        job_budget.release(len(b_data))  # duplicate payload discarded
    return out_files

  async def _tikwm_quote() -> Dict[str, Any]:
    """One TikWM API answer (rate-limit paced + one retry).

    Hoisted out of Engine 1 so an incomplete photo download can ask for a fresh quote:
    TikTok signs each slide to a CDN node, and TikWM sometimes hands back a node that
    answers 403 for that object.
    """
    global _LAST_TIKWM_CALL_AT
    for attempt in range(2):
      try:
        async with _TIKWM_LOCK:
          elapsed = time.monotonic() - _LAST_TIKWM_CALL_AT
          if elapsed < 1.05:
            await asyncio.sleep(1.05 - elapsed)
          _LAST_TIKWM_CALL_AT = time.monotonic()
        api_url = f"https://www.tikwm.com/api/?url={urllib.parse.quote(resolved_url)}&hd=0"
        async with session.get(api_url, headers={"User-Agent": "Mozilla/5.0 AngelBot/10.0"}, timeout=aiohttp.ClientTimeout(total=8)) as resp:
          if resp.status == 200:
            _raw = await read_bounded_stream(resp, max_bytes=2 * 1024 * 1024)
            data = json.loads(_raw.decode("utf-8", "replace")) if _raw else None
            if isinstance(data, dict) and data.get("code") == 0 and isinstance(data.get("data"), dict):
              return data["data"]
        if attempt == 0:
          await asyncio.sleep(1.1)
      except Exception:
        if attempt == 0:
          await asyncio.sleep(0.8)
    return {}

  # Engine 1: TikWM API (with 1.05s rate-limit guard + automatic retry)
  vdata = await _tikwm_quote()

  if vdata:
    title = (vdata.get("title") or "").strip()[:180]
    author_name = (vdata.get("author") or {}).get("nickname") or (vdata.get("author") or {}).get("unique_id") or "TikTok"
    images_list = vdata.get("images")
    # 1A. TikTok Photo / Slideshow Post!
    if isinstance(images_list, list) and images_list:
      photo_urls = [u for u in images_list if isinstance(u, str) and u.startswith("http")]
      if photo_urls:

        async def _fresh_photo_urls():
          return (await _tikwm_quote()).get("images")

        photo_files = await _download_photo_list(photo_urls, requote=_fresh_photo_urls)
        if photo_files:
          _safe_gc_collect()
          cap = f"📸 **{author_name}**" + (f" — {title}" if title else "")
          return photo_files, None, cap

    # 1B. TikTok video post. Never save an MP3 audio URL as video.mp4.
    else:
      for v_key in ("play", "wmplay", "hdplay"):
        play_url = vdata.get(v_key)
        if not isinstance(play_url, str) or not play_url.startswith("http"):
          continue
        if play_url.lower().split("?")[0].endswith(".mp3"):
          continue
        try:
          _final, v_status, v_ctype, video_bytes = await safe_fetch_response(
              play_url,
              max_bytes=max_bytes,
              headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.tikwm.com/"},
              session=session,
              budget=job_budget,
          )
          if v_status == 200 and video_bytes and len(video_bytes) >= 4096:
            if _is_valid_mp4_video_bytes(video_bytes, v_ctype):
              clean_vid = await _ensure_discord_playable_mp4(video_bytes, max_bytes=max_bytes)
              _safe_gc_collect()
              cap = f"🎬 **{author_name}**" + (f" — {title}" if title else "")
              return [(clean_vid, "video.mp4")], None, cap
          job_budget.release(len(video_bytes or b""))
        except Exception:
          continue

  # Engine 2: Tiklydown API + tnktok.com / tfxktok.com OGP Scraper
  for tikly_ep in (
      f"https://api.tiklydown.eu.org/api/download?url={urllib.parse.quote(resolved_url)}",
      f"https://api.tiklydown.eu.org/api/download/v3?url={urllib.parse.quote(resolved_url)}",
  ):
    try:
      async with session.get(tikly_ep, headers={"User-Agent": "Mozilla/5.0"}, timeout=aiohttp.ClientTimeout(total=6.5)) as tresp:
        if tresp.status == 200:
          _t_bytes = await read_bounded_stream(tresp, max_bytes=2 * 1024 * 1024)
          tdata = json.loads(_t_bytes.decode("utf-8", "replace")) if _t_bytes else None
          if isinstance(tdata, dict):
            res_obj = tdata.get("result") if isinstance(tdata.get("result"), dict) else tdata
            t_title = (res_obj.get("title") or res_obj.get("desc") or "").strip()[:180]
            t_author = (res_obj.get("author") or {}).get("name") or (res_obj.get("author") or {}).get("nickname") or "TikTok"
            t_imgs = res_obj.get("images")
            if isinstance(t_imgs, list) and t_imgs:
              p_urls = [
                  (im.get("url") if isinstance(im, dict) else im)
                  for im in t_imgs
                  if isinstance(im, (str, dict))
              ]
              p_urls = [u for u in p_urls if isinstance(u, str) and u.startswith("http")]
              if p_urls:
                photo_files = await _download_photo_list(p_urls)
                if photo_files:
                  _safe_gc_collect()
                  cap = f"📸 **{t_author}**" + (f" — {t_title}" if t_title else "")
                  return photo_files, None, cap

            vid_obj = res_obj.get("video") or {}
            v_cand = (
                (vid_obj.get("noWatermark") if isinstance(vid_obj, dict) else None)
                or (vid_obj.get("watermark") if isinstance(vid_obj, dict) else None)
                or (res_obj.get("video") if isinstance(res_obj.get("video"), str) else None)
            )
            if isinstance(v_cand, str) and v_cand.startswith("http"):
              _final, v_status, v_ctype, v_bytes = await safe_fetch_response(
                  v_cand,
                  headers={"User-Agent": "Mozilla/5.0"},
                  max_bytes=max_bytes,
                  budget=job_budget,
                  timeout=timeout,
              )
              if v_status == 200 and v_bytes and len(v_bytes) >= 4096:
                if _is_valid_mp4_video_bytes(v_bytes, (v_ctype or "").lower()):
                  clean_vid = await _ensure_discord_playable_mp4(v_bytes, max_bytes=max_bytes)
                  _safe_gc_collect()
                  cap = f"🎬 **{t_author}**" + (f" — {t_title}" if t_title else "")
                  return [(clean_vid, "video.mp4")], None, cap
                job_budget.release(len(v_bytes or b""))
              elif v_bytes:
                job_budget.release(len(v_bytes))
    except Exception:
      continue

  # Engine 2B: Scrape tnktok.com / tfxktok.com OGP meta tags
  is_photo_url = "/photo/" in resolved_url.lower()
  for proxy_dom in ("www.tfxktok.com", "a.tnktok.com", "tnktok.com"):
    proxy_u = re.sub(r"(?:www\.|vm\.|vt\.|m\.|lite\.)?tiktok\.com", proxy_dom, resolved_url, flags=re.IGNORECASE)
    try:
      _final_p, p_status, p_ct, p_body = await safe_fetch_response(
          proxy_u,
          allowed_domains=("tfxktok.com", "tnktok.com"),
          max_bytes=max_bytes,
          headers={"User-Agent": "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)"},
          session=session,
          budget=job_budget,
      )
      if p_status == 200:
          if "video/" in p_ct:
            v_bytes = p_body
            if _is_valid_mp4_video_bytes(v_bytes, p_ct):
              clean_vid = await _ensure_discord_playable_mp4(v_bytes, max_bytes=max_bytes)
              return [(clean_vid, "video.mp4")], None, "🎬 **TikTok**"
            job_budget.release(len(v_bytes or b""))
          phtml = (p_body or b"").decode("utf-8", "replace")
          if p_body:
            # An HTML page is parsed and dropped: give its claim back for the media
            # download the tags below will trigger.
            job_budget.release(len(p_body))
          phtml = (p_body or b"").decode("utf-8", "replace")
          if "Due to a legal request" in phtml:
            continue
          if not is_photo_url:
            for og_vpat in (
                r'<meta[^>]+property="og:video(?::secure_url)?"[^>]+content="([^"]+)"',
                r'<meta[^>]+content="([^"]+)"[^>]+property="og:video(?::secure_url)?"',
            ):
              vm = re.search(og_vpat, phtml, re.IGNORECASE)
              if vm:
                vu = html_lib.unescape(vm.group(1)).strip()
                if vu.startswith("http"):
                  _dv_final, dv_status, dv_ct, v_bytes = await safe_fetch_response(
                      vu, max_bytes=max_bytes,
                      headers={"User-Agent": "Mozilla/5.0"}, session=session, budget=job_budget)
                  if dv_status == 200 and _is_valid_mp4_video_bytes(v_bytes, dv_ct):
                    clean_vid = await _ensure_discord_playable_mp4(v_bytes, max_bytes=max_bytes)
                    return [(clean_vid, "video.mp4")], None, "🎬 **TikTok**"
                  job_budget.release(len(v_bytes or b""))
          # Check og:image tags for TikTok photo posts
          og_imgs: List[str] = []
          for og_ipat in (
              r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
              r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"',
          ):
            for im in re.finditer(og_ipat, phtml, re.IGNORECASE):
              iu = html_lib.unescape(im.group(1)).strip()
              if iu.startswith("http") and iu not in og_imgs:
                og_imgs.append(iu)
          if og_imgs and is_photo_url:
            photo_files = await _download_photo_list(og_imgs)
            if photo_files:
              return photo_files, None, "📸 **TikTok Photo**"
    except Exception:
      continue

  # Engine 3: Local yt-dlp fallback for TikTok videos (subprocess: killable on timeout)
  if yt_dlp is not None and not is_photo_url:
    try:
      info = await run_ytdlp_json(
          resolved_url, timeout=7.5,
          extra=["-f", "best[vcodec^=avc1][ext=mp4]/best[ext=mp4]/best"],
      )
      if isinstance(info, dict):
        v_u = info.get("url")
        v_hdrs = info.get("http_headers") or {}
        v_title = (info.get("title") or "").strip()[:140]
        if isinstance(v_u, str) and v_u.startswith("http"):
          _final, v_status, v_ctype, v_bytes = await safe_fetch_response(
              v_u,
              headers=v_hdrs,
              max_bytes=max_bytes,
              budget=job_budget,
              timeout=timeout,
          )
          if v_status == 200 and v_bytes and len(v_bytes) >= 4096:
            if _is_valid_mp4_video_bytes(v_bytes, v_ctype or ""):
              clean_vid = await _ensure_discord_playable_mp4(v_bytes, max_bytes=max_bytes)
              return [(clean_vid, "video.mp4")], None, "🎬 **TikTok**" + (f" — {v_title}" if v_title else "")
            job_budget.release(len(v_bytes or b""))
          elif v_bytes:
            job_budget.release(len(v_bytes))
    except Exception:
      pass

  # Engine 4: working fallback embed domain. tfxktok.com; vxtiktok.com was shut down.
  fixed = re.sub(
      r"(?:www\.|vm\.|vt\.|m\.|lite\.)?tiktok\.com",
      "www.tfxktok.com",
      resolved_url,
      flags=re.IGNORECASE,
  )
  return [], fixed, None


# 4b. X / Twitter resolver: every photo and video, not just a link.
_X_STATUS_RE = re.compile(r"/(?:status|statuses)/(\d+)", re.IGNORECASE)
_X_HANDLE_RE = re.compile(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/(?:status|statuses)/", re.IGNORECASE)


def _x_status_id(url: str) -> Optional[str]:
  m = _X_STATUS_RE.search(url or "")
  return m.group(1) if m else None


def _x_fallback_url(url: str) -> str:
  return re.sub(
      r"https?://(?:[a-z0-9]+\.)?(?:x|twitter)\.com",
      "https://fxtwitter.com",
      url or "",
      flags=re.IGNORECASE,
  )


async def _download_photo_slides(img_urls: List[str], max_bytes: int, prefix: str,
                                 referer: str = "",
                                 budget: Optional[SharedByteBudget] = None) -> List[Tuple[bytes, str]]:
  """Download every image in order and drop only the ones the CDN refuses.

  Same shape as the TikTok photo downloader (`_download_photo_list`) without the
  re-quote step: photo CDNs behind X do not rotate per-burst signatures.
  """
  sem = asyncio.Semaphore(4)
  img_urls = list(img_urls)[:10]
  session = await get_shared_http_session()

  async def _one(idx: int, target: str) -> Optional[Tuple[int, bytes, str]]:
    if budget is not None and budget.remaining <= 0:
      return None  # job budget exhausted: do not start another download
    async with sem:
      try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        if referer:
          headers["Referer"] = referer
        _final, status, _ctype, raw = await safe_fetch_response(
            target,
            headers=headers,
            max_bytes=max_bytes,
            budget=budget,
            session=session,
            timeout=aiohttp.ClientTimeout(total=12),
        )
        if status != 200 or not raw or len(raw) < 400:
          if budget is not None and raw:
            budget.release(len(raw))
          return None
        norm = await _normalize_image_bytes(raw)
        if norm:
          ext = "png" if norm.startswith(b"\x89PNG") else "jpg"
          return (idx, norm, f"{prefix}_{idx}.{ext}")
        if budget is not None:
          budget.release(len(raw or b""))
      except Exception:
        pass
      return None

  gathered = await asyncio.gather(*(_one(i, u) for i, u in enumerate(img_urls, start=1)), return_exceptions=True)
  ordered = sorted((g for g in gathered if isinstance(g, tuple)), key=lambda t: t[0])
  return [(body, name) for _idx, body, name in ordered]


async def _download_one_video(video_url: str, headers: Dict[str, str], max_bytes: int,
                              name: str = "video.mp4",
                              budget: Optional[SharedByteBudget] = None) -> Optional[Tuple[bytes, str]]:
  session = await get_shared_http_session()
  try:
    _final, status, ctype, body = await safe_fetch_response(
        video_url,
        headers=headers,
        max_bytes=max_bytes,
        budget=budget,
        session=session,
        timeout=aiohttp.ClientTimeout(total=25),
    )
    if status != 200 or not body or len(body) < 4096:
      if budget is not None and body:
        budget.release(len(body))
      return None
    if not _is_valid_mp4_video_bytes(body, ctype or ""):
      if budget is not None:
        budget.release(len(body or b""))
      return None
    clean = await _ensure_discord_playable_mp4(body, max_bytes=max_bytes)
    return clean, name
  except Exception:
    return None


async def extract_x_media_items(
    url: str, max_bytes: int = 10 * 1024 * 1024
) -> Tuple[List[Tuple[bytes, str]], Optional[str], Optional[str]]:
  """Every photo/video of one X post, using FxEmbed's public JSON (no auth, no cookies).

  Engine order: `api.fxtwitter.com` (all photos + video variants) -> yt-dlp (video posts
  the API does not expose) -> bare `fxtwitter.com` link. The link is still returned when
  everything fails: Discord renders FxEmbed's gallery, so the post degrades instead of
  vanishing. The files themselves are what matters, which is why the API comes first.
  """
  status_id = _x_status_id(url)
  fixed = _x_fallback_url(url)
  if not status_id:
    return [], fixed, None

  handle = (_X_HANDLE_RE.search(url).group(1) if _X_HANDLE_RE.search(url) else "i")
  session = await get_shared_http_session()
  # Shared ceiling for the photos and video variants of this one post (C-007).
  job_budget = SharedByteBudget(MAX_JOB_BYTES)
  tweet: Optional[Dict[str, Any]] = None
  try:
    api_url = f"https://api.fxtwitter.com/{handle}/status/{status_id}"
    async with session.get(
        api_url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=aiohttp.ClientTimeout(total=10),
        allow_redirects=False,
    ) as resp:
      if resp.status == 200:
        _x_bytes = await read_bounded_stream(resp, max_bytes=2 * 1024 * 1024)
        payload = json.loads(_x_bytes.decode("utf-8", "replace")) if _x_bytes else None
        if isinstance(payload, dict) and payload.get("code") == 200 and isinstance(payload.get("tweet"), dict):
          tweet = payload["tweet"]
  except Exception:
    tweet = None

  if tweet:
    author = (tweet.get("author") or {}).get("name") or handle
    text = (tweet.get("text") or "").strip()
    caption = f"🐦 **{author}**" + (f" — {text[:180]}" if text else "")
    media = tweet.get("media") or {}
    entries = [e for e in (media.get("all") or []) if isinstance(e, dict)]

    photos = [
        str(e.get("url")) for e in entries
        if e.get("type") == "photo" and str(e.get("url", "")).startswith("http")
    ]
    if photos:
      files = await _download_photo_slides(
          photos, max_bytes=max_bytes, prefix="x", referer=f"https://x.com/{handle}",
          budget=job_budget)
      if files:
        _safe_gc_collect()
        return files, None, caption

    for entry in entries:
      if entry.get("type") not in ("video", "gif"):
        continue
      variants = [
          v for v in (entry.get("variants") or [])
          if isinstance(v, dict) and str(v.get("url", "")).startswith("http")
          and ("mp4" in (v.get("content_type") or "") or str(v.get("url")).split("?")[0].endswith(".mp4"))
      ]
      variants.sort(key=lambda v: int(v.get("bitrate") or 0), reverse=True)
      for variant in variants[:2]:
        got = await _download_one_video(
            str(variant["url"]), {"User-Agent": "Mozilla/5.0"}, max_bytes, budget=job_budget)
        if got:
          _safe_gc_collect()
          return [got], None, f"🎬 {caption}"

  # Engine 2: yt-dlp resolves X video posts the JSON API may not expose (killable subprocess).
  if yt_dlp is not None:
    try:
      info = await run_ytdlp_json(
          url, timeout=9.0,
          extra=["-f", "best[vcodec^=avc1][ext=mp4]/best[ext=mp4]/best"],
      )
    except Exception:
      info = None
    if isinstance(info, dict) and isinstance(info.get("url"), str):
      got = await _download_one_video(
          info["url"], info.get("http_headers") or {"User-Agent": "Mozilla/5.0"}, max_bytes,
          budget=job_budget)
      if got:
        return [got], None, "🎬 **X**"

  return [], fixed, None


async def process_social_media_url_multi(
    url: str, max_bytes: int = 10 * 1024 * 1024
) -> Tuple[List[Tuple[bytes, str]], Optional[str], Optional[str]]:
    """Extract media inside the per-job byte budget (C-007).

    Each extractor claims against one shared `SharedByteBudget` while downloading, so
    peak retained RAM is bounded during the parallel fetch, not filtered afterwards.
    The final `_fit_file_budget` pass stays as a backstop for payloads that bypass the
    claim path (for example a yt-dlp staged file read).
    """
    files, fixed_url, caption = await _process_social_media_url_multi(url, max_bytes)
    if files:
        kept, dropped = _fit_file_budget(files)
        if dropped:
            logger.info(
                "gallery-budget url_sha=%s dropped=%d kept=%d budget_mb=%d",
                hashlib.sha256(url.encode()).hexdigest()[:8], dropped, len(kept),
                MAX_JOB_BYTES // (1024 * 1024),
            )
        files = kept
    return files, fixed_url, caption


async def _process_social_media_url_multi(
    url: str, max_bytes: int = 10 * 1024 * 1024
) -> Tuple[List[Tuple[bytes, str]], Optional[str], Optional[str]]:
  """
  Extract playable video(s) or full photo album from TikTok, Instagram, X, or Reddit.
  Returns: (list_of_(file_bytes, filename), fallback_fixed_url, caption)
  """
  if not _allowed_social_host(url):
    return [], None, None
  resolved_url = await resolve_social_redirect_and_clean(url)
  if not _allowed_social_host(resolved_url) or not await asyncio.to_thread(
      _is_safe_public_http_url, resolved_url
  ):
    return [], None, None

  # 1. TikTok (Videos + Multi-Photo Slideshows)
  if is_allowed_hostname(resolved_url, ("tiktok.com", "tnktok.com", "tfxktok.com", "vxtiktok.com")):
    return await extract_tiktok_media_items(resolved_url, max_bytes=max_bytes)

  # 2. Instagram (Reels + Single & Multi-Photo Carousel Posts)
  if is_allowed_hostname(resolved_url, ("instagram.com", "instagr.am", "ddinstagram.com")):
    norm_ig = re.sub(r"/reels/", "/reel/", resolved_url, flags=re.IGNORECASE)
    return await extract_instagram_media_items(norm_ig, max_bytes=max_bytes)

  # 3. X / Twitter (photos and video files, FxEmbed JSON first, link as the last resort)
  if is_allowed_hostname(resolved_url, ("x.com", "twitter.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com")):
    return await extract_x_media_items(resolved_url, max_bytes=max_bytes)

  # 4. Reddit
  if is_allowed_hostname(resolved_url, ("reddit.com", "redd.it")):
    fixed = re.sub(r"https?://(?:[a-z0-9]+\.)?reddit\.com", "https://rxddit.com", resolved_url, flags=re.IGNORECASE)
    return [], fixed, None

  return [], None, None


async def process_social_media_url(url: str) -> Tuple[Optional[bytes], Optional[str], Optional[str], str]:
  """Backward-compatible single-file wrapper around process_social_media_url_multi."""
  files, fixed_url, caption = await process_social_media_url_multi(url)
  if files:
    return files[0][0], None, caption, files[0][1]
  return None, fixed_url, caption, "video.mp4"


def _get_active_audio_stage_files() -> Set[str]:
  """Return paths of local staged audio files currently being played in any guild VoiceClient."""
  active: Set[str] = set()
  try:
    b = get_bot()
    if b and hasattr(b, "music_states"):
      for ms in b.music_states.values():
        ct = getattr(ms, "current_track", None)
        if isinstance(ct, dict):
          su = str(ct.get("stream_url") or "")
          if su.startswith("/"):
            active.add(os.path.abspath(su))
        for q_item in getattr(ms, "queue", []):
          if isinstance(q_item, dict):
            su = str(q_item.get("stream_url") or "")
            if su.startswith("/"):
              active.add(os.path.abspath(su))
  except Exception:
    pass
  return active


async def perform_full_system_and_bot_update() -> Dict[str, Any]:
  """Read-only owner update report. The bot process never escalates to root.

  Package upgrades run from the host (unattended-upgrades or an operator SSH
  session), not from inside a Discord message handler. Keeping the command
  registered preserves the command census; it only reports instructions and runs
  the ordinary storage cleanup.
  """
  clean_stats = await perform_storage_cleanup(deep=True)
  instructions = (
      "تحديث النظام يتم من السيرفر وليس من البوت (بدون sudo):\n"
      "1) ssh <user>@<host>\n"
      "2) sudo unattended-upgrade -d  (أو: sudo apt update && sudo apt full-upgrade -y)\n"
      "3) python -m pip install -r requirements.txt --upgrade\n"
      "4) sudo systemctl restart angelbot"
  )
  return {
      "logs_tail": instructions,
      "clean_stats": clean_stats,
      "reboot_required": os.path.isfile("/var/run/reboot-required"),
  }


async def perform_storage_cleanup(deep: bool = True) -> Dict[str, Any]:
  """
  Storage and memory cleanup for the running bot:
  1. Deletes non-active staged audio files in `/tmp/angelbot_audio/`, `/tmp/angelbot_social/`,
     `/tmp/angelbot_ytdlp_cache/`, and stale media/temp files in `/tmp`.
  2. Deletes `__pycache__` `.pyc` files and `~/.cache/yt-dlp` / `~/.cache/pip` when `deep=True`.
  3. Prunes old transient SQLite rows, runs `PRAGMA wal_checkpoint(TRUNCATE)`, and `VACUUM`s the database.
  4. Clears stale in-memory caches (`_AUDIO_STREAM_CACHE`, `_KNOWN_PREVIEW_URLS`, `snipe_cache`, `editsnipe_cache`,
     stale cooldowns) and invokes `gc.collect()` + Linux `libc.malloc_trim(0)` to release RAM to the OS.
  """
  freed_bytes = 0
  deleted_files = 0
  active_audio_paths = _get_active_audio_stage_files()

  def _clean_dir_tree(dir_path: str, keep_paths: Optional[Set[str]] = None, min_age_sec: float = 0.0):
    nonlocal freed_bytes, deleted_files
    if not os.path.isdir(dir_path):
      return
    now_ts = time.time()
    for root, dirs, files in os.walk(dir_path, topdown=False):
      for fn in files:
        fp = os.path.abspath(os.path.join(root, fn))
        if keep_paths and fp in keep_paths:
          continue
        try:
          st = os.stat(fp)
          if min_age_sec > 0 and (now_ts - st.st_mtime) < min_age_sec:
            continue
          sz = st.st_size
          os.remove(fp)
          freed_bytes += sz
          deleted_files += 1
        except Exception:
          pass
      for dn in dirs:
        dp = os.path.join(root, dn)
        try:
          if not os.listdir(dp):
            os.rmdir(dp)
        except Exception:
          pass

  loop = asyncio.get_running_loop()
  tmp_root = tempfile.gettempdir()

  def _sync_disk_sweep():
    nonlocal freed_bytes, deleted_files
    # 1. Clean AngelBot staging and cache directories. Reveal only our own prefixes:
    #    other services share the host temp directory.
    _clean_dir_tree(os.path.join(tmp_root, "angelbot_audio"),
                    keep_paths=active_audio_paths, min_age_sec=0.0 if deep else 600.0)
    for entry in os.listdir(tmp_root):
      if entry.startswith(("angelbot_social_", "angelbot_transcode_")):
        _clean_dir_tree(os.path.join(tmp_root, entry), min_age_sec=60.0)
    _clean_dir_tree(os.path.join(tmp_root, "angelbot_social"), min_age_sec=30.0)
    if deep:
      _clean_dir_tree(os.path.join(tmp_root, "angelbot_ytdlp_cache"), min_age_sec=60.0)
    else:
      _clean_dir_tree(os.path.join(tmp_root, "angelbot_ytdlp_cache"), min_age_sec=3600.0)

    # 2. Deliberately no sweep of the rest of /tmp: other services share the host,
    #    so matching "tmp*"/"*.mp4" there deleted another process's files mid-flight.
    #    Only Angel's own staging directories above are ours to clean.

    # 3. Clean __pycache__ and user ~/.cache (pip / yt-dlp / fontconfig) on deep cleanup
    if deep:
      _clean_dir_tree(os.path.join(BASE_DIR, "__pycache__"), min_age_sec=0.0)
      home_cache = os.path.expanduser("~/.cache")
      for cache_sub in ("yt-dlp", "pip", "thumbnails"):
        _clean_dir_tree(os.path.join(home_cache, cache_sub), min_age_sec=0.0)

  await loop.run_in_executor(None, _sync_disk_sweep)

  # 4. Prune & Vacuum SQLite Database
  pruned_rows = 0
  db_size_bytes = 0
  b = get_bot()
  if b and getattr(b, "db", None):
    try:
      db_before = 0
      for sfx in ("", "-wal", "-shm"):
        p = b.db.db_path + sfx
        if os.path.isfile(p):
          db_before += os.path.getsize(p)
      pruned_rows, db_size_bytes = await b.db.cleanup_and_vacuum(deep=deep)
      if db_before > db_size_bytes:
        freed_bytes += (db_before - db_size_bytes)
    except Exception:
      pass

  # 5. Clear in-memory caches & trim C heap back to OS
  _AUDIO_STREAM_CACHE.clear()
  _KNOWN_PREVIEW_URLS.clear()
  if b:
    if deep:
      b.snipe_cache.clear()
      b.editsnipe_cache.clear()
    now_m = time.monotonic()
    b.xp_cooldowns = {k: v for k, v in b.xp_cooldowns.items() if now_m - v < 60.0}
    b.social_url_cooldowns.clear()
    b.spam_tracker.clear()
    unlocked = [uid for uid, lk in b.user_locks.items() if not lk.locked()]
    for uid in unlocked:
      b.user_locks.pop(uid, None)

  await loop.run_in_executor(None, _safe_gc_collect)
  if sys.platform.startswith("linux"):
    def _trim_heap():
      try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
      except Exception:
        pass
    await loop.run_in_executor(None, _trim_heap)

  # 6. Collect Disk & RAM telemetry
  disk_free_gb = 0.0
  disk_total_gb = 0.0
  try:
    du = shutil.disk_usage(BASE_DIR)
    disk_free_gb = round(du.free / (1024 ** 3), 2)
    disk_total_gb = round(du.total / (1024 ** 3), 2)
  except Exception:
    pass

  ram_mb = 0.0
  if os.path.isfile("/proc/self/status"):
    try:
      with open("/proc/self/status", "r", encoding="utf-8") as sf:
        for ln in sf:
          if ln.startswith("VmRSS:"):
            parts = ln.split()
            if len(parts) >= 2 and parts[1].isdigit():
              ram_mb = round(int(parts[1]) / 1024.0, 1)
            break
    except Exception:
      pass

  return {
      "freed_bytes": freed_bytes,
      "freed_mb": round(freed_bytes / (1024 * 1024), 2),
      "deleted_files": deleted_files,
      "pruned_rows": pruned_rows,
      "db_size_kb": round(db_size_bytes / 1024.0, 1),
      "disk_free_gb": disk_free_gb,
      "disk_total_gb": disk_total_gb,
      "ram_mb": ram_mb,
  }
