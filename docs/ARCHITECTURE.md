# Architecture — Angel bot, website, and hosting

Status: final for the closeout. Every value below was measured on 2026-11-15, not copied from an
earlier report. Commit identifiers are the ones that were serving at the time of writing.

## 1. Components

| Component | Where it runs | What it is |
|---|---|---|
| Discord bot `Angel` | the bot host, `angelbot.service` | Python 3 process (`bot.py` + `angel/` + `cogs/`), discord.py, SQLite |
| Bot database | same host, `chat_history.db` | one SQLite file: archive, FTS5 index, memory, DM logs, summaries |
| Scheduled jobs | same host, systemd timers | maintenance, learning, backup and metrics timers |
| Angel website | GitHub Pages, repo `Certainty7/angel-web` | static build of `angelbot/website` (Astro), custom domain `angel.aetherisnode.cloud` |
| Aetheris portal | GitHub Pages, repo `Certainty7/aetherisnode-home` | static site, custom domain `aetherisnode.cloud` |
| DNS | the domain's authoritative nameservers | apex `A` → four GitHub Pages addresses; `www`/`angel` `CNAME` → `certainty7.github.io` |
| TLS | GitHub Pages managed certificates | Let's Encrypt, valid to 2027-02-13 |
| CI | GitHub Actions | `checks` (selftest + website), `build` (portal), Cloudflare Pages check |

There is no application server behind either website, no database exposed to the internet, and no
traffic from the websites to the bot host.

## 2. Request path

```
visitor → authoritative DNS → GitHub Pages edge (Fastly)
        → angel-web/main (static files, CNAME, .nojekyll, CSP <meta>)
```

```
Discord gateway ⇄ angelbot.service (bot host) → chat_history.db
                                     └→ model provider over HTTPS (outbound only)
```

The bot host serves no web traffic.

## 3. Source of truth

| Artefact | Canonical location | Published copy |
|---|---|---|
| Bot code | `Certainty7/angelbot` `master` | `<deploy-dir>` on the bot host, same commit |
| Website source | `angelbot` `website/` (Astro + `src/i18n/content.ts`) | `Certainty7/angel-web` `main`, byte-identical to `website/dist` |
| Portal source | `Certainty7/aetherisnode-home` `main` | `gh-pages` branch of the same repository |
| Deployment contract | `website/scripts/build.sh` | run by CI and by manual publish |
| Drift gate | `website/scripts/check-published.sh` | compares a fresh build to `angel-web` |

`angel-web` is a **publish artefact repository**, not a second source tree. The drift gate exists
because publishing is a manual copy today; it fails on any byte difference.

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
4. Agent host → GitHub: a personal access token with repository write scope (see the security
   audit for the open rotation item).
5. Operator → bot host: key-based access only.

## 6. Known limitations

- GitHub Pages ignores `_headers`: no HSTS, no `X-Frame-Options`, no CSP response header. Angel
  pages carry a CSP `<meta>` (which cannot express `frame-ancestors`); the portal carries a
  stricter `default-src 'none'` meta policy.
- `cache-control: max-age=600` on HTML and assets; a publish can take up to ten minutes to be
  visible everywhere.
- Publishing is manual: a build followed by a forward-only commit to `angel-web`.
- The bot keeps the privileged `members` intent for autorole, member-name matching and voice
  channel matching; that caps the application at 100 guilds without Discord verification.
