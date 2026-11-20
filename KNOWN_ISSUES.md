# Known issues

Open items after the v1.0.5 stabilization pass. Everything resolved is listed in the second
section, with the test that now protects it. Severity follows: **Critical** = data loss or full
compromise; **High** = privilege bypass, silent failure, or unbootable install; **Medium** = wrong
behaviour with a workaround; **Low** = cosmetic or tooling.

## Open

### KI-001 — Live Discord voice and DAVE are not verified
- **Severity:** High (unverified, not known-broken)
- **Component:** `angel/voice_engine.py`, `cogs/music.py`
- **Status:** Blocked-external
- **Details:** The DAVE gate, the decoded-byte monitor and the channel-ownership checks are
  unit-tested with fakes. They have not run against a real encrypted voice channel from this
  environment.
- **Workaround:** none needed; the bot refuses to claim playback it cannot deliver.
- **Verification required:** `docs/LIVE_VERIFICATION.md` §1.
- **Related tests:** `tests/test_voice_and_guard.py`, `tests/test_audio_hardening.py`.

### KI-002 — YouTube extraction depends on the host
- **Severity:** Medium
- **Component:** `angel/audio_source.py`, `angel/downloader.py`, Dockerfile
- **Status:** Blocked-external
- **Details:** YouTube requires Deno 2.9+ and, for some videos, fresh cookies. The image ships
  Deno 2.9.8; a host install must provide it. SoundCloud remains the fallback source.
- **Workaround:** set `MUSIC_YOUTUBE=0` to use SoundCloud only, or supply `cookies.txt`.
- **Verification required:** `docs/LIVE_VERIFICATION.md` §2.

### KI-003 — Public git history retains pre-v1.0.4 operator details
- **Severity:** Medium
- **Component:** repository history
- **Status:** Deferred-with-reason
- **Details:** `51090aa` removed hosting/provider/personal details from the tree, but `v1.0.3` and
  earlier commits still contain them. No credential was ever committed.
- **Workaround:** make the repository private, or rewrite history and re-tag (breaks existing
  clones; an owner decision).
- **Verification required:** owner decision; see `SECURITY.md` → "Known residual exposure".

### KI-004 — Docker image not built in this environment
- **Severity:** Medium
- **Component:** `Dockerfile`, `docker-compose.yml`
- **Status:** Blocked-external
- **Details:** No Docker daemon was available. The Dockerfile is statically validated (Deno version
  and hashes, `.dockerignore`, hardening flags) and the compose file is linted by test, but no
  image was built or started.
- **Verification required:** `docs/LIVE_VERIFICATION.md` §4.

### KI-005 — systemd unit validated by parsing, not by systemd
- **Severity:** Low
- **Component:** `deploy/*.service`, `deploy/*.timer`
- **Status:** Blocked-external
- **Details:** `systemd-analyze verify` is not installed on this machine. The unit is asserted by
  `tests/test_ops_and_gates.py` (database path, restart bounds, writable path, timers present).
- **Verification required:** `docs/LIVE_VERIFICATION.md` §3.

### KI-006 — Cloudflare Pages headers not observed live
- **Severity:** Low
- **Component:** `website/public/_headers`
- **Status:** Blocked-external
- **Details:** The file is now syntactically valid (only `#` comments; a single explicit `/*` rule
  carrying the CSP). Whether Cloudflare serves it is only observable after a deploy.
- **Verification required:** `curl -I https://<site>/` and check the CSP header.

### KI-007 — Model output can still be wrong
- **Severity:** Low
- **Component:** `angel/brain.py`, `angel/output_filter.py`
- **Status:** Accepted
- **Details:** Output is filtered for mentions, secrets, control tags and false moderation claims.
  The filter is not a truth layer; the model cannot execute an action, so a wrong sentence cannot
  change state.
- **Related tests:** `tests/test_security_controls.py`.

