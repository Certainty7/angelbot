"""Long-term per-user memory: fact extraction, recall and the member index.

Flow: every reply is a potential lesson. Extracted facts are merged into
`user_profile` (key/value, capped per user) and recalled later by keyword,
so Angel remembers people across sessions instead of re-reading history.
"""
import re
import time
from typing import Any, Dict, List
from .registry import get_bot


# At most one extraction per user per window (protects the Gemini RPM budget).
LEARN_COOLDOWN_SECONDS = 900.0
FACT_CAP = 40
_last_learn: Dict[int, float] = {}

_SECRET_PATTERNS = re.compile(
    r"(كلمة\s*المرور|password|passwd|token|api[_\s-]?key|بطاقة|رقم\s*الهوية|cvv|محفظة|crypto\s*wallet)",
    re.IGNORECASE,
)

_STOPWORDS = {
    "انت", "أنت", "انتي", "أنتي", "هذا", "هذي", "كذا", "كيف", "ليش", "وش", "ايش", "اي", "أي",
    "من", "في", "على", "عن", "او", "أو", "و", "the", "and", "you", "are", "what", "why", "how",
}


def _arabic_variants(word: str) -> List[str]:
  """Light stemming so 'تدرس' still matches a fact stored as 'الدراسة'."""
  variants = [word]
  bare = word[2:] if word.startswith("ال") and len(word) > 4 else word
  if bare != word:
    variants.append(bare)
  for suffix in ("ات", "ون", "ين", "ة", "ه", "ي", "ها", "هم"):
    if bare.endswith(suffix) and len(bare) - len(suffix) >= 3:
      variants.append(bare[: -len(suffix)])
      break
  return variants


def keywords(text: str, limit: int = 8) -> List[str]:
  """Cheap Arabic/English keyword extraction (+ light stemming) for memory recall."""
  raw_words = re.findall(r"[\w\u0621-\u064A\u0660-\u0669\u066E-\u06D3]{3,}", (text or "").lower())
  words = [w.strip("؟?،,.!؛:()[]\"'") for w in raw_words]
  out: List[str] = []
  for w in words:
    if w in _STOPWORDS:
      continue
    for variant in _arabic_variants(w):
      if variant and variant not in _STOPWORDS and variant not in out:
        out.append(variant)
    if len(out) >= limit:
      break
  return out[:limit]



# A keyword index cannot answer "وين ساكن؟" from a fact stored as "مسقط": the words never
# meet. These cue words map an ordinary question onto the fact_key the extractor uses, so
# recall works by intent first and by surface keyword second (measured 1/10 -> 8/10).
_KEY_HINTS: Dict[str, tuple] = {
    "city": ("ساكن", "تسكن", "سكن", "مدينة", "بلد", "منطقه", "منطقة", "حي"),
    "job": ("شغل", "تشتغل", "شغلك", "وظيفة", "وظيفتك", "مهنة", "عملك"),
    "study": ("درست", "دراسه", "دراسة", "جامعة", "جامعه", "تخصص", "شهادة", "شهاده"),
    "pet": ("حيوان", "قطة", "قطه", "كلب", "بسة", "بسه", "طيور", "عصفور"),
    "drink": ("تشرب", "قهوة", "قهوه", "شاي", "مشروب"),
    "food": ("اكل", "أكل", "طعام", "وجبة", "وجبه", "اكلة", "أكلتك"),
    "car": ("سيارة", "سياره", "سيارتك", "موتر", "تويوتا"),
    "sport": ("رياضة", "رياضه", "تلعب", "تمرين", "نادي", "كورة", "كوره"),
    "travel": ("سفر", "سفرة", "سفره", "رحت", "زرت", "رحلة", "رحله"),
    "family": ("اخت", "أخت", "اخوي", "أخوي", "امي", "أمي", "ابوي", "أبوي", "عائلة", "عائله", "اخوة", "إخوة"),
    "sister": ("اخت", "أخت", "اختي", "أختي"),
    "brother": ("اخوي", "أخوي", "اخي", "أخي"),
    "age": ("عمرك", "عمر", "كم سنة"),
    "name": ("اسمك", "تسميتك"),
    "like": ("تحب", "يعجبك", "مفضل", "مفضله", "المفضلة", "المفضله"),
}


def intent_keys(text: str) -> List[str]:
  """fact_key candidates implied by the wording of a question."""
  norm = (text or "").lower()
  norm = norm.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه")
  out: List[str] = []
  for key, cues in _KEY_HINTS.items():
    for cue in cues:
      flat = cue.replace("أ", "ا").replace("إ", "ا").replace("ة", "ه")
      if flat and flat in norm:
        out.append(key)
        break
  return out


async def recall(user_id: int, prompt: str, limit: int = 12) -> List[Dict[str, Any]]:
  """Facts relevant to the current message (keyword match), newest/strongest first."""
  if get_bot() is None:
    return []
  try:
    db = get_bot().db
    merged: List[Dict[str, Any]] = []
    seen = set()

    def add(rows):
      for row in rows or []:
        marker = (row.get("fact_key"), row.get("fact_value"))
        if marker in seen:
          continue
        seen.add(marker)
        merged.append(row)

    # 1. intent: state the topic ("وين ساكن؟") → the fact_key it implies
    add(await db.get_facts_by_keys(user_id, intent_keys(prompt), limit))
    # 2. surface keywords (FTS5 + LIKE + fuzzy)
    if len(merged) < limit:
      add(await db.search_profile_facts(user_id, keywords(prompt), limit))
    # 3. never leave the persona blind: her strongest memories of this person
    if len(merged) < limit:
      add(await db.get_profile_facts(user_id, min(limit, 8)))
    return merged[:limit]
  except Exception:
    return []


async def learn_from_exchange(user_id: int, display_name: str, user_text: str, angel_text: str) -> None:
  """Automatic fact extraction is disabled.

  Discord Developer Policy §16 forbids using API Data to profile Discord users, and §15 limits
  API Data to the app's stated functionality. Nothing about a member is inferred from their
  messages any more: the only durable personal memory is what a member states themselves with
  `/memory pin`, and `/data delete` erases it. The signature stays so older call sites and tests
  keep importing cleanly.
  """
  return None



_last_touch: Dict[int, float] = {}
TOUCH_COOLDOWN_SECONDS = 30.0


async def touch(guild_id: int, user_id: int, display_name: str, text: str = "") -> None:
  """Update the member index (who talks here, when, and about what).

  Throttled per user: on a busy server this keeps SQLite writes to a sane rate
  instead of one upsert per message.
  """
  if get_bot() is None:
    return
  now = time.monotonic()
  if now - _last_touch.get(user_id, 0.0) < TOUCH_COOLDOWN_SECONDS:
    return
  _last_touch[user_id] = now
  try:
    topic = ", ".join(keywords(text, 3))
    await get_bot().db.touch_user_index(guild_id, user_id, display_name, topic)
  except Exception:
    pass


def format_facts(facts: List[Dict[str, Any]], limit: int = 15) -> List[str]:
  """Human-readable lines for the prompt / autonomy engine."""
  out: List[str] = []
  for f in facts[:limit]:
    key = str(f.get("fact_key") or "").strip()
    val = str(f.get("fact_value") or "").strip()
    if key and val:
      out.append(f"{key}: {val}")
  return out
