"""Per-channel Discord sender: bounded queues, isolated 429 handling, idle eviction.

The old design had one queue and one worker for every channel: a 429 sleep in
channel A delayed channel B for every other server, a dead channel's jobs stayed in
`pending` forever, and the task outlived shutdown. Each channel now owns a bounded
queue, its own token bucket and its own worker, and an idle worker exits.
"""
import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional

import discord


@dataclass
class SendJob:
    channel_id: int
    content: Optional[str] = None
    reply_to: Optional[int] = None
    attempts: int = 0
    kind: str = "text"
    meta: Dict[str, Any] = field(default_factory=dict)


class LeakyBucket:
    def __init__(self, capacity: int = 5, rate_per_sec: float = 1.0):
        self.capacity = capacity
        self.rate = max(0.01, rate_per_sec)
        self.tokens = float(capacity)
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self):
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now

    async def acquire(self):
        async with self._lock:
            while True:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                await asyncio.sleep(min((1.0 - self.tokens) / self.rate, 2.0))


class _ChannelWorker:
    def __init__(self, sender: "Sender", channel_id: int):
        self.sender = sender
        self.channel_id = channel_id
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=sender.max_queue)
        self.bucket = LeakyBucket(sender.capacity, sender.rate_per_sec)
        self.task: Optional[asyncio.Task] = None
        self.last_active = time.monotonic()


class Sender:
    """Bounded per-channel sender used by `bot.sender`."""

    def __init__(
        self,
        client,
        capacity: int = 5,
        rate_per_sec: float = 1.0,
        max_attempts: int = 4,
        max_channels: int = 500,
        idle_ttl_seconds: float = 300.0,
        max_queue: int = 50,
    ):
        self.client = client
        self.capacity = capacity
        self.rate_per_sec = rate_per_sec
        self.max_attempts = max_attempts
        self.max_channels = max_channels
        self.idle_ttl_seconds = idle_ttl_seconds
        self.max_queue = max_queue
        self._workers: Dict[int, _ChannelWorker] = {}
        self.dead_letters: Deque[SendJob] = deque(maxlen=100)
        self.sent = 0
        self.retried = 0
        self._stopped = False

    def start(self):
        # Workers are created on first enqueue; nothing to do here.
        self._stopped = False

    async def enqueue(self, job: SendJob):
        if self._stopped or self.client.is_closed():
            self.dead_letters.append(job)
            return
        worker = self._workers.get(job.channel_id)
        if worker is None:
            self._evict_oldest_if_full()
            worker = _ChannelWorker(self, job.channel_id)
            self._workers[job.channel_id] = worker
            worker.task = asyncio.create_task(self._run(worker))
        worker.last_active = time.monotonic()
        try:
            worker.queue.put_nowait(job)
        except asyncio.QueueFull:
            # Bounded: drop the oldest queued message for this channel, keep the newest.
            try:
                worker.queue.get_nowait()
                worker.queue.task_done()
            except Exception:
                pass
            worker.queue.put_nowait(job)

    def _evict_oldest_if_full(self):
        if len(self._workers) < self.max_channels:
            return
        oldest_id = min(self._workers, key=lambda cid: self._workers[cid].last_active)
        worker = self._workers.pop(oldest_id, None)
        if worker and worker.task and not worker.task.done():
            worker.task.cancel()

    async def _run(self, worker: _ChannelWorker):
        try:
            await self.client.wait_until_ready()
            while not self.client.is_closed():
                try:
                    job = await asyncio.wait_for(worker.queue.get(), timeout=self.idle_ttl_seconds)
                except asyncio.TimeoutError:
                    if worker.queue.empty():
                        break  # idle: this worker ends here
                    continue
                try:
                    await self._deliver(worker, job)
                finally:
                    worker.queue.task_done()
                worker.last_active = time.monotonic()
        except asyncio.CancelledError:
            raise
        finally:
            if self._workers.get(worker.channel_id) is worker:
                self._workers.pop(worker.channel_id, None)

    def _requeue(self, worker: "_ChannelWorker", job: SendJob):
        # Never block the worker that is re-queueing: a full queue means the channel is
        # backed up, so drop the oldest waiting job and keep the newest one.
        try:
            worker.queue.put_nowait(job)
        except asyncio.QueueFull:
            try:
                dropped = worker.queue.get_nowait()
                worker.queue.task_done()
                self.dead_letters.append(dropped)
            except Exception:
                pass
            try:
                worker.queue.put_nowait(job)
            except asyncio.QueueFull:
                self.dead_letters.append(job)

    async def _deliver(self, worker: _ChannelWorker, job: SendJob):
        channel = self.client.get_channel(job.channel_id)
        if channel is None:
            try:
                channel = await self.client.fetch_channel(job.channel_id)
            except Exception:
                channel = None
        if channel is None:
            job.attempts = self.max_attempts + 1
            self.dead_letters.append(job)
            return
        await worker.bucket.acquire()
        content = job.content
        if isinstance(content, str) and len(content) > 2000:
            content = content[:1997].rstrip() + "…"
        try:
            kwargs = {"allowed_mentions": discord.AllowedMentions(everyone=False, roles=False, users=True)}
            if job.reply_to:
                kwargs["reference"] = channel.get_partial_message(job.reply_to)
            await channel.send(content, **kwargs)
            self.sent += 1
        except discord.HTTPException as exc:
            status = int(getattr(exc, "status", 0) or 0)
            retry_after = float(getattr(exc, "retry_after", 0) or 0)
            if status not in (429, 500, 502, 503, 504):
                # 400/403/404 will fail the same way forever; do not burn retries on them.
                self.dead_letters.append(job)
                return
            job.attempts += 1
            self.retried += 1
            if job.attempts <= self.max_attempts:
                # Only THIS channel's worker sleeps; every other channel keeps flowing.
                if status == 429:
                    if retry_after > 60.0:
                        # A multi-minute Retry-After means the channel is unusable now.
                        self.dead_letters.append(job)
                        return
                    delay = max(0.5, retry_after)
                else:
                    delay = min(8.0, 1.5 * job.attempts)
                await asyncio.sleep(delay)
                self._requeue(worker, job)
                return
            self.dead_letters.append(job)
        except Exception:
            job.attempts += 1
            self.retried += 1
            if job.attempts <= self.max_attempts:
                self._requeue(worker, job)
            else:
                self.dead_letters.append(job)

    async def stop(self):
        self._stopped = True
        tasks = [w.task for w in list(self._workers.values()) if w.task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._workers.clear()

    def stats(self) -> Dict[str, int]:
        return {
            "queued": sum(w.queue.qsize() for w in self._workers.values()),
            "sent": self.sent,
            "retried": self.retried,
            "pending": len(self.dead_letters),
            "channels": len(self._workers),
        }
