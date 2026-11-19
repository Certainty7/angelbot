#!/usr/bin/env python3
"""Offline self-test for the Angel bot (no Discord connection, no production DB writes).

    cd <project-root> && ./venv/bin/python tools/selftest.py

Checks:
  1. every package module imports
  2. config.BASE_DIR resolves to the project root
  3. slash-command tree is complete (silence/autonomy must exist)
  4. per-user memory: facts persist, recall by keyword, cap enforced
  5. harem-only romance gate: romantic actions are refused without network access
  6. silence map persists and is readable
  7. autonomy engine respects its rate limits
  8. system ffmpeg is executable (video resolvers)
  9. conversation metrics: ai-reply/ai-guard lines parse, caller tag hides the raw id
 10. gallery: every platform's extraction path, fixture in -> slide list out (offline)

Exit 0 = all good.
"""
import asyncio
import importlib
import logging
import os
import subprocess
import sys
import tempfile

# Windows consoles default to cp1252, which cannot print the Arabic check details.
try:
  sys.stdout.reconfigure(encoding="utf-8", errors="replace")
  sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
  pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
TMP_DB = os.path.join(tempfile.gettempdir(), "angel_selftest.db")
os.environ.setdefault("ANGEL_DB_PATH", TMP_DB)
# These two ids define the hermetic admin context the ACL checks assert on. They are forced
# (not setdefault): under systemd the EnvironmentFile already carries the production admin ids,
# and inheriting them made `context-acl` fail on the real deploy path. A false negative in a
# startup gate is an outage, so the test owns its own ids.
os.environ["MALAK_ADMIN_ROLE_IDS"] = "555"
os.environ["MALAK_ADMIN_CHANNEL_IDS"] = "999"
# The owner id is environment-only now, so the test must use the real declared id
# (falling back to an obvious placeholder on a clean checkout without .env).
def _declared_owner_id() -> str:
    try:
        from dotenv import dotenv_values

        value = (dotenv_values(os.path.join(ROOT, ".env")).get("MALAK_OWNER_ID") or "").strip()
        return value if value.isdigit() else "42"
    except Exception:  # noqa: BLE001 - a missing .env is not a test failure by itself
        return "42"


os.environ.setdefault("MALAK_OWNER_ID", _declared_owner_id())

EXPECTED_COMMANDS = 67
results = []


def check(name):
    def deco(fn):
        try:
            detail = fn()
            results.append((True, name, detail or ""))
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            results.append((False, name, f"{type(exc).__name__}: {exc}"))
        return fn
    return deco


@check("imports")
def _imports():
    mods = ("config", "net", "persona", "quota", "database", "downloader",
            "media", "images", "brain", "guard", "memory", "autonomy",
            "triage", "scoring", "cost", "context_acl", "sendqueue", "evolution", "rules")
    for mod in mods:
        importlib.import_module(f"angel.{mod}")
    importlib.import_module("bot")
    return f"{len(mods)} modules"


@check("BASE_DIR")
def _base_dir():
    cfg = importlib.import_module("angel.config")
    assert os.path.realpath(cfg.BASE_DIR) == os.path.realpath(ROOT), cfg.BASE_DIR
    prod_db = os.path.realpath(os.path.join(ROOT, "chat_history.db"))
    if os.path.realpath(cfg.DB_PATH) == prod_db:
        assert os.path.isfile(cfg.DB_PATH), cfg.DB_PATH
    return cfg.BASE_DIR


@check("commands")
def _commands():
    bot_mod = importlib.import_module("bot")
    tree = bot_mod.bot.tree
    total = len(tree.get_commands())
    assert total == EXPECTED_COMMANDS, f"runtime tree {total}, expected {EXPECTED_COMMANDS}"
    for required in ("silence", "autonomy", "gif", "chat", "summarize_channel", "help"):
        assert tree.get_command(required) is not None, f"missing /{required}"
    return f"{total} commands"


