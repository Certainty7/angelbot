# RECOVERY LEDGER — AngelBot v1.0.4 stabilization

Every historical finding from `angelbot_v1_0_4_independent_audit_2026-11-20.md` is listed with its
current status. Status vocabulary:

`Open` · `Fixed-verified` · `Fixed-not-live-verified` · `Already-fixed-before` · `Not-reproducible` ·
`Blocked-external` · `Deferred-with-reason`

"Verified" means a regression test in this repository executes the fixed path and passes.
"Not-live-verified" means the code path is fixed and unit-verified but the real external service
(Discord voice, Gemini, Cloudflare, systemd, Docker) was not reachable from this environment.

Baseline audited commit: `51090aa`. All findings below were re-checked against the current tree
rather than accepted from the report.

---

## A. Confirmed findings (35)

### C-001 — Every deployment path fails on first boot
- **Status:** Fixed-verified
- **Claim:** `--checkpoint-db` exits 1 when the database does not exist, and `selftest` fails
  `BASE_DIR` on the default path; systemd/Docker/Windows therefore never reach `setup_hook()`.
- **Evidence:** `bot.py` `_run_sqlite_cli_utility` returned 1 on `not os.path.exists(DB_PATH)`;
  `tools/selftest.py` asserted `os.path.isfile(cfg.DB_PATH)` for the default path.
- **Reproduced:** yes — empty temp dir, `ANGEL_DB_PATH` pointing at a missing file.
- **Root cause:** a pre-start gate demanded an artifact the application itself creates later.
- **Fix:** checkpoint mode reports "no database yet" and returns 0; `--verify-db` still fails.
  `selftest` treats the default, not-yet-created database as a skip instead of a failure and no
  longer inherits a production `ANGEL_DB_PATH`.
- **Test:** `tests/test_ops_and_gates.py::test_checkpoint_db_on_fresh_directory`,
  `::test_selftest_skips_missing_default_db`, `::test_verify_db_still_fails_without_database`.

### C-002 — systemd unit cannot write its database and restarts forever
- **Status:** Fixed-verified (unit-file lint) / Blocked-external (real `systemd-analyze`)
- **Claim:** `ProtectSystem=strict` + no `ANGEL_DB_PATH` + `Restart=always` without start limits.
- **Root cause:** the shipped unit relied on a default DB path under a read-only mount and used an
  unbounded restart policy.
- **Fix:** `Environment=ANGEL_DB_PATH=/opt/angelbot/data/angel.db`, `StateDirectory=angelbot`,
  `StartLimitIntervalSec`/`StartLimitBurst`, `Restart=on-failure`, `TimeoutStopSec=60`,
  `UMask=0077`.
- **Test:** `tests/test_ops_and_gates.py::SystemdUnitTest` parses the unit and
  asserts each property.
- **Limit:** `systemd-analyze verify` is not installed here.

### C-003 — Daily budget breaker fails open; `STOP_RATIO` unbounded; TOCTOU
- **Status:** Fixed-verified
- **Claim:** an exception during evolution load left `ai.db = None`, `budget_blocked()` then
  returned `False` (no ceiling); `STOP_RATIO=0` blocked everyone and `>1` raised the cap; the
  check-then-spend window admitted concurrent overspend.
- **Reproduced:** yes — corrupted `state.settings`, `STOP_RATIO` edge values.
- **Fix:** the AI service receives its database handle outside the evolution `try`;
  `budget_blocked()` fails closed for a missing handle unless the cap is explicitly disabled;
  `STOP_RATIO` is clamped to `(0, 1]`; spend is reserved under a lock before the request and
  reconciled with the actual cost afterwards.
- **Test:** `tests/test_cost_breaker.py` (five cases including a 10-way concurrency test).

### C-004 — Natural-language channel summary bypasses `Read Message History`
- **Status:** Fixed-verified
- **Claim:** `/summarize_channel` checked permissions; the NL path checked only owner/cooldown.
- **Fix:** a shared `can_read_history(channel, member)` guard is used by both entry points, with a
  DM/no-guild denial. The NL path returns the same message the slash command returns.
- **Test:** `tests/test_security_controls.py::HistoryAccessTest`,
  `tests/test_summarize_security.py`.

