"""Audit finding 6: rolling memory must be scoped to one conversation.

`messages` and `user_summaries` were keyed by `user_id` alone, so a DM sentinel appeared in
the next guild prompt and guild-A text reached a guild-B payload. Pinned facts stay
cross-room on purpose; everything else follows `(channel_id, user_id)`.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile

from angel.database import BotDatabase


def _fresh_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


DM, GUILD_A, GUILD_B = 900, 100, 200
USER = 42


async def _db() -> BotDatabase:
    db = BotDatabase(_fresh_path())
    await db.initialize()
    return db


def _contents(messages) -> str:
    return " | ".join(m["content"] for m in messages)


def test_dm_and_guild_memory_do_not_mix():
    async def _run():
        db = await _db()
        try:
            await db.add_exchange(DM, USER, "dm sentinel", "dm reply")
            await db.add_exchange(GUILD_A, USER, "guild a sentinel", "a reply")
            _, dm = await db.get_context_data(DM, USER)
            _, a = await db.get_context_data(GUILD_A, USER)
            _, b = await db.get_context_data(GUILD_B, USER)
            return _contents(dm), _contents(a), _contents(b)
        finally:
            await db.close()

    dm, a, b = asyncio.run(_run())
    assert "dm sentinel" in dm
    assert "guild a sentinel" not in dm
    assert "guild a sentinel" in a
    assert "dm sentinel" not in a
    assert b == "", "a third conversation must start empty"


def test_summaries_are_per_conversation():
    async def _run():
        db = await _db()
        try:
            await db.apply_summary_and_prune(GUILD_A, USER, "summary A", 0)
            await db.apply_summary_and_prune(GUILD_B, USER, "summary B", 0)
            sa, _ = await db.get_context_data(GUILD_A, USER)
            sb, _ = await db.get_context_data(GUILD_B, USER)
            return sa, sb
        finally:
            await db.close()

    assert asyncio.run(_run()) == ("summary A", "summary B")


def test_clear_only_affects_the_current_conversation():
    async def _run():
        db = await _db()
        try:
            await db.add_exchange(DM, USER, "dm secret", "r")
            await db.add_exchange(GUILD_A, USER, "guild secret", "r")
            await db.clear_user_memory(DM, USER)
            _, dm = await db.get_context_data(DM, USER)
            _, a = await db.get_context_data(GUILD_A, USER)
            return _contents(dm), _contents(a)
        finally:
            await db.close()

    dm, a = asyncio.run(_run())
    assert dm == ""
    assert "guild secret" in a


def test_forget_erases_every_conversation():
    async def _run():
        db = await _db()
        try:
            await db.add_exchange(DM, USER, "the token", "r")
            await db.add_exchange(GUILD_A, USER, "the token", "r")
            await db.apply_summary_and_prune(GUILD_A, USER, "remembers the token", 0)
            await db.forget_user_keyword(USER, "token")
            _, dm = await db.get_context_data(DM, USER)
            _, a = await db.get_context_data(GUILD_A, USER)
            sa, _ = await db.get_context_data(GUILD_A, USER)
            return _contents(dm), _contents(a), sa
        finally:
            await db.close()

    dm, a, summary = asyncio.run(_run())
    assert "token" not in dm and "token" not in a
    assert summary in (None, "")


def test_migration_v4_discards_legacy_mixed_rows():
    path = _fresh_path()
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE user_summaries (
            user_id INTEGER PRIMARY KEY,
            summary TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO messages (user_id, role, content) VALUES (42, 'user', 'legacy line');
        INSERT INTO user_summaries (user_id, summary) VALUES (42, 'legacy summary');
        PRAGMA user_version = 3;
        """
    )
    conn.commit()
    conn.close()

    async def _run():
        db = BotDatabase(path)
        await db.initialize()
        try:
            async with db._connect() as c:
                async with c.execute("PRAGMA user_version") as cur:
                    version = (await cur.fetchone())[0]
                async with c.execute("SELECT COUNT(*) FROM messages") as cur:
                    rows = (await cur.fetchone())[0]
                async with c.execute("SELECT COUNT(*) FROM user_summaries") as cur:
                    summaries = (await cur.fetchone())[0]
            await db.add_exchange(GUILD_A, 42, "fresh line", "reply")
            _, fresh = await db.get_context_data(GUILD_A, 42)
            return int(version), int(rows), int(summaries), _contents(fresh)
        finally:
            await db.close()

    version, rows, summaries, fresh = asyncio.run(_run())
    assert version == 4, "the channel migration must bump user_version"
    assert rows == 0, "rows that cannot be attributed to one channel must be discarded"
    assert summaries == 0
    assert "fresh line" in fresh


def test_retention_keeps_the_cap_per_conversation():
    async def _run():
        db = await _db()
        db.MESSAGES_RETAINED_PER_USER = 2
        try:
            for i in range(5):
                await db.add_exchange(GUILD_A, USER, f"a{i}", "r")
                await db.add_exchange(GUILD_B, USER, f"b{i}", "r")
            async with db._connect() as c:
                await c.execute("DELETE FROM state WHERE key = 'retention_day'")
                await db._apply_retention(c)
                await c.commit()
            _, a = await db.get_context_data(GUILD_A, USER)
            _, b = await db.get_context_data(GUILD_B, USER)
            return [m["content"] for m in a], [m["content"] for m in b]
        finally:
            await db.close()

    a, b = asyncio.run(_run())
    assert a == ["a4", "r"], a
    assert b == ["b4", "r"], b
