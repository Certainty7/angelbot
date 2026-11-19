# Changelog

## 1.0.1 — 2026-11-19

Correctness and hardening fixes after the first independent audit of v1.0.0.

### Security

- Gemini responses can no longer fall back to hidden `thought` parts, and a rejected key
  rotates to the backup key on `401`/`403`.
- Display names are sanitised before they enter the system prompt; `[SYSTEM]`/`[INST]`
  and angle brackets are stripped from untrusted context.
- Typo injection skips URLs, code spans, mentions and control tags.

### Fixes

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

