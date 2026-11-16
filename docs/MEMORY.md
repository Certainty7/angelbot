# Memory and data handling

What Angel stores, what it refuses to infer, and how a member reads or erases it.

## What is stored

| Store | Table | Contents | Retention |
|---|---|---|---|
| Server archive | `server_messages` + FTS5 | Messages the bot can read, truncated at 1500 characters, with author id, channel, timestamp | 365 days, pruned as new rows arrive |
| Chat window | `messages` | The last 60 exchanges per member with the bot | Rolling, 60 per member |
| Conversation summary | `user_summaries` | A short summary of that chat window | Replaced as the window turns over |
| Pinned memory | `user_preferences.pinned_facts` | Only what a member typed into `/memory pin` | Until the member removes it |
| Direct messages | `dm_logs` | DMs sent to the bot, its reply, attachment URLs | 30 days |
| Backups | host-local snapshots | Nightly, not encrypted | 14 days |

Warnings, XP and guild settings are server records, not member chat history, and survive a
`/data delete`.

## What is not stored

Angel does not build a profile of anyone. There is no member dossier, no nightly fact miner and no
per-user trait or style summary. Automatic extraction from messages was removed: the only durable
personal memory is what a member writes themselves.

## Why

Discord's Developer Policy, updated 2026-11-15, says in §15:

> Do not use API Data for any purpose outside of what is necessary to provide your stated functionality.

and in §16:

> Do not use API Data to: profile Discord users, their identities, or their relationships with other users

Source: <https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy>

A profile assembled from someone's messages is API Data used to describe that person, which §16
prohibits regardless of what a privacy page says. The archive is different: recall is the bot's
stated feature, it is disclosed, it is scoped to readable channels, and `/data` erases a member's
rows.

## Member controls

| Command | Effect |
|---|---|
| `/memory view` | Shows pinned notes and the current conversation summary |
| `/memory pin <text>` | Stores a note the member wrote themselves |
| `/memory forget <text>` | Deletes matching notes and any stored fact that mentions the text |
| `/memory clear` | Clears the rolling chat window |
| `/data view` | Counts what is stored: archive rows, chat rows, notes, DM rows, auto-save state |
| `/data delete confirm:true` | Deletes all of the above for that member and sets `opt_out`, so nothing new is stored |

Deletion is immediate in the live database. Nightly backups rotate within 14 days, so a deleted
row can survive in a snapshot until that window closes; that is stated on the privacy page.

## Operator duties

- Run `/data delete` requests yourself if a member cannot use the command.
- Do not re-enable message-content extraction, member dossiers or per-user profiling without a
  written policy review: it is the one behaviour Discord names explicitly in §16.
- Keep `dm_logs` at 30 days; the privacy page promises it.
