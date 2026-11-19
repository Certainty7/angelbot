"""Shared HTTP session pool, SSRF guards and bounded stream readers.

Every outbound request the bot makes goes through this module. The rules here are
deliberate and must not be relaxed:

  * only http/https, no userinfo, no control characters, no non-canonical IPv4;
  * every resolved address must be globally routable (no loopback, RFC1918,
    link-local, CGNAT, Teredo/6to4, NAT64, cloud metadata);
  * redirects are followed manually so every hop is validated again;
  * response bodies are bounded before they are buffered.

`SafeAsyncResolver` enforces the same check at aiohttp connect time, which closes
the DNS-rebinding window between a pre-flight lookup and the real connection.
"""

import asyncio
import ipaddress
import re
import socket
import weakref
from typing import Iterable, Optional, Tuple
from urllib.parse import urljoin, urlparse

import aiohttp
from aiohttp.abc import AbstractResolver

from .config import logger

# 0.5 Shared HTTP Pool, Bounded Stream Reader & CPU Guards (small single-core host)
_SHARED_HTTP_SESSION: Optional[aiohttp.ClientSession] = None
_SESSION_LOCK: Optional[asyncio.Lock] = None
# An asyncio.Semaphore binds to the loop that first waits on it. A module-level
# instance created at import time breaks the next `asyncio.run()` (tests, CLI jobs),
# so each running loop gets its own bounded set.
_SEMAPHORES: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict]" = weakref.WeakKeyDictionary()
_WORKER_NICED = False


def _semaphore(name: str, limit: int) -> asyncio.Semaphore:
  loop = asyncio.get_running_loop()
  per_loop = _SEMAPHORES.get(loop)
  if per_loop is None:
    per_loop = {}
    _SEMAPHORES[loop] = per_loop
  sem = per_loop.get(name)
  if sem is None:
    sem = per_loop[name] = asyncio.Semaphore(limit)
  return sem


def get_ytdlp_semaphore() -> asyncio.Semaphore:
  return _semaphore("ytdlp", 1)


def get_image_proc_semaphore() -> asyncio.Semaphore:
  return _semaphore("image", 1)


def get_media_download_semaphore() -> asyncio.Semaphore:
  return _semaphore("media", 2)

_MAX_REDIRECT_HOPS = 4
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_SENSITIVE_REDIRECT_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})

_NAT64_NET = ipaddress.IPv6Network("64:ff9b::/96")
_NAT64_LOCAL_NET = ipaddress.IPv6Network("64:ff9b:1::/48")
_IPV4_TRANSLATED_NET = ipaddress.IPv6Network("::ffff:0:0:0/96")
_EXTRA_NON_PUBLIC_NETS = (
    ipaddress.ip_network("192.88.99.0/24"),
    ipaddress.ip_network("3fff::/20"),
)
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".arpa")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_IG_SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]{5,64}$")


def _lower_worker_cpu_priority():
  # Keep normal CPU scheduling priority (nice 0) on dedicated VPS so 20ms audio frames never stutter
  return


def _strip_zone_id(ip_str: str) -> str:
  return ip_str.split("%", 1)[0].strip()


def _is_noncanonical_ipv4(host: str) -> bool:
  """Detect decimal/hex/octal/short IPv4 forms such as 2130706433 or 127.1."""
  labels = host.split(".")
  if not labels or len(labels) > 4:
    return False
  if not all(re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)", lbl) for lbl in labels):
    return False
  if len(labels) == 4 and all(
      lbl == "0" or (lbl.isdigit() and not lbl.startswith("0")) for lbl in labels
  ):
    return False
  return True


def is_public_ip(ip_str: str) -> bool:
  """True only for a globally routable IP address."""
  cleaned = _strip_zone_id(ip_str or "")
  if not cleaned:
    return False
  try:
    ip = ipaddress.ip_address(cleaned)
  except ValueError:
    return False
  if isinstance(ip, ipaddress.IPv6Address):
    if ip.ipv4_mapped is not None:
      return is_public_ip(str(ip.ipv4_mapped))
    if ip.sixtofour is not None:
      return is_public_ip(str(ip.sixtofour))
    if ip.teredo is not None:
      server_ip, client_ip = ip.teredo
      return is_public_ip(str(server_ip)) and is_public_ip(str(client_ip))
    if ip in _NAT64_NET or ip in _NAT64_LOCAL_NET or ip in _IPV4_TRANSLATED_NET:
      return False
  if any(ip in net for net in _EXTRA_NON_PUBLIC_NETS if net.version == ip.version):
    return False
  return (
      ip.is_global
      and not ip.is_private
      and not ip.is_loopback
      and not ip.is_link_local
      and not ip.is_multicast
      and not ip.is_reserved
      and not ip.is_unspecified
  )


