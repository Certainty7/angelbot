"""Text helpers shared by bot.py and the cogs.

`split_message`, `plan_reply_delivery` and `clean_social_url` are pure and never touch
the client.
"""
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TIKTOK_TRACKING_PARAMS = {"is_from_webapp", "sender_device", "web_id", "lang", "u_code", "preview_pb"}
# Exact names only: `story_fbid`, `tab`, `type` and `sort` are meaningful Facebook params and
# must survive; a prefix match on "s"/"t" used to destroy them.
SOCIAL_TRACKING_EXACT = {
    "s", "t", "si", "ref", "igsh", "igshid", "ig_mid", "fbclid", "feature",
    "share", "share_app_id", "share_link_id", "share_source",
}
SOCIAL_TRACKING_PREFIXES = ("utm_", "ref_", "ga_")


def split_message(text: str, max_len: int = 1950) -> List[str]:
  if max_len <= 0:
    raise ValueError("max_len must be positive")
  chunks = []
  while text:
    if len(text) <= max_len:
      chunks.append(text)
      break
    idx = text.rfind("\n", 0, max_len)
    if idx <= 0:
      idx = max_len
    chunks.append(text[:idx])
    text = text[idx:].lstrip("\n")
  return [chunk for chunk in chunks if chunk.strip()]


def plan_reply_delivery(
    reply: str, gif_bytes: Optional[bytes], gif_url: Optional[str], img_bytes: Optional[bytes]
):
  """How a model reply reaches Discord, or None when nothing should be sent.

  An image-only or GIF-only reply (`[GENERATE_IMAGE: ...]` with no prose) is a valid
  outcome: the media is delivered without text. A reply with neither visible text nor
  deliverable media stays silent instead of inventing a fallback line.
  Returns (first_chunk, rest_chunks, has_files, use_gif_url).
  """
  text = (reply or "").strip()
  has_files = bool(img_bytes or gif_bytes)
  use_gif_url = bool(gif_url and not gif_bytes)
  if not (text or has_files or use_gif_url):
    return None
  chunks = split_message(text) if text else []
  return (chunks[0] if chunks else None, chunks[1:], has_files, use_gif_url)


def clean_social_url(url: str) -> str:
  """Drop tracking parameters so the same post is one key, and the extractor sees a plain path."""
  try:
    parts = urlsplit(url.strip())
  except ValueError:
    return url
  if not parts.query:
    return url
  kept = [
    (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
    if k.lower() not in TIKTOK_TRACKING_PARAMS
    and k.lower() not in SOCIAL_TRACKING_EXACT
    and not k.lower().startswith(SOCIAL_TRACKING_PREFIXES)
  ]
  return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))
