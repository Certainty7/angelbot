# Legacy rolling memory: archive instead of delete

## Goal

Stop the channel-scope migration (finding 06, schema v4) from silently destroying legacy
rolling memory: keep the dropped rows in dedicated archive tables, and backfill today's
production archive from the pre-deploy backup that is already on the server.

## Current context / assumptions

- Repo: `<home>/projects/angelbot` (`Certainty7/angelbot`), branch `master` at `9e40a43`, suite
  green: `356 passed, 1 warning, 339 subtests`.
- Finding 06 fixed a real leak: rolling memory was keyed by `user_id` only, so DM lines reached
  guild prompts. The fix keys `messages` and `user_summaries` by `(channel_id, user_id)`.
- `angel/database.py:587-615` is the v4 migration. Legacy rows carry no channel and cannot be
  attributed, so it runs `DELETE FROM messages` (line 611) and rebuilds `user_summaries` without
  copying the old rows.
- Production (`/opt/angelbot` on `<deploy-host>`) was deployed to `9e40a43` today, so v4
  already ran there and dropped **140** `messages` rows and **10** `user_summaries` rows. A
  verified pre-deploy backup exists at `/opt/angelbot/data/angel-3.20261125T141655Z.db`.
- Restoring those rows into `messages` is **not** acceptable: reads are `ORDER BY id ASC`
  (`angel/database.py:1088`), so rows inserted now would be treated as the newest turns and the
  summarizer would rewrite a user's profile from stale context. The archive is evidence only.
- Tests run with `-p no:asyncio` + `asyncio.run(...)` (no `pytest-asyncio` in the venv).
- The plan assumes a single production host. Fresh installs never enter the v4 branch, so the
  archive tables stay empty there.

## Architecture / proposed approach

Two `*_legacy_archive` tables live in the same SQLite file, created in `initialize()` next to the
tables they shadow. The v4 migration copies rows into them before deleting, so a future upgrade
of an old database loses nothing. A small operator tool replays the same copy step from a backup
file for hosts that already migrated, with dry-run as the default and `INSERT OR IGNORE` on the
original primary keys so a second run writes nothing.

## Tasks

Each task is one TDD cycle: write the failing test, watch it fail, implement minimally, watch it
pass, commit. Run every command from `<home>/projects/angelbot`.

### Task 1 — failing test: the v4 migration must archive before it deletes

Create `tests/test_legacy_archive.py`:

```python
"""Migration v4 must keep the rows it refuses to attribute (finding 06 follow-up).

The migration deletes per-member memory because a legacy row has no channel. Deleting is right;
forgetting is not. The rows are copied into `messages_legacy_archive` and
`user_summaries_legacy_archive`, which the bot never reads.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile

from angel.database import BotDatabase


def _legacy_v3() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(path)
    con.executescript(
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
        PRAGMA user_version = 3;
        """
    )
    con.execute(
        "INSERT INTO messages (user_id, role, content, created_at)"
        " VALUES (42, 'user', 'أهلاً', '2026-11-01 10:00:00')"
    )
    con.execute(
        "INSERT INTO messages (user_id, role, content, created_at)"
        " VALUES (42, 'model', 'وعليكم', '2026-11-01 10:00:05')"
    )
    con.execute(
        "INSERT INTO user_summaries (user_id, summary, updated_at)"
        " VALUES (42, 'يحب القهوة', '2026-11-01 10:00:09')"
    )
    con.commit()
    con.close()
    return path


def _migrate(path: str) -> None:
    db = BotDatabase(path)

    async def _run():
        try:
            await db.initialize()
        finally:
            await db.close()

    asyncio.run(_run())


def test_the_migration_keeps_the_rows_it_drops():
    path = _legacy_v3()
    _migrate(path)
    con = sqlite3.connect(path)
    archived = con.execute(
        "SELECT user_id, role, content FROM messages_legacy_archive ORDER BY id"
    ).fetchall()
    assert archived == [(42, "user", "أهلاً"), (42, "model", "وعليكم")]
    assert con.execute("SELECT summary FROM user_summaries_legacy_archive").fetchall() == [
        ("يحب القهوة",)
    ]
    assert con.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
```

Run it:

