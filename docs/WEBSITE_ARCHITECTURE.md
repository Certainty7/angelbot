# Website architecture

The Angel website is a static site. It runs no server, holds no database and calls no API at
request time. Everything it publishes is produced at build time from this repository, so the
published facts and the bot source cannot drift apart without the build failing.

Pipeline:

```
bot source (cogs/, bot.py, angel/client.py)
        │  tools/website-data-generator/generate.py   (AST, standard library only)
        ▼
website/src/data/commands.json      website/src/data/invite.json
        │  Astro build
        ▼
website/dist  →  Cloudflare Pages  →  angel.aetherisnode.cloud
```

## Command discovery

Discovery is AST-based, not textual. A `grep -r` over the tree counts decorators: it matches the
decorator text in comments and docstrings, and it cannot tell a command that reaches the command
tree from one whose cog is never loaded. The generator therefore parses the modules the bot
actually loads and refuses to emit anything otherwise:

- `bot.py` — the eagerly installed cogs (`from cogs import X` + `X.install(bot)`), read as an AST.
- `angel/client.py` — the lazily loaded extension (`load_extension("cogs.music")`).
- A decorated command in a module in neither set is a hard error, not a silent omission.
- Duplicate command names are a hard error: Discord rejects the second registration.

Per command the generator records the registered name, the description Discord receives
(`description_discord`) and the Arabic the site publishes (`description_ar`: the editorial
`data/descriptions_ar.json` entry when there is one, else the decorator literal, which is the only
source for the 3 context menus), the category, the options (name, type, description, required flag,
choices), the Discord permission the command carries (`app_commands.default_permissions` plus the
runtime `has_perm_or_mistress` gate), and whether the handler refuses everyone but the owner (an
`if not is_mistress(...)` before any work — including one disjunct of an `or`).

## Counts (verified 2026-11-14)

| Measure | Value |
|---|---|
| Commands registered when music is enabled | 68 |
| Slash commands | 65 |
| Message context menus | 3 |
| Eager tree at startup | 64 (61 slash + 3 context menus) |
| Music commands, loaded from `setup_hook` | 4 |

`64` is the startup tree and `68` is the full surface; both are true and neither is a typo. Source
files scanned: 14 (`cogs/*.py`), 13 categories.

The generator's output is compared against `tests/website/fixtures/runtime_census.json`, which was
captured by importing every cog's `install()` against a stub command tree on the production host:
that is the object Discord receives, not an interpretation of the source. Any disagreement between
the AST result and the runtime census fails the test.

## Invite and permissions

`tools/website-data-generator/data/invite.json` lists every permission the bot itself needs, each
with the code path that requires it. The mask is computed from that list, never copied from an old
invite link, and the generator refuses to run if `administrator` ever appears in it.

`administrator` and `manage_guild` do appear in the source, but only as command gates
(`app_commands.default_permissions`): Discord checks those against the member who runs the command,
not against the bot. Requesting them at invite time would grant the bot rights no code path uses.

The application id (`1559932443102941284`) was read from `GET /oauth2/applications/@me` with the
live bot token on 2026-11-14, and the application reports `bot_public: true` and
`require_code_grant: false`, so the invite link works for anyone.

## Reproducibility

`generate.py --check` re-generates the data in memory and fails when the committed files differ, so
a bot change that alters the command surface cannot ship without a matching data change. The CI job
`website-data` runs the generator check and the catalogue tests on every push and pull request. It
needs no dependencies, no token and no network.

## Failure modes to keep in mind

- A new cog that is written but never installed makes the generator fail on purpose. Fix `bot.py`,
  not the generator.
- Moving a command between modules changes its category. Categories are a property of the module.
- `docs/COMMANDS.md` and the README are hand-maintained prose. The generated JSON is the artefact the
  website reads; when a count changes, the generator output is the source of truth.
