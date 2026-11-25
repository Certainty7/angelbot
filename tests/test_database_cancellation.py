"""Audit finding 4: a cancelled write must not leave an open transaction.

`_connect()` is the one place every query passes through. Before the fix it released
the lock on cancellation without rolling back, so the next unrelated write committed
the half-finished one — a privacy delete could land with the messages still present.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

from angel.database import BotDatabase


def _fresh_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


async def _seeded_db() -> BotDatabase:
    db = BotDatabase(_fresh_path())
    await db.initialize()
    async with db._connect() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS probe (x INTEGER)")
        await conn.execute("INSERT INTO probe VALUES (1)")
        await conn.commit()
    return db


async def _count(db: BotDatabase) -> int:
    async with db._connect() as conn:
        async with conn.execute("SELECT COUNT(*) FROM probe") as cur:
            row = await cur.fetchone()
    assert row is not None
    return int(row[0])


async def _run_interrupted(db: BotDatabase, exc: BaseException) -> None:
    async def operation() -> None:
        async with db._connect() as conn:
            await conn.execute("DELETE FROM probe")
            raise exc

    try:
        await asyncio.create_task(operation())
    except BaseException:
        pass


async def _assert_rolled_back(exc: BaseException) -> None:
    db = await _seeded_db()
    await _run_interrupted(db, exc)

    assert db._conn is not None
    assert db._conn.in_transaction is False, "an interrupted write left a transaction open"
    assert await _count(db) == 1, "the cancelled DELETE was not rolled back"

    # A later, unrelated write must not carry the abandoned statement with it.
    async with db._connect() as conn:
        await conn.execute("INSERT INTO probe VALUES (2)")
        await conn.commit()
    assert await _count(db) == 2
    await db.close()


def test_cancellation_rolls_back_the_shared_connection():
    asyncio.run(_assert_rolled_back(asyncio.CancelledError()))


def test_an_ordinary_exception_also_rolls_back():
    asyncio.run(_assert_rolled_back(RuntimeError("boom")))


def test_successful_writes_still_commit():
    async def _run() -> int:
        db = await _seeded_db()
        async with db._connect() as conn:
            await conn.execute("INSERT INTO probe VALUES (3)")
            await conn.commit()
        total = await _count(db)
        await db.close()
        return total

    assert asyncio.run(_run()) == 2
