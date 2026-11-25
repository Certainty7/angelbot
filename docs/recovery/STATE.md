# RECOVERY STATE — AngelBot stabilization (archive)

This file recorded a continuation point for the stabilization pass of 2026-11-20. That pass is
closed: everything it opened was merged, released and verified. The numbers below are kept as the
record of that pass, not as the current state — for those, read `CHANGELOG.md` at the tag and
`docs/LIVE_VERIFICATION.md`.

## Status

Closed. The stabilization branch merged into `master`; releases `1.0.1` through `1.1.2` shipped from
it. `docs/SECURITY/static-audit-2026-11-25.md` carries the current audit, and `CHANGELOG.md` carries
the counts measured at each tag.

## What the pass covered

- Phase Zero preflight: recovery tag, `--all` bundle, working-tree snapshot, diff and untracked
  inventory.
- Local/remote reconciliation, then the audio hotfix committed unchanged so later edits stayed
  reviewable as a diff.
- Checkpoints 1–4: bootstrap and deploy, database and migrations, security and authorization,
  privacy and deletion, audio/media/resources, website and CI.
- Documentation: `AGENTS.md`, `KNOWN_ISSUES.md`, `docs/DATA_MODEL.md`,
  `docs/LIVE_VERIFICATION.md`, `SECURITY.md` data-flow matrix, bilingual changelog, both READMEs.
- The review round on the pull request: the full inventory re-verified against the tree, with every
  finding fixed or justified and covered by a regression test.

## Baseline measurements (before the pass)

| Command | Result |
|---|---|
| `python -m pytest -q` | 63 passed, 322 subtests passed |
| `python --version` | 3.13.14 (project targets 3.12) |
| `node --version` / `npm --version` | v26.13.0 / 11.20.0 |
| `ffmpeg` on PATH | absent (imageio_ffmpeg fallback used) |
| `deno`, `docker`, `sqlite3` CLI, `gitleaks`, `semgrep` | absent |

## Verification at the end of the pass

| Command | Result |
|---|---|
| `python -m compileall -q bot.py angel cogs tools tests` | 0 |
| `python -m pytest -q` | 223 passed, 322 subtests passed |
| `python tools/selftest.py` | 50/50 |
| `python tools/security_probe.py` | PASS |
| `python tools/recall_probe.py` | 10/10 |
| `npx playwright test` (website) | 67/67 |

Superseded: current counts live in `CHANGELOG.md` under the newest tag, because a number written
into a document without a date becomes a claim about the future.

## Checking out an old state

```bash
git fetch --all --tags
git log --oneline --decorate -n 20
git show <tag>:docs/recovery/STATE.md
```

Set `ANGEL_DB_PATH` to a scratch file and run `python -m pytest -q`. The bot needs nothing else to
run its offline gates.

## Open blockers

None in the repository. External surfaces that no offline gate can prove — live Discord voice and
DAVE, YouTube extraction, a Docker build, real systemd behaviour, response headers on the deployed
host — stay listed in `docs/LIVE_VERIFICATION.md` and `KNOWN_ISSUES.md`.
