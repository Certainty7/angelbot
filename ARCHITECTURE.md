# Angel bot: architecture

Package + cogs layout. `bot.py` is the entry point only: it constructs the client, installs the
registry, registers the event handlers and runs. Every command lives in `cogs/`.

```
angelbot/
├── bot.py                  # entry point only: quota/db/brain singletons, bot = AngelDiscordBot(),
│                           # registry install, event handlers, __main__ (run + CLI utilities)
├── angel/
│   ├── config.py           # bootstrap, ffmpeg resolution, .env, constants, permissions
│   ├── net.py              # shared aiohttp session, bounded stream reader, CPU guards
│   ├── registry.py         # install(bot) once, get_bot() everywhere else
│   ├── client.py           # AngelDiscordBot: caches, conversation pipeline, background tasks
│   ├── nl_router.py        # natural-language router ("انجل اطردي فلان"), client as first arg
│   ├── persona.py          # persona, style modes, prompt builder, filters
│   ├── quota.py            # Gemini quota/latency tracker
│   ├── cost.py             # USD breaker + local-day accounting
│   ├── database.py         # BotDatabase: aiosqlite (WAL), memory/silence/flags tables
│   ├── media.py            # TikTok / Instagram / X / Reddit resolvers, storage cleaner
│   ├── audio_source.py     # yt-dlp resolve + smart ranking (SoundCloud, YouTube)
│   ├── voice_engine.py     # queue/playback (MusicEngine, GuildQueue), DAVE state
│   ├── images.py           # image & GIF fetch, watermark crop, tag sanitizer
│   ├── brain.py            # Gemini client: replies, GIF pools, fact extraction, ambient
│   ├── guard.py            # harem-only romance gate, silence map, refusal lines
│   ├── memory.py           # per-user facts, recall, member index
│   ├── autonomy.py         # self-initiated conversations (rate-limited, quiet hours)
│   ├── interactions.py     # _safe_interaction_reply / _defer shared by cogs
│   ├── text.py             # split_message
│   ├── ui.py               # persisted views (tickets, giveaway, control centre, art studio)
│   ├── dashboard.py        # build_server_pulse_embed(bot, guild)
│   ├── summarize.py        # analyze_channel_history_deep(bot, channel, requester, ...)
│   └── rules.py, scoring.py, triage.py, evolution.py, sendqueue.py, context_acl.py, downloader.py,
│       archive.py, output_filter.py, persona_notes.py
├── cogs/                   # the command surface: admin 17, community 11, memory_rules 6, owner 6,
│                           # flagship 6, ai_chat 4, context_menus 3, control 3, productivity 2,
│                           # fun_gif 2, media_tools 2, xp_profile 2 = 64 in the eager tree
│   └── music.py            # 4 more, loaded lazily from setup_hook behind MUSIC_ENABLED
├── tools/selftest.py       # offline gate (50 checks); run before every commit/restart
├── tools/gate_checks.py    # the checks selftest imports
├── tools/audit_map.py      # regenerates docs/AUDIT.md (never hand-edit it)
├── tools/symptoms.py       # mines the journal into an error-class table
├── deploy/angelbot.service # the unit: ExecStartPre runs the selftest, so a restart is gated
├── docs/                   # architecture, decisions, command reference, runbooks
├── tests/fixtures/         # gallery extraction fixtures
└── backups/, chat_history.db*  # git-ignored
```

## Command tree

No decorators live in `bot.py`. Each cog exposes

```python
def install(bot) -> None:
  for command in Cog(bot).get_app_commands():
    bot.tree.add_command(command)
```

and `bot.py` calls `install(bot)` at import time. That is deliberate: the tree must be complete
*before* `on_ready` syncs it, and the offline selftest must be able to count it without a gateway
connection. `cogs/music.py` is the exception: it is loaded from `setup_hook` behind `MUSIC_ENABLED`
so a broken voice stack can never stop the bot from starting.

Context menus cannot live in a Cog (`discord.py` raises "context menus cannot be defined inside a
class"), so `cogs/context_menus.py` keeps three module-level functions that `install(bot)` adds.

## Client access

One direction: `bot.py` → cogs/package, never the reverse (a cog importing `bot` is an import cycle).

- `angel/registry.py` holds the client for the package (`install(bot)` once, `get_bot()` everywhere);
  no module keeps a `bot = None` placeholder any more, and `tools/gate_checks.py::late-binding-free`
  fails the gate if one comes back.
- Shared helpers take the client explicitly: `build_server_pulse_embed(bot, guild)`,
  `analyze_channel_history_deep(bot, channel, requester, ...)`, and every router entry point
  (`tools/gate_checks.py::router-injection` asserts it).
- Views in `angel/ui.py` receive the client in their constructor; nothing reads a module global.

## Gates

1. `./venv/bin/python tools/selftest.py` → must print `50/50 checks passed` (the count grows with each
   added check; read the final line, never a remembered number).
2. The unit runs the same selftest as `ExecStartPre`, so a restart cannot replace the running bot with
   a tree that fails the gate.
3. `command-census` compares the per-cog decorator counts, the declared totals and
   `len(bot.tree.get_commands())`, so a command cannot disappear between bot.py and a cog without the
   gate failing.

## Known constraints

- `BASE_DIR` must always resolve to the project root (one level above the package): it drives
  `DB_PATH`, the cookies lookup and the audio staging paths.
- Romance rule: `config.ROMANTIC_GIF_ACTIONS` + `guard.romantic_allowed()` gate every path (`/gif`,
  natural-language affection, `[SEND_GIF]` from the model, `fetch_anime_gif_data`).
- Autonomy send limits live in `angel/autonomy.py` (env-overridable): 4/h, 30/day, quiet hours in the owner's timezone,
  20 min per channel, 6 h per member.
- GIF sourcing (verified from this host): Tenor (key invalid), Giphy (no key), Reddit (403),
  safebooru/danbooru (Cloudflare 403), waifu.pics (DNS dead) are unusable. The engine uses
  **nekos.best → purrbot → otakugifs** with the descriptive `config.GIF_USER_AGENT`, plus a
  `gif_pool` table it grows. For harem requests only results whose `anime_name` is in
  `config.YURI_ANIME_WHITELIST` are accepted.
- Music (2026-11-11): `/play /skip /queue /playlist`, public APIs only, kill switch
  `MUSIC_ENABLED=0`; the queue state is a pure dataclass. Provenance and what was withdrawn are
  recorded in `docs/DECISIONS.md`.
- The reference host is a small single-core instance. It runs no builds, and the service keeps
  memory headroom for SQLite and the voice client.
