"""Audit finding 20d: the 365-day promise must survive a direct backfill.

The archive was pruned on a 1-in-500 insert, so a bulk backfill could import rows far older than
the published year and keep them until the counter happened to hit 500. Pruning now belongs to
the daily retention pass, `created_at` is indexed so the delete is cheap, and the import tools
refuse a row that is already outside the window.
"""

import asyncio
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from angel.database import BotDatabase  # noqa: E402
from tools import backfill_history  # noqa: E402

OLD = (datetime.now(timezone.utc) - timedelta(days=366)).isoformat(timespec="seconds")
FRESH = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
ROW = dict(
    guild_id=1, channel_id=2, user_id=3, display_name="m", content="hi",
)


class ArchiveRetentionTest(unittest.TestCase):
    def _db(self):
        path = Path(tempfile.mkdtemp(prefix="angel_ret_")) / "db.sqlite"
        return BotDatabase(path)

    def test_the_daily_pass_prunes_rows_past_the_year(self):
        async def _run():
            db = self._db()
            await db.initialize()
            try:
                async with db._connect() as c:
                    await c.execute(
                        "INSERT INTO server_messages (guild_id, channel_id, user_id, display_name,"
                        " content, created_at, message_id) VALUES (?,?,?,?,?,?,?)",
                        (1, 2, 3, "m", "old", OLD, "1"),
                    )
                    await c.execute(
                        "INSERT INTO server_messages (guild_id, channel_id, user_id, display_name,"
                        " content, created_at, message_id) VALUES (?,?,?,?,?,?,?)",
                        (1, 2, 3, "m", "fresh", FRESH, "2"),
                    )
                    await c.execute("DELETE FROM state WHERE key = 'retention_day'")
                    await db._apply_retention(c)
                    await c.commit()
                    async with c.execute("SELECT content FROM server_messages ORDER BY message_id") as cur:
                        return [r[0] for r in await cur.fetchall()]
            finally:
                await db.close()

        self.assertEqual(asyncio.run(_run()), ["fresh"])

    def test_created_at_is_indexed(self):
        async def _run():
            db = self._db()
            await db.initialize()
            try:
                async with db._connect() as c:
                    async with c.execute("PRAGMA index_list(server_messages)") as cur:
                        return {r[1] for r in await cur.fetchall()}
            finally:
                await db.close()

        self.assertIn("idx_srv_msg_created", asyncio.run(_run()))

    def test_the_backfill_refuses_a_row_outside_the_window(self):
        db = sqlite3.connect(":memory:")
        backfill_history.ensure_schema(db)
        self.assertEqual(backfill_history.insert_message(db, message_id="1", created_at=OLD, **ROW), 0)
        self.assertEqual(backfill_history.insert_message(db, message_id="2", created_at=FRESH, **ROW), 1)


if __name__ == "__main__":
    unittest.main()
