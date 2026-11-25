"""Audit finding 5: `/memory forget` must not claim success when the archive fails.

The archive delete was wrapped in a `try/except` that debug-logged and continued, so a
broken FTS trigger left the row in place while the user was told the text was gone.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from angel.database import BotDatabase


def _fresh_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


async def _seeded() -> BotDatabase:
    db = BotDatabase(_fresh_path())
    await db.initialize()
    await db.log_server_message(1, 2, 42, "member", "the secret token")
    await db.add_exchange(1, 42, "the secret token", "noted")
    return db


async def _break_archive_trigger(db: BotDatabase) -> None:
    async with db._connect() as conn:
        await conn.execute(
            "CREATE TRIGGER audit_boom AFTER DELETE ON server_messages "
            "BEGIN SELECT RAISE(ABORT, 'fts out of sync'); END"
        )
        await conn.commit()


async def _count(db: BotDatabase, table: str) -> int:
    async with db._connect() as conn:
        async with conn.execute(f"SELECT COUNT(*) FROM {table}") as cur:
            row = await cur.fetchone()
    assert row is not None
    return int(row[0])


async def _count_matching(db: BotDatabase, table: str) -> int:
    async with db._connect() as conn:
        async with conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE LOWER(content) LIKE '%secret%'"
        ) as cur:
            row = await cur.fetchone()
    assert row is not None
    return int(row[0])


def test_a_failing_archive_delete_raises_and_rolls_back():
    async def _run():
        db = await _seeded()
        try:
            await _break_archive_trigger(db)
            with pytest.raises(Exception):
                await db.forget_user_keyword(42, "secret")
            return (
                await _count_matching(db, "server_messages"),
                await _count_matching(db, "messages"),
            )
        finally:
            await db.close()

    server_rows, message_rows = asyncio.run(_run())
    assert server_rows == 1, "the archive row was deleted despite the trigger failure"
    assert message_rows == 1, "the message delete was not rolled back"


def test_forget_still_removes_every_copy_when_the_archive_is_healthy():
    async def _run():
        db = await _seeded()
        try:
            await db.forget_user_keyword(42, "secret")
            return await _count_matching(db, "server_messages"), await _count_matching(db, "messages")
        finally:
            await db.close()

    assert asyncio.run(_run()) == (0, 0)


def _cog_with_db(forget):
    from cogs.memory_rules import MemoryRules

    cog = MemoryRules.__new__(MemoryRules)
    bot = MagicMock()
    bot.db.forget_user_keyword = forget
    bot.get_harem_title = MagicMock(return_value=None)
    cog.bot = bot
    interaction = MagicMock()
    interaction.user.id = 42
    interaction.user.name = "tester"
    interaction.user.display_name = "tester"
    interaction.user.guild_permissions = MagicMock(administrator=False)
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return cog, interaction


def test_a_failed_forget_sends_no_success_receipt():
    from cogs.memory_rules import MemoryRules

    async def _boom(*_a, **_k):
        raise RuntimeError("fts out of sync")

    cog, interaction = _cog_with_db(AsyncMock(side_effect=_boom))

    asyncio.run(MemoryRules.memory_cmd.callback(
        cog, interaction, action="forget", text="secret", style=None, confirm=True))

    interaction.response.defer.assert_awaited()
    interaction.response.send_message.assert_not_awaited()
    interaction.followup.send.assert_awaited()
    receipt = str(interaction.followup.send.await_args.args[0])
    assert "تعذّر" in receipt or "لم" in receipt, receipt
    assert "تم حذف" not in receipt


def test_a_successful_forget_reports_success_after_deferring():
    from cogs.memory_rules import MemoryRules

    cog, interaction = _cog_with_db(AsyncMock(return_value=None))

    asyncio.run(MemoryRules.memory_cmd.callback(
        cog, interaction, action="forget", text="secret", style=None, confirm=True))

    interaction.response.defer.assert_awaited()
    interaction.followup.send.assert_awaited()
    receipt = str(interaction.followup.send.await_args.args[0])
    assert "تم حذف" in receipt