@check("memory")
def _memory():
    db_mod = importlib.import_module("angel.database")
    mem = importlib.import_module("angel.memory")

    async def run():
        path = os.path.join(tempfile.gettempdir(), "angel_selftest_mem.db")
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass
        db = db_mod.BotDatabase(path)
        await db.initialize()
        uid = 424242
        await db.upsert_profile_fact(uid, "العمل", "مهندس شبكات", 0.9)
        await db.upsert_profile_fact(uid, "المدينة", "مسقط", 0.8)
        await db.upsert_profile_fact(uid, "العمل", "مهندس شبكات أول", 0.95)
        facts = await db.get_profile_facts(uid)
        assert len(facts) == 2, facts
        hit = await db.search_profile_facts(uid, ["مسقط"])
        assert hit and "مسقط" in hit[0]["fact_value"], hit
        lines = mem.format_facts(facts)
        assert any("العمل" in line for line in lines), lines
        for i in range(50):
            await db.upsert_profile_fact(uid, f"k{i}", f"v{i}", 0.5)
        await db.prune_profile_facts(uid, 10)
        assert len(await db.get_profile_facts(uid, 100)) <= 10
        await db.close()

    asyncio.run(run())
    return "upsert/recall/prune ok"


@check("romance-gate")
def _romance_gate():
    cfg = importlib.import_module("angel.config")
    brain_mod = importlib.import_module("angel.brain")
    assert cfg.is_romantic_gif("kiss") and cfg.is_romantic_gif("yuri_hug")
    assert not cfg.is_romantic_gif("pat") and not cfg.is_romantic_gif("smile")

    ai = brain_mod.AngelBrainService(api_key="x", models_list=["m"], quota_guard=type("Q", (), {})())
    for action in ("kiss", "hug", "cheek_kiss", "cuddle", "handhold"):
        got = asyncio.run(ai.fetch_anime_gif_data(action, for_female_pair=False, allow_romantic=False))
        assert got == (None, None), (action, got)
    return "romantic actions refused offline"


@check("silence")
def _silence():
    db_mod = importlib.import_module("angel.database")

    async def run():
        path = os.path.join(tempfile.gettempdir(), "angel_selftest_silence.db")
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass
        db = db_mod.BotDatabase(path)
        await db.initialize()
        await db.set_silent(111, 0, True, 1)
        await db.set_silent(111, 222, True, 1)
        mapping = await db.get_silent_map()
        assert mapping.get(111) == {0, 222}, mapping
        await db.set_silent(111, 222, False, 1)
        mapping = await db.get_silent_map()
        assert mapping.get(111) == {0}, mapping
        await db.close()

    asyncio.run(run())
    return "guild + channel mute persist"


@check("autonomy-limits")
def _autonomy():
    aut = importlib.import_module("angel.autonomy")
    engine = aut.AutonomyEngine()
    assert engine.can_send() is True
    import time as _t
    engine.sent_times = [_t.monotonic()] * aut.MAX_PER_HOUR
    assert engine.can_send() is False, "hourly cap not enforced"
    engine.sent_times = []
    engine.daily_count = aut.MAX_PER_DAY
    assert engine.can_send() is False, "daily cap not enforced"
    assert isinstance(engine.in_quiet_hours(), bool)
    # the configured caps must stay inside the product rule they were set for
    assert 1 <= aut.MAX_PER_HOUR <= 12 and 1 <= aut.MAX_PER_DAY <= 60, (aut.MAX_PER_HOUR, aut.MAX_PER_DAY)
    assert 0 < (aut.QUIET_END - aut.QUIET_START) % 24, "quiet window is degenerate"
    return f"{aut.MAX_PER_HOUR}/h, {aut.MAX_PER_DAY}/d, quiet {aut.QUIET_START}-{aut.QUIET_END}"


@check("ffmpeg")
def _ffmpeg():
    cfg = importlib.import_module("angel.config")
    out = subprocess.run([cfg.FFMPEG_EXE, "-version"], capture_output=True, text=True, timeout=10)
    assert out.returncode == 0, out.stderr[:120]
    return out.stdout.splitlines()[0][:40]



# ---------------- merged from the Malak build ----------------
def _fresh_db(tag: str):
    from angel.database import BotDatabase
    path = os.path.join(tempfile.gettempdir(), f"angel_selftest_{tag}.db")
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass
    return BotDatabase(path)


