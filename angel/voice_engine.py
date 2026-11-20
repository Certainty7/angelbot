"""Music queue + playback on discord.py's public voice API only.

Rules this module keeps:
  * DAVE is discord.py's job (davey 0.1.7) -- no private attributes, no monkey-patches.
  * one voice client per guild, one track at a time, every failure answered.
  * the queue is a plain state machine so it is testable without Discord.

E2EE send-path awareness. With `dave_protocol_version > 0` the
channel is end-to-end encrypted, and discord.py sends *plaintext* opus whenever
`can_encrypt` is False (voice_client.py:_get_voice_packet). Those frames are dropped by
the channel: `is_playing()` stays True, ffmpeg stays healthy, no exception is raised, and the
result is total silence. So before every play we wait (briefly) for the MLS session to be ready,
and we log the DAVE state and the decoded byte flow, which is the measurement this build
was missing. Waiting is bounded: a channel with nobody else in it never advances the MLS
group, and playback must still start in that case.
"""
from __future__ import annotations

import asyncio
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

import discord

from .audio_source import invalidate_cache, resolve_best
from .config import FFMPEG_EXE, logger
from .net import validate_extracted_stream_url

# Reconnect options matter: SoundCloud hands out HLS/m3u8 URLs that expire and drop.
# The protocol whitelist keeps a hostile playlist/redirect from naming a local file or
# an exotic FFmpeg protocol after yt-dlp has already handed us the URL.
FFMPEG_BEFORE = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
    "-protocol_whitelist https,http,tcp,tls,crypto"
)
QUEUE_MAX = 200


def _ffmpeg_quote(value: str) -> str:
  """Quote one FFmpeg argv token (FFmpeg has its own parser, not the shell)."""
  return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _before_options(track: "Track") -> str:
  """Reconnect + the extractor's UA/Referer, never cookies.

  SoundCloud's CDN answers 403 to FFmpeg's default UA while accepting yt-dlp's;
  passing the safe header subset is the difference between "playing" and silence.
  """
  parts = [FFMPEG_BEFORE, "-nostdin", "-rw_timeout 15000000"]
  raw = dict(getattr(track, "http_headers", None) or {})
  ua = ""
  for key in list(raw):
    if key.lower() == "user-agent":
      ua = raw.pop(key)
      break
  # Never forward cookies/authorization even if a future caller sets them.
  headers = {
      k: v for k, v in raw.items()
      if k.lower() in {"referer", "origin", "accept-language"} and v
  }
  if ua:
    parts.append(f"-user_agent {_ffmpeg_quote(str(ua))}")
  if headers:
    lines = [f"{k}: {v}" for k, v in headers.items()]
    if lines:
      crlf = chr(13) + chr(10)
      parts.append(f"-headers {_ffmpeg_quote(crlf.join(lines) + crlf)}")
  return " ".join(parts)

# How long to wait for the DAVE (E2EE) session to become ready before starting anyway.
DAVE_WAIT_S = 8.0
# When to report the send-path state of a track that has already started.
AUDIO_WATCH_S = 6.0
# 48 kHz, stereo, s16 -- what FFmpegPCMAudio produces, so a stalled decoder is obvious.
PCM_BYTES_PER_SECOND = 48000 * 2 * 2


class VoiceBusyError(RuntimeError):
  """The bot already streams in another voice channel of this guild."""

  def __init__(self, channel):
    self.channel = channel
    super().__init__(f"already connected to {getattr(channel, 'name', channel)}")


class _CountingSource(discord.AudioSource):
  """Counts decoded bytes so the logs can tell 'decoder stalled' from 'frames dropped'."""

  def __init__(self, inner: discord.AudioSource):
    self.inner = inner
    self.bytes_read = 0
    self._bytes_lock = threading.Lock()

  def read(self) -> bytes:
    data = self.inner.read()
    if data:
      with self._bytes_lock:
        self.bytes_read += len(data)
    return data

  def is_opus(self) -> bool:
    return bool(getattr(self.inner, "is_opus", lambda: False)())

  def cleanup(self) -> None:
    cleaner = getattr(self.inner, "cleanup", None)
    if cleaner is not None:
      cleaner()


