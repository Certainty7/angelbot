# RECOVERY STATE — AngelBot stabilization

Durable continuation point. Read this first in a new session, then `LEDGER.md` and `DECISIONS.md`.

## Current phase

Checkpoint 5 — documentation, independent review, final validation and GitHub delivery.

## Repository anchors

| Item | Value |
|---|---|
| Local path | `C:\OpenCode\Angel Bot` |
| Remote | `https://github.com/Certainty7/angelbot.git` (`origin`) |
| Baseline commit | `51090aa66c60f4fba94ce13cc5066f9d809672c3` |
| Remote `master` at start | `51090aa` (identical to local `HEAD`) |
| Working branch | `recovery/stabilization` |
| Recovery tag | `recovery/pre-stabilization-2026-11-20` |
| Recovery area | `%TEMP%\opencode\angelbot-recovery` |

The working tree arrived carrying the audio hotfix (`angel/config.py`, `angel/audio_source.py`,
`angel/voice_engine.py`, `bot.py`, `cogs/music.py` + `tests/test_audio_hardening.py`). It is now
commit 1 of the branch (unchanged), so later changes to those files are reviewable as a diff.

## Baseline measurements (before changes)

| Command | Result |
|---|---|
| `python -m pytest -q` | 63 passed, 322 subtests passed |
| `python --version` | 3.13.14 (project targets 3.12) |
| `node --version` / `npm --version` | v26.13.0 / 11.20.0 |
| `ffmpeg` on PATH | absent (imageio_ffmpeg fallback used) |
| `deno`, `docker`, `sqlite3` CLI, `gitleaks`, `semgrep` | absent |

## Completed

- Phase Zero preflight, recovery tag, `--all` bundle, working-tree snapshot, diff + untracked
  inventory.
- Local/remote reconciliation: identical at `51090aa`; the two remote Dependabot branches are
  superseded by the pinned versions in `requirements.txt`.
- Full audit (35 confirmed + 9 potential) extracted into `LEDGER.md`, each item re-checked against
  the tree.
- Audio patch compared hunk by hunk with the current source and committed unchanged.
- Checkpoints 1–4 implemented: bootstrap/deploy, database/migrations, security/authorization,
  privacy/deletion, audio/media/resources, website/CI.
- Documentation: `AGENTS.md`, `KNOWN_ISSUES.md`, `docs/DATA_MODEL.md`,
  `docs/LIVE_VERIFICATION.md`, `SECURITY.md` data-flow matrix, bilingual changelog, README.
- New regression suite: 182 tests plus 322 subtests (final run).

## Verification ledger (last run)

| Command | Result |
|---|---|
| `python -m compileall -q bot.py angel cogs tools tests` | 0 |
| `python -m pytest -q` | 182 passed, 322 subtests passed (exits cleanly) |
| `python tools/selftest.py` | 50/50 |
| `python tools/security_probe.py` | PASS |
| `python tools/recall_probe.py` | 10/10 |
| secret scan | no real credential; one documented placeholder |
| `npx playwright test` (website) | 67/67 |
| GitHub Actions on the PR | `checks`, `website-build`, `website-data`, `catalogue`, `build/typecheck/e2e` PASS |

## Delivery

| Item | Value |
|---|---|
| Pushed branch | `recovery/stabilization` |
| Verified green tip | `dfe227b` (`checks`, `website-build`, `website-data`, `catalogue`, `build/typecheck/e2e` all pass) |
| Pull request | https://github.com/Certainty7/angelbot/pull/9 (base `master`, open, **not merged**) |
| `master` | unchanged at `51090aa`; merging would trigger the Cloudflare Pages production build |

After `dfe227b` the branch only receives documentation commits (this state update); the code and
tests that CI verified are unchanged.

## Remaining work

1. ~~Final full-suite run~~ — done: 182 tests + 322 subtests, suite exits cleanly.
2. ~~Independent adversarial review~~ — done; the findings it produced are N-006..N-010 in
   `LEDGER.md` and are fixed in commit `3fe74a4`.
3. ~~Push and open the pull request~~ — done: PR #9, branch `recovery/stabilization`.
4. Owner decision: merge PR #9 (this triggers the Cloudflare Pages production build) and restart
   the bot service, then run `docs/LIVE_VERIFICATION.md` §1–§4.

## Resume instructions

```powershell
cd "C:\OpenCode\Angel Bot"
git switch recovery/stabilization
Get-Content docs/recovery/STATE.md, docs/recovery/LEDGER.md, docs/recovery/DECISIONS.md
$env:ANGEL_OWNER_ID="42"; $env:ANGEL_AUTO_INSTALL="0"
$env:ANGEL_DB_PATH="$env:TEMP\angel-verify.db"
python -m pytest -q
```

## Open blockers

Local: none. External: live Discord voice/DAVE, YouTube extraction, a Docker build, real systemd
and Cloudflare headers; tracked in `docs/LIVE_VERIFICATION.md` and `KNOWN_ISSUES.md`.