@check("memory-fts5")
def _memory_fts5():
    import asyncio

    async def run():
        db = _fresh_db("fts")
        await db.initialize()
        await db.upsert_profile_fact(7, "السكن", "مسقط", 0.9)
        await db.upsert_profile_fact(7, "العمل", "مهندس برمجيات", 0.8)
        hits = await db.search_profile_facts(7, ["مسقط"])
        assert hits and any("مسقط" in str(h.get("fact_value")) for h in hits), hits
        # Arabic morphology fallback (plural vs singular)
        await db.upsert_rule(9, "قاعدة 1", "يمنع نشر الروابط الدعائية في القنوات العامة")
        rules = await db.search_rules(9, "هل مسموح أنشر رابط دعائي؟")
        assert rules, "rules fuzzy fallback failed"
        await db.close()
        return f"{len(hits)} fact hit, {len(rules)} rule hit"

    return asyncio.run(run())


@check("context-acl")
def _context_acl():
    from types import SimpleNamespace
    from angel import context_acl as acl

    role = SimpleNamespace(id=555)
    admin = SimpleNamespace(id=1, roles=[role], guild_permissions=SimpleNamespace(administrator=False))
    member = SimpleNamespace(id=2, roles=[], guild_permissions=SimpleNamespace(administrator=False))
    admin_ch = SimpleNamespace(id=999, guild=SimpleNamespace(id=5))
    public_ch = SimpleNamespace(id=1000, guild=SimpleNamespace(id=5))

    assert acl.resolve_context(admin, admin_ch).is_admin
    assert not acl.resolve_context(admin, public_ch).is_admin, "role alone must not unlock admin scope"
    assert not acl.resolve_context(member, admin_ch).is_admin, "channel alone must not unlock admin scope"
    try:
        acl.require_admin_context(member, public_ch)
        raise AssertionError("public context passed require_admin_context")
    except acl.AclError:
        pass
    assert acl.public_refusal("وش صار في سجل الإدارة؟") is not None
    assert acl.public_refusal("كيف حالك") is None
    return "role+channel both required"


@check("cost-breaker")
def _cost_breaker():
    import asyncio
    from angel import cost

    async def run():
        db = _fresh_db("budget")
        await db.initialize()
        pair = await db.add_usage(cost.local_day(), 1000, 500, cost.stop_at() + 0.01)
        assert pair >= cost.stop_at(), pair

        class _AI:
            db = None

            async def budget_blocked(self):
                return (await self.db.day_cost(cost.local_day())) >= cost.stop_at()

        from angel.brain import AngelBrainService
        ai = AngelBrainService.__new__(AngelBrainService)
        ai.db = db
        assert await AngelBrainService.budget_blocked(ai) is True
        await db.close()
        return f"stops at ${cost.stop_at():.4f}"

    return asyncio.run(run())


@check("scoring")
def _scoring():
    from angel import scoring as sc

    low = sc.reply_probability(sc.Signals(msgs_in_window=0, mood=0.2, seconds_since_last_reply=0))
    hot = sc.reply_probability(sc.Signals(msgs_in_window=8, topic_hits=3, mood=0.8, seconds_since_last_reply=3000))
    mention = sc.reply_probability(sc.Signals(msgs_in_window=0, mentioned=True, mood=0.15, seconds_since_last_reply=0))
    assert 0 <= low < hot <= 1 and mention >= 0.90, (low, hot, mention)
    assert 0.0 < sc.typing_delay("مرحبا") <= 6.5
    return f"p_low={low:.2f} p_hot={hot:.2f} p_mention={mention:.2f}"


@check("triage")
def _triage():
    from angel import triage as tr

    t = tr.triage("اسمي يوسف وأسكن في مسقط وأشتغل مهندس")
    assert len(t.facts) >= 2, t.facts
    assert tr.triage("هههههه").store is False
    assert all(0 < c <= 1 for _, _, c in t.facts)
    return f"{len(t.facts)} facts"


