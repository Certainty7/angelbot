"""Audit finding 20c: identity must be the snowflake, not the text.

`backfill_history.ensure_schema` created a unique index on
`(channel_id, user_id, created_at, content)`. Two different messages with the same author, text
and second — a repeated "👍" — collapsed into one row, and the runtime schema never agreed with
the tool schema. The legacy index is dropped and both tools insert with
`ON CONFLICT(message_id) DO NOTHING`.
"""

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
    content="👍",
    created_at="2026-01-01T00:00:00+00:00",
)


class ArchiveIdentityTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute(
            "CREATE TABLE server_messages (id INTEGER PRIMARY KEY, guild_id INTEGER, channel_id INTEGER,"
            " user_id INTEGER, display_name TEXT, content TEXT, created_at TEXT, message_id TEXT)"
        )
        self.db.execute(
            "CREATE UNIQUE INDEX idx_srv_msg_unique ON server_messages"
            " (channel_id, user_id, created_at, content)"
        )

    def _indexes(self):
        return {r[1] for r in self.db.execute("PRAGMA index_list(server_messages)")}

    def test_the_legacy_index_is_dropped(self):
        backfill_history.ensure_schema(self.db)
        self.assertNotIn("idx_srv_msg_unique", self._indexes())

    def test_two_identical_messages_with_different_snowflakes_both_survive(self):
        backfill_history.ensure_schema(self.db)
        first = backfill_history.insert_message(self.db, message_id="1", **ROW)
        second = fetch_all_history.insert_message(self.db, message_id="2", **ROW)
        self.assertEqual((first, second), (1, 1))
        self.assertEqual(self.db.execute("select count(*) from server_messages").fetchone()[0], 2)

    def test_the_same_snowflake_is_still_written_once(self):
        backfill_history.ensure_schema(self.db)
        self.assertEqual(backfill_history.insert_message(self.db, message_id="1", **ROW), 1)
        self.assertEqual(backfill_history.insert_message(self.db, message_id="1", **ROW), 0)


if __name__ == "__main__":
    unittest.main()
