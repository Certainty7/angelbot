# Static analysis — bot source

Date: 2026-11-14. Scope: `angel/`, `cogs/`, `bot.py`, `tools/` at `master`. The website's own analysis
is added when `website/` contains code; this file covers the bot, which is the part with a live
deployment.

Tools and versions used, all run locally in a throwaway venv (`uv venv`, no global install):

| Tool | Command |
|---|---|
| bandit | `bandit -r angel cogs bot.py tools -x '*/__pycache__/*' -f json` |
| ruff | `ruff check angel cogs bot.py tools --select E9,F63,F7,F82,S` |
| gitleaks | `gitleaks detect --source . --log-opts=--all` → **0 findings** |

`semgrep`, `trivy` and `osv-scanner` are not installed on this host; the dependency surface was covered
with the OSV API directly (`DEPENDENCIES.md`) and secrets with gitleaks. This is recorded rather than
implied.

## Totals

- bandit: **316 issues — 5 HIGH, 19 MEDIUM, 292 LOW**, 304 high-confidence, across 28 files.
- ruff: **313 findings**, dominated by `S101 assert` (172) and `S110 try-except-pass` (85), which are
  style-level in a bot whose test paths use asserts.

High counts are not findings. Each HIGH and MEDIUM site was opened and classified by hand.

**All five HIGH are the same rule, B324 weak MD5, and none is a security primitive:**

| Site | What the hash is for | Verdict |
|---|---|---|
| `angel/media.py:772` | deduplicating image bytes inside one process | non-exploitable |
| `angel/media.py:799` | same dedupe path, second call site | non-exploitable |
| `angel/media.py:944` | content cache key | non-exploitable |
| `tools/selftest.py:593` | comparing fixture bytes in the deploy gate | non-exploitable |
| `tools/selftest.py:612` | same comparison, second call site | non-exploitable |

Fix when any of those files is next touched: `hashlib.md5(b, usedforsecurity=False)`.

**MEDIUM by rule: B608 ×5, B104 ×1, B108 ×6, B310 ×7.** The meaningful ones:

> **Historical record.** `tools/build_member_files.py` and `tools/build_member_files_legacy.py`
> were deleted on 2026-11-15 with the member-file route. Their rows below are retained as the
> record of the scan that was actually run, not as a description of the current tree.

| Site | Rule | Verdict | Reasoning |
|---|---|---|---|
| `bot.py:682` | S608 / B608 SQL built by string | **false positive** | `tbl` iterates a literal tuple of table names, filtered by membership in `sqlite_master` first. No user input reaches the string. |
| `angel/database.py:1309` | S608 | **false positive** | `placeholders` is `",".join("?" for _ in clean)`; every value is bound. The rule sees an f-string and stops there. |
| `angel/database.py:1342` | S608 | **false positive** | clauses are literal `(fact_key LIKE ? OR fact_value LIKE ?)`, parameters appended to `params`. |
| `tools/build_member_files.py:121` | S608 | **false positive** | the interpolated fragment is a ternary between two literal SQL strings. |
| `tools/build_member_files_legacy.py:145` | S608 | **false positive** | same shape as above; legacy script, not in the deploy path. |
| `angel/images.py:166` | B104 bind to all interfaces | **false positive** | the flagged literal is `"0.0.0.0"` inside an **SSRF blocklist**, i.e. the opposite of the risk the rule describes. |
| `angel/media.py:210,1464–1469` | B108 hardcoded `/tmp` | **true positive, low** | transcode scratch files under `/tmp/angelbot_social`, named by pid+rand. Single-tenant host, no untrusted local users. Correct future fix: `tempfile.mkdtemp()`. |
| `tools/metrics.py:179` | B108 | **low** | operator-run metrics script, not reachable from Discord input. |
| `tools/*.py` (7 sites) | B310 `urlopen` scheme | **low** | operator-run scripts (`backfill_history`, `build_member_files`, `evolve_persona`, `fetch_all_history`, `learn_from_log`) — none is reachable from member input. |

## What the scan confirms positively

- An SSRF guard exists and blocks loopback, private, link-local, multicast, IPv4-mapped and
  `169.254.169.254`, with the scheme restricted to http/https (`angel/images.py`).
- All SQL that touches member data is parameterised; the only interpolations are structural literals.
- No `eval`, no `exec`, no `pickle.loads` on untrusted input, no `shell=True` in a subprocess call, and
  no `subprocess` built from member-controlled strings.
- `except: pass` blocks are concentrated in best-effort cleanup, not in permission decisions.

## Residual

`assert` used for internal invariants (172 sites) disappears under `python -O`. The service does not run
with `-O` (`deploy/angelbot.service` has no `PYTHONOPTIMIZE`), so this is noted, not acted on.

## Statement

At the time of this scan, **no exploitable SQL injection, command injection, path traversal, or
unauthenticated remote-code path was identified in the scanned bot source**, and no secret was found in
the full commit history. This is bounded by the tools, versions and commands above — it is not a claim
of absolute immunity.
