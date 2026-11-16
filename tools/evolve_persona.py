"""Distil this server's culture from its own messages, once a day.

Reads the most recent human lines of the busiest channel, asks one model for a compact note
(tone / running topics / in-jokes / what to avoid), and stores it per guild. The persona prompt
injects it on every reply, so Angel fits the room instead of sounding like a generic assistant.
"""
import json
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
    for line in pathlib.Path(".env").read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return default


def ask(model: str, api_key: str, prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
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
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.load(r)
    parts = data["candidates"][0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts).strip()


PROMPT = """اقرأ رسائل أعضاء هذا السيرفر واستخرج "ثقافة المكان" كما يفهمها عضو قديم:
أعد JSON فقط بالشكل:
{"tone": "نبرة الكلام السائدة بجملة واحدة", "topics": ["موضوع دارج", "..."],
 "jokes": ["دعابة أو لقب متكرر", "..."], "avoid": "ما لا يناسب هذا المكان أو يزعج أهله"}
اجعلها قصيرة جداً (كل عنصر أقل من ١٢ كلمة)، وبالعربية كما يتكلمون.
الرسائل:
{lines}"""


def main() -> int:
    api_key = env("GEMINI_API_KEY")
    db = sqlite3.connect("chat_history.db")
    db.row_factory = sqlite3.Row

    top = db.execute(
        "SELECT guild_id, channel_id, COUNT(*) n FROM server_messages "
        "WHERE created_at > datetime('now','-30 days') "
        "GROUP BY guild_id, channel_id ORDER BY n DESC LIMIT 1"
    ).fetchone()
    if not top:
        print("no history yet")
        return 1

    rows = db.execute(
        "SELECT display_name, content FROM server_messages "
        "WHERE channel_id = ? ORDER BY created_at DESC LIMIT ?",
        (top["channel_id"], SAMPLE),
    ).fetchall()
    lines = "\n".join(f"{r['display_name'] or 'عضو'}: {r['content'][:180]}" for r in reversed(rows))

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
