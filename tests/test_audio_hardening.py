"""Audio hardening: FFmpeg gets a browser-like UA/Referer, never credentials.

These tests are pure/offline: no yt-dlp run, no FFmpeg process, no voice socket.
"""
from __future__ import annotations

import json
import unittest

import angel.audio_source as audio_source
from angel.audio_source import (
    _is_youtube_url,
    _safe_ffmpeg_headers,
    _youtube_oembed_url,
    parse_info,
)
from angel.voice_engine import Track, _before_options


class TestAudioHardening(unittest.TestCase):
    def test_credentials_never_reach_ffmpeg(self):
        safe = _safe_ffmpeg_headers({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://soundcloud.com/",
            "Cookie": "session=secret",
            "Authorization": "Bearer secret",
            "Accept-Language": "ar",
        })
        self.assertEqual(
            safe,
            {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://soundcloud.com/",
                "Accept-Language": "ar",
            },
        )

    def test_parse_info_keeps_only_the_safe_subset(self):
        payload = json.dumps({
            "url": "https://cdn.example/stream",
            "title": "track",
            "duration": 61,
            "http_headers": {
                "User-Agent": "UA",
                "Referer": "https://soundcloud.com/",
                "Cookie": "secret=1",
            },
        })
        info = parse_info(payload)
        self.assertEqual(info["http_headers"], {
            "User-Agent": "UA",
            "Referer": "https://soundcloud.com/",
        })

    def test_before_options_carry_ua_and_referer_only(self):
        opts = _before_options(Track(
            title="track",
            stream_url="https://cdn.example/stream",
            http_headers={
                "User-Agent": "Mozilla/5.0 Test",
                "Referer": "https://soundcloud.com/",
                "Cookie": "secret=1",
                "Authorization": "Bearer secret",
            },
        ))
        self.assertIn("-user_agent", opts)
        self.assertIn("Mozilla/5.0 Test", opts)
        self.assertIn("-headers", opts)
        self.assertIn("Referer: https://soundcloud.com/", opts)
        self.assertNotIn("Cookie", opts)
        self.assertNotIn("Authorization", opts)
        self.assertIn("-rw_timeout", opts)
        self.assertIn("-nostdin", opts)

    def test_no_headers_is_still_playable(self):
        opts = _before_options(Track(title="track", stream_url="https://cdn.example/stream"))
        self.assertIn("-protocol_whitelist", opts)
        self.assertNotIn("-user_agent", opts)
        self.assertNotIn("-headers", opts)

    def test_youtube_fallback_helpers(self):
        self.assertTrue(_is_youtube_url("https://youtu.be/abc"))
        self.assertTrue(_is_youtube_url("https://www.youtube.com/watch?v=abc"))
        self.assertTrue(_is_youtube_url("https://music.youtube.com/watch?v=abc"))
        self.assertFalse(_is_youtube_url("https://soundcloud.com/x/y"))
        self.assertFalse(_is_youtube_url("https://youtube.com.evil.example/watch?v=abc"))
        oembed = _youtube_oembed_url("https://youtu.be/abc")
        self.assertTrue(oembed.startswith("https://www.youtube.com/oembed?"))
        self.assertIn("url=https%3A%2F%2Fyoutu.be%2Fabc", oembed)


class TestYouTubeFallback(unittest.IsolatedAsyncioTestCase):
    async def test_failed_youtube_url_plays_the_same_song_from_soundcloud(self):
        info = {
            "title": "same song", "stream_url": "https://cdn.example/audio",
            "webpage_url": "", "duration": 120.0, "ext": "m4a", "uploader": "",
            "http_headers": {"User-Agent": "UA"},
        }

        async def fail_ytdlp(*_args, **_kwargs):
            raise audio_source.ResolveError("yt-dlp exit 1")

        async def fake_title(_url):
            return "same song"

        async def fake_target(_target, _timeout):
            return dict(info)

        async def fake_validate(_url):
            return _url

        saved = (
            audio_source._run_ytdlp,
            audio_source._youtube_oembed_title,
            audio_source._resolve_target,
            audio_source.validate_extracted_stream_url,
            audio_source._is_safe_public_http_url,
        )
        audio_source._run_ytdlp = fail_ytdlp
        audio_source._youtube_oembed_title = fake_title
        audio_source._resolve_target = fake_target
        audio_source.validate_extracted_stream_url = fake_validate
        audio_source._is_safe_public_http_url = lambda _url: True
        try:
            resolved = await audio_source.resolve("https://youtu.be/abc", timeout=1.0)
        finally:
            (
                audio_source._run_ytdlp,
                audio_source._youtube_oembed_title,
                audio_source._resolve_target,
                audio_source.validate_extracted_stream_url,
                audio_source._is_safe_public_http_url,
            ) = saved
        self.assertEqual(resolved["source"], "SoundCloud")
        self.assertEqual(resolved["search_title"], "same song")

    async def test_non_youtube_url_keeps_the_real_error(self):
        async def fail_ytdlp(*_args, **_kwargs):
            raise audio_source.ResolveError("yt-dlp exit 1")

        saved = audio_source._run_ytdlp
        saved_precheck = audio_source._is_safe_public_http_url
        audio_source._run_ytdlp = fail_ytdlp
        audio_source._is_safe_public_http_url = lambda _url: True
        try:
            with self.assertRaises(audio_source.ResolveError) as ctx:
                await audio_source.resolve("https://soundcloud.com/artist/track", timeout=1.0)
        finally:
            audio_source._run_ytdlp = saved
            audio_source._is_safe_public_http_url = saved_precheck
        self.assertIn("yt-dlp exit 1", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