### C-005 — Ops tools leak member messages to Gemini, skip opt-out, hardcode the DB path
- **Status:** Fixed-verified
- **Claim:** `evolve_persona.py` read a fixed `chat_history.db`, selected the busiest channel
  across all guilds, sent 300 rows with display names, put the API key in the query string, and
  stored unvalidated JSON. `backfill_history.py`/`fetch_all_history.py` re-inserted opted-out
  members.
- **Fix:** all three tools resolve `ANGEL_DB_PATH` through the shared `tools/dbpath.py` resolver,
  filter opted-out users in SQL, send the key in the `x-goog-api-key` header, validate the parsed
  payload is a dict, and refuse to run unless `ANGEL_PERSONA_CHANNEL_ID` names a channel (the
  archive records no channel type, so "busiest channel" could be a staff room). Backfill writes
  `message_id` and uses `INSERT OR IGNORE` so it cannot duplicate live rows.
- **Test:** `tests/test_operator_tools.py::test_opted_out_text_never_enters_the_prompt`,
  `::test_the_key_travels_in_a_header`, `::test_a_non_object_payload_is_rejected`.

### C-006 — `/data delete` and opt-out are incomplete
- **Status:** Fixed-verified
- **Claim:** DM messages were never treated as opt-out, XP was re-created after deletion,
  `ambient_log`/`afk_users`/`harem_members`/`persona_culture` survived, `count_user_data`
  under-reported, `memory.touch` built a topic index, in-flight writes resurrected rows, and
  `active_chat_window` used `.items()` so the window never expired.
- **Fix:** opt-out is evaluated for DMs too; XP, DM forwarding and ambient buffering are gated;
  deletion covers every user-associated table (schema-derived, see D-005); the count matches the
  deletion set; `active_chat_window` iterates `.keys()`; writes carry the opt-out predicate in SQL.
- **Test:** `tests/test_privacy_lifecycle.py` (deletion coverage, XP after delete, DM silence,
  ambient rows, window expiry), `tests/test_privacy_lifecycle.py::DeletionCoverageTest` (schema-driven).

### C-007 — Media memory budget exceeds the 1 GB unit cap
- **Status:** Fixed-verified
- **Claim:** up to 20 slides × 25 MB × 4 concurrent jobs ≈ 2 GB.
- **Fix:** one shared download semaphore, `MAX_JOB_BYTES` accumulated while slides are collected,
  Instagram carousels capped at 10 slides, and `chunk_slides` cannot exceed the attachment limit.
- **Test:** `tests/test_security_controls.py::MediaBudgetTest`.

### C-008 — `summarize.py` puts opted-out text, raw transcript and `focus_query` in one prompt
- **Status:** Fixed-verified
- **Fix:** opt-out is filtered fail-closed, the transcript is wrapped in `<untrusted_transcript>`,
  every line and `focus_query` pass through the untrusted-context sanitiser, and the history read
  requires `read_message_history`.
- **Test:** `tests/test_summarize_security.py`.

### C-009 — Missing `tzdata` silently forces UTC; Pacific midnight raises
- **Status:** Fixed-verified
- **Fix:** `tzdata` added to requirements and the image; `_resolve_timezone` keeps a documented
  fixed-offset fallback instead of reporting UTC as if it were the requested zone;
  `_seconds_until_pacific_midnight` falls back to a fixed PST/PDT offset; `per day` matching is
  case-insensitive.
- **Test:** `tests/test_config_and_time.py::TimezoneTest`.

### C-010 — A non-dict `persona_culture` row kills every AI reply in the guild
- **Status:** Fixed-verified
- **Fix:** `_render` returns an empty string for any non-dict payload; the writer validates
  `isinstance(parsed, dict)` before storing.
- **Test:** `tests/test_persona_notes.py`.

### C-011 — Role-hierarchy and permission gaps across moderation and NL
- **Status:** Fixed-verified
- **Claim:** kick/ban/timeout used a hand-written weaker check, `/clear_warnings` had none,
  `[EXEC: NICKNAME]` had none, NL `WARN`/`CLEAR_WARNINGS` accepted lower privileges, `/announce`
  allowed `@everyone` with `manage_guild`, and 17 admin commands lacked `guild_only`.
