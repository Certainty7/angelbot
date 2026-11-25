"""Audit finding 12: a yt-dlp timeout must take the whole process tree down.

`proc.kill()` signals the direct extractor only; yt-dlp spawns Deno and other helpers that
keep burning CPU and network after the timeout. The fix isolates the extractor in its own
session and signals the group on POSIX, `taskkill /T` on Windows.
"""

import asyncio
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from angel.downloader import (
    _windows_taskkill_argv,
    read_bounded_subprocess_stdout,
    subprocess_session_kwargs,
    terminate_process_tree,
)

POSIX = os.name == "posix"


def _run(coro):
    return asyncio.run(coro)


def _alive(pid: int) -> bool:
    if POSIX:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, check=False,
    ).stdout
    return str(pid) in out


def _wait_dead(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


class SessionTest(unittest.TestCase):
    def test_posix_spawns_in_its_own_session(self):
        kwargs = subprocess_session_kwargs()
        if POSIX:
            self.assertEqual(kwargs, {"start_new_session": True})
        else:
            self.assertEqual(kwargs, {})

    def test_windows_uses_argv_taskkill_without_a_shell(self):
        self.assertEqual(
            _windows_taskkill_argv(4242), ["taskkill", "/PID", "4242", "/T", "/F"]
        )


class TreeTest(unittest.TestCase):
    def test_timeout_kills_the_grandchild_too(self):
        tmp = Path(tempfile.mkdtemp(prefix="angel-tree-"))
        pid_file = tmp / "child.pid"
        parent_code = (
            "import subprocess,sys,pathlib,time;"
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']);"
            f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid));"
            "time.sleep(120)"
        )

        async def scenario():
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", parent_code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **subprocess_session_kwargs(),
            )
            for _ in range(200):
                if pid_file.exists():
                    break
                await asyncio.sleep(0.02)
            child_pid = int(pid_file.read_text())
            parent_pid = proc.pid
            try:
                await read_bounded_subprocess_stdout(proc, timeout=0.5)
            except asyncio.TimeoutError:
                pass
            terminate_process_tree(proc)
            await asyncio.wait_for(proc.wait(), timeout=5)
            return parent_pid, child_pid

        parent_pid, child_pid = _run(scenario())

        self.assertTrue(_wait_dead(parent_pid), "the parent survived the timeout")
        self.assertTrue(_wait_dead(child_pid), "the grandchild survived the timeout")

    def test_cancellation_kills_the_grandchild_too(self):
        tmp = Path(tempfile.mkdtemp(prefix="angel-tree-"))
        pid_file = tmp / "child.pid"
        parent_code = (
            "import subprocess,sys,pathlib,time;"
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']);"
            f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid));"
            "time.sleep(120)"
        )

        async def scenario():
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", parent_code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **subprocess_session_kwargs(),
            )
            for _ in range(200):
                if pid_file.exists():
                    break
                await asyncio.sleep(0.02)
            child_pid = int(pid_file.read_text())
            task = asyncio.create_task(read_bounded_subprocess_stdout(proc, timeout=60))
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            terminate_process_tree(proc)
            await asyncio.wait_for(proc.wait(), timeout=5)
            return proc.pid, child_pid

        parent_pid, child_pid = _run(scenario())

        self.assertTrue(_wait_dead(parent_pid), "the parent survived cancellation")
        self.assertTrue(_wait_dead(child_pid), "the grandchild survived cancellation")

    @unittest.skipUnless(POSIX, "process groups are a POSIX concept")
    def test_a_shared_group_process_is_never_group_killed(self):
        """If the child shares our group, killpg would kill the test runner itself."""

        async def scenario():
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", "import time; time.sleep(60)",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            terminate_process_tree(proc)
            await asyncio.wait_for(proc.wait(), timeout=5)
            return proc.pid, os.getpid()

        target_pid, own_pid = _run(scenario())

        self.assertTrue(_wait_dead(target_pid), "the shared-group child was not reaped")
        self.assertTrue(_alive(own_pid), "terminate_process_tree killed its own group")