```bash
timeout 120 env PYTHONPATH=. .venv/bin/python -m pytest tests/test_legacy_archive.py -q -p no:asyncio
```

Expected: `1 failed` with `sqlite3.OperationalError: no such table: messages_legacy_archive`.

### Task 2 — create the archive tables in `initialize()`

In `angel/database.py`, immediately after the `user_summaries` `CREATE TABLE` block (ends around
line 158, before the `user_preferences` block), add two `await db.execute(""" ... """)` calls in
the same style:

```python
      await db.execute("""
                CREATE TABLE IF NOT EXISTS messages_legacy_archive (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP,
                    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS user_summaries_legacy_archive (
                    user_id INTEGER PRIMARY KEY,
                    summary TEXT NOT NULL,
                    updated_at TIMESTAMP,
                    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
```

Re-run the Task 1 command. Expected: still `1 failed`, now on the assertion (tables exist but are
empty) — the failure moved, so the schema step is done.

### Task 3 — copy before delete in the v4 migration

In `angel/database.py`, inside `if version < 4:` (starts line 587):

1. Before `await db.execute("DROP TABLE user_summaries_legacy")` (line 604), insert:

```python
        await db.execute(
            "INSERT OR IGNORE INTO user_summaries_legacy_archive (user_id, summary, updated_at) "
            "SELECT user_id, summary, updated_at FROM user_summaries_legacy"
        )
```

2. Replace `await db.execute("DELETE FROM messages")` (line 611) with:

```python
      await db.execute(
          "INSERT OR IGNORE INTO messages_legacy_archive (id, user_id, role, content, created_at) "
          "SELECT id, user_id, role, content, created_at FROM messages"
      )
      await db.execute("DELETE FROM messages")
```

Re-run:

```bash
timeout 120 env PYTHONPATH=. .venv/bin/python -m pytest tests/test_legacy_archive.py -q -p no:asyncio
```

Expected: `1 passed`.

Gate before committing:

```bash
timeout 300 env PYTHONPATH=. .venv/bin/python -m pytest -q -p no:asyncio 2>&1 | tail -1
```

Expected: `357 passed, 1 warning, 339 subtests passed` (356 + the new test).

```bash
git add angel/database.py tests/test_legacy_archive.py
git commit -m "fix(memory): archive the rows the v4 migration drops"
```

### Task 4 — failing test: the backup replay tool

Create `tests/test_archive_legacy_tool.py`:

```python
"""The replay tool copies a backup's legacy memory into the archive exactly once."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile

from angel.database import BotDatabase
from tools import archive_legacy_memory as tool


def _path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _legacy_backup() -> str:
    path = _path()
    con = sqlite3.connect(path)
    con.executescript(
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
        """
    )
    con.executemany(
        "INSERT INTO messages (id, user_id, role, content, created_at) VALUES (?,?,?,?,?)",
        [(1, 42, "user", "أهلاً", "2026-11-01 10:00:00"),
         (2, 42, "model", "وعليكم", "2026-11-01 10:00:05")],
    )
    con.execute(
        "INSERT INTO user_summaries (user_id, summary, updated_at)"
        " VALUES (42, 'يحب القهوة', '2026-11-01 10:00:09')"
    )
    con.commit()
    con.close()
    return path


def _live() -> str:
    path = _path()
    db = BotDatabase(path)

    async def _run():
        try:
            await db.initialize()
        finally:
            await db.close()

    asyncio.run(_run())
    return path


def test_dry_run_writes_nothing_and_apply_writes_once():
    backup, live = _legacy_backup(), _live()
    counts = tool.run(backup, live, apply=False)
    assert counts == (2, 1)
    con = sqlite3.connect(live)
    assert con.execute("SELECT count(*) FROM messages_legacy_archive").fetchone()[0] == 0

    assert tool.run(backup, live, apply=True) == (2, 1)
    assert tool.run(backup, live, apply=True) == (0, 0)
    assert con.execute("SELECT content FROM messages_legacy_archive ORDER BY id").fetchall() == [
        ("أهلاً",), ("وعليكم",)
    ]
```

Run:

