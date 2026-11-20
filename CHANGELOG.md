# Changelog

## 1.0.5 — 2026-11-20

Recovery and security-hardening pass against an independent 35-finding audit, plus everything
found while fixing it. Every claim below is backed by a test in `tests/`.

### Boot and deployment

- `--checkpoint-db` no longer fails on a fresh install: a missing database is a "nothing to
  checkpoint" success, while `--verify-db` still fails. systemd, Docker and the Windows launcher
  can boot an empty host again.
- The systemd unit sets `ANGEL_DB_PATH`, bounds restarts (`StartLimitBurst`), stops on failure and
  waits 60 s for a clean shutdown. Backup and persona timers now ship in `deploy/`.
- Docker: Deno 2.9.8 with published hashes, `sqlite3` for the backup script, read-only root
  filesystem with `tmpfs`, `pids_limit` and a healthcheck; `.env.*` is excluded from the build.
- The Windows launcher reconciles dependencies on every run, refreshes `.venv` after a partial
  failure and switches the console to UTF-8. CLI output no longer crashes on a legacy code page.
- `tzdata` is pinned. A non-UTC `ANGEL_TIMEZONE` without it now fails loudly instead of silently
  running on UTC.

### Security and authorization

- Every registered command declares a policy in the authorization inventory (scope, `guild_only`,
  permission, intent); a test fails when the tree and the inventory disagree.
- Natural-language actions share the slash-command guards: channel summaries require
  `Read Message History`, storage cleanup is owner-only, and nickname changes respect the role
  hierarchy.
- The confirmation gate is bound to the originating channel, reports the real execution result,
  covers every state-changing action, and no longer treats `نفذ`/`لا` as triggers.
- `/announce` needs `mention_everyone` to ping everyone; administrative commands are guild-only.
- `AllowedMentions` and the output filter neutralise `<@id>` mentions from model output, media
  titles and archive quotes.
- AI quota gaps closed: `/translate`, `/rules`, `/summarize_channel` and the NL summary all
  consume the user and guild quotas; image generation skips cooling/dead models.

### Privacy and data

- `/data delete` erases every per-member table, including ambient lines, AFK state, harem
  membership, XP and the derived persona culture; the count it reports matches the deletion set,
  and a schema-driven test fails when a new member table is added without a policy.
- Opt-out is enforced inside SQL, so a reply in flight cannot re-create a deleted member. DMs are
  covered too.
- The summariser filters opted-out members before the prompt and wraps the transcript in an
  untrusted block. The persona-refresh tool resolves the configured database, filters opt-out,
  sends the key in a header and validates the payload.
- `forget_user_keyword` treats `%` and `_` literally. `initialize()` no longer rewrites user data
  on every boot: legacy clean-up runs once behind `PRAGMA user_version`.

### Reliability

- The daily budget breaker fails closed when its database handle is missing, clamps
  `STOP_RATIO` to `(0, 1]`, and reserves estimated cost under a lock so concurrent calls cannot
  pass the same check.
- Cancelled extractions kill and reap yt-dlp and FFmpeg; DNS validation runs off the event loop.
- Media jobs share one download semaphore and a 50 MB per-job byte budget.
- The anti-spam guard runs on message edits; a failed delete no longer cancels the timeout or the
  modlog entry; the ghost-ping detector no longer republishes deleted text.
- The voice engine refuses to move out of another channel, leaves an empty channel, and still
  refuses to announce playback it cannot encrypt.
- The archive search requires an explicit channel allow-list and folds Arabic diacritics; the rules
  index gains a delete trigger and an atomic replace.

### Tooling and documentation

- The Cloudflare token verifier no longer reports transport errors, 429 or 5xx as PASS.
- Gate checks fail closed: a `SyntaxError` propagates, any `shell` keyword and `sh -c` are
  detected, and the owner-id check reads the environment.
- The website headers file is valid Cloudflare syntax and the site reports four media platforms,
  not fourteen.
- New: `AGENTS.md`, `KNOWN_ISSUES.md`, `docs/DATA_MODEL.md`, `docs/LIVE_VERIFICATION.md` and the
  `docs/recovery/` ledger, state and decision record.

## 1.0.4 — 2026-11-19

Privacy and public-repository hygiene pass.

### Privacy

- Removed personal and operator-specific details from the public tree: display names, the
  location-specific default timezone, hosting provider and exact host specifications, internal
  project and DNS names, and legacy publish-repository references.
