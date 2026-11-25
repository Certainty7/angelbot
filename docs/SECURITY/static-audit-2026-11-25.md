# Static audit — 2026-11-25

Scope: the whole tree at `b581c11` plus the full commit history of every branch and tag.
Trigger: a leak of the operator's deploy address and SSH key path had been found inside the
tracked plan files, so the question was whether the same class of leak existed anywhere else.

## What was run

| Check | Command | Result |
|---|---|---|
| Secrets in history (every blob, keyed by object id) | `python3 scripts/scan_secrets.py` | `no secrets found` |
| Deploy identifiers in docs | `pytest tests/test_no_infra_in_docs.py` | 2 passed |
| Address / key / home path anywhere in history | `git log --all -S…`, `git grep` over all commits | 0 hits |
| Static analysis | `bandit -r angel/ tools/ scripts/ -ll` | 12 medium, all triaged below |
| Python dependencies | `pip-audit -r requirements.txt` | no known vulnerabilities |
| Website dependencies | `npm audit --omit=dev` | 0 of any severity |
| Personal data in tracked text | email / phone / public-IP sweep | only documentation ranges and test fixtures |

A fresh clone of the published repository was scanned separately, not just the working copy:
0 commits matching the address, 0 matching the key name, 0 blobs containing the home path.

## Findings and triage

**`hashlib.md5(...)` without `usedforsecurity=False`** (5 call sites: three in `angel/media.py`,
two in `tools/selftest.py`). Fixed. The digest is a content fingerprint for de-duplicating
downloads and for comparing test output, so the algorithm is not a security property; the flag
states that where a reader looks. `tests/test_crypto_hygiene.py` now fails if a bare call returns.

**Hardcoded `/tmp` path** in `tools/metrics.py`. Fixed: `tempfile.gettempdir()`.

**B608 — SQL built with an f-string** (8 sites in `angel/database.py`). Not a defect. Each site
interpolates a table or column name taken from a module-level allowlist, and every value is a
bound parameter. The rule cannot see that distinction; the code is unchanged. If these ever start
taking a name from outside the module, the rule will not save us — the allowlist is the control,
not the scanner.

**B310 — `urllib.request.urlopen`** (4 developer tools). Not a defect. Each URL is built from an
`https` constant or the Google API base; no user input reaches the scheme. These tools are run by
the operator, never by the bot.

## Deliberately not done

Bandit is not wired into CI. Twelve triaged findings would train the next reader to ignore the
output, and the checks that do run (secret scan, infra-doc gate, release consistency) are the ones
with a demonstrated failure. Reconsider if the allowlist in `angel/database.py` is ever replaced
by a query builder that takes names from a request.