### KI-008 — User quota is consumed before the guild cap may refuse
- **Severity:** Low
- **Component:** `angel/quota.py`, summary paths in `angel/nl_router.py`, `cogs/ai_chat.py`
- **Status:** Deferred-with-reason (CodeRabbit re-review note on the PR #9 remediation)
- **Details:** Every gated command (`/translate`, `/chat`, `/imagine`, `/rules`, summaries)
  admits the user (consuming their cooldown and daily count) before the guild daily cap may
  refuse. A refund only in the summary paths would fork the semantics; a general refund would
  make probing past a guild cap free for the prober. The cooldown-rejection path consumes
  nothing, which is what the review required.
- **Workaround:** none needed; the user quota is a per-member rate limit, not a payment.
- **Verification required:** owner decision if quota admission should become transactional.

## Resolved in this pass

| ID | Issue | Test |
|---|---|---|
| C-001 | Fresh install could not boot (`--checkpoint-db` demanded the database) | `test_ops_and_gates.py` || C-002 | systemd unit was unwritable and restarted forever | `test_ops_and_gates.py` |
| C-003 | Budget breaker failed open; `STOP_RATIO` unbounded; concurrent overspend | `test_cost_breaker.py` |
| C-004 | NL channel summary bypassed `Read Message History` | `test_security_controls.py`, `test_summarize_security.py` |
| C-005 | Ops tools leaked member text, skipped opt-out, key in URL | `test_privacy_lifecycle.py` |
| C-006 | `/data delete` and opt-out left rows behind | `test_privacy_lifecycle.py` |
| C-007 | Media memory could reach ~2 GB on a 1 GB unit | `test_security_controls.py` |
| C-008 | Summary prompt mixed raw text, opt-out members and `focus_query` | `test_summarize_security.py` |
| C-009 | Missing `tzdata` silently forced UTC; Pacific midnight raised | `test_config_and_time.py` |
| C-010 | Non-dict `persona_culture` killed every reply | `test_persona_notes.py` |
| C-011 | Role-hierarchy gaps in moderation and NL; missing `guild_only` | `test_security_controls.py`, `test_command_policy.py` |
| C-012 | NL storage cleanup was open to any moderator | `test_command_policy.py`, `docs/COMMANDS.md` |
| C-013 | Confirmation gate not bound to channel; false success | `nl_router` unit paths, policy test |
| C-014 | AI quota gaps on `/translate`, `/rules`, NL summary, images | `test_cost_breaker.py`, policy test |
| C-015 | Mention injection from model output and media titles | `test_security_controls.py` |
| C-016 | Voice hijack via playlist/message player; `start()` race | `test_voice_and_guard.py` |
| C-017 | Cancelled subprocess left yt-dlp/FFmpeg alive; blocking DNS | `test_subprocess_cleanup.py` |
| C-018 | Anti-spam ignored edits; failed delete cancelled timeout | `test_voice_and_guard.py` |
| C-019 | Ghost-ping detector republished deleted text | `test_voice_and_guard.py` |
| C-020 | `forget_user_keyword("%")` erased everything | `test_database_integrity.py` |
| C-021 | `initialize()` mutated user data on every boot | `test_database_integrity.py` |
| C-022 | `/rules` never indexed; FTS kept orphan rows | `test_database_integrity.py` |
| C-023 | FTS/LIKE quoting; Arabic diacritics broke search | `test_database_integrity.py` |
| C-024 | Backup not atomic; sidecars leaked; no `sqlite3` in the image | `test_ops_and_gates.py` |
| C-025 | Docker pinned an outdated Deno; no runtime hardening | `test_ops_and_gates.py` |
| C-026 | `_headers` used invalid C comments; dead `/*.html` rule | `test_ops_and_gates.py` |
| C-028 | Cloudflare verifier treated failures as PASS | `test_ops_and_gates.py` |
| C-029 | Gate checks failed open | `test_ops_and_gates.py` |
| C-030 | Unbounded caches, FIFO "LRU", silent queue drops | `test_security_controls.py` |
| C-031 | Discord embed/text limits exceeded | `test_security_controls.py` |
| C-032 | `ANGEL_OWNER_ID="0"` accepted; Unicode digits crashed | `test_config_and_time.py` |
| C-033 | Website published 14 "platforms" for 4 sites | `tests/website/test_command_catalog.py` |
| C-034 | Windows launcher skipped pip after a partial failure | `test_ops_and_gates.py` |
| C-035 | Music reported success without transmitted audio | `test_audio_hardening.py`, `test_voice_and_guard.py` |
| P-001 | Empty or malformed provider response | `test_brain_hardening.py` |
| P-002 | `search_archive` default read everything | `test_database_integrity.py` |
| P-003 | Legacy dossier rows contradicted the README | `test_database_integrity.py` |
| P-004 | `opt_out` race with in-flight writes | `test_privacy_lifecycle.py` |
| P-005 | Direct destructive NL commands without confirmation | `nl_router` confirmation set, policy test |
| P-006 | Backup/persona timers were not in the repository | `test_ops_and_gates.py` |
| P-007 | Dependency audit could not fail | `test_ops_and_gates.py` |
| P-008 | `ANGEL_AUTO_INSTALL` installed at import | `test_config_and_time.py` |
| P-009 | `_SESSION_LOCK` bound to one event loop | `test_security_controls.py` |

## Resolved in the final review round (PR #9)

| ID | Issue | Test |
|---|---|---|
| FR-A | One budget reservation covered a whole model-fallback chain | `test_cost_breaker.py` |
| FR-B | Image-only / GIF-only AI replies were dropped before delivery | `test_admin_and_delivery.py` |
| FR-C | `/rep`, `/afk` and the background summary re-created opted-out rows | `test_privacy_lifecycle.py` |
| FR-C2 | Ambient prompt lines had no author marker and survived deletion | `test_privacy_lifecycle.py` |
| FR-D | The media byte budget filtered results after `gather`, not peak RAM | `test_media_budget.py` |
| FR-E | A confirmation authorized the stale requester snapshot | `test_confirm_gate.py` |
| FR-F | A summary inside cooldown still consumed user and guild quota | `test_ai_quota.py`, confirm-gate suite |
| FR-G | A stale DAVE retry dequeued tracks over active playback | `test_voice_and_guard.py` |
| FR-H | `/announce` used guild-level `mention_everyone`, ignoring overwrites | `test_admin_and_delivery.py` |
| FR-I | The backup directory was never provisioned before enabling the timer | `test_ops_and_gates.py` |
| FR-J | History tools missed `user_preferences` and swallowed failed inserts | `test_operator_tools.py` |
| FR-K | `cleanup_and_vacuum` fought the documented 60-line retention | `test_privacy_lifecycle.py` |
| FR-L | NL `انسي كلمة` deleted archive rows with no confirmation | `test_confirm_gate.py` |
| FR-M | 32 review minors (docs, tests, tools, workflow) — see `docs/recovery/LEDGER.md` | respective files |