- Added `ANGEL_TIMEZONE` (IANA name, default `UTC`). Quiet hours, greetings and the daily budget
  follow it. `ANGEL_OWNER_ID` is the documented owner variable; legacy environment names are still
  read for compatibility so an existing host does not break on upgrade.
- The bot presence and the generated owner role use `Angel`; `LICENSE` names the project
  contributors. The dead publish-check script was removed.
- `CONTRIBUTING.md` now requires placeholders for personal IDs, hostnames, account/project IDs,
  DNS records, exact host specifications and locations.

### Operations

- The static host's path filter was corrected so every push to `master` deploys; the next push
  was used to verify the automatic build. Account, project and DNS settings stay in private
  operator notes.
- `website/` package name is now `angel-website`.

## 1.0.3 — 2026-11-19

Full hardening pass from an independent 45-finding audit, verified against this tree.

### Security and authorization

- Custom HTTP sessions must use `SafeAsyncResolver`; TikWM media and cached stream URLs are
  revalidated through the bounded redirect path.
- Owner `toggle_role` is behind `SOVEREIGN_TOOLS_ENABLED` with role/permission checks. Ticket
  ownership uses an exact ID match plus a per-user lock; image-studio rerolls are author-only.
- Context menus, music skip/playlist, moderation hierarchy, snipe, AFK and stickies now enforce
  their scope. AFK is per guild, and sticky deletion requires the matching guild.
- Prompt context is sanitised as untrusted data; image fallbacks verify raster magic bytes;
  response bodies and Pollinations prompts are bounded.

### Reliability

- Per-event-loop semaphores, per-guild DAVE state, FFmpeg cleanup on failed play, and a locked
  music `start()`.
- Autonomy flags load from SQLite before the gateway; BoundedDict/cache types survive refreshes;
  giveaway failures no longer retry forever; shutdown cancels background tasks.
- `safe_reply` retries only a deleted-reference (50035) and rewinds files; zero-width characters
  no longer bypass the Arabic scam filter; `split_message` never emits an empty chunk.
- SendQueue caps `retry_after`, records dropped jobs, and rejects sends after close.

### Data and AI

- A zero daily AI limit is honoured; LIKE wildcards are escaped; maintenance no longer VACUUMs
  under the shared DB lock.
- Key rotation is locked, the RPM tick is released per request, and a per-day 429 cools until
  midnight Pacific instead of retrying hourly.
- Summaries, profile facts and ambient prompts validate types and cap response size; unclosed
  control tags are stripped; questions are not stored as profile facts.
- The model chain remains free-tier only: `gemini-3-flash-preview`, `gemini-3.1-flash-lite`,
  `gemini-3.5-flash-lite`, `gemini-4-hydrogen` (Google AI Studio pricing, 2026-11-19).

### Website and docs

- TypeScript is pinned to `~6.0.3` because Astro 7 requires `<7`; Dependabot ignores TS majors
  until Astro supports TypeScript 7.

## 1.0.2 — 2026-11-19

Latency and model-quality pass driven by measured behaviour on this deployment.

### Engine

- `gemini-3-flash-preview` leads the chain: on this account it answers a real prompt in
  ~1–3 s with full-flash Arabic quality, while `gemini-3.5-flash-lite` answers in 14–20 s
  and `gemini-4-hydrogen` mostly returns 503. Thinking is disabled for it, as for 3.1/4.x,
  because the model otherwise spends the whole token budget before writing.
- `gemini-3.1-flash-lite` is the first fallback, then `3.5-flash-lite`; retired and
  unavailable models (`gemini-2.5-*`, `gemini-flash-latest`) are out of the chain.
- One quick retry on `503` before falling back, because a spike on the fast model clears
  in about a second while the lite fallbacks cost 14–20 s.
- A `429` that names a per-day free-tier limit cools the model for an hour instead of two
  minutes, so an exhausted daily quota is not retried on every message.
- The whole fallback chain is bounded at 28 s and each request at 18 s; a reply can no
  longer sit through five slow models. Chat output is capped at 450 tokens, enough for the
  1–3 sentence persona.
- `ai-reply` log lines now carry `in=`/`out=` token counts alongside latency and cost.

### Prompt size

- Archive recall now injects 4 lines instead of 6, and each culture note field is capped at
  160 characters. On a free-tier key the measured cost of an oversized prompt is seconds:
  1.4 k input tokens ≈ 2.5 s, 3.4 k ≈ 5–10 s.

