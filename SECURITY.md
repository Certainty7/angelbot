# Security policy

## Reporting a vulnerability

Do not open a public issue. Use GitHub's private vulnerability reporting on this repository
(**Security** tab, then **Report a vulnerability**). If the button is not available, open an issue
that says only that you have a security report, with no details, and the maintainer will open a
private channel.

Please include the affected command or code path, a reproduction if you have one, and the version
or commit you tested.

## In scope

- Bypassing the owner or permission checks, including through the natural-language router or a
  model-emitted control tag.
- Reading data outside the channels a member can see, or reading a direct message through the
  archive.
- Leaking a token, key or database file through the repository, logs or a reply.
- Command injection or a path escape in media download, cleanup or the subprocess runner.

## Authorization model

Every registered command declares a policy in `angel/authz.py` (scope, `guild_only`, required
Discord permission and intent). `tests/test_command_policy.py` fails when the live command tree and
that inventory disagree, so a new command cannot ship with an implicit "everyone" policy.

Three independent layers protect a destructive action:

1. **Discord permission** (`default_permissions` + `has_perm_or_mistress`).
2. **Hierarchy** (`can_moderate_member`, `can_assign_role`): Discord only enforces the *bot's*
   role position, so the application must refuse a target whose role is at or above the caller's.
3. **Confirmation** for model-proposed actions: the pending entry is bound to the guild, the
   author *and* the channel, expires after 60 seconds, and re-checks permissions when executed.

Natural language shares these primitives. The router is a second front end, not a second
permission model: a request that needs `Read Message History` to be answered by slash command
needs it through the router too.

## Data flow and privacy

| Path | Collected | Stored | Sent to a provider | Opt-out honoured | Deleted by `/data delete` |
|---|---|---|---|---|---|
| Guild chat | author id, display name, text | `server_messages`, `messages`, `user_summaries` | only the snippet in the current prompt | yes (SQL predicate) | yes |
| DM chat | author id, text | `dm_logs` (30 days) | only if the owner forwards it (`ENABLE_SOVEREIGN_TOOLS=1`) | yes | yes |
| Channel summary | up to 500 messages | nothing | transcript wrapped in `<untrusted_transcript>` | yes, filtered before the prompt | n/a |
| Memory facts | only what a member pins | `user_profile` | facts relevant to the current question | yes | yes |
| Member index | id, display name, counts | `user_index` | no | yes | yes |
| Ambient lines | the bot's own text | `ambient_log` | no | yes | yes |
| Moderation | warnings + moderator id | `warnings` | no | no (guild evidence) | no, and the reply says so |
| Cost | per-day tokens and USD | `llm_usage` | no identifying data | n/a | n/a |
| Logs | module, ids, timings | host journal | no message text | n/a | n/a |
| Backups | the whole database | `ANGEL_BACKUP_DIR` | no | follows the database | only when the backup expires (14 days) |

External providers receive message text only when a model call is actually made. Keys travel in
the `x-goog-api-key` header, never in a URL. Logs record ids, outcomes and timings, never message
bodies.

`/data delete` sets `opt_out = 1`; from then on the write paths refuse to store that member again
(the predicate is inside the SQL, so a concurrent reply cannot resurrect them).

## Owner-only commands

A small set of commands is gated by a private owner id configured outside the repository, not by
a Discord permission: `/sovereign`, `/dm_logs`, `/dm_send`, `/whisper`, `/harem`, `/autonomy`,
`/silence`, `/mood`, `/sync`, `/diagnostics`, `/budget` and `/cleanup`. They are listed with their
parameters in `docs/COMMANDS.md`. The bot also forwards a DM sent to it to the owner and keeps those
DMs for 30 days, as stated in `docs/MEMORY.md` and on the site's privacy page. None of this surface
is reachable by a guild member, and nothing about it is hidden from the owner or the host. The risky
subset (self role escalation, stealth moderation, bot-voiced messages and DM forwarding) is disabled
unless `ENABLE_SOVEREIGN_TOOLS=1` is set in the host environment.

## Media and network

Outbound fetches go through `angel/net.py`: a validating resolver rejects loopback, RFC1918,
link-local, CGNAT, metadata, IPv4-mapped, 6to4, Teredo and NAT64 addresses; redirects are followed
one hop at a time and re-validated; `Cookie` and `Authorization` are stripped across origins;
response bodies are read with a byte cap. `yt-dlp` and FFmpeg run as argv arrays, never through a
shell, and are killed and reaped on timeout or cancellation.

## Known residual exposure

- **Git history.** Commit `51090aa` removed operator details (hosting provider, project name, the
  owner's timezone) from the tree, but earlier commits (`v1.0.3` and before) still contain them.
  No token, API key, private key or webhook was ever committed; a full-history scan is recorded in
  `docs/recovery/SECRET_SCAN.md`. Removing the information completely requires either making the
  repository private or rewriting published history, which would break every clone and tag. That is
  an owner decision, deliberately not taken unilaterally.
- **Denial of service.** The bot is a single process on a small host; a determined member can
  consume the daily AI quota. Per-user and per-guild caps bound the cost, not the availability.
- **Model output.** Output is filtered for mentions, secrets and control tags, and a false
  moderation claim is rewritten. A model can still be wrong; it cannot act.

## Out of scope

- Spam or abuse from a bot token or account that is already compromised.
- Rate limits, model output quality and moderation decisions made by a server's own staff.
- Denial of service from a self-hosted deployment the maintainer does not control.

## Supported versions

The `master` branch is the supported version. There are no maintained release branches.

## Response

This is a single-maintainer project. Reports are acknowledged when they are read, and a fix lands
on `master` when it is ready. Please give the maintainer time to ship a fix before writing about
the issue publicly.
