"""Resolve ANGEL_DB_PATH exactly like the bot does, without importing angel.config.

`angel.config` refuses to import without ANGEL_OWNER_ID, and an operator tool should not need
the owner id (or a Discord token) just to find the database file. The rules here mirror it:
environment first, then `.env` in the repository root, with `export ` prefixes and quotes
handled the way python-dotenv handles them.
"""
import os
import pathlib


def _clean(value: str) -> str:
    text = (value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1]
    return text.strip()


def _from_env_file(root: pathlib.Path, key: str) -> str:
    try:
        lines = (root / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("export "):
            stripped = stripped[len("export "):].strip()
        if not stripped.startswith(f"{key}="):
            continue
        return _clean(stripped.split("=", 1)[1])
    return ""


def resolve() -> str:
    root = pathlib.Path(__file__).resolve().parent.parent
    configured = _clean(os.environ.get("ANGEL_DB_PATH") or "")
    if configured:
        return configured
    from_file = _from_env_file(root, "ANGEL_DB_PATH")
    return from_file or str(root / "chat_history.db")
