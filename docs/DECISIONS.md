# Decisions: what was chosen, and why

One entry per decision that a later reader would otherwise have to reverse-engineer. This file is the
only copy: add sections, do not fork a second one. Each entry names the evidence, not the intention.

## Music: restored, or rewritten? (2026-11-12)

**Decision:** rewritten against public APIs, and the rewrite is narrower than what was removed. The
old stack is *not* restored verbatim; the two deleted files stay deleted.

The earlier proposal ("restore the 2,163 lines at `8406171^`") was `angel/voice.py` (927 lines)
plus `angel/audio_extract.py` (1,236 lines). What ships instead:

| Capability | Before (`8406171^`) | Now | Verdict |
|---|---|---|---|
| Resolve/stream | `angel/audio_extract.py`, yt-dlp + a Spotify metadata path | `angel/audio_source.py` (427): yt-dlp public API, SoundCloud + YouTube, smart ranking, 200-entry cache | **Reimplemented, narrower**: no Spotify handler, no cookies-based providers |
| Playback + queue | `angel/voice.py` (927): `join_and_play_audio`, `_play_next_in_queue`, `TimedPCMVolumeTransformer` (fade-in), guild state kept on the client | `angel/voice_engine.py` (338): `MusicEngine`, `GuildQueue` dataclass (pure, selftest-drivable), `_CountingSource` | **Reimplemented**: queue state moved out of the client, no fade-in |
| DAVE / E2EE | monkey-patches on the voice client: `_wrap_ws_dave_binary`, `_install_voice_client_guards`, `_wait_for_dave_ready` | `dave_state()` + an 8 s bounded wait in the play path, member-facing refusal text when E2EE did not come up | **Reimplemented as behaviour**: the library is no longer patched |
| Command surface | `play`, `skip`, `queue`, `playlist`, `volume`, `audio_filter`, `join`, `stay`, `leave` (9) | `play`, `skip`, `queue`, `playlist` (4) | **Narrower, deliberately** |
| Volume | `/volume` 10–200 %, `adjust_guild_volume` | `GuildQueue.volume` + `MusicEngine.set_volume()` (0–200 %); **no command** | Engine ready, dial missing |
| Loop | `loop` mode in the queue | `GuildQueue.loop` + `pop_next()` honours it, with **no command**; `/queue` prints its state | Engine ready, dial missing |
| 24/7 | `/stay`, `set_guild_stay_247` | `GuildQueue.stay_247`, with **no command and no rejoin logic** | Withdrawn (see below) |
| Audio filters | `/audio_filter`, `apply_guild_audio_filter` (ffmpeg filter graph) | **absent** | Withdrawn (see below) |
| Join/leave/stop | `/join`, `/leave` | implicit: `/play` joins; `MusicEngine.stop(disconnect=True)` exists, with no command | Dial missing |
| Voice region guard | `_ensure_non_uae_voice_region` | **absent** | Withdrawn (see below) |

**Why not restore verbatim:** the old stack's failure modes are exactly what the previous round of
work spent days on: two gateway sessions invalidating each other, `is_playing()` lying during the
between-track gap, monkey-patches that break on a `discord.py` bump, and silent E2EE. The new code
keeps those lessons in code comments, and its queue is testable offline.

**Withdrawn, needs the owner's word (do not silently re-add):**
- `audio_filter`: ffmpeg filter graphs on the live stream were the least reliable part of the old
  stack and have no equivalent now.
- 24/7 `stay`: a permanently connected voice client on a small single-core box; the earlier
  music work never re-validated it.
- the UAE voice-region guard: the earlier music sessions showed no region-related join failure from this host.

Restoring `/volume`, `/loop` and `/stop` is small (the engine already holds the state and the
methods); restoring `audio_filter` and 24/7 is not, and should be a new, owner-approved change.
Until then the music work is **PARTIAL**: music exists, plays, and is proven audibly (owner,
2026-11-12), but the surface is four commands, not nine.


## Silent-failure census (2026-11-12)

A silent failure is a path where the bot looks healthy and the user gets nothing. Every row below was
observed or read in the code while these notes were written. The point of the table is that "no
exception" is not evidence of success, and to name what now detects each one.