@check("queue-429")
def _queue_429():
    import asyncio
    import discord
    from angel import sendqueue

    class _Resp:
        status = 429
        reason = "Too Many Requests"
        headers = {}

    class _Chan:
        id = 1

        def __init__(self):
            self.calls = 0
            self.sent = []

        def get_partial_message(self, _id):
            return None

        async def send(self, content, **_kw):
            self.calls += 1
            if self.calls == 1:
                exc = discord.HTTPException(_Resp(), "rate limited")
                exc.retry_after = 0.01
                raise exc
            self.sent.append(content)

    class _Client:
        def __init__(self, ch):
            self.ch = ch

        async def wait_until_ready(self):
            return None

        def is_closed(self):
            return False

        def get_channel(self, _id):
            return self.ch

    ch = _Chan()
    sender = sendqueue.Sender(_Client(ch), capacity=5, rate_per_sec=50)

    async def run():
        sender.start()
        await sender.enqueue(sendqueue.SendJob(channel_id=1, content="hello"))
        for _ in range(80):
            if ch.sent:
                break
            await asyncio.sleep(0.05)
        await sender.stop()
        assert ch.sent == ["hello"], ch.sent
        assert sender.retried >= 1

    asyncio.run(run())
    return "429 honoured, message retried and delivered"


@check("evolution-clamp")
def _evolution_clamp():
    import random
    from angel import evolution

    mood, settings, rng = 0.55, {k: (lo + hi) / 2 for k, (lo, hi) in evolution.SETTING_RANGES.items()}, random.Random(7)
    for _ in range(500):
        state = evolution.step(mood, settings, rng)
        mood, settings = state["mood"], state["settings"]
        assert evolution.MOOD_RANGE[0] <= mood <= evolution.MOOD_RANGE[1], mood
        for key, (lo, hi) in evolution.SETTING_RANGES.items():
            assert lo <= settings[key] <= hi, (key, settings[key])
    return f"mood={mood:.2f} stayed in range"


@check("rules-answer")
def _rules_answer():
    import asyncio
    from angel import rules

    class _FailingAI:
        async def generate_angel_reply_raw(self, *_a, **_kw):
            from angel.cost import BudgetExhausted
            raise BudgetExhausted("blocked")

    async def run():
        db = _fresh_db("rules")
        await db.initialize()
        await db.upsert_rule(5, "قاعدة 3", "يمنع إرسال الروابط الدعائية في القنوات العامة")
        text = await rules.answer(_FailingAI(), db, 5, "هل أقدر أنشر رابط دعائي؟")
        await db.close()
        assert "قاعدة 3" in text and ("روابط" in text or "رابط" in text), text
        return text[:40]

    return asyncio.run(run())


@check("persona-guards")
def _persona_guards():
    from angel import persona

    out = persona.humanize("بالتأكيد! كيف أقدر أساعدك؟ الله يسعدك", {"typo_rate": 0.0})
    assert "بالتأكيد" not in out and "أساعدك" not in out, out
    assert len(persona.trim_emoji("يا هلا 😂😂😂", 1)) < len("يا هلا 😂😂😂")
    return "tics stripped, emoji capped"


class _User:
    """Stand-in for discord.abc.User: the owner gates only read `.id`."""

    def __init__(self, uid):
        self.id = uid


@check("owner-identity")
def _owner_identity():
    from dotenv import dotenv_values

    cfg = importlib.import_module("angel.config")
    declared = (os.getenv("MALAK_OWNER_ID") or dotenv_values(os.path.join(ROOT, ".env")).get("MALAK_OWNER_ID") or "").strip()
    assert declared.isdigit(), "MALAK_OWNER_ID missing or non-numeric"
    owner = int(declared)  # read at runtime; the id is never written in this file
    assert cfg.MISTRESS_INT_ID == owner, "config owner id drifted from MALAK_OWNER_ID"
    assert owner in cfg._ALLOWED_OWNER_IDS, "_ALLOWED_OWNER_IDS lost the owner"
    if cfg.MISTRESS_USER_ID.isdigit():
        assert int(cfg.MISTRESS_USER_ID) in cfg._ALLOWED_OWNER_IDS, "env override not wired into _ALLOWED_OWNER_IDS"

    assert cfg.is_mistress(_User(owner)) is True, "owner gate must answer True for the owner id"
    assert cfg.is_mistress(_User(owner + 7919)) is False, "owner gate must reject a stranger"
    assert cfg.is_mistress(_User(0)) is False, "owner gate must reject id 0"
    return "env-declared id admitted; stranger and 0 refused"


