# Gallery extraction: what `angel/media.py` returns per platform

Entry point: `process_social_media_url_multi(url)` → `(files, fallback_url, caption)`.
`files` are `(bytes, filename)` pairs; `bot.py` sends them in `chunk_slides()` batches of 10
(`/fix` and the social-link handler both send **every** batch). `fallback_url`, when set, is posted
as plain content so Discord unfurls it. Fixtures: `tests/fixtures/gallery/*.case.json`, exercised
offline by the `gallery` check in `tools/selftest.py`.

## Matrix: state on 2026-11-12 (code anchor: `f66f489`, `angel/media.py` sha256 `e313eb71…`)

`Slides` is what the resolver hands to `bot.py`. `Live` says whether that count was measured against
a real public post from this host in the verification pass below. An empty cell is never left:
whatever was not measured says so and says what is missing.

| Platform | Slides | Live | Notes / what is missing |
|---|---|---|---|
| TikTok video | 1 mp4 | **no live check** | Offline fixture `tiktok_video` only. Missing: a live video post run in this pass (the photo path shares the TikWM engine, so the gap is the mp4 validation step, not the lookup) |
| TikTok photo post | up to 35 images | **yes: 3/3 and 3/3** | ≤2 concurrent downloads + one TikWM re-quote retrying only the missing slides; two independent posts, stable over 3 repeats |
| Instagram carousel | up to 20 slides | **yes: 8/8** on an 8-slide post, 4/4–5/5 on a 5-slide control | SnapSave + `/embed/captioned/` + GraphQL in parallel, then 4 proxy hosts; md5 dedupe, then a repair wave that re-downloads **only the lost indices** (other Wave-1 list first, then one bounded re-quote) and one `gallery-shortfall` INFO line when the loss cannot be repaired |
| Instagram reel | video slides only | **no live check** | Offline fixture `ig_reel` only. Missing: a live `/reel/` URL in this pass |
| X / Twitter photos | every photo of the post | **yes: 2/2 and 4/4** | `api.fxtwitter.com` JSON (`media.all`), then yt-dlp, then the fxtwitter link |
| X / Twitter video | 1 mp4 | **no live check** | Offline fixture `x_video` only. Missing: a public video post gone through `extract_x_media_items` live |
| Reddit gallery | **none** | **yes: 0 files + `rxddit.com` link** | By design: the rxddit embed renders the gallery in Discord; a parser needs Reddit OAuth |
| anything else | none | n/a | returns `(, None, None)`; the bot stays silent and leaves the original link alone |


## Forced single-source failures (measured 2026-11-12 04:45Z)

Each platform's **primary** engine was disabled in a probe process (monkeypatch only, no file in the
repo was changed) and the real resolver was run against a real public post from this host. This is the
column the matrix could not fill from live successes alone: what the *user* receives when the engine
that normally wins is unavailable.

| Platform | Primary disabled | What the user actually receives | Verdict |
|---|---|---|---|
| TikTok photo | `www.tikwm.com` (all calls) | **3/3 slides, 542 214 bytes**, caption `📸 **TikTok Photo**`, identical to the healthy run | Second engine carries it; no regression |
| Instagram carousel | `_fetch_snapsave_instagram_slides()` | **1 slide, 156 717 bytes**, caption `📸 **Instagram Post**`, and no shortfall line in the journal, because the surviving engine reported `discovered=1` | **Degradation, not a fallback**: a reader sees one image of an 8-slide post and nothing says so |
| X / Twitter photos | `fxtwitter.com` (API *and* link host) | **0 files + `https://fxtwitter.com/elonmusk/status/…`** as plain content | Correct: the embed stands in, no partial album |
| Reddit gallery | none needed | **0 files + `https://rxddit.com/r/pics/comments/…`** | As designed |

Two things this measures that the matrix cannot:

1. **The 0-slide fallbacks are honest.** X and Reddit hand the link back and the message is never a
   half-empty album. That is the behaviour a carousel should copy.
2. **The Instagram secondary path is not a fallback, it is a silent downgrade.** With SnapSave gone the
   embed/GraphQL path reports one slide, so `gallery-shortfall` never fires (it compares delivered
   against `discovered`, and `discovered` is wrong) and the caption still says `Instagram Post`. The
   next step is *not* a blind patch of `angel/media.py`: first make the secondary path report the
   true carousel count (`edge_sidecar_to_children` in the embed payload, or the GraphQL count), then
   apply the rule already used for shortfalls: if delivered < discovered, return the mirror link
   instead of a partial carousel, exactly like the X path does.