| # | Failure | Where | Symptom | Detection today | Gap |
|---|---|---|---|---|---|
| 1 | DAVE/E2EE never established (lone bot in the channel) | `angel/voice_engine.py::dave_state`, `cogs/music.py` | `is_playing()` True, healthy ffmpeg, **total silence**, no exception | the play path logs `dave` state and answers the member with a refusal line when `can_encrypt` is false | audibility itself only provable by a human in the room |
| 2 | Carousel degraded to one slide | `angel/media.py` (Instagram, SnapSave down) | user sees 1 image of an 8-slide post, caption unchanged | `gallery-shortfall` line, **only when `discovered` is right**, which it is not on that path | needs the secondary engine to report the true count (documented in `docs/GALLERY.md`) |
| 3 | Summariser or background task dies | `angel/client.py` (`_background_summarize_user`, init steps) | history stops summarising; nothing user-visible | `logger.debug` now records the exception class; init steps log a warning | a repeated failure still only shows at debug level |
| 4 | Logger misuse | `logger.exception` outside an `except` block | `NoneType: None` in the journal, no context | fixed in the current tree; the place to check when a traceback looks empty | none |
| 5 | A restart "succeeds" but the new code is not live | systemd + `Shard ID None session has been invalidated` | `is-active` says active while the bot is not ready for ~2 minutes | readiness is proven only by `Angel is online as:` in the journal | scripted checks must poll that line, never `is-active` |
| 6 | Extraction engine returns `{}` and the caller posts a fallback | `angel/media.py` (the hoisted `_tikwm_quote` + `global` bug in `_LAST_TIKWM_CALL_AT`) | a photo post silently loses slides | the shortfall log + a fixture-driven `gallery` check | fixtures cannot see a live engine regression; only a live post does |
| 7 | Cost breaker trips | `angel/cost.py` | replies stop for the day | `/budget` reports spend against the 95 % stop line, and the breaker logs | none |
| 8 | A body moved without its imports (split refactor) | `cogs/*.py`, `bot.py` | the command answers `NameError` only when a user calls it; compile, the census and the tree dump all stay green; `/help` failed exactly this way in production from 05:46Z, seen at 07:37Z on 2026-11-12 | `undefined-globals` gate (symtable scan of `bot.py`, `angel/`, `cogs/`) fails the selftest on any global a function reads but the module never defines or imports; proven to bite by deleting one import from a copy | the scan sees name lookups only, not a wrong attribute on `self.bot` |

Rule of thumb that came out of this: a path that swallows an exception must either log the exception
class or set a user-visible flag. `except Exception: pass` is acceptable only where an unrelated
feature must keep working, and even then it should say so in the journal.


## How the resource and conversation numbers are measured (2026-11-12)

**Decision:** every number below has exactly one definition, and it lives in `tools/metrics.py`. A
second definition in a doc, a dashboard or a report is a bug; change the function, then this table.

| Field | Definition | Where | Reading |
|---|---|---|---|
| memory | RSS of the service process, MB = systemd `MemoryCurrent / 1048576` | `rss_mb()` | **187.5 MB** (2026-11-12 10:11Z), 130.6 MB at 04:15Z |
| CPU | 1-minute load average from `/proc/loadavg`; the reference box is single-core, so load1 is CPU saturation and sustained `> 0.8` is the alarm line | `load1()` | **0.15** (10:11Z), 0.30 at 04:15Z |
| latency | nearest-rank p50/p95 over `ai-reply ms=` journal lines with `cmd in {message, chat}` **only**; background calls (summary, facts, ambient) are excluded on purpose, since they would hide a slow chat path | `ai_stats()` | `null`; no chat traffic yet |
| recall | a reply that restates a stored fact about the user which is **absent from the triggering message and from the last 5 kept rows** (`KEEP_RECENT_MESSAGES`); counted from `user_summaries`/facts, sampled by hand. Reply length is not evidence | definition only, no counter | not measurable yet (needs real chat) |
| refusal | one `ai-guard reason=<X>` line with X in `{harem-gate, probe, budget}`; all four romance layers report as `harem-gate`, so the layer is named in the line's surrounding context, not in the reason | `ai_stats()` | **0** in 24 h |

**Reference latency, measured 2026-11-12 10:11Z:** three one-shot calls through
`AngelBrainService.generate_angel_reply_raw` with no DB attached (no usage row, no production write),
on the same `TEXT_VISION_MODELS` chain the bot uses: **842 / 1372 / 888 ms, p50 888 ms**.