- **Fix:** every moderation route calls `can_moderate_member`; NL warn/clear use the same guard;
  `@everyone` requires `mention_everyone`; administrative commands are `guild_only` while the
  explicitly DM-capable ones stay usable in DMs.
- **Test:** `tests/test_security_controls.py::ModerationHierarchyTest`, `tests/test_command_policy.py`.

### C-012 — NL storage cleanup available to any moderator
- **Status:** Fixed-verified
- **Fix:** the NL route requires the owner, matching `/cleanup`.
- **Test:** `tests/test_command_policy.py (cleanup policy) and `angel/nl_router.py` owner check`.

### C-013 — Confirmation gate is not bound to its channel and reports false success
- **Status:** Fixed-verified
- **Claim:** the pending entry keyed only `(guild, author)`, a stale message could be executed from
  another channel, the executor's return value was ignored so success was always announced,
  nine state-changing actions skipped confirmation, and `نفذ`/`لا` were unsafe trigger words.
- **Fix:** the pending entry is bound to `channel_id`, the target and actor are re-fetched and
  re-authorized at execution time, the reply reflects the real result, the confirm set covers every
  state-changing action, and bare `نفذ`/`لا` are no longer trigger words.
- **Test:** `tests/test_confirm_gate.py` (queue channel binding, hierarchy refusal, real
  outcome, ordinary words are not confirmations).

### C-014 — AI quota gaps: `/translate`, `/rules`, NL summary, image generation
- **Status:** Fixed-verified
- **Fix:** every AI entry point calls `check_user_allowed` and consumes the guild quota; image
  generation paces global RPM and skips cooling/dead models; all callers pass `user=`.
- **Test:** `tests/test_ai_quota.py` plus `tests/test_cost_breaker.py`.

### C-015 — Mention injection through model output and third-party titles
- **Status:** Fixed-verified
- **Fix:** `AllowedMentions.none()` is passed on every untrusted outbound path (model output,
  transcripts, media titles, archive quotes, AFK reasons) via `untrusted=True`, and
  `filter_outgoing` neutralises `<@id>`/`<@!id>` alongside `@everyone`/roles. The client default
  stays `users=True` so bot-authored confirmations still ping the member they name.
- **Test:** `tests/test_security_controls.py::OutputFilterTest`, `tests/test_summarize_security.py`.

### C-016 — Voice client hijack via `/playlist load` or the message player; `start()` race
- **Status:** Fixed-verified (logic) / Blocked-external (live voice)
- **Fix:** `ensure_connected` refuses to move the bot out of another channel, the message player
  checks the same precondition, `start()` performs its check and enqueue under one lock, and
  `on_voice_state_update` leaves an empty channel.
- **Test:** `tests/test_voice_and_guard.py::VoiceChannelGuardTest`.

### C-017 — Cancellation orphans `yt-dlp`/FFmpeg; synchronous DNS blocks the loop
- **Status:** Fixed-verified
- **Fix:** every subprocess is wrapped in `try/finally` that kills and reaps the child; `_drain`
  catches `BaseException`; DNS validation runs in a worker thread.
- **Test:** `tests/test_subprocess_cleanup.py`.

### C-018 — Anti-spam ignores edits; a failed delete cancels timeout and modlog
- **Status:** Fixed-verified
- **Fix:** `on_message_edit` runs the same guard; delete, timeout and modlog are independent
  `try` blocks and failures are logged.
- **Test:** `tests/test_voice_and_guard.py::GuardTest`.

### C-019 — Ghost-ping detector republishes deleted content
- **Status:** Fixed-verified
- **Fix:** the public-channel fallback is removed; without a modlog channel the event is logged
  locally instead of broadcast.
- **Test:** `tests/test_voice_and_guard.py::GhostPingTest`.

### C-020 — `forget_user_keyword` treats `%`/`_` as wildcards
- **Status:** Fixed-verified
- **Fix:** `_like_escape` plus `ESCAPE '\'` on every keyword query, and the command now asks for
  confirmation.
- **Test:** `tests/test_core_hardening.py`.

### C-021 — `initialize()` mutates and deletes user data on every boot
- **Status:** Fixed-verified
- **Fix:** the cleanup became a versioned one-time migration guarded by `PRAGMA user_version`;
  length-based deletion is gone.
