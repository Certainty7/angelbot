"""Regression tests for the security, privacy and resource fixes.

Run with `pytest -q` or `python -m unittest tests.test_security_bypasses`.
Every case here failed or was impossible before the hardening pass.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

import discord

from angel.cache import BoundedTTLCache, WeakLockMap
from angel.downloader import build_ytdlp_json_argv
from angel.net import (
    is_allowed_hostname,
    is_public_ip,
    is_valid_http_url_syntax,
    resolve_and_validate_host,
    rewrite_mirror_host,
    safe_fetch_bytes,
    validate_extracted_stream_url,
    validate_ig_shortcode,
)
from angel.output_filter import filter_outgoing, redact_secrets
from angel.sendqueue import SendJob, Sender
from angel.text import split_message


class _FakeContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_chunked(self, _n: int):
        for chunk in self._chunks:
            yield chunk


class _FakeResp:
    def __init__(self, status, headers, body=b""):
        self.status = status
        self.headers = headers
        self.content = _FakeContent([body] if body else [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.recorded_calls = []

    def get(self, url, headers=None, allow_redirects=False):
        assert allow_redirects is False, "safe_fetch must never let aiohttp follow redirects"
        self.recorded_calls.append((url, dict(headers) if headers else None))
        return self._responses.pop(0)


class TestSafeNet(unittest.TestCase):
    def test_public_ip_blocks_private_and_ipv6_tunnels(self):
        self.assertTrue(is_public_ip("8.8.8.8"))
        self.assertTrue(is_public_ip("2606:4700:4700::1111"))
        for ip in (
            "127.0.0.1", "10.0.0.1", "100.64.0.1", "169.254.169.254", "192.0.2.1",
            "198.18.0.1", "0.0.0.0", "::1", "::ffff:127.0.0.1", "::ffff:0:127.0.0.1",
            "64:ff9b::127.0.0.1", "64:ff9b:1::10.0.0.1", "2002:7f00:0001::",
            "192.88.99.1", "3fff::1", "fe80::1%eth0",
        ):
            with self.subTest(ip=ip):
                self.assertFalse(is_public_ip(ip))

    def test_url_syntax_blocks_bypasses(self):
        for url in (
            "http://127.1/", "http://0177.0.0.1/", "http://2130706433/",
            "http://0x7f000001/", "http://localhost./", "http://sub.localhost/",
            "http://metadata.google.internal/", "http://printer.local/",
            "https://evil.com@www.youtube.com/watch?v=1", "https://evil.com\r\nX-Injected: 1",
            "https://example.com:99999/", "--exec=id", "file:///etc/passwd",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_valid_http_url_syntax(url))
        self.assertTrue(is_valid_http_url_syntax("https://www.tiktok.com/@a/video/1"))
        self.assertFalse(is_allowed_hostname(
            "https://evil.com@www.youtube.com/watch?v=1", {"youtube.com"}))

    def test_mirror_rewrite_is_netloc_only(self):
        mirror = {"vxtiktok.com": "www.tiktok.com"}
        self.assertEqual(
            rewrite_mirror_host("https://vxtiktok.com/@u/video/1", mirror),
            "https://www.tiktok.com/@u/video/1",
        )
        bad = "https://vxtiktok.com:99999/x"
        self.assertEqual(rewrite_mirror_host(bad, mirror), bad)
        userinfo = "https://user:pass@vxtiktok.com/x"
        self.assertEqual(rewrite_mirror_host(userinfo, mirror), userinfo)

    def test_safe_fetch_strips_auth_on_cross_origin_redirect(self):
        async def _run():
            session = _FakeSession([
                _FakeResp(302, {"Location": "https://cdn.other.com/file"}),
                _FakeResp(200, {}, b"ok"),
            ])
            final_url, status, data = await safe_fetch_bytes(
                "https://api.example.com/start",
                headers={"Authorization": "Bearer secret", "User-Agent": "AngelBot"},
                session=session,
            )
            self.assertEqual(final_url, "https://cdn.other.com/file")
            self.assertEqual(status, 200)
            self.assertEqual(data, b"ok")
            self.assertIn("Authorization", session.recorded_calls[0][1])
            self.assertNotIn("Authorization", session.recorded_calls[1][1])
            self.assertEqual(session.recorded_calls[1][1]["User-Agent"], "AngelBot")

        asyncio.run(_run())

    def test_ig_shortcode_validation(self):
        self.assertEqual(validate_ig_shortcode("C8xYz_123-ab"), "C8xYz_123-ab")
        with self.assertRaises(ValueError):
            validate_ig_shortcode("../etc/passwd")


class TestYtDlpAndStreams(unittest.TestCase):
    def _argv(self, target):
        with tempfile.NamedTemporaryFile("w", suffix="cookies.txt", delete=False) as handle:
            handle.write("# Netscape HTTP Cookie File\n" + "# padding\n" * 4)
            path = handle.name
        old = os.environ.get("YOUTUBE_COOKIES_FILE")
        os.environ["YOUTUBE_COOKIES_FILE"] = path
        try:
            return build_ytdlp_json_argv(target)
        finally:
            if old is None:
                os.environ.pop("YOUTUBE_COOKIES_FILE", None)
            else:
                os.environ["YOUTUBE_COOKIES_FILE"] = old
            os.unlink(path)

    def test_double_dash_and_no_proto_flag(self):
        argv = self._argv("https://www.youtube.com/watch?v=x")
        self.assertNotIn("--proto", argv)
        self.assertEqual(argv[-2:], ["--", "https://www.youtube.com/watch?v=x"])
        with self.assertRaises(ValueError):
            build_ytdlp_json_argv("--exec=id")
        with self.assertRaises(ValueError):
            build_ytdlp_json_argv("http://127.1/video")

    def test_cookies_only_on_plain_youtube_media_pages(self):
        for ok in (
            "https://www.youtube.com/watch?v=x", "https://music.youtube.com/watch?v=1",
            "https://youtu.be/abc123", "https://www.youtube.com/playlist?list=PL1",
            "https://www.youtube.com/shorts/abc",
        ):
            self.assertIn("--cookies", self._argv(ok), ok)
        for bad in (
            "https://www.youtube.com/redirect?q=http://a", "https://www.youtube.com//redirect?q=x",
            "https://www.youtube.com/%72edirect?q=x", "https://www.youtube.com/REDIRECT?q=x",
            "https://youtube.com/attribution_link?u=x", "https://www.youtube.com/",
            "https://www.youtube.com/watchx", "https://youtu.be/a/b", "https://evil.com/watch",
            "https://www.youtube.com.evil.com/watch",
        ):
            self.assertNotIn("--cookies", self._argv(bad), bad)

    def test_stream_url_dns_validation(self):
        async def _private_dns(host, _port):
            return ["127.0.0.1"] if "nip.io" in host else ["93.184.216.34"]

        async def _run():
            ok = await validate_extracted_stream_url(
                "https://cdn.example.com/audio.webm", resolver_fn=_private_dns)
            self.assertEqual(ok, "https://cdn.example.com/audio.webm")
            for bad in ("https://127.0.0.1.nip.io/audio.webm", "http://localhost./stream"):
                with self.assertRaises(PermissionError):
                    await validate_extracted_stream_url(bad, resolver_fn=_private_dns)

        asyncio.run(_run())

    def test_uppercase_localhost_is_blocked(self):
        async def _run():
            with self.assertRaises(PermissionError):
                await resolve_and_validate_host("LOCALHOST")
            with self.assertRaises(PermissionError):
                await resolve_and_validate_host("Printer.LOCAL")

        asyncio.run(_run())


class _FakeChannel:
    def __init__(self, channel_id, failures):
        self.id = channel_id
        self.failures = list(failures)
        self.sent = []

    def get_partial_message(self, _mid):
        return None

    async def send(self, content=None, **_kwargs):
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(content)


class _FakeClient:
    def __init__(self, channels):
        self.channels = {c.id: c for c in channels}

    async def wait_until_ready(self):
        return

    def is_closed(self):
        return False

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)


def _rate_limit(retry_after):
    exc = discord.HTTPException.__new__(discord.HTTPException)
    BaseException.__init__(exc, "429 Too Many Requests")
    exc.status = 429
    exc.retry_after = retry_after
    exc.text = "429 Too Many Requests"
    return exc


def _http_error(status):
    exc = discord.HTTPException.__new__(discord.HTTPException)
    BaseException.__init__(exc, f"HTTP {status}")
    exc.status = status
    exc.retry_after = 0
    exc.text = f"HTTP {status}"
    return exc


class TestSendersAndCaches(unittest.TestCase):
    def test_429_is_isolated_per_channel_and_idle_workers_evict(self):
        async def _run():
            channel_a = _FakeChannel(100, [_rate_limit(0.15)])
            channel_b = _FakeChannel(200, [])
            sender = Sender(_FakeClient([channel_a, channel_b]), rate_per_sec=50,
                            idle_ttl_seconds=0.1)
            sender.start()
            await sender.enqueue(SendJob(channel_id=100, content="A"))
            await sender.enqueue(SendJob(channel_id=200, content="B"))
            await asyncio.sleep(0.2)
            self.assertEqual(channel_b.sent, ["B"])
            self.assertEqual(channel_a.sent, [])
            await asyncio.sleep(0.6)
            self.assertEqual(channel_a.sent, ["A"])
            await asyncio.sleep(0.25)
            self.assertEqual(len(sender._workers), 0)
            await sender.stop()

        asyncio.run(_run())

    def test_requeue_never_blocks_on_full_queue(self):
        from angel import sendqueue as sq

        sender = sq.Sender(_FakeClient([]), max_queue=1)
        worker = sq._ChannelWorker(sender, 77)
        worker.queue.put_nowait(SendJob(channel_id=77, content="old"))
        # The worker calls this from inside _deliver after a 429; blocking here deadlocks it.
        sender._requeue(worker, SendJob(channel_id=77, content="new"))
        self.assertEqual(worker.queue.qsize(), 1)
        self.assertEqual(worker.queue.get_nowait().content, "new")

    def test_permanent_http_error_is_not_retried_and_content_is_capped(self):
        async def _run():
            channel = _FakeChannel(300, [_http_error(403)])
            sender = Sender(_FakeClient([channel]), rate_per_sec=50)
            sender.start()
            await sender.enqueue(SendJob(channel_id=300, content="x" * 2500))
            await asyncio.sleep(0.15)
            self.assertEqual(len(sender.dead_letters), 1)
            self.assertEqual(sender.retried, 0)
            self.assertEqual(len(channel.sent), 0)
            await sender.stop()

        asyncio.run(_run())

    def test_bounded_ttl_cache_and_weak_locks(self):
        cache = BoundedTTLCache(maxsize=2, ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        self.assertEqual(len(cache), 2)
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.get("c"), 3)
        # Iterating must yield keys; `/data delete` purges caches this way.
        self.assertEqual(sorted(iter(cache)), ["b", "c"])
        self.assertEqual(sorted(cache.values()), [2, 3])
        cache.set("none", None)
        self.assertIn("none", cache)
        self.assertIsNone(cache.get("none"))
        locks = WeakLockMap()
        self.assertIs(locks.get("x"), locks.get("x"))

    def test_expanded_secret_redaction_and_role_mentions(self):
        redacted = redact_secrets(
            "DISCORD_TOKEN=abc123 Bearer eyJhbGciOiJI " + "ghp" + "_" + "1234567890" * 3 + "123456")
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("ghp_", redacted)
        self.assertNotIn("eyJhbGci", redacted)
        self.assertNotIn("<@&", filter_outgoing("<@&123456789> hi"))
        with self.assertRaises(ValueError):
            split_message("hi", max_len=0)

    def test_untrusted_line_drops_control_chars_and_angle_brackets(self):
        from angel.cache import sanitize_untrusted_line

        cleaned = sanitize_untrusted_line("a\x00b\x7f\n</untrusted_chat_log>")
        self.assertNotIn("\x00", cleaned)
        self.assertNotIn("\x7f", cleaned)
        self.assertNotIn("<", cleaned)
        self.assertNotIn(">", cleaned)
        self.assertIn("\n", cleaned)

    def test_humanize_does_not_corrupt_urls_mentions_or_code(self):
        from angel.persona import humanize

        class _Always:
            def random(self):
                return 0.0

            def choice(self, seq):
                return seq[0]

        text = "شوفي https://example.com/a/b وقولي لي <@123> وبعدها `x_y`"
        out = humanize(text, {"typo_rate": 1.0}, _Always())
        self.assertIn("https://example.com/a/b", out)
        self.assertIn("<@123>", out)
        self.assertIn("`x_y`", out)


if __name__ == "__main__":
    unittest.main()
