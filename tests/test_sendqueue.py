"""Sender queue accounting (C-030).

The queue is bounded on purpose; the regression is that a dropped job must be recorded, not
silently discarded.
"""
import asyncio
import unittest
from unittest.mock import MagicMock

from angel.sendqueue import SendJob, Sender


class SendQueueTest(unittest.TestCase):
    def _sender(self):
        client = MagicMock()
        client.is_closed.return_value = False
        sender = Sender(client, capacity=5, rate_per_sec=10.0, max_queue=2)
        return sender

    def test_an_overflow_is_recorded_as_a_dead_letter(self):
        async def _run():
            sender = self._sender()
            for index in range(4):
                await sender.enqueue(SendJob(channel_id=1, content=f"m{index}"))
            dead = list(sender.dead_letters)
            # The worker never started (no ready client), so the queue overflowed.
            for worker in sender._workers.values():
                if worker.task is not None:
                    worker.task.cancel()
            await asyncio.gather(
                *(w.task for w in sender._workers.values() if w.task is not None),
                return_exceptions=True,
            )
            return dead

        dead = asyncio.run(_run())
        self.assertTrue(dead, "an overflowing queue must not drop jobs silently")
        self.assertLessEqual(len(dead), 100)

    def test_a_stopped_sender_records_the_job(self):
        async def _run():
            sender = self._sender()
            sender._stopped = True
            await sender.enqueue(SendJob(channel_id=1, content="after stop"))
            return list(sender.dead_letters)

        dead = asyncio.run(_run())
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0].content, "after stop")


if __name__ == "__main__":
    unittest.main()
