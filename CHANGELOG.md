# Changelog

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

