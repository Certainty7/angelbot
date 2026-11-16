"""yt-dlp plumbing shared by the social-media resolvers.

Every extraction runs as a subprocess (`python -m yt_dlp -J`) with a hard timeout and a
kill. The old implementation ran yt-dlp inside a two-worker ThreadPoolExecutor and shielded
the future on timeout, so two hung extractors pinned both threads and stalled the whole
social-media path until the bot restarted. A process can be killed; a thread cannot.

The target is one argv element, never shell text.
"""
import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

from .config import yt_dlp
from .net import _YTDLP_SEMAPHORE

# Kept for API compatibility with the cleanup routine.
_AUDIO_STREAM_CACHE: Dict[str, Any] = {}
_KNOWN_PREVIEW_URLS: set = set()


def _find_youtube_cookies_file() -> Optional[str]:
  """Locate an optional cookies.txt for yt-dlp (never required)."""
  from .config import BASE_DIR

  env_cookie = (os.getenv("YOUTUBE_COOKIES_FILE") or "").strip()
  for candidate_path in (
      env_cookie,
      os.path.join(BASE_DIR, "cookies.txt"),
      "cookies.txt",
  ):
    if candidate_path and os.path.isfile(candidate_path):
      try:
        if os.path.getsize(candidate_path) > 32:
          return candidate_path
      except Exception:
        pass
  return None


async def run_ytdlp_json(
    target: str, timeout: float, extra: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
  """`yt-dlp -J <target>` in a killable subprocess; the info dict or None.

  Returns None on any failure (missing package, non-zero exit, bad JSON, timeout) so the
  caller can fall through to its next engine. A playlist wrapper is unwrapped to its first
  entry, matching what the old in-process `extract_info` call returned.
  """
  if yt_dlp is None:
    return None

  argv = [sys.executable, "-m", "yt_dlp", "-J", "--no-warnings", "--no-playlist",
          "--socket-timeout", "6", "--retries", "1"]
  cookie_file = _find_youtube_cookies_file()
  if cookie_file:
    argv += ["--cookies", cookie_file]
  if extra:
    argv += list(extra)
  argv.append(target)

  async with _YTDLP_SEMAPHORE:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
      out, _err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
      proc.kill()
      await proc.wait()
      return None
  if proc.returncode != 0:
    return None
  try:
    data = json.loads((out or b"").decode("utf-8", "replace"))
  except (json.JSONDecodeError, UnicodeDecodeError):
    return None
  if isinstance(data, dict) and data.get("_type") == "playlist":
    entries = data.get("entries") or []
    first = entries[0] if entries else None
    return first if isinstance(first, dict) else None
  return data if isinstance(data, dict) else None


__all__ = [
    "_AUDIO_STREAM_CACHE",
    "_KNOWN_PREVIEW_URLS",
    "_find_youtube_cookies_file",
    "run_ytdlp_json",
]
