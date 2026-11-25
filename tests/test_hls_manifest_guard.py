"""Audit finding 15: a manifest must not be able to point FFmpeg at a private URL.

Angel validates the top-level stream URL, but an HLS manifest is a second request the
validator never sees: FFmpeg reads the playlist and then fetches whatever segment and key
URLs it names. The reproduction pointed a manifest at ``http://127.0.0.1:<port>/segment.ts``
and FFmpeg requested it.

The policy under test: progressive media keeps working, and a manifest is refused unless its
host is explicitly trusted through ``ANGEL_HLS_HOSTS``. That is the reachable production
boundary — no supported source is allowlisted by default, so nothing can smuggle a private
segment URL through a manifest.
"""

import asyncio
import unittest
from unittest import mock

import angel.net as net
from angel import voice_engine


async def _public_dns(_host, _port):
    return ["93.184.216.34"]


async def _private_dns(_host, _port):
    return ["127.0.0.1"]


class HlsManifestPolicyTest(unittest.TestCase):
    def test_a_manifest_is_refused_by_default(self):
        async def _run():
            for url in (
                "https://cdn.example.com/live/index.m3u8",
                "https://cdn.example.com/live/index.M3U8?token=x",
                "https://cdn.example.com/radio.m3u",
            ):
                with self.subTest(url=url):
                    with self.assertRaises(PermissionError):
                        await net.validate_extracted_stream_url(url, resolver_fn=_public_dns)

        asyncio.run(_run())

    def test_a_trusted_manifest_host_is_allowed(self):
        async def _run():
            with mock.patch.object(net, "HLS_ALLOWED_HOSTS", frozenset({"cdn.example.com"})):
                url = "https://cdn.example.com/live/index.m3u8"
                self.assertEqual(
                    await net.validate_extracted_stream_url(url, resolver_fn=_public_dns), url
                )
                with self.assertRaises(PermissionError):
                    await net.validate_extracted_stream_url(
                        "https://other.example.com/live/index.m3u8", resolver_fn=_public_dns
                    )

        asyncio.run(_run())

    def test_a_trusted_host_cannot_be_a_private_address(self):
        async def _run():
            with mock.patch.object(net, "HLS_ALLOWED_HOSTS", frozenset({"127.0.0.1"})):
                with self.assertRaises(PermissionError):
                    await net.validate_extracted_stream_url(
                        "http://127.0.0.1:9/segment.m3u8", resolver_fn=_private_dns
                    )
            with mock.patch.object(net, "HLS_ALLOWED_HOSTS", frozenset({"media.example.com"})):
                with self.assertRaises(PermissionError):
                    await net.validate_extracted_stream_url(
                        "https://media.example.com/x.m3u8", resolver_fn=_private_dns
                    )

        asyncio.run(_run())

    def test_progressive_media_is_unaffected(self):
        async def _run():
            url = "https://cdn.example.com/audio.webm"
            self.assertEqual(
                await net.validate_extracted_stream_url(url, resolver_fn=_public_dns), url
            )

        asyncio.run(_run())

    def test_the_ffmpeg_protocol_whitelist_names_no_local_protocol(self):
        whitelist = voice_engine.FFMPEG_BEFORE.split("-protocol_whitelist", 1)[1].split()[0]
        protocols = {p.strip() for p in whitelist.split(",")}
        self.assertEqual(protocols, {"https", "http", "tcp", "tls", "crypto"})
        for forbidden in ("file", "data", "concat", "subfile", "pipe"):
            self.assertNotIn(forbidden, protocols)


if __name__ == "__main__":
    unittest.main()
