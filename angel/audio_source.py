"""Resolve a playable audio stream without ever blocking the event loop.

One `yt-dlp -j` call per candidate returns metadata and the direct stream URL.
Search sources are tried in order (SoundCloud before YouTube), and
every failure is turned into a reason string instead of an exception into the
player.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from .config import BASE_DIR, logger
from .net import get_ytdlp_semaphore, is_allowed_hostname, is_valid_http_url_syntax, validate_extracted_stream_url
from .images import _is_safe_public_http_url
from .downloader import read_bounded_subprocess_stdout

YTDLP = os.path.join(BASE_DIR, "venv", "bin", "yt-dlp")
COOKIES = os.path.join(BASE_DIR, "cookies.txt")
DENO = "/usr/local/bin/deno"
DEFAULT_TIMEOUT = 30.0
MAX_DURATION = 6 * 3600  # a 6-hour stream is a mistake, not a request
MAX_YTDLP_STDOUT_BYTES = 2 * 1024 * 1024

# Cookies are operator credentials: only the YouTube media pages ever receive them.
_COOKIE_DOMAINS = ("youtube.com", "youtu.be", "music.youtube.com")

# Search order: SoundCloud, then a direct URL, then YouTube.
SEARCH_SOURCES: Tuple[Tuple[str, str], ...] = (("SoundCloud", "scsearch"), ("YouTube", "ytsearch"))

# YouTube needs cookies (bot check) and a JS runtime (sig/nsig). Both are optional at runtime:
# without them the source drops out of the chain.
YOUTUBE_ENABLED = os.environ.get("MUSIC_YOUTUBE", "1").strip().lower() not in {"0", "false", "no", "off"}


def _build_args(target: str, *, json_flag: str = "-j", extra: Optional[List[str]] = None) -> List[str]:
  """Hardened yt-dlp argv: ignore user config, no generic extractor, `--`, scoped cookies."""
  args = [json_flag, "--ignore-config", "--no-warnings", "--no-playlist",
          "--use-extractors", "default,-generic", "-S", "proto:https"]
  if os.path.exists(DENO):
    args += ["--js-runtimes", f"deno:{DENO}"]
  if extra:
    args += list(extra)
  if os.path.exists(COOKIES) and is_valid_http_url_syntax(target) and is_allowed_hostname(target, _COOKIE_DOMAINS):
    args += ["--cookies", COOKIES]
  args += ["--", target]
  return args


class ResolveError(RuntimeError):
  """The query could not be turned into a playable stream."""


# What a user must never see in a "not found" reply.
_INTERNAL_NOISE = ("Expecting value", "JSONDecodeError", "UnicodeDecodeError", "Traceback",
                   "Expecting property name", "Extra data")


def clean_reason(text: str) -> str:
  """Turn a resolver failure into one short user-facing sentence.

  Parser errors are a bug in the extractor handshake, not a message for the owner:
  they collapse into the same "nothing found" line the user can act on.
  """
  raw = (text or "").strip()
  if not raw:
    return "لم أجد نتيجة لهذا البحث"
  if any(noise in raw for noise in _INTERNAL_NOISE):
    return "لم أجد نتيجة لهذا البحث"
  return raw[:180]


def parse_info(payload: str) -> Dict[str, Any]:
  """Turn one `yt-dlp -j` document into the fields the player needs (pure)."""
  data = json.loads(payload)
  if isinstance(data, dict) and data.get("_type") == "playlist":
    entries = data.get("entries") or []
    if not entries:
      raise ResolveError("nothing found")
    data = entries[0]
  if not isinstance(data, dict):
    raise ResolveError("unexpected extractor output")

  url = data.get("url") or ""
  if not url:
    raise ResolveError("no stream url in extractor output")

  title = (data.get("title") or "بدون عنوان").strip()
  return {
      "title": title[:120],
      "stream_url": url,
      "webpage_url": data.get("webpage_url") or data.get("original_url") or "",
      "duration": float(data.get("duration") or 0),
      "ext": data.get("ext") or "",
      "uploader": data.get("uploader") or data.get("channel") or "",
  }


def build_target(query: str, source: str) -> str:
  """`url` passes through; a search source becomes yt-dlp's `scsearch1:<q>` form."""
  query = (query or "").strip()
  if source in {"url", "direct"}:
    return query
  return f"{source}1:{query}"


