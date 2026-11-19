# Discord policy review — data handling

Independent review requested before Angel is promoted or invited to more servers. Scope: the
behaviour the public site describes (archive, member notes, DM logging), checked against the live
implementation, not the wording alone.

Measured 2026-11-15. Source of the rules: **Discord Developer Policy**, page `updated_at`
**2026-11-15T05:06:54Z**, <https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy>.

> **§15** — “Do not use API Data for any purpose outside of what is necessary to provide your stated functionality.”

> **§16** — “Do not use API Data to: profile Discord users, their identities, or their relationships with other users; to discriminate against anyone based on protected characteristics […] or, for eligibility considerations for benefits […]”

API Data here includes message content, member ids, names and metadata the bot receives over the
gateway, and the Terms define it as “any data, information, or other content you obtain through the
APIs (including personal data)”, with policy rule 7 extending it to data “inferred through the use of
your Application”. A profile assembled from a member's messages is API Data used to describe that person.

## What the code did

Production checkout `<deploy-dir>` at `2bfddfa`; its key files hash identically to the
audited tree (`angel/client.py`, `angel/database.py`, `angel/member_files.py`, `cogs/owner.py`,
`tools/build_member_files.py`), so this review describes what was running.

> **Historical record.** The member-file builder and the `angel/member_files.py` render path were
> removed on 2026-11-15 (`angelbot@a840c9d`), together with their systemd units. This document is
> kept unchanged as the evidence of what the review found and why the removal was required; it does
> not describe the current code.

| # | Behaviour | Where | Live volume |
|---|---|---|---|
| F1 | Monthly LLM-built **member dossier**: summary, style, topics, up to 4 “facts” each with a quote | `tools/build_member_files.py`, table `user_dossier`, injected at `angel/client.py:436` | 54 dossiers, 189–240 messages each, last built 2026-11-13 |
| F2 | **Automatic fact extraction** from every exchange, plus a nightly miner over 60 messages per member | `angel/memory.py:learn_from_exchange`, `tools/learn_from_log.py`, table `user_profile` | 54 facts, sources `chat` (28) and `nightly` (26), 18 members |
| F3 | Archive of every readable message | `server_messages` + FTS5 | 172,490 rows, 413 distinct users; main guild 172,304 |
| F4 | DM logging and forwarding to the owner | `angel/client.py:forward_dm_to_mistress`, `dm_logs` | 145 rows, 6 senders, 10 with attachments |
| F5 | No self-service access or erasure beyond `/memory forget` | `cogs/memory_rules.py` | — |

F1 and F2 are the conflict. They use message content to build a description of a person
(“style”, “topics”, “facts”) that is served back in later prompts. §16 names that use directly, and
§15 rules out “it is useful for the product” as a justification. A privacy notice does not cure it:
the notice described the behaviour accurately, which is why the wording was never the problem.

## What changed

| Change | File |
|---|---|
| Automatic fact extraction returns without doing anything; only `/memory pin` writes memory | `angel/memory.py` |
| Dossier render path returns `None`; the prompt no longer receives a profile | `angel/member_files.py`, `angel/client.py` |
| Dossier builder, legacy builder and nightly miner deleted | `tools/build_member_files.py`, `tools/build_member_files_legacy.py`, `tools/learn_from_log.py` |
| Monthly member-file timer and service deleted | `deploy/angel-member-files.*` |
| Member-facing `/data` command: `view` counts what is stored, `delete confirm:true` erases it and sets `opt_out` | `cogs/memory_rules.py`, `angel/database.py:delete_all_user_data` |
| DM log retention changed from “last 150 rows” to **30 days** | `angel/database.py` |
| Privacy page rewritten: no profile claim, retention stated for archive, DMs and backups, `/data` documented | `website/src/i18n/content.ts` |
| README (AR + EN), commands table, threat model updated to the new memory model | `README*.md`, `docs/COMMANDS.md`, `docs/SECURITY_THREAT_MODEL.md` |
| Existing dossiers and inferred facts deleted from the live database after a backup | operations step, see **Deployment record** below |

No behaviour was removed for the owner: `/memory pin`, `/memory forget`, `/clear_history`,
`/dm_logs` and `/dm_send` are unchanged.

