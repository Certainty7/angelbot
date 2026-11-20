"""Database correctness: LIKE escaping, one-time migrations, FTS hygiene, Arabic search.

C-020, C-021, C-022, C-023, P-002.
"""
import asyncio
import os
import tempfile
import unittest

from angel.database import BotDatabase


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


class ForgetKeywordTest(unittest.TestCase):
    """C-020: % and _ are literals in a keyword, not wildcards."""

    def test_percent_does_not_erase_everything(self):
        async def _run():
            path = _fresh_db()
            db = BotDatabase(path)
            try:
                await db.initialize()
                await db.add_exchange(42, "alpha secret", "reply one")
                await db.add_exchange(42, "beta normal", "reply two")
                await db.add_exchange(99, "other member", "reply three")
                await db.forget_user_keyword(42, "%")
                _, mine = await db.get_context_data(42)
                _, theirs = await db.get_context_data(99)
                return len(mine), len(theirs)
            finally:
                await db.close()
                os.unlink(path)

        mine, theirs = asyncio.run(_run())
        self.assertEqual(mine, 4, "a literal % must not match every row")
        self.assertEqual(theirs, 2)

    def test_a_real_keyword_still_removes_its_rows(self):
        async def _run():
            path = _fresh_db()
            db = BotDatabase(path)
            try:
                await db.initialize()
                await db.add_exchange(42, "alpha secret", "reply one")
                await db.add_exchange(42, "beta normal", "reply two")
                await db.forget_user_keyword(42, "alpha")
                _, mine = await db.get_context_data(42)
                return mine
            finally:
                await db.close()
                os.unlink(path)

        rows = asyncio.run(_run())
        self.assertFalse(any("alpha" in row["content"] for row in rows))


class MigrationTest(unittest.TestCase):
    """C-021 / P-003: initialize() must be idempotent and non-destructive."""

    def test_a_short_summary_survives_a_second_initialize(self):
        async def _run():
            path = _fresh_db()
            db = BotDatabase(path)
            try:
                await db.initialize()
                async with db._connect() as conn:
                    await conn.execute(
                        "INSERT INTO user_summaries (user_id, summary) VALUES (42, ?)",
                        ("يحب القهوة",),
                    )
                    await conn.commit()
                await db.close()
                db = BotDatabase(path)
                await db.initialize()
                summary, _ = await db.get_context_data(42)
                return summary
            finally:
                await db.close()
                os.unlink(path)

        self.assertEqual(asyncio.run(_run()), "يحب القهوة")

    def test_migrations_are_recorded(self):
        async def _run():
            path = _fresh_db()
            db = BotDatabase(path)
            try:
                await db.initialize()
                async with db._connect() as conn:
                    cur = await conn.execute("PRAGMA user_version")
                    return (await cur.fetchone())[0]
            finally:
                await db.close()
                os.unlink(path)

        self.assertGreaterEqual(asyncio.run(_run()), 3)

    def test_legacy_dossier_rows_are_cleared_once(self):
        async def _run():
            path = _fresh_db()
            db = BotDatabase(path)
            try:
                await db.initialize()
                async with db._connect() as conn:
                    await conn.execute(
                        "INSERT OR REPLACE INTO user_dossier (user_id, summary) VALUES (7, 'legacy')"
                    )
                    await conn.execute("PRAGMA user_version = 1")
                    await conn.commit()
                await db.close()
                db = BotDatabase(path)
                await db.initialize()
                return await db.get_user_dossier(7)
            finally:
                await db.close()
                os.unlink(path)

        self.assertIsNone(asyncio.run(_run()))


class RulesIndexTest(unittest.TestCase):
    """C-022: a deletion must not leave a ghost row in the FTS index."""

    def test_delete_trigger_removes_the_index_row(self):
        async def _run():
            path = _fresh_db()
            db = BotDatabase(path)
            try:
                await db.initialize()
                await db.replace_rules(1, [("قاعدة 1", "spam is forbidden")])
                before = await db.search_rules(1, "spam", 3)
                await db.clear_rules(1)
                after = await db.search_rules(1, "spam", 3)
                return before, after
            finally:
                await db.close()
                os.unlink(path)

        before, after = asyncio.run(_run())
        self.assertTrue(before)
        self.assertEqual(after, [], "a deleted rule must not still match")

    def test_replace_is_atomic(self):
        async def _run():
            path = _fresh_db()
            db = BotDatabase(path)
            try:
                await db.initialize()
                await db.replace_rules(1, [("قاعدة 1", "keep this rule")])
                with self.assertRaises(Exception):
                    await db.replace_rules(1, [("قاعدة 1", "new rule"), ("bad", None)])
                return await db.search_rules(1, "keep", 3)
            finally:
                await db.close()
                os.unlink(path)

        self.assertTrue(asyncio.run(_run()), "a failed replace must leave the old rules intact")


class ArabicSearchTest(unittest.TestCase):
    """C-023 / P-002: folded diacritics and a mandatory channel allow-list."""

    def test_diacritics_match_the_plain_word(self):
        async def _run():
            path = _fresh_db()
            db = BotDatabase(path)
            try:
                await db.initialize()
                await db.log_server_message(7, 8, 42, "member", "محمد كان هنا")
                return await db.search_archive(["مُحَمَّد"], limit=5, allowed_channels={8})
            finally:
                await db.close()
                os.unlink(path)

        self.assertTrue(asyncio.run(_run()), "a vocalised query must match the plain word")

    def test_search_without_a_channel_set_is_refused(self):
        async def _run():
            path = _fresh_db()
            db = BotDatabase(path)
            try:
                await db.initialize()
                await db.log_server_message(7, 8, 42, "member", "private ticket text")
                return await db.search_archive(["private"], limit=5)
            finally:
                await db.close()
                os.unlink(path)

        self.assertEqual(asyncio.run(_run()), [])

    def test_fts_operators_do_not_raise(self):
        async def _run():
            path = _fresh_db()
            db = BotDatabase(path)
            try:
                await db.initialize()
                await db.log_server_message(7, 8, 42, "member", "hello world")
                return await db.search_archive(
                    ["NOT", '"unclosed', "content:"], limit=5, allowed_channels={8}
                )
            finally:
                await db.close()
                os.unlink(path)

        self.assertIsInstance(asyncio.run(_run()), list)


if __name__ == "__main__":
    unittest.main()