def _safe_parse_url(url: str):
  if not url or not isinstance(url, str):
    return None
  if _CONTROL_CHAR_RE.search(url):
    return None
  try:
    parsed = urlparse(url)
    _ = parsed.port
  except ValueError:
    return None
  return parsed


def is_valid_http_url_syntax(url: str) -> bool:
  """Syntactic gate applied before DNS resolution or a subprocess is spawned."""
  if not url or url.startswith("-"):
    return False
  parsed = _safe_parse_url(url)
  if parsed is None or parsed.scheme.lower() not in _ALLOWED_SCHEMES:
    return False
  if parsed.username is not None or parsed.password is not None:
    return False
  host = (parsed.hostname or "").lower().rstrip(".")
  if not host or host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
    return False
  if _is_noncanonical_ipv4(host):
    return False
  try:
    ipaddress.ip_address(_strip_zone_id(host))
    return is_public_ip(host)
  except ValueError:
    return True


def is_allowed_hostname(url: str, allowed_domains: Iterable[str]) -> bool:
  """Exact/suffix hostname match; never a substring match."""
  if not is_valid_http_url_syntax(url):
    return False
  parsed = _safe_parse_url(url)
  if parsed is None:
    return False
  host = (parsed.hostname or "").lower().rstrip(".")
  for domain in allowed_domains:
    d = domain.lower().strip().lstrip(".").rstrip(".")
    if d and (host == d or host.endswith("." + d)):
      return True
  return False


def rewrite_mirror_host(url: str, mirror_map: dict) -> str:
  """Rewrite a mirror hostname on the netloc only, never inside path/query."""
  parsed = _safe_parse_url(url)
  if parsed is None or parsed.username is not None or parsed.password is not None:
    return url
  host = (parsed.hostname or "").lower().rstrip(".")
  if host not in mirror_map:
    return url
  target = mirror_map[host]
  if ":" in target and not target.startswith("["):
    target = f"[{target}]"
  try:
    port = parsed.port
  except ValueError:
    return url
  port_part = f":{port}" if port else ""
  return parsed._replace(netloc=f"{target}{port_part}").geturl()


def validate_ig_shortcode(shortcode: str) -> str:
  if not _IG_SHORTCODE_RE.fullmatch(shortcode or ""):
    raise ValueError(f"Invalid Instagram shortcode: {shortcode!r}")
  return shortcode


def _validate_resolved(host: str, addrs: Iterable[str]) -> list:
  resolved = list(dict.fromkeys(addrs))
  if not resolved:
    raise PermissionError(f"SSRF blocked: DNS returned no addresses for {host!r}")
  for addr in resolved:
    if not is_public_ip(addr):
      raise PermissionError(f"SSRF blocked: {host!r} resolved to non-public IP {addr!r}")
  return resolved


def is_safe_public_http_url_sync(url: str) -> bool:
  """Blocking SSRF check used where a sync predicate is needed (e.g. executors)."""
  if not is_valid_http_url_syntax(url):
    return False
  host = (urlparse(url).hostname or "").lower().rstrip(".")
  try:
    ipaddress.ip_address(_strip_zone_id(host))
    return is_public_ip(host)
  except ValueError:
    pass
  try:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
  except OSError:
    return False
  addrs = [info[4][0] for info in infos]
  try:
    _validate_resolved(host, addrs)
    return True
  except PermissionError:
    return False


async def resolve_and_validate_host(host: str, port: int = 443, *, resolver_fn=None) -> list:
  """Resolve via DNS and require EVERY returned address to be public."""
  cleaned = (host or "").strip().rstrip(".").lower()
  if not cleaned:
    raise PermissionError("SSRF blocked: empty hostname")
  if cleaned == "localhost" or cleaned.endswith(_BLOCKED_HOST_SUFFIXES):
    raise PermissionError(f"SSRF blocked: forbidden hostname {host!r}")
  if _is_noncanonical_ipv4(cleaned):
    raise PermissionError(f"SSRF blocked: non-canonical IPv4 {host!r}")
  try:
    ipaddress.ip_address(_strip_zone_id(cleaned))
    if not is_public_ip(cleaned):
      raise PermissionError(f"SSRF blocked: non-public literal IP {host!r}")
    return [cleaned]
  except ValueError:
    pass

  if resolver_fn is not None:
    addrs = await resolver_fn(cleaned, port)
  else:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(cleaned, port, type=socket.SOCK_STREAM)
    addrs = [info[4][0] for info in infos]
  return _validate_resolved(cleaned, addrs)


