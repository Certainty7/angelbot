"""A bounded, single-worker queue for background persistence work.

Every guild message used to spawn its own task in `_bg_tasks`: with a blocked database that
became a thousand pending tasks, exceptions surfaced only as "Task exception was never
retrieved", and shutdown cancelled in-flight writes so nothing was stored (audit finding 10).

The queue is deliberately small: one worker, a fixed capacity, non-blocking admission, and a
drain window. It is not a retry mechanism and it is not the Discord sender.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, Awaitable, Callable, Deque, List, Optional, Tuple

logger = logging.getLogger("angel.work_queue")

JobFactory = Callable[[], Awaitable[Any]]


class BoundedWorkQueue:
  """Queue with capacity counted over queued *and* active jobs.

  `submit` never blocks and never awaits: when the queue is full (or draining) the job is
  rejected, its coroutine is closed to avoid an "never awaited" warning, and the job id is
  logged so the loss is observable.
  """

  def __init__(self, name: str, capacity: int = 256) -> None:
    self.name = name
    self.capacity = max(1, int(capacity))
    self._jobs: Deque[Tuple[Any, JobFactory]] = deque()
    self._active: Optional[Tuple[Any, JobFactory]] = None
    self._worker: Optional[asyncio.Task] = None
    self._wakeup = asyncio.Event()
    self._closing = False
    self._finished = asyncio.Event()
    self._finished.set()
    self.rejected = 0

  @property
  def depth(self) -> int:
    """Queued plus the one job currently running."""
    return len(self._jobs) + (1 if self._active is not None else 0)

  async def start(self) -> None:
    if self._worker is not None and not self._worker.done():
      return
    self._closing = False
    self._finished.clear()
    self._worker = asyncio.create_task(self._run(), name=f"{self.name}-queue")

  def submit(self, job_id: Any, factory: JobFactory) -> bool:
    """Admit a job without waiting. Returns False when it was rejected."""
    if self._closing or self.depth >= self.capacity:
      self.rejected += 1
      coro = factory()
      close = getattr(coro, "close", None)
      if close is not None:
        close()
      logger.warning(
          f"{self.name} queue full ({self.depth}/{self.capacity}); rejected message_id={job_id}"
      )
      return False
    self._jobs.append((job_id, factory))
    self._wakeup.set()
    return True

  async def _run(self) -> None:
    while True:
      if not self._jobs:
        if self._closing:
          break
        self._wakeup.clear()
        await self._wakeup.wait()
        continue
      job_id, factory = self._jobs.popleft()
      self._active = (job_id, factory)
      try:
        await factory()
      except asyncio.CancelledError:
        raise
      except Exception as exc:  # noqa: BLE001 - one bad job must not kill the worker
        logger.error(f"{self.name} job {job_id} failed: {type(exc).__name__}: {exc}")
      finally:
        self._active = None
    self._finished.set()

  async def drain(self, timeout: float = 10.0) -> List[Any]:
    """Stop admission, finish what is queued up to `timeout`, return unfinished job ids."""
    self._closing = True
    self._wakeup.set()
    try:
      if timeout <= 0:
        raise asyncio.TimeoutError
      await asyncio.wait_for(self._finished.wait(), timeout=timeout)
    except asyncio.TimeoutError:
      unfinished: List[Any] = []
      if self._active is not None:
        unfinished.append(self._active[0])
        self._active = None
      unfinished.extend(job_id for job_id, _ in self._jobs)
      self._jobs.clear()
      if unfinished:
        logger.warning(f"{self.name} shutdown left {len(unfinished)} unsent job(s): {unfinished}")
      return unfinished

    if self._worker is not None and not self._worker.done():
      self._worker.cancel()
      try:
        await self._worker
      except (asyncio.CancelledError, Exception):  # noqa: BLE001 - shutdown must not raise
        pass
    self._worker = None
    if self.rejected:
      logger.warning(f"{self.name} rejected {self.rejected} job(s) while saturated")
    return []
