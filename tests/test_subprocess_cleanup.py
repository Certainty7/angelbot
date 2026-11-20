"""Cancellation must not leave yt-dlp/FFmpeg children alive (C-017)."""
import asyncio
import sys
import unittest

from angel.downloader import read_bounded_subprocess_stdout


class SubprocessCancellationTest(unittest.TestCase):
    def test_cancelling_the_reader_kills_the_child(self):
        async def _run():
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", "import time; time.sleep(30)",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            task = asyncio.create_task(
                read_bounded_subprocess_stdout(proc, timeout=60)
            )
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            for _ in range(50):
                if proc.returncode is not None:
                    break
                await asyncio.sleep(0.05)
            return proc.returncode

        returncode = asyncio.run(_run())
        self.assertIsNotNone(returncode, "the child was still running after cancellation")
        self.assertNotEqual(returncode, 0)

    def test_a_timeout_kills_the_child(self):
        async def _run():
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", "import time; time.sleep(30)",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await read_bounded_subprocess_stdout(proc, timeout=0.4)
            except asyncio.TimeoutError:
                pass
            for _ in range(50):
                if proc.returncode is not None:
                    break
                await asyncio.sleep(0.05)
            return proc.returncode

        self.assertIsNotNone(asyncio.run(_run()))


if __name__ == "__main__":
    unittest.main()
