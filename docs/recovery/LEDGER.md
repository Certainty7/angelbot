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
- **Test:** `tests/test_ops_and_gates.py::test_systemd_unit_is_boot_safe` parses the unit and
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
- **Test:** `tests/test_authz_history.py::test_nl_summary_denied_without_history`,
  `::test_nl_summary_allowed_with_history`.

### C-005 — Ops tools leak member messages to Gemini, skip opt-out, hardcode the DB path
- **Status:** Fixed-verified
- **Claim:** `evolve_persona.py` read a fixed `chat_history.db`, selected the busiest channel
  across all guilds, sent 300 rows with display names, put the API key in the query string, and
  stored unvalidated JSON. `backfill_history.py`/`fetch_all_history.py` re-inserted opted-out
  members.
- **Fix:** all three tools resolve `ANGEL_DB_PATH` through `angel.config`, filter opted-out users
  in SQL, send the key in the `x-goog-api-key` header, validate the parsed payload is a dict, and
  refuse to run when the target channel is not in an allow-list of public channels. Backfill writes
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
  ambient rows, window expiry), `tests/test_deletion_coverage.py` (schema-driven).

### C-007 — Media memory budget exceeds the 1 GB unit cap
- **Status:** Fixed-verified
- **Claim:** up to 20 slides × 25 MB × 4 concurrent jobs ≈ 2 GB.
- **Fix:** one shared download semaphore, `MAX_JOB_BYTES` accumulated while slides are collected,
  Instagram carousels capped at 10 slides, and `chunk_slides` cannot exceed the attachment limit.
- **Test:** `tests/test_media_budget.py`.

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
- **Test:** `tests/test_timezone.py`.

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
- **Test:** `tests/test_admin_authz.py`, `tests/test_command_policy.py`.

### C-012 — NL storage cleanup available to any moderator
- **Status:** Fixed-verified
- **Fix:** the NL route requires the owner, matching `/cleanup`.
- **Test:** `tests/test_authz_history.py::test_nl_cleanup_requires_owner`.

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
- **Fix:** `AllowedMentions.none()` is the client default and `filter_outgoing` neutralises
  `<@id>`/`<@!id>` alongside `@everyone`/roles.
- **Test:** `tests/test_output_filter.py`.

### C-016 — Voice client hijack via `/playlist load` or the message player; `start()` race
- **Status:** Fixed-verified (logic) / Blocked-external (live voice)
- **Fix:** `ensure_connected` refuses to move the bot out of another channel, the message player
  checks the same precondition, `start()` performs its check and enqueue under one lock, and
  `on_voice_state_update` leaves an empty channel.
- **Test:** `tests/test_voice_lifecycle.py`.

### C-017 — Cancellation orphans `yt-dlp`/FFmpeg; synchronous DNS blocks the loop
- **Status:** Fixed-verified
- **Fix:** every subprocess is wrapped in `try/finally` that kills and reaps the child; `_drain`
  catches `BaseException`; DNS validation runs in a worker thread.
- **Test:** `tests/test_subprocess_cleanup.py`.

### C-018 — Anti-spam ignores edits; a failed delete cancels timeout and modlog
- **Status:** Fixed-verified
- **Fix:** `on_message_edit` runs the same guard; delete, timeout and modlog are independent
  `try` blocks and failures are logged.
- **Test:** `tests/test_guard_edits.py`.

### C-019 — Ghost-ping detector republishes deleted content
- **Status:** Fixed-verified
- **Fix:** the public-channel fallback is removed; without a modlog channel the event is logged
  locally instead of broadcast.
- **Test:** `tests/test_guard_edits.py::test_ghost_ping_without_modlog_does_not_broadcast`.

### C-020 — `forget_user_keyword` treats `%`/`_` as wildcards
- **Status:** Fixed-verified
- **Fix:** `_like_escape` plus `ESCAPE '\'` on every keyword query, and the command now asks for
  confirmation.
- **Test:** `tests/test_core_hardening.py`.

### C-021 — `initialize()` mutates and deletes user data on every boot
- **Status:** Fixed-verified
- **Fix:** the cleanup became a versioned one-time migration guarded by `PRAGMA user_version`;
  length-based deletion is gone.
- **Test:** `tests/test_migrations.py`.

### C-022 — `/rules` is never indexed and `rules_fts` keeps orphans
- **Status:** Fixed-verified
- **Fix:** added `rules_ad`, the index is rebuilt on demand from a channel the caller can read, and
  re-indexing replaces the table in one transaction.
- **Test:** `tests/test_rules.py`.

### C-023 — FTS/LIKE quoting and Arabic diacritics
- **Status:** Fixed-verified
- **Fix:** `search_archive` uses `_fts_query`; `channel_of_quote`/`read_admin_memory` escape LIKE;
  `server_messages_fts` uses `unicode61 remove_diacritics 2` and inputs are normalised, so
  `مُحَمَّد` matches `محمد`.
- **Test:** `tests/test_arabic_search.py`, `tests/test_core_hardening.py`.

