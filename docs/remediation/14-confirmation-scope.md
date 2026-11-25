# Finding 14 — confirmation scope (decision record)

**Status:** decided and implemented.
**Owner decision (2026-11-25):** narrow the promise, document the exception, never leave it implicit.

## The invariant

An **irreversible** destructive action runs only after the same person types `تأكيد` in the same
channel, within 60 seconds, and only if the permission still holds at that moment.

Irreversible means "there is no undo in Discord":

- `PURGE` — messages are gone, including other people's.
- `BAN` — membership and (optionally) up to seven days of messages.
- `CLEAR_WARNINGS` — the moderation record is erased.

## Gated surfaces

Every route to those three actions is gated, not just the model's:

- slash commands: `/purge`, `/ban`, `/clear_warnings`
- natural language: «امسحي ٥٠ رسالة»، «احظري فلان»، «امسحي إنذارات فلان»
- custom triggers: any trigger whose action is `ban` or `purge`
- model-proposed `[EXEC: ...]` actions (already gated before this finding)

## Approved exceptions (documented, not implicit)

Reversible single-target commands stay immediate:

`/timeout`, `/untimeout`, `/kick`, `/lock`, `/unlock`, `/slowmode`, `/warn`, `/unban`, role add and
remove, announcement edits.

Reason: each has a direct undo in the same interface, the blast radius is one member or one channel
setting, and a confirmation step there trains people to confirm reflexively — which weakens the gate
where it matters. `AGENTS.md` and the README list this exception next to the rule so a future change
cannot quietly widen or narrow it.

## Binding and re-checks

A pending action is keyed by `(guild_id, author_id)` and stores the requesting channel, the summary
shown to the human, the timestamp and a closure that performs the action. On `تأكيد`:

1. expiry is evaluated first — past 60 seconds the entry is dropped and nothing runs;
2. a confirmation typed in another channel **cancels** the action instead of confirming it;
3. a cancel word (`الغاء`, `إلغاء`, `كنسل`, `cancel`) clears it;
4. any other word leaves it pending until the minute runs out;
5. the closure re-reads the confirmer's live permissions, re-resolves the target by id, and re-runs
   the hierarchy guard — a moderator who lost the role inside the window cannot execute;
6. the entry is popped before the action runs, so a double `تأكيد` cannot double-ban.

## Where it lives

`angel/confirmations.py` is the only implementation: `queue_confirmation`, `queue_slash_confirmation`,
`take_confirmation`, `CONFIRM_TTL`, `CONFIRM_WORDS`, `CANCEL_WORDS`. Slash surfaces acknowledge the
interaction first (finding 13) and then queue; natural-language and trigger surfaces queue instead
of mutating; the model path keeps its own entry shape and shares the same take/verdict logic.

## Evidence

- `tests/test_confirmation_scope.py`: 13 tests + 2 subtests across slash, natural language, trigger,
  lifecycle (expiry, wrong channel, cancel, lost permission, wrong confirmer) and the reversible
  exception.
- Red proof: restoring the pre-fix `cogs/admin.py` and `angel/nl_router.py` makes **12 of them fail**
  (immediate mutation, no queue); with the gate all pass.
- Full suite: **304 passed + 336 subtests**; `tools/selftest.py`: **50/50**.
