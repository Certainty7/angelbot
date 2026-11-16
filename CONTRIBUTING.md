# Contributing

Contributions are by invitation. If you have access, these are the rules the project runs on.

## Before you open a pull request

```bash
python -m compileall -q bot.py angel cogs tools
python tools/selftest.py
```

The gate must end with `N/N checks passed`. Paste that line in the pull request. If a check fails,
fix the code, not the check.

## What a change should look like

- One topic per pull request. A bug fix and a refactor in the same branch is two branches.
- Match the surrounding style. The codebase uses two-space indentation and short module docstrings.
- New behaviour needs a check in `tools/selftest.py` or a case in `tools/gate_checks.py`. The gate
  is the contract.
- Commands are registered through `install(bot)` from a cog in `cogs/`. The command census in the
  gate counts them, so update the expected counts in the same commit.
- Do not add a dependency, a service or a network call the bot does not already need.
- Never commit `.env`, `cookies.txt`, a database file or a token. `.gitignore` covers the common
  cases, not your judgement.

## Commits

Conventional Commits, imperative subject, 72 characters or fewer:

```
fix(archive): scope recall to readable channels
feat(music): add a queue command
docs: describe the deploy gate
```

## Reporting a bug

Open an issue with the command or message that triggered it, the expected result, the actual
result, and the relevant journal lines. Remove IDs, tokens and message content you do not want
published.

Security issues do not go in the issue tracker. See [SECURITY.md](SECURITY.md).
