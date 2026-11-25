"""Recall probe: does memory return the right fact for a paraphrased question?

Run with PYTHONPATH=. (the package lives in the repo root):
    PYTHONPATH=. ./venv/bin/python tools/recall_probe.py

It works on a TEMP COPY of the database: the production file is never opened for writing.
"""
import asyncio
import os
import sqlite3

from tools import dbpath
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from angel import memory, registry
from angel.database import BotDatabase

PROBE_USER = 999_000_001  # never a real Discord id

# Fixtures are deliberately fictional: a shipped screenshot must never look like a real member.
CASES = [
    ("city", "مدينة الشمال", "وين ساكن الحين؟"),
    ("job", "مهندس أنظمة", "وش شغلك بالضبط؟"),
    ("pet", "قطة اسمها رملة", "عندك حيوان في البيت؟"),
    ("drink", "شاي بالنعناع", "وش تحب تشرب الصبح؟"),
    ("car", "سيارة صغيرة", "وش نوع سيارتك؟"),
    ("study", "علوم حاسب", "وش درست في الجامعة؟"),
    ("sport", "سباحة أسبوعياً", "تلعب رياضة؟"),
    ("food", "أرز بالخضار", "وش أكلتك المفضلة؟"),
    ("travel", "مدينة الساحل", "وين رحت آخر سفرة؟"),
    ("family", "أخي الأكبر", "عندك إخوة؟"),
]


class _Stub:
    def __init__(self, db):
        self.db = db


def source_db_path() -> str:
    """The database the bot actually writes, not a hardcoded repo-root file."""
    return dbpath.resolve()


async def run() -> int:
    tmp = os.path.join(tempfile.gettempdir(), "angel-recall-probe.db")
    src_path = source_db_path()
    if os.path.isfile(src_path):
        # A WAL database copied with shutil is a torn snapshot; `.backup` reads a consistent one.
        src = sqlite3.connect(src_path)
        dst = sqlite3.connect(tmp)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
    db = BotDatabase(tmp)
    await db.initialize()
    registry.install(_Stub(db))

    try:
        hits = 0
        for key, value, _question in CASES:
            await db.upsert_profile_fact(PROBE_USER, key, value, confidence=0.9)

        for key, value, question in CASES:
            facts = await memory.recall(PROBE_USER, question, limit=8)
            got = any(value.split()[0] in (f.get("fact_value") or "") for f in facts)
            hits += got
            print(f"[{'HIT ' if got else 'MISS'}] {key:7s} {value!r:30s} q={question!r:26s} n={len(facts)}")

        print(f"\nrecall: {hits}/{len(CASES)} = {hits * 100 // len(CASES)}%")
        return 0 if hits == len(CASES) else 1
    finally:
        await db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(tmp + suffix)
            except OSError:
                pass


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