## Privileged intents and size

Live application `Angel` (`1559932443102941284`) reports flags `11051008`: `GATEWAY_MESSAGE_CONTENT_LIMITED`,
`GATEWAY_GUILD_MEMBERS_LIMITED`, `GATEWAY_PRESENCE_LIMITED`. The `_LIMITED` bit means the intents
are **enabled but not approved**. Since 2026-06-10 the review threshold is **10,000 users**, not
100 servers: “If your app is accessible to fewer than 10,000 users, these changes do not impact your
app” (`Changes to Privileged Intent Access for Discord Apps`, updated 2026-11-14). The bot is in 4
servers, far below that line, so the self-serve toggle is legitimate today. At 10,000 users the app
must apply for Privileged Intent review and reapply annually.

The bot does not require the presence intent for any feature; keeping it enabled widens the data it
could collect for no stated purpose, and §15 is about purpose. Disabling it is the safer default
and is tracked as a follow-up, not done in this change because it needs a restart window.

## Privacy statements vs deployed behaviour

| Statement (privacy page) | Verified |
|---|---|
| Archive holds readable messages with metadata, searchable, server-scoped | yes, `server_messages` + FTS5 |
| Archive kept one year | yes, prune at 365 days on write |
| Messages truncated at 1500 characters | yes, `text[:1500]` |
| No member profiles, only `/memory pin` | yes, after this change |
| DMs logged for the owner, kept 30 days | yes, `dm_logs` prune |
| Backups nightly, mode `600`, 14 days, host-local | yes, nightly snapshots with a 14-day prune |
| Site has no analytics, cookies or third-party requests; theme in `localStorage` | yes, no `document.cookie`, no analytics code, no external hosts in `src/` |

Not claimed anywhere and still true: the bot's `user_summaries` and 60-message chat window are stored
per member; that is conversation context, not a profile, and `/data delete` removes both.

## Residual risks — not fixed here

1. **Direct-message forwarding.** A DM to the bot is copied to the owner. It is disclosed and now
   capped at 30 days, but it is still API Data leaving the member's conversation. If the owner does
   not need the text, switch the notification to a ping without content.
2. **Archive breadth.** 172k messages retained for a year is the stated recall feature. It needs
   server-side disclosure (a rule or pinned message), not just a page on the website.
3. **Backups.** A deleted row can survive up to 14 days in a nightly snapshot.
4. **Intent approval.** The message-content intent is unapproved; at 10,000 users it needs Privileged Intent review and an annual reapplication, and content stops arriving until approval.
5. **Presence intent** is enabled without a feature that needs it.

## Compliance statement

This document does **not** certify compliance. It records that the one behaviour Discord names
explicitly — profiling users from API data — was found in the code and removed, and that each
remaining data flow now has a stated purpose, a disclosed retention period and a member-facing
deletion path. Anything beyond that needs Discord's own review, and the intent application is the
point where Discord performs it.

## Deployment record

- 2026-11-15 05:40Z — database snapshot before any deletion:
  a database snapshot taken before the change (mode `600`).
- 05:41Z — production checkout moved from `2bfddfa` to `9d65116`; `tools/selftest.py` reported
  **50/50** before the restart.
- 05:41Z — `DELETE FROM user_dossier` and `DELETE FROM user_profile WHERE source IN ('chat','nightly')`:
  **54 → 0** dossiers, **54 → 0** inferred facts. `user_summaries` and the 60-message windows stay;
  they are conversation context and `/data delete` removes them per member.
- 05:41Z — `systemctl restart angelbot`; service `active`, “Commands synced cleanly”, 69 global
  commands with `data` present, intents `members=True message_content=True presences=False`.
- Rollback: `git reset --hard rollback-pre-policy` on the host and restart; the database snapshot
  above restores the pre-change rows.

`angel.aetherisnode.cloud` is served by Cloudflare Pages project `angel-site`, built directly
from `Certainty7/angelbot` on every push to `master`; the apex and `www` are served by the
`aetheris-node` Worker. The old `angel-web` publish repository and its GitHub Pages origin were
removed on 2026-11-19.
