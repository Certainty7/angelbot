# Architecture — Angel bot, website, and hosting

Status: current as of 2026-11-19. The website is hosted on a managed static host; the bot and
data hosting are unchanged.

## 1. Components

| Component | Where it runs | What it is |
|---|---|---|
| Discord bot `Angel` | the deployment host, `angelbot.service` | Python 3 process (`bot.py` + `angel/` + `cogs/`), discord.py, SQLite |
| Bot database | same host, `chat_history.db` | one SQLite file: archive, FTS5 index, memory, DM logs, summaries |
| Scheduled jobs | same host, systemd timers | maintenance, learning, backup and metrics timers |
| Angel website | managed static host | static build of `angelbot/website` (Astro), public domain |
| Operator site | operator-managed edge site | separate static/edge site for the apex and `www` |
| DNS / TLS | host-managed | operator-configured records and certificates |
| CI | GitHub Actions | `checks` (bot + probes) and `website` (build + type-check + e2e) |

There is no application server behind the Angel site, no database exposed to the internet, and no
traffic from the website to the bot host.

## 2. Request path

```
visitor → DNS → static-host edge
        → production deployment (static files from website/dist)
```

```
Discord gateway ⇄ angelbot.service (deployment host) → chat_history.db
                                     └→ model provider over HTTPS (outbound only)
```

The deployment host serves no web traffic.

## 3. Source of truth

| Artefact | Canonical location | Published copy |
|---|---|---|
| Bot code | `Certainty7/angelbot` `master` | `<deploy-dir>` on the deployment host, same commit |
| Website source | `angelbot` `website/` (Astro + `src/i18n/content.ts`) | production build from `bash website/scripts/build.sh` |
| Generated facts | `tools/website-data-generator/generate.py` | `website/src/data/{commands,invite,changelog,site}.json` |
| Deployment contract | `website/scripts/build.sh` | run by the static host and by CI |
| Drift gate | `generate.py --check` + `tests/website/` | fails the build on stale data |

The site has no separate publish copy to drift from.

## 4. Data model (bot)

| Table | Purpose | Retention |
|---|---|---|
| `server_messages` + `server_messages_fts` | messages the bot can see, searchable | 365 days, deleted by job |
| `messages` | last 60 turns per member in the bot DM | rolling, erased by `/memory clear` or `/data` |
| `dm_logs` | DMs sent to the bot, forwarded to the owner | 30 days |
| `user_preferences` (pinned facts) | explicit `/memory pin` only | until `/memory forget` or `/data` |
| `user_summaries` | short conversation summaries | erased by `/data` |
| `user_profile`, `user_dossier` | legacy profiling tables | schema retained, **no writer and no reader** since 2026-11-15; both empty |

Encryption at rest: **none**. The database is a plain SQLite file, mode `600`, on a single host.
This is a documented limitation, not a control.

## 5. Trust boundaries

1. Discord → bot: untrusted user content, including prompt-injection attempts; mitigated by
   `angel/guard.py` and `sanitize_untrusted_context`.
2. Bot → model provider: message content leaves the host over TLS; the provider is a data
   processor outside the owner's control.
3. CI → production pages: only static output; no deploy token is stored in the workflows.
4. Deployment automation → GitHub: a scoped token held outside the repository.
5. Operator access: restricted to the deployment owner.

## 6. Known limitations

- HTML is revalidated; `_astro/*` is immutable. A Pages deployment is usually visible within a
  minute, but edge caches may serve the previous HTML until it revalidates.
- Publishing is automatic on `master`; if the static host leaves a build queued, trigger the
  production deployment from its dashboard.
- The bot keeps the privileged `members` intent for autorole, member-name matching and voice
  channel matching; that caps the application at 100 guilds without Discord verification.
