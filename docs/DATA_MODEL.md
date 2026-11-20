# Data model

Every table lives in one SQLite file (`ANGEL_DB_PATH`, default `<repo>/chat_history.db`) in WAL
mode. `angel/database.py` owns the schema; `_run_migrations()` applies one-time data migrations
behind `PRAGMA user_version`. `tests/test_docs_sync.py` fails when a table appears in the schema
but not in this document.

## Per-member tables

`/data delete` erases every row in this group (see `BotDatabase.USER_DATA_TABLES`).

| Table | Key | Holds | Deleted by `/data delete` |
|---|---|---|---|
| `server_messages` | `id` | the durable channel archive (365-day retention) | yes |
| `messages` | `id` | the rolling prompt window for one member (60 lines) | yes |
| `user_summaries` | `user_id` | the rolling conversation summary | yes |
| `user_profile` | `(user_id, fact_key)` | facts inferred by the model from chat, written by `upsert_profile_fact` (`source='chat'`) | yes |
| `user_dossier` | `user_id` | legacy table, emptied by migration v2, no writer | yes |
| `dm_logs` | `id` | the DM mirror seen by the owner (30-day retention) | yes |
| `user_index` | `(guild_id, user_id)` | who speaks, when, message count (no topic profiling) | yes |
| `ambient_log` | `id` | the bot's own ambient lines, capped at 400 rows | yes |
| `afk_users` | `(guild_id, user_id)` | AFK reason and timestamp | yes |
| `harem_members` | `user_id` | owner-curated roster entries | yes |
| `user_xp` | `(guild_id, user_id)` | XP, level, message count, reputation | yes |

`user_preferences` survives a deletion with `opt_out = 1` and an empty `pinned_facts`, because it
is the record that stops the bot from learning about that member again. It also holds the facts a
member pinned explicitly with `/memory pin` (`pinned_facts`) — those are cleared by the deletion.
`user_profile` is a different store: inferred facts, erased by the deletion the same way.

## Server-scoped tables

These are owned by the guild, not by a member, and are deliberately kept:

| Table | Holds |
|---|---|
| `warnings` | moderation evidence (member + moderator ids) |
| `guild_settings` | modlog, welcome, autorole, guard mode, dialect, daily AI cap |
| `guild_daily_usage` | per-guild AI calls per UTC day |
| `silent_channels` | channels where Angel observes without replying |
| `sticky_messages` | the repeating message per channel |
| `auto_triggers` | phrase → canned reply |
| `custom_action_triggers` | phrase → stored moderation action (owner/administrator only) |
| `saved_playlists` | named playlists per guild |
| `giveaways` | prize, end time, participant id list |
| `server_knowledge` | staff-authored notes about the server |
| `admin_memory` | admin-context notes (admin role + admin channel only) |
| `rules` | the indexed rule text |
| `persona_culture` | guild-level persona notes derived from speech (regenerated) |

## Operational tables

| Table | Holds |
|---|---|
| `llm_usage` | per-day calls, tokens, USD and blocked-call counter (no member identity) |
| `state` | small key/value bot state, including the last retention pass date |
| `bot_flags` | feature flags, including per-guild autonomy |
| `gif_pool` | cached GIF URLs |

## Full-text indexes

| Index | Content | Sync |
|---|---|---|
| `server_messages_fts` | `server_messages.content` and `display_name`, `unicode61 remove_diacritics 2` | `server_messages_ai/ad/au` triggers |
| `rules_fts` | `rules.rule_key` and `content` | `rules_ai/ad/au` triggers |
| `user_profile_fts` | `user_profile.fact_key` and `fact_value` | `user_profile_ai/ad/au` triggers |

The `*_config`, `*_data`, `*_docsize` and `*_idx` tables are FTS5 shadow tables. Do not query or
migrate them directly; recreate the virtual table and rebuild instead.

## Retention

Once per UTC day, `_apply_retention()` removes:

- `dm_logs` older than 30 days;
- `messages` beyond the 60 newest per member (the shared `MESSAGES_RETAINED_PER_USER`
  constant, also used by the periodic `cleanup_and_vacuum` pass so the two paths can
  never disagree).

The other caps run on their own triggers:

- `server_messages` older than 365 days (checked every 500 inserts in `log_server_message`);
- `ambient_log` beyond 400 rows (on every insert in `log_ambient`).
