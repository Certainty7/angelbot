# ENGINEERING DECISIONS — AngelBot stabilization

Permanent engineering memory for the recovery work. Each entry records the decision, the
alternatives that were rejected, and the constraint that forced the choice.

## D-001 — Work on `recovery/stabilization`, never on `master`

`master` is wired to production (Cloudflare Pages on the website workflow). The delivery brief
forbids triggering production deployment, so all work lands on a dedicated branch and reaches
`master` only through a reviewed pull request that a human merges.

Rejected: committing directly to `master` and reverting; rewriting `master`.

## D-002 — Commit the audio hotfix as-is first, then fix it

The hotfix was already applied in the working tree but uncommitted. Committing it unchanged before
touching it gives a clean bisect point and keeps the supplied artifact comparable to the repository
state. Changes to it in later commits are then reviewable as a normal diff.

Rejected: reverting and re-applying the patch (risk of losing local edits); squashing it into the
recovery work (loses the provenance of the supplied artifact).

## D-003 — `--checkpoint-db` succeeds on a missing database; `--verify-db` does not

`--checkpoint-db` is a pre-start housekeeping step in systemd, Docker and the Windows launcher.
A first install has no database yet, and the bot creates it in `setup_hook()`. Failing the gate
there makes every documented deployment path unable to boot (C-001). `--verify-db` keeps failing
on a missing file because its whole purpose is to audit an existing database.

Rejected: having the gate create the schema itself (duplicates `initialize()` outside the bot
lifecycle and can race a concurrently starting service).

## D-004 — Budget accounting fails closed, including when the database handle is missing

A cost breaker that opens when its own state is unreadable is not a breaker. `budget_blocked()`
now blocks when `self.db is None` unless the operator explicitly disabled the cap with
`DAILY_LIMIT_USD == 0`. `STOP_RATIO` is clamped to `(0, 1]` because `0` blocks every non-owner and
`>1` silently raises the ceiling.

Rejected: warning-only behaviour on a `None` handle (this is exactly the C-003 defect).

## D-005 — Deletion is schema-driven and additive

`delete_all_user_data` now derives its table list from the live schema instead of a hand-written
list, and a test fails when a new user-associated table appears without a deletion decision. This
is the only way to keep `/data delete` honest as the schema grows.

What is deliberately *not* deleted, and is disclosed to the user:
`warnings` and `moderation records` (server safety evidence owned by the guild, not the member)
and aggregated `user_xp` only when the guild keeps leaderboards — the current implementation
deletes XP as well, and the reply text states exactly what was removed.

## D-006 — `opt_out` is enforced in SQL, not only in Python callers

`/data delete` racing an in-flight reply used to re-insert rows. Each write path now carries the
opt-out predicate inside the statement, so a concurrent writer cannot resurrect a deleted member.
Python-level checks remain as a fast path and for user-facing messaging.

## D-007 — Natural-language actions share the slash-command authorization primitive

The NL router is a second front end, not a second permission model. Every destructive or
history-reading NL action now calls the same guard as its slash equivalent
(`can_moderate_member`, `can_read_history`, `is_mistress`). This is enforced by an explicit policy
inventory plus a test that fails when a registered action has no policy.

Rejected: adding checks ad hoc per route (that is how the original bypasses appeared).

## D-008 — `AllowedMentions.none()` is the default for every outbound path

Model output, archive text, media titles and third-party metadata are untrusted. A global default
of "no pings" plus an explicit opt-in list at the few call sites that genuinely ping is safer than
auditing every `send()`.

## D-009 — Media memory is budgeted in bytes per job, not in "slides × size" comments

The comment in `bot.py` described "10 slides of 10 MB" while the code allowed 20 slides of 25 MB
across up to four concurrent jobs. The budget is now an explicit constant checked while slides are
accumulated, and the semaphore is shared by every download path.

## D-010 — Migrations become versioned; destructive "cleanup" stops running on every boot

`initialize()` used to run 19 `REPLACE` statements plus `DELETE ... WHERE LENGTH(summary) < 35`
on every start. That silently deleted legitimate short summaries. It moves behind
`PRAGMA user_version` with a one-time migration, and length-based deletion is removed entirely.

Rejected: keeping the cleanup but adding a backup step (still destroys data the user wrote).

## D-011 — Deno is pinned and verified, and the image is hardened

Deno must be 2.9+ for current `yt-dlp-ejs` challenges. The Dockerfile pinned 2.1.4 with correct
hashes, so the hash check was fine but the version was not. The version is raised and the hashes
are regenerated from the published `SHASUMS256.txt`; the image also drops `curl`/`unzip` after
use, runs read-only with a `tmpfs`, caps PIDs, and gains a healthcheck.

## D-012 — Historical git privacy is documented, not rewritten

Removing operator details from `HEAD` does not remove them from public history. Rewriting a
published branch would break every clone and tag and is outside the authorized scope. The posture
is documented in `SECURITY.md` so the owner can decide between making the repository private and
rebuilding history.

## D-013 — Audio success requires evidence of transmitted bytes

`is_playing()` returning true is not proof of audio. The DAVE gate refuses playback when the
session cannot encrypt for a non-zero protocol version, the audio monitor counts decoded bytes,
and a zero-byte stream is reported as a failure instead of a success toast. Live DAVE behaviour
still requires a real voice session and is documented in `docs/LIVE_VERIFICATION.md`.

## D-014 — Test isolation is enforced, not assumed

Every test runs with credentials scrubbed and a temp database. An autouse fixture blocks unexpected
outbound sockets so a regression cannot quietly reach Discord or Gemini from CI.
