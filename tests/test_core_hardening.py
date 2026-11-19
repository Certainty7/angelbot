"""Core data-path tests: guild quota, settings, erasure and the scam guard."""
import asyncio
import os
import tempfile
import unittest

from angel.database import BotDatabase
from angel.guard import is_suspicious_arabic_scam


class TestGuildQuota(unittest.TestCase):
    def test_settings_round_trip_and_atomic_quota(self):
        async def _run():
            fd, path = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            db = BotDatabase(path)
            try:
                await db.initialize()
                await db.upsert_guild_settings(
                    guild_id=1, dialect="egyptian", guard_level="active",
                    social_fixer_enabled=False)
                settings = await db.get_guild_settings(1)
                self.assertEqual(settings["dialect"], "egyptian")
                self.assertEqual(settings["guard_level"], "active")
                self.assertEqual(int(settings["social_fixer_enabled"]), 0)

                # A partial update must not reset the fields it did not touch.
                await db.upsert_guild_settings(guild_id=1, social_fixer_enabled=True)
                settings = await db.get_guild_settings(1)
                self.assertEqual(settings["dialect"], "egyptian")
                self.assertEqual(settings["guard_level"], "active")
                self.assertEqual(int(settings["social_fixer_enabled"]), 1)

                # Lower the limit to one and race two calls: exactly one may pass.
                async with db._connect() as conn:
                    await conn.execute(
                        "UPDATE guild_settings SET daily_ai_limit = 1 WHERE guild_id = 1")
                    await conn.commit()
                results = await asyncio.gather(
                    db.consume_guild_ai_quota(1), db.consume_guild_ai_quota(1))
                self.assertEqual(sum(1 for allowed, _used in results if allowed), 1)
                self.assertEqual({used for _allowed, used in results}, {1})
            finally:
                await db.close()
                os.unlink(path)

        asyncio.run(_run())

    def test_data_delete_purges_fts_and_rows(self):
        async def _run():
            fd, path = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            db = BotDatabase(path)
            try:
                await db.initialize()
                unique = "zzdeletetoken"
                await db.log_server_message(7, 8, 42, "member", f"hello {unique}")
                hits = await db.search_archive([unique], limit=5)
                self.assertTrue(hits, "message should be archived before deletion")
                await db.delete_all_user_data(42)
                hits_after = await db.search_archive([unique], limit=5)
                self.assertFalse(hits_after, "FTS must not recall a deleted member")
                counts = await db.count_user_data(42)
                self.assertEqual(counts["archived_messages"], 0)
                self.assertTrue((await db.get_user_prefs(42)).get("opt_out"))
            finally:
                await db.close()
                os.unlink(path)

        asyncio.run(_run())

    def test_arabizi_scam_guard(self):
        self.assertTrue(is_suspicious_arabic_scam("اربح 500 دولار مجانا https://x.example"))
        self.assertTrue(is_suspicious_arabic_scam("نيتـرو مجاني هدية"))
        self.assertFalse(is_suspicious_arabic_scam("السلام عليكم كيف حالكم اليوم"))


if __name__ == "__main__":
    unittest.main()
