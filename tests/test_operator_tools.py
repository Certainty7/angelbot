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

import evolve_persona  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
