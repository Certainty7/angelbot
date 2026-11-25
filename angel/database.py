"""Local SQLite layer (aiosqlite, WAL mode)."""

import aiosqlite
import asyncio
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from .config import logger

# 3. Local SQLite Database Layer (19 Tables)
def _fts_query(text: str) -> str:
  """Safe FTS5 MATCH expression (prefix tokens, OR-joined); empty when nothing usable."""
  import re

  from .persona import normalize_arabic_text

  # Fold diacritics and tatweel before tokenising: "مُحَمَّد" otherwise splits into single
  # letters and is dropped by the {2,} filter, so the search silently returns nothing.
  normalized = normalize_arabic_text(text or "").lower()
  tokens = re.findall(r"[\w\u0621-\u064A\u0660-\u0669]{2,}", normalized)
  stop = {"the", "and", "you", "are", "what", "وش", "في", "من", "على", "عن", "هو", "هي"}
  tokens = [t for t in tokens if t not in stop][:6]
  return " OR ".join(f'"{t}"*' for t in tokens)


def _like_escape(value: str) -> str:
  """Escape LIKE wildcards so a fact/keyword containing % or _ stays literal."""
  return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _norm_ar(text: str) -> str:
  import re
  import unicodedata

  t = unicodedata.normalize("NFKC", (text or "").lower())
  t = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", t)
  t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
  t = re.sub(r"\bال", "", t)
  return re.sub(r"\s+", " ", t).strip()


def _fuzzy_best(query: str, rows, text_key: str, limit: int = 3, threshold: float = 0.52):
  """Arabic morphology rarely matches FTS verbatim; score words with difflib."""
  from difflib import SequenceMatcher

  q_tokens = [w for w in _norm_ar(query).split() if len(w) >= 3]
  if not q_tokens or not rows:
    return []
  scored = []
  for row in rows:
    words = _norm_ar(str(row.get(text_key, ""))).split()
    best = 0.0
    for qt in q_tokens:
      for w in words:
        r = SequenceMatcher(None, qt, w).ratio()
        if r > best:
          best = r
    if best >= threshold:
      scored.append((best, row))
  scored.sort(key=lambda x: x[0], reverse=True)
  return [row for _, row in scored[:limit]]


