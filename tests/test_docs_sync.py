"""Documentation must describe the code that actually ships (Stage 7).

These are inventory checks, not keyword searches: the command list and the table list are
generated from the live tree/schema and compared with the canonical documents.
"""
import asyncio
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from angel.database import BotDatabase  # noqa: E402

FTS_SHADOW = re.compile(r"_(config|data|docsize|idx)$")


def _live_commands():
    import bot  # noqa: F401 - registers every eager command
    names = {c.name for c in bot.bot.tree.get_commands()}
    music = re.findall(
        r'@app_commands\.command\(name="([^"]+)"',
        (REPO / "cogs" / "music.py").read_text(encoding="utf-8"),
    )
    return names | set(music)


def _documented_commands():
    text = (REPO / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
    slash = set(re.findall(r"^\| `/([a-z_]+)`", text, re.MULTILINE))
    menus = set(re.findall(r"^\| ([\u0600-\u06FF][^|]*?) \| Message \|", text, re.MULTILINE))
    return slash, {m.strip() for m in menus}


def _schema_tables():
    path = os.path.join(tempfile.mkdtemp(prefix="angel-docs-"), "schema.db")
    db = BotDatabase(path)

    async def _run():
        await db.initialize()
        async with db._connect() as conn:
            async with conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ) as cur:
                return {row[0] for row in await cur.fetchall()}

    try:
        return asyncio.run(_run())
    finally:
        asyncio.run(db.close())
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except FileNotFoundError:
                pass


class CommandDocumentationTest(unittest.TestCase):
    def test_every_command_is_documented(self):
        live = _live_commands()
        slash, menus = _documented_commands()
        documented = slash | menus
        missing = sorted(live - documented)
        self.assertFalse(missing, "commands missing from docs/COMMANDS.md: " + ", ".join(missing))

    def test_no_documented_command_is_phantom(self):
        live = _live_commands()
        slash, menus = _documented_commands()
        extra = sorted((slash | menus) - live)
        self.assertFalse(extra, "docs/COMMANDS.md lists commands that do not exist: " + ", ".join(extra))


class DataModelDocumentationTest(unittest.TestCase):
    def test_every_table_is_documented(self):
        tables = {t for t in _schema_tables() if not FTS_SHADOW.search(t)}
        text = (REPO / "docs" / "DATA_MODEL.md").read_text(encoding="utf-8")
        missing = sorted(t for t in tables if f"`{t}`" not in text)
        self.assertFalse(missing, "tables missing from docs/DATA_MODEL.md: " + ", ".join(missing))

    def test_documented_tables_still_exist(self):
        tables = _schema_tables()
        text = (REPO / "docs" / "DATA_MODEL.md").read_text(encoding="utf-8")
        documented = set(re.findall(r"^\| `([a-z_]+)`", text, re.MULTILINE))
        stale = sorted(t for t in documented if t not in tables)
        self.assertFalse(stale, "docs/DATA_MODEL.md lists tables that no longer exist: " + ", ".join(stale))


class OperationsDocumentationTest(unittest.TestCase):
    REQUIRED = (
        "README.md",
        "ARCHITECTURE.md",
        "SECURITY.md",
        "KNOWN_ISSUES.md",
        "AGENTS.md",
        "docs/COMMANDS.md",
        "docs/DATA_MODEL.md",
        "docs/LIVE_VERIFICATION.md",
        "docs/recovery/LEDGER.md",
        "docs/recovery/STATE.md",
        "docs/recovery/DECISIONS.md",
    )

    def test_required_documents_exist(self):
        missing = [rel for rel in self.REQUIRED if not (REPO / rel).is_file()]
        self.assertFalse(missing, "missing documents: " + ", ".join(missing))

    def test_env_variables_are_documented(self):
        example = (REPO / ".env.example").read_text(encoding="utf-8")
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        for name in ("ANGEL_OWNER_ID", "ANGEL_DB_PATH", "ANGEL_TIMEZONE", "GEMINI_API_KEY"):
            self.assertIn(name, example, f"{name} is not in .env.example")
            self.assertIn(name, readme, f"{name} is not in README.md")


if __name__ == "__main__":
    unittest.main()