## 1.0.1 — 2026-11-19

Correctness and hardening fixes after the first independent audit of v1.0.0.

### Security

- Gemini responses can no longer fall back to hidden `thought` parts, and a rejected key
  rotates to the backup key on `401`/`403`.
- Display names are sanitised before they enter the system prompt; `[SYSTEM]`/`[INST]`
  and angle brackets are stripped from untrusted context.
- Typo injection skips URLs, code spans, mentions and control tags.

### Fixes

- The outgoing reply sanitiser no longer raises `bad escape \\u` on every reply: the
  `@everyone`/`@here` neutraliser builds a real zero-width space instead of passing a raw
  escape to `re.sub`, which had made the bot answer every message with the generic error
  notice. Regression tests cover the plain reply, both mentions and the length cap.
- `BoundedTTLCache.values()` no longer mis-unpacks entries; `None` values, TTL-aware
  `pop`, and control characters in untrusted lines are handled correctly.
- `/catchup` survives a forbidden history read, and refunds the guild quota when the
  summary call fails.
- Permanent Discord `4xx` send errors go to dead letters instead of retrying forever;
  long messages are capped at 2000 characters and missing channels are fetched.
- The voice engine captures the event loop before the audio callback can need it.
- `resolve_and_validate_host` lowercases the hostname before its blocklist checks.
- Image generation honours the daily budget, key rotation and URL-safe prompt encoding.

### Operations

- Docker stops via `exec` so `SIGTERM` reaches Python; the Deno archive is SHA-256 checked.
- The Windows launcher verifies Python 3.12 and every install/checkpoint exit code.
- The backup script validates retention and handles paths without URI/quote pitfalls.
- CI quotes changed filenames for ruff and no longer hides pip-audit failures.
- The failing TypeScript 7 dependency PR was closed.

### Website

- The website is rebuilt from the repository and shows v1.0.1 with the corrected
  changelog.

## 1.0.0 — 2026-11-19

First open-source release after the security and stability hardening pass.

### Security

- All outbound HTTP now goes through one shared network layer: strict URL syntax (no
  userinfo, control characters or non-canonical IPv4), every resolved address must be
  public, the async resolver re-checks at connect time, redirects are followed manually
  with each hop validated, and auth/cookie headers are dropped on cross-origin hops.
- `yt-dlp` is invoked with `--ignore-config`, `--use-extractors default,-generic` and
  `--` before the target; operator cookies are sent only on plain YouTube media pages.
- Extracted stream URLs are DNS-validated before FFmpeg, which now runs with
  `-protocol_whitelist https,http,tcp,tls,crypto`.
- `sudo` removed from the bot process; the systemd unit sets `NoNewPrivileges=true` and
  only the bot's data directory is writable.
- Output filter redacts GitHub/Bearer/env-style secrets and neutralises role mentions.

### Privacy

- Opt-out is fail-closed everywhere: message logging, snipe/edit-snipe, modlog,
  ambient context, autonomy targets and `/data delete` caches.
- `/data delete` also clears the member from in-memory buffers and per-user locks.
- `/catchup` drops opted-out authors before spending the guild quota and frames chat text
  as untrusted data.

### Stability

- Per-channel send queue: a 429 in one channel no longer blocks the others; idle workers
  exit; dead letters are bounded.
- Bounded LRU/TTL caches replace the long-lived unbounded dictionaries.
- Guild daily AI quota is atomic; `/setup` stores dialect, guard level and social-fixer
  state per guild.
- Voice reconnect is serialised per guild, DAVE timeouts trigger one clean reconnect, and
  the queue/byte counters are bounded.

### Operations

- CI runs compileall, pytest, the deploy gate, the security probe and the recall probe as
  blocking checks; ruff is advisory on changed files; pip-audit runs weekly.
- `scripts/backup_db.sh` creates a verified SQLite backup with 14-day retention.
- Hardened Dockerfile/docker-compose (non-root, read-only code, persisted `/app/data`) and
  a Windows launcher.
- MIT license and bilingual documentation for installation, backup/restore and contribution.

### Website

- Cloudflare Pages now builds the site from this repository on every push to `master`
  (`bash website/scripts/build.sh`), replacing the manual GitHub Pages copy.
- HSTS, CSP with `frame-ancestors 'none'`, `X-Frame-Options: DENY`, COOP and
  Permissions-Policy are live response headers.
- The command catalogue, media counts, version, license and changelog are generated from
  the repository at build time; a stale file fails the build.

