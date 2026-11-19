"""Text helpers shared by bot.py and the cogs.

`split_message` and `clean_social_url` are pure and never touch the client.
"""
from typing import List
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
    if idx == -1:
      idx = max_len
    chunks.append(text[:idx])
    text = text[idx:].lstrip("\n")
  return chunks


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
