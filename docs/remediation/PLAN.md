# Remediation program — angelbot audit

Status: **in progress**. Ticket list: [`TICKETS.md`](TICKETS.md). Findings, evidence and fix
sketches: [`Certainty7/angelbot-audit`](https://github.com/Certainty7/angelbot-audit).

## Goal

Close all 20 findings from the audit of `eb09d2e` — 14 must-fix, 6 should-fix — while keeping
the bot's observable behaviour unchanged except where a finding requires otherwise.

## Non-goals

- No rewrite and no module reshuffle: the audit found defects, not a broken architecture.
- No new features, no dependency major bumps, no formatting sweep.
- No change to the persona or to member-facing wording.

## Invariants

1. `pytest` stays green: baseline at `eb09d2e` was **225 passed + 322 subtests**.
2. Every fix ships a regression test that **fails on the parent commit** and passes with the fix.
   A test that passes both ways is not evidence.
3. A guarded resource is never double-counted: when a fetch is rejected, its byte budget is released.
4. User-visible behaviour changes only when the finding names it (e.g. the wrong language on a
   settings card); those changes are stated in the PR body.

## Order

Security and data-loss first, then resource and correctness, then should-fix. `11` depends on `06`,
so `06` lands first even though it is lower on the list. Each PR is one finding unless two touch
the same seam and splitting them would leave the tree red between merges.

## Gate for every PR

1. Failing test committed first (or in the same commit, visible in the diff).
2. Fix keeps the suite green; no unrelated file touched.
3. Self-review against the audit's own "Done when" line, quoted in the PR body.
4. Conventional commit title, PR body lists the test evidence and the audit issue number.

## Definition of done for the program

- All 20 tickets `done` in `TICKETS.md`.
- `master` green: full suite plus the repo's self-test.
- Each finding's "Done when" line satisfied and quoted in its merged PR.
- A short closing report: what changed, what was deliberately left alone, remaining risk.
