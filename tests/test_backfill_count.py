"""Audit finding 20b: an ignored INSERT is not saved work.

Both import tools incremented their counters after `INSERT OR IGNORE`, so a duplicate snowflake
or an opted-out member counted toward the hard cap. A capped run then stopped while real rows
were still missing, and the summary overstated what the archive held.
"""

import os
import sqlite3
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import backfill_history, fetch_all_history  # noqa: E402

ROW = dict(
    guild_id=1,
    channel_id=2,
    user_id=3,
    display_name="m",
    content="hello",
    created_at="2026-01-01T00:00:00+00:00",
    message_id="900",
)


class InsertCounterTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        backfill_history.ensure_schema(self.db)

    def _insert(self, module, **over):
        row = dict(ROW)
        row.update(over)
        return module.insert_message(self.db, **row)

    def test_both_tools_report_a_fresh_row_as_written(self):
        self.assertEqual(self._insert(backfill_history), 1)
        self.assertEqual(self._insert(fetch_all_history, message_id="901", content="hello2"), 1)

    def test_a_duplicate_snowflake_is_not_written(self):
        self._insert(backfill_history)
        self.assertEqual(self._insert(backfill_history), 0)

    def test_an_opted_out_member_is_not_written(self):
        self.db.execute(
            "INSERT INTO user_preferences (user_id, opt_out) VALUES (?, 1)", (ROW["user_id"],)
        )
        self.assertEqual(self._insert(backfill_history), 0)


if __name__ == "__main__":
    unittest.main()
