"""Audit finding 1: untrusted media URLs must pass the SSRF guard.

Regression test for `Certainty7/angelbot-audit` issue 01. A URL that arrives inside a
third-party media response is untrusted: a loopback or metadata literal, or a redirect
to one, must be refused *before* the shared aiohttp session is touched.
"""

from __future__ import annotations

import asyncio

import pytest

from types import SimpleNamespace

from angel import brain, media, net
from angel.net import SafeAsyncResolver


class _RecordingSession:
    """Minimal stand-in for the shared session: records every request attempt."""

    def __init__(self, response=None):
        self.calls: list[str] = []
        self._response = response
        # safe_fetch_response only checks that the session is backed by the connect-time
        # resolver; `__new__` avoids the resolver's event-loop-bound internals.
        self.connector = SimpleNamespace(_resolver=object.__new__(SafeAsyncResolver))

    def get(self, url, **kwargs):
        self.calls.append(str(url))
        if self._response is not None:
            return self._response
        raise RuntimeError("network access attempted for an untrusted URL")


class _Resp:
    def __init__(self, status=200, headers=None, body=b"x" * 4096):
        self.status = status
        self.headers = headers or {}
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read(self, n=-1):
        body, self._body = self._body, b""
        return body


def _patch_session(monkeypatch, session):
    monkeypatch.setattr(net, "get_shared_http_session", _async_return(session))
    monkeypatch.setattr(media, "get_shared_http_session", _async_return(session))
    monkeypatch.setattr(brain, "get_shared_http_session", _async_return(session))


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def test_video_download_refuses_loopback_literal_without_a_request(monkeypatch):
    session = _RecordingSession()
    _patch_session(monkeypatch, session)

    result = asyncio.run(media._download_one_video("http://127.0.0.1:9/video.mp4", {}, 1024 * 1024))

    assert result is None
    assert session.calls == [], f"guard let a request through: {session.calls}"


def test_photo_downloader_refuses_loopback_literal_without_a_request(monkeypatch):
    session = _RecordingSession()
    _patch_session(monkeypatch, session)

    result = asyncio.run(
        media._download_photo_slides(["http://127.0.0.1:9/a.jpg"], 1024 * 1024, "x")
    )

    assert result == []
    assert session.calls == [], f"guard let a request through: {session.calls}"


def test_safe_fetch_response_refuses_redirect_to_loopback(monkeypatch):
    session = _RecordingSession(_Resp(302, {"Location": "http://127.0.0.1:9/secret"}))
    monkeypatch.setattr(net, "get_shared_http_session", _async_return(session))

    with pytest.raises(PermissionError):
        asyncio.run(net.safe_fetch_response("https://cdn.example.com/a.mp4"))

    assert session.calls == ["https://cdn.example.com/a.mp4"]
    assert all("127.0.0.1" not in call for call in session.calls)
