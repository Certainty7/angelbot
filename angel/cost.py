"""USD budget + circuit breaker helpers (merged from the Malak build)."""
import os
from datetime import datetime, timedelta, timezone

LOCAL_TZ = timezone(timedelta(hours=4))


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


DAILY_LIMIT_USD = _f("MALAK_DAILY_COST_LIMIT_USD", 0.0)  # 0 = no daily ceiling
STOP_RATIO = _f("MALAK_COST_STOP_RATIO", 0.95)
PRICE_INPUT_PER_MTOK = _f("MALAK_PRICE_INPUT_PER_MTOK", 0.10)
PRICE_OUTPUT_PER_MTOK = _f("MALAK_PRICE_OUTPUT_PER_MTOK", 0.40)


class BudgetExhausted(RuntimeError):
    """Raised instead of calling the model once 95% of the daily budget is spent."""


def local_day() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")


def cost_of(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000) * PRICE_INPUT_PER_MTOK + (output_tokens / 1_000_000) * PRICE_OUTPUT_PER_MTOK


def stop_at() -> float:
    """Spend ceiling. A non-positive limit disables the guard entirely (free key, 2026-11-12)."""
    if DAILY_LIMIT_USD <= 0:
        return float("inf")
    return DAILY_LIMIT_USD * STOP_RATIO