It is a *reference*, not a baseline, and it deliberately does **not** enter `tools/metrics.log`: that
series is journal-derived only, so a probe line would be indistinguishable from user traffic later.

**Why the latency numbers stay open:** the only honest 24 h baseline is real conversation through
the service. All four `metrics.log` rows (11-11 22:44Z, 23:46Z, 11-12 04:15Z, 10:11Z) carry
`replies_24h=0` because nobody talked to the bot; manufacturing traffic would make the first
"baseline" a measurement of the probe. The first row after a real conversation is the baseline.
Until then the rule that no prompt changes without a baseline is honoured by not changing prompts,
which is also why the persona and prompt surface are untouched since the music work.

## Reddit: the embed is the product (2026-11-12)

**Decision:** Angel does not parse Reddit. For a Reddit post it returns the post embed link
(`https://rxddit.com/<path>`), which Discord renders as the gallery. The Reddit gallery requirement
is recorded as **N/A by owner decision**, not as a failure and not as a silent gap.

**Evidence (2026-11-12, from the deployment host):** `www.reddit.com/.../*.json` -> 403, `old.reddit.com` -> 403,
`api.reddit.com` -> 403, `oauth.reddit.com` -> 403, `api.pullpush.io` -> 526, `rxddit.com` -> 403.
No JSON payload is reachable from this host, so no parser could have been tested here.

**Owner acceptance (verbatim):** "حسنا لا حاجة لريديت" (2026-11-12).

**What this costs:** a Reddit post delivers a link rather than files, so it never appears in the
attachment count, and a deleted post renders nothing. That is the accepted trade.

## Website: where does the source live? (2026-11-14)

**Decision:** inside this repository, under `website/`, built from the repository root.

**Why:** the source of truth for a product belongs next to the product. The website's command
explorer is generated from `cogs/` and `angel/`, so a separate repository would either duplicate the
bot source or fetch it at build time — both create drift. The old website project stays as a
read-only legacy reference and is not overwritten.

**Consequence:** the Pages build runs from the repository root, installs from `website/package-lock.json`,
and publishes `website/dist`. Watch paths must include `cogs/**`, `angel/**`, `bot.py` and
`tools/website-data-generator/**` — not only `website/**`.

## Website: static hosting on a CDN, no origin server (2026-11-14)

**Decision:** a managed static host with Git integration (not Direct Upload), two independent projects.

**Why:** the brief forbids public website traffic on the web host and forbids a backend. Git
integration keeps every deployment traceable to a commit and is the documented mode for a
GitHub-backed static site. Direct Upload cannot later be switched to Git integration, so the mode is
chosen now, before any project exists.

**Blocker:** no hosting credentials are available to any agent. This is recorded once; the build,
tests and security work continue independently and the deployment step stays blocked.

## Website: no runtime backend, ever (2026-11-14)

**Decision:** no API, no database, no auth, no dashboard, no scheduled publishing, no client tracking.
The command catalogue is generated at build time into static JSON.

**Why:** the brief cancels these explicitly, and a hobby bot does not justify an origin to maintain.
Anything that needs state at request time is out of scope by definition.

## Legacy status service on the bot host (2026-11-14)

**Decision:** retire the legacy status/metrics service and do **not** connect the new website to it.
Any uptime or usage figure shown on the site comes from static facts, not from that service.

**Why:** it is a separately deployed service on the live bot host; stopping it is a production change
that must be sequenced after the new site is verified and the old site no longer depends on it.
Removing the unnecessary public surface is required by the brief; doing it in the right order is
required by "do not break the running bot".

**Rollback:** the unit file is kept on the host but disabled, so the previous state can be restored by
enabling it again if the site ever needs it.

## GitHub Actions hardening in `checks.yml` (2026-11-14)

**Decision:** the workflow gets an explicit least-privilege `permissions:` block and its two third-party
actions are pinned to immutable commit SHAs instead of floating major tags.

**Why:** a workflow with implicit write permissions and mutable `@v4` refs is a supply-chain path into
a repository that holds a production bot. Pinning is cheap and reversible; no check behaviour changes.