def dave_state(voice: discord.VoiceClient) -> Dict[str, object]:
  """Read-only view of the E2EE send path (public attributes only)."""
  conn = getattr(voice, "_connection", None)
  session = getattr(conn, "dave_session", None) if conn is not None else None
  return {
      "ver": getattr(conn, "dave_protocol_version", 0) if conn is not None else 0,
      "can_encrypt": bool(getattr(conn, "can_encrypt", False)) if conn is not None else False,
      "ready": getattr(session, "ready", None) if session is not None else None,
      "pending": len(getattr(conn, "dave_pending_transitions", {}) or {}) if conn is not None else 0,
  }


@dataclass
class Track:
  title: str
  stream_url: str
  requester_id: int = 0
  requester_name: str = ""
  duration: float = 0.0
  webpage_url: str = ""
  source: str = ""
  # Original /play text, so a stalled signed URL can be invalidated and re-resolved.
  query: str = ""
  # yt-dlp's browser-like UA/Referer, safe subset only (no cookies/authorization).
  http_headers: Dict[str, str] = field(default_factory=dict)

  @property
  def duration_text(self) -> str:
    if not self.duration or not math.isfinite(self.duration):
      return "—"
    total = int(self.duration)
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


@dataclass
class GuildQueue:
  """Pure queue state -- no Discord calls, so selftest can drive it."""

  tracks: Deque[Track] = field(default_factory=lambda: deque(maxlen=QUEUE_MAX))
  current: Optional[Track] = None
  loop: bool = False
  volume: float = 1.0
  stay_247: bool = False
  text_channel_id: int = 0

  def add(self, track: Track) -> int:
    self.tracks.append(track)
    return len(self.tracks)

  def pop_next(self) -> Optional[Track]:
    if self.loop and self.current is not None:
      return self.current
    return self.tracks.popleft() if self.tracks else None

  def remove_at(self, index: int) -> Optional[Track]:
    if 0 <= index < len(self.tracks):
      return self._drop(index)
    return None

  def _drop(self, index: int) -> Track:
    items = list(self.tracks)
    removed = items.pop(index)
    self.tracks = deque(items, maxlen=QUEUE_MAX)
    return removed

  def clear(self) -> None:
    self.tracks.clear()
    self.current = None
    self.loop = False

  def snapshot(self, limit: int = 10) -> List[Track]:
    return list(self.tracks)[:limit]

  @property
  def total_duration(self) -> float:
    return sum(t.duration for t in self.tracks)


