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
            timed_out = False
            try:
                await read_bounded_subprocess_stdout(proc, timeout=0.4)
            except asyncio.TimeoutError:
                timed_out = True
            for _ in range(50):
                if proc.returncode is not None:
                    break
                await asyncio.sleep(0.05)
            return timed_out, proc.returncode

        timed_out, returncode = asyncio.run(_run())
        # The old assertion accepted `0`: a reader that ignored its timeout let the child
        # exit normally after 30 seconds and the test still passed.
        self.assertTrue(timed_out, "the reader ignored its timeout")
        self.assertIsNotNone(returncode, "the child was still running after the timeout")
        self.assertNotEqual(returncode, 0)


if __name__ == "__main__":
    unittest.main()