**Evidence:** `actions/checkout` v4.4.0 → `11d5960a326750d5838078e36cf38b85af677262`,
`actions/setup-python` v5.6.0 → `a26af69be951a213d495a4c3e4e4022e16d87065` (both read with
`git ls-remote --tags`, not from memory).

## Website: brand direction and visual system (2026-11-14)

**Decision:** direction **A, "Pearl Light / Roseglass"**, with the other two directions subordinated
rather than discarded. Full evaluation in `docs/BRAND_DIRECTIONS.md`; the implementable contract is
`docs/DESIGN_SYSTEM.md`, the tokens are `website/src/styles/tokens.css`, the assets are
`website/src/assets/brand/`, and the hero is specified in `docs/HERO_COMPOSITION.md`.

**Why A:** it is the only one of the three that is light-primary *and* has an independently composed dark
variant — because its material logic (light through a thin rose film) produces a daylight face and a
night face honestly, instead of inverting one to get the other. It also refuses every category
convention (dark hero, neon accent, card grid), which is what the brief asked for.

**Kept from the rejected directions:** B (Vellum & Seal) supplies the editorial discipline — folio
hairlines, rule-as-structure, generous measure. C (Rose Night Instrument) supplies the optics — the
concentric aperture, the specular bloom, the mono micro-label. Both are now subordinate layers inside A,
and C survives as the dark variant's elevation law (luminance + halo instead of drop shadows).

**Brand facts fixed here (do not drift):**
- Mark: "Nacre A" — two tapered blades meeting at a flat apex, a single deep-rose pearl suspended in the
  aperture at crossbar height. No halo, no wings, no mascot.
- Type: Arabic display **Amiri** (OFL), Arabic text **IBM Plex Sans Arabic**, Latin display **Instrument
  Serif**, Latin/command **IBM Plex Sans / Plex Mono** — all OFL, all self-hosted, no CDN.
- Palette: pearl `#FDFBFA`, ivory `#F5EEE7`, blush `#F1DFDC`, rose quartz `#E4C2C6`, deep rose
  `#8A2E45`, ink `#221A1B`. Rose Night: ground `#14100F`, card `#241C1E`, text `#F6EEEC`, lifted rose
  `#E9A9B6`. Contrast is measured, not assumed: every text pair ≥ 4.5:1, every control border ≥ 3:1.

**Consequence for implementation:** tokens are authored by the design owner and consumed by the implementation. Palette changes
never transition (a transition on a palette-driven colour restarts per recalculation and Chrome can leave
inherited colours on the old palette). Arabic takes no letter-spacing. Wordmarks are outlines, not live
text.

**Verification:** the Arabic and Latin wordmark outlines were compared pixel-wise against Chrome's own
render of the same strings in the same fonts — identical ink bounding boxes (291×278 and 777 wide) and
ink area within 0.33% / 0.57%.


## Website CI may legitimately skip (2026-11-14)

**Decision:** the website gate is its own workflow (`.github/workflows/website.yml`), it runs on
pushes to the work branch and on pull requests, it is **not** a required check on `master`, and both
of its jobs report success with an explicit `::notice::` when their inputs do not exist yet.

**Why:** the two failure modes to avoid are asymmetric. A website regression must not block a bot
hotfix, and an unbuilt site must not turn the branch red — but a gate that passes because it checked
nothing is worse than no gate. The workflow therefore skips only on a *missing input*
(`tools/website-data-generator/generate.py`, `website/package.json`) and never on a failing step; the
skip is visible in the Actions UI as a notice, and the moment the scaffold lands the same jobs run
for real with no edit.

**Exit condition:** in the commit that merges the site to `master`, add `master` to the workflow's
`push.branches` list and (only then) make `website` a required status check.

**Evidence:** run 43640462157 — catalogue job real (generator, drift gate, `--check`, 6 oracle tests,
JSON/leak gate), website job skipped with the notice. Run 43640817100 on a throwaway probe branch —
the same jobs with a fixture `website/` ran `build.sh`, `astro check` and Playwright green, which is
what makes the skip honest rather than decorative.

## Portal: committed output, no Pages build step (2026-11-14)

**Decision:** the portal repository (private) holds its sources in `src/` **and** its built site in
`public/`. `node scripts/build.mjs` regenerates `public/` from `src/`; the static host serves
`public/` with an empty build command; CI rebuilds and fails if the two differ.

