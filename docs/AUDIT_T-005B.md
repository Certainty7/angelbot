# T-005b — core-module audit (2026-11-19)

Scope: the four tails the first audit never read, plus the `/data delete` guarantee.

## `angel/database.py`

- **SQL parameterisation — OK.** Every statement that takes member or guild input uses
  `?` placeholders. No f-string SQL with user data was found (schema DDL is static).
- **`/data delete` and FTS5 — OK.** `server_messages_fts` is an FTS5 table with
  `AFTER INSERT/UPDATE/DELETE` triggers on `server_messages`; deleting the member's rows
  therefore removes them from the index. `user_profile_fts` has the matching triggers.
  `tests/test_core_hardening.py::test_data_delete_purges_fts_and_rows` proves a unique
  token is no longer recallable after `delete_all_user_data`.
- **RAM caches — fixed.** `/data delete` now also drops the member from
  `recent_speakers`, `last_social_target`, `active_chat_window`, `pending_step`,
  `pending_confirm` and `user_locks` (`cogs/memory_rules.py`). Snipe/edit-snipe entries
  carry no user id, so they are bounded caches and cannot be attributed to a member.
- **Private attributes — fixed.** `_ensure_conn` no longer reads `aiosqlite._running` /
  `._connection`; liveness is tracked by `close()` setting `self._conn = None`.

## `angel/nl_router.py`

- **Privileged actions — OK.** Every destructive branch checks
  `mistress or author.guild_permissions.<permission>` before executing (lines ~644–1780).
  Owner-only branches check `mistress` alone. Destructive actions still pass through the
  60-second `pending_confirm` gate, and the confirmed path re-executes
  `execute_ai_inferred_action(..., confirmed=True)`.
- The server-update phrase now reports read-only instructions instead of running `sudo`.

## `angel/brain.py`

- **Logging — OK.** Logs model, latency, USD and a hashed user tag; prompts and keys are
  never logged.
- **Retry — fixed.** Headers are rebuilt inside the attempt loop and a 429 rotates the
  key, so `GEMINI_API_KEY_2` is actually used. `add_usage` is guarded when `db is None`.

## `angel/config.py`

- Secrets are read from environment only. The import-time `sudo apt-get` path was removed;
  a missing FFmpeg now prints an instruction instead of escalating.

## Backups (D-2)

`scripts/backup_db.sh` writes a verified copy under `ANGEL_BACKUP_DIR` and keeps
`ANGEL_BACKUP_RETENTION_DAYS` (default 14). This retention window is what the Privacy
Policy must disclose; a member's deleted data can survive in an existing backup until the
oldest copy expires.

## Result

No unresolved High-severity issue found in these tails. Two small fixes were applied
(private aiosqlite attributes, RAM cache eviction) and are covered by tests.