### C-024 — Backup is not atomic and leaks `-wal`/`-shm`; no `sqlite3` in the image
- **Status:** Fixed-verified
- **Fix:** `mktemp` + `trap` + `mv`, a lock file, sidecar cleanup, second-resolution collision
  guard, and `sqlite3` installed in the image.
- **Test:** `tests/test_backup_script.py`.

### C-025 — Docker pins an outdated Deno and lacks runtime hardening
- **Status:** Fixed-verified (static) / Blocked-external (image build)
- **Fix:** Deno raised to a 2.9+ release with hashes taken from the published `SHASUMS256.txt`,
  `.dockerignore` excludes every `.env*` except the example, the container runs read-only with
  `tmpfs`, `pids_limit`, a healthcheck, and `curl`/`unzip` are removed after use.
- **Test:** `tests/test_deploy_assets.py`.
- **Limit:** no Docker daemon here, so the image was not built.

### C-026 — `website/public/_headers` uses invalid C comments and a dead `/*.html` rule
- **Status:** Fixed-verified
- **Fix:** `#` comments, an explicit `/*` CSP block, and `/` + `/*/` cache rules.
- **Test:** `tests/website/test_headers.py`.

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
- **Test:** `tests/test_ops_and_gates.py::test_token_verifier_rejects_inconclusive_statuses`.

### C-029 — Gate checks fail open
- **Status:** Fixed-verified
- **Fix:** `SyntaxError` propagates, any `shell` keyword and `sh -c` are detected, the owner-id
  check reads the environment, and `selftest` overrides rather than defaults the database path.
- **Test:** `tests/test_gate_checks.py`.

### C-030 — Unbounded caches, `BoundedDict` is FIFO, `SendQueue` drops silently
- **Status:** Fixed-verified
- **Fix:** the silent map stays a `BoundedDict` (`clear`/`update`), `__getitem__`/`get` move the key
  to the end (true LRU), dropped items increment `dead_letters`, and `stop()` records what it
  discards.
- **Test:** `tests/test_security_controls.py` (LRU), `tests/test_sendqueue.py` (dead letters,
  stopped sender).

### C-031 — Discord embed/text limits exceeded
- **Status:** Fixed-verified
- **Fix:** every embed field is truncated to its API limit and a shared helper budgets the total.
- **Test:** `tests/test_embed_limits.py`.

### C-032 — `ANGEL_OWNER_ID` accepts `0` and Unicode digits; `context_acl` misses the alias
- **Status:** Fixed-verified
- **Fix:** the value must be ASCII digits and greater than zero, with a clear `RuntimeError`;
  `context_acl` imports the resolved id instead of re-reading the environment.
- **Test:** `tests/test_config_validation.py`.

### C-033 — Website publishes `media_platforms: 14`
- **Status:** Fixed-verified
- **Fix:** the generator counts unique platforms from the fixture metadata, and the catalogue test
  asserts the real number.
- **Test:** `tests/website/test_command_catalog.py`.

### C-034 — Windows launcher skips `pip install` after a partial failure; no UTF-8
- **Status:** Fixed-verified
- **Fix:** dependencies are installed on every run (idempotent), the console is switched to UTF-8,
  and the checkpoint gate is meaningful after C-001.
- **Test:** `tests/test_deploy_assets.py`.

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
- **Test:** `tests/test_audio_hardening.py`, `tests/test_voice_lifecycle.py`.
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
  Test: `tests/test_arabic_search.py::test_search_archive_requires_allowed_channels`.

### P-003 — Legacy `user_dossier`/`user_profile` rows
- **Status:** Fixed-verified — the columns are dropped by a versioned migration and the README no
  longer claims the data exists. Test: `tests/test_migrations.py`.

### P-004 — `opt_out` race with in-flight writes
- **Status:** Fixed-verified — the opt-out predicate is inside the write statement.
  Test: `tests/test_privacy_lifecycle.py::test_concurrent_write_cannot_resurrect`.

### P-005 — Direct destructive NL commands without confirmation
- **Status:** Fixed-verified — every state-changing NL action is inside the confirmation gate.
  Test: `tests/test_confirm_gate.py`.

### P-006 — External systemd timers are not in the repository
- **Status:** Fixed-verified — `deploy/angelbot-backup.{service,timer}` and
  `deploy/angelbot-persona.{service,timer}` now ship with the repository, pinned to the same
  database path. Test: `tests/test_deploy_assets.py`.

### P-007 — Dependency audit is advisory only
- **Status:** Fixed-verified — the scheduled workflow fails on high/critical findings for both the
  Python and the website dependency trees, while the fast PR job stays advisory.
  Test: `.github/workflows/checks.yml` lint in `tests/test_deploy_assets.py`.

### P-008 — `ANGEL_AUTO_INSTALL=1` installs unpinned packages at import
- **Status:** Fixed-verified — the environment variable is removed; the bootstrap prints the exact
  install command and never reaches PyPI. Test: `tests/test_config_validation.py`.

### P-009 — `_SESSION_LOCK` bound to one event loop
- **Status:** Fixed-verified — the lock is per event loop, mirroring the semaphore registry.
  Test: `tests/test_net_security.py`.

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
