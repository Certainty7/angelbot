"""Leaky-bucket sender with Retry-After handling and a never-drop pending list."""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
        self.rate = rate_per_sec
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


class Sender:
    def __init__(self, client, capacity: int = 5, rate_per_sec: float = 1.0, max_attempts: int = 4):
        self.client = client
        self.bucket = LeakyBucket(capacity, rate_per_sec)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.max_attempts = max_attempts
        self.pending: List[SendJob] = []
        self.sent = 0
        self.retried = 0
        self._task: Optional[asyncio.Task] = None

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._worker())

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def enqueue(self, job: SendJob):
        await self.queue.put(job)

    async def _worker(self):
        await self.client.wait_until_ready()
        while not self.client.is_closed():
            job = await self.queue.get()
            try:
                await self._deliver(job)
            finally:
                self.queue.task_done()

    async def _deliver(self, job: SendJob):
        channel = self.client.get_channel(job.channel_id)
        if channel is None:
            return
        await self.bucket.acquire()
        try:
            kwargs = {"allowed_mentions": discord.AllowedMentions(everyone=False, roles=False, users=True)}
            if job.reply_to:
                kwargs["reference"] = channel.get_partial_message(job.reply_to)
            await channel.send(job.content, **kwargs)
            self.sent += 1
        except discord.HTTPException as exc:
            job.attempts += 1
            self.retried += 1
            retry_after = float(getattr(exc, "retry_after", 0) or 0)
            if getattr(exc, "status", 0) == 429 and job.attempts <= self.max_attempts:
                await asyncio.sleep(max(0.5, retry_after))
                await self.queue.put(job)
                return
            if job.attempts <= self.max_attempts:
                await asyncio.sleep(min(8.0, 1.5 * job.attempts))
                await self.queue.put(job)
                return
            self.pending.append(job)
        except Exception:
            job.attempts += 1
            if job.attempts <= self.max_attempts:
                await self.queue.put(job)
            else:
                self.pending.append(job)

    def stats(self) -> Dict[str, int]:
        return {"queued": self.queue.qsize(), "sent": self.sent, "retried": self.retried,
                "pending": len(self.pending)}
