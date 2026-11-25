"""Audit finding 19c: the FFmpeg transcode must be capped while it writes.

The output was only checked after FFmpeg finished, so a long or malformed input could fill the
temp volume before the size gate ran. `-fs` stops the muxer at the cap; the post-check stays as
a second line of defence.
"""

import asyncio
import os
import stat
import tempfile
import unittest
from unittest import mock

from angel import media

MIB = 1024 * 1024

STUB = """#!/bin/sh
out=""
fs=""
prev=""
for a in "$@"; do
  if [ "$prev" = "-fs" ]; then fs="$a"; fi
  prev="$a"
done
for a in "$@"; do out="$a"; done
limit=4194304
if [ -n "$fs" ]; then limit="$fs"; fi
head -c "$limit" /dev/zero > "$out"
exit 0
"""


class TranscodeCapTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="angel_ff_")
        self.stub = os.path.join(self.dir, "ffmpeg")
        with open(self.stub, "w") as fh:
            fh.write(STUB)
        os.chmod(self.stub, os.stat(self.stub).st_mode | stat.S_IEXEC)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.dir, True)

    def _run(self, max_bytes):
        payload = b"\x00\x00\x00\x20ftypisom" + b"hvc1" + b"\x00" * (500 * 1024)
        with mock.patch.object(media, "FFMPEG_EXE", self.stub):
            return asyncio.run(media._ensure_discord_playable_mp4(payload, max_bytes=max_bytes))

    def test_the_output_is_capped_at_the_limit(self):
        out = self._run(1 * MIB)
        self.assertEqual(len(out), 1 * MIB)

    def test_the_post_check_still_refuses_an_oversized_file(self):
        out = self._run(64 * 1024)
        self.assertLessEqual(len(out), 64 * 1024)


if __name__ == "__main__":
    unittest.main()