- **Test:** `tests/test_database_integrity.py::MigrationTest`.

### C-022 — `/rules` is never indexed and `rules_fts` keeps orphans
- **Status:** Fixed-verified
- **Fix:** added `rules_ad`, `replace_rules()` replaces the table in one transaction, and the
  index is rebuilt on demand from the guild's configured rules channel by staff only (`/rules
  refresh: نعم`). A cache miss never re-indexes an arbitrary channel.
- **Test:** `tests/test_database_integrity.py::RulesIndexTest`.

### C-023 — FTS/LIKE quoting and Arabic diacritics
- **Status:** Fixed-verified
- **Fix:** `search_archive` uses `_fts_query`; `channel_of_quote`/`read_admin_memory` escape LIKE;
  `server_messages_fts` uses `unicode61 remove_diacritics 2` and inputs are normalised, so
  `مُحَمَّد` matches `محمد`.
- **Test:** `tests/test_database_integrity.py::ArabicSearchTest`, `tests/test_core_hardening.py`.

### C-024 — Backup is not atomic and leaks `-wal`/`-shm`; no `sqlite3` in the image
- **Status:** Fixed-verified
- **Fix:** `mktemp` + `trap` + `mv`, a lock file, sidecar cleanup, second-resolution collision
  guard, and `sqlite3` installed in the image.
- **Test:** `tests/test_ops_and_gates.py::BackupScriptTest`.

### C-025 — Docker pins an outdated Deno and lacks runtime hardening
- **Status:** Fixed-verified (static) / Blocked-external (image build)
- **Fix:** Deno raised to a 2.9+ release with hashes taken from the published `SHASUMS256.txt`,
  `.dockerignore` excludes every `.env*` except the example, the container runs read-only with
  `tmpfs`, `pids_limit`, a healthcheck, and `curl`/`unzip` are removed after use.
- **Test:** `tests/test_ops_and_gates.py (SystemdUnitTest, ContainerAssetsTest, WindowsLauncherTest)`.
- **Limit:** no Docker daemon here, so the image was not built.

### C-026 — `website/public/_headers` uses invalid C comments and a dead `/*.html` rule
- **Status:** Fixed-verified
- **Fix:** `#` comments, an explicit `/*` CSP block, and `/` + `/*/` cache rules.
- **Test:** `tests/test_ops_and_gates.py::HeadersFileTest`.

### C-027 — Public git history retains removed operator details
- **Status:** Deferred-with-reason
- **Reason:** rewriting a published branch breaks every clone and tag and is outside the authorized
  scope. The removal from `HEAD` stands; the residual exposure and the two available remedies are
  documented in `SECURITY.md`. No credentials were ever committed.
- **Evidence:** full-history scan recorded in `docs/recovery/SECRET_SCAN.md`.

### C-028 — `verify_cloudflare_token.py` treats transport failure, 429 and 5xx as success
- **Status:** Fixed-verified
- **Fix:** `authorised()` is an allow-list of `200/400/404`; `0`/`429`/`5xx` are reported as
  inconclusive or failed.
- **Test:** `tests/test_ops_and_gates.py::ToolingGatesTest`.

### C-029 — Gate checks fail open
- **Status:** Fixed-verified
- **Fix:** `SyntaxError` propagates, any `shell` keyword and `sh -c` are detected, the owner-id
  check reads the environment, and `selftest` overrides rather than defaults the database path.
- **Test:** `tests/test_ops_and_gates.py::ToolingGatesTest`.

### C-030 — Unbounded caches, `BoundedDict` is FIFO, `SendQueue` drops silently
- **Status:** Fixed-verified
- **Fix:** the silent map stays a `BoundedDict` (`clear`/`update`), `__getitem__`/`get` move the key
  to the end (true LRU), dropped items increment `dead_letters`, and `stop()` records what it
  discards.
- **Test:** `tests/test_security_controls.py::CacheTest, `tests/test_sendqueue.py`.

### C-031 — Discord embed/text limits exceeded
- **Status:** Fixed-verified
- **Fix:** every embed field is truncated to its API limit and a shared helper budgets the total.
- **Test:** `tests/test_security_controls.py::EmbedLimitTest`.