@check("owner-gates")
def _owner_gates():
    from types import SimpleNamespace

    cfg = importlib.import_module("angel.config")
    acl = importlib.import_module("angel.context_acl")
    owner = cfg.MISTRESS_INT_ID

    assert cfg.is_server_staff(_User(owner), None) is True, "owner lost the staff bypass"
    for action in ("ADD_HAREM", "BAN", "SET_MODLOG"):
        assert cfg.check_staff_action_permission(_User(owner), None, action) is True, f"owner lost {action}"
    assert cfg.check_staff_action_permission(_User(owner + 7919), None, "BAN") is False, "stranger got staff rights"

    # context_acl reads its own owner id from MALAK_OWNER_ID at import time
    assert acl.OWNER_ID, "context_acl.OWNER_ID unset (MALAK_OWNER_ID not read)"
    plain = SimpleNamespace(id=acl.OWNER_ID, roles=[], guild_permissions=SimpleNamespace(administrator=False))
    outsider = SimpleNamespace(id=acl.OWNER_ID + 7919, roles=[], guild_permissions=SimpleNamespace(administrator=False))
    assert acl.is_admin_member(plain) is True, "context_acl owner branch is gone"
    assert acl.is_admin_member(outsider) is False, "context_acl admits a stranger"
    ch = SimpleNamespace(id=min(acl.ADMIN_CHANNEL_IDS) if acl.ADMIN_CHANNEL_IDS else 0, guild=SimpleNamespace(id=5))
    assert acl.resolve_context(plain, ch).is_admin is True, "owner lost admin context"
    assert acl.resolve_context(outsider, ch).is_admin is False, "stranger gained admin context"
    return "config bypasses + context_acl owner branch intact"


@check("ai-metrics")
def _ai_metrics():
    import importlib.util

    from angel.brain import _user_tag

    spec = importlib.util.spec_from_file_location(
        "angel_metrics", os.path.join(ROOT, "tools", "metrics.py"))
    metrics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metrics)

    lines = [
        "2026-11-11 22:00:00 | INFO | ai-reply ms=900.0 model=gemini-x usd=0.001200 cmd=message user=aaaa1111",
        "2026-11-11 22:00:01 | INFO | ai-reply ms=100.0 model=gemini-x usd=0.000800 cmd=chat user=aaaa1111",
        "2026-11-11 22:00:02 | INFO | ai-reply ms=50.0 model=gemini-x usd=0.000100 cmd=facts user=-",
        "2026-11-11 22:00:03 | INFO | ai-guard reason=harem-gate",
        "2026-11-11 22:00:04 | INFO | ai-guard reason=recall-hit",
        "2026-11-11 22:00:05 | INFO | message body that must not be counted",
    ]
    stats = metrics.ai_stats(lines)
    assert stats["replies_24h"] == 2, stats
    assert stats["latency_p50_ms"] == 100.0 and stats["latency_p95_ms"] == 900.0, stats
    assert stats["refusals_24h"] == 1, stats
    assert abs(stats["cost_usd_24h"] - 0.0021) < 1e-6, stats
    assert metrics.ai_stats([])["latency_p50_ms"] is None, "empty window must report null, not 0"

    tag = _user_tag(_User(123456789012345678))
    assert len(tag) == 12 and tag != "-" and "123456789012345678" not in tag, tag
    return f"p50={stats['latency_p50_ms']}ms refusals={stats['refusals_24h']} tag={tag[:4]}…"


