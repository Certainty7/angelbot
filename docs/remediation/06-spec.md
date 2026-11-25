# Finding 06 — scope rolling memory by conversation

Status: spec approved for implementation. Audit issue: `Certainty7/angelbot-audit` 06 (must-fix).

## Problem

`messages` and `user_summaries` are keyed by `user_id` alone, so one member's rolling
memory mixes every room they speak in. A DM sentinel showed up in the next guild prompt,
and guild-A text appeared in a guild-B provider payload. Private DM content can therefore
be repeated in a public channel.

## Decision

Key rolling memory by `(channel_id, user_id)`. Discord channel snowflakes already
distinguish guild channels from DM channels, so no extra type column is needed. Pinned
facts (`user_preferences.pinned_facts`) stay per user: they are the documented
cross-guild store and the `/memory pin` contract says so.

Rejected alternatives:

- *Key by guild only* — DM channels would collapse into one bucket and two DMs from
  different bots/users would mix.
- *Encrypt per channel* — hides the leak but keeps the wrong scope, and no key rotation
  story exists.

## Schema (migration v4)

```sql
ALTER TABLE messages ADD COLUMN channel_id INTEGER NOT NULL DEFAULT 0;
ALTER TABLE user_summaries ADD COLUMN channel_id INTEGER NOT NULL DEFAULT 0;
-- legacy rows are mixed by construction: discard them rather than guess a channel
DELETE FROM messages;
DELETE FROM user_summaries;
CREATE INDEX idx_channel_user_messages ON messages (channel_id, user_id, id ASC);
DROP INDEX IF EXISTS idx_user_messages;
PRAGMA user_version = 4;
```

`user_summaries` gets a composite primary key, so the table is rebuilt:
`CREATE TABLE user_summaries_v4 (channel_id, user_id, summary, updated_at, PRIMARY KEY (channel_id, user_id))`,
copy nothing, drop old, rename. `DELETE FROM messages` is required by the audit: legacy
rows cannot be attributed, and keeping them would preserve the leak.

## API threading

| Method | Change |
| --- | --- |
| `add_exchange(channel_id, user_id, user_msg, model_reply)` | insert both rows with the channel |
| `get_context_data(channel_id, user_id)` | read window + summary for that channel |
| `save_summary(channel_id, user_id, summary)` | upsert on the composite key |
| `clear_user_memory(channel_id, user_id)` | clear this conversation only |
| `forget_user_keyword(user_id, keyword)` | stays user-wide: forgetting is a privacy action |
| `delete_all_user_data(user_id)` | unchanged, deletes every channel |
| `_apply_retention` | keep N most recent rows **per (channel, user)** |
| `count_user_data`, `export_user_data` | unchanged totals, now channel-aware rows |

Call sites: `angel/client.py:489,594`, `angel/ui.py:242`, `cogs/memory_rules.py:60,116,122`,
`angel/nl_router.py:755,778`. Each has the interaction/message in scope, so
`channel_id` comes from `message.channel.id` / `interaction.channel_id`.

## Documented `/memory` behaviour

- `view` — the current conversation only; the footer states that pinned facts are cross-room.
- `clear` — the current conversation only, with the channel named in the receipt.
- `forget <word>` — every conversation, because it is a privacy erase, and the receipt says so.

## Tests (red first)

1. `test_dm_and_guild_memory_do_not_mix` — write in DM and in guild A, assert guild B's
   context is empty and each context returns only its own sentinel.
2. `test_summary_is_per_conversation` — two summaries for one user in two channels.
3. `test_clear_only_affects_the_current_channel`.
4. `test_forget_erases_every_channel`.
5. `test_migration_v4_discards_legacy_mixed_rows` — seed v3 rows, run initialize, assert
   empty and `user_version = 4`.
6. `test_retention_keeps_the_cap_per_conversation`.
7. `/memory view` and `/memory clear` receipts name the current channel.

## Rollout

One PR. The migration runs on boot and is irreversible, so the PR description states that
rolling back requires restoring a backup. `tools/selftest.py` gains a check that no query
touches `messages` or `user_summaries` without a `channel_id` predicate.