```bash
timeout 120 env PYTHONPATH=. .venv/bin/python -m pytest tests/test_archive_legacy_tool.py -q -p no:asyncio
```

Expected: `ModuleNotFoundError: No module named 'tools.archive_legacy_memory'`.

### Task 5 — implement `tools/archive_legacy_memory.py`

```python
"""Copy legacy rolling memory from a pre-v4 backup into the archive tables.

The v4 migration deletes per-member memory rows that carry no channel (finding 06). This tool
replays that step for a host that already migrated: the rows land in `*_legacy_archive`, which
the bot never reads, so nothing can leak back into a prompt.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS messages_legacy_archive (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP,
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS user_summaries_legacy_archive (
    user_id INTEGER PRIMARY KEY,
    summary TEXT NOT NULL,
    updated_at TIMESTAMP,
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def plan(backup: sqlite3.Connection, live: sqlite3.Connection) -> tuple[list, list]:
    have_messages = {r[0] for r in live.execute("SELECT id FROM messages_legacy_archive")}
    have_summaries = {r[0] for r in live.execute("SELECT user_id FROM user_summaries_legacy_archive")}
    messages = [
        r
        for r in backup.execute(
            "SELECT id, user_id, role, content, created_at FROM messages ORDER BY id"
        )
        if r[0] not in have_messages
    ]
    summaries = [
        r
        for r in backup.execute(
            "SELECT user_id, summary, updated_at FROM user_summaries ORDER BY user_id"
        )
        if r[0] not in have_summaries
    ]
    return messages, summaries


def run(backup_path: str, live_path: str, *, apply: bool) -> tuple[int, int]:
    live = sqlite3.connect(live_path)
    live.executescript(DDL)
    backup = sqlite3.connect(f"file:{Path(backup_path)}?mode=ro", uri=True)
    messages, summaries = plan(backup, live)
    if apply:
        live.executemany(
            "INSERT OR IGNORE INTO messages_legacy_archive"
            " (id, user_id, role, content, created_at) VALUES (?,?,?,?,?)",
            messages,
        )
        live.executemany(
            "INSERT OR IGNORE INTO user_summaries_legacy_archive"
            " (user_id, summary, updated_at) VALUES (?,?,?)",
            summaries,
        )
        live.commit()
    live.close()
    backup.close()
    return len(messages), len(summaries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, help="pre-v4 database file (read only)")
    parser.add_argument("--db", required=True, help="live database file")
    parser.add_argument("--apply", action="store_true", help="write; default is a dry run")
    args = parser.parse_args()
    messages, summaries = run(args.backup, args.db, apply=args.apply)
    verb = "archived" if args.apply else "would archive"
    print(f"{verb} {messages} messages and {summaries} summaries")


if __name__ == "__main__":
    main()
```

Run:

```bash
timeout 120 env PYTHONPATH=. .venv/bin/python -m pytest tests/test_archive_legacy_tool.py -q -p no:asyncio
```

Expected: `1 passed`.

Gate and commit:

```bash
timeout 300 env PYTHONPATH=. .venv/bin/python -m pytest -q -p no:asyncio 2>&1 | tail -1
```

Expected: `358 passed, 1 warning, 339 subtests passed`.

```bash
git add tools/archive_legacy_memory.py tests/test_archive_legacy_tool.py
git commit -m "feat(tools): replay legacy memory into the archive from a backup"
```

### Task 6 — document the policy

Append to `docs/remediation/06-spec.md`:

```markdown
## Legacy rows

The v4 migration deletes per-member memory that carries no channel, because attributing it would
reintroduce the leak. The rows are copied to `messages_legacy_archive` and
`user_summaries_legacy_archive` first. Those tables are evidence, never prompt input: reads are
`ORDER BY id ASC` over `messages`, so a restored row would be treated as the newest turn.

Hosts that migrated before this change can replay their pre-v4 backup with
`python -m tools.archive_legacy_memory --backup <file> --db <file>` (dry run) and `--apply`.
```

```bash
git add docs/remediation/06-spec.md
git commit -m "docs(memory): say why legacy rows are archived, not restored"
```

### Task 7 — branch, PR and merge

```bash
git checkout -b fix/audit-06-legacy-archive
git push -q -u origin fix/audit-06-legacy-archive
```

