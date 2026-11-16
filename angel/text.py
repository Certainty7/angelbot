"""Text helpers shared by bot.py and the cogs.

`split_message` is pure and never touches the client.
"""
from typing import List


def split_message(text: str, max_len: int = 1950) -> List[str]:
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
