"""Backfill server_messages from Discord's REST API (no gateway: the live bot keeps its session).

main channel  : up to 1000 human messages (owner's ceiling)
other channels: last 200 each
Rate limits    : honours 429 retry_after and sleeps 0.25 s between pages.
"""
import json
import os
import pathlib
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

MAIN_CHANNEL = int(os.getenv("MAIN_CHANNEL_ID", "0"))
MAIN_LIMIT = int(os.getenv("BACKFILL_MAIN_LIMIT", "10000"))
OTHER_LIMIT = int(os.getenv("BACKFILL_OTHER_LIMIT", "200"))
CHANNEL_ONLY = os.getenv("BACKFILL_CHANNEL_ONLY", "").strip()
API = "https://discord.com/api/v10"


def token() -> str:
    for line in pathlib.Path(".env").read_text().splitlines():
        if line.startswith("DISCORD_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no token")


def call(path: str, tok: str):
    req = urllib.request.Request(f"{API}{path}", headers={
        "Authorization": f"Bot {tok}",
        "User-Agent": "AngelBackfill/1.0",
    })
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = float(exc.headers.get("Retry-After", 2))
                time.sleep(min(wait, 30))
                continue
            raise
    raise RuntimeError("rate limited")


def history(channel_id: int, limit: int, tok: str):
    got, before = [], None
    while len(got) < limit:
        page_size = min(100, limit - len(got))
        q = f"/channels/{channel_id}/messages?limit={page_size}"
        if before:
            q += f"&before={before}"
        batch = call(q, tok)
        if not batch:
            break
        got.extend(batch)
        before = batch[-1]["id"]
        time.sleep(0.25)
    return got[:limit]


def database_path() -> str:
    """ANGEL_DB_PATH, resolved with the same rules as angel.config."""
    import dbpath  # tools/ is on sys.path when a tool runs from the repository root

    return dbpath.resolve()


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS server_messages ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,"
        " channel_id INTEGER NOT NULL, user_id INTEGER NOT NULL,"
        " display_name TEXT, content TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    try:
        db.execute("ALTER TABLE server_messages ADD COLUMN message_id TEXT")
    except sqlite3.Error:
        pass  # already present
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_srv_msg_mid ON server_messages (message_id)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_srv_msg_unique ON server_messages (channel_id, user_id, created_at, content)")
    # The opt-out predicate below reads user_preferences; without this DDL a fresh
    # database made every insert fail with "no such table" and each message was
    # silently counted as skipped (C-005).
    db.execute(
        "CREATE TABLE IF NOT EXISTS user_preferences ("
        " user_id INTEGER PRIMARY KEY, pinned_facts TEXT DEFAULT '',"
        " style_mode TEXT DEFAULT 'realistic', opt_out INTEGER DEFAULT 0,"
        " updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    db.commit()


def main() -> None:
    tok = token()
    db = sqlite3.connect(database_path())
    ensure_schema(db)

    guilds = call("/users/@me/guilds", tok)
    print("guilds:", [(g["name"], g["id"]) for g in guilds])

    saved = skipped = 0
    for guild in guilds:
        channels = call(f"/guilds/{guild['id']}/channels", tok)
        texts = [c for c in channels if c.get("type") in (0, 5)]  # text + announcement
        for ch in texts:
            if CHANNEL_ONLY and str(ch["id"]) != CHANNEL_ONLY:
                continue
            is_main = str(ch["id"]) == str(MAIN_CHANNEL)
            limit = MAIN_LIMIT if is_main else OTHER_LIMIT
            try:
                msgs = history(int(ch["id"]), limit, tok)
            except Exception as exc:
                print(f"  skip #{ch.get('name')}: {type(exc).__name__} {str(exc)[:60]}")
                continue
            for m in msgs:
                author = m.get("author") or {}
                if author.get("bot") or not (m.get("content") or "").strip():
                    skipped += 1
                    continue
                created = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")).astimezone(timezone.utc)
                try:
                    # message_id makes a backfilled line and the live archive one row, not two.
                    # The opt-out predicate means a member who ran /data delete is never
                    # re-imported by a later run (C-005).
                    db.execute(
                        "INSERT OR IGNORE INTO server_messages "
                        "(guild_id, channel_id, user_id, display_name, content, created_at, message_id) "
                        "SELECT ?,?,?,?,?,?,? WHERE NOT EXISTS ("
                        "SELECT 1 FROM user_preferences WHERE user_id = ? AND opt_out = 1)",
                        (int(guild["id"]), int(ch["id"]), int(author["id"]),
                         (author.get("global_name") or author.get("username") or "")[:80],
                         m["content"].strip()[:1500], created.isoformat(timespec="seconds"),
                         str(m.get("id") or "") or None, int(author["id"])),
                    )
                    saved += 1
                except sqlite3.Error:
                    skipped += 1
            db.commit()
            print(f"  #{ch.get('name')}: fetched={len(msgs)} (limit {limit})")
    db.commit()
    total = db.execute("select count(*) from server_messages").fetchone()[0]
    print(f"\nsaved={saved} skipped={skipped} total_rows={total}")


if __name__ == "__main__":
    main()