**Why:** the portal has to survive years of unattended hosting. Zero npm dependencies means no
registry, no lockfile drift and no build image to age; serving committed bytes means the artifact
that was reviewed is the artifact that is deployed. The cost is a committed `public/`, which is a
fair trade for a site this small.

**Consequence:** a project is added with `node scripts/new-project.mjs --slug … --title …` plus a
build, and the build refuses to publish template sentences, so a half-written project cannot ship.
The build also asserts RTL, one `<h1>`, canonical URLs, zero `<script>` tags, resolvable internal
links and no build-host paths.

**History:** an earlier seed commit in that repository carried a single English placeholder page and
stated it would be replaced by this build. It was replaced by a normal commit on top (`7a2e49c`),
not by a force-push. The portal project and repository names are operator-managed and are not
recorded in this public repository.

## Website catalogue: which Arabic ships, and what `owner_only` means (2026-11-14)

**Decision:** `website/src/data/commands.json` carries two descriptions per command.
`description_discord` is the `description=` literal of the decorator — what Discord itself registers,
and what `tests/website/test_command_catalog.py` keeps checking against the runtime census.
`description_ar` is the Arabic the site publishes: the `descriptions_ar.json` entry when that file
has one, and the decorator literal only as a fallback — which today is exactly the 3 context menus,
since Discord gives them no description.

**Why:** before this the file was consulted only when the decorator had no Arabic, so 65 of its 68
entries were unreachable and a copy editor editing it changed nothing. Measured, not assumed:
overwriting 5 slash keys with a sentinel and regenerating produced a byte-identical `commands.json`
(sha256 `930be592…`) with 0 sentinels in the output. The shipped decorator copy also breaks this
project's own Arabic rules in 18 of 68 commands (11 end on an ASCII `)` after a Latin run; 7
owner-gated commands state no gate) where the authored file breaks 0 — but the decorator string is
Discord's user-visible copy, so it is not ours to rewrite from a website card.

**Alternative rejected:** an Astro-layer override reading `descriptions_ar.json` directly. It saves
the generator edit but keeps two Arabic sources alive and leaves `description_ar` in the JSON lying
about what it means.

**Same pass, `owner_only`:** the detector now accepts `not is_mistress(...)` as one **disjunct** of
the guard's test (`if not is_mistress(user) or not interaction.guild:`) — it previously required the
bare `not`, so `/autonomy` and `/silence` published as `owner_only: false`. A `not is_mistress(...)`
inside an `and` chain is deliberately *not* a gate: there it protects a target from a higher-ranked
caller (`kick`, `ban`, `rep`), and an administrator still passes. The ten owner-gated commands are
pinned by name in the test, so a new gate or a broken detector fails the suite instead of publishing
a permissive catalogue.

**Consequence:** editing `descriptions_ar.json` now changes the site at the next generation run.
What Discord displays stays the decorator literal until the owner approves a copy change and a
command re-sync — a separate card, out of scope here.

**Evidence:** `generate.py` (`collect()`, `build()`, `is_owner_only()`),
`tests/website/test_command_catalog.py` (census oracle on `description_discord`, editorial-copy pin,
`owner_only` oracle), `generate.py --check` clean after regeneration.

**Current count (v1.1.1):** the catalogue has **71** entries — 68 slash commands and 3 context
menus; 67 load eagerly and the 4 music commands load lazily. The historical measurements above
refer to the 68-entry census captured on 2026-11-14.


## D-040 — Four older commit subjects stay as written

**Decision:** the four subjects that exceed 72 characters or read as statements (`b7c9ffa`,
`7dd5e58`, `6830bc4`, `f7807e9` in the pre-rewrite numbering) are not reworded. The rule in
`CONTRIBUTING.md` applies from the commit that introduced it onward.

**Why:** rewording them means rewriting every ref again and moving three tags, which would cost an
owner announcement, a fresh protect/unprotect cycle and another published release for a cosmetic
gain. The rule itself is not weakened — a new subject over the limit is a defect; those four are
history.

**Consequence:** `git log --format=%s` on `master` will keep showing them. Anyone reading the history
sees the rule applied from 2026-11-25 forward, which is what the rule can honestly claim.
