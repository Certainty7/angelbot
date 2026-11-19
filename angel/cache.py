"""Small bounded containers used by the long-lived caches.

Every one of these exists to stop a multi-day process from growing a dictionary per
user, channel or URL until systemd restarts it. They are dict-compatible with the
handful of methods the bot already uses.
"""
import asyncio
import time
import weakref
from collections import OrderedDict, deque
from typing import Any, Callable, Generic, Optional, TypeVar

T = TypeVar("T")


class BoundedDict(OrderedDict):
  """LRU dictionary: writes beyond maxsize evict the least-recently-used key."""

  def __init__(self, maxsize: int = 1024, *args, **kwargs):
    self._maxsize = max(1, int(maxsize))
    super().__init__(*args, **kwargs)
    while len(self) > self._maxsize:
      self.popitem(last=False)

  def __setitem__(self, key, value):
    super().__setitem__(key, value)
    self.move_to_end(key)
    while len(self) > self._maxsize:
      self.popitem(last=False)

  def update(self, *args, **kwargs):
    for key, value in dict(*args, **kwargs).items():
      self[key] = value

  def setdefault(self, key, default=None):
    if key in self:
      return self[key]
    self[key] = default
    return default


class BoundedDefaultDict(BoundedDict):
  """BoundedDict with the `defaultdict(deque)` behaviour the channel buffers need."""

  def __init__(self, default_factory: Callable[[], Any], maxsize: int = 1024):
    self.default_factory = default_factory
    super().__init__(maxsize)

  def __missing__(self, key):
    value = self.default_factory()
    self[key] = value
    return value


class BoundedTTLCache(Generic[T]):
  """LRU + TTL dictionary for time-based caches (cooldowns, snippets)."""

  def __init__(self, maxsize: int = 512, ttl_seconds: float = 3600.0) -> None:
    if maxsize <= 0 or ttl_seconds <= 0:
      raise ValueError("maxsize and ttl_seconds must be positive")
    self._maxsize = maxsize
    self._ttl = ttl_seconds
    self._store: "OrderedDict[Any, tuple[float, T]]" = OrderedDict()

  def set(self, key: Any, value: T) -> None:
    now = time.monotonic()
    self._store[key] = (now + self._ttl, value)
    self._store.move_to_end(key)
    self.prune(now)

  def __setitem__(self, key: Any, value: T) -> None:
    self.set(key, value)

  def get(self, key: Any, default: Optional[T] = None) -> Optional[T]:
    item = self._store.get(key)
    if item is None:
      return default
    expires_at, value = item
    if time.monotonic() > expires_at:
      self._store.pop(key, None)
      return default
    self._store.move_to_end(key)
    return value

  def __getitem__(self, key: Any) -> T:
    sentinel = object()
    value = self.get(key, sentinel)  # type: ignore[arg-type]
    if value is sentinel:
      raise KeyError(key)
    return value  # type: ignore[return-value]

  def __contains__(self, key: Any) -> bool:
    sentinel = object()
    return self.get(key, sentinel) is not sentinel  # type: ignore[arg-type]

  def pop(self, key: Any, default: Optional[T] = None) -> Optional[T]:
    item = self._store.get(key)
    if item is None:
      return default
    expires_at, value = item
    self._store.pop(key, None)
    if time.monotonic() > expires_at:
      return default
    return value

  def items(self):
    self.prune()
    return [(k, v) for k, (_exp, v) in self._store.items()]

  def values(self):
    return [v for _k, v in self.items()]

  def clear(self) -> None:
    self._store.clear()

  def prune(self, now: Optional[float] = None) -> int:
    now = now if now is not None else time.monotonic()
    removed = 0
    for key in [k for k, (exp, _v) in self._store.items() if now > exp]:
      self._store.pop(key, None)
      removed += 1
    while len(self._store) > self._maxsize:
      self._store.popitem(last=False)
      removed += 1
    return removed

  def __len__(self) -> int:
    self.prune()
    return len(self._store)

  def __iter__(self):
    self.prune()
    return iter(list(self._store))


class WeakLockMap:
  """Per-key locks that disappear when no coroutine holds them."""

  def __init__(self) -> None:
    self._locks: "weakref.WeakValueDictionary[Any, asyncio.Lock]" = weakref.WeakValueDictionary()

  def get(self, key: Any) -> asyncio.Lock:
    lock = self._locks.get(key)
    if lock is None:
      lock = asyncio.Lock()
      self._locks[key] = lock
    return lock

  def __getitem__(self, key: Any) -> asyncio.Lock:
    return self.get(key)

  def __contains__(self, key: Any) -> bool:
    return key in self._locks

  def pop(self, key: Any, default=None):
    return self._locks.pop(key, default)

  def items(self):
    return list(self._locks.items())

  def __len__(self) -> int:
    return len(self._locks)


def sanitize_untrusted_line(text: str) -> str:
  """Neutralise angle brackets and control characters in untrusted chat text."""
  cleaned = "".join(
      ch for ch in (text or "")
      if ch in ("\n", "\t") or ch.isprintable()
  )
  return cleaned.replace("<", "\u2039").replace(">", "\u203a")


def channel_buffer(maxlen: int = 60) -> BoundedDefaultDict:
  return BoundedDefaultDict(lambda: deque(maxlen=maxlen), maxsize=2000)


def cooldown_map(maxsize: int = 5000) -> BoundedTTLCache:
  return BoundedTTLCache(maxsize=maxsize, ttl_seconds=24 * 3600.0)
