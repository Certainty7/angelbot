"""Shared HTTP session pool, bounded stream reader and CPU priority guards."""

import aiohttp
import asyncio
from typing import Optional
from .config import _safe_gc_collect

# 0.5 Shared HTTP Pool, Bounded Stream Reader & CPU Guards (Wispbyte 0.35 vCPU / 612 MiB RAM)
_SHARED_HTTP_SESSION: Optional[aiohttp.ClientSession] = None
_YTDLP_SEMAPHORE = asyncio.Semaphore(1)
_IMAGE_PROC_SEMAPHORE = asyncio.Semaphore(1)
_MEDIA_DOWNLOAD_SEMAPHORE = asyncio.Semaphore(2)
_WORKER_NICED = False


def _lower_worker_cpu_priority():
  # Keep normal CPU scheduling priority (nice 0) on dedicated VPS so 20ms audio frames never stutter
  return


async def get_shared_http_session() -> aiohttp.ClientSession:
  global _SHARED_HTTP_SESSION
  if _SHARED_HTTP_SESSION is None or _SHARED_HTTP_SESSION.closed:
    connector = aiohttp.TCPConnector(
        limit=25,
        ttl_dns_cache=600,
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
  """Stream HTTP body in 64KiB chunks and abort immediately if size exceeds max_bytes to prevent OOM Kill."""
  try:
    cl_header = resp.headers.get("Content-Length")
    if cl_header and cl_header.isdigit():
      cl_val = int(cl_header)
      if cl_val > max_bytes or cl_val < min_bytes:
        return None
    buf = bytearray()
    async for chunk in resp.content.iter_chunked(65536):
      buf.extend(chunk)
      if len(buf) > max_bytes:
        buf.clear()
        _safe_gc_collect()
        return None
    if len(buf) < min_bytes:
      return None
    return bytes(buf)
  except Exception:
    return None
