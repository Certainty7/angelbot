"""Client registry.

`bot.py` installs the client once, right after it is constructed, and package modules call
`get_bot()` instead of reading a module-level placeholder or looking the client up in `globals()`.
`get_bot()` returns None before installation, so the "not wired yet" guards keep their meaning.
"""
from typing import Any, Optional

_bot: Optional[Any] = None


def install(bot) -> None:
  """Bind the client. Called once by bot.py; safe to call again in tests."""
  global _bot
  _bot = bot


def get_bot():
  """The client, or None when bot.py has not installed it yet."""
  return _bot