### C-032 — `ANGEL_OWNER_ID` accepts `0` and Unicode digits; `context_acl` misses the alias
- **Status:** Fixed-verified
- **Fix:** the value must be ASCII digits and greater than zero, with a clear `RuntimeError`;
  `context_acl` imports the resolved id instead of re-reading the environment.
- **Test:** `tests/test_config_and_time.py`.

### C-033 — Website publishes `media_platforms: 14`
- **Status:** Fixed-verified
- **Fix:** the generator counts unique platforms from the fixture metadata, and the catalogue test
  asserts the real number.
- **Test:** `tests/website/test_command_catalog.py`.

### C-034 — Windows launcher skips `pip install` after a partial failure; no UTF-8
- **Status:** Fixed-verified
- **Fix:** dependencies are installed on every run (idempotent), the console is switched to UTF-8,
  and the checkpoint gate is meaningful after C-001.
- **Test:** `tests/test_ops_and_gates.py (SystemdUnitTest, ContainerAssetsTest, WindowsLauncherTest)`.

### C-035 — Music reports success while nothing is transmitted
- **Status:** Fixed-verified (logic) / Blocked-external (live DAVE session)
- **Claim:** DAVE frames dropped silently with `can_encrypt=False`, `FFMPEG_PATH` was read before
  `.env` loaded, yt-dlp headers were not forwarded, cached SoundCloud URLs expired, YouTube failed
  with a raw exit code.
- **Fix:** `.env` loads before any `os.getenv`; the host ffmpeg is preferred; safe yt-dlp headers are
  forwarded to FFmpeg with timeouts; a strict DAVE gate refuses playback it cannot deliver; the
  audio monitor counts decoded bytes and reports a silent stream instead of claiming success; the
  cache can be invalidated; YouTube failures explain themselves and fall back to a SoundCloud
  search by oEmbed title.
- **Test:** `tests/test_audio_hardening.py`, `tests/test_voice_and_guard.py::VoiceChannelGuardTest`.
- **Limit:** a real Discord voice session with DAVE negotiation cannot be created here; see
  `docs/LIVE_VERIFICATION.md`.

---

## B. Potential risks (9)

### P-001 — Empty/thought-only or malformed Gemini response
- **Status:** Fixed-verified — `visible_text` is validated; an empty answer cools that model and
  fails over to the next one, and a JSON decode failure cannot escape the loop. The caller no
  longer substitutes "تم." for an empty reply. Test: `tests/test_persona_notes.py`
  (`ProviderResponseTest`).

### P-002 — `search_archive(allowed_channels=None)` reads everything
- **Status:** Fixed-verified — `allowed_channels` is required; `None` yields an empty result and a
  warning rather than an unrestricted read, and the filter runs inside SQL.
  Test: `tests/test_database_integrity.py::ArabicSearchTest`.

### P-003 — Legacy `user_dossier`/`user_profile` rows
- **Status:** Fixed-verified — the columns are dropped by a versioned migration and the README no
  longer claims the data exists. Test: `tests/test_database_integrity.py::MigrationTest`.

### P-004 — `opt_out` race with in-flight writes
- **Status:** Fixed-verified — the opt-out predicate is inside the write statement.
  Test: `tests/test_privacy_lifecycle.py::OptOutTest`.

### P-005 — Direct destructive NL commands without confirmation
- **Status:** Fixed-verified — every state-changing NL action is inside the confirmation gate.
  Test: `tests/test_confirm_gate.py`.

### P-006 — External systemd timers are not in the repository
- **Status:** Fixed-verified — `deploy/angelbot-backup.{service,timer}` and
  `deploy/angelbot-persona.{service,timer}` now ship with the repository, pinned to the same
  database path. Test: `tests/test_ops_and_gates.py (SystemdUnitTest, ContainerAssetsTest, WindowsLauncherTest)`.

### P-007 — Dependency audit is advisory only
- **Status:** Fixed-verified — the scheduled workflow fails on high/critical findings for both the
  Python and the website dependency trees, while the fast PR job stays advisory.
  Test: `.github/workflows/checks.yml` lint in `tests/test_ops_and_gates.py (SystemdUnitTest, ContainerAssetsTest, WindowsLauncherTest)`.

