"""USD budget + circuit breaker helpers."""
import math
import os
from datetime import datetime

from .config import ANGEL_TZ


def _f(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None and name.startswith("ANGEL_"):
        raw = os.getenv("MALAK_" + name[len("ANGEL_"):])
    if raw is None:
        raw = default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(value) or value < 0:
        return float(default)
    return value


LOCAL_TZ = ANGEL_TZ


DAILY_LIMIT_USD = _f("ANGEL_DAILY_COST_LIMIT_USD", 0.0)  # 0 = no daily ceiling
STOP_RATIO = _f("ANGEL_COST_STOP_RATIO", 0.95)
PRICE_INPUT_PER_MTOK = _f("ANGEL_PRICE_INPUT_PER_MTOK", 0.10)
PRICE_OUTPUT_PER_MTOK = _f("ANGEL_PRICE_OUTPUT_PER_MTOK", 0.40)


class BudgetExhausted(RuntimeError):
    """Raised instead of calling the model once 95% of the daily budget is spent."""


def local_day() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")


def cost_of(input_tokens: int, output_tokens: int) -> float:
    safe_input = max(0, int(input_tokens or 0))
    safe_output = max(0, int(output_tokens or 0))
    return (safe_input / 1_000_000) * PRICE_INPUT_PER_MTOK + (safe_output / 1_000_000) * PRICE_OUTPUT_PER_MTOK


def stop_at() -> float:
    """Spend ceiling. A non-positive limit disables the guard entirely (free key, 2026-11-12)."""
    if DAILY_LIMIT_USD <= 0:
        return float("inf")
    return DAILY_LIMIT_USD * STOP_RATIO