## Verification pass (2026-11-11 23:56 UTC)

Anchor: `HEAD` `4fa0407`, `angel/media.py` sha256 `fc527bd45fb15a1c330feb9c55932c9b1f2da45f36479febcfd9c91788a490de`
(the gallery code last changed in `3e5dacc`, file mtime 23:52:53; the running service started
00:00:02 UTC (`systemctl show angelbot -p ExecMainStartTimestamp`), so production served exactly
that file. The earlier "23:58:37" in this line was wrong; the start time is 00:00:02.)

Gate:

```
$ ./venv/bin/python -m py_compile bot.py angel/media.py tools/selftest.py   -> COMPILE_OK
$ ./venv/bin/python tools/selftest.py
[PASS] gallery          12 platforms, 14 slides: ig_carousel, ig_reel, reddit_gallery,
                        reddit_old, reddit_prefixed, tiktok_photo, tiktok_video, x_mobile,
                        x_multi, x_photos, x_prefixed, x_video
29/29 checks passed
```

The check bites. Damaging `tests/fixtures/gallery/ig_carousel.embed.html` (first 600 bytes only)
gives `[FAIL] gallery  AssertionError: ig_carousel: got [] want [5 slides]` and `27/28 checks
passed`; swapping slide 1 and slide 5 URLs gives `got [4 items] want [5 items]` (order drift); both
restored to sha256 `b57ca53a…` with the gate green again.

Live runs of the resolver:

| Case | Post | Slides | Distinct | Bytes | Wall | Worst loop lag |
|---|---|---|---|---|---|---|
| TikTok photo | `@motivate.yourself__/photo/7688359214636354819` | 3/3 | 3 | 542 214 | 2.06 s | 9 ms |
| TikTok photo | `@anamiriamyepez/photo/7498924643227536645` | 3/3 | 3 | 361 586 | 2.54 s | 12 ms |
| IG carousel | `instagram.com/p/DZu_E3IGxQ7` | 5/5 | 5 | 711 412 | 3.00 s | 98 ms |
| X photos | `x.com/elonmusk/status/2120591950961353125` | 2/2 | 2 | 221 521 | 1.92 s | 583 ms* |
| X photos | `x.com/ManCity/status/2120524829010899007` | 4/4 | 4 | 12 485 705 | 3.06 s | 731 ms* |
| Reddit | `reddit.com/r/pics/comments/1xnnogq/blue_wave/` | 0 + link | – | – | 0.0 s | – |

Ground truth is not taken from the resolver:

- TikTok: `tikwm.com/api/` `data.images` length = 3 for both posts (matches).
- Instagram: the post's own embed payload, `edge_sidecar_to_children.edges` = 5, `is_video`
  sequence `false, false, true, true, false`; the resolver returned `jpeg, jpeg, mp4, mp4, jpeg`
  in that same order. Stable 5/5 over three repeats.
- X: `api.fxtwitter.com` `media.all` length = 2 and 4 (matches).

Per-candidate timeouts are unchanged: each candidate request carries its own
`aiohttp.ClientTimeout` (5.5 s SnapSave/SaveIG, 4.5 s GraphQL, 5.0 s proxy hosts, 12.0 s slide
download, 14 s TikWM, 8 s TikWM API) and the waves are `asyncio.gather` over those coroutines, so a
dead candidate costs its own timeout and nothing else.

Event loop: while the 12.4 MB X photo post was being resolved, a 20 ms ticker measured
p50 0.4 ms / p99 12.1 ms / worst 56.7 ms. Re-running that same case a second time produced no
spike, and the same ticker on an idle loop on this host measured p50 0.1 ms / p99 65 ms / worst
76.4 ms at loadavg 1.9 on 2 vCPU. The resolver's own work adds no measurable stall: the
583/731 ms outliers marked `*` above are host contention (another process was probing the same box),
not a blocking call, since the identical case later measured 56.7 ms worst, below the idle baseline.
Image re-encoding already runs off-loop (`run_in_executor`) and JPEG/PNG pass through untouched.

## Verification pass (2026-11-12 04:35 UTC): Instagram shortfall repair

Anchor: commit `f66f489`, `angel/media.py` sha256
`e313eb71c2b185d7fa15eb110341b9b0685e9a05b793e42933215bad50647813`,
`tools/selftest.py` sha256 `0a3e6b0eaea2d7350bf496ec4dddf417d341d542107cc0f970c0123846394b7d`.
This pass supersedes the gallery numbers in the section above.