class MusicEngine:
  """Owns one `GuildQueue` per guild and the play loop."""

  def __init__(self, bot: discord.Client):
    self.bot = bot
    self.queues: Dict[int, GuildQueue] = {}
    self._loop: Optional[asyncio.AbstractEventLoop] = None
    self.last_dave: Dict[int, Dict[str, object]] = {}
    self._watch_tasks: Dict[int, asyncio.Task] = {}
    self._locks: Dict[int, asyncio.Lock] = {}

  def _guild_lock(self, guild_id: int) -> asyncio.Lock:
    lock = self._locks.get(guild_id)
    if lock is None:
      lock = asyncio.Lock()
      self._locks[guild_id] = lock
    return lock

  def _current_loop(self) -> asyncio.AbstractEventLoop:
    if self._loop is None:
      self._loop = asyncio.get_event_loop()
    return self._loop

  # ---- state -------------------------------------------------------------
  def state(self, guild_id: int) -> GuildQueue:
    queue = self.queues.get(guild_id)
    if queue is None:
      queue = GuildQueue()
      self.queues[guild_id] = queue
    return queue

  # ---- connection --------------------------------------------------------
  async def ensure_connected(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
    """Join the member's voice channel, never silently moving out of another one.

    `/play` refuses when the bot is busy elsewhere, but `/playlist load` and the
    message-based player reached this method directly and dragged the bot away from
    listeners in another room (C-016).
    """
    self._loop = asyncio.get_running_loop()
    async with self._guild_lock(channel.guild.id):
      voice = channel.guild.voice_client
      if voice is not None and voice.is_connected():
        if voice.channel and voice.channel.id != channel.id:
          raise VoiceBusyError(voice.channel)
        return voice
      if voice is not None:
        try:
          await voice.disconnect(force=True)
        except Exception:
          pass
      return await channel.connect(timeout=25.0, reconnect=True, self_deaf=True)

  # ---- queue -------------------------------------------------------------
  async def enqueue(self, channel: discord.VoiceChannel, query: str, requester: discord.abc.User) -> Track:
    # Smart search: rank SoundCloud/YouTube hits and play the best one; a URL passes through.
    info = await resolve_best(query)  # raises ResolveError with the real reason
    track = Track(
        title=info["title"],
        stream_url=info["stream_url"],
        requester_id=getattr(requester, "id", 0),
        requester_name=getattr(requester, "display_name", str(requester)),
        duration=info["duration"],
        webpage_url=info["webpage_url"],
        source=info.get("source", ""),
        query=query,
        http_headers=info.get("http_headers") or {},
    )
    self.state(channel.guild.id).add(track)
    return track

  # ---- E2EE send path ----------------------------------------------------
  @staticmethod
  def _listener_count(voice: discord.VoiceClient) -> int:
    """Humans in the bot's channel (the DAVE group only advances with another member)."""
    channel = getattr(voice, "channel", None)
    members = getattr(channel, "members", None) or []
    return max(0, len(members) - 1) if members else 0

  async def _notify(self, guild: discord.Guild, text: str) -> None:
    """Best-effort user-facing status; never let a missing channel break playback."""
    channel_id = self.state(guild.id).text_channel_id
    if not channel_id:
      return
    channel = self.bot.get_channel(channel_id)
    if channel is None:
      try:
        channel = await self.bot.fetch_channel(channel_id)
      except Exception:
        return
    try:
      await channel.send(text)
    except Exception:
      return

  async def _wait_for_dave(self, voice: discord.VoiceClient, timeout: float = DAVE_WAIT_S) -> Dict[str, object]:
    """Wait for the MLS session to be ready; never wait longer than `timeout`."""
    started = time.monotonic()
    while True:
      state = dave_state(voice)
      if state["can_encrypt"] or not state["ver"]:
        break
      if time.monotonic() - started >= timeout:
        break
      await asyncio.sleep(0.2)
    state["waited"] = round(time.monotonic() - started, 2)
    state["listeners"] = self._listener_count(voice)
    if state["ver"] and not state["can_encrypt"]:
      logger.warning(
          f"music-dave WARNING ver={state['ver']} can_encrypt=False ready={state['ready']} "
          f"pending={state['pending']} waited={state['waited']}s listeners={state['listeners']} -- "
          f"frames leave as plaintext and an encrypted channel drops them (audible silence, no error). "
          f"Playback continues; the session becomes usable once another member is in the channel."
      )
    else:
      logger.info(
          f"music-dave ver={state['ver']} can_encrypt={state['can_encrypt']} "
          f"ready={state['ready']} pending={state['pending']} waited={state['waited']}s "
          f"listeners={state['listeners']}"
      )
    return state

  def _watch_audio(self, guild: discord.Guild, voice: discord.VoiceClient, source: _CountingSource,
                   track: Track) -> None:
    """After a few seconds, state whether audio is really flowing and really encrypted."""

    async def runner() -> None:
      await asyncio.sleep(AUDIO_WATCH_S)
      try:
        decoded = source.bytes_read
        state = dave_state(voice)
        expected = int(PCM_BYTES_PER_SECOND * AUDIO_WATCH_S)
        playing = voice.is_playing()
        logger.info(
            f"music-audio guild={guild.id} title={track.title[:40]!r} playing={playing} "
            f"decoded_kb={decoded // 1024} expected_kb~{expected // 1024} "
            f"can_encrypt={state['can_encrypt']} ver={state['ver']}"
        )
        if decoded < expected // 4:
          logger.warning(
              f"music-audio WARNING decoder delivered {decoded // 1024}KB in {AUDIO_WATCH_S:.0f}s "
              f"(expected ~{expected // 1024}KB) -- the stream is stalled, not silent-but-playing"
          )
        # Two failure modes look identical to the user ("playing" but silent):
        # FFmpeg produced no bytes at all, or DAVE drops the plaintext frames.
        # Stop the lie, tell the channel, and let `after` advance.
        if decoded < expected // 10 and self.state(guild.id).current is track:
          logger.warning("music-audio stalled: decoded=%s bytes; stopping the silent track", decoded)
          # A cached signed URL may have expired; force a fresh extraction next time.
          if track.query:
            invalidate_cache(track.query)
          await self._notify(
              guild,
              "⚠️ تعذّر فك الصوت من المصدر (FFmpeg لم يُخرج صوتاً). "
              "أعدت تعيين رابط الصوت — أعيدي `/play` وسأستخرج رابطاً جديداً.",
          )
          try:
            if voice.is_playing():
              voice.stop()
          except Exception:
            pass
        elif state["ver"] and not state["can_encrypt"] and self._listener_count(voice) > 0 \
                and self.state(guild.id).current is track:
          logger.warning(
              "music-audio dave silent: ver=%s can_encrypt=False listeners=%s; stopping",
              state["ver"], self._listener_count(voice),
          )
          await self._notify(
              guild,
              "🔇 القناة مشفّرة (E2EE) والإطارات تُسقط قبل السماع. أوقفت التشغيل الصامت.",
          )
          try:
            if voice.is_playing():
              voice.stop()
          except Exception:
            pass
      except Exception as exc:  # noqa: BLE001 - a diagnostic must never break playback
        logger.debug(f"music-audio watch failed: {type(exc).__name__}: {exc}")

    task = asyncio.ensure_future(runner())
    previous = self._watch_tasks.get(guild.id)
    if previous is not None and not previous.done():
      previous.cancel()
    self._watch_tasks[guild.id] = task

  # ---- playback ----------------------------------------------------------
  def _make_source(self, track: Track, volume: float):
    pcm = discord.FFmpegPCMAudio(
        track.stream_url,
        executable=FFMPEG_EXE,
        before_options=_before_options(track),
        options="-vn",
    )
    counted = _CountingSource(pcm)
    return discord.PCMVolumeTransformer(counted, volume=max(0.0, min(2.0, volume))), counted

  def _schedule_advance(self, guild: discord.Guild, delay: float = 0.4,
                        only_if_idle: bool = False) -> None:
    """Schedule the next queue advance on the loop thread.

    `only_if_idle` is for retries of a *blocked* playback attempt: if another `/play`
    already started a track while we waited, this retry is stale and must not dequeue
    anything — the old shape popped track after track, each `play()` failing with
    "Already playing audio" until the queue was consumed.
    """
    async def runner() -> None:
      await asyncio.sleep(delay)
      if only_if_idle:
        await self._advance_if_idle(guild)
      else:
        await self.play_next(guild)

    try:
      fut = asyncio.run_coroutine_threadsafe(runner(), self._current_loop())

      def _done(f):
        try:
          exc = f.exception()
        except Exception:
          return
        if exc is not None:
          logger.warning(f"music-advance failed: {type(exc).__name__}: {exc}")

      fut.add_done_callback(_done)
    except RuntimeError:  # loop already closed during shutdown -- nothing to advance
      pass

  async def _advance_if_idle(self, guild: discord.Guild) -> None:
    """Advance only when playback never started: under one lock hold, the blocked
    attempt still owns the queue (no current track, nothing playing), and the
    advance itself runs under the same hold so nothing can start between the
    check and the dequeue."""
    async with self._guild_lock(guild.id):
      voice = guild.voice_client
      state = self.state(guild.id)
      if (voice is not None and (voice.is_playing() or voice.is_paused())) \
              or state.current is not None:
        logger.info("music-advance skipped: playback is already active")
        return
      await self._play_next_locked(guild)

  async def _recover_dave(self, guild: discord.Guild, voice: discord.VoiceClient) -> discord.VoiceClient:
    """One clean reconnect when an encrypted channel left the MLS session unusable."""
    channel = getattr(voice, "channel", None)
    try:
      await voice.disconnect(force=True)
    except Exception:
      pass
    if channel is None:
      return voice
    try:
      fresh = await channel.connect(timeout=20.0, reconnect=True, self_deaf=True)
    except Exception as exc:  # noqa: BLE001 - playback must degrade, not crash
      logger.warning(f"music-dave reconnect failed: {type(exc).__name__}: {exc}")
      return voice
    try:
      self.last_dave[guild.id] = await self._wait_for_dave(fresh)
    except Exception:
      self.last_dave[guild.id] = {}
    return fresh

  async def play_next(self, guild: discord.Guild) -> Optional[Track]:
    # Capture the loop on the event-loop thread; `after` runs on the audio thread and
    # must never call get_running_loop() itself.
    self._loop = asyncio.get_running_loop()
    async with self._guild_lock(guild.id):
      return await self._play_next_locked(guild)

  async def _play_next_locked(self, guild: discord.Guild) -> Optional[Track]:
    started = time.monotonic()
    state = self.state(guild.id)
    voice = guild.voice_client
    if voice is None or not voice.is_connected():
      state.current = None
      return None

    track = state.pop_next()
    state.current = track
    if track is None:
      return None

    def after(error: Optional[Exception]) -> None:
      if error is not None:
        logger.warning(f"music-playback error: {error}")
      self._schedule_advance(guild)

    try:
      dave = await self._wait_for_dave(voice)
      if dave.get("ver") and not dave.get("can_encrypt"):
        voice = await self._recover_dave(guild, voice)
        # Re-read the new client: the reconnect may have fixed the MLS state or not.
        dave = dave_state(voice)
      self.last_dave[guild.id] = dave
    except Exception as exc:  # noqa: BLE001 - a diagnostic must never block playback
      logger.debug(f"music-dave probe failed: {type(exc).__name__}: {exc}")
      self.last_dave[guild.id] = {}
      dave = {}

    # A DAVE channel drops plaintext frames: is_playing() stays True and the
    # result is total silence. Never announce a track we know cannot be heard.
    if dave.get("ver") and not dave.get("can_encrypt") and self._listener_count(voice) > 0:
      logger.warning(
          "music-dave blocked playback: ver=%s can_encrypt=False listeners=%s; "
          "not sending silent frames",
          dave.get("ver"), self._listener_count(voice),
      )
      state.current = None
      # Put the track back instead of consuming it: a queue must not be eaten one track at a
      # time by a condition that will still be true for the next one.
      state.tracks.appendleft(track)
      await self._notify(
          guild,
          "🔇 القناة الصوتية مشفّرة (E2EE) وجلسة التشفير لم تجهز، "
          "لذلك لن أشغّل شيئاً بلا صوت. جرّبي مرة أخرى بعد ثانية، أو أعيدي البوت للقناة.",
      )
      # The retry is bound to this blocked attempt: if another /play starts a track
      # inside the delay, the stale retry must return without dequeuing anything.
      self._schedule_advance(guild, delay=1.0, only_if_idle=True)
      return None

    try:
      await validate_extracted_stream_url(track.stream_url)
    except PermissionError as exc:
      logger.warning(f"music-stream blocked: {exc}")
      self._schedule_advance(guild, delay=0.2)
      return None

    source = None
    try:
      source, counted = self._make_source(track, state.volume)
      voice.play(source, after=after)
    except Exception as exc:  # noqa: BLE001 - a bad stream must never kill the bot
      if source is not None:
        try:
          source.cleanup()
        except Exception:
          pass
      logger.warning(f"music-playback failed to start: {exc}")
      self._schedule_advance(guild, delay=1.0)
      return None

    logger.info(
        f"music-play guild={guild.id} title={track.title[:60]!r} "
        f"dur={track.duration_text} source={track.source} "
        f"can_encrypt={self.last_dave.get(guild.id, {}).get('can_encrypt')} "
        f"encode_ms={round((time.monotonic() - started) * 1000, 1)}"
    )
    self._watch_audio(guild, voice, counted, track)
    return track

  async def start(self, guild: discord.Guild) -> Optional[Track]:
    # Check and start under the same lock: releasing it between is_playing()
    # and play_next() let two concurrent /play calls consume two tracks and
    # raise "Already playing audio".
    self._loop = asyncio.get_running_loop()
    async with self._guild_lock(guild.id):
      voice = guild.voice_client
      if voice is not None and voice.is_playing():
        return self.state(guild.id).current
      return await self._play_next_locked(guild)

  async def skip(self, guild: discord.Guild) -> Optional[Track]:
    async with self._guild_lock(guild.id):
      voice = guild.voice_client
      state = self.state(guild.id)
      skipped = state.current
      state.current = None
      if voice is not None and (voice.is_playing() or voice.is_paused()):
        voice.stop()  # fires `after` -> play_next
        return skipped
    return await self.play_next(guild)

  async def set_volume(self, guild: discord.Guild, volume: float) -> float:
    state = self.state(guild.id)
    state.volume = max(0.0, min(2.0, volume))
    voice = guild.voice_client
    if voice is not None and isinstance(voice.source, discord.PCMVolumeTransformer):
      voice.source.volume = state.volume
    return state.volume

  async def stop(self, guild: discord.Guild, *, disconnect: bool = True) -> None:
    state = self.state(guild.id)
    state.clear()
    task = self._watch_tasks.pop(guild.id, None)
    if task is not None and not task.done():
      task.cancel()
    voice = guild.voice_client
    if voice is None:
      return
    try:
      if voice.is_playing() or voice.is_paused():
        voice.stop()
    finally:
      if disconnect and voice.is_connected():
        await voice.disconnect(force=False)