def is_url(text: str) -> bool:
  return (text or "").strip().lower().startswith(("http://", "https://"))


async def _run_ytdlp(args: List[str], timeout: float) -> str:
  if not (os.path.exists(YTDLP) or shutil.which("yt-dlp")):
    raise ResolveError("yt-dlp is not installed")
  async with get_ytdlp_semaphore():
    proc = await asyncio.create_subprocess_exec(
        YTDLP if os.path.exists(YTDLP) else "yt-dlp",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
      out = await read_bounded_subprocess_stdout(proc, max_bytes=MAX_YTDLP_STDOUT_BYTES, timeout=timeout)
    except asyncio.TimeoutError:
      raise ResolveError(f"timed out after {timeout:.0f}s")
    except ValueError:
      raise ResolveError("extractor output too large")
  if proc.returncode != 0:
    raise ResolveError(f"yt-dlp exit {proc.returncode}")
  return (out or b"").decode("utf-8", "replace")


async def resolve(query: str, *, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
  """Resolve a URL or a search phrase. Raises ResolveError with every attempt's reason."""
  text = (query or "").strip()
  if not text:
    raise ResolveError("empty query")

  # yt-dlp will happily fetch any http(s) host, including loopback, the VPN subnet and the
  # cloud metadata address. The image path already had this guard; the music path did not.
  if is_url(text):
    loop = asyncio.get_running_loop()
    if not await loop.run_in_executor(None, _is_safe_public_http_url, text):
      raise ResolveError("unsupported url")

  targets = [("direct", "url")] if is_url(text) else list(SEARCH_SOURCES)
  if not YOUTUBE_ENABLED:
    targets = [t for t in targets if t[0] != "YouTube"]
  errors: List[str] = []

  for label, source in targets:
    target = build_target(text, source)
    try:
      payload = await _run_ytdlp(_build_args(target, extra=["-f", "ba/b"]), timeout)
      info = parse_info(payload)
      await validate_extracted_stream_url(info["stream_url"])
    except json.JSONDecodeError:
      # yt-dlp printed something that is not JSON: an extractor handshake failure, not a
      # user-facing error. Keep the raw parser text out of the reply.
      errors.append(f"{label}: no usable result")
      continue
    except ResolveError as exc:
      errors.append(f"{label}: {exc}")
      continue

    if info["duration"] > MAX_DURATION:
      errors.append(f"{label}: too long ({info['duration'] / 3600:.1f}h)")
      continue

    info["source"] = label
    logger.info(
        f"music-resolve ok source={label} dur={info['duration']:.0f}s title={info['title'][:60]!r}"
    )
    return info

  raise ResolveError(" · ".join(errors) or "not found")


# Smart search: any song name -> best candidate across sources.

_DIACRITICS = re.compile(r"[\u0617-\u061A\u064B-\u0652\u0670\u0640]")
_WAKE = re.compile(r"^\s*(?:يا\s+)?(?:انجل|أنجل|إنجل|angel)\b[\s,،:.\-–—]*", re.IGNORECASE)
_VERB = re.compile(r"^(?:شغلي|شغّلي|شغليلي|شغل|play|اعزفي|عزفي|حملي)\b[\s,،:.\-–—]*", re.IGNORECASE)
_NOISE = ("remix", "live", "cover", "8d", "slowed", "reverb", "nightcore", "loop",
          "karaoke", "instrumental", "sped up", "1 hour", "10 hours",
          "البارت المحذوف", "مقطع", "teaser", "clip")
_GENERIC = {"اغنيه", "اغنية", "أغنية", "موسيقي", "موسيقى", "فيديو", "song", "songs", "music",
            "video", "track", "official", "audio", "افضل", "احلى", "جديد", "جديده"}
_STOP = {"من", "في", "علي", "عن", "يا", "الي", "مع", "هذا", "هذه", "كان", "قد", "او", "انا",
         "انت", "هو", "هي", "كل", "بعد", "قبل", "لي", "لك", "له", "بي", "ولا", "ثم", "حتي"}


def normalize_ar(text: str) -> str:
  """Fold Arabic orthography (alef forms, ى) without collapsing ة->ه.

  Folding ة to ه makes 'عبدة' equal 'عبده' and lets an unrelated song outrank the real
  one, so only the alef/yā forms are unified here.
  """
  folded = _DIACRITICS.sub("", text or "")
  for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي")):
    folded = folded.replace(src, dst)
  return folded


def _tokens(text: str) -> set:
  return {tok for tok in re.findall(r"[0-9a-z\u0621-\u064a]{2,}", normalize_ar(text).lower())}


def _match_tokens(text: str) -> set:
  """Tokens used for matching only: ة folded to ه so 'أغنية' and 'اغنيه' meet.

  The strict tokens stay separate so a fold never decides which song is which.
  """
  return {tok.replace("ة", "ه") for tok in _tokens(text)}


def parse_play_request(text: str) -> Optional[str]:
  """'انجل شغلي <اسم أو رابط>' -> the query; anything else -> None (pure, testable)."""
  raw = (text or "").strip()
  wake = _WAKE.match(raw)
  if not wake:
    return None
  rest = raw[wake.end():].strip()
  verb = _VERB.match(rest)
  if not verb:
    return None
  query = rest[verb.end():].strip(" \"'«»،,.:-–—")
  return query or None


def strip_command_words(text: str) -> str:
  """Remove the wake word and the play verb from a query typed inside /play."""
  cleaned = (text or "").strip()
  wake = _WAKE.match(cleaned)
  if wake:
    cleaned = cleaned[wake.end():]
  verb = _VERB.match(cleaned)
  if verb:
    cleaned = cleaned[verb.end():]
  return cleaned.strip(" \"'«»،,.:-–—") or (text or "").strip()


def score_candidate(title: str, duration: float, query: str, source: str = "") -> float:
  """Rank one search hit against the ask: token overlap, sane duration, no junk versions."""
  wanted = (_tokens(query) - _GENERIC - _STOP) or _tokens(query)
  if not wanted:
    return 0.0
  wanted_m = {t.replace("ة", "ه") for t in wanted}
  got = _match_tokens(title)
  overlap = len(wanted_m & got) / len(wanted_m)
  score = overlap * 100.0

  # The most distinctive word of the ask must actually be in the title, or the hit is a
  # different song that only shares a common word.
  key_token = max(wanted_m, key=len)
  if key_token not in got:
    score *= 0.35

  # A hit whose title only mentions the ask after a long unrelated prefix is usually a
  # mashup/remix that borrowed the words ("Crazy Story ... But It's Lofi Hip Hop Radio").
  order = re.findall(r"[0-9a-z\u0621-\u064a]{2,}", normalize_ar(title).lower())
  first_hit = next((i for i, tok in enumerate(order) if tok.replace("ة", "ه") in wanted_m), None)
  if first_hit is not None and first_hit >= 2:
    score -= 22.0
  elif first_hit == 0:
    score += 15.0  # the title opens with what was asked for

  if 120 <= (duration or 0) <= 420:
    score += 15.0
  elif 20 <= (duration or 0) <= 600:
    score += 8.0
  elif (duration or 0) > 1800:
    score -= 20.0
  elif 0 < (duration or 0) < 20:
    score -= 15.0

  lowered = (title or "").lower()
  asked = (query or "").lower()
  for noise in _NOISE:
    if noise in lowered and noise not in asked:
      score -= 18.0

  if source == "SoundCloud":  # tiebreak only; the score dominates
    score += 2.0
  return round(score, 2)


def _entry_url(entry: Dict[str, Any]) -> str:
  url = entry.get("webpage_url") or entry.get("url") or ""
  if isinstance(url, str) and url.startswith(("http://", "https://")):
    return url
  vid = entry.get("id")
  if vid and entry.get("ie_key") in (None, "Youtube"):
    return f"https://www.youtube.com/watch?v={vid}"
  return ""


async def _search_entries(source: str, query: str, limit: int, timeout: float) -> List[Dict[str, Any]]:
  payload = await _run_ytdlp(
      _build_args(f"{source}{limit}:{query}", json_flag="-J", extra=["--flat-playlist"]), timeout
  )
  data = json.loads(payload)
  entries = data.get("entries") if isinstance(data, dict) else None
  return [e for e in (entries or []) if isinstance(e, dict) and e.get("title")]


# In-process cache: a repeated request (same normalised query) skips the whole search.
_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL = 900.0
_CACHE_MAX = 48


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
  hit = _CACHE.get(key)
  if not hit:
    return None
  stamp, info = hit
  if time.monotonic() - stamp > _CACHE_TTL:
    _CACHE.pop(key, None)
    return None
  return dict(info)


def _cache_put(key: str, info: Dict[str, Any]) -> None:
  if len(_CACHE) >= _CACHE_MAX:
    oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
    _CACHE.pop(oldest, None)
  _CACHE[key] = (time.monotonic(), dict(info))


async def _collect_source(label: str, source: str, search_text: str, limit: int,
                          timeout: float) -> List[Dict[str, Any]]:
  """Search one source and score its hits; [] on any extractor failure."""
  try:
    entries = await _search_entries(source, search_text, limit, timeout)
  except (ResolveError, json.JSONDecodeError):
    return []
  found: List[Dict[str, Any]] = []
  for entry in entries:
    url = _entry_url(entry)
    if not url:
      continue
    dur = float(entry.get("duration") or 0)
    found.append({
        "title": entry.get("title") or "",
        "duration": dur,
        "url": url,
        "source": label,
        "score": score_candidate(entry.get("title") or "", dur, search_text, label),
    })
  return found


async def _resolve_target(target: str, timeout: float) -> Dict[str, Any]:
  """Extract one explicit yt-dlp target (search pseudo-URL or video URL) directly."""
  payload = await _run_ytdlp(_build_args(target, extra=["-f", "ba/b"]), timeout)
  info = parse_info(payload)
  await validate_extracted_stream_url(info["stream_url"])
  return info


async def resolve_best(query: str, *, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
  """Any song name -> the best playable stream, fast.

  Latency strategy: SoundCloud is searched first (fast, scored); a confident hit (>=70) is
  played without touching YouTube. A weak result falls back to a single `ytsearch1` call
  instead of search-then-extract, roughly halving the YouTube-only wait. Results are cached.
  """
  text = strip_command_words(query)
  if is_url(text):
    return await resolve(text, timeout=timeout)

  key = f"{text.lower()}|{YOUTUBE_ENABLED}"
  cached = _cache_get(key)
  if cached is not None:
    # A cached direct URL is re-checked like a fresh extraction: signed CDN URLs expire
    # and a stale entry must never reach FFmpeg unvalidated.
    try:
      await validate_extracted_stream_url(cached["stream_url"])
    except (KeyError, PermissionError):
      _CACHE.pop(key, None)
    else:
      logger.info("music-search cache-hit %r" % text[:40])
      return cached

  errors: List[str] = []
  # Measured 2026-11-12 on the 1-OCPU host: running yt-dlp beside the SoundCloud search
  # makes both slower, so the probe stays lazy -- it only starts when SoundCloud is weak.
  candidates = await _collect_source("SoundCloud", "scsearch", text, 5, timeout)
  best_sc = max((c["score"] for c in candidates), default=-999.0)

  if not candidates or best_sc < 55.0:
    core = " ".join(sorted(_tokens(text) - _GENERIC - _STOP)) or text
    if core and core != text:
      candidates += await _collect_source("SoundCloud", "scsearch", core, 3, timeout)

  # A short, generic ask ("lofi hip hop") cannot be judged by word overlap alone: the
  # mashups score as high as the real stream. For those, demand a near-perfect SoundCloud
  # match and otherwise defer to YouTube's own relevance ranking.
  distinctive = len([t for t in _tokens(text) if t not in _GENERIC and t not in _STOP])
  threshold = 100.0 if distinctive <= 3 else 70.0
  if YOUTUBE_ENABLED and best_sc < threshold:
    try:
      info = await _resolve_target(f"ytsearch1:{text}", timeout)
      info["source"] = "YouTube"
      info["score"] = None
      info["search_title"] = info.get("title", "")
      _cache_put(key, info)
      return info
    except ResolveError as exc:
      errors.append(f"YouTube: {exc}")

  if not candidates:
    raise ResolveError(" · ".join(errors) or "not found")

  candidates.sort(key=lambda c: -c["score"])
  logger.info(
      "music-search best=%s score=%.1f title=%r"
      % (candidates[0]["source"], candidates[0]["score"], candidates[0]["title"][:50])
  )

  for cand in candidates[:3]:
    try:
      info = await resolve(cand["url"], timeout=timeout)
    except ResolveError as exc:
      errors.append(f"{cand['source']}: {exc}")
      continue
    info["source"] = cand["source"]
    info["score"] = cand["score"]
    info["search_title"] = cand["title"]
    _cache_put(key, info)
    return info

  raise ResolveError(" · ".join(errors) or "not found")