Gate (on that commit):

```
$ ./venv/bin/python -m py_compile bot.py angel/media.py tools/selftest.py   -> COMPILE_OK
$ ./venv/bin/python tools/selftest.py
[PASS] gallery          14 platforms, 24 slides: ig_carousel, ig_reel, ig_shortfall_retry,
                        ig_shortfall_warn, reddit_gallery, reddit_old, reddit_prefixed,
                        tiktok_photo, tiktok_video, x_mobile, x_multi, x_photos, x_prefixed, x_video
29/29 checks passed
```

The two new fixtures fail on the previous resolver (`media.py` `fc527bd4…`) and pass on this one;
that is the regression lock for the silent shortfall:

```
# old code, both new cases present
[FAIL] gallery  AssertionError: ig_shortfall_retry: got [ig_1.mp4, ig_3.jpg] want [8 slides]   28/29
# old code, retry case parked so the warn case is reached
[FAIL] gallery  AssertionError: ig_shortfall_warn: no log line containing
                'gallery-shortfall platform=instagram discovered=8 delivered=2'; saw []       28/29
```

`ig_shortfall_retry` is 8 discovered slides where the mirror hands back one placeholder per media
type (harness key `same_as`), with the 8 real URLs in the embed wave: the repair has to fetch exactly
the 6 lost indices and deliver 8/8 in order. `ig_shortfall_warn` is the same degenerate mirror with
no second source at all: 2 delivered and exactly one `gallery-shortfall` line (`expect.log`).

Live runs on `instagram.com/p/DeMhid3kUtk` (ground truth 8 slides: `edge_sidecar_to_children.edges`
= 8, `is_video` = `true,true,false,false,false,false,true,true`). The mirror alternates between a
healthy phase (8 distinct payloads) and a degenerate one (2 distinct payloads for 8 slots), so both
states were measured:

| When | Code | Mirror phase | Delivered | Names | Shortfall line |
|---|---|---|---|---|---|
| 04:14 | old `fc527bd4` | degenerate | 4, 4, 4 of 8 | mixed, 4 distinct | none (silent) |
| 04:31 | new `e313eb71` | degenerate | 6 of 8 | `ig_1, ig_3, ig_4, ig_5, ig_7, ig_8`, with indices 4,5,7,8 repaired | 1 line |
| 04:33 | new `e313eb71` | healthy | 8, 8, 8 of 8 | `ig_1…ig_8`, kind order mp4,mp4,jpg,jpg,jpg,jpg,mp4,mp4 | none |
| 04:34 | control `DZu_E3IGxQ7` | healthy / one degenerate run | 5, 4, 5 of 5 | n/a | 1 line on the 4/5 run |

Deterministic before/after, because the natural degenerate phase comes and goes: the **first** snapsave
quote is rewritten to the measured fault (every video slot = first video URL, every image slot = first
image URL) and everything else (downloads, dedupe, repair quote, payloads) is the real CDN. Two
rounds, old tree vs new tree, same minute:

```
OLD-code  delivered 2  names [ig_1.mp4, ig_3.jpg]  snapsave_calls 1  shortfall []
NEW-code  delivered 8  names [ig_1…ig_8]           snapsave_calls 2  shortfall []
```

and with the fault kept on *every* quote (the mirror never recovering), the new code reports instead
of staying silent:

```
delivered 2  shortfall ["gallery-shortfall platform=instagram discovered=8 delivered=2
                        url=https://www.instagram.com/p/DeMhid3kUtk/"]
```

Latency and loop: the repair only runs when something was lost. Healthy posts are unchanged
(2.2–5.3 s wall, same 8 GETs as before); a shortfall adds the bounded re-quote (1 s pause + 8 s
`wait_for` ceiling, both waves inside it) and measured 9.4–9.6 s wall on the control post. A 20 ms
ticker during the new-code runs measured p50 0.1 ms, p99 2.1–29.0 ms, worst 119.8 ms: every
candidate keeps its own `aiohttp.ClientTimeout` and the repair reuses the same `Semaphore(4)`.

Deployment state: the running service (started 00:30:24 UTC, `angel/media.py` mtime 00:15:06) still
serves the **previous** resolver; this pass ran the committed tree (`f66f489`, clean worktree at the
time of the runs, `media.py` sha256 `e313eb71…`) with the project venv, which is exactly what the
service loads on its next start. Restart to pick it up:

