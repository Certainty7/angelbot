"""Test isolation: synthetic credentials, a temp database, and no real network.

Imported before every test module, so `angel.config` resolves with fixture values even when
the developer's shell has no production `.env`. Nothing here reads or writes a real database.
"""
import os
import socket
import tempfile

# Force, never setdefault: a developer shell with a production ANGEL_DB_PATH must not point
# the suite at live data.
_TMP_ROOT = tempfile.mkdtemp(prefix="angel-tests-")
os.environ["ANGEL_DB_PATH"] = os.path.join(_TMP_ROOT, "test.db")
# The synthetic owner is forced too: `setdefault` preserved a shell value like 123 and
# the hierarchy tests, which assert on member 42, failed for a reason no test could see.
os.environ["ANGEL_OWNER_ID"] = "42"
os.environ["ANGEL_AUTO_INSTALL"] = "0"
# Credentials are scrubbed by setting explicit empty values, not by popping the keys:
# `angel.config` calls `load_dotenv()` at import, and dotenv happily re-fills *absent*
# keys from a populated checkout `.env` — in this process and in every child `run_python`
# process, which inherits these empties and is therefore immune to the same restore.
for _secret in ("DISCORD_TOKEN", "GEMINI_API_KEY", "GEMINI_API_KEY_2", "CLOUDFLARE_API_TOKEN"):
    os.environ[_secret] = ""


class NetworkBlocked(RuntimeError):
    """Raised when a test tries to reach a real host."""


def _is_loopback(host) -> bool:
    text = str(host or "")
    return text in {"", "localhost", "127.0.0.1", "::1"} or text.startswith("127.")


if os.environ.get("ANGEL_TESTS_ALLOW_NETWORK") != "1":
    _real_connect = socket.socket.connect

    def _guarded_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if not _is_loopback(host):
            raise NetworkBlocked(f"outbound connection blocked in tests: {host!r}")
        return _real_connect(self, address, *args, **kwargs)

    socket.socket.connect = _guarded_connect

    _real_getaddrinfo = socket.getaddrinfo

    def _guarded_getaddrinfo(host, *args, **kwargs):
        if not _is_loopback(host):
            raise NetworkBlocked(f"DNS lookup blocked in tests: {host!r}")
        return _real_getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = _guarded_getaddrinfo
