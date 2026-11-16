"""Rule-based triage: what is worth remembering, without calling the model."""
import re
from dataclasses import dataclass, field
from typing import List, Tuple

FACT_PATTERNS: List[Tuple[re.Pattern, str, float]] = [
    (re.compile(r"(?:اسمي|يدعوني|ينادوني)\s+([\w\u0621-\u064A][\w\u0621-\u064A\s]{1,24})", re.I), "الاسم", 0.85),
    (re.compile(r"(?:أنا|انا)\s+من\s+([\w\u0621-\u064A\s]{2,25})", re.I), "الموطن", 0.8),
    (re.compile(r"(?:أسكن|اسكن|ساكن|مقيم)\s+(?:في|ب)\s*([\w\u0621-\u064A\s]{2,25})", re.I), "السكن", 0.8),
    (re.compile(r"(?:عمري)\s+(\d{1,2})\s*(?:سنة|سنه)?", re.I), "العمر", 0.8),
    (re.compile(r"(?:أشتغل|اشتغل|شغلي|وظيفتي|أعمل|اعمل)\s+(?:في|ب|ك)?\s*([\w\u0621-\u064A\s]{2,30})", re.I), "العمل", 0.8),
    (re.compile(r"(?:أدرس|ادرس|دراستي|تخصصي)\s+(?:في|ب)?\s*([\w\u0621-\u064A\s]{2,30})", re.I), "الدراسة", 0.8),
    (re.compile(r"(?:أحب|احب|أعشق|اعشق)\s+([\w\u0621-\u064A\s]{2,30})", re.I), "يحب", 0.75),
    (re.compile(r"(?:أكره|اكره|ما أحب|ما احب)\s+([\w\u0621-\u064A\s]{2,30})", re.I), "يكره", 0.75),
]

QUESTION_RE = re.compile(r"[?؟]\s*$|^(?:وش|ايش|ليش|كيف|متى|وين|هل|منو|مين)\b", re.I)
NOISE_RE = re.compile(r"^(?:هه+|هاها+|😂+|🤣+|ok|اوك|okay)$", re.I)


@dataclass
class Triage:
    store: bool = False
    facts: List[Tuple[str, str, float]] = field(default_factory=list)
    is_question: bool = False
    is_noise: bool = False
    score_hint: float = 0.0


def clean(value: str) -> str:
    """Trim a captured value to a single fact (stop before the next 'و + verb' clause)."""
    value = re.split(r"\s+و(?=[\u0621-\u064A]{3,})", value or "")[0]
    value = re.sub(r"\s+", " ", value).strip(" .,!،؟?\n\t")
    return " ".join(value.split()[:4])


def triage(text: str) -> Triage:
    raw = (text or "").strip()
    t = Triage()
    if not raw:
        t.is_noise = True
        return t
    t.is_question = bool(QUESTION_RE.search(raw))
    t.is_noise = bool(NOISE_RE.match(raw)) or len(raw) < 4

    for pattern, key, conf in FACT_PATTERNS:
        m = pattern.search(raw)
        if not m:
            continue
        value = clean(m.group(m.lastindex) if m.lastindex else m.group(0))
        if not (2 <= len(value) <= 60):
            continue
        if value in {"انا", "أنا", "هو", "هي", "شي", "كذا"}:
            continue
        t.facts.append((key, value, conf))

    t.store = bool(t.facts) or (len(raw) >= 40 and not t.is_noise)
    t.score_hint = 0.7 if t.facts else (0.5 if t.is_question else 0.3 if not t.is_noise else 0.0)
    return t
