"""Probabilistic interaction scoring: P(reply) and pattern selection."""
import os
import random
from dataclasses import dataclass


def _f(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None and name.startswith("ANGEL_"):
        raw = os.getenv("MALAK_" + name[len("ANGEL_"):])
    try:
        return float(raw if raw is not None else default)
    except (TypeError, ValueError):
        return float(default)


W_ACTIVITY = _f("ANGEL_W_ACTIVITY", 0.18)
W_MENTION = _f("ANGEL_W_MENTION", 0.30)
W_TOPIC = _f("ANGEL_W_TOPIC", 0.18)
W_MOOD = _f("ANGEL_W_MOOD", 0.14)
W_RECENCY = _f("ANGEL_W_RECENCY", 0.20)
REPLY_THRESHOLD = _f("ANGEL_REPLY_THRESHOLD", 0.55)
MENTION_FLOOR = 0.90


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class Signals:
    msgs_in_window: int = 0
    window_seconds: float = 2400.0
    mentioned: bool = False
    called_by_name: bool = False
    topic_hits: int = 0
    mood: float = 0.55
    seconds_since_last_reply: float = 3600.0
    has_media: bool = False


def reply_probability(s: Signals) -> float:
    activity = _clamp(s.msgs_in_window / 6.0)
    mention = 1.0 if s.mentioned else (0.8 if s.called_by_name else 0.0)
    topic = _clamp(s.topic_hits / 3.0)
    mood = _clamp(s.mood)
    recency = _clamp(s.seconds_since_last_reply / 1800.0)
    p = (W_ACTIVITY * activity + W_MENTION * mention + W_TOPIC * topic
         + W_MOOD * mood + W_RECENCY * recency)
    if s.mentioned:
        p = max(p, MENTION_FLOOR)
    return _clamp(p)


def should_reply(s: Signals, rng: random.Random = None) -> bool:
    rng = rng or random
    return rng.random() < reply_probability(s)


def pick_pattern(p: float, has_media: bool = False, has_history: bool = False, rng=None) -> str:
    rng = rng or random
    weights = [
        ("text", 0.55 * (0.6 + p)),
        ("reaction", 0.20 * (1.6 - p)),
        ("new_topic", 0.10),
        ("followup", 0.10 if has_history else 0.0),
        ("media", 0.15 if has_media else 0.0),
    ]
    total = sum(w for _, w in weights) or 1.0
    r = rng.random() * total
    acc = 0.0
    for name, w in weights:
        acc += w
        if r <= acc:
            return name
    return "text"


def typing_delay(text: str, rng=None) -> float:
    rng = rng or random
    return min(6.5, 0.055 * max(6, len(text or "")) * rng.uniform(0.7, 1.35))


def mention_likelihood(p: float) -> float:
    return _clamp(0.15 + 0.45 * p)
