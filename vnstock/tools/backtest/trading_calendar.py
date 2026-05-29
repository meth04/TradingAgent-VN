"""Vietnam trading-calendar helpers for backtests.

This module centralizes weekend + explicit holiday closures used by both
legacy vnstock and cognitive_trading backtest loops.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

TET_2026_CLOSURES = {
    "2026-02-14",
    "2026-02-15",
    "2026-02-16",
    "2026-02-17",
    "2026-02-18",
    "2026-02-19",
    "2026-02-20",
    "2026-02-21",
    "2026-02-22",
}

MARKET_HOLIDAYS = frozenset(TET_2026_CLOSURES)


def is_trading_day(value: str | date) -> bool:
    current = value if isinstance(value, date) else date.fromisoformat(value)
    if current.weekday() >= 5:
        return False
    return current.isoformat() not in MARKET_HOLIDAYS


def iter_trading_days(start: str, end: str) -> Iterable[str]:
    current = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    while current <= end_date:
        if is_trading_day(current):
            yield current.isoformat()
        current += timedelta(days=1)


def previous_trading_day(value: str) -> str | None:
    current = date.fromisoformat(value) - timedelta(days=1)
    while current >= date.min:
        if is_trading_day(current):
            return current.isoformat()
        current -= timedelta(days=1)
    return None


def next_trading_day(value: str) -> str:
    current = date.fromisoformat(value) + timedelta(days=1)
    while not is_trading_day(current):
        current += timedelta(days=1)
    return current.isoformat()


__all__ = [
    "MARKET_HOLIDAYS",
    "TET_2026_CLOSURES",
    "is_trading_day",
    "iter_trading_days",
    "previous_trading_day",
    "next_trading_day",
]