@check("gallery")
def _gallery():
    """Fixture in -> slide list out for every platform the resolver supports.

    Offline by construction: `media.get_shared_http_session` is swapped for a fake that
    answers from `tests/fixtures/gallery/` (unmapped URLs get the 404 the dead proxied
    endpoints really return), and `media.yt_dlp` is disabled so no engine can fall back
    to its own HTTP client.
    """
    import glob
    import hashlib
    import json

    from angel import media

    fix_dir = os.path.join(ROOT, "tests", "fixtures", "gallery")
    VIDEO_HEAD = b"\x00\x00\x00\x18ftypisom"

    def media_bytes(url, name):
        # Deterministic stand-ins that pass the resolvers' own validators:
        # 6400 B MP4 (ftyp header, >=4096) and 644 B JPEG (SOI magic, >=400/500).
        seed = hashlib.sha256(url.encode()).digest()
        return VIDEO_HEAD + seed * 200 if name.endswith(".mp4") else b"\xff\xd8\xff\xe0" + seed * 20

    class _Content:
        def __init__(self, body):
            self.body = body

        async def iter_chunked(self, chunk):
            for i in range(0, len(self.body), chunk):
                yield self.body[i:i + chunk]

    class _Response:
        """Just enough of aiohttp.ClientResponse for angel.net.read_bounded_stream."""

        def __init__(self, status, body, ctype, url):
            self.status, self.url, self.body = status, url, body
            self.headers = {"Content-Type": ctype, "Content-Length": str(len(body))}
            self.content = _Content(body)

        async def text(self):
            return self.body.decode("utf-8", "replace")

        async def json(self, **_kw):
            return json.loads(self.body)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    class _Session:
        def __init__(self, routes):
            self.routes, self.hits = routes, []

        def _response(self, url):
            self.hits.append(url)
            body, ctype, status = self.routes.get(url, (b"", "text/html", 404))
            return _Response(status, body, ctype, url)

        def get(self, url, **_kw):
            return self._response(url)

        def post(self, url, **_kw):
            return self._response(url)

    class _LogCapture(logging.Handler):
        """Collects the resolver's own log lines so a case can assert what the journal shows."""

        def __init__(self):
            super().__init__(level=logging.INFO)
            self.messages = []

        def emit(self, record):
            try:
                self.messages.append(record.getMessage())
            except Exception:  # noqa: BLE001
                self.messages.append(str(record.msg))

    capture = _LogCapture()

    async def run_case(case):
        routes = {}
        for url, spec in case.get("responses", {}).items():
            with open(os.path.join(fix_dir, spec["file"]), "rb") as fh:
                routes[url] = (fh.read(), "text/html", 200)
        want = []
        for slide in case["expect"]["slides"]:
            # `same_as` serves the exact bytes of another slide's URL: that is what a stale
            # mirror answering every slot of one media type with one placeholder looks like.
            body = media_bytes(slide.get("same_as") or slide["url"], slide["name"])
            is_video = slide["name"].endswith(".mp4")
            routes[slide["url"]] = (body, "video/mp4" if is_video else "image/jpeg", 200)
            want.append({"name": slide["name"], "digest": hashlib.md5(body).hexdigest()})
        # `extra_routes` exist but must NOT reach the output: the duplicate placeholders the
        # resolver has to drop (and then repair) are served here.
        for extra in case.get("extra_routes", []):
            name = extra.get("name") or "ig_extra.jpg"
            body = media_bytes(extra.get("same_as") or extra["url"], name)
            routes[extra["url"]] = (body, "video/mp4" if name.endswith(".mp4") else "image/jpeg", 200)
        session = _Session(routes)

        async def _fake_session():
            return session

        capture.messages.clear()
        real_session, real_ytdlp = media.get_shared_http_session, media.yt_dlp
        media.get_shared_http_session, media.yt_dlp = _fake_session, None
        try:
            files, fallback, _caption = await media.process_social_media_url_multi(case["url"])
        finally:
            media.get_shared_http_session, media.yt_dlp = real_session, real_ytdlp
        got = [{"name": fname, "digest": hashlib.md5(body).hexdigest()} for body, fname in files]
        assert got == want, f"{case['case']}: got {got} want {want}"
        assert fallback == case["expect"]["fallback"], f"{case['case']}: fallback {fallback!r}"
        want_log = case["expect"].get("log")
        if want_log:
            assert any(want_log in msg for msg in capture.messages), (
                f"{case['case']}: no log line containing {want_log!r}; saw {capture.messages}")
        no_log = case["expect"].get("no_log")
        if no_log:
            assert not any(no_log in msg for msg in capture.messages), (
                f"{case['case']}: unexpected log line {no_log!r}; saw {capture.messages}")
        return len(got)

    paths = sorted(glob.glob(os.path.join(fix_dir, "*.case.json")))
    assert len(paths) >= 6, f"only {len(paths)} gallery fixtures in {fix_dir}"
    cases = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            cases.append(json.load(fh))

    async def run_all():
        # one loop for every case: media._TIKWM_LOCK binds to the first running loop
        angel_log = logging.getLogger("Angel")
        angel_log.addHandler(capture)
        try:
            return [await run_case(case) for case in cases]
        finally:
            angel_log.removeHandler(capture)

    slides = asyncio.run(run_all())
    return f"{len(cases)} platforms, {sum(slides)} slides: " + ", ".join(c["case"] for c in cases)


