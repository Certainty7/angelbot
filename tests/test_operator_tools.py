"""Operator tools must honour the same privacy rules as the bot (C-005)."""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import backfill_history  # noqa: E402
import evolve_persona  # noqa: E402
import fetch_all_history  # noqa: E402


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _database():
    path = os.path.join(tempfile.mkdtemp(prefix="angel-tool-"), "angel.db")
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE user_preferences (user_id INTEGER PRIMARY KEY, opt_out INTEGER DEFAULT 0);
        CREATE TABLE server_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL, user_id INTEGER NOT NULL, display_name TEXT,
            content TEXT NOT NULL, created_at TEXT NOT NULL, message_id TEXT
        );
        INSERT INTO user_preferences (user_id, opt_out) VALUES (2, 1);
        INSERT INTO user_preferences (user_id, opt_out) VALUES (7, 0);
        INSERT INTO server_messages (guild_id, channel_id, user_id, display_name, content, created_at)
            VALUES (1, 10, 2, 'opted', 'PRIVATE-OPTED-OUT-TEXT', '2026-11-20T10:00:00+00:00');
        INSERT INTO server_messages (guild_id, channel_id, user_id, display_name, content, created_at)
            VALUES (1, 10, 7, 'member', 'ordinary line', '2026-11-20T10:01:00+00:00');
        """
    )
    db.commit()
    db.close()
    return path


class EvolvePersonaTest(unittest.TestCase):
    def _run(self, payload):
        path = _database()
        captured = {}

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.data.decode())
            return _FakeResponse(json.dumps(payload).encode())

        env = {
            "ANGEL_DB_PATH": path,
            "GEMINI_API_KEY": "test-key-not-real",
            "ANGEL_PERSONA_CHANNEL_ID": "10",
        }
        with patch.dict(os.environ, env, clear=False), \
                patch("urllib.request.urlopen", fake_urlopen):
            code = evolve_persona.main()

        db = sqlite3.connect(path)
        try:
            row = db.execute("SELECT notes_json FROM persona_culture").fetchone()
        except sqlite3.Error:
            row = None
        db.close()
        return code, captured, row

    def test_opted_out_text_never_enters_the_prompt(self):
        code, captured, _row = self._run({
            "candidates": [{"content": {"parts": [{"text": '{"tone": "هادئ"}'}]}}]
        })
        self.assertEqual(code, 0)
        sent = json.dumps(captured["body"], ensure_ascii=False)
        self.assertNotIn("PRIVATE-OPTED-OUT-TEXT", sent)
        self.assertIn("ordinary line", sent)

    def test_the_key_travels_in_a_header(self):
        _code, captured, _row = self._run({
            "candidates": [{"content": {"parts": [{"text": '{"tone": "هادئ"}'}]}}]
        })
        header_names = {k.lower() for k in captured["headers"]}
        self.assertIn("x-goog-api-key", header_names)
        self.assertNotIn("key=", captured["url"])

    def test_refuses_without_a_pinned_channel(self):
        path = _database()
        captured = []

        def fake_urlopen(request, timeout=0):
            captured.append(request)
            return _FakeResponse(b"{}")

        env = {"ANGEL_DB_PATH": path, "GEMINI_API_KEY": "test-key-not-real"}
        env.pop("ANGEL_PERSONA_CHANNEL_ID", None)
        with patch.dict(os.environ, env, clear=False), \
                patch("urllib.request.urlopen", fake_urlopen):
            os.environ.pop("ANGEL_PERSONA_CHANNEL_ID", None)
            code = evolve_persona.main()
        self.assertEqual(code, 2)
        self.assertEqual(captured, [], "the tool reached the network without an allowed channel")

    def test_a_non_object_payload_is_rejected(self):
        code, _captured, row = self._run({
            "candidates": [{"content": {"parts": [{"text": "[1, 2, 3]"}]}}]
        })
        self.assertEqual(code, 1)
        self.assertIsNone(row, "a list payload must not be stored")


class FetchHistorySchemaTest(unittest.TestCase):
    """The fetch tool must create `user_preferences` before its guarded inserts (C-005).

    Without the table every insert raised `no such table`, the old handler swallowed it,
    and pages were marked done with nothing stored — a rerun never re-fetched them.
    """

    def _fresh_db(self):
        path = os.path.join(tempfile.mkdtemp(prefix="angel-fetch-"), "fetch.db")
        return path

    def test_ensure_schema_creates_the_opt_out_table_on_a_brand_new_database(self):
        path = self._fresh_db()
        db = sqlite3.connect(path)
        try:
            fetch_all_history.ensure_schema(db)
            tables = {
                r[0] for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("user_preferences", tables)
            # The exact guarded insert the tool runs must succeed on this schema.
            db.execute(
                "INSERT OR IGNORE INTO server_messages "
                "(guild_id, channel_id, user_id, display_name, content, created_at, message_id) "
                "SELECT ?,?,?,?,?,?,? WHERE NOT EXISTS ("
                "SELECT 1 FROM user_preferences WHERE user_id = ? AND opt_out = 1)",
                (1, 2, 7, "member", "hello", "2026-11-20T00:00:00+00:00", "m1", 7),
            )
            db.commit()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM server_messages").fetchone()[0], 1)
        finally:
            db.close()

    def test_backfill_ensure_schema_creates_the_opt_out_table(self):
        path = self._fresh_db()
        db = sqlite3.connect(path)
        try:
            backfill_history.ensure_schema(db)
            tables = {
                r[0] for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("user_preferences", tables)
        finally:
            db.close()


class FetchHistoryFailureTest(unittest.TestCase):
    """A failed page must stay retryable and never duplicate the rows that did store."""

    def _msg(self, mid, content, timestamp="2026-11-20T12:00:00+00:00", uid=7):
        return {
            "id": mid, "content": content, "timestamp": timestamp,
            "author": {"id": str(uid), "bot": False, "global_name": "member"},
        }

    def _run_main(self, path, page):
        def fake_call(api_path, _tok):
            if api_path == "/users/@me/guilds":
                return [{"id": "1", "name": "guild"}]
            if api_path.startswith("/guilds/1/channels"):
                return [{"id": "10", "type": 0, "name": "room"}]
            if "before=" in api_path:
                return []  # the page before the cursor is exhausted
            return page

        with patch.object(fetch_all_history, "call", fake_call), \
                patch.object(fetch_all_history, "token", lambda: "tok"), \
                patch.object(fetch_all_history, "database_path", lambda: path):
            fetch_all_history.main()

    def test_a_page_with_one_bad_row_is_not_marked_done_and_reruns_cleanly(self):
        path = os.path.join(tempfile.mkdtemp(prefix="angel-fetchfail-"), "fail.db")
        # Row 1 has a malformed timestamp (the injected failure); row 2 is healthy.
        page = [self._msg("m1", "broken", timestamp="not-a-date"),
                self._msg("m2", "healthy")]

        self._run_main(path, page)

        db = sqlite3.connect(path)
        try:
            stored = db.execute("SELECT COUNT(*) FROM server_messages").fetchone()[0]
            state = db.execute("SELECT COUNT(*) FROM fetch_state").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(stored, 1, "the healthy row must be stored")
        self.assertEqual(state, 0, "a failed page was marked done and became unretryable")

        # A rerun retries the same page: the healthy row is not duplicated.
        self._run_main(path, page)
        db = sqlite3.connect(path)
        try:
            stored = db.execute("SELECT COUNT(*) FROM server_messages").fetchone()[0]
            state = db.execute("SELECT COUNT(*) FROM fetch_state").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(stored, 1, "the resume duplicated stored rows")
        self.assertEqual(state, 0)

    def test_a_clean_page_is_marked_done(self):
        path = os.path.join(tempfile.mkdtemp(prefix="angel-fetchok-"), "ok.db")
        page = [self._msg("m1", "one"), self._msg("m2", "two")]
        self._run_main(path, page)
        db = sqlite3.connect(path)
        try:
            stored = db.execute("SELECT COUNT(*) FROM server_messages").fetchone()[0]
            state = db.execute("SELECT oldest_id FROM fetch_state WHERE channel_id = 10").fetchone()
        finally:
            db.close()
        self.assertEqual(stored, 2)
        self.assertIsNotNone(state, "a clean page must advance the resume cursor")


if __name__ == "__main__":
    unittest.main()
