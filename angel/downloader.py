"""yt-dlp plumbing shared by the social-media resolvers.

Every extraction runs as a subprocess (`python -m yt_dlp -J`) with a hard timeout,
bounded stdout/stderr drains and a kill. The old implementation ran yt-dlp inside a
two-worker ThreadPoolExecutor and shielded the future on timeout, so two hung
extractors pinned both threads and stalled the whole social-media path until the bot
restarted. A process can be killed; a thread cannot.

The target is one argv element, never shell text, and always follows `--` so a
crafted string can never become an option. Operator cookies are attached only for
plain YouTube media pages.
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .config import yt_dlp
from .net import get_ytdlp_semaphore, is_allowed_hostname, is_valid_http_url_syntax

# Kept for API compatibility with the cleanup routine.
_AUDIO_STREAM_CACHE: Dict[str, Any] = {}
_KNOWN_PREVIEW_URLS: set = set()

MAX_YTDLP_STDOUT_BYTES = 2 * 1024 * 1024
MAX_YTDLP_STDERR_BYTES = 64 * 1024
_COOKIE_ALLOWED_DOMAINS = frozenset({"youtube.com", "youtu.be", "music.youtube.com"})
_YT_EXACT_PATHS = ("/watch", "/playlist")
_YT_PREFIX_PATHS = ("/shorts/", "/live/")


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


def _is_safe_cookie_target(target_url: str) -> bool:
  """Cookies only for allowlisted YouTube hosts and plain media paths."""
  if not is_allowed_hostname(target_url, _COOKIE_ALLOWED_DOMAINS):
    return False
  raw_path = urlparse(target_url).path or ""
  if "%" in raw_path or "//" in raw_path or "\\" in raw_path:
    return False
  host = (urlparse(target_url).hostname or "").lower().rstrip(".")
  path = raw_path.lower()
  if host == "youtu.be":
    return len(path) > 1 and "/" not in path[1:]
  if path in _YT_EXACT_PATHS:
    return True
  return path.startswith(_YT_PREFIX_PATHS) and len(path) > 7


def build_ytdlp_json_argv(target: str, extra: Optional[List[str]] = None) -> List[str]:
  """Hardened argv for `yt-dlp -J`: no config, no generic extractor, `--`, scoped cookies."""
  if not is_valid_http_url_syntax(target):
    raise ValueError(f"Rejected unsafe yt-dlp target: {target!r}")
  argv = [
      sys.executable, "-m", "yt_dlp", "-J",
      "--ignore-config", "--no-warnings", "--no-playlist",
      "--use-extractors", "default,-generic",
      "-S", "proto:https",
      "--socket-timeout", "6", "--retries", "1",
  ]
  if extra:
    argv += list(extra)
  cookie_file = _find_youtube_cookies_file()
  if cookie_file and _is_safe_cookie_target(target):
    argv += ["--cookies", cookie_file]
  argv += ["--", target]
  return argv


async def _read_bounded_pipe(stream, max_bytes: int, *, fail_on_overflow: bool) -> bytes:
  if stream is None:
    return b""
  buf = bytearray()
  while True:
    chunk = await stream.read(32_768)
    if not chunk:
      break
    if len(buf) + len(chunk) > max_bytes:
      if fail_on_overflow:
        raise ValueError(f"Subprocess output exceeded {max_bytes} bytes")
      continue  # stderr: keep draining so the child never blocks
    buf.extend(chunk)
  return bytes(buf)


def subprocess_session_kwargs() -> Dict[str, Any]:
  """Give the extractor its own session/process group on POSIX.

  A group signal only reaches helpers spawned by yt-dlp if the extractor leads its own
  group: in the bot's group `killpg` would take the bot down too.
  """
  return {"start_new_session": True} if os.name == "posix" else {}


def _windows_taskkill_argv(pid: int) -> List[str]:
  """argv-based tree kill: no shell, no ctypes, no command-string assembly."""
  return ["taskkill", "/PID", str(pid), "/T", "/F"]


def terminate_process_tree(proc: asyncio.subprocess.Process) -> None:
  """Signal the extractor *and* its descendants; callers reap with `proc.wait()`.

  Synchronous by design: the timeout/cancellation path may already be running inside a
  cancelled task, where any `await` would raise before the kill is delivered.
  """
  if proc.returncode is not None:
    return
  if os.name == "posix":
    try:
      group = os.getpgid(proc.pid)
    except ProcessLookupError:
      group = None
    if group is not None and group != os.getpgid(0):
      try:
        os.killpg(group, signal.SIGKILL)
        return
      except (ProcessLookupError, PermissionError):
        pass
  else:
    try:
      # Short and bounded: ~20 ms, and it must land even under cancellation.
      subprocess.run(
          _windows_taskkill_argv(proc.pid),
          capture_output=True,
          check=False,
          timeout=10,
      )
    except (OSError, subprocess.TimeoutExpired):
      pass
  try:
    proc.kill()
  except ProcessLookupError:
    pass


async def read_bounded_subprocess_stdout(
    proc: asyncio.subprocess.Process,
    max_bytes: int = MAX_YTDLP_STDOUT_BYTES,
    timeout: float = 25.0,
) -> bytes:
  """Drain stdout and stderr concurrently with caps and a timeout."""
  assert proc.stdout is not None

  async def _drain() -> bytes:
    stdout_task = asyncio.create_task(
        _read_bounded_pipe(proc.stdout, max_bytes, fail_on_overflow=True)
    )
    stderr_task = asyncio.create_task(
        _read_bounded_pipe(proc.stderr, MAX_YTDLP_STDERR_BYTES, fail_on_overflow=False)
    )
    try:
      stdout_data, _stderr = await asyncio.gather(stdout_task, stderr_task)
    except BaseException:
      # CancelledError inherits BaseException: the old `except Exception` left yt-dlp
      # running after the caller was cancelled (C-017).
      for task in (stdout_task, stderr_task):
        if not task.done():
          task.cancel()
      raise
    await proc.wait()
    return stdout_data

  try:
    return await asyncio.wait_for(_drain(), timeout=timeout)
  except asyncio.TimeoutError:
    raise
  finally:
    # One reap path for timeout, cancellation and overflow.
    if proc.returncode is None:
      terminate_process_tree(proc)
      # Do not await inside a cancelled task: hand the reap to the loop.
      try:
        asyncio.get_running_loop().create_task(proc.wait())
      except RuntimeError:
        pass


async def run_ytdlp_json(
    target: str, timeout: float, extra: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
  """`yt-dlp -J <target>` in a killable subprocess; the info dict or None."""
  if yt_dlp is None:
    return None
  try:
    argv = build_ytdlp_json_argv(target, extra)
  except ValueError:
    return None

  async with get_ytdlp_semaphore():
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **subprocess_session_kwargs(),
    )
    try:
      out = await read_bounded_subprocess_stdout(proc, timeout=timeout)
    except (asyncio.TimeoutError, ValueError):
      return None
    finally:
      if proc.returncode is None:
        terminate_process_tree(proc)
        try:
          asyncio.get_running_loop().create_task(proc.wait())
        except RuntimeError:
          pass
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
    "_is_safe_cookie_target",
    "build_ytdlp_json_argv",
    "read_bounded_subprocess_stdout",
    "subprocess_session_kwargs",
    "terminate_process_tree",
    "run_ytdlp_json",
]