# ---- certification gate -------------------------------------------------------------------
# The blocks above are the original 21 checks. The certification gate adds the later ones:
# command census over cogs, owner escape hatch on the cost breaker,
# requirements-vs-venv, owner id not in source, error correlation id, music kill-switch
# wording, clean resolve errors). They live in tools/gate_checks.py so they can be read and
# run on their own; the selftest just registers them.
_GATE_DIR = os.path.join(ROOT, "tools")
if _GATE_DIR not in sys.path:
    sys.path.insert(0, _GATE_DIR)
try:
    import gate_checks

    for _gate_name, _gate_fn in gate_checks.CHECKS:
        check(_gate_name)(_gate_fn)
except Exception as exc:  # noqa: BLE001 - a broken gate module must fail the run, not vanish
    results.append((False, "gate-checks", f"{type(exc).__name__}: {exc}"))


@check("music-search")
def _music_search():
    from angel.audio_source import parse_play_request, score_candidate, strip_command_words

    assert parse_play_request("انجل شغلي اغنية محمد عبده الاصيله") == "اغنية محمد عبده الاصيله"
    assert parse_play_request("يا انجل شغلي https://youtu.be/abc") == "https://youtu.be/abc"
    assert parse_play_request("شغلي لوفي") is None, "a bare verb must not trigger"
    assert parse_play_request("انجل كيف حالك") is None, "chat must not trigger"
    assert strip_command_words("انجل شغلي lofi hip hop") == "lofi hip hop"

    good = score_candidate("الاصيله - محمد عبده", 300, "اغنية محمد عبده الاصيله", "SoundCloud")
    junk = score_candidate("Al-Asila 8D slowed reverb 1 hour", 3600, "اغنية محمد عبده الاصيله", "YouTube")
    assert good > junk, (good, junk)
    assert score_candidate("lofi hip hop radio", 3815, "lofi hip hop", "SoundCloud") > 0
    return f"trigger + ranking ok (good={good:.0f} junk={junk:.0f})"


