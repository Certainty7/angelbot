# Remediation tickets — audit of `eb09d2e`

Source: `Certainty7/angelbot-audit`. One ticket per finding, in the audit's own numbering.
Evidence and fix sketches live there; this file tracks order and status only.

## Status key

`todo` → `in review` (PR open) → `done` (merged, suite green).

## Must-fix

### 01 · 1. Direct HTTP calls can reach private and metadata addresses

- **Status:** in review — PR #12
- **Done when:** loopback literals and redirects are refused before the local server records a hit, including direct POST paths.

### 02 · 2. A small SnapSave response can freeze the whole bot

- **Status:** todo
- **Done when:** the 20k/20k fixture fails closed or completes well under one second, and oversized fields are rejected before decoding.

### 03 · 3. Tiny compressed images can exhaust memory

- **Status:** todo
- **Done when:** a four-way high-pixel fixture stays within a numeric memory assertion and oversized dimensions are rejected before allocation.

### 04 · 4. Cancellation can leave a partial database transaction for another request to commit

- **Status:** todo
- **Done when:** cancellation propagates, no transaction remains open, all user data is unchanged, and a later write commits none of the cancelled operation.

### 05 · 5. `/memory forget` can report success while the text remains searchable

- **Status:** todo
- **Done when:** a broken archive delete raises/returns failure, no success receipt is sent, and a later reindex cannot expose the token.

### 06 · 6. DM and guild conversation memory leak across contexts

- **Status:** todo
- **Done when:** guild-A and DM sentinels are absent from guild-B prompts, and `/memory view`, `/memory clear` and `/memory forget` have documented current-context behavior.

### 07 · 7. Natural-language snipe bypasses the staff-only slash permission

- **Status:** todo
- **Done when:** an unprivileged member receives no cache content and a staff member with effective `manage_messages` still receives it.

### 08 · 8. Natural-language owner tools bypass `ENABLE_SOVEREIGN_TOOLS`

- **Status:** todo
- **Done when:** both NL branches refuse while the flag is false and still work for the owner when it is true.

### 09 · 9. PR-Agent runs mutable third-party code with write credentials

- **Status:** todo
- **Done when:** CI rejects mutable action refs and rolling runtime tags, and the enabled workflow uses the approved immutable artifacts.

### 10 · 10. Archive work is unbounded, unobserved and cancelled on shutdown

- **Status:** todo
- **Done when:** 1,000 blocked messages create no more than 256 queued/active jobs and no waiting producers, rejected message IDs are logged, failures are observed, and a graceful shutdown persists accepted work within the drain window.

### 11 · 11. Conversation state is saved before Discord confirms delivery

- **Status:** todo
- **Done when:** a failed or partial multi-chunk/media delivery creates no rolling/ambient/forwarded reply state, while one complete delivery stores it exactly once.

### 12 · 12. Killing yt-dlp leaves its child processes alive

- **Status:** todo
- **Done when:** parent and child both exit after timeout/cancellation on Windows and Linux CI.

### 13 · 13. Slow moderation actions can succeed after the interaction deadline

- **Status:** todo
- **Done when:** a delayed mutation is deferred first and its followup/modlog still run after the delay.

### 14 · 14. Destructive action surfaces do not share the required confirmation gate

- **Status:** todo
- **Done when:** each destructive surface either queues the same typed, expiring, channel-bound confirmation or has an approved documented exception.

## Should-fix

### 15 · 15. FFmpeg may fetch private URLs hidden inside an HLS manifest

- **Status:** todo
- **Done when:** an end-to-end supported-source test cannot make FFmpeg request a private segment/key URL.

### 16 · 16. Alternate moderation paths skip hierarchy or target-channel checks

- **Status:** todo
- **Done when:** lower-ranked warning targets and denied target channels are refused without mutation, while allowed cases still work.

### 17 · 17. A confirmation can execute against a different target

- **Status:** todo
- **Done when:** each target class keeps its original identity and a deleted/replaced target causes refusal.

### 18 · 18. Secondary send paths bypass mention and secret filtering

- **Status:** todo
- **Done when:** fake foreign mentions and secret shapes are absent, while the intended autonomy target can still be mentioned.

### 19 · 19. Media budgets and type checks are not enforced end to end

- **Status:** todo
- **Done when:** each focused test enforces its numeric/type boundary and the full suite still passes.

### 20 · 20. Operator tools and backfills can produce false or incomplete evidence

- **Status:** todo
- **Done when:** configured-path tools read the sentinel DB, backfills reach the requested number of real rows, distinct snowflakes survive, and 366-day-old rows are pruned.