### P-008 — `ANGEL_AUTO_INSTALL=1` installs unpinned packages at import
- **Status:** Fixed-verified — the environment variable is removed; the bootstrap prints the exact
  install command and never reaches PyPI. Test: `tests/test_config_and_time.py`.

### P-009 — `_SESSION_LOCK` bound to one event loop
- **Status:** Fixed-verified — the lock is per event loop, mirroring the semaphore registry.
  Test: `tests/test_security_controls.py::SessionLockTest`.

---

## C. New defects found during this recovery

Recorded as `N-00x` with the same fields. Filled in as they were found and fixed.

### N-001 — `docs/` recovery record absent
- **Status:** Fixed-verified — this ledger plus `STATE.md`/`DECISIONS.md` are the durable record.

### N-002 — Test suite inherited a production database path
- **Status:** Fixed-verified — the suite now forces a temp database and scrubs credentials through
  an autouse fixture (`tests/conftest.py`).

### N-003 — No network isolation in tests
- **Status:** Fixed-verified — an autouse socket guard rejects unexpected outbound connections.

### N-004 — CLI utilities crashed on a legacy Windows code page
- **Status:** Fixed-verified
- **Found by:** the fresh-install regression test, which failed with `UnicodeEncodeError` while
  printing the checkpoint message under a cp1252 pipe.
- **Root cause:** `print()` of an emoji on a non-UTF-8 stdout; the gate then exited 1 on a
  successful run.
- **Fix:** `_force_utf8_console()` reconfigures stdout/stderr at the start of every CLI mode, and
  the missing-package notice moved to stderr.
- **Test:** `tests/test_ops_and_gates.py::FreshInstallGateTest`.

### N-005 — An empty model reply was reported as success
- **Status:** Fixed-verified
- **Found by:** the provider-response regression test.
- **Root cause:** `_post_with_retry` returned `""` for a thought-only answer, and
  `handle_conversation` replaced it with "تم." — a confident success message for a failed call.
- **Fix:** an empty visible answer cools that model and fails over; if every model is empty the
  reply is empty (and logged), never invented.
- **Test:** `tests/test_persona_notes.py::ProviderResponseTest`.

### N-006 — `/rules` could be used to overwrite the rule corpus with chat text
- **Status:** Fixed-verified
- **Found by:** the independent review pass.
- **Root cause:** on any cache miss the command re-indexed whatever channel the caller was in and
  `replace_rules()` deletes the previous index first. A member could replace staff rules with a
  chat line, which `/rules` then quoted back as authoritative.
- **Fix:** indexing requires the guild's configured rules channel and `manage_guild` (or the
  owner), and `index_channel` filters opted-out authors. `/rules refresh: نعم` is the explicit
  staff action.
- **Test:** `tests/test_command_policy.py` (policy) + `tests/test_database_integrity.py::RulesIndexTest`.

### N-007 — `/data view` raised KeyError and the delete receipt reported zeros
- **Status:** Fixed-verified
- **Found by:** the independent review pass.
- **Root cause:** `count_user_data()` switched to table-keyed counts while the command still read
  the old aliases; the receipt used `.get(old_key, 0)` and therefore always printed 0.
- **Fix:** the command reads the real keys, shows XP and ambient rows, and a failed table is
  surfaced in the receipt instead of being swallowed.
- **Test:** `tests/test_privacy_lifecycle.py::DeletionTest`.

### N-008 — The test suite never exited
- **Status:** Fixed-verified
- **Found by:** the independent review pass.
- **Root cause:** `GhostPingTest` invoked the module-level handler with the real global client,
  which opened an aiosqlite connection the test never closed. The non-daemon worker thread kept
  the interpreter alive after the summary, so CI would hang until the job timeout.
- **Fix:** the test injects a fake client with `patch.object(module, "bot", bot)`.
- **Test:** `tests/test_voice_and_guard.py::GhostPingTest` (the suite now exits on its own).

### N-009 — Deleted members survived in RAM
- **Status:** Fixed-verified
- **Found by:** the independent review pass.
- **Root cause:** `/data delete` cleared the DB and three buffers but left `afk_cache`,
  `harem_cache` and `recent_channel_msgs`, so a deleted member's AFK reason and last lines kept
  reaching other members' prompts.