```
sudo -n systemctl restart angelbot
# rollback: git revert --no-edit f66f489 && sudo -n systemctl restart angelbot
# or: cp "$BACKUP_DIR"/media.py.20261112T042103Z.bak angel/media.py
#     cp "$BACKUP_DIR"/selftest.py.20261112T042103Z.bak tools/selftest.py
```

## Gaps that remain, and why

- **Instagram carousel: the mirror's degenerate phase is fixed, not cured.** `d.rapidcdn.app` still
  answers every video slot with one payload and every image slot with another while it is in its bad
  phase (measured 04:13 and 04:31 UTC 2026-11-12: 8 slots, 2 distinct payloads, stable per URL and
  across re-quotes). What changed: the resolver no longer accepts the loss. The dropped indices are
  re-downloaded from another source, and when nothing can repair them the post goes out short **with**
  `gallery-shortfall platform=instagram discovered=8 delivered=3 url=…` in `journalctl -u angelbot`.
  On this host the only working carousel source is SnapSave: `/embed/captioned/` answers `302` and
  `api.instagram.com/oembed` answers `302` (0 bytes), `i.instagram.com/api/v1/media/…/info/` answers
  `401`, and the proxy hosts return a cover image at best (`kkinstagram` 4 247 B, `vxinstagram` 1
  `og:image`, `instagramez` 151 B, `ddinstagram` NXDOMAIN, `snapinsta.app` NXDOMAIN). So the repair
  is only as good as the second quote: when the mirror is degenerate for every quote the user still
  gets a short carousel; the difference is that it is now visible instead of silent. A real cure
  needs an authenticated Instagram source (cookies or a logged-in session), which this host does not
  have.
- **The repair assumes the second list is positionally aligned.** It only runs when the fresh list has
  the same length as the discovered one (the same guard the TikTok photo re-quote uses), so a source
  that returns a differently shaped list is ignored rather than mapped onto the wrong slide.
- **X and Reddit have no parser for post text/media beyond what the mirrors expose.** X photos and
  videos come from FxEmbed's JSON now; Reddit deliberately stays link-only (`rxddit.com`) because a
  parser needs OAuth and would duplicate the embed.
- **Pasted fixer links are un-fixed first.** `fxtwitter.com`, `vxtwitter.com`, `fixupx.com`,
  `rxddit.com` and `vxreddit.com` are normalized back to `x.com` / `www.reddit.com` before the
  rewrite; without that, the substring rewrite produced dead `fxfxtwitter.com` / `vxrxddit.com`
  mirrors and the post lost its embed entirely.
- **Reddit `/s/` share links (mobile "Copy link") are rewritten as-is** and never resolved first.
  Still unverified live: a share token cannot be minted from this host. If `rxddit.com/r/<sub>/s/<token>`
  does not follow the token, that fallback link is dead. Fix would be a redirect resolve for
  `reddit.com/…/s/…`, same as `redd.it/`.
- **No headless end-to-end Discord delivery exists to test with.** `bot.py:267` drops
  bot-authored messages and a slash command needs a real user interaction, so an automated check cannot make
  the live bot post. Everything above is measured on the resolver the production process runs, and
  the send loop is covered by driving the real `fix_cmd` callback with synthetic Discord objects; 15 resolved slides produced attachment counts `[10, 5]`, which is
  the 10-per-message cap respected and no slide dropped. Missing: one human-triggered
  `/fix` in a real channel, watched in `journalctl -u angelbot`.
- **`mobile.twitter.com` / `www.fxtwitter.com` links never reach the resolver** when posted in chat:
  `SOCIAL_URL_REGEX` only allows `www.|m.|fx|vx|…` prefixes before the canonical domain, so nothing
  is rewritten and Discord's own unfurl stands. Harmless; `/fix` with such a URL is handled by the
  un-fix step above.

## Live resolution check 2026-11-12 (from the deployment host, no Discord involved)

| Input | Items | Time | Note |
|---|---|---|---|
| `instagram.com/p/DeMhid3kUtk/` | 3 | 8.8 s | carousel slides resolved live |
| `tiktok.com/@tiktok/photo/7286740230059574570` | 3 | 9.8 s | photo post resolves |
| Reddit | 0 | – | embed only, by the Reddit decision |

This proves **extraction** end to end. Delivery into a channel (attachment upload, 10-slide chunks,
caption) still needs one live Discord run, which only the owner can trigger.
