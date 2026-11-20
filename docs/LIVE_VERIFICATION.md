# Live verification (owner-operated)

Some behaviour cannot be verified from a development machine or CI: it needs a real Discord
session, a real network path, or the production host. This file lists exactly what to check, how
to check it, and what a failure looks like. Nothing here has been executed by the recovery work.

## 1. Discord voice playback (DAVE / E2EE)

**Why it cannot be automated:** Discord voice requires a live gateway, a real voice channel and an
encryption handshake (`davey` + `PyNaCl`) that no fake client reproduces.

1. Deploy the branch to a test guild (not production) and join a voice channel with at least one
   human listener.
2. Run `/play` with a SoundCloud URL, then with a YouTube URL.
3. Watch the log while it plays:

   ```bash
   journalctl -u angelbot -n 200 | grep -E "music-audio|music-dave|music-play"
   ```

| Log line | Meaning | Action |
|---|---|---|
| `music-play ... dave=...` and `music-audio ... decoded_kb≈expected_kb` | audio reached the encoder | working |
| `music-dave blocked playback: ver=... can_encrypt=False` | the channel is E2EE and the session could not encrypt | bot refuses rather than playing silence; retry after a second, then check `davey`/`PyNaCl` versions |
| `music-audio stalled: decoded=0` | FFmpeg produced no bytes | the cached URL was invalidated automatically; retry once |
| `music-left-empty` | the bot left after the last human | expected |

4. Confirm the listener actually hears audio. `is_playing()` is not proof; the decoded byte
   counter is the closest automated proxy.

## 2. YouTube extraction

1. `/play https://www.youtube.com/watch?v=...` in a test guild.
2. If it fails, the reply names the reason. Check Deno is 2.9+ (`deno --version` in the container
   or host) and that `yt-dlp --version` matches `requirements.txt`.
3. If YouTube requires a session, place a fresh `cookies.txt` next to the code (or set
   `YOUTUBE_COOKIES_FILE`) and restart. Cookies are only attached to plain YouTube media URLs.

## 3. Production deployment (systemd)

```bash
sudo cp deploy/angelbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart angelbot
systemctl status angelbot --no-pager
journalctl -u angelbot -n 50 --no-pager
```

A fresh install must now start without a pre-existing database. Verify `ANGEL_DB_PATH` points at
`/opt/angelbot/data/angel.db` and that `ReadWritePaths` includes that directory.

Install the optional timers too:

```bash
sudo cp deploy/angelbot-backup.{service,timer} /etc/systemd/system/
sudo cp deploy/angelbot-persona.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now angelbot-backup.timer angelbot-persona.timer
systemctl list-timers 'angelbot*'
```

## 4. Docker deployment

```bash
docker compose build
docker compose up -d
docker compose ps          # healthcheck must become "healthy"
docker compose logs -f --tail 50
```

The container runs with a read-only root filesystem, a 1 GB memory limit and `pids_limit: 256`.
If it restarts immediately, check that the `angel_data` volume is mounted at `/app/data`.

## 5. Gemini provider behaviour

The suite mocks the provider. Live behaviour to confirm by hand:

- a normal reply arrives within the 28-second deadline;
- a daily 429 cools the model until the next Pacific midnight instead of retrying hourly;
- an owner call still works past the soft ceiling (it is logged as `cost-guard owner_override=1`).

## 6. Cloudflare token verifier

```bash
export CLOUDFLARE_API_TOKEN=...   # never commit this
python tools/verify_cloudflare_token.py --zone example.com
```

A transport failure or an HTTP 429/5xx is reported as inconclusive now, not as PASS.
