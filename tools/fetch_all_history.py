"""Resumable full-history fetch: every text channel, every message, into server_messages.

- Idempotent: `message_id` unique index; re-running never duplicates.
- Resumable: each channel remembers its oldest fetched id in `fetch_state`.
- Polite: 429 retry_after honoured, 0.15 s between pages, hard cap via TOTAL_LIMIT.

Usage:
  ./venv/bin/python tools/fetch_all_history.py                # default 200k total
  TOTAL_LIMIT=500000 ./venv/bin/python tools/fetch_all_history.py
  CHANNEL_ONLY=<channel-id> ./venv/bin/python tools/fetch_all_history.py
"""
import json
import os
import pathlib
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://discord.com/api/v10"
TOTAL_LIMIT = int(os.getenv("TOTAL_LIMIT", "200000"))
CHANNEL_ONLY = os.getenv("CHANNEL_ONLY", "").strip()
PAGE = 100


def token() -> str:
    for line in pathlib.Path(".env").read_text().splitlines():
        if line.startswith("DISCORD_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no DISCORD_TOKEN")


def call(path: str, tok: str):
    req = urllib.request.Request(f"{API}{path}", headers={
        "Authorization": f"Bot {tok}", "User-Agent": "AngelFetch/1.0"})
    for _ in range(8):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = float(exc.headers.get("Retry-After", 2))
                time.sleep(min(wait, 20))
                continue
            if exc.code in (500, 502, 503):
                time.sleep(2)
                continue
            raise
    raise RuntimeError("rate limit exhausted")


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS server_messages ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,"
        " channel_id INTEGER NOT NULL, user_id INTEGER NOT NULL,"
        " display_name TEXT, content TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    cols = {r[1] for r in db.execute("PRAGMA table_info(server_messages)")}
    if "message_id" not in cols:
        db.execute("ALTER TABLE server_messages ADD COLUMN message_id TEXT")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_srv_msg_mid ON server_messages (message_id)")
    # Same agreement as the runtime schema: identity is the snowflake alone (finding 20c).
    db.execute("DROP INDEX IF EXISTS idx_srv_msg_unique")
    db.execute("CREATE INDEX IF NOT EXISTS idx_srv_msg_user_time ON server_messages (user_id, created_at)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS fetch_state ("
        " channel_id INTEGER PRIMARY KEY, oldest_id TEXT, fetched INTEGER DEFAULT 0, updated_at TEXT)"
    )
    # The opt-out predicate below reads user_preferences; without this DDL a fresh
    # database made every insert fail with "no such table" (C-005).
    db.execute(
        "CREATE TABLE IF NOT EXISTS user_preferences ("
        " user_id INTEGER PRIMARY KEY, pinned_facts TEXT DEFAULT '',"
        " style_mode TEXT DEFAULT 'realistic', opt_out INTEGER DEFAULT 0,"
        " updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    db.commit()


def database_path() -> str:
    """ANGEL_DB_PATH, resolved with the same rules as angel.config."""
    import dbpath  # tools/ is on sys.path when a tool runs from the repository root

    return dbpath.resolve()


def insert_message(db: sqlite3.Connection, guild_id: int, channel_id: int, user_id: int,
                   display_name: str, content: str, created_at: str, message_id: str) -> int:
    """Insert one archived message and return how many rows the statement actually wrote.

    `INSERT OR IGNORE` reports nothing to the caller, so the old counter treated a duplicate
    snowflake or an opted-out member as saved work: a capped run stopped early while real rows
    were still missing (finding 20b). `rowcount` is the honest number.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat(timespec="seconds")
    if str(created_at) < cutoff:
        # Nothing older than the retention window enters the archive, so a direct backfill
        # cannot outlive the promise the runtime makes (finding 20d).
        return 0
    cur = db.execute(
        "INSERT INTO server_messages "
        "(guild_id, channel_id, user_id, display_name, content, created_at, message_id) "
        "SELECT ?,?,?,?,?,?,? WHERE NOT EXISTS ("
        "SELECT 1 FROM user_preferences WHERE user_id = ? AND opt_out = 1) "
        "ON CONFLICT(message_id) DO NOTHING",
        (guild_id, channel_id, user_id, display_name, content, created_at, message_id, user_id),
    )
    return cur.rowcount


def main() -> None:
    tok = token()
    db = sqlite3.connect(database_path(), timeout=30)
    ensure_schema(db)

    total = db.execute("select count(*) from server_messages").fetchone()[0]
    print(f"start rows={total} limit={TOTAL_LIMIT}", flush=True)

    guilds = call("/users/@me/guilds", tok)
    for guild in guilds:
        channels = call(f"/guilds/{guild['id']}/channels", tok)
        texts = [c for c in channels if c.get("type") in (0, 5)]
        for ch in texts:
            if CHANNEL_ONLY and str(ch["id"]) != CHANNEL_ONLY:
                continue
            cid = int(ch["id"])
            row = db.execute("select oldest_id, fetched from fetch_state where channel_id=?", (cid,)).fetchone()
            before = row[0] if row else None
            got = row[1] if row else 0
            name = ch.get("name", str(cid))
            if total >= TOTAL_LIMIT:
                print(f"cap reached ({total}); stopping", flush=True)
                return
            pages = 0
            while True:
                q = f"/channels/{cid}/messages?limit={PAGE}"
                if before:
                    q += f"&before={before}"
                try:
                    batch = call(q, tok)
                except Exception as exc:
                    print(f"  #{name}: stop ({type(exc).__name__})", flush=True)
                    break
                if not batch:
                    break
                before = batch[-1]["id"]
                added = 0
                failed = 0
                for m in batch:
                    a = m.get("author") or {}
                    if a.get("bot") or not (m.get("content") or "").strip():
                        continue
                    try:
                        # Never re-import a member who ran /data delete (C-005).
                        ts = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")).astimezone(timezone.utc)
                        added += insert_message(
                            db, int(guild["id"]), cid, int(a["id"]),
                            (a.get("global_name") or a.get("username") or "")[:80],
                            m["content"].strip()[:1500], ts.isoformat(timespec="seconds"),
                            m["id"],
                        )
                    except (sqlite3.Error, ValueError) as exc:
                        # A failed row (insert error or malformed timestamp) must not be
                        # swallowed: the page is not marked done, so a rerun retries
                        # exactly the missing window.
                        failed += 1
                        print(f"  #{name}: insert failed mid={m.get('id')}: {exc}", flush=True)
                db.commit()
                if failed:
                    # Do not advance fetch_state.oldest_id: `before` stays at the last
                    # fully-stored page, and the unique message_id index makes the
                    # retry never duplicate what this pass did store.
                    print(
                        f"  #{name}: {failed} insert(s) failed; page not marked done, retry this channel",
                        flush=True,
                    )
                    break
                got += len(batch)
                total += added
                db.execute(
                    "INSERT INTO fetch_state (channel_id, oldest_id, fetched, updated_at) VALUES (?,?,?,datetime('now')) "
                    "ON CONFLICT(channel_id) DO UPDATE SET oldest_id=excluded.oldest_id, fetched=excluded.fetched, updated_at=datetime('now')",
                    (cid, before, got),
                )
                db.commit()
                pages += 1
                if pages % 10 == 0:
                    print(f"  #{name}: {got} msgs scanned, total rows {total}", flush=True)
                if total >= TOTAL_LIMIT:
                    print(f"cap reached ({total}) inside #{name}", flush=True)
                    return
                time.sleep(0.15)
            print(f"  #{name}: done, scanned={got}", flush=True)

    total = db.execute("select count(*) from server_messages").fetchone()[0]
    users = db.execute("select count(distinct user_id) from server_messages").fetchone()[0]
    print(f"FINISHED rows={total} users={users}", flush=True)


if __name__ == "__main__":
    main()