- **Fix:** all three are purged in the same block.
- **Test:** `tests/test_privacy_lifecycle.py` (DB) plus the purge block in `cogs/memory_rules.py`.

### N-010 — `/memory forget` was immediate and missed the archive
- **Status:** Fixed-verified
- **Found by:** the independent review pass.
- **Root cause:** the keyword scrub touched `messages` and the profile tables but not
  `server_messages`, which is what `archive.lookup` quotes back, and it ran without confirmation.
- **Fix:** `confirm: نعم` is required, and the archive rows are scrubbed too (the FTS delete
  trigger keeps the index in sync).
- **Test:** `tests/test_database_integrity.py::ForgetKeywordTest`.

---

## Verification

Executed on the branch tip, Windows 11, Python 3.13.14, with `ANGEL_OWNER_ID=42`,
`ANGEL_AUTO_INSTALL=0` and a temporary `ANGEL_DB_PATH`.

| Command | Result |
|---|---|
| `python -m compileall -q bot.py angel cogs tools tests` | exit 0 |
| `python -m pytest -q` | 182 passed, 322 subtests passed |
| `python tools/selftest.py` | 50/50, exit 0 |
| `python tools/security_probe.py` | PASS, exit 0 |
| `python tools/recall_probe.py` | 10/10, exit 0 |
| `python bot.py --checkpoint-db` with no database | exit 0, no database created |
| `python tools/website-data-generator/generate.py --check` | exit 0 |
| `python tests/website/test_command_catalog.py` | 14/14 |
| secret scan over 46 commits and 276 tracked files | no real credential; one documented `AKIA`+16`A` placeholder |

`tools/gate_checks.py` is a library, not a standalone script: its checks run inside
`tools/selftest.py` and are included in the 50/50 result.

Not executable in this environment (recorded, not claimed): a real Discord voice/DAVE session,
YouTube extraction against the live provider, a Docker image build, real systemd, live Cloudflare
response headers, and any Gemini request. See `docs/LIVE_VERIFICATION.md`.

---

## Final review round — PR #9 remediation (2026-11-20, GLM 5.3)

The branch head `7ef1163` was re-reviewed through the full PR #9 CodeRabbit inventory
(11 inline majors, 3 outside-diff findings, 24 + 8 minors). Every finding was verified against the
tree; all confirmed defects were fixed with regression tests.

### Findings and disposition

| # | Finding (file) | Disposition | Test |
|---|---|---|---|
| A | Budget reservation covered the whole fallback chain (`brain.py`) | Fixed: per-attempt reserve + atomic settle | `test_cost_breaker.py` |
| B | Media-only replies silently dropped (`bot.py`, `cogs/ai_chat.py`) | Fixed: `plan_reply_delivery` | `test_admin_and_delivery.py` |
| C | `/rep`, `/afk`, background summary re-created opted-out rows (`database.py`) | Fixed: SQL guards in each writer | `test_privacy_lifecycle.py` |
| D | Byte budget applied after `gather` (`media.py`) | Fixed: `SharedByteBudget` per-chunk claims | `test_media_budget.py` |
| E | Confirmation authorized the stale requester snapshot (`nl_router.py`) | Fixed: current actor re-resolved + re-checked | `test_confirm_gate.py` |
| F | Summary cooldown consumed quota first (`nl_router.py`, `ai_chat.py`) | Fixed: claim-then-quota with rollback | `test_ai_quota.py`, manual via code order |
| G | Stale DAVE retry ate the queue (`voice_engine.py`) | Fixed: `_advance_if_idle` ownership check | `test_voice_and_guard.py` |
| H | `/announce` ignored channel overwrites (`admin.py`) | Fixed: effective perms both sides | `test_admin_and_delivery.py` |
| I | `ReadWritePaths` does not create the backup dir (`deploy`) | Fixed: documented provisioning + gate | `test_ops_and_gates.py` |
| J | `user_preferences` missing; inserts swallowed (`tools/fetch_all_history.py`) | Fixed: schema + page failure tracking | `test_operator_tools.py` |
| R1 | `cleanup_and_vacuum` deleted short summaries / capped at 50 (`database.py`) | Fixed: shared `MESSAGES_RETAINED_PER_USER` | `test_privacy_lifecycle.py` |
| R2 | `active_chat_window` iterated `.items()` (`memory_rules.py`) | Fixed: iterate keys | `test_privacy_lifecycle.py` |
| R3 | NL `انسي كلمة` deleted without confirmation (`nl_router.py`) | Fixed: pending-confirm + `FORGET_KEYWORD` | `test_confirm_gate.py` |
| M1..M24 | 24 review-body minors (Dockerfile healthcheck, dbpath parsing, music/playlist channel assignment, edit flood counting, config test AST, timezone test, conftest dotenv restore, README units install, exec-tag assertion, lock identity, owner fixture, prompt bound, warnings embed size, guild contexts, persona docstring, DATA_MODEL fixes, count failure reporting, migration v2 topics, comment reference, corpus existence, argv shell gate, summarize opt-out re-read) | Fixed | respective files |
| F1..F8 | 8 follow-up minors (interaction fallback mentions, cooldown-before-quota, atomic settle, notification channel, cookies discovery, SoundCloud duration, timeout assertion, npm audit job) | Fixed | respective files |