@check("metrics-fixture")
def _metrics_fixture():
    """The deploy gate must never read as traffic: a fixture block contributes zero."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("angel_metrics", "tools/metrics.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    fixture = [
        "2026-11-12 17:45:58 | WARNING  | cost-guard owner_override=1 spent=0.4755",
        "2026-11-12 17:45:58 | INFO     | ai-reply ms=0.0 model=m1 usd=0.000003 cmd=chat user=f5b40557e19d",
        "2026-11-12 17:45:58 | INFO     | ai-guard reason=budget",
    ]
    stats = mod.ai_stats(fixture)
    assert stats["replies_24h"] == 0, stats
    assert stats["refusals_24h"] == 0, stats
    assert stats["cost_usd_24h"] == 0.0, stats
    assert stats["latency_p50_ms"] is None, stats

    real = [
        "2026-11-12 18:00:00 | INFO     | ai-reply ms=850.0 model=gemini-2.5-flash usd=0.0012 cmd=chat user=aaaa1111",
        "2026-11-12 18:00:10 | INFO     | ai-guard reason=harem-gate",
    ]
    stats2 = mod.ai_stats(real)
    assert stats2["replies_24h"] == 1, stats2
    assert stats2["refusals_24h"] == 1, stats2
    assert stats2["latency_p50_ms"] == 850.0, stats2
    return "gate block ignored, real reply counted"


@check("social-url-cleanup")
def _social_url_cleanup():
    """Tracking parameters must not create two keys for one post (dedupe + caching)."""
    import bot as bot_mod

    clean = bot_mod.clean_social_url
    assert clean("https://www.instagram.com/p/ABC123/?igsh=MWx5cQ%3D%3D&utm_source=ig_web") == \
        "https://www.instagram.com/p/ABC123/"
    assert clean("https://www.tiktok.com/@u/video/7312?is_from_webapp=1&sender_device=pc") == \
        "https://www.tiktok.com/@u/video/7312"
    assert clean("https://x.com/u/status/1723") == "https://x.com/u/status/1723"
    assert clean("https://example.com/a?utm_medium=x") == "https://example.com/a"
    # a query that carries meaning must survive
    assert clean("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    return "4 tracking params stripped, meaningful query kept"


@check("memory-intent")
def _memory_intent():
    """A question must find the fact by intent, not by literal word overlap."""
    from angel.memory import intent_keys

    assert "city" in intent_keys("وين ساكن الحين؟"), intent_keys("وين ساكن الحين؟")
    assert "job" in intent_keys("وش شغلك بالضبط؟")
    assert "pet" in intent_keys("عندك حيوان في البيت؟")
    assert "family" in intent_keys("عندك إخوة؟")
    # the hamza/taa-marbuta variants must collapse, or half the questions miss
    assert "study" in intent_keys("وش درست في الجامعه؟")
    assert intent_keys("شكرا لك") == []
    return "6 intent routes, unrelated text routes nowhere"


@check("caption-hygiene")
def _caption_hygiene():
    """Captions must keep the human text and drop hashtag walls, tracking lines and bloat."""
    import bot as bot_mod

    raw = "#تصوير #فن #اكسبلور\nhttps://instagram.com/p/abc\nطلع الضوء حلو اليوم\n#photooftheday\n@someone"
    out = bot_mod.tidy_caption(raw)
    assert "طلع الضوء حلو اليوم" in out, out
    assert "#" not in out and "instagram.com" not in out, out
    assert len(bot_mod.tidy_caption("ا" * 900)) <= 280
    assert bot_mod.tidy_caption("") == ""
    return "hashtag wall and links dropped, human line kept"


@check("server-log")
def _server_log():
    """Every human line must land in server_messages; the table must exist on a fresh DB."""
    import asyncio
    import os
    import tempfile

    from angel.database import BotDatabase

    async def run():
        path = os.path.join(tempfile.gettempdir(), "angel-serverlog-test.db")
        if os.path.exists(path):
            os.remove(path)
        db = BotDatabase(path)
        await db.log_server_message(1, 2, 3, "tester", "رسالة تجريبية للتعلم")
        async with db._connect() as conn:  # noqa: SLF001
            cur = await conn.execute("SELECT content FROM server_messages ORDER BY id DESC LIMIT 1")
            row = await cur.fetchone()
        await db.close()  # or the aiosqlite worker outlives the loop and prints a traceback
        os.remove(path)
        return row[0] if row else None

    got = asyncio.run(run())
    assert got == "رسالة تجريبية للتعلم", got
    return "table created on a fresh DB and the line is stored verbatim"


@check("archive-intent")
def _archive_intent():
    """Only a recall-shaped question may touch the archive; ordinary chat must not."""
    import asyncio
    from angel import archive

    assert archive.is_recall("انجل متى تكلمنا عن السوني؟")
    assert archive.is_recall("تتذكرين سالفة القهوة؟")
    assert not archive.is_recall("انجل كيف حالك")
    assert not archive.is_recall("شغلي لوفي")
    assert asyncio.run(archive.lookup("كيف حالك")) is None
    return "recall detection + no lookup for chat"


@check("member-file-absent")
def _member_file_absent():
    """No module, cue table or NL branch may restore message-derived member profiling."""
    import importlib

    try:
        importlib.import_module("angel.member_files")
    except ModuleNotFoundError:
        pass
    else:
        raise AssertionError("angel.member_files still exists")

    import angel.nl_router as router

    for attr in ("MEMBER_FILE_QUESTION_CUES", "parse_member_file_facts", "render_member_file_answer"):
        assert not hasattr(router, attr), attr
    assert "member_file_notes" not in open(router.__file__, encoding="utf-8").read()
    return "profiling module, cues and NL branch gone"


def main():
    failed = [r for r in results if not r[0]]
    for ok, name, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name:16s} {detail}")
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
