"""Privacy lifecycle: opt-out, `/data delete`, and the schema-driven deletion contract.

C-006, P-004, plus the guard that a new user-bearing table cannot be added silently.
"""
import asyncio
import os
import tempfile
import unittest

from angel.database import BotDatabase


def _fresh():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


async def _with_db(fn):
    path = _fresh()
    db = BotDatabase(path)
    try:
        await db.initialize()
        return await fn(db)
    finally:
        await db.close()
        os.unlink(path)


class OptOutTest(unittest.TestCase):
    def test_writes_are_refused_after_opt_out(self):
        async def _run(db):
            await db.delete_all_user_data(42)
            await db.add_xp(1, 42, 100)
            await db.add_exchange(42, "hello", "hi")
            await db.touch_user_index(1, 42, "member", "topic")
            await db.log_ambient(1, 2, 42, "ambient line")
            await db.log_server_message(1, 2, 42, "member", "archived line")
            await db.log_dm(42, "member", "dm line", "", "reply")
            counts = await db.count_user_data(42)
            return counts

        counts = asyncio.run(_with_db(_run))
        for table in ("user_xp", "messages", "user_index", "ambient_log",
                      "server_messages", "dm_logs"):
            self.assertEqual(counts[table], 0, f"{table} was re-created after opt-out")

    def test_a_member_who_never_opted_out_is_still_stored(self):
        async def _run(db):
            await db.add_xp(1, 7, 100)
            await db.log_server_message(1, 2, 7, "member", "hello")
            return await db.count_user_data(7)

        counts = asyncio.run(_with_db(_run))
        self.assertEqual(counts["user_xp"], 1)
        self.assertEqual(counts["server_messages"], 1)


class DeletionTest(unittest.TestCase):
    def test_every_personal_store_is_erased(self):
        async def _run(db):
            await db.add_xp(1, 42, 500)
            await db.add_exchange(42, "private line", "reply")
            await db.touch_user_index(1, 42, "member", "topic")
            await db.log_ambient(1, 2, 42, "ambient line")
            await db.log_server_message(1, 2, 42, "member", "archived line")
            await db.log_dm(42, "member", "dm line", "", "reply")
            await db.set_afk(1, 42, "busy")
            await db.add_harem_member(42, "member", "title")
            await db.set_persona_culture(1, '{"notes": ["said something"]}')
            before = await db.count_user_data(42)
            deleted = await db.delete_all_user_data(42)
            after = await db.count_user_data(42)
            return before, deleted, after

        before, deleted, after = asyncio.run(_with_db(_run))
        self.assertGreater(before["user_xp"], 0)
        for table, value in after.items():
            self.assertEqual(value, 0, f"{table} survived /data delete")
        self.assertIn("harem_members", deleted)

    def test_the_reply_counts_match_the_deletion_set(self):
        async def _run(db):
            await db.log_dm(42, "member", "dm line", "", "reply")
            counts = await db.count_user_data(42)
            return counts

        counts = asyncio.run(_with_db(_run))
        expected = set(BotDatabase.USER_DATA_TABLES)
        self.assertEqual(set(counts), expected,
                         "count_user_data must report exactly the tables that are deleted")


class DeletionCoverageTest(unittest.TestCase):
    """A new table with a member column must be classified, or this fails."""

    MEMBER_COLUMNS = {"user_id", "sender_id", "author_id", "moderator_id", "added_by"}

    def test_schema_is_fully_classified(self):
        async def _run(db):
            rows = []
            async with db._connect() as conn:
                async with conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ) as cur:
                    tables = [r[0] for r in await cur.fetchall()]
                for table in tables:
                    async with conn.execute(f"PRAGMA table_info({table})") as cur:
                        columns = {r[1] for r in await cur.fetchall()}
                    rows.append((table, columns))
            return rows

        schema = asyncio.run(_with_db(_run))
        known = set(BotDatabase.USER_DATA_TABLES) | set(BotDatabase.USER_DATA_EXEMPT)
        members = {t for t, cols in schema if cols & self.MEMBER_COLUMNS}
        unclassified = sorted(members - known)
        self.assertFalse(
            unclassified,
            "user-bearing tables with no deletion policy: " + ", ".join(unclassified),
        )
        present = {t for t, _cols in schema}
        missing = sorted(set(BotDatabase.USER_DATA_TABLES) - present)
        self.assertFalse(missing, "deletion map references tables that no longer exist: "
                         + ", ".join(missing))


if __name__ == "__main__":
    unittest.main()