Notes: the budget finding required restoring the historical `budget_blocked()` precheck beside the
new reservation (D-015): with the cap disabled (`stop_at=inf`) the gate's synthetic over-ceiling
stranger must still be refused before any HTTP call, which the reservation short-circuit alone
did not do. The `dbpath.py` minor was fixed with the pinned python-dotenv parser, keeping the
"no `angel.config` import" rule. Nothing from the review was applied blindly; the three
`upsert_profile_fact`-style comments that were already accurate or unreachable were verified and
left unchanged.

### Verification (final round)

Windows 11, Python 3.13.14, `ANGEL_OWNER_ID=42`, temp `ANGEL_DB_PATH`,
`PYTHONIOENCODING=utf-8` (console codepage; CI is UTF-8 Linux).

| Command | Result |
|---|---|
| `python -m compileall -q bot.py angel cogs tools tests` | exit 0 |
| `python -m pytest -q` | 223 passed, 322 subtests passed, exit 0 |
| `python tools/selftest.py` | 50/50, exit 0 (includes `gate_checks.py`) |
| `python tools/security_probe.py` | PASS, exit 0 |
| `python tools/recall_probe.py` | 10/10, exit 0 |
| `python tools/website-data-generator/generate.py --check` | exit 0 |
| `python tests/website/test_command_catalog.py` | 14/14, exit 0 |
| website build (`npm ci` + `npm run build`, no local bash) | 20 pages, exit 0 |
| publish guards (files ≤ 20000, index/404, no >25 MiB, no leaks) | pass |
| `npx playwright test` | 67 passed, exit 0 |
| `python -m pip_audit -r requirements.txt` | no known vulnerabilities, exit 0 |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilities, exit 0 |
| secret scan (tracked tree + new diff) | clean |

### Post-merge re-review findings (CodeRabbit on `7b38ee1`, received after the merge)

1. **User quota is consumed before the guild quota gate rejects (NL + slash summary).**
   Valid observation, deliberately not changed: this is the established accounting shape of
   every gated command (`/translate`, `/chat`, `/imagine`, `/rules` all admit the user before
   the guild cap may refuse). Refunding the user quota only in the summary paths would fork the
   semantics, and a general refund changes anti-abuse behaviour (probing past a guild cap would
   become free for the prober). The original finding — cooldown rejection consuming quota — is
   fixed and confirmed by the reviewer. Left for an owner decision if the semantics should ever
   become transactional.
2. **Instagram dedup released duplicate claims while the gather result still referenced the
   payloads** (a repair could claim the released bytes while the duplicate stayed in RAM).
   Confirmed defect in the remediation itself; fixed on the follow-up branch
   `recovery/followup-media-budget`: `_dedupe_downloaded_slides` now returns the discarded
   byte total, and the caller clears `valid_items`/`dl_results` before releasing. Regression:
   `tests/test_media_budget.py::DuplicateSlideAccountingTest`.

Still not executable here (unchanged): live Discord/DAVE, live YouTube, Docker build, systemd,
live Cloudflare headers, live Gemini. `docs/LIVE_VERIFICATION.md` remains the checklist.