class SafeAsyncResolver(AbstractResolver):
  """aiohttp resolver that refuses private addresses at connect time."""

  def __init__(self, inner: Optional[AbstractResolver] = None) -> None:
    self._inner = inner or aiohttp.DefaultResolver()

  async def resolve(self, host: str, port: int = 0, family: int = 0) -> list:
    results = await self._inner.resolve(host, port, family)
    safe = []
    for entry in results:
      if not is_public_ip(entry.get("host", "")):
        raise PermissionError(f"SSRF blocked: resolved non-public IP for {host!r}")
      safe.append(entry)
    if not safe:
      raise PermissionError(f"SSRF blocked: no public IP resolved for {host!r}")
    return safe

  async def close(self) -> None:
    await self._inner.close()


def _session_lock() -> asyncio.Lock:
  global _SESSION_LOCK
  if _SESSION_LOCK is None:
    _SESSION_LOCK = asyncio.Lock()
  return _SESSION_LOCK


async def get_shared_http_session() -> aiohttp.ClientSession:
  global _SHARED_HTTP_SESSION
  async with _session_lock():
    if _SHARED_HTTP_SESSION is None or _SHARED_HTTP_SESSION.closed:
      connector = aiohttp.TCPConnector(
          resolver=SafeAsyncResolver(),
          limit=25,
          ttl_dns_cache=30,
          enable_cleanup_closed=True,
          keepalive_timeout=30,
      )
      _SHARED_HTTP_SESSION = aiohttp.ClientSession(
          connector=connector,
          timeout=aiohttp.ClientTimeout(total=25),
      )
    return _SHARED_HTTP_SESSION


async def close_shared_http_session():
  global _SHARED_HTTP_SESSION
  if _SHARED_HTTP_SESSION and not _SHARED_HTTP_SESSION.closed:
    try:
      await _SHARED_HTTP_SESSION.close()
    except Exception:
      pass
  _SHARED_HTTP_SESSION = None


async def read_bounded_stream(
    resp: aiohttp.ClientResponse,
    max_bytes: int = 10 * 1024 * 1024,
    min_bytes: int = 1,
) -> Optional[bytes]:
  """Read a response body, refusing to buffer more than max_bytes."""
  if max_bytes <= 0:
    raise ValueError("max_bytes must be positive")
  try:
    cl_header = resp.headers.get("Content-Length")
    if cl_header and cl_header.isdigit():
      cl_val = int(cl_header)
      if cl_val > max_bytes or cl_val < min_bytes:
        return None
    buf = bytearray()
    async for chunk in resp.content.iter_chunked(65536):
      if len(buf) + len(chunk) > max_bytes:
        return None
      buf.extend(chunk)
    if len(buf) < min_bytes:
      return None
    return bytes(buf)
  except Exception as exc:
    logger.debug("bounded stream read failed: %s: %s", type(exc).__name__, exc)
    return None


def _strip_sensitive_headers(headers: Optional[dict], prev_url: str, next_url: str) -> Optional[dict]:
  if not headers:
    return headers
  p1, p2 = urlparse(prev_url), urlparse(next_url)
  same_origin = (
      p1.scheme.lower() == p2.scheme.lower()
      and (p1.hostname or "").lower() == (p2.hostname or "").lower()
      and p1.port == p2.port
  )
  if same_origin:
    return headers
  return {k: v for k, v in headers.items() if k.lower() not in _SENSITIVE_REDIRECT_HEADERS}


async def _safe_session_or_shared(session) -> aiohttp.ClientSession:
  """Reject injected sessions that would bypass the connect-time SSRF resolver."""
  if session is None:
    return await get_shared_http_session()
  connector = getattr(session, "connector", None)
  if not isinstance(getattr(connector, "_resolver", None), SafeAsyncResolver):
    raise PermissionError("custom HTTP session must use SafeAsyncResolver")
  return session