class BotDatabase:
  """
  Persistent single-connection SQLite manager optimized for a small single-core host.
  Avoids spawning a new OS thread per query and keeps WAL + synchronous=NORMAL + temp_store=MEMORY active permanently.
  """

  # One shared cap for every retention path: `_apply_retention` and the 30-minute
  # `cleanup_and_vacuum` must never disagree on how many chat lines a member keeps.
  MESSAGES_RETAINED_PER_USER = 60

  def __init__(self, db_path: str):
    self.db_path = db_path
    self._conn: Optional[aiosqlite.Connection] = None
    self._lock = asyncio.Lock()

  async def _ensure_conn(self) -> aiosqlite.Connection:
    # Public state only: `close()` sets this to None, so a closed database is reopened.
    if self._conn is None:
      self._conn = await aiosqlite.connect(self.db_path)
      self._conn.row_factory = aiosqlite.Row
      await self._conn.execute("PRAGMA journal_mode=WAL")
      await self._conn.execute("PRAGMA synchronous=NORMAL")
      await self._conn.execute("PRAGMA temp_store=MEMORY")
      await self._conn.execute("PRAGMA cache_size=-4000")
      await self._conn.execute("PRAGMA busy_timeout=5000")
    return self._conn

  @asynccontextmanager
  async def _connect(self):
    async with self._lock:
      db = await self._ensure_conn()
      db.row_factory = aiosqlite.Row
      try:
        yield db
      except BaseException:
        # Every query shares this one connection, so a write interrupted mid-transaction
        # would be committed by whatever runs next. Roll it back before releasing the lock.
        if db.in_transaction:
          try:
            await db.rollback()
          except Exception as exc:
            logger.warning("database rollback failed: %s: %s", type(exc).__name__, exc)
        raise

  async def close(self):
    async with self._lock:
      if self._conn is not None:
        try:
          await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
          await self._conn.close()
        except Exception as exc:
          logger.warning("database close failed: %s: %s", type(exc).__name__, exc)
        self._conn = None

  async def health_check(self) -> Tuple[bool, int]:
    """Live SELECT 1 plus the real table count (the old dashboard hardcoded '19')."""
    async with self._connect() as db:
      async with db.execute(
          "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
      ) as cur:
        row = await cur.fetchone()
      async with db.execute("SELECT 1") as cur:
        await cur.fetchone()
    return True, int(row[0]) if row else 0

  async def initialize(self):
    async with self._connect() as db:
      await db.execute("PRAGMA journal_mode=WAL")
      await db.execute("PRAGMA synchronous=NORMAL")
      await db.execute("PRAGMA temp_store=MEMORY")
      await db.execute("PRAGMA cache_size=-4000")
      await db.execute("PRAGMA busy_timeout=5000")
      await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL DEFAULT 0,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS user_summaries (
                    channel_id INTEGER NOT NULL DEFAULT 0,
                    user_id INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (channel_id, user_id)
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id INTEGER PRIMARY KEY,
                    pinned_facts TEXT DEFAULT '',
                    style_mode TEXT DEFAULT 'realistic',
                    opt_out INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS server_knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    content TEXT NOT NULL,
                    added_by INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
      await db.execute("CREATE INDEX IF NOT EXISTS idx_guild_knowledge ON server_knowledge (guild_id)")
      await db.execute("""
                CREATE TABLE IF NOT EXISTS saved_playlists (
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    query TEXT NOT NULL,
                    added_by INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, name)
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
      await db.execute("CREATE INDEX IF NOT EXISTS idx_guild_user_warnings ON warnings (guild_id, user_id)")
      await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    modlog_channel_id INTEGER,
                    welcome_channel_id INTEGER,
                    dmlog_channel_id INTEGER,
                    autorole_id INTEGER,
                    guard_mode TEXT DEFAULT 'off',
                    stay_voice_channel_id INTEGER
                )
            """)
      for col_sql in (
          "ALTER TABLE guild_settings ADD COLUMN autorole_id INTEGER",
          "ALTER TABLE guild_settings ADD COLUMN guard_mode TEXT DEFAULT 'off'",
          "ALTER TABLE guild_settings ADD COLUMN stay_voice_channel_id INTEGER",
          "ALTER TABLE guild_settings ADD COLUMN dialect TEXT DEFAULT 'gulf'",
          "ALTER TABLE guild_settings ADD COLUMN social_fixer_enabled INTEGER DEFAULT 1",
          "ALTER TABLE guild_settings ADD COLUMN daily_ai_limit INTEGER DEFAULT 40",
          "ALTER TABLE guild_settings ADD COLUMN updated_at TEXT",
      ):
        try:
          await db.execute(col_sql)
        except Exception as exc:
          logger.debug("guild_settings migration skipped: %s", exc)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_daily_usage (
                    guild_id INTEGER NOT NULL,
                    day_utc TEXT NOT NULL,
                    ai_calls INTEGER NOT NULL DEFAULT 0,
                    catchup_calls INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, day_utc)
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS dm_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id INTEGER NOT NULL,
                    sender_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    attachments TEXT,
                    angel_reply TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS afk_users (
                    guild_id INTEGER NOT NULL DEFAULT 0,
                    user_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    since TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
      # Migrate the legacy per-user table once; AFK reasons must not cross guilds.
      async with db.execute("PRAGMA table_info(afk_users)") as cur:
        afk_cols = [row[1] for row in await cur.fetchall()]
      if "guild_id" not in afk_cols:
        await db.execute("""
                  CREATE TABLE afk_users_scoped (
                      guild_id INTEGER NOT NULL DEFAULT 0,
                      user_id INTEGER NOT NULL,
                      reason TEXT NOT NULL,
                      since TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      PRIMARY KEY (guild_id, user_id)
                  )
              """)
        await db.execute(
            "INSERT OR IGNORE INTO afk_users_scoped (guild_id, user_id, reason, since) "
            "SELECT 0, user_id, reason, since FROM afk_users"
        )
        await db.execute("DROP TABLE afk_users")
        await db.execute("ALTER TABLE afk_users_scoped RENAME TO afk_users")
      await db.execute("""
                CREATE TABLE IF NOT EXISTS user_xp (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    xp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    messages_count INTEGER DEFAULT 0,
                    rep_points INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
      try:
        await db.execute("ALTER TABLE user_xp ADD COLUMN rep_points INTEGER DEFAULT 0")
      except Exception as exc:
        logger.debug("user_xp migration skipped: %s", exc)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS auto_triggers (
                    guild_id INTEGER NOT NULL,
                    trigger_word TEXT NOT NULL,
                    response_text TEXT NOT NULL,
                    PRIMARY KEY (guild_id, trigger_word)
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS giveaways (
                    message_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    prize TEXT NOT NULL,
                    winners_count INTEGER NOT NULL,
                    end_at TIMESTAMP NOT NULL,
                    participants TEXT DEFAULT '',
                    ended INTEGER DEFAULT 0
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS harem_members (
                    user_id INTEGER PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    custom_title TEXT DEFAULT 'الحريم',
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS custom_action_triggers (
                    guild_id INTEGER NOT NULL,
                    phrase TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    param_value INTEGER DEFAULT 15,
                    custom_reply TEXT DEFAULT '',
                    usage_count INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, phrase)
                )
            """)
      try:
        await db.execute("ALTER TABLE custom_action_triggers ADD COLUMN usage_count INTEGER DEFAULT 0")
      except Exception as exc:
        logger.debug("custom_action migration skipped: %s", exc)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS sticky_messages (
                    channel_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    last_message_id INTEGER DEFAULT 0
                )
            """)
      # Legacy clean-up and retention are versioned and bounded; see _run_migrations().
      # --- Social memory, silence map & autonomous-chat audit (2026-11) ---
      await db.execute("""
                CREATE TABLE IF NOT EXISTS silent_channels (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    added_by INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, channel_id)
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS user_profile (
                    user_id INTEGER NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    confidence REAL DEFAULT 0.7,
                    source TEXT DEFAULT 'chat',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, fact_key)
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS user_index (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    display_name TEXT DEFAULT '',
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    msg_count INTEGER DEFAULT 0,
                    topics TEXT DEFAULT '',
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS gif_pool (
                    url TEXT PRIMARY KEY,
                    action TEXT DEFAULT '',
                    source TEXT DEFAULT '',
                    sapphic INTEGER DEFAULT 0,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_flags (
                    flag_key TEXT PRIMARY KEY,
                    flag_value TEXT DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS ambient_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    user_id INTEGER DEFAULT 0,
                    angel_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
      # --- Merged from the Malak build (2026-11-07) ---
      await db.execute("""
                CREATE TABLE IF NOT EXISTS server_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    display_name TEXT,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    message_id TEXT
                )
            """)
      await db.execute("CREATE INDEX IF NOT EXISTS idx_srv_msg_guild ON server_messages (guild_id, created_at)")
      await db.execute("CREATE INDEX IF NOT EXISTS idx_srv_msg_created ON server_messages (created_at)")
      await db.execute("CREATE INDEX IF NOT EXISTS idx_srv_msg_user ON server_messages (user_id, created_at)")
      await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_srv_msg_mid ON server_messages (message_id)")
      await db.execute("""
                CREATE TABLE IF NOT EXISTS user_dossier (
                    user_id INTEGER PRIMARY KEY, display_name TEXT, summary TEXT,
                    facts_json TEXT, style TEXT, topics TEXT, notes TEXT,
                    msg_count INTEGER, model TEXT, updated_at TEXT
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS admin_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    content TEXT NOT NULL,
                    author_id INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    rule_key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(guild_id, rule_key)
                )
            """)
      await db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS rules_fts USING fts5(
                    rule_key, content, content='rules', content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                )
            """)
      await db.execute("""
                CREATE TRIGGER IF NOT EXISTS rules_ai AFTER INSERT ON rules BEGIN
                    INSERT INTO rules_fts(rowid, rule_key, content) VALUES (new.id, new.rule_key, new.content);
                END
            """)
      await db.execute("""
                CREATE TRIGGER IF NOT EXISTS rules_au AFTER UPDATE ON rules BEGIN
                    INSERT INTO rules_fts(rules_fts, rowid, rule_key, content)
                    VALUES ('delete', old.id, old.rule_key, old.content);
                    INSERT INTO rules_fts(rowid, rule_key, content) VALUES (new.id, new.rule_key, new.content);
                END
            """)
      # Without this trigger a deleted rule stays in the index and keeps matching forever.
      await db.execute("""
                CREATE TRIGGER IF NOT EXISTS rules_ad AFTER DELETE ON rules BEGIN
                    INSERT INTO rules_fts(rules_fts, rowid, rule_key, content)
                    VALUES ('delete', old.id, old.rule_key, old.content);
                END
            """)
      await db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS user_profile_fts USING fts5(
                    fact_key, fact_value, content='user_profile', content_rowid='rowid',
                    tokenize='unicode61 remove_diacritics 2'
                )
            """)
      await db.execute("""
                CREATE TRIGGER IF NOT EXISTS user_profile_ai AFTER INSERT ON user_profile BEGIN
                    INSERT INTO user_profile_fts(rowid, fact_key, fact_value)
                    VALUES (new.rowid, new.fact_key, new.fact_value);
                END
            """)
      await db.execute("""
                CREATE TRIGGER IF NOT EXISTS user_profile_au AFTER UPDATE ON user_profile BEGIN
                    INSERT INTO user_profile_fts(user_profile_fts, rowid, fact_key, fact_value)
                    VALUES ('delete', old.rowid, old.fact_key, old.fact_value);
                    INSERT INTO user_profile_fts(rowid, fact_key, fact_value)
                    VALUES (new.rowid, new.fact_key, new.fact_value);
                END
            """)
      await db.execute("""
                CREATE TRIGGER IF NOT EXISTS user_profile_ad AFTER DELETE ON user_profile BEGIN
                    INSERT INTO user_profile_fts(user_profile_fts, rowid, fact_key, fact_value)
                    VALUES ('delete', old.rowid, old.fact_key, old.fact_value);
                END
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS persona_culture (
                    guild_id INTEGER PRIMARY KEY,
                    notes_json TEXT,
                    updated_at TEXT
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS llm_usage (
                    day TEXT PRIMARY KEY,
                    calls INTEGER DEFAULT 0,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    blocked INTEGER DEFAULT 0
                )
            """)
      await db.execute("""
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
      await db.commit()
      await self._run_migrations(db)
      await self._apply_retention(db)
      await db.commit()
    # Archive FTS + its sync triggers must exist on every deployment, not only where an
    # operator created them by hand: search_archive() silently returns [] without them.
    await self.ensure_archive_index()
    logger.info("Database initialized.")

  async def _run_migrations(self, db) -> None:
    """Versioned, one-time data migrations (PRAGMA user_version).

    The old initialize() rewrote rows and deleted every summary shorter than 35 characters
    on *every* boot: legitimate data ("يحب القهوة") vanished silently, and the write lock was
    held at startup for 50+ full-table statements. Schema DDL above stays idempotent; only
    data rewrites belong here.
    """
    async with db.execute("PRAGMA user_version") as cur:
      row = await cur.fetchone()
    version = int(row[0] if row else 0)
    if version < 1:
      for noisy_phrase in (
          "تفضلي يا اليقين، آمريني؟", "تأمرين يا اليقين، ", "تامرين يا اليقين، ",
          "يا اليقين، ", "يا اليقين.. ", "يا اليقين. ", " يا اليقين", "يا اليقين",
          "يا سيدتي، ", "يا سيدتي.. ", " يا سيدتي",
          "عيون أنجل وقلبها.. ", "عيون أنجل وقلبها، ", "تأمرين ", "تامرين ", "آمريني؟", "آمريني",
          "عيونof..", "عيونof",
      ):
        try:
          await db.execute(
              "UPDATE messages SET content = REPLACE(content, ?, '') WHERE role = 'model' AND content LIKE ?",
              (noisy_phrase, f"%{noisy_phrase}%"),
          )
          await db.execute(
              "UPDATE user_summaries SET summary = REPLACE(summary, ?, '') WHERE summary LIKE ?",
              (noisy_phrase, f"%{noisy_phrase}%"),
          )
          await db.execute(
              "UPDATE user_preferences SET pinned_facts = REPLACE(pinned_facts, ?, 'صاحبتي') WHERE pinned_facts LIKE ?",
              (noisy_phrase, f"%{noisy_phrase}%"),
          )
        except Exception as exc:
          logger.debug("preference cleanup skipped: %s", exc)
      await db.execute("PRAGMA user_version = 1")
      version = 1
    if version < 2:
      # user_dossier has had no writer since automatic profiling was removed; clear any row
      # inherited from an older build so the README's "no member files" claim is true.
      # user_index.topics holds the same legacy keyword profiles: `touch()` stopped
      # writing topics, but rows upgraded from older builds kept them forever.
      try:
        await db.execute("DELETE FROM user_dossier")
        await db.execute("UPDATE user_index SET topics = ''")
      except Exception as exc:
        logger.debug("legacy profile cleanup skipped: %s", exc)
      await db.execute("PRAGMA user_version = 2")
      version = 2
    if version < 3:
      # The archive index was created without `remove_diacritics`; recreate it and rebuild
      # once so a search for "مُحَمَّد" can match "محمد". A durable marker survives a crash
      # between the drop and the rebuild: otherwise the index would stay empty forever.
      for trigger in ("server_messages_ai", "server_messages_ad", "server_messages_au"):
        await db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
      await db.execute(
          "INSERT INTO state (key, value, updated_at) VALUES ('fts_rebuild_pending', '1', CURRENT_TIMESTAMP) "
          "ON CONFLICT(key) DO UPDATE SET value = '1'"
      )
      await db.execute("DROP TABLE IF EXISTS server_messages_fts")
      self._fts_rebuild_needed = True
      await db.execute("PRAGMA user_version = 3")
      version = 3
    if version < 4:
      # Rolling memory used to be per member, so a DM line could be quoted into a guild
      # prompt. Legacy rows carry no channel and cannot be attributed, so they are discarded
      # rather than guessed at (audit finding 06).
      async with db.execute("PRAGMA table_info(user_summaries)") as cur:
        summary_cols = {row[1] for row in await cur.fetchall()}
      if "channel_id" not in summary_cols:
        await db.execute("ALTER TABLE user_summaries RENAME TO user_summaries_legacy")
        await db.execute("""
                    CREATE TABLE user_summaries (
                        channel_id INTEGER NOT NULL DEFAULT 0,
                        user_id INTEGER NOT NULL,
                        summary TEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (channel_id, user_id)
                    )
                """)
        await db.execute("DROP TABLE user_summaries_legacy")
      async with db.execute("PRAGMA table_info(messages)") as cur:
        message_cols = {row[1] for row in await cur.fetchall()}
      if "channel_id" not in message_cols:
        await db.execute(
            "ALTER TABLE messages ADD COLUMN channel_id INTEGER NOT NULL DEFAULT 0"
        )
      await db.execute("DELETE FROM messages")
      await db.execute("DROP INDEX IF EXISTS idx_user_messages")
      await db.execute(
          "CREATE INDEX IF NOT EXISTS idx_channel_user_messages ON messages (channel_id, user_id, id ASC)"
      )
      await db.execute("PRAGMA user_version = 4")

  async def _apply_retention(self, db) -> None:
    """Documented caps, applied at most once per UTC day instead of on every boot.

    - dm_logs: 30 days (the DM mirror is the most sensitive store in the database).
    - messages: the `MESSAGES_RETAINED_PER_USER` most recent chat lines per member, which
      is already far beyond the 10-line summary window the prompt uses.
    """
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with db.execute("SELECT value FROM state WHERE key = 'retention_day'") as cur:
      row = await cur.fetchone()
    if row and row[0] == today:
      return
    try:
      await db.execute("DELETE FROM dm_logs WHERE created_at < datetime('now', '-30 days')")
      # The published promise is one rolling year of the archive. Pruning lives here, once a
      # day, instead of riding a 1-in-500 insert counter: a bulk backfill could otherwise keep
      # rows far past the window until the counter happened to fire (finding 20d).
      await db.execute(
          "DELETE FROM server_messages WHERE created_at < ?",
          ((datetime.now(timezone.utc) - timedelta(days=365)).isoformat(timespec="seconds"),),
      )
      await db.execute(
          f"""
          DELETE FROM messages
          WHERE id NOT IN (
              SELECT id FROM (
                  SELECT id, ROW_NUMBER() OVER (PARTITION BY channel_id, user_id ORDER BY id DESC) AS rn
                  FROM messages
              ) WHERE rn <= {self.MESSAGES_RETAINED_PER_USER}
          )
          """
      )
    except Exception as exc:
      # Do not mark the day as done: a transient lock would otherwise defer the pass by 24h.
      logger.warning("retention pass failed: %s: %s", type(exc).__name__, exc)
      return
    await db.execute(
        "INSERT INTO state (key, value, updated_at) VALUES ('retention_day', ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
        (today,),
    )

  # --- Memory Vault (Pinned Facts & Style Mode) ---
  async def get_opted_out_ids(self) -> set:
    """Every member who asked to be forgotten; prompt builders filter against this set."""
    async with self._connect() as db:
      async with db.execute("SELECT user_id FROM user_preferences WHERE opt_out = 1") as cur:
        return {int(row[0]) async for row in cur}

  async def get_user_prefs(self, user_id: int) -> Dict[str, Any]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
        if row:
          return dict(row)
        return {"user_id": user_id, "pinned_facts": "", "style_mode": "realistic", "opt_out": 0}

  async def pin_user_fact(self, user_id: int, fact: str):
    # The read and the write share one connection on purpose: two pins that arrive together
    # would otherwise both read the old row and the second one would drop the first fact.
    async with self._connect() as db:
      cur = await db.execute(
          "SELECT pinned_facts, style_mode, opt_out FROM user_preferences WHERE user_id = ?",
          (user_id,),
      )
      row = await cur.fetchone()
      prefs = dict(row) if row else {"pinned_facts": "", "style_mode": "realistic", "opt_out": 0}
      existing = [x.strip() for x in (prefs.get("pinned_facts") or "").split("\n") if x.strip()]
      existing.append(f"• {fact.strip()}")
      merged = "\n".join(existing[-15:])
      await db.execute(
          """
          INSERT INTO user_preferences (user_id, pinned_facts, style_mode, opt_out, updated_at)
          VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id) DO UPDATE SET pinned_facts = excluded.pinned_facts, updated_at = CURRENT_TIMESTAMP
          """,
          (user_id, merged, prefs.get("style_mode", "realistic"), prefs.get("opt_out", 0)),
      )
      await db.commit()

  async def set_user_style(self, user_id: int, style_mode: str):
    async with self._connect() as db:
      cur = await db.execute(
          "SELECT pinned_facts, opt_out FROM user_preferences WHERE user_id = ?",
          (user_id,),
      )
      row = await cur.fetchone()
      prefs = dict(row) if row else {"pinned_facts": "", "opt_out": 0}
      await db.execute(
          """
          INSERT INTO user_preferences (user_id, pinned_facts, style_mode, opt_out, updated_at)
          VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id) DO UPDATE SET style_mode = excluded.style_mode, updated_at = CURRENT_TIMESTAMP
          """,
          (user_id, prefs.get("pinned_facts", ""), style_mode, prefs.get("opt_out", 0)),
      )
      await db.commit()

  async def forget_user_keyword(self, user_id: int, keyword: str):
    prefs = await self.get_user_prefs(user_id)
    kw_lower = keyword.lower().strip()
    lines = [
        x for x in (prefs.get("pinned_facts") or "").split("\n")
        if x.strip() and kw_lower not in x.lower()
    ]
    async with self._connect() as db:
      await db.execute(
          "UPDATE user_preferences SET pinned_facts = ? WHERE user_id = ?",
          ("\n".join(lines), user_id),
      )
      await db.execute(
          "DELETE FROM messages WHERE user_id = ? AND LOWER(content) LIKE ? ESCAPE '\\'",
          (user_id, f"%{_like_escape(kw_lower)}%"),
      )
      # The archive is what recall quotes back into a later prompt, so a "forgotten" word
      # that survives there has not really been forgotten. The delete trigger keeps FTS in
      # sync; if it fails, the error must reach the caller so no success receipt is sent.
      await db.execute(
          "DELETE FROM server_messages WHERE user_id = ? AND LOWER(content) LIKE ? ESCAPE '\\'",
          (user_id, f"%{_like_escape(kw_lower)}%"),
      )
      # Also scrub or clear user_summaries so the forgotten keyword never re-enters prompt
      # context (F-07). Forgetting is a privacy erase, so it covers every conversation.
      async with db.execute(
          "SELECT channel_id, summary FROM user_summaries WHERE user_id = ?", (user_id,)
      ) as cur:
        rows = await cur.fetchall()
      for channel_id, old_sum in rows:
        if not old_sum or kw_lower not in old_sum.lower():
          continue
        kept_parts = [
            p.strip() for p in re.split(r"[.\n،!؟]+", old_sum)
            if p.strip() and kw_lower not in p.lower()
        ]
        if kept_parts:
          await db.execute(
              "UPDATE user_summaries SET summary = ?, updated_at = CURRENT_TIMESTAMP "
              "WHERE channel_id = ? AND user_id = ?",
              ("، ".join(kept_parts) + ".", channel_id, user_id),
          )
        else:
          await db.execute(
              "DELETE FROM user_summaries WHERE channel_id = ? AND user_id = ?",
              (channel_id, user_id),
          )
      # Facts and the dossier are what actually reach the prompt; a keyword that survives
      # there keeps being recalled after the user asked to forget it.
      await db.execute(
          "DELETE FROM user_profile WHERE user_id = ? AND (LOWER(fact_key) LIKE ? ESCAPE '\\' "
          "OR LOWER(fact_value) LIKE ? ESCAPE '\\')",
          (user_id, f"%{_like_escape(kw_lower)}%", f"%{_like_escape(kw_lower)}%"),
      )
      await db.execute(
          "DELETE FROM user_dossier WHERE user_id = ? AND (LOWER(COALESCE(facts_json, '')) LIKE ? ESCAPE '\\' "
          "OR LOWER(COALESCE(summary, '')) LIKE ? ESCAPE '\\')",
          (user_id, f"%{_like_escape(kw_lower)}%", f"%{_like_escape(kw_lower)}%"),
      )
      await db.commit()

  # --- Server Knowledge Brain ---
  async def add_knowledge(self, guild_id: int, topic: str, content: str, added_by: int) -> int:
    async with self._connect() as db:
      cur = await db.execute(
          "INSERT INTO server_knowledge (guild_id, topic, content, added_by) VALUES (?, ?, ?, ?)",
          (guild_id, topic.strip(), content.strip(), added_by),
      )
      await db.commit()
      return cur.lastrowid

  async def get_guild_knowledge(self, guild_id: int) -> List[Dict[str, Any]]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute(
          "SELECT id, topic, content, added_by, created_at FROM server_knowledge WHERE guild_id = ? ORDER BY id ASC",
          (guild_id,),
      ) as cur:
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

  async def delete_knowledge(self, guild_id: int, entry_id: int) -> bool:
    async with self._connect() as db:
      cur = await db.execute(
          "DELETE FROM server_knowledge WHERE guild_id = ? AND id = ?",
          (guild_id, entry_id),
      )
      await db.commit()
      return cur.rowcount > 0

  async def search_knowledge_for_prompt(self, guild_id: int, query: str) -> Optional[str]:
    entries = await self.get_guild_knowledge(guild_id)
    if not entries:
      return None
    q_words = [w for w in re.split(r"\s+", query.lower()) if len(w) >= 3]
    scored = []
    for e in entries:
      haystack = f"{e['topic']} {e['content']}".lower()
      hits = sum(1 for w in q_words if w in haystack)
      scored.append((hits, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [e for hits, e in scored[:5] if hits > 0] or [e for _, e in scored[:3]]
    return "\n".join(f"• [{e['topic']}]: {e['content']}" for e in selected)

  # --- Saved Playlists (Music 2.0) ---
  async def save_playlist_track(self, guild_id: int, name: str, query: str, added_by: int):
    async with self._connect() as db:
      await db.execute(
          """
          INSERT INTO saved_playlists (guild_id, name, query, added_by)
          VALUES (?, ?, ?, ?)
          ON CONFLICT(guild_id, name) DO UPDATE SET query = excluded.query
          """,
          (guild_id, name.lower().strip(), query.strip(), added_by),
      )
      await db.commit()

  async def get_saved_playlists(self, guild_id: int) -> List[Dict[str, Any]]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute("SELECT * FROM saved_playlists WHERE guild_id = ?", (guild_id,)) as cur:
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

  async def delete_playlist_track(self, guild_id: int, name: str) -> bool:
    async with self._connect() as db:
      cur = await db.execute(
          "DELETE FROM saved_playlists WHERE guild_id = ? AND name = ?",
          (guild_id, name.lower().strip()),
      )
      await db.commit()
      return cur.rowcount > 0

  # --- Guard Mode ---
  async def set_guard_mode(self, guild_id: int, mode: str):
    async with self._connect() as db:
      await db.execute(
          """
          INSERT INTO guild_settings (guild_id, guard_mode)
          VALUES (?, ?)
          ON CONFLICT(guild_id) DO UPDATE SET guard_mode = excluded.guard_mode
          """,
          (guild_id, mode),
      )
      await db.commit()

  async def get_guard_mode(self, guild_id: int) -> str:
    async with self._connect() as db:
      async with db.execute("SELECT guard_mode FROM guild_settings WHERE guild_id = ?", (guild_id,)) as cur:
        row = await cur.fetchone()
        return (row[0] if row and row[0] else "off")

  # --- Reputation Points (Angel Guild) ---
  async def add_rep(self, guild_id: int, user_id: int) -> int:
    async with self._connect() as db:
      # `/rep` writes member data like any other path: an opted-out member must not
      # have a `user_xp` row re-created through it (C-006). The guard lives in SQL.
      async with db.execute(
          "SELECT 1 FROM user_preferences WHERE user_id = ? AND opt_out = 1", (user_id,)
      ) as opt_cur:
        if await opt_cur.fetchone():
          return 0
      await db.execute(
          """
          INSERT INTO user_xp (guild_id, user_id, xp, level, messages_count, rep_points)
          VALUES (?, ?, 0, 1, 0, 1)
          ON CONFLICT(guild_id, user_id) DO UPDATE SET rep_points = COALESCE(rep_points, 0) + 1
          """,
          (guild_id, user_id),
      )
      await db.commit()
      async with db.execute("SELECT rep_points FROM user_xp WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cur:
        row = await cur.fetchone()
        return row[0] if row else 1

  # --- Sticky Messages ---
  async def set_sticky(self, channel_id: int, guild_id: int, content: str, last_msg_id: int = 0):
    async with self._connect() as db:
      await db.execute(
          """
                INSERT INTO sticky_messages (channel_id, guild_id, content, last_message_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    content = excluded.content,
                    last_message_id = excluded.last_message_id
                """,
          (channel_id, guild_id, content, last_msg_id),
      )
      await db.commit()

  async def remove_sticky(self, channel_id: int, guild_id: int) -> int:
    async with self._connect() as db:
      cursor = await db.execute(
          "DELETE FROM sticky_messages WHERE channel_id = ? AND guild_id = ?",
          (channel_id, guild_id),
      )
      await db.commit()
      return cursor.rowcount

  async def get_all_stickies(self, guild_id: Optional[int] = None) -> Dict[int, Dict[str, Any]]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      if guild_id is None:
        cursor = await db.execute("SELECT * FROM sticky_messages")
      else:
        cursor = await db.execute(
            "SELECT * FROM sticky_messages WHERE guild_id = ?", (guild_id,)
        )
      async with cursor:
        rows = await cursor.fetchall()
        return {r["channel_id"]: dict(r) for r in rows}

  # --- Auto-Role ---
  async def set_autorole(self, guild_id: int, role_id: Optional[int]):
    async with self._connect() as db:
      await db.execute(
          """
                INSERT INTO guild_settings (guild_id, autorole_id)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET autorole_id = excluded.autorole_id
                """,
          (guild_id, role_id),
      )
      await db.commit()

  async def get_autorole(self, guild_id: int) -> Optional[int]:
    async with self._connect() as db:
      async with db.execute("SELECT autorole_id FROM guild_settings WHERE guild_id = ?", (guild_id,)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row and row[0] else None

  # --- 24/7 Stay-in-Voice Mode ---
  async def set_stay_voice_channel(self, guild_id: int, channel_id: Optional[int]):
    async with self._connect() as db:
      await db.execute(
          """
                INSERT INTO guild_settings (guild_id, stay_voice_channel_id)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET stay_voice_channel_id = excluded.stay_voice_channel_id
                """,
          (guild_id, channel_id),
      )
      await db.commit()

  async def get_stay_voice_channel(self, guild_id: int) -> Optional[int]:
    async with self._connect() as db:
      async with db.execute("SELECT stay_voice_channel_id FROM guild_settings WHERE guild_id = ?", (guild_id,)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row and row[0] else None

  # --- Custom Action Triggers ---
  async def set_action_trigger(
      self, guild_id: int, phrase: str, action_type: str, param_value: int = 15, custom_reply: str = ""
  ):
    async with self._connect() as db:
      await db.execute(
          """
                INSERT INTO custom_action_triggers (guild_id, phrase, action_type, param_value, custom_reply)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, phrase) DO UPDATE SET
                    action_type = excluded.action_type,
                    param_value = excluded.param_value,
                    custom_reply = excluded.custom_reply
                """,
          (guild_id, phrase.lower().strip(), action_type.lower().strip(), param_value, custom_reply),
      )
      await db.commit()

  async def increment_trigger_usage(self, guild_id: int, phrase: str):
    async with self._connect() as db:
      await db.execute(
          "UPDATE custom_action_triggers SET usage_count = COALESCE(usage_count, 0) + 1 WHERE guild_id = ? AND phrase = ?",
          (guild_id, phrase.lower().strip()),
      )
      await db.commit()

  async def remove_action_trigger(self, guild_id: int, phrase: str) -> int:
    async with self._connect() as db:
      cursor = await db.execute(
          "DELETE FROM custom_action_triggers WHERE guild_id = ? AND phrase = ?",
          (guild_id, phrase.lower().strip()),
      )
      await db.commit()
      return cursor.rowcount

  async def get_action_triggers(self, guild_id: int) -> Dict[str, Dict[str, Any]]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute(
          "SELECT phrase, action_type, param_value, custom_reply, COALESCE(usage_count, 0) AS usage_count FROM custom_action_triggers WHERE guild_id = ?",
          (guild_id,),
      ) as cursor:
        rows = await cursor.fetchall()
        return {r["phrase"]: dict(r) for r in rows}

  # --- Harem Methods ---
  async def add_harem_member(self, user_id: int, display_name: str, custom_title: str = "الحريم"):
    async with self._connect() as db:
      await db.execute(
          """
                INSERT INTO harem_members (user_id, display_name, custom_title)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    custom_title = excluded.custom_title
                """,
          (user_id, display_name, custom_title),
      )
      await db.commit()

  async def remove_harem_member(self, user_id: int) -> int:
    async with self._connect() as db:
      cursor = await db.execute("DELETE FROM harem_members WHERE user_id = ?", (user_id,))
      await db.commit()
      return cursor.rowcount

  async def get_all_harem_members(self) -> Dict[int, Dict[str, Any]]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute("SELECT * FROM harem_members ORDER BY added_at ASC") as cursor:
        rows = await cursor.fetchall()
        return {r["user_id"]: dict(r) for r in rows}

  # --- AI Memory ---
  async def check_and_expire_old_session(self, channel_id: int, user_id: int, timeout_hours: int) -> bool:
    async with self._connect() as db:
      async with db.execute(
          "SELECT MAX(created_at) FROM messages WHERE channel_id = ? AND user_id = ?",
          (channel_id, user_id),
      ) as cursor:
        row = await cursor.fetchone()
        if not row or not row[0]:
          return False
        last_time = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last_time > timedelta(hours=timeout_hours):
          await db.execute(
              "DELETE FROM messages WHERE channel_id = ? AND user_id = ?", (channel_id, user_id)
          )
          await db.execute(
              "DELETE FROM user_summaries WHERE channel_id = ? AND user_id = ?",
              (channel_id, user_id),
          )
          await db.commit()
          return True
    return False

  async def add_exchange(self, channel_id: int, user_id: int, user_msg: str, model_reply: str):
    async with self._connect() as db:
      # opt_out is evaluated in the statement: `/data delete` racing an in-flight reply used
      # to re-insert the member it had just erased (P-004).
      for role, text in (("user", user_msg), ("model", model_reply)):
        await db.execute(
            "INSERT INTO messages (channel_id, user_id, role, content) "
            "SELECT ?, ?, ?, ? WHERE NOT EXISTS ("
            "SELECT 1 FROM user_preferences WHERE user_id = ? AND opt_out = 1)",
            (channel_id, user_id, role, text, user_id),
        )
      await db.commit()

  async def get_context_data(self, channel_id: int, user_id: int) -> Tuple[Optional[str], List[Dict[str, str]]]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute(
          "SELECT summary FROM user_summaries WHERE channel_id = ? AND user_id = ?",
          (channel_id, user_id),
      ) as cur_sum:
        sum_row = await cur_sum.fetchone()
        summary = sum_row["summary"] if sum_row else None
      async with db.execute(
          "SELECT id, role, content FROM messages WHERE channel_id = ? AND user_id = ? ORDER BY id ASC",
          (channel_id, user_id),
      ) as cur_msg:
        rows = await cur_msg.fetchall()
        messages = [{"id": r["id"], "role": r["role"], "content": r["content"]} for r in rows]
      return summary, messages

  async def apply_summary_and_prune(self, channel_id: int, user_id: int, new_summary: str, max_id_to_delete: int):
    """Store a background summary. The opt-out guard covers the race where `/data delete`
    ran while `_background_summarize_user` was awaiting the model: the summary must not
    re-create rows for a member who just erased their data."""
    async with self._connect() as db:
      async with db.execute(
          "SELECT 1 FROM user_preferences WHERE user_id = ? AND opt_out = 1", (user_id,)
      ) as opt_cur:
        if await opt_cur.fetchone():
          return
      await db.execute(
          """
                INSERT INTO user_summaries (channel_id, user_id, summary, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(channel_id, user_id) DO UPDATE SET summary = excluded.summary, updated_at = CURRENT_TIMESTAMP
                """,
          (channel_id, user_id, new_summary),
      )
      await db.execute(
          "DELETE FROM messages WHERE channel_id = ? AND user_id = ? AND id <= ?",
          (channel_id, user_id, max_id_to_delete),
      )
      await db.commit()

  async def clear_user_memory(self, channel_id: int, user_id: int):
    """Erase what Angel remembers about one conversation, not the whole member.

    The old version kept `user_profile` and `user_dossier`, so "forget me" was false: the
    facts kept being re-injected into every later prompt. Explicitly pinned preferences stay
    (the user asked to remember those on purpose) and so do other conversations.
    """
    async with self._connect() as db:
      await db.execute(
          "DELETE FROM messages WHERE channel_id = ? AND user_id = ?", (channel_id, user_id)
      )
      await db.execute(
          "DELETE FROM user_summaries WHERE channel_id = ? AND user_id = ?", (channel_id, user_id)
      )
      await db.execute("DELETE FROM user_profile WHERE user_id = ?", (user_id,))
      await db.execute("DELETE FROM user_dossier WHERE user_id = ?", (user_id,))
      await db.commit()

  # Per-member tables and the column that identifies the member. `/data delete` iterates
  # this map, and tests/test_privacy_lifecycle.py (DeletionCoverageTest) fails when the
  # live schema grows a user-bearing table that is neither here nor in USER_DATA_EXEMPT.
  USER_DATA_TABLES = {
      "server_messages": "user_id",
      "messages": "user_id",
      "user_summaries": "user_id",
      "user_profile": "user_id",
      "user_dossier": "user_id",
      "dm_logs": "sender_id",
      "user_index": "user_id",
      "ambient_log": "user_id",
      "afk_users": "user_id",
      "harem_members": "user_id",
      "user_xp": "user_id",
  }
  # Deliberately retained, with the reason the user is told about:
  USER_DATA_EXEMPT = {
      "user_preferences": "kept with opt_out=1 only, so nothing is learned again",
      "warnings": "moderation evidence owned by the server, not the member's chat history",
      "saved_playlists": "guild playlists, keyed by whoever added them",
      "server_knowledge": "staff-authored server notes",
      "admin_memory": "staff-authored admin notes",
      "rules": "the server's own rule text",
      "giveaways": "guild-scoped, participants stored as an opaque id list",
      "custom_action_triggers": "guild automation",
      "auto_triggers": "guild automation",
      "guild_settings": "guild configuration",
      "guild_daily_usage": "guild counters",
      "silent_channels": "guild configuration",
      "sticky_messages": "guild configuration",
      "sticky_state": "guild configuration",
      "persona_culture": "guild aggregate derived from speech; cleared when the member spoke there",
      "server_messages_fts": "FTS shadow of server_messages (synced by trigger)",
      "user_profile_fts": "FTS shadow of user_profile (synced by trigger)",
      "rules_fts": "FTS shadow of rules (synced by trigger)",
      "llm_usage": "aggregated cost counters, no member identity",
      "state": "bot state, no member identity",
      "bot_flags": "bot state, no member identity",
      "gif_pool": "GIF URLs only",
      "persona_state": "persona state",
      "modlog": "guild configuration",
      "metrics": "aggregated counters",
  }

  async def count_user_data(self, user_id: int) -> Dict[str, int]:
    """What the bot currently holds for one member, used by `/data view`.

    Counts the same tables that `/data delete` erases; reporting a shorter list was how
    the command told members "this is everything" while rows remained (C-006).
    """
    out: Dict[str, int] = {}
    failed: List[str] = []
    async with self._connect() as db:
      for table, column in self.USER_DATA_TABLES.items():
        try:
          async with db.execute(
              f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (user_id,)
          ) as cur:
            row = await cur.fetchone()
          out[table] = int(row[0] if row else 0)
        except Exception as exc:
          # A locked or damaged table must not silently vanish from the list the
          # member is told is complete; `delete_all_user_data` reports the same way.
          logger.warning("count from %s failed: %s: %s", table, type(exc).__name__, exc)
          failed.append(table)
    if failed:
      out["_failed_tables"] = failed  # type: ignore[assignment]
    return out

  async def delete_all_user_data(self, user_id: int) -> Dict[str, int]:
    """Erase every per-member row the bot holds, and stop learning from them.

    This is the `/data delete` path. It covers the archive, the rolling chat window, the
    summary, inferred facts, the member index, ambient lines, AFK state, harem membership,
    XP and the DM mirror. The preference row survives only to carry `opt_out = 1`, so
    nothing is re-learned on the next message. `warnings` stays because it is moderation
    evidence owned by the server; the reply text says so.
    """
    counts: Dict[str, int] = {}
    failed: List[str] = []
    async with self._connect() as db:
      # persona_culture is an aggregate derived from member speech: clear the guilds this
      # member actually spoke in, otherwise the aggregate keeps reflecting them.
      async with db.execute(
          "SELECT DISTINCT guild_id FROM server_messages WHERE user_id = ? "
          "UNION SELECT DISTINCT guild_id FROM user_index WHERE user_id = ?",
          (user_id, user_id),
      ) as cur:
        guild_ids = [row[0] for row in await cur.fetchall()]
      for table, column in self.USER_DATA_TABLES.items():
        try:
          cur = await db.execute(f"DELETE FROM {table} WHERE {column} = ?", (user_id,))
          counts[table] = int(cur.rowcount or 0)
        except Exception as exc:
          # A locked or damaged table must not be reported as "deleted" to the member.
          logger.warning("delete from %s failed: %s: %s", table, type(exc).__name__, exc)
          failed.append(table)
      for gid in guild_ids:
        try:
          cur = await db.execute("DELETE FROM persona_culture WHERE guild_id = ?", (gid,))
          counts["persona_culture"] = counts.get("persona_culture", 0) + int(cur.rowcount or 0)
        except Exception as exc:
          logger.warning("persona_culture delete failed: %s", type(exc).__name__)
          failed.append("persona_culture")
          break
      await db.execute(
          "INSERT INTO user_preferences (user_id, pinned_facts, style_mode, opt_out, updated_at) "
          "VALUES (?, '', 'realistic', 1, CURRENT_TIMESTAMP) "
          "ON CONFLICT(user_id) DO UPDATE SET pinned_facts = '', opt_out = 1, updated_at = CURRENT_TIMESTAMP",
          (user_id,),
      )
      await db.commit()
    if failed:
      # The caller surfaces this instead of a clean receipt.
      counts["_failed"] = len(failed)  # type: ignore[assignment]
      counts["_failed_tables"] = failed  # type: ignore[assignment]
    return counts

  # --- DM Spy Logs ---
  async def log_dm(self, sender_id: int, sender_name: str, content: str, attachments: str, angel_reply: str):
    async with self._connect() as db:
      # A member who deleted their data (`opt_out = 1`) must not be logged again.
      await db.execute(
          "INSERT INTO dm_logs (sender_id, sender_name, content, attachments, angel_reply) "
          "SELECT ?, ?, ?, ?, ? WHERE NOT EXISTS ("
          "SELECT 1 FROM user_preferences WHERE user_id = ? AND opt_out = 1)",
          (sender_id, sender_name, content, attachments, angel_reply, sender_id),
      )
      await db.commit()

  async def get_recent_dm_logs(self, limit: int = 15) -> List[Dict[str, Any]]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute("SELECT * FROM dm_logs ORDER BY id DESC LIMIT ?", (limit,)) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

  # --- Warnings & Settings ---
  async def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
    async with self._connect() as db:
      await db.execute(
          "INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
          (guild_id, user_id, moderator_id, reason),
      )
      await db.commit()
      async with db.execute("SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 1

  async def get_warnings(self, guild_id: int, user_id: int) -> List[Dict]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute(
          "SELECT id, moderator_id, reason, created_at FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY id DESC",
          (guild_id, user_id),
      ) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

  async def clear_warnings(self, guild_id: int, user_id: int) -> int:
    async with self._connect() as db:
      cursor = await db.execute("DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
      await db.commit()
      return cursor.rowcount

  async def set_modlog_channel(self, guild_id: int, channel_id: Optional[int]):
    async with self._connect() as db:
      await db.execute(
          """
                INSERT INTO guild_settings (guild_id, modlog_channel_id)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET modlog_channel_id = excluded.modlog_channel_id
                """,
          (guild_id, channel_id),
      )
      await db.commit()

  async def get_modlog_channel(self, guild_id: int) -> Optional[int]:
    async with self._connect() as db:
      async with db.execute("SELECT modlog_channel_id FROM guild_settings WHERE guild_id = ?", (guild_id,)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row and row[0] else None

  # --- AFK System (guild-scoped) ---
  async def set_afk(self, guild_id: int, user_id: int, reason: str) -> bool:
    """Set AFK state. Returns False for an opted-out member: the SQL guard keeps their
    rows gone after `/data delete`, and the caller must not cache the state either."""
    async with self._connect() as db:
      async with db.execute(
          "SELECT 1 FROM user_preferences WHERE user_id = ? AND opt_out = 1", (user_id,)
      ) as opt_cur:
        if await opt_cur.fetchone():
          return False
      await db.execute(
          "INSERT OR REPLACE INTO afk_users (guild_id, user_id, reason, since) "
          "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
          (guild_id, user_id, reason),
      )
      await db.commit()
      return True

  async def remove_afk(self, guild_id: int, user_id: int) -> Optional[Tuple[str, str]]:
    async with self._connect() as db:
      async with db.execute(
          "SELECT reason, since FROM afk_users WHERE guild_id = ? AND user_id = ?",
          (guild_id, user_id),
      ) as cursor:
        row = await cursor.fetchone()
        if not row:
          return None
      await db.execute(
          "DELETE FROM afk_users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
      )
      await db.commit()
      return row[0], row[1]

  async def get_afk(self, guild_id: int, user_id: int) -> Optional[Tuple[str, str]]:
    async with self._connect() as db:
      async with db.execute(
          "SELECT reason, since FROM afk_users WHERE guild_id = ? AND user_id = ?",
          (guild_id, user_id),
      ) as cursor:
        row = await cursor.fetchone()
        return (row[0], row[1]) if row else None

  async def get_all_afk(self) -> Dict[Tuple[int, int], Tuple[str, str]]:
    async with self._connect() as db:
      async with db.execute("SELECT guild_id, user_id, reason, since FROM afk_users") as cursor:
        rows = await cursor.fetchall()
        return {(r[0], r[1]): (r[2], r[3]) for r in rows}

  async def get_all_guild_settings_map(self) -> Dict[int, Dict[str, Any]]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute("SELECT * FROM guild_settings") as cursor:
        rows = await cursor.fetchall()
        return {r["guild_id"]: dict(r) for r in rows}

  # --- Multi-tenant guild settings & quota (Phase D) ---
  async def get_guild_settings(self, guild_id: int) -> Optional[Dict[str, Any]]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)) as cursor:
        row = await cursor.fetchone()
        if row is None:
          return None
        data = dict(row)
        data["guard_level"] = data.get("guard_mode") or "off"
        return data

  async def upsert_guild_settings(
      self,
      guild_id: int,
      *,
      dialect: Optional[str] = None,
      guard_level: Optional[str] = None,
      social_fixer_enabled: Optional[bool] = None,
  ) -> None:
    """Update only the fields that were supplied; omitted fields keep their value."""
    from datetime import datetime, timezone
    fields = []
    params: list = []
    if dialect is not None:
      fields.append("dialect = ?")
      params.append(dialect)
    if guard_level is not None:
      fields.append("guard_mode = ?")
      params.append(guard_level)
    if social_fixer_enabled is not None:
      fields.append("social_fixer_enabled = ?")
      params.append(int(bool(social_fixer_enabled)))
    async with self._connect() as db:
      await db.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
      if fields:
        fields.append("updated_at = ?")
        params.extend([datetime.now(timezone.utc).isoformat(), guild_id])
        await db.execute(
            f"UPDATE guild_settings SET {', '.join(fields)} WHERE guild_id = ?", params)
      await db.commit()

  async def consume_guild_ai_quota(self, guild_id: int) -> Tuple[bool, int]:
    """Atomically reserve one AI reply for a guild today: (allowed, used_after)."""
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with self._connect() as db:
      await db.execute(
          "INSERT INTO guild_daily_usage (guild_id, day_utc, ai_calls) VALUES (?, ?, 0) "
          "ON CONFLICT(guild_id, day_utc) DO NOTHING",
          (guild_id, day),
      )
      limit = 40
      async with db.execute("SELECT daily_ai_limit FROM guild_settings WHERE guild_id = ?", (guild_id,)) as cursor:
        row = await cursor.fetchone()
        if row and row[0] is not None:
          limit = int(row[0])
      cursor = await db.execute(
          "UPDATE guild_daily_usage SET ai_calls = ai_calls + 1 "
          "WHERE guild_id = ? AND day_utc = ? AND ai_calls < ?",
          (guild_id, day, limit),
      )
      allowed = cursor.rowcount == 1
      async with db.execute(
          "SELECT ai_calls FROM guild_daily_usage WHERE guild_id = ? AND day_utc = ?",
          (guild_id, day),
      ) as cursor:
        used_row = await cursor.fetchone()
      await db.commit()
    return bool(allowed), int(used_row[0]) if used_row else 0

  async def get_guild_ai_usage(self, guild_id: int) -> Tuple[int, int]:
    """Read-only (used, limit) for today's guild AI quota."""
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with self._connect() as db:
      limit = 40
      async with db.execute(
          "SELECT daily_ai_limit FROM guild_settings WHERE guild_id = ?", (guild_id,)
      ) as cursor:
        row = await cursor.fetchone()
        if row and row[0] is not None:
          limit = int(row[0])
      async with db.execute(
          "SELECT ai_calls FROM guild_daily_usage WHERE guild_id = ? AND day_utc = ?",
          (guild_id, day),
      ) as cursor:
        used_row = await cursor.fetchone()
    return (int(used_row[0]) if used_row else 0), limit

  async def refund_guild_ai_quota(self, guild_id: int) -> None:
    """Give back one reserved call when the provider failed before answering."""
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with self._connect() as db:
      await db.execute(
          "UPDATE guild_daily_usage "
          "SET ai_calls = CASE WHEN ai_calls > 0 THEN ai_calls - 1 ELSE 0 END "
          "WHERE guild_id = ? AND day_utc = ?",
          (guild_id, day),
      )
      await db.commit()

  # --- Leveling & XP ---
  async def add_xp(self, guild_id: int, user_id: int, xp_gain: int) -> Tuple[int, int, bool]:
    async with self._connect() as db:
      # A member who ran `/data delete` must not have an XP row re-created by the next line
      # they type (C-006). The predicate lives in SQL so a concurrent write cannot win.
      async with db.execute(
          "SELECT 1 FROM user_preferences WHERE user_id = ? AND opt_out = 1", (user_id,)
      ) as opt_cur:
        if await opt_cur.fetchone():
          return 0, 1, False
      async with db.execute("SELECT xp, level, messages_count FROM user_xp WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cursor:
        row = await cursor.fetchone()
        curr_xp, curr_lvl, msgs = (row[0], row[1], row[2]) if row else (0, 1, 0)
      new_xp = curr_xp + xp_gain
      new_msgs = msgs + 1
      calc_lvl = max(1, int(0.1 * math.sqrt(new_xp)) + 1)
      leveled_up = calc_lvl > curr_lvl
      await db.execute(
          """
                INSERT INTO user_xp (guild_id, user_id, xp, level, messages_count)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    xp = excluded.xp, level = excluded.level, messages_count = excluded.messages_count
                """,
          (guild_id, user_id, new_xp, calc_lvl, new_msgs),
      )
      await db.commit()
      return new_xp, calc_lvl, leveled_up

  async def get_user_rank(self, guild_id: int, user_id: int) -> Tuple[int, int, int, int, int]:
    async with self._connect() as db:
      async with db.execute("SELECT xp, level, messages_count, COALESCE(rep_points, 0) FROM user_xp WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)) as cursor:
        row = await cursor.fetchone()
        if not row:
          return 0, 1, 0, 0, 0
        xp, lvl, msgs, rep = row[0], row[1], row[2], row[3]
      async with db.execute("SELECT COUNT(*) FROM user_xp WHERE guild_id = ? AND xp > ?", (guild_id, xp)) as cur_rank:
        r_row = await cur_rank.fetchone()
        rank_pos = (r_row[0] if r_row else 0) + 1
      return xp, lvl, msgs, rank_pos, rep

  async def get_leaderboard(self, guild_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute("SELECT user_id, xp, level, messages_count, COALESCE(rep_points, 0) AS rep_points FROM user_xp WHERE guild_id = ? ORDER BY xp DESC LIMIT ?", (guild_id, limit)) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

  # --- Auto-Responder Triggers ---
  async def set_auto_trigger(self, guild_id: int, trigger_word: str, response_text: str):
    async with self._connect() as db:
      await db.execute(
          """
                INSERT INTO auto_triggers (guild_id, trigger_word, response_text)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, trigger_word) DO UPDATE SET response_text = excluded.response_text
                """,
          (guild_id, trigger_word.lower().strip(), response_text),
      )
      await db.commit()

  async def remove_auto_trigger(self, guild_id: int, trigger_word: str) -> int:
    async with self._connect() as db:
      cursor = await db.execute("DELETE FROM auto_triggers WHERE guild_id = ? AND trigger_word = ?", (guild_id, trigger_word.lower().strip()))
      await db.commit()
      return cursor.rowcount

  async def get_auto_triggers(self, guild_id: int) -> Dict[str, str]:
    async with self._connect() as db:
      async with db.execute("SELECT trigger_word, response_text FROM auto_triggers WHERE guild_id = ?", (guild_id,)) as cursor:
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}

  # --- Giveaways ---
  async def create_giveaway(self, message_id: int, channel_id: int, guild_id: int, prize: str, winners_count: int, end_at_str: str):
    async with self._connect() as db:
      await db.execute(
          "INSERT INTO giveaways (message_id, channel_id, guild_id, prize, winners_count, end_at) VALUES (?, ?, ?, ?, ?, ?)",
          (message_id, channel_id, guild_id, prize, winners_count, end_at_str),
      )
      await db.commit()

  async def toggle_giveaway_participant(self, message_id: int, user_id: int) -> Tuple[bool, int]:
    async with self._connect() as db:
      async with db.execute("SELECT participants, ended FROM giveaways WHERE message_id = ?", (message_id,)) as cursor:
        row = await cursor.fetchone()
        if not row or row[1] == 1:
          return False, 0
        parts = set(x for x in (row[0] or "").split(",") if x.strip())
        uid_str = str(user_id)
        if uid_str in parts:
          parts.remove(uid_str)
          entered = False
        else:
          parts.add(uid_str)
          entered = True
      await db.execute("UPDATE giveaways SET participants = ? WHERE message_id = ?", (",".join(parts), message_id))
      await db.commit()
      return entered, len(parts)

  async def get_due_giveaways(self, now_str: str) -> List[Dict[str, Any]]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute("SELECT * FROM giveaways WHERE ended = 0 AND end_at <= ?", (now_str,)) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

  async def mark_giveaway_ended(self, message_id: int):
    async with self._connect() as db:
      await db.execute("UPDATE giveaways SET ended = 1 WHERE message_id = ?", (message_id,))
      await db.commit()


  # --- Silence map (owner toggle: /silence) ---
  async def set_silent(self, guild_id: int, channel_id: int, silent: bool, added_by: int = 0):
    """channel_id = 0 means the whole guild is silenced."""
    async with self._connect() as db:
      if silent:
        await db.execute(
            "INSERT OR REPLACE INTO silent_channels (guild_id, channel_id, added_by) VALUES (?, ?, ?)",
            (guild_id, channel_id, added_by),
        )
      else:
        await db.execute(
            "DELETE FROM silent_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
      await db.commit()

  async def get_silent_map(self) -> Dict[int, set]:
    async with self._connect() as db:
      out: Dict[int, set] = {}
      async with db.execute("SELECT guild_id, channel_id FROM silent_channels") as cur:
        async for row in cur:
          out.setdefault(int(row["guild_id"]), set()).add(int(row["channel_id"]))
      return out

  # --- Structured per-user memory (facts) ---
  async def upsert_profile_fact(
      self, user_id: int, fact_key: str, fact_value: str, confidence: float = 0.7, source: str = "chat"
  ):
    key = (fact_key or "").strip()[:60].lower()
    val = (fact_value or "").strip()[:400]
    if not key or not val:
      return
    async with self._connect() as db:
      await db.execute(
          """
          INSERT INTO user_profile (user_id, fact_key, fact_value, confidence, source, updated_at)
          VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, fact_key) DO UPDATE SET
              fact_value = excluded.fact_value,
              confidence = excluded.confidence,
              source = excluded.source,
              updated_at = CURRENT_TIMESTAMP
          """,
          (user_id, key, val, float(confidence), source),
      )
      await db.commit()

  async def get_profile_facts(self, user_id: int, limit: int = 40) -> List[Dict[str, Any]]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute(
          "SELECT fact_key, fact_value, confidence, updated_at FROM user_profile "
          "WHERE user_id = ? ORDER BY confidence DESC, updated_at DESC LIMIT ?",
          (user_id, limit),
      ) as cur:
        return [dict(r) async for r in cur]

  async def ensure_archive_index(self) -> None:
    """FTS5 over the human archive. Built once, then kept in sync by triggers.

    INSERT alone is not enough: the 365-day retention deletes rows, and an external-content
    FTS table without a delete trigger keeps them in the index (stale hits, failed
    integrity-check). Update is covered for completeness.
    """
    rebuild = getattr(self, "_fts_rebuild_needed", False)
    async with self._connect() as db:
      if not rebuild:
        try:
          async with db.execute(
              "SELECT value FROM state WHERE key = 'fts_rebuild_pending'"
          ) as cur:
            row = await cur.fetchone()
          rebuild = bool(row and row[0] == "1")
        except Exception:
          rebuild = False
      await db.executescript(
          "CREATE VIRTUAL TABLE IF NOT EXISTS server_messages_fts USING fts5("
          " content, display_name, channel_id UNINDEXED, created_at UNINDEXED,"
          " content='server_messages', content_rowid='id',"
          " tokenize='unicode61 remove_diacritics 2');"
      )
      await db.executescript(
          "CREATE TRIGGER IF NOT EXISTS server_messages_ai AFTER INSERT ON server_messages BEGIN "
          " INSERT INTO server_messages_fts(rowid, content, display_name, channel_id, created_at)"
          " VALUES (new.id, new.content, new.display_name, new.channel_id, new.created_at); END;"
      )
      await db.executescript(
          "CREATE TRIGGER IF NOT EXISTS server_messages_ad AFTER DELETE ON server_messages BEGIN "
          " INSERT INTO server_messages_fts(server_messages_fts, rowid, content, display_name, channel_id, created_at)"
          " VALUES ('delete', old.id, old.content, old.display_name, old.channel_id, old.created_at); END;"
      )
      await db.executescript(
          "CREATE TRIGGER IF NOT EXISTS server_messages_au AFTER UPDATE ON server_messages BEGIN "
          " INSERT INTO server_messages_fts(server_messages_fts, rowid, content, display_name, channel_id, created_at)"
          " VALUES ('delete', old.id, old.content, old.display_name, old.channel_id, old.created_at);"
          " INSERT INTO server_messages_fts(rowid, content, display_name, channel_id, created_at)"
          " VALUES (new.id, new.content, new.display_name, new.channel_id, new.created_at); END;"
      )
      await db.commit()
      if rebuild:
        # The tokenizer migration dropped the old index; repopulate it from the archive.
        await db.execute("INSERT INTO server_messages_fts(server_messages_fts) VALUES('rebuild')")
        await db.execute("DELETE FROM state WHERE key = 'fts_rebuild_pending'")
        await db.commit()
        self._fts_rebuild_needed = False

  async def reindex_archive(self) -> int:
    await self.ensure_archive_index()
    async with self._connect() as db:
      await db.execute("INSERT INTO server_messages_fts(server_messages_fts) VALUES('rebuild')")
      await db.commit()
      async with db.execute("SELECT count(*) FROM server_messages_fts") as cur:
        return (await cur.fetchone())[0]

  async def search_archive(self, keywords: list, limit: int = 8,
                           guild_id: Optional[int] = None,
                           allowed_channels: Optional[set] = None):
    """Top archive lines for a question, newest first among the best matches.

    `guild_id` and `allowed_channels` keep a recall answer inside the room the asker can
    actually read: the archive holds every channel the bot sees, including tickets.
    """
    clean = [k for k in keywords if k and len(k) >= 3][:6]
    if not clean:
      return []
    match = _fts_query(" ".join(clean))
    if not match:
      return []
    if allowed_channels is None:
      # Fail closed: the archive holds tickets and staff rooms, so an unfiltered search is
      # never the safe default (P-002).
      logger.warning("archive search refused: no allowed channel set")
      return []
    allowed = [int(c) for c in allowed_channels]
    if not allowed:
      return []
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      try:
        placeholders = ",".join("?" for _ in allowed)
        sql = ("SELECT m.content, m.display_name, m.channel_id, m.created_at "
               "FROM server_messages_fts f JOIN server_messages m ON m.id = f.rowid "
               f"WHERE server_messages_fts MATCH ? AND m.channel_id IN ({placeholders})")
        params: list = [match, *allowed]
        if guild_id is not None:
          sql += " AND m.guild_id = ?"
          params.append(guild_id)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        async with db.execute(sql, params) as cur:
          return [dict(r) async for r in cur]
      except Exception as exc:
        logger.warning("archive FTS query failed: %s: %s", type(exc).__name__, exc)
        return []

  async def get_user_dossier(self, user_id: int):
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute(
          "SELECT summary, facts_json, style, topics, notes FROM user_dossier WHERE user_id = ?",
          (user_id,),
      ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None

  async def channel_of_quote(self, user_id: int, quote: str) -> Optional[int]:
    """Channel the cited words came from; a dossier cites the member, not the room."""
    async with self._connect() as db:
      async with db.execute(
          "SELECT channel_id FROM server_messages WHERE user_id = ? AND content LIKE ? ESCAPE '\\' "
          "ORDER BY created_at DESC LIMIT 1",
          (user_id, f"%{_like_escape(quote)}%"),
      ) as cur:
        row = await cur.fetchone()
        return row[0] if row else None


  async def get_persona_culture(self, guild_id: int):
    async with self._connect() as db:
      await db.execute(
          "CREATE TABLE IF NOT EXISTS persona_culture ("
          " guild_id INTEGER PRIMARY KEY, notes_json TEXT, updated_at TEXT)"
      )
      await db.commit()
      async with db.execute("SELECT notes_json FROM persona_culture WHERE guild_id = ?", (guild_id,)) as cur:
        row = await cur.fetchone()
        return row[0] if row else None

  async def set_persona_culture(self, guild_id: int, notes_json: str) -> None:
    async with self._connect() as db:
      await db.execute(
          "CREATE TABLE IF NOT EXISTS persona_culture ("
          " guild_id INTEGER PRIMARY KEY, notes_json TEXT, updated_at TEXT)"
      )
      await db.execute(
          "INSERT INTO persona_culture (guild_id, notes_json, updated_at) VALUES (?,?,datetime('now')) "
          "ON CONFLICT(guild_id) DO UPDATE SET notes_json=excluded.notes_json, updated_at=datetime('now')",
          (guild_id, notes_json),
      )
      await db.commit()

  async def log_server_message(self, guild_id: int, channel_id: int, user_id: int,
                               display_name: str, content: str,
                               message_id: Optional[int] = None) -> None:
    """Every human message is a lesson: keep the raw line so learning can look back at it.

    Growth is bounded: rows older than 365 days are dropped on a 1-in-500 insert, which keeps
    the table near a rolling year without a cron job or a VACUUM storm.
    """
    text = (content or "").strip()
    if not text:
      return
    async with self._connect() as db:
      if not getattr(self, "_server_log_ready", False):
        await db.executescript(
            "CREATE TABLE IF NOT EXISTS server_messages ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,"
            " user_id INTEGER NOT NULL, display_name TEXT,"
            " content TEXT NOT NULL, created_at TEXT NOT NULL, message_id TEXT);"
            "CREATE INDEX IF NOT EXISTS idx_srv_msg_guild ON server_messages (guild_id, created_at);"
            "CREATE INDEX IF NOT EXISTS idx_srv_msg_user ON server_messages (user_id, created_at);"
      "CREATE INDEX IF NOT EXISTS idx_srv_msg_created ON server_messages (created_at);"
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_srv_msg_mid ON server_messages (message_id);"
            # The insert below carries the opt-out predicate, so the preferences table must
            # exist even when this tool is the first thing to touch the file.
            "CREATE TABLE IF NOT EXISTS user_preferences ("
            " user_id INTEGER PRIMARY KEY, pinned_facts TEXT DEFAULT '',"
            " style_mode TEXT DEFAULT 'realistic', opt_out INTEGER DEFAULT 0,"
            " updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
        )
        self._server_log_ready = True
      # message_id makes the live line and a later backfill of the same Discord message one
      # row instead of two (the text/timestamp pair was never identical between the two).
      await db.execute(
          "INSERT OR IGNORE INTO server_messages "
          "(guild_id, channel_id, user_id, display_name, content, created_at, message_id) "
          "SELECT ?, ?, ?, ?, ?, ?, ? WHERE NOT EXISTS ("
          "SELECT 1 FROM user_preferences WHERE user_id = ? AND opt_out = 1)",
          (guild_id, channel_id, user_id, display_name[:80], text[:1500],
           datetime.now(timezone.utc).isoformat(timespec="seconds"),
           str(message_id) if message_id else None, user_id),
      )
      await db.commit()
      # Pruning is the daily retention pass's job (finding 20d); this path only writes.

  async def get_facts_by_keys(self, user_id: int, keys: List[str], limit: int = 12) -> List[Dict[str, Any]]:
    """Exact fact_key recall: a question about "شغلك" must find the stored `job` fact."""
    clean = [k for k in dict.fromkeys(keys) if k]
    if not clean:
      return []
    placeholders = ",".join("?" for _ in clean)
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute(
          f"SELECT fact_key, fact_value, confidence, updated_at FROM user_profile "
          f"WHERE user_id = ? AND fact_key IN ({placeholders}) "
          f"ORDER BY confidence DESC, updated_at DESC LIMIT ?",
          (user_id, *clean, limit),
      ) as cur:
        return [dict(r) async for r in cur]

  async def search_profile_facts(self, user_id: int, keywords: List[str], limit: int = 12) -> List[Dict[str, Any]]:
    """FTS5 recall with LIKE and fuzzy fallbacks (Arabic morphology friendly)."""
    if not keywords:
      return await self.get_profile_facts(user_id, limit)
    match = _fts_query(" ".join(keywords[:8]))
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      if match:
        try:
          async with db.execute(
              """SELECT p.fact_key, p.fact_value, p.confidence
                 FROM user_profile_fts JOIN user_profile p ON p.rowid = user_profile_fts.rowid
                 WHERE user_profile_fts MATCH ? AND p.user_id = ? ORDER BY rank LIMIT ?""",
              (match, user_id, limit),
          ) as cur:
            rows = [dict(r) async for r in cur]
            if rows:
              return rows
        except Exception as exc:
          logger.warning("profile FTS query failed: %s: %s", type(exc).__name__, exc)
      clauses, params = [], [user_id]
      for kw in keywords[:8]:
        clauses.append("(fact_key LIKE ? ESCAPE '\\' OR fact_value LIKE ? ESCAPE '\\')")
        params.extend([f"%{_like_escape(kw)}%", f"%{_like_escape(kw)}%"])
      params.append(limit)
      async with db.execute(
          "SELECT fact_key, fact_value, confidence FROM user_profile WHERE user_id = ? AND ("
          + " OR ".join(clauses) + ") ORDER BY confidence DESC LIMIT ?",
          params,
      ) as cur:
        rows = [dict(r) async for r in cur]
        if rows:
          return rows
      async with db.execute(
          "SELECT fact_key, fact_value, confidence FROM user_profile WHERE user_id = ? ORDER BY confidence DESC LIMIT 80",
          (user_id,),
      ) as cur:
        candidates = [dict(r) async for r in cur]
      return _fuzzy_best(" ".join(keywords[:8]), candidates, "fact_value", limit) or _fuzzy_best(
          " ".join(keywords[:8]), candidates, "fact_key", limit
      )

  async def prune_profile_facts(self, user_id: int, cap: int = 40):
    async with self._connect() as db:
      await db.execute(
          """
          DELETE FROM user_profile WHERE user_id = ? AND fact_key NOT IN (
              SELECT fact_key FROM user_profile WHERE user_id = ?
              ORDER BY confidence DESC, updated_at DESC LIMIT ?
          )
          """,
          (user_id, user_id, cap),
      )
      await db.commit()

  # --- Member index (who talks, how often, about what) ---
  async def touch_user_index(self, guild_id: int, user_id: int, display_name: str = "", topic: str = ""):
    async with self._connect() as db:
      await db.execute(
          """
          INSERT INTO user_index (guild_id, user_id, display_name, last_seen, msg_count, topics)
          SELECT ?, ?, ?, CURRENT_TIMESTAMP, 1, ?
          WHERE NOT EXISTS (SELECT 1 FROM user_preferences WHERE user_id = ? AND opt_out = 1)
          ON CONFLICT(guild_id, user_id) DO UPDATE SET
              display_name = CASE WHEN excluded.display_name != '' THEN excluded.display_name ELSE user_index.display_name END,
              last_seen = CURRENT_TIMESTAMP,
              msg_count = user_index.msg_count + 1,
              topics = CASE WHEN excluded.topics != '' THEN excluded.topics ELSE user_index.topics END
          """,
          (guild_id, user_id, (display_name or "")[:64], (topic or "")[:200], user_id),
      )
      await db.commit()

  async def get_active_users(self, guild_id: int, limit: int = 25) -> List[Dict[str, Any]]:
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute(
          "SELECT user_id, display_name, last_seen, msg_count FROM user_index "
          "WHERE guild_id = ? ORDER BY last_seen DESC LIMIT ?",
          (guild_id, limit),
      ) as cur:
        return [dict(r) async for r in cur]

  # --- Autonomous-chat audit trail (anti-repetition + transparency) ---
  async def log_ambient(self, guild_id: int, channel_id: int, user_id: int, angel_text: str):
    async with self._connect() as db:
      await db.execute(
          "INSERT INTO ambient_log (guild_id, channel_id, user_id, angel_text) "
          "SELECT ?, ?, ?, ? WHERE NOT EXISTS ("
          "SELECT 1 FROM user_preferences WHERE user_id = ? AND opt_out = 1)",
          (guild_id, channel_id, user_id, (angel_text or "")[:600], user_id),
      )
      await db.execute(
          "DELETE FROM ambient_log WHERE id NOT IN (SELECT id FROM ambient_log ORDER BY id DESC LIMIT 400)"
      )
      await db.commit()

  async def get_recent_ambient(self, guild_id: int, channel_id: int, limit: int = 12) -> List[str]:
    async with self._connect() as db:
      async with db.execute(
          "SELECT angel_text FROM ambient_log WHERE guild_id = ? AND channel_id = ? "
          "ORDER BY id DESC LIMIT ?",
          (guild_id, channel_id, limit),
      ) as cur:
        return [r["angel_text"] for r in [x async for x in cur]]


  # --- Generic bot flags (per-guild toggles such as autonomy) ---
  async def get_flag(self, key: str, default: str = "") -> str:
    async with self._connect() as db:
      async with db.execute("SELECT flag_value FROM bot_flags WHERE flag_key = ?", (key,)) as cur:
        row = await cur.fetchone()
        return str(row["flag_value"]) if row else default

  async def get_flags_with_prefix(self, prefix: str) -> Dict[str, str]:
    """All flags whose key starts with `prefix`, without a LIKE wildcard injection surface."""
    async with self._connect() as db:
      async with db.execute(
          "SELECT flag_key, flag_value FROM bot_flags WHERE substr(flag_key, 1, ?) = ?",
          (len(prefix), prefix),
      ) as cur:
        return {r["flag_key"]: str(r["flag_value"]) async for r in cur}

  async def set_flag(self, key: str, value: str):
    async with self._connect() as db:
      await db.execute(
          """
          INSERT INTO bot_flags (flag_key, flag_value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
          ON CONFLICT(flag_key) DO UPDATE SET flag_value = excluded.flag_value, updated_at = CURRENT_TIMESTAMP
          """,
          (key, str(value)),
      )
      await db.commit()


  # --- GIF pool (verified reaction URLs; grows as the engine discovers them) ---
  async def add_gif_url(self, url: str, action: str = "", source: str = "", sapphic: bool = False):
    if not url:
      return
    async with self._connect() as db:
      await db.execute(
          "INSERT OR IGNORE INTO gif_pool (url, action, source, sapphic) VALUES (?, ?, ?, ?)",
          (url, action[:24], source[:24], 1 if sapphic else 0),
      )
      await db.execute(
          "DELETE FROM gif_pool WHERE rowid NOT IN (SELECT rowid FROM gif_pool ORDER BY rowid DESC LIMIT 600)"
      )
      await db.commit()

  async def get_random_gif_urls(self, action: str, sapphic: bool, limit: int = 6) -> List[str]:
    async with self._connect() as db:
      async with db.execute(
          "SELECT url FROM gif_pool WHERE action = ? AND sapphic = ? ORDER BY RANDOM() LIMIT ?",
          (action[:24], 1 if sapphic else 0, limit),
      ) as cur:
        return [r["url"] for r in [x async for x in cur]]


  # ---------- merged from Malak: admin memory (ACL-gated by angel.context_acl) ----------
  async def add_admin_memory(self, guild_id: int, channel_id: int, topic: str, content: str, author_id: int = 0):
    async with self._connect() as db:
      await db.execute(
          "INSERT INTO admin_memory (guild_id, channel_id, topic, content, author_id) VALUES (?, ?, ?, ?, ?)",
          (guild_id, channel_id, topic[:80], content[:800], author_id),
      )
      await db.commit()

  async def read_admin_memory(self, guild_id: int, query: str, limit: int = 4) -> List[Dict[str, Any]]:
    """Callers MUST pass angel.context_acl.require_admin_context first."""
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      async with db.execute(
          "SELECT topic, content, channel_id FROM admin_memory WHERE guild_id = ? "
          "AND (topic LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\') ORDER BY id DESC LIMIT ?",
          (guild_id, f"%{_like_escape(query[:60])}%", f"%{_like_escape(query[:60])}%", limit),
      ) as cur:
        rows = [dict(r) async for r in cur]
        if rows:
          return rows
      async with db.execute(
          "SELECT topic, content, channel_id FROM admin_memory WHERE guild_id = ? ORDER BY id DESC LIMIT 80",
          (guild_id,),
      ) as cur:
        candidates = [dict(r) async for r in cur]
      return _fuzzy_best(query, candidates, "content", limit) or _fuzzy_best(query, candidates, "topic", limit)

  # ---------- rules index ----------
  async def clear_rules(self, guild_id: int) -> None:
    async with self._connect() as db:
      await db.execute("DELETE FROM rules WHERE guild_id = ?", (guild_id,))
      await db.commit()

  async def replace_rules(self, guild_id: int, rules: List[tuple]) -> int:
    """Replace every rule for a guild in ONE transaction.

    The old re-index loop cleared first and then upserted row by row; a failure halfway
    left the guild with a partial rule set.
    """
    async with self._connect() as db:
      # Finish anything the shared connection left open, otherwise BEGIN IMMEDIATE raises
      # "cannot start a transaction within a transaction" and a rollback would discard it.
      await db.commit()
      await db.execute("BEGIN IMMEDIATE")
      try:
        await db.execute("DELETE FROM rules WHERE guild_id = ?", (guild_id,))
        for key, content in rules:
          await db.execute(
              "INSERT INTO rules (guild_id, rule_key, content) VALUES (?, ?, ?)",
              (guild_id, key[:60], content[:1500]),
          )
        await db.commit()
      except Exception:
        await db.rollback()
        raise
    return len(rules)

  async def upsert_rule(self, guild_id: int, key: str, content: str):
    async with self._connect() as db:
      await db.execute(
          """INSERT INTO rules (guild_id, rule_key, content) VALUES (?, ?, ?)
             ON CONFLICT(guild_id, rule_key) DO UPDATE SET content = excluded.content, updated_at = CURRENT_TIMESTAMP""",
          (guild_id, key[:60], content[:1500]),
      )
      await db.commit()

  async def search_rules(self, guild_id: int, query: str, limit: int = 3) -> List[Dict[str, Any]]:
    match = _fts_query(query)
    async with self._connect() as db:
      db.row_factory = aiosqlite.Row
      if match:
        try:
          async with db.execute(
              """SELECT r.rule_key, r.content FROM rules_fts
                 JOIN rules r ON r.id = rules_fts.rowid
                 WHERE rules_fts MATCH ? AND r.guild_id = ? ORDER BY rank LIMIT ?""",
              (match, guild_id, limit),
          ) as cur:
            rows = [dict(r) async for r in cur]
            if rows:
              return rows
        except Exception as exc:
          logger.warning("rules FTS query failed: %s: %s", type(exc).__name__, exc)
      async with db.execute(
          "SELECT rule_key, content FROM rules WHERE guild_id = ? ORDER BY id LIMIT 300", (guild_id,)
      ) as cur:
        candidates = [dict(r) async for r in cur]
      return _fuzzy_best(query, candidates, "content", limit)

  async def rules_corpus_exists(self, guild_id: int) -> bool:
    """Whether any rule is indexed for this guild.

    An empty `search_rules` answer means the question matched nothing; it must not be
    read as "no corpus" or a populated index gets rebuilt from whatever channel the
    caller is standing in.
    """
    async with self._connect() as db:
      async with db.execute(
          "SELECT 1 FROM rules WHERE guild_id = ? LIMIT 1", (guild_id,)
      ) as cur:
        return await cur.fetchone() is not None

  # ---------- USD budget ----------
  async def add_usage(self, day: str, in_tokens: int, out_tokens: int, cost: float, blocked: bool = False) -> float:
    async with self._connect() as db:
      await db.execute(
          """INSERT INTO llm_usage (day, calls, input_tokens, output_tokens, cost_usd, blocked)
             VALUES (?, 1, ?, ?, ?, ?)
             ON CONFLICT(day) DO UPDATE SET
               calls = llm_usage.calls + 1,
               input_tokens = llm_usage.input_tokens + excluded.input_tokens,
               output_tokens = llm_usage.output_tokens + excluded.output_tokens,
               cost_usd = llm_usage.cost_usd + excluded.cost_usd,
               blocked = llm_usage.blocked + excluded.blocked""",
          (day, in_tokens, out_tokens, cost, 1 if blocked else 0),
      )
      await db.commit()
      async with db.execute("SELECT cost_usd FROM llm_usage WHERE day = ?", (day,)) as cur:
        row = await cur.fetchone()
        return float(row["cost_usd"]) if row else 0.0

  async def day_cost(self, day: str) -> float:
    async with self._connect() as db:
      async with db.execute("SELECT cost_usd FROM llm_usage WHERE day = ?", (day,)) as cur:
        row = await cur.fetchone()
        return float(row["cost_usd"]) if row else 0.0

  # ---------- evolving state (mood / behaviour settings) ----------
  async def set_state_value(self, key: str, value: Any):
    import json as _json

    async with self._connect() as db:
      await db.execute(
          """INSERT INTO state (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
             ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP""",
          (key, _json.dumps(value)),
      )
      await db.commit()

  async def get_state_value(self, key: str, default: Any = None) -> Any:
    import json as _json

    async with self._connect() as db:
      async with db.execute("SELECT value FROM state WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
        return _json.loads(row["value"]) if row else default

  async def cleanup_and_vacuum(self, deep: bool = False) -> Tuple[int, int]:
    """
    Prune old transient records, checkpoint WAL to 0 bytes, and optionally VACUUM the SQLite database
    so disk space is reclaimed on the server. Returns (pruned_rows, final_db_bytes).

    The message cap is the shared retention constant: a private 50-row cap here deleted
    rows 51-60 for every member on each 30-minute pass, fighting `_apply_retention`'s
    documented 60. Short summaries are not deleted at all: D-010 removed that rule from
    the startup path, and a legitimate summary like "يحب القهوة" is shorter than 35
    characters.
    """
    pruned = 0
    async with self._connect() as db:
      for sql in (
          "DELETE FROM giveaways WHERE ended = 1 AND end_at <= datetime('now', '-3 days')",
          "DELETE FROM dm_logs WHERE created_at < datetime('now', '-30 days')",
          f"""
          DELETE FROM messages
          WHERE id NOT IN (
              SELECT id FROM (
                  SELECT id, ROW_NUMBER() OVER (PARTITION BY channel_id, user_id ORDER BY id DESC) AS rn
                  FROM messages
              ) WHERE rn <= {self.MESSAGES_RETAINED_PER_USER}
          )
          """,
      ):
        try:
          cur = await db.execute(sql)
          if cur.rowcount and cur.rowcount > 0:
            pruned += cur.rowcount
        except Exception as exc:
          logger.debug("cleanup statement skipped: %s", exc)
      await db.commit()
      if deep:
        try:
          # VACUUM takes an exclusive lock and blocks every other DB call on this host;
          # a passive checkpoint plus incremental vacuum keeps the file healthy without it.
          await db.execute("PRAGMA wal_checkpoint(PASSIVE)")
          await db.execute("PRAGMA incremental_vacuum")
          await db.commit()
        except Exception as exc:
          logger.warning("maintenance checkpoint failed: %s: %s", type(exc).__name__, exc)
      try:
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await db.execute("PRAGMA optimize")
        await db.commit()
      except Exception as exc:
        logger.warning("maintenance optimize failed: %s: %s", type(exc).__name__, exc)

    total_db_bytes = 0
    for suffix in ("", "-wal", "-shm"):
      p = self.db_path + suffix
      if os.path.isfile(p):
        try:
          total_db_bytes += os.path.getsize(p)
        except Exception:
          pass
    return pruned, total_db_bytes