Then, with a token exported from `<home>/.env`:

```bash
set -a && . <home>/.env && set +a
curl -s -X POST -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/repos/Certainty7/angelbot/pulls \
  -d '{"title":"fix(memory): archive legacy rows instead of dropping them","head":"fix/audit-06-legacy-archive","base":"master"}'
```

Expected: a JSON body with a `number`.

CI for the pushed head:

```bash
SHA=$(git rev-parse origin/fix/audit-06-legacy-archive)
curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/Certainty7/angelbot/actions/runs?head_sha=$SHA" \
  | python3 -c "import json,sys;print([(r['status'],r['conclusion']) for r in json.load(sys.stdin)['workflow_runs']])"
```

Expected: `[('completed', 'success')]`. Then squash-merge:

```bash
curl -s -X PUT -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/repos/Certainty7/angelbot/pulls/<number>/merge \
  -d '{"merge_method":"squash","commit_title":"fix(memory): archive legacy rows instead of dropping them"}'
```

Expected: `"merged": true`. Note: `commits/<sha>/check-runs` can answer `[]` on this repo even
when runs exist — always query `actions/runs?head_sha=`.

### Task 8 — deploy and replay on the server

```bash
ssh -i <ssh-key> <deploy-host> \
  'sudo -n git -c safe.directory=/opt/angelbot -C /opt/angelbot pull -q --ff-only && \
   sudo -n systemctl restart angelbot && sleep 15 && sudo -n systemctl is-active angelbot'
```

Expected: `active`.

Dry run first:

```bash
ssh -i <ssh-key> <deploy-host> \
  'cd /opt/angelbot && sudo -n -u angel venv/bin/python -m tools.archive_legacy_memory \
     --backup data/angel-3.20261125T141655Z.db --db data/angel.db'
```

Expected: `would archive 140 messages and 10 summaries`. If the numbers differ, stop and read the
backup's counts before writing anything.

Apply:

```bash
ssh -i <ssh-key> <deploy-host> \
  'cd /opt/angelbot && sudo -n -u angel venv/bin/python -m tools.archive_legacy_memory \
     --backup data/angel-3.20261125T141655Z.db --db data/angel.db --apply && \
   sudo -n -u angel venv/bin/python -m tools.archive_legacy_memory \
     --backup data/angel-3.20261125T141655Z.db --db data/angel.db'
```

Expected: first line `archived 140 messages and 10 summaries`, second line
`would archive 0 messages and 0 summaries` (idempotent).

## Tests / validation

- Per-task cycle above; the suite grows 356 → 357 → 358 with one focused test file per task.
- Final full suite (`-p no:asyncio`) must print `358 passed, 1 warning, 339 subtests passed`.
- `ANGEL_OWNER_ID=42 .venv/bin/python tools/selftest.py` in a clean copy must still print
  `50/50 checks passed` (the archive tables change no runtime path).
- Production: dry run prints `140` / `10`, apply makes it `0` / `0` on a second run, and the bot
  stays `active` with a connected gateway after the restart.
- Nothing is restored into `messages`: after the replay, `select count(*) from messages` stays as
  it was before the tool ran (it will be whatever the live bot wrote since the deploy).

## Risks, tradeoffs, open questions

- **Chronology beats sentiment.** Restoring into `messages` would make stale turns look newest
  (`ORDER BY id ASC`). The archive keeps the text without touching prompts; accepted loss of
  personalization is the same 140 rows, but now provable and greppable.
- **PII on disk.** The archive holds member text. Keep the file on the server, readable by
  `angel` only; do not copy it to a workstation.
- **Size.** `messages` is bounded by the rolling window (140 rows here), so the archive stays
  small; a host with a large legacy table would add one copy, not a second index.
- **Crash window.** `INSERT OR IGNORE` on the original ids makes the copy re-runnable if the
  process dies between the insert and the `DELETE`.
- **Fresh installs.** The v4 branch never runs, so the archive tables exist but stay empty — one
  schema addition, no behaviour change.
- **Open question (deferred, YAGNI).** Whether operators want a read-only query over the archive
  (`tools/recall_probe`-style). No user has asked; the backup file already answers it today.