async def safe_fetch_bytes(
    url: str,
    *,
    allowed_domains: Optional[Iterable[str]] = None,
    max_bytes: int = 8 * 1024 * 1024,
    max_hops: int = _MAX_REDIRECT_HOPS,
    headers: Optional[dict] = None,
    session=None,
) -> Tuple[str, int, bytes]:
  """GET a URL following redirects manually, validating every hop."""
  sess = await _safe_session_or_shared(session)
  current_url = url
  req_headers = dict(headers) if headers else None

  for _hop in range(max_hops + 1):
    if not is_valid_http_url_syntax(current_url):
      raise PermissionError(f"Blocked invalid/unsafe URL: {current_url!r}")
    if allowed_domains is not None and not is_allowed_hostname(current_url, allowed_domains):
      raise PermissionError(f"Blocked disallowed host: {current_url!r}")

    async with sess.get(current_url, headers=req_headers, allow_redirects=False) as resp:
      if resp.status in {301, 302, 303, 307, 308}:
        loc = resp.headers.get("Location")
        if not loc:
          raise PermissionError("Redirect response missing Location header")
        next_url = urljoin(current_url, loc)
        req_headers = _strip_sensitive_headers(req_headers, current_url, next_url)
        current_url = next_url
        continue
      data = await read_bounded_stream(resp, max_bytes=max_bytes)
      if data is None:
        raise ValueError(f"Response exceeded {max_bytes} bytes limit")
      return current_url, resp.status, data

  raise PermissionError(f"Exceeded max redirect hops ({max_hops})")


async def safe_fetch_text(
    url: str,
    *,
    allowed_domains: Optional[Iterable[str]] = None,
    max_bytes: int = 4 * 1024 * 1024,
    headers: Optional[dict] = None,
    session=None,
) -> Tuple[str, int, str]:
  """Like safe_fetch_bytes, decoded as UTF-8 for HTML/JSON scraping."""
  final_url, status, data = await safe_fetch_bytes(
      url,
      allowed_domains=allowed_domains,
      max_bytes=max_bytes,
      headers=headers,
      session=session,
  )
  return final_url, status, data.decode("utf-8", "replace")


async def safe_fetch_response(    url: str,
    *,
    allowed_domains: Optional[Iterable[str]] = None,
    max_bytes: int = 10 * 1024 * 1024,
    headers: Optional[dict] = None,
    session=None,
) -> Tuple[str, int, str, Optional[bytes]]:
  """GET with manual redirects; returns (final_url, status, content_type, body)."""
  sess = await _safe_session_or_shared(session)
  current_url = url
  req_headers = dict(headers) if headers else None

  for _hop in range(_MAX_REDIRECT_HOPS + 1):
    if not is_valid_http_url_syntax(current_url):
      raise PermissionError(f"Blocked invalid/unsafe URL: {current_url!r}")
    if allowed_domains is not None and not is_allowed_hostname(current_url, allowed_domains):
      raise PermissionError(f"Blocked disallowed host: {current_url!r}")
    async with sess.get(current_url, headers=req_headers, allow_redirects=False) as resp:
      if resp.status in {301, 302, 303, 307, 308}:
        loc = resp.headers.get("Location")
        if not loc:
          raise PermissionError("Redirect response missing Location header")
        next_url = urljoin(current_url, loc)
        req_headers = _strip_sensitive_headers(req_headers, current_url, next_url)
        current_url = next_url
        continue
      ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
      if resp.status != 200:
        return current_url, resp.status, ctype, None
      return current_url, resp.status, ctype, await read_bounded_stream(resp, max_bytes=max_bytes)

  raise PermissionError(f"Exceeded max redirect hops ({_MAX_REDIRECT_HOPS})")


async def validate_extracted_stream_url(
    stream_url: str,
    *,
    allowed_domains: Optional[Iterable[str]] = None,
    resolver_fn=None,
) -> str:
  """Validate a yt-dlp stream URL, including DNS, before it reaches FFmpeg."""
  if not is_valid_http_url_syntax(stream_url):
    raise PermissionError(f"Rejected unsafe extracted stream_url: {stream_url!r}")
  if allowed_domains is not None and not is_allowed_hostname(stream_url, allowed_domains):
    raise PermissionError(f"Rejected disallowed stream host: {stream_url!r}")
  parsed = urlparse(stream_url)
  host = (parsed.hostname or "").lower()
  port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
  await resolve_and_validate_host(host, port, resolver_fn=resolver_fn)
  return stream_url


__all__ = [
    "SafeAsyncResolver",
    "close_shared_http_session",
    "get_image_proc_semaphore",
    "get_media_download_semaphore",
    "get_shared_http_session",
    "get_ytdlp_semaphore",
    "is_allowed_hostname",
    "is_public_ip",
    "is_safe_public_http_url_sync",
    "is_valid_http_url_syntax",
    "read_bounded_stream",
    "resolve_and_validate_host",
    "rewrite_mirror_host",
    "safe_fetch_bytes",
    "safe_fetch_response",
    "safe_fetch_text",
    "validate_extracted_stream_url",
    "validate_ig_shortcode",
]
