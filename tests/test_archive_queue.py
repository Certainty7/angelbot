"""Audit finding 10: archive work must be a bounded queue with observed failures and a drain.

Today every guild message creates a fire-and-forget task in `_bg_tasks`: a blocked database
turned into 1,000 pending tasks, failures surfaced as "Task exception was never retrieved",
and shutdown cancelled in-flight work so the rows were never written.
"""

import asyncio
import pathlib
import unittest

from angel.work_queue import BoundedWorkQueue

REPO = pathlib.Path(__file__).resolve().parent.parent

CAPACITY = 256


def _run(coro):
    return asyncio.run(coro)


class CapacityTest(unittest.TestCase):
    def test_a_thousand_blocked_messages_queue_exactly_the_capacity(self):
        async def scenario():
            release = asyncio.Event()

            async def blocked(job_id):
                await release.wait()

            queue = BoundedWorkQueue("archive", capacity=CAPACITY)
            await queue.start()
            accepted = [queue.submit(i, lambda i=i: blocked(i)) for i in range(1000)]
            await asyncio.sleep(0)
            queued = queue.depth
            release.set()
            await queue.drain(timeout=5)
            return sum(accepted), queued, len(accepted) - sum(accepted)

        accepted_count, queued, rejected = _run(scenario())

        self.assertEqual(accepted_count, CAPACITY)
        self.assertLessEqual(queued, CAPACITY)
        self.assertEqual(rejected, 744)

    def test_a_rejected_message_id_is_logged(self):
        async def scenario():
            release = asyncio.Event()

            async def blocked(job_id):
                await release.wait()

            queue = BoundedWorkQueue("archive", capacity=2)
            await queue.start()
            queue.submit(11, lambda: blocked(11))
            queue.submit(22, lambda: blocked(22))
            with self.assertLogs("angel.work_queue", level="WARNING") as logs:
                accepted = queue.submit(33, lambda: blocked(33))
            release.set()
            await queue.drain(timeout=5)
            return accepted, logs.output

        accepted, output = _run(scenario())

        self.assertFalse(accepted)
        self.assertTrue(any("33" in line for line in output), output)

    def test_a_rejected_coroutine_is_closed(self):
        async def scenario():
            release = asyncio.Event()

            async def blocked(job_id):
                await release.wait()

            queue = BoundedWorkQueue("archive", capacity=1)
            await queue.start()
            queue.submit(1, lambda: blocked(1))
            pending = blocked(2)
            queue.submit(2, lambda: pending)
            release.set()
            await queue.drain(timeout=5)
            return pending

        coro = _run(scenario())

        self.assertIsNone(coro.cr_frame)


class FailureTest(unittest.TestCase):
    def test_a_failure_is_logged_and_the_next_job_still_runs(self):
        async def scenario():
            done = asyncio.Event()
            seen = []

            async def boom():
                raise RuntimeError("disk full")

            async def fine(job_id):
                seen.append(job_id)
                done.set()

            queue = BoundedWorkQueue("archive", capacity=8)
            await queue.start()
            with self.assertLogs("angel.work_queue", level="ERROR") as logs:
                queue.submit(7, boom)
                queue.submit(8, lambda: fine(8))
                try:
                    await asyncio.wait_for(done.wait(), timeout=5)
                finally:
                    await queue.drain(timeout=5)
            return seen, logs.output

        seen, output = _run(scenario())

        self.assertEqual(seen, [8])
        self.assertTrue(any("7" in line and "disk full" in line for line in output), output)


class DrainTest(unittest.TestCase):
    def test_a_graceful_drain_processes_every_accepted_job(self):
        async def scenario():
            seen = []

            async def work(job_id):
                await asyncio.sleep(0)
                seen.append(job_id)

            queue = BoundedWorkQueue("archive", capacity=32)
            await queue.start()
            for i in range(20):
                queue.submit(i, lambda i=i: work(i))
            unsent = await queue.drain(timeout=5)
            return seen, unsent

        seen, unsent = _run(scenario())

        self.assertEqual(sorted(seen), list(range(20)))
        self.assertEqual(unsent, [])

    def test_a_slow_drain_reports_the_jobs_it_could_not_finish(self):
        async def scenario():
            release = asyncio.Event()

            async def stuck(job_id):
                await release.wait()

            queue = BoundedWorkQueue("archive", capacity=8)
            await queue.start()
            queue.submit(101, lambda: stuck(101))
            queue.submit(102, lambda: stuck(102))
            await asyncio.sleep(0)
            unsent = await queue.drain(timeout=0.05)
            release.set()
            return unsent

        unsent = _run(scenario())

        self.assertEqual(sorted(unsent), [101, 102])


class PipelineWiringTest(unittest.TestCase):
    """The message path must go through the queue, not through a bare task per message."""

    def test_the_pipeline_submits_instead_of_spawning_tasks(self):
        source = (REPO / "bot.py").read_text(encoding="utf-8")

        self.assertNotIn("create_task(bot.db.log_server_message", source)
        self.assertNotIn("create_task(memory.touch", source)
        self.assertEqual(source.count("bot.work_queue.submit("), 2)
