"""Self-evolution inside hard numeric ranges (mood + behaviour settings)."""
from .cost import local_day
import random
from typing import Dict

MOOD_RANGE = (0.15, 0.85)
MOOD_BASELINE = 0.55
SETTING_RANGES = {
    "verbosity": (0.2, 0.6),
    "emoji_rate": (0.0, 0.18),
    "typo_rate": (0.0, 0.04),
    "curiosity": (0.3, 0.8),
}


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def step(mood: float, settings: Dict[str, float], rng: random.Random = None) -> Dict[str, object]:
    rng = rng or random
    new_mood = clamp(mood + (MOOD_BASELINE - mood) * 0.25 + rng.uniform(-0.06, 0.06), *MOOD_RANGE)
    new_settings = dict(settings)
    for key, (lo, hi) in SETTING_RANGES.items():
        current = float(new_settings.get(key, (lo + hi) / 2))
        new_settings[key] = round(clamp(current + rng.uniform(-0.02, 0.02), lo, hi), 4)
    return {"mood": round(new_mood, 4), "settings": new_settings}


async def load(db) -> Dict[str, object]:
    mood = clamp(float(await db.get_state_value("mood", MOOD_BASELINE)), *MOOD_RANGE)
    settings = await db.get_state_value("settings", {k: (lo + hi) / 2 for k, (lo, hi) in SETTING_RANGES.items()})
    for key, (lo, hi) in SETTING_RANGES.items():
        settings[key] = clamp(float(settings.get(key, (lo + hi) / 2)), lo, hi)
    return {"mood": mood, "settings": settings}


async def save(db, state: Dict[str, object]) -> None:
    await db.set_state_value("mood", state["mood"])
    await db.set_state_value("settings", state["settings"])


async def daily_step(db, rng: random.Random = None) -> Dict[str, object]:
    state = await load(db)
    new_state = step(state["mood"], state["settings"], rng)
    await save(db, new_state)
    return new_state


async def maybe_daily_step(db):
    """Run at most once per local day; returns the new state or None."""
    day = local_day()
    if (await db.get_state_value("evolution_day", "")) == day:
        return None
    await db.set_state_value("evolution_day", day)
    return await daily_step(db)
