# AGENTS.md — engineering context for future agents

Read this before changing code. It is written for a session that starts with no history.

## What this project is

Angel is a single-process Discord bot (Python 3.12) with an Astro static website. One SQLite file
is the only durable store. There is no backend service, no queue, and no external state beyond the
Discord gateway, Gemini and the media CDNs.

## Layout and ownership

| Path | Owns |
|---|---|
| `bot.py` | entry point, event handlers, CLI utilities (`--checkpoint-db`, `--verify-db`, `--cleanup`) |
| `angel/config.py` | environment, `.env` loading, permissions, `safe_reply`, timezone |
| `angel/client.py` | the `discord.Client` subclass: caches, scheduler, shutdown |
| `angel/database.py` | the entire schema, migrations, every query |
| `angel/brain.py` | Gemini text/vision client, model fallback, budget reservation |
| `angel/cost.py` | USD prices, daily ceiling, `STOP_RATIO` |
| `angel/nl_router.py` | the natural-language front end; reuses the slash-command guards |
| `angel/authz.py` | the authorization inventory for every registered command |
| `angel/media.py` | social-media extraction, FFmpeg, temp files, storage cleanup |
| `angel/audio_source.py` | yt-dlp resolution, safe headers, SoundCloud fallback |
| `angel/voice_engine.py` | queue, DAVE gate, decoded-byte monitor |
| `angel/net.py` | SSRF-safe HTTP: resolver, redirects, bounded reads, semaphores |
| `angel/summarize.py` | channel transcript → prompt, with opt-out + injection defence |
| `cogs/*` | command surfaces; no business logic that belongs in `angel/` |
| `tools/` | operator and CI tools; they may import `angel`, never the reverse |
| `website/` | static Astro site, generated data under `src/data/` |
| `tests/` | regression suite; `tests/conftest.py` isolates every run |

## Execution paths worth knowing

1. **Gateway message:** `bot.on_message` → opt-out check → archive write → guard → music shortcut →
   social-media fixer → XP → natural-language router → AI reply.
2. **Slash command:** discord.py `app_commands` → `has_perm_or_mistress` → body-level hierarchy
   check → database → reply.
3. **Destructive action, any surface:** slash, natural language, custom trigger or a model
   `[EXEC: ...]` all queue through `angel/confirmations.py` → the same human types `تأكيد` in the
   same channel within 60 seconds → permissions and the target are re-resolved → execute.
4. **Startup:** `angel.config` (env, ffmpeg, timezone) → `bot.py` builds the client → cogs register
   at import → `setup_hook` initialises the database, runs migrations, loads caches, starts tasks.

## Invariants — do not break these

- **Owner id is configuration.** Never hardcode it. It must be ASCII digits and greater than zero.
- **`ANGEL_DB_PATH` is the only database path.** Tools must resolve it through `angel.config`.
- **Every write that stores a member checks opt-out inside SQL.** A Python-level check alone races
  `/data delete`.
- **Every registered command has a policy in `angel/authz.py`.** `tests/test_command_policy.py`
  fails otherwise.
- **Irreversible actions require the confirmation gate**, bound to guild + author + channel:
  message purge, ban, warning erasure. Reversible commands (`/timeout`, `/kick`, `/lock`,
  `/slowmode`, roles, `/warn`, `/unban`) are an approved exception documented in
  `docs/remediation/14-confirmation-scope.md`; do not add or remove a surface without updating it.
- **Untrusted text is data.** Sanitise before a prompt, and pass `untrusted=True` to `safe_reply`
  when replying with model output, transcripts, titles or archive quotes.
- **No shell.** Subprocesses are argv arrays; children are killed and reaped on timeout and
  cancellation.
- **Close the archive over `allowed_channels`.** `search_archive` refuses an unfiltered call.
- **Deletion is schema-driven.** A new user-bearing table must be added to
  `BotDatabase.USER_DATA_TABLES` or `USER_DATA_EXEMPT`, with a reason.
- **`initialize()` may create, never rewrite.** Data changes belong in `_run_migrations()`, guarded
  by `PRAGMA user_version`.

## Database rules

- Add a table with `CREATE TABLE IF NOT EXISTS` inside `initialize()`.
- Add a column with the existing tolerant `ALTER TABLE ... try/except` pattern.
- Change data with a new `user_version` step; never re-run a destructive statement on every boot.
- Update `docs/DATA_MODEL.md`; `tests/test_docs_sync.py` fails when a table is undocumented.
- FTS changes require dropping the virtual table + triggers and setting `_fts_rebuild_needed`.

## Testing

```bash
export ANGEL_OWNER_ID=42            # fixture id; conftest sets it if absent
export ANGEL_DB_PATH="$(mktemp -u).db"
python -m pytest -q                 # whole suite
python tools/selftest.py            # startup gate (50 checks)
python tools/security_probe.py      # adversarial probe
python tools/recall_probe.py        # Arabic recall
python tools/gate_checks.py         # static gates
python -m compileall -q bot.py angel cogs tools tests
```

`tests/conftest.py` forces a temp database, scrubs provider credentials and blocks outbound
sockets. A test that needs the network must set `ANGEL_TESTS_ALLOW_NETWORK=1` and justify it.

## Documentation requirements

- Update `docs/COMMANDS.md` when a command is added or renamed.
- Update `docs/DATA_MODEL.md` when the schema changes.
- Update `docs/recovery/LEDGER.md` and `STATE.md` for recovery work.
- Record a non-obvious decision in `docs/recovery/DECISIONS.md` (or `docs/DECISIONS.md` for
  product decisions) with the alternatives that were rejected.

## Deployment restrictions

- `master` is wired to the production website workflow. Do recovery work on a branch and open a
  pull request; do not push to `master` to "make it live".
- Do not deploy the bot or the website from an agent session.
- Live-only checks are listed in `docs/LIVE_VERIFICATION.md`; never mark them as passed.

## How to fix a defect here

1. Reproduce it with the smallest fake that exercises the real state transition (see
   `tests/test_voice_and_guard.py` for the pattern).
2. Write the failing test first; confirm it fails for the stated reason.
3. Fix the root cause once, in the shared helper, not at each call site.
4. Re-run the full suite plus the gates above.
5. Update the ledger, known issues and the changelog.
