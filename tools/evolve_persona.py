"""Distil this server's culture from its own messages.

Reads the most recent human lines of the busiest public channel, asks one model for a compact
note (tone / running topics / in-jokes / what to avoid), and stores it per guild. The persona
prompt injects it on every reply, so Angel fits the room instead of sounding like a generic
assistant.

Privacy rules enforced here (the audit's C-005):
  * the database path comes from ANGEL_DB_PATH via angel.config, never a hardcoded file;
  * members who ran `/data delete` are excluded in SQL;
  * the API key travels in the `x-goog-api-key` header, not the query string;
  * a parsed payload must be a dict before it is stored.

The archive does not record a channel *type*, so "the busiest channel" could be a staff room.
Set `ANGEL_PERSONA_CHANNEL_ID` to a channel you know is public; otherwise the tool samples the
busiest one and prints which channel it used.
"""
import json
import os
import pathlib
import sqlite3
import sys
import time
import urllib.error
import urllib.request

MODEL = "gemini-4-hydrogen"
FALLBACK = "gemini-3.5-flash-lite"
SAMPLE = 300


def env(key: str, default: str = "") -> str:
    value = (os.environ.get(key) or "").strip()
    if value:
        return value
    root = pathlib.Path(__file__).resolve().parent.parent
    try:
        for raw in (root / ".env").read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if line.startswith(f"{key}="):
                value = line.split("=", 1)[1].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                return value
    except OSError:
        pass
    return default


def database_path() -> str:
    """ANGEL_DB_PATH, resolved with the same rules as angel.config."""
    import dbpath  # tools/ is on sys.path when a tool runs from the repository root

    return dbpath.resolve()


def ask(model: str, api_key: str, prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    config = {"temperature": 0.3, "maxOutputTokens": 700,
              "responseMimeType": "application/json"}
    if model.startswith(("gemini-4", "gemini-3.1")):
        # These models otherwise spend the whole output budget on their thought stream and
        # come back with no text at all.
        config["thinkingConfig"] = {"thinkingBudget": 0}
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": config,
    }).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.load(r)
    parts = data["candidates"][0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


PROMPT = """اقرأ رسائل أعضاء هذا السيرفر واستخرج "ثقافة المكان" كما يفهمها عضو قديم:
أعد JSON فقط بالشكل:
{"tone": "نبرة الكلام السائدة بجملة واحدة", "topics": ["موضوع دارج", "..."],
 "jokes": ["دعابة أو لقب متكرر", "..."], "avoid": "ما لا يناسب هذا المكان أو يزعج أهله"}
اجعلها قصيرة جداً (كل عنصر أقل من ١٢ كلمة)، وبالعربية كما يتكلمون.
الرسائل:
{lines}"""


def _pick_channel(db) -> sqlite3.Row | None:
    """The channel named by ANGEL_PERSONA_CHANNEL_ID.

    There is no safe automatic choice: the archive records no channel type, so "the busiest
    channel" can be a staff room or a ticket. Refusing is the only defensible default.
    """
    pinned = env("ANGEL_PERSONA_CHANNEL_ID")
    if not pinned.isdigit():
        return None
    return db.execute(
        "SELECT guild_id, channel_id, COUNT(*) n FROM server_messages "
        "WHERE channel_id = ? GROUP BY guild_id, channel_id",
        (int(pinned),),
    ).fetchone()


def main() -> int:
    api_key = env("GEMINI_API_KEY")
    if not api_key:
        print("no GEMINI_API_KEY configured")
        return 2
    db_path = database_path()
    if not os.path.isfile(db_path):
        print(f"database not found: {db_path}")
        return 1
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    top = _pick_channel(db)
    if not top:
        print(
            "refusing to learn: set ANGEL_PERSONA_CHANNEL_ID to a public channel id. "
            "The archive has no channel type, so the tool will not guess."
        )
        return 2

    rows = db.execute(
        "SELECT display_name, content FROM server_messages "
        "WHERE channel_id = ? "
        "AND user_id NOT IN (SELECT user_id FROM user_preferences WHERE opt_out = 1) "
        "ORDER BY created_at DESC LIMIT ?",
        (top["channel_id"], SAMPLE),
    ).fetchall()
    if not rows:
        print("nothing to learn after the privacy filter")
        return 1
    lines = "\n".join(
        f"{r['display_name'] or 'عضو'}: {r['content'][:180]}" for r in reversed(rows)
    )

    payload = None
    for model in (MODEL, FALLBACK):
        try:
            payload = ask(model, api_key, PROMPT.replace("{lines}", lines))
        except urllib.error.HTTPError as exc:
            print(f"{model}: HTTP {exc.code}")
            payload = None
            if exc.code in (429, 503):
                time.sleep(5)
            continue
        except Exception as exc:
            print(f"{model}: {type(exc).__name__}")
            payload = None
            continue
        if not payload:
            print(f"{model}: empty answer")
            payload = None
            continue
        break
    if not payload:
        print("no culture stored: every model failed")
        return 1

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        print("unparsable:", payload[:120])
        return 1
    if not isinstance(parsed, dict):
        # A list or a bare string in this column used to crash every AI reply in the guild.
        print("rejected: the model returned a non-object payload")
        return 1

    db.execute(
        "CREATE TABLE IF NOT EXISTS persona_culture ("
        " guild_id INTEGER PRIMARY KEY, notes_json TEXT, updated_at TEXT)"
    )
    db.execute(
        "INSERT INTO persona_culture (guild_id, notes_json, updated_at) VALUES (?,?,datetime('now')) "
        "ON CONFLICT(guild_id) DO UPDATE SET notes_json=excluded.notes_json, updated_at=datetime('now')",
        (top["guild_id"], json.dumps(parsed, ensure_ascii=False)),
    )
    db.commit()
    print("culture stored:", json.dumps(parsed, ensure_ascii=False)[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
